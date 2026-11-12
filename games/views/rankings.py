"""The games rankings page and its SEO landing pages."""

import datetime
import re
from functools import cached_property

from django.db.models import Count, Max, Q
from django.db.models.functions import Lower
from django.http import Http404, QueryDict
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers
from django.views.generic import ListView, TemplateView

from core import sites
from core.cache_helpers import batched_cache_reads, cache_get, cache_set
from core.mixins import AnonymousResponseCacheMixin, RobustPaginationMixin
from core.services import ranking, seo
from core.services.query_params import parse_id_list
from games import config, models, utils
from games.cache import (
    GENERATION_HERO,
    GENERATION_TRACKING,
    HERO_STATS_CACHE_KEY,
    played_ids_cache_key,
    want_ids_cache_key,
)
from games.services import landing_pages, playtime
from games.services.data_version import compute_game_data_version
from games.services.query_filters import resolve_year_range
from games.services.game_filters import (
    PLATFORMS_CACHE_KEY,
    apply_game_filters,
    platforms_lookup,
    playtime_range,
)

from ._helpers import (
    _facet_cache_key,
    _genre_ids_with_games_or_descendant_games,
    _get_hero_stats,
    _get_played_game_ids,
    _get_want_to_play_game_ids,
    _get_year_bounds,
)
from .filter_titles import _build_filter_title, _build_tab_title

# The first year a rankings page is kept for. A fixed bound, not the corpus's
# own first year: that is a shared-cache read, which in production is a query,
# on a path whose whole point is to make none
FIRST_CACHEABLE_YEAR = 1950
YEAR = re.compile(r"[0-9]{4}")
# A row id as a link writes it. Not "041" or "+41": the page renders the
# parameter as given into its filter state, so each spelling is another page
ROW_ID = re.compile(r"[1-9][0-9]{0,8}")


def cacheable_facet(query_string):
    """Name the one facet a rankings query filters by, or None for any other.

    The pages worth keeping whole for anonymous visitors are the ones a row
    links to: a year, a platform, a genre, and the decade a detail page links
    to. Twice a day a scraper asked for about 4,000 of those links in five
    minutes, each from another address and each with its own ``highlight``,
    so each was a render (Sentry uptime, 2026-11-03 to 11-09).

    ``highlight`` is left out: the browser reads it from the address, and
    the page holds nothing of it. So is a tracking tag (`page_query`). What
    is left must be exactly one facet, each parameter given once, in any
    order - the scraper replays a list it re-serialises
    (``?highlight=1458&start=2009&end=2009``) - and spelt as a link spells
    it, so a page has one key. Anything else is rendered.
    """
    params = dict(page_query(query_string).lists())
    if not params:
        return "default"
    if any(len(values) != 1 for values in params.values()):
        return None
    params = {name: values[0] for name, values in params.items()}
    if set(params) == {"start", "end"}:
        start, end = params["start"], params["end"]
        if not (YEAR.fullmatch(start) and YEAR.fullmatch(end)):
            return None
        start, end = int(start), int(end)
        if not FIRST_CACHEABLE_YEAR <= start <= datetime.date.today().year + 1:
            return None
        if start == end:
            return f"year:{start}"
        if start % 10 == 0 and end == start + 9:
            return f"decade:{start}"
        return None
    for name, kind in (("platforms", "platform"), ("genres", "genre")):
        if set(params) == {name} and ROW_ID.fullmatch(params[name]):
            return f"{kind}:{params[name]}"
    return None


# What a link picks up on its way here and the page never reads: the tags
# of the campaign or the share it was followed from. A link shared on
# Facebook arrives as `/?fbclid=...`, a different one for every reader.
TRACKING_PARAMS = frozenset(
    {
        "dclid",
        "fbclid",
        "gbraid",
        "gclid",
        "igsh",
        "igshid",
        "mc_cid",
        "mc_eid",
        "msclkid",
        "ref",
        "wbraid",
    }
)


def page_query(query_string):
    """The query the page is rendered from: as sent, less what it never shows.

    That is ``highlight``, where a reader landed, which is the browser's to
    act on, and the tracking tags. Neither may reach a page that is kept for
    the next visitor, nor make a second copy of it.
    """
    query = QueryDict(query_string, mutable=True)
    for name in list(query):
        if name == "highlight" or name in TRACKING_PARAMS or name.startswith("utm_"):
            del query[name]
    return query


def _rendered_filters_query(filters, min_year, max_year):
    """The filters a list was rendered with, as a query the browser reads.

    Written into the list (`#game-rendered-filters`), which a filter request
    that fails leaves behind the controls: the filter component puts them
    back on it (`_rollBackIfStranded`). In the spelling `getFiltersFromURL`
    reads, with the defaults left out as the address leaves them out.
    """
    query = QueryDict(mutable=True)
    if filters["q"]:
        query["q"] = filters["q"]
    if filters["start"] != min_year or filters["end"] != max_year:
        query["start"] = filters["start"]
        query["end"] = filters["end"]
    for name in ("genres", "platforms", "series"):
        if filters[name]:
            query[name] = ",".join(filters[name])
    if filters["played"]:
        query["played"] = filters["played"]
    if filters["sort"] != "rank":
        query["sort"] = filters["sort"]
    if filters["sortDirection"] != "asc":
        query["dir"] = filters["sortDirection"]
    if filters["hltb_mode"] != "main":
        query["hltb_mode"] = filters["hltb_mode"]
    for name in ("hltb_min", "hltb_max"):
        if filters[name] is not None:
            query[name] = filters[name]
    return query.urlencode(safe=",")


def _list_url(request):
    """Where Load More asks for more of the list: the path and `page_query`.

    From the query as sent, not ``request.GET``: a landing page's own
    filters are injected there, and its list is asked for at its path.
    """
    query = page_query(request.META.get("QUERY_STRING", ""))
    return request.path + (f"?{query.urlencode(safe=',')}" if query else "")


def genres_cache_key(data_version):
    """The sidebar's genres, with counts, for this version of the game data.

    Keyed on the version because nothing drops them: a page rendered just
    before an import would otherwise show the old counts for a day. The
    24-hour timeout only clears the entries a moved version leaves.
    """
    return (
        f"search_wikipedia_genres_list_with_counts:{config.CACHE_VERSION}"
        f":{data_version}"
    )


def series_cache_key(data_version):
    """The sidebar's series, as ``genres_cache_key``: IGDB's series for the
    games an import added land in a fetch after it, which moves the version."""
    return f"search_series_list_with_counts:{config.CACHE_VERSION}:{data_version}"


def _order_games(qs, params):
    """The rankings page's sort, shared by the list and the CSV download.

    The CSV used to ignore it, so "Year, newest first" downloaded in rank
    order.
    """
    sort = params.get("sort", "rank")
    if sort not in {"rank", "year", "name", "playtime"}:
        sort = "rank"

    sort_direction = params.get("dir", "asc")
    if sort_direction not in {"asc", "desc"}:
        sort_direction = "asc"

    def sort_field(field_name):
        return f"-{field_name}" if sort_direction == "desc" else field_name

    if sort == "year":
        return qs.distinct().order_by(sort_field("year_of_release"), "rank")
    elif sort == "name":
        # Case-insensitively, as the payload's `ni` is computed, with rank
        # breaking ties in the same direction, so the client can flip its
        # whole order for descending and still agree with this one
        if sort_direction == "desc":
            return qs.distinct().order_by(Lower("name").desc(), "-rank")
        return qs.distinct().order_by(Lower("name"), "rank")
    elif sort == "playtime":
        field_prefix = playtime.hours_field(params.get("hltb_mode", "main"))
        return (
            qs.exclude(**{field_prefix: None})
            .filter(playtime.shown_q())
            .distinct()
            .order_by(sort_field(field_prefix), "rank")
        )
    else:  # Default to rank
        return qs.distinct().order_by(sort_field("rank"))


@method_decorator(vary_on_headers("X-Requested-With", "HX-Request"), name="dispatch")
class HomePageView(AnonymousResponseCacheMixin, RobustPaginationMixin, ListView):
    model = models.Game
    template_name = "games/home.html"
    context_object_name = "games"
    paginate_by = 100
    paginate_orphans = 0

    @property
    def page_cache_timeout(self):
        """Five minutes for the unfiltered page, and an hour for a facet's,
        which is a landing page (`/games/1994/`) by another address."""
        if self._page_cache_facet == "default":
            return config.CACHE_TIMEOUT_HOME_PAGE
        return config.CACHE_TIMEOUT_LANDING_PAGE

    @cached_property
    def _page_cache_facet(self):
        return cacheable_facet(self.request.META.get("QUERY_STRING", ""))

    def get_page_cache_key(self):
        """The unfiltered page, and each page a row links to (`cacheable_facet`)."""
        if self._page_cache_facet is None:
            return None
        return f"home_page:{config.CACHE_VERSION}:{self._page_cache_facet}"

    def may_store_page(self):
        """Not a platform or genre page for an id the site does not have.

        A year is bounded where its key is made; an id can only be looked
        up, which costs a query, so it waits for a miss. Unchecked, every
        number anyone cared to ask for would be a page to keep.
        """
        kind, _, value = (self._page_cache_facet or "").partition(":")
        model = {"platform": models.Platform, "genre": models.WikipediaGenre}.get(kind)
        return model is None or model.objects.filter(pk=value).exists()

    def get_page_cache_version(self):
        """A stored page is served only while the game data is the same.

        The client joins the page's rows to `/api/games/all/`'s by position,
        so a page from before an import beside the new payload repeated and
        dropped games on its first Load More or jump.
        """
        return self.game_data_version

    @cached_property
    def game_data_version(self):
        """Read once a request: what the cache checks, stores and the page
        names are the same value, and the sidebar's lists are keyed on it."""
        return compute_game_data_version()

    @cached_property
    def _genre_descendants(self):
        """The genre hierarchy, fetched once however often this request filters.

        A filtered page applies the genre filter to the list and again to each
        facet; uncached, each would otherwise fetch the hierarchy itself.
        """
        return utils.genre_descendant_map()

    def get(self, request, *args, **kwargs):
        # Every cached value the page reads, in one shared-cache round trip
        with batched_cache_reads(self._prefetch_cache_keys()):
            return super().get(request, *args, **kwargs)

    def _played_cache_user_id(self):
        """The user the facet caches are per, when the played filter applies."""
        if self.request.GET.get("played") and self.request.user.is_authenticated:
            return self.request.user.id
        return None

    @cached_property
    def _facet_cache_keys(self):
        """The keys of the facet counts and the chart for this request's filters."""
        params = self.request.GET
        user_id = self._played_cache_user_id()
        return {
            "year": _facet_cache_key("home_year_counts", params, "year", user_id),
            "genres": _facet_cache_key("home_genre_counts", params, "genres", user_id),
            "platforms": _facet_cache_key(
                "home_platform_counts", params, "platforms", user_id
            ),
            "rank_dist": _facet_cache_key(
                "home_rank_dist",
                params,
                user_id=user_id,
                # sort=playtime leaves out games with no time, so the chart too
                extra={"sort": params.get("sort", "rank")},
            ),
        }

    def _prefetch_cache_keys(self):
        """Every shared-cache key the page reads before it renders."""
        keys = [
            genres_cache_key(self.game_data_version),
            series_cache_key(self.game_data_version),
            PLATFORMS_CACHE_KEY,
            config.CACHE_KEY_YEAR_STATS,
            HERO_STATS_CACHE_KEY,
            GENERATION_HERO,
            *landing_pages.cache_keys(),
            *self._facet_cache_keys.values(),
        ]
        if self.request.user.is_authenticated:
            keys += [
                played_ids_cache_key(self.request.user.id),
                want_ids_cache_key(self.request.user.id),
                GENERATION_TRACKING,
            ]
        return keys

    def get_paginate_by(self, queryset):
        """Always use standard page size - client-side handles deep jumps."""
        return self.paginate_by

    def get_template_names(self):
        # Support HTMX partial responses
        # Check both HX-Request header (for real HTMX) and
        # X-Requested-With header (for fetch)
        is_htmx = (
            self.request.headers.get("HX-Request")
            or self.request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or self.request.GET.get("partial") == "true"
        )

        # Append mode for Load More - returns just game rows
        if self.request.GET.get("append") == "true":
            return ["games/includes/_game_list_append.html"]

        if is_htmx:
            # Targeted update for just the results container
            if self.request.headers.get("HX-Target") == "game-results-container":
                return ["games/includes/_game_list_results.html"]
            # Full content partial for pagination and initial loads
            return ["games/includes/_game_list_content.html"]
        return super().get_template_names()

    def get_queryset(self):
        qs = (
            models.Game.objects.with_relations()
            .with_played_status(self.request.user)
            .with_list_count()
        )

        qs = apply_game_filters(
            qs,
            self.request.GET,
            user=self.request.user,
            descendants=self._genre_descendants,
        )
        return _order_games(qs, self.request.GET)

    def _facet_queryset(self, skip):
        """Every game under the page's filters but ``skip``'s, for a count.

        The counts beside each year cell, genre and platform answer "how
        many if I picked this", so each leaves its own dimension out - as
        the client engine's counts do, now including series and playtime.
        """
        return apply_game_filters(
            models.Game.objects.all(),
            self.request.GET,
            skip=(skip,),
            user=self.request.user,
            descendants=self._genre_descendants,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get Wikipedia genres with hierarchy for AdvancedFilters (cached for 24 hours)
        # Convert IDs to strings for proper Alpine.js binding
        # Includes game_count for heatmap visualization and hierarchy fields
        # Filter out genres with 0 games (but keep parents if children have games)
        genres_key = genres_cache_key(self.game_data_version)
        genres = cache_get(genres_key)
        if genres is None:
            all_genres = list(
                models.WikipediaGenre.objects.annotate(
                    game_count=Count("games_with_wikipedia_genre")
                )
                .order_by("level", "display_order", "name")
                .values(
                    "id",
                    "name",
                    "game_count",
                    "parent_id",
                    "level",
                    "display_order",
                    "slug",
                )
            )
            visible_genre_ids = _genre_ids_with_games_or_descendant_games(all_genres)
            genres = [
                {
                    **g,
                    "id": str(g["id"]),
                    "parent_id": str(g["parent_id"]) if g["parent_id"] else None,
                }
                for g in all_genres
                if g["id"] in visible_genre_ids
            ]
            cache_set(
                genres_key,
                genres,
                config.CACHE_TIMEOUT_DEFAULT,
            )

        platforms = platforms_lookup()

        # Get series list with game counts (only show series with 2+ games)
        MIN_SERIES_GAMES = 2
        series_key = series_cache_key(self.game_data_version)
        series_list = cache_get(series_key)
        if series_list is None:
            series_list = list(
                models.Series.objects.annotate(game_count=Count("games"))
                .filter(game_count__gte=MIN_SERIES_GAMES)
                .values("id", "name", "slug", "game_count")
                .order_by("-game_count", "name")
            )
            # Convert IDs to strings for Alpine.js
            series_list = [{**s, "id": str(s["id"])} for s in series_list]
            cache_set(
                series_key,
                series_list,
                config.CACHE_TIMEOUT_DEFAULT,
            )

        min_year, max_year = _get_year_bounds()

        # The one range the four year parameters stand for, which the list
        # is filtered to as well (`resolve_year_range`)
        start_param = self.request.GET.get("start")
        end_param = self.request.GET.get("end")
        year_param = self.request.GET.get("year")
        decade_param = self.request.GET.get("decade")

        start_val, end_val = resolve_year_range(
            decade=decade_param, year=year_param, start=start_param, end=end_param
        )
        if start_val is None:
            start_val = min_year
        if end_val is None:
            end_val = max_year

        # Build filters dict from query params
        q_param = self.request.GET.get("q", "")
        sort_param = self.request.GET.get("sort", "rank")
        if sort_param not in {"rank", "year", "name", "playtime"}:
            sort_param = "rank"

        dir_param = self.request.GET.get("dir", "asc")
        if dir_param not in {"asc", "desc"}:
            dir_param = "asc"
        genres_param = self.request.GET.get("genres")
        # Ids only, as the list is filtered: anything else was named raw in
        # the heading over a list it had not narrowed
        platform_ids = [
            str(pk) for pk in parse_id_list(self.request.GET.get("platforms"))
        ]
        series_param = self.request.GET.get("series")
        played_param = self.request.GET.get("played")

        # Parse HLTB parameters
        hltb_mode = self.request.GET.get("hltb_mode", "main")
        # The typed range, before a preset overrides it - the filter
        # component shows the preset separately - parsed by the same rule as
        # the queryset (game_filters.playtime_range)
        hltb_min, hltb_max = playtime_range(self.request.GET, ignore_preset=True)

        # Determine if any filter actually narrows results (affects rank display)
        # Year filter only counts if it's narrower than the full range
        has_year_filter = (
            (year_param or decade_param)
            or (start_val > min_year)
            or (end_val < max_year)
        )
        has_any_filter = (
            q_param
            or has_year_filter
            or genres_param
            or platform_ids
            or series_param
            or sort_param != "rank"
            or dir_param != "asc"
            or (played_param and self.request.user.is_authenticated)
            or hltb_min is not None
            or hltb_max is not None
        )

        filters = {
            "q": q_param,
            "start": start_val,
            "end": end_val,
            "genres": genres_param.split(",") if genres_param else [],
            "platforms": platform_ids,
            "series": series_param.split(",") if series_param else [],
            "played": (
                played_param
                if played_param and self.request.user.is_authenticated
                else ""
            ),
            "rank_display": "filtered" if has_any_filter else "alltime",
            "sort": sort_param,
            "sortDirection": dir_param,
            "hltb_mode": hltb_mode,
            "hltb_min": hltb_min,
            "hltb_max": hltb_max,
            # Keep legacy params for context
            "year": year_param,
            "decade": decade_param,
        }
        played_cache_user_id = self._played_cache_user_id()
        facet_cache_timeout = (
            config.CACHE_TIMEOUT_1_MINUTE
            if q_param or played_cache_user_id is not None
            else config.CACHE_TIMEOUT_5_MINUTES
        )

        context["genres"] = genres
        context["platforms"] = platforms
        context["series_list"] = series_list
        context["filters"] = filters
        # Slug map so client-side filtering can push the clean /games/...
        # SEO URLs when the filter state matches one (single root genre,
        # single qualifying platform, or a pure year/decade range)
        context["seo_url_data"] = {
            "genres": {
                str(g["id"]): g["slug"] for g in landing_pages.get_landing_genres()
            },
            "platforms": {
                str(p["id"]): p["slug"] for p in landing_pages.get_landing_platforms()
            },
            "years": landing_pages.get_landing_years(),
            "decades": landing_pages.get_landing_decades(),
        }
        context["min_year"] = min_year
        context["max_year"] = max_year
        # No `highlight` here: the page is kept whole for anonymous visitors
        # whatever it says (`cacheable_facet`), so the browser reads it from
        # the address, and nothing of one visitor's may be rendered. Nor in
        # the address Load More asks for more of the list at
        context["list_url"] = _list_url(self.request)
        context["rendered_filters_query"] = _rendered_filters_query(
            filters, min_year, max_year
        )
        context["is_filtered"] = True  # GameSearch is always filtered
        context["filter_title"] = _build_filter_title(
            filters, genres, platforms, min_year, max_year, series_list
        )
        context["tab_title"] = _build_tab_title(
            filters, genres, platforms, min_year, max_year, series_list
        )
        # Genre subtitle not needed for single-select mode
        context["genre_subtitle"] = ""

        # Get year counts for heatmap grid based on current filters (excluding year)
        # This allows users to see which years have games given their other filters
        year_counts_cache_key = self._facet_cache_keys["year"]
        year_counts = cache_get(year_counts_cache_key)
        if year_counts is None:
            base_qs = self._facet_queryset("year")

            # Calculate year counts from filtered base queryset
            # Use distinct=True to avoid counting games multiple times when M2M JOINs
            # cause duplicate rows (e.g., a game with WIN+MAC platforms matched twice)
            all_years = range(min_year, max_year + 1)
            year_count_map = {
                entry["year_of_release"]: entry["count"]
                for entry in base_qs.values("year_of_release")
                .annotate(count=Count("id", distinct=True))
                .order_by("year_of_release")
            }
            year_counts = [
                {"year": x, "count": year_count_map.get(x, 0)} for x in all_years
            ]
            cache_set(year_counts_cache_key, year_counts, facet_cache_timeout)

        context["year_counts"] = year_counts

        # FACETED COUNTS FOR GENRES
        # Apply all filters EXCEPT genres (standard faceting for single-select)
        genre_counts_cache_key = self._facet_cache_keys["genres"]
        genre_counts = cache_get(genre_counts_cache_key)
        if genre_counts is None:
            genre_facet_qs = self._facet_queryset("genres")

            # Standard faceted counting (single-select mode)
            genre_counts = dict(
                genre_facet_qs.values("wikipedia_genres__id")
                .exclude(wikipedia_genres__id__isnull=True)
                .annotate(count=Count("id", distinct=True))
                .values_list("wikipedia_genres__id", "count")
            )
            cache_set(genre_counts_cache_key, genre_counts, facet_cache_timeout)

        # FACETED COUNTS FOR PLATFORMS
        # Base: apply all filters EXCEPT platforms (q, year, genres)
        platform_counts_cache_key = self._facet_cache_keys["platforms"]
        platform_counts = cache_get(platform_counts_cache_key)
        if platform_counts is None:
            platform_facet_qs = self._facet_queryset("platforms")

            # Count games per platform
            platform_counts = dict(
                platform_facet_qs.values("platforms__id")
                .exclude(platforms__id__isnull=True)
                .annotate(count=Count("id", distinct=True))
                .values_list("platforms__id", "count")
            )
            cache_set(
                platform_counts_cache_key,
                platform_counts,
                facet_cache_timeout,
            )

        # Merge filtered counts into genres/platforms lists
        genres_with_filtered = [
            {**g, "filtered_count": genre_counts.get(int(g["id"]), 0)} for g in genres
        ]
        platforms_with_filtered = [
            {**p, "filtered_count": platform_counts.get(int(p["id"]), 0)}
            for p in platforms
        ]

        # Replace context with filtered versions
        context["genres"] = genres_with_filtered
        context["platforms"] = platforms_with_filtered

        # JSON for HTMX partial updates (keyed by string ID)
        context["genre_counts_json"] = {str(k): v for k, v in genre_counts.items()}
        context["platform_counts_json"] = {
            str(k): v for k, v in platform_counts.items()
        }

        # HLTB preset counts for filter (short/medium/long buckets), for both
        # completion modes so the Main/100% toggle can switch without a refetch
        hltb_fields = {
            mode: playtime.hours_field(mode) for mode in playtime.MODE_FIELDS
        }
        aggregates = {}
        for mode, field in hltb_fields.items():
            aggregates[f"{mode}_short"] = Count(
                "id", filter=Q(**{f"{field}__lt": 10}), distinct=True
            )
            aggregates[f"{mode}_medium"] = Count(
                "id",
                filter=Q(**{f"{field}__gte": 10, f"{field}__lt": 30}),
                distinct=True,
            )
            aggregates[f"{mode}_long"] = Count(
                "id", filter=Q(**{f"{field}__gte": 30}), distinct=True
            )
        totals = models.Game.objects.filter(playtime.shown_q()).aggregate(**aggregates)
        context["hltb_counts_json"] = {
            mode: {
                bucket: totals[f"{mode}_{bucket}"]
                for bucket in ("short", "medium", "long")
            }
            for mode in hltb_fields
        }

        # Rank distribution uses a fixed bin count across the current global max
        # rank so filtered views stay comparable to the full dataset.
        rank_dist_cache_key = self._facet_cache_keys["rank_dist"]
        cached_rank_data = cache_get(rank_dist_cache_key)
        if cached_rank_data is None:
            # Get global max rank for consistent bin structure
            max_rank = (
                models.Game.objects.filter(rank__isnull=False).aggregate(
                    max_rank=Max("rank")
                )["max_rank"]
                or 0
            )

            ranks = (
                self.get_queryset()
                .filter(rank__gte=1, rank__lte=max_rank)
                .order_by()
                .values_list("rank", flat=True)
            )
            rank_bins = ranking.rank_distribution(
                ranks, max_rank, config.RANK_DISTRIBUTION_BIN_COUNT
            )

            cached_rank_data = {"rank_bins": rank_bins, "max_rank": max_rank}
            cache_set(rank_dist_cache_key, cached_rank_data, facet_cache_timeout)
        else:
            rank_bins = cached_rank_data["rank_bins"]
            max_rank = cached_rank_data["max_rank"]

        context["rank_distribution"] = rank_bins
        context["max_rank"] = max_rank
        context["rank_distribution_bin_count"] = config.RANK_DISTRIBUTION_BIN_COUNT

        # Load More context
        page_obj = context.get("page_obj")
        if page_obj:
            context["has_more"] = page_obj.has_next()
            context["next_page"] = (
                page_obj.next_page_number() if page_obj.has_next() else None
            )
            context["total_count"] = page_obj.paginator.count
            context["loaded_count"] = page_obj.end_index()
            context["remaining_count"] = max(
                0, page_obj.paginator.count - page_obj.end_index()
            )
            context["max_loaded"] = page_obj.end_index() >= page_obj.paginator.count

        # Enable client-side filtering for fast subsequent interactions
        context["enable_client_filtering"] = True

        # Sorts for the shared results-header controls
        # (core/includes/_media_list_controls.html)
        context["sort_options"] = config.SORT_OPTIONS
        context["quick_mark_options"] = config.QUICK_MARK_OPTIONS
        context["game_status_options"] = config.GAME_STATUS_OPTIONS

        # Add played/want-to-play game IDs for client-side rendering (cached per-user)
        if self.request.user.is_authenticated:
            context["played_game_ids"] = _get_played_game_ids(self.request.user)
            context["want_to_play_game_ids"] = _get_want_to_play_game_ids(
                self.request.user
            )

        # Hero section context (for homepage at /)
        hero_stats = _get_hero_stats()
        context["list_count"] = hero_stats["list_count"]
        context["publication_count"] = hero_stats["publication_count"]
        context["game_count"] = hero_stats["game_count"]
        metadata = models.SiteMetadata.get_instance()
        context["last_update"] = metadata.last_full_update

        return context


def _landing_itemlist_json(name, games):
    """ItemList JSON-LD for a landing page's ranked games: the shared
    builder (``core.services.seo``), which was lifted from this function
    and which music's landing pages use."""
    return seo.itemlist_json(
        name,
        (
            (game.name, reverse("game-detail", kwargs={"slug": game.slug}))
            for game in games
        ),
        sites.GAMES,
    )


class SeoRankingPageView(HomePageView):
    """Serve the interactive rankings page at a crawlable /games/... URL.

    The slug/year/decade in the path is translated into the equivalent
    filter params and injected into request.GET before the normal home
    page machinery runs, so the full filter UI, pagination, and
    client-side filtering work unchanged while the URL stays clean and
    self-canonical for search engines. Explicit query params from user
    interactions take precedence over the path-implied filters.
    """

    page_cache_timeout = config.CACHE_TIMEOUT_LANDING_PAGE

    def get_page_cache_key(self):
        # A shared link's tracking tags, and `highlight`, are not the page's:
        # it is the same page with them (`page_query`), as the home page's
        # cache already read it, where it was rendered each time
        if page_query(self.request.META.get("QUERY_STRING", "")):
            return None
        return f"landing_page:{config.CACHE_VERSION}:{self.request.path}"

    def get_page_seo(self):
        """Return filter params and head copy for this URL, or raise 404."""
        raise NotImplementedError

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.seo = self.get_page_seo()
        params = request.GET.copy()
        for key, value in self.seo["params"].items():
            if key not in params:
                params[key] = value
        request.GET = params

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # The natural filter title doubles as the page title so the SEO
        # routes stay consistent with the interactively filtered page
        context["seo_title"] = context["filter_title"]
        context["seo_meta_description"] = self.seo["meta_description"]
        context["itemlist_json"] = _landing_itemlist_json(
            context["filter_title"], list(context["games"])[: landing_pages.TOP_N]
        )
        return context


class CategoryRankingView(SeoRankingPageView):
    """Genre or platform rankings at /games/<slug>/."""

    def get_page_seo(self):
        slug = self.kwargs["slug"]
        resolved = landing_pages.resolve_slug(slug)
        if resolved is None:
            raise Http404("No landing page for this slug")
        kind, entry = resolved

        if kind == "genre":
            params = {"genres": str(entry["id"])}
        else:
            params = {"platforms": str(entry["id"])}

        return {
            "params": params,
            "meta_description": (
                f"The most critically acclaimed {entry['name']} games of all "
                f"time, ranked by aggregating hundreds of critic lists. "
                f"Explore {entry['game_count']} acclaimed games."
            ),
        }


class YearRankingView(SeoRankingPageView):
    """Year rankings at /games/<year>/."""

    def get_page_seo(self):
        year = int(self.kwargs["year"])
        years = landing_pages.get_landing_years()
        if year not in years:
            raise Http404("No landing page for this year")

        return {
            "params": {"start": str(year), "end": str(year)},
            "meta_description": (
                f"The most critically acclaimed video games of {year}, ranked "
                f"by critic consensus across hundreds of published lists."
            ),
        }


class DecadeRankingView(SeoRankingPageView):
    """Decade rankings at /games/<decade>s/."""

    def get_page_seo(self):
        decade = int(self.kwargs["decade"])
        if decade not in landing_pages.get_landing_decades():
            raise Http404("No landing page for this decade")

        return {
            "params": {"start": str(decade), "end": str(decade + 9)},
            "meta_description": (
                f"The most critically acclaimed video games of the {decade}s, "
                f"ranked by critic consensus across hundreds of published "
                f"lists."
            ),
        }


class BrowseIndexView(AnonymousResponseCacheMixin, TemplateView):
    """Index of all /games/... SEO ranking pages."""

    template_name = "games/landing/browse.html"
    page_cache_timeout = config.CACHE_TIMEOUT_LANDING_PAGE

    def get_page_cache_key(self):
        # A shared link's tracking tags, and `highlight`, are not the page's:
        # it is the same page with them (`page_query`), as the home page's
        # cache already read it, where it was rendered each time
        if page_query(self.request.META.get("QUERY_STRING", "")):
            return None
        return f"landing_page:{config.CACHE_VERSION}:{self.request.path}"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["genre_pages"] = [
            {
                "label": f"{g['name']} Games",
                "url": reverse("games-by-category", kwargs={"slug": g["slug"]}),
            }
            for g in landing_pages.get_landing_genres()
        ]
        context["platform_pages"] = [
            {
                "label": f"{p['name']} Games",
                "url": reverse("games-by-category", kwargs={"slug": p["slug"]}),
            }
            for p in landing_pages.get_landing_platforms()
        ]
        context["decade_pages"] = [
            {
                "label": f"Games of the {decade}s",
                "url": reverse("games-by-decade", kwargs={"decade": decade}),
            }
            for decade in landing_pages.get_landing_decades()
        ]
        context["year_pages"] = [
            {
                "label": f"Games of {year}",
                "url": reverse("games-by-year", kwargs={"year": year}),
            }
            for year in landing_pages.get_landing_years()
        ]
        return context

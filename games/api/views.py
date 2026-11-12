import functools
import hashlib
from collections import defaultdict
from datetime import datetime

from django.contrib.flatpages.models import FlatPage
from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.http import Http404, HttpResponse
from django.utils.cache import patch_response_headers, patch_vary_headers
from django.utils.decorators import method_decorator
from django.conf import settings
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.views import APIView, Response


from core import sites
from core.services import search_ranking
from core.services.genre_tree import descendants_by_id
from core.services.query_params import parse_id_list, parse_limit
from core.services.request_body import SavedFilterJSONParser, read_saved_filter
from games.services.data_version import compute_game_data_version
from games.services.developer_service import get_developer_game_counts

from .. import config, models, utils
from . import serializers


def _json_response(body, max_age):
    """Stored JSON, as a response a browser may keep for ``max_age``."""
    response = HttpResponse(body, content_type="application/json")
    patch_response_headers(response, max_age)
    return response


def _asks_for_plain_json(request):
    """Whether DRF would answer ``request`` with JSON, whatever is asked.

    No `Accept`, or only `application/json` and `*/*` with no parameters.
    It need only be sufficient: anything else is left to DRF's own content
    negotiation and is not kept, the browsable API (`text/html`) and
    `application/json; indent=4` among them.
    """
    accept = request.META.get("HTTP_ACCEPT")
    if not accept:
        return True
    return all(
        item.strip() in ("application/json", "*/*") for item in accept.split(",")
    )


def cache_page(timeout):
    """Keep a view's JSON in the shared cache, under nothing a caller writes.

    The key is the Heroku release, the game data version, the host and the
    path. These responses sit in the shared cache, which outlives a deploy,
    so a new release must not be served the old code's output; see
    ``core.cache_config.release_cache_prefix``. And an import must not be
    served the rows from before it, ``/games/None/`` slugs and all, until
    the timeout lapses, so the game data version is read on every request:
    six small queries, beside the one a hit costs. A response rendered
    across an import's commit is stored under the version before it, which
    no request asks for again.

    This was Django's ``cache_page`` until 2026-11-10, whose key also
    hashes the `Vary` headers (`Accept`, here) and the whole address, port
    included: each is the caller's to write, and each distinct value was
    two more rows in a table of 5,000 that culls a quarter when full. So
    the keys are now as many as the paths, which the data bounds:

    - A query string is rendered, and throttled as any uncached API
      request is. A few thousand `?q=` values once culled the generation
      keys and the metadata fetch's lock.
    - An `Accept` that is not plainly JSON is rendered too, by DRF.
    - The host is spelt one way (``sites.host_key``), and only an answer
      rendered for that spelling is kept: a list's `next` link is
      absolute, so a kept answer for `Host: ...:8443` would hand every
      caller that port.
    - Only a 200 is kept, and only from a GET; HEAD reads the GET's entry.
    """

    def decorator(view):
        @functools.wraps(view)
        def cached_view(request, *args, **kwargs):
            if (
                request.method not in ("GET", "HEAD")
                or request.META.get("QUERY_STRING")
                or not _asks_for_plain_json(request)
            ):
                return view(request, *args, **kwargs)
            host = sites.host_key(request)
            # Hashed: a path is as long as its slug, and a key has 250
            # characters
            address = hashlib.md5(
                f"{host}{request.path}".encode(), usedforsecurity=False
            ).hexdigest()
            version = compute_game_data_version()
            key = f"games_api:{settings.RELEASE_CACHE_PREFIX}:{version}:{address}"
            body = cache.get(key)
            if body is None:
                response = view(request, *args, **kwargs)
                keep = (
                    request.method == "GET"
                    and response.status_code == 200
                    and request.get_host() == host
                    and getattr(response, "accepted_media_type", None)
                    == "application/json"
                )
                if not keep:
                    return response
                body = response.render().content
                cache.set(key, body, timeout)
            response = _json_response(body, timeout)
            patch_vary_headers(response, ["Accept"])
            return response

        return cached_view

    return decorator


@method_decorator(cache_page(60 * 15), name="dispatch")  # 15 min cache
class GameListView(ListAPIView):

    serializer_class = serializers.GameSummarySerializer
    # Build search fields based on database vendor
    # PostgreSQL supports full-text search, SQLite does not
    search_fields = ["name_normalized__icontains", "name__icontains"]
    if connection.vendor == "postgresql":
        search_fields = [
            "name_normalized__search",
            "name__search",
        ] + search_fields
    filters = [
        utils.Filter(
            param="q",
            fields=search_fields,
        ),
        utils.Filter(param="developer", fields=["developers__igdb_id"], coerce=int),
        utils.Filter(param="start", fields=["year_of_release__gte"], coerce=int),
        utils.Filter(param="end", fields=["year_of_release__lte"], coerce=int),
    ]

    ORDERING_FIELDS = {"rank", "name", "year_of_release", "year_rank", "decade_rank"}

    def get_queryset(self):
        qs = models.Game.objects.with_relations()

        for filter in self.filters:
            param_val = self.request.GET.get(filter.param)
            qs = filter.filter_queryset(qs, param_val)

        # Genre filtering (single-select, so match_all doesn't matter)
        genre_ids = parse_id_list(self.request.GET.get("genres"))
        if genre_ids:
            qs = utils.apply_genre_filter(qs, genre_ids, match_all=False)

        # Platform filtering
        platform_ids = parse_id_list(self.request.GET.get("platforms"))
        if platform_ids:
            qs = utils.apply_platform_filter(qs, platform_ids)

        # Only the summary's own sortable columns: order_by() follows
        # relations, so passing the parameter through let a caller sort by
        # fields the serializer never exposes, and an unknown one was a 500.
        order_by = self.request.GET.get("order_by", "")
        if order_by.removeprefix("-") in self.ORDERING_FIELDS:
            qs = qs.order_by(order_by)

        return qs.distinct()


@method_decorator(cache_page(60 * 30), name="dispatch")  # 30 min cache
class GameDetailView(RetrieveAPIView):
    lookup_field = "slug"
    serializer_class = serializers.GameDetailSerializer
    # The serializer reads the list appearances itself, joined and
    # ordered, so prefetching them here was a query nothing read.
    queryset = models.Game.objects.select_related(
        "primary_igdb_game_data",
        "primary_wikipedia_game_data",
    )


class CountsThroughStudiosMixin:
    """A developer's ``games_count`` is its studios' games too.

    As the developers page and the search box count them. The list counted
    direct games only and showed developers with any, so a parent whose
    games all belong to its studios (Microsoft, CD Projekt) was missing.
    """

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["developer_game_counts"] = get_developer_game_counts()
        return context


@method_decorator(cache_page(60 * 30), name="dispatch")  # 30 min cache
class DeveloperDetailAPIView(CountsThroughStudiosMixin, RetrieveAPIView):
    """API endpoint for developer details."""

    lookup_field = "slug"
    serializer_class = serializers.DeveloperSerializer
    queryset = models.Developer.objects.select_related("parent").prefetch_related(
        "subsidiaries"
    )


# Legacy alias for backward compatibility
CompanyDetailView = DeveloperDetailAPIView


class DeveloperListAPIView(CountsThroughStudiosMixin, ListAPIView):
    """API endpoint for listing developers."""

    serializer_class = serializers.DeveloperSerializer
    search_fields = ["name__icontains"]
    if connection.vendor == "postgresql":
        search_fields = ["name__search"] + search_fields
    filters = [
        utils.Filter(
            param="q",
            fields=search_fields,
        )
    ]

    def get_queryset(self):
        # Only developers with games, their studios' included
        qs = (
            models.Developer.objects.filter(id__in=list(get_developer_game_counts()))
            .select_related("parent")
            .prefetch_related("subsidiaries")
            .order_by(Lower("name"))
        )

        for filter in self.filters:
            param_val = self.request.GET.get(filter.param)
            qs = filter.filter_queryset(qs, param_val)

        return qs


# Legacy alias for backward compatibility
StudioListView = DeveloperListAPIView


class DeveloperDetailByIdView(CountsThroughStudiosMixin, RetrieveAPIView):
    """API endpoint for developer details by IGDB ID."""

    lookup_field = "igdb_id"
    serializer_class = serializers.DeveloperSerializer
    queryset = models.Developer.objects.select_related("parent").prefetch_related(
        "subsidiaries"
    )


# Legacy alias for backward compatibility
StudioDetailView = DeveloperDetailByIdView


class ListListView(ListAPIView):

    serializer_class = serializers.ListSerializer

    filters = [
        utils.Filter(param="publisher", fields=["publisher_id"], coerce=int),
        utils.Filter(param="year", fields=["year"], coerce=int),
        utils.Filter(param="type", fields=["type"], coerce=str),
    ]

    def get_queryset(self):
        qs = models.List.objects.select_related(
            "publisher",
        ).order_by(
            "publisher",
            "year",
            "name",
        )

        for filter in self.filters:
            param_val = self.request.GET.get(filter.param)
            qs = filter.filter_queryset(qs, param_val)

        return qs


class PublicationListView(ListAPIView):
    serializer_class = serializers.PublicationSerializer
    queryset = models.Publication.objects.all()


class PublicationDetailView(RetrieveAPIView):
    serializer_class = serializers.PublicationSerializer
    queryset = models.Publication.objects.all()


@method_decorator(cache_page(config.CACHE_TIMEOUT_1_HOUR), name="dispatch")
class MetaView(APIView):

    def get(self, *args, **kwargs):
        data = {}

        # Lists
        list_year_counts = (
            models.List.objects.order_by(
                "year",
            )
            .values(
                "year",
            )
            .annotate(count=Count("id"))
            .values(
                "year",
                "count",
            )
        )

        data["lists"] = {
            "years": list_year_counts,
            "total_count": models.List.objects.count(),
        }

        # Games. A game the release gives no year is in neither list: it
        # was a decade of ``None``, and ``None + 9`` a 500.
        year_count_map = {
            entry["year_of_release"]: entry["count"]
            for entry in models.Game.objects.exclude(year_of_release__isnull=True)
            .values("year_of_release")
            .annotate(count=Count("id"))
            .order_by("year_of_release")
        }
        min_year = min(year_count_map, default=1970)
        # Through this year: ``range`` stops one short of its end
        all_years = range(min_year, datetime.today().year + 1)

        all_years_with_counts = [
            {"year": x, "count": year_count_map.get(x, 0)} for x in all_years
        ]

        # Summed here rather than in SQL, as music's is: ``Floor`` answers
        # a float on SQLite, and the label read "1990.0-99".
        decade_counts = {}
        for year, count in year_count_map.items():
            decade = (year // 10) * 10
            decade_counts[decade] = decade_counts.get(decade, 0) + count

        decades_with_counts = [
            {"decade": f"{decade}-{str(decade + 9)[-2:]}", "count": count}
            for decade, count in sorted(decade_counts.items())
        ]

        # Get last_full_update from SiteMetadata
        metadata = models.SiteMetadata.get_instance()
        last_update = metadata.last_full_update

        data["games"] = {
            "years": all_years_with_counts,
            "decades": decades_with_counts,
            "last_update": last_update,
        }

        # Publications
        data["publications"] = {
            "total_count": models.Publication.objects.count(),
        }

        return Response(data)


class SnippetDetailView(APIView):
    def get(self, *args, **kwargs):
        snippet = get_object_or_404(models.Snippet, **kwargs)
        return Response({"snippet": snippet.text})


class PageDetailView(RetrieveAPIView):

    serializer_class = serializers.PageSerializer

    def get_object(self):
        url = self.kwargs.get("url")
        # `first()`, as the page's own view: the URL is not unique
        # Never one for signed-in readers only: this API authenticates nobody,
        # and its answers are kept for everyone
        page = (
            FlatPage.objects.filter(url=f"/{url}/", registration_required=False)
            .order_by("pk")
            .first()
        )
        if page is None:
            raise Http404("No such page")
        return page


@method_decorator(cache_page(config.CACHE_TIMEOUT_24_HOURS), name="dispatch")
class WikipediaGenreListView(ListAPIView):
    """
    List all Wikipedia genres (flat list with hierarchy metadata).

    Returns genres ordered by level and display_order for consistent rendering.
    Includes parent_id for client-side tree building if needed.
    """

    serializer_class = serializers.WikipediaGenreSerializer
    queryset = models.WikipediaGenre.objects.all().order_by(
        "level", "display_order", "name"
    )


@method_decorator(cache_page(config.CACHE_TIMEOUT_24_HOURS), name="dispatch")
class WikipediaGenreTreeView(ListAPIView):
    """
    List Wikipedia genres as hierarchical tree structure.

    Returns only root categories (level=0), with children nested recursively.
    Includes game counts for each genre.

    Response format:
    [
        {
            "id": 1,
            "name": "Action",
            "slug": "action",
            "level": 0,
            "game_count": 1234,
            "children": [
                {"id": 2, "name": "Shooter", "level": 1,
                 "game_count": 456, "children": []},
                ...
            ]
        },
        ...
    ]
    """

    serializer_class = serializers.WikipediaGenreTreeSerializer

    def _counted(self):
        return models.WikipediaGenre.objects.annotate(
            game_count_annotated=Count("games_with_wikipedia_genre")
        ).order_by("display_order", "name")

    def get_queryset(self):
        """Return only root categories (parent=None) for tree building."""
        return self._counted().filter(parent=None)

    def get_serializer_context(self):
        """Every genre, counted, by parent: one query for the whole tree."""
        context = super().get_serializer_context()
        children = defaultdict(list)
        for genre in self._counted().exclude(parent=None):
            children[genre.parent_id].append(genre)
        context["genre_children"] = children
        return context


@method_decorator(cache_page(config.CACHE_TIMEOUT_24_HOURS), name="dispatch")
class PlatformListView(ListAPIView):
    serializer_class = serializers.PlatformSerializer
    queryset = models.Platform.objects.all()


class GameSearchAPIView(APIView):
    """
    API endpoint for navbar search - returns JSON list of games matching query.
    Used by GameSearchComponent in navbar.
    """

    def get(self, request):
        from django.http import JsonResponse

        q = request.GET.get("q", "").strip()
        q_normalized = models.normalize_name(q)
        limit = parse_limit(request.GET.get("limit"), default=5)

        if len(q) < 2:
            return JsonResponse({"results": [], "count": 0})

        # Search games by name (only fetch required fields for performance)
        # Search both original name and normalized (accent-stripped) version.
        # Use normalized query so accented and ASCII input both match.
        games = (
            models.Game.objects.filter(
                Q(name__icontains=q) | Q(name_normalized__icontains=q_normalized)
            )
            .select_related("primary_igdb_game_data")
            .only(
                "id",
                "name",
                "slug",
                "year_of_release",
                "rank",
                "primary_igdb_game_data__artwork_id",
            )
            .order_by("rank")[:limit]
        )

        results = []
        for game in games:
            results.append(
                {
                    "id": game.id,
                    "name": game.name,
                    "slug": game.slug,
                    "year_of_release": game.year_of_release,
                    "rank": game.rank,
                    "thumbnail": game.thumbnail,
                }
            )

        return JsonResponse({"results": results, "count": len(results)})


#: The unified search's groups, in the order a tie between them falls: a
#: name that is a game and a series equally ("Portal") is after the game.
SEARCH_GROUPS = ("games", "series", "developers")


def _best_first(q, matches, limit, counts=None):
    """A creator-like group's rows, best match first, then most games.

    ``matches`` is annotated with ``games_count``. Exact names come first in
    the database (``search_ranking.exact_first``), so the bounded read of
    ``search_ranking.CANDIDATES`` rows cannot leave one out. Each row is
    ``(score, -games, name, id, games)``.

    ``counts``, by id, replaces the annotation where a row's games are not
    only its own (a developer's subsidiaries'); a row it counts at none is
    left out.
    """
    candidates = search_ranking.exact_first(
        matches,
        "-games_count",
        "name",
        name=q,
        name_normalized=models.normalize_name(q),
    ).values_list("id", "name", "name_normalized", "games_count")
    rows = (
        (
            row_id,
            name,
            normalized,
            counts.get(row_id, 0) if counts is not None else count,
        )
        for row_id, name, normalized, count in candidates[: search_ranking.CANDIDATES]
    )
    return sorted(
        (
            search_ranking.quality_or(q, (name, normalized), search_ranking.SUBSTRING),
            -count,
            name.lower(),
            row_id,
            count,
        )
        for row_id, name, normalized, count in rows
        if count > 0
    )[:limit]


class UnifiedSearchView(APIView):
    """
    Unified search endpoint for navbar - returns both developers and games.
    Used by unified search component in navbar for grouped dropdown results.

    ``order`` names the groups in the order the dropdown shows them: the one
    holding the better match (``core.services.search_ranking``) leads, so
    "Nintendo" leads with the developer and "Halo" with the series. Games
    keep rank order but for an exact title; developers and series are best
    match first, then most games.
    """

    def get(self, request):
        from django.http import JsonResponse

        q = request.GET.get("q", "").strip()
        game_limit = parse_limit(request.GET.get("game_limit"), default=5)
        developer_limit = parse_limit(request.GET.get("developer_limit"), default=3)
        series_limit = parse_limit(request.GET.get("series_limit"), default=3)
        q_normalized = models.normalize_name(q)

        if len(q) < 2:
            return JsonResponse(
                {"developers": [], "games": [], "series": [], "order": SEARCH_GROUPS}
            )

        # Each group is scored in Python on a bounded read of its matches
        # (search_ranking.CANDIDATES), and only the rows shown are fetched
        # whole.
        # Counted through subsidiaries, as the developers list counts: by
        # direct games, a parent whose games are all its studios' was not
        # found, and one that was showed fewer than its page
        # Only developers with games somewhere in their tree take a place
        # in the bounded read
        counts = get_developer_game_counts()
        developer_rows = _best_first(
            q,
            models.Developer.objects.filter(
                Q(name__icontains=q) | Q(name_normalized__contains=q_normalized),
                id__in=list(counts),
            ).annotate(games_count=Count("developed_games")),
            developer_limit,
            counts=counts,
        )
        # root_developer walks the parent chain; join it instead
        developers_by_id = models.Developer.objects.select_related(
            *models.DEVELOPER_PARENT_CHAIN
        ).in_bulk([row[3] for row in developer_rows])

        developer_results = []
        # A row an import replaced between the two reads is gone; drop it, so
        # it neither raises nor decides which group leads.
        developer_rows = [row for row in developer_rows if row[3] in developers_by_id]
        for *_, dev_id, games_count in developer_rows:
            dev = developers_by_id[dev_id]
            # The root developer's slug and id, for URL routing: the
            # developer itself when it has no parent, so never None
            root = dev.root_developer
            developer_results.append(
                {
                    "id": dev.id,
                    "name": dev.name,
                    "root_slug": root.slug,
                    "root_id": root.id,
                    "games_count": games_count,
                }
            )

        # Search games by original and normalized names for accent-insensitive matching.
        # Use normalized query so accented and ASCII input both match.
        # Ranked, with an exact title first, in one bounded query.
        games = list(
            search_ranking.exact_first(
                models.Game.objects.filter(
                    Q(name__icontains=q) | Q(name_normalized__icontains=q_normalized)
                ),
                "rank",
                name=q,
                name_normalized=q_normalized,
            )
            .select_related("primary_igdb_game_data")
            .only(
                "id",
                "name",
                "name_normalized",
                "slug",
                "year_of_release",
                "rank",
                "primary_igdb_game_data__artwork_id",
            )[:game_limit]
        )

        game_results = []
        for game in games:
            game_results.append(
                {
                    "id": game.id,
                    "name": game.name,
                    "slug": game.slug,
                    "year_of_release": game.year_of_release,
                    "rank": game.rank,
                    "thumbnail": game.thumbnail,
                }
            )

        # Series with 2+ games, as the filter lists
        series_rows = _best_first(
            q,
            models.Series.objects.filter(
                Q(name__icontains=q) | Q(name_normalized__contains=q_normalized)
            )
            .annotate(games_count=Count("games"))
            .filter(games_count__gte=2),
            series_limit,
        )
        series_by_id = models.Series.objects.only("id", "name", "slug").in_bulk(
            [row[3] for row in series_rows]
        )
        series_rows = [row for row in series_rows if row[3] in series_by_id]
        series_results = [
            {
                "id": series_id,
                "name": series_by_id[series_id].name,
                "slug": series_by_id[series_id].slug,
                "games_count": games_count,
            }
            for *_, series_id, games_count in series_rows
        ]

        order = search_ranking.group_order(
            {
                "games": min(
                    (
                        search_ranking.quality_or(
                            q,
                            (game.name, game.name_normalized),
                            search_ranking.SUBSTRING,
                        )
                        for game in games
                    ),
                    default=None,
                ),
                "series": series_rows[0][0] if series_rows else None,
                "developers": developer_rows[0][0] if developer_rows else None,
            },
            SEARCH_GROUPS,
        )

        return JsonResponse(
            {
                "developers": developer_results,
                "games": game_results,
                "series": series_results,
                "order": order,
            }
        )


class GameAllDataView(APIView):
    """
    Complete game data endpoint for client-side filtering.

    Returns all games with minimal payload for efficient client-side filtering:
    - Compressed field names to minimize payload size
    - Reference data (developers, platforms, genres) keyed by ID
    - Genre hierarchy with descendant IDs for hierarchical filtering

    Response format:
    {
        "version": "abc123def456",
        "data": {
            "games": [{id, n, s, r, y, a, dv, p, g, sr, lc}, ...],
            "developers": {id: {n, pa, s}, ...},
            "platforms": {id: {n, c, ys, ye}, ...},
            "genres": [{id, n, s, p, l, d}, ...],
            "series": {id: {n, s}, ...}
        }
    }
    """

    def get(self, request):
        """The payload, cached in the shared cache under its data version.

        Not ``cache_page``, which kept the last import's payload for up to an
        hour beside pages naming the new data: the client joins the page's
        rows to these by position. Keyed on the version computed here rather
        than on the URL, so the client's ``?v=``, which keeps its browser's
        copy honest, cannot fill the cache with copies of the payload.
        """
        version = compute_game_data_version()
        key = f"games_all_data:{settings.RELEASE_CACHE_PREFIX}:{version}"
        body = cache.get(key)
        if body is not None:
            return _json_response(body, config.CACHE_TIMEOUT_1_HOUR)
        payload = self._payload(version)
        # An import that committed while the rows were read leaves them of
        # either version, so they are labelled with none, which no page
        # names and no client keeps, and are kept by no cache
        current = compute_game_data_version() == version
        if not current:
            payload["version"] = ""
        body = JSONRenderer().render(payload)
        response = HttpResponse(body, content_type="application/json")
        if current:
            cache.set(key, body, config.CACHE_TIMEOUT_1_HOUR)
            patch_response_headers(response, config.CACHE_TIMEOUT_1_HOUR)
        return response

    def _payload(self, version):
        # Fetch base game rows with scalar fields only (no model instantiation)
        game_rows = list(
            models.Game.objects.values(
                "id",
                "igdb_id",
                "name",
                "slug",
                "rank",
                "year_of_release",
                "primary_igdb_game_data__artwork_id",
                "primary_hltb_game_data__main_story_hours",
                "primary_hltb_game_data__completionist_hours",
                "primary_hltb_game_data__is_open_ended",
            )
            .annotate(list_count=Count("lists", distinct=True))
            .order_by("rank")
        )
        game_ids = [row["id"] for row in game_rows]

        # Group related IDs via through tables (ordered for deterministic output)
        game_developer_ids = defaultdict(list)
        used_developer_ids = set()
        if game_ids:
            for game_id, developer_id in (
                models.Game.developers.through.objects.filter(game_id__in=game_ids)
                .order_by("game_id", "developer__name", "developer_id")
                .values_list("game_id", "developer_id")
            ):
                game_developer_ids[game_id].append(developer_id)
                used_developer_ids.add(developer_id)

        game_platform_ids = defaultdict(list)
        used_platform_ids = set()
        if game_ids:
            for game_id, platform_id in (
                models.Game.platforms.through.objects.filter(game_id__in=game_ids)
                .order_by("game_id", "platform__name", "platform_id")
                .values_list("game_id", "platform_id")
            ):
                game_platform_ids[game_id].append(platform_id)
                used_platform_ids.add(platform_id)

        game_genre_ids = defaultdict(list)
        if game_ids:
            genre_links = models.Game.wikipedia_genres.through.objects.filter(
                game_id__in=game_ids
            ).order_by(
                "game_id",
                "wikipediagenre__level",
                "wikipediagenre__display_order",
                "wikipediagenre__name",
                "wikipediagenre_id",
            )
            for game_id, genre_id in genre_links.values_list(
                "game_id", "wikipediagenre_id"
            ):
                game_genre_ids[game_id].append(genre_id)

        game_series_ids = defaultdict(list)
        used_series_ids = set()
        if game_ids:
            for game_id, series_id in (
                models.Game.series.through.objects.filter(game_id__in=game_ids)
                .order_by("game_id", "series__name", "series_id")
                .values_list("game_id", "series_id")
            ):
                game_series_ids[game_id].append(series_id)
                used_series_ids.add(series_id)

        # Developers: fetch only game-linked developers + their immediate parents.
        developer_rows = {}
        pending_ids = set(used_developer_ids)
        while pending_ids:
            fetched_rows = list(
                models.Developer.objects.filter(id__in=pending_ids).values(
                    "id", "name", "parent_id", "slug"
                )
            )
            for row in fetched_rows:
                developer_rows[row["id"]] = row
            pending_ids = {
                row["parent_id"]
                for row in fetched_rows
                if row["parent_id"] and row["parent_id"] not in developer_rows
            }

        direct_parent_ids = {
            developer_rows[dev_id]["parent_id"]
            for dev_id in used_developer_ids
            if dev_id in developer_rows and developer_rows[dev_id]["parent_id"]
        }
        response_developer_ids = used_developer_ids | direct_parent_ids

        def _resolve_root_slug(dev_id):
            current_id = dev_id
            visited = set()
            while current_id and current_id not in visited:
                visited.add(current_id)
                current = developer_rows.get(current_id)
                if not current:
                    break
                if not current["parent_id"]:
                    return current["slug"]
                current_id = current["parent_id"]
            current = developer_rows.get(dev_id)
            return current["slug"] if current else None

        developers_dict = {}
        for dev_id in sorted(
            response_developer_ids,
            key=lambda pk: developer_rows.get(pk, {}).get("name", ""),
        ):
            row = developer_rows.get(dev_id)
            if not row:
                continue
            developers_dict[dev_id] = {
                "n": row["name"],
                "pa": row["parent_id"],
                "s": _resolve_root_slug(dev_id),
            }

        platform_rows = models.Platform.objects.filter(id__in=used_platform_ids).values(
            "id", "name", "code", "year_start", "year_end"
        )
        platforms_dict = {
            row["id"]: {
                "n": row["name"],
                "c": row["code"],
                "ys": row["year_start"],
                "ye": row["year_end"],
            }
            for row in platform_rows
        }

        series_rows = models.Series.objects.filter(id__in=used_series_ids).values(
            "id", "name", "slug"
        )
        series_dict = {
            row["id"]: {
                "n": row["name"],
                "s": row["slug"],
            }
            for row in series_rows
        }

        # Build all genres and descendants from one in-memory hierarchy map.
        genre_rows = list(
            models.WikipediaGenre.objects.values(
                "id", "name", "slug", "parent_id", "level", "display_order"
            ).order_by("level", "display_order", "name")
        )
        descendant_ids_by_genre_id = descendants_by_id(
            (row["id"], row["parent_id"]) for row in genre_rows
        )

        genres_data = [
            {
                "id": row["id"],
                "n": row["name"],
                "s": row["slug"],
                "p": row["parent_id"],
                "l": row["level"],
                "d": descendant_ids_by_genre_id[row["id"]],
            }
            for row in genre_rows
        ]

        # `ni` is each game's position in the server's own name order, which
        # the client sorts by rather than comparing names itself: no
        # JavaScript comparator reproduces a database collation (SQLite
        # files "DOOM 64" before "Doom"; Postgres does not), as
        # music's payload found first. Ties go to rank, as `_order_games`.
        name_order = {
            game_id: position
            for position, game_id in enumerate(
                models.Game.objects.order_by(Lower("name"), "rank").values_list(
                    "id", flat=True
                )
            )
        }

        # Assemble games preserving existing compressed keys/semantics.
        games_data = []
        for row in game_rows:
            playtime = row["primary_hltb_game_data__main_story_hours"]
            completionist = row["primary_hltb_game_data__completionist_hours"]
            if row["primary_hltb_game_data__is_open_ended"]:
                # No finish line, so no time to beat (games.services.playtime)
                playtime = completionist = None
            games_data.append(
                {
                    "id": row["id"],
                    "i": row["igdb_id"],  # IGDB ID for played game tracking
                    "n": row["name"],
                    "s": row["slug"],
                    "r": row["rank"],
                    "y": row["year_of_release"],
                    "a": row["primary_igdb_game_data__artwork_id"],
                    "dv": game_developer_ids.get(row["id"], []),
                    "p": game_platform_ids.get(row["id"], []),
                    "g": game_genre_ids.get(row["id"], []),
                    "sr": game_series_ids.get(row["id"], []),
                    "lc": row["list_count"],  # List count for display
                    # A game deleted between the two queries sorts last
                    # rather than failing the whole payload
                    "ni": name_order.get(row["id"], len(name_order)),
                    "pt": float(playtime) if playtime is not None else None,
                    "ptc": (
                        float(completionist) if completionist is not None else None
                    ),
                }
            )

        return {
            "version": version,
            "data": {
                "games": games_data,
                "developers": developers_dict,
                "platforms": platforms_dict,
                "genres": genres_data,
                "series": series_dict,
            },
        }


def _saved_filter_name_error(name, user, exclude_pk=None):
    """The name rules, or an error string if the name breaks one.

    Shared by create and rename, as music's are
    (``music.api.views._validate_saved_filter_name``): each method had its
    own copy of the three rules, and of the ceiling.
    """
    if not name:
        return "Filter name is required."
    if len(name) > config.SAVED_FILTER_NAME_MAX_LENGTH:
        return (
            f"Filter name must be {config.SAVED_FILTER_NAME_MAX_LENGTH} "
            "characters or less."
        )
    duplicates = models.SavedFilterSet.objects.filter(user=user, name=name)
    if exclude_pk is not None:
        duplicates = duplicates.exclude(pk=exclude_pk)
    if duplicates.exists():
        return "A filter with this name already exists."
    return None


class SavedFilterSetListCreateView(APIView):
    """
    List saved filter sets for current user (GET).
    Create new saved filter set (POST).

    Enforces ``config.MAX_SAVED_FILTERS`` saved filters per user.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [SavedFilterJSONParser]

    def get(self, request):
        """List all saved filter sets for current user."""
        filter_sets = models.SavedFilterSet.objects.filter(user=request.user).order_by(
            "-modified"
        )[: config.MAX_SAVED_FILTERS]

        data = [
            {
                "id": fs.id,
                "name": fs.name,
                "filters": fs.filters,
                "modified": fs.modified.isoformat(),
            }
            for fs in filter_sets
        ]
        return Response({"filter_sets": data, "count": len(data)})

    def post(self, request):
        """Create a new saved filter set."""
        current_count = models.SavedFilterSet.objects.filter(user=request.user).count()

        if current_count >= config.MAX_SAVED_FILTERS:
            return Response(
                {
                    "error": f"Maximum of {config.MAX_SAVED_FILTERS} saved filters "
                    "allowed. Delete one to save a new filter."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        name, filters = read_saved_filter(request.data)

        if not name:
            return Response(
                {"error": "Filter name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if filters is None:
            return Response(
                {"error": "Filters must be an object."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        error = _saved_filter_name_error(name, request.user)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        filter_set = models.SavedFilterSet.objects.create(
            user=request.user,
            name=name,
            filters=filters,
        )

        return Response(
            {
                "id": filter_set.id,
                "name": filter_set.name,
                "filters": filter_set.filters,
                "modified": filter_set.modified.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


class SavedFilterSetDetailView(APIView):
    """
    Update (PATCH) or delete (DELETE) a saved filter set.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [SavedFilterJSONParser]

    def get_object(self, pk, user):
        return get_object_or_404(models.SavedFilterSet, pk=pk, user=user)

    def patch(self, request, pk):
        """Rename saved filter set."""
        filter_set = self.get_object(pk, request.user)

        name, _ = read_saved_filter(request.data)
        error = _saved_filter_name_error(name, request.user, exclude_pk=pk)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        filter_set.name = name
        filter_set.save(update_fields=["name", "modified"])

        return Response(
            {
                "id": filter_set.id,
                "name": filter_set.name,
            }
        )

    def delete(self, request, pk):
        """Delete saved filter set."""
        filter_set = self.get_object(pk, request.user)
        filter_set.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

"""
Music views for the multi-media platform.

Every view is staff-only: the section is a beta and should look absent, not
forbidden, to everyone else. That gate is ``core.mixins.StaffOnlyMixin``,
which raises 404.

Unlike the books app, the album list is server-rendered with HTMX filtering.
There is no client-side filtering bundle yet, so every variable these
templates read is set here.
"""

from collections import defaultdict
from io import TextIOWrapper
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Prefetch, Q
from django.db.models.functions import Lower
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views import View
from django.views.generic import DetailView, ListView

from core import constants as core_constants
from core.cache_helpers import get_year_bounds
from core.mixins import HTMXPartialMixin, RobustPaginationMixin, StaffOnlyMixin
from music import config, models
from music.forms import MusicImportForm
from music.services import import_handler

# The checked-in release files, offered as the import default so the page is
# usable without hunting for them.
BUNDLED_RELEASE_DIR = (
    Path(settings.BASE_DIR) / "acclaimedgames" / "test_input_files" / "music"
)
BUNDLED_FILES = {
    "lists_file": "ListData.txt",
    "albums_file": "WebRankings.txt",
    "positions_file": "ListPositions.txt",
}

# Sorts are declared in their natural ascending form and the direction flips
# only the primary field, so a tiebreaker keeps pointing the same way: albums
# by year descending is newest-first then best-ranked, not newest-first then
# worst-ranked. Declaring a field pre-negated here would make `dir=desc`
# double-negate it.
ALBUM_SORTS = {
    "rank": ("rank",),
    "name": (Lower("name"),),
    "year": ("year_released", "rank"),
    "lists": ("list_count", "rank"),
}

ARTIST_SORTS = {
    "albums": ("albums_count", Lower("name")),
    "name": (Lower("name"),),
}


def _decade_options(min_year, max_year, current_start, current_end):
    """Decade quick-filters with album counts, for the sidebar.

    Mirrors the games year filter's role without the heatmap: the album data
    spans seven decades, so a row of chips covers it.
    """
    counts = {}
    for row in (
        models.Album.objects.exclude(year_released__isnull=True)
        .values("year_released")
        .annotate(count=Count("id"))
    ):
        decade = (row["year_released"] // 10) * 10
        counts[decade] = counts.get(decade, 0) + row["count"]

    options = []
    for decade in sorted(counts):
        end = decade + 9
        options.append(
            {
                "start": decade,
                "end": end,
                "label": f"{decade}s",
                "count": counts[decade],
                "selected": (
                    str(current_start) == str(decade) and str(current_end) == str(end)
                ),
            }
        )
    return options


def _filter_title(params):
    """A natural page title describing the current filter state.

    Deliberately avoids "best"/"top" phrasing, matching the wording used on
    the games ranking pages.
    """
    base = "Most Acclaimed Albums"
    start = params.get("start")
    end = params.get("end")
    query = params.get("q")

    if query:
        return f"Albums matching \u201c{query}\u201d"
    if start and end and start == end:
        return f"{base} of {start}"
    if start and end:
        if start.endswith("0") and end == str(int(start) + 9):
            return f"{base} of the {start}s"
        return f"{base}, {start}\u2013{end}"
    if start:
        return f"{base} from {start}"
    if end:
        return f"{base} up to {end}"
    return base


def _get_year_bounds():
    """Return the cached global min/max release years."""
    return get_year_bounds(
        model_class=models.Album,
        year_field="year_released",
        cache_key=config.CACHE_KEY_YEAR_STATS,
        cache_timeout=config.CACHE_TIMEOUT_24_HOURS,
        default_min=config.DEFAULT_MIN_YEAR,
    )


def _parse_id_list(raw):
    """Parse a comma-separated id parameter, ignoring anything non-numeric."""
    if not raw:
        return []
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


def _parse_int(raw):
    """Parse an integer parameter, returning None rather than raising."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _apply_sort(queryset, sorts, sort, direction, default):
    """Order a queryset by one of ``sorts``, flipping the primary field."""
    fields = sorts.get(sort) or sorts[default]
    if direction == "desc":
        fields = (_reverse_order(fields[0]),) + tuple(fields[1:])
    return queryset.order_by(*fields)


def _reverse_order(field):
    """Invert a single order_by term, string or expression."""
    if isinstance(field, str):
        return field[1:] if field.startswith("-") else f"-{field}"
    return field.desc()


def _cached_artist_options():
    """Return the artist filter options: every artist with at least one album."""
    cache_key = f"{config.CACHE_VERSION}:music_artist_options"
    options = cache.get(cache_key)
    if options is None:
        options = list(
            models.Artist.objects.annotate(albums_count=Count("albums"))
            .filter(albums_count__gt=0)
            .order_by(Lower("name"))
            .values("id", "name", "slug", "albums_count")
        )
        cache.set(cache_key, options, config.CACHE_TIMEOUT_24_HOURS)
    return options


def _cached_genre_options():
    """Return the genre filter options.

    Empty until the metadata pass populates ``MusicGenre``; the template
    hides the genre filter when there is nothing to show. ``albums_count`` is
    selected explicitly - annotating without naming it in ``values()`` leaves
    the template rendering a blank count.
    """
    cache_key = f"{config.CACHE_VERSION}:music_genre_options"
    options = cache.get(cache_key)
    if options is None:
        options = list(
            models.MusicGenre.objects.annotate(albums_count=Count("albums"))
            .filter(albums_count__gt=0)
            .order_by("level", "display_order", "name")
            .values("id", "name", "slug", "level", "parent_id", "path", "albums_count")
        )
        cache.set(cache_key, options, config.CACHE_TIMEOUT_24_HOURS)
    return options


def group_genre_options(options):
    """Group flat genre options under their root, for <optgroup>.

    The taxonomy is two levels - a root genre and the Discogs styles beneath
    it - which is more than a flat list of two hundred names can present
    usefully. Roots keep the order ``genre_normalizer.GENRE_HIERARCHY`` sets,
    which the query's ``display_order`` already reflects.

    A root is offered as a selectable option of its own as well as a group
    label, because filtering on "all of Rock" is the most useful thing a
    reader can ask for.
    """
    by_id = {option["id"]: option for option in options}
    groups = []
    group_index = {}

    for option in options:
        root = option
        # Walk up to the root; the tree is two deep, so this is one step.
        while root.get("parent_id") and root["parent_id"] in by_id:
            root = by_id[root["parent_id"]]

        if root["id"] not in group_index:
            group_index[root["id"]] = {"root": root, "options": []}
            groups.append(group_index[root["id"]])
        group_index[root["id"]]["options"].append(option)

    for group in groups:
        group["options"].sort(key=lambda item: (item["level"], item["name"]))

    return groups


def _cached_hero_stats():
    """Return the counts shown in the page heading."""
    cache_key = f"{config.CACHE_VERSION}:music_hero_stats"
    stats = cache.get(cache_key)
    if stats is None:
        stats = {
            "album_count": models.Album.objects.count(),
            "artist_count": models.Artist.objects.filter(parent__isnull=True)
            .annotate(albums_count=Count("albums"))
            .filter(albums_count__gt=0)
            .count(),
            "list_count": models.MusicList.objects.count(),
            "publication_count": models.MusicPublication.objects.count(),
        }
        cache.set(cache_key, stats, config.CACHE_TIMEOUT_24_HOURS)
    return stats


def group_list_appearances(memberships):
    """Group an album's list appearances by list type, most important first.

    Labels come from ``core.constants`` so they match the codes actually
    stored on the list, and the group order follows
    ``LIST_TYPE_IMPORTANCE_ORDER`` rather than a hand-kept list of strings.
    """
    grouped = defaultdict(list)
    for membership in memberships:
        source = membership.list
        grouped[source.type].append(
            {
                "id": source.id,
                "name": source.name,
                "publication": source.publisher.name if source.publisher else "",
                "publisher": source.publisher,
                "type": source.type,
                "type_name": core_constants.get_list_type_label(source.type),
                "url": source.url,
                "year": source.year,
                "rank": membership.rank,
            }
        )

    return [
        (core_constants.get_list_type_label(code), grouped[code])
        for code in core_constants.LIST_TYPE_IMPORTANCE_ORDER
        if code in grouped
    ]


class AlbumHomePageView(StaffOnlyMixin, RobustPaginationMixin, ListView):
    """
    The album rankings page, with search, filtering and HTMX updates.

    Supports text search across title and published credit, a release-year
    range, artist and genre filters, and four sorts in either direction.
    """

    model = models.Album
    template_name = "music/home.html"
    context_object_name = "albums"
    paginate_by = config.DEFAULT_PAGE_SIZE
    paginate_orphans = 0

    def get_template_names(self):
        """Serve the right fragment for HTMX, the full page otherwise."""
        if self.request.GET.get("append") == "true":
            return ["music/includes/_album_list_append.html"]

        is_htmx = (
            self.request.headers.get("HX-Request")
            or self.request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or self.request.GET.get("partial") == "true"
        )
        if is_htmx:
            if self.request.headers.get("HX-Target") == "album-results-container":
                return ["music/includes/_album_list_results.html"]
            return ["music/includes/_album_list_content.html"]
        return super().get_template_names()

    def get_queryset(self):
        qs = models.Album.objects.with_relations().with_list_count()

        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(name_normalized__icontains=q)
                | Q(artist_credit__icontains=q)
            )

        start = _parse_int(self.request.GET.get("start"))
        if start is not None:
            qs = qs.filter(year_released__gte=start)
        end = _parse_int(self.request.GET.get("end"))
        if end is not None:
            qs = qs.filter(year_released__lte=end)

        artist_ids = _parse_id_list(self.request.GET.get("artists"))
        if artist_ids:
            qs = qs.filter(artists__id__in=artist_ids).distinct()

        genre_ids = _parse_id_list(self.request.GET.get("genres"))
        if genre_ids:
            qs = qs.filter(genres__id__in=genre_ids).distinct()

        return _apply_sort(
            qs,
            ALBUM_SORTS,
            self.request.GET.get("sort", "rank"),
            self.request.GET.get("dir", "asc"),
            default="rank",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        min_year, max_year = _get_year_bounds()
        context["min_year"] = min_year
        context["max_year"] = max_year
        context["artists"] = _cached_artist_options()
        genres = _cached_genre_options()
        context["genres"] = genres
        context["genre_groups"] = group_genre_options(genres)
        context.update(_cached_hero_stats())

        page_obj = context.get("page_obj")
        total_count = page_obj.paginator.count if page_obj else 0
        loaded_count = page_obj.end_index() if page_obj and total_count else 0
        context["total_count"] = total_count
        context["loaded_count"] = loaded_count
        context["remaining_count"] = total_count - loaded_count
        context["has_more"] = bool(page_obj and page_obj.has_next())
        context["next_page"] = (
            page_obj.next_page_number() if context["has_more"] else None
        )

        # Echo the filter state back so the controls stay in sync after a swap.
        context["current_q"] = self.request.GET.get("q", "")
        context["current_start"] = self.request.GET.get("start", "")
        context["current_end"] = self.request.GET.get("end", "")
        context["current_artists"] = self.request.GET.get("artists", "")
        context["current_genres"] = self.request.GET.get("genres", "")
        context["current_sort"] = self.request.GET.get("sort", "rank")
        context["current_dir"] = self.request.GET.get("dir", "asc")
        context["is_filtered"] = any(
            self.request.GET.get(param)
            for param in ("q", "start", "end", "artists", "genres")
        )
        context["filter_title"] = _filter_title(self.request.GET)
        context["decades"] = _decade_options(
            min_year,
            max_year,
            self.request.GET.get("start"),
            self.request.GET.get("end"),
        )
        context["show_rank"] = "filtered" if context["is_filtered"] else "alltime"
        context["highlight"] = _parse_int(self.request.GET.get("highlight"))
        context["query_string"] = self._filter_query_string()

        return context

    def _filter_query_string(self):
        """The current filter params, minus page, for load-more links."""
        params = self.request.GET.copy()
        params.pop("page", None)
        params.pop("append", None)
        return params.urlencode()


class AlbumDetailView(StaffOnlyMixin, DetailView):
    """One album, with every list it appears on grouped by list type."""

    model = models.Album
    template_name = "music/album_detail.html"
    context_object_name = "album"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        return models.Album.objects.prefetch_related(
            "artists",
            "artists__parent",
            "genres",
            Prefetch(
                "lists",
                queryset=models.AlbumListMembership.objects.select_related(
                    "list__publisher"
                ).order_by(
                    "-list__year",
                    "list__publisher__name",
                    "list__name",
                    "rank",
                ),
            ),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        album = context["album"]
        context["grouped_lists"] = group_list_appearances(album.lists.all())
        context["list_appearance_count"] = len(album.lists.all())

        total_album_count = cache.get(f"{config.CACHE_VERSION}:total_album_count")
        if total_album_count is None:
            total_album_count = models.Album.objects.count()
            cache.set(
                f"{config.CACHE_VERSION}:total_album_count",
                total_album_count,
                config.CACHE_TIMEOUT_24_HOURS,
            )
        context["total_album_count"] = total_album_count

        if album.artists.exists():
            context["related_albums"] = (
                models.Album.objects.filter(artists__in=album.artists.all())
                .exclude(id=album.id)
                .distinct()
                .order_by("rank")[:10]
            )

        return context


class ArtistListView(StaffOnlyMixin, RobustPaginationMixin, HTMXPartialMixin, ListView):
    """Artists that have at least one ranked album, with search and sorting."""

    model = models.Artist
    template_name = "music/artists/artist_list.html"
    context_object_name = "artists"
    paginate_by = config.DEFAULT_PAGE_SIZE
    paginate_orphans = 0
    htmx_partial_template = "music/artists/includes/_artist_list_results.html"

    def get_template_names(self):
        if self.request.GET.get("append") == "true":
            return ["music/artists/includes/_artist_list_append.html"]
        return super().get_template_names()

    def get_queryset(self):
        qs = (
            models.Artist.objects.annotate(albums_count=Count("albums"))
            .filter(albums_count__gt=0)
            .select_related("parent")
            .prefetch_related("subsidiaries")
        )

        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(name__icontains=q)

        return _apply_sort(
            qs,
            ARTIST_SORTS,
            self.request.GET.get("sort", "albums"),
            self.request.GET.get("dir", "desc"),
            default="albums",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_q"] = self.request.GET.get("q", "")
        context["current_sort"] = self.request.GET.get("sort", "albums")
        context["current_dir"] = self.request.GET.get("dir", "desc")

        page_obj = context.get("page_obj")
        total_count = page_obj.paginator.count if page_obj else 0
        context["total_count"] = total_count
        context["loaded_count"] = (
            page_obj.end_index() if page_obj and total_count else 0
        )
        context["has_more"] = bool(page_obj and page_obj.has_next())
        context["next_page"] = (
            page_obj.next_page_number() if context["has_more"] else None
        )
        return context


class ArtistDetailView(StaffOnlyMixin, DetailView):
    """One artist, with their ranked albums and any subsidiary acts."""

    model = models.Artist
    template_name = "music/artists/artist_detail.html"
    context_object_name = "artist"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        return models.Artist.objects.prefetch_related(
            Prefetch(
                "subsidiaries",
                queryset=models.Artist.objects.order_by("name"),
            ),
            Prefetch(
                "albums",
                queryset=models.Album.objects.with_relations()
                .with_list_count()
                .order_by("rank"),
            ),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        artist = context["artist"]
        albums = list(artist.albums.all())
        context["artist_albums"] = albums
        context["albums_count"] = len(albums)
        context["best_album"] = albums[0] if albums else None
        return context


class AlbumSearchView(StaffOnlyMixin, ListView):
    """HTMX search results for the album search box."""

    model = models.Album
    template_name = "music/includes/_album_search_results.html"
    context_object_name = "albums"
    paginate_by = 20

    def get_queryset(self):
        q = self.request.GET.get("q")
        if not q:
            return models.Album.objects.none()
        return (
            models.Album.objects.with_relations()
            .filter(
                Q(name__icontains=q)
                | Q(name_normalized__icontains=q)
                | Q(artist_credit__icontains=q)
            )
            .order_by("rank")[:20]
        )


class MusicListListView(
    StaffOnlyMixin, RobustPaginationMixin, HTMXPartialMixin, ListView
):
    """The source lists behind the album rankings, grouped by publication."""

    model = models.MusicList
    template_name = "music/lists/list_list.html"
    context_object_name = "music_lists"
    paginate_by = config.DEFAULT_PAGE_SIZE
    paginate_orphans = 0
    htmx_partial_template = "music/lists/includes/_list_list_results.html"

    def get_queryset(self):
        qs = (
            models.MusicList.objects.select_related("publisher")
            .annotate(album_count=Count("albumlistmembership"))
            .order_by("order")
        )

        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(publisher__name__icontains=q))

        list_type = self.request.GET.get("type")
        if list_type in dict(core_constants.LIST_TYPES):
            qs = qs.filter(type=list_type)

        sort = self.request.GET.get("sort", "order")
        if sort == "year":
            qs = qs.order_by("-year", "publisher__name", "name")
        elif sort == "albums":
            qs = qs.order_by("-album_count", "publisher__name", "name")
        elif sort == "publication":
            qs = qs.order_by("publisher__name", "-year", "name")

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_q"] = self.request.GET.get("q", "")
        context["current_type"] = self.request.GET.get("type", "")
        context["current_sort"] = self.request.GET.get("sort", "order")
        context["list_types"] = [
            {
                "code": code,
                "label": core_constants.get_list_type_label(code),
                "count": models.MusicList.objects.filter(type=code).count(),
            }
            for code in core_constants.LIST_TYPE_IMPORTANCE_ORDER
        ]
        context["total_count"] = (
            context["page_obj"].paginator.count if context.get("page_obj") else 0
        )
        return context


class AlbumCoverView(StaffOnlyMixin, View):
    """Serve our own stored copy of an album cover.

    The Cover Art Archive is the source of this art, but hotlinking it means
    every page view depends on archive.org, which 500s intermittently; a
    list page showing a hundred covers then shows several broken images on
    every load. Storing the bytes and serving them from here removes that
    dependency, and also the 307 redirect each remote image costs.

    The URL carries the archive's release MBID, image id and size, all of
    which are immutable for a given image, so the response is cached for a
    year. Staff-gated like every other music route.
    """

    # A year, which is the maximum worth asking for, marked immutable so a
    # revalidation request is never made.
    CACHE_CONTROL = "public, max-age=31536000, immutable"

    def get(self, request, release_mbid, image_id, size):
        cover = models.AlbumCover.objects.filter(
            release_mbid=release_mbid, image_id=image_id, size=size
        ).first()
        if cover is None:
            raise Http404("No such cover")

        response = HttpResponse(bytes(cover.data), content_type=cover.content_type)
        response["Cache-Control"] = self.CACHE_CONTROL
        response["Content-Length"] = str(len(cover.data))
        return response


class MusicImportView(StaffOnlyMixin, View):
    """Import the album rankings from uploaded files or the bundled release.

    Staff-gated like every other music view, as ``games.views.ImportView``
    now is too - it was login-gated until 2026-10-17, which let any verified
    account replace the game rankings.

    The import runs inline rather than over SSE: 500 albums land in well
    under a second, so the streaming progress machinery the games importer
    needs would be scaffolding without a purpose.
    """

    template_name = "music/import.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            self._context(MusicImportForm()),
        )

    def post(self, request):
        form = MusicImportForm(request.POST, request.FILES)
        summary = None
        error = None

        if form.is_valid():
            try:
                summary = self._run_import(form.cleaned_data)
            except Exception as exc:  # noqa: BLE001 - surfaced to the page
                # The importer runs in one transaction, so a failure leaves
                # the previous rankings in place; report it and carry on.
                error = str(exc)

        return render(
            request,
            self.template_name,
            self._context(form, summary=summary, error=error),
        )

    def _run_import(self, data):
        """Run the batch import, from uploads or the bundled files."""
        if data.get("seed_bundled_data"):
            missing = [
                name
                for name in BUNDLED_FILES.values()
                if not (BUNDLED_RELEASE_DIR / name).is_file()
            ]
            if missing:
                raise FileNotFoundError(
                    "Bundled release files are missing: " + ", ".join(missing)
                )
            with (
                (BUNDLED_RELEASE_DIR / BUNDLED_FILES["lists_file"]).open(
                    encoding="utf-8-sig", newline=""
                ) as lists_file,
                (BUNDLED_RELEASE_DIR / BUNDLED_FILES["albums_file"]).open(
                    encoding="utf-8-sig", newline=""
                ) as albums_file,
                (BUNDLED_RELEASE_DIR / BUNDLED_FILES["positions_file"]).open(
                    encoding="utf-8-sig"
                ) as positions_file,
            ):
                _, message = import_handler.import_batch(
                    lists_file, albums_file, positions_file
                )
        else:
            wrappers = [
                TextIOWrapper(data[field], encoding="utf-8-sig", newline="")
                for field in MusicImportForm.FILE_FIELDS
            ]
            try:
                _, message = import_handler.import_batch(*wrappers)
            finally:
                for wrapper in wrappers:
                    wrapper.detach()

        _invalidate_music_caches()
        return {"message": message, "counts": _music_counts()}

    def _context(self, form, summary=None, error=None):
        return {
            "form": form,
            "summary": summary,
            "error": error,
            "counts": _music_counts(),
            "bundled_files": [
                {"label": MusicImportForm().fields[field].label, "name": name}
                for field, name in BUNDLED_FILES.items()
            ],
            "bundled_dir": _bundled_dir_label(),
            "bundled_available": all(
                (BUNDLED_RELEASE_DIR / name).is_file()
                for name in BUNDLED_FILES.values()
            ),
        }


def _bundled_dir_label():
    """The bundled release directory, shown relative to the project root.

    Falls back to the absolute path when the directory sits outside the
    project, which only happens when it has been pointed elsewhere.
    """
    try:
        return str(BUNDLED_RELEASE_DIR.relative_to(settings.BASE_DIR))
    except ValueError:
        return str(BUNDLED_RELEASE_DIR)


def _music_counts():
    """Current row counts, shown before and after an import."""
    return {
        "albums": models.Album.objects.count(),
        "artists": models.Artist.objects.count(),
        "lists": models.MusicList.objects.count(),
        "publications": models.MusicPublication.objects.count(),
        "memberships": models.AlbumListMembership.objects.count(),
    }


def _invalidate_music_caches():
    """Drop the cached filter options and counts after a data change."""
    cache.delete_many(
        [
            config.CACHE_KEY_YEAR_STATS,
            f"{config.CACHE_VERSION}:music_artist_options",
            f"{config.CACHE_VERSION}:music_genre_options",
            f"{config.CACHE_VERSION}:music_hero_stats",
            f"{config.CACHE_VERSION}:total_album_count",
        ]
    )

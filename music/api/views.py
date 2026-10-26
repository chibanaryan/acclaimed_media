"""
Music API views.

Behind ``music.access.MusicAPIGateMixin`` - public once ``MUSIC_ENABLED``
is on, a staff-only 404 until then - and almost all read-only. ``all/`` is
the bulk endpoint feeding the client-side filtering bundle; there is
deliberately no ``version/`` endpoint beside it, because the album rankings
page renders the same data version into the page itself, so the client can
tell a stale copy from a current one without a second request.

``saved-filters/`` is the exception and the only endpoint here that writes.
It is why there are two mixins below rather than one: CSRF enforcement
now applies to this module, where before no unsafe method existed to trigger
it.
"""

from django.db.models import Count, Max, Min, Prefetch, Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView, Response

from core import constants as core_constants
from core.services import genre_tree
from core.services.query_params import parse_limit

from .. import config, models
from ..access import MusicAPIGateMixin
from ..services.artist_graph import ArtistGraph, artist_summary
from ..services.data_version import compute_album_data_version
from . import serializers


class MusicReadAPIMixin(MusicAPIGateMixin):
    """The section's gate, and nothing more, for the read-only endpoints.

    ``MusicAPIGateMixin`` names ``SessionAuthentication`` - without it a DRF
    view sees every request as anonymous, since
    ``DEFAULT_AUTHENTICATION_CLASSES`` is empty project-wide - and 404s
    anyone the section is hidden from. Past that gate a read needs no
    permission, so once ``MUSIC_ENABLED`` is on these are as public as
    games' API. The saved-filter views use :class:`MusicWriteAPIMixin`.
    """

    permission_classes = []


class MusicWriteAPIMixin(MusicAPIGateMixin):
    """The same gate, for the endpoints that write, plus a login.

    Separate from :class:`MusicReadAPIMixin` in name on purpose:
    ``SessionAuthentication`` enforces CSRF on unsafe methods, so every
    caller of a view using this mixin has to send ``X-CSRFToken``, and a
    reader can tell which endpoints that applies to without reading the
    methods.

    Note the status codes this yields. While the section is hidden an
    outsider gets 404 from the gate, because it has to look absent rather
    than merely forbidden. Once it is public a signed-out caller gets
    ``IsAuthenticated``'s 403, as games' saved filters answer.
    """

    permission_classes = [IsAuthenticated]


# Note on caching: these endpoints are deliberately uncached. `cache_page`
# wraps `dispatch`, so it is consulted *before* the gate runs - a response
# generated for a staff member is then replayed to anonymous callers, which
# defeats the hidden section entirely, and one cached while `MUSIC_ENABLED`
# was on would go on being served after it was turned off. The dataset is
# 1000 albums, so there is nothing here worth that risk. Any future caching
# must vary on the user and on the flag.


class AlbumAllDataView(MusicReadAPIMixin, APIView):
    """
    Every album in one payload, for client-side filtering.

    The whole corpus is 500 albums, which is about 100 KB of JSON and 38 KB
    over the wire, so the client fetches it once and filters in the browser
    instead of making an HTMX round trip per filter change. Field names are
    single letters for the same reason they are in the games and books
    equivalents: at this row count the key names are a real share of the
    payload.

    Artists and genres are sent as lookup tables rather than repeated inline,
    since the renderer has to reproduce the ``artist_links`` template tag and
    the genre filter has to resolve a root genre to its styles - and the
    artist filter an artist to the projects and aliases that roll up into
    it, which each artist's ``"d"`` lists (see ``music.services.artist_graph``).
    """

    def get(self, request):
        albums = (
            models.Album.objects.select_related("primary_musicbrainz_album_data")
            .prefetch_related(models.credits_prefetch(), "genres")
            .with_list_count()
            .order_by("rank")
        )

        # The alphabetical sort ships as a precomputed position rather than
        # being recomputed in the browser. `Lower(name)` orders under the
        # database's collation, and no JavaScript comparator reproduces that
        # for every title: `localeCompare` files "Agaetis byrjun" next to the
        # A's while SQLite sorts it past Z, and punctuation is weighted
        # differently again. Sending the server's own ordering makes the two
        # agree exactly, whatever the collation - and keeps local SQLite
        # behaving like production Postgres.
        name_order = {
            album_id: position
            for position, album_id in enumerate(
                models.Album.objects.order_by(Lower("name")).values_list(
                    "id", flat=True
                )
            )
        }

        albums_data = []
        artists = {}

        for album in albums:
            artist_ids = []
            # In credit order, which the renderer's credit line follows.
            for artist in album.credited_artists:
                artist_ids.append(artist.id)
                if artist.id not in artists:
                    artists[artist.id] = {"n": artist.name, "s": artist.slug}

            albums_data.append(
                {
                    "id": album.id,
                    "n": album.name,
                    # The server's text search is `name OR name_normalized OR
                    # artist_credit`, all three case-insensitive and none of
                    # them accent-folded. `name_normalized` is `unidecode(name)`
                    # and is stored only when it differs, so it is sent as it
                    # is: reimplementing unidecode in the browser would be a
                    # second, drifting copy of the rule.
                    "nn": album.name_normalized or "",
                    "s": album.slug,
                    "r": album.rank,
                    "y": album.year_released,
                    # The release date orders a year's albums. ISO, so the
                    # client compares it as a string; null when undated.
                    "rd": album.release_date and album.release_date.isoformat(),
                    "c": album.artist_credit,  # credit line, names joined
                    "t": album.thumbnail,  # 250px cover, local copy preferred
                    "ar": artist_ids,
                    "g": [genre.id for genre in album.genres.all()],
                    "lc": album.list_count,
                    "ni": name_order[album.id],  # alphabetical position
                }
            )

        # One fetch for the table, one in-memory walk for the descendants.
        # Recursing through `children` instead cost a query per genre, and
        # `values()` keeps the manager's ordering, so "d" comes out exactly
        # as it did - depth first, excluding the genre itself.
        genre_rows = list(
            models.MusicGenre.objects.values("id", "name", "slug", "parent_id", "level")
        )
        descendants = genre_tree.descendants_by_id(
            (row["id"], row["parent_id"]) for row in genre_rows
        )
        genres_data = [
            {
                "id": row["id"],
                "n": row["name"],
                "s": row["slug"],
                "p": row["parent_id"],
                "l": row["level"],
                "d": descendants.get(row["id"], []),
            }
            for row in genre_rows
        ]

        # An artist the filter can pick is one who owns albums, which
        # includes one credited only through a project (Jason Molina, via
        # Songs: Ohia), so those join the lookup too, with what rolls up
        # into them under "d".
        derived = ArtistGraph.load(with_credits=False).derived_map()
        missing = [artist_id for artist_id in derived if artist_id not in artists]
        for artist in models.Artist.objects.filter(id__in=missing).values(
            "id", "name", "slug"
        ):
            artists[artist["id"]] = {"n": artist["name"], "s": artist["slug"]}
        for artist_id, derived_ids in derived.items():
            artists[artist_id]["d"] = derived_ids

        return Response(
            {
                "version": compute_album_data_version(),
                "albums": albums_data,
                "artists": artists,
                "genres": genres_data,
            }
        )


class MusicUnifiedSearchView(MusicReadAPIMixin, APIView):
    """Albums and artists in one response, for the sidebar search box.

    The games equivalent (``games.api.views.UnifiedSearchView``) feeds the
    same search box in the same chrome; music had no endpoint at all, which
    is why the sidebar's search input was gated on ``media_type == 'games'``
    and the section had no search anywhere.
    """

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        album_limit = parse_limit(request.query_params.get("album_limit"), 5)
        artist_limit = parse_limit(request.query_params.get("artist_limit"), 3)

        if len(q) < 2:
            return Response({"albums": [], "artists": []})

        albums = (
            models.Album.objects.filter(
                Q(name__icontains=q)
                | Q(name_normalized__icontains=q)
                | Q(artist_credit__icontains=q)
            )
            .distinct()
            .order_by("rank")[:album_limit]
        )

        artists = _artists_with_albums(
            models.Artist.objects.filter(name__icontains=q), include_appearances=True
        )[:artist_limit]

        return Response(
            {
                "albums": [
                    {
                        "id": album.id,
                        "name": album.name,
                        "slug": album.slug,
                        "rank": album.rank,
                        "year_released": album.year_released,
                        "artist_credit": album.artist_credit,
                        "thumbnail": album.thumbnail or "",
                    }
                    for album in albums
                ],
                "artists": [
                    {
                        "id": artist.id,
                        "name": artist.name,
                        "slug": artist.slug,
                        "albums_count": artist.albums_count,
                        "appears_on_count": artist.appears_on_count,
                        # "5 albums", or "appears on 3 albums" for an act
                        # that owns none - what the dropdown shows.
                        "summary": artist_summary(
                            artist.albums_count, artist.appears_on_count
                        ),
                    }
                    for artist in artists
                ],
            }
        )


class AlbumListView(MusicReadAPIMixin, ListAPIView):
    """
    List albums with filtering and search.

    Query params: ``q`` (title or credit), ``artist`` (slug), ``genres``
    (comma-separated ids), ``start``/``end`` (release-year range).
    """

    serializer_class = serializers.AlbumSummarySerializer

    def get_queryset(self):
        qs = models.Album.objects.with_relations().with_list_count()
        params = self.request.query_params

        q = params.get("q")
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(artist_credit__icontains=q)

        artist = params.get("artist")
        if artist:
            # The artist's own albums, rolled-up projects and aliases included.
            artist_ids = models.Artist.objects.filter(slug=artist).values_list(
                "id", flat=True
            )
            graph = ArtistGraph.load(with_credits=False)
            qs = qs.filter(artists__id__in=graph.expand(artist_ids))

        genres = params.get("genres")
        if genres:
            genre_ids = [x.strip() for x in genres.split(",") if x.strip().isdigit()]
            if genre_ids:
                qs = qs.filter(genres__id__in=genre_ids)

        for param, lookup in (("start", "gte"), ("end", "lte")):
            value = params.get(param)
            if value and value.isdigit():
                qs = qs.filter(**{f"year_released__{lookup}": int(value)})

        return qs.distinct().order_by("rank")


class AlbumDetailView(MusicReadAPIMixin, RetrieveAPIView):
    """One album with its list appearances."""

    serializer_class = serializers.AlbumDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return models.Album.objects.with_relations().with_list_count()


class AlbumSearchAPIView(MusicReadAPIMixin, ListAPIView):
    """Album search, capped at 20 results."""

    serializer_class = serializers.AlbumSummarySerializer
    pagination_class = None

    def get_queryset(self):
        q = self.request.query_params.get("q")
        if not q:
            return models.Album.objects.none()
        qs = models.Album.objects.with_relations()
        return (
            (qs.filter(name__icontains=q) | qs.filter(artist_credit__icontains=q))
            .distinct()
            .order_by("rank")[:20]
        )


def _artists_with_albums(queryset, include_appearances=False):
    """``queryset``'s artists that own an album, most albums first.

    "Own" includes albums rolled up from projects and aliases, which no join
    counts, so this is a list with ``albums_count`` set on each artist.

    ``include_appearances`` adds the acts that only feature on or back other
    records (Crazy Horse), after every owner, with ``appears_on_count`` set:
    a search for one by name should find its page, though a browse of the
    rankings' artists should not list it.
    """
    graph = ArtistGraph.load()
    album_ids = graph.album_ids_by_artist()
    appears_on = graph.appears_on_by_artist() if include_appearances else {}
    artists = list(
        queryset.filter(id__in=list(set(album_ids) | set(appears_on))).prefetch_related(
            Prefetch(
                "relations",
                queryset=models.ArtistRelation.objects.select_related("related"),
            )
        )
    )
    for artist in artists:
        artist.albums_count = len(album_ids.get(artist.id, ()))
        artist.appears_on_count = len(appears_on.get(artist.id, ()))
    artists.sort(
        key=lambda artist: (
            -artist.albums_count,
            -artist.appears_on_count,
            artist.name.lower(),
        )
    )
    return artists


class ArtistListView(MusicReadAPIMixin, ListAPIView):
    """Artists with at least one ranked album of their own."""

    serializer_class = serializers.ArtistSerializer

    def get_queryset(self):
        qs = models.Artist.objects.all()
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(name__icontains=q)
        return _artists_with_albums(qs)


class ArtistDetailView(MusicReadAPIMixin, RetrieveAPIView):
    """One artist with their ranked albums and the ones they appear on."""

    serializer_class = serializers.ArtistDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return models.Artist.objects.prefetch_related(
            Prefetch(
                "relations",
                queryset=models.ArtistRelation.objects.select_related("related"),
            )
        )

    def get_object(self):
        artist = super().get_object()
        graph = ArtistGraph.load()
        albums = models.Album.objects.with_relations().with_list_count()
        artist.own_albums = albums.filter(id__in=graph.album_ids(artist.id)).order_by(
            "rank"
        )
        artist.appears_on_albums = albums.filter(
            id__in=graph.appears_on_ids(artist.id)
        ).order_by("rank")
        artist.albums_count = len(artist.own_albums)
        return artist


class MusicListListView(MusicReadAPIMixin, ListAPIView):
    """The published source lists."""

    serializer_class = serializers.MusicListSerializer

    def get_queryset(self):
        qs = models.MusicList.objects.select_related("publisher").order_by("order")
        list_type = self.request.query_params.get("type")
        if list_type in dict(core_constants.LIST_TYPES):
            qs = qs.filter(type=list_type)
        return qs


class MusicGenreListView(MusicReadAPIMixin, ListAPIView):
    """Every music genre, flat, ordered for tree reassembly."""

    serializer_class = serializers.MusicGenreSerializer
    pagination_class = None

    def get_queryset(self):
        return models.MusicGenre.objects.select_related("parent").order_by(
            "level", "display_order", "name"
        )


class MusicMetaView(MusicReadAPIMixin, APIView):
    """Counts and year distributions for the music database."""

    def get(self, request, *args, **kwargs):
        music_lists = models.MusicList.objects.all()
        bounds = models.Album.objects.aggregate(
            min_year=Min("year_released"), max_year=Max("year_released")
        )

        year_counts = list(
            models.Album.objects.exclude(year_released__isnull=True)
            .values("year_released")
            .annotate(count=Count("id"))
            .order_by("year_released")
        )
        decade_counts = {}
        for entry in year_counts:
            decade = (entry["year_released"] // 10) * 10
            decade_counts[decade] = decade_counts.get(decade, 0) + entry["count"]

        return Response(
            {
                "albums": {
                    "total_count": models.Album.objects.count(),
                    "min_year": bounds["min_year"],
                    "max_year": bounds["max_year"],
                    "years": year_counts,
                    "decades": [
                        {"decade": f"{decade}-{str(decade + 9)[-2:]}", "count": count}
                        for decade, count in sorted(decade_counts.items())
                    ],
                },
                "artists": {
                    "total_count": len(ArtistGraph.load().album_ids_by_artist())
                },
                "lists": {
                    "total_count": music_lists.count(),
                    "by_type": [
                        {
                            "type": code,
                            "label": core_constants.get_list_type_label(code),
                            "count": music_lists.filter(type=code).count(),
                        }
                        for code in core_constants.LIST_TYPE_IMPORTANCE_ORDER
                    ],
                    "years": list(
                        music_lists.values("year")
                        .annotate(count=Count("id"))
                        .order_by("year")
                    ),
                },
                "publications": {
                    "total_count": models.MusicPublication.objects.count()
                },
            }
        )


def _saved_filter_payload(filter_set):
    """One saved filter, in the shape the sidebar's dropdown reads."""
    return {
        "id": filter_set.id,
        "name": filter_set.name,
        "filters": filter_set.filters,
        "modified": filter_set.modified.isoformat(),
    }


def _validate_saved_filter_name(name, user, exclude_pk=None):
    """The name rules, or an error string if the name breaks one.

    Shared by create and rename so the two cannot disagree about the
    ceiling or about what counts as a duplicate - games enforces the same
    three rules twice over, once per method.
    """
    if not name:
        return "Filter name is required."
    if len(name) > config.SAVED_FILTER_NAME_MAX_LENGTH:
        return (
            f"Filter name must be {config.SAVED_FILTER_NAME_MAX_LENGTH} "
            "characters or less."
        )
    duplicates = models.SavedAlbumFilterSet.objects.filter(user=user, name=name)
    if exclude_pk is not None:
        duplicates = duplicates.exclude(pk=exclude_pk)
    if duplicates.exists():
        return "A filter with this name already exists."
    return None


class SavedAlbumFilterSetListCreateView(MusicWriteAPIMixin, APIView):
    """List this reader's saved album filters, or save the current one.

    The cap is ``config.MAX_SAVED_FILTERS`` and is enforced here rather than
    by a constraint, as games' is: it is a courtesy to keep the dropdown
    readable, not an invariant.
    """

    def get(self, request):
        filter_sets = models.SavedAlbumFilterSet.objects.filter(
            user=request.user
        ).order_by("-modified")[: config.MAX_SAVED_FILTERS]
        data = [_saved_filter_payload(entry) for entry in filter_sets]
        return Response({"filter_sets": data, "count": len(data)})

    def post(self, request):
        current_count = models.SavedAlbumFilterSet.objects.filter(
            user=request.user
        ).count()
        if current_count >= config.MAX_SAVED_FILTERS:
            return Response(
                {
                    "error": f"Maximum of {config.MAX_SAVED_FILTERS} saved "
                    "filters allowed. Delete one to save a new filter."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = str(request.data.get("name", "")).strip()
        error = _validate_saved_filter_name(name, request.user)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        filter_set = models.SavedAlbumFilterSet.objects.create(
            user=request.user,
            name=name,
            filters=request.data.get("filters", {}),
        )
        return Response(
            _saved_filter_payload(filter_set), status=status.HTTP_201_CREATED
        )


class SavedAlbumFilterSetDetailView(MusicWriteAPIMixin, APIView):
    """Rename or delete one saved album filter.

    Both methods go through an owner-scoped lookup, so another reader's id
    is a 404 rather than a 403 - the same answer the whole section gives an
    outsider.
    """

    def get_object(self, pk, user):
        return get_object_or_404(models.SavedAlbumFilterSet, pk=pk, user=user)

    def patch(self, request, pk):
        filter_set = self.get_object(pk, request.user)
        name = str(request.data.get("name", "")).strip()
        error = _validate_saved_filter_name(name, request.user, exclude_pk=pk)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        filter_set.name = name
        # `modified` is auto_now, so it has to be named for the update to
        # bump it - and the ordering the dropdown relies on is by `modified`.
        filter_set.save(update_fields=["name", "modified"])
        return Response({"id": filter_set.id, "name": filter_set.name})

    def delete(self, request, pk):
        self.get_object(pk, request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

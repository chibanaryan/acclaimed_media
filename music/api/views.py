"""
Music API views.

Read-only and staff-only. ``all/`` is the bulk endpoint feeding the
client-side filtering bundle; there is deliberately no ``version/`` endpoint
beside it, because the album rankings page renders the same data version into
the page itself, so the client can tell a stale copy from a current one
without a second request.
"""

from django.db.models import Count, Max, Min, Prefetch
from django.db.models.functions import Lower
from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.views import APIView, Response

from core import constants as core_constants
from core.permissions import IsStaffOrHide

from .. import models
from ..services.data_version import compute_album_data_version
from . import serializers


class StaffReadAPIMixin:
    """Authenticate by session, then allow staff only.

    ``DEFAULT_AUTHENTICATION_CLASSES`` is empty project-wide, so a DRF view
    that does not name an authenticator sees every request as anonymous -
    which, combined with ``IsStaffOrHide``, would 404 even for a logged-in
    staff member holding a valid session cookie. Naming
    ``SessionAuthentication`` here is what makes these endpoints reachable
    from the browser. Every music endpoint is read-only, so CSRF enforcement
    on unsafe methods never comes into play.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsStaffOrHide]


# Note on caching: these endpoints are deliberately uncached. `cache_page`
# wraps `dispatch`, so it is consulted *before* permissions run - a response
# generated for a staff member is then replayed to anonymous callers, which
# defeats `IsStaffOrHide` entirely. The dataset is 500 albums, so there is
# nothing here worth that risk. Any future caching must vary on the user.


class AlbumAllDataView(StaffReadAPIMixin, APIView):
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
    the genre filter has to resolve a root genre to its styles.
    """

    def get(self, request):
        albums = (
            models.Album.objects.prefetch_related("artists", "genres")
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
            for artist in album.artists.all():
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
                    "c": album.artist_credit,  # published credit
                    "t": album.thumbnail,  # 250px cover, local copy preferred
                    "ar": artist_ids,
                    "g": [genre.id for genre in album.genres.all()],
                    "lc": album.list_count,
                    "ni": name_order[album.id],  # alphabetical position
                }
            )

        genres_data = [
            {
                "id": genre.id,
                "n": genre.name,
                "s": genre.slug,
                "p": genre.parent_id,
                "l": genre.level,
                "d": genre.get_descendant_ids(include_self=False),
            }
            for genre in models.MusicGenre.objects.prefetch_related("children")
        ]

        return Response(
            {
                "version": compute_album_data_version(),
                "albums": albums_data,
                "artists": artists,
                "genres": genres_data,
            }
        )


class AlbumListView(StaffReadAPIMixin, ListAPIView):
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
            qs = qs.filter(artists__slug=artist)

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


class AlbumDetailView(StaffReadAPIMixin, RetrieveAPIView):
    """One album with its list appearances."""

    serializer_class = serializers.AlbumDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return models.Album.objects.with_relations().with_list_count()


class AlbumSearchAPIView(StaffReadAPIMixin, ListAPIView):
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


class ArtistListView(StaffReadAPIMixin, ListAPIView):
    """Artists with at least one ranked album."""

    serializer_class = serializers.ArtistSerializer

    def get_queryset(self):
        qs = (
            models.Artist.objects.annotate(albums_count=Count("albums"))
            .filter(albums_count__gt=0)
            .order_by("-albums_count", "name")
        )
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(name__icontains=q)
        return qs


class ArtistDetailView(StaffReadAPIMixin, RetrieveAPIView):
    """One artist with their ranked albums."""

    serializer_class = serializers.ArtistDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return models.Artist.objects.annotate(
            albums_count=Count("albums")
        ).prefetch_related(
            Prefetch(
                "albums",
                queryset=models.Album.objects.with_relations()
                .with_list_count()
                .order_by("rank"),
            )
        )


class MusicListListView(StaffReadAPIMixin, ListAPIView):
    """The published source lists."""

    serializer_class = serializers.MusicListSerializer

    def get_queryset(self):
        qs = models.MusicList.objects.select_related("publisher").order_by("order")
        list_type = self.request.query_params.get("type")
        if list_type in dict(core_constants.LIST_TYPES):
            qs = qs.filter(type=list_type)
        return qs


class MusicGenreListView(StaffReadAPIMixin, ListAPIView):
    """Every music genre, flat, ordered for tree reassembly."""

    serializer_class = serializers.MusicGenreSerializer
    pagination_class = None

    def get_queryset(self):
        return models.MusicGenre.objects.select_related("parent").order_by(
            "level", "display_order", "name"
        )


class MusicMetaView(StaffReadAPIMixin, APIView):
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
                    "total_count": models.Artist.objects.annotate(n=Count("albums"))
                    .filter(n__gt=0)
                    .count()
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

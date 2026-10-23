"""
Music API serializers.

Follows the same shape as the games and books serializers: plain
``ModelSerializer`` / ``Serializer`` classes, no routers, no viewsets.
"""

from django.db.models import F
from rest_framework import serializers

from .. import models


class IdSlugNameSerializer(serializers.Serializer):
    """Compact representation of a related object."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()


album_fields = [
    "id",
    "name",
    "name_normalized",
    "slug",
    "rank",
    "year_rank",
    "decade_rank",
    "year_released",
    "artist_credit",
    "artists",
    "genres",
    "cover_image_url",
    "thumbnail_url",
    "wikidata_id",
    "musicbrainz_release_group_id",
    "discogs_master_id",
]


class AlbumSummarySerializer(serializers.ModelSerializer):
    """Album fields needed by list and grid displays."""

    # In credit order: "artists" is Paul McCartney then Wings.
    artists = IdSlugNameSerializer(source="credited_artists", many=True)
    genres = IdSlugNameSerializer(many=True)
    list_count = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = models.Album
        fields = album_fields + ["list_count"]

    def get_thumbnail_url(self, obj):
        """The URL a client should render, which may be our local copy.

        ``cover_image_url`` is the Cover Art Archive's own URL, kept for
        provenance and for Open Graph scrapers; this is what to display.
        """
        return obj.thumbnail

    def get_list_count(self, obj):
        """Use the ``with_list_count()`` annotation when it is present."""
        annotated = getattr(obj, "list_count", None)
        if annotated is not None:
            return annotated
        return obj.lists.count()


class AlbumDetailSerializer(AlbumSummarySerializer):
    """Album fields plus every list appearance."""

    lists = serializers.SerializerMethodField()

    class Meta:
        model = models.Album
        fields = album_fields + ["list_count", "description", "lists"]

    def get_lists(self, obj):
        return obj.lists.order_by("list__publisher__name", "list__year").values(
            "rank",
            name=F("list__name"),
            publication=F("list__publisher__name"),
            type=F("list__type"),
            url=F("list__url"),
            year=F("list__year"),
        )


class ArtistSerializer(serializers.ModelSerializer):
    """Artist fields, their relation tags and an album count.

    ``albums_count`` counts the albums that are the artist's own, including
    those rolled up from projects and aliases; the views set it from
    ``music.services.artist_graph``. ``relations`` reads "Prince and the
    Revolution" as ``[{"kind": "P", "artist": <Prince>}]``.
    """

    albums_count = serializers.IntegerField(read_only=True)
    relations = serializers.SerializerMethodField()

    class Meta:
        model = models.Artist
        fields = [
            "id",
            "name",
            "slug",
            "musicbrainz_id",
            "wikidata_id",
            "albums_count",
            "relations",
        ]

    def get_relations(self, obj):
        return [
            {
                "kind": relation.kind,
                "artist": IdSlugNameSerializer(relation.related).data,
            }
            for relation in obj.relations.all()
        ]


class ArtistDetailSerializer(ArtistSerializer):
    """Artist fields plus their ranked albums, and the ones they appear on."""

    albums = AlbumSummarySerializer(many=True, read_only=True, source="own_albums")
    appears_on = AlbumSummarySerializer(
        many=True, read_only=True, source="appears_on_albums"
    )

    class Meta:
        model = models.Artist
        fields = ArtistSerializer.Meta.fields + ["albums", "appears_on"]


class MusicGenreSerializer(serializers.ModelSerializer):
    """A genre node, flat; the client reassembles the tree from parent_id."""

    parent_id = serializers.IntegerField(source="parent.id", allow_null=True)

    class Meta:
        model = models.MusicGenre
        fields = [
            "id",
            "name",
            "slug",
            "level",
            "display_order",
            "path",
            "parent_id",
            "icon_name",
        ]


class MusicListSerializer(serializers.ModelSerializer):
    """One published source list."""

    publication = serializers.CharField(source="publisher.name", default="")

    class Meta:
        model = models.MusicList
        fields = ["id", "name", "publication", "year", "type", "url", "order"]

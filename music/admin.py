"""Admin registrations for the music app."""

from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html

from music import models


class SubsidiaryArtistInline(admin.TabularInline):
    """Edit an act's side projects and member bands in place."""

    model = models.Artist
    fk_name = "parent"
    extra = 0
    fields = ["name", "slug", "musicbrainz_id", "wikidata_id"]
    show_change_link = True


class MusicGenreChildInline(admin.TabularInline):
    model = models.MusicGenre
    fk_name = "parent"
    extra = 0
    fields = ["name", "slug", "level", "display_order"]
    readonly_fields = ["level"]
    show_change_link = True


@admin.register(models.Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ["__str__", "slug", "musicbrainz_id", "wikidata_id", "album_count"]
    list_filter = ["parent"]
    search_fields = ["name", "slug", "musicbrainz_id", "wikidata_id"]
    inlines = [SubsidiaryArtistInline]
    raw_id_fields = ["parent"]
    prepopulated_fields = {"slug": ("name",)}

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("parent")
            .annotate(_album_count=Count("albums"))
        )

    @admin.display(description="Albums", ordering="_album_count")
    def album_count(self, obj):
        return obj._album_count


@admin.register(models.MusicGenre)
class MusicGenreAdmin(admin.ModelAdmin):
    list_display = ["name", "parent", "level", "path", "album_count", "display_order"]
    list_filter = ["level", "parent"]
    search_fields = ["name", "path"]
    readonly_fields = ["level", "path"]
    inlines = [MusicGenreChildInline]
    raw_id_fields = ["parent"]
    prepopulated_fields = {"slug": ("name",)}

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("parent")
            .annotate(_album_count=Count("albums"))
        )

    @admin.display(description="Albums", ordering="_album_count")
    def album_count(self, obj):
        return obj._album_count


@admin.register(models.Album)
class AlbumAdmin(admin.ModelAdmin):
    list_display = [
        "rank",
        "name",
        "artist_credit",
        "year_released",
        "year_rank",
        "decade_rank",
        "list_count",
        "wikidata_link",
    ]
    list_display_links = ["name"]
    list_filter = ["year_released"]
    search_fields = [
        "name",
        "name_normalized",
        "slug",
        "artist_credit",
        "wikidata_id",
        "musicbrainz_release_group_id",
    ]
    filter_horizontal = ["artists", "genres"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["created", "modified", "name_normalized"]
    ordering = ["rank"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related("artists", "genres")
            .annotate(_list_count=Count("lists"))
        )

    @admin.display(description="Lists", ordering="_list_count")
    def list_count(self, obj):
        return obj._list_count

    @admin.display(description="Wikidata")
    def wikidata_link(self, obj):
        if not obj.wikidata_id:
            return "-"
        return format_html(
            '<a href="https://www.wikidata.org/wiki/{}" target="_blank" '
            'rel="noopener">{}</a>',
            obj.wikidata_id,
            obj.wikidata_id,
        )


@admin.register(models.MusicPublication)
class MusicPublicationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "reputation_score", "list_count"]
    list_display_links = ["name", "slug"]
    list_editable = ["reputation_score"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_list_count=Count("lists"))

    @admin.display(description="Lists", ordering="_list_count")
    def list_count(self, obj):
        return obj._list_count


@admin.register(models.MusicList)
class MusicListAdmin(admin.ModelAdmin):
    list_display = ["name", "publisher", "year", "type", "order", "album_count"]
    list_filter = ["type", "year", "publisher"]
    search_fields = ["name", "publisher__name"]
    raw_id_fields = ["publisher"]
    ordering = ["order"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("publisher")
            .annotate(_album_count=Count("albumlistmembership"))
        )

    @admin.display(description="Albums", ordering="_album_count")
    def album_count(self, obj):
        return obj._album_count


@admin.register(models.AlbumListMembership)
class AlbumListMembershipAdmin(admin.ModelAdmin):
    list_display = ["list", "album", "rank"]
    list_filter = ["list__type", "list"]
    search_fields = ["album__name", "list__name"]
    raw_id_fields = ["list", "album"]
    ordering = ["list", "rank"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("list", "album")


class ExternalDataAdminBase(admin.ModelAdmin):
    """Shared shape for the fetched-metadata tables.

    These are all written by ``fetch_album_metadata`` rather than by hand, so
    the admin's job is to let staff see what a fetch produced and correct the
    odd wrong answer, not to be a data-entry form.
    """

    readonly_fields = ["fetched_at", "updated_at"]
    list_select_related = ["album"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("album")


@admin.register(models.WikipediaAlbumData)
class WikipediaAlbumDataAdmin(ExternalDataAdminBase):
    list_display = [
        "album",
        "wikidata_id",
        "page_title",
        "release_date",
        "record_label",
        "is_primary",
    ]
    list_filter = ["is_primary"]
    search_fields = ["album__name", "wikidata_id", "page_title", "record_label"]
    autocomplete_fields = ["album"]


@admin.register(models.DiscogsAlbumData)
class DiscogsAlbumDataAdmin(ExternalDataAdminBase):
    list_display = [
        "album",
        "master_id",
        "title",
        "main_release_year",
        "genre_summary",
        "style_summary",
        "is_primary",
    ]
    list_filter = ["is_primary"]
    search_fields = ["album__name", "master_id", "title"]
    autocomplete_fields = ["album"]

    @admin.display(description="Discogs genres")
    def genre_summary(self, obj):
        return ", ".join(obj.genres) or "-"

    @admin.display(description="Discogs styles")
    def style_summary(self, obj):
        return ", ".join(obj.styles) or "-"


@admin.register(models.MusicBrainzAlbumData)
class MusicBrainzAlbumDataAdmin(ExternalDataAdminBase):
    list_display = [
        "album",
        "release_group_mbid",
        "primary_type",
        "first_release_date",
        "rating",
        "cover_art_stored",
        "is_primary",
    ]
    list_filter = ["is_primary", "cover_art_stored", "primary_type"]
    search_fields = ["album__name", "release_group_mbid", "title"]
    autocomplete_fields = ["album"]


@admin.register(models.AlbumCover)
class AlbumCoverAdmin(admin.ModelAdmin):
    """The stored cover bytes.

    ``data`` is deliberately absent from every form and list: it is up to a
    few hundred kilobytes of binary per row, and rendering it into a change
    form would be slow and useless.
    """

    list_display = ["album", "size", "kilobytes", "content_type", "fetched_at"]
    list_filter = ["size", "content_type"]
    search_fields = ["album__name", "release_mbid", "image_id"]
    readonly_fields = ["fetched_at", "kilobytes", "preview"]
    exclude = ["data"]
    autocomplete_fields = ["album"]

    def get_queryset(self, request):
        # defer() the bytes: a changelist of 100 rows is otherwise ~5 MB.
        return super().get_queryset(request).select_related("album").defer("data")

    @admin.display(description="Size", ordering="byte_size")
    def kilobytes(self, obj):
        return f"{obj.byte_size // 1024} KB"

    @admin.display(description="Preview")
    def preview(self, obj):
        if not obj.pk:
            return "-"
        return format_html(
            '<img src="{}" width="200" height="200" style="object-fit:contain">',
            obj.album.thumbnail if obj.album else "",
        )


@admin.register(models.ListenedAlbum)
class ListenedAlbumAdmin(admin.ModelAdmin):
    """Albums users have marked as listened to.

    `raw_id_fields` rather than the `autocomplete_fields` the metadata
    admins use: a tracking changelist can hold a row per user per album, and
    an autocomplete widget loads its options per row.
    """

    list_display = ["user", "album_name", "wikidata_id", "created", "link_status"]
    list_filter = ["created"]
    search_fields = ["user__username", "user__email", "album__name", "wikidata_id"]
    raw_id_fields = ["user", "album"]
    readonly_fields = ["created"]
    ordering = ["-created"]

    @admin.display(description="Album")
    def album_name(self, obj):
        """The album's name, or the id it is waiting to be reconnected by."""
        if obj.album:
            return obj.album.name
        return f"(orphaned) Wikidata:{obj.wikidata_id}"

    @admin.display(description="Status")
    def link_status(self, obj):
        """Whether an import has left this row waiting for its album."""
        return "Connected" if obj.album else "Orphaned"


@admin.register(models.WantToListenAlbum)
class WantToListenAlbumAdmin(admin.ModelAdmin):
    """Albums users want to listen to."""

    list_display = ["user", "album_name", "wikidata_id", "created", "link_status"]
    list_filter = ["created"]
    search_fields = ["user__username", "user__email", "album__name", "wikidata_id"]
    raw_id_fields = ["user", "album"]
    readonly_fields = ["created"]
    ordering = ["-created"]

    @admin.display(description="Album")
    def album_name(self, obj):
        """The album's name, or the id it is waiting to be reconnected by."""
        if obj.album:
            return obj.album.name
        return f"(orphaned) Wikidata:{obj.wikidata_id}"

    @admin.display(description="Status")
    def link_status(self, obj):
        """Whether an import has left this row waiting for its album."""
        return "Connected" if obj.album else "Orphaned"

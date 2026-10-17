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

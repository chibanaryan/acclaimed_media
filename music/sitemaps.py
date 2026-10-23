"""
Sitemaps for the music section, merged into ``/sitemap.xml``.

Every section is empty until ``MUSIC_ENABLED`` is on: a hidden section 404s
for crawlers, and listing its URLs would advertise it. Django instantiates a
sitemap class per request, so ``items()`` reads the flag live and
``override_settings`` reaches it in tests.
"""

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from music import models
from music.services import landing_pages
from music.services.artist_graph import ArtistGraph


class MusicSitemap(Sitemap):
    """Lists ``music_items()`` only while the section is public."""

    def items(self):
        if not settings.MUSIC_ENABLED:
            return []
        return self.music_items()

    def music_items(self):
        raise NotImplementedError


class MusicStaticSitemap(MusicSitemap):
    """The section's index pages."""

    priority = 0.5
    changefreq = "weekly"

    def music_items(self):
        return ["music:home", "music:artist-list", "music:list-list", "music:browse"]

    def location(self, item):
        return reverse(item)


class MusicLandingPageSitemap(MusicSitemap):
    """The /music/genres/<slug>/ and /music/<decade>s/ ranking pages."""

    priority = 0.7
    changefreq = "weekly"

    def music_items(self):
        items = [
            ("music:by-genre", {"slug": genre["slug"]})
            for genre in landing_pages.get_landing_genres()
        ]
        items += [
            ("music:by-decade", {"decade": decade})
            for decade in landing_pages.get_landing_decades()
        ]
        return items

    def location(self, item):
        name, kwargs = item
        return reverse(name, kwargs=kwargs)


class AlbumSitemap(MusicSitemap):
    """One entry per album, best-ranked first."""

    priority = 0.8
    changefreq = "monthly"

    def music_items(self):
        return models.Album.objects.order_by("rank")

    def lastmod(self, obj):
        return obj.modified


class ArtistSitemap(MusicSitemap):
    """Artists with at least one ranked album of their own, as the list shows.

    An act that only features on or backs other records (Crazy Horse) has a
    page, but a page of other acts' albums is left for the crawl to find.
    """

    priority = 0.6
    changefreq = "monthly"

    def music_items(self):
        album_ids = ArtistGraph.load().album_ids_by_artist()
        return (
            models.Artist.objects.filter(id__in=list(album_ids))
            .exclude(slug__isnull=True)
            .exclude(slug="")
            .order_by("name")
        )


music_sitemaps = {
    "music-static": MusicStaticSitemap,
    "music-landing": MusicLandingPageSitemap,
    "music-albums": AlbumSitemap,
    "music-artists": ArtistSitemap,
}

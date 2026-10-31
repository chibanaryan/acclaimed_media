"""
Which music SEO ranking pages exist.

The single source of truth for ``/music/genres/<slug>/``,
``/music/<decade>s/``, the browse index and the music sitemap, as
``games.services.landing_pages`` is for the games pages. Both lists are
cached under keys in ``config.CACHE_KEYS``, so an import or a metadata
refresh drops them with everything else.

Kept free of ``music.views`` so the views, the sitemap and the tests can all
import it without a cycle.
"""

from collections import defaultdict

from django.db.models import Count

from core.services import genre_tree
from music import config, models
from music.services import caching

# How many albums go into a page's ItemList structured data.
TOP_N = 25

# A page needs enough albums to be worth a search result. In the 1000-album
# corpus this keeps every root genre but Classical (3 albums), and every
# decade from the 1950s on.
MIN_GENRE_ALBUMS = 10
MIN_DECADE_ALBUMS = 10


def get_landing_genres():
    """Root genres with a page: ``[{id, name, slug, album_count}]``.

    A root qualifies with a slug, at least one album tagged with it directly,
    and ``MIN_GENRE_ALBUMS`` across its whole subtree. The direct album is
    not pedantry: the heading's genre names come from the filter options,
    which list only genres an album carries, so a root reached solely
    through its styles would title its page "Most Acclaimed Albums".

    ``album_count`` is distinct across the subtree, as the sidebar counts
    it, so it is exactly what the page lists.
    """
    return caching.cached(
        config.CACHE_KEY_LANDING_GENRES, _landing_genres, config.CACHE_TIMEOUT_24_HOURS
    )


def _landing_genres():
    """`get_landing_genres`, uncached."""
    descendants = genre_tree.fetch_descendants_by_id(models.MusicGenre.objects.all())
    albums_by_genre = defaultdict(set)
    for album_id, genre_id in models.Album.objects.exclude(
        genres__isnull=True
    ).values_list("id", "genres__id"):
        albums_by_genre[genre_id].add(album_id)

    entries = []
    roots = (
        models.MusicGenre.objects.filter(level=0)
        .exclude(slug__isnull=True)
        .exclude(slug="")
        .order_by("display_order", "name")
        .values("id", "name", "slug")
    )
    for root in roots:
        if not albums_by_genre.get(root["id"]):
            continue
        albums = set()
        for genre_id in (root["id"], *descendants.get(root["id"], ())):
            albums |= albums_by_genre.get(genre_id, set())
        if len(albums) >= MIN_GENRE_ALBUMS:
            entries.append({**root, "album_count": len(albums)})
    return entries


def get_landing_decades():
    """Decades with a page, ascending: ``[1950, 1960, ...]``."""
    return caching.cached(
        config.CACHE_KEY_LANDING_DECADES,
        _landing_decades,
        config.CACHE_TIMEOUT_24_HOURS,
    )


def _landing_decades():
    """`get_landing_decades`, uncached."""
    counts = defaultdict(int)
    for row in (
        models.Album.objects.exclude(year_released__isnull=True)
        .order_by()
        .values("year_released")
        .annotate(count=Count("id"))
    ):
        counts[(row["year_released"] // 10) * 10] += row["count"]
    return sorted(
        decade for decade, count in counts.items() if count >= MIN_DECADE_ALBUMS
    )


def resolve_genre_slug(slug):
    """The landing entry for ``slug``, or ``None`` if it has no page."""
    for entry in get_landing_genres():
        if entry["slug"] == slug:
            return entry
    return None

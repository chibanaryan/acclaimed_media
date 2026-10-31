"""A reader's album counts, for the Account modal.

A service rather than the tracked-id helpers in ``music.views``, so that the
modal's view, which lives in ``games``, need not import that module.
"""

from django.db.models import Count, Q

from core.services import percentile
from music import config
from music.models import Album, ListenedAlbum, WantToListenAlbum
from music.services import caching

# "tracked", not "heard": the rank counts Have as well as Heard, and Have is
# for readers who track what they own, so "heard" could be false of them.
RANK_WORDING = percentile.RankWording(
    item="albums",
    people="listeners",
    verb="tracked",
    prompt="Mark an album Heard or Have",
)


def get_listener_counts():
    """How many Have and Heard albums each reader with any holds.

    Cached for an hour; a toggle drops it, through
    ``caching.invalidate_listen_caches``. Orphaned rows are left out, so a
    release dropping an album cannot leave a user ranked on what they can't see.
    """
    return caching.cached(
        config.CACHE_KEY_LISTENER_COUNTS,
        lambda: list(
            ListenedAlbum.objects.filter(album__isnull=False)
            .values("user_id")
            .annotate(collected=Count("pk"))
            .order_by()
            .values_list("collected", flat=True)
        ),
        config.CACHE_TIMEOUT_1_HOUR,
    )


def total_album_count():
    """How many albums the ranking holds; an admin edit waits out the 24 hours."""
    return caching.cached(
        config.CACHE_KEY_TOTAL_ALBUM_COUNT,
        Album.objects.count,
        config.CACHE_TIMEOUT_24_HOURS,
    )


def listening_stats(user):
    """Everything the modal's Music block shows for ``user``.

    Have and Heard are exclusive states, so ``collected`` is their plain sum.
    The reader's own counts are uncached, as games' are: the modal is opened
    rarely and must show a change they have just made.
    """
    counts = ListenedAlbum.objects.filter(user=user, album__isnull=False).aggregate(
        heard=Count("pk", filter=Q(owned=False)),
        owned=Count("pk", filter=Q(owned=True)),
    )
    collected = counts["heard"] + counts["owned"]
    return {
        "heard": counts["heard"],
        "owned": counts["owned"],
        "collected": collected,
        "want": WantToListenAlbum.objects.filter(
            user=user, album__isnull=False
        ).count(),
        "total_albums": total_album_count(),
        "rank_message": percentile.calculate_percentile(
            collected, get_listener_counts, RANK_WORDING
        )["message"],
    }

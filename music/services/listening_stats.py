"""A reader's album counts, for the Account modal.

A service rather than the tracked-id helpers in ``music.views``, so that the
modal's view, which lives in ``games``, need not import that module.
"""

from django.core.cache import cache
from django.db.models import Count, Q

from core.services import percentile
from music import config
from music.models import Album, ListenedAlbum, WantToListenAlbum

# "tracked", not "heard": the rank counts Have as well as Heard, and Have is
# for readers who track what they own, so "heard" could be false of them.
RANK_WORDING = percentile.RankWording(
    item="albums",
    people="listeners",
    more_than="You've tracked more albums than {percent}% of listeners",
)


def get_listener_distribution():
    """(user_id, count) of Have and Heard albums, for everyone with any.

    Sorted by count, as games' is. Cached for an hour; a toggle drops it, through
    ``caching.invalidate_listen_caches``. Orphaned rows are left out, so a
    release dropping an album cannot leave a user ranked on what they can't see.
    """
    distribution = cache.get(config.CACHE_KEY_LISTENER_DISTRIBUTION)
    if distribution is None:
        distribution = list(
            ListenedAlbum.objects.filter(album__isnull=False)
            .values("user_id")
            .annotate(collected=Count("pk"))
            .order_by("collected")
            .values_list("user_id", "collected")
        )
        cache.set(
            config.CACHE_KEY_LISTENER_DISTRIBUTION,
            distribution,
            config.CACHE_TIMEOUT_1_HOUR,
        )
    return distribution


def listening_stats(user):
    """Everything the modal's Music block shows for ``user``.

    Have and Heard are exclusive states, so ``collected`` is their plain sum.
    Uncached, as games' counts are: the modal is opened rarely and must show a
    change the reader has just made.
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
        "total_albums": Album.objects.count(),
        "rank_message": percentile.calculate_percentile(
            collected, get_listener_distribution, RANK_WORDING
        )["message"],
    }

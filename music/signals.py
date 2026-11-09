"""Cache drops for changes made outside the section's own write paths.

The toggle, `mark_albums_listened` and an import each drop what they change
(`music.services.caching`). A row edited in the admin, or a user, album or
list deleted there, went through none of them: the listener counts lagged an
hour, a reader's id sets five minutes, and the heading's counts a day.

Every drop here waits for the commit and is folded into one
(`core.cache_helpers.drop_on_commit`), with the drop the toggle or the bulk
command queues for itself, so an import, which saves and deletes rows by the
thousand, pays one drop at its commit for being heard.

Not covered, and still waiting out a TTL or `clear_music_caches`: an album
whose year or genres are edited in the admin (the year counts and landing
lists, a day), and a tracking row moved to another user or an album deleted
there (the readers' id sets, five minutes).
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from music.models import (
    Album,
    AlbumCredit,
    Artist,
    ListenedAlbum,
    MusicList,
    MusicPublication,
    WantToListenAlbum,
)
from music.services import caching


@receiver([post_save, post_delete], sender=ListenedAlbum)
@receiver([post_save, post_delete], sender=WantToListenAlbum)
def drop_listen_caches_on_tracking_change(sender, instance, **kwargs):
    """A reader's id sets and the listener counts follow their rows.

    A deleted user is covered too: the cascade deletes their rows one by
    one, since these receivers rule out the fast path.
    """
    caching.invalidate_listen_caches([instance.user_id])


@receiver([post_save, post_delete], sender=Album)
@receiver([post_save, post_delete], sender=AlbumCredit)
@receiver([post_save, post_delete], sender=Artist)
@receiver([post_save, post_delete], sender=MusicList)
@receiver([post_save, post_delete], sender=MusicPublication)
def drop_counts_on_count_change(sender, instance, **kwargs):
    """The section's counts follow a row that is added or deleted.

    Albums, artists, the credits that say which artists have an album, and
    the lists and their publications: what the heading counts and the
    filters offer. Not an ordinary save: a metadata pass saves every album
    and artist, and the entries would never survive it. `post_delete` sends
    no ``created``. A deleted album orphans its tracking rows by
    SET_NULL, which sends no signal of theirs, so the listener counts, one
    of the section's keys, go here.
    """
    if kwargs.get("created", True):
        caching.invalidate_music_caches_on_commit()

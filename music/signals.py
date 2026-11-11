"""Cache drops for changes made outside the section's own write paths.

The toggle, `mark_albums_listened` and an import each drop what they change
(`music.services.caching`). A row edited in the admin, or a user, album or
list deleted there, went through none of them: the listener counts lagged an
hour, a reader's id sets five minutes, and the heading's counts a day.

Every drop here waits for the commit and is folded into one
(`core.cache_helpers.drop_on_commit`), with the drop the toggle or the bulk
command queues for itself, so an import, which saves and deletes rows by the
thousand, pays one drop at its commit for being heard.

A genre renamed or deleted there counts, as do an album's year or genres
changed there (the year counts and the landing lists), a tracking row given
to another reader and an album deleted with rows on it (the readers' id
sets). A changed year or reader is seen without a query, from what the row
held when it was read (`core.loaded_values`).
"""

from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete
from django.dispatch import receiver

from core import loaded_values

from music.models import (
    Album,
    AlbumCredit,
    Artist,
    ListenedAlbum,
    MusicGenre,
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
    one, since these receivers rule out the fast path. A row given to
    another reader in the admin drops the reader it left as well, whose
    sets went on naming the album.
    """
    readers = {instance.user_id}
    left = loaded_values.previous(instance, "user_id", kwargs.get("update_fields"))
    if left is not loaded_values.UNKNOWN:
        readers.add(left)
    caching.invalidate_listen_caches(readers)


@receiver(pre_delete, sender=Album)
def drop_listen_caches_on_album_delete(sender, instance, **kwargs):
    """The readers of an album being deleted have it in their cached sets.

    Their rows stay, orphaned by SET_NULL, which sends no signal of theirs;
    before the delete, while the rows still name the album.
    """
    readers = set()
    for model in (ListenedAlbum, WantToListenAlbum):
        readers.update(
            model.objects.filter(album=instance).values_list("user_id", flat=True)
        )
    caching.invalidate_listen_caches(readers)


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


@receiver(post_save, sender=Album)
def drop_counts_on_year_change(sender, instance, created, update_fields=None, **kwargs):
    """The year counts and the landing lists follow an album's year.

    Only a year that changed: a metadata pass saves every album, and the
    entries would never survive that.
    """
    if not created and loaded_values.changed(instance, "year_released", update_fields):
        caching.invalidate_music_caches_on_commit()


@receiver(m2m_changed, sender=Album.genres.through)
def drop_counts_on_genre_change(sender, action, **kwargs):
    """The genre counts and the landing lists follow an album's genres.

    After the change. The corpus-wide rebuild sets every album's genres
    inside one transaction, so its drops fold into the one at its commit.
    """
    if action in ("post_add", "post_remove", "post_clear"):
        caching.invalidate_music_caches_on_commit()


@receiver([post_save, post_delete], sender=MusicGenre)
def drop_counts_on_genre_edit(sender, instance, **kwargs):
    """The genre filter and the landing lists follow a genre's name and
    existence. Any save, not only a new row: a rename is the edit that
    matters, and genres are saved rarely - the corpus-wide rebuild saves
    them in one transaction, which folds its drops into one at its commit.
    """
    caching.invalidate_music_caches_on_commit()

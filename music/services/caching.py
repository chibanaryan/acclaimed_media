"""Cache invalidation for the music section.

Lives here rather than in ``music.views`` so the importer can call it:
``views`` imports ``import_handler``, so the dependency cannot run the other
way. It used to be a private helper on the view, which meant the import page
dropped the cached counts and the ``import_music_data`` management command
did not - and a command-line import left the heading reading "The top 500
most recommended albums across 54 critic lists" for up to 24 hours after the
release grew to 1000.
"""

from functools import partial

from django.core.cache import cache
from django.db import transaction

from music import config


def invalidate_music_caches() -> None:
    """Drop every cached filter option and count the section holds.

    ``config.CACHE_KEYS`` is the whole set, so a value that is cached without
    being listed there is a value nothing can invalidate.
    """
    cache.delete_many(list(config.CACHE_KEYS))


def invalidate_listen_caches(user_ids) -> None:
    """Drop these users' cached tracking id sets, and the listener distribution.

    Separate from `invalidate_music_caches` because these keys are per-user:
    there is no enumerable set of them, so they are dropped by the three things
    that can change them rather than by a blanket sweep. The distribution is
    one global key, but those same three are what normally change it; a row
    edited in the admin or a deleted user waits out its hour, as games' does.

    Runs once the open transaction commits, or at once with none open. An
    import holds a transaction across several steps, and dropped inside it, a
    page load before the commit would refill a set from the old rows with
    nothing left to drop it. A read already under way at the commit can still
    do that, for the set's TTL. ``robust`` because the rows are committed by
    then: a cache error must not report the write as failed.
    """
    if not user_ids:
        return
    keys = [config.CACHE_KEY_LISTENER_DISTRIBUTION]
    for user_id in user_ids:
        keys.extend(
            template.format(user_id=user_id)
            for template in config.PER_USER_CACHE_KEY_TEMPLATES
        )
    transaction.on_commit(partial(cache.delete_many, keys), robust=True)

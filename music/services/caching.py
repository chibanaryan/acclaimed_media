"""Cache invalidation for the music section.

Lives here rather than in ``music.views`` so the importer can call it:
``views`` imports ``import_handler``, so the dependency cannot run the other
way. It used to be a private helper on the view, which meant the import page
dropped the cached counts and the ``import_music_data`` management command
did not - and a command-line import left the heading reading "The top 500
most recommended albums across 54 critic lists" for up to 24 hours after the
release grew to 1000.
"""

import logging
from functools import partial
from typing import Any, Callable, Iterable, List, Optional
from uuid import uuid4

from django.core.cache import cache
from django.db import transaction

from core.cache_helpers import cache_get, cache_set, remember_in_batch
from music import config

logger = logging.getLogger(__name__)

CACHES_NOT_CLEARED = (
    "Caches not cleared: filter options, counts and landing pages can lag for "
    "up to 24 hours. Run python manage.py clear_music_caches to clear them."
)


def _drop(keys: List[str]) -> bool:
    """Delete ``keys``, reporting failure rather than raising it.

    Every caller has already committed the write these keys describe, so a
    cache error must not report that write as failed. The generation moves
    first, so a read under way cannot save over the delete (see `cached`).
    """
    try:
        cache.set(config.CACHE_KEY_GENERATION, uuid4().hex, None)
        cache.delete_many(keys)
    except Exception:  # noqa: BLE001 - logged, and the write stands
        logger.exception("Music caches were not dropped")
        return False
    return True


def current_generation() -> Optional[str]:
    """The value `set_if_current` compares against, taken before reading rows.

    A page's batch answers this, so a miss costs no second read here. A value
    from the start of the request is older, which only makes the check stricter.
    """
    return cache_get(config.CACHE_KEY_GENERATION)


def set_if_current(
    key: str, value: Any, timeout: int, generation: Optional[str]
) -> None:
    """Cache ``value`` unless an invalidation has run since ``generation``.

    Without this, a read that queried just before a commit saves the old rows
    just after the commit's delete, and they stay for the key's whole TTL. A
    tiny window remains between this check and the write. A skipped value still
    answers the rest of a batch, or each later read would compute it again.
    """
    if cache.get(config.CACHE_KEY_GENERATION) == generation:
        cache_set(key, value, timeout)
    else:
        remember_in_batch(key, value)


def cached(key: str, compute: Callable[[], Any], timeout: int) -> Any:
    """``key``'s value, computed and saved on a miss.

    Every value in this section is written through here or `set_if_current`.
    A hit costs what `cache_get` costs; a miss adds one generation read, or
    two outside a page's batch.
    """
    value = cache_get(key)
    if value is None:
        generation = current_generation()
        value = compute()
        set_if_current(key, value, timeout, generation)
    return value


def invalidate_music_caches() -> bool:
    """Drop every cached filter option and count the section holds.

    ``config.CACHE_KEYS`` is the whole set, so a value that is cached without
    being listed there is a value nothing can invalidate.

    Returns:
        False if the drop failed. It is logged, and the values lag their TTL.
    """
    return _drop(list(config.CACHE_KEYS))


def _listen_keys(user_ids: Iterable[int]) -> List[str]:
    """Every per-user key for these users."""
    return [
        template.format(user_id=user_id)
        for user_id in user_ids
        for template in config.PER_USER_CACHE_KEY_TEMPLATES
    ]


def invalidate_listen_caches(user_ids) -> None:
    """Drop these users' cached tracking id sets, and the listener counts.

    Separate from `invalidate_music_caches` because these keys are per-user:
    there is no enumerable set of them, so they are dropped by the things that
    can change them rather than by a blanket sweep: a toggle and the bulk
    command here, and an import through `invalidate_release_caches`. The
    listener counts are one global key, but those same things normally change
    them; a row edited in the admin or a deleted user waits out its hour, as
    games' does.

    Runs once the open transaction commits, or at once with none open: dropped
    inside one, a page load before the commit would refill a set from the old
    rows with nothing left to drop it.
    """
    if not user_ids:
        return
    keys = [config.CACHE_KEY_LISTENER_COUNTS, *_listen_keys(user_ids)]
    transaction.on_commit(partial(_drop, keys))


def invalidate_release_caches(user_ids) -> bool:
    """Everything an import changed, in one drop: `invalidate_music_caches`'
    keys and `invalidate_listen_caches`' for these users.

    For `import_batch`, once its transaction has committed.

    Returns:
        False if the drop failed. It is logged, and the values lag their TTL.
    """
    return _drop([*config.CACHE_KEYS, *_listen_keys(user_ids)])

"""
Shared cache helper functions for the multi-media platform.

Provides common caching patterns used across games and books apps
to reduce code duplication.
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from threading import local
from uuid import uuid4

from django.core.cache import cache
from django.db import transaction
from django.db.models import Max, Min

logger = logging.getLogger(__name__)

# The active `batched_cache_reads` block's (keys, found), or None outside one.
_batched = ContextVar("batched_cache_reads", default=None)

# Keys waiting on this thread's commit, as ``drops``: {generation key: {keys}}.
_queued = local()

# Only has to outlive a read: one that loses a generation to expiry just skips
# its save.
GENERATION_TIMEOUT = 60 * 60


@contextmanager
def batched_cache_reads(keys):
    """Read ``keys`` from the default cache in one round trip for this block.

    In production the default alias is a `DatabaseCache`, so every
    `cache.get` is a query. The games rankings page read fifteen values one
    at a time (Sentry ACCLAIMED-VIDEO-GAMES-9E, an N+1 on ``cache_table``);
    `get_many` fetches them in one SELECT, and `cache_get` answers from it.

    The batch is the answer for every key it asked for, misses included:
    a crawler's new filter misses its facet keys every time, and re-reading
    each would cost the queries the batch saved. So a batched key has to be
    written with `cache_set`, or a second read in the block will not see it.
    Readers of one key share one object, where `cache.get` unpickled a copy
    each - do not mutate what it returns.
    """
    keys = list(dict.fromkeys(keys))
    token = _batched.set((set(keys), cache.get_many(keys)))
    try:
        yield
    finally:
        _batched.reset(token)


def cache_get(key):
    """`cache.get(key)`, answered by an active batch when it asked for the key."""
    batch = _batched.get()
    if batch is not None and key in batch[0]:
        return batch[1].get(key)
    return cache.get(key)


def remember_in_batch(key, value):
    """``value`` for the rest of an active batch, if it asked for ``key``."""
    batch = _batched.get()
    if batch is not None and key in batch[0]:
        batch[1][key] = value


def cache_set(key, value, timeout):
    """`cache.set`, and the value for the rest of an active batch."""
    cache.set(key, value, timeout)
    remember_in_batch(key, value)


def current_generation(generation_key):
    """The value `set_if_current` compares against, taken before reading rows.

    A page's batch can answer this, so a miss costs no second read here. A value
    from the start of the request is older, which only makes the check stricter.
    """
    return cache_get(generation_key)


def set_if_current(key, value, timeout, generation_key, generation):
    """Cache ``value`` unless `drop_keys` has moved ``generation_key`` since.

    Without this, a read that queried just before a commit saves the old rows
    just after the commit's delete, and they stay for the key's whole TTL. A
    tiny window remains between this check and the write. A skipped value still
    answers the rest of a batch, or each later read would compute it again.
    """
    if cache.get(generation_key) == generation:
        cache_set(key, value, timeout)
    else:
        remember_in_batch(key, value)


def cached(key, compute, timeout, generation_key):
    """``key``'s value, computed and saved on a miss, guarded by `set_if_current`.

    A hit costs what `cache_get` costs; a miss adds one generation read, or two
    outside a batch holding it.
    """
    value = cache_get(key)
    if value is None:
        generation = current_generation(generation_key)
        value = compute()
        set_if_current(key, value, timeout, generation_key, generation)
    return value


def drop_keys(keys, generation_key) -> bool:
    """Delete ``keys``, reporting failure rather than raising it.

    Every caller has already committed the write these keys describe, so a
    cache error must not report that write as failed. The generation moves
    first, so a read under way cannot save over the delete (see `cached`).

    Returns:
        False if the drop failed. It is logged, and the values lag their TTL.
    """
    try:
        cache.set(generation_key, uuid4().hex, GENERATION_TIMEOUT)
        cache.delete_many(keys)
    except Exception:  # noqa: BLE001 - logged, and the write stands
        logger.exception("Cache keys were not dropped: %s", keys[:5])
        return False
    return True


def _flush_queued_drops():
    """Run every drop this thread has queued, one per generation."""
    queued, _queued.drops = getattr(_queued, "drops", {}), {}
    for generation_key, keys in queued.items():
        drop_keys(sorted(keys), generation_key)


def drop_on_commit(key, generation_key):
    """`drop_keys` once the open transaction commits, or at once with none.

    Inside one, as a `post_save` during an import is, a page load before the
    commit would refill ``key`` from the old rows with nothing left to drop it.
    Keys are collected and flushed together, because an import saves a thousand
    rows and each drop is several queries on a `DatabaseCache`: the first hook
    to run empties the queue and the rest find nothing. A rolled-back write
    leaves its keys queued for the next commit on this thread, which drops them
    needlessly and harmlessly.
    """
    if not hasattr(_queued, "drops"):
        _queued.drops = {}
    _queued.drops.setdefault(generation_key, set()).add(key)
    transaction.on_commit(_flush_queued_drops)


def get_year_bounds(
    model_class,
    year_field,
    cache_key,
    cache_timeout,
    default_min=1970,
    generation_key=None,
):
    """
    Return cached global min/max years for a model.

    Args:
        model_class: Django model class to query
        year_field: Name of the year field on the model
        cache_key: Unique cache key for this model's year stats
        cache_timeout: Cache timeout in seconds
        default_min: Default minimum year if no data exists
        generation_key: The section's generation, if it guards its writes

    Returns:
        Tuple of (min_year, max_year)
    """

    def aggregate():
        return model_class.objects.aggregate(
            min_year=Min(year_field),
            max_year=Max(year_field),
        )

    if generation_key is not None:
        year_stats = cached(cache_key, aggregate, cache_timeout, generation_key)
    else:
        year_stats = cache_get(cache_key)
        if year_stats is None:
            year_stats = aggregate()
            cache_set(cache_key, year_stats, cache_timeout)
    min_year = year_stats["min_year"] or default_min
    max_year = year_stats["max_year"] or datetime.today().year
    return min_year, max_year

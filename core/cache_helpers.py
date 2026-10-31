"""
Shared cache helper functions for the multi-media platform.

Provides common caching patterns used across games and books apps
to reduce code duplication.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from django.core.cache import cache
from django.db.models import Max, Min

# The active `batched_cache_reads` block's (keys, found), or None outside one.
_batched = ContextVar("batched_cache_reads", default=None)


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


def get_year_bounds(
    model_class,
    year_field,
    cache_key,
    cache_timeout,
    default_min=1970,
    read_through=None,
):
    """
    Return cached global min/max years for a model.

    Args:
        model_class: Django model class to query
        year_field: Name of the year field on the model
        cache_key: Unique cache key for this model's year stats
        cache_timeout: Cache timeout in seconds
        default_min: Default minimum year if no data exists
        read_through: A section's own ``(key, compute, timeout)`` cache read,
            for one that guards its writes

    Returns:
        Tuple of (min_year, max_year)
    """

    def aggregate():
        return model_class.objects.aggregate(
            min_year=Min(year_field),
            max_year=Max(year_field),
        )

    if read_through is not None:
        year_stats = read_through(cache_key, aggregate, cache_timeout)
    else:
        year_stats = cache_get(cache_key)
        if year_stats is None:
            year_stats = aggregate()
            cache_set(cache_key, year_stats, cache_timeout)
    min_year = year_stats["min_year"] or default_min
    max_year = year_stats["max_year"] or datetime.today().year
    return min_year, max_year

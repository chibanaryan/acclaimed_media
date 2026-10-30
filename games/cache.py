"""
Cache utilities for the games app.

Centralized cache key management and invalidation functions to avoid
tight coupling between signals and views.
"""

from django.core.cache import cache

HERO_STATS_CACHE_KEY = "homepage_hero_stats"


def played_ids_cache_key(user_id):
    """The key of a user's cached played-game ids."""
    return f"played_games_{user_id}"


def want_ids_cache_key(user_id):
    """The key of a user's cached want-to-play game ids."""
    return f"want_to_play_games_{user_id}"


def invalidate_played_games_cache(user_id):
    """Invalidate the played games cache for a specific user."""
    cache.delete(played_ids_cache_key(user_id))


def invalidate_want_to_play_cache(user_id):
    """Invalidate the want-to-play games cache for a specific user."""
    cache.delete(want_ids_cache_key(user_id))

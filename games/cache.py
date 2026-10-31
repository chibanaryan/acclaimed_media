"""
Cache utilities for the games app.

Centralized cache key management and invalidation functions to avoid
tight coupling between signals and views.

A value here that something invalidates is read through
`core.cache_helpers.cached` and dropped through `drop_on_commit`, so a page
load during an import cannot put the old rows back (see those two). There is a
generation per family rather than per key, or one for the whole section: a
generation row is written on every drop, whether or not the key was cached, so
one per developer and user could outgrow the cache table's budget; and a shared
one would have the weekly refresh cancel every other family's saves.
"""

from core import cache_helpers
from games import config

HERO_STATS_CACHE_KEY = "homepage_hero_stats"

GENERATION_HERO = "games_generation:hero"
GENERATION_TRACKING = "games_generation:tracking"
GENERATION_DEVELOPERS = "games_generation:developers"


def played_ids_cache_key(user_id):
    """The key of a user's cached played-game ids."""
    return f"played_games_{user_id}"


def want_ids_cache_key(user_id):
    """The key of a user's cached want-to-play game ids."""
    return f"want_to_play_games_{user_id}"


def developer_detail_cache_key(developer_id):
    """The key of a developer page's cached context."""
    return f"{config.CACHE_VERSION}:developer_detail:{developer_id}"


def invalidate_hero_stats():
    """Invalidate the counts in the rankings heading."""
    cache_helpers.drop_on_commit(HERO_STATS_CACHE_KEY, generation_key=GENERATION_HERO)


def invalidate_played_games_cache(user_id):
    """Invalidate the played games cache for a specific user."""
    cache_helpers.drop_on_commit(
        played_ids_cache_key(user_id), generation_key=GENERATION_TRACKING
    )


def invalidate_want_to_play_cache(user_id):
    """Invalidate the want-to-play games cache for a specific user."""
    cache_helpers.drop_on_commit(
        want_ids_cache_key(user_id), generation_key=GENERATION_TRACKING
    )


def invalidate_played_counts():
    """Invalidate the played count of every user, which the rank line reads."""
    cache_helpers.drop_on_commit(
        config.CACHE_KEY_PLAYED_COUNTS, generation_key=GENERATION_TRACKING
    )


def invalidate_developer_detail(developer_id):
    """Invalidate one developer page's cached context."""
    cache_helpers.drop_on_commit(
        developer_detail_cache_key(developer_id),
        generation_key=GENERATION_DEVELOPERS,
    )

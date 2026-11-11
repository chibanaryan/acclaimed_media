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
# How many games each release year has, for a game page's "#N of M" lines
YEAR_COUNTS_CACHE_KEY = f"{config.CACHE_VERSION}:game_year_counts"

GENERATION_HERO = "games_generation:hero"
GENERATION_TRACKING = "games_generation:tracking"
GENERATION_DEVELOPERS = "games_generation:developers"
GENERATION_RELEASE = "games_generation:release"

# The genre list, with counts, that the CSV download names its file by
CSV_GENRES_CACHE_KEY = f"search_genres_list_with_counts:{config.CACHE_VERSION}"


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
    """Invalidate the counts in the rankings heading, and a game page's
    "#N of M" totals, which are counts of the same rows."""
    cache_helpers.drop_on_commit(
        HERO_STATS_CACHE_KEY, YEAR_COUNTS_CACHE_KEY, generation_key=GENERATION_HERO
    )


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


def release_cache_keys():
    """The day-long caches a games release changes and nothing else drops.

    Not keyed on the data version, as the sidebar's genre and series lists
    are: the year bounds, the platform list, the landing pages' lists and
    the CSV's genre list. A release adding a year left the year grid ending
    a year early, and that year's landing page a 404, for a day.
    """
    from games.services import landing_pages
    from games.services.game_filters import PLATFORMS_CACHE_KEY

    return [
        config.CACHE_KEY_YEAR_STATS,
        PLATFORMS_CACHE_KEY,
        CSV_GENRES_CACHE_KEY,
        *landing_pages.cache_keys(),
    ]


def invalidate_release_caches():
    """Drop `release_cache_keys` once the import's transaction commits."""
    cache_helpers.drop_on_commit(
        *release_cache_keys(), generation_key=GENERATION_RELEASE
    )

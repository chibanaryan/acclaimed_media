"""
Percentile calculation service for user statistics.

Calculates where a user's played game count ranks relative to other users.
"""

from django.core.cache import cache
from django.db.models import Count, Q

from core.models import User
from core.services import percentile
from games import config

RANK_WORDING = percentile.RankWording(
    item="games",
    people="players",
    more_than="You've played more games than {percent}% of players",
)


def get_played_games_distribution():
    """
    Get cached distribution of played game counts across users.

    Returns a sorted list of (user_id, played_count) tuples for users
    with at least 1 non-orphaned played game.

    Cached for 1 hour.
    """
    cache_key = "user_played_games_distribution"
    distribution = cache.get(cache_key)

    if distribution is None:
        # Aggregate played game counts per user (non-orphaned only)
        distribution = list(
            User.objects.annotate(
                played_count=Count(
                    "played_games", filter=Q(played_games__game__isnull=False)
                )
            )
            .filter(played_count__gt=0)
            .values_list("id", "played_count")
            .order_by("played_count")
        )
        cache.set(cache_key, distribution, config.CACHE_TIMEOUT_1_HOUR)

    return distribution


def calculate_percentile(user_played_count: int) -> dict:
    """
    Calculate the percentile ranking for a user's played count.

    Args:
        user_played_count: Number of non-orphaned games the user has played

    Returns:
        The dict `core.services.percentile.calculate_percentile` describes.
    """
    return percentile.calculate_percentile(
        user_played_count, get_played_games_distribution, RANK_WORDING
    )

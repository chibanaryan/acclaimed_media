"""
Percentile calculation service for user statistics.

Calculates where a user's played game count ranks relative to other users.
"""

from django.db.models import Count, Q

from core.cache_helpers import cached
from core.models import User
from core.services import percentile
from games import config
from games.cache import GENERATION_TRACKING

RANK_WORDING = percentile.RankWording(
    item="games",
    people="players",
    verb="played",
    prompt="Mark a game Played",
)


def get_played_counts():
    """
    Get the cached played game count of every user with at least 1
    non-orphaned played game.

    Cached for 1 hour.
    """
    # Aggregate played game counts per user (non-orphaned only)
    return cached(
        config.CACHE_KEY_PLAYED_COUNTS,
        lambda: list(
            User.objects.annotate(
                played_count=Count(
                    "played_games", filter=Q(played_games__game__isnull=False)
                )
            )
            .filter(played_count__gt=0)
            .order_by()
            .values_list("played_count", flat=True)
        ),
        config.CACHE_TIMEOUT_1_HOUR,
        GENERATION_TRACKING,
    )


def calculate_percentile(user_played_count: int) -> dict:
    """
    Calculate the percentile ranking for a user's played count.

    Args:
        user_played_count: Number of non-orphaned games the user has played

    Returns:
        The dict `core.services.percentile.calculate_percentile` describes.
    """
    return percentile.calculate_percentile(
        user_played_count, get_played_counts, RANK_WORDING
    )

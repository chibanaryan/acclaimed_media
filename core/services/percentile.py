"""Where a user's tracked count ranks among everyone else's.

Shared by the games and music sections of the Account modal. Each section
supplies its own distribution and wording, since it alone knows what is being
counted.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RankWording:
    """The words a section's rank line is built from."""

    item: str  # "games"
    people: str  # "players"
    more_than: str  # "You've played more games than {percent}% of players"


def calculate_percentile(
    count: int, get_distribution: Callable[[], list], wording: RankWording
) -> dict:
    """
    Calculate the percentile ranking for a user's tracked count.

    Args:
        count: The user's count, orphaned rows left out
        get_distribution: Returns (user_id, count) tuples for every user with
            at least one. A callable so that a count of 0 costs no query
        wording: The section's words

    Returns:
        dict with:
        - percentile: int (0-100) or None if not applicable
        - total_users: int - number of active users in comparison
        - message: str - formatted display message
    """
    start_tracking = f"Start tracking {wording.item} to see your rank!"
    if count == 0:
        return {"percentile": None, "total_users": 0, "message": start_tracking}

    distribution = get_distribution()
    total_users = len(distribution)

    if total_users == 0:
        return {"percentile": None, "total_users": 0, "message": start_tracking}

    if total_users == 1:
        return {
            "percentile": 100,
            "total_users": 1,
            "message": f"You're the first to start tracking {wording.item}!",
        }

    # Count users with FEWER tracked items and calculate rank
    users_with_fewer = sum(1 for _, other in distribution if other < count)
    # 1 = best. Counted from those ahead, so that a tie shares the better rank;
    # capped because a stale distribution can hold more ahead than it has users
    rank = min(1 + sum(1 for _, other in distribution if other > count), total_users)

    # For small populations, show rank instead of percentile
    if total_users < 10:
        if rank == 1:
            message = f"You're #1 of {total_users} {wording.people}!"
        else:
            message = f"You're #{rank} of {total_users} {wording.people}"
        return {
            "percentile": None,
            "total_users": total_users,
            "message": message,
        }

    # Calculate percentile for larger populations
    percentile = round((users_with_fewer / total_users) * 100)

    # Format message
    if percentile >= 99:
        message = f"You're in the top 1% of {wording.people}!"
    else:
        message = wording.more_than.format(percent=percentile)

    return {
        "percentile": percentile,
        "total_users": total_users,
        "message": message,
    }

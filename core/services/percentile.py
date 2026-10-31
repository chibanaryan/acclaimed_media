"""Where a user's tracked count ranks among everyone else's.

Shared by the games and music sections of the Account modal. Each section
supplies its own counts and wording, since it alone knows what is being
counted.
"""

from dataclasses import dataclass
from typing import Callable, List


@dataclass(frozen=True)
class RankWording:
    """The words a section's rank line is built from."""

    item: str  # "games"
    people: str  # "players"
    verb: str  # "played"
    prompt: str  # "Mark a game Played"


def calculate_percentile(
    count: int, get_counts: Callable[[], List[int]], wording: RankWording
) -> dict:
    """
    Calculate the percentile ranking for a user's tracked count.

    Args:
        count: The user's count, orphaned rows left out
        get_counts: Returns the count of every user with at least one, the
            user included. A callable so that a count of 0 costs no query
        wording: The section's words

    Returns:
        dict with:
        - percentile: int (0-100) or None if not applicable
        - total_users: int - number of active users in comparison
        - message: str - formatted display message
    """
    prompt = f"{wording.prompt} to see your rank!"
    if count == 0:
        return {"percentile": None, "total_users": 0, "message": prompt}

    counts = get_counts()
    total_users = len(counts)

    if total_users == 0:
        return {"percentile": None, "total_users": 0, "message": prompt}

    if total_users == 1:
        return {
            "percentile": 100,
            "total_users": 1,
            "message": f"You're the first to start tracking {wording.item}!",
        }

    users_with_fewer = sum(1 for other in counts if other < count)
    tied = sum(1 for other in counts if other == count) > 1
    # 1 = best. Counted from those ahead, so that a tie shares the better rank;
    # capped because stale counts can hold more ahead than they have users
    rank = min(1 + sum(1 for other in counts if other > count), total_users)

    # Small populations show a position. Compared with everyone else, not
    # everyone: the reader cannot beat themselves, so a leader of 20 would
    # otherwise have "more than 95%". Capped for the same stale counts, and
    # below 100 for anyone with someone ahead of them
    percentile = None
    if total_users >= 10:
        share = users_with_fewer / (total_users - 1)
        percentile = min(round(share * 100), 100 if rank == 1 else 99)

    position = f"#{rank} of {total_users} {wording.people}"
    if tied:
        position = f"tied for {position}"

    # From those level with or ahead of the reader, not from `rank`, where a
    # tie shares the better position: 30 tied at the top of 150 are not the
    # top 1%. `not percentile` is None or 0, which can round down from above
    if rank == 1:
        message = f"You're {position}!"
    elif total_users - users_with_fewer <= total_users / 100:
        message = f"You're in the top 1% of {wording.people}!"
    elif not percentile:
        message = f"You're {position}"
    else:
        message = (
            f"You've {wording.verb} more {wording.item} than "
            f"{percentile}% of {wording.people}"
        )

    return {
        "percentile": percentile,
        "total_users": total_users,
        "message": message,
    }

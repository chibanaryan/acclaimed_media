"""
Ranking service for Acclaimed Games.

Handles year and decade ranking calculations for games. The implementation
lives in ``core.services.ranking`` so every media type shares it; this module
binds it to the Game model and keeps the historical import path
(``games.utils.update_year_decade_ranks``) working.
"""

from typing import Tuple

from core.services.ranking import year_to_decade  # noqa: F401
from core.services.ranking import update_year_decade_ranks as _update_ranks
from games import models


def update_year_decade_ranks() -> Tuple[int, int]:
    """
    Bulk update year_rank and decade_rank for all games.
    Should be called after importing/updating game rankings.

    Returns:
        Tuple of (games_updated, years_processed)
    """
    return _update_ranks(models.Game, "games_game", "year_of_release")

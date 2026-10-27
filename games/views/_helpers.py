"""Small helpers the games views share: cached lookups and cache keys."""

import hashlib
import json

from django.core.cache import cache

from core.cache_helpers import get_year_bounds
from games import config, models
from games.services.game_filters import facet_params


def _get_year_bounds():
    """Return cached global min/max release years."""
    return get_year_bounds(
        model_class=models.Game,
        year_field="year_of_release",
        cache_key=config.CACHE_KEY_YEAR_STATS,
        cache_timeout=config.CACHE_TIMEOUT_24_HOURS,
        default_min=config.DEFAULT_MIN_YEAR,
    )


def _get_hero_stats():
    """Return cached hero section statistics (list, publication, game counts)."""
    cache_key = "homepage_hero_stats"
    stats = cache.get(cache_key)
    if stats is None:
        stats = {
            "list_count": models.List.objects.count(),
            "publication_count": models.Publication.objects.count(),
            "game_count": models.Game.objects.count(),
        }
        cache.set(cache_key, stats, config.CACHE_TIMEOUT_24_HOURS)
    return stats


def _facet_cache_key(prefix, params, skip=None, user_id=None, extra=None):
    """A cache key from the page's filter parameters, but ``skip``'s.

    Keyed on the raw parameters, so a playtime preset counts: the older key
    built from the derived filters dict left `hltb_preset` out, and every
    preset shared one rank-distribution chart. ``extra`` adds what a value
    depends on beyond the filters (the chart: the sort).
    """
    payload = facet_params(params, (skip,) if skip else ())
    payload.update(extra or {})
    if user_id is not None:
        payload["user"] = user_id
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"{prefix}:{config.CACHE_VERSION}:{digest}"


def _genre_ids_with_games_or_descendant_games(genres):
    """Return genre IDs that have games plus every ancestor ID."""
    by_id = {genre["id"]: genre for genre in genres}
    visible_ids = set()

    for genre in genres:
        if genre["game_count"] <= 0:
            continue

        current = genre
        while current and current["id"] not in visible_ids:
            visible_ids.add(current["id"])
            parent_id = current["parent_id"]
            current = by_id.get(parent_id) if parent_id else None

    return visible_ids


def _get_played_game_ids(user):
    """Return cached list of played game IGDB IDs for a user."""
    cache_key = f"played_games_{user.id}"
    ids = cache.get(cache_key)
    if ids is None:
        ids = list(
            models.PlayedGame.objects.filter(user=user).values_list(
                "igdb_id", flat=True
            )
        )
        cache.set(cache_key, ids, 300)  # 5 minutes
    return ids


def _get_want_to_play_game_ids(user):
    """Return cached list of want-to-play game IGDB IDs for a user."""
    cache_key = f"want_to_play_games_{user.id}"
    ids = cache.get(cache_key)
    if ids is None:
        ids = list(
            models.WantToPlayGame.objects.filter(user=user).values_list(
                "igdb_id", flat=True
            )
        )
        cache.set(cache_key, ids, 300)  # 5 minutes
    return ids

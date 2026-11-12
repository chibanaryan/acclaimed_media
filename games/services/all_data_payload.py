"""What `/api/games/all/` serves: every game, for client-side filtering.

Compressed field names, the reference data (developers, platforms, genres,
series) keyed by id, and each genre's descendants for hierarchical
filtering::

    {
        "version": "abc123def456",
        "data": {
            "games": [{id, n, s, r, y, a, dv, p, g, sr, lc}, ...],
            "developers": {id: {n, pa, s}, ...},
            "platforms": {id: {n, c, ys, ye}, ...},
            "genres": [{id, n, s, p, l, d}, ...],
            "series": {id: {n, s}, ...}
        }
    }

Here and not on the view because two things build it: the view, and the
weekly refresh's fingerprint (``post_import.payload_fingerprint``), which
reached into the view for it until 2026-11-12.
"""

from collections import defaultdict

from django.db.models import Count
from django.db.models.functions import Lower

from core.services.genre_tree import descendants_by_id
from games import models


def build(version):
    """The payload, labelled with ``version``: every game, and what they name."""
    # Fetch base game rows with scalar fields only (no model instantiation)
    game_rows = list(
        models.Game.objects.values(
            "id",
            "igdb_id",
            "name",
            "slug",
            "rank",
            "year_of_release",
            "primary_igdb_game_data__artwork_id",
            "primary_hltb_game_data__main_story_hours",
            "primary_hltb_game_data__completionist_hours",
            "primary_hltb_game_data__is_open_ended",
        )
        .annotate(list_count=Count("lists", distinct=True))
        .order_by("rank")
    )
    game_ids = [row["id"] for row in game_rows]

    # Group related IDs via through tables (ordered for deterministic output)
    game_developer_ids = defaultdict(list)
    used_developer_ids = set()
    if game_ids:
        for game_id, developer_id in (
            models.Game.developers.through.objects.filter(game_id__in=game_ids)
            .order_by("game_id", "developer__name", "developer_id")
            .values_list("game_id", "developer_id")
        ):
            game_developer_ids[game_id].append(developer_id)
            used_developer_ids.add(developer_id)

    game_platform_ids = defaultdict(list)
    used_platform_ids = set()
    if game_ids:
        for game_id, platform_id in (
            models.Game.platforms.through.objects.filter(game_id__in=game_ids)
            .order_by("game_id", "platform__name", "platform_id")
            .values_list("game_id", "platform_id")
        ):
            game_platform_ids[game_id].append(platform_id)
            used_platform_ids.add(platform_id)

    game_genre_ids = defaultdict(list)
    if game_ids:
        genre_links = models.Game.wikipedia_genres.through.objects.filter(
            game_id__in=game_ids
        ).order_by(
            "game_id",
            "wikipediagenre__level",
            "wikipediagenre__display_order",
            "wikipediagenre__name",
            "wikipediagenre_id",
        )
        for game_id, genre_id in genre_links.values_list(
            "game_id", "wikipediagenre_id"
        ):
            game_genre_ids[game_id].append(genre_id)

    game_series_ids = defaultdict(list)
    used_series_ids = set()
    if game_ids:
        for game_id, series_id in (
            models.Game.series.through.objects.filter(game_id__in=game_ids)
            .order_by("game_id", "series__name", "series_id")
            .values_list("game_id", "series_id")
        ):
            game_series_ids[game_id].append(series_id)
            used_series_ids.add(series_id)

    # Developers: fetch only game-linked developers + their immediate parents.
    developer_rows = {}
    pending_ids = set(used_developer_ids)
    while pending_ids:
        fetched_rows = list(
            models.Developer.objects.filter(id__in=pending_ids).values(
                "id", "name", "parent_id", "slug"
            )
        )
        for row in fetched_rows:
            developer_rows[row["id"]] = row
        pending_ids = {
            row["parent_id"]
            for row in fetched_rows
            if row["parent_id"] and row["parent_id"] not in developer_rows
        }

    direct_parent_ids = {
        developer_rows[dev_id]["parent_id"]
        for dev_id in used_developer_ids
        if dev_id in developer_rows and developer_rows[dev_id]["parent_id"]
    }
    response_developer_ids = used_developer_ids | direct_parent_ids

    def _resolve_root_slug(dev_id):
        current_id = dev_id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            current = developer_rows.get(current_id)
            if not current:
                break
            if not current["parent_id"]:
                return current["slug"]
            current_id = current["parent_id"]
        current = developer_rows.get(dev_id)
        return current["slug"] if current else None

    developers_dict = {}
    for dev_id in sorted(
        response_developer_ids,
        key=lambda pk: developer_rows.get(pk, {}).get("name", ""),
    ):
        row = developer_rows.get(dev_id)
        if not row:
            continue
        developers_dict[dev_id] = {
            "n": row["name"],
            "pa": row["parent_id"],
            "s": _resolve_root_slug(dev_id),
        }

    platform_rows = models.Platform.objects.filter(id__in=used_platform_ids).values(
        "id", "name", "code", "year_start", "year_end"
    )
    platforms_dict = {
        row["id"]: {
            "n": row["name"],
            "c": row["code"],
            "ys": row["year_start"],
            "ye": row["year_end"],
        }
        for row in platform_rows
    }

    series_rows = models.Series.objects.filter(id__in=used_series_ids).values(
        "id", "name", "slug"
    )
    series_dict = {
        row["id"]: {
            "n": row["name"],
            "s": row["slug"],
        }
        for row in series_rows
    }

    # Build all genres and descendants from one in-memory hierarchy map.
    genre_rows = list(
        models.WikipediaGenre.objects.values(
            "id", "name", "slug", "parent_id", "level", "display_order"
        ).order_by("level", "display_order", "name")
    )
    descendant_ids_by_genre_id = descendants_by_id(
        (row["id"], row["parent_id"]) for row in genre_rows
    )

    genres_data = [
        {
            "id": row["id"],
            "n": row["name"],
            "s": row["slug"],
            "p": row["parent_id"],
            "l": row["level"],
            "d": descendant_ids_by_genre_id[row["id"]],
        }
        for row in genre_rows
    ]

    # `ni` is each game's position in the server's own name order, which
    # the client sorts by rather than comparing names itself: no
    # JavaScript comparator reproduces a database collation (SQLite
    # files "DOOM 64" before "Doom"; Postgres does not), as
    # music's payload found first. Ties go to rank, as `_order_games`.
    name_order = {
        game_id: position
        for position, game_id in enumerate(
            models.Game.objects.order_by(Lower("name"), "rank").values_list(
                "id", flat=True
            )
        )
    }

    # Assemble games preserving existing compressed keys/semantics.
    games_data = []
    for row in game_rows:
        playtime = row["primary_hltb_game_data__main_story_hours"]
        completionist = row["primary_hltb_game_data__completionist_hours"]
        if row["primary_hltb_game_data__is_open_ended"]:
            # No finish line, so no time to beat (games.services.playtime)
            playtime = completionist = None
        games_data.append(
            {
                "id": row["id"],
                "i": row["igdb_id"],  # IGDB ID for played game tracking
                "n": row["name"],
                "s": row["slug"],
                "r": row["rank"],
                "y": row["year_of_release"],
                "a": row["primary_igdb_game_data__artwork_id"],
                "dv": game_developer_ids.get(row["id"], []),
                "p": game_platform_ids.get(row["id"], []),
                "g": game_genre_ids.get(row["id"], []),
                "sr": game_series_ids.get(row["id"], []),
                "lc": row["list_count"],  # List count for display
                # A game deleted between the two queries sorts last
                # rather than failing the whole payload
                "ni": name_order.get(row["id"], len(name_order)),
                "pt": float(playtime) if playtime is not None else None,
                "ptc": (float(completionist) if completionist is not None else None),
            }
        )

    return {
        "version": version,
        "data": {
            "games": games_data,
            "developers": developers_dict,
            "platforms": platforms_dict,
            "genres": genres_data,
            "series": series_dict,
        },
    }

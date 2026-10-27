"""The rankings page as a CSV file, with the page's own filters and sort."""

import csv

from django.db.models import Count
from django.http import HttpResponse
from django.utils.text import slugify

from core.services.query_params import parse_id_list
from games import config, models, utils
from games.services import playtime
from games.services.game_filters import (
    apply_game_filters,
    expand_platform_virtual_ids,
    platforms_lookup,
    playtime_range,
)

from ._helpers import _get_year_bounds
from .filter_titles import _build_filter_title
from .rankings import _order_games


def download_games_csv(request):
    """Download games list as CSV, respecting current filters."""
    # Get filtered queryset using same logic as HomePageView
    # with_relations() already includes all needed prefetches:
    # developers, platforms, genres, and series.
    qs = models.Game.objects.with_relations()

    # Add played status annotation for authenticated users
    user = request.user
    is_authenticated = user.is_authenticated
    if is_authenticated:
        qs = qs.with_played_status(user)

    q = request.GET.get("q")
    decade = request.GET.get("decade")
    year = request.GET.get("year")
    start = request.GET.get("start")
    end = request.GET.get("end")
    genres_param = request.GET.get("genres")
    platforms_param = request.GET.get("platforms")
    series_param = request.GET.get("series")
    played_param = request.GET.get("played")

    hltb_mode = request.GET.get("hltb_mode", "main")
    hltb_preset = request.GET.get("hltb_preset", "")
    # The typed range, before a preset overrides it, for the heading
    hltb_min, hltb_max = playtime_range(request.GET, ignore_preset=True)

    platforms_lookup_list = platforms_lookup()
    genre_ids = parse_id_list(genres_param)
    platform_ids = (
        expand_platform_virtual_ids(platforms_param, platforms_lookup_list)
        if platforms_param
        else []
    )

    # The page's own filters and sort, so the file is what was on screen
    qs = apply_game_filters(qs, request.GET, user=user, platforms=platforms_lookup_list)
    qs = _order_games(qs, request.GET)

    use_filtered_rank = True

    # Build filename based on filters
    min_year, max_year = _get_year_bounds()
    genres_lookup = utils.get_or_set_cache(
        f"search_genres_list_with_counts:{config.CACHE_VERSION}",
        models.WikipediaGenre.objects.annotate(
            game_count=Count("games_with_wikipedia_genre")
        ),
        ["id", "name", "game_count"],
        order_by="name",
        transform_id=True,
    )
    # platforms_lookup_list already loaded above for virtual ID expansion

    # Get series list for title building (if series filter is used)
    series_list = None
    if series_param:
        series_ids_for_title = parse_id_list(series_param)
        series_list = list(
            models.Series.objects.filter(id__in=series_ids_for_title).values(
                "id", "name"
            )
        )
        # Convert IDs to strings for lookup
        for s in series_list:
            s["id"] = str(s["id"])

    def _safe_int(val, default):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def _decade_bounds(decade_str):
        import re

        pattern = re.compile(r"(\d{2})(\d{2})-(\d{2})")
        match = pattern.match(decade_str) if decade_str else None
        if not match:
            return None, None
        start_str = match.group(1) + match.group(2)
        end_str = match.group(1) + match.group(3)
        return _safe_int(start_str, None), _safe_int(end_str, None)

    start_for_title = _safe_int(start, None)
    end_for_title = _safe_int(end, None)
    if decade:
        d_start, d_end = _decade_bounds(decade)
        start_for_title = d_start
        end_for_title = d_end
    elif year:
        y_val = _safe_int(year, None)
        start_for_title = y_val
        end_for_title = y_val
    if start_for_title is None:
        start_for_title = min_year
    if end_for_title is None:
        end_for_title = max_year

    # Get series IDs for title (if series filter is used)
    series_ids_for_filter = []
    if series_param:
        series_ids_for_filter = [str(x) for x in series_param.split(",") if x.strip()]

    # HLTB parameters already parsed at top of function

    filters_for_title = {
        "q": q or "",
        "start": start_for_title,
        "end": end_for_title,
        "genres": [str(gid) for gid in genre_ids],
        "platforms": [str(pid) for pid in platform_ids],
        "series": series_ids_for_filter,
        "played": (
            [s.strip() for s in played_param.split(",") if s.strip()]
            if played_param
            else []
        ),
        "rank_display": "filtered",
        "hltb_mode": hltb_mode,
        "hltb_preset": hltb_preset,
        "hltb_min": hltb_min,
        "hltb_max": hltb_max,
    }
    filter_title = _build_filter_title(
        filters_for_title,
        genres_lookup,
        platforms_lookup_list,
        min_year,
        max_year,
        series_list=series_list,
    )
    # Use the page title directly as the filename (slugified)
    filename_base = slugify(filter_title) or "acclaimed-games"
    filename = f"{filename_base}.csv"

    # Create CSV response
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    # Build header row - include Played column for authenticated users
    header = [
        "Filtered Rank",
        "Global Rank",
        "Name",
        "Year",
        "Developers",
        "Platforms",
        "Genres",
        "Series",
        "HLTB Main (hours)",
        "HLTB Main+Extra (hours)",
        "HLTB 100% (hours)",
    ]
    if is_authenticated:
        header.append("Played")
    writer.writerow(header)

    for index, game in enumerate(qs, start=1):
        developers = ", ".join(d.name for d in game.developers.all())
        platforms = ", ".join(p.name for p in game.platforms.all())
        genres = ", ".join(g.name for g in game.wikipedia_genres.all())
        series = ", ".join(s.name for s in game.series.all())
        filtered_rank = index if use_filtered_rank else game.rank

        # Get HLTB data
        hltb_main = ""
        hltb_main_extra = ""
        hltb_completionist = ""
        # An open-ended game's hours are not a time to beat
        if playtime.shown_record(game.primary_hltb_game_data):
            if game.primary_hltb_game_data.main_story_hours:
                hltb_main = f"{game.primary_hltb_game_data.main_story_hours:.1f}"
            if game.primary_hltb_game_data.main_extra_hours:
                hltb_main_extra = f"{game.primary_hltb_game_data.main_extra_hours:.1f}"
            if game.primary_hltb_game_data.completionist_hours:
                hltb_completionist = (
                    f"{game.primary_hltb_game_data.completionist_hours:.1f}"
                )

        row = [
            filtered_rank,
            game.rank,
            game.name,
            game.year_of_release,
            developers,
            platforms,
            genres,
            series,
            hltb_main,
            hltb_main_extra,
            hltb_completionist,
        ]
        if is_authenticated:
            # Use the annotated is_played_by_user field
            played = "Yes" if getattr(game, "is_played_by_user", False) else "No"
            row.append(played)
        writer.writerow(row)

    return response

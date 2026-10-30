"""The games rankings page's filters, applied one way everywhere.

The list, the three facet counts beside the year grid, the genre tree and
the platform tree, and the CSV download each built the filters themselves
until 2026-10-26, and the five copies had drifted: the counts and the CSV
matched the search against ``name`` only, so "pokemon" listed the Pokémon
games while the counts and the download left them out; the counts never
applied the series or playtime filters, which the client engine's counts
always had; the CSV ignored the sort. ``apply_game_filters`` is the one
rule, as ``music.views.apply_album_filters`` is for albums.
"""

from django.db.models import Q

from core.services.query_params import parse_id_list, parse_int
from games import config, models, utils
from games.services import playtime

# Every dimension, and the query parameters that set it. A facet count
# leaves its own dimension out (``skip``) and is cached on the others.
DIMENSIONS = {
    "q": ("q",),
    "year": ("decade", "year", "start", "end"),
    "genres": ("genres",),
    "platforms": ("platforms",),
    "series": ("series",),
    "played": ("played",),
    "playtime": (
        "hltb_mode",
        "hltb_preset",
        "pt_min",
        "pt_max",
        "hltb_min",
        "hltb_max",
    ),
}

PLAYTIME_PRESETS = {
    "short": (0, 10),  # Under 10 hours
    "medium": (10, 30),  # 10-30 hours
    "long": (30, None),  # 30+ hours (no upper bound)
}


def playtime_range(params, *, ignore_preset=False):
    """The playtime filter's ``(min, max)`` hours, either None when unset.

    ``pt_min``/``pt_max`` are the current names and ``hltb_min``/
    ``hltb_max`` the older ones; ``hltb_preset`` overrides both. A max alone
    starts at 0, a max below the min is raised to it, and a negative value
    counts as 0. ``ignore_preset`` gives the typed range alone, which the
    headings show beside the preset.
    """
    pt_min = parse_int(params.get("pt_min") or params.get("hltb_min"))
    max_raw = params.get("pt_max") or params.get("hltb_max")
    pt_max = None if max_raw == "unlimited" else parse_int(max_raw)
    pt_min = None if pt_min is None else max(0, pt_min)
    pt_max = None if pt_max is None else max(0, pt_max)

    preset = None if ignore_preset else params.get("hltb_preset")
    if preset in PLAYTIME_PRESETS:
        pt_min, pt_max = PLAYTIME_PRESETS[preset]

    if pt_max is not None and pt_min is None:
        pt_min = 0
    if pt_min is not None and pt_max is not None and pt_max < pt_min:
        pt_max = pt_min
    return pt_min, pt_max


PLATFORMS_CACHE_KEY = f"search_platforms_list:{config.CACHE_VERSION}"


def platforms_lookup():
    """The platform list virtual ids expand against, cached."""
    return utils.get_or_set_cache(
        PLATFORMS_CACHE_KEY,
        models.Platform.objects.all(),
        ["id", "name", "code", "year_start", "year_end"],
        order_by="name",
        transform_id=True,
    )


def wants_played_filter(params, user):
    """Whether the played dimension applies, which needs its annotation."""
    return bool(params.get("played") and user and user.is_authenticated)


def apply_game_filters(
    queryset, params, *, skip=(), user=None, descendants=None, platforms=None
):
    """Apply the rankings page's filters in ``params`` to ``queryset``.

    ``skip`` leaves dimensions out (see ``DIMENSIONS``): a facet count is how
    many games each option has under the *other* filters. ``user`` is needed
    for the played dimension, which also adds its annotation when the
    queryset lacks it. ``descendants`` (the genre descendant map) and
    ``platforms`` (``platforms_lookup()``) can be passed in by a caller that
    filters several times per request; left out, they are built here.
    """
    q = params.get("q")
    if q and "q" not in skip:
        # Accent-insensitive: name_normalized is unidecode(name)
        queryset = queryset.filter(
            Q(name__icontains=q) | Q(name_normalized__icontains=q)
        )

    if "year" not in skip:
        queryset = utils.apply_year_filters(
            queryset,
            decade=params.get("decade"),
            year=params.get("year"),
            start=params.get("start"),
            end=params.get("end"),
        )

    genre_ids = parse_id_list(params.get("genres"))
    if genre_ids and "genres" not in skip:
        # Single-select, so match_all does not matter
        queryset = utils.apply_genre_filter(
            queryset,
            genre_ids,
            match_all=False,
            use_wikipedia=True,
            descendants=descendants,
        )

    platforms_param = params.get("platforms")
    if platforms_param and "platforms" not in skip:
        platform_ids = expand_platform_virtual_ids(
            platforms_param, platforms if platforms is not None else platforms_lookup()
        )
        queryset = utils.apply_platform_filter(queryset, platform_ids)

    series_ids = parse_id_list(params.get("series"))
    if series_ids and "series" not in skip:
        queryset = utils.apply_series_filter(queryset, series_ids)

    if "played" not in skip and wants_played_filter(params, user):
        if "is_played_by_user" not in queryset.query.annotations:
            queryset = queryset.with_played_status(user)
        queryset = apply_played_filter(queryset, user, params.get("played"))

    if "playtime" not in skip:
        pt_min, pt_max = playtime_range(params)
        if pt_min is not None or pt_max is not None:
            # Open-ended games have no time to beat, so the filter leaves
            # them out; values are compared unrounded
            field = playtime.hours_field(params.get("hltb_mode", "main"))
            queryset = queryset.filter(playtime.shown_q()).exclude(**{field: None})
            if pt_min is not None:
                queryset = queryset.filter(**{f"{field}__gte": pt_min})
            if pt_max is not None:
                queryset = queryset.filter(**{f"{field}__lte": pt_max})

    return queryset


# Comma lists whose order does not matter, so `genres=3,7` and `genres=7,3`
# share one cache entry
UNORDERED_LISTS = {"genres", "platforms", "series", "played"}


def facet_params(params, skip):
    """The parameters a facet count depends on, for its cache key."""
    out = {}
    for dimension, names in DIMENSIONS.items():
        if dimension in skip:
            continue
        for name in names:
            value = params.get(name)
            if not value:
                continue
            if name in UNORDERED_LISTS:
                value = ",".join(
                    sorted(p.strip() for p in value.split(",") if p.strip())
                )
            out[name] = value
    return out


# Platform hierarchy - maps virtual IDs to platform codes. The sidebar's copy is
# filter-subcomponents.js SHARED_PLATFORM_HIERARCHY_UI, with client-filter.js's
# fallback; games/tests/test_visual_regression.py holds all three equal.
PLATFORM_VIRTUAL_IDS = {
    # Manufacturer virtual IDs
    "mfr-nintendo": [
        "NES",
        "FDS",
        "SNES",
        "N64",
        "GC",
        "Wii",
        "WiiU",
        "SW",
        "SW2",
        "GB",
        "GBC",
        "GBA",
        "DS",
        "3DS",
        "GW",
    ],
    "mfr-playstation": ["PS", "PS2", "PS3", "PS4", "PS5", "PSVR", "PSP", "PSV"],
    "mfr-xbox": ["Xbox", "X360", "XB1", "XBXS"],
    "mfr-sega": ["SMS", "GEN", "SCD", "SAT", "DC", "GG"],
    "mfr-pc": ["WIN", "DOS", "LIN", "MAC"],
    "mfr-arcadePlus": ["ARC", "AND", "iOS", "LMD", "VR", "BR"],
    "mfr-retro": [
        "A26",
        "A52",
        "A78",
        "INTV",
        "CV",
        "TG16",
        "3DO",
        "NG",
        "JAG",
        "LYNX",
        "NGP",
        "VECT",
        "WS",
    ],
    "mfr-computers": [
        "VC20",
        "C64",
        "AMI",
        "CD32",
        "D32",
        "MIC",
        "ZXS",
        "CPC",
        "BBCM",
        "ARCH",
        "PC88",
        "PC98",
        "FM7",
        "FMT",
        "SX1",
        "MSX",
        "A8",
        "AST",
        "A2",
        "TT",
        "T80",
        "TCC",
        "PDP",
        "HP21",
        "E60",
    ],
    # Form factor virtual IDs
    "ff-nintendo-home": [
        "NES",
        "FDS",
        "SNES",
        "N64",
        "GC",
        "Wii",
        "WiiU",
        "SW",
        "SW2",
    ],
    "ff-nintendo-handheld": ["GW", "GB", "GBC", "GBA", "DS", "3DS"],
    "ff-playstation-home": ["PS", "PS2", "PS3", "PS4", "PS5", "PSVR"],
    "ff-playstation-handheld": ["PSP", "PSV"],
    "ff-sega-home": ["SMS", "GEN", "SCD", "SAT", "DC"],
    "ff-sega-handheld": ["GG"],
    # Microcomputer form factor virtual IDs
    "ff-computers-commodore": ["VC20", "C64", "AMI", "CD32"],
    "ff-computers-uk": ["ZXS", "CPC", "BBCM", "ARCH", "D32"],
    "ff-computers-japan": ["PC88", "PC98", "FM7", "FMT", "SX1", "MSX", "TT"],
    "ff-computers-atari": ["A8", "AST"],
    "ff-computers-other": ["A2", "T80", "TCC", "PDP", "HP21", "E60", "MIC"],
}


def expand_platform_virtual_ids(platforms_param, platforms):
    """Expand virtual IDs (mfr-nintendo, ff-nintendo-home) to actual platform IDs.

    Returns a list of platform IDs (integers) that should be used for filtering.
    If the param contains regular IDs, returns those directly.
    Using - instead of : for URL-friendliness.
    """
    if not platforms_param:
        return []

    # Build code -> ID lookup from platforms list (ensure int IDs)
    code_to_id = {p.get("code"): int(p["id"]) for p in platforms if p.get("code")}

    platform_ids = []
    for param in platforms_param.split(","):
        param = param.strip()
        if param in PLATFORM_VIRTUAL_IDS:
            # Virtual ID - expand to all platform codes
            codes = PLATFORM_VIRTUAL_IDS[param]
            for code in codes:
                if code in code_to_id:
                    platform_ids.append(code_to_id[code])
        else:
            # Regular ID; anything else is skipped
            platform_ids.extend(parse_id_list(param))

    return platform_ids


def apply_played_filter(qs, user, played_param):
    """Apply played status filter. Requires qs to have is_played_by_user annotation.

    Supports multi-select via comma-separated values (e.g., "no,want" shows both
    untracked and want-to-play games).
    """
    if not played_param or not user or not user.is_authenticated:
        return qs

    # Parse comma-separated values for multi-select support
    statuses = [s.strip() for s in played_param.split(",") if s.strip()]
    if not statuses:
        return qs

    # Build Q objects for each selected status
    q_filter = Q()
    for status in statuses:
        if status == "yes":
            q_filter |= Q(is_played_by_user=True)
        elif status == "want":
            q_filter |= Q(is_want_to_play_by_user=True)
        elif status == "no":
            q_filter |= Q(is_played_by_user=False, is_want_to_play_by_user=False)

    # Only apply filter if we have valid statuses
    if q_filter:
        return qs.filter(q_filter)
    return qs

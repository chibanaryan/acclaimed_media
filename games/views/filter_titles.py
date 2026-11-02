"""The rankings heading's wording, composed from the filter state."""

from core.services import titles
from games import config

# Both heading helpers now live in core, so the album rankings page composes
# its heading the same way this one does.
_join_names = titles.join_names


_join_names = titles.join_names
_build_time_window = titles.build_time_window


# Platform groups the heading names whole, as utils-base.js PLATFORM_GROUPS does
# on the client (games/tests/test_visual_regression.py holds the two equal).
# Groups are checked in order - broader manufacturer groups first, then form factors
# This ensures "Nintendo" is used when all Nintendo platforms are selected,
# but "Nintendo Handheld" when only handhelds are selected
PLATFORM_TITLE_GROUPS = [
    # Big manufacturer groups (checked first to collapse when all are selected)
    (
        "Nintendo",
        [
            "NES",
            "SNES",
            "N64",
            "GC",
            "Wii",
            "WiiU",
            "DS",
            "3DS",
            "SW",
            "SW2",
            "GB",
            "GBA",
            "GBC",
            "FDS",
            "GW",
        ],
    ),
    ("PlayStation", ["PS", "PS2", "PS3", "PS4", "PS5", "PSP", "PSV", "PSVR"]),
    ("Sega", ["GEN", "SMS", "DC", "SAT", "GG", "SCD"]),
    # Other manufacturer groups
    ("Xbox", ["Xbox", "X360", "XB1", "XBXS"]),
    ("PC", ["WIN", "DOS", "LIN", "MAC"]),
    ("Arcade, Mobile & VR", ["ARC", "AND", "iOS", "LMD", "VR", "BR"]),
    (
        "Retro Consoles",
        [
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
    ),
    (
        "Microcomputer",
        [
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
    ),
    # Form factor groups (checked after manufacturer groups)
    ("Nintendo Handheld", ["GW", "GB", "GBC", "GBA", "DS", "3DS"]),
    (
        "Nintendo Home Console",
        ["NES", "FDS", "SNES", "N64", "GC", "Wii", "WiiU", "SW", "SW2"],
    ),
    ("PlayStation Handheld", ["PSP", "PSV"]),
    ("PlayStation Home Console", ["PS", "PS2", "PS3", "PS4", "PS5", "PSVR"]),
    ("Sega Handheld", ["GG"]),
    ("Sega Home Console", ["SMS", "GEN", "SCD", "SAT", "DC"]),
    # Microcomputer form factor groups
    ("Commodore", ["VC20", "C64", "AMI", "CD32"]),
    ("UK Microcomputer", ["ZXS", "CPC", "BBCM", "ARCH", "D32"]),
    ("Japanese Microcomputer", ["PC88", "PC98", "FM7", "FMT", "SX1", "MSX", "TT"]),
    ("Atari Microcomputer", ["A8", "AST"]),
]


def _build_platform_segment(selected_platform_ids, platforms, include_games=True):
    """Return platform segment text like 'Nintendo Switch Games'."""
    name_lookup = {str(p["id"]): p["name"] for p in platforms}
    code_lookup = {str(p["id"]): p.get("code") for p in platforms}

    selected_ids = {str(pid) for pid in selected_platform_ids}
    labels = []
    consumed_ids = set()

    # Add group labels when entire group is selected (checking more specific first)
    for group_name, codes in PLATFORM_TITLE_GROUPS:
        group_ids = [pid for pid, code in code_lookup.items() if code in codes]
        # Only match if ALL platforms in group are selected, none consumed
        unconsumed_group_ids = [gid for gid in group_ids if gid not in consumed_ids]
        if unconsumed_group_ids and all(
            gid in selected_ids for gid in unconsumed_group_ids
        ):
            # Check if this exact set matches (not a subset)
            if set(unconsumed_group_ids) == set(group_ids):
                labels.append(group_name)
                consumed_ids.update(group_ids)

    # Add remaining platform names
    for pid in selected_ids - consumed_ids:
        labels.append(name_lookup.get(pid, pid))

    if not labels:
        return "Video" + (" Games" if include_games else "")
    return f"{_join_names(labels)}" + (" Games" if include_games else "")


def _build_genre_subtitle(selected_genre_ids, option, genres):
    """Return subtitle string with AND/OR connector for genres."""
    if not selected_genre_ids:
        return ""
    name_lookup = {str(g["id"]): g["name"] for g in genres}
    genre_names = [name_lookup.get(str(gid), str(gid)) for gid in selected_genre_ids]
    genre_names = [name for name in genre_names if name]
    if not genre_names:
        return ""
    connector = " AND " if option == "all" else " OR "
    return f"Genre: {connector.join(genre_names)}"


def _playtime_label(filters):
    """The playtime range as the heading names it ("Short (<10 Hour)"), or ""."""
    hltb_mode = filters.get("hltb_mode", "main")
    hltb_min = filters.get("hltb_min")
    hltb_max = filters.get("hltb_max")
    if hltb_min is None and hltb_max is None:
        return ""

    mode_suffix = " (100%)" if hltb_mode == "completionist" else ""
    time_desc = ""

    # Recognize preset patterns from min/max values
    # Short: 0-10, Medium: 10-30, Long: 30+
    if hltb_min == 0 and hltb_max == 10:
        time_desc = "Short (<10 Hour)"
    elif hltb_min == 10 and hltb_max == 30:
        time_desc = "Medium (10-30 Hour)"
    elif hltb_min == 30 and hltb_max is None:
        time_desc = "Long (30+ Hour)"
    # Custom ranges
    elif hltb_min == 0 and hltb_max is not None:
        time_desc = f"<{int(hltb_max)} Hour"
    elif hltb_min is not None and hltb_max is not None:
        if hltb_min == hltb_max:
            time_desc = f"~{int(hltb_min)} Hour"
        else:
            time_desc = f"{int(hltb_min)}-{int(hltb_max)} Hour"
    elif hltb_min is not None:
        time_desc = f"{int(hltb_min)}+ Hour"
    elif hltb_max is not None:
        time_desc = f"<{int(hltb_max)} Hour"

    return f"{time_desc}{mode_suffix}" if time_desc else ""


# The played filter's values in the order the heading names them, as
# filter-component.js `_playedLabel` does; their titles are the options'
PLAYED_TITLE_ORDER = ("yes", "want", "no")


def _played_label(played):
    """The played filter's statuses ("Played + Want to Play"), or ""."""
    if isinstance(played, str):
        played = played.split(",")
    chosen = set(played or [])
    titles_by_value = {
        option["value"]: option["title"] for option in config.GAME_STATUS_OPTIONS
    }
    return " + ".join(
        titles_by_value[value] for value in PLAYED_TITLE_ORDER if value in chosen
    )


def _selected_names(selected_ids, items):
    """The names of the selected ``items`` (dicts with ``id`` and ``name``)."""
    name_lookup = {str(item["id"]): item["name"] for item in items}
    names = (name_lookup.get(str(item_id), "").strip() for item_id in selected_ids)
    return [name for name in names if name]


def _series_name(filters, series_list):
    """The series' name when exactly one is selected, which is when titles name it."""
    selected_series = filters.get("series") or []
    if len(selected_series) != 1 or not series_list:
        return ""
    names = _selected_names(selected_series, series_list)
    return names[0] if names else ""


def _build_filter_title(
    filters, genres, platforms, min_year, max_year, series_list=None
):
    """Compose the heading text based on filters."""
    start_year = filters.get("start")
    end_year = filters.get("end")
    time_window = _build_time_window(start_year, end_year, min_year, max_year)
    platform_label = _build_platform_segment(
        filters.get("platforms", []), platforms, include_games=False
    )
    # Fold selected genres into the title after platform
    genre_names = _selected_names(filters.get("genres") or [], genres)
    genre_label = f" {_join_names(genre_names)}" if genre_names else ""

    # If exactly one series is selected, fold it into the title
    series_name = _series_name(filters, series_list)
    series_label = f" {series_name}" if series_name else ""

    hltb_label = _playtime_label(filters)

    # Omit "Video" prefix when genre, series, or playtime is selected
    if platform_label == "Video" and (genre_label or series_label or hltb_label):
        platform_label = ""

    time_suffix = f" of {time_window}" if time_window else ""

    played = _played_label(filters.get("played"))
    played_suffix = f": {played}" if played else ""

    # Build title with playtime before platform
    # Add space after hltb_label only if it exists
    if hltb_label:
        title = (
            f"Most Acclaimed {hltb_label} "
            f"{platform_label}{genre_label}{series_label} Games"
        )
    else:
        title = f"Most Acclaimed {platform_label}{genre_label}{series_label} Games"
    return " ".join(f"{title}{time_suffix}{played_suffix}".split())


def _build_tab_title(filters, genres, platforms, min_year, max_year, series_list=None):
    """The document title's text for a filtered page, or "" for an unfiltered one.

    The facets alone ("Nintendo Switch · Action · 1990s"), for the template
    to put the section's suffix after; ``_build_filter_title`` keeps the
    heading, the phrase an unfiltered page is searched for.
    """
    query = filters.get("q") or ""
    platform_label = _build_platform_segment(
        filters.get("platforms", []), platforms, include_games=False
    )
    return titles.short_title(
        [
            f"\u201c{query}\u201d" if query else "",
            _playtime_label(filters),
            "" if platform_label == "Video" else platform_label,
            _join_names(_selected_names(filters.get("genres") or [], genres)),
            _series_name(filters, series_list),
            titles.short_time_window(
                filters.get("start"), filters.get("end"), min_year, max_year
            ),
            _played_label(filters.get("played")),
        ]
    )

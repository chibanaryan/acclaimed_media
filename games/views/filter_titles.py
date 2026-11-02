"""The rankings heading's wording, composed from the filter state."""

from core.services import titles
from games import config

# Both heading helpers now live in core, so the album rankings page composes
# its heading the same way this one does.
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


# Status labels, in the filter's own order, as the client's `_titleParts` reads
# them; titled from GAME_STATUS_OPTIONS so the heading says what the filter says.
_STATUS_TITLES = tuple(
    (option["value"], option["title"]) for option in config.GAME_STATUS_OPTIONS
)


def _playtime_label(filters):
    """The heading's playtime words: "Short (<10 Hour)", "20+ Hour (100%)"."""
    hltb_mode = filters.get("hltb_mode", "main")
    hltb_min = filters.get("hltb_min")
    hltb_max = filters.get("hltb_max")
    if hltb_min is None and hltb_max is None:
        return ""

    mode_suffix = " (100%)" if hltb_mode == "completionist" else ""
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
    else:
        time_desc = f"<{int(hltb_max)} Hour"
    return f"{time_desc}{mode_suffix}"


def _filter_title_parts(
    filters, genres, platforms, min_year, max_year, series_list=None
):
    """The pieces the rankings titles are composed of (``_page_titles``)."""
    platform_label = _build_platform_segment(
        filters.get("platforms", []), platforms, include_games=False
    )
    if platform_label == "Video":
        platform_label = ""

    genre_label = ""
    selected_genres = filters.get("genres") or []
    if selected_genres:
        name_lookup = {str(g["id"]): g["name"] for g in genres}
        genre_label = _join_names(
            [
                name_lookup.get(str(gid), "").strip()
                for gid in selected_genres
                if name_lookup.get(str(gid), "").strip()
            ]
        )

    # If exactly one series is selected, fold it into the title
    series_label = ""
    selected_series = filters.get("series") or []
    if len(selected_series) == 1 and series_list:
        name_lookup = {str(s["id"]): s["name"] for s in series_list}
        series_label = name_lookup.get(str(selected_series[0]), "").strip()

    # The parameter is multi-select ("yes,want"); this used to read only an
    # exact "yes" or "no", so any other choice left the heading saying nothing.
    played = filters.get("played") or ""
    if isinstance(played, str):
        played = played.split(",")
    status_label = _join_names(
        [title for value, title in _STATUS_TITLES if value in played]
    )

    return {
        "playtime": _playtime_label(filters),
        "platform": platform_label,
        "genres": genre_label,
        "series": series_label,
        "window": _build_time_window(
            filters.get("start"), filters.get("end"), min_year, max_year
        ),
        "statuses": status_label,
    }


def _page_titles(filters, genres, platforms, min_year, max_year, series_list=None):
    """The rankings page's three titles, as ``music.views._page_titles``.

    ``heading`` is "Short (<10 Hour) Nintendo Switch Action Games of the
    1990s: Played"; ``keyword`` prefixes it with "Most Acclaimed" for the
    indexed ``<title>``, ``og:title``, the ItemList and the CSV filename;
    ``short`` is "Short (<10 Hour) · Nintendo Switch · Action · 1990s ·
    Played" for a filtered page's tab. ``filterComponent._titleParts`` and its
    two composers build the same in the browser.
    """
    parts = _filter_title_parts(
        filters, genres, platforms, min_year, max_year, series_list
    )
    subjects = [parts[key] for key in ("playtime", "platform", "genres", "series")]
    # "Video Games" when nothing names the kind of game
    noun = "Games" if any(subjects) else "Video Games"
    heading = " ".join(
        (
            " ".join(subjects)
            + f" {noun}"
            + (f" of {parts['window']}" if parts["window"] else "")
            + (f": {parts['statuses']}" if parts["statuses"] else "")
        ).split()
    )
    return {
        "heading": heading,
        "keyword": titles.keyword_title(heading),
        "short": titles.short_title(subjects, parts["window"], parts["statuses"]),
    }


def _build_filter_title(
    filters, genres, platforms, min_year, max_year, series_list=None
):
    """Compose the on-page heading from the filters (``_page_titles``)."""
    return _page_titles(filters, genres, platforms, min_year, max_year, series_list)[
        "heading"
    ]

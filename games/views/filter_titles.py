"""The rankings heading's wording, composed from the filter state."""

from core.services import titles

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
    genre_label = ""
    selected_genres = filters.get("genres") or []
    if selected_genres:
        name_lookup = {str(g["id"]): g["name"] for g in genres}
        genre_names = [
            name_lookup.get(str(gid), "").strip()
            for gid in selected_genres
            if name_lookup.get(str(gid), "").strip()
        ]
        if genre_names:
            genre_label = f" {_join_names(genre_names)}"

    # If exactly one series is selected, fold it into the title
    series_label = ""
    selected_series = filters.get("series") or []
    if len(selected_series) == 1 and series_list:
        name_lookup = {str(s["id"]): s["name"] for s in series_list}
        series_name = name_lookup.get(str(selected_series[0]), "").strip()
        if series_name:
            series_label = f" {series_name}"

    # Build HLTB playtime label
    hltb_label = ""
    hltb_mode = filters.get("hltb_mode", "main")
    hltb_min = filters.get("hltb_min")
    hltb_max = filters.get("hltb_max")

    if hltb_min is not None or hltb_max is not None:
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

        if time_desc:
            hltb_label = f"{time_desc}{mode_suffix}"

    # Omit "Video" prefix when genre, series, or playtime is selected
    if platform_label == "Video" and (genre_label or series_label or hltb_label):
        platform_label = ""

    time_suffix = f" of {time_window}" if time_window else ""

    # Add played status suffix
    played_suffix = ""
    played = filters.get("played")
    if played == "yes":
        played_suffix = ": Played"
    elif played == "no":
        played_suffix = ": Untracked"

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

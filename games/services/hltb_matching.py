"""Which HowLongToBeat entry a game is given, and how it is stored.

`fetch_hltb_data` and the weekly `refresh_all_metadata` both look a game up
by the HLTB id Wikidata holds, else by name, and save what they find. Each
had its own copy of all of it until 2026-11-10; this is the one.

A name search can answer with several entries. They are narrowed by
similarity, then release year, then platform, each only while more than one
is left and only if it leaves any. The platform step never ran before
2026-11-10: it read ``profile_platform``, where howlongtobeatpy's entry has
``profile_platforms``, a list.
"""

import re
from decimal import Decimal

from games.models import Game, HLTBGameData

# Roman numeral conversion mappings
ROMAN_TO_ARABIC = {
    "I": "1",
    "II": "2",
    "III": "3",
    "IV": "4",
    "V": "5",
    "VI": "6",
    "VII": "7",
    "VIII": "8",
    "IX": "9",
    "X": "10",
    "XI": "11",
    "XII": "12",
    "XIII": "13",
    "XIV": "14",
    "XV": "15",
    "XVI": "16",
    "XVII": "17",
    "XVIII": "18",
    "XIX": "19",
    "XX": "20",
}

ARABIC_TO_ROMAN = {v: k for k, v in ROMAN_TO_ARABIC.items()}

# HLTB's name for a platform (lowercased) to the names we hold for it: the
# Platform table's own, and the short forms older data used. A name that is
# the same on both sides needs no entry. The key is the whole of HLTB's
# name: looked for anywhere in it, as it was, "playstation" answered for
# PlayStation 4 and "nes" for SNES and Genesis.
PLATFORM_ALIASES = {
    "pc": ["PC", "Windows PC", "Windows", "DOS", "Linux", "Mac"],
    "mac": ["Apple Macintosh"],
    "playstation": ["PlayStation", "PS1", "PSX"],
    "playstation 2": ["PlayStation 2", "PS2"],
    "playstation 3": ["PlayStation 3", "PS3"],
    "playstation 4": ["PlayStation 4", "PS4"],
    "playstation 5": ["PlayStation 5", "PS5"],
    "xbox": ["Xbox"],
    "xbox 360": ["Xbox 360"],
    "xbox one": ["Xbox One"],
    "xbox series x/s": ["Xbox Series X/S", "Xbox Series X", "Xbox Series S"],
    "nintendo switch": ["Nintendo Switch", "Switch"],
    "wii": ["Wii", "Nintendo Wii"],
    "wii u": ["Wii U", "Nintendo Wii U"],
    "nintendo 64": ["Nintendo 64", "N64"],
    "gamecube": ["GameCube", "NGC", "Nintendo GameCube"],
    "nintendo gamecube": ["GameCube", "NGC"],
    "game boy": ["Game Boy", "GB"],
    "game boy advance": ["Game Boy Advance", "GBA"],
    "nintendo ds": ["Nintendo DS", "DS"],
    "nintendo 3ds": ["Nintendo 3DS", "3DS"],
    "nes": ["NES", "Nintendo Entertainment System"],
    "snes": ["SNES", "Super Nintendo Entertainment System", "Super Nintendo"],
    "super nintendo": ["SNES", "Super Nintendo Entertainment System"],
    "mobile": ["iOS", "Android", "Mobile", "iPhone", "Legacy Mobile Device"],
    "dreamcast": ["Sega Dreamcast"],
    "sega mega drive/genesis": ["Sega Mega Drive / Genesis"],
    "neo geo": ["SNK Neo Geo"],
    "3do": ["3DO Interactive Multiplayer"],
    "commodore 64": ["Commodore 64/128"],
    "atari st": ["Atari ST/STE"],
    "atari 8-bit family": ["Atari 8-bit"],
    "turbografx-16": ["TurboGrafx-16 / PC Engine"],
    "turbografx-cd": ["TurboGrafx-16 / PC Engine"],
    "nec pc-88": ["PC-8800"],
    "nec pc-98": ["PC-9800"],
    "pc vr": ["Virtual Reality"],
    "meta quest": ["Virtual Reality"],
}


def platform_matches(hltb_platform, game_platforms):
    """Whether one of HLTB's platform names is one of the game's platforms.

    The same name matches whatever its case or padding. Otherwise HLTB's
    name is looked up whole in ``PLATFORM_ALIASES``, and its names for us
    are compared with the game's exactly.
    """
    if not hltb_platform or not game_platforms:
        return False

    hltb_lower = hltb_platform.lower().strip()
    if any(platform.lower() == hltb_lower for platform in game_platforms):
        return True
    return any(
        our_name in game_platforms for our_name in PLATFORM_ALIASES.get(hltb_lower, ())
    )


def entry_platforms(entry):
    """The platforms HLTB lists for an entry, as a list of names.

    howlongtobeatpy gives ``profile_platforms``, already split. A string is
    split here, in case it stops.
    """
    platforms = getattr(entry, "profile_platforms", None)
    if isinstance(platforms, str):
        platforms = platforms.split(",")
    if not isinstance(platforms, (list, tuple)):
        return []
    return [name.strip() for name in platforms if isinstance(name, str) and name]


def convert_numerals(name):
    """
    Generate alternate versions of a game name with Roman/Arabic numerals swapped.

    Examples:
        "Final Fantasy VII" -> ["Final Fantasy 7"]
        "Street Fighter 2" -> ["Street Fighter II"]
        "Grand Theft Auto V" -> ["Grand Theft Auto 5"]

    Returns:
        List of alternate name versions, or empty list if no conversions found.
    """
    alternates = []

    # Roman numerals at word boundaries, to numbers
    roman_pattern = r"\b(" + "|".join(ROMAN_TO_ARABIC.keys()) + r")\b"
    roman_converted = re.sub(
        roman_pattern, lambda match: ROMAN_TO_ARABIC[match.group(1)], name
    )
    if roman_converted != name:
        alternates.append(roman_converted)

    # One- and two-digit numbers at word boundaries, to Roman numerals;
    # a number with no numeral here is kept
    arabic_converted = re.sub(
        r"\b(\d{1,2})\b",
        lambda match: ARABIC_TO_ROMAN.get(match.group(1), match.group(1)),
        name,
    )
    if arabic_converted != name and arabic_converted not in alternates:
        alternates.append(arabic_converted)

    return alternates


def search_names(game_name, wiki_page_title=None):
    """The names to search HLTB for, in the order to try them.

    Wikipedia's title first, where it differs, then ours, each followed by
    its Roman/Arabic numeral variants; no name twice.
    """
    names = []
    if wiki_page_title and wiki_page_title != game_name:
        names.append(wiki_page_title)
        names.extend(convert_numerals(wiki_page_title))
    names.append(game_name)
    names.extend(convert_numerals(game_name))
    return list(dict.fromkeys(names))


def _released_near(entry, year):
    """Whether HLTB dates the entry within a year of ``year``: regional
    releases straddle a new year."""
    try:
        return abs(int(entry.release_world) - year) <= 1
    except (AttributeError, TypeError, ValueError):
        return False


def choose_entry(results, *, min_similarity, game_year=None, game_platforms=()):
    """The entry of a name search's ``results`` to keep, or None.

    Those similar enough, narrowed by year and then by platform, each only
    while several are left and only if it leaves any; then the most
    similar.
    """
    candidates = [entry for entry in results if entry.similarity >= min_similarity]
    if not candidates:
        return None

    if game_year and len(candidates) > 1:
        same_year = [entry for entry in candidates if _released_near(entry, game_year)]
        candidates = same_year or candidates

    if game_platforms and len(candidates) > 1:
        on_platform = [
            entry
            for entry in candidates
            if any(
                platform_matches(name, game_platforms)
                for name in entry_platforms(entry)
            )
        ]
        candidates = on_platform or candidates

    return max(candidates, key=lambda entry: entry.similarity)


def entry_hours(entry, field_name):
    """An entry's playtime in hours, to one decimal place, or None.

    The library has given the value as hours under the field's own name, as
    seconds under ``<name>_seconds``, and under ``gameplay_<name>``.
    """
    for attr in (field_name, f"{field_name}_seconds", f"gameplay_{field_name}"):
        value = getattr(entry, attr, None)
        if value is not None and value > 0:
            if "seconds" in attr:
                return round(value / 3600, 1)
            return round(value, 1)
    return None


def _submission_count(raw):
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def entry_profile(entry):
    """
    HLTB's description of an entry, as ``HLTBGameData`` field values: its
    type, whether HLTB pools single-player and multiplayer times for it, and
    how many submissions each average rests on. Read from the raw search
    row: howlongtobeatpy maps neither submission count, and its
    ``complexity_lvl_combine`` turns a missing flag into False, where we
    keep None for "not reported".
    """
    raw = getattr(entry, "json_content", None)
    if not isinstance(raw, dict):
        return {}
    combine = raw.get("comp_lvl_combine")
    return {
        "game_type": str(raw.get("game_type") or "")[:20],
        "comp_lvl_combine": bool(combine) if combine is not None else None,
        "main_story_count": _submission_count(raw.get("comp_main_count")),
        "main_extra_count": _submission_count(raw.get("comp_plus_count")),
        "completionist_count": _submission_count(raw.get("comp_100_count")),
    }


def _decimal(value):
    return Decimal(str(value)) if value else None


def save_entry(
    game_id,
    game_igdb_id,
    hltb_id,
    hltb_name,
    fetch_method,
    similarity,
    main_story,
    main_extra,
    completionist,
    profile=None,
):
    """Store an HLTB entry as the game's primary HLTB record.

    A record orphaned by an import (same IGDB id, no game) is reconnected
    and updated. Otherwise the game's row for this IGDB id is created or
    updated; a new one (IGDB re-keyed the game) inherits the staff
    open-ended call of the row it replaces.
    """
    game = Game.objects.get(id=game_id)
    values = {
        "hltb_id": hltb_id,
        "hltb_name": hltb_name,
        "fetch_method": fetch_method,
        "similarity": _decimal(similarity),
        "main_story_hours": _decimal(main_story),
        "main_extra_hours": _decimal(main_extra),
        "completionist_hours": _decimal(completionist),
        **(profile or {}),
    }
    primary = HLTBGameData.objects.filter(game=game, is_primary=True)

    orphaned_record = HLTBGameData.objects.filter(
        igdb_id=game_igdb_id,
        game__isnull=True,
        is_primary=True,
    ).first()

    if orphaned_record:
        primary.update(is_primary=False)
        orphaned_record.game = game
        for field, value in values.items():
            setattr(orphaned_record, field, value)
        orphaned_record.save()
        hltb_data = orphaned_record
    else:
        previous_call = primary.values_list("open_ended_override", flat=True).first()
        primary.update(is_primary=False)
        hltb_data, created = HLTBGameData.objects.update_or_create(
            game=game,
            igdb_id=game_igdb_id,
            defaults={**values, "is_primary": True},
        )
        if created and previous_call is not None:
            hltb_data.open_ended_override = previous_call
            hltb_data.save(update_fields=["open_ended_override"])

    game.primary_hltb_game_data = hltb_data
    game.save(update_fields=["primary_hltb_game_data"])

    return hltb_data

"""
Move the editorial open-ended calls out of code and onto the records, as
``HLTBGameData.open_ended_override``, so staff manage them in the admin.

The calls are copied here, as they stood in ``games/open_ended.py`` (now
deleted), and written only where no override is set, so an earlier staff call
wins. A game with no HLTB row yet gets nothing; staff can mark it once HLTB
matches it, and HLTB's own type usually decides it first. Then every row's
``is_open_ended`` is derived from the override, else HLTB's type. Reversing
clears the listed games' overrides that hold the value written here - a
staff call that agrees with the list included - and re-derives.

The test behind the calls: does the game have an ending that HLTB's "Main"
time measures? Sandboxes with no win state, grand strategy with no victory,
multiplayer-first games, sports league sims, arcade games that loop until a
kill screen and endless puzzle games do not. Anything with a campaign,
story, ladder or finite set of levels does.
"""

from django.db import migrations, models

OPEN_ENDED_GAME_TYPES = ["multi", "endless", "sports"]

HELP_TEXT = (
    "Staff call on whether this game has a finish line, the test being: does "
    "it have an ending that HLTB's Main time measures? Yes (a campaign, story, "
    "ladder or finite set of levels) keeps its playtime; no (a sandbox, an MMO "
    "or other multiplayer-first game, a sports league sim, a looping arcade or "
    "endless puzzle game) hides it. Unknown falls back to HLTB's game type."
)

OPEN_ENDED_IGDB_IDS = [
    # Sandbox and management sims with no win state
    1272,  # SimCity
    330,  # SimCity 2000
    237,  # SimCity 3000
    1275,  # SimCity 4
    9066,  # Cities: Skylines
    223,  # The Sims
    224,  # The Sims 2
    260,  # The Sims 3
    283,  # Theme Park
    7236,  # Viva Piñata
    2655,  # Animal Crossing
    2645,  # Animal Crossing: Wild World
    109462,  # Animal Crossing: New Horizons
    2687,  # Animal Crossing: New Leaf
    146112,  # Farming Simulator 22
    3102,  # Kerbal Space Program
    3278,  # Garry's Mod
    6341,  # Dwarf Fortress
    2955,  # Elite Dangerous
    119295,  # Microsoft Flight Simulator
    3353,  # Microsoft Flight Simulator 1.0
    2953,  # Frontier: Elite II
    2951,  # Elite
    2712,  # Brain Age / Dr. Kawashima's Brain Training
    # Grand strategy with no victory
    2918,  # Crusader Kings II
    124954,  # Crusader Kings III
    # Multiplayer first
    1905,  # Fortnite
    114795,  # Apex Legends
    119313,  # Fall Guys
    111469,  # Among Us
    1279,  # Hearthstone
    7360,  # Tom Clancy's Rainbow Six Siege
    185258,  # ARC Raiders
    11137,  # Sea of Thieves
    2283,  # Defense of the Ancients (DotA)
    6359,  # Team Fortress Classic
    202279,  # Marvel Snap
    119188,  # Dota Auto Chess / Auto Chess
    5611,  # RuneScape / RuneScape 3
    2117,  # DayZ
    11529,  # The Jackbox Party Pack
    15091,  # SingStar
    17251,  # Warlords
    16759,  # Combat
    11198,  # Rocket League
    240,  # Battlefield 1942 (no campaign)
    277,  # Battlefield 2 (no campaign)
    2115,  # Titanfall (multiplayer only)
    881,  # Starsiege: Tribes
    17456,  # Bomberman Live
    15536,  # Escape from Tarkov
    7479,  # Warhawk
    7830,  # City of Heroes
    2987,  # Wolfenstein: Enemy Territory
    # Sports: league sims whose seasons repeat without end, and event
    # collections with no end. Arcade sports with a finite ladder or career
    # (NBA Jam, Virtua Tennis, Mario Golf, Tecmo Bowl) keep their hours
    705,  # FIFA: Road to World Cup 98
    699,  # FIFA 99
    3134,  # FIFA 09
    3133,  # FIFA 10
    503,  # FIFA 11
    2946,  # FIFA 12
    77321,  # Pro Evolution Soccer 3
    47354,  # Pro Evolution Soccer 4
    72967,  # Pro Evolution Soccer 5
    2484,  # Pro Evolution Soccer 6
    28403,  # ISS Pro Evolution
    9862,  # International Superstar Soccer Deluxe
    3516,  # International Superstar Soccer 64
    3514,  # International Superstar Soccer 98
    13257,  # Sensible Soccer
    10121,  # Sensible World of Soccer
    23064,  # Football Manager
    93149,  # Championship Manager 3
    4506,  # Madden NFL '95
    777,  # Madden NFL 2004
    778,  # Madden NFL 2005
    7881,  # ESPN NFL 2K5
    16595,  # Tecmo Super Bowl
    5056,  # NBA 2K11
    5057,  # NBA 2K12
    255788,  # NBA 2K24
    5405,  # NHL '94
    824,  # NHL 09
    9903,  # Baseball Stars
    2182,  # Wii Sports Resort
    1333,  # Pong
    11984,  # California Games
    6439,  # Track & Field / Hyper Olympic
    20406,  # International Track & Field
    9861,  # International Superstar Soccer
    15241,  # Kick Off 2
    18532,  # Ice Hockey (NES: exhibition matches only)
    43335,  # FIFA 2003
    19459,  # FIFA 17
    44932,  # International Superstar Soccer Pro 98
    945,  # Football Manager 2007
    45387,  # DecAthlete / Athlete Kings
    176,  # Ballblazer
    # Arcade games that loop until a kill screen, and score attacks
    7452,  # Ms. Pac-Man
    20900,  # Pac-Man Championship Edition
    21737,  # Pac-Man Championship Edition DX
    4614,  # Galaxian
    2751,  # Galaga
    3601,  # Space Invaders
    7758,  # Asteroids
    3873,  # Defender
    3592,  # Robotron: 2084
    2235,  # Centipede
    12313,  # Missile Command
    15383,  # Tempest
    2636,  # Dig Dug
    1086,  # Donkey Kong (1981 arcade; the 1994 Game Boy game has an ending)
    145209,  # Donkey Kong (Game & Watch)
    1087,  # Donkey Kong Jr.
    3105,  # Mario Bros.
    3659,  # Joust
    6795,  # Frogger
    2754,  # Breakout
    12916,  # Battlezone (1980 arcade, not the 1998 strategy game)
    12858,  # Star Wars (1983 arcade)
    4167,  # Spy Hunter
    12266,  # Qix
    1475,  # Scramble
    12346,  # Xevious
    5693,  # River Raid
    12314,  # Moon Patrol
    5247,  # Tron
    6100,  # Bomb Jack
    3502,  # Gauntlet
    3503,  # Gauntlet II
    15756,  # Geometry Wars: Retro Evolved
    4887,  # Geometry Wars: Retro Evolved 2
    16973,  # Lunar Lander
    18118,  # Blockade
    21817,  # Discs of Tron
    2753,  # Zaxxon
    # Endless puzzle games
    130749,  # Tetris
    3476,  # Dr. Mario
    8318,  # Bejeweled
    9054,  # Threes!
    29044,  # Drop7
    186090,  # Wordle
    28395,  # Snake
    # Pinball, a score attack
    3024,  # Pinball Dreams
    # HLTB's game_type marks these itself. Listed so they hold before a
    # refresh has fetched the type, and if one ever fails to re-match
    115,  # League of Legends
    121,  # Minecraft
    123,  # World of Warcraft
    241,  # Counter-Strike / Counter-Strike 1.6
    282,  # EverQuest
    301,  # Microsoft Flight Simulator X
    307,  # Counter-Strike: Source
    891,  # Team Fortress 2
    1183,  # Guild Wars 2
    1372,  # Counter-Strike: Global Offensive
    1829,  # PlanetSide
    1904,  # Europa Universalis IV
    2153,  # FIFA 13
    2181,  # Wii Sports
    2584,  # Eve Online
    2750,  # Pac-Man
    2963,  # Dota 2
    3126,  # Ultima Online
    4345,  # FIFA International Soccer
    4542,  # Madden NFL '96
    7574,  # FIFA 15
    8173,  # Overwatch
    8203,  # Mario Paint
    12515,  # Pokémon Go
    15707,  # Clash Royale
    27062,  # NHL Hockey
    27789,  # PUBG: Battlegrounds
    119277,  # Genshin Impact
    126294,  # FIFA 2000
]

FINISHABLE_IGDB_IDS = [
    386,  # Final Fantasy XIV: A Realm Reborn (its main scenario)
    234,  # Guild Wars / Guild Wars Prophecies (its campaign)
    8995,  # NBA Jam
    4036,  # NBA Street Vol. 2
    8168,  # Tecmo Bowl
    6291,  # Virtua Tennis / Power Smash
    7235,  # Virtua Tennis 3
    81523,  # Super Tennis
    135389,  # Mario Golf
    2541,  # Rockstar Games Presents Table Tennis
    7788,  # Blades of Steel
    2195,  # Punch-Out!!
    9151,  # Super Punch-Out!!
    2194,  # Punch-Out!! (2009)
    21968,  # Phantasy Star Online (its offline story)
    325594,  # Split Fiction (co-op story)
    135243,  # It Takes Two (co-op story)
    36897,  # A Way Out (co-op story)
    325591,  # Elden Ring Nightreign (a roguelike with final bosses)
]

CALLS = ((OPEN_ENDED_IGDB_IDS, True), (FINISHABLE_IGDB_IDS, False))


def derive(HLTBGameData):
    """``HLTBGameData.derive_open_ended`` for every row, as queries."""
    rows = HLTBGameData.objects.all()
    rows.update(is_open_ended=False)
    rows.filter(game_type__in=OPEN_ENDED_GAME_TYPES).update(is_open_ended=True)
    for override in (True, False):
        rows.filter(open_ended_override=override).update(is_open_ended=override)


def seed_overrides(apps, schema_editor):
    HLTBGameData = apps.get_model("games", "HLTBGameData")
    for igdb_ids, override in CALLS:
        HLTBGameData.objects.filter(
            igdb_id__in=igdb_ids, open_ended_override__isnull=True
        ).update(open_ended_override=override)
    derive(HLTBGameData)


def clear_overrides(apps, schema_editor):
    HLTBGameData = apps.get_model("games", "HLTBGameData")
    for igdb_ids, override in CALLS:
        HLTBGameData.objects.filter(
            igdb_id__in=igdb_ids, open_ended_override=override
        ).update(open_ended_override=None)
    derive(HLTBGameData)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0119_derive_open_ended_without_combine"),
    ]

    operations = [
        migrations.AlterField(
            model_name="hltbgamedata",
            name="open_ended_override",
            field=models.BooleanField(
                blank=True,
                help_text=HELP_TEXT,
                null=True,
            ),
        ),
        migrations.RunPython(seed_overrides, clear_overrides),
    ]

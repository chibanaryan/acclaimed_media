"""
Editorial open-ended calls, by IGDB id, for the games HLTB's flags get wrong
or have not been fetched for. ``HLTBGameData.derive_open_ended`` consults
them after a staff override and before HLTB's own flags.

The test: does the game have an ending that HLTB's "Main" time measures?
If not - a sandbox with no win state, grand strategy with no victory, a
multiplayer-first game, a sports league sim's endless seasons, an arcade
game that loops until a kill screen, an endless puzzle or pinball game - its
hours are time invested and it shows none (see games/services/playtime.py).
Anything with a campaign, story, ladder or finite set of levels keeps its
hours: fighting games, kart racers, 4X, RTS, racing, rhythm games,
roguelikes, scenario-based tycoon games, arcade sports with a ladder,
Stardew Valley. Minecraft and Animal Crossing: New Horizons nominally end,
but are not played toward it.

Kept in code rather than written as overrides, so a row created later - a
listed game HLTB is first matched for - gets the call too. Keyed on IGDB id,
as HLTBGameData is; a game IGDB re-keys falls back to HLTB's flags until its
new id is listed here. Changing a list needs a migration that re-derives the
stored flag with ``derive_all`` (as 0118 does); a one-off correction belongs
in the admin override.
"""

from django.db.models import Q

# HLTB entry types for games with no finish line. Measured against the
# corpus on 2026-10-26: these, with ``comp_lvl_combine``, catch every MMO,
# MOBA and arena shooter plus Minecraft, Pac-Man and Wii Sports, and no
# story game. Everything else HLTB files as "game".
OPEN_ENDED_GAME_TYPES = frozenset({"multi", "endless", "sports"})

OPEN_ENDED_IGDB_IDS = frozenset(
    {
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
        # Pinball, a score attack
        3024,  # Pinball Dreams
        # HLTB flags these itself (2026-10-26). Listed so they hold from deploy,
        # before a refresh has fetched the flags, and if one ever fails to
        # re-match
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
        11198,  # Rocket League
        12515,  # Pokémon Go
        15707,  # Clash Royale
        27062,  # NHL Hockey
        27789,  # PUBG: Battlegrounds
        109462,  # Animal Crossing: New Horizons
        119277,  # Genshin Impact
        126294,  # FIFA 2000
    }
)

# Games whose Main time measures a real ending, though HLTB flags them or
# may: MMOs with a finite campaign, and arcade sports with a ladder or
# career, which HLTB's "sports" type would otherwise hide
FINISHABLE_IGDB_IDS = frozenset(
    {
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
    }
)


def derive_all(HLTBGameData):
    """
    Re-derive ``is_open_ended`` for every row of ``HLTBGameData`` (a live or a
    historical model) as queries, lowest precedence first: HLTB's flags, then
    the calls above, then any staff override. Restates
    ``HLTBGameData.derive_open_ended``, which a historical model lacks;
    ``games/tests/test_playtime.py`` checks the two agree. Run it from a new
    migration whenever a list here changes.
    """
    rows = HLTBGameData.objects.all()
    rows.update(is_open_ended=False)
    rows.filter(
        Q(game_type__in=OPEN_ENDED_GAME_TYPES) | Q(comp_lvl_combine=True)
    ).update(is_open_ended=True)
    rows.filter(igdb_id__in=OPEN_ENDED_IGDB_IDS).update(is_open_ended=True)
    rows.filter(igdb_id__in=FINISHABLE_IGDB_IDS).update(is_open_ended=False)
    for override in (True, False):
        rows.filter(open_ended_override=override).update(is_open_ended=override)

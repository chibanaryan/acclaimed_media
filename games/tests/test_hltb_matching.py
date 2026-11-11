"""Which HowLongToBeat entry a name search keeps, and how it is stored:
`games.services.hltb_matching`, which `fetch_hltb_data` and
`refresh_all_metadata` both use.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from games.models import Game, HLTBGameData
from games.services import hltb_matching
from games.services.hltb_matching import (
    choose_entry,
    convert_numerals,
    entry_hours,
    entry_platforms,
    platform_matches,
    search_names,
)


class PlatformMatchesTests(SimpleTestCase):
    def assert_table(self, cases):
        for hltb_platform, game_platforms, expected in cases:
            with self.subTest(hltb=hltb_platform, ours=game_platforms):
                self.assertIs(platform_matches(hltb_platform, game_platforms), expected)

    def test_nothing_to_compare_is_no_match(self):
        self.assert_table(
            [
                (None, ["PlayStation 4"], False),
                ("", ["PlayStation 4"], False),
                ("PlayStation 4", [], False),
                ("PlayStation 4", None, False),
            ]
        )

    def test_the_same_name_matches_whatever_its_case_or_padding(self):
        self.assert_table(
            [
                ("PlayStation 4", ["PlayStation 4"], True),
                ("playstation 4 ", ["PlayStation 4"], True),
                ("Sega Saturn", ["PlayStation", "sega saturn"], True),
                # In no alias list, so only the name itself can match
                ("Nintendo GameCube", ["Nintendo GameCube"], True),
            ]
        )

    def test_an_alias_matches_one_of_our_names_for_the_platform(self):
        self.assert_table(
            [
                ("PC", ["Linux"], True),
                ("Nintendo Switch", ["Switch"], True),
                ("Nintendo 64", ["N64"], True),
                ("NES", ["Nintendo Entertainment System"], True),
                ("Mobile", ["Android"], True),
                # Any one of the game's platforms is enough
                ("Xbox One", ["PlayStation 4", "Xbox One"], True),
            ]
        )

    def test_an_alias_is_compared_with_our_names_exactly(self):
        self.assert_table([("Nintendo Switch", ["switch"], False)])

    def test_another_platform_is_no_match(self):
        self.assert_table(
            [
                ("Sega Saturn", ["PlayStation"], False),
                ("PC", ["PlayStation 4"], False),
                ("PlayStation", ["PlayStation 2"], False),
                ("Nintendo 3DS", ["Nintendo DS"], False),
            ]
        )

    def test_a_platform_does_not_match_one_whose_name_contains_its_own(self):
        # An alias key was looked for anywhere in HLTB's name, so "playstation"
        # answered for PlayStation 4, and "nes" for SNES and Genesis.
        self.assert_table(
            [
                ("PlayStation 4", ["PlayStation"], False),
                ("Xbox 360", ["Xbox"], False),
                ("Wii U", ["Wii"], False),
                ("Game Boy Advance", ["Game Boy"], False),
                ("SNES", ["NES"], False),
                ("Sega Mega Drive/Genesis", ["Nintendo Entertainment System"], False),
            ]
        )

    def test_the_sites_own_platform_names_match_hltbs(self):
        # The alias lists predated the names the Platform table holds now.
        self.assert_table(
            [
                ("PC", ["Windows PC"], True),
                ("Wii", ["Nintendo Wii"], True),
                ("Wii U", ["Nintendo Wii U"], True),
                ("Mobile", ["iPhone"], True),
                ("Super Nintendo", ["Super Nintendo Entertainment System"], True),
                ("Dreamcast", ["Sega Dreamcast"], True),
                ("Sega Mega Drive/Genesis", ["Sega Mega Drive / Genesis"], True),
                ("Commodore VIC-20", ["VIC-20"], True),
                ("FM-7", ["Fujitsu Micro 7"], True),
                ("NEC PC-98", ["PC-9800"], True),
                ("Mac", ["Apple Macintosh"], True),
            ]
        )


class ConvertNumeralsTests(SimpleTestCase):
    def assert_table(self, cases):
        for name, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(convert_numerals(name), expected)

    def test_a_roman_numeral_becomes_a_number(self):
        self.assert_table(
            [
                ("Final Fantasy VII", ["Final Fantasy 7"]),
                ("Grand Theft Auto V", ["Grand Theft Auto 5"]),
                ("Civilization IV", ["Civilization 4"]),
                ("Dragon Quest XI", ["Dragon Quest 11"]),
                # Mid-title, and more than one
                ("Star Wars: Episode I - Racer", ["Star Wars: Episode 1 - Racer"]),
                ("Ys I & II", ["Ys 1 & 2"]),
            ]
        )

    def test_a_number_becomes_a_roman_numeral(self):
        self.assert_table(
            [
                ("Street Fighter 2", ["Street Fighter II"]),
                ("Half-Life 2: Episode 1", ["Half-Life II: Episode I"]),
                ("Persona 5 Royal", ["Persona V Royal"]),
                ("Tekken 20", ["Tekken XX"]),
            ]
        )

    def test_a_name_with_both_gets_one_alternate_each_way(self):
        self.assert_table(
            [
                ("Final Fantasy X-2", ["Final Fantasy 10-2", "Final Fantasy X-II"]),
                (
                    "Final Fantasy XIII-2",
                    ["Final Fantasy 13-2", "Final Fantasy XIII-II"],
                ),
            ]
        )

    def test_only_a_whole_word_is_a_numeral(self):
        self.assert_table(
            [
                ("Portal", []),
                ("", []),
                # Letters and digits run together are one word
                ("Mega Man X4", []),
                ("1942", []),
                # "3rd" stays; the III beside it does not
                ("Street Fighter III: 3rd Strike", ["Street Fighter 3: 3rd Strike"]),
                # Roman numerals are capitals
                ("final fantasy vii", []),
            ]
        )

    def test_a_number_outside_one_to_twenty_is_left_alone(self):
        self.assert_table(
            [
                ("Fallout 76", []),
                ("FIFA 21", []),
                ("Resident Evil 0", []),
                # A leading zero is not the number
                ("Madden NFL 08", []),
                # XXI is not in the table, and XX inside it is not a word
                ("Rocky XXI", []),
            ]
        )

    def test_a_capital_that_is_a_word_is_read_as_a_numeral(self):
        # Only ever an extra name to search for, beside the original.
        self.assert_table(
            [
                ("I Am Alive", ["1 Am Alive"]),
                ("Mega Man X", ["Mega Man 10"]),
            ]
        )


def entry(name, similarity, year=None, platforms=None, **extra):
    return SimpleNamespace(
        game_name=name,
        similarity=similarity,
        release_world=year,
        profile_platforms=platforms,
        **extra,
    )


class EntryPlatformsTests(SimpleTestCase):
    def test_the_librarys_list_is_read_as_it_is(self):
        self.assertEqual(
            entry_platforms(entry("G", 1, platforms=["PC", " Nintendo Switch "])),
            ["PC", "Nintendo Switch"],
        )

    def test_a_string_is_split(self):
        self.assertEqual(
            entry_platforms(entry("G", 1, platforms="PC, PlayStation 4")),
            ["PC", "PlayStation 4"],
        )

    def test_nothing_usable_is_no_platforms(self):
        for platforms in (None, 7, [], [None, ""]):
            with self.subTest(platforms=platforms):
                self.assertEqual(
                    entry_platforms(entry("G", 1, platforms=platforms)), []
                )
        self.assertEqual(entry_platforms(object()), [])


class SearchNamesTests(SimpleTestCase):
    def test_wikipedias_title_first_then_ours_each_with_its_numerals(self):
        self.assertEqual(
            search_names("Final Fantasy 7", "Final Fantasy VII (1997 video game)"),
            [
                "Final Fantasy VII (1997 video game)",
                "Final Fantasy 7 (1997 video game)",
                "Final Fantasy 7",
                "Final Fantasy VII",
            ],
        )

    def test_no_name_is_searched_twice(self):
        self.assertEqual(search_names("Portal", "Portal"), ["Portal"])
        self.assertEqual(search_names("Portal"), ["Portal"])
        self.assertEqual(search_names("Doom 2", "Doom II"), ["Doom II", "Doom 2"])


class ChooseEntryTests(SimpleTestCase):
    def choose(self, results, year=None, platforms=()):
        chosen = choose_entry(
            results, min_similarity=0.85, game_year=year, game_platforms=platforms
        )
        return chosen and chosen.game_name

    def test_nothing_similar_enough_is_no_entry(self):
        self.assertIsNone(self.choose([]))
        self.assertIsNone(self.choose([entry("Other", 0.5)]))

    def test_the_most_similar_entry_wins(self):
        results = [entry("Near", 0.9), entry("Exact", 1.0), entry("Far", 0.4)]
        self.assertEqual(self.choose(results), "Exact")

    def test_the_year_narrows_several_entries(self):
        """Within a year either way: regional releases straddle a new year."""
        results = [entry("Remake", 1.0, year=2019), entry("Original", 0.9, year="1999")]
        self.assertEqual(self.choose(results, year=1998), "Original")
        self.assertEqual(self.choose(results, year=2019), "Remake")

    def test_a_year_no_entry_has_narrows_nothing(self):
        results = [entry("A", 1.0, year=2019), entry("B", 0.9, year="soon")]
        self.assertEqual(self.choose(results, year=1980), "A")
        self.assertEqual(
            self.choose([entry("A", 1.0), entry("B", 0.9)], year=1980), "A"
        )

    def test_the_platform_narrows_what_the_year_left(self):
        """It never ran: the code read `profile_platform`, and the library's
        entry has `profile_platforms`, a list."""
        results = [
            entry("16-bit", 1.0, year=1991, platforms=["Sega Mega Drive/Genesis"]),
            entry("8-bit", 0.95, year=1991, platforms=["Sega Master System"]),
        ]
        self.assertEqual(
            self.choose(results, year=1991, platforms=["Sega Master System"]), "8-bit"
        )
        self.assertEqual(
            self.choose(results, year=1991, platforms=["Sega Mega Drive / Genesis"]),
            "16-bit",
        )

    def test_a_platform_no_entry_is_on_narrows_nothing(self):
        results = [
            entry("A", 1.0, platforms=["PC"]),
            entry("B", 0.9, platforms=None),
        ]
        self.assertEqual(self.choose(results, platforms=["Arcade"]), "A")

    def test_one_entry_is_kept_whatever_its_year_or_platform(self):
        results = [entry("Only", 0.9, year=2001, platforms=["PC"])]
        self.assertEqual(self.choose(results, year=1985, platforms=["Arcade"]), "Only")


class EntryHoursTests(SimpleTestCase):
    def test_hours_are_rounded_to_a_decimal_place(self):
        self.assertEqual(
            entry_hours(SimpleNamespace(main_story=12.34), "main_story"), 12.3
        )

    def test_seconds_become_hours(self):
        self.assertEqual(
            entry_hours(SimpleNamespace(main_story_seconds=5400), "main_story"), 1.5
        )

    def test_the_gameplay_prefix_is_read_too(self):
        self.assertEqual(
            entry_hours(SimpleNamespace(gameplay_main_story=2), "main_story"), 2
        )

    def test_nothing_or_zero_is_no_time(self):
        self.assertIsNone(entry_hours(SimpleNamespace(main_story=0), "main_story"))
        self.assertIsNone(entry_hours(SimpleNamespace(), "main_story"))


class SaveEntryTests(TestCase):
    def save(self, game, **changes):
        values = {
            "hltb_id": "77",
            "hltb_name": "Name",
            "fetch_method": "wikidata",
            "similarity": 1.0,
            "main_story": 10,
            "main_extra": 0,
            "completionist": 30.5,
        }
        values.update(changes)
        return hltb_matching.save_entry(game.id, game.igdb_id, **values)

    def test_a_new_row_becomes_the_games_primary_record(self):
        game = Game.objects.create(name="G", rank=1, igdb_id=1)
        data = self.save(game, profile={"game_type": "game"})
        game.refresh_from_db()
        self.assertEqual(game.primary_hltb_game_data, data)
        self.assertTrue(data.is_primary)
        self.assertEqual(
            (data.main_story_hours, data.main_extra_hours, data.completionist_hours),
            (10, None, 30.5),
        )
        self.assertEqual(data.game_type, "game")

    def test_saving_again_updates_the_same_row(self):
        game = Game.objects.create(name="G", rank=1, igdb_id=1)
        first = self.save(game)
        second = self.save(game, main_story=12, hltb_name="Renamed")
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.main_story_hours, 12)
        self.assertEqual(HLTBGameData.objects.filter(game=game).count(), 1)

    def test_an_orphaned_record_is_reconnected(self):
        orphan = HLTBGameData.objects.create(
            game=None, igdb_id=1, hltb_id="old", is_primary=True
        )
        game = Game.objects.create(name="G", rank=1, igdb_id=1)
        data = self.save(game)
        self.assertEqual(data.pk, orphan.pk)
        self.assertEqual((data.game, data.hltb_id), (game, "77"))

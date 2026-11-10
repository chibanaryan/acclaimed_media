"""Which HowLongToBeat entry a name search keeps: `platform_matches` and
`convert_numerals` in `fetch_hltb_data`, which `refresh_all_metadata` uses too.
"""

import unittest

from django.test import SimpleTestCase

from games.management.commands.fetch_hltb_data import (
    convert_numerals,
    platform_matches,
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

    @unittest.expectedFailure
    def test_a_platform_does_not_match_one_whose_name_contains_its_own(self):
        # An alias key is looked for anywhere in HLTB's name, so "playstation"
        # answers for PlayStation 4, and "nes" for SNES and Genesis.
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

    @unittest.expectedFailure
    def test_the_sites_own_platform_names_match_hltbs(self):
        # The alias lists predate the names the Platform table holds now.
        self.assert_table(
            [
                ("PC", ["Windows PC"], True),
                ("Wii", ["Nintendo Wii"], True),
                ("Wii U", ["Nintendo Wii U"], True),
                ("Mobile", ["iPhone"], True),
                ("Super Nintendo", ["Super Nintendo Entertainment System"], True),
                ("Dreamcast", ["Sega Dreamcast"], True),
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

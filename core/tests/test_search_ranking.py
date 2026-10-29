"""Tests for the search boxes' match scores and group order."""

from django.test import SimpleTestCase, TestCase

from core.services import search_ranking as ranking
from games.models import Game


class MatchQualityTests(SimpleTestCase):
    def test_the_kinds_of_match_score_in_order(self):
        cases = [
            ("beatles", ["The Beatles"], ranking.EXACT),
            ("the beatles", ["The Beatles"], ranking.EXACT),
            ("bjork", ["Björk"], ranking.EXACT),
            ("  Led   ZEPPELIN ", ["Led Zeppelin"], ranking.EXACT),
            ("zep", ["Led Zeppelin"], ranking.WORD_START),
            ("the", ["The Beatles"], ranking.WORD_START),
            ("eatle", ["The Beatles"], ranking.SUBSTRING),
            ("x", ["Abbey Road"], None),
            ("", ["Abbey Road"], None),
        ]
        for q, names, expected in cases:
            with self.subTest(q=q):
                self.assertEqual(ranking.match_quality(q, names), expected)

    def test_the_best_of_several_names_counts(self):
        names = ["Prince", "Prince and the Revolution"]
        self.assertEqual(ranking.match_quality("revolution", names), ranking.WORD_START)
        self.assertEqual(ranking.match_quality("prince", names), ranking.EXACT)

    def test_a_row_the_names_miss_takes_the_fallback(self):
        # An album the database matched on its credit line alone.
        self.assertEqual(
            ranking.quality_or("radiohead", ["Kid A"], ranking.INDIRECT),
            ranking.INDIRECT,
        )
        self.assertEqual(
            ranking.quality_or("agaetis", ["Ágætis byrjun"], ranking.INDIRECT),
            ranking.WORD_START,
        )


class ExactFirstTests(TestCase):
    """Exact names lead in the database, so a bounded slice keeps them."""

    def _names(self, q, q_normalized):
        return [
            game.name
            for game in ranking.exact_first(
                Game.objects.all(), "rank", name=q, name_normalized=q_normalized
            )
        ]

    def test_an_exact_name_jumps_the_ranking(self):
        for name, rank in (("Street Fighter II", 5), ("Street Fighter", 900)):
            Game.objects.create(name=name, rank=rank, year_of_release=1991)
        self.assertEqual(
            self._names("STREET fighter", "street fighter"),
            ["Street Fighter", "Street Fighter II"],
        )

    def test_a_leading_the_and_accents_are_read_as_match_quality_does(self):
        for name, rank in (("Pokémon Red", 3), ("The Pokémon", 800)):
            Game.objects.create(name=name, rank=rank, year_of_release=1996)
        # "pokemon" names The Pokémon exactly, through its folded copy.
        self.assertEqual(
            self._names("pokemon", "pokemon"), ["The Pokémon", "Pokémon Red"]
        )


class GroupOrderTests(SimpleTestCase):
    TIES = ("games", "series", "developers")

    def test_the_best_match_leads(self):
        self.assertEqual(
            ranking.group_order(
                {"games": ranking.WORD_START, "series": None, "developers": 0},
                self.TIES,
            ),
            ["developers", "games", "series"],
        )

    def test_ties_fall_in_the_given_order(self):
        self.assertEqual(
            ranking.group_order(
                {"games": 0, "series": 0, "developers": ranking.SUBSTRING}, self.TIES
            ),
            ["games", "series", "developers"],
        )

    def test_empty_groups_go_last(self):
        self.assertEqual(
            ranking.group_order({"developers": ranking.INDIRECT}, self.TIES),
            ["developers", "games", "series"],
        )
        self.assertEqual(ranking.group_order({}, self.TIES), list(self.TIES))

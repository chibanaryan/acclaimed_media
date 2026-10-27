"""The list, its facet counts and the CSV filter one way.

Until 2026-10-26 each built the filters itself, and the copies had drifted:
the counts and the CSV searched `name` only (no accent folding), the counts
ignored series and playtime, and the CSV ignored the sort.
"""

import csv
import io

from django.test import TestCase

from core.tests.utils import clear_all_caches
from games.models import Game, HLTBGameData, Platform, Series, WikipediaGenre


class SharedGameFiltersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.platform = Platform.objects.create(code="GB", name="Game Boy")
        cls.genre = WikipediaGenre.objects.create(name="RPG", slug="rpg", level=0)
        cls.series = Series.objects.create(name="Pokémon", slug="pokemon", igdb_id=1)

        def game(name, rank, year, hours, series=False):
            g = Game.objects.create(
                name=name,
                slug=f"g{rank}",
                rank=rank,
                igdb_id=rank,
                year_of_release=year,
            )
            g.platforms.add(cls.platform)
            g.wikipedia_genres.add(cls.genre)
            if series:
                g.series.add(cls.series)
            hltb = HLTBGameData.objects.create(
                game=g,
                igdb_id=rank,
                hltb_id=str(rank),
                main_story_hours=hours,
                is_primary=True,
            )
            g.primary_hltb_game_data = hltb
            g.save()
            return g

        cls.red = game("Pokémon Red", 1, 1996, 26, series=True)
        cls.tetris = game("Tetris", 2, 1989, 5)
        cls.links = game("Link's Awakening", 3, 1993, 15)

    def setUp(self):
        clear_all_caches()

    def _context(self, query):
        return self.client.get(f"/?{query}").context

    def _year_count(self, context, year):
        return next(e["count"] for e in context["year_counts"] if e["year"] == year)

    def test_the_counts_fold_accents_as_the_list_does(self):
        context = self._context("q=pokemon")

        self.assertEqual([g.name for g in context["games"]], ["Pokémon Red"])
        self.assertEqual(self._year_count(context, 1996), 1)
        self.assertEqual(context["genre_counts_json"][str(self.genre.id)], 1)
        self.assertEqual(context["platform_counts_json"][str(self.platform.id)], 1)

    def test_the_counts_apply_the_series_filter(self):
        context = self._context(f"series={self.series.id}")

        self.assertEqual(self._year_count(context, 1989), 0)  # Tetris
        self.assertEqual(self._year_count(context, 1996), 1)
        self.assertEqual(context["genre_counts_json"][str(self.genre.id)], 1)

    def test_the_counts_apply_the_playtime_filter(self):
        context = self._context("hltb_preset=short")  # under 10 hours

        self.assertEqual([g.name for g in context["games"]], ["Tetris"])
        self.assertEqual(self._year_count(context, 1989), 1)
        self.assertEqual(self._year_count(context, 1993), 0)
        self.assertEqual(context["platform_counts_json"][str(self.platform.id)], 1)

    def test_a_count_leaves_only_its_own_dimension_out(self):
        """Filtered to 1996, the year grid still counts the other years."""
        context = self._context("start=1996&end=1996")

        self.assertEqual(self._year_count(context, 1989), 1)
        self.assertEqual(context["genre_counts_json"][str(self.genre.id)], 1)

    def _csv_names(self, query):
        response = self.client.get(f"/download/?{query}")
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        header = next(i for i, row in enumerate(rows) if "Name" in row)
        name = rows[header].index("Name")
        return [row[name] for row in rows[header + 1 :] if len(row) > name]

    def test_the_csv_folds_accents(self):
        self.assertEqual(self._csv_names("q=pokemon"), ["Pokémon Red"])

    def test_the_csv_follows_the_sort(self):
        self.assertEqual(
            self._csv_names("sort=year&dir=desc"),
            ["Pokémon Red", "Link's Awakening", "Tetris"],
        )

    def test_reordered_id_lists_share_a_facet_cache_key(self):
        from django.http import QueryDict

        from games.views._helpers import _facet_cache_key

        self.assertEqual(
            _facet_cache_key("home_year_counts", QueryDict("genres=3,7&platforms=2,1")),
            _facet_cache_key("home_year_counts", QueryDict("genres=7,3&platforms=1,2")),
        )

"""The list, its facet counts and the CSV filter one way.

Until 2026-10-26 each built the filters itself, and the copies had drifted:
the counts and the CSV searched `name` only (no accent folding), the counts
ignored series and playtime, and the CSV ignored the sort.
"""

import csv
import io

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from core.tests.utils import clear_all_caches
from games.models import (
    Game,
    HLTBGameData,
    List,
    ListMembership,
    Platform,
    Publication,
    Series,
    WikipediaGenre,
)
from games.services.game_filters import apply_game_filters


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


class RankingsListQueryTests(TestCase):
    """The rankings' list query, and the number of lists each row shows.

    ``list_count`` was ``Count("lists", distinct=True)``: a join to every
    list membership, grouped over every column of every game, under a
    ``DISTINCT`` the sort added, all before the first hundred rows were
    taken. It was 109 ms of the page's 120 ms of SQL. It is a subquery a
    row now. The ``DISTINCT`` was left that day to the filters that joined
    many-to-many, and they no longer join.
    """

    def setUp(self):
        clear_all_caches()
        self.pc = Platform.objects.create(code="WIN", name="PC")
        self.mac = Platform.objects.create(code="MAC", name="Mac")
        self.root = WikipediaGenre.objects.create(name="Query Root", slug="query-root")
        self.child = WikipediaGenre.objects.create(
            name="Query Child", slug="query-child", parent=self.root, level=1
        )
        publication = Publication.objects.create(name="Mag")
        self.lists = [
            List.objects.create(name=f"List {n}", publisher=publication, year=2000 + n)
            for n in range(3)
        ]
        self.both = Game.objects.create(name="On both", rank=1, slug="on-both")
        self.both.platforms.add(self.pc, self.mac)
        self.both.wikipedia_genres.add(self.root, self.child)
        for position, source in enumerate(self.lists, start=1):
            ListMembership.objects.create(game=self.both, list=source, rank=position)
        self.unlisted = Game.objects.create(name="On none", rank=2, slug="on-none")
        self.unlisted.platforms.add(self.pc)

    def rows(self, query=""):
        response = self.client.get("/?" + query)
        return [(game.name, game.list_count) for game in response.context["games"]]

    def test_each_game_is_listed_once_with_its_lists(self):
        self.assertEqual(self.rows(), [("On both", 3), ("On none", 0)])

    def test_a_game_on_two_selected_platforms_is_listed_once(self):
        """The join that would list it twice also multiplied a joined count."""
        query = f"platforms={self.pc.id},{self.mac.id}"
        self.assertEqual(self.rows(query), [("On both", 3), ("On none", 0)])

    def test_a_game_tagged_a_genre_and_its_child_is_listed_once(self):
        self.assertEqual(self.rows(f"genres={self.root.id}"), [("On both", 3)])

    def test_every_sort_lists_each_game_once(self):
        query = f"platforms={self.pc.id},{self.mac.id}&sort="
        for sort in ("rank", "year", "name"):
            with self.subTest(sort=sort):
                self.assertEqual(len(self.rows(query + sort)), 2)

    def test_the_unfiltered_list_is_not_grouped_or_made_distinct(self):
        clear_all_caches()
        with CaptureQueriesContext(connection) as captured:
            self.client.get("/")
        lists = [
            query["sql"]
            for query in captured.captured_queries
            if '"games_game"."name_normalized"' in query["sql"]
            and "LIMIT" in query["sql"]
        ]
        self.assertEqual(len(lists), 1, lists)
        self.assertNotIn("SELECT DISTINCT", lists[0])
        # The count's own subquery groups its memberships; the games are not
        self.assertNotIn('GROUP BY "games_game"', lists[0])

    def test_a_filtered_list_is_not_made_distinct_either(self):
        """Each many-to-many filter is an ``EXISTS``, not a join.

        A join lists a game once per matching platform, genre or series, so
        each filter added a ``DISTINCT`` over every column of every game,
        ahead of the page's hundred rows (ROADMAP 5, until 2026-11-12).
        """
        series = Series.objects.create(name="Query Series", slug="qs", igdb_id=1)
        self.both.series.add(series)
        query = (
            f"platforms={self.pc.id},{self.mac.id}"
            f"&genres={self.root.id}&series={series.id}"
        )
        clear_all_caches()
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get("/?" + query)
        self.assertEqual([game.name for game in response.context["games"]], ["On both"])
        lists = [
            query["sql"]
            for query in captured.captured_queries
            if '"games_game"."name_normalized"' in query["sql"]
            and "LIMIT" in query["sql"]
        ]
        self.assertEqual(len(lists), 1, lists)
        self.assertNotIn("SELECT DISTINCT", lists[0])
        self.assertEqual(lists[0].count("EXISTS"), 3, lists[0])

    def test_a_filtered_lists_count_counts_each_game_once(self):
        query = f"platforms={self.pc.id},{self.mac.id}&genres={self.root.id}"
        response = self.client.get("/?" + query)
        self.assertEqual(response.context["paginator"].count, 1)

    def test_the_chart_under_a_filter_counts_games_and_not_ranks(self):
        """Two games may share a rank. Under a filter the chart read
        ``SELECT DISTINCT rank``, so a tie was one game there and two
        without the filter."""
        tied = Game.objects.create(name="Tied", rank=2, slug="tied")
        tied.platforms.add(self.pc)
        filtered = apply_game_filters(
            Game.objects.all(), {"platforms": str(self.pc.id)}
        )
        self.assertEqual(sorted(filtered.values_list("rank", flat=True)), [1, 2, 2])

    def test_the_csv_lists_a_game_on_two_selected_platforms_once(self):
        response = self.client.get(
            "/download/", {"platforms": f"{self.pc.id},{self.mac.id}"}
        )
        lines = response.content.decode().strip().splitlines()
        self.assertEqual(len(lines), 3)  # the header and two games

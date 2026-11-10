"""One range for `decade`, `year`, `start` and `end`, wherever they are read.

The list, the heading and the CSV's file name each had a rule of their own.
"""

from django.test import SimpleTestCase, TestCase
from django.utils.text import slugify

from core.tests.utils import clear_all_caches
from games import models
from games.services.query_filters import resolve_year_range


class ResolveYearRangeTests(SimpleTestCase):
    def test_each_parameter_alone(self):
        self.assertEqual(resolve_year_range(year="1995"), (1995, 1995))
        self.assertEqual(resolve_year_range(decade="1990-99"), (1990, 1999))
        self.assertEqual(resolve_year_range(start="1990"), (1990, None))
        self.assertEqual(resolve_year_range(end="1999"), (None, 1999))
        self.assertEqual(resolve_year_range(start="1990", end="1999"), (1990, 1999))
        self.assertEqual(resolve_year_range(), (None, None))

    def test_a_start_or_an_end_beats_a_year_which_beats_a_decade(self):
        self.assertEqual(
            resolve_year_range(decade="1990-99", year="1995"), (1995, 1995)
        )
        self.assertEqual(
            resolve_year_range(decade="1990-99", start="2000"), (2000, None)
        )
        self.assertEqual(resolve_year_range(year="1995", end="2005"), (None, 2005))

    def test_what_is_not_a_year_is_no_value(self):
        self.assertEqual(resolve_year_range(year="abc"), (None, None))
        self.assertEqual(resolve_year_range(year="²"), (None, None))
        self.assertEqual(resolve_year_range(decade="the-90s"), (None, None))
        # Not a decade's first year, as in the browser
        self.assertEqual(resolve_year_range(decade="1995-99"), (None, None))
        self.assertEqual(resolve_year_range(decade="1990-99x"), (None, None))
        self.assertEqual(resolve_year_range(start="9" * 40), (None, None))

    def test_an_unreadable_start_still_outranks_a_year(self):
        """As `currentFilterParams` has it: the list is then unfiltered."""
        self.assertEqual(resolve_year_range(year="1995", start="abc"), (None, None))


class OneRangeEverywhereTests(TestCase):
    """The list, the heading and the CSV's name agree on a mixed query."""

    @classmethod
    def setUpTestData(cls):
        for rank, year in enumerate((1985, 1991, 1995, 1999, 2003), start=1):
            models.Game.objects.create(
                name=f"Game {year}",
                rank=rank,
                igdb_id=rank,
                slug=f"game-{year}",
                year_of_release=year,
            )

    def setUp(self):
        clear_all_caches()
        self.addCleanup(clear_all_caches)

    def page(self, query):
        response = self.client.get(f"/?{query}")
        self.assertEqual(response.status_code, 200)
        years = [game.year_of_release for game in response.context["games"]]
        return years, response.context["filter_title"]

    def csv(self, query):
        response = self.client.get(f"/download/?{query}")
        self.assertEqual(response.status_code, 200)
        rows = response.content.decode().strip().splitlines()[1:]
        return len(rows), response["Content-Disposition"]

    def test_a_year_beats_a_decade(self):
        """The list showed the 1990s under a heading that said 1995."""
        years, title = self.page("decade=1990-99&year=1995")
        self.assertEqual(years, [1995])
        self.assertIn("1995", title)
        self.assertNotIn("1990s", title)

        count, disposition = self.csv("decade=1990-99&year=1995")
        self.assertEqual(count, 1)
        self.assertIn(slugify(title), disposition)

    def test_a_start_beats_a_decade(self):
        """The list was empty under a heading that began at 2000."""
        years, title = self.page("decade=1990-99&start=2000")
        self.assertEqual(years, [2003])
        self.assertIn("2000", title)

        count, disposition = self.csv("decade=1990-99&start=2000")
        self.assertEqual(count, 1)
        self.assertIn(slugify(title), disposition)

    def test_a_decade_alone_is_unchanged(self):
        years, title = self.page("decade=1990-99")
        self.assertEqual(years, [1991, 1995, 1999])
        self.assertIn("1990s", title)
        self.assertEqual(self.csv("decade=1990-99")[0], 3)

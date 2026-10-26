"""A malformed query string is the visitor's mistake, not a 500.

Every URL here returned a server error until the parsing moved to
``core.services.query_params``; most of them were a bare ``int()`` on a
comma-separated id list or a year.
"""

from django.test import TestCase

from core.tests.utils import clear_all_caches
from games import models

BAD_VALUES = ("abc", "1,x", "1.5", "99999999999999999999")

HTML_PARAMS = ("genres", "series", "platforms", "start", "end", "year", "decade")
API_PARAMS = ("genres", "platforms", "developer", "start", "end", "limit", "order_by")
LIMIT_URLS = (
    "/api/games/search/?q=zelda&limit=",
    "/api/unified-search/?q=zelda&game_limit=",
    "/api/unified-search/?q=zelda&developer_limit=",
    "/api/unified-search/?q=zelda&series_limit=",
)


class MalformedQueryParamTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        models.Game.objects.create(
            name="The Legend of Zelda", rank=1, igdb_id=1, year_of_release=1986
        )

    def setUp(self):
        clear_all_caches()

    def _assert_not_a_server_error(self, url):
        response = self.client.get(url)
        self.assertLess(response.status_code, 500, url)

    def test_rankings_page_and_download(self):
        for path in ("/", "/download/"):
            for param in HTML_PARAMS:
                for value in BAD_VALUES:
                    with self.subTest(path=path, param=param, value=value):
                        self._assert_not_a_server_error(f"{path}?{param}={value}")

    def test_games_api(self):
        for param in API_PARAMS:
            for value in BAD_VALUES + ("-5",):
                with self.subTest(param=param, value=value):
                    self._assert_not_a_server_error(f"/api/games/?{param}={value}")

    def test_search_limits(self):
        for url in LIMIT_URLS:
            for value in BAD_VALUES + ("", "-5"):
                with self.subTest(url=url, value=value):
                    self._assert_not_a_server_error(url + value)


class DecadeParamMatchesTheListTests(TestCase):
    """The heading's range and the list's filter read `?decade=` one way."""

    @classmethod
    def setUpTestData(cls):
        models.Game.objects.create(name="Old", rank=1, igdb_id=11, year_of_release=1985)
        models.Game.objects.create(
            name="Nineties", rank=2, igdb_id=12, year_of_release=1995
        )

    def setUp(self):
        clear_all_caches()

    def _range_and_names(self, query):
        response = self.client.get(f"/{query}")
        filters = response.context["filters"]
        names = [game.name for game in response.context["games"]]
        return (filters["start"], filters["end"]), names

    def test_a_decade_filters_both(self):
        (start, end), names = self._range_and_names("?decade=1990-99")
        self.assertEqual((start, end), (1990, 1999))
        self.assertEqual(names, ["Nineties"])

    def test_an_unrecognised_decade_filters_neither(self):
        """`?decade=1990` named the 1990s in the year grid while the list,
        which needs the 1990-99 form, stayed unfiltered."""
        (start, end), names = self._range_and_names("?decade=1990")
        self.assertEqual((start, end), (1985, 1995))
        self.assertEqual(names, ["Old", "Nineties"])

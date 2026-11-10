"""The list's echo of the filters it was rendered with.

`#game-rendered-filters`: what the filter component puts its controls back
on when a filter request fails and no engine is coming.
`scripts/browser_smoke.js` ("games failed request ...") runs the roll-back.
"""

import re

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase

from core.tests.utils import clear_all_caches
from games import models


class RenderedFiltersEchoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.genre = models.WikipediaGenre.objects.create(
            name="Echo Action", slug="echo-action", level=0
        )
        cls.platform = models.Platform.objects.create(code="EPC", name="Echo PC")
        for rank, year in enumerate((1985, 1991, 1995, 1999, 2003), start=1):
            game = models.Game.objects.create(
                name=f"Game {year}",
                rank=rank,
                igdb_id=rank,
                slug=f"game-{year}",
                year_of_release=year,
            )
            game.platforms.add(cls.platform)
            game.wikipedia_genres.add(cls.genre)

    def setUp(self):
        clear_all_caches()
        self.addCleanup(clear_all_caches)

    def echo(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        found = re.findall(
            r'<div id="game-rendered-filters" hidden data-query="([^"]*)">', html
        )
        self.assertEqual(len(found), 1, "one echo a page")
        return QueryDict(found[0].replace("&amp;", "&"))

    def test_an_unfiltered_list_echoes_nothing(self):
        self.assertEqual(self.echo("/").dict(), {})

    def test_the_filters_are_echoed_as_the_browser_reads_them(self):
        query = (
            f"q=game&start=1990&end=1999&genres={self.genre.id}"
            f"&platforms={self.platform.id}&sort=name&dir=desc"
            "&hltb_mode=completionist&hltb_min=5&hltb_max=20"
        )
        self.assertEqual(
            self.echo(f"/?{query}").dict(),
            {
                "q": "game",
                "start": "1990",
                "end": "1999",
                "genres": str(self.genre.id),
                "platforms": str(self.platform.id),
                "sort": "name",
                "dir": "desc",
                "hltb_mode": "completionist",
                "hltb_min": "5",
                "hltb_max": "20",
            },
        )

    def test_the_echo_is_in_a_partial_render_too(self):
        """That is the render a filter change swaps in."""
        self.assertEqual(
            self.echo("/?start=1990&end=1999&partial=true").dict(),
            {"start": "1990", "end": "1999"},
        )

    def test_where_the_reader_landed_is_no_filter(self):
        """The page is kept whole for the next visitor."""
        self.assertEqual(self.echo("/?highlight=3&utm_source=x").dict(), {})

    def test_the_older_year_parameters_are_echoed_as_the_range_they_mean(self):
        self.assertEqual(
            self.echo("/?year=1995").dict(), {"start": "1995", "end": "1995"}
        )
        self.assertEqual(
            self.echo("/?decade=1990-99").dict(), {"start": "1990", "end": "1999"}
        )

    def test_a_status_filter_is_echoed_only_for_a_reader_it_applies_to(self):
        self.assertEqual(self.echo("/?played=yes").dict(), {})
        user = get_user_model().objects.create_user(username="reader", password="pw")
        self.client.force_login(user)
        self.assertEqual(self.echo("/?played=yes").dict(), {"played": "yes"})

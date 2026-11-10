"""A game with no release year, on the server's side of each rendering.

`Game.year_of_release` is nullable. The templates wrote it bare, so an undated
game was "(None)" in its row, its heading and its descriptions, where the
client renderer writes "(N/A)" in the row
(`games/static/games/js/game-list-renderer.js`).
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from core.tests.utils import clear_all_caches
from games import models

RENDERER = Path(settings.BASE_DIR) / "games/static/games/js/game-list-renderer.js"


class UndatedGameTests(TestCase):
    def setUp(self):
        clear_all_caches()
        self.game = models.Game.objects.create(
            name="Timeless Game", rank=1, slug="timeless-game"
        )
        self.dated = models.Game.objects.create(
            name="Dated Game", rank=2, slug="dated-game", year_of_release=1998
        )

    def _rows(self):
        soup = BeautifulSoup(self.client.get(reverse("home")).content, "html.parser")
        return (
            soup.find(id=f"game-{self.game.id}"),
            soup.find(id=f"game-{self.game.id}-mobile"),
        )

    def test_no_row_says_none(self):
        desktop, mobile = self._rows()
        self.assertNotIn("None", desktop.get_text())
        self.assertNotIn("None", mobile.get_text())

    def test_the_desktop_row_says_what_the_renderer_says(self):
        desktop, _ = self._rows()
        self.assertEqual(desktop.find(attrs={"data-slot": "year"}).get_text(), "N/A")

    def test_the_mobile_row_says_what_the_renderer_says(self):
        _, mobile = self._rows()
        title = mobile.find(attrs={"data-slot": "title"}).get_text(" ", strip=True)
        self.assertIn("Timeless Game (N/A)", re.sub(r"\s+", " ", title))

    def test_the_renderer_still_writes_that_for_an_undated_game(self):
        """The other half of the pair: if this wording moves, the rows do."""
        source = RENDERER.read_text(encoding="utf-8")
        self.assertIn("this._fillSlot(row, 'year', game.y || 'N/A');", source)
        self.assertIn("(${game.y || 'N/A'})</span>", source)

    def test_a_dated_row_is_unchanged(self):
        soup = BeautifulSoup(self.client.get(reverse("home")).content, "html.parser")
        desktop = soup.find(id=f"game-{self.dated.id}")
        mobile = soup.find(id=f"game-{self.dated.id}-mobile")
        self.assertEqual(desktop.find(attrs={"data-slot": "year"}).get_text(), "1998")
        self.assertIn("(1998)", mobile.get_text())

    def test_the_detail_page_leaves_the_year_out(self):
        response = self.client.get(
            reverse("game-detail", kwargs={"slug": self.game.slug})
        )
        self.assertEqual(response.status_code, 200)
        soup = BeautifulSoup(response.content, "html.parser")
        heading = soup.find("h1").get_text(" ", strip=True)
        self.assertEqual(heading, "Timeless Game")
        for attrs in ({"name": "description"}, {"property": "og:description"}):
            content = soup.find("meta", attrs=attrs)["content"]
            self.assertNotIn("None", content)
            self.assertNotIn("()", content)
            self.assertIn("Timeless Game", content)
            self.assertIn("#1", content)

    def test_a_dated_detail_page_is_unchanged(self):
        response = self.client.get(
            reverse("game-detail", kwargs={"slug": self.dated.slug})
        )
        soup = BeautifulSoup(response.content, "html.parser")
        self.assertEqual(soup.find("h1").get_text(" ", strip=True), "Dated Game (1998)")
        description = soup.find("meta", attrs={"name": "description"})["content"]
        self.assertTrue(description.startswith("Dated Game (1998) - Ranked #2"))
        og = soup.find("meta", attrs={"property": "og:description"})["content"]
        self.assertTrue(og.startswith("Dated Game (1998) is ranked #2"))

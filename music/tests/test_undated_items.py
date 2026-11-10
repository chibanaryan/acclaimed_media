"""An album with no release year, on the server's side of each rendering.

`Album.year_released` is nullable. The detail page's descriptions wrote it
bare ("(None)"), and the mobile row wrapped nothing in brackets ("()") where
`album-list-renderer.js` writes nothing at all.
"""

from pathlib import Path

from bs4 import BeautifulSoup
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from core.tests.utils import clear_all_caches
from music import models
from music.tests.site import setUpModule, tearDownModule  # noqa: F401

RENDERER = Path(settings.BASE_DIR) / "music/static/music/js/album-list-renderer.js"


class UndatedAlbumTests(TestCase):
    def setUp(self):
        clear_all_caches()
        self.album = models.Album.objects.create(
            name="Timeless", rank=1, slug="timeless", artist_credit="Nobody"
        )
        self.dated = models.Album.objects.create(
            name="Doolittle",
            rank=2,
            slug="doolittle",
            artist_credit="Pixies",
            year_released=1989,
        )

    def _year_mobile(self, album):
        soup = BeautifulSoup(
            self.client.get(reverse("music:home")).content, "html.parser"
        )
        row = soup.find(id=f"music-{album.id}-mobile")
        return row.find(attrs={"data-slot": "year-mobile"}).get_text(strip=True)

    def test_the_mobile_row_shows_no_empty_brackets(self):
        self.assertEqual(self._year_mobile(self.album), "")

    def test_a_dated_mobile_row_is_unchanged(self):
        self.assertEqual(self._year_mobile(self.dated), "(1989)")

    def test_the_renderer_still_writes_nothing_for_an_undated_album(self):
        """The other half of the pair: if this moves, the row does."""
        source = RENDERER.read_text(encoding="utf-8")
        self.assertIn(
            "yearEl.textContent = album.year === null ? '' : `(${album.year})`;",
            source,
        )

    def test_the_detail_page_leaves_the_year_out(self):
        response = self.client.get(
            reverse("music:album-detail", kwargs={"slug": self.album.slug})
        )
        self.assertEqual(response.status_code, 200)
        soup = BeautifulSoup(response.content, "html.parser")
        for attrs in ({"name": "description"}, {"property": "og:description"}):
            content = soup.find("meta", attrs=attrs)["content"]
            self.assertNotIn("None", content)
            self.assertNotIn("()", content)
            self.assertTrue(content.startswith("Timeless by Nobody"), content)

    def test_a_dated_detail_page_is_unchanged(self):
        response = self.client.get(
            reverse("music:album-detail", kwargs={"slug": self.dated.slug})
        )
        soup = BeautifulSoup(response.content, "html.parser")
        description = soup.find("meta", attrs={"name": "description"})["content"]
        self.assertTrue(
            description.startswith("Doolittle (1989) by Pixies - ranked #2")
        )
        og = soup.find("meta", attrs={"property": "og:description"})["content"]
        self.assertTrue(og.startswith("Doolittle (1989) by Pixies is ranked #2"))


class EmptyOverlayLinesTests(TestCase):
    """The grid card's overlay, for an album with no credit, genres or lists.

    `_album_card_grid.html` leaves each empty line out. The renderer filled
    the clone's three with nothing and left them in, each taking its gap in
    the overlay's column.
    """

    def test_the_renderer_removes_a_line_it_has_nothing_for(self):
        source = RENDERER.read_text(encoding="utf-8")
        start = source.index("_renderGridCard(")
        card = source[start : source.index("_fillCover(row, album", start)]
        for name in ("creator", "genres", "listCount"):
            self.assertIn(f"{name}.remove();", card)

    def test_the_server_card_leaves_the_same_lines_out(self):
        from django.template.loader import render_to_string

        album = models.Album.objects.create(name="Bare", rank=3, slug="bare")
        album.list_count = 0
        html = render_to_string(
            "music/includes/_album_card_grid.html",
            {"item": album, "show_rank": "alltime"},
        )
        overlay = BeautifulSoup(html, "html.parser").find(
            attrs={"data-slot": "overlay"}
        )
        self.assertEqual(overlay.find_all(attrs={"data-slot": True}), [])

"""Dual-rendering tests for the album row.

`_album_row.html` serves twice: the server renders rows with it, and
`music/home.html` renders it empty inside <template> elements for
`album-list-renderer.js` to clone and fill. These tests pin the contract
between the two - every data-slot the renderer writes to has to exist in both
renderings, and in the empty one in particular, where a condition on the item
would quietly leave a slot out.

Reference files that must stay in sync:
- music/templates/music/includes/_album_row.html
- core/templates/core/includes/_base_media_row.html
- music/static/music/js/album-list-renderer.js
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup
from django.conf import settings
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from core import constants as core_constants
from core.models import User
from music import models

RENDERER = Path(settings.BASE_DIR) / "music/static/music/js/album-list-renderer.js"

DESKTOP_SLOTS = {
    "root",
    "media-row",
    "rank",
    "global-rank",
    "thumb-link",
    "thumbnail",
    "thumbnail-placeholder",
    "title-link",
    "name",
    "year-link",
    "year",
    "meta-row",
}

MOBILE_SLOTS = {
    "root-mobile",
    "rank-mobile",
    "thumbnail-mobile",
    "thumbnail-mobile-placeholder",
    "title-mobile",
    "year-mobile",
    "meta-mobile",
}


def slots(html):
    soup = BeautifulSoup(html, "html.parser")
    return {el["data-slot"] for el in soup.select("[data-slot]")}


def row_slots(variant=None):
    """The slots `_album_row.html` emits with no album, for one variant."""
    context = {"row_variant": variant} if variant else {}
    return slots(render_to_string("music/includes/_album_row.html", context))


class EmptyRowTemplateTests(TestCase):
    """The row as it is rendered into a <template>, with no album."""

    def test_the_desktop_variant_carries_every_slot(self):
        self.assertEqual(DESKTOP_SLOTS - row_slots("desktop"), set())

    def test_the_mobile_variant_carries_every_slot(self):
        self.assertEqual(MOBILE_SLOTS - row_slots("mobile"), set())

    def test_each_variant_renders_only_its_own_half(self):
        desktop = row_slots("desktop")
        mobile = row_slots("mobile")
        self.assertEqual(desktop & MOBILE_SLOTS, set())
        self.assertEqual(mobile & DESKTOP_SLOTS - {"meta-row"}, set())

    def test_both_halves_render_when_no_variant_is_given(self):
        # How games and books use the shared row, and how the server renders
        # an album row on the page itself.
        self.assertEqual((DESKTOP_SLOTS | MOBILE_SLOTS) - row_slots(), set())

    def test_the_cover_image_slot_survives_having_no_cover(self):
        # The trap this contract exists for: with the img inside a condition
        # on the album's thumbnail, a clone would have no thumbnail slot and
        # the renderer nowhere to write the cover URL.
        html = render_to_string(
            "music/includes/_album_row.html", {"row_variant": "desktop"}
        )
        soup = BeautifulSoup(html, "html.parser")
        img = soup.select_one('img[data-slot="thumbnail"]')
        self.assertIsNotNone(img)
        self.assertIsNone(img.get("src"))


class ServerRenderedRowTests(TestCase):
    """The same row with an album in it."""

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="rowstaff", password="rowpass", is_staff=True
        )
        self.client.login(username="rowstaff", password="rowpass")

        self.artist = models.Artist.objects.create(name="Pixies", slug="pixies")
        self.genre = models.MusicGenre.objects.create(name="Alternative Rock")
        self.album = models.Album.objects.create(
            name="Doolittle",
            rank=1,
            slug="doolittle",
            artist_credit="Pixies",
            year_released=1989,
        )
        self.album.artists.set([self.artist])
        self.album.genres.set([self.genre])

        publication = models.MusicPublication.objects.create(name="NME")
        source = models.MusicList.objects.create(
            name="Albums of the 1980s",
            year=2021,
            publisher=publication,
            order=1,
            type=core_constants.LIST_DECADE,
        )
        models.AlbumListMembership.objects.create(list=source, album=self.album, rank=1)

    def _page(self):
        return self.client.get(reverse("music:home")).content.decode()

    def test_the_rendered_row_carries_the_same_slots(self):
        found = slots(self._page())
        self.assertEqual((DESKTOP_SLOTS | MOBILE_SLOTS) - found, set())

    def test_the_metadata_line_holds_the_credit_genres_and_list_count(self):
        soup = BeautifulSoup(self._page(), "html.parser")
        meta = soup.select_one('[data-slot="meta-row"]')
        self.assertIn("Pixies", meta.get_text())
        self.assertIn("Alternative Rock", meta.get_text())
        self.assertIn("1 list", meta.get_text())

    def test_the_artist_credit_is_a_link_to_the_artist(self):
        # `artist_links`, which the renderer reproduces.
        soup = BeautifulSoup(self._page(), "html.parser")
        credit = soup.select_one('[data-slot="artist-credit"]')
        link = credit.select_one("a")
        self.assertEqual(link["href"], "/music/artists/pixies/")

    def test_the_row_ids_match_what_the_renderer_writes(self):
        page = self._page()
        self.assertIn(f'id="music-{self.album.id}"', page)
        self.assertIn(f'id="music-{self.album.id}-mobile"', page)
        source = RENDERER.read_text()
        self.assertIn("`music-${album.id}`", source)
        self.assertIn("`music-${album.id}-mobile`", source)


class RendererContractTests(TestCase):
    """The renderer must not reach for a slot the templates do not emit."""

    def _declared_slots(self):
        """The slot list `album-list-renderer.js` declares for this purpose."""
        source = RENDERER.read_text()
        block = re.search(r"AlbumListRenderer\.SLOTS = \[(.*?)\];", source, re.S)
        self.assertIsNotNone(block, "AlbumListRenderer.SLOTS is gone")
        return set(re.findall(r"'([a-z-]+)'", block.group(1)))

    def test_the_renderer_declares_the_slots_it_fills(self):
        declared = self._declared_slots()
        self.assertIn("thumbnail", declared)
        self.assertEqual(declared & {"artist-credit", "genres", "list-count"}, set())

    def test_the_templates_emit_every_slot_the_renderer_declares(self):
        self.assertEqual(self._declared_slots() - row_slots(), set())

    def test_the_declared_slots_are_split_across_the_two_variants(self):
        # Each <template> only holds one half, so a slot the renderer fills
        # has to be in the half it clones for that row.
        variants = (("desktop", DESKTOP_SLOTS), ("mobile", MOBILE_SLOTS))
        for variant, expected in variants:
            with self.subTest(variant=variant):
                available = row_slots(variant)
                self.assertEqual(self._declared_slots() & expected - available, set())

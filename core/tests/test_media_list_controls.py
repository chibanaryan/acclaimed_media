"""The ranking-list controls are one partial, shared by every section.

`core/includes/_media_list_controls.html` renders the sort dropdown, the
direction flip, the list/grid toggle and the jump-to-rank box. Games' and
music's results headers were written separately before this and drifted:
music's sort became a pair of native selects in the sidebar and it never had
the other two controls at all. These tests pin the partial's contract and
check both rankings pages actually render it.
"""

from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from bs4 import BeautifulSoup

from core.models import User
from games import config as games_config
from games import models as game_models
from music import config as music_config
from music import models as music_models


def render_controls(**context):
    base = {
        "sort_options": music_config.SORT_OPTIONS,
        "default_sort_label": "Rank",
        "item_noun": "Album",
        "total_count": 500,
        "loaded_count": 100,
    }
    base.update(context)
    return BeautifulSoup(
        render_to_string("core/includes/_media_list_controls.html", base),
        "html.parser",
    )


class ControlsPartialTests(TestCase):
    def test_every_sort_option_appears_in_the_menu_and_the_select(self):
        soup = render_controls()
        for option in music_config.SORT_OPTIONS:
            with self.subTest(sort=option["value"]):
                self.assertTrue(
                    soup.select(f'[\\@click="updateSort(\'{option["value"]}\')"]')
                )
                self.assertTrue(soup.select(f'option[value="{option["value"]}"]'))

    def test_the_current_label_expression_covers_every_option(self):
        # The dropdown's label is one chained ternary built from the options,
        # so an option missing from it would show the fallback label instead.
        label = render_controls().select_one('[x-text*="filters.sort"]')["x-text"]
        for option in music_config.SORT_OPTIONS:
            with self.subTest(sort=option["value"]):
                self.assertIn(f"filters.sort === '{option['value']}'", label)

    def test_a_label_expression_is_rendered_unescaped(self):
        # Games' playtime label depends on other filter state, so its label
        # is an Alpine expression. Escaping its quotes would leave Alpine
        # with entities instead of a string.
        label = render_controls(
            sort_options=games_config.SORT_OPTIONS,
        ).select_one(
            '[x-text*="filters.sort"]'
        )["x-text"]
        self.assertIn("filters.hltb_mode === 'completionist'", label)
        self.assertNotIn("&#x27;", label)

    def test_the_jump_box_carries_the_paging_state(self):
        box = render_controls().select_one(".jump-to-rank-input")
        self.assertEqual(box["data-total"], "500")
        self.assertEqual(box["data-loaded"], "100")
        self.assertEqual(box["data-per-page"], "100")
        self.assertEqual(box["placeholder"], "Album #")

    def test_the_view_toggle_can_be_turned_off(self):
        self.assertTrue(render_controls().select('[aria-label="Grid view"]'))
        self.assertFalse(
            render_controls(show_view_toggle=False).select('[aria-label="Grid view"]')
        )

    def test_the_jump_box_can_be_turned_off(self):
        self.assertFalse(
            render_controls(show_jump_to_rank=False).select(".jump-to-rank-input")
        )

    def test_both_count_lines_are_addressable(self):
        # A client-side renderer has to update the desktop and the mobile
        # line; querySelector would only ever find the first.
        soup = render_controls()
        found = {el["data-result-count"] for el in soup.select("[data-result-count]")}
        self.assertEqual(found, {"desktop", "mobile"})

    def test_the_empty_count_label_shows_when_nothing_matched(self):
        soup = render_controls(total_count=0, empty_count_label="Advanced Search")
        self.assertIn("Advanced Search", soup.get_text())


class BothRankingPagesRenderTheControlsTests(TestCase):
    """The point of the partial: one header on both rankings pages."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="controls", password="controlspass", is_staff=True
        )
        self.client.login(username="controls", password="controlspass")

        game_models.Game.objects.create(
            name="Tetris", rank=1, slug="tetris", year_of_release=1984, igdb_id=1
        )
        music_models.Album.objects.create(
            name="Doolittle", rank=1, slug="doolittle", year_released=1989
        )

    def _controls(self, url_name):
        page = self.client.get(reverse(url_name)).content.decode()
        return BeautifulSoup(page, "html.parser")

    def test_each_page_renders_the_same_controls(self):
        for url_name in ("home", "music:home"):
            with self.subTest(page=url_name):
                soup = self._controls(url_name)
                self.assertTrue(soup.select('[x-text*="filters.sort"]'))
                self.assertTrue(soup.select('[\\@click="toggleSortDirection()"]'))
                self.assertTrue(soup.select('[aria-label="Grid view"]'))
                self.assertTrue(soup.select(".jump-to-rank-input"))

    def test_each_page_offers_its_own_sorts(self):
        # Playtime is games-only; albums have no equivalent metric, so the
        # album page offers the three shared sorts and nothing more.
        music = self._controls("music:home")
        self.assertTrue(music.select("[\\@click=\"updateSort('rank')\"]"))
        self.assertFalse(music.select("[\\@click=\"updateSort('playtime')\"]"))
        self.assertTrue(
            self._controls("home").select("[\\@click=\"updateSort('playtime')\"]")
        )

    def test_music_no_longer_carries_a_second_sort_control(self):
        # The sidebar's native selects were the visible divergence; the form
        # now carries the state as hidden fields instead.
        soup = self._controls("music:home")
        form = soup.select_one("#album-filters")
        self.assertEqual(form.select_one('[name="sort"]')["type"], "hidden")
        self.assertEqual(form.select_one('[name="dir"]')["type"], "hidden")

"""Keyboard and screen-reader access to the rankings pages (2026-10-26).

The filters were mouse-only: year cells, genre, platform, series and
playtime rows, and the section headers were clickable divs with no role, no
tab stop and no pressed state. These pin the markup; the behaviour (arrow
keys in the year grid, Enter and Space on a row, focus in the mobile sheet)
was checked in Chrome.
"""

import re

from bs4 import BeautifulSoup
from django.conf import settings
from django.test import Client, TestCase

from core.tests.utils import clear_all_caches
from games.models import Game, Platform, Series, WikipediaGenre


class RankingsPageAccessibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        platforms = [
            Platform.objects.create(code=code, name=name)
            for code, name in (
                ("NES", "NES"),
                ("SNES", "Super NES"),
                ("N64", "Nintendo 64"),
            )
        ]
        genre = WikipediaGenre.objects.create(name="A11y Root", slug="a11y-root")
        WikipediaGenre.objects.create(
            name="A11y Leaf", slug="a11y-leaf", parent=genre, level=1
        )
        series = Series.objects.create(name="Mario", slug="mario", igdb_id=1)
        game = Game.objects.create(
            name="Super Mario", slug="super-mario", rank=1, year_of_release=1990
        )
        game.platforms.add(*platforms)
        game.wikipedia_genres.add(genre)
        game.series.add(series)
        sequel = Game.objects.create(
            name="Super Mario 2", slug="super-mario-2", rank=2, year_of_release=1991
        )
        sequel.series.add(series)  # the series filter lists series of two or more

        # One render for the class: every test here only reads the markup
        clear_all_caches()
        cls.soup = BeautifulSoup(Client().get("/").content, "html.parser")

    def test_one_page_heading_per_layout(self):
        """The site title is branding; each layout has one h1, the other hidden."""
        ids = [h1.get("id") for h1 in self.soup.find_all("h1")]
        self.assertEqual(sorted(ids), ["search-title", "search-title-mobile"])

    def test_filter_rows_are_keyboard_buttons_with_a_pressed_state(self):
        for selector in (
            "[\\@click^=selectPreset]",
            ".genre-item",
            ".platform-item",
            ".series-item",
        ):
            rows = self.soup.select(selector)
            with self.subTest(selector=selector):
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(row.get("role"), "button")
                    self.assertEqual(row.get("tabindex"), "0")
                    self.assertIn(":aria-pressed", row.attrs)
                    self.assertIn("@keydown.enter.prevent", row.attrs)

    def test_section_headers_are_buttons_that_say_whether_they_are_open(self):
        toggles = self.soup.select("button[\\:aria-expanded]")
        labels = {" ".join(b.get_text().split()) for b in toggles}
        for section in ("Release Year", "Platform", "Genre", "Series"):
            self.assertIn(section, labels)

    def test_the_year_grid_is_one_keyboard_group(self):
        grid = self.soup.select_one(".year-grid")
        self.assertEqual(grid.get("role"), "group")
        self.assertIn("@keydown", grid.attrs)
        decade = self.soup.select_one(".year-grid-decade")
        self.assertEqual(decade.get("role"), "button")
        self.assertIn(":tabindex", decade.attrs)

    def test_the_result_count_is_announced(self):
        counts = self.soup.select(".result-count")
        self.assertTrue(counts)
        self.assertTrue(all(c.get("role") == "status" for c in counts))

    def test_platform_links_in_rows_are_labelled_buttons(self):
        buttons = self.soup.select("button[data-add-platforms]")
        self.assertTrue(buttons)
        self.assertTrue(
            all(b.get("aria-label", "").startswith("Filter by") for b in buttons)
        )
        self.assertFalse(self.soup.select("span[data-add-platforms]"))

    def test_the_mobile_sheet_is_a_modal_dialog(self):
        sheet = self.soup.select_one('[aria-labelledby="mobile-filters-title"]')
        self.assertEqual(sheet.get("role"), "dialog")
        self.assertEqual(sheet.get("aria-modal"), "true")
        self.assertIn("@keydown.escape.window", sheet.attrs)

    def test_saved_filter_dialogs_open_as_real_modals(self):
        dialogs = self.soup.select("dialog.modal[x-effect]")
        self.assertTrue(dialogs)
        for dialog in dialogs:
            self.assertIn("showModal()", dialog["x-effect"])
            self.assertIn("@close", dialog.attrs)
        self.assertNotIn("'modal-open':", str(self.soup))

    def test_icon_glyphs_are_hidden_from_screen_readers(self):
        icons = self.soup.select('span[class^="mdi"], span[class*=" mdi"]')
        self.assertTrue(icons)
        self.assertEqual([i for i in icons if i.get("aria-hidden") != "true"], [])


class NavigationAccessibilityTests(TestCase):
    def test_the_current_page_is_marked_in_the_navigation(self):
        clear_all_caches()
        soup = BeautifulSoup(self.client.get("/developers/").content, "html.parser")
        current = soup.select('a[aria-current="page"]')
        self.assertTrue(current)
        self.assertTrue(all("/developers/" in a["href"] for a in current))
        self.assertTrue(soup.select('nav[aria-label="Main"]'))
        # The Games section icon marks the current section, not the page
        self.assertTrue(soup.select('a[href="/"][aria-current="true"]'))

    def test_the_current_link_keeps_the_site_look(self):
        """DaisyUI 5 restyles a menu link carrying aria-current (neutral
        grey, a shadow, a noise texture) and outranks `.active`: adding
        aria-current turned the sidebar's green pill grey. Its knobs are set
        back to the site's primary, with no depth or noise."""
        css = (settings.BASE_DIR / "theme/static_src/src/styles.css").read_text()
        rule = re.search(r"aside \.menu li > a\[aria-current\] \{[^}]*\}", css)
        self.assertIsNotNone(rule)
        for declaration in (
            "--menu-active-bg: var(--color-primary)",
            "--menu-active-fg: var(--color-primary-content)",
            "--depth: 0",
            "--fx-noise: none",
        ):
            self.assertIn(declaration, rule.group(0))

    def test_the_skip_link_sits_above_the_mobile_header(self):
        css = (settings.BASE_DIR / "theme/static_src/src/styles.css").read_text()
        rule = re.search(r"\.skip-link \{[^}]*\}", css).group(0)
        self.assertIn("z-index: 100000", rule)


class AlpineBindingSyntaxTests(TestCase):
    """The keyboard bindings were added by script across many templates; one
    truncated an expression at a comma, and the mobile sheet threw a
    SyntaxError in the browser while every server-side test passed."""

    def test_every_added_binding_balances_its_parentheses(self):
        pattern = re.compile(
            r"(:aria-pressed|:aria-expanded|@keydown\.(?:enter|space)\.prevent)"
            r'="([^"]*)"'
        )
        unbalanced = []
        for app in ("games", "core", "music"):
            for path in (settings.BASE_DIR / app / "templates").rglob("*.html"):
                for match in pattern.finditer(path.read_text()):
                    expression = match.group(2)
                    if expression.count("(") != expression.count(")"):
                        unbalanced.append(f"{path.name}: {match.group(0)}")
        self.assertEqual(unbalanced, [])

    def test_no_attribute_was_written_inside_another(self):
        """The bulk aria-hidden edit once landed inside an Alpine :class
        value (`:class=" aria-hidden="true"allExpanded ? ...`), breaking the
        lists page's script in the browser only."""
        corrupted = []
        for app in ("games", "core", "music", "books"):
            for path in (settings.BASE_DIR / app / "templates").rglob("*.html"):
                text = path.read_text()
                if re.search(r'="\s*aria-hidden="', text):
                    corrupted.append(path.name)
        self.assertEqual(corrupted, [])

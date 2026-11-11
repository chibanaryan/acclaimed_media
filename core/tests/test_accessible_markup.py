"""What a control says about itself to someone who cannot see it.

Each of these was true of the page for a sighted reader with a mouse and not
otherwise: a selected filter shown by colour alone, a dialog with no name, a
search box named only by its placeholder, a card that ignored Ctrl+click.
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import User
from core.tests.utils import clear_all_caches
from games import models as games_models
from music import models as music_models
from music.tests.site import music_site

BASE = Path(settings.BASE_DIR)


def read(path):
    return (BASE / path).read_text(encoding="utf-8")


def pressed(expression):
    return f""":aria-pressed="{expression} ? 'true' : 'false'\""""


class _SignedInPage(TestCase):
    url_name = "home"

    def setUp(self):
        clear_all_caches()
        User.objects.create_user(username="reader", password="readerpass")
        self.client.login(username="reader", password="readerpass")
        self.make_rows()
        self.html = self.client.get(reverse(self.url_name)).content.decode()
        self.soup = BeautifulSoup(self.html, "html.parser")

    def make_rows(self):
        games_models.Game.objects.create(
            name="Doom", rank=1, slug="doom", year_of_release=1993
        )

    def assert_inputs_are_named(self):
        """A placeholder is not a name: it goes when the reader types."""
        unnamed = []
        inputs = self.soup.find_all("input", attrs={"type": ["text", "search"]})
        self.assertTrue(inputs)
        for field in inputs:
            if field.get("name") == "website" and field.get("tabindex") == "-1":
                continue  # the contact form's honeypot, hidden from everyone
            label = field.get("id") and self.soup.find(
                "label", attrs={"for": field["id"]}
            )
            if not field.get("aria-label") and not (
                label and label.get_text(strip=True)
            ):
                unnamed.append(str(field)[:120])
        self.assertEqual(unnamed, [])

    def assert_dialogs_are_named(self, expected):
        dialogs = self.soup.find_all("dialog")
        named = {}
        for dialog in dialogs:
            target = dialog.get("aria-labelledby")
            self.assertTrue(target, str(dialog)[:120])
            named[target] = dialog
        self.assertEqual(set(named), expected)
        return named


class GamesRankingsMarkupTests(_SignedInPage):
    def test_a_selected_toggle_says_so(self):
        """Each of these showed its state by a class alone."""
        for expression in (
            "viewMode === 'list'",
            "viewMode === 'grid'",
            "!(filters.played || []).length",
            "(filters.played || []).includes('yes')",
            "(filters.played || []).includes('want')",
            "(filters.played || []).includes('no')",
        ):
            with self.subTest(expression=expression):
                self.assertIn(pressed(expression), self.html)

    def test_the_view_toggle_says_so_at_both_widths(self):
        self.assertEqual(self.html.count(pressed("viewMode === 'list'")), 2)
        self.assertEqual(self.html.count(pressed("viewMode === 'grid'")), 2)

    def test_every_dialog_is_named_by_a_heading_on_the_page(self):
        named = self.assert_dialogs_are_named(
            {
                "contactModalTitle",
                "authModalTitle",
                "saveFilterModalTitle",
                "renameFilterModalTitle",
                "deleteFilterModalTitle",
            }
        )
        for target, dialog in named.items():
            if target == "authModalTitle":
                continue
            with self.subTest(target=target):
                headings = self.soup.find_all(id=target)
                self.assertEqual(len(headings), 1)
                self.assertTrue(dialog.find(id=target))
                self.assertTrue(headings[0].get_text(strip=True))

    def test_the_sign_in_dialog_is_named_before_and_after_its_content_loads(self):
        """Its heading arrives with whichever screen htmx loads into it, so
        until then `aria-labelledby` points at nothing and the label stands."""
        dialog = self.soup.find("dialog", id="authModal")
        self.assertEqual(dialog["aria-labelledby"], "authModalTitle")
        self.assertEqual(dialog["aria-label"], "Account")
        self.assertIsNone(self.soup.find(id="authModalTitle"))

    def test_every_text_input_has_a_name(self):
        self.assert_inputs_are_named()

    def test_the_mobile_search_button_says_whether_its_panel_is_open(self):
        self.assertIn(
            """:aria-expanded="showSearchDropdown ? 'true' : 'false'\"""", self.html
        )


class GamesEntityPagesMarkupTests(_SignedInPage):
    def test_the_developers_search_has_a_name(self):
        self.html = self.client.get(reverse("developers-list")).content.decode()
        self.soup = BeautifulSoup(self.html, "html.parser")
        self.assert_inputs_are_named()
        self.assertEqual(
            self.soup.find(id="developer-search")["aria-label"],
            "Search developers by name",
        )

    def test_the_source_lists_search_has_a_name(self):
        self.html = self.client.get(reverse("list-list")).content.decode()
        self.soup = BeautifulSoup(self.html, "html.parser")
        self.assert_inputs_are_named()
        self.assertEqual(
            self.soup.find(id="publication-search")["aria-label"],
            "Search publications",
        )


@music_site
class MusicMarkupTests(_SignedInPage):
    url_name = "music:home"

    def make_rows(self):
        music_models.Album.objects.create(
            name="Doolittle", rank=1, slug="doolittle", year_released=1989
        )

    def test_a_selected_toggle_says_so(self):
        for expression in (
            "viewMode === 'list'",
            "!(filters.listened || []).length",
            "(filters.listened || []).includes('own')",
            "(filters.listened || []).includes('yes')",
        ):
            with self.subTest(expression=expression):
                self.assertIn(pressed(expression), self.html)

    def test_every_dialog_is_named_by_a_heading_on_the_page(self):
        named = self.assert_dialogs_are_named(
            {
                "contactModalTitle",
                "authModalTitle",
                "saveFilterModalTitle",
                "renameFilterModalTitle",
                "deleteFilterModalTitle",
            }
        )
        for target in named:
            if target != "authModalTitle":
                self.assertEqual(len(self.soup.find_all(id=target)), 1, target)

    def test_every_text_input_has_a_name(self):
        self.assert_inputs_are_named()

    def test_the_shared_search_box_takes_its_name_from_the_page(self):
        for url_name, input_id, label in (
            ("music:artist-list", "artist-search", "Search artists by name"),
            ("music:list-list", "music-list-search", "Search publications"),
        ):
            with self.subTest(url_name=url_name):
                self.html = self.client.get(reverse(url_name)).content.decode()
                self.soup = BeautifulSoup(self.html, "html.parser")
                self.assert_inputs_are_named()
                self.assertEqual(self.soup.find(id=input_id)["aria-label"], label)


class FilterTreeMarkupTests(SimpleTestCase):
    """The genre and platform trees, which render only with rows to show.

    A category, a manufacturer and a form factor are each selected by a
    button beside the one that expands them, and its state was the row's
    background colour.
    """

    def test_each_select_button_says_whether_it_is_selected(self):
        for path, expression in (
            (
                "core/templates/core/includes/_genre_filter.html",
                "isCategorySelected(category.id)",
            ),
            (
                "core/templates/core/includes/_mobile_filter_genres.html",
                "isCategorySelected(category.id)",
            ),
            (
                "games/templates/includes/_platform_filter.html",
                "isManufacturerSelected(mfrKey)",
            ),
            (
                "games/templates/includes/_platform_filter.html",
                "isFormFactorSelected(mfrKey, ffKey)",
            ),
            (
                "games/templates/games/includes/_mobile_filter_platforms.html",
                "isManufacturerSelected(mfrKey)",
            ),
            (
                "games/templates/games/includes/_mobile_filter_platforms.html",
                "isFormFactorSelected(mfrKey, ffKey)",
            ),
        ):
            with self.subTest(path=path, expression=expression):
                self.assertEqual(read(path).count(pressed(expression)), 1)


class AuthModalHeadingTests(SimpleTestCase):
    def test_every_screen_carries_the_heading_the_dialog_is_named_by(self):
        partials = sorted((BASE / "games/templates/auth/partials").glob("*.html"))
        # Pieces included by a screen, not screens of their own
        pieces = {"_profile_games_stats.html", "_no_address.html"}
        screens = [p for p in partials if p.name not in pieces]
        self.assertEqual(len(screens), 8)
        for partial in screens:
            with self.subTest(partial=partial.name):
                source = partial.read_text(encoding="utf-8")
                self.assertEqual(source.count('<h3 id="authModalTitle"'), 1)


class ListenersDoNotPileUpTests(SimpleTestCase):
    """base.html rebuilds Alpine after a back/forward-cache restore, which
    runs every `x-init` again: a listener added there was added again each
    time. One Alpine binds itself (`@event.window`) it also removes."""

    def test_the_search_boxes_add_no_window_listener_of_their_own(self):
        for path in (
            "games/templates/includes/_sidebar.html",
            "games/templates/includes/_nav_mobile.html",
        ):
            with self.subTest(path=path):
                source = read(path)
                self.assertNotIn("addEventListener('reset-search-state'", source)
                # Nothing ever dispatched the event its four listeners
                # waited for; they went on 2026-11-10
                self.assertNotIn("reset-search-state", source)

    def test_the_filter_component_removes_every_window_listener_it_adds(self):
        source = read("games/static/games/js/filter-component.js")
        destroy = source[source.index("destroy() {") : source.index("init() {")]
        added = re.findall(
            r"window\.addEventListener\('([^']+)', this\.(_\w+Listener)\)", source
        )
        self.assertIn(("acclaimed:need-csf", "_needCsfListener"), added)
        for event, listener in added:
            with self.subTest(event=event):
                self.assertIn(
                    f"window.removeEventListener('{event}', this.{listener})", destroy
                )


class SearchBoxesCancelTests(SimpleTestCase):
    """Emptying a games search box went round `loadResults()`, which is
    where a request in flight is cancelled, so its results came back."""

    def test_every_search_input_goes_through_load_results(self):
        for path in (
            "games/templates/includes/_sidebar.html",
            "games/templates/includes/_nav_mobile.html",
        ):
            with self.subTest(path=path):
                source = read(path)
                self.assertEqual(
                    source.count('@input.debounce.300ms="loadResults()"'), 2
                )
                self.assertNotIn("developers = []", source)


class CardClickTests(SimpleTestCase):
    """A mobile row card is a `[data-href]`, navigated by one listener in
    base.html. It set `location.href` whatever was held down, and the middle
    button fires `auxclick`, which it never heard."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = read("games/templates/base.html")

    def test_a_modified_click_opens_a_tab_and_leaves_this_one(self):
        start = self.source.index(
            "document.addEventListener('click', function(e) {\n"
            "            if (e.button) return;"
        )
        handler = self.source[start : self.source.index("});", start)]
        modified = handler.index("if (e.ctrlKey || e.metaKey || e.shiftKey) {")
        opened = handler.index("window.open(href, '_blank', 'noopener');")
        returned = handler.index("return;", opened)
        navigated = handler.index("window.location.href = href;")
        self.assertLess(modified, opened)
        self.assertLess(opened, returned)
        self.assertLess(returned, navigated)

    def test_the_middle_button_opens_a_tab(self):
        start = self.source.index("document.addEventListener('auxclick'")
        handler = self.source[start : self.source.index("});", start)]
        self.assertIn("if (e.button !== 1) return;", handler)
        self.assertIn("window.open(href, '_blank', 'noopener')", handler)
        self.assertNotIn("location.href", handler)

    def test_a_click_on_a_link_or_button_inside_is_still_its_own(self):
        start = self.source.index("function cardHref(e) {")
        helper = self.source[start : self.source.index("\n        }", start)]
        self.assertIn("e.defaultPrevented", helper)
        self.assertIn(
            "closest('a, button, [data-add-platforms], [data-add-genre]')", helper
        )
        self.assertNotIn("row.dataset.href;\n        });", self.source)


class GridOverlayTests(SimpleTestCase):
    def test_the_overlay_shows_for_keyboard_focus_as_for_hover(self):
        """The developer, platforms and genres were behind `:hover` alone."""
        source = read("theme/static_src/src/styles.css")
        rule = source[source.index(".game-card-grid:hover .game-card-overlay,") :]
        selectors = rule[: rule.index("{")]
        for selector in (
            ".media-card-grid:hover .media-card-overlay",
            ".game-card-grid:focus-within .game-card-overlay",
            ".media-card-grid:focus-within .media-card-overlay",
        ):
            self.assertIn(selector, selectors)

    def test_the_built_stylesheet_has_it(self):
        built = read("theme/static/css/dist/styles.css")
        self.assertIn(".game-card-grid:focus-within .game-card-overlay", built)
        self.assertIn(".media-card-grid:focus-within .media-card-overlay", built)


class ReadableTextTests(SimpleTestCase):
    """`text-base-content/50` is 3.2-3.3:1 on the light theme's backgrounds.
    /65 is the lowest step that clears 4.5:1 on all three of them in both
    themes (4.99:1 at worst, light theme on base-300)."""

    def test_all_results_loaded_reads_the_same_from_server_and_client(self):
        opening = '<div class="text-base-content/65 text-sm">'
        icon = '<span class="mdi mdi-check-circle-outline" aria-hidden="true"></span>'
        for path in (
            "games/templates/games/includes/_game_list_results.html",
            "music/templates/music/includes/_album_load_more.html",
            "games/static/games/js/game-list-renderer.js",
            "games/static/games/js/utils-loadmore.js",
        ):
            with self.subTest(path=path):
                source = read(path)
                at = source.index("results loaded</span>")
                before = re.sub(r"\s+", " ", source[at - 400 : at])
                self.assertIn(f"{opening} {icon} <span>All ", before)

    def test_the_listed_text_is_no_longer_half_opacity(self):
        for path in ("core/templates/core/includes/_saved_filters_dropdown.html",):
            with self.subTest(path=path):
                self.assertNotIn("text-base-content/50", read(path))

    def test_text_a_reader_needs_is_not_at_forty_or_fifty_percent(self):
        """The fine print, hints and empty states left at /50 and /40 after
        2026-11-10's pass, and the icon-only expand buttons, whose glyph is
        all there is to see. Not a disabled control, nor a decorative icon."""
        faint = re.compile(r"text-base-content/(?:40|50)\b")
        for path in (
            "core/templates/core/includes/_mobile_filter_genres.html",
            "core/templates/core/includes/_mobile_saved_filters.html",
            "games/templates/games/includes/_mobile_filter_platforms.html",
            "games/templates/games/includes/_mobile_filter_sheet.html",
            "games/templates/auth/partials/_forgot_password_sent.html",
            "games/templates/auth/partials/_unverified_email.html",
            "games/templates/auth/partials/_verification_resent.html",
            "games/templates/auth/partials/_verification_sent.html",
            "games/templates/auth/partials/_profile_games_stats.html",
            "games/templates/auth/partials/_signup_form.html",
            "games/templates/developers/includes/_developer_row.html",
            "games/templates/import.html",
            "music/templates/music/home.html",
        ):
            with self.subTest(path=path):
                self.assertIsNone(faint.search(read(path)))
        # The one control left faint in each is disabled until a filter is on
        for path in (
            "games/templates/includes/_advanced_filters.html",
            "core/templates/core/includes/_saved_filters_dropdown.html",
        ):
            with self.subTest(path=path):
                lines = [line for line in read(path).splitlines() if faint.search(line)]
                self.assertEqual(len(lines), 1)
                self.assertIn("cursor-not-allowed", lines[0])
        self.assertIn(
            '<span class="text-xs mt-2 text-base-content/65">No cover art yet</span>',
            read("music/templates/music/album_detail.html"),
        )


class ImportPageMessagesTests(SimpleTestCase):
    def test_no_message_is_interpolated_into_markup(self):
        """An import error names the uploaded file, and the name was read as
        HTML: `innerHTML` built from a template literal with a value in it."""
        source = read("games/templates/import.html")
        literals = re.findall(r"innerHTML\s*\+?=\s*`([^`]*)`", source)
        self.assertTrue(literals)
        self.assertEqual([text for text in literals if "${" in text], [])
        self.assertIn("errorRow.textContent = errorMsg", source)


class RemovedCodeStaysRemovedTests(SimpleTestCase):
    def test_the_year_preview_listener_is_gone(self):
        """It toggled `.year-preview` on `.game-year[data-year]`: no element
        has had that class or attribute, and no rule styled the result."""
        for path in (
            "games/static/games/js/utils-base.js",
            "games/static/games/js/utils-base.min.js",
            "games/static/games/js/filter-component.js",
            "games/static/games/js/filter-component.min.js",
        ):
            with self.subTest(path=path):
                self.assertNotIn("YearPreview", read(path))

    def test_nor_is_the_event_it_listened_for_sent(self):
        """The year grid went on dispatching `year-preview` on every drag
        step, to nothing."""
        for path in (
            "core/static/core/js/filter-subcomponents.js",
            "core/static/core/js/filter-subcomponents.min.js",
        ):
            with self.subTest(path=path):
                self.assertNotIn("year-preview", read(path))

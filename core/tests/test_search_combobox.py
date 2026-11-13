"""The search boxes are comboboxes: arrow keys, an active option, a name
for the popup.

Until 2026-11-10 each was a field followed by a list of links, with no way
from the field to a result but Tab. The behaviour is `searchComboboxState`
in utils-base.js, spread into both search components and run here under
Node on the real files; the markup is the WAI-ARIA combobox pattern with a
grouped listbox. Never heard on a real screen reader, and not planned to
be (ROADMAP, "Known, not planned").
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.tests.node import require_node, run_node
from core.tests.utils import clear_all_caches, get_on_site, select_all
from core import sites

BASE = Path(settings.BASE_DIR)
TEMPLATES = (
    "games/templates/includes/_sidebar.html",
    "games/templates/includes/_nav_mobile.html",
)
COMBOBOX = "core/templates/core/includes/_search_combobox.html"
# Each site's option rows, by the name the include is given
OPTIONS = ("includes/_search_options.html", "music/includes/_search_options.html")


class SearchComboboxBehaviourTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_node()
        cls.output = run_node("search_combobox.js")

    def each(self):
        for site in ("games", "music"):
            with self.subTest(site=site):
                yield self.output[site]

    def test_nothing_is_active_to_start_with(self):
        for result in self.each():
            self.assertEqual(result["startsWithNone"], "")

    def test_no_results_is_no_active_option(self):
        for result in self.each():
            self.assertEqual(result["noListbox"], {"active": "", "entered": False})
            self.assertEqual(result["noOptions"], "")

    def test_the_arrow_keys_move_through_the_results_and_wrap(self):
        for result in self.each():
            self.assertEqual(
                result["steps"],
                [
                    ["results-option-0", "first"],
                    ["results-option-1", "second"],
                    ["results-option-2", "third"],
                    ["results-option-0", "first"],  # down past the end
                    ["results-option-2", "third"],  # up past the top
                    ["results-option-1", "second"],
                ],
            )
            self.assertEqual(
                result["ids"],
                ["results-option-0", "results-option-1", "results-option-2"],
            )
            # One option is selected; the others say they are not
            self.assertEqual(result["unselected"], ["false", "true", "false"])

    def test_up_from_the_field_starts_at_the_last_result(self):
        for result in self.each():
            self.assertEqual(result["upFirst"], "third")

    def test_enter_follows_the_active_option(self):
        for result in self.each():
            self.assertIs(result["entered"], True)
            self.assertEqual(result["prevented"], 1)
            self.assertEqual(result["clicked"], ["third"])

    def test_enter_with_no_active_option_is_left_to_the_full_search(self):
        for result in self.each():
            self.assertEqual(result["cleared"], {"active": "", "selected": []})
            self.assertIs(result["enteredWithNone"], False)
            self.assertEqual(result["preventedAfter"], 1)

    def test_a_new_query_or_the_clear_button_forgets_the_active_option(self):
        """The results under it are changing, and a keyed loop keeps the
        elements: one left selected would be an option nobody chose."""
        for result in self.each():
            self.assertEqual(result["afterNewQuery"], {"active": "", "selected": []})
            self.assertEqual(result["afterReset"], {"active": "", "selected": []})

    def test_ids_follow_the_positions_as_they_are_now(self):
        for result in self.each():
            self.assertEqual(
                result["renumbered"], ["results-option-0", "results-option-1"]
            )
            self.assertIs(result["scrolledNearest"], True)


class SearchComboboxMarkupTests(SimpleTestCase):
    """The pattern is written once, in `core/includes/_search_combobox.html`,
    for all four boxes. Each of the two templates carried two copies of it
    until 2026-11-12: every attribute below, four times."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.include = (BASE / COMBOBOX).read_text(encoding="utf-8")
        # Up to the attribute it ends on: the handlers hold a ">"
        cls.fields = re.findall(r'<input .*?autocomplete="off">', cls.include, re.S)

    def test_there_is_one_field_and_it_is_the_shared_one(self):
        self.assertEqual(len(self.fields), 1)
        self.assertIn('role="combobox"', self.fields[0])
        for path in TEMPLATES:
            with self.subTest(path=path):
                source = (BASE / path).read_text(encoding="utf-8")
                self.assertNotIn('role="combobox"', source)
                self.assertNotIn('role="listbox"', source)
                self.assertEqual(
                    source.count("{% include 'core/includes/_search_combobox.html'"), 2
                )

    def test_each_box_is_given_its_own_id_and_its_sites_options(self):
        for path, input_id in zip(TEMPLATES, ("sidebar-search", "nav-search-mobile")):
            source = (BASE / path).read_text(encoding="utf-8")
            includes = re.findall(
                r"{% include 'core/includes/_search_combobox.html' with (.*?) %}",
                source,
            )
            with self.subTest(path=path):
                self.assertEqual(
                    [f"input_id='{input_id}'" in props for props in includes],
                    [True, True],
                )
                self.assertEqual(
                    sorted(
                        re.search(r"options_template='([^']+)'", props).group(1)
                        for props in includes
                    ),
                    sorted(OPTIONS),
                )

    def test_the_field_is_a_combobox_that_names_its_listbox(self):
        field = self.fields[0]
        self.assertIn('aria-controls="{{ input_id }}-results"', field)
        self.assertEqual(
            self.include.count('role="listbox" id="{{ input_id }}-results"'), 1
        )
        self.assertIn('aria-autocomplete="list"', field)
        self.assertIn(":aria-expanded=", field)
        self.assertIn(':aria-activedescendant="activeOption || false"', field)

    def test_the_arrow_keys_escape_and_enter_are_bound(self):
        field = self.fields[0]
        self.assertIn('@keydown.down.prevent="showMenu = true; moveOption(1)"', field)
        self.assertIn('@keydown.up.prevent="showMenu = true; moveOption(-1)"', field)
        self.assertIn("@keydown.escape=", field)
        # Typing forgets the active option at once. Left to the
        # debounced search, Enter within 300 ms of the last key
        # followed the option of the query before
        self.assertIn('@input="showMenu = true; clearActiveOption()"', field)
        # Enter with nothing active is still the full search
        self.assertRegex(
            field,
            r'@keydown\.enter="if \(!activateOption\(\$event\) && '
            r"q\.trim\(\)\.length >= 2\) window\.location\.href = ",
        )

    def test_where_enter_goes_is_written_as_code_not_text(self):
        """The address sits inside an Alpine expression (AGENTS.md, "A value
        in an Alpine expression is code")."""
        self.assertIn("'{{ enter_url|escapejs }}?q='", self.fields[0])

    def test_the_listbox_holds_one_group_looped_over(self):
        soup = BeautifulSoup(self.include, "html.parser")
        listboxes = select_all(soup, '[role="listbox"]')
        self.assertEqual(len(listboxes), 1)
        # The group is an x-for's body, and the hints are in x-ifs
        groups = select_all(listboxes[0], 'ul[role="group"]')
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0].has_attr(":aria-label"))
        self.assertIn("{% include options_template %}", str(groups[0]))
        # The hints ("Enter 2+ characters") are a list of their own
        self.assertFalse(select_all(listboxes[0], ".disabled"))
        self.assertEqual(len(select_all(soup, ".disabled")), 3)

    def test_a_sites_options_are_options_and_nothing_else(self):
        """Nothing in a listbox is a bare list item, which it may not own:
        wrappers are role="none", titles hidden."""
        for path in OPTIONS:
            with self.subTest(path=path):
                source = next(
                    found.read_text(encoding="utf-8")
                    for found in BASE.glob(f"*/templates/{path}")
                )
                soup = BeautifulSoup(source, "html.parser")
                links = soup.find_all("a")
                self.assertGreaterEqual(len(links), 4)
                self.assertEqual(
                    [link.get("role") for link in links], ["option"] * len(links)
                )
                self.assertEqual(
                    {item.get("role") for item in soup.find_all("li")},
                    {"none", "presentation"},
                )
                # Every row here is in an x-if or an x-for
                self.assertFalse(select_all(soup, ".disabled"))

    def test_an_item_with_no_year_shows_none_and_no_separator(self):
        """A game's rows read "null • #12" and "Name (null)" for one; an
        album's compact row, " • #12", a separator with nothing before it."""
        games = (BASE / "games/templates/includes/_search_options.html").read_text()
        music = next(BASE.glob("*/templates/music/includes/_search_options.html"))
        self.assertIn(
            "(result.year_of_release ? result.year_of_release + ' &bull; ' : '')"
            " + '#' + result.rank",
            games,
        )
        self.assertIn(
            "(result.year_of_release ? ' (' + result.year_of_release + ')' : '')",
            games,
        )
        self.assertIn(
            "(album.year_released ? album.year_released + ' &bull; ' : '')"
            " + '#' + album.rank",
            music.read_text(),
        )
        for source in (games, music.read_text()):
            self.assertNotIn("|| '') + ' &bull;", source)


class SearchComboboxPageTests(TestCase):
    def setUp(self):
        clear_all_caches()

    def check(self, html):
        soup = BeautifulSoup(html, "html.parser")
        fields = select_all(soup, 'input[role="combobox"]')
        # The sidebar's and the mobile bar's
        self.assertEqual(len(fields), 2)
        ids = [field["aria-controls"] for field in fields]
        self.assertEqual(len(set(ids)), 2)
        for field in fields:
            listbox = soup.find(id=field["aria-controls"])
            self.assertEqual(listbox.get("role"), "listbox")
            self.assertTrue(listbox.get("aria-label"))
            # A name of its own, beside the role
            self.assertTrue(field.get("aria-label"))

    def test_the_games_pages_boxes(self):
        self.check(self.client.get(reverse("home")).content.decode())

    def test_the_music_pages_boxes(self):
        self.check(get_on_site(self.client, sites.MUSIC, "music:home").content.decode())

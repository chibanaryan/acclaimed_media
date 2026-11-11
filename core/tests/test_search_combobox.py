"""The search boxes are comboboxes: arrow keys, an active option, a name
for the popup.

Until 2026-11-10 each was a field followed by a list of links, with no way
from the field to a result but Tab. The behaviour is `searchComboboxState`
in utils-base.js, spread into both search components and run here under
Node on the real files; the markup is the WAI-ARIA combobox pattern with a
grouped listbox. Not yet heard on a real screen reader:
docs/ASSISTIVE_TECH_CHECKLIST.md has the steps.
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.tests.node import require_node, run_node
from core.tests.utils import clear_all_caches, get_on_site
from core import sites

BASE = Path(settings.BASE_DIR)
TEMPLATES = (
    "games/templates/includes/_sidebar.html",
    "games/templates/includes/_nav_mobile.html",
)


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
    """Each template holds two boxes, one a site: the same pattern in all."""

    def boxes(self):
        for path in TEMPLATES:
            source = (BASE / path).read_text(encoding="utf-8")
            # Up to the attribute each ends on: the handlers hold a ">"
            inputs = [
                tag
                for tag in re.findall(r'<input .*?autocomplete="off">', source, re.S)
                if 'role="combobox"' in tag
            ]
            with self.subTest(path=path):
                self.assertEqual(len(inputs), 2)
                yield source, inputs

    def test_the_field_is_a_combobox_that_names_its_listbox(self):
        for source, inputs in self.boxes():
            for field in inputs:
                controls = re.search(r'aria-controls="([^"]+)"', field).group(1)
                self.assertEqual(source.count(f'role="listbox" id="{controls}"'), 2)
                self.assertIn('aria-autocomplete="list"', field)
                self.assertIn(":aria-expanded=", field)
                self.assertIn(':aria-activedescendant="activeOption || false"', field)

    def test_the_arrow_keys_escape_and_enter_are_bound(self):
        for _source, inputs in self.boxes():
            for field in inputs:
                self.assertIn(
                    '@keydown.down.prevent="showMenu = true; moveOption(1)"', field
                )
                self.assertIn(
                    '@keydown.up.prevent="showMenu = true; moveOption(-1)"', field
                )
                self.assertIn("@keydown.escape=", field)
                # Enter with nothing active is still the full search
                self.assertRegex(
                    field,
                    r'@keydown\.enter="if \(!activateOption\(\$event\) && '
                    r"q\.trim\(\)\.length >= 2\) window\.location\.href = ",
                )

    def test_a_listbox_holds_groups_of_options_and_nothing_else(self):
        for path in TEMPLATES:
            soup = BeautifulSoup(
                (BASE / path).read_text(encoding="utf-8"), "html.parser"
            )
            listboxes = soup.select('[role="listbox"]')
            with self.subTest(path=path):
                self.assertEqual(len(listboxes), 2)
            for listbox in listboxes:
                with self.subTest(path=path, listbox=listbox["id"]):
                    links = listbox.find_all("a")
                    self.assertGreaterEqual(len(links), 4)
                    self.assertEqual(
                        [link.get("role") for link in links], ["option"] * len(links)
                    )
                    groups = listbox.select('ul[role="group"]')
                    self.assertEqual(len(groups), 1)  # one, looped over
                    self.assertTrue(groups[0].has_attr(":aria-label"))
                    # Nothing in it is a bare list item, which a listbox
                    # may not own: wrappers are role="none", titles hidden
                    self.assertEqual(
                        {item.get("role") for item in listbox.find_all("li")},
                        {"none", "presentation"},
                    )
                    # The hints ("Enter 2+ characters") are a list of their own
                    self.assertFalse(listbox.select(".disabled"))


class SearchComboboxPageTests(TestCase):
    def setUp(self):
        clear_all_caches()

    def check(self, html):
        soup = BeautifulSoup(html, "html.parser")
        fields = soup.select('input[role="combobox"]')
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

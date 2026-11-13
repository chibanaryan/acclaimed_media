"""The tracking button's dropdown is a menu, and is walked like one.

Music's status button said `aria-haspopup` from the day it was written,
and what it opened had no role and took no key: a list of buttons a
keyboard reader tabbed through, and a screen reader was promised a menu and
given none. Games' shared menu (`played-menu.js`) has had both since
2026-11-11. The keys are `core/static/core/js/media-tracking.js`, run here
under Node on the real file.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from core.tests.node import require_node, run_node

BASE = Path(settings.BASE_DIR)
TEMPLATES = (
    "core/templates/core/includes/_tracking_button.html",
    "core/templates/core/includes/_tracking_button_template.html",
)


class TrackingMenuKeysTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_node()
        cls.out = run_node("tracking_menu.js")

    def assert_moved(self, name, to):
        self.assertEqual(
            self.out[name], {"focus": to, "prevented": True, "dispatched": []}, name
        )

    def assert_left_alone(self, name, on):
        self.assertEqual(
            self.out[name], {"focus": on, "prevented": False, "dispatched": []}, name
        )

    def test_the_arrows_walk_the_items_and_wrap(self):
        self.assert_moved("downFromAnItem", "item1")
        self.assert_moved("downWraps", "item0")
        self.assert_moved("upWraps", "item2")

    def test_home_and_end_go_to_the_ends(self):
        self.assert_moved("home", "item0")
        self.assert_moved("end", "item2")

    def test_an_arrow_on_the_button_of_an_open_menu_enters_it(self):
        self.assert_moved("downFromTheButtonOfAnOpenMenu", "item0")
        self.assert_moved("upFromTheButtonOfAnOpenMenu", "item2")

    def test_where_each_key_goes(self):
        self.assertEqual(
            self.out["nextIndex"],
            {
                "downFromFirst": 1,
                "downFromLast": 0,
                "downFromTheButton": 0,
                "upFromFirst": 2,
                "upFromLast": 1,
                "upFromTheButton": 2,
                "home": 0,
                "end": 2,
            },
        )

    def test_tab_leaves_the_menu_for_its_button_and_closes_it(self):
        """The items are still on screen while the menu fades, so the
        browser's own Tab would land on the next of them."""
        self.assertEqual(
            self.out["tabInTheMenu"],
            {
                "focus": "trigger",
                "prevented": True,
                "dispatched": ["close-tracking-dropdowns"],
            },
        )

    def test_escape_puts_focus_back_on_the_button(self):
        """Alpine closes the menu; the focus it held would be nowhere."""
        self.assert_left_alone("escapeInTheMenu", "trigger")

    def test_tab_and_escape_on_the_button_are_the_browsers(self):
        self.assert_left_alone("tabOnTheButton", "trigger")
        self.assert_left_alone("escapeOnTheButton", "trigger")

    def test_an_arrow_on_a_closed_button_opens_it(self):
        self.assertEqual(
            self.out["downOnAClosedButton"],
            {"focus": "trigger", "prevented": True, "dispatched": [], "clicks": 1},
        )
        self.assertEqual(self.out["upOnAClosedButton"]["clicks"], 2)

    def test_an_arrow_never_marks_in_quick_mark_mode(self):
        """With a quick-mark mode on, a click on the button applies the
        picked status and opens nothing. An arrow that opened the menu by
        clicking would have marked the album Heard, and the next press
        cleared it: the key scrolls the page, as it did before the menu
        took keys."""
        self.assertEqual(
            self.out["downOnAClosedButtonInQuickMark"],
            {"focus": "trigger", "prevented": False, "dispatched": [], "clicks": 0},
        )

    def test_quick_mark_in_another_scope_does_not_stop_the_arrow(self):
        self.assertEqual(
            self.out["downOnAClosedButtonInAnotherScope"],
            {"focus": "trigger", "prevented": True, "dispatched": [], "clicks": 1},
        )

    def test_home_on_a_closed_button_still_scrolls_the_page(self):
        self.assertEqual(
            self.out["homeOnAClosedButton"],
            {"focus": "trigger", "prevented": False, "dispatched": [], "clicks": 2},
        )

    def test_keys_elsewhere_are_not_touched(self):
        self.assert_left_alone("anotherKeyInTheMenu", "item1")
        self.assert_left_alone("keyOutsideAnyButton", "elsewhere")
        self.assert_left_alone("keyOnSomethingElseInTheWrapper", "stray")
        self.assertEqual(
            self.out["keyOnTheDocument"], {"prevented": False, "dispatched": []}
        )

    def test_a_menu_opened_from_the_keyboard_starts_on_its_first_item(self):
        """Enter or Space on the button is a click whose `detail` is 0. It
        waits a frame at a time for Alpine to show the list."""
        self.assertEqual(self.out["framesWaitedFor"], 1)
        self.assertEqual(self.out["keyboardOpenFocuses"], "item0")

    def test_a_pointer_leaves_focus_where_it_is(self):
        self.assertEqual(
            self.out["pointerOpenLeavesFocus"], {"focus": "trigger", "frames": 0}
        )

    def test_closing_from_the_keyboard_moves_nothing(self):
        self.assertEqual(
            self.out["keyboardCloseLeavesFocus"], {"focus": "trigger", "frames": 0}
        )
        self.assertEqual(
            self.out["aClickOnAnItemIsNotTheButtons"], {"focus": "item0", "frames": 0}
        )

    def test_a_menu_that_never_shows_is_given_up_on(self):
        """Quick-mark mode takes the click and opens nothing."""
        self.assertEqual(self.out["givesUpAfter"], 10)
        self.assertEqual(self.out["focusWhenItNeverShowed"], "trigger")


class TrackingMenuMarkupTests(SimpleTestCase):
    def test_the_button_and_its_clone_twin_are_menus(self):
        """`role="menu"` owns `menuitem`s alone, so each `<li>` between
        them is `role="none"`."""
        for path in TEMPLATES:
            with self.subTest(path=path):
                source = (BASE / path).read_text()
                self.assertEqual(
                    source.count('role="menu" aria-label="Change status"'), 1
                )
                self.assertEqual(source.count('aria-haspopup="true"'), 1)
                rows = re.findall(r"<li\b[^>]*>", source)
                self.assertEqual(len(rows), 4)
                for row in rows:
                    self.assertIn('role="none"', row)
                self.assertEqual(
                    len(re.findall(r'<button type="button" role="menuitem"', source)),
                    4,
                )

    def test_the_minified_script_has_the_keys(self):
        """The pages load only the minified copy."""
        minified = (BASE / "core/static/core/js/media-tracking.min.js").read_text()
        for needle in ('"ArrowDown"', '[role="menuitem"]', "close-tracking-dropdowns"):
            self.assertIn(needle, minified)

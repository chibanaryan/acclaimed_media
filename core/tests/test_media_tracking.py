"""Source-level contract for `core/static/core/js/media-tracking.js`.

Two mistakes in this file cost an afternoon and neither showed up in any
Python test, because both only appear once a real browser runs HTMX: the
listener read the swapped-away element, and the album page's filter
suppressor cancelled the toggle. They are pinned here the way
`music/tests/test_visual_regression.py` pins the renderer's slots - by
reading the source - because the alternative is a browser in the test suite.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TRACKING_JS = Path(settings.BASE_DIR) / "core/static/core/js/media-tracking.js"


class MediaTrackingSourceTests(SimpleTestCase):
    def setUp(self):
        self.source = TRACKING_JS.read_text()

    def test_it_listens_after_the_request_not_after_the_swap(self):
        # With hx-swap="outerHTML" the swap replaces the target, so by
        # htmx:afterSwap `detail.target` is the detached old element and
        # still carries the pre-swap data-status. Listening there left the
        # id Sets one toggle behind for ever, and the status filter with
        # them.
        self.assertIn("'htmx:afterRequest'", self.source)
        self.assertNotIn("addEventListener('htmx:afterSwap'", self.source)

    def test_it_ignores_a_failed_toggle(self):
        # A rejected POST changed nothing on the server, so it must not
        # change the Sets either.
        self.assertIn("detail.successful", self.source)

    def test_it_takes_the_new_status_from_the_request(self):
        # Not from the DOM: the replaced element holds the old status and so
        # does its desktop/mobile twin, so neither says what just happened.
        self.assertIn("_requestedStatus", self.source)
        self.assertIn("status=", self.source)

    def test_it_mirrors_from_the_freshly_rendered_wrapper(self):
        # Copying from the event's target would paint the old icon onto the
        # twin. The fresh one is the attached wrapper already reading the
        # new status.
        self.assertIn("dataset.status === status", self.source)

    def test_it_matches_twins_on_size(self):
        # Otherwise a detail page's large button writes its oversized icon
        # into a list row, which is what games' version does.
        self.assertIn("dataset.size", self.source)

    def test_it_knows_nothing_about_any_one_section(self):
        # The scope registry is the whole point: games and books can adopt
        # this file without it learning their nouns. Comments are stripped
        # first - the usage example in the docstring names albums, which is
        # documentation, not coupling.
        code = re.sub(r"/\*.*?\*/", "", self.source, flags=re.S)
        code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
        for noun in ("album", "Album", "game", "Game", "book", "Book"):
            with self.subTest(noun=noun):
                self.assertNotIn(noun, code)

    def test_a_status_is_added_to_its_own_set_and_removed_from_the_rest(self):
        # The states are exclusive and a section may have any number of them
        # (music has three), so the Sets are a status -> Set map rather than
        # a done/want pair: anything else needs a branch per state.
        self.assertIn("config.sets", self.source)
        update = self.source.split("_updateSets(config, itemId, status) {", 1)[1]
        update = update.split("_mirrorTwins", 1)[0]
        self.assertIn("setStatus === status", update)
        self.assertIn("ids.add(itemId)", update)
        self.assertIn("ids.delete(itemId)", update)

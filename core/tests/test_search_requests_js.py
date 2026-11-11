"""The search boxes' requests, answered out of order.

Run under Node on the real files (games' `createUnifiedSearchData` in
utils-base.js, music's `createMediaSearchData` in media-search.js): what is
tested is which of two answers ends up on screen, which a source-text test
cannot see.
"""

from django.test import SimpleTestCase

from core.tests.node import require_node, run_node

SHOWN = {"names": ["for beatles"], "loading": False}
EMPTY = {"names": [], "loading": False}


class SearchRequestOrderTests(SimpleTestCase):
    """`aborting` is a browser's fetch, which rejects when its signal is
    aborted. `deaf` ignores the signal and answers anyway: a response that
    was already being read when the newer request went out."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_node()
        cls.output = run_node("search_requests.js")

    def each_box(self):
        for section in ("games", "music"):
            for mode in ("aborting", "deaf"):
                yield section, mode, self.output[section]

    def test_a_slower_older_answer_does_not_replace_the_newer_one(self):
        """Neither factory aborted anything or counted its requests, so the
        answer for "be", arriving after the one for "beatles", was shown
        under a box that said "beatles"."""
        for section, mode, output in self.each_box():
            with self.subTest(section=section, mode=mode):
                self.assertEqual(output[mode + "Overtaken"]["after"], SHOWN)

    def test_every_request_carries_a_signal(self):
        for section, mode, output in self.each_box():
            with self.subTest(section=section, mode=mode):
                self.assertTrue(output[mode + "Overtaken"]["sentSignals"])

    def test_an_aborted_request_leaves_loading_to_the_newer_one(self):
        """The older request's `finally` must not say the search is over
        while the one that replaced it is still out."""
        for section, mode, output in self.each_box():
            with self.subTest(section=section, mode=mode):
                self.assertEqual(
                    output[mode + "Overtaken"]["whileNewerIsOut"],
                    {"names": [], "loading": True},
                )

    def test_emptying_the_box_cancels_the_request_in_flight(self):
        """Under two characters there is nothing to search for, and the
        results of the request still out came back into the emptied box."""
        for section, mode, output in self.each_box():
            with self.subTest(section=section, mode=mode):
                self.assertEqual(output[mode + "Cleared"], EMPTY)

    def test_a_reset_cancels_the_request_in_flight(self):
        for section, mode, output in self.each_box():
            with self.subTest(section=section, mode=mode):
                self.assertEqual(output[mode + "Reset"], EMPTY)

    def test_a_search_on_its_own_is_answered_as_before(self):
        for section in ("games", "music"):
            with self.subTest(section=section):
                output = self.output[section]
                self.assertEqual(
                    output["alone"], {"loadingWhileOut": True, "after": SHOWN}
                )
                self.assertEqual(output["failed"], EMPTY)
                # Which the box says, where it read "No results found"
                self.assertIs(output["failedFlag"], True)
                self.assertIs(output["failedThenAnswered"], False)

    def test_two_boxes_on_a_page_do_not_abort_each_other(self):
        """The sidebar and the mobile bar each make their own component."""
        for section in ("games", "music"):
            with self.subTest(section=section):
                self.assertEqual(
                    self.output[section]["twoBoxes"],
                    [
                        {"names": ["for abbey"], "loading": False},
                        {"names": ["for revolver"], "loading": False},
                    ],
                )

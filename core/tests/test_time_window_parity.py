"""The heading's time window reads the same from the server and the client.

The server composes it for the first render and the client rebuilds it after
a filter change, so if they drift one heading shows until a reload. Only
running the real functions can tell: a test of the source would pass with the
branches in the wrong order.
"""

import json
from django.test import SimpleTestCase

from core.services import titles
from core.tests.node import require_node, run_node

CASES = [
    (1970, 2026, 1970, 2026),  # all of it
    (1960, 2029, 1970, 2026),  # past both ends, as a drag across every row
    (1975, 1975, 1970, 2026),  # one year
    (1990, 1999, 1970, 2026),  # a decade
    (2020, 2029, 1970, 2026),  # the last decade, which ends past the last year
    (2020, 2026, 1970, 2026),  # stopped at it, which is no decade pick
    (1950, 1959, 1952, 2019),  # a first decade that starts part way through
    (1985, 2003, 1970, 2026),  # a plain range
    (1990, 2029, 1970, 2026),  # a range past the last year
    (1960, 1985, 1971, 2026),  # and before the first
    (2026, 2029, 1970, 2026),  # down to one year there is
    (1960, 1979, 1970, 2026),  # two decades, stopped at the first year
    (1900, 1950, 1970, 2026),  # nothing there: says what was asked for
    (2027, 2035, 1970, 2026),
]


class TimeWindowParityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_node()
        cls.output = run_node("time_window.js", json.dumps(CASES))
        cls.expected = [titles.build_time_window(*case) for case in CASES]

    def test_the_client_matches_the_server(self):
        self.assertEqual(self.output["windows"], self.expected)

    def test_the_tab_title_window_matches_the_server(self):
        # A filtered page's tab title names the window too, without the
        # article and without "All Time", which filters nothing.
        expected = [titles.short_time_window(*case) for case in CASES]
        self.assertEqual(self.output["shortWindows"], expected)
        self.assertEqual(expected[:4], ["", "", "1975", "1990s"])

    def test_the_tab_title_joins_the_facets_as_the_server_does(self):
        self.assertEqual(
            self.output["shortTitle"],
            titles.short_title(["Rock", "", "1990s", None, "Heard"]),
        )
        self.assertEqual(self.output["shortTitle"], "Rock \u00b7 1990s \u00b7 Heard")

    def test_the_cases_mean_what_they_say(self):
        self.assertEqual(
            self.expected,
            [
                "All Time",
                "All Time",
                "1975",
                "the 1990s",
                "the 2020s",
                "2020-2026",
                "the 1950s",
                "1985-2003",
                "1990-2026",
                "1971-1985",
                "2026",
                "1970-1979",
                "1900-1950",
                "2027-2035",
            ],
        )

    def test_a_range_past_both_ends_is_no_year_in_a_clean_url(self):
        self.assertEqual(self.output["cleanUrlPastTheLastYear"], "/games/rock/")
        self.assertIsNone(self.output["cleanUrlOfARealRange"])

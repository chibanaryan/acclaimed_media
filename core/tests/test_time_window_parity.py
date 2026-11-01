"""The heading's time window reads the same from the server and the client.

The server composes it for the first render and two scripts rebuild it after
a filter change, so a copy that drifts shows one heading until a reload. Only
running the real functions can tell: a test of the source would pass with the
branches in the wrong order.
"""

import json
import unittest

from django.test import SimpleTestCase

from core.services import titles
from core.tests.node import node_available, run_node

CASES = [
    (1970, 2026, 1970, 2026),  # all of it
    (1960, 2029, 1970, 2026),  # past both ends, as a drag across every row
    (1975, 1975, 1970, 2026),  # one year
    (1990, 1999, 1970, 2026),  # a decade
    (2020, 2029, 1970, 2026),  # the last decade, which ends past the last year
    (1985, 2003, 1970, 2026),  # a plain range
    (1990, 2029, 1970, 2026),  # a range past the last year
    (1960, 1985, 1971, 2026),  # and before the first
    (2026, 2029, 1970, 2026),  # down to one year there is
    (1900, 1950, 1970, 2026),  # nothing there: says what was asked for
    (2027, 2035, 1970, 2026),
]


class TimeWindowParityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not node_available():
            raise unittest.SkipTest("Node is not installed")
        cls.output = run_node("time_window.js", json.dumps(CASES))
        cls.expected = [titles.build_time_window(*case) for case in CASES]

    def test_the_shared_client_copy_matches_the_server(self):
        self.assertEqual(self.output["shared"], self.expected)

    def test_games_own_copy_matches_the_server(self):
        self.assertEqual(self.output["games"], self.expected)

    def test_the_cases_mean_what_they_say(self):
        self.assertEqual(
            self.expected,
            [
                "All Time",
                "All Time",
                "1975",
                "the 1990s",
                "the 2020s",
                "1985-2003",
                "1990-2026",
                "1971-1985",
                "2026",
                "1900-1950",
                "2027-2035",
            ],
        )

    def test_a_range_past_both_ends_is_no_year_in_a_clean_url(self):
        self.assertEqual(self.output["cleanUrlPastTheLastYear"], "/games/rock/")
        self.assertIsNone(self.output["cleanUrlOfARealRange"])

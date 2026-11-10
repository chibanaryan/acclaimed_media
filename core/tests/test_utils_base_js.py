"""utils-base.js when the browser refuses something.

Run under Node on the real file: what is tested is that nothing throws, which
a source-text test cannot see.
"""

import unittest

from django.test import SimpleTestCase

from core.tests.node import node_available, run_node


class UtilsBaseTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not node_available():
            raise unittest.SkipTest("Node is not installed")
        cls.output = run_node("utils_base.js")

    def test_refused_storage_reads_as_nothing_stored(self):
        """With cookies blocked, Chrome throws on the `localStorage` property
        itself. The games filter component read six preferences in its data
        literal, so it never started: no filters, no sort, no view toggle."""
        self.assertEqual(
            self.output["refused"],
            {
                "read": None,
                "readSession": None,
                "json": True,
                "stored": "no throw",
                "removed": "no throw",
            },
        )

    def test_storage_that_works_is_read_and_written_as_before(self):
        self.assertEqual(
            self.output["allowed"],
            {
                "read": "false",
                "json": {"3": True},
                "missingJson": True,
                # A value something else wrote, or half-wrote
                "brokenJson": "fallback",
                "noKey": None,
                "afterRemove": None,
            },
        )

    def test_a_failed_fetch_is_an_error_not_a_page_to_show(self):
        """`fetchHtml` handed back the body whatever the status, and the
        filter component set the results to it: a 500's error page, inside
        the rankings."""
        self.assertEqual(self.output["answers"]["ok"], {"html": "<p>rows</p>"})
        self.assertIn("500", self.output["answers"]["error"]["error"])

    def test_a_scripted_scroll_is_not_animated_for_a_reader_who_asked_for_less(self):
        """The stylesheet turns `scroll-behavior` off under
        `prefers-reduced-motion`, but a script that asks for `smooth` by name
        overrides a stylesheet: Clear, a jump and a highlight landing all
        still glided the length of the page."""
        self.assertEqual(
            self.output["scrolls"],
            {"reduced": "auto", "unreduced": "smooth", "unknown": "smooth"},
        )

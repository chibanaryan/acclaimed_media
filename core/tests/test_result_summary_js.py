"""The count line the engine writes, against the server's.

`_media_list_controls.html` reads `empty_count_label` on desktop and nothing
on a phone when nothing matched; games' engine wrote "Showing 0 of 0" there.
"""

from django.test import SimpleTestCase

from core.tests.node import require_node, run_node


class ResultSummaryTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_node()
        cls.output = run_node("result_summary.js")

    def test_an_empty_result_reads_as_the_server_reads_it(self):
        # games/includes/_game_list_results.html passes 'Advanced Search';
        # music passes none
        self.assertEqual(self.output["games"]["empty"], "Advanced Search")
        self.assertEqual(self.output["music"]["empty"], "")
        for section in ("games", "music"):
            self.assertEqual(self.output[section]["emptyCompact"], "")

    def test_a_result_is_counted(self):
        for section in ("games", "music"):
            self.assertIn("</span> of 10", self.output[section]["some"])

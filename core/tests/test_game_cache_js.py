"""game-cache.js when IndexedDB fails, run under Node on the real file.

Its reads and writes returned the request's promise from inside a `try`
without awaiting it, so a failed request escaped the `try`: `getData` threw,
and the engine, whose start is latched, never started, though the payload
itself would have loaded. Safari's "connection to IndexedDB lost" is one way
there.
"""

from django.test import SimpleTestCase

from core.tests.node import require_node, run_node

EXPECTED = {"data": {"games": [1, 2, 3]}, "cleared": "no throw"}


class GameCacheFailureTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_node()
        cls.output = run_node("game_cache.js")

    def test_a_failed_read_falls_back_to_the_network(self):
        self.assertEqual(self.output["requestFails"], EXPECTED)

    def test_a_lost_connection_falls_back_to_the_network(self):
        self.assertEqual(self.output["transactionThrows"], EXPECTED)

    def test_no_indexeddb_at_all_falls_back_to_the_network(self):
        self.assertEqual(self.output["noIndexedDB"], EXPECTED)

    def test_a_connection_another_tab_upgrades_is_let_go(self):
        self.assertEqual(
            self.output["versionChange"], {"closed": True, "forgotten": True}
        )

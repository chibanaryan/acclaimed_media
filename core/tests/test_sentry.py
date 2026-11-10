"""Sentry event processing."""

from django.test import SimpleTestCase

from core.sentry import name_unrouted_transactions


def transaction(name, source, status=None):
    contexts = {"trace": {"op": "http.server"}}
    if status is not None:
        contexts["response"] = {"status_code": status}
    return {
        "type": "transaction",
        "transaction": name,
        "transaction_info": {"source": source},
        "contexts": contexts,
    }


class NameUnroutedTransactionsTests(SimpleTestCase):
    def test_a_path_that_matched_no_route_is_named_for_its_answer(self):
        """Each probe and each slash-less link was a transaction of its own."""
        for path, status, name in (
            ("/config.env", 404, "unrouted 404"),
            ("/wp-admin/install.php", 404, "unrouted 404"),
            ("/developers/valve", 301, "redirect 301"),
            ("/kind-of-blue", 302, "redirect 302"),
        ):
            with self.subTest(path=path):
                event = name_unrouted_transactions(transaction(path, "url", status), {})
                self.assertEqual(event["transaction"], name)
                self.assertEqual(event["transaction_info"]["source"], "custom")

    def test_a_path_answered_without_a_route_keeps_its_name(self):
        """WhiteNoise answers `/static/...` and the flat pages their paths
        from middleware, with no route matched: those are real pages and
        files, and Sentry groups the static ones by directory itself."""
        for path, status in (
            ("/static/games/js/utils-base.min.js", 200),
            ("/static/games/js/utils-base.min.js", 304),
            ("/page/about/", 200),
            ("/anything", 500),
            ("/anything", None),
        ):
            with self.subTest(path=path, status=status):
                before = transaction(path, "url", status)
                self.assertEqual(name_unrouted_transactions(dict(before), {}), before)

    def test_a_routed_transaction_is_left_as_it_is(self):
        for source in ("route", "view", "custom", "task"):
            with self.subTest(source=source):
                before = transaction("/game/{slug}/", source, 404)
                self.assertEqual(name_unrouted_transactions(dict(before), {}), before)

    def test_an_event_with_no_source_is_left_as_it_is(self):
        event = {"type": "transaction", "transaction": "task"}
        self.assertEqual(name_unrouted_transactions(dict(event), {}), event)

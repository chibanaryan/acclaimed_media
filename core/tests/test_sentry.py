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


class EventScrubberTests(SimpleTestCase):
    """sentry-sdk's scrubber matches whole key names, and `password` is on
    its list but allauth's `password1`, `password2` and `oldpassword` are
    not: a sign-up that raised sent both passwords in the request body."""

    def test_allauths_password_fields_are_scrubbed(self):
        from core.sentry import event_scrubber

        event = {
            "request": {
                "data": {
                    "email": "reader@example.com",
                    "password1": "hunter22",
                    "password2": "hunter22",
                    "oldpassword": "old-one",
                }
            },
            "exception": {
                "values": [
                    {
                        "stacktrace": {
                            "frames": [{"vars": {"password1": "hunter22", "x": 1}}]
                        }
                    }
                ]
            },
        }
        event_scrubber().scrub_event(event)
        data = event["request"]["data"]
        for field in ("password1", "password2", "oldpassword"):
            self.assertNotEqual(data[field], "hunter22", field)
            self.assertNotEqual(data[field], "old-one", field)
        self.assertEqual(data["email"], "reader@example.com")
        frame = event["exception"]["values"][0]["stacktrace"]["frames"][0]
        self.assertNotEqual(frame["vars"]["password1"], "hunter22")

    def test_settings_pass_it(self):
        from pathlib import Path

        from django.conf import settings

        source = (Path(settings.BASE_DIR) / "acclaimedgames/settings.py").read_text()
        self.assertIn("event_scrubber=event_scrubber()", source)

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
        event_scrubber(True).scrub_event(event)
        data = event["request"]["data"]
        for field in ("password1", "password2", "oldpassword"):
            self.assertNotEqual(data[field], "hunter22", field)
            self.assertNotEqual(data[field], "old-one", field)
        self.assertEqual(data["email"], "reader@example.com")
        frame = event["exception"]["values"][0]["stacktrace"]["frames"][0]
        self.assertNotEqual(frame["vars"]["password1"], "hunter22")

    def test_the_csrf_token_is_scrubbed_wherever_it_travels(self):
        """The SDK redacts the CSRF and session cookies by their configured
        names, and the `Cookie` header. The token also rides in htmx's
        `X-CSRFToken` header (`base.html`'s `hx-headers`) and each form's
        `csrfmiddlewaretoken`, and the default list has `x_csrftoken`,
        which a header written with a hyphen does not match."""
        from core.sentry import event_scrubber

        event = {
            "request": {
                "headers": {"X-Csrftoken": "token", "User-Agent": "browser"},
                "data": {"csrfmiddlewaretoken": "token", "name": "Reader"},
            }
        }
        event_scrubber(True).scrub_event(event)
        self.assertNotEqual(event["request"]["headers"]["X-Csrftoken"], "token")
        self.assertNotEqual(event["request"]["data"]["csrfmiddlewaretoken"], "token")
        self.assertEqual(event["request"]["headers"]["User-Agent"], "browser")
        self.assertEqual(event["request"]["data"]["name"], "Reader")

    def test_client_addresses_are_kept(self):
        """Settings send PII on purpose (`send_default_pii=True`), and the
        SDK's own scrubber honours that; one built without saying so also
        filtered every client address, which trace scrapers and limits."""
        from core.sentry import event_scrubber

        event = {
            "request": {"headers": {"X-Forwarded-For": "203.0.113.9"}},
            "user": {"ip_address": "203.0.113.9"},
        }
        event_scrubber(True).scrub_event(event)
        self.assertEqual(event["user"]["ip_address"], "203.0.113.9")
        self.assertEqual(event["request"]["headers"]["X-Forwarded-For"], "203.0.113.9")

    def test_settings_pass_it(self):
        from pathlib import Path

        from django.conf import settings

        source = (Path(settings.BASE_DIR) / "acclaimedgames/settings.py").read_text()
        self.assertIn("event_scrubber=event_scrubber(SENTRY_SEND_DEFAULT_PII)", source)
        self.assertIn("send_default_pii=SENTRY_SEND_DEFAULT_PII", source)


class RequestErrorsReachTheLogsTests(SimpleTestCase):
    """Django prints a request's traceback only under DEBUG and mails it to
    ADMINS, of which there are none: a 500 reached Sentry alone."""

    def test_django_request_logs_to_the_console(self):
        from django.conf import settings

        logger = settings.LOGGING["loggers"]["django.request"]
        self.assertEqual(logger["handlers"], ["console"])
        self.assertFalse(logger["propagate"])

    def test_django_security_logs_to_the_console_but_for_wrong_hosts(self):
        """A refused CSRF token printed nowhere outside DEBUG. A wrong Host
        is every scanner that asks by address, so it stays out."""
        from django.conf import settings

        loggers = settings.LOGGING["loggers"]
        self.assertEqual(loggers["django.security"]["handlers"], ["console"])
        self.assertFalse(loggers["django.security"]["propagate"])
        self.assertEqual(loggers["django.security.DisallowedHost"]["level"], "CRITICAL")

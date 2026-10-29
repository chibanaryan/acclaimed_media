"""The Content Security Policy, report-only (2026-10-26)."""

import re

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from core.csp import handler_hash, sentry_report_uri
from core.tests.utils import clear_all_caches
from games.models import Game

HEADER = "Content-Security-Policy-Report-Only"
NONCE_IN_HEADER = re.compile(r"'nonce-([^']+)'")
NONCE_ATTR = re.compile(r'nonce="([^"]*)"')
INLINE_HANDLER = re.compile(r'\son[a-z]+="([^"]*)"')


class PolicyTests(TestCase):
    def setUp(self):
        clear_all_caches()
        Game.objects.create(name="Doom", slug="doom", rank=1, year_of_release=1993)

    def _nonces(self, response):
        header_nonce = NONCE_IN_HEADER.search(response[HEADER]).group(1)
        page_nonces = set(NONCE_ATTR.findall(response.content.decode()))
        return header_nonce, page_nonces

    def test_every_page_script_carries_the_nonce_its_header_allows(self):
        for url in ("/", "/game/doom/", "/developers/"):
            with self.subTest(url=url):
                header_nonce, page_nonces = self._nonces(self.client.get(url))
                self.assertEqual(page_nonces, {header_nonce})

    def test_a_cached_page_is_given_the_new_requests_nonce(self):
        """`/` is whole-page cached for anonymous visitors; replaying the
        render's nonce would put every inline script outside the policy."""
        first = self.client.get("/")
        second = self.client.get("/")  # served from the page cache

        first_nonce, _ = self._nonces(first)
        header_nonce, page_nonces = self._nonces(second)
        self.assertEqual(page_nonces, {header_nonce})
        self.assertNotEqual(header_nonce, first_nonce)
        self.assertNotIn(b"\x00", second.content)

    def test_htmx_is_told_the_nonce(self):
        response = self.client.get("/")
        header_nonce, _ = self._nonces(response)
        self.assertIn(
            f'"inlineScriptNonce": "{header_nonce}"', response.content.decode()
        )

    def test_the_only_inline_handler_is_the_one_the_hash_allows(self):
        allowed = {"event.stopPropagation()"}
        self.assertIn(
            handler_hash("event.stopPropagation()"),
            settings.SECURE_CSP_REPORT_ONLY["script-src"],
        )
        for url in ("/", "/game/doom/", "/developers/", "/lists/"):
            with self.subTest(url=url):
                handlers = set(
                    INLINE_HANDLER.findall(self.client.get(url).content.decode())
                )
                self.assertEqual(handlers - allowed, set())


class ConnectSrcTests(TestCase):
    def test_the_served_policy_lets_google_analytics_send_its_hits(self):
        """gtag.js posts to these; www.google.com/g/collect was reported
        blocked on 2026-10-29 (ACCLAIMED-VIDEO-GAMES-99)."""
        policy = self.client.get("/lists/")[HEADER]
        connect_src = re.search(r"connect-src ([^;]*)", policy).group(1).split()
        for source in (
            "https://*.google-analytics.com",
            "https://*.analytics.google.com",
            "https://*.googletagmanager.com",
            "https://www.google.com/g/collect",
        ):
            with self.subTest(source=source):
                self.assertIn(source, connect_src)
        self.assertNotIn("https://www.google.com", connect_src)


class ReportUriTests(SimpleTestCase):
    def test_built_from_the_sentry_dsn(self):
        self.assertEqual(
            sentry_report_uri("https://abc123@o42.ingest.us.sentry.io/7"),
            "https://o42.ingest.us.sentry.io/api/7/security/?sentry_key=abc123",
        )

    def test_none_without_a_usable_dsn(self):
        for dsn in (None, "", "https://o42.ingest.us.sentry.io/7", "https://abc@host/"):
            with self.subTest(dsn=dsn):
                self.assertIsNone(sentry_report_uri(dsn))

    def test_tests_send_no_reports(self):
        self.assertNotIn("report-uri", settings.SECURE_CSP_REPORT_ONLY)


class NoInlineHandlersInTemplatesTests(SimpleTestCase):
    def test_no_template_has_any_other_inline_handler(self):
        """The page tests above render games pages only; books' rows had
        two handlers none of them reached."""
        found = set()
        for app in ("games", "core", "music", "books"):
            for path in (settings.BASE_DIR / app / "templates").rglob("*.html"):
                found |= set(INLINE_HANDLER.findall(path.read_text()))
        self.assertEqual(found - {"event.stopPropagation()"}, set())

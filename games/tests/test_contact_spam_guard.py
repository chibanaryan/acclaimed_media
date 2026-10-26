"""Tests for contact spam guard service."""

from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from core.tests.utils import clear_all_caches
from games import config
from games.services import contact_spam_guard


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class ContactSpamGuardTests(TestCase):
    """Test contact form spam/rate-limit checks."""

    def setUp(self):
        self.factory = RequestFactory()
        clear_all_caches()

    def tearDown(self):
        clear_all_caches()

    def _request(self, ip="127.0.0.1"):
        request = self.factory.post("/contact/")
        request.META["REMOTE_ADDR"] = ip
        return request

    def _cleaned_data(self, *, email="user@testmail.com", message="Hello"):
        return {
            "name": "Test User",
            "email": email,
            "category": "general",
            "message": message,
        }

    def test_allows_first_three_submissions_in_10_min_window(self):
        request = self._request()

        for i in range(config.CONTACT_RATE_LIMIT_PER_10_MIN):
            decision = contact_spam_guard.evaluate(
                request, self._cleaned_data(message=f"Hello {i}")
            )
            self.assertTrue(decision.allowed)

    def test_blocks_fourth_submission_in_10_min_window(self):
        request = self._request()

        for i in range(config.CONTACT_RATE_LIMIT_PER_10_MIN):
            contact_spam_guard.evaluate(
                request, self._cleaned_data(message=f"Hello {i}")
            )

        decision = contact_spam_guard.evaluate(
            request, self._cleaned_data(message="Hello 4")
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "rate_limit")

    def test_allows_first_ten_submissions_in_24_hour_window(self):
        request = self._request()
        base_time = 1_700_000_000

        for i in range(config.CONTACT_RATE_LIMIT_PER_24_HOURS):
            with patch(
                "games.services.contact_spam_guard.time.time",
                return_value=base_time + (i * 601),
            ):
                decision = contact_spam_guard.evaluate(
                    request, self._cleaned_data(message=f"Day message {i}")
                )
            self.assertTrue(decision.allowed)

    def test_blocks_eleventh_submission_in_24_hour_window(self):
        request = self._request()
        base_time = 1_700_000_000

        for i in range(config.CONTACT_RATE_LIMIT_PER_24_HOURS):
            with patch(
                "games.services.contact_spam_guard.time.time",
                return_value=base_time + (i * 601),
            ):
                contact_spam_guard.evaluate(
                    request, self._cleaned_data(message=f"Day message {i}")
                )

        with patch(
            "games.services.contact_spam_guard.time.time",
            return_value=base_time + (config.CONTACT_RATE_LIMIT_PER_24_HOURS * 601),
        ):
            decision = contact_spam_guard.evaluate(
                request, self._cleaned_data(message="Day message 11")
            )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "rate_limit")

    def test_blocks_duplicate_fingerprint(self):
        request = self._request()
        data = self._cleaned_data(message="Same exact message")

        first = contact_spam_guard.evaluate(request, data)
        second = contact_spam_guard.evaluate(request, data)

        self.assertTrue(first.allowed)
        self.assertFalse(second.allowed)
        self.assertEqual(second.reason, "duplicate")

    def test_blocks_placeholder_domains_when_email_provided(self):
        request = self._request()

        for domain in sorted(config.CONTACT_PLACEHOLDER_DOMAINS):
            with self.subTest(domain=domain):
                decision = contact_spam_guard.evaluate(
                    request,
                    self._cleaned_data(email=f"fake@{domain}", message=f"msg-{domain}"),
                )
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason, "placeholder_domain")

    def test_does_not_block_when_email_omitted(self):
        request = self._request()
        decision = contact_spam_guard.evaluate(request, self._cleaned_data(email=""))
        self.assertTrue(decision.allowed)

    def test_cache_failure_fails_open(self):
        request = self._request()
        with patch(
            "games.services.contact_spam_guard.cache.incr",
            side_effect=Exception("cache unavailable"),
        ):
            decision = contact_spam_guard.evaluate(request, self._cleaned_data())
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "cache_unavailable")

    def test_a_forged_header_does_not_reset_the_rate_limit(self):
        """The client writes the left of X-Forwarded-For; the router the right."""
        for n in range(config.CONTACT_RATE_LIMIT_PER_10_MIN):
            request = self._request(ip="10.0.0.5")
            request.META["HTTP_X_FORWARDED_FOR"] = f"203.0.113.{n}, 45.148.10.143"
            decision = contact_spam_guard.evaluate(
                request, self._cleaned_data(message=f"Hello {n}")
            )
            self.assertTrue(decision.allowed)

        request = self._request(ip="10.0.0.5")
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.99, 45.148.10.143"
        decision = contact_spam_guard.evaluate(
            request, self._cleaned_data(message="Hello again")
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "rate_limit")
        self.assertEqual(decision.client_ip, "45.148.10.143")

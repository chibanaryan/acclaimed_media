"""Tests for RateLimitMiddleware."""

import time
from unittest.mock import MagicMock, patch

from django.core.cache import caches
from django.test import TestCase, override_settings

from games.config import (
    RATE_LIMIT_CACHE_PREFIX,
    RATE_LIMIT_PER_HOUR,
    RATE_LIMIT_PER_MINUTE,
)

LOCMEM = {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}


@override_settings(
    CACHES={
        "default": LOCMEM,
        # The views these tests request cache whole pages on `local`.
        "local": dict(LOCMEM, LOCATION="local"),
        "ratelimit": dict(LOCMEM, LOCATION="ratelimit"),
    }
)
class RateLimitMiddlewareTest(TestCase):
    """Test rate limiting middleware.

    The counters live on the per-process `ratelimit` alias, not `default` -
    see `core.cache_config` for why - so the seeding helpers write there.
    """

    def setUp(self):
        self.cache = caches["ratelimit"]
        self.cache.clear()

    def tearDown(self):
        self.cache.clear()

    def _seed_minute_count(self, ip="127.0.0.1", count=RATE_LIMIT_PER_MINUTE):
        """Pre-seed the per-minute counter to just at the limit."""
        now = int(time.time())
        key = f"{RATE_LIMIT_CACHE_PREFIX}:min:{ip}:{now // 60}"
        self.cache.set(key, count, timeout=60)

    def _seed_hour_count(self, ip="127.0.0.1", count=RATE_LIMIT_PER_HOUR):
        """Pre-seed the per-hour counter to just at the limit."""
        now = int(time.time())
        key = f"{RATE_LIMIT_CACHE_PREFIX}:hr:{ip}:{now // 3600}"
        self.cache.set(key, count, timeout=3600)

    def _block_ip(self, ip="127.0.0.1"):
        """Simulate a blocked IP."""
        self.cache.set(f"{RATE_LIMIT_CACHE_PREFIX}:block:{ip}", True, timeout=300)

    def test_normal_request_passes(self):
        """Normal requests should return 200."""
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)

    def test_exempt_paths_not_rate_limited(self):
        """Requests to exempt paths should never be rate limited."""
        exempt_paths = [
            "/robots.txt",
            "/sitemap.xml",
            "/favicon.ico",
            "/admin/login/",
            "/static/test.css",
            "/accounts/login/",
            # A hundred of these are requested per album rankings page.
            "/music/cover/abc/123-250.jpg",
        ]
        for path in exempt_paths:
            self._block_ip()
            response = self.client.get(path)
            self.assertNotEqual(
                response.status_code, 429, f"Exempt path {path} was rate limited"
            )
            self.cache.clear()

    def test_per_minute_rate_limit_allows_up_to_threshold(self):
        """Requests at the per-minute limit should pass."""
        self._seed_minute_count(count=RATE_LIMIT_PER_MINUTE - 1)
        response = self.client.get("/")
        self.assertNotEqual(response.status_code, 429)

    def test_per_minute_rate_limit_blocks_over_threshold(self):
        """Exceeding per-minute threshold should trigger 429."""
        self._seed_minute_count(count=RATE_LIMIT_PER_MINUTE)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertIn("Rate limit", response.content.decode())

    def test_blocked_ip_stays_blocked(self):
        """Once blocked, subsequent requests should also get 429."""
        self._block_ip()

        response = self.client.get("/")
        self.assertEqual(response.status_code, 429)

        response = self.client.get("/games/")
        self.assertEqual(response.status_code, 429)

    def test_per_hour_rate_limit(self):
        """Exceeding per-hour threshold should trigger 429."""
        self._seed_hour_count(count=RATE_LIMIT_PER_HOUR)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 429)

    def test_x_forwarded_for_ip_extraction(self):
        """Should key on the address Heroku's router appended: the last one."""
        bot_ip = "45.148.10.143"
        self._block_ip(bot_ip)

        # The router appends the connecting address, so the bot is last
        response = self.client.get("/", HTTP_X_FORWARDED_FOR=f"10.0.0.1, {bot_ip}")
        self.assertEqual(response.status_code, 429)

        # Request from different IP should NOT be blocked
        response = self.client.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4")
        self.assertNotEqual(response.status_code, 429)

    def test_a_forged_header_does_not_buy_a_fresh_bucket(self):
        """Whatever a client writes into X-Forwarded-For comes before the
        router's own entry, so varying it changes nothing."""
        real_ip = "45.148.10.143"
        self._seed_minute_count(ip=real_ip, count=RATE_LIMIT_PER_MINUTE)

        response = self.client.get(
            "/", HTTP_X_FORWARDED_FOR=f"203.0.113.{time.time_ns() % 250}, {real_ip}"
        )
        self.assertEqual(response.status_code, 429)

    def test_a_forged_header_cannot_get_another_address_blocked(self):
        victim_ip = "198.51.100.7"
        attacker_ip = "45.148.10.143"
        self._seed_minute_count(ip=attacker_ip, count=RATE_LIMIT_PER_MINUTE)

        response = self.client.get(
            "/", HTTP_X_FORWARDED_FOR=f"{victim_ip}, {attacker_ip}"
        )
        self.assertEqual(response.status_code, 429)
        self.assertIsNone(
            self.cache.get(f"{RATE_LIMIT_CACHE_PREFIX}:block:{victim_ip}")
        )

    def test_different_ips_tracked_separately(self):
        """Rate limits should be per-IP, not global."""
        ip1 = "10.0.0.1"
        self._seed_minute_count(ip=ip1, count=RATE_LIMIT_PER_MINUTE)

        # IP 1 should be blocked
        response = self.client.get("/", HTTP_X_FORWARDED_FOR=ip1)
        self.assertEqual(response.status_code, 429)

        # IP 2 should still work
        response = self.client.get("/", HTTP_X_FORWARDED_FOR="10.0.0.2")
        self.assertNotEqual(response.status_code, 429)

    def test_cache_failure_allows_request(self):
        """If cache is unavailable, requests should pass through."""
        broken = MagicMock()
        broken.get.side_effect = Exception("Cache unavailable")
        with patch("games.middleware.caches", new={"ratelimit": broken}):
            response = self.client.get("/")
            # Should not be 429 - graceful degradation
            self.assertNotEqual(response.status_code, 429)

    def test_block_key_created_on_exceed(self):
        """Block cache key should be set when limit is exceeded."""
        ip = "127.0.0.1"
        self._seed_minute_count(ip=ip, count=RATE_LIMIT_PER_MINUTE)

        # Trigger the block
        self.client.get("/")

        # Verify block key exists
        block_key = f"{RATE_LIMIT_CACHE_PREFIX}:block:{ip}"
        self.assertTrue(self.cache.get(block_key))

    def test_429_response_format(self):
        """429 response should have correct content type and message."""
        self._block_ip()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertIn("Rate limit exceeded", response.content.decode())

    def test_non_exempt_path_is_rate_limited(self):
        """Non-exempt paths should be subject to rate limiting."""
        self._block_ip()
        response = self.client.get("/games/")
        self.assertEqual(response.status_code, 429)

    def test_block_key_cache_set_failure_is_ignored(self):
        """
        Rate limiter should still return 429
        even if cache.set for block key fails.
        """
        unwritable = MagicMock()
        unwritable.get.return_value = None
        unwritable.set.side_effect = Exception("cache write failed")
        with patch("games.middleware.caches", new={"ratelimit": unwritable}):
            with patch(
                "games.middleware.RateLimitMiddleware._incr",
                side_effect=[RATE_LIMIT_PER_MINUTE + 1, 1],
            ):
                response = self.client.get("/")
        self.assertEqual(response.status_code, 429)


@override_settings(CACHES={"default": LOCMEM, "ratelimit": dict(LOCMEM, LOCATION="rl")})
class RateLimitCounterTests(TestCase):
    """`_incr` has to count every request to a new key, even two at once.

    It used to `incr`, catch the missing key and `set(key, 1)` - so under
    gunicorn's gthread workers two threads meeting a new key could both
    `set(1)`, and the second reset the first one's count.
    """

    def setUp(self):
        from games.middleware import RateLimitMiddleware

        self.cache = caches["ratelimit"]
        self.cache.clear()
        self.middleware = RateLimitMiddleware(lambda request: None)

    def tearDown(self):
        self.cache.clear()

    def test_a_new_key_counts_from_one(self):
        self.assertEqual(self.middleware._incr("rl-test:new", 60), 1)
        self.assertEqual(self.middleware._incr("rl-test:new", 60), 2)

    def test_an_existing_count_is_not_reset(self):
        self.cache.set("rl-test:seeded", 5, timeout=60)
        self.assertEqual(self.middleware._incr("rl-test:seeded", 60), 6)

    def test_a_key_evicted_between_add_and_incr_starts_again(self):
        flaky = MagicMock()
        flaky.incr.side_effect = ValueError("evicted")
        with patch("games.middleware.caches", new={"ratelimit": flaky}):
            self.assertEqual(self.middleware._incr("rl-test:gone", 60), 1)
        flaky.add.assert_called_once_with("rl-test:gone", 0, timeout=60)
        flaky.set.assert_called_once_with("rl-test:gone", 1, timeout=60)

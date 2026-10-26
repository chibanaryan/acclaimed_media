"""Tests for the client address the rate limits key on."""

from django.conf import settings
from django.core.cache import caches
from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.request import Request

from core.services.client_ip import get_client_ip
from core.throttling import ClientIPAnonRateThrottle

LOCMEM = {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}


class GetClientIPTests(SimpleTestCase):
    def _request(self, forwarded_for=None, remote_addr="10.0.0.5"):
        request = RequestFactory().get("/")
        request.META["REMOTE_ADDR"] = remote_addr
        if forwarded_for is not None:
            request.META["HTTP_X_FORWARDED_FOR"] = forwarded_for
        return request

    def test_takes_the_entry_the_router_appended(self):
        request = self._request("203.0.113.9, 198.51.100.1, 45.148.10.143")
        self.assertEqual(get_client_ip(request), "45.148.10.143")

    def test_a_single_entry_is_the_client(self):
        self.assertEqual(get_client_ip(self._request("45.148.10.143")), "45.148.10.143")

    def test_falls_back_to_remote_addr_without_the_header(self):
        self.assertEqual(get_client_ip(self._request()), "10.0.0.5")

    def test_falls_back_to_remote_addr_when_the_last_entry_is_blank(self):
        self.assertEqual(get_client_ip(self._request("45.148.10.143, ")), "10.0.0.5")

    def test_unknown_without_any_address(self):
        request = RequestFactory().get("/")
        del request.META["REMOTE_ADDR"]
        self.assertEqual(get_client_ip(request), "unknown")


@override_settings(CACHES={"default": LOCMEM, "ratelimit": dict(LOCMEM, LOCATION="rl")})
class ClientIPAnonRateThrottleTests(SimpleTestCase):
    def setUp(self):
        caches["ratelimit"].clear()
        caches["default"].clear()

    def _request(self, forwarded_for):
        request = RequestFactory().get("/api/games/")
        request.META["HTTP_X_FORWARDED_FOR"] = forwarded_for
        return Request(request)

    def test_is_the_api_default(self):
        self.assertEqual(
            settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"],
            ["core.throttling.ClientIPAnonRateThrottle"],
        )

    def test_a_forged_header_does_not_buy_a_fresh_bucket(self):
        throttle = ClientIPAnonRateThrottle()
        for n in range(throttle.num_requests):
            request = self._request(f"203.0.113.{n % 250}, 45.148.10.143")
            self.assertTrue(ClientIPAnonRateThrottle().allow_request(request, None))

        request = self._request("198.51.100.1, 45.148.10.143")
        self.assertFalse(ClientIPAnonRateThrottle().allow_request(request, None))

    def test_counts_in_the_per_process_cache_not_the_shared_one(self):
        ClientIPAnonRateThrottle().allow_request(self._request("45.148.10.143"), None)

        key = "throttle_anon_45.148.10.143"
        self.assertIsNotNone(caches["ratelimit"].get(key))
        self.assertIsNone(caches["default"].get(key))

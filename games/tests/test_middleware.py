from django.core.exceptions import DisallowedHost
from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory, TestCase

from games.middleware import (
    EventStreamAwareGZipMiddleware,
    HTMXPushURLMiddleware,
    UncompressedUptimeCheckMiddleware,
)

SENTRY_UPTIME_UA = (
    "SentryUptimeBot/1.0 (+http://docs.sentry.io/product/alerts/uptime-monitoring/)"
)


class UncompressedUptimeCheckMiddlewareTest(TestCase):
    """Sentry's gzip-less uptime check gets a tiny 200, everyone else the page."""

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = UncompressedUptimeCheckMiddleware(
            lambda request: HttpResponse("<html>the real page</html>")
        )

    def test_uptime_check_without_gzip_is_short_circuited(self):
        request = self.factory.get("/", HTTP_USER_AGENT=SENTRY_UPTIME_UA)

        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Vary"], "User-Agent, Accept-Encoding")

    def test_uptime_check_accepting_gzip_gets_the_real_page(self):
        request = self.factory.get(
            "/",
            HTTP_USER_AGENT=SENTRY_UPTIME_UA,
            HTTP_ACCEPT_ENCODING="gzip, deflate",
        )

        response = self.middleware(request)

        self.assertEqual(response.content, b"<html>the real page</html>")

    def test_other_clients_without_gzip_get_the_real_page(self):
        request = self.factory.get("/", HTTP_USER_AGENT="curl/8.7.1")

        response = self.middleware(request)

        self.assertEqual(response.content, b"<html>the real page</html>")

    def test_head_of_root_is_short_circuited_too(self):
        request = self.factory.head("/", HTTP_USER_AGENT=SENTRY_UPTIME_UA)

        self.assertEqual(self.middleware(request).content, b"OK")

    def test_uptime_check_of_another_path_gets_the_real_page(self):
        """A monitor on any other URL must still exercise that URL's view."""
        request = self.factory.get("/music/", HTTP_USER_AGENT=SENTRY_UPTIME_UA)

        response = self.middleware(request)

        self.assertEqual(response.content, b"<html>the real page</html>")

    def test_post_with_the_uptime_user_agent_gets_the_real_view(self):
        request = self.factory.post("/", HTTP_USER_AGENT=SENTRY_UPTIME_UA)

        response = self.middleware(request)

        self.assertEqual(response.content, b"<html>the real page</html>")

    def test_spoofed_check_with_a_disallowed_host_is_rejected(self):
        request = self.factory.get(
            "/", HTTP_USER_AGENT=SENTRY_UPTIME_UA, HTTP_HOST="evil.example"
        )

        with self.assertRaises(DisallowedHost):
            self.middleware(request)

    def test_installed_ahead_of_rate_limiting_and_sessions(self):
        """It must answer before anything that counts, or touches the database."""
        from django.conf import settings

        stack = settings.MIDDLEWARE
        position = stack.index("games.middleware.UncompressedUptimeCheckMiddleware")
        # After SecurityMiddleware, so the HTTPS redirect and HSTS still apply
        self.assertGreater(
            position, stack.index("django.middleware.security.SecurityMiddleware")
        )
        self.assertLess(position, stack.index("games.middleware.RateLimitMiddleware"))
        self.assertLess(
            position,
            stack.index("django.contrib.sessions.middleware.SessionMiddleware"),
        )


class HTMXPushURLMiddlewareTest(TestCase):
    """Test the HTMX middleware for URL push support."""

    def setUp(self):
        self.factory = RequestFactory()
        self.get_response = lambda request: HttpResponse("OK")
        self.middleware = HTMXPushURLMiddleware(self.get_response)

    def test_adds_hx_push_url_for_htmx_requests_with_hx_request_header(self):
        """HX-Push-URL header added for HTMX (HTTP_HX_REQUEST)."""
        request = self.factory.get("/games/?page=2")
        request.META["HTTP_HX_REQUEST"] = "true"

        response = self.middleware(request)

        self.assertEqual(response["HX-Push-URL"], "/games/?page=2")

    def test_adds_hx_push_url_for_htmx_requests_with_hx_request_in_headers(self):
        """HX-Push-URL header added for HTMX (headers dict)."""
        request = self.factory.get("/developers/?q=nintendo")
        # Simulate headers dict attribute that Django uses
        request.headers = {"HX-Request": "true"}

        response = self.middleware(request)

        self.assertEqual(response["HX-Push-URL"], "/developers/?q=nintendo")

    def test_does_not_add_header_for_non_htmx_requests(self):
        """Test that HX-Push-URL header is not added for regular requests."""
        request = self.factory.get("/games/")

        response = self.middleware(request)

        self.assertNotIn("HX-Push-URL", response)

    def test_respects_existing_hx_push_url_header(self):
        """Test that existing HX-Push-URL header is not overwritten."""
        request = self.factory.get("/games/")
        request.META["HTTP_HX_REQUEST"] = "true"

        # Simulate response that already has HX-Push-URL
        def get_response_with_header(request):
            response = HttpResponse("OK")
            response["HX-Push-URL"] = "/custom/url/"
            return response

        middleware = HTMXPushURLMiddleware(get_response_with_header)
        response = middleware(request)

        # Should keep the existing custom URL, not replace with request path
        self.assertEqual(response["HX-Push-URL"], "/custom/url/")


class EventStreamAwareGZipMiddlewareTest(TestCase):
    """Test that SSE streams bypass compression."""

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self):
        request = self.factory.get("/import/igdb-progress/")
        request.META["HTTP_ACCEPT_ENCODING"] = "gzip"
        return request

    def test_event_stream_is_not_compressed(self):
        """SSE events must reach the client as they are yielded."""
        chunks = [b'data: {"event": "start"}\n\n', b": keepalive\n\n"]

        def get_response(request):
            return StreamingHttpResponse(iter(chunks), content_type="text/event-stream")

        middleware = EventStreamAwareGZipMiddleware(get_response)
        response = middleware(self._request())

        self.assertNotIn("Content-Encoding", response)
        self.assertEqual(list(response.streaming_content), chunks)

    def test_regular_response_is_still_compressed(self):
        """Compression stays on for everything else."""

        def get_response(request):
            return HttpResponse("<html>" + "a" * 500 + "</html>")

        middleware = EventStreamAwareGZipMiddleware(get_response)
        response = middleware(self._request())

        self.assertEqual(response["Content-Encoding"], "gzip")

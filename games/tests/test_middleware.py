from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory, TestCase

from games.middleware import EventStreamAwareGZipMiddleware, HTMXPushURLMiddleware


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

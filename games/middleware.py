"""
Middleware for HTMX history support, rate limiting, and response compression.
"""

import logging
import time

from django.core.cache import caches
from django.http import HttpResponse
from django.middleware.gzip import GZipMiddleware

from games.config import (
    RATE_LIMIT_BLOCK_DURATION,
    RATE_LIMIT_CACHE_PREFIX,
    RATE_LIMIT_PER_HOUR,
    RATE_LIMIT_PER_MINUTE,
)

logger = logging.getLogger(__name__)

# Paths exempt from rate limiting.
#
# `/music/cover/` is here because it is a static asset in everything but the
# URL: immutable bytes from our own store, served with a year's cache. A
# single album rankings page asks for up to a hundred of them, so counting
# them against a 120/minute budget meant one page load nearly exhausted it
# and the next one 429'd - and client-side filtering makes that worse, since
# every filter change renders another hundred rows.
RATE_LIMIT_EXEMPT_PREFIXES = (
    "/robots.txt",
    "/sitemap.xml",
    "/favicon.ico",
    "/admin/",
    "/static/",
    "/accounts/",
    "/music/cover/",
)


class RateLimitMiddleware:
    """
    Fixed-window rate limiting per IP address.

    Blocks IPs that exceed per-minute or per-hour thresholds.

    The counters live in the per-process ``local`` cache rather than the
    shared ``default`` one. Three cache operations run on every non-exempt
    request and the keys are per-IP-per-minute, so on a database-backed cache
    this would add writes to Postgres on every hit from every crawler and
    churn the shared entries out through culling. The cost is that each
    gunicorn worker counts independently, so the effective limit is looser
    than the configured one by the worker count - which is how this has
    always behaved, LocMemCache being per-process too.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @property
    def cache(self):
        """The counter cache, resolved per access.

        Resolved here rather than held from ``__init__`` so that a test's
        ``override_settings(CACHES=...)`` applies: middleware is instantiated
        once per handler, long before any such override.
        """
        return caches["local"]

    def __call__(self, request):
        path = request.path

        # Skip rate limiting for exempt paths
        if any(path.startswith(prefix) for prefix in RATE_LIMIT_EXEMPT_PREFIXES):
            return self.get_response(request)

        ip = self._get_client_ip(request)
        block_key = f"{RATE_LIMIT_CACHE_PREFIX}:block:{ip}"

        try:
            # Check if IP is currently blocked
            if self.cache.get(block_key):
                return HttpResponse(
                    "Rate limit exceeded. Try again later.",
                    status=429,
                    content_type="text/plain",
                )

            # Atomically increment per-minute and per-hour counters
            now = int(time.time())
            minute_key = f"{RATE_LIMIT_CACHE_PREFIX}:min:{ip}:{now // 60}"
            hour_key = f"{RATE_LIMIT_CACHE_PREFIX}:hr:{ip}:{now // 3600}"

            minute_count = self._incr(minute_key, 60)
            hour_count = self._incr(hour_key, 3600)
        except Exception:
            # If cache is unavailable, allow the request through
            return self.get_response(request)

        # Check thresholds
        if minute_count > RATE_LIMIT_PER_MINUTE or hour_count > RATE_LIMIT_PER_HOUR:
            try:
                self.cache.set(block_key, True, timeout=RATE_LIMIT_BLOCK_DURATION)
            except Exception:
                pass
            exceeded = (
                f"{minute_count}/min"
                if minute_count > RATE_LIMIT_PER_MINUTE
                else f"{hour_count}/hr"
            )
            logger.warning(
                "Rate limit exceeded for %s (%s) - blocked for %ds. Path: %s",
                ip,
                exceeded,
                RATE_LIMIT_BLOCK_DURATION,
                path,
            )
            return HttpResponse(
                "Rate limit exceeded. Try again later.",
                status=429,
                content_type="text/plain",
            )

        return self.get_response(request)

    def _incr(self, key, timeout):
        """Atomically increment a cache counter, creating it if needed."""
        try:
            return self.cache.incr(key)
        except ValueError:
            # Key doesn't exist yet — create it
            self.cache.set(key, 1, timeout=timeout)
            return 1

    @staticmethod
    def _get_client_ip(request):
        """Extract client IP from X-Forwarded-For (Heroku) or REMOTE_ADDR."""
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")


class HTMXPushURLMiddleware:
    """
    Middleware that adds HX-Push-URL header to HTMX responses.

    When hx-push-url="true" is used in templates, HTMX expects the server
    to return an HX-Push-URL header. This middleware ensures that header
    is present, preventing historyCacheError.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Check if this is an HTMX request
        is_htmx_request = (
            request.META.get("HTTP_HX_REQUEST") == "true"
            or request.headers.get("HX-Request") == "true"
        )

        if is_htmx_request:
            # Check if HX-Push-URL is already set (case-insensitive check)
            # Django's HttpResponse headers are case-insensitive
            hx_push_url = response.get("HX-Push-URL")
            if not hx_push_url:
                # Build the full URL with query parameters
                full_url = request.get_full_path()
                response["HX-Push-URL"] = full_url

        return response


class EventStreamAwareGZipMiddleware(GZipMiddleware):
    """
    GZipMiddleware that leaves Server-Sent Event streams uncompressed.

    zlib buffers its output, so compressing a long-lived ``text/event-stream``
    response keeps every progress event - and every keepalive ping - inside the
    compressor until the stream finishes. On Heroku the router sees no bytes for
    55 seconds and drops the connection, which the browser reports as a
    connection error even though the import thread is still working.
    """

    def process_response(self, request, response):
        content_type = response.get("Content-Type", "")
        if content_type.startswith("text/event-stream"):
            return response
        return super().process_response(request, response)

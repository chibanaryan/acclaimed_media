"""
Middleware for HTMX history support, rate limiting, and response compression.
"""

import logging
import re
import time

from django.core.cache import caches
from django.http import HttpResponse
from django.middleware.gzip import GZipMiddleware
from django.utils.cache import patch_vary_headers

from core.services.client_ip import get_client_ip
from games.config import (
    RATE_LIMIT_BLOCK_DURATION,
    RATE_LIMIT_CACHE_PREFIX,
    RATE_LIMIT_PER_HOUR,
    RATE_LIMIT_PER_MINUTE,
)

logger = logging.getLogger(__name__)
# Its own logger because this module's is held at WARNING; see
# UncompressedUptimeCheckMiddleware.
uptime_logger = logging.getLogger(f"{__name__}.uptime")

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
    "/healthz/",
)


class UncompressedUptimeCheckMiddleware:
    """
    Answer Sentry's uptime checks with a tiny 200 when they refuse gzip.

    Two SentryUptimeBot checks poll ``/`` once a minute each. Ours, at :17
    past the minute, sends ``Accept-Encoding: gzip`` and gets the ~63 KB
    compressed page. The other, at :39, sends none, so it pulled the whole
    ~667 KB of HTML every minute - about 1 GB a day - and the router logged an
    H13 ("Connection closed without response") on some of those transfers,
    cut off ~80 KB in. It is not in our Sentry organization: on 2026-10-26
    Sentry Support confirmed we have one monitor and began tracing the other
    from its ``sentry-trace`` header. So it is short-circuited here.

    Each check answered here is logged to ``games.middleware.uptime`` with
    that header, so the values Sentry asked for can be read off
    ``heroku logs``. That logging is temporary: remove it once Sentry has
    named the source.

    The answer proves only that a dyno is up and Django is serving: it touches
    no database and renders no template. The gzip monitor still fetches the
    real page, so a broken render is still caught there. Only a ``GET`` or
    ``HEAD`` of ``/`` qualifies, so a monitor pointed anywhere else still
    checks the real URL, and ``get_host()`` still runs, so a spoofed
    User-Agent cannot skip the ``ALLOWED_HOSTS`` check.
    """

    USER_AGENT_MARKER = "SentryUptimeBot"
    ACCEPTS_GZIP = re.compile(r"\bgzip\b")
    LOGGED_HEADER_MAX = 300

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        accept_encoding = request.META.get("HTTP_ACCEPT_ENCODING", "")
        if (
            request.path == "/"
            and request.method in ("GET", "HEAD")
            and self.USER_AGENT_MARKER in user_agent
            and not self.ACCEPTS_GZIP.search(accept_encoding)
        ):
            request.get_host()  # raises DisallowedHost -> 400, as usual
            self._log_trace(request, accept_encoding)
            response = HttpResponse("OK", content_type="text/plain")
            response["Cache-Control"] = "no-store"
            patch_vary_headers(response, ("User-Agent", "Accept-Encoding"))
            return response
        return self.get_response(request)

    def _log_trace(self, request, accept_encoding):
        # Capped, because the User-Agent is all that admits a request here
        # and it runs ahead of rate limiting. The client IP is already on
        # the router's own line, as fwd=.
        def capped(value):
            return value[: self.LOGGED_HEADER_MAX]

        uptime_logger.info(
            "sentry uptime check: accept-encoding=%r sentry-trace=%r baggage=%r",
            capped(accept_encoding),
            capped(request.META.get("HTTP_SENTRY_TRACE", "")),
            capped(request.META.get("HTTP_BAGGAGE", "")),
        )


class RateLimitMiddleware:
    """
    Fixed-window rate limiting per IP address.

    Blocks IPs that exceed per-minute or per-hour thresholds.

    The counters live in the per-process ``ratelimit`` cache rather than the
    shared ``default`` one. Three cache operations run on every non-exempt
    request and the keys are per-IP-per-minute, so on a database-backed cache
    this would add writes to Postgres on every hit from every crawler and
    churn the shared entries out through culling. The cost is that each
    gunicorn worker counts independently, so the effective limit is looser
    than the configured one by the worker count - which is how this has
    always behaved, LocMemCache being per-process too.

    They had their own alias from 2026-10-18. Sharing ``local`` with the
    rendered pages meant the two culled each other out of one 500-entry
    LocMem, so a crawl wide enough to matter evicted the very counters meant
    to stop it.
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
        return caches["ratelimit"]

    def __call__(self, request):
        path = request.path

        # Skip rate limiting for exempt paths
        if any(path.startswith(prefix) for prefix in RATE_LIMIT_EXEMPT_PREFIXES):
            return self.get_response(request)

        ip = get_client_ip(request)
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
        """Atomically increment a cache counter, creating it if needed.

        ``add`` only writes a missing key, so two threads meeting a new key
        both count: the old incr-or-``set(1)`` let the second ``set`` reset
        the first one's count under gunicorn's gthread workers. ``incr``
        can still miss a key evicted in between, hence the fallback.
        """
        self.cache.add(key, 0, timeout=timeout)
        try:
            return self.cache.incr(key)
        except ValueError:
            self.cache.set(key, 1, timeout=timeout)
            return 1


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

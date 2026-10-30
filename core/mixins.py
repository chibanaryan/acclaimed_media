"""Reusable view mixins for the multi-media platform."""

import re
import zlib

from django.conf import settings
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.cache import caches
from django.core.paginator import EmptyPage, Paginator
from django.http import Http404, HttpResponse
from django.middleware.csp import get_nonce as get_csp_nonce
from django.middleware.csrf import get_token


class RobustPaginationMixin:
    """Pagination mixin with graceful handling of invalid page numbers.

    Instead of raising 404 errors for invalid page numbers, returns
    the last valid page (or first page if no results).
    """

    def paginate_queryset(self, queryset, page_size):
        """Paginate the queryset with graceful fallback for invalid pages."""
        paginator = Paginator(queryset, page_size, orphans=self.paginate_orphans)
        page = self.request.GET.get("page")

        try:
            page_number = int(page) if page else 1
        except (TypeError, ValueError):
            page_number = 1

        try:
            page_obj = paginator.page(page_number)
        except EmptyPage:
            # If page is out of range, return the last valid page (or first if no pages)
            if paginator.num_pages > 0:
                page_obj = paginator.page(paginator.num_pages)
            else:
                # No results at all - handle gracefully
                try:
                    page_obj = paginator.page(1)
                except EmptyPage:
                    return (paginator, None, [], False)

        return (paginator, page_obj, page_obj.object_list, page_obj.has_other_pages())


class AnonymousResponseCacheMixin:
    """Cache rendered full-page responses for anonymous users to reduce TTFB.

    Subclasses must implement `get_page_cache_key()` returning the cache key
    for the current request, or None to skip caching, and set
    `page_cache_timeout` (seconds). Only anonymous, non-HTMX GET requests
    are cached; only successful, non-streaming responses are stored.

    Whole pages go to the per-process `local` alias, never to the shared
    `default` cache: the values are entire HTML bodies keyed by URL, so on a
    shared backend a crawler would both bloat it and cull the small shared
    entries - the filter options and counts - straight out of it. Nothing
    here needs cross-process agreement; see `core.cache_config`.

    The body is stored deflated. These pages are big - the rankings page is
    ~1.4 MB of HTML - and there are ~50 cacheable URLs between the home page
    and the SEO landing pages, which at full size is 60-70 MB in every
    gunicorn worker on a 512 MB dyno. Deflate cuts that by about 15x, and
    inflating on a hit costs a few milliseconds against the ~300 ms the
    render it replaces takes.
    """

    page_cache_timeout = None
    page_cache_alias = "local"

    # A render's CSRF token cannot be cached with the rest of the page: it is
    # masked from the secret in *that* visitor's cookie, so replaying it hands
    # every later visitor a token their own cookie will not match - and the
    # cache hit does not render a template, so nothing calls `get_token` and
    # no cookie is set at all. The contact form in `base.html` therefore 403'd
    # for anyone whose first page was a cached one. The token is swapped for a
    # sentinel on the way in and re-minted per request on the way out, which
    # keeps the page cacheable and the secret per-visitor. NUL bytes cannot
    # occur in the rendered HTML, so the sentinel cannot collide with it.
    CSRF_TOKEN_SENTINEL = b"\x00csrf-token\x00"
    CSRF_INPUT_RE = re.compile(rb'name="csrfmiddlewaretoken" value="([^"]+)"')
    # The CSP nonce is the second per-request token, and the same trap: the
    # Content-Security-Policy header carries a fresh nonce on every
    # response, so a cached page replaying the nonce it was rendered with
    # would have every inline script fail the policy. Stashed and re-minted
    # the same way; every copy of it (script tags, htmx's inlineScriptNonce)
    # shares one value, so one replace catches them all.
    CSP_NONCE_SENTINEL = b"\x00csp-nonce\x00"
    CSP_NONCE_RE = re.compile(rb'nonce="([^"]+)"')

    CACHE_HEADER_SKIP = {
        "content-length",
        "content-type",
        "transfer-encoding",
        "connection",
    }

    def get_page_cache_key(self):
        raise NotImplementedError("Subclasses must implement get_page_cache_key()")

    @classmethod
    def _serialize_headers(cls, response):
        headers = {}
        for name, value in response.headers.items():
            if name.lower() in cls.CACHE_HEADER_SKIP:
                continue
            headers[name] = value
        return headers

    @classmethod
    def _stash_csrf_token(cls, content):
        """Swap this render's CSRF token for the sentinel, if it has one."""
        match = cls.CSRF_INPUT_RE.search(content)
        if match is None:
            return content
        # Replace the value itself, not the input tag, so the copy in
        # `base.html`'s `hx-headers` is caught by the same pass.
        return content.replace(match.group(1), cls.CSRF_TOKEN_SENTINEL)

    @classmethod
    def _stash_csp_nonce(cls, content):
        """Swap this render's CSP nonce for the sentinel, if it has one."""
        match = cls.CSP_NONCE_RE.search(content)
        if match is None:
            return content
        return content.replace(match.group(1), cls.CSP_NONCE_SENTINEL)

    @classmethod
    def _restore_csp_nonce(cls, request, content):
        """Put this request's nonce, the one its CSP header names, back in."""
        if cls.CSP_NONCE_SENTINEL not in content:
            return content
        # A LazyNonce is falsy until generated, so test for None: str() is
        # what generates it, and the middleware then puts the same value in
        # the header. No nonce at all (no CSP middleware) leaves the
        # attribute empty rather than a NUL byte in the page.
        nonce = get_csp_nonce(request)
        value = str(nonce).encode() if nonce is not None else b""
        return content.replace(cls.CSP_NONCE_SENTINEL, value)

    @classmethod
    def _restore_csrf_token(cls, request, content):
        """Mint a token for this request in place of the sentinel.

        `get_token` marks the cookie for update, so `CsrfViewMiddleware`
        sets it on the way out - whether the visitor arrived with one or not.
        """
        if cls.CSRF_TOKEN_SENTINEL not in content:
            return content
        return content.replace(cls.CSRF_TOKEN_SENTINEL, get_token(request).encode())

    @staticmethod
    def _serialize_cookies(response):
        cookies = {}
        for name, morsel in response.cookies.items():
            if name == settings.CSRF_COOKIE_NAME:
                # Never replay one visitor's CSRF secret to another. Nothing
                # puts it here today - `CsrfViewMiddleware` runs after this -
                # but a middleware reorder should not become a shared secret.
                continue
            max_age = morsel["max-age"] or None
            if max_age is not None:
                try:
                    max_age = int(max_age)
                except (TypeError, ValueError):
                    max_age = None
            cookies[name] = {
                "value": morsel.value,
                "expires": morsel["expires"] or None,
                "max_age": max_age,
                "path": morsel["path"] or "/",
                "domain": morsel["domain"] or None,
                "secure": bool(morsel["secure"]),
                "httponly": bool(morsel["httponly"]),
                "samesite": morsel["samesite"] or None,
            }
        return cookies

    @classmethod
    def _apply_cached_headers(cls, response, headers):
        for name, value in (headers or {}).items():
            if name.lower() in cls.CACHE_HEADER_SKIP:
                continue
            response[name] = value

    @staticmethod
    def _apply_cached_cookies(response, cookies):
        for name, data in (cookies or {}).items():
            response.set_cookie(
                name,
                data.get("value", ""),
                expires=data.get("expires") or None,
                max_age=data.get("max_age"),
                path=data.get("path") or "/",
                domain=data.get("domain") or None,
                secure=bool(data.get("secure")),
                httponly=bool(data.get("httponly")),
                samesite=data.get("samesite") or None,
            )

    def dispatch(self, request, *args, **kwargs):
        is_htmx = (
            request.headers.get("HX-Request")
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.GET.get("partial") == "true"
            or request.GET.get("append") == "true"
        )

        if request.user.is_authenticated or is_htmx or request.method != "GET":
            return super().dispatch(request, *args, **kwargs)

        cache_key = self.get_page_cache_key()
        if cache_key is None:
            return super().dispatch(request, *args, **kwargs)
        # Keyed on the host as well: a page names the other sites by absolute
        # URL (core.sites.site_origin), and those follow the host it was
        # rendered for, so no two hosts may share one copy.
        cache_key = f"{request.get_host()}:{cache_key}"

        cache = caches[self.page_cache_alias]

        # Check cache (store only rendered content to avoid retaining
        # request/context)
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            if isinstance(cached_payload, dict) and "body" in cached_payload:
                content = self._restore_csp_nonce(
                    request,
                    self._restore_csrf_token(
                        request, zlib.decompress(cached_payload["body"])
                    ),
                )
                status = cached_payload.get("status", 200)
                content_type = cached_payload.get("content_type")
                response = HttpResponse(
                    content,
                    status=status,
                    content_type=content_type or "text/html; charset=utf-8",
                )
                self._apply_cached_headers(response, cached_payload.get("headers"))
                self._apply_cached_cookies(response, cached_payload.get("cookies"))
                return response
            # Drop anything older - response objects, and the uncompressed
            # `content` payloads this replaced - and rebuild.
            cache.delete(cache_key)

        # Generate response and cache it
        response = super().dispatch(request, *args, **kwargs)

        # Only cache successful, non-streaming responses (render first)
        if response.status_code == 200 and not getattr(response, "streaming", False):
            if hasattr(response, "render"):
                response.render()
            cache.set(
                cache_key,
                {
                    # Level 1: the saving over level 6 is a few percent on
                    # HTML this repetitive, and this runs in the request.
                    "body": zlib.compress(
                        self._stash_csp_nonce(self._stash_csrf_token(response.content)),
                        1,
                    ),
                    "status": response.status_code,
                    "content_type": response.get("Content-Type"),
                    "headers": self._serialize_headers(response),
                    "cookies": self._serialize_cookies(response),
                },
                self.page_cache_timeout,
            )

        return response


class HTMXPartialMixin:
    """Mixin for views that serve both full pages and HTMX partial responses.

    Set `htmx_partial_template` on your view class to the template path
    that should be used for HTMX requests.
    """

    htmx_partial_template = None

    def get_template_names(self):
        """Return partial template for HTMX requests, full template otherwise."""
        if self.request.headers.get("HX-Request") and self.htmx_partial_template:
            return [self.htmx_partial_template]
        return super().get_template_names()


class StaffOnlyMixin(UserPassesTestMixin):
    """Restrict a view to staff users, hiding it from everyone else.

    Returns 404 rather than 403 so an unlaunched media vertical looks
    absent instead of merely forbidden. The DRF counterpart is
    ``core.permissions.IsStaffOrHide``.
    """

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

    def handle_no_permission(self):
        raise Http404("Page not found")

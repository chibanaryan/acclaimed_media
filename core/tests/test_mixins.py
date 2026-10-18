"""Tests for the shared staff gate: core.mixins and core.permissions."""

import re
import zlib
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from django.http import Http404, HttpResponse
from django.middleware.csrf import _does_token_match, get_token
from django.test import RequestFactory, TestCase
from django.views.generic import View

from core.mixins import AnonymousResponseCacheMixin, StaffOnlyMixin
from core.models import User
from core.permissions import IsStaffOrHide
from core.tests.utils import clear_all_caches


class StaffOnlyView(StaffOnlyMixin, View):
    def get(self, request, *args, **kwargs):
        return HttpResponse("staff only")


class StaffOnlyMixinTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _get(self, user):
        request = self.factory.get("/anything/")
        request.user = user
        return StaffOnlyView.as_view()(request)

    def test_a_staff_user_is_allowed_through(self):
        user = User.objects.create_user(
            username="staffer", password="pw", is_staff=True
        )
        response = self._get(user)
        self.assertEqual(response.status_code, 200)

    def test_a_non_staff_user_gets_404_not_403(self):
        # 404 keeps an unlaunched section looking absent rather than forbidden.
        user = User.objects.create_user(username="plain", password="pw")
        with self.assertRaises(Http404):
            self._get(user)

    def test_an_anonymous_visitor_gets_404(self):
        from django.contrib.auth.models import AnonymousUser

        with self.assertRaises(Http404):
            self._get(AnonymousUser())

    def test_test_func_reports_staff_status(self):
        view = StaffOnlyView()
        view.request = self.factory.get("/anything/")
        view.request.user = User.objects.create_user(
            username="staffer", password="pw", is_staff=True
        )
        self.assertTrue(view.test_func())
        view.request.user = User.objects.create_user(username="plain", password="pw")
        self.assertFalse(view.test_func())


class IsStaffOrHideTests(TestCase):
    def setUp(self):
        self.permission = IsStaffOrHide()
        self.factory = RequestFactory()

    def _request_for(self, user):
        request = self.factory.get("/api/anything/")
        request.user = user
        return request

    def test_a_staff_user_is_allowed_through(self):
        user = User.objects.create_user(
            username="staffer", password="pw", is_staff=True
        )
        self.assertTrue(
            self.permission.has_permission(self._request_for(user), mock.Mock())
        )

    def test_a_non_staff_user_gets_404_not_403(self):
        user = User.objects.create_user(username="plain", password="pw")
        with self.assertRaises(Http404):
            self.permission.has_permission(self._request_for(user), mock.Mock())

    def test_an_anonymous_visitor_gets_404(self):
        from django.contrib.auth.models import AnonymousUser

        with self.assertRaises(Http404):
            self.permission.has_permission(
                self._request_for(AnonymousUser()), mock.Mock()
            )


class CachedPage(AnonymousResponseCacheMixin, View):
    page_cache_timeout = 60

    def get(self, request, *args, **kwargs):
        return HttpResponse("rendered")

    def get_page_cache_key(self):
        return "example_page"


class CachedPageWithForm(AnonymousResponseCacheMixin, View):
    """A cached page carrying a CSRF token, as every real one does."""

    page_cache_timeout = 60

    def get(self, request, *args, **kwargs):
        token = get_token(request)
        return HttpResponse(
            f'<body hx-headers=\'{{"X-CSRFToken": "{token}"}}\'>'
            f'<input type="hidden" name="csrfmiddlewaretoken" value="{token}">'
            "</body>"
        )

    def get_page_cache_key(self):
        return "example_form_page"


class CachedPageCsrfTests(TestCase):
    """A cached page's CSRF token has to be minted per request.

    Replaying one visitor's token hands the next a value their own cookie
    cannot match, and a cache hit renders no template, so nothing calls
    `get_token` and no cookie is set at all. That 403'd the contact form in
    `base.html` for anyone whose first page was a cached one.
    """

    TOKEN = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')

    def setUp(self):
        self.factory = RequestFactory()
        clear_all_caches()

    def _get(self):
        request = self.factory.get("/anything/")
        request.user = AnonymousUser()
        response = CachedPageWithForm.as_view()(request)
        return request, response

    def _token(self, response):
        return self.TOKEN.search(response.content.decode()).group(1)

    def test_each_request_gets_its_own_token(self):
        _, cold = self._get()
        _, hit = self._get()
        self.assertNotEqual(self._token(cold), self._token(hit))

    def test_the_cache_hit_asks_for_a_cookie_to_be_set(self):
        self._get()
        request, _ = self._get()
        # `get_token` sets this, and `CsrfViewMiddleware` reads it on the way
        # out; without it the visitor gets a token and no cookie.
        self.assertTrue(request.META.get("CSRF_COOKIE_NEEDS_UPDATE"))

    def test_the_token_matches_the_secret_it_was_minted_from(self):
        self._get()
        request, hit = self._get()
        self.assertTrue(
            _does_token_match(self._token(hit), request.META["CSRF_COOKIE"])
        )

    def test_both_copies_of_the_token_are_replaced(self):
        # `base.html` repeats it in `hx-headers`; one pass has to catch both.
        self._get()
        _, hit = self._get()
        body = hit.content.decode()
        self.assertEqual(body.count(self._token(hit)), 2)

    def test_the_sentinel_never_reaches_a_visitor(self):
        self._get()
        _, hit = self._get()
        self.assertNotIn(AnonymousResponseCacheMixin.CSRF_TOKEN_SENTINEL, hit.content)

    def test_a_page_with_no_token_is_stored_untouched(self):
        content = b"<p>nothing to stash</p>"
        self.assertEqual(
            AnonymousResponseCacheMixin._stash_csrf_token(content), content
        )

    def test_a_body_with_no_sentinel_is_served_untouched(self):
        content = b"<p>nothing to restore</p>"
        request = self.factory.get("/anything/")
        self.assertEqual(
            AnonymousResponseCacheMixin._restore_csrf_token(request, content),
            content,
        )

    def test_a_csrf_cookie_is_never_cached(self):
        # Nothing puts one here today - CsrfViewMiddleware runs after this -
        # but replaying it would give every visitor one shared secret.
        response = HttpResponse("ok")
        response.set_cookie(settings.CSRF_COOKIE_NAME, "shared-secret")
        response.set_cookie("harmless", "1")
        serialized = AnonymousResponseCacheMixin._serialize_cookies(response)
        self.assertNotIn(settings.CSRF_COOKIE_NAME, serialized)
        self.assertIn("harmless", serialized)


class AnonymousResponseCacheAliasTests(TestCase):
    """Whole pages belong on the per-process alias, not the shared cache.

    If this ever reverts, production starts writing every anonymous page's
    full HTML into Postgres and culling the shared filter options out of it.
    """

    def setUp(self):
        self.factory = RequestFactory()
        clear_all_caches()

    def _get(self):
        request = self.factory.get("/anything/")
        request.user = AnonymousUser()
        return CachedPage.as_view()(request)

    def test_the_rendered_page_is_stored_on_the_local_alias(self):
        self._get()
        self.assertIsNotNone(caches["local"].get("example_page"))

    def test_the_shared_cache_is_left_alone(self):
        self._get()
        self.assertIsNone(caches["default"].get("example_page"))

    def test_a_cached_page_is_served_back(self):
        self._get()
        caches["local"].set(
            "example_page",
            {
                "body": zlib.compress(b"from the cache"),
                "status": 200,
                "content_type": None,
            },
            60,
        )
        self.assertEqual(self._get().content, b"from the cache")

    def test_the_stored_body_is_deflated(self):
        # Uncompressed, ~50 cacheable URLs at ~1.4 MB each would be 60-70 MB
        # in every worker.
        self._get()
        payload = caches["local"].get("example_page")
        self.assertNotIn("content", payload)
        self.assertEqual(zlib.decompress(payload["body"]), self._get().content)

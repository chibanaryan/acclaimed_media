"""Tests for the shared staff gate: core.mixins and core.permissions."""

from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from django.http import Http404, HttpResponse
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
            {"content": b"from the cache", "status": 200, "content_type": None},
            60,
        )
        self.assertEqual(self._get().content, b"from the cache")

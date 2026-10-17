"""Tests for the shared staff gate: core.mixins and core.permissions."""

from unittest import mock

from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase
from django.views.generic import View

from core.mixins import StaffOnlyMixin
from core.models import User
from core.permissions import IsStaffOrHide


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

"""Shared DRF permissions for the multi-media platform."""

from django.http import Http404
from rest_framework.permissions import BasePermission


class IsStaffOrHide(BasePermission):
    """Allow staff through and 404 for everyone else.

    Hides an unlaunched media vertical's API instead of advertising it
    with a 403. The view-level counterpart is ``core.mixins.StaffOnlyMixin``.
    """

    def has_permission(self, request, view):
        if request.user.is_authenticated and request.user.is_staff:
            return True
        raise Http404("Page not found")

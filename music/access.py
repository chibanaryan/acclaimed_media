"""
Who can see the music section.

``settings.MUSIC_ENABLED`` is the public-launch switch. Off, the section is a
staff-only beta and has to look absent to everyone else, so every gate here
raises 404 rather than 403. On, anyone may read it; writing still needs a
login, which each write view asks for in its own section's usual way.

One predicate, two gates. Books keeps ``core.mixins.StaffOnlyMixin`` and
``core.permissions.IsStaffOrHide``; music no longer uses either, except for
the import page, which is staff-only whatever the flag says.
"""

from django.conf import settings
from django.http import Http404
from rest_framework.authentication import SessionAuthentication


def music_visible_to(user):
    """Whether ``user`` may see the music section at all."""
    if settings.MUSIC_ENABLED:
        return True
    return user.is_authenticated and user.is_staff


class MusicVisibleMixin:
    """404 a view for anyone the section is hidden from.

    A plain ``dispatch`` check, deliberately not a ``UserPassesTestMixin``:
    that mixin's ``handle_no_permission`` would override
    ``LoginRequiredMixin``'s on the toggle view, and a signed-out visitor to
    the public section would get 404 where games gives a login redirect.
    """

    def dispatch(self, request, *args, **kwargs):
        if not music_visible_to(request.user):
            raise Http404("Page not found")
        return super().dispatch(request, *args, **kwargs)


class MusicAPIGateMixin:
    """The DRF counterpart, gating before authentication runs.

    ``DEFAULT_AUTHENTICATION_CLASSES`` is empty project-wide, so naming
    ``SessionAuthentication`` is what lets a browser session through at all.
    But DRF authenticates before it checks permissions, and
    ``SessionAuthentication`` enforces CSRF for any logged-in user - so with
    the gate as a permission class, a signed-in non-staff POST without a
    token got DRF's "CSRF Failed" 403 instead of 404, which told them the
    endpoint existed. The gate therefore runs first, on the Django request's
    own session user, which does not trigger DRF's authenticators.
    """

    authentication_classes = [SessionAuthentication]

    def initial(self, request, *args, **kwargs):
        if not music_visible_to(request._request.user):
            raise Http404("Page not found")
        super().initial(request, *args, **kwargs)

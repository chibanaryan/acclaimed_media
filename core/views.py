from django.http import Http404
from django.urls import reverse
from django.views.csrf import csrf_failure as default_csrf_failure


def csrf_failure(request, reason=""):
    """Answer a failed CSRF check with 404 inside a staff-only section.

    `CsrfViewMiddleware` rejects a token-less POST before the view's
    `StaffOnlyMixin` runs, so without this every `/music/` path answered an
    anonymous POST with 403 - and a path that does not resolve 404s, so the
    difference told an outsider which music URLs exist. Staff still get the
    real 403, since a failed check is worth seeing when it is yours.
    """
    user = request.user
    if request.path_info.startswith(reverse("music:home")) and not (
        user.is_authenticated and user.is_staff
    ):
        raise Http404("Page not found")
    return default_csrf_failure(request, reason=reason)

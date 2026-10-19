from django.http import Http404
from django.urls import reverse
from django.views.csrf import csrf_failure as default_csrf_failure

from music.access import music_visible_to


def csrf_failure(request, reason=""):
    """Answer a failed CSRF check with 404 inside a hidden section.

    `CsrfViewMiddleware` rejects a token-less POST before the view's own
    gate runs, so without this every `/music/` path answered an anonymous
    POST with 403 while the section was hidden - and a path that does not
    resolve 404s, so the difference told an outsider which music URLs exist.
    Anyone the section is visible to (staff, or everyone once
    `MUSIC_ENABLED` is on) gets the real 403, as on the rest of the site.
    """
    if request.path_info.startswith(reverse("music:home")) and not (
        music_visible_to(request.user)
    ):
        raise Http404("Page not found")
    return default_csrf_failure(request, reason=reason)

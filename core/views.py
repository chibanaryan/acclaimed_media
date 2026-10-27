import logging

from django.db import Error as DatabaseError, connection
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.views.csrf import csrf_failure as default_csrf_failure

from music.access import music_visible_to

logger = logging.getLogger(__name__)


def healthz(request):
    """200 when Django can reach the database, 503 when it cannot.

    For uptime monitoring. Neither existing check proves the database is up:
    the gzip-less monitor gets UncompressedUptimeCheckMiddleware's 2-byte
    answer, which touches nothing, and the other fetches `/`, which can be
    served from the per-process page cache for minutes. Exempt from rate
    limiting, never cached. Catches ``django.db.Error``, which also covers
    an ``InterfaceError`` from a connection the database dropped.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        response = HttpResponse("ok", content_type="text/plain")
    except DatabaseError:
        logger.exception("Health check could not reach the database")
        response = HttpResponse(
            "database unavailable", status=503, content_type="text/plain"
        )
    response["Cache-Control"] = "no-store"
    return response


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

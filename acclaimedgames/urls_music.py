"""
URLconf of music.acclaimedmedia.org.

The section that lived under ``/music/`` and ``/api/music/`` at the apex now
sits at the root of its own host, under the same URL names: ``music:...``
and ``music-api:...``. ``urls_root`` redirects the old paths.

The album detail page is the catch-all ``<slug>/``, so the shared routes go
first, and every first segment they use is in
``music.config.RESERVED_ALBUM_SLUGS``.
"""

from django.urls import include, path

from acclaimedgames.urls_common import common_urlpatterns, with_debug_and_static
from core.sitemaps import for_site
from music.sitemaps import music_sitemaps

handler404 = "games.views.custom_404_view"

urlpatterns = with_debug_and_static(
    [
        *common_urlpatterns(for_site("music", music_sitemaps)),
        path("api/", include("music.api.urls", namespace="music-api")),
        path("", include("music.urls", namespace="music")),
    ]
)

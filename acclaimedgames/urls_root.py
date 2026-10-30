"""
URLconf of the apex, acclaimedmedia.org: the landing page.

Besides the shared routes it serves only ``/``. Every other path is one the
apex served before the games and music sites moved to their own subdomains,
so it is redirected to the site that serves it now
(``core.views.redirect_to_site``).
"""

from django.urls import re_path

from acclaimedgames.urls_common import common_urlpatterns, with_debug_and_static
from core import views as core_views
from core.sitemaps import root_sitemaps

handler404 = "games.views.custom_404_view"

urlpatterns = with_debug_and_static(
    [
        re_path(r"^$", core_views.LandingView.as_view(), name="landing"),
        *common_urlpatterns(root_sitemaps),
    ]
)
# After the static routes, so /static/ is still served in development
urlpatterns.append(re_path(r"^.*$", core_views.redirect_to_site))

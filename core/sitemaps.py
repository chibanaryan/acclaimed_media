"""
Sitemaps per site.

Each host serves its own ``sitemap.xml`` (``acclaimedgames/urls_*.py``).
Django names every ``<loc>`` with the ``Site`` row's domain, which is the
apex; ``for_site`` makes a site's sitemaps name that site's own origin
instead.
"""

from urllib.parse import urlsplit

from django.contrib.sitemaps import Sitemap

from core import sites
from games.sitemaps import PageSitemap


def for_site(site, sitemaps):
    """``sitemaps`` with every ``<loc>`` on ``site``'s public origin."""
    origin = urlsplit(sites.canonical_origin(site))

    def get_domain(self, site=None):
        return origin.netloc

    return {
        name: type(
            cls.__name__, (cls,), {"get_domain": get_domain, "protocol": origin.scheme}
        )
        for name, cls in sitemaps.items()
    }


class LandingSitemap(Sitemap):
    """The apex's one page."""

    priority = 1.0
    changefreq = "weekly"

    def items(self):
        return ["landing"]

    def location(self, item):
        return sites.site_reverse(sites.ROOT, item)


# The shared pages (About, Donate...) are served on every site and listed
# here, at the apex, where their canonical links point
root_sitemaps = for_site(sites.ROOT, {"landing": LandingSitemap, "pages": PageSitemap})

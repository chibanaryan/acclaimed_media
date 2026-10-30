"""
Middleware shared by every site.
"""

from django.conf import settings
from django.core.exceptions import DisallowedHost

from core import sites


class SiteHostMiddleware:
    """Route a request to its site's URLconf by host.

    Sets ``request.site_key`` (``"root"``, ``"games"`` or ``"music"``) and,
    for a host that names a site, ``request.urlconf``, which Django uses to
    resolve the path and as the default for every ``reverse()`` while the
    request is handled. Any other host keeps ``ROOT_URLCONF`` and is
    recorded as the site that URLconf belongs to.

    A host outside ``ALLOWED_HOSTS`` is left for ``CommonMiddleware`` to
    reject with its usual 400.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            site = sites.site_for_host(request.get_host())
        except DisallowedHost:
            site = None
        if site is None:
            site = sites.default_site()
        else:
            request.urlconf = settings.SITE_URLCONFS[site]
        request.site_key = site
        return self.get_response(request)

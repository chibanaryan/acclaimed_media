"""
The three sites one app serves, told apart by host.

``acclaimedmedia.org`` is the landing page, ``games.acclaimedmedia.org`` the
game rankings and ``music.acclaimedmedia.org`` the album rankings. Each has its
own URLconf (``settings.SITE_URLCONFS``), which
``core.middleware.SiteHostMiddleware`` sets on the request, so ``reverse()``
and ``{% url %}`` give paths on the current host. A link to another site needs
its origin as well: ``site_url()`` and the ``{% site_url %}`` tag.

In development the same names work under ``localhost``: ``localhost:8000``,
``games.localhost:8000``, ``music.localhost:8000``. Any other host - the test
client's ``testserver``, ``127.0.0.1`` - gets ``ROOT_URLCONF`` and the site it
belongs to, which is how a test picks a site: override ``ROOT_URLCONF``.
"""

from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http.request import split_domain_port
from django.urls import reverse

ROOT = "root"
GAMES = "games"
MUSIC = "music"
SUBDOMAIN_SITES = (GAMES, MUSIC)
# Each site's front page, by URL name in its own URLconf
HOME_VIEWS = {ROOT: "landing", GAMES: "home", MUSIC: "music:home"}

# Base domains a site label may sit under: production's apex, and localhost
# for development
LOCAL_BASE = "localhost"


def _base_domains():
    return (urlsplit(settings.SITE_ORIGINS[ROOT]).hostname, LOCAL_BASE)


def _split_host(host):
    """``(site, base)`` for a ``host[:port]`` this app serves, else ``(None, None)``.

    ``base`` keeps a dev server's port, so a link built from it stays there.
    Not a port on the public domain: the router forwards whatever a caller
    writes in ``Host``, and every link to another site carried it
    (``https://music.acclaimedmedia.org:8443/``).
    """
    hostname, _, port = host.lower().partition(":")
    # Django's ALLOWED_HOSTS check accepts a fully qualified "example.org."
    hostname = hostname.rstrip(".")
    for base in _base_domains():
        suffix = f":{port}" if port and base == LOCAL_BASE else ""
        if hostname == base:
            return ROOT, base + suffix
        label, _, rest = hostname.partition(".")
        if rest == base and label in SUBDOMAIN_SITES:
            return label, base + suffix
    return None, None


def site_for_host(host):
    """The site ``host`` names, or None for a host that names none."""
    return _split_host(host)[0]


def default_site():
    """The site ``ROOT_URLCONF`` belongs to: the one an unknown host gets."""
    for site, urlconf in settings.SITE_URLCONFS.items():
        if urlconf == settings.ROOT_URLCONF:
            return site
    return GAMES


def request_site(request):
    """The site a request is for, as ``SiteHostMiddleware`` recorded it."""
    return getattr(request, "site_key", None) or default_site()


def _request_host(request):
    try:
        return request.get_host()
    except DisallowedHost:
        return ""


def host_key(request):
    """The request's host, spelt one way, for a cache key.

    Without its case or trailing dot, and without its port, each of which
    the router passes through as the caller wrote it: keyed on
    ``get_host()``, a page had a copy for every port anyone cared to name.
    A dev server's port is kept, as `site_origin` keeps it in the links it
    writes into a page, so a key and its page always agree.
    """
    host = _request_host(request)
    site, base = _split_host(host)
    if site is None:
        return split_domain_port(host)[0]
    return base if site == ROOT else f"{site}.{base}"


def canonical_origin(site):
    """``site``'s public origin, for canonical links and structured data."""
    return settings.SITE_ORIGINS[site]


def site_origin(site, request=None):
    """The origin to link to ``site`` from ``request``.

    On a host this app recognises it is the same base domain, scheme and port
    with ``site``'s label - so a link from ``games.localhost:8000`` to music
    stays on the dev server. Otherwise, and without a request, it is the
    public origin.
    """
    if request is not None:
        _, base = _split_host(_request_host(request))
        if base:
            host = base if site == ROOT else f"{site}.{base}"
            return f"{request.scheme}://{host}"
    return canonical_origin(site)


def site_reverse(site, viewname, args=None, kwargs=None):
    """``viewname``'s path on ``site``, whichever host is being served.

    For URLs a model or a management command builds, which must not depend
    on the URLconf of the request that happens to be running.
    """
    return reverse(
        viewname, urlconf=settings.SITE_URLCONFS[site], args=args, kwargs=kwargs
    )


def site_url(site, viewname, *args, request=None, **kwargs):
    """The absolute URL of ``viewname`` on ``site``, reversed in its URLconf."""
    path = site_reverse(site, viewname, args=args or None, kwargs=kwargs or None)
    return site_origin(site, request) + path


def canonical_url(site, path):
    """``path`` on ``site``'s public origin."""
    return canonical_origin(site) + path

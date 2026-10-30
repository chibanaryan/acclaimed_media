"""
Custom template context processors.
"""


def feature_flags(request):
    """
    Add feature flags to template context.
    """
    import os

    from django.conf import settings

    from music import config as music_config

    return {
        # Books feature is hidden until ready for public release
        "BOOKS_ENABLED": os.environ.get("BOOKS_ENABLED", "").lower() == "true",
        # Music's public-launch switch. Nav entries key off this alone, not
        # off staff status, so staff see no links while the section is a
        # beta, exactly as before the flag existed.
        "MUSIC_ENABLED": settings.MUSIC_ENABLED,
        # The "Beta" badge on music pages, public or not
        "MUSIC_BETA": music_config.MUSIC_BETA,
    }


def media_type(request):
    """
    Add the current site and media type to template context.

    ``site_key`` is the site the host names (core/sites.py): ``"root"`` for
    the landing page, ``"games"`` or ``"music"``; ``site_home_url`` is that
    site's front page. ``media_type`` follows it,
    except that the staff-only books section, which lives on the games host,
    is told apart by its URL namespace. Every page on a site is that site's,
    the shared ones (About, Contact, sign-in) included, so they keep the
    sidebar of the site the visitor is on.
    """
    from django.contrib.auth.models import AnonymousUser

    from core import sites
    from music.access import music_visible_to

    site = sites.request_site(request)
    # The shared pages and the 404s on a hidden music host must not name the
    # section, so they wear the apex's bare chrome
    user = getattr(request, "user", AnonymousUser())
    if site == sites.MUSIC and not music_visible_to(user):
        return {
            "site_key": sites.ROOT,
            "media_type": sites.ROOT,
            "site_home_url": sites.site_url(sites.ROOT, "landing", request=request),
        }
    resolver_match = getattr(request, "resolver_match", None)
    namespace = getattr(resolver_match, "namespace", "") or ""
    if site == sites.GAMES and namespace.startswith("books"):
        kind = "books"
    else:
        kind = site
    return {
        "site_key": site,
        "media_type": kind,
        "site_home_url": sites.site_reverse(site, sites.HOME_VIEWS[site]),
    }


def canonical_origin(request):
    """
    Add the current site's public origin, for canonical links and structured
    data.
    """
    from core import sites

    return {"canonical_origin": sites.canonical_origin(sites.request_site(request))}

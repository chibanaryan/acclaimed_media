"""Cache backend selection, shared by ``settings`` and its tests.

There are three aliases, deliberately.

``default`` is the **shared** cache. In production it is Django's
``DatabaseCache`` on the Postgres we already run, so the gunicorn workers and
whatever one-off dyno a management command lands in all read the same entries.
That is what makes ``music.views._invalidate_music_caches`` mean anything:
under ``LocMemCache`` every process held its own copy and an invalidation
reached exactly one of them, so a metadata refresh left stale genre and artist
filter options behind for up to their 24-hour TTL.

``local`` is a per-process cache and has to stay one. It holds the whole
rendered pages of ``core.mixins.AnonymousResponseCacheMixin`` - entire HTML
bodies, keyed by URL - which are large and need no cross-process agreement: on
a shared backend a crawler working through the SEO URLs would push every page's
HTML into Postgres and cull the handful of shared entries straight back out of
it.

``ratelimit`` holds the per-IP counters in ``games.middleware``. They are
per-process for the same reason, but they are tiny and there are thousands of
them, so they get their own alias rather than sharing ``local``'s entry budget:
page bodies and counters culled each other out of one 500-entry LocMem, which
degraded rate limiting under exactly the crawler load it exists to stop.
"""

import re

import environ

LOCMEM_BACKEND = "django.core.cache.backends.locmem.LocMemCache"
FILE_BACKEND = "django.core.cache.backends.filebased.FileBasedCache"
DATABASE_BACKEND = "django.core.cache.backends.db.DatabaseCache"
DUMMY_BACKEND = "django.core.cache.backends.dummy.DummyCache"

# Postgres holds only the small shared entries - filter options, hero stats,
# counters - so the working set is tens of rows, not thousands. The ceiling is
# generous anyway because Django's default of 300 culls a third of the cache
# on almost every write.
DATABASE_CACHE_OPTIONS = {"MAX_ENTRIES": 5000, "CULL_FREQUENCY": 4}

# Whole-page HTML, keyed by URL. Only the two views using
# `AnonymousResponseCacheMixin` write here, and both decline any request with
# a query string, so this is a handful of keys - but each is a whole page
# (the home page is ~1.4 MB of HTML), and the dyno has 512 MB for every
# worker together, so the ceiling stays low.
LOCAL_CACHE_OPTIONS = {"MAX_ENTRIES": 500}

# One or two integer counters per client IP per hour. A distributed crawl
# needs thousands of them and they cost a few bytes each.
RATELIMIT_CACHE_OPTIONS = {"MAX_ENTRIES": 5000}


def build_default_cache(cache_url, *, debug, test_mode, base_dir):
    """Return the ``default`` (shared) cache config for an environment."""
    if debug and not test_mode and (not cache_url or cache_url.startswith("dbcache")):
        # Local dev stays on LocMem: dbcache would need `createcachetable`
        # run in every new worktree.
        return {"BACKEND": LOCMEM_BACKEND}

    if cache_url:
        config = environ.Env.cache_url_config(cache_url)
        if config["BACKEND"] == DATABASE_BACKEND:
            # `cache_url_config` returns only BACKEND and LOCATION, so the
            # entry limits have to be set here rather than hidden in a
            # Heroku config var.
            config.setdefault("OPTIONS", dict(DATABASE_CACHE_OPTIONS))
        return config

    # No URL and not DEBUG: a file-based cache survives dev server restarts.
    return {"BACKEND": FILE_BACKEND, "LOCATION": base_dir / "django_cache"}


def release_cache_prefix(release):
    """Heroku's ``HEROKU_RELEASE_VERSION``, zero-padded, or "" without one.

    The API's page caches are keyed on it (``games.api.views.cache_page``):
    they live in the shared Postgres cache, which outlives a deploy, so
    without it new code served what old code had cached - the games payload's
    version for up to an hour after a ``SCHEMA_VERSION`` bump. Padded because
    DatabaseCache culls the lowest keys first, in string order: unpadded,
    "v100" sorts before "v99", and the first cull after that deploy would
    evict the live release's entries while the dead ones stayed.

    Only those page caches carry it. The whole alias did until review: that
    reset allauth's and the contact form's rate-limit counters on every
    release, and left a long job's cache invalidation aimed at the release
    it started under. The hand-built caches carry their own version
    constants (``config.CACHE_VERSION``, music's ``CACHE_VERSION``).
    """
    if not release:
        return ""
    return re.sub(r"\d+", lambda m: m[0].zfill(8), release)


def build_caches(cache_url, *, debug, test_mode, base_dir):
    """Return the whole ``CACHES`` setting: a shared alias and two local ones."""
    default = build_default_cache(
        cache_url, debug=debug, test_mode=test_mode, base_dir=base_dir
    )
    return {
        "default": default,
        "local": {
            "BACKEND": LOCMEM_BACKEND,
            "LOCATION": "local",
            "OPTIONS": dict(LOCAL_CACHE_OPTIONS),
        },
        "ratelimit": (
            # Under test the counters are kept nowhere. Django's runner does
            # not clear caches between tests (pytest's conftest does), so a
            # test process that made 120 requests inside a minute started
            # failing unrelated tests with 429s. The tests of the limits
            # override CACHES with a real backend.
            {"BACKEND": DUMMY_BACKEND}
            if test_mode
            else {
                "BACKEND": LOCMEM_BACKEND,
                "LOCATION": "ratelimit",
                "OPTIONS": dict(RATELIMIT_CACHE_OPTIONS),
            }
        ),
    }

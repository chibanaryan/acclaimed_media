"""Cache backend selection, shared by ``settings`` and its tests.

There are two aliases, deliberately.

``default`` is the **shared** cache. In production it is Django's
``DatabaseCache`` on the Postgres we already run, so the three gunicorn
workers and whatever one-off dyno a management command lands in all read the
same entries. That is what makes ``music.views._invalidate_music_caches``
mean anything: under ``LocMemCache`` every process held its own copy and an
invalidation reached exactly one of them, so a metadata refresh left stale
genre and artist filter options behind for up to their 24-hour TTL.

``local`` is a per-process cache and has to stay one. It holds whole rendered
pages - ``UpdateCacheMiddleware``/``FetchFromCacheMiddleware``, which
``settings`` installs in production, and
``core.mixins.AnonymousResponseCacheMixin`` - plus the per-IP rate-limit
counters in ``games.middleware``. Those are large or high-churn and none of
them needs cross-process agreement: a crawler working through the SEO URLs
would otherwise push every page's HTML into Postgres and cull the handful of
shared entries straight back out of it.
"""

import environ

LOCMEM_BACKEND = "django.core.cache.backends.locmem.LocMemCache"
FILE_BACKEND = "django.core.cache.backends.filebased.FileBasedCache"
DATABASE_BACKEND = "django.core.cache.backends.db.DatabaseCache"

# Postgres holds only the small shared entries - filter options, hero stats,
# counters - so the working set is tens of rows, not thousands. The ceiling is
# generous anyway because Django's default of 300 culls a third of the cache
# on almost every write.
DATABASE_CACHE_OPTIONS = {"MAX_ENTRIES": 5000, "CULL_FREQUENCY": 4}

# Whole-page HTML, keyed by URL. Bounded so a crawler cannot grow the heap.
LOCAL_CACHE_OPTIONS = {"MAX_ENTRIES": 500}


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


def build_caches(cache_url, *, debug, test_mode, base_dir):
    """Return the whole ``CACHES`` setting: a shared alias and a local one."""
    return {
        "default": build_default_cache(
            cache_url, debug=debug, test_mode=test_mode, base_dir=base_dir
        ),
        "local": {
            "BACKEND": LOCMEM_BACKEND,
            "LOCATION": "local",
            "OPTIONS": dict(LOCAL_CACHE_OPTIONS),
        },
    }

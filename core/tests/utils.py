"""Helpers shared by the test suites."""

from django.core.cache import caches


def clear_all_caches():
    """Empty every cache alias.

    Tests used to call `cache.clear()`, which only empties `default`. Whole
    rendered pages now live on the per-process `local` alias (see
    `core.cache_config`), so clearing `default` alone lets one test's cached
    page be served to the next one. `conftest.py` does this between tests for
    pytest; this is for the setUp/tearDown calls, which also run under
    Django's own test runner, where there is no conftest.
    """
    for cache in caches.all():
        cache.clear()

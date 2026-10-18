"""Shared pytest fixtures."""

import pytest

from core.tests.utils import clear_all_caches


@pytest.fixture(autouse=True)
def clear_cache_between_tests():
    """Start every test with every cache alias empty.

    `AnonymousResponseCacheMixin` stores rendered home/landing page responses
    in the locmem cache, which outlives the test database rollback. Without
    this, one test's rendered page can be served to another test that happens
    to share an xdist worker, which fails depending on how xdist distributes
    the tests. Both aliases are cleared because whole pages and the
    rate-limit counters live on `local` while everything else is on
    `default`; see `core.cache_config`.
    """
    clear_all_caches()
    yield
    clear_all_caches()

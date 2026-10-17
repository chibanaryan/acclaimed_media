"""Shared pytest fixtures."""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_cache_between_tests():
    """Start every test with an empty cache.

    `AnonymousResponseCacheMixin` stores rendered home/landing page responses
    in the locmem cache, which outlives the test database rollback. Without
    this, one test's rendered page can be served to another test that happens
    to share an xdist worker, which fails depending on how xdist distributes
    the tests.
    """
    cache.clear()
    yield
    cache.clear()

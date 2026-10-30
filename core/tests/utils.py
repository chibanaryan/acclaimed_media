"""Helpers shared by the test suites."""

from django.conf import settings
from django.core.cache import caches
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext


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


@override_settings(
    CACHES={
        **settings.CACHES,
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "cache_table",
        },
    }
)
class DatabaseCacheTestCase(TestCase):
    """A TestCase whose default cache is production's `DatabaseCache`.

    For counting shared-cache round trips (Sentry ACCLAIMED-VIDEO-GAMES-9E),
    which the suite's LocMem default cannot show.
    """

    # What `get_many` sends; a write's SELECTs differ
    CACHE_READ = 'FROM "cache_table" WHERE "cache_key" IN ('

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The test database was built while the default alias was LocMem.
        # Inside the class's transaction, so it is rolled back after it.
        call_command("createcachetable", verbosity=0)

    def cache_reads(self, url):
        """The shared-cache reads one GET of ``url`` makes."""
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return [
            query["sql"]
            for query in captured.captured_queries
            if self.CACHE_READ in query["sql"]
        ]

    def warm_cache_reads(self, url):
        """`cache_reads` on a second visit, once the first has filled it."""
        self.assertEqual(self.client.get(url).status_code, 200)
        return self.cache_reads(url)

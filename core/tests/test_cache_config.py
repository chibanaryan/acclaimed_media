"""Tests for the cache backend selection in `core.cache_config`.

The interesting branch - DatabaseCache with explicit entry limits - is the
one production takes and the one no other test can reach, since the suite
runs on locmem.
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from core import cache_config


class BuildDefaultCacheTests(SimpleTestCase):
    """The shared `default` alias, per environment."""

    def _build(self, cache_url, debug=False, test_mode=False):
        return cache_config.build_default_cache(
            cache_url, debug=debug, test_mode=test_mode, base_dir=Path("/tmp/example")
        )

    def test_local_dev_without_a_url_uses_locmem(self):
        config = self._build(None, debug=True)
        self.assertEqual(config["BACKEND"], cache_config.LOCMEM_BACKEND)

    def test_local_dev_ignores_a_dbcache_url(self):
        # dbcache in dev would need createcachetable run in every worktree.
        config = self._build("dbcache://cache_table", debug=True)
        self.assertEqual(config["BACKEND"], cache_config.LOCMEM_BACKEND)

    def test_tests_honour_their_configured_url(self):
        config = self._build("locmemcache://", debug=True, test_mode=True)
        self.assertEqual(config["BACKEND"], cache_config.LOCMEM_BACKEND)
        self.assertEqual(config["LOCATION"], "")

    def test_dbcache_url_gets_a_table_and_entry_limits(self):
        config = self._build("dbcache://cache_table")
        self.assertEqual(config["BACKEND"], cache_config.DATABASE_BACKEND)
        self.assertEqual(config["LOCATION"], "cache_table")
        # Django's default of 300 would cull a third of the cache on almost
        # every write.
        self.assertEqual(config["OPTIONS"]["MAX_ENTRIES"], 5000)
        self.assertEqual(config["OPTIONS"]["CULL_FREQUENCY"], 4)

    def test_dbcache_options_are_not_shared_between_calls(self):
        first = self._build("dbcache://cache_table")
        first["OPTIONS"]["MAX_ENTRIES"] = 1
        second = self._build("dbcache://cache_table")
        self.assertEqual(second["OPTIONS"]["MAX_ENTRIES"], 5000)

    def test_a_non_database_url_is_passed_through_untouched(self):
        config = self._build("locmemcache://")
        self.assertEqual(config["BACKEND"], cache_config.LOCMEM_BACKEND)
        self.assertNotIn("OPTIONS", config)

    def test_no_url_outside_dev_falls_back_to_a_file_cache(self):
        config = self._build(None)
        self.assertEqual(config["BACKEND"], cache_config.FILE_BACKEND)
        self.assertEqual(config["LOCATION"], Path("/tmp/example") / "django_cache")


class BuildCachesTests(SimpleTestCase):
    """Both aliases together."""

    def test_both_aliases_are_defined(self):
        caches = cache_config.build_caches(
            "dbcache://cache_table", debug=False, test_mode=False, base_dir=Path("/tmp")
        )
        self.assertEqual(sorted(caches), ["default", "local"])
        self.assertEqual(caches["default"]["BACKEND"], cache_config.DATABASE_BACKEND)

    def test_the_local_alias_is_always_per_process(self):
        # Whole-page HTML and the rate-limit counters live here, so it must
        # never follow CACHE_URL onto a shared backend.
        for url in (None, "dbcache://cache_table", "locmemcache://"):
            with self.subTest(url=url):
                caches = cache_config.build_caches(
                    url, debug=False, test_mode=False, base_dir=Path("/tmp")
                )
                self.assertEqual(
                    caches["local"]["BACKEND"], cache_config.LOCMEM_BACKEND
                )
                self.assertEqual(caches["local"]["OPTIONS"]["MAX_ENTRIES"], 500)


class SettingsWiringTests(SimpleTestCase):
    """What settings.py did with the above."""

    def test_the_whole_page_middleware_cache_is_the_local_alias(self):
        # Pointing this at `default` would send every anonymous page's HTML
        # into Postgres in production and cull the shared entries out of it.
        self.assertEqual(settings.CACHE_MIDDLEWARE_ALIAS, "local")

    def test_the_local_alias_is_configured(self):
        self.assertIn("local", settings.CACHES)
        self.assertEqual(
            settings.CACHES["local"]["BACKEND"], cache_config.LOCMEM_BACKEND
        )

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
    """All three aliases together."""

    def test_every_alias_is_defined(self):
        caches = cache_config.build_caches(
            "dbcache://cache_table", debug=False, test_mode=False, base_dir=Path("/tmp")
        )
        self.assertEqual(sorted(caches), ["default", "local", "ratelimit"])
        self.assertEqual(caches["default"]["BACKEND"], cache_config.DATABASE_BACKEND)

    def test_the_shared_alias_is_keyed_on_the_release(self):
        """The Postgres cache outlives a deploy; the prefix starts each
        release on keys the previous one never wrote."""
        caches = cache_config.build_caches(
            "dbcache://cache_table",
            debug=False,
            test_mode=False,
            base_dir=Path("/tmp"),
            release="v412",
        )
        self.assertEqual(caches["default"]["KEY_PREFIX"], "v00000412")
        self.assertNotIn("KEY_PREFIX", caches["local"])
        self.assertNotIn("KEY_PREFIX", caches["ratelimit"])

    def test_a_later_release_sorts_after_an_earlier_one(self):
        """DatabaseCache culls the lowest keys first, by string order."""

        def prefix(release):
            return cache_config.build_caches(
                "dbcache://cache_table",
                debug=False,
                test_mode=False,
                base_dir=Path("/tmp"),
                release=release,
            )["default"]["KEY_PREFIX"]

        self.assertLess(prefix("v99"), prefix("v100"))

    def test_no_release_and_tests_get_no_prefix(self):
        for release, test_mode in ((None, False), ("", False), ("v412", True)):
            with self.subTest(release=release, test_mode=test_mode):
                caches = cache_config.build_caches(
                    "locmemcache://",
                    debug=False,
                    test_mode=test_mode,
                    base_dir=Path("/tmp"),
                    release=release,
                )
                self.assertNotIn("KEY_PREFIX", caches["default"])

    def test_the_per_process_aliases_are_always_per_process(self):
        # Whole-page HTML and the rate-limit counters live here, so neither
        # may follow CACHE_URL onto a shared backend.
        for url in (None, "dbcache://cache_table", "locmemcache://"):
            for alias in ("local", "ratelimit"):
                with self.subTest(url=url, alias=alias):
                    caches = cache_config.build_caches(
                        url, debug=False, test_mode=False, base_dir=Path("/tmp")
                    )
                    self.assertEqual(
                        caches[alias]["BACKEND"], cache_config.LOCMEM_BACKEND
                    )

    def test_pages_and_counters_do_not_share_an_entry_budget(self):
        # One 500-entry LocMem held both, so a wide crawl's cached pages
        # culled out the counters meant to stop it.
        caches = cache_config.build_caches(
            "dbcache://cache_table", debug=False, test_mode=False, base_dir=Path("/tmp")
        )
        self.assertNotEqual(
            caches["local"]["LOCATION"], caches["ratelimit"]["LOCATION"]
        )
        self.assertEqual(caches["local"]["OPTIONS"]["MAX_ENTRIES"], 500)
        self.assertEqual(caches["ratelimit"]["OPTIONS"]["MAX_ENTRIES"], 5000)


class SettingsWiringTests(SimpleTestCase):
    """What settings.py did with the above."""

    def test_the_per_process_aliases_are_configured(self):
        for alias in ("local", "ratelimit"):
            with self.subTest(alias=alias):
                self.assertIn(alias, settings.CACHES)
                self.assertEqual(
                    settings.CACHES[alias]["BACKEND"], cache_config.LOCMEM_BACKEND
                )

    def test_there_is_no_site_wide_page_cache_middleware(self):
        # Every page varies on Cookie, so this pair stored a copy of each
        # page per visitor and filled the dyno. `AnonymousResponseCacheMixin`
        # is the whole-page cache; see the comment in settings.py.
        self.assertNotIn(
            "django.middleware.cache.UpdateCacheMiddleware", settings.MIDDLEWARE
        )
        self.assertNotIn(
            "django.middleware.cache.FetchFromCacheMiddleware", settings.MIDDLEWARE
        )

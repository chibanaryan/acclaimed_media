"""The section's cache writes, and what happens when dropping them fails."""

import re
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from core.cache_helpers import batched_cache_reads
from music import config
from music.services import caching
from music.tests.site import setUpModule, tearDownModule  # noqa: F401

KEY = config.CACHE_KEY_HERO_STATS
WRITE = re.compile(
    r"\bcache_set\(|\bcaches\[|\bcache\.(set|add|set_many|get_or_set|incr|touch)\("
)


class CachedTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_a_miss_computes_and_saves(self):
        self.assertEqual(caching.cached(KEY, lambda: "fresh", 60), "fresh")
        self.assertEqual(cache.get(KEY), "fresh")

    def test_a_hit_does_not_compute(self):
        cache.set(KEY, "saved", 60)
        compute = mock.Mock()
        self.assertEqual(caching.cached(KEY, compute, 60), "saved")
        compute.assert_not_called()

    def test_a_falsy_value_is_a_hit(self):
        cache.set(KEY, [], 60)
        compute = mock.Mock()
        self.assertEqual(caching.cached(KEY, compute, 60), [])
        compute.assert_not_called()

    def test_a_read_overtaken_by_an_invalidation_is_not_saved(self):
        """The race: rows read before a commit, saved after its delete."""

        def read_old_rows_then_lose_the_race():
            caching.invalidate_music_caches()
            return "old rows"

        value = caching.cached(KEY, read_old_rows_then_lose_the_race, 60)

        self.assertEqual(value, "old rows")
        self.assertIsNone(cache.get(KEY))

    def test_any_invalidation_overtakes_a_read(self):
        def read_old_rows_then_lose_the_race():
            caching.invalidate_release_caches([1])
            return "old rows"

        caching.cached(KEY, read_old_rows_then_lose_the_race, 60)

        self.assertIsNone(cache.get(KEY))

    def test_a_skipped_value_still_answers_the_rest_of_a_batch(self):
        def read_old_rows_then_lose_the_race():
            caching.invalidate_music_caches()
            return "old rows"

        with batched_cache_reads([KEY]):
            caching.cached(KEY, read_old_rows_then_lose_the_race, 60)
            compute = mock.Mock()
            self.assertEqual(caching.cached(KEY, compute, 60), "old rows")
        compute.assert_not_called()
        self.assertIsNone(cache.get(KEY))

    def test_a_page_batch_answers_the_generation(self):
        with batched_cache_reads([KEY, config.CACHE_KEY_GENERATION]):
            with mock.patch("core.cache_helpers.cache") as spy:
                caching.current_generation()
        spy.get.assert_not_called()

    def test_a_saved_value_reaches_the_rest_of_a_batch(self):
        with batched_cache_reads([KEY]):
            caching.cached(KEY, lambda: "fresh", 60)
            compute = mock.Mock()
            self.assertEqual(caching.cached(KEY, compute, 60), "fresh")
        compute.assert_not_called()


class ClearMusicCachesCommandTests(SimpleTestCase):
    def test_it_says_when_they_are_cleared(self):
        out = StringIO()
        call_command("clear_music_caches", stdout=out)
        self.assertIn("cleared", out.getvalue())

    def test_a_failure_exits_non_zero(self):
        with mock.patch(
            "music.services.caching.invalidate_music_caches", return_value=False
        ):
            with self.assertRaises(CommandError):
                call_command("clear_music_caches")


class EveryWriteIsGuardedTests(SimpleTestCase):
    def test_nothing_in_the_section_writes_the_cache_directly(self):
        """A value saved around the guard can bring the race back for a day."""
        root = Path(settings.BASE_DIR) / "music"
        unguarded = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if "tests" not in path.relative_to(root).parts
            and path.name != "caching.py"
            and WRITE.search(path.read_text())
        ]
        self.assertEqual(unguarded, [])


class DroppingCachesTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_a_failed_drop_is_reported_not_raised(self):
        with mock.patch("music.services.caching.cache") as broken:
            broken.delete_many.side_effect = ConnectionError
            with self.assertLogs("music.services.caching", "ERROR"):
                self.assertFalse(caching.invalidate_music_caches())

    def test_a_good_drop_says_so(self):
        self.assertTrue(caching.invalidate_music_caches())

    def test_a_failed_toggle_drop_cannot_fail_the_commit(self):
        with mock.patch("music.services.caching.cache") as broken:
            broken.delete_many.side_effect = ConnectionError
            with self.assertLogs("music.services.caching", "ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    caching.invalidate_listen_caches([1])

    def test_no_users_means_no_drop(self):
        with self.captureOnCommitCallbacks() as callbacks:
            caching.invalidate_listen_caches(set())
        self.assertEqual(callbacks, [])

    def test_a_release_drop_is_one_call_with_each_key_once(self):
        with mock.patch("music.services.caching.cache") as spy:
            self.assertTrue(caching.invalidate_release_caches({7}))

        spy.delete_many.assert_called_once()
        keys = spy.delete_many.call_args.args[0]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(set(config.CACHE_KEYS) <= set(keys))
        self.assertIn(config.CACHE_KEY_LISTENED_ALBUMS.format(user_id=7), keys)

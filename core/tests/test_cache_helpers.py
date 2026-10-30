"""Tests for `core.cache_helpers.batched_cache_reads` and `cache_get`."""

from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from core.cache_helpers import batched_cache_reads, cache_get, cache_set
from core.tests.utils import clear_all_caches


class BatchedCacheReadsTests(SimpleTestCase):
    """One `get_many` for the block; `cache_get` answers its hits."""

    def setUp(self):
        clear_all_caches()

    def tearDown(self):
        clear_all_caches()

    def test_a_hit_is_answered_from_the_batch(self):
        cache.set("batched:hit", [1, 2])
        with batched_cache_reads(["batched:hit"]):
            with mock.patch.object(cache, "get") as get:
                self.assertEqual(cache_get("batched:hit"), [1, 2])
        get.assert_not_called()

    def test_the_keys_are_read_in_one_call(self):
        with mock.patch.object(cache, "get_many", return_value={}) as get_many:
            with batched_cache_reads(["batched:a", "batched:b"]):
                pass
        get_many.assert_called_once_with(["batched:a", "batched:b"])

    def test_a_miss_is_not_read_again(self):
        # The batch is the answer: a crawler's new filter misses every time
        with batched_cache_reads(["batched:miss"]):
            with mock.patch.object(cache, "get") as get:
                self.assertIsNone(cache_get("batched:miss"))
        get.assert_not_called()

    def test_cache_set_is_seen_by_later_reads_in_the_block(self):
        with batched_cache_reads(["batched:late"]):
            cache_set("batched:late", "set later", 60)
            self.assertEqual(cache_get("batched:late"), "set later")
        self.assertEqual(cache.get("batched:late"), "set later")

    def test_cache_set_of_another_key_leaves_the_batch_alone(self):
        with batched_cache_reads(["batched:hit"]):
            cache_set("batched:other", "direct", 60)
            self.assertEqual(cache_get("batched:other"), "direct")

    def test_cache_set_outside_a_block_is_cache_set(self):
        cache_set("batched:plain", "plain", 60)
        self.assertEqual(cache.get("batched:plain"), "plain")

    def test_a_key_outside_the_batch_is_read_directly(self):
        cache.set("batched:other", "direct")
        with batched_cache_reads(["batched:hit"]):
            self.assertEqual(cache_get("batched:other"), "direct")

    def test_outside_a_block_it_is_cache_get(self):
        cache.set("batched:plain", "plain")
        self.assertEqual(cache_get("batched:plain"), "plain")
        self.assertIsNone(cache_get("batched:absent"))

    def test_the_batch_ends_with_its_block_even_on_an_error(self):
        cache.set("batched:hit", "old")
        with self.assertRaises(RuntimeError):
            with batched_cache_reads(["batched:hit"]):
                raise RuntimeError
        cache.set("batched:hit", "new")
        self.assertEqual(cache_get("batched:hit"), "new")

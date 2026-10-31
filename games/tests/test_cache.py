"""Games' invalidated caches: when a drop lands, and reads it overtakes."""

from unittest import mock

from django.core.cache import cache
from django.db import transaction
from django.test import TestCase

from core.cache_helpers import cached
from core.models import User
from core.tests.utils import CommitHooksRunNowMixin, clear_all_caches
from games import cache as games_cache
from games import config
from games.cache import HERO_STATS_CACHE_KEY
from games.models import Developer, Game, List, PlayedGame, Publication
from games.services.percentile_service import get_played_counts
from games.services.user_tracking_service import reconnect_tracking_records
from games.views import _get_hero_stats


class DropOnCommitTests(TestCase):
    def setUp(self):
        clear_all_caches()

    def test_a_save_inside_a_transaction_waits_for_the_commit(self):
        """A read before the commit would put the old count back for a day."""
        cache.set(HERO_STATS_CACHE_KEY, {"game_count": 1}, 60)

        with self.captureOnCommitCallbacks() as callbacks:
            Game.objects.create(name="G", slug="g", rank=1)

        self.assertIsNotNone(cache.get(HERO_STATS_CACHE_KEY))
        for callback in callbacks:
            callback()
        self.assertIsNone(cache.get(HERO_STATS_CACHE_KEY))

    def test_an_ordinary_save_keeps_the_hero_stats(self):
        """The weekly refresh saves every game; no count moves."""
        game = Game.objects.create(name="G", slug="g", rank=1)
        cache.set(HERO_STATS_CACHE_KEY, {"game_count": 1}, 60)

        with self.captureOnCommitCallbacks(execute=True):
            game.name = "Renamed"
            game.save()

        self.assertIsNotNone(cache.get(HERO_STATS_CACHE_KEY))

    def test_many_saves_make_one_drop_per_family(self):
        """An import saves a thousand rows; each drop is several queries."""
        with mock.patch("core.cache_helpers.drop_keys") as drop:
            with self.captureOnCommitCallbacks(execute=True):
                for n in range(5):
                    Game.objects.create(name=f"G{n}", slug=f"g{n}", rank=n + 1)
                Developer.objects.create(name="D", slug="d", igdb_id=1)

        self.assertEqual(
            sorted(call.args[1] for call in drop.call_args_list),
            sorted([games_cache.GENERATION_HERO, games_cache.GENERATION_DEVELOPERS]),
        )

    def test_a_drop_lost_to_a_savepoint_is_queued_again(self):
        cache.set(HERO_STATS_CACHE_KEY, {"game_count": 1}, 60)
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValueError):
                with transaction.atomic():
                    Game.objects.create(name="G1", slug="g1", rank=1)
                    raise ValueError
            Game.objects.create(name="G2", slug="g2", rank=2)
        self.assertIsNone(cache.get(HERO_STATS_CACHE_KEY))

    def test_a_rolled_back_save_drops_nothing(self):
        cache.set(HERO_STATS_CACHE_KEY, {"game_count": 1}, 60)

        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValueError):
                with transaction.atomic():
                    Game.objects.create(name="G", slug="g", rank=1)
                    raise ValueError

        self.assertIsNotNone(cache.get(HERO_STATS_CACHE_KEY))

    def test_a_cache_error_cannot_fail_the_commit(self):
        with mock.patch(
            "core.cache_helpers.cache.delete_many", side_effect=ConnectionError
        ):
            with self.assertLogs("core.cache_helpers", "ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    Game.objects.create(name="G", slug="g", rank=1)

    def test_a_played_game_drops_the_played_counts(self):
        """An admin edit or a deleted user reaches the rank line too."""
        user = User.objects.create_user(username="reader", password="pw")
        game = Game.objects.create(name="G", slug="g", rank=1, igdb_id=1)
        self.assertEqual(get_played_counts(), [])

        with self.captureOnCommitCallbacks(execute=True):
            PlayedGame.objects.create(user=user, game=game, igdb_id=1)

        self.assertEqual(get_played_counts(), [1])

    def test_reconnecting_a_row_drops_the_played_counts(self):
        user = User.objects.create_user(username="reader", password="pw")
        PlayedGame.objects.create(user=user, game=None, igdb_id=7)
        self.assertEqual(get_played_counts(), [])
        game = Game.objects.create(name="G", slug="g", rank=1, igdb_id=7)

        with self.captureOnCommitCallbacks(execute=True):
            reconnect_tracking_records(game, [7], 7)

        self.assertEqual(get_played_counts(), [1])


class HeroStatsSendersTests(CommitHooksRunNowMixin, TestCase):
    """Each count the heading holds has its own sender."""

    def setUp(self):
        clear_all_caches()
        self.publication = Publication.objects.create(name="Mag")
        self.list = List.objects.create(
            name="L", publisher=self.publication, year=2000, type="A"
        )

    def _dropped_by(self, change):
        cache.set(HERO_STATS_CACHE_KEY, {"list_count": 1}, 60)
        change()
        return cache.get(HERO_STATS_CACHE_KEY) is None

    def test_adding_a_list(self):
        self.assertTrue(
            self._dropped_by(
                lambda: List.objects.create(
                    name="M", publisher=self.publication, year=2001, type="A"
                )
            )
        )

    def test_deleting_a_list(self):
        self.assertTrue(self._dropped_by(self.list.delete))

    def test_adding_a_publication(self):
        self.assertTrue(
            self._dropped_by(lambda: Publication.objects.create(name="Other"))
        )

    def test_deleting_a_publication(self):
        self.assertTrue(self._dropped_by(self.publication.delete))

    def test_renaming_a_list_is_not_a_count_change(self):
        self.list.name = "Renamed"
        self.assertFalse(self._dropped_by(self.list.save))


class OvertakenReadTests(TestCase):
    def setUp(self):
        clear_all_caches()

    def test_a_read_overtaken_by_a_drop_is_not_saved(self):
        def read_old_rows_then_lose_the_race():
            with self.captureOnCommitCallbacks(execute=True):
                games_cache.invalidate_hero_stats()
            return "old rows"

        value = cached(
            HERO_STATS_CACHE_KEY,
            read_old_rows_then_lose_the_race,
            60,
            games_cache.GENERATION_HERO,
        )

        self.assertEqual(value, "old rows")
        self.assertIsNone(cache.get(HERO_STATS_CACHE_KEY))

    def test_a_drop_in_one_family_does_not_cancel_anothers_save(self):
        """The hero family moves while games change; the rest must still cache."""
        key = config.CACHE_KEY_PLAYED_COUNTS

        def read_while_a_game_is_added():
            with self.captureOnCommitCallbacks(execute=True):
                games_cache.invalidate_hero_stats()
            return "fresh"

        cached(key, read_while_a_game_is_added, 60, games_cache.GENERATION_TRACKING)

        self.assertEqual(cache.get(key), "fresh")

    def test_a_developer_deleted_mid_render_is_a_404(self):
        developer = Developer.objects.create(name="D", slug="d", igdb_id=1)

        with mock.patch(
            "games.views.developers.current_generation",
            side_effect=lambda _key: Developer.objects.filter(pk=developer.pk).delete(),
        ):
            self.assertEqual(self.client.get("/developers/d/").status_code, 404)

    def test_hero_stats_are_read_through_the_guard(self):
        Game.objects.create(name="G", slug="g", rank=1)
        clear_all_caches()
        self.assertEqual(_get_hero_stats()["game_count"], 1)
        self.assertEqual(cache.get(HERO_STATS_CACHE_KEY)["game_count"], 1)

    def test_a_developer_page_built_over_a_change_is_not_saved(self):
        developer = Developer.objects.create(name="D", slug="d", igdb_id=1)
        key = games_cache.developer_detail_cache_key(developer.id)

        def change_it_mid_build(_developer):
            with self.captureOnCommitCallbacks(execute=True):
                games_cache.invalidate_developer_detail(developer.id)

        with mock.patch(
            "games.views.developers.DeveloperDetailView._prefetch_hierarchy",
            side_effect=change_it_mid_build,
        ):
            self.assertEqual(self.client.get("/developers/d/").status_code, 200)

        self.assertIsNone(cache.get(key))

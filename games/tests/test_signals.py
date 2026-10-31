"""Tests for Django signals in the games app."""

from django.core.cache import cache
from django.test import TestCase

from core.tests.utils import CommitHooksRunNowMixin, clear_all_caches
from games import config
from games.models import Developer, Game, WikipediaGenre


class DeveloperCacheInvalidationSignalTests(CommitHooksRunNowMixin, TestCase):
    """Tests for developer hierarchy cache invalidation signals."""

    def setUp(self):
        """Clear cache before each test."""
        clear_all_caches()

    def tearDown(self):
        """Clear cache after each test."""
        clear_all_caches()

    def test_developer_save_invalidates_cache(self):
        """Test that saving a developer invalidates the hierarchy cache."""
        from games.services.developer_service import DEVELOPER_HIERARCHY_CACHE_KEY

        # Pre-populate cache
        cache.set(DEVELOPER_HIERARCHY_CACHE_KEY, {"test": "data"})

        # Save a developer (triggers post_save signal)
        Developer.objects.create(name="Test Dev", igdb_id=1)

        # Cache should be invalidated
        self.assertIsNone(cache.get(DEVELOPER_HIERARCHY_CACHE_KEY))

    def test_developer_delete_invalidates_cache(self):
        """Test that deleting a developer invalidates the hierarchy cache."""
        from games.services.developer_service import DEVELOPER_HIERARCHY_CACHE_KEY

        dev = Developer.objects.create(name="Test Dev", igdb_id=1)

        # Pre-populate cache
        cache.set(DEVELOPER_HIERARCHY_CACHE_KEY, {"test": "data"})

        # Delete developer (triggers post_delete signal)
        dev.delete()

        # Cache should be invalidated
        self.assertIsNone(cache.get(DEVELOPER_HIERARCHY_CACHE_KEY))

    def test_developer_detail_cache_invalidated_on_change(self):
        """Test that developer detail page cache is invalidated."""
        dev = Developer.objects.create(name="Test Dev", igdb_id=1)

        # Pre-populate detail cache
        cache_key = f"{config.CACHE_VERSION}:developer_detail:{dev.id}"
        cache.set(cache_key, {"detail": "cached"})

        # Update developer
        dev.name = "Updated Name"
        dev.save()

        # Detail cache should be invalidated
        self.assertIsNone(cache.get(cache_key))

    def test_subsidiary_change_invalidates_root_cache(self):
        """Test that changing a subsidiary invalidates root developer's cache."""
        parent = Developer.objects.create(name="Parent", igdb_id=1, slug="parent")
        child = Developer.objects.create(name="Child", igdb_id=2, parent=parent)

        # Pre-populate root's detail cache
        parent_cache_key = f"{config.CACHE_VERSION}:developer_detail:{parent.id}"
        cache.set(parent_cache_key, {"detail": "cached"})

        # Update child
        child.name = "Updated Child"
        child.save()

        # Parent's detail cache should be invalidated
        self.assertIsNone(cache.get(parent_cache_key))

    def test_a_studio_moving_parent_drops_the_root_it_left(self):
        """The old root's page still lists the studio and its games."""
        old_root = Developer.objects.create(name="Old", igdb_id=1)
        new_root = Developer.objects.create(name="New", igdb_id=2)
        created = Developer.objects.create(name="Studio", igdb_id=3, parent=old_root)
        key = f"{config.CACHE_VERSION}:developer_detail:{old_root.id}"

        for studio in (created, Developer.objects.get(pk=created.pk)):
            with self.subTest(studio=studio):
                cache.set(key, {"detail": "cached"})

                studio.parent = new_root
                studio.save()

                self.assertIsNone(cache.get(key))
                studio.parent = old_root
                studio.save()

    def test_a_new_row_given_its_own_pk_still_drops(self):
        from games.services.developer_service import DEVELOPER_HIERARCHY_CACHE_KEY

        cache.set(DEVELOPER_HIERARCHY_CACHE_KEY, {"test": "data"})

        Developer(pk=987, name="Given", igdb_id=1).save()

        self.assertIsNone(cache.get(DEVELOPER_HIERARCHY_CACHE_KEY))

    def test_a_save_that_changes_nothing_drops_nothing(self):
        """The IGDB refresh saves every developer on every game."""
        from games.services.developer_service import DEVELOPER_HIERARCHY_CACHE_KEY

        studio = Developer.objects.create(name="Studio", igdb_id=1)
        cache.set(DEVELOPER_HIERARCHY_CACHE_KEY, {"test": "data"})

        Developer.objects.get(pk=studio.pk).save()

        self.assertIsNotNone(cache.get(DEVELOPER_HIERARCHY_CACHE_KEY))

    def test_a_save_that_did_not_reach_the_row_does_not_hide_a_later_move(self):
        """The old parent is read from the row, not remembered on the instance."""
        old_root = Developer.objects.create(name="Old", igdb_id=1)
        new_root = Developer.objects.create(name="New", igdb_id=2)
        studio = Developer.objects.create(name="Studio", igdb_id=3, parent=old_root)
        key = f"{config.CACHE_VERSION}:developer_detail:{old_root.id}"

        studio.parent = new_root
        studio.save(update_fields=["name"])
        cache.set(key, {"detail": "cached"})
        studio.save()

        self.assertIsNone(cache.get(key))

    def test_a_studio_moving_parent_drops_the_new_root_after_a_cached_read(self):
        """`root_creator` is cached on the instance from before the move."""
        old_root = Developer.objects.create(name="Old", igdb_id=1)
        new_root = Developer.objects.create(name="New", igdb_id=2)
        studio = Developer.objects.create(name="Studio", igdb_id=3, parent=old_root)
        self.assertEqual(studio.root_developer, old_root)
        key = f"{config.CACHE_VERSION}:developer_detail:{new_root.id}"
        cache.set(key, {"detail": "cached"})

        studio.parent = new_root
        studio.save()

        self.assertIsNone(cache.get(key))

    def test_a_studio_detached_from_its_parent_forgets_its_root(self):
        root = Developer.objects.create(name="Root", igdb_id=1)
        studio = Developer.objects.create(name="Studio", igdb_id=2, parent=root)
        self.assertEqual(studio.root_developer, root)

        studio.parent = None
        studio.save()

        self.assertEqual(studio.root_developer, studio)

    def test_a_new_developer_makes_no_lookup_for_a_root_it_left(self):
        with self.assertNumQueries(1):
            Developer(name="New", igdb_id=2).save()

    def test_an_ordinary_save_leaves_the_root_alone_in_that_step(self):
        root = Developer.objects.create(name="Root", igdb_id=1)
        studio = Developer.objects.create(name="Studio", igdb_id=2, parent=root)

        studio.save()

        self.assertIsNone(studio._root_left_id)

    def test_handles_deleted_parent_during_subsidiary_delete(self):
        """Test graceful handling when parent is already deleted."""
        parent = Developer.objects.create(name="Parent", igdb_id=1, slug="parent")
        child = Developer.objects.create(name="Child", igdb_id=2, parent=parent)

        # Delete parent first (child still references it)
        parent.delete()

        # Deleting child should not raise exception
        # (the signal handler should catch DoesNotExist)
        child.delete()  # Should not raise


class GameDeveloperM2MSignalTests(CommitHooksRunNowMixin, TestCase):
    """Tests for Game.developers M2M change signals."""

    def setUp(self):
        """Clear cache before each test."""
        clear_all_caches()

    def tearDown(self):
        """Clear cache after each test."""
        clear_all_caches()

    def test_adding_developer_to_game_invalidates_cache(self):
        """Test that adding a developer to a game invalidates cache."""
        from games.services.developer_service import DEVELOPER_HIERARCHY_CACHE_KEY

        dev = Developer.objects.create(name="Dev", igdb_id=1)
        game = Game.objects.create(name="Test Game", rank=1, igdb_id=100)

        # Pre-populate cache
        cache.set(DEVELOPER_HIERARCHY_CACHE_KEY, {"test": "data"})

        # Add developer to game (triggers m2m_changed signal)
        game.developers.add(dev)

        # Cache should be invalidated
        self.assertIsNone(cache.get(DEVELOPER_HIERARCHY_CACHE_KEY))

    def test_removing_developer_from_game_invalidates_cache(self):
        """Test that removing a developer from a game invalidates cache."""
        from games.services.developer_service import DEVELOPER_HIERARCHY_CACHE_KEY

        dev = Developer.objects.create(name="Dev", igdb_id=1)
        game = Game.objects.create(name="Test Game", rank=1, igdb_id=100)
        game.developers.add(dev)

        # Pre-populate cache
        cache.set(DEVELOPER_HIERARCHY_CACHE_KEY, {"test": "data"})

        # Remove developer from game
        game.developers.remove(dev)

        # Cache should be invalidated
        self.assertIsNone(cache.get(DEVELOPER_HIERARCHY_CACHE_KEY))

    def test_developer_detail_cache_invalidated_on_m2m_change(self):
        """Test that developer detail cache is invalidated on M2M change."""
        dev = Developer.objects.create(name="Dev", igdb_id=1)
        game = Game.objects.create(name="Test Game", rank=1, igdb_id=100)

        # Pre-populate detail cache
        cache_key = f"{config.CACHE_VERSION}:developer_detail:{dev.id}"
        cache.set(cache_key, {"detail": "cached"})

        # Add developer to game
        game.developers.add(dev)

        # Detail cache should be invalidated
        self.assertIsNone(cache.get(cache_key))

    def test_root_developer_cache_invalidated_on_subsidiary_m2m_change(self):
        """Test root developer cache invalidation on subsidiary M2M changes."""
        parent = Developer.objects.create(name="Parent", igdb_id=1, slug="parent")
        child = Developer.objects.create(name="Child", igdb_id=2, parent=parent)
        game = Game.objects.create(name="Test Game", rank=1, igdb_id=100)

        # Pre-populate root's detail cache
        parent_cache_key = f"{config.CACHE_VERSION}:developer_detail:{parent.id}"
        cache.set(parent_cache_key, {"detail": "cached"})

        # Add subsidiary to game
        game.developers.add(child)

        # Parent's detail cache should be invalidated
        self.assertIsNone(cache.get(parent_cache_key))

    def test_handles_deleted_developer_during_m2m_change(self):
        """Test graceful handling when developer is deleted during M2M operation."""
        dev = Developer.objects.create(name="Dev", igdb_id=1)
        game = Game.objects.create(name="Test Game", rank=1, igdb_id=100)
        game.developers.add(dev)

        # Delete developer
        dev.delete()

        # Clear the game's developers (referencing deleted dev shouldn't crash)
        game.developers.clear()  # Should not raise

    def test_m2m_signal_handles_nonexistent_developer_in_pk_set(self):
        """Test that M2M signal handles developer IDs that don't exist in DB."""
        from games.signals import invalidate_developer_cache_on_game_change

        game = Game.objects.create(name="Test Game", rank=1, igdb_id=100)

        # Manually trigger the signal with a pk_set containing a nonexistent ID
        # This simulates the scenario where a developer is deleted but its ID
        # is still in the pk_set during M2M change processing
        invalidate_developer_cache_on_game_change(
            sender=Game.developers.through,
            instance=game,
            pk_set={99999},  # Nonexistent developer ID
            action="post_add",
        )
        # Should not raise - the except Developer.DoesNotExist should handle it


class GameDeleteSignalTests(CommitHooksRunNowMixin, TestCase):
    def test_deleting_a_game_drops_its_developers_pages_and_their_root(self):
        """The through rows cascade without an `m2m_changed`."""
        from games.services.developer_service import DEVELOPER_HIERARCHY_CACHE_KEY

        root = Developer.objects.create(name="Root", igdb_id=1)
        studio = Developer.objects.create(name="Studio", igdb_id=2, parent=root)
        game = Game.objects.create(name="G", rank=1, igdb_id=100)
        game.developers.add(studio)
        keys = [
            DEVELOPER_HIERARCHY_CACHE_KEY,
            f"{config.CACHE_VERSION}:developer_detail:{studio.id}",
            f"{config.CACHE_VERSION}:developer_detail:{root.id}",
        ]
        cache.set_many({key: {"test": "data"} for key in keys})

        game.delete()

        self.assertEqual(cache.get_many(keys), {})


class GenreHierarchyChangesApplyImmediatelyTests(TestCase):
    """A re-parented genre filters by its new tree on the very next request.

    Descendant ids used to be cached per genre for 24 hours, and the filter's
    key (`genre_descendants:<id>`) was not one the invalidation signal
    deleted (`...:<id>:True` / `:False`). So moving a genre in the admin left
    genre filtering expanding the old tree, in every worker, for up to a day.
    The hierarchy is now read uncached, so there is nothing to go stale.
    """

    def setUp(self):
        clear_all_caches()

    def tearDown(self):
        clear_all_caches()

    def test_reparented_genre_moves_between_filters(self):
        from games.utils import apply_genre_filter

        strategy = WikipediaGenre.objects.create(name="Strategy Root")
        sports = WikipediaGenre.objects.create(name="Sports Root")
        racing = WikipediaGenre.objects.create(name="Racing Leaf", parent=strategy)
        game = Game.objects.create(name="Lap Game", rank=1)
        game.wikipedia_genres.add(racing)

        def matching(root):
            return set(
                apply_genre_filter(Game.objects.all(), [root.id], match_all=False)
            )

        # Warm whatever a filter might cache, then move the leaf.
        self.assertEqual(matching(strategy), {game})
        self.assertEqual(matching(sports), set())
        self.assertEqual(strategy.get_descendant_ids(), [racing.id])

        racing.parent = sports
        racing.save()

        self.assertEqual(matching(strategy), set())
        self.assertEqual(matching(sports), {game})
        self.assertEqual(strategy.get_descendant_ids(), [])
        self.assertEqual(
            sports.get_descendant_ids(include_self=True), [sports.id, racing.id]
        )

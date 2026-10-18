"""`core.services.genre_tree` - the one-query descendant map."""

from django.test import TestCase

from core.services.genre_tree import descendants_by_id, fetch_descendants_by_id
from music import models as music_models


class DescendantsByIdTests(TestCase):
    """The pure walk. No database."""

    def test_no_rows_is_an_empty_map(self):
        self.assertEqual(descendants_by_id([]), {})

    def test_a_lone_root_has_no_descendants(self):
        self.assertEqual(descendants_by_id([(1, None)]), {1: []})

    def test_a_root_collects_its_children_in_arrival_order(self):
        # Not sorted: the caller's ordering is the contract, because it is
        # what reproduces `self.children.all()` under Meta.ordering.
        self.assertEqual(
            descendants_by_id([(1, None), (9, 1), (4, 1), (7, 1)]),
            {1: [9, 4, 7], 9: [], 4: [], 7: []},
        )

    def test_a_grandchild_follows_its_parent_depth_first(self):
        # This ordering is what the `/api/music/all/` "d" key sends, so it
        # is pinned rather than incidental.
        self.assertEqual(
            descendants_by_id([(1, None), (2, 1), (3, 2)]),
            {1: [2, 3], 2: [3], 3: []},
        )

    def test_deeper_nesting_stays_depth_first_across_branches(self):
        self.assertEqual(
            descendants_by_id([(1, None), (2, 1), (3, 2), (4, 1), (5, 4)]),
            {1: [2, 3, 4, 5], 2: [3], 3: [], 4: [5], 5: []},
        )

    def test_the_map_iterates_in_arrival_order(self):
        # Callers walk this to count genres or render a tree, so the order
        # has to be the order the rows came in and not the post-order the
        # walk resolves them in.
        pairs = [(1, None), (2, 1), (3, None), (4, 3)]
        self.assertEqual(list(descendants_by_id(pairs)), [1, 2, 3, 4])

    def test_a_node_whose_parent_is_absent_still_gets_an_entry(self):
        # A genre filtered out of the fetch, or a dangling parent_id: the
        # node itself is still a key, and its missing parent is not.
        self.assertEqual(descendants_by_id([(5, 99)]), {5: []})

    def test_a_child_listed_before_its_parent_is_resolved_once(self):
        self.assertEqual(descendants_by_id([(2, 1), (1, None)]), {2: [], 1: [2]})

    def test_a_parent_cycle_terminates_instead_of_hanging(self):
        # Bad data the recursive version raised RecursionError on. Spinning
        # a web worker forever is strictly worse, so the walk guards and
        # returns whatever it reached.
        self.assertEqual(descendants_by_id([(1, 2), (2, 1)]), {1: [2, 1], 2: [1]})

    def test_a_self_parented_node_terminates(self):
        self.assertEqual(descendants_by_id([(1, 1)]), {1: [1]})


class FetchDescendantsByIdTests(TestCase):
    """The database half: one query for the whole table."""

    def setUp(self):
        self.rock = music_models.MusicGenre.objects.create(name="Rock")
        self.punk = music_models.MusicGenre.objects.create(
            name="Punk Rock", parent=self.rock
        )
        self.post = music_models.MusicGenre.objects.create(
            name="Post-Punk", parent=self.punk
        )
        self.jazz = music_models.MusicGenre.objects.create(name="Jazz")

    def test_one_query_maps_the_whole_table(self):
        with self.assertNumQueries(1):
            descendants = fetch_descendants_by_id(music_models.MusicGenre.objects.all())
        self.assertEqual(
            descendants,
            {
                self.rock.id: [self.punk.id, self.post.id],
                self.jazz.id: [],
                self.punk.id: [self.post.id],
                self.post.id: [],
            },
        )

    def test_it_agrees_with_the_per_instance_walk_it_replaces(self):
        # `MusicGenre.get_descendant_ids` is the contract this has to match;
        # it stays on the model for one-off use.
        descendants = fetch_descendants_by_id(music_models.MusicGenre.objects.all())
        for genre in music_models.MusicGenre.objects.all():
            with self.subTest(genre=genre.name):
                self.assertEqual(
                    descendants[genre.id], genre.get_descendant_ids(include_self=False)
                )

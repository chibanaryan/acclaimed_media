"""Tests for the artist roll-up, ``music.services.artist_graph``.

Built from plain tuples rather than rows wherever possible: the graph is an
in-memory walk, and the cases worth pinning are its shapes - several
parents, a chain, a cycle - not the ORM.
"""

from django.test import SimpleTestCase, TestCase

from music import models
from music.services.artist_graph import (
    ArtistGraph,
    artist_summary,
    credit_separator,
    credit_text,
)

# Ids borrowed from ArtistInfo.txt, so the shapes read as the real ones.
PRINCE, PRINCE_REV = 8, 9
CSN, NEIL, CSNY = 113, 56, 2145
HORSE, NEIL_HORSE = 192, 2153
SNAITH, CARIBOU, MANITOBA = 1, 2, 3

RELATIONS = [
    (PRINCE_REV, PRINCE, "P"),
    (CSNY, CSN, "P"),
    (CSNY, NEIL, "C"),
    (NEIL_HORSE, NEIL, "P"),
    (NEIL_HORSE, HORSE, "F"),
    (CARIBOU, SNAITH, "A"),
    (MANITOBA, CARIBOU, "A"),
]

# (album, artist): Purple Rain 10, Sign o' the Times 11, Deja Vu 20,
# Harvest 30, Rust Never Sleeps 31, Up in Flames 40.
CREDITS = [
    (10, PRINCE_REV),
    (11, PRINCE),
    (20, CSNY),
    (30, NEIL),
    (31, NEIL_HORSE),
    (40, MANITOBA),
]


class CreditTextTests(SimpleTestCase):
    def test_the_house_style(self):
        self.assertEqual(credit_text(["A"]), "A")
        self.assertEqual(credit_text(["A", "B"]), "A & B")
        self.assertEqual(credit_text(["A", "B", "C"]), "A, B & C")

    def test_no_names_is_various_artists(self):
        self.assertEqual(credit_text([]), "Various Artists")

    def test_separators(self):
        self.assertEqual(
            [credit_separator(i, 4) for i in range(4)], ["", ", ", ", ", " & "]
        )


class ArtistSummaryTests(SimpleTestCase):
    def test_an_owner_counts_its_albums(self):
        self.assertEqual(artist_summary(1), "1 album")
        self.assertEqual(artist_summary(5, 2), "5 albums")
        self.assertEqual(artist_summary(0), "0 albums")

    def test_an_act_that_only_appears_says_so(self):
        self.assertEqual(artist_summary(0, 1), "appears on 1 album")
        self.assertEqual(artist_summary(0, 3), "appears on 3 albums")


class ArtistGraphTests(SimpleTestCase):
    def setUp(self):
        self.graph = ArtistGraph(RELATIONS, CREDITS)

    def test_a_project_rolls_up_into_its_owner(self):
        self.assertEqual(self.graph.album_ids(PRINCE), {10, 11})
        self.assertEqual(self.graph.album_ids(PRINCE_REV), {10})

    def test_a_collaboration_belongs_to_every_party(self):
        self.assertIn(20, self.graph.album_ids(CSN))
        self.assertIn(20, self.graph.album_ids(NEIL))

    def test_aliases_roll_up_transitively(self):
        self.assertEqual(self.graph.derived_ids(SNAITH), [CARIBOU, MANITOBA])
        self.assertEqual(self.graph.album_ids(SNAITH), {40})

    def test_a_featured_act_owns_nothing_but_appears(self):
        self.assertEqual(self.graph.album_ids(HORSE), set())
        self.assertEqual(self.graph.appears_on_ids(HORSE), {31})
        self.assertEqual(self.graph.appears_on_ids(NEIL), set())

    def test_expand_adds_what_rolls_up(self):
        self.assertEqual(self.graph.expand([NEIL]), {NEIL, CSNY, NEIL_HORSE})
        self.assertEqual(self.graph.expand([HORSE]), {HORSE})

    def test_roots_walk_to_the_top_once_each(self):
        self.assertEqual(self.graph.roots([PRINCE_REV]), [PRINCE])
        self.assertEqual(self.graph.roots([CSNY]), [CSN, NEIL])
        self.assertEqual(self.graph.roots([MANITOBA]), [SNAITH])
        # Neil reached twice - directly and through his project - is listed once.
        self.assertEqual(self.graph.roots([NEIL, NEIL_HORSE]), [NEIL])

    def test_album_ids_by_artist_lists_only_owners(self):
        owners = self.graph.album_ids_by_artist()
        self.assertEqual(owners[NEIL], {20, 30, 31})
        self.assertNotIn(HORSE, owners)

    def test_appears_on_by_artist_lists_only_appearing_acts(self):
        self.assertEqual(self.graph.appears_on_by_artist(), {HORSE: {31}})

    def test_an_act_featured_on_its_own_project_is_not_listed(self):
        # Featured on a project of its own: nothing left once its own albums
        # are taken out, so it does not count as appearing anywhere.
        graph = ArtistGraph([(9, 8, "P"), (9, 8, "F")], [(10, 9)])
        self.assertEqual(graph.appears_on_by_artist(), {})

    def test_derived_map_holds_only_artists_with_derived_acts(self):
        self.assertEqual(
            set(self.graph.derived_map()), {PRINCE, CSN, NEIL, SNAITH, CARIBOU}
        )

    def test_a_cycle_does_not_hang(self):
        graph = ArtistGraph([(1, 2, "A"), (2, 1, "A")], [(5, 1)])
        self.assertEqual(graph.album_ids(2), {5})
        self.assertEqual(graph.roots([1]), [])

    def test_album_questions_need_the_credits(self):
        graph = ArtistGraph(RELATIONS)
        self.assertEqual(graph.expand([PRINCE]), {PRINCE, PRINCE_REV})
        with self.assertRaises(ValueError):
            graph.album_ids(PRINCE)


class ArtistGraphLoadTests(TestCase):
    def test_load_reads_the_relation_and_credit_tables(self):
        prince = models.Artist.objects.create(name="Prince", slug="prince")
        act = models.Artist.objects.create(name="Prince and the Revolution", slug="ptr")
        models.ArtistRelation.objects.create(artist=act, related=prince, kind="P")
        album = models.Album.objects.create(name="Purple Rain", rank=1)
        album.artists.set([act])

        with self.assertNumQueries(2):
            graph = ArtistGraph.load()
            self.assertEqual(graph.album_ids(prince.id), {album.id})

        with self.assertNumQueries(1):
            ArtistGraph.load(with_credits=False).expand([prince.id])

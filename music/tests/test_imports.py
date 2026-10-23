"""Tests for the music import handler.

The importers are driven with StringIO rather than files, matching
``games/tests/test_imports.py``. The real release files in
``acclaimedgames/test_input_files/music/`` back the end-to-end test.
"""

from contextlib import ExitStack
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from core import constants as core_constants
from core.models import User
from music import config, models
from music.services import import_handler
from music.services.artist_graph import ArtistGraph
from django.core.cache import cache
from django.urls import reverse
from games.models import SiteMetadata
from music.tests.test_views import StaffUserTestMixin

FIXTURE_DIR = Path(settings.BASE_DIR) / "acclaimedgames" / "test_input_files" / "music"

LISTS_TSV = (
    "Rolling Stone\t2023\tThe 500 Greatest Albums of All Time\thttps://rs.example\n"
    "Pitchfork\t2022\tThe 150 Best Albums of the 1990s\thttps://pf.example\n"
    "Spin\t2010\t125 Best Albums of the Past 25 Years\t\n"
)

# Shaped like the real ArtistInfo.txt: sparse provider ids, a blank tags
# column for a plain act, and a joint act tagged with what makes it up.
ARTISTS_TSV = (
    "3\tThe Beach Boys\t\tQ183048\n"
    "56\tNeil Young\t\tQ633\n"
    "113\tCrosby, Stills & Nash\t\tQ214567\n"
    "192\tCrazy Horse\t\t\n"
    "2145\tCrosby, Stills, Nash & Young\tP:113,C:56\tQ10461933\n"
    "2153\tNeil Young & Crazy Horse\tP:56,F:192\t\n"
)

ALBUMS_TSV = (
    "1\tPet Sounds\t3\t1966\tQ212863\n"
    "2\tDéjà Vu\t2145\t1970\tQ1136782\n"
    "3\tRust Never Sleeps\t2153\t1979\tQ1140313,Q999999\n"
)

POSITIONS_TSV = "0:2\t1:5\n0:1\t2:9\n0:3\n"


def import_artists(tsv=ARTISTS_TSV):
    return import_handler.import_artists(StringIO(tsv))


def import_release(**overrides):
    """``import_batch`` over the inline fixtures, any of them replaced."""
    files = {
        "lists_file": LISTS_TSV,
        "albums_file": ALBUMS_TSV,
        "positions_file": POSITIONS_TSV,
        "artists_file": ARTISTS_TSV,
    }
    files.update(overrides)
    return import_handler.import_batch(
        **{name: StringIO(text) for name, text in files.items()}
    )


class InferListTypeTests(TestCase):
    """The lists file has no type column, so the title has to carry it."""

    def test_all_time_wording(self):
        for title in [
            "The 500 Greatest Albums of All Time",
            "The All-TIME 100 Albums",
            "100 Greatest Albums Ever",
            "The 100 Greatest Albums Ever Made",
            "1001 Albums You Must Hear Before You Die (2021)",
        ]:
            with self.subTest(title=title):
                self.assertEqual(
                    import_handler.infer_list_type(title),
                    core_constants.LIST_ALLTIME,
                )

    def test_decade_wording(self):
        for title in [
            "The 150 Best Albums of the 1990s",
            "100 Best Albums of the ’90s",
            "100 Best Albums of the Eighties",
            "The Best Albums of The Decade: The 2010s",
            "Die 100 besten Alben der 10-er Jahre",
            "100 meilleurs albums des années 2000",
        ]:
            with self.subTest(title=title):
                self.assertEqual(
                    import_handler.infer_list_type(title),
                    core_constants.LIST_DECADE,
                )

    def test_era_wording_is_miscellaneous(self):
        for title in [
            "The 300 Best Albums of the Past 30 Years",
            "Top 100 Albums of the Last 20 Years",
            "The 250 Greatest Albums of the 21st Century So Far",
            "The 100 Greatest Albums of Our Lifetime",
            "The 100 Best Albums 1969 - 2009",
            "The Best Albums 2000-2015",
            "Les 100 albums des années 1986 - 1996",
        ]:
            with self.subTest(title=title):
                self.assertEqual(
                    import_handler.infer_list_type(title),
                    core_constants.LIST_MISC,
                )

    def test_an_unqualified_title_falls_back_to_all_time(self):
        # Every list in this corpus is retrospective, so a ranking with no
        # period in its name is making an all-time claim.
        for title in ["Top 100 Albums", "Apple Music 100 Best Albums"]:
            with self.subTest(title=title):
                self.assertEqual(
                    import_handler.infer_list_type(title),
                    core_constants.LIST_ALLTIME,
                )

    def test_empty_and_none_titles_do_not_raise(self):
        self.assertEqual(
            import_handler.infer_list_type(""), core_constants.LIST_ALLTIME
        )
        self.assertEqual(
            import_handler.infer_list_type(None), core_constants.LIST_ALLTIME
        )

    def test_decade_wording_wins_over_all_time_wording(self):
        # "of the 1990s" must not be swallowed by a looser all-time match.
        self.assertEqual(
            import_handler.infer_list_type(
                "The Greatest Albums of All Time: the 1990s"
            ),
            core_constants.LIST_DECADE,
        )

    def test_every_real_list_title_classifies_without_falling_through(self):
        rows = _read_fixture_rows("ListData.txt")
        self.assertGreater(len(rows), 0)
        types = {import_handler.infer_list_type(row[2]) for row in rows}
        # Every supplied title lands on a known type, and none of them is an
        # end-of-year list.
        self.assertTrue(types)
        self.assertNotIn(core_constants.LIST_EOY, types)
        self.assertEqual(types - set(dict(core_constants.LIST_TYPES)), set())


class NormalizeArtistNameTests(TestCase):
    def test_ampersand_and_the_are_collapsed(self):
        self.assertEqual(
            import_handler.normalize_artist_name("Bob Marley & The Wailers"),
            import_handler.normalize_artist_name("Bob Marley and the Wailers"),
        )

    def test_different_acts_do_not_collapse(self):
        self.assertNotEqual(
            import_handler.normalize_artist_name("Jimi Hendrix"),
            import_handler.normalize_artist_name("The Jimi Hendrix Experience"),
        )


class ImportArtistsTests(TestCase):
    def test_creates_every_artist_under_its_provider_id(self):
        success, message = import_artists()
        self.assertTrue(success)
        self.assertIn("Artists: 6 (6 new, 0 removed), 4 relations", message)
        young = models.Artist.objects.get(source_id=56)
        self.assertEqual(young.name, "Neil Young")
        self.assertEqual(young.slug, "neil-young")
        self.assertEqual(young.wikidata_id, "Q633")
        self.assertIsNone(models.Artist.objects.get(source_id=192).wikidata_id)

    def test_tags_become_relations_in_file_order(self):
        import_artists()
        act = models.Artist.objects.get(source_id=2153)
        self.assertEqual(
            [(r.kind, r.related.name, r.position) for r in act.relations.all()],
            [("P", "Neil Young", 0), ("F", "Crazy Horse", 1)],
        )

    def test_a_reimport_keeps_every_pk_and_slug(self):
        import_artists()
        before = dict(models.Artist.objects.values_list("source_id", "pk"))
        success, message = import_artists()
        self.assertIn("(0 new, 0 removed)", message)
        self.assertEqual(
            dict(models.Artist.objects.values_list("source_id", "pk")), before
        )

    def test_a_renamed_artist_keeps_its_slug(self):
        import_artists()
        import_artists(ARTISTS_TSV.replace("Crazy Horse\t", "Crazy Horse (band)\t"))
        horse = models.Artist.objects.get(source_id=192)
        self.assertEqual(horse.name, "Crazy Horse (band)")
        self.assertEqual(horse.slug, "crazy-horse")

    def test_a_changed_qid_drops_the_old_musicbrainz_id(self):
        import_artists()
        models.Artist.objects.filter(source_id__in=[56, 3]).update(musicbrainz_id="mb")
        import_artists(ARTISTS_TSV.replace("Q633", "Q634"))
        self.assertIsNone(models.Artist.objects.get(source_id=56).musicbrainz_id)
        self.assertEqual(models.Artist.objects.get(source_id=3).musicbrainz_id, "mb")

    def test_relations_are_rebuilt_from_the_file(self):
        import_artists()
        import_artists(ARTISTS_TSV.replace("P:56,F:192", "P:56"))
        act = models.Artist.objects.get(source_id=2153)
        self.assertEqual([r.kind for r in act.relations.all()], ["P"])

    def test_a_repeated_tag_is_stored_once(self):
        import_artists(ARTISTS_TSV.replace("P:56,F:192", "P:56,P:56"))
        self.assertEqual(models.Artist.objects.get(source_id=2153).relations.count(), 1)

    def test_kinds_and_whitespace_are_forgiven(self):
        import_artists(ARTISTS_TSV.replace("P:56,F:192", " p : 56 , f:192 "))
        act = models.Artist.objects.get(source_id=2153)
        self.assertEqual([r.kind for r in act.relations.all()], ["P", "F"])

    def test_an_existing_artist_is_adopted_by_qid(self):
        # Rows from the credit-guessing imports carry no source id; matching
        # them keeps their pk, so links and filters keep working.
        old = models.Artist.objects.create(
            name="Neil Young (old spelling)", slug="neil-young", wikidata_id="Q633"
        )
        import_artists()
        adopted = models.Artist.objects.get(source_id=56)
        self.assertEqual(adopted.pk, old.pk)
        self.assertEqual(adopted.name, "Neil Young")
        self.assertEqual(adopted.slug, "neil-young")

    def test_an_existing_artist_is_adopted_by_name(self):
        old = models.Artist.objects.create(name="Crazy Horse", slug="horse")
        import_artists()
        self.assertEqual(models.Artist.objects.get(source_id=192).pk, old.pk)

    def test_an_existing_artist_is_adopted_by_a_normalized_name(self):
        old = models.Artist.objects.create(
            name="Neil Young and Crazy Horse", slug="nyach"
        )
        import_artists()
        self.assertEqual(models.Artist.objects.get(source_id=2153).pk, old.pk)

    def test_an_adopted_artist_without_a_slug_gets_one(self):
        models.Artist.objects.create(name="Crazy Horse", slug="")
        import_artists()
        self.assertEqual(models.Artist.objects.get(source_id=192).slug, "crazy-horse")

    def test_artists_the_file_does_not_list_are_removed(self):
        models.Artist.objects.create(name="Guessed From A Credit", slug="guessed")
        import_artists()
        _, message = import_artists(
            ARTISTS_TSV.replace("192\tCrazy Horse\t\t\n", "").replace(",F:192", "")
        )
        self.assertIn("1 removed", message)
        self.assertFalse(
            models.Artist.objects.filter(name="Guessed From A Credit").exists()
        )
        self.assertFalse(models.Artist.objects.filter(source_id=192).exists())

    def test_a_colliding_slug_gets_a_numeric_tail(self):
        models.Artist.objects.create(name="Nico (singer)", slug="nico", source_id=1)
        import_artists(ARTISTS_TSV + "22\tNico\t\t\n")
        self.assertEqual(models.Artist.objects.get(source_id=22).slug, "nico-2")

    def test_progress_callback_receives_each_stage(self):
        events = []
        import_handler.import_artists(
            StringIO(ARTISTS_TSV), lambda name, data: events.append((name, data))
        )
        names = [name for name, _ in events]
        self.assertEqual(names[0], "start")
        self.assertEqual(names[-1], "complete")
        self.assertEqual(names.count("progress"), 6)
        self.assertEqual(dict(events)["complete"]["relations"], 4)

    def test_a_bad_file_is_rejected_before_anything_is_written(self):
        for tsv, expected in (
            ("1\n", "expected at least 2"),
            ("x\tNobody\n", "is not a number"),
            ("1\tA\n1\tB\n", "appears twice"),
            ("1\t \n", "has no name"),
            ("1\tA\tQ:2\n2\tB\n", "is not KIND:id"),
            ("1\tA\tP:two\n", "is not KIND:id"),
            ("1\tA\tP:1\n", "related to itself"),
            ("1\tA\tP:9\n", "no artist with that id"),
        ):
            with self.subTest(tsv=tsv):
                with self.assertRaises(ValueError) as ctx:
                    import_artists(tsv)
                self.assertIn(expected, str(ctx.exception))
                self.assertFalse(models.Artist.objects.exists())


class ImportListsTests(TestCase):
    def test_creates_publications_and_lists_with_inferred_types(self):
        success, message = import_handler.import_lists(StringIO(LISTS_TSV))
        self.assertTrue(success)
        self.assertIn("Lists: 3 created", message)
        self.assertEqual(models.MusicList.objects.count(), 3)
        self.assertEqual(models.MusicPublication.objects.count(), 3)

        first = models.MusicList.objects.get(order=1)
        self.assertEqual(first.type, core_constants.LIST_ALLTIME)
        self.assertEqual(first.publisher.name, "Rolling Stone")
        self.assertEqual(first.url, "https://rs.example")

        second = models.MusicList.objects.get(order=2)
        self.assertEqual(second.type, core_constants.LIST_DECADE)

        third = models.MusicList.objects.get(order=3)
        self.assertEqual(third.type, core_constants.LIST_MISC)

    def test_order_is_the_one_based_row_number(self):
        import_handler.import_lists(StringIO(LISTS_TSV))
        self.assertEqual(
            list(
                models.MusicList.objects.order_by("order").values_list(
                    "order", flat=True
                )
            ),
            [1, 2, 3],
        )

    def test_a_blank_url_is_stored_as_null(self):
        import_handler.import_lists(StringIO(LISTS_TSV))
        self.assertIsNone(models.MusicList.objects.get(order=3).url)

    def test_a_missing_url_column_is_tolerated(self):
        import_handler.import_lists(StringIO("Mojo\t1995\tThe 100 Greatest Albums\n"))
        self.assertIsNone(models.MusicList.objects.get(order=1).url)

    def test_reimporting_replaces_the_previous_lists(self):
        import_handler.import_lists(StringIO(LISTS_TSV))
        success, message = import_handler.import_lists(StringIO(LISTS_TSV))
        self.assertTrue(success)
        self.assertIn("deleted 3 old", message)
        self.assertEqual(models.MusicList.objects.count(), 3)

    def test_one_publication_is_reused_across_its_lists(self):
        tsv = (
            "Pitchfork\t2022\tThe 150 Best Albums of the 1990s\t\n"
            "Pitchfork\t2019\tThe 200 Best Albums of the 2010s\t\n"
        )
        import_handler.import_lists(StringIO(tsv))
        self.assertEqual(models.MusicPublication.objects.count(), 1)
        self.assertEqual(models.MusicList.objects.count(), 2)

    def test_blank_rows_are_skipped(self):
        import_handler.import_lists(StringIO(LISTS_TSV + "\n\n"))
        self.assertEqual(models.MusicList.objects.count(), 3)

    def test_a_short_row_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            import_handler.import_lists(StringIO("Mojo\t1995\n"))
        self.assertIn("expected at least 3", str(ctx.exception))

    def test_progress_callback_receives_each_stage(self):
        events = []
        import_handler.import_lists(
            StringIO(LISTS_TSV), lambda name, data: events.append((name, data))
        )
        names = [name for name, _ in events]
        self.assertEqual(names[0], "start")
        self.assertEqual(names[-1], "complete")
        self.assertEqual(names.count("progress"), 3)
        self.assertEqual(len(dict(events)["complete"]["inferred"]), 3)


class ImportAlbumsTests(TestCase):
    def setUp(self):
        import_artists()

    def test_creates_albums_artists_and_derived_ranks(self):
        success, message = import_handler.import_albums(StringIO(ALBUMS_TSV))
        self.assertTrue(success)
        self.assertIn("Albums: 3 created", message)
        self.assertIn("3 ranks calculated", message)
        self.assertEqual(models.Album.objects.count(), 3)

        album = models.Album.objects.get(rank=1)
        self.assertEqual(album.name, "Pet Sounds")
        self.assertEqual(album.artist_credit, "The Beach Boys")
        self.assertEqual([a.source_id for a in album.credited_artists], [3])
        self.assertEqual(album.year_released, 1966)
        self.assertEqual(album.wikidata_id, "Q212863")
        self.assertEqual(album.all_wikidata_ids, ["Q212863"])
        self.assertEqual(album.year_rank, 1)
        self.assertEqual(album.decade_rank, 1)

    def test_an_album_is_credited_to_the_joint_act_itself(self):
        import_handler.import_albums(StringIO(ALBUMS_TSV))
        album = models.Album.objects.get(rank=2)
        self.assertEqual(
            [a.name for a in album.credited_artists], ["Crosby, Stills, Nash & Young"]
        )
        self.assertEqual(album.artist_credit, "Crosby, Stills, Nash & Young")

    def test_several_artists_keep_the_files_order_in_the_credit(self):
        import_handler.import_albums(StringIO("1\tTogether\t192,56,3\t1990\n"))
        album = models.Album.objects.get(rank=1)
        self.assertEqual(
            [a.name for a in album.credited_artists],
            ["Crazy Horse", "Neil Young", "The Beach Boys"],
        )
        self.assertEqual(
            album.artist_credit, "Crazy Horse, Neil Young & The Beach Boys"
        )

    def test_two_artists_are_joined_with_an_ampersand(self):
        import_handler.import_albums(StringIO("1\tTogether\t56, 192\t1990\n"))
        self.assertEqual(
            models.Album.objects.get(rank=1).artist_credit, "Neil Young & Crazy Horse"
        )

    def test_a_repeated_id_is_credited_once(self):
        import_handler.import_albums(StringIO("1\tTwice\t56,56\t1990\n"))
        self.assertEqual(models.AlbumCredit.objects.count(), 1)

    def test_a_blank_credit_is_various_artists(self):
        import_handler.import_albums(StringIO("1\tNuggets\t\t1972\tQ744572\n"))
        album = models.Album.objects.get(rank=1)
        self.assertEqual(album.artist_credit, "Various Artists")
        self.assertEqual(album.credited_artists, [])

    def test_an_old_format_credit_is_rejected_by_name(self):
        with self.assertRaises(ValueError) as ctx:
            import_handler.import_albums(
                StringIO("1\tPet Sounds\tThe Beach Boys\t1966\tQ212863\n")
            )
        self.assertIn("column 3 should be artist ids", str(ctx.exception))

    def test_an_unknown_artist_id_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            import_handler.import_albums(StringIO("1\tPet Sounds\t999\t1966\n"))
        self.assertIn("credits artist 999", str(ctx.exception))

    def test_the_first_wikidata_id_is_primary_and_the_rest_are_kept(self):
        import_handler.import_albums(StringIO(ALBUMS_TSV))
        album = models.Album.objects.get(rank=3)
        self.assertEqual(album.wikidata_id, "Q1140313")
        self.assertEqual(album.all_wikidata_ids, ["Q1140313", "Q999999"])

    def test_a_missing_wikidata_column_is_tolerated(self):
        import_handler.import_albums(StringIO("1\tUntitled\t3\t1999\n"))
        album = models.Album.objects.get(rank=1)
        self.assertIsNone(album.wikidata_id)
        self.assertEqual(album.all_wikidata_ids, [])

    def test_a_blank_year_is_stored_as_null(self):
        import_handler.import_albums(StringIO("1\tUndated\t3\t\tQ1\n"))
        self.assertIsNone(models.Album.objects.get(rank=1).year_released)

    def test_a_title_collision_is_disambiguated_by_the_credit(self):
        import_handler.import_albums(
            StringIO("1\tHarvest\t56\t1972\n2\tHarvest\t3\t1980\n")
        )
        self.assertEqual(
            models.Album.objects.get(rank=2).slug, "harvest-the-beach-boys"
        )

    def test_reimporting_replaces_the_previous_albums(self):
        import_handler.import_albums(StringIO(ALBUMS_TSV))
        success, message = import_handler.import_albums(StringIO(ALBUMS_TSV))
        self.assertTrue(success)
        self.assertIn("deleted 3 old", message)
        self.assertEqual(models.Album.objects.count(), 3)
        self.assertEqual(models.AlbumCredit.objects.count(), 3)

    def test_a_short_row_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            import_handler.import_albums(StringIO("1\tPet Sounds\n"))
        self.assertIn("expected at least 4", str(ctx.exception))

    def test_progress_callback_receives_each_stage(self):
        events = []
        import_handler.import_albums(
            StringIO(ALBUMS_TSV), lambda name, data: events.append((name, data))
        )
        names = [name for name, _ in events]
        self.assertEqual(names[0], "start")
        self.assertEqual(names[-1], "complete")
        self.assertEqual(dict(events)["complete"]["count"], 3)


class ImportListMembershipsTests(TestCase):
    def setUp(self):
        import_artists()
        import_handler.import_lists(StringIO(LISTS_TSV))
        import_handler.import_albums(StringIO(ALBUMS_TSV))

    def test_joins_positions_to_the_right_list_and_album(self):
        success, message = import_handler.import_listmemberships(
            StringIO(POSITIONS_TSV)
        )
        self.assertTrue(success)
        self.assertIn("5 created", message)

        first_list = models.MusicList.objects.get(order=1)
        pet_sounds = models.Album.objects.get(rank=1)
        membership = models.AlbumListMembership.objects.get(
            list=first_list, album=pet_sounds
        )
        # Row 1, cell "0:2": list index 0 is order 1, position 2.
        self.assertEqual(membership.rank, 2)

    def test_the_second_row_belongs_to_the_album_at_rank_two(self):
        import_handler.import_listmemberships(StringIO(POSITIONS_TSV))
        third_list = models.MusicList.objects.get(order=3)
        membership = models.AlbumListMembership.objects.get(list=third_list)
        self.assertEqual(membership.album.rank, 2)
        self.assertEqual(membership.rank, 9)

    def test_an_unknown_list_index_is_skipped(self):
        success, message = import_handler.import_listmemberships(
            StringIO("0:1\t99:1\n")
        )
        self.assertTrue(success)
        self.assertIn("1 created", message)

    def test_a_row_with_no_matching_album_is_rejected(self):
        models.Album.objects.filter(rank=3).delete()
        with self.assertRaises(ValueError) as ctx:
            import_handler.import_listmemberships(StringIO(POSITIONS_TSV))
        self.assertIn("no album at rank 3", str(ctx.exception))

    def test_reimporting_replaces_the_previous_memberships(self):
        import_handler.import_listmemberships(StringIO(POSITIONS_TSV))
        import_handler.import_listmemberships(StringIO(POSITIONS_TSV))
        self.assertEqual(models.AlbumListMembership.objects.count(), 5)

    def test_blank_cells_are_ignored(self):
        success, message = import_handler.import_listmemberships(
            StringIO("0:1\t\t1:2\n")
        )
        self.assertTrue(success)
        self.assertIn("2 created", message)

    def test_memberships_are_written_in_batches(self):
        with self.settings():
            original = import_handler.config.IMPORT_BATCH_SIZE
            import_handler.config.IMPORT_BATCH_SIZE = 1
            try:
                success, message = import_handler.import_listmemberships(
                    StringIO(POSITIONS_TSV)
                )
            finally:
                import_handler.config.IMPORT_BATCH_SIZE = original
        self.assertTrue(success)
        self.assertEqual(models.AlbumListMembership.objects.count(), 5)

    def test_progress_callback_receives_each_stage(self):
        events = []
        import_handler.import_listmemberships(
            StringIO(POSITIONS_TSV), lambda name, data: events.append((name, data))
        )
        names = [name for name, _ in events]
        self.assertEqual(names[0], "start")
        self.assertEqual(names[-1], "complete")
        self.assertEqual(dict(events)["complete"]["count"], 5)


class ImportBatchTests(TestCase):
    def test_runs_all_four_importers_in_order(self):
        success, message = import_release()
        self.assertTrue(success)
        self.assertTrue(message.startswith("Artists: 6"))
        self.assertIn("Lists: 3 created", message)
        self.assertIn("Albums: 3 created", message)
        self.assertIn("memberships: 5 created", message)
        self.assertEqual(models.Artist.objects.count(), 6)
        self.assertEqual(models.MusicList.objects.count(), 3)
        self.assertEqual(models.Album.objects.count(), 3)
        self.assertEqual(models.AlbumListMembership.objects.count(), 5)

    def test_an_empty_lists_file_stops_the_batch(self):
        with self.assertRaises(ValueError) as ctx:
            import_release(lists_file="\n")
        self.assertIn("No lists were imported", str(ctx.exception))

    def test_an_empty_albums_file_stops_the_batch(self):
        with self.assertRaises(ValueError) as ctx:
            import_release(albums_file="\n")
        self.assertIn("No albums were imported", str(ctx.exception))

    def test_albums_cannot_credit_artists_the_release_lacks(self):
        with self.assertRaises(ValueError) as ctx:
            import_release(artists_file="3\tThe Beach Boys\n")
        self.assertIn("not in the artists file", str(ctx.exception))

    def test_a_failure_rolls_the_whole_batch_back(self):
        # A positions file with more rows than albums fails mid-import; the
        # artists, lists and albums written before it must not survive.
        with self.assertRaises(ValueError):
            import_release(positions_file=POSITIONS_TSV + "0:1\n")
        self.assertEqual(models.Artist.objects.count(), 0)
        self.assertEqual(models.MusicList.objects.count(), 0)
        self.assertEqual(models.Album.objects.count(), 0)


class RealReleaseFilesTests(TestCase):
    """End-to-end over the files the rankings actually shipped with."""

    def test_the_supplied_release_imports_completely(self):
        success, _ = import_real_release()

        self.assertTrue(success)
        # Counted from the files, so a new release does not fail the suite
        # just for being bigger. What matters is that every row lands.
        album_rows = _read_fixture_rows("WebRankings.txt")
        list_rows = _read_fixture_rows("ListData.txt")
        self.assertEqual(models.Album.objects.count(), len(album_rows))
        self.assertEqual(models.MusicList.objects.count(), len(list_rows))
        self.assertEqual(
            models.MusicPublication.objects.count(),
            len({row[0] for row in list_rows}),
        )
        self.assertGreater(models.AlbumListMembership.objects.count(), 0)

        top = models.Album.objects.get(rank=1)
        self.assertEqual(top.name, "Pet Sounds")
        self.assertEqual(top.artist_credit, "The Beach Boys")
        self.assertEqual(top.year_released, 1966)
        self.assertEqual(top.wikidata_id, "Q212863")
        self.assertEqual(top.year_rank, 1)
        self.assertEqual(top.decade_rank, 1)

    def test_every_artist_lands_under_its_provider_id(self):
        import_real_release()
        artist_rows = _read_fixture_rows("ArtistInfo.txt")
        self.assertEqual(models.Artist.objects.count(), len(artist_rows))
        self.assertFalse(models.Artist.objects.filter(source_id__isnull=True).exists())
        tags = sum(len([t for t in row[2].split(",") if t]) for row in artist_rows)
        self.assertEqual(models.ArtistRelation.objects.count(), tags)
        slugs = list(models.Artist.objects.values_list("slug", flat=True))
        self.assertEqual(len(set(slugs)), len(slugs))
        self.assertNotIn("", slugs)

    def test_the_credits_read_as_the_artist_system_intends(self):
        # The cases the artist system was designed around, from the
        # 2026-10 discussion with the data provider.
        import_real_release()
        graph = ArtistGraph.load()

        def credit(name):
            return models.Album.objects.get(name=name).artist_credit

        def owns(artist_name, album_name):
            artist = models.Artist.objects.get(name=artist_name)
            album = models.Album.objects.get(name=album_name)
            return album.id in graph.album_ids(artist.id)

        def appears_on(artist_name):
            artist = models.Artist.objects.get(name=artist_name)
            return set(
                models.Album.objects.filter(
                    id__in=graph.appears_on_ids(artist.id)
                ).values_list("name", flat=True)
            )

        self.assertEqual(credit("Band on the Run"), "Paul McCartney & Wings")
        self.assertEqual(credit("The Harder They Come"), "Various Artists")
        self.assertEqual(credit("Déjà Vu"), "Crosby, Stills, Nash & Young")
        self.assertTrue(owns("Prince", "Purple Rain"))
        self.assertTrue(owns("Crosby, Stills & Nash", "Déjà Vu"))
        self.assertTrue(owns("Neil Young", "Déjà Vu"))
        self.assertTrue(owns("The Velvet Underground", "The Velvet Underground & Nico"))
        self.assertFalse(owns("Nico", "The Velvet Underground & Nico"))
        self.assertEqual(appears_on("Nico"), {"The Velvet Underground & Nico"})
        self.assertEqual(
            appears_on("Crazy Horse"),
            {"Everybody Knows This Is Nowhere", "Rust Never Sleeps", "Ragged Glory"},
        )

    def test_every_album_appears_on_at_least_one_list(self):
        self._import_release()
        orphaned = models.Album.objects.filter(lists__isnull=True).count()
        self.assertEqual(orphaned, 0)

    def test_every_album_slug_is_unique(self):
        self._import_release()
        slugs = list(models.Album.objects.values_list("slug", flat=True))
        self.assertEqual(len(set(slugs)), len(slugs))
        self.assertEqual(len(slugs), len(_read_fixture_rows("WebRankings.txt")))

    def test_the_unranked_lists_record_every_member_at_rank_one(self):
        # An unranked list is one where every position in the file is the
        # same; the importer records all of its albums at rank 1.
        self._import_release()
        unranked = [
            source
            for source in models.MusicList.objects.all()
            if set(
                models.AlbumListMembership.objects.filter(list=source).values_list(
                    "rank", flat=True
                )
            )
            == {1}
            and models.AlbumListMembership.objects.filter(list=source).count() > 1
        ]
        self.assertTrue(unranked, "the release has no unranked list any more")
        for source in unranked:
            with self.subTest(list=source.name):
                memberships = models.AlbumListMembership.objects.filter(list=source)
                self.assertEqual(set(memberships.values_list("rank", flat=True)), {1})

    def _import_release(self):
        import_real_release()


def import_real_release():
    """``import_batch`` over the checked-in release, as the command opens it."""
    with ExitStack() as stack:
        files = {
            field: stack.enter_context(
                (FIXTURE_DIR / name).open(
                    encoding="utf-8-sig",
                    newline=None if field == "positions_file" else "",
                )
            )
            for field, name in (
                ("artists_file", "ArtistInfo.txt"),
                ("lists_file", "ListData.txt"),
                ("albums_file", "WebRankings.txt"),
                ("positions_file", "ListPositions.txt"),
            )
        }
        return import_handler.import_batch(**files)


def _read_fixture_rows(filename):
    """Read a release TSV into a list of column lists."""
    with (FIXTURE_DIR / filename).open(encoding="utf-8-sig") as handle:
        return [line.rstrip("\r\n").split("\t") for line in handle if line.strip()]


class ImportInvalidatesCachesTests(StaffUserTestMixin, TestCase):
    """An import has to drop the counts it just made wrong.

    Only the import *page* used to invalidate, so a command-line import left
    the rankings heading reading "The top 500 most recommended albums across
    54 critic lists" for up to 24 hours after the release grew to 1000.
    """

    def _import_release(self):
        return import_real_release()

    def test_the_import_drops_every_cached_key(self):
        for key in config.CACHE_KEYS:
            cache.set(key, "stale", 600)
        self._import_release()
        for key in config.CACHE_KEYS:
            with self.subTest(key=key):
                self.assertIsNone(cache.get(key))

    def test_the_heading_counts_are_right_straight_after_an_import(self):
        # The symptom, end to end: cache the old counts, import a bigger
        # release, and the page must not still be describing the old one.
        self.client.get(reverse("music:home"))
        self._import_release()
        response = self.client.get(reverse("music:home"))
        self.assertEqual(response.context["album_count"], models.Album.objects.count())
        self.assertEqual(
            response.context["list_count"], models.MusicList.objects.count()
        )
        self.assertEqual(
            response.context["publication_count"],
            models.MusicPublication.objects.count(),
        )

    def test_the_import_stamps_the_update_time(self):
        self._import_release()
        self.assertIsNotNone(
            SiteMetadata.get_instance(config.SITE_METADATA_KEY).last_full_update
        )


class ImportReconnectsTrackingTests(TestCase):
    """An import replaces every album, and must not empty a collection.

    The rows survive the delete because their album FK nulls rather than
    cascading, but they are useless until something points them at the new
    rows - so the importer runs the reconnection pass itself.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="listener", password="pw")
        import_artists()
        import_handler.import_albums(StringIO(ALBUMS_TSV))

    def test_a_reimport_re_adopts_a_tracked_album(self):
        album = models.Album.objects.get(rank=1)
        models.ListenedAlbum.objects.create(
            user=self.user, album=album, wikidata_id=album.wikidata_id
        )

        import_handler.import_albums(StringIO(ALBUMS_TSV))

        row = models.ListenedAlbum.objects.get()
        self.assertIsNotNone(row.album)
        self.assertEqual(row.album.name, "Pet Sounds")
        # A different row object than before: every album was replaced.
        self.assertNotEqual(row.album_id, album.id)

    def test_a_reimport_re_adopts_both_kinds_of_row(self):
        listened = models.Album.objects.get(rank=1)
        wanted = models.Album.objects.get(rank=2)
        models.ListenedAlbum.objects.create(
            user=self.user, album=listened, wikidata_id=listened.wikidata_id
        )
        models.WantToListenAlbum.objects.create(
            user=self.user, album=wanted, wikidata_id=wanted.wikidata_id
        )

        import_handler.import_albums(StringIO(ALBUMS_TSV))

        self.assertEqual(models.ListenedAlbum.objects.get().album.name, "Pet Sounds")
        self.assertEqual(models.WantToListenAlbum.objects.get().album.name, "Déjà Vu")

    def test_a_reimport_normalizes_a_secondary_wikidata_id(self):
        # Rust Never Sleeps carries two ids in the fixture; a row stored
        # under the second has to find its way home and then be renamed to
        # the primary, or the next import orphans it again.
        models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q999999"
        )

        import_handler.import_albums(StringIO(ALBUMS_TSV))

        row = models.ListenedAlbum.objects.get()
        self.assertEqual(row.album.name, "Rust Never Sleeps")
        self.assertEqual(row.wikidata_id, "Q1140313")

    def test_a_reimport_merges_two_rows_that_now_point_at_one_album(self):
        models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q1140313"
        )
        models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q999999"
        )

        import_handler.import_albums(StringIO(ALBUMS_TSV))

        self.assertEqual(models.ListenedAlbum.objects.count(), 1)
        self.assertEqual(
            models.ListenedAlbum.objects.get().album.name, "Rust Never Sleeps"
        )

    def test_a_reimport_leaves_an_untracked_database_alone(self):
        # The common case, and the reason the pass is behind an existence
        # check rather than run unconditionally.
        success, _ = import_handler.import_albums(StringIO(ALBUMS_TSV))
        self.assertTrue(success)
        self.assertEqual(models.ListenedAlbum.objects.count(), 0)

    def test_a_reimport_drops_the_affected_users_caches(self):
        album = models.Album.objects.get(rank=1)
        models.ListenedAlbum.objects.create(
            user=self.user, album=album, wikidata_id=album.wikidata_id
        )
        key = config.CACHE_KEY_LISTENED_ALBUMS.format(user_id=self.user.id)
        cache.set(key, [album.id], 300)

        import_handler.import_albums(StringIO(ALBUMS_TSV))

        self.assertIsNone(cache.get(key))

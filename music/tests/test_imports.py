"""Tests for the music import handler.

The importers are driven with StringIO rather than files, matching
``games/tests/test_imports.py``. The real release files in
``acclaimedgames/test_input_files/music/`` back the end-to-end test.
"""

from io import StringIO
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from core import constants as core_constants
from core.models import User
from music import config, models
from music.services import import_handler
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

ALBUMS_TSV = (
    "1\tPet Sounds\tThe Beach Boys\t1966\tQ212863\n"
    "2\tDéjà Vu\tCrosby, Stills & Nash\t1970\tQ1136782\n"
    "3\tRust Never Sleeps\tNeil Young, Crazy Horse\t1979\tQ1140313,Q999999\n"
)

POSITIONS_TSV = "0:2\t1:5\n0:1\t2:9\n0:3\n"


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


class SplitArtistCreditTests(TestCase):
    def test_single_artist(self):
        self.assertEqual(
            import_handler.split_artist_credit("The Beach Boys"), ["The Beach Boys"]
        )

    def test_comma_separates_collaborators(self):
        self.assertEqual(
            import_handler.split_artist_credit("Neil Young, Crazy Horse"),
            ["Neil Young", "Crazy Horse"],
        )

    def test_an_act_whose_name_contains_a_comma_is_not_split(self):
        self.assertEqual(
            import_handler.split_artist_credit("Crosby, Stills & Nash"),
            ["Crosby, Stills & Nash"],
        )

    def test_every_exception_survives_intact(self):
        for credit in import_handler.ARTISTS_WITH_COMMAS:
            with self.subTest(credit=credit):
                self.assertEqual(import_handler.split_artist_credit(credit), [credit])

    def test_blank_credits_yield_nothing(self):
        self.assertEqual(import_handler.split_artist_credit(""), [])
        self.assertEqual(import_handler.split_artist_credit("   "), [])
        self.assertEqual(import_handler.split_artist_credit(None), [])

    def test_duplicates_within_a_credit_are_collapsed(self):
        self.assertEqual(
            import_handler.split_artist_credit("Prince, Prince"), ["Prince"]
        )

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(
            import_handler.split_artist_credit(" Brian Eno ,  David Byrne "),
            ["Brian Eno", "David Byrne"],
        )

    def test_every_real_comma_credit_parses_as_expected(self):
        # Named rather than counted: a release that adds an act whose own
        # name contains a comma has to add it to ARTISTS_WITH_COMMAS, and a
        # bare count would only say that the number changed. "Tyler, the
        # Creator" arrived in the 2026 release and split into an artist
        # called "Tyler" and another called "the Creator".
        rows = _read_fixture_rows("WebRankings.txt")
        comma_credits = {row[2] for row in rows if "," in row[2]}
        unsplit = {
            credit
            for credit in comma_credits
            if import_handler.split_artist_credit(credit) == [credit]
        }
        self.assertEqual(
            unsplit,
            {"Crosby, Stills & Nash", "Earth, Wind & Fire", "Tyler, the Creator"},
        )

    def test_a_collaboration_credit_still_splits(self):
        rows = _read_fixture_rows("WebRankings.txt")
        comma_credits = {row[2] for row in rows if "," in row[2]}
        collaborations = comma_credits - import_handler.ARTISTS_WITH_COMMAS
        for credit in sorted(collaborations):
            with self.subTest(credit=credit):
                self.assertGreater(len(import_handler.split_artist_credit(credit)), 1)


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
    def test_creates_albums_artists_and_derived_ranks(self):
        success, message = import_handler.import_albums(StringIO(ALBUMS_TSV))
        self.assertTrue(success)
        self.assertIn("Albums: 3 created", message)
        self.assertIn("3 ranks calculated", message)
        self.assertEqual(models.Album.objects.count(), 3)

        album = models.Album.objects.get(rank=1)
        self.assertEqual(album.name, "Pet Sounds")
        self.assertEqual(album.artist_credit, "The Beach Boys")
        self.assertEqual(album.year_released, 1966)
        self.assertEqual(album.wikidata_id, "Q212863")
        self.assertEqual(album.all_wikidata_ids, ["Q212863"])
        self.assertEqual(album.year_rank, 1)
        self.assertEqual(album.decade_rank, 1)

    def test_an_act_with_a_comma_in_its_name_becomes_one_artist(self):
        import_handler.import_albums(StringIO(ALBUMS_TSV))
        album = models.Album.objects.get(rank=2)
        self.assertEqual(
            [a.name for a in album.artists.all()], ["Crosby, Stills & Nash"]
        )

    def test_collaborators_become_separate_artists(self):
        import_handler.import_albums(StringIO(ALBUMS_TSV))
        album = models.Album.objects.get(rank=3)
        self.assertCountEqual(
            [a.name for a in album.artists.all()], ["Neil Young", "Crazy Horse"]
        )

    def test_the_first_wikidata_id_is_primary_and_the_rest_are_kept(self):
        import_handler.import_albums(StringIO(ALBUMS_TSV))
        album = models.Album.objects.get(rank=3)
        self.assertEqual(album.wikidata_id, "Q1140313")
        self.assertEqual(album.all_wikidata_ids, ["Q1140313", "Q999999"])

    def test_a_missing_wikidata_column_is_tolerated(self):
        import_handler.import_albums(StringIO("1\tUntitled\tAnon\t1999\n"))
        album = models.Album.objects.get(rank=1)
        self.assertIsNone(album.wikidata_id)
        self.assertEqual(album.all_wikidata_ids, [])

    def test_a_blank_year_is_stored_as_null(self):
        import_handler.import_albums(StringIO("1\tUndated\tAnon\t\tQ1\n"))
        self.assertIsNone(models.Album.objects.get(rank=1).year_released)

    def test_an_artist_is_reused_across_albums(self):
        tsv = (
            "1\tRevolver\tThe Beatles\t1966\tQ1\n"
            "2\tAbbey Road\tThe Beatles\t1969\tQ2\n"
        )
        import_handler.import_albums(StringIO(tsv))
        self.assertEqual(models.Artist.objects.filter(name="The Beatles").count(), 1)

    def test_artists_with_colliding_slugs_get_distinct_slugs(self):
        models.Artist.objects.create(name="Nico (singer)", slug="nico")
        import_handler.import_albums(StringIO("1\tChelsea Girl\tNico\t1967\tQ1\n"))
        imported = models.Artist.objects.get(name="Nico")
        self.assertEqual(imported.slug, "nico-2")

    def test_reimporting_replaces_the_previous_albums(self):
        import_handler.import_albums(StringIO(ALBUMS_TSV))
        success, message = import_handler.import_albums(StringIO(ALBUMS_TSV))
        self.assertTrue(success)
        self.assertIn("deleted 3 old", message)
        self.assertEqual(models.Album.objects.count(), 3)

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
    def test_runs_all_three_importers_in_order(self):
        success, message = import_handler.import_batch(
            StringIO(LISTS_TSV), StringIO(ALBUMS_TSV), StringIO(POSITIONS_TSV)
        )
        self.assertTrue(success)
        self.assertIn("Lists: 3 created", message)
        self.assertIn("Albums: 3 created", message)
        self.assertIn("memberships: 5 created", message)
        self.assertEqual(models.MusicList.objects.count(), 3)
        self.assertEqual(models.Album.objects.count(), 3)
        self.assertEqual(models.AlbumListMembership.objects.count(), 5)

    def test_an_empty_lists_file_stops_the_batch(self):
        with self.assertRaises(ValueError) as ctx:
            import_handler.import_batch(
                StringIO("\n"), StringIO(ALBUMS_TSV), StringIO(POSITIONS_TSV)
            )
        self.assertIn("No lists were imported", str(ctx.exception))

    def test_an_empty_albums_file_stops_the_batch(self):
        with self.assertRaises(ValueError) as ctx:
            import_handler.import_batch(
                StringIO(LISTS_TSV), StringIO("\n"), StringIO(POSITIONS_TSV)
            )
        self.assertIn("No albums were imported", str(ctx.exception))

    def test_a_failure_rolls_the_whole_batch_back(self):
        # A positions file with more rows than albums fails mid-import; the
        # lists and albums written before it must not survive.
        with self.assertRaises(ValueError):
            import_handler.import_batch(
                StringIO(LISTS_TSV),
                StringIO(ALBUMS_TSV),
                StringIO(POSITIONS_TSV + "0:1\n"),
            )
        self.assertEqual(models.MusicList.objects.count(), 0)
        self.assertEqual(models.Album.objects.count(), 0)


class RealReleaseFilesTests(TestCase):
    """End-to-end over the files the rankings actually shipped with."""

    def test_the_supplied_release_imports_completely(self):
        with (
            (FIXTURE_DIR / "ListData.txt").open(
                encoding="utf-8-sig", newline=""
            ) as lists_file,
            (FIXTURE_DIR / "WebRankings.txt").open(
                encoding="utf-8-sig", newline=""
            ) as albums_file,
            (FIXTURE_DIR / "ListPositions.txt").open(
                encoding="utf-8-sig"
            ) as positions_file,
        ):
            success, _ = import_handler.import_batch(
                lists_file, albums_file, positions_file
            )

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
        with (
            (FIXTURE_DIR / "ListData.txt").open(
                encoding="utf-8-sig", newline=""
            ) as lists_file,
            (FIXTURE_DIR / "WebRankings.txt").open(
                encoding="utf-8-sig", newline=""
            ) as albums_file,
            (FIXTURE_DIR / "ListPositions.txt").open(
                encoding="utf-8-sig"
            ) as positions_file,
        ):
            import_handler.import_batch(lists_file, albums_file, positions_file)


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
        with (
            (FIXTURE_DIR / "ListData.txt").open(encoding="utf-8-sig") as lists_file,
            (FIXTURE_DIR / "WebRankings.txt").open(encoding="utf-8-sig") as albums_file,
            (FIXTURE_DIR / "ListPositions.txt").open(
                encoding="utf-8-sig"
            ) as positions_file,
        ):
            return import_handler.import_batch(lists_file, albums_file, positions_file)

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

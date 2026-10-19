"""Tests for the offline genre rebuild and its management command.

The rebuild reads only what the metadata passes stored, so these tests build
the stored rows directly rather than mocking any client.
"""

from collections import Counter
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from music import models
from music.services import genre_normalizer as gn
from music.services import genre_rebuild


class RebuildTestCase(TestCase):
    def setUp(self):
        # Most tests use one or two albums; pruning is tested on its own.
        patcher = mock.patch.object(gn, "MIN_LEAF_ALBUMS", 1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def album(self, name, rank, discogs=None, wikidata=None, musicbrainz=None):
        album = models.Album.objects.create(name=name, rank=rank)
        if discogs is not None:
            styles, genres = discogs
            record = models.DiscogsAlbumData.objects.create(
                album=album, master_id=rank, styles=styles, genres=genres
            )
            album.primary_discogs_album_data = record
        if wikidata is not None:
            record = models.WikipediaAlbumData.objects.create(
                album=album, wikidata_id=f"Q{rank}", all_genres=wikidata
            )
            album.primary_wikipedia_album_data = record
        if musicbrainz is not None:
            record = models.MusicBrainzAlbumData.objects.create(
                album=album, release_group_mbid=f"mbid-{rank}", all_genres=musicbrainz
            )
            album.primary_musicbrainz_album_data = record
        album.save()
        return album

    def names(self, album):
        return sorted(genre.name for genre in album.genres.all())


class AlbumVotesTests(RebuildTestCase):
    def test_each_source_votes_in_priority_order(self):
        album = self.album(
            "Harvest",
            1,
            discogs=(["Folk Rock"], ["Rock"]),
            wikidata="country rock, folk rock",
            musicbrainz="folk rock",
        )
        votes = genre_rebuild.album_votes(album)
        self.assertEqual(
            [v.name for v in votes], ["discogs", "wikidata", "musicbrainz"]
        )
        self.assertEqual(votes[1].leaves, ["Country Rock", "Folk Rock"])

    def test_the_primary_row_is_preferred(self):
        album = self.album("X", 1, discogs=(["Grunge"], ["Rock"]))
        models.DiscogsAlbumData.objects.create(
            album=album, master_id=99, styles=["Disco"], genres=["Funk / Soul"]
        )
        votes = genre_rebuild.album_votes(album)
        self.assertEqual(votes[0].leaves, ["Grunge"])

    def test_without_a_primary_the_first_row_is_used(self):
        album = models.Album.objects.create(name="X", rank=1)
        models.WikipediaAlbumData.objects.create(
            album=album, wikidata_id="Q1", all_genres="grunge"
        )
        votes = genre_rebuild.album_votes(album)
        self.assertEqual(votes[0].leaves, ["Grunge"])

    def test_only_the_top_musicbrainz_genres_count(self):
        """MusicBrainz lists everything anyone voted for."""
        labels = ["rock", "grunge", "punk", "metal", "soul", "disco", "jazz"]
        album = self.album("X", 1, musicbrainz=", ".join(labels))
        votes = genre_rebuild.album_votes(album)
        self.assertEqual(votes[0].leaves, ["Grunge"])
        self.assertEqual(votes[0].roots, ["Rock", "Punk", "Metal", "Soul"])

    def test_an_album_with_no_metadata_has_no_votes(self):
        album = models.Album.objects.create(name="X", rank=1)
        self.assertEqual(genre_rebuild.album_votes(album), [])


class RebuildTests(RebuildTestCase):
    def test_genres_are_written_with_their_roots(self):
        album = self.album(
            "Harvest",
            1,
            discogs=(["Folk Rock", "Country Rock"], ["Rock"]),
            wikidata="country rock, folk rock",
        )
        report = genre_rebuild.rebuild_album_genres()
        self.assertEqual(
            self.names(album), ["Country", "Country Rock", "Folk", "Folk Rock", "Rock"]
        )
        self.assertEqual(
            models.MusicGenre.objects.get(name="Country Rock").parent.name, "Rock"
        )
        self.assertIn(album.id, report.changed)
        self.assertEqual(report.albums, 1)
        self.assertEqual(report.leaves_after, 2)

    def test_a_dry_run_changes_nothing(self):
        album = self.album("X", 1, discogs=(["Grunge"], ["Rock"]))
        report = genre_rebuild.rebuild_album_genres(dry_run=True)
        self.assertEqual(album.genres.count(), 0)
        self.assertEqual(models.MusicGenre.objects.count(), 0)
        self.assertTrue(report.dry_run)
        self.assertEqual(report.changed[album.id], ("X", [], ["Grunge", "Rock"]))
        self.assertIn("would change", report.summary())

    def test_an_unchanged_album_is_not_rewritten(self):
        album = self.album("X", 1, discogs=(["Grunge"], ["Rock"]))
        genre_rebuild.rebuild_album_genres()
        album.refresh_from_db()
        stamp = album.modified

        report = genre_rebuild.rebuild_album_genres()
        album.refresh_from_db()
        self.assertEqual(report.changed, {})
        self.assertEqual(album.modified, stamp)
        self.assertIn("0 changed", report.summary())

    def test_a_changed_album_is_touched_for_the_data_version(self):
        """Setting an M2M does not touch Album.modified, which the payload reads."""
        album = self.album("X", 1, discogs=(["Grunge"], ["Rock"]))
        before = album.modified
        genre_rebuild.rebuild_album_genres()
        album.refresh_from_db()
        self.assertGreater(album.modified, before)

    def test_caches_are_dropped_on_commit(self):
        self.album("X", 1, discogs=(["Grunge"], ["Rock"]))
        with mock.patch(
            "music.services.caching.invalidate_music_caches"
        ) as invalidate, self.captureOnCommitCallbacks(execute=True):
            genre_rebuild.rebuild_album_genres()
        invalidate.assert_called_once()

    def test_unclassified_labels_are_reported(self):
        self.album("X", 1, discogs=(["Grunge", "Zeuhl"], ["Rock"]), wikidata="zeuhl")
        report = genre_rebuild.rebuild_album_genres(dry_run=True)
        self.assertEqual(
            report.unclassified,
            {("discogs", "Zeuhl"): 1, ("wikidata", "zeuhl"): 1},
        )

    def test_counts_before_and_after(self):
        album = self.album("X", 1, discogs=(["Grunge"], ["Rock"]))
        stray = gn.get_or_create_genre("Thrash", "Metal")
        album.genres.add(stray, gn.get_or_create_genre("Metal"))
        report = genre_rebuild.rebuild_album_genres(dry_run=True)
        self.assertEqual(report.leaves_before, 1)
        self.assertEqual(report.single_album_leaves_before, 1)
        self.assertEqual(report.leaves_after, 1)
        self.assertEqual(report.single_album_leaves_after, 1)
        self.assertEqual(report.genres_per_album, 2.0)
        self.assertEqual(report.albums_without_genres, 0)

    def test_an_album_with_nothing_is_counted(self):
        models.Album.objects.create(name="X", rank=1)
        report = genre_rebuild.rebuild_album_genres(dry_run=True)
        self.assertEqual(report.albums_without_genres, 1)

    def test_an_empty_corpus(self):
        report = genre_rebuild.rebuild_album_genres()
        self.assertEqual(report.albums, 0)
        self.assertEqual(report.genres_per_album, 0.0)


class PruningTests(RebuildTestCase):
    def test_a_rare_leaf_is_not_created_and_its_root_is_kept(self):
        with mock.patch.object(gn, "MIN_LEAF_ALBUMS", 2):
            a = self.album("A", 1, discogs=(["Grunge", "Shoegaze"], ["Rock"]))
            b = self.album("B", 2, discogs=(["Grunge"], ["Rock"]))
            report = genre_rebuild.rebuild_album_genres()
        self.assertEqual(report.pruned, {"Shoegaze": 1})
        self.assertEqual(self.names(a), ["Grunge", "Rock"])
        self.assertEqual(self.names(b), ["Grunge", "Rock"])
        self.assertFalse(models.MusicGenre.objects.filter(name="Shoegaze").exists())


class GenreRowTests(RebuildTestCase):
    def test_an_aliased_row_is_renamed_so_its_id_survives(self):
        """'Glam' becomes 'Glam Rock' in place; ?genres=<id> keeps working."""
        album = self.album("Ziggy", 1, discogs=(["Glam"], ["Rock"]))
        old = gn.get_or_create_genre("Glam", "Rock")
        album.genres.add(old)

        report = genre_rebuild.rebuild_album_genres()
        old.refresh_from_db()
        self.assertEqual(old.name, "Glam Rock")
        self.assertEqual(old.slug, "glam-rock")
        self.assertIn(old, album.genres.all())
        self.assertEqual(report.renamed, [("Glam", "Glam Rock")])

    def test_the_busiest_alias_row_is_the_one_renamed(self):
        album = self.album("A", 1, discogs=(["Thrash"], ["Rock"]))
        quiet = gn.get_or_create_genre("Speed Metal", "Metal")
        busy = gn.get_or_create_genre("Thrash", "Metal")
        album.genres.add(busy)

        genre_rebuild.rebuild_album_genres()
        busy.refresh_from_db()
        self.assertEqual(busy.name, "Thrash Metal")
        self.assertFalse(models.MusicGenre.objects.filter(pk=quiet.pk).exists())

    def test_a_rename_keeps_the_old_slug_if_the_new_one_is_taken(self):
        self.album("A", 1, discogs=(["Glam"], ["Rock"]))
        old = gn.get_or_create_genre("Glam", "Rock")
        models.MusicGenre.objects.create(name="Unrelated", slug="glam-rock")

        genre_rebuild.rebuild_album_genres()
        old.refresh_from_db()
        self.assertEqual(old.name, "Glam Rock")
        self.assertEqual(old.slug, "glam")

    def test_a_row_already_named_for_the_vocabulary_is_not_renamed(self):
        self.album("A", 1, discogs=(["Glam"], ["Rock"]))
        existing = gn.get_or_create_genre("Glam Rock", "Rock")
        gn.get_or_create_genre("Glam", "Rock")

        report = genre_rebuild.rebuild_album_genres()
        self.assertEqual(report.renamed, [])
        self.assertTrue(models.MusicGenre.objects.filter(pk=existing.pk).exists())
        self.assertFalse(models.MusicGenre.objects.filter(name="Glam").exists())

    def test_a_misfiled_row_is_moved(self):
        album = self.album("A", 1, discogs=(["Bubblegum", "Pop Rock"], ["Pop"]))
        gn.get_or_create_genre("Pop Rock", "Electronic")
        genre_rebuild.rebuild_album_genres()
        self.assertEqual(self.names(album), ["Pop", "Pop Rock", "Rock"])
        self.assertEqual(
            models.MusicGenre.objects.get(name="Pop Rock").parent.name, "Rock"
        )

    def test_unused_rows_are_deleted_deepest_first(self):
        self.album("A", 1, discogs=(["Grunge"], ["Rock"]))
        gn.get_or_create_genre("Radioplay", "Electronic")
        deep = models.MusicGenre.objects.create(
            name="Deep",
            parent=gn.get_or_create_genre("Mid", "Classical"),
        )

        report = genre_rebuild.rebuild_album_genres()
        remaining = set(models.MusicGenre.objects.values_list("name", flat=True))
        self.assertEqual(remaining, {"Rock", "Grunge"})
        self.assertEqual(report.deleted.index("Deep"), 0)
        self.assertFalse(models.MusicGenre.objects.filter(pk=deep.pk).exists())

    def test_a_parent_is_kept_while_a_child_is_used(self):
        """``parent`` cascades, so deleting a used row's parent deletes it too."""
        album = self.album("A", 1, discogs=(["Grunge"], ["Rock"]))
        legacy = gn.get_or_create_genre("Legacy", "Rock")
        child = models.MusicGenre.objects.create(name="Child", parent=legacy)
        # An album the plan does not cover still uses the child.
        other = models.Album.objects.create(name="B", rank=2)
        other.genres.add(child)

        plan = (
            [album],
            {album.id: gn.AlbumGenres(leaves=["Grunge"], roots=["Rock"])},
            {},
            Counter(),
        )
        with mock.patch.object(genre_rebuild, "plan_genres", return_value=plan):
            genre_rebuild.rebuild_album_genres()
        self.assertTrue(models.MusicGenre.objects.filter(pk=legacy.pk).exists())
        self.assertTrue(models.MusicGenre.objects.filter(pk=child.pk).exists())


class SavedFilterRemapTests(RebuildTestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user("reader", password="x")
        self.album("A", 1, discogs=(["Grunge", "Glam"], ["Rock"]))

    def saved(self, genres, name="mine"):
        return models.SavedAlbumFilterSet.objects.create(
            user=self.user, name=name, filters={"genres": genres, "sort": "rank"}
        )

    def test_a_deleted_alias_points_at_its_leaf(self):
        leaf = gn.get_or_create_genre("Grunge", "Rock")
        alias = gn.get_or_create_genre("Seattle Sound", "Rock")
        saved = self.saved([str(alias.id), str(leaf.id)])

        with mock.patch.dict(
            gn._LOOKUP, {"seattle sound": gn.Canonical("Grunge", ("Rock",))}
        ):
            report = genre_rebuild.rebuild_album_genres()
        saved.refresh_from_db()
        self.assertEqual(saved.filters["genres"], [str(leaf.id)])
        self.assertEqual(saved.filters["sort"], "rank")
        self.assertEqual(report.saved_filters_remapped, 1)

    def test_a_deleted_root_alias_points_at_the_root(self):
        stale = gn.get_or_create_genre("Rock Music", "Rock")
        saved = self.saved([stale.id])
        genre_rebuild.rebuild_album_genres()
        saved.refresh_from_db()
        rock = models.MusicGenre.objects.get(name="Rock")
        self.assertEqual(saved.filters["genres"], [rock.id])

    def test_an_unknown_deleted_genre_falls_back_to_its_old_root(self):
        stale = gn.get_or_create_genre("Zeuhl", "Rock")
        saved = self.saved([str(stale.id)])
        genre_rebuild.rebuild_album_genres()
        saved.refresh_from_db()
        rock = models.MusicGenre.objects.get(name="Rock")
        self.assertEqual(saved.filters["genres"], [str(rock.id)])

    def test_a_genre_with_no_surviving_ancestor_is_dropped(self):
        stale = gn.get_or_create_genre("Zeuhl", "Classical")
        dropped = gn.get_or_create_genre("Vocal", "Classical")
        saved = self.saved([str(stale.id), str(dropped.id)])
        genre_rebuild.rebuild_album_genres()
        saved.refresh_from_db()
        self.assertEqual(saved.filters["genres"], [])

    def test_a_canonical_leaf_that_did_not_survive_falls_to_its_root(self):
        stale = gn.get_or_create_genre("Shoegaze", "Rock")
        saved = self.saved([str(stale.id)])
        genre_rebuild.rebuild_album_genres()
        saved.refresh_from_db()
        rock = models.MusicGenre.objects.get(name="Rock")
        self.assertEqual(saved.filters["genres"], [str(rock.id)])

    def test_untouched_and_malformed_filters_are_left_alone(self):
        rock = gn.get_or_create_genre("Rock")
        gn.get_or_create_genre("Zeuhl", "Rock")
        untouched = self.saved([str(rock.id), "not-an-id"], name="a")
        empty = self.saved([], name="b")
        odd = models.SavedAlbumFilterSet.objects.create(
            user=self.user, name="c", filters=["not", "a", "dict"]
        )
        no_genres = models.SavedAlbumFilterSet.objects.create(
            user=self.user, name="d", filters={"sort": "rank"}
        )

        report = genre_rebuild.rebuild_album_genres()
        for saved, expected in [
            (untouched, {"genres": [str(rock.id), "not-an-id"], "sort": "rank"}),
            (empty, {"genres": [], "sort": "rank"}),
            (odd, ["not", "a", "dict"]),
            (no_genres, {"sort": "rank"}),
        ]:
            saved.refresh_from_db()
            self.assertEqual(saved.filters, expected)
        self.assertEqual(report.saved_filters_remapped, 0)


class CommandTests(RebuildTestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command("rebuild_album_genres", *args, stdout=out)
        return out.getvalue()

    def test_a_dry_run_reports_without_writing(self):
        self.album("Ziggy", 1, discogs=(["Glam", "Zeuhl"], ["Rock"]))
        output = self.run_command("--dry-run", "--report")
        self.assertIn("would change", output)
        self.assertIn("Dry run: nothing was changed.", output)
        self.assertIn("discogs: Zeuhl", output)
        self.assertIn("Ziggy: + Glam Rock, Rock", output)
        self.assertEqual(models.MusicGenre.objects.count(), 0)

    def test_the_real_run_reports_renames_deletions_and_remaps(self):
        user = get_user_model().objects.create_user("reader", password="x")
        album = self.album("Ziggy", 1, discogs=(["Glam"], ["Rock"]))
        album.genres.add(gn.get_or_create_genre("Glam", "Rock"))
        stale = gn.get_or_create_genre("Zeuhl", "Rock")
        album.genres.add(stale)
        models.SavedAlbumFilterSet.objects.create(
            user=user, name="x", filters={"genres": [str(stale.id)]}
        )

        output = self.run_command()
        self.assertIn("Renamed: Glam -> Glam Rock", output)
        self.assertIn("Deleted 1 unused genre row(s)", output)
        self.assertIn("Remapped 1 saved filter(s)", output)
        self.assertNotIn("Dry run", output)

    def test_the_report_lists_pruned_leaves_and_removals(self):
        with mock.patch.object(gn, "MIN_LEAF_ALBUMS", 2):
            album = self.album("A", 1, discogs=(["Grunge", "Shoegaze"], ["Rock"]))
            self.album("B", 2, discogs=(["Grunge"], ["Rock"]))
            album.genres.add(gn.get_or_create_genre("Thrash", "Metal"))
            output = self.run_command("--dry-run", "--report")
        self.assertIn("Shoegaze (1)", output)
        self.assertIn("A: - Thrash  + Grunge, Rock", output)

    def test_without_report_unclassified_labels_are_only_counted(self):
        self.album("A", 1, discogs=(["Zeuhl"], ["Rock"]))
        output = self.run_command("--dry-run")
        self.assertIn("1 label(s) the vocabulary does not classify yet", output)
        self.assertNotIn("discogs: Zeuhl", output)

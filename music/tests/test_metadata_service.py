"""Tests for the album metadata orchestration service.

Every client is mocked: these tests are about what gets written to the
database and in what order, not about HTTP.
"""

from datetime import date, datetime
from unittest import mock

from django.test import SimpleTestCase, TestCase

from music import models
from music.musicbrainz import CoverArt, ReleaseGroup
from music.discogs import DiscogsMaster
from music.services.import_handler import normalize_artist_name
from music.services.metadata_service import (
    AlbumMetadataService,
    PassResult,
    fit,
)
from music.wikidata import AlbumMetadata, ArtistMetadata

RG_MBID = "9162580e-5df4-32de-80cc-f45a8d8a9b1d"
RELEASE_MBID = "f04cce33-b9a0-4bed-af11-f84d649652b2"


class NormalizeArtistNameTests(SimpleTestCase):
    def test_ampersand_and_the_are_collapsed(self):
        self.assertEqual(
            normalize_artist_name("Bob Marley & The Wailers"),
            normalize_artist_name("Bob Marley and the Wailers"),
        )

    def test_punctuation_is_ignored(self):
        self.assertEqual(
            normalize_artist_name("Public Image Ltd."),
            normalize_artist_name("Public Image Ltd"),
        )

    def test_apostrophes_are_ignored(self):
        self.assertEqual(
            normalize_artist_name("The B-52's"), normalize_artist_name("The B-52s")
        )

    def test_different_acts_do_not_collapse(self):
        self.assertNotEqual(
            normalize_artist_name("Jimi Hendrix"),
            normalize_artist_name("The Jimi Hendrix Experience"),
        )

    def test_an_empty_name_normalizes_to_nothing(self):
        self.assertEqual(normalize_artist_name(""), "")
        self.assertEqual(normalize_artist_name("the"), "")


class PassResultTests(SimpleTestCase):
    def test_a_bare_summary_names_only_what_happened(self):
        self.assertEqual(PassResult(name="X", processed=3).summary(), "X: 3 processed")

    def test_every_counter_appears_when_set(self):
        result = PassResult(name="X", processed=1, skipped=2, adopted=3, errors=["a"])
        summary = result.summary()
        self.assertIn("1 processed", summary)
        self.assertIn("3 reconnected", summary)
        self.assertIn("2 skipped", summary)
        self.assertIn("1 failed", summary)


class ServiceTestCase(TestCase):
    def setUp(self):
        self.service = AlbumMetadataService()
        self.album = models.Album.objects.create(
            name="Abbey Road",
            rank=2,
            year_released=1969,
            artist_credit="The Beatles",
            wikidata_id="Q173643",
        )

    def album_meta(self, **overrides):
        defaults = dict(
            wikidata_id="Q173643",
            page_title="Abbey Road",
            release_date=date(1969, 9, 26),
            release_date_precision="day",
            record_label_qid="Q213710",
            spotify_album_id="0ETFjACtuP2ADo6",
            musicbrainz_release_group_id=RG_MBID,
            discogs_master_id=24047,
            performer_qids=["Q1299"],
            genre_qids=["Q11399"],
        )
        defaults.update(overrides)
        return AlbumMetadata(**defaults)


class AlbumQidTests(ServiceTestCase):
    def test_the_primary_qid_comes_first(self):
        self.album.all_wikidata_ids = ["Q999", "Q173643"]
        self.assertEqual(self.album.wikidata_qids, ["Q173643", "Q999"])

    def test_duplicates_are_removed(self):
        self.album.all_wikidata_ids = ["Q173643", "Q173643"]
        self.assertEqual(self.album.wikidata_qids, ["Q173643"])

    def test_blank_entries_are_ignored(self):
        self.album.all_wikidata_ids = ["", None, "Q2"]
        self.assertEqual(self.album.wikidata_qids, ["Q173643", "Q2"])

    def test_an_album_with_no_primary_id_still_offers_the_others(self):
        self.album.wikidata_id = None
        self.album.all_wikidata_ids = ["Q2"]
        self.assertEqual(self.album.wikidata_qids, ["Q2"])


class WikidataPassTests(ServiceTestCase):
    def run_pass(self, metadata=None, artists=None, labels=None, albums=None):
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_album_metadata.return_value = (
            metadata if metadata is not None else {"Q173643": self.album_meta()}
        )
        client.fetch_artists.return_value = (
            artists
            if artists is not None
            else {
                "Q1299": ArtistMetadata(
                    wikidata_id="Q1299", name="The Beatles", musicbrainz_id="b10bbbfc"
                )
            }
        )
        client.fetch_labels.return_value = (
            labels
            if labels is not None
            else {"Q11399": "rock music", "Q213710": "Apple Records"}
        )
        with mock.patch(
            "music.services.metadata_service.WikidataClient", return_value=client
        ):
            return self.service.run_wikidata(
                albums if albums is not None else [self.album]
            )

    def test_the_wikipedia_record_is_written(self):
        result = self.run_pass()
        self.assertEqual(result.processed, 1)
        record = self.album.wikipedia_album_data_set.get()
        self.assertEqual(record.page_title, "Abbey Road")
        self.assertEqual(record.release_date, date(1969, 9, 26))
        self.assertEqual(record.release_date_precision, "day")
        self.assertEqual(record.record_label, "Apple Records")
        self.assertEqual(record.spotify_album_id, "0ETFjACtuP2ADo6")
        self.assertEqual(record.primary_genre, "rock music")
        self.assertEqual(record.all_genres, "rock music")
        self.assertTrue(record.is_primary)

    def test_the_album_gets_the_external_ids(self):
        self.run_pass()
        self.album.refresh_from_db()
        self.assertEqual(self.album.musicbrainz_release_group_id, RG_MBID)
        self.assertEqual(self.album.discogs_master_id, 24047)
        self.assertIsNotNone(self.album.primary_wikipedia_album_data)

    def test_artists_get_their_musicbrainz_id_from_their_own_entity(self):
        beatles = models.Artist.objects.create(
            name="The Beatles", slug="the-beatles", wikidata_id="Q1299"
        )
        self.run_pass(
            artists={
                "Q1299": ArtistMetadata(
                    wikidata_id="Q1299", name="Beatles (label)", musicbrainz_id="b10"
                )
            }
        )
        beatles.refresh_from_db()
        self.assertEqual(beatles.musicbrainz_id, "b10")
        # The name is the release's, never Wikidata's label.
        self.assertEqual(beatles.name, "The Beatles")

    def test_the_artists_asked_for_are_ours_not_the_performers(self):
        models.Artist.objects.create(name="Ours", slug="ours", wikidata_id="Q42")
        models.Artist.objects.create(name="No QID", slug="no-qid")
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_album_metadata.return_value = {"Q173643": self.album_meta()}
        client.fetch_artists.return_value = {}
        client.fetch_labels.return_value = {}
        with mock.patch(
            "music.services.metadata_service.WikidataClient", return_value=client
        ):
            self.service.run_wikidata([self.album])
        self.assertEqual(client.fetch_artists.call_args.args[0], {"Q42"})

    def test_an_unchanged_or_missing_mbid_is_left_alone(self):
        artist = models.Artist.objects.create(
            name="The Beatles",
            slug="the-beatles",
            wikidata_id="Q1299",
            musicbrainz_id="keep",
        )
        self.run_pass(artists={"Q1299": ArtistMetadata(wikidata_id="Q1299", name="x")})
        artist.refresh_from_db()
        self.assertEqual(artist.musicbrainz_id, "keep")

    def test_the_pass_never_changes_an_albums_credits(self):
        credited = models.Artist.objects.create(name="Credited", slug="credited")
        self.album.artists.set([credited])
        self.run_pass()
        self.assertEqual(self.album.credited_artists, [credited])

    def test_an_orphaned_record_is_adopted_instead_of_duplicated(self):
        orphan = models.WikipediaAlbumData.objects.create(
            album=None, wikidata_id="Q173643", page_title="Stale"
        )
        self.run_pass()
        orphan.refresh_from_db()
        self.assertEqual(orphan.album, self.album)
        self.assertEqual(models.WikipediaAlbumData.objects.count(), 1)

    def test_an_existing_record_is_updated_in_place(self):
        existing = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q173643", page_title="Stale"
        )
        self.run_pass()
        existing.refresh_from_db()
        self.assertEqual(existing.page_title, "Abbey Road")
        self.assertEqual(models.WikipediaAlbumData.objects.count(), 1)

    def test_an_album_wikidata_knows_nothing_about_is_an_error(self):
        result = self.run_pass(metadata={})
        self.assertEqual(result.processed, 0)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Abbey Road", result.errors[0])

    def test_the_edition_carrying_the_identifiers_is_preferred(self):
        """Two albums in the release carry a second QID for another edition."""
        self.album.all_wikidata_ids = ["Q173643", "Q999"]
        self.album.save()
        result = self.run_pass(
            metadata={
                "Q173643": self.album_meta(musicbrainz_release_group_id=None),
                "Q999": self.album_meta(
                    wikidata_id="Q999", musicbrainz_release_group_id=RG_MBID
                ),
            }
        )
        self.album.refresh_from_db()
        self.assertEqual(result.processed, 1)
        self.assertEqual(self.album.musicbrainz_release_group_id, RG_MBID)

    def test_no_albums_is_a_no_op(self):
        result = self.service.run_wikidata([])
        self.assertEqual(result.processed, 0)
        self.assertEqual(result.errors, [])

    def test_an_album_with_no_wikidata_id_at_all_is_reported(self):
        self.album.wikidata_id = None
        self.album.save()
        result = self.service.run_wikidata([self.album])
        self.assertEqual(result.errors, ["No album carries a Wikidata ID"])

    def test_a_failure_on_one_album_does_not_stop_the_others(self):
        other = models.Album.objects.create(
            name="Revolver", rank=7, wikidata_id="Q189622"
        )
        with mock.patch.object(
            self.service, "_save_wikidata", side_effect=[ValueError("nope"), None]
        ):
            result = self.run_pass(albums=[self.album, other])
        self.assertEqual(result.processed, 1)
        self.assertEqual(len(result.errors), 1)

    def test_progress_is_reported(self):
        events = []
        self.service.progress_callback = lambda kind, data: events.append((kind, data))
        self.run_pass()
        kinds = [kind for kind, _ in events]
        self.assertIn("start", kinds)
        self.assertIn("progress", kinds)
        self.assertIn("complete", kinds)

    def test_a_label_qid_without_a_label_leaves_the_field_blank(self):
        self.run_pass(labels={})
        record = self.album.wikipedia_album_data_set.get()
        self.assertIsNone(record.record_label)
        self.assertIsNone(record.all_genres)


class CoverPassTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.album.musicbrainz_release_group_id = RG_MBID
        self.album.save()
        self.art = CoverArt(release_mbid=RELEASE_MBID, image_id="123")

    def build_client(
        self, front=None, release_front=None, payload=(b"img", "image/jpeg")
    ):
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_front_cover.return_value = front
        client.fetch_release_front_cover.return_value = release_front
        client.get_bytes.return_value = payload
        return client

    def run_pass(self, client, albums=None):
        with mock.patch(
            "music.services.metadata_service.CoverArtArchiveClient",
            return_value=client,
        ):
            return self.service.run_covers(albums or [self.album])

    def test_a_cover_is_stored_at_both_sizes(self):
        result = self.run_pass(self.build_client(front=self.art))
        self.assertEqual(result.processed, 1)
        self.assertEqual(models.AlbumCover.objects.count(), 2)
        self.assertEqual(
            sorted(models.AlbumCover.objects.values_list("size", flat=True)),
            sorted(models.AlbumCover.SIZES),
        )
        record = self.album.musicbrainz_album_data_set.get()
        self.assertTrue(record.cover_art_stored)

    def test_the_album_gets_the_remote_url_for_open_graph(self):
        self.run_pass(self.build_client(front=self.art))
        self.album.refresh_from_db()
        self.assertIn("coverartarchive.org", self.album.cover_image_url)

    def test_the_rendered_urls_point_at_our_own_copy(self):
        self.run_pass(self.build_client(front=self.art))
        album = models.Album.objects.get(pk=self.album.pk)
        self.assertTrue(album.thumbnail.startswith("/music/cover/"))
        self.assertTrue(album.image.startswith("/music/cover/"))

    def test_an_album_with_no_release_group_is_skipped(self):
        self.album.musicbrainz_release_group_id = None
        self.album.save()
        with mock.patch.object(self.service, "_musicbrainz") as mb:
            mb.return_value.search_release_group.return_value = None
            result = self.run_pass(self.build_client())
        self.assertIn("no MusicBrainz release group", result.errors[0])

    def test_a_missing_release_group_is_searched_for(self):
        self.album.musicbrainz_release_group_id = None
        self.album.save()
        with mock.patch.object(self.service, "_musicbrainz") as mb:
            mb.return_value.search_release_group.return_value = RG_MBID
            self.run_pass(self.build_client(front=self.art))
        self.album.refresh_from_db()
        self.assertEqual(self.album.musicbrainz_release_group_id, RG_MBID)

    def test_a_compilation_is_searched_for_by_title_alone(self):
        # "Various Artists" is our wording, not a credit MusicBrainz knows.
        self.album.musicbrainz_release_group_id = None
        self.album.artist_credit = "Various Artists"
        self.album.save()
        with mock.patch.object(self.service, "_musicbrainz") as mb:
            mb.return_value.search_release_group.return_value = RG_MBID
            self.run_pass(self.build_client(front=self.art))
        mb.return_value.search_release_group.assert_called_with("Abbey Road", "", 1969)

    def test_a_group_with_no_art_falls_back_to_its_releases(self):
        client = self.build_client(front=None, release_front=self.art)
        with mock.patch.object(self.service, "_release_mbids", return_value=["rel-1"]):
            result = self.run_pass(client)
        self.assertEqual(result.processed, 1)
        client.fetch_release_front_cover.assert_called_once_with("rel-1")

    def test_art_whose_bytes_will_not_download_is_rejected(self):
        """A URL in the listing is not evidence of an image."""
        client = self.build_client(front=self.art, payload=None)
        with mock.patch.object(self.service, "_release_mbids", return_value=[]):
            result = self.run_pass(client)
        self.assertEqual(result.processed, 0)
        self.assertIn("no front cover", result.errors[0])

    def test_a_release_whose_bytes_fail_is_passed_over(self):
        client = self.build_client(front=None, release_front=self.art)
        # The first release's verification download fails; the second's
        # succeeds, then both sizes are stored.
        client.get_bytes.side_effect = [
            None,
            (b"img", "image/jpeg"),
            (b"img", "image/jpeg"),
            (b"img", "image/jpeg"),
        ]
        with mock.patch.object(
            self.service, "_release_mbids", return_value=["rel-1", "rel-2"]
        ):
            result = self.run_pass(client)
        self.assertEqual(result.processed, 1)

    def stored_image_id(self):
        return self.album.musicbrainz_album_data_set.get().cover_art_image_id

    def test_a_clean_group_cover_ends_the_search(self):
        client = self.build_client(front=self.art)
        with mock.patch.object(self.service, "_release_mbids") as releases:
            self.run_pass(client)
        releases.assert_not_called()

    def test_a_package_photo_loses_to_a_later_clean_release(self):
        """It Takes a Nation of Millions: broken group art, then a photo of
        the jewel case on the earliest release, then a clean scan."""
        photo = CoverArt("rel-1", "1", ("Front", "Back", "Medium"))
        clean = CoverArt("rel-2", "2", ("Front",))
        client = self.build_client(front=None)
        client.fetch_release_front_cover.side_effect = [photo, clean]
        with mock.patch.object(
            self.service, "_release_mbids", return_value=["rel-1", "rel-2"]
        ):
            self.run_pass(client)
        self.assertEqual(self.stored_image_id(), "2")

    def test_a_compromised_group_cover_gives_way_to_a_clean_release(self):
        obi = CoverArt(RELEASE_MBID, "obi", ("Front", "Obi"))
        clean = CoverArt("rel-1", "clean", ("Front",))
        client = self.build_client(front=obi, release_front=clean)
        with mock.patch.object(self.service, "_release_mbids", return_value=["rel-1"]):
            self.run_pass(client)
        self.assertEqual(self.stored_image_id(), "clean")

    def test_a_compromised_group_cover_is_kept_over_nothing_better(self):
        obi = CoverArt(RELEASE_MBID, "obi", ("Front", "Obi"))
        sticker = CoverArt("rel-1", "sticker", ("Front", "Sticker"))
        photo = CoverArt("rel-2", "photo", ("Front", "Back", "Medium"))
        client = self.build_client(front=obi)
        client.fetch_release_front_cover.side_effect = [sticker, photo, None]
        with mock.patch.object(
            self.service, "_release_mbids", return_value=["rel-1", "rel-2", "rel-3"]
        ):
            result = self.run_pass(client)
        self.assertEqual(result.processed, 1)
        self.assertEqual(self.stored_image_id(), "obi")

    def test_a_package_photo_is_better_than_no_cover(self):
        photo = CoverArt("rel-1", "photo", ("Front", "Back", "Medium"))
        obi = CoverArt("rel-2", "obi", ("Front", "Obi"))
        client = self.build_client(front=None)
        client.fetch_release_front_cover.side_effect = [photo, obi]
        with mock.patch.object(
            self.service, "_release_mbids", return_value=["rel-1", "rel-2"]
        ):
            self.run_pass(client)
        self.assertEqual(self.stored_image_id(), "obi")

    def test_only_the_first_few_releases_are_tried(self):
        client = self.build_client(front=None, release_front=None)
        many = [f"rel-{i}" for i in range(40)]
        with mock.patch.object(self.service, "_release_mbids", return_value=many):
            self.run_pass(client)
        self.assertLessEqual(client.fetch_release_front_cover.call_count, 12)

    def test_an_album_that_already_has_stored_art_is_skipped(self):
        self.run_pass(self.build_client(front=self.art))
        client = self.build_client(front=self.art)
        result = self.run_pass(client)
        self.assertEqual(result.skipped, 1)
        client.fetch_front_cover.assert_not_called()

    def test_known_ids_without_bytes_are_downloaded_without_a_listing_request(self):
        models.MusicBrainzAlbumData.objects.create(
            album=self.album,
            release_group_mbid=RG_MBID,
            cover_art_release_mbid=RELEASE_MBID,
            cover_art_image_id="123",
            cover_art_stored=False,
        )
        client = self.build_client(front=self.art)
        result = self.run_pass(client)
        self.assertEqual(result.processed, 1)
        client.fetch_front_cover.assert_not_called()
        self.assertEqual(models.AlbumCover.objects.count(), 2)

    def test_force_refetches_even_when_stored(self):
        self.run_pass(self.build_client(front=self.art))
        self.service.force = True
        client = self.build_client(front=self.art)
        self.run_pass(client)
        client.fetch_front_cover.assert_called_once()

    def test_existing_cover_rows_are_repointed_at_the_new_album(self):
        """An import replaces every Album row; the bytes outlive it."""
        models.AlbumCover.objects.create(
            release_mbid=RELEASE_MBID, image_id="123", size=250, data=b"x", album=None
        )
        models.AlbumCover.objects.create(
            release_mbid=RELEASE_MBID, image_id="123", size=500, data=b"x", album=None
        )
        client = self.build_client(front=self.art)
        self.run_pass(client)
        self.assertEqual(models.AlbumCover.objects.filter(album=self.album).count(), 2)
        client.get_bytes.assert_not_called()

    def test_an_orphaned_musicbrainz_record_is_adopted(self):
        models.AlbumCover.objects.create(
            release_mbid=RELEASE_MBID, image_id="123", size=250, data=b"x"
        )
        models.AlbumCover.objects.create(
            release_mbid=RELEASE_MBID, image_id="123", size=500, data=b"x"
        )
        models.MusicBrainzAlbumData.objects.create(
            album=None,
            release_group_mbid=RG_MBID,
            cover_art_release_mbid=RELEASE_MBID,
            cover_art_image_id="123",
        )
        client = self.build_client()
        result = self.run_pass(client)
        self.assertEqual(result.adopted, 1)
        client.fetch_front_cover.assert_not_called()
        record = self.album.musicbrainz_album_data_set.get()
        self.assertTrue(record.cover_art_stored)

    def test_an_orphan_is_adopted_whole_title_and_all(self):
        """Copying only the cover ids lost the rest, and MusicBrainz refetched."""
        for size in models.AlbumCover.SIZES:
            models.AlbumCover.objects.create(
                release_mbid=RELEASE_MBID, image_id="123", size=size, data=b"x"
            )
        orphan = models.MusicBrainzAlbumData.objects.create(
            album=None,
            release_group_mbid=RG_MBID,
            title="Abbey Road",
            all_genres="rock",
            cover_art_release_mbid=RELEASE_MBID,
            cover_art_image_id="123",
            cover_art_stored=True,
            is_primary=True,
        )
        client = self.build_client()

        result = self.run_pass(client)

        self.assertEqual(result.adopted, 1)
        self.assertEqual(result.skipped, 0)
        client.fetch_front_cover.assert_not_called()
        record = self.album.musicbrainz_album_data_set.get()
        self.assertEqual(record.pk, orphan.pk)
        self.assertEqual(record.title, "Abbey Road")
        self.assertEqual(record.all_genres, "rock")
        self.assertTrue(record.is_primary)
        self.album.refresh_from_db()
        self.assertEqual(self.album.primary_musicbrainz_album_data, record)
        self.assertIn(RELEASE_MBID, self.album.cover_image_url)
        self.assertEqual(
            models.AlbumCover.objects.filter(album=self.album).count(),
            len(models.AlbumCover.SIZES),
        )

    def test_a_row_without_art_borrows_an_orphans_cover(self):
        # The album's own row has no cover yet, but a stray row for the same
        # release group does: its ids are copied rather than refetched.
        models.MusicBrainzAlbumData.objects.create(
            album=self.album, release_group_mbid=RG_MBID, title="Abbey Road"
        )
        models.MusicBrainzAlbumData.objects.create(
            album=None,
            release_group_mbid=RG_MBID,
            cover_art_release_mbid=RELEASE_MBID,
            cover_art_image_id="123",
        )
        client = self.build_client()

        result = self.run_pass(client)

        self.assertEqual(result.adopted, 1)
        client.fetch_front_cover.assert_not_called()
        record = self.album.musicbrainz_album_data_set.get()
        self.assertEqual(record.title, "Abbey Road")
        self.assertEqual(record.cover_art_image_id, "123")
        self.assertFalse(
            models.MusicBrainzAlbumData.objects.filter(album__isnull=True).exists()
        )

    def test_an_orphan_with_no_art_is_not_adopted(self):
        models.MusicBrainzAlbumData.objects.create(
            album=None, release_group_mbid=RG_MBID, cover_art_image_id=""
        )
        result = self.run_pass(self.build_client(front=self.art))
        self.assertEqual(result.adopted, 0)
        self.assertEqual(result.processed, 1)

    def test_a_single_size_download_takes_the_serial_path(self):
        models.AlbumCover.objects.create(
            release_mbid=RELEASE_MBID, image_id="123", size=250, data=b"x"
        )
        client = self.build_client(front=self.art)
        result = self.run_pass(client)
        self.assertEqual(result.processed, 1)
        self.assertEqual(client.get_bytes.call_count, 1)

    def test_no_albums_is_a_no_op(self):
        self.assertEqual(self.service.run_covers([]).processed, 0)

    def test_the_musicbrainz_client_is_closed_when_the_pass_ends(self):
        client = self.build_client(front=None, release_front=None)
        mb_client = mock.MagicMock()
        mb_client.browse_release_mbids.return_value = []
        with mock.patch(
            "music.services.metadata_service.MusicBrainzClient", return_value=mb_client
        ):
            self.run_pass(client)
        mb_client.close.assert_called_once()


class DiscogsPassTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.album.discogs_master_id = 24047
        self.album.save()

    def build_client(self, master=None):
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_master.return_value = (
            master
            if master is not None
            else DiscogsMaster(
                master_id=24047,
                title="Abbey Road",
                year=1969,
                genres=["Rock"],
                styles=["Pop Rock", "Psychedelic Rock"],
            )
        )
        return client

    def run_pass(self, client, albums=None):
        with mock.patch(
            "music.services.metadata_service.DiscogsClient", return_value=client
        ):
            return self.service.run_discogs(albums or [self.album])

    def test_the_master_is_stored_verbatim(self):
        result = self.run_pass(self.build_client())
        self.assertEqual(result.processed, 1)
        record = self.album.discogs_album_data_set.get()
        self.assertEqual(record.genres, ["Rock"])
        self.assertEqual(record.styles, ["Pop Rock", "Psychedelic Rock"])
        self.assertEqual(record.main_release_year, 1969)
        self.assertTrue(record.is_primary)

    def test_the_pass_stores_styles_but_writes_no_genres(self):
        """Genres are derived afterwards, from every source, corpus-wide.

        The sources vote and rare leaves are pruned by count, so neither can
        be decided one album at a time; ``genre_rebuild`` does it once the
        passes have stored their data.
        """
        self.run_pass(self.build_client())
        self.assertEqual(self.album.genres.count(), 0)
        self.assertEqual(models.MusicGenre.objects.count(), 0)

    def test_an_album_with_no_master_id_is_reported(self):
        self.album.discogs_master_id = None
        self.album.save()
        result = self.service.run_discogs([self.album])
        self.assertIn("no Discogs master ID", result.errors[0])

    def test_a_master_discogs_does_not_have_is_reported(self):
        client = self.build_client()
        client.fetch_master.return_value = None
        result = self.run_pass(client)
        self.assertEqual(result.processed, 0)
        self.assertIn("not found", result.errors[0])

    def test_an_existing_record_is_reused_and_kept_primary(self):
        self.run_pass(self.build_client())
        self.album.primary_discogs_album_data = None
        self.album.save()
        client = self.build_client()
        result = self.run_pass(client)
        self.assertEqual(result.skipped, 1)
        client.fetch_master.assert_not_called()
        self.album.refresh_from_db()
        self.assertIsNotNone(self.album.primary_discogs_album_data)

    def test_an_orphaned_record_is_adopted_without_a_request(self):
        models.DiscogsAlbumData.objects.create(
            album=None, master_id=24047, genres=["Rock"], styles=["Punk"]
        )
        client = self.build_client()
        result = self.run_pass(client)
        self.assertEqual(result.adopted, 1)
        client.fetch_master.assert_not_called()
        self.assertEqual(self.album.discogs_album_data_set.get().styles, ["Punk"])

    def test_force_refetches(self):
        self.run_pass(self.build_client())
        self.service.force = True
        client = self.build_client()
        self.run_pass(client)
        client.fetch_master.assert_called_once()

    def test_no_albums_is_a_no_op(self):
        self.assertEqual(self.service.run_discogs([]).processed, 0)


class MusicBrainzPassTests(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.album.musicbrainz_release_group_id = RG_MBID
        self.album.save()

    def build_client(self, group=None):
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_release_group.return_value = (
            group
            if group is not None
            else ReleaseGroup(
                mbid=RG_MBID,
                title="Abbey Road",
                primary_type="Album",
                secondary_types=["Live"],
                first_release_date="1969-09-26",
                rating=4.5,
                rating_votes=120,
                genres=["rock", "pop rock"],
            )
        )
        return client

    def run_pass(self, client, albums=None):
        with mock.patch(
            "music.services.metadata_service.MusicBrainzClient", return_value=client
        ):
            return self.service.run_musicbrainz(albums or [self.album])

    def test_the_release_group_is_stored(self):
        result = self.run_pass(self.build_client())
        self.assertEqual(result.processed, 1)
        record = self.album.musicbrainz_album_data_set.get()
        self.assertEqual(record.title, "Abbey Road")
        self.assertEqual(record.primary_type, "Album")
        self.assertEqual(record.secondary_types, ["Live"])
        self.assertEqual(record.first_release_date, "1969-09-26")
        self.assertEqual(record.rating, 4.5)
        self.assertEqual(record.rating_votes, 120)
        self.assertEqual(record.all_genres, "rock, pop rock")
        self.assertTrue(record.is_primary)

    def test_a_partial_date_is_kept_as_text(self):
        group = ReleaseGroup(mbid=RG_MBID, title="X", first_release_date="1966")
        self.run_pass(self.build_client(group=group))
        self.assertEqual(
            self.album.musicbrainz_album_data_set.get().first_release_date, "1966"
        )

    def test_an_album_with_no_release_group_is_skipped(self):
        self.album.musicbrainz_release_group_id = None
        self.album.save()
        self.assertEqual(self.service.run_musicbrainz([self.album]).processed, 0)

    def test_a_missing_release_group_is_reported(self):
        client = self.build_client()
        client.fetch_release_group.return_value = None
        result = self.run_pass(client)
        self.assertIn("release group not found", result.errors[0])

    def test_an_album_already_enriched_is_skipped(self):
        self.run_pass(self.build_client())
        client = self.build_client()
        result = self.run_pass(client)
        self.assertEqual(result.skipped, 1)
        client.fetch_release_group.assert_not_called()

    def test_force_refetches(self):
        self.run_pass(self.build_client())
        self.service.force = True
        client = self.build_client()
        self.run_pass(client)
        client.fetch_release_group.assert_called_once()

    def test_an_orphan_with_a_title_is_adopted_without_a_request(self):
        orphan = models.MusicBrainzAlbumData.objects.create(
            album=None, release_group_mbid=RG_MBID, title="Abbey Road"
        )
        client = self.build_client()

        result = self.run_pass(client)

        self.assertEqual(result.adopted, 1)
        self.assertEqual(result.skipped, 0)
        client.fetch_release_group.assert_not_called()
        orphan.refresh_from_db()
        self.assertEqual(orphan.album, self.album)
        self.assertTrue(orphan.is_primary)
        self.album.refresh_from_db()
        self.assertEqual(self.album.primary_musicbrainz_album_data, orphan)

    def test_an_orphan_that_was_primary_displaces_the_albums_own(self):
        # The orphan was its old album's primary; adopting it as-is would
        # break the one-primary-per-album constraint against this one's.
        own = models.MusicBrainzAlbumData.objects.create(
            album=self.album, release_group_mbid="old-group", is_primary=True
        )
        orphan = models.MusicBrainzAlbumData.objects.create(
            album=None, release_group_mbid=RG_MBID, title="X", is_primary=True
        )

        self.run_pass(self.build_client())

        own.refresh_from_db()
        orphan.refresh_from_db()
        self.assertFalse(own.is_primary)
        self.assertTrue(orphan.is_primary)
        self.assertEqual(orphan.album, self.album)

    def test_the_fullest_of_several_orphans_is_adopted(self):
        models.MusicBrainzAlbumData.objects.create(
            album=None, release_group_mbid=RG_MBID, cover_art_image_id="1"
        )
        titled = models.MusicBrainzAlbumData.objects.create(
            album=None, release_group_mbid=RG_MBID, title="Abbey Road"
        )
        models.MusicBrainzAlbumData.objects.create(
            album=None, release_group_mbid=RG_MBID
        )

        self.run_pass(self.build_client())

        self.assertEqual(self.album.musicbrainz_album_data_set.get(), titled)

    def test_an_untitled_orphan_is_adopted_and_filled_in(self):
        orphan = models.MusicBrainzAlbumData.objects.create(
            album=None, release_group_mbid=RG_MBID
        )

        result = self.run_pass(self.build_client())

        self.assertEqual(result.processed, 1)
        record = self.album.musicbrainz_album_data_set.get()
        self.assertEqual(record.pk, orphan.pk)
        self.assertEqual(record.title, "Abbey Road")

    def test_force_refetches_into_the_adopted_row(self):
        orphan = models.MusicBrainzAlbumData.objects.create(
            album=None, release_group_mbid=RG_MBID, title="Old title"
        )
        self.service.force = True
        client = self.build_client()

        self.run_pass(client)

        client.fetch_release_group.assert_called_once()
        self.assertEqual(models.MusicBrainzAlbumData.objects.count(), 1)
        orphan.refresh_from_db()
        self.assertEqual(orphan.title, "Abbey Road")
        self.assertEqual(orphan.album, self.album)

    def test_genres_with_no_votes_yield_no_string(self):
        group = ReleaseGroup(mbid=RG_MBID, title="X", genres=[])
        self.run_pass(self.build_client(group=group))
        self.assertIsNone(self.album.musicbrainz_album_data_set.get().all_genres)

    def test_no_albums_is_a_no_op(self):
        self.assertEqual(self.service.run_musicbrainz([]).processed, 0)


class StaleMusicBrainzRefreshTests(ServiceTestCase):
    """``refresh_stale`` re-fetches the oldest enriched rows, a slice a run."""

    def setUp(self):
        super().setUp()
        self.albums = [self.album]
        for rank in (3, 4):
            self.albums.append(
                models.Album.objects.create(name=f"Album {rank}", rank=rank)
            )
        self.records = []
        for offset, album in enumerate(self.albums):
            album.musicbrainz_release_group_id = f"rg-{album.pk}"
            album.save()
            record = models.MusicBrainzAlbumData.objects.create(
                album=album,
                release_group_mbid=album.musicbrainz_release_group_id,
                title="Old title",
                is_primary=True,
            )
            # Oldest first: the first album's row is the stalest.
            models.MusicBrainzAlbumData.objects.filter(pk=record.pk).update(
                updated_at=datetime(2026, 1, 1 + offset)
            )
            self.records.append(record)

    def run_pass(self, **options):
        service = AlbumMetadataService(**options)
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.fetch_release_group.side_effect = lambda mbid: ReleaseGroup(
            mbid=mbid, title="New title"
        )
        with mock.patch(
            "music.services.metadata_service.MusicBrainzClient", return_value=client
        ):
            return service.run_musicbrainz(self.albums), client

    def titles(self):
        return [
            models.MusicBrainzAlbumData.objects.get(pk=r.pk).title for r in self.records
        ]

    def test_the_oldest_rows_are_refetched(self):
        result, client = self.run_pass(refresh_stale=2)
        self.assertEqual(result.refreshed, 2)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.processed, 0)
        self.assertEqual(client.fetch_release_group.call_count, 2)
        self.assertEqual(self.titles(), ["New title", "New title", "Old title"])
        self.assertIn("2 refreshed", result.summary())

    def test_a_refresh_moves_the_slice_on(self):
        self.run_pass(refresh_stale=2)
        result, client = self.run_pass(refresh_stale=1)
        client.fetch_release_group.assert_called_once_with(
            self.albums[2].musicbrainz_release_group_id
        )
        self.assertEqual(self.titles(), ["New title"] * 3)

    def test_nothing_is_refreshed_by_default(self):
        result, client = self.run_pass()
        self.assertEqual(result.skipped, 3)
        client.fetch_release_group.assert_not_called()

    def test_force_counts_everything_as_processed(self):
        result, _ = self.run_pass(force=True, refresh_stale=1)
        self.assertEqual(result.processed, 3)
        self.assertEqual(result.refreshed, 0)

    def test_a_row_never_enriched_is_fetched_as_usual(self):
        models.MusicBrainzAlbumData.objects.filter(pk=self.records[0].pk).update(
            title=""
        )
        result, _ = self.run_pass(refresh_stale=1)
        # The untitled row is fetched on its own account; the slice goes to
        # the oldest of the enriched ones.
        self.assertEqual(result.processed, 1)
        self.assertEqual(result.refreshed, 1)
        self.assertEqual(self.titles(), ["New title", "New title", "Old title"])


class PrimaryRecordTests(ServiceTestCase):
    def test_a_previous_primary_is_demoted(self):
        first = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q1", is_primary=True
        )
        second = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q2"
        )
        self.service._set_primary(self.album, second, "primary_wikipedia_album_data")
        first.refresh_from_db()
        second.refresh_from_db()
        self.album.refresh_from_db()
        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)
        self.assertEqual(self.album.primary_wikipedia_album_data, second)

    def test_a_record_already_primary_is_left_alone(self):
        record = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q1", is_primary=True
        )
        self.service._set_primary(self.album, record, "primary_wikipedia_album_data")
        record.refresh_from_db()
        self.assertTrue(record.is_primary)


class WikipediaDuplicateCollapseTests(ServiceTestCase):
    def test_duplicate_rows_are_collapsed_to_one(self):
        first = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q173643", page_title="A"
        )
        second = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q173643", page_title="B", is_primary=True
        )
        kept = models.WikipediaAlbumData.collapse_duplicates(self.album, "Q173643")
        self.assertEqual(kept, second)
        self.assertFalse(models.WikipediaAlbumData.objects.filter(pk=first.pk).exists())

    def test_the_albums_pointer_is_moved_before_the_delete(self):
        doomed = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q173643", page_title="A"
        )
        survivor = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q173643", page_title="B", is_primary=True
        )
        self.album.primary_wikipedia_album_data = doomed
        self.album.save()

        kept = models.WikipediaAlbumData.collapse_duplicates(self.album, "Q173643")
        self.album.refresh_from_db()
        self.assertEqual(kept, survivor)
        self.assertEqual(self.album.primary_wikipedia_album_data, survivor)

    def test_with_no_primary_the_oldest_row_survives(self):
        first = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q173643", page_title="A"
        )
        models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q173643", page_title="B"
        )
        self.assertEqual(
            models.WikipediaAlbumData.collapse_duplicates(self.album, "Q173643"),
            first,
        )

    def test_nothing_to_collapse_returns_none(self):
        self.assertIsNone(
            models.WikipediaAlbumData.collapse_duplicates(self.album, "Q173643")
        )

    def test_a_single_row_is_returned_untouched(self):
        only = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q173643"
        )
        self.assertEqual(
            models.WikipediaAlbumData.collapse_duplicates(self.album, "Q173643"),
            only,
        )


class PartialCoverDownloadTests(ServiceTestCase):
    """A cover that only half downloads is not treated as stored."""

    def setUp(self):
        super().setUp()
        self.album.musicbrainz_release_group_id = RG_MBID
        self.album.save()
        self.art = CoverArt(release_mbid=RELEASE_MBID, image_id="123")

    def test_one_size_failing_leaves_the_album_on_the_remote_url(self):
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_front_cover.return_value = self.art
        # Verification download succeeds, then one of the two sizes fails.
        client.get_bytes.side_effect = [
            (b"img", "image/jpeg"),
            (b"img", "image/jpeg"),
            None,
        ]
        with mock.patch(
            "music.services.metadata_service.CoverArtArchiveClient",
            return_value=client,
        ):
            result = self.service.run_covers([self.album])

        self.assertEqual(result.processed, 1)
        self.assertIn("would not download", result.errors[0])
        record = self.album.musicbrainz_album_data_set.get()
        self.assertFalse(record.cover_art_stored)
        album = models.Album.objects.get(pk=self.album.pk)
        self.assertIn("coverartarchive.org", album.thumbnail)

    def test_known_ids_whose_bytes_fail_fall_through_to_resolution(self):
        models.MusicBrainzAlbumData.objects.create(
            album=self.album,
            release_group_mbid=RG_MBID,
            cover_art_release_mbid=RELEASE_MBID,
            cover_art_image_id="123",
            cover_art_stored=False,
        )
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_front_cover.return_value = None
        client.get_bytes.return_value = None
        with mock.patch(
            "music.services.metadata_service.CoverArtArchiveClient",
            return_value=client,
        ):
            with mock.patch.object(self.service, "_release_mbids", return_value=[]):
                result = self.service.run_covers([self.album])
        # The bytes-only path failed, so it went on to re-resolve the art.
        client.fetch_front_cover.assert_called_once()
        self.assertEqual(result.processed, 0)


class MusicBrainzGenreTests(ServiceTestCase):
    """The MusicBrainz pass stores its genres as a vote, not as genres.

    It used to fill an album's genres directly where Discogs had supplied
    none. Now every source votes in ``genre_rebuild``, which covers that
    case - an album whose only data is MusicBrainz's is trusted outright.
    """

    def setUp(self):
        super().setUp()
        self.album.musicbrainz_release_group_id = RG_MBID
        self.album.save()

    def run_pass(self, genres):
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_release_group.return_value = ReleaseGroup(
            mbid=RG_MBID, title="X", genres=genres
        )
        with mock.patch(
            "music.services.metadata_service.MusicBrainzClient", return_value=client
        ):
            return self.service.run_musicbrainz([self.album])

    def test_genres_are_stored_in_vote_order(self):
        self.run_pass(["soul", "southern soul", "r&b"])
        record = self.album.musicbrainz_album_data_set.get()
        self.assertEqual(record.all_genres, "soul, southern soul, r&b")

    def test_the_pass_writes_no_genres(self):
        self.run_pass(["soul", "southern soul"])
        self.assertEqual(self.album.genres.count(), 0)


class ExternalTextLengthTests(ServiceTestCase):
    """External text must be cut to fit its column before it is saved.

    SQLite ignores varchar length, so an over-long value stores fine in the
    test and dev databases and the whole pipeline looks healthy, then
    PostgreSQL raises DataError in production. That is not hypothetical: a
    clean local run was followed by the Heroku run aborting at album 451 of
    497 on Fiona Apple's "When the Pawn...", whose real title is 444
    characters. These tests assert the lengths directly rather than relying
    on the database to complain.
    """

    LONG = "When the Pawn Hits the Conflicts He Thinks like a King " * 12

    def test_fit_leaves_a_short_value_alone(self):
        self.assertEqual(fit(models.DiscogsAlbumData, "title", "Kid A"), "Kid A")

    def test_fit_passes_none_through(self):
        self.assertIsNone(fit(models.DiscogsAlbumData, "title", None))

    def test_fit_truncates_to_the_column_width(self):
        value = fit(models.DiscogsAlbumData, "title", self.LONG)
        self.assertEqual(len(value), 300)
        self.assertTrue(self.LONG.startswith(value))

    def test_fit_leaves_an_unbounded_field_alone(self):
        self.assertEqual(
            fit(models.MusicBrainzAlbumData, "all_genres", self.LONG), self.LONG
        )

    def test_a_long_discogs_title_is_stored_truncated(self):
        self.album.discogs_master_id = 24047
        self.album.save()
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_master.return_value = DiscogsMaster(
            master_id=24047, title=self.LONG, genres=["Rock"], styles=["Pop Rock"]
        )
        with mock.patch(
            "music.services.metadata_service.DiscogsClient", return_value=client
        ):
            self.service.run_discogs([self.album])

        record = self.album.discogs_album_data_set.get()
        self.assertEqual(
            len(record.title),
            models.DiscogsAlbumData._meta.get_field("title").max_length,
        )

    def test_a_long_musicbrainz_title_is_stored_truncated(self):
        self.album.musicbrainz_release_group_id = RG_MBID
        self.album.save()
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_release_group.return_value = ReleaseGroup(
            mbid=RG_MBID, title=self.LONG, primary_type="Album"
        )
        with mock.patch(
            "music.services.metadata_service.MusicBrainzClient", return_value=client
        ):
            self.service.run_musicbrainz([self.album])

        record = self.album.musicbrainz_album_data_set.get()
        self.assertEqual(
            len(record.title),
            models.MusicBrainzAlbumData._meta.get_field("title").max_length,
        )

    def test_long_wikidata_text_is_stored_truncated(self):
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_album_metadata.return_value = {
            "Q173643": self.album_meta(page_title=self.LONG, spotify_album_id="x" * 80)
        }
        client.fetch_artists.return_value = {}
        client.fetch_labels.return_value = {"Q213710": self.LONG}
        with mock.patch(
            "music.services.metadata_service.WikidataClient", return_value=client
        ):
            self.service.run_wikidata([self.album])

        record = self.album.wikipedia_album_data_set.get()
        model = models.WikipediaAlbumData
        for field in ("page_title", "record_label", "spotify_album_id"):
            with self.subTest(field=field):
                self.assertLessEqual(
                    len(getattr(record, field)),
                    model._meta.get_field(field).max_length,
                )

    def test_every_stored_value_fits_its_column_after_a_full_pass(self):
        """A sweep, so a newly added field cannot quietly reintroduce this."""
        self.album.discogs_master_id = 24047
        self.album.save()
        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.fetch_master.return_value = DiscogsMaster(
            master_id=24047,
            title=self.LONG,
            genres=["Rock"],
            styles=[self.LONG, "Pop Rock"],
        )
        with mock.patch(
            "music.services.metadata_service.DiscogsClient", return_value=client
        ):
            self.service.run_discogs([self.album])

        for model in (
            models.DiscogsAlbumData,
            models.MusicGenre,
            models.Album,
            models.Artist,
        ):
            for record in model.objects.all():
                for field in model._meta.get_fields():
                    max_length = getattr(field, "max_length", None)
                    if not max_length or not hasattr(record, field.name):
                        continue
                    value = getattr(record, field.name)
                    if isinstance(value, str):
                        with self.subTest(model=model.__name__, field=field.name):
                            self.assertLessEqual(len(value), max_length)

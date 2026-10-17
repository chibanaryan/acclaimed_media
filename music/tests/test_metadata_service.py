"""Tests for the album metadata orchestration service.

Every client is mocked: these tests are about what gets written to the
database and in what order, not about HTTP.
"""

from datetime import date
from unittest import mock

from django.test import SimpleTestCase, TestCase

from music import models
from music.musicbrainz import CoverArt, ReleaseGroup
from music.discogs import DiscogsMaster
from music.services.metadata_service import (
    AlbumMetadataService,
    PassResult,
    normalize_artist_name,
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
        self.assertEqual(self.service._album_qids(self.album), ["Q173643", "Q999"])

    def test_duplicates_are_removed(self):
        self.album.all_wikidata_ids = ["Q173643", "Q173643"]
        self.assertEqual(self.service._album_qids(self.album), ["Q173643"])

    def test_blank_entries_are_ignored(self):
        self.album.all_wikidata_ids = ["", None, "Q2"]
        self.assertEqual(self.service._album_qids(self.album), ["Q173643", "Q2"])

    def test_an_album_with_no_primary_id_still_offers_the_others(self):
        self.album.wikidata_id = None
        self.album.all_wikidata_ids = ["Q2"]
        self.assertEqual(self.service._album_qids(self.album), ["Q2"])


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

    def test_artists_come_from_both_the_credit_and_p175(self):
        self.run_pass(
            artists={
                "Q1299": ArtistMetadata(
                    wikidata_id="Q1299", name="The Beatles", musicbrainz_id="b10"
                )
            }
        )
        names = sorted(a.name for a in self.album.artists.all())
        self.assertEqual(names, ["The Beatles"])
        artist = self.album.artists.get()
        self.assertEqual(artist.wikidata_id, "Q1299")
        self.assertEqual(artist.musicbrainz_id, "b10")

    def test_a_credit_p175_disagrees_with_keeps_both(self):
        """Band on the Run is credited to McCartney and Wings; P175 says Wings."""
        self.album.artist_credit = "Paul McCartney, Wings"
        self.album.save()
        self.run_pass(
            metadata={"Q173643": self.album_meta(performer_qids=["Q622988"])},
            artists={"Q622988": ArtistMetadata(wikidata_id="Q622988", name="Wings")},
        )
        self.assertEqual(
            sorted(a.name for a in self.album.artists.all()),
            ["Paul McCartney", "Wings"],
        )

    def test_a_punctuation_variant_reuses_the_existing_artist(self):
        self.album.artist_credit = "Bob Marley and the Wailers"
        self.album.save()
        self.run_pass(
            metadata={"Q173643": self.album_meta(performer_qids=["Q2525354"])},
            artists={
                "Q2525354": ArtistMetadata(
                    wikidata_id="Q2525354", name="Bob Marley & The Wailers"
                )
            },
        )
        self.assertEqual(self.album.artists.count(), 1)
        artist = self.album.artists.get()
        self.assertEqual(artist.name, "Bob Marley and the Wailers")
        self.assertEqual(artist.wikidata_id, "Q2525354")

    def test_an_artist_matched_by_qid_is_reused(self):
        existing = models.Artist.objects.create(
            name="Renamed", slug="renamed", wikidata_id="Q1299"
        )
        self.album.artist_credit = ""
        self.album.save()
        self.run_pass()
        self.assertEqual(list(self.album.artists.all()), [existing])

    def test_unresolved_performers_are_skipped(self):
        self.run_pass(artists={})
        self.assertEqual([a.name for a in self.album.artists.all()], ["The Beatles"])

    def test_an_album_with_no_credit_and_no_performers_keeps_its_artists(self):
        self.album.artist_credit = ""
        self.album.save()
        self.run_pass(
            metadata={"Q173643": self.album_meta(performer_qids=[])}, artists={}
        )
        self.assertEqual(self.album.artists.count(), 0)

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

    def test_styles_become_genres_with_their_root(self):
        self.run_pass(self.build_client())
        self.assertEqual(
            sorted(g.name for g in self.album.genres.all()),
            ["Pop Rock", "Psychedelic Rock", "Rock"],
        )

    def test_an_album_with_no_styles_still_gets_a_root_genre(self):
        master = DiscogsMaster(master_id=24047, genres=["Jazz"], styles=[])
        self.run_pass(self.build_client(master=master))
        self.assertEqual([g.name for g in self.album.genres.all()], ["Jazz"])

    def test_an_album_with_neither_styles_nor_known_genres_gets_none(self):
        master = DiscogsMaster(master_id=24047, genres=["Non-Music"], styles=[])
        self.run_pass(self.build_client(master=master))
        self.assertEqual(self.album.genres.count(), 0)

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

    def test_an_existing_record_is_reused_and_its_genres_reapplied(self):
        self.run_pass(self.build_client())
        self.album.genres.clear()
        client = self.build_client()
        result = self.run_pass(client)
        self.assertEqual(result.skipped, 1)
        client.fetch_master.assert_not_called()
        self.assertEqual(self.album.genres.count(), 3)

    def test_an_orphaned_record_is_adopted_without_a_request(self):
        models.DiscogsAlbumData.objects.create(
            album=None, master_id=24047, genres=["Rock"], styles=["Punk"]
        )
        client = self.build_client()
        result = self.run_pass(client)
        self.assertEqual(result.adopted, 1)
        client.fetch_master.assert_not_called()
        self.assertEqual(sorted(g.name for g in self.album.genres.all()), ["Punk"])

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

    def test_genres_with_no_votes_yield_no_string(self):
        group = ReleaseGroup(mbid=RG_MBID, title="X", genres=[])
        self.run_pass(self.build_client(group=group))
        self.assertIsNone(self.album.musicbrainz_album_data_set.get().all_genres)

    def test_no_albums_is_a_no_op(self):
        self.assertEqual(self.service.run_musicbrainz([]).processed, 0)


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


class ArtistNormalizedMatchTests(ServiceTestCase):
    def test_a_blank_name_matches_nothing(self):
        self.assertIsNone(self.service._find_artist_by_normalized_name(""))

    def test_a_name_with_no_counterpart_matches_nothing(self):
        models.Artist.objects.create(name="Someone Else", slug="someone-else")
        self.assertIsNone(self.service._find_artist_by_normalized_name("Nobody Here"))

    def test_a_subsidiary_is_not_matched(self):
        """Only root creators carry the canonical name."""
        parent = models.Artist.objects.create(name="Neil Young", slug="neil-young")
        models.Artist.objects.create(name="Crazy Horse", parent=parent)
        self.assertIsNone(self.service._find_artist_by_normalized_name("Crazy Horse"))


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

"""Tests for the music models."""

from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.db.utils import IntegrityError
from django.test import TestCase

from core import constants as core_constants
from core.models import User
from music import models


class ArtistTests(TestCase):
    def setUp(self):
        self.parent = models.Artist.objects.create(name="Neil Young", slug="neil-young")

    def test_str_is_name_for_root_artist(self):
        self.assertEqual(str(self.parent), "Neil Young")

    def test_str_includes_parent_for_subsidiary(self):
        child = models.Artist.objects.create(name="Crazy Horse", parent=self.parent)
        self.assertEqual(str(child), "Crazy Horse (Neil Young)")

    def test_subsidiary_slug_is_cleared_on_save(self):
        child = models.Artist.objects.create(
            name="Crazy Horse", slug="crazy-horse", parent=self.parent
        )
        child.refresh_from_db()
        self.assertEqual(child.slug, "")

    def test_is_root_and_is_subsidiary(self):
        child = models.Artist.objects.create(name="Crazy Horse", parent=self.parent)
        self.assertTrue(self.parent.is_root)
        self.assertFalse(self.parent.is_subsidiary)
        self.assertFalse(child.is_root)
        self.assertTrue(child.is_subsidiary)

    def test_root_creator_walks_the_hierarchy(self):
        child = models.Artist.objects.create(name="Crazy Horse", parent=self.parent)
        grandchild = models.Artist.objects.create(name="Side Act", parent=child)
        self.assertEqual(grandchild.root_creator, self.parent)

    def test_get_all_subsidiary_ids(self):
        child = models.Artist.objects.create(name="Crazy Horse", parent=self.parent)
        self.assertEqual(self.parent.get_all_subsidiary_ids(), [child.id])
        self.assertEqual(
            sorted(self.parent.get_all_subsidiary_ids(include_self=True)),
            sorted([self.parent.id, child.id]),
        )

    def test_get_all_subsidiaries(self):
        child = models.Artist.objects.create(name="Crazy Horse", parent=self.parent)
        self.assertEqual(self.parent.get_all_subsidiaries(), [child])
        self.assertEqual(
            self.parent.get_all_subsidiaries(include_self=True), [self.parent, child]
        )

    def test_get_absolute_url(self):
        self.assertEqual(self.parent.get_absolute_url(), "/music/artists/neil-young/")


class MusicGenreTests(TestCase):
    def test_root_genre_gets_slug_level_and_path(self):
        rock = models.MusicGenre.objects.create(name="Rock")
        self.assertEqual(rock.slug, "rock")
        self.assertEqual(rock.level, 0)
        self.assertEqual(rock.path, "Rock")

    def test_child_genre_inherits_level_and_path(self):
        rock = models.MusicGenre.objects.create(name="Rock")
        punk = models.MusicGenre.objects.create(name="Punk Rock", parent=rock)
        post = models.MusicGenre.objects.create(name="Post-Punk", parent=punk)
        self.assertEqual(punk.level, 1)
        self.assertEqual(punk.path, "Rock > Punk Rock")
        self.assertEqual(post.level, 2)
        self.assertEqual(post.path, "Rock > Punk Rock > Post-Punk")

    def test_explicit_slug_is_kept(self):
        genre = models.MusicGenre.objects.create(name="R&B", slug="rhythm-and-blues")
        self.assertEqual(genre.slug, "rhythm-and-blues")

    def test_str_uses_path(self):
        rock = models.MusicGenre.objects.create(name="Rock")
        punk = models.MusicGenre.objects.create(name="Punk Rock", parent=rock)
        self.assertEqual(str(punk), "Rock > Punk Rock")

    def test_str_falls_back_to_name_when_path_is_blank(self):
        genre = models.MusicGenre(name="Unsaved")
        self.assertEqual(str(genre), "Unsaved")

    def test_is_root_and_is_leaf(self):
        rock = models.MusicGenre.objects.create(name="Rock")
        punk = models.MusicGenre.objects.create(name="Punk Rock", parent=rock)
        self.assertTrue(rock.is_root)
        self.assertFalse(rock.is_leaf)
        self.assertFalse(punk.is_root)
        self.assertTrue(punk.is_leaf)

    def test_get_descendants_and_ids(self):
        rock = models.MusicGenre.objects.create(name="Rock")
        punk = models.MusicGenre.objects.create(name="Punk Rock", parent=rock)
        post = models.MusicGenre.objects.create(name="Post-Punk", parent=punk)
        self.assertEqual(rock.get_descendants(), [punk, post])
        self.assertEqual(rock.get_descendants(include_self=True), [rock, punk, post])
        self.assertEqual(rock.get_descendant_ids(), [punk.id, post.id])
        self.assertEqual(
            rock.get_descendant_ids(include_self=True), [rock.id, punk.id, post.id]
        )

    def test_moving_a_genre_recomputes_level_and_path(self):
        rock = models.MusicGenre.objects.create(name="Rock")
        punk = models.MusicGenre.objects.create(name="Punk Rock", parent=rock)
        punk.parent = None
        punk.save()
        punk.refresh_from_db()
        self.assertEqual(punk.level, 0)
        self.assertEqual(punk.path, "Punk Rock")


class AlbumTests(TestCase):
    def setUp(self):
        self.album = models.Album.objects.create(
            name="Pet Sounds",
            rank=1,
            artist_credit="The Beach Boys",
            year_released=1966,
        )

    def test_slug_is_generated_from_the_name(self):
        self.assertEqual(self.album.slug, "pet-sounds")

    def test_name_normalized_is_set_for_non_ascii_names(self):
        album = models.Album.objects.create(
            name="Déjà Vu", rank=2, artist_credit="Crosby, Stills & Nash"
        )
        self.assertEqual(album.name_normalized, "Deja Vu")

    def test_name_normalized_is_left_unset_for_ascii_names(self):
        self.assertIsNone(self.album.name_normalized)

    def test_slug_collision_disambiguates_with_the_artist(self):
        other = models.Album.objects.create(
            name="Pet Sounds", rank=2, artist_credit="Another Act"
        )
        self.assertEqual(other.slug, "pet-sounds-another-act")

    def test_slug_collision_falls_back_to_a_numeric_suffix(self):
        # Same title and same credit, so the artist-qualified slug collides too.
        second = models.Album.objects.create(
            name="Pet Sounds", rank=2, artist_credit="The Beach Boys"
        )
        third = models.Album.objects.create(
            name="Pet Sounds", rank=3, artist_credit="The Beach Boys"
        )
        self.assertEqual(second.slug, "pet-sounds-the-beach-boys")
        self.assertEqual(third.slug, "pet-sounds-2")

    def test_slug_counter_keeps_climbing_past_the_first_numeric_suffix(self):
        # Four albums sharing a title and a credit: base, artist-qualified,
        # then -2, then -3.
        slugs = [self.album.slug]
        for rank in (2, 3, 4):
            album = models.Album.objects.create(
                name="Pet Sounds", rank=rank, artist_credit="The Beach Boys"
            )
            slugs.append(album.slug)
        self.assertEqual(
            slugs,
            [
                "pet-sounds",
                "pet-sounds-the-beach-boys",
                "pet-sounds-2",
                "pet-sounds-3",
            ],
        )

    def test_slug_is_regenerated_for_a_saved_album_whose_slug_was_cleared(self):
        self.album.slug = None
        self.album.save()
        self.album.refresh_from_db()
        # It may reclaim its own slug: the uniqueness check excludes itself.
        self.assertEqual(self.album.slug, "pet-sounds")

    def test_slug_falls_back_when_the_name_has_no_slug_characters(self):
        album = models.Album.objects.create(name="!!!", rank=9, artist_credit="")
        self.assertEqual(album.slug, "album")

    def test_explicit_slug_is_kept(self):
        album = models.Album.objects.create(
            name="Kid A", rank=4, slug="kid-a-custom", artist_credit="Radiohead"
        )
        self.assertEqual(album.slug, "kid-a-custom")

    def test_resaving_keeps_the_existing_slug(self):
        self.album.rank = 7
        self.album.save()
        self.album.refresh_from_db()
        self.assertEqual(self.album.slug, "pet-sounds")
        self.assertEqual(self.album.rank, 7)

    def test_decade(self):
        self.assertEqual(self.album.decade, 1960)

    def test_decade_is_none_without_a_release_year(self):
        album = models.Album.objects.create(name="Undated", rank=5)
        self.assertIsNone(album.decade)

    def test_year_alias_matches_year_released(self):
        self.assertEqual(self.album.year, 1966)

    def test_thumbnail_and_image_follow_the_cover_url(self):
        album = models.Album.objects.create(
            name="With Cover",
            rank=6,
            cover_image_url="https://example.com/cover.jpg",
        )
        self.assertEqual(album.thumbnail, "https://example.com/cover.jpg")
        self.assertEqual(album.image, "https://example.com/cover.jpg")

    def test_get_absolute_url(self):
        self.assertEqual(self.album.get_absolute_url(), "/music/pet-sounds/")

    def test_str_is_the_name(self):
        self.assertEqual(str(self.album), "Pet Sounds")

    def test_get_display_artists_drops_a_parent_of_another_credited_artist(self):
        young = models.Artist.objects.create(name="Neil Young", slug="neil-young")
        horse = models.Artist.objects.create(name="Crazy Horse", parent=young)
        album = models.Album.objects.create(
            name="Rust Never Sleeps", rank=10, artist_credit="Neil Young, Crazy Horse"
        )
        album.artists.set([young, horse])
        self.assertEqual(album.get_display_artists(), [horse])

    def test_get_display_artists_keeps_unrelated_artists(self):
        eno = models.Artist.objects.create(name="Brian Eno", slug="brian-eno")
        byrne = models.Artist.objects.create(name="David Byrne", slug="david-byrne")
        album = models.Album.objects.create(name="My Life", rank=11)
        album.artists.set([eno, byrne])
        self.assertCountEqual(album.get_display_artists(), [eno, byrne])

    def test_get_display_artists_respects_max_count(self):
        eno = models.Artist.objects.create(name="Brian Eno", slug="brian-eno")
        byrne = models.Artist.objects.create(name="David Byrne", slug="david-byrne")
        album = models.Album.objects.create(name="My Life", rank=12)
        album.artists.set([eno, byrne])
        self.assertEqual(len(album.get_display_artists(max_count=1)), 1)

    def test_default_ordering_is_by_rank(self):
        models.Album.objects.create(name="Second", rank=20)
        models.Album.objects.create(name="Third", rank=30)
        self.assertEqual([a.rank for a in models.Album.objects.all()], [1, 20, 30])


class AlbumQuerySetTests(TestCase):
    def setUp(self):
        self.artist = models.Artist.objects.create(name="Radiohead", slug="radiohead")
        self.genre = models.MusicGenre.objects.create(name="Rock")
        self.album = models.Album.objects.create(
            name="Kid A", rank=1, artist_credit="Radiohead", year_released=2000
        )
        self.album.artists.set([self.artist])
        self.album.genres.set([self.genre])

        publication = models.MusicPublication.objects.create(name="Pitchfork")
        for index in range(2):
            source = models.MusicList.objects.create(
                name=f"List {index}",
                year=2000 + index,
                publisher=publication,
                order=index + 1,
                type=core_constants.LIST_ALLTIME,
            )
            models.AlbumListMembership.objects.create(
                list=source, album=self.album, rank=index + 1
            )

    def test_with_list_count_annotates_distinct_memberships(self):
        album = models.Album.objects.with_list_count().get(pk=self.album.pk)
        self.assertEqual(album.list_count, 2)

    def test_with_relations_prefetches_artists_and_genres(self):
        with self.assertNumQueries(3):
            album = models.Album.objects.with_relations().get(pk=self.album.pk)
            self.assertEqual([a.name for a in album.artists.all()], ["Radiohead"])
            self.assertEqual([g.name for g in album.genres.all()], ["Rock"])


class MusicPublicationTests(TestCase):
    def test_slug_is_generated_from_the_name(self):
        publication = models.MusicPublication.objects.create(name="Rolling Stone")
        self.assertEqual(publication.slug, "rolling-stone")

    def test_str_is_the_name(self):
        publication = models.MusicPublication.objects.create(name="Mojo")
        self.assertEqual(str(publication), "Mojo")

    def test_reputation_score_defaults_to_none(self):
        publication = models.MusicPublication.objects.create(name="Uncut")
        self.assertIsNone(publication.reputation_score)


class MusicListTests(TestCase):
    def setUp(self):
        self.publication = models.MusicPublication.objects.create(name="NME")

    def test_str_is_the_name(self):
        source = models.MusicList.objects.create(
            name="The 500 Greatest Albums", year=2013, publisher=self.publication
        )
        self.assertEqual(str(source), "The 500 Greatest Albums")

    def test_type_defaults_to_end_of_year(self):
        source = models.MusicList.objects.create(name="Any", year=2020)
        self.assertEqual(source.type, core_constants.LIST_EOY)

    def test_get_type_label(self):
        source = models.MusicList.objects.create(
            name="Any", year=2020, type=core_constants.LIST_ALLTIME
        )
        self.assertEqual(source.get_type_label(), "All time")

    def test_publisher_name_and_year_are_unique_together(self):
        models.MusicList.objects.create(
            name="Same", year=2013, publisher=self.publication
        )
        with self.assertRaises(IntegrityError):
            models.MusicList.objects.create(
                name="Same", year=2013, publisher=self.publication
            )


class AlbumListMembershipTests(TestCase):
    def setUp(self):
        self.album = models.Album.objects.create(name="Kid A", rank=1)
        self.publication = models.MusicPublication.objects.create(name="Pitchfork")
        self.source = models.MusicList.objects.create(
            name="Best of 2000", year=2000, publisher=self.publication, order=1
        )

    def test_str_names_the_list_album_and_rank(self):
        membership = models.AlbumListMembership.objects.create(
            list=self.source, album=self.album, rank=3
        )
        self.assertEqual(str(membership), "Best of 2000 - Kid A - 3")

    def test_an_album_cannot_appear_twice_on_one_list(self):
        models.AlbumListMembership.objects.create(
            list=self.source, album=self.album, rank=1
        )
        with self.assertRaises(IntegrityError):
            models.AlbumListMembership.objects.create(
                list=self.source, album=self.album, rank=2
            )

    def test_rank_may_be_null(self):
        membership = models.AlbumListMembership.objects.create(
            list=self.source, album=self.album
        )
        self.assertIsNone(membership.rank)


class ExternalDataModelTests(TestCase):
    """The fetched-metadata records and their derived URLs."""

    def setUp(self):
        self.album = models.Album.objects.create(
            name="Abbey Road", rank=2, wikidata_id="Q173643"
        )

    def test_wikipedia_data_str_names_its_album(self):
        record = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q173643"
        )
        self.assertEqual(str(record), "Wikipedia data for Abbey Road")

    def test_an_orphaned_wikipedia_record_says_so(self):
        record = models.WikipediaAlbumData.objects.create(wikidata_id="Q1")
        self.assertEqual(str(record), "Orphaned Wikipedia data (Wikidata: Q1)")

    def test_an_orphaned_record_with_no_id_still_has_a_str(self):
        record = models.WikipediaAlbumData.objects.create()
        self.assertEqual(str(record), "Orphaned Wikipedia data (Wikidata: unknown)")

    def test_the_wikipedia_url_is_built_from_the_page_title(self):
        record = models.WikipediaAlbumData.objects.create(
            album=self.album, page_title="What's Going On (album)"
        )
        self.assertEqual(
            record.wikipedia_url,
            "https://en.wikipedia.org/wiki/What's_Going_On_(album)",
        )

    def test_no_page_title_means_no_wikipedia_url(self):
        record = models.WikipediaAlbumData.objects.create(album=self.album)
        self.assertIsNone(record.wikipedia_url)

    def test_discogs_data_str_and_url(self):
        record = models.DiscogsAlbumData.objects.create(
            album=self.album, master_id=24047
        )
        self.assertEqual(str(record), "Discogs data for Abbey Road")
        self.assertEqual(record.discogs_url, "https://www.discogs.com/master/24047")

    def test_an_orphaned_discogs_record_says_so(self):
        record = models.DiscogsAlbumData.objects.create(master_id=24047)
        self.assertEqual(str(record), "Orphaned Discogs data (master: 24047)")

    def test_musicbrainz_data_str_and_url(self):
        record = models.MusicBrainzAlbumData.objects.create(
            album=self.album, release_group_mbid="rg-1"
        )
        self.assertEqual(str(record), "MusicBrainz data for Abbey Road")
        self.assertEqual(
            record.release_group_url, "https://musicbrainz.org/release-group/rg-1"
        )

    def test_an_orphaned_musicbrainz_record_says_so(self):
        record = models.MusicBrainzAlbumData.objects.create(release_group_mbid="rg-1")
        self.assertEqual(str(record), "Orphaned MusicBrainz data (rg-1)")

    def test_a_cover_art_url_is_composed_per_size(self):
        record = models.MusicBrainzAlbumData.objects.create(
            album=self.album,
            release_group_mbid="rg-1",
            cover_art_release_mbid="rel-1",
            cover_art_image_id="img-1",
        )
        self.assertEqual(
            record.cover_art_url(250),
            "https://coverartarchive.org/release/rel-1/img-1-250.jpg",
        )

    def test_a_cover_art_url_with_no_size_is_the_full_image(self):
        record = models.MusicBrainzAlbumData.objects.create(
            album=self.album,
            release_group_mbid="rg-1",
            cover_art_release_mbid="rel-1",
            cover_art_image_id="img-1",
        )
        self.assertEqual(
            record.cover_art_url(),
            "https://coverartarchive.org/release/rel-1/img-1.jpg",
        )

    def test_no_cover_identifiers_means_no_urls(self):
        record = models.MusicBrainzAlbumData.objects.create(
            album=self.album, release_group_mbid="rg-1"
        )
        self.assertIsNone(record.cover_art_url(250))
        self.assertIsNone(record.local_cover_art_url(250))

    def test_the_local_cover_url_routes_through_our_own_view(self):
        record = models.MusicBrainzAlbumData.objects.create(
            album=self.album,
            release_group_mbid="rg-1",
            cover_art_release_mbid="rel-1",
            cover_art_image_id="img-1",
        )
        self.assertEqual(
            record.local_cover_art_url(500), "/music/cover/rel-1/img-1-500.jpg"
        )

    def test_a_cover_row_describes_itself(self):
        cover = models.AlbumCover.objects.create(
            release_mbid="rel-1", image_id="img-1", size=250, data=b"x", byte_size=42
        )
        self.assertEqual(str(cover), "Cover img-1 @ 250px (42 bytes)")

    def test_a_cover_is_unique_per_image_and_size(self):
        models.AlbumCover.objects.create(
            release_mbid="rel-1", image_id="img-1", size=250, data=b"x"
        )
        with self.assertRaises(IntegrityError):
            models.AlbumCover.objects.create(
                release_mbid="rel-1", image_id="img-1", size=250, data=b"y"
            )

    def test_only_one_record_per_source_can_be_primary(self):
        models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q1", is_primary=True
        )
        with self.assertRaises(IntegrityError):
            models.WikipediaAlbumData.objects.create(
                album=self.album, wikidata_id="Q2", is_primary=True
            )

    def test_orphaned_records_may_both_be_primary(self):
        """The constraint is scoped to rows that still have an album."""
        models.WikipediaAlbumData.objects.create(wikidata_id="Q1", is_primary=True)
        models.WikipediaAlbumData.objects.create(wikidata_id="Q2", is_primary=True)
        self.assertEqual(models.WikipediaAlbumData.objects.count(), 2)

    def test_metadata_survives_its_album_being_deleted(self):
        """Every import deletes all albums; the metadata must outlive that."""
        record = models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q173643"
        )
        cover = models.AlbumCover.objects.create(
            album=self.album, release_mbid="rel", image_id="img", size=250, data=b"x"
        )
        self.album.delete()
        record.refresh_from_db()
        cover.refresh_from_db()
        self.assertIsNone(record.album)
        self.assertIsNone(cover.album)


class AlbumCoverUrlTests(TestCase):
    """Which URL an album renders depends on whether we hold the bytes."""

    def setUp(self):
        self.album = models.Album.objects.create(name="Abbey Road", rank=2)

    def attach(self, stored):
        record = models.MusicBrainzAlbumData.objects.create(
            album=self.album,
            release_group_mbid="rg-1",
            cover_art_release_mbid="rel-1",
            cover_art_image_id="img-1",
            cover_art_stored=stored,
        )
        self.album.primary_musicbrainz_album_data = record
        self.album.save()
        return models.Album.objects.get(pk=self.album.pk)

    def test_a_stored_cover_is_served_locally(self):
        album = self.attach(stored=True)
        self.assertEqual(album.thumbnail, "/music/cover/rel-1/img-1-250.jpg")
        self.assertEqual(album.image, "/music/cover/rel-1/img-1-500.jpg")

    def test_an_unstored_cover_falls_back_to_the_archive(self):
        album = self.attach(stored=False)
        self.assertIn("coverartarchive.org", album.thumbnail)
        self.assertTrue(album.thumbnail.endswith("-250.jpg"))

    def test_with_no_metadata_record_the_stored_url_is_used(self):
        self.album.cover_image_url = "https://example.test/cover.jpg"
        self.album.save()
        album = models.Album.objects.get(pk=self.album.pk)
        self.assertEqual(album.thumbnail, "https://example.test/cover.jpg")

    def test_with_nothing_at_all_there_is_no_cover(self):
        album = models.Album.objects.get(pk=self.album.pk)
        self.assertIsNone(album.thumbnail)
        self.assertIsNone(album.image)

    def test_reading_a_cover_url_costs_no_extra_query(self):
        """Without the select_related a hundred-row page runs a hundred more."""
        self.attach(stored=True)
        albums = list(models.Album.objects.with_relations().all())
        with self.assertNumQueries(0):
            self.assertEqual(
                [album.thumbnail for album in albums],
                ["/music/cover/rel-1/img-1-250.jpg"],
            )


class AlbumTrackingModelTests(TestCase):
    """`ListenedAlbum` / `WantToListenAlbum`, and what survives a reimport."""

    def setUp(self):
        self.user = User.objects.create_user(username="listener", password="pw")
        self.album = models.Album.objects.create(
            name="Doolittle", rank=1, slug="doolittle", wikidata_id="Q123"
        )

    def test_str_names_the_album(self):
        row = models.ListenedAlbum.objects.create(
            user=self.user, album=self.album, wikidata_id="Q123"
        )
        self.assertEqual(str(row), "listener listened to Doolittle")

    def test_want_to_listen_str_names_the_album(self):
        row = models.WantToListenAlbum.objects.create(
            user=self.user, album=self.album, wikidata_id="Q123"
        )
        self.assertEqual(str(row), "listener wants to listen to Doolittle")

    def test_str_falls_back_to_the_wikidata_id_when_orphaned(self):
        # What an admin sees between an import and the reconnection pass.
        for model_class, verb in (
            (models.ListenedAlbum, "listened to"),
            (models.WantToListenAlbum, "wants to listen to"),
        ):
            with self.subTest(model=model_class.__name__):
                row = model_class.objects.create(
                    user=self.user, album=None, wikidata_id="Q999"
                )
                self.assertEqual(str(row), f"listener {verb} Wikidata:Q999")

    def test_a_user_cannot_track_one_album_twice(self):
        for model_class in (models.ListenedAlbum, models.WantToListenAlbum):
            with self.subTest(model=model_class.__name__):
                model_class.objects.create(
                    user=self.user, album=self.album, wikidata_id="Q123"
                )
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        model_class.objects.create(
                            user=self.user, album=self.album, wikidata_id="Q123"
                        )

    def test_two_users_can_track_the_same_album(self):
        other = User.objects.create_user(username="other", password="pw")
        models.ListenedAlbum.objects.create(
            user=self.user, album=self.album, wikidata_id="Q123"
        )
        models.ListenedAlbum.objects.create(
            user=other, album=self.album, wikidata_id="Q123"
        )
        self.assertEqual(models.ListenedAlbum.objects.count(), 2)

    def test_deleting_the_album_orphans_the_row_rather_than_deleting_it(self):
        # The whole reason the external id is stored: an import deletes every
        # album, and the collection has to outlive that.
        row = models.ListenedAlbum.objects.create(
            user=self.user, album=self.album, wikidata_id="Q123"
        )
        self.album.delete()
        row.refresh_from_db()
        self.assertIsNone(row.album)
        self.assertEqual(row.wikidata_id, "Q123")

    def test_deleting_the_user_deletes_the_row(self):
        models.ListenedAlbum.objects.create(
            user=self.user, album=self.album, wikidata_id="Q123"
        )
        self.user.delete()
        self.assertEqual(models.ListenedAlbum.objects.count(), 0)


class AlbumListenStatusAnnotationTests(TestCase):
    """`AlbumQuerySet.with_listen_status`."""

    def setUp(self):
        self.user = User.objects.create_user(username="listener", password="pw")
        self.listened = models.Album.objects.create(
            name="Doolittle", rank=1, slug="doolittle", wikidata_id="Q1"
        )
        self.wanted = models.Album.objects.create(
            name="Surfer Rosa", rank=2, slug="surfer-rosa", wikidata_id="Q2"
        )
        self.untracked = models.Album.objects.create(
            name="Bossanova", rank=3, slug="bossanova", wikidata_id="Q3"
        )
        models.ListenedAlbum.objects.create(
            user=self.user, album=self.listened, wikidata_id="Q1"
        )
        models.WantToListenAlbum.objects.create(
            user=self.user, album=self.wanted, wikidata_id="Q2"
        )

    def _annotated(self):
        return {
            album.slug: album
            for album in models.Album.objects.with_listen_status(self.user)
        }

    def test_it_annotates_both_flags(self):
        albums = self._annotated()
        self.assertTrue(albums["doolittle"].is_listened_by_user)
        self.assertFalse(albums["doolittle"].is_want_to_listen_by_user)
        self.assertTrue(albums["surfer-rosa"].is_want_to_listen_by_user)
        self.assertFalse(albums["surfer-rosa"].is_listened_by_user)
        self.assertFalse(albums["bossanova"].is_listened_by_user)
        self.assertFalse(albums["bossanova"].is_want_to_listen_by_user)

    def test_another_users_tracking_does_not_leak(self):
        other = User.objects.create_user(username="other", password="pw")
        albums = {
            album.slug: album
            for album in models.Album.objects.with_listen_status(other)
        }
        self.assertFalse(albums["doolittle"].is_listened_by_user)

    def test_an_orphaned_row_does_not_annotate(self):
        # No FK, nothing to join on - which is why the id sets filter these
        # out too, rather than showing a row the page cannot mark.
        models.ListenedAlbum.objects.filter(album=self.listened).update(album=None)
        self.assertFalse(self._annotated()["doolittle"].is_listened_by_user)

    def test_it_is_a_no_op_for_an_anonymous_user(self):
        # The annotations are absent rather than False, so anything filtering
        # on them has to guard the same way.
        albums = models.Album.objects.with_listen_status(AnonymousUser())
        self.assertFalse(hasattr(albums.first(), "is_listened_by_user"))

    def test_it_is_a_no_op_for_no_user(self):
        albums = models.Album.objects.with_listen_status(None)
        self.assertFalse(hasattr(albums.first(), "is_listened_by_user"))

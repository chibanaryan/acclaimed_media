"""Tests for the music models."""

from django.db.utils import IntegrityError
from django.test import TestCase

from core import constants as core_constants
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

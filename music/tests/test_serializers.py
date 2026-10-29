"""Tests for the music serializers, beyond what the API tests cover."""

from django.test import TestCase

from music import models
from music.api import serializers


class AlbumSummarySerializerTests(TestCase):
    def setUp(self):
        self.artist = models.Artist.objects.create(name="Radiohead", slug="radiohead")
        self.album = models.Album.objects.create(
            name="Kid A", rank=1, artist_credit="Radiohead", year_released=2000
        )
        self.album.artists.set([self.artist])

    def test_list_count_falls_back_to_a_query_without_the_annotation(self):
        data = serializers.AlbumSummarySerializer(self.album).data
        self.assertEqual(data["list_count"], 0)

    def test_list_count_uses_the_annotation_when_present(self):
        publication = models.MusicPublication.objects.create(name="Pitchfork")
        source = models.MusicList.objects.create(
            name="Best of 2000", year=2000, publisher=publication, order=1
        )
        models.AlbumListMembership.objects.create(list=source, album=self.album, rank=1)
        annotated = models.Album.objects.with_list_count().get(pk=self.album.pk)
        data = serializers.AlbumSummarySerializer(annotated).data
        self.assertEqual(data["list_count"], 1)

    def test_artists_are_serialized_with_id_slug_name_and_credited_name(self):
        data = serializers.AlbumSummarySerializer(self.album).data
        self.assertEqual(
            data["artists"],
            [
                {
                    "id": self.artist.id,
                    "name": "Radiohead",
                    "slug": "radiohead",
                    "credited_name": "Radiohead",
                }
            ],
        )
        self.assertFalse(data["various_artists"])

    def test_genres_are_empty_when_none_are_set(self):
        data = serializers.AlbumSummarySerializer(self.album).data
        self.assertEqual(data["genres"], [])


class AlbumDetailSerializerTests(TestCase):
    def test_lists_are_empty_for_an_album_on_no_lists(self):
        album = models.Album.objects.create(name="Unlisted", rank=1)
        data = serializers.AlbumDetailSerializer(album).data
        self.assertEqual(list(data["lists"]), [])


class MusicGenreSerializerTests(TestCase):
    def test_a_root_genre_has_a_null_parent_id(self):
        genre = models.MusicGenre.objects.create(name="Rock")
        data = serializers.MusicGenreSerializer(genre).data
        self.assertIsNone(data["parent_id"])
        self.assertEqual(data["level"], 0)
        self.assertEqual(data["path"], "Rock")

    def test_a_child_genre_carries_its_parent_id(self):
        rock = models.MusicGenre.objects.create(name="Rock")
        punk = models.MusicGenre.objects.create(name="Punk Rock", parent=rock)
        data = serializers.MusicGenreSerializer(punk).data
        self.assertEqual(data["parent_id"], rock.id)
        self.assertEqual(data["level"], 1)


class MusicListSerializerTests(TestCase):
    def test_publication_falls_back_to_an_empty_string(self):
        source = models.MusicList.objects.create(name="Orphan", year=2000, order=1)
        data = serializers.MusicListSerializer(source).data
        self.assertEqual(data["publication"], "")

    def test_publication_name_is_flattened(self):
        publication = models.MusicPublication.objects.create(name="Mojo")
        source = models.MusicList.objects.create(
            name="Greatest", year=1995, publisher=publication, order=1
        )
        data = serializers.MusicListSerializer(source).data
        self.assertEqual(data["publication"], "Mojo")

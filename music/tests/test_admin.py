"""Tests for the music admin."""

from django.contrib.admin.sites import site
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.models import User
from music import admin as music_admin
from music import models


class AdminRegistrationTests(TestCase):
    def test_every_music_model_is_registered(self):
        for model in [
            models.Artist,
            models.MusicGenre,
            models.Album,
            models.MusicPublication,
            models.MusicList,
            models.AlbumListMembership,
        ]:
            with self.subTest(model=model.__name__):
                self.assertIn(model, site._registry)


class AdminAnnotationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.superuser = User.objects.create_superuser(
            username="musicadmin", password="adminpass", email="admin@example.com"
        )
        self.request = self.factory.get("/admin/")
        self.request.user = self.superuser

        self.artist = models.Artist.objects.create(name="Radiohead", slug="radiohead")
        self.genre = models.MusicGenre.objects.create(name="Rock")
        self.album = models.Album.objects.create(
            name="Kid A", rank=1, artist_credit="Radiohead", wikidata_id="Q202698"
        )
        self.album.artists.set([self.artist])
        self.album.genres.set([self.genre])

        self.publication = models.MusicPublication.objects.create(name="Pitchfork")
        self.source = models.MusicList.objects.create(
            name="Best of 2000", year=2000, publisher=self.publication, order=1
        )
        models.AlbumListMembership.objects.create(
            list=self.source, album=self.album, rank=1
        )

    def test_artist_album_count(self):
        admin_obj = site._registry[models.Artist]
        obj = admin_obj.get_queryset(self.request).get(pk=self.artist.pk)
        self.assertEqual(admin_obj.album_count(obj), 1)

    def test_genre_album_count(self):
        admin_obj = site._registry[models.MusicGenre]
        obj = admin_obj.get_queryset(self.request).get(pk=self.genre.pk)
        self.assertEqual(admin_obj.album_count(obj), 1)

    def test_album_list_count(self):
        admin_obj = site._registry[models.Album]
        obj = admin_obj.get_queryset(self.request).get(pk=self.album.pk)
        self.assertEqual(admin_obj.list_count(obj), 1)

    def test_album_wikidata_link(self):
        admin_obj = site._registry[models.Album]
        rendered = admin_obj.wikidata_link(self.album)
        self.assertIn("wikidata.org/wiki/Q202698", rendered)
        self.assertIn("Q202698", rendered)

    def test_album_wikidata_link_without_an_id(self):
        admin_obj = site._registry[models.Album]
        album = models.Album.objects.create(name="No Id", rank=2)
        self.assertEqual(admin_obj.wikidata_link(album), "-")

    def test_publication_list_count(self):
        admin_obj = site._registry[models.MusicPublication]
        obj = admin_obj.get_queryset(self.request).get(pk=self.publication.pk)
        self.assertEqual(admin_obj.list_count(obj), 1)

    def test_music_list_album_count(self):
        admin_obj = site._registry[models.MusicList]
        obj = admin_obj.get_queryset(self.request).get(pk=self.source.pk)
        self.assertEqual(admin_obj.album_count(obj), 1)

    def test_membership_queryset_selects_related(self):
        admin_obj = site._registry[models.AlbumListMembership]
        queryset = admin_obj.get_queryset(self.request)
        self.assertEqual(queryset.count(), 1)


class AdminChangelistTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="musicadmin", password="adminpass", email="admin@example.com"
        )
        self.client.login(username="musicadmin", password="adminpass")

        self.artist = models.Artist.objects.create(name="Radiohead", slug="radiohead")
        models.MusicGenre.objects.create(name="Rock")
        album = models.Album.objects.create(
            name="Kid A", rank=1, artist_credit="Radiohead"
        )
        album.artists.set([self.artist])
        publication = models.MusicPublication.objects.create(name="Pitchfork")
        source = models.MusicList.objects.create(
            name="Best of 2000", year=2000, publisher=publication, order=1
        )
        models.AlbumListMembership.objects.create(list=source, album=album, rank=1)

    def test_every_changelist_loads(self):
        for model in [
            models.Artist,
            models.MusicGenre,
            models.Album,
            models.MusicPublication,
            models.MusicList,
            models.AlbumListMembership,
        ]:
            url = reverse(f"admin:music_{model._meta.model_name}_changelist")
            with self.subTest(model=model.__name__):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_an_album_change_form_loads(self):
        album = models.Album.objects.first()
        url = reverse("admin:music_album_change", args=[album.pk])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_an_artist_change_form_loads_with_its_inline(self):
        url = reverse("admin:music_artist_change", args=[self.artist.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_album_search_works(self):
        url = reverse("admin:music_album_changelist")
        response = self.client.get(url, {"q": "Kid"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kid A")


class AdminInlineTests(TestCase):
    def test_subsidiary_artist_inline_points_at_the_parent_fk(self):
        inline = music_admin.SubsidiaryArtistInline
        self.assertEqual(inline.model, models.Artist)
        self.assertEqual(inline.fk_name, "parent")

    def test_genre_child_inline_points_at_the_parent_fk(self):
        inline = music_admin.MusicGenreChildInline
        self.assertEqual(inline.model, models.MusicGenre)
        self.assertEqual(inline.fk_name, "parent")

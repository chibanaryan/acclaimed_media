"""Tests for the music admin."""

from django.contrib.admin.sites import site
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.models import User
from music import admin as music_admin
from music import models


class AdminRegistrationTests(TestCase):
    def test_every_music_model_is_registered(self):
        """Derived from the app's models, so a new model cannot be forgotten.

        A hand-kept list here silently passed when the metadata models were
        added, which is exactly when an unregistered model is easiest to miss.
        """
        from django.apps import apps

        music_models = [
            model
            for model in apps.get_app_config("music").get_models()
            if not model._meta.auto_created
        ]
        self.assertGreaterEqual(len(music_models), 10)
        for model in music_models:
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


class MetadataAdminTests(TestCase):
    """The fetched-metadata admins: display helpers and the deferred bytes."""

    def setUp(self):
        self.factory = RequestFactory()
        self.superuser = User.objects.create_superuser(
            username="metaadmin", password="adminpass", email="meta@example.com"
        )
        self.request = self.factory.get("/admin/")
        self.request.user = self.superuser
        self.album = models.Album.objects.create(
            name="Abbey Road", rank=2, wikidata_id="Q173643"
        )

    def test_the_external_data_admins_select_the_album(self):
        for model in [
            models.WikipediaAlbumData,
            models.DiscogsAlbumData,
            models.MusicBrainzAlbumData,
        ]:
            with self.subTest(model=model.__name__):
                model_admin = site._registry[model]
                queryset = model_admin.get_queryset(self.request)
                self.assertIn("album", queryset.query.select_related)

    def test_discogs_genre_and_style_summaries(self):
        record = models.DiscogsAlbumData.objects.create(
            album=self.album,
            master_id=24047,
            genres=["Rock", "Pop"],
            styles=["Pop Rock"],
        )
        model_admin = site._registry[models.DiscogsAlbumData]
        self.assertEqual(model_admin.genre_summary(record), "Rock, Pop")
        self.assertEqual(model_admin.style_summary(record), "Pop Rock")

    def test_empty_discogs_summaries_render_a_dash(self):
        record = models.DiscogsAlbumData.objects.create(
            album=self.album, master_id=1, genres=[], styles=[]
        )
        model_admin = site._registry[models.DiscogsAlbumData]
        self.assertEqual(model_admin.genre_summary(record), "-")
        self.assertEqual(model_admin.style_summary(record), "-")

    def test_the_cover_admin_defers_the_image_bytes(self):
        """A changelist of a hundred rows would otherwise be megabytes."""
        model_admin = site._registry[models.AlbumCover]
        queryset = model_admin.get_queryset(self.request)
        self.assertIn("data", queryset.query.deferred_loading[0])

    def test_the_cover_admin_reports_kilobytes(self):
        cover = models.AlbumCover.objects.create(
            release_mbid="r", image_id="i", size=250, data=b"x", byte_size=25600
        )
        model_admin = site._registry[models.AlbumCover]
        self.assertEqual(model_admin.kilobytes(cover), "25 KB")

    def test_the_cover_admin_previews_a_saved_row(self):
        record = models.MusicBrainzAlbumData.objects.create(
            album=self.album,
            release_group_mbid="rg",
            cover_art_release_mbid="rel",
            cover_art_image_id="img",
            cover_art_stored=True,
        )
        self.album.primary_musicbrainz_album_data = record
        self.album.save()
        cover = models.AlbumCover.objects.create(
            album=self.album, release_mbid="rel", image_id="img", size=250, data=b"x"
        )
        model_admin = site._registry[models.AlbumCover]
        self.assertIn("/music/cover/", model_admin.preview(cover))

    def test_an_unsaved_cover_has_no_preview(self):
        model_admin = site._registry[models.AlbumCover]
        self.assertEqual(model_admin.preview(models.AlbumCover()), "-")

    def test_a_cover_with_no_album_previews_nothing(self):
        cover = models.AlbumCover.objects.create(
            release_mbid="r", image_id="i", size=250, data=b"x", album=None
        )
        model_admin = site._registry[models.AlbumCover]
        self.assertIn("<img", model_admin.preview(cover))

    def test_every_metadata_changelist_loads(self):
        models.WikipediaAlbumData.objects.create(
            album=self.album, wikidata_id="Q173643", page_title="Abbey Road"
        )
        models.DiscogsAlbumData.objects.create(album=self.album, master_id=24047)
        models.MusicBrainzAlbumData.objects.create(
            album=self.album, release_group_mbid="rg"
        )
        models.AlbumCover.objects.create(
            release_mbid="r", image_id="i", size=250, data=b"x", album=self.album
        )
        self.client.force_login(self.superuser)
        for model in [
            models.WikipediaAlbumData,
            models.DiscogsAlbumData,
            models.MusicBrainzAlbumData,
            models.AlbumCover,
        ]:
            with self.subTest(model=model.__name__):
                url = reverse(f"admin:music_{model._meta.model_name}_changelist")
                self.assertEqual(self.client.get(url).status_code, 200)


class TrackingAdminTests(TestCase):
    """The tracking admins, and how they show a row an import orphaned."""

    def setUp(self):
        self.user = User.objects.create_user(username="listener", password="pw")
        self.album = models.Album.objects.create(
            name="Doolittle", rank=1, slug="doolittle", wikidata_id="Q123"
        )

    def test_a_connected_row_shows_the_album_name(self):
        for model_class in (models.ListenedAlbum, models.WantToListenAlbum):
            with self.subTest(model=model_class.__name__):
                row = model_class.objects.create(
                    user=self.user, album=self.album, wikidata_id="Q123"
                )
                admin_obj = site._registry[model_class]
                self.assertEqual(admin_obj.album_name(row), "Doolittle")
                self.assertEqual(admin_obj.link_status(row), "Connected")
                row.delete()

    def test_an_orphaned_row_shows_the_id_it_is_waiting_on(self):
        # What an admin sees between an import and the reconnection pass -
        # and the signal that the pass has not run.
        for model_class in (models.ListenedAlbum, models.WantToListenAlbum):
            with self.subTest(model=model_class.__name__):
                row = model_class.objects.create(
                    user=self.user, album=None, wikidata_id="Q999"
                )
                admin_obj = site._registry[model_class]
                self.assertEqual(admin_obj.album_name(row), "(orphaned) Wikidata:Q999")
                self.assertEqual(admin_obj.link_status(row), "Orphaned")
                row.delete()

    def test_the_changelists_load(self):
        staff = User.objects.create_user(
            username="admin", password="pw", is_staff=True, is_superuser=True
        )
        self.client.login(username="admin", password="pw")
        models.ListenedAlbum.objects.create(
            user=self.user, album=self.album, wikidata_id="Q123"
        )
        models.WantToListenAlbum.objects.create(
            user=staff, album=self.album, wikidata_id="Q123"
        )

        for model_class in (models.ListenedAlbum, models.WantToListenAlbum):
            with self.subTest(model=model_class.__name__):
                url = reverse(f"admin:music_{model_class._meta.model_name}_changelist")
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_the_listened_changelist_separates_have_from_heard(self):
        # "Have" has no table of its own; filtering on owned is how an admin
        # finds it.
        User.objects.create_user(
            username="admin", password="pw", is_staff=True, is_superuser=True
        )
        self.client.login(username="admin", password="pw")
        other = models.Album.objects.create(
            name="Surfer Rosa", rank=2, slug="surfer-rosa", wikidata_id="Q456"
        )
        models.ListenedAlbum.objects.create(
            user=self.user, album=self.album, wikidata_id="Q123", owned=True
        )
        models.ListenedAlbum.objects.create(
            user=self.user, album=other, wikidata_id="Q456"
        )
        admin_obj = site._registry[models.ListenedAlbum]
        self.assertIn("owned", admin_obj.list_display)
        self.assertIn("owned", admin_obj.list_filter)

        url = reverse("admin:music_listenedalbum_changelist")
        have = self.client.get(url, {"owned__exact": "1"}).content.decode()
        heard = self.client.get(url, {"owned__exact": "0"}).content.decode()

        self.assertIn("Doolittle", have)
        self.assertNotIn("Surfer Rosa", have)
        self.assertIn("Surfer Rosa", heard)
        self.assertNotIn("Doolittle", heard)

    def test_the_admins_search_by_user_and_album(self):
        # So a support question about one person's collection is answerable.
        for model_class in (models.ListenedAlbum, models.WantToListenAlbum):
            with self.subTest(model=model_class.__name__):
                fields = site._registry[model_class].search_fields
                self.assertIn("user__username", fields)
                self.assertIn("album__name", fields)
                self.assertIn("wikidata_id", fields)


class SavedAlbumFilterAdminTests(TestCase):
    """The one-line summary of a stored filter blob.

    Each dimension is checked on its own, because the summary is the only
    place an admin sees what a saved filter actually does - the JSON column
    itself is unreadable at a glance.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="saver", password="pw")
        self.admin_obj = site._registry[models.SavedAlbumFilterSet]

    def summarise(self, filters):
        row = models.SavedAlbumFilterSet(
            user=self.user, name="Example", filters=filters
        )
        return self.admin_obj.filter_summary(row)

    def test_an_empty_blob_says_so(self):
        self.assertEqual(self.summarise({}), "(no filters)")

    def test_a_null_blob_says_so(self):
        # `filters` is non-null in the schema, but a row written by hand or
        # by an older client can still hold JSON null.
        self.assertEqual(self.summarise(None), "(no filters)")

    def test_a_search_term_is_shown_and_truncated(self):
        self.assertEqual(self.summarise({"q": "miles"}), "search: miles")
        self.assertEqual(self.summarise({"q": "x" * 40}), "search: " + "x" * 20)

    def test_genres_are_counted(self):
        self.assertEqual(self.summarise({"genres": ["1", "2"]}), "2 genres")

    def test_the_listen_status_is_named(self):
        self.assertEqual(
            self.summarise({"listened": ["yes", "want"]}), "listen: yes,want"
        )

    def test_a_year_window_is_shown(self):
        self.assertEqual(self.summarise({"start": 1970, "end": 1979}), "1970-1979")

    def test_a_half_open_window_marks_the_missing_end(self):
        self.assertEqual(self.summarise({"start": 1970}), "1970-?")
        self.assertEqual(self.summarise({"end": 1979}), "?-1979")

    def test_the_default_sort_is_left_out(self):
        self.assertEqual(self.summarise({"sort": "rank"}), "(no filters)")

    def test_a_non_default_sort_is_named(self):
        self.assertEqual(self.summarise({"sort": "year"}), "sort: year")

    def test_every_dimension_reads_together(self):
        self.assertEqual(
            self.summarise(
                {
                    "q": "jazz",
                    "genres": ["3"],
                    "listened": ["yes"],
                    "start": 1960,
                    "end": 1969,
                    "sort": "year",
                }
            ),
            "search: jazz, 1 genres, listen: yes, 1960-1969, sort: year",
        )

    def test_the_changelist_loads(self):
        User.objects.create_user(
            username="sfadmin", password="pw", is_staff=True, is_superuser=True
        )
        self.client.login(username="sfadmin", password="pw")
        models.SavedAlbumFilterSet.objects.create(
            user=self.user, name="Seventies", filters={"start": 1970, "end": 1979}
        )
        url = reverse("admin:music_savedalbumfilterset_changelist")
        self.assertEqual(self.client.get(url).status_code, 200)

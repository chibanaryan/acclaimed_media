"""Who can reach the music section, with ``MUSIC_ENABLED`` off and on.

Off is the staff-only beta every other music suite runs under (the setting is
forced off under test). These tests pin what turning it on changes - reads go
public, writes want a login, the import page does not move - and the one
hole the off state had: a signed-in outsider's token-less POST to the
saved-filter API was answered with DRF's CSRF 403, not the section's 404.
"""

import json

from django.contrib.auth.models import AnonymousUser
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import User
from core.tests.utils import clear_all_caches
from music import models
from music.access import music_visible_to


class MusicVisibleToTests(TestCase):
    """The single predicate every music gate asks."""

    def setUp(self):
        self.staff = User.objects.create_user(username="pstaff", is_staff=True)
        self.plain = User.objects.create_user(username="pplain")

    def test_only_staff_see_the_hidden_section(self):
        self.assertTrue(music_visible_to(self.staff))
        self.assertFalse(music_visible_to(self.plain))
        self.assertFalse(music_visible_to(AnonymousUser()))

    @override_settings(MUSIC_ENABLED=True)
    def test_everyone_sees_the_public_section(self):
        for user in (self.staff, self.plain, AnonymousUser()):
            with self.subTest(user=user):
                self.assertTrue(music_visible_to(user))


class AccessFixtureMixin:
    def setUp(self):
        super().setUp()
        clear_all_caches()
        self.artist = models.Artist.objects.create(name="The Who", slug="the-who")
        self.rock = models.MusicGenre.objects.create(name="Rock")
        self.albums = []
        for index in range(12):
            album = models.Album.objects.create(
                name=f"Album {index}",
                rank=index + 1,
                artist_credit="The Who",
                year_released=1970 + index % 10,
                wikidata_id=f"Q{9000 + index}",
            )
            album.artists.set([self.artist])
            album.genres.set([self.rock])
            self.albums.append(album)
        self.album = self.albums[0]
        self.plain = User.objects.create_user(username="plain", password="plainpass")
        self.staff = User.objects.create_user(
            username="staff", password="staffpass", is_staff=True
        )

    def read_urls(self):
        return [
            reverse("music:home"),
            reverse("music:search") + "?q=album",
            reverse("music:download"),
            reverse("music:list-list"),
            reverse("music:artist-list"),
            reverse("music:artist-detail", kwargs={"slug": self.artist.slug}),
            reverse("music:browse"),
            reverse("music:by-genre", kwargs={"slug": self.rock.slug}),
            reverse("music:by-decade", kwargs={"decade": 1970}),
            self.album.get_absolute_url(),
            reverse("music-api:album-list"),
            reverse("music-api:album-all-data"),
            reverse("music-api:unified-search") + "?q=album",
            reverse("music-api:meta"),
            reverse("music-api:genre-list"),
            reverse("music-api:album-detail", kwargs={"slug": self.album.slug}),
        ]


class HiddenSectionTests(AccessFixtureMixin, TestCase):
    """``MUSIC_ENABLED`` off: the section is absent for everyone but staff."""

    def test_every_read_url_404s_for_an_anonymous_visitor(self):
        for url in self.read_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_every_read_url_404s_for_a_signed_in_outsider(self):
        self.client.login(username="plain", password="plainpass")
        for url in self.read_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_staff_reach_every_read_url(self):
        self.client.login(username="staff", password="staffpass")
        for url in self.read_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_an_outsiders_tokenless_post_to_saved_filters_is_a_404(self):
        # DRF authenticates before it checks permissions, and session
        # authentication enforces CSRF for any signed-in user, so with the
        # gate as a permission this answered "CSRF Failed" with a 403 - which
        # told the caller the endpoint existed.
        client = Client(enforce_csrf_checks=True)
        client.login(username="plain", password="plainpass")
        response = client.post(
            reverse("music-api:saved-filter-list"),
            json.dumps({"name": "Probe", "filters": {}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(models.SavedAlbumFilterSet.objects.exists())

    def test_an_anonymous_toggle_is_a_404_not_a_login_redirect(self):
        url = reverse("music:toggle-listened", args=[self.album.pk])
        response = self.client.post(f"{url}?status=listened")
        self.assertEqual(response.status_code, 404)


@override_settings(MUSIC_ENABLED=True)
class PublicSectionTests(AccessFixtureMixin, TestCase):
    """``MUSIC_ENABLED`` on: reads are public, writes want a login."""

    def test_every_read_url_renders_for_an_anonymous_visitor(self):
        for url in self.read_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_every_read_url_renders_for_a_signed_in_reader(self):
        self.client.login(username="plain", password="plainpass")
        for url in self.read_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_the_import_page_stays_staff_only(self):
        url = reverse("music:import")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.login(username="plain", password="plainpass")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.login(username="staff", password="staffpass")
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_a_signed_out_toggle_redirects_to_login_as_games_does(self):
        url = reverse("music:toggle-listened", args=[self.album.pk])
        response = self.client.post(f"{url}?status=listened")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))
        self.assertFalse(models.ListenedAlbum.objects.exists())

    def test_a_signed_in_reader_can_track_an_album(self):
        self.client.login(username="plain", password="plainpass")
        url = reverse("music:toggle-listened", args=[self.album.pk])
        response = self.client.post(f"{url}?status=listened")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            models.ListenedAlbum.objects.filter(
                user=self.plain, album=self.album
            ).exists()
        )

    def test_a_signed_out_caller_gets_403_from_saved_filters(self):
        url = reverse("music-api:saved-filter-list")
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_a_signed_in_reader_can_save_a_filter_with_a_token(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="plain", password="plainpass")
        client.get(reverse("music:home"))
        response = client.post(
            reverse("music-api:saved-filter-list"),
            json.dumps({"name": "Mine", "filters": {"genres": ["1"]}}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            models.SavedAlbumFilterSet.objects.get().user_id, self.plain.pk
        )

    def test_a_failed_csrf_check_is_the_real_403_once_public(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("music:home"))
        self.assertEqual(response.status_code, 403)

    def test_an_anonymous_rankings_page_has_no_tracking_state_or_beta_badge(self):
        response = self.client.get(reverse("music:home"))
        self.assertContains(response, "window.isAuthenticated = false;")
        self.assertNotContains(response, "Beta</span>")

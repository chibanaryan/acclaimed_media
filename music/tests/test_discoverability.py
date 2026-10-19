"""The music section must not be reachable by browsing the main site.

Music is a staff-only beta with no entry point in the chrome: the only way in
is to know the URL. These tests pin that down so a link cannot be added back
by accident, and they run as staff - the strongest case, since a staff member
is the one person who *could* be shown a link.
"""

from django.test import TestCase
from django.urls import resolve, reverse

from core.models import User
from music import models


class NoNavigationEntryTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="navstaff", password="navpass", is_staff=True
        )
        self.client.login(username="navstaff", password="navpass")
        models.Album.objects.create(
            name="Pet Sounds",
            rank=1,
            artist_credit="The Beach Boys",
            year_released=1966,
        )

    def _assert_no_music_link(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn('href="/music/', html)
        self.assertNotIn("Music</span>", html)

    def test_the_games_home_page_does_not_link_to_music(self):
        self._assert_no_music_link(reverse("home"))

    def test_the_developer_list_does_not_link_to_music(self):
        self._assert_no_music_link(reverse("developers-list"))

    def test_the_games_source_lists_page_does_not_link_to_music(self):
        self._assert_no_music_link(reverse("list-list"))

    def test_the_media_switcher_offers_no_music_tab(self):
        from django.template.loader import render_to_string

        rendered = render_to_string(
            "core/includes/_media_switcher.html",
            {"BOOKS_ENABLED": True, "media_type": "games"},
        )
        self.assertNotIn("/music/", rendered)
        self.assertIn("Games", rendered)

    def test_the_sitemap_excludes_music(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("/music/", response.content.decode())


class ReachableByUrlTests(TestCase):
    """Unlinked is not the same as unreachable: staff can still type the URL."""

    def setUp(self):
        self.album = models.Album.objects.create(
            name="Pet Sounds",
            rank=1,
            artist_credit="The Beach Boys",
            year_released=1966,
        )

    def test_staff_reach_every_music_page_directly(self):
        User.objects.create_user(username="navstaff", password="navpass", is_staff=True)
        self.client.login(username="navstaff", password="navpass")
        for url in [
            reverse("music:home"),
            reverse("music:list-list"),
            reverse("music:artist-list"),
            self.album.get_absolute_url(),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_a_normal_visitor_gets_404_even_with_the_url(self):
        User.objects.create_user(username="plain", password="plainpass")
        self.client.login(username="plain", password="plainpass")
        for url in [
            reverse("music:home"),
            reverse("music:list-list"),
            reverse("music:artist-list"),
            self.album.get_absolute_url(),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_an_anonymous_visitor_gets_404_even_with_the_url(self):
        for url in [reverse("music:home"), self.album.get_absolute_url()]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)


class SavedFilterApiIsHiddenTests(TestCase):
    """The saved-filter endpoints are the section's only writes.

    They are checked here as well as in `test_saved_filters` because this
    file is the sweep a reader consults to ask "is anything reachable?", and
    a write endpoint is the one worth being sure of.
    """

    def test_staff_reach_the_saved_filter_api(self):
        User.objects.create_user(username="sfstaff", password="sfpass", is_staff=True)
        self.client.login(username="sfstaff", password="sfpass")
        response = self.client.get(reverse("music-api:saved-filter-list"))
        self.assertEqual(response.status_code, 200)

    def test_a_normal_visitor_gets_404(self):
        User.objects.create_user(username="sfplain", password="sfpass")
        self.client.login(username="sfplain", password="sfpass")
        self.assertEqual(
            self.client.get(reverse("music-api:saved-filter-list")).status_code, 404
        )

    def test_an_anonymous_visitor_gets_404(self):
        self.assertEqual(
            self.client.get(reverse("music-api:saved-filter-list")).status_code, 404
        )

    def test_the_route_sits_before_the_album_slug_catch_all(self):
        # `saved-filters/` would otherwise resolve as an album slug, which
        # would make a POST to it a 405 from the detail view instead.
        match = resolve("/api/music/saved-filters/")
        self.assertEqual(match.url_name, "saved-filter-list")

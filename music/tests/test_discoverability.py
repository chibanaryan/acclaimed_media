"""Whether the music section can be found by browsing the main site.

Until ``MUSIC_ENABLED`` is on, music is a staff-only beta with no entry point
in the chrome: the only way in is to know the URL. The first classes pin that
down so a link cannot be added by accident, and they run as staff - the
strongest case, since a staff member is the one person who *could* be shown a
link. The nav keys off the flag alone for exactly that reason.

``LaunchedSectionTests`` pins the other half: once the flag is on, the
switcher, both navs and the sitemap all lead there.
"""

from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import resolve, reverse

from core.models import User
from core.tests.utils import clear_all_caches
from music import models

# The sidebar's own links, as rendered once template indentation is stripped.
SIDEBAR_RANKINGS_LINK = (
    '<span class="mdi mdi-medal text-xl" aria-hidden="true"></span>\nRankings'
)
SIDEBAR_BACK_TO_GAMES = (
    '<span class="mdi mdi-arrow-left text-xl" aria-hidden="true"></span>\nBack to Games'
)


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
        rendered = render_to_string(
            "core/includes/_media_switcher.html",
            {"BOOKS_ENABLED": True, "MUSIC_ENABLED": False, "media_type": "games"},
        )
        self.assertNotIn("/music/", rendered)
        self.assertIn("Games", rendered)

    def test_the_sitemap_excludes_music(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("/music/", response.content.decode())

    def test_robots_txt_does_not_name_the_section(self):
        # robots.txt is public, so a Disallow for a hidden path would be the
        # link this file exists to forbid.
        response = self.client.get("/robots.txt")
        self.assertNotIn("/music/", response.content.decode())

    def test_music_pages_keep_their_own_way_back_to_games(self):
        response = self.client.get(reverse("music:home"))
        self.assertContains(response, SIDEBAR_BACK_TO_GAMES)
        self.assertContains(response, "Beta</span>")

    def test_the_games_sidebar_keeps_its_rankings_link(self):
        response = self.client.get(reverse("developers-list"))
        self.assertContains(response, SIDEBAR_RANKINGS_LINK)


@override_settings(MUSIC_ENABLED=True)
class LaunchedSectionTests(TestCase):
    """With ``MUSIC_ENABLED`` on, the main site leads to music."""

    def setUp(self):
        # The games pages are whole-page cached for anonymous visitors, so a
        # copy rendered under the other flag state would be replayed.
        clear_all_caches()
        self.album = models.Album.objects.create(
            name="Pet Sounds",
            rank=1,
            artist_credit="The Beach Boys",
            year_released=1966,
        )

    def test_the_games_pages_link_to_music_for_anonymous_visitors(self):
        for url in (reverse("home"), reverse("developers-list"), reverse("list-list")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, 'href="/music/"')

    def test_the_switcher_offers_music_without_books(self):
        for variant in ("tabs", "pills", "minimal", "menu"):
            with self.subTest(variant=variant):
                rendered = render_to_string(
                    "core/includes/_media_switcher.html",
                    {
                        "BOOKS_ENABLED": False,
                        "MUSIC_ENABLED": True,
                        "media_type": "music",
                        "variant": variant,
                    },
                )
                self.assertIn('href="/music/"', rendered)
                self.assertIn('href="/"', rendered)
                self.assertNotIn("/books/", rendered)

    def test_the_mobile_nav_has_a_music_entry(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'data-nav-item="music"')

    def test_the_switcher_replaces_the_games_rankings_link(self):
        # The switcher's Games tab is the way to the rankings once it shows,
        # as it already was whenever books was enabled.
        response = self.client.get(reverse("developers-list"))
        self.assertNotContains(response, SIDEBAR_RANKINGS_LINK)
        self.assertContains(response, '<nav aria-label="Section"')

    def test_music_pages_lead_back_through_the_switcher(self):
        response = self.client.get(reverse("music:home"))
        self.assertNotContains(response, SIDEBAR_BACK_TO_GAMES)
        self.assertContains(response, 'class="tab gap-1 tab-active"')
        self.assertNotContains(response, "Beta</span>")

    def test_the_sitemap_lists_the_music_section(self):
        response = self.client.get("/sitemap.xml")
        content = response.content.decode()
        self.assertIn("/music/</loc>", content)
        self.assertIn(f"{self.album.get_absolute_url()}</loc>", content)

    def test_robots_txt_keeps_crawlers_off_the_import_and_csv_pages(self):
        content = self.client.get("/robots.txt").content.decode()
        self.assertIn("Disallow: /music/import/", content)
        self.assertIn("Disallow: /music/download/", content)

    def test_turning_the_flag_back_off_hides_it_all_again(self):
        self.client.get(reverse("home"))
        # Production gets this for free: setting a config var restarts the
        # dynos, which empties the per-process page cache.
        clear_all_caches()
        with self.settings(MUSIC_ENABLED=False):
            self.assertNotContains(self.client.get(reverse("home")), 'href="/music/')
            self.assertNotIn(
                "/music/", self.client.get("/sitemap.xml").content.decode()
            )
            self.assertEqual(self.client.get(reverse("music:home")).status_code, 404)


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

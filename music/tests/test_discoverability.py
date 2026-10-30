"""Whether the music site can be found by browsing the others.

Until ``MUSIC_ENABLED`` is on, music is a staff-only beta with no entry point
in the chrome: the only way in is to know the URL. The first classes pin that
down so a link cannot be added by accident, and they run as staff - the
strongest case, since a staff member is the one person who *could* be shown a
link. The nav keys off the flag alone for exactly that reason.

``LaunchedSectionTests`` pins the other half: once the flag is on, the
switcher, both navs, the landing page and the sitemap all lead there.

Music is its own host (core/sites.py), so these requests name the real hosts,
over HTTPS, and a link to music is an absolute one.
"""

from unittest import mock

from django.conf import settings
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import resolve, reverse

from core import sites
from core.models import User
from core.tests.utils import clear_all_caches
from music import config, models
from music.tests.site import music_site

GAMES_HOST = "games.acclaimedmedia.org"
MUSIC_HOST = "music.acclaimedmedia.org"
ROOT_HOST = "acclaimedmedia.org"
MUSIC_HOME = 'href="https://music.acclaimedmedia.org/"'
GAMES_HOME = 'href="https://games.acclaimedmedia.org/"'

# The sidebar's own links, as rendered once template indentation is stripped.
SIDEBAR_RANKINGS_LINK = (
    '<span class="mdi mdi-medal text-xl" aria-hidden="true"></span>\nRankings'
)
SIDEBAR_BACK_TO_GAMES = "Back to Games"


def site_menu(response_or_html):
    """The sidebar's site menu, the top of every page's sidebar."""
    html = getattr(response_or_html, "content", response_or_html)
    if isinstance(html, bytes):
        html = html.decode()
    start = html.index('<details class="site-menu')
    return html[start : html.index("</details>", start)]


class HostClientMixin:
    """GETs on a named site, by URL name in that site's URLconf."""

    def get_on(self, site, viewname, **kwargs):
        host = {sites.GAMES: GAMES_HOST, sites.MUSIC: MUSIC_HOST}.get(site, ROOT_HOST)
        path = sites.site_reverse(site, viewname, kwargs=kwargs or None)
        return self.client.get(path, HTTP_HOST=host, secure=True)

    def get_path_on(self, host, path):
        return self.client.get(path, HTTP_HOST=host, secure=True)


class NoNavigationEntryTests(HostClientMixin, TestCase):
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

    def _assert_no_music_link(self, viewname):
        response = self.get_on(sites.GAMES, viewname)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn(MUSIC_HOST, html)
        self.assertNotIn("Music</span>", html)

    def test_the_games_home_page_does_not_link_to_music(self):
        self._assert_no_music_link("home")

    def test_the_developer_list_does_not_link_to_music(self):
        self._assert_no_music_link("developers-list")

    def test_the_games_source_lists_page_does_not_link_to_music(self):
        self._assert_no_music_link("list-list")

    def test_the_landing_page_does_not_link_to_music(self):
        response = self.get_on(sites.ROOT, "landing")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(MUSIC_HOST, response.content.decode())

    def test_the_site_menu_offers_no_music(self):
        rendered = render_to_string(
            "core/includes/_site_menu.html",
            {"BOOKS_ENABLED": True, "MUSIC_ENABLED": False, "media_type": "games"},
        )
        self.assertNotIn(MUSIC_HOST, rendered)
        self.assertIn("Games", rendered)

    def test_no_sitemap_lists_music(self):
        for host in (GAMES_HOST, ROOT_HOST, MUSIC_HOST):
            with self.subTest(host=host):
                response = self.get_path_on(host, "/sitemap.xml")
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(MUSIC_HOST, response.content.decode())

    def test_the_music_robots_txt_names_no_path(self):
        # robots.txt is public, so a Disallow for a hidden path would be the
        # link this file exists to forbid. The whole host is disallowed.
        content = self.get_path_on(MUSIC_HOST, "/robots.txt").content.decode()
        self.assertIn("User-agent: *\nDisallow: /\n", content)
        self.assertNotIn("import", content)

    def test_music_pages_keep_a_way_back_to_games(self):
        # No switcher yet, so the mobile bar's Games icon and the wordmark
        # are the way out of the beta
        response = self.get_on(sites.MUSIC, "music:home")
        self.assertContains(response, GAMES_HOME)
        self.assertContains(response, 'href="https://acclaimedmedia.org/"')
        self.assertContains(response, "Beta</span>")

    def test_the_games_sidebar_keeps_its_rankings_link(self):
        response = self.get_on(sites.GAMES, "developers-list")
        self.assertContains(response, SIDEBAR_RANKINGS_LINK)


@override_settings(MUSIC_ENABLED=True)
class LaunchedSectionTests(HostClientMixin, TestCase):
    """With ``MUSIC_ENABLED`` on, the other sites lead to music."""

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
        for viewname in ("home", "developers-list", "list-list"):
            with self.subTest(viewname=viewname):
                self.assertContains(self.get_on(sites.GAMES, viewname), MUSIC_HOME)

    def test_the_landing_page_leads_to_both_sites(self):
        response = self.get_on(sites.ROOT, "landing")
        self.assertContains(response, MUSIC_HOME)
        self.assertContains(response, GAMES_HOME)

    def test_the_site_menu_offers_music_without_books(self):
        rendered = render_to_string(
            "core/includes/_site_menu.html",
            {"BOOKS_ENABLED": False, "MUSIC_ENABLED": True, "media_type": "music"},
        )
        self.assertIn(MUSIC_HOME, rendered)
        self.assertIn(GAMES_HOME, rendered)
        self.assertNotIn("/books/", rendered)

    def test_the_mobile_nav_has_a_music_entry(self):
        response = self.get_on(sites.GAMES, "home")
        self.assertContains(response, 'data-nav-item="music"')

    def test_the_games_sidebar_shows_the_site_menu_and_its_rankings_link(self):
        # The menu chooses the site and the links the page
        response = self.get_on(sites.GAMES, "developers-list")
        self.assertContains(response, SIDEBAR_RANKINGS_LINK)
        self.assertContains(response, '<details class="site-menu')

    def test_music_pages_lead_back_through_the_site_menu(self):
        response = self.get_on(sites.MUSIC, "music:home")
        self.assertNotContains(response, SIDEBAR_BACK_TO_GAMES)
        menu = site_menu(response)
        self.assertIn(GAMES_HOME, menu)
        self.assertIn('class="active" aria-current="true">', menu)
        self.assertIn('href="https://acclaimedmedia.org/"', menu)

    def test_the_public_launch_is_still_badged_beta(self):
        response = self.get_on(sites.MUSIC, "music:home")
        self.assertContains(response, "Beta</span>")

    def test_the_music_sitemap_lists_the_section_on_its_own_host(self):
        content = self.get_path_on(MUSIC_HOST, "/sitemap.xml").content.decode()
        self.assertIn("<loc>https://music.acclaimedmedia.org/</loc>", content)
        self.assertIn(
            f"https://music.acclaimedmedia.org{self.album.get_absolute_url()}</loc>",
            content,
        )

    def test_robots_txt_keeps_crawlers_off_the_import_and_csv_pages(self):
        content = self.get_path_on(MUSIC_HOST, "/robots.txt").content.decode()
        self.assertIn("Disallow: /import/", content)
        self.assertIn("Disallow: /download/", content)
        self.assertIn("Sitemap: https://music.acclaimedmedia.org/sitemap.xml", content)

    def test_turning_the_flag_back_off_hides_it_all_again(self):
        self.get_on(sites.GAMES, "home")
        # Production gets this for free: setting a config var restarts the
        # dynos, which empties the per-process page cache.
        clear_all_caches()
        with self.settings(MUSIC_ENABLED=False):
            self.assertNotContains(self.get_on(sites.GAMES, "home"), MUSIC_HOST)
            self.assertNotIn(
                MUSIC_HOST,
                self.get_path_on(MUSIC_HOST, "/sitemap.xml").content.decode(),
            )
            self.assertEqual(self.get_on(sites.MUSIC, "music:home").status_code, 404)


@music_site
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
            reverse("music:import"),
            self.album.get_absolute_url(),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_staff_see_no_import_link_anywhere(self):
        # The import page is reached by typing its URL, not from the chrome
        User.objects.create_user(username="navstaff", password="navpass", is_staff=True)
        self.client.login(username="navstaff", password="navpass")
        import_url = f'href="{reverse("music:import")}"'
        for url in [
            reverse("music:home"),
            reverse("music:list-list"),
            reverse("music:artist-list"),
        ]:
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), import_url)

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


@music_site
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
        match = resolve("/api/saved-filters/", urlconf=settings.SITE_URLCONFS["music"])
        self.assertEqual(match.url_name, "saved-filter-list")


BETA_BADGE = ">Beta</span>"
BETA_NOTICE = "The music site is in beta."


@override_settings(MUSIC_ENABLED=True)
class BetaIsClearThroughoutTests(HostClientMixin, TestCase):
    """The public launch is a beta, and every way into music says so."""

    def setUp(self):
        clear_all_caches()
        self.album = models.Album.objects.create(
            name="Pet Sounds",
            rank=1,
            artist_credit="The Beach Boys",
            year_released=1966,
        )
        self.artist = models.Artist.objects.create(
            name="The Beach Boys", slug="the-beach-boys", source_id=1
        )
        self.album.artists.set([self.artist])

    def music_pages(self):
        return {
            "rankings": self.get_on(sites.MUSIC, "music:home"),
            "album": self.get_path_on(MUSIC_HOST, self.album.get_absolute_url()),
            "artists": self.get_on(sites.MUSIC, "music:artist-list"),
            "artist": self.get_path_on(MUSIC_HOST, self.artist.get_absolute_url()),
            "lists": self.get_on(sites.MUSIC, "music:list-list"),
            "browse": self.get_on(sites.MUSIC, "music:browse"),
            "404": self.get_path_on(MUSIC_HOST, "/no-such-album/"),
        }

    def test_every_music_page_carries_the_notice_and_a_badge(self):
        for name, response in self.music_pages().items():
            with self.subTest(page=name):
                status = 404 if name == "404" else 200
                self.assertContains(response, BETA_NOTICE, status_code=status)
                if name != "404":
                    self.assertContains(response, BETA_BADGE)

    def test_the_notice_asks_for_feedback_through_the_contact_form(self):
        self.assertContains(
            self.get_on(sites.MUSIC, "music:home"),
            'data-message="Feedback on the music beta: ">Send feedback</button>',
        )

    def test_the_games_site_carries_no_notice(self):
        self.assertNotContains(self.get_on(sites.GAMES, "home"), BETA_NOTICE)

    def test_every_link_into_music_is_marked_beta(self):
        games = self.get_on(sites.GAMES, "home").content.decode()
        # The sidebar's site menu
        menu = site_menu(games)
        self.assertIn(BETA_BADGE, menu[menu.index(MUSIC_HOME) :])
        # The games mobile bar's Music icon, and its overflow-menu label
        self.assertIn('data-menu-label="Music (beta)"', games)
        self.assertIn('aria-label="Music (beta)"', games)
        # The landing page's Music card
        landing = self.get_on(sites.ROOT, "landing").content.decode()
        card = landing[landing.index('<span class="mdi mdi-album') :]
        self.assertIn(BETA_BADGE, card[: card.index("</h2>")])
        self.assertIn("<strong>New, and in beta:</strong>", card)

    def test_the_music_site_names_itself_beta_in_the_site_menu(self):
        menu = site_menu(self.get_on(sites.MUSIC, "music:home"))
        summary = menu[: menu.index("</summary>")]
        self.assertIn("Music", summary)
        self.assertIn(BETA_BADGE, summary)

    def test_turning_the_beta_off_removes_every_marker(self):
        with mock.patch.object(config, "MUSIC_BETA", False):
            for name, response in self.music_pages().items():
                with self.subTest(page=name):
                    status = 404 if name == "404" else 200
                    self.assertNotContains(response, BETA_NOTICE, status_code=status)
                    self.assertNotContains(response, BETA_BADGE, status_code=status)
            clear_all_caches()
            games = self.get_on(sites.GAMES, "home")
            self.assertNotContains(games, BETA_BADGE)
            self.assertContains(games, 'data-menu-label="Music"')

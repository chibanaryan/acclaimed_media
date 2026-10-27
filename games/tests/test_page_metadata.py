"""Each page's description and social card say what is on it."""

import re

from django.contrib.flatpages.models import FlatPage
from django.contrib.sites.models import Site
from django.test import TestCase

from core.tests.utils import clear_all_caches
from games.models import Developer, Game

META = re.compile(r'<meta (?:name|property)="([^"]+)" content="([^"]*)"')


def metadata(response):
    return dict(META.findall(response.content.decode()))


class PageMetadataTests(TestCase):
    def setUp(self):
        clear_all_caches()

    def test_developer_pages_describe_the_developer(self):
        developer = Developer.objects.create(name="Valve", slug="valve", igdb_id=1)
        for rank, name in ((5, "Half-Life 2"), (40, "Portal")):
            game = Game.objects.create(
                name=name,
                slug=name.lower().replace(" ", "-"),
                rank=rank,
                year_of_release=2004,
            )
            game.developers.add(developer)

        meta = metadata(self.client.get("/developers/valve/"))

        self.assertEqual(
            meta["description"],
            "Valve has 2 games among the most critically acclaimed video games "
            "of all time, led by Half-Life 2 (#5).",
        )
        self.assertEqual(meta["og:title"], "Valve | Acclaimed Video Games")
        self.assertIn("Valve: 2 games", meta["og:description"])

    def test_list_pages_and_flat_pages_have_their_own_descriptions(self):
        page = FlatPage.objects.create(
            url="/about/", title="About", content="**Acclaimed** ranks games."
        )
        page.sites.add(Site.objects.get_current())
        home = metadata(self.client.get("/"))["description"]

        for url, expected in (
            ("/developers/", "studios and publishers"),
            ("/lists/", "critics' lists"),
            ("/page/about/", "Acclaimed ranks games."),
        ):
            with self.subTest(url=url):
                description = metadata(self.client.get(url))["description"]
                self.assertIn(expected, description)
                self.assertNotEqual(description, home)

    def test_x_reads_the_open_graph_tags(self):
        """No twitter:title/description/image, which drifted from og:*."""
        Game.objects.create(name="Doom", slug="doom", rank=1, year_of_release=1993)

        for url in ("/", "/game/doom/"):
            with self.subTest(url=url):
                meta = metadata(self.client.get(url))
                self.assertEqual(meta["twitter:card"], "summary_large_image")
                for tag in ("twitter:title", "twitter:description", "twitter:image"):
                    self.assertNotIn(tag, meta)
                self.assertIn("og:image", meta)


class ErrorPageTests(TestCase):
    def test_a_server_error_renders_the_site_page_not_djangos_bare_text(self):
        from django.test import RequestFactory
        from django.views.defaults import server_error

        response = server_error(RequestFactory().get("/"))

        self.assertEqual(response.status_code, 500)
        body = response.content.decode()
        self.assertIn("Something went wrong", body)
        self.assertIn("css/dist/styles", body)

    def test_the_404_heading_reads_as_404(self):
        body = self.client.get("/no-such-page-here/").content.decode()
        self.assertIn('alt="0"', body)
        self.assertNotIn('alt="Moon"', body)


class CoverPlaceholderTests(TestCase):
    """A game with no cover shows the placeholder, on both render paths."""

    def setUp(self):
        clear_all_caches()

    def test_server_rendered_rows_never_write_src_none(self):
        Game.objects.create(name="Coverless", slug="coverless", rank=1)

        body = self.client.get("/").content.decode()

        self.assertNotIn('src="None"', body)
        self.assertIn("games/images/cover-placeholder.svg", body)

    def test_the_client_renderer_is_given_the_placeholder(self):
        """GameListRenderer returns `_staticUrls.placeholder` for a game with
        no artwork; home.html never set it, so the client wrote
        src="undefined"."""
        Game.objects.create(name="Coverless", slug="coverless", rank=1)

        body = self.client.get("/").content.decode()
        static_urls = body[body.index("window.staticUrls = {") :][:600]

        self.assertIn("placeholder:", static_urls)
        self.assertIn("cover-placeholder.svg", static_urls)


class HomeScreenIconTests(TestCase):
    def test_the_page_names_a_touch_icon_and_theme_colours(self):
        from django.contrib.staticfiles import finders

        body = self.client.get("/").content.decode()
        self.assertIn('rel="apple-touch-icon"', body)
        self.assertEqual(body.count('name="theme-color"'), 2)
        self.assertTrue(finders.find("games/brand/apple-touch-icon.png"))


class FlatPageDescriptionTests(TestCase):
    def test_an_ampersand_is_not_escaped_twice(self):
        """striptags on markdown's HTML kept its &amp;, and autoescape made it
        &amp;amp;, so search results read "Q&amp;A"."""
        page = FlatPage.objects.create(
            url="/faq/", title="FAQ", content="**Q&A** about the rankings"
        )
        page.sites.add(Site.objects.get_current())

        meta = metadata(self.client.get("/page/faq/"))

        self.assertEqual(meta["description"], "Q&amp;A about the rankings")

"""
Tests for sitemap configuration.

These tests directly test the sitemap classes to ensure coverage
of their methods beyond the integration tests in test_main_views.py.
"""

from django.contrib.flatpages.models import FlatPage
from django.contrib.sites.models import Site
from django.test import TestCase
from django.urls import reverse

from core.tests.utils import clear_all_caches
from games.models import Article, Developer, Game
from core.sitemaps import root_sitemaps
from games.sitemaps import (
    ArticleSitemap,
    DeveloperSitemap,
    GameSitemap,
    PageSitemap,
    StaticViewSitemap,
    sitemaps,
)


class StaticViewSitemapTests(TestCase):
    """Tests for the StaticViewSitemap class."""

    def setUp(self):
        self.sitemap = StaticViewSitemap()

    def test_items_returns_expected_pages(self):
        """Test that items() returns the correct static page names."""
        items = self.sitemap.items()
        self.assertEqual(
            items, ["home", "developers-list", "list-list", "article-list"]
        )

    def test_location_returns_valid_urls(self):
        """Test that location() returns valid URLs for each item."""
        for item in self.sitemap.items():
            location = self.sitemap.location(item)
            self.assertTrue(location.startswith("/"))
            self.assertEqual(location, reverse(item))

    def test_priority_is_set(self):
        """Test that priority is correctly set."""
        self.assertEqual(self.sitemap.priority, 0.5)

    def test_changefreq_is_set(self):
        """Test that changefreq is correctly set."""
        self.assertEqual(self.sitemap.changefreq, "weekly")


class GameSitemapTests(TestCase):
    """Tests for the GameSitemap class."""

    def setUp(self):
        self.sitemap = GameSitemap()
        self.game1 = Game.objects.create(
            name="Test Game 1",
            slug="test-game-1",
            rank=1,
        )
        self.game2 = Game.objects.create(
            name="Test Game 2",
            slug="test-game-2",
            rank=2,
        )

    def test_items_returns_all_games(self):
        """Test that items() returns all games."""
        items = list(self.sitemap.items())
        self.assertEqual(len(items), 2)
        self.assertIn(self.game1, items)
        self.assertIn(self.game2, items)

    def test_location_returns_game_detail_url(self):
        """Test that location() returns the correct game detail URL."""
        location = self.sitemap.location(self.game1)
        expected = reverse("game-detail", kwargs={"slug": self.game1.slug})
        self.assertEqual(location, expected)

    def test_lastmod_is_the_games_modified_time(self):
        """It read `updated_at`, which Game does not have, so no game URL
        carried a <lastmod>; the test that covered it used a mock."""
        self.assertIsNotNone(self.game1.modified)
        self.assertEqual(self.sitemap.lastmod(self.game1), self.game1.modified)

    def test_priority_is_set(self):
        """Test that priority is correctly set."""
        self.assertEqual(self.sitemap.priority, 0.8)

    def test_changefreq_is_set(self):
        """Test that changefreq is correctly set."""
        self.assertEqual(self.sitemap.changefreq, "monthly")


class DeveloperSitemapTests(TestCase):
    """Tests for the DeveloperSitemap class."""

    def setUp(self):
        self.sitemap = DeveloperSitemap()
        self.dev1 = Developer.objects.create(name="Test Dev 1", slug="test-dev-1")
        self.dev2 = Developer.objects.create(name="Test Dev 2", slug="test-dev-2")

    def test_items_returns_developers_with_slugs(self):
        """Test that items() returns only developers with slugs."""
        items = list(self.sitemap.items())
        self.assertEqual(len(items), 2)
        self.assertIn(self.dev1, items)
        self.assertIn(self.dev2, items)

    def test_items_excludes_developers_without_slugs(self):
        """Test that items() excludes subsidiary developers without slugs."""
        # Create a subsidiary developer without a slug
        subsidiary = Developer.objects.create(
            name="Subsidiary Dev", slug="", parent=self.dev1
        )
        items = list(self.sitemap.items())
        self.assertEqual(len(items), 2)
        self.assertNotIn(subsidiary, items)

    def test_location_returns_developer_detail_url(self):
        """Test that location() returns the correct developer detail URL."""
        location = self.sitemap.location(self.dev1)
        expected = reverse("developer-detail", kwargs={"slug": self.dev1.slug})
        self.assertEqual(location, expected)

    def test_priority_is_set(self):
        """Test that priority is correctly set."""
        self.assertEqual(self.sitemap.priority, 0.6)

    def test_changefreq_is_set(self):
        """Test that changefreq is correctly set."""
        self.assertEqual(self.sitemap.changefreq, "monthly")


class SitemapsConfigurationTests(TestCase):
    """Tests for the sitemaps dictionary configuration."""

    def test_sitemaps_dict_has_expected_keys(self):
        """Test that the sitemaps dict has all expected keys."""
        self.assertIn("static", sitemaps)
        self.assertIn("games", sitemaps)
        self.assertIn("developers", sitemaps)

    def test_sitemaps_dict_has_correct_classes(self):
        """Test that the sitemaps dict maps to correct classes."""
        self.assertEqual(sitemaps["static"], StaticViewSitemap)
        self.assertEqual(sitemaps["games"], GameSitemap)
        self.assertEqual(sitemaps["developers"], DeveloperSitemap)
        self.assertEqual(sitemaps["articles"], ArticleSitemap)
        # The shared pages are listed once, on the apex their canonical
        # links name, not on every site that serves them
        self.assertNotIn("pages", sitemaps)
        self.assertTrue(issubclass(root_sitemaps["pages"], PageSitemap))


class ArticleSitemapTests(TestCase):
    def test_lists_only_published_articles_with_their_update_time(self):
        published = Article.objects.create(
            title="Published", slug="published", status=Article.Status.PUBLISHED
        )
        Article.objects.create(title="Draft", slug="draft")

        sitemap = ArticleSitemap()

        self.assertEqual(list(sitemap.items()), [published])
        self.assertEqual(sitemap.location(published), "/blog/published/")
        self.assertEqual(sitemap.lastmod(published), published.updated_at)


class PageSitemapTests(TestCase):
    def _page(self, url, **kwargs):
        page = FlatPage.objects.create(url=url, title=url, **kwargs)
        page.sites.add(Site.objects.get_current())
        return page

    def test_lists_pages_at_the_address_the_site_links(self):
        self._page("/about/")
        self._page("/page/about/")  # the same page by the other address
        self._page("/page/donate/")
        self._page("/members/", registration_required=True)
        self._page("/deep/nested/")
        self._page("/terms.html/")  # <slug:slug> cannot reverse this
        self._page("/no-slash")  # PageDetailView would not find this
        other_site = Site.objects.create(domain="other.example", name="Other")
        FlatPage.objects.create(url="/elsewhere/", title="x").sites.add(other_site)

        sitemap = PageSitemap()

        self.assertEqual(sitemap.items(), ["about", "donate"])
        self.assertEqual(
            [sitemap.location(item) for item in sitemap.items()],
            ["/page/about/", "/page/donate/"],
        )


class SitemapXmlTests(TestCase):
    def setUp(self):
        clear_all_caches()

    def test_game_urls_carry_a_lastmod(self):
        Game.objects.create(name="Doom", slug="doom", rank=1, year_of_release=1993)

        content = self.client.get("/sitemap.xml").content.decode()

        self.assertIn("/game/doom/</loc><lastmod>", content)

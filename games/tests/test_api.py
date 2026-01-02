from django.contrib.flatpages.models import FlatPage
from django.test import TestCase
from rest_framework.test import APIClient

from .. import models
from ..api import serializers


class GameListApiTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.platform_pc = models.Platform.objects.create(code="PC", name="PC")
        self.platform_ps = models.Platform.objects.create(code="PS", name="PlayStation")
        self.genre_action = models.IGDBGenre.objects.create(name="Action")
        self.genre_adventure = models.IGDBGenre.objects.create(name="Adventure")

        self.developer = models.Developer.objects.create(
            name="Studio", slug="studio", igdb_id=10
        )

        self.game1 = models.Game.objects.create(
            name="Alpha Quest",
            rank=1,
            igdb_id=1001,
            year_of_release=2000,
            slug="alpha-quest",
        )
        self.game1.platforms.add(self.platform_pc)
        self.game1.genres.add(self.genre_action)
        self.game1.developers.add(self.developer)

        self.game2 = models.Game.objects.create(
            name="Beta Saga",
            rank=2,
            igdb_id=1002,
            year_of_release=2010,
            slug="beta-saga",
        )
        self.game2.platforms.add(self.platform_ps)
        self.game2.genres.add(self.genre_adventure)

    def _get_game_names(self, **params):
        response = self.client.get("/api/games/", params)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        results = data["results"] if "results" in data else data
        return [item["name"] for item in results]

    def test_filter_by_platform(self):
        names = self._get_game_names(platforms=str(self.platform_ps.id))
        self.assertEqual(names, ["Beta Saga"])

    def test_filter_by_single_genre(self):
        """Single genre filter should work (single-select mode)."""
        self.game2.genres.add(self.genre_action)
        names = self._get_game_names(genres=str(self.genre_action.id))
        self.assertCountEqual(names, ["Alpha Quest", "Beta Saga"])

    def test_filter_by_developer(self):
        names = self._get_game_names(developer=str(self.developer.igdb_id))
        self.assertEqual(names, ["Alpha Quest"])

    def test_order_by_parameter_applies(self):
        names = self._get_game_names(order_by="-year_of_release")
        self.assertEqual(names, ["Beta Saga", "Alpha Quest"])


class ApiSmokeTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.publication = models.Publication.objects.create(name="IGN")
        self.list = models.List.objects.create(
            publisher=self.publication,
            name="Top 10",
            year=2020,
            type="E",
        )
        self.developer = models.Developer.objects.create(
            name="Studio", slug="studio", igdb_id=200
        )
        self.post = models.Post.objects.create(title="News", text="Hello", active=True)
        models.Snippet.objects.create(slug="about", text="About text")
        models.Snippet.objects.create(slug="donate", text="Donate info")
        self.game = models.Game.objects.create(
            name="Alpha Quest",
            rank=1,
            igdb_id=1234,
            year_of_release=2000,
        )
        self.game.developers.add(self.developer)
        self.flatpage = FlatPage.objects.create(
            url="/faq/", title="FAQ", content="**Docs**"
        )

    def test_lists_endpoint(self):
        resp = self.client.get("/api/lists/")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["count"], 1)

    def test_developer_detail_endpoint(self):
        resp = self.client.get(f"/api/developers/{self.developer.slug}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Studio")

    def test_meta_endpoint(self):
        resp = self.client.get("/api/meta/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Check games data structure
        self.assertIn("games", data)
        self.assertIn("years", data["games"])
        self.assertIn("decades", data["games"])
        self.assertIn("last_update", data["games"])

        # Check lists data structure with total_count
        self.assertIn("lists", data)
        self.assertIn("years", data["lists"])
        self.assertIn("total_count", data["lists"])
        self.assertIsInstance(data["lists"]["total_count"], int)
        self.assertGreaterEqual(data["lists"]["total_count"], 1)

        # Check publications data structure with total_count
        self.assertIn("publications", data)
        self.assertIn("total_count", data["publications"])
        self.assertIsInstance(data["publications"]["total_count"], int)
        self.assertGreaterEqual(data["publications"]["total_count"], 1)

    def test_snippet_endpoint(self):
        resp = self.client.get("/api/snippets/about/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("snippet", resp.json())

    def test_page_endpoint_returns_404_for_missing(self):
        resp = self.client.get("/api/pages/missing/")
        self.assertEqual(resp.status_code, 404)

    def test_page_endpoint_returns_content(self):
        resp = self.client.get("/api/pages/faq/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["title"], "FAQ")

    def test_platforms_endpoint(self):
        resp = self.client.get("/api/platforms/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results", resp.json())

    def test_genres_endpoint(self):
        resp = self.client.get("/api/genres/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results", resp.json())

    def test_developer_alias_search_filters_results(self):
        resp = self.client.get("/api/developer-aliases/", {"q": "Studio"})
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["count"], 1)

    def test_publication_detail_endpoint(self):
        resp = self.client.get(f"/api/publications/{self.publication.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "IGN")


class SerializerBehaviorTests(TestCase):

    def test_game_detail_serializer_lists_field(self):
        publication = models.Publication.objects.create(name="IGN")
        lst = models.List.objects.create(
            publisher=publication,
            name="Top 10",
            year=2020,
            type="E",
            order=1,
        )
        game = models.Game.objects.create(
            name="Sample", rank=1, igdb_id=1010, year_of_release=2020
        )
        models.ListMembership.objects.create(list=lst, game=game, rank=1)
        data = serializers.GameDetailSerializer(game).data
        self.assertEqual(len(data["lists"]), 1)
        self.assertEqual(data["lists"][0]["publication"], "IGN")

    def test_page_serializer_renders_markdown(self):
        page = FlatPage.objects.create(url="/terms/", title="Terms", content="**Hi**")
        serializer = serializers.PageSerializer(page)
        self.assertIn("<strong>Hi</strong>", serializer.data["content"])


class GameSearchAPIViewTests(TestCase):
    """Test the GameSearchAPIView (navbar search endpoint)."""

    def setUp(self):
        self.client = APIClient()

        # Create test developer
        self.developer = models.Developer.objects.create(
            name="Test Developer", slug="test-dev", igdb_id=10
        )

        self.game1 = models.Game.objects.create(
            name="The Legend of Zelda",
            rank=1,
            year_of_release=1986,
            slug="zelda",
        )
        self.game1.developers.add(self.developer)

        self.game2 = models.Game.objects.create(
            name="Zelda II: The Adventure of Link",
            rank=50,
            year_of_release=1987,
            slug="zelda-2",
        )
        self.game2.developers.add(self.developer)

        self.game3 = models.Game.objects.create(
            name="Super Mario Bros",
            rank=2,
            year_of_release=1985,
            slug="mario",
        )

    def test_search_with_valid_query(self):
        """Test searching with a valid query returns results."""
        response = self.client.get("/api/games/search/", {"q": "zelda"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("results", data)
        self.assertIn("count", data)
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["results"]), 2)

    def test_search_returns_correct_fields(self):
        """Test that search results contain expected fields."""
        response = self.client.get("/api/games/search/", {"q": "zelda"})
        data = response.json()
        result = data["results"][0]
        self.assertIn("id", result)
        self.assertIn("name", result)
        self.assertIn("slug", result)
        self.assertIn("year_of_release", result)
        self.assertIn("rank", result)
        self.assertIn("thumbnail", result)

    def test_search_with_short_query_returns_empty(self):
        """Test that queries less than 2 characters return empty results."""
        response = self.client.get("/api/games/search/", {"q": "z"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(len(data["results"]), 0)

    def test_search_without_query_returns_empty(self):
        """Test that no query parameter returns empty results."""
        response = self.client.get("/api/games/search/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 0)

    def test_search_with_empty_query_returns_empty(self):
        """Test that empty query returns empty results."""
        response = self.client.get("/api/games/search/", {"q": ""})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 0)

    def test_search_with_limit(self):
        """Test that limit parameter works."""
        response = self.client.get("/api/games/search/", {"q": "zelda", "limit": 1})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(len(data["results"]), 1)

    def test_search_orders_by_rank(self):
        """Test that search results are ordered by rank."""
        response = self.client.get("/api/games/search/", {"q": "zelda"})
        data = response.json()
        # Game1 has rank=1, Game2 has rank=50
        self.assertEqual(data["results"][0]["name"], "The Legend of Zelda")
        self.assertEqual(data["results"][1]["name"], "Zelda II: The Adventure of Link")

    def test_search_case_insensitive(self):
        """Test that search is case insensitive."""
        response = self.client.get("/api/games/search/", {"q": "ZELDA"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)

    def test_search_partial_match(self):
        """Test that search matches partial names."""
        response = self.client.get("/api/games/search/", {"q": "mario"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["name"], "Super Mario Bros")


class UnifiedSearchViewTests(TestCase):
    """Test the UnifiedSearchView for unified navbar search."""

    def setUp(self):
        self.client = APIClient()

        # Create test developers (root developers with subsidiaries)
        self.nintendo = models.Developer.objects.create(
            name="Nintendo", slug="nintendo", igdb_id=10
        )
        self.nintendo_ead = models.Developer.objects.create(
            parent=self.nintendo, name="Nintendo EAD", igdb_id=11
        )

        self.capcom = models.Developer.objects.create(
            name="Capcom", slug="capcom", igdb_id=20
        )
        self.capcom_studio = models.Developer.objects.create(
            parent=self.capcom, name="Capcom Production Studio 4", igdb_id=21
        )

        # Independent developer with no parent (but also no slug, so no detail page)
        self.indie_dev = models.Developer.objects.create(
            name="Indie Dev Studio", igdb_id=30
        )

        # Create test games
        self.game1 = models.Game.objects.create(
            name="The Legend of Zelda",
            rank=1,
            year_of_release=1986,
            slug="zelda",
        )
        self.game1.developers.add(self.nintendo_ead)

        self.game2 = models.Game.objects.create(
            name="Super Mario Bros",
            rank=2,
            year_of_release=1985,
            slug="mario",
        )
        self.game2.developers.add(self.nintendo_ead)

        self.game3 = models.Game.objects.create(
            name="Street Fighter II",
            rank=5,
            year_of_release=1991,
            slug="sf2",
        )
        self.game3.developers.add(self.capcom_studio)

    def test_unified_search_returns_both_developers_and_games(self):
        """Test that unified search returns both developers and games."""
        response = self.client.get("/api/unified-search/", {"q": "nintendo"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("developers", data)
        self.assertIn("games", data)

    def test_unified_search_developer_results_have_correct_fields(self):
        """Test that developer results contain expected fields."""
        response = self.client.get("/api/unified-search/", {"q": "nintendo"})
        data = response.json()
        self.assertGreater(len(data["developers"]), 0)
        dev = data["developers"][0]
        self.assertIn("id", dev)
        self.assertIn("name", dev)
        self.assertIn("root_slug", dev)
        self.assertIn("games_count", dev)

    def test_unified_search_game_results_have_correct_fields(self):
        """Test that game results contain expected fields."""
        response = self.client.get("/api/unified-search/", {"q": "zelda"})
        data = response.json()
        self.assertGreater(len(data["games"]), 0)
        game = data["games"][0]
        self.assertIn("id", game)
        self.assertIn("name", game)
        self.assertIn("slug", game)
        self.assertIn("year_of_release", game)
        self.assertIn("rank", game)
        self.assertIn("thumbnail", game)

    def test_unified_search_with_short_query_returns_empty(self):
        """Test that queries less than 2 characters return empty results."""
        response = self.client.get("/api/unified-search/", {"q": "n"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["developers"]), 0)
        self.assertEqual(len(data["games"]), 0)

    def test_unified_search_respects_limits(self):
        """Test that developer_limit and game_limit parameters work."""
        response = self.client.get(
            "/api/unified-search/",
            {"q": "nintendo", "developer_limit": 1, "game_limit": 1},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertLessEqual(len(data["developers"]), 1)
        self.assertLessEqual(len(data["games"]), 1)

    def test_unified_search_excludes_independent_studios(self):
        """Test that studios without a parent company are not included."""
        # Search for indie studio by name - should not appear in results
        response = self.client.get("/api/unified-search/", {"q": "indie"})
        data = response.json()
        # The indie studio should not appear in developer results
        for dev in data["developers"]:
            self.assertNotEqual(dev["name"], "Indie Dev Studio")

    def test_unified_search_developers_ordered_by_games_count(self):
        """Test that developer results are ordered by games count descending."""
        # Nintendo EAD has 2 games, Capcom has 1 game
        response = self.client.get("/api/unified-search/", {"q": "studio"})
        data = response.json()
        if len(data["developers"]) > 1:
            # First developer should have more or equal games than second
            self.assertGreaterEqual(
                data["developers"][0]["games_count"],
                data["developers"][1]["games_count"],
            )

    def test_unified_search_games_ordered_by_rank(self):
        """Test that game results are ordered by rank."""
        response = self.client.get("/api/unified-search/", {"q": "the"})
        data = response.json()
        if len(data["games"]) > 1:
            # First game should have lower rank (better) than second
            self.assertLessEqual(data["games"][0]["rank"], data["games"][1]["rank"])


class GameFilterDataViewTests(TestCase):
    """Test the GameFilterDataView endpoint for client-side filtering."""

    def setUp(self):
        self.client = APIClient()
        # Use get_or_create since migrations may have already created genres
        self.genre, _ = models.WikipediaGenre.objects.get_or_create(
            slug="test-filter-action", defaults={"name": "Test Action"}
        )
        self.platform, _ = models.Platform.objects.get_or_create(
            code="TFPC", defaults={"name": "Test Filter PC"}
        )
        self.series = models.Series.objects.create(
            name="Test Filter Series", slug="test-filter-series", igdb_id=99999
        )
        self.game = models.Game.objects.create(
            name="Test Filter Game",
            rank=1,
            igdb_id=9999,
            year_of_release=2020,
            slug="test-filter-game",
        )
        self.game.wikipedia_genres.add(self.genre)
        self.game.platforms.add(self.platform)
        self.game.series.add(self.series)

    def test_filter_data_returns_games_array(self):
        """Test that filter data endpoint returns games array."""
        response = self.client.get("/api/games/filter-data/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("games", data)
        self.assertIn("version", data)
        # Should have at least our test game
        self.assertGreaterEqual(len(data["games"]), 1)

    def test_filter_data_has_correct_fields(self):
        """Test that game data has all required filter fields."""
        response = self.client.get("/api/games/filter-data/")
        data = response.json()
        # Find our test game by ID
        game = next((g for g in data["games"] if g["id"] == self.game.id), None)
        self.assertIsNotNone(game, "Test game not found in filter data")
        # Check all abbreviated fields are present
        self.assertEqual(game["id"], self.game.id)
        self.assertEqual(game["y"], 2020)  # year
        self.assertEqual(game["n"], "test filter game")  # name (lowercase)
        self.assertEqual(game["g"], [self.genre.id])  # genres
        self.assertEqual(game["p"], [self.platform.id])  # platforms
        self.assertEqual(game["s"], [self.series.id])  # series
        self.assertEqual(game["i"], 9999)  # igdb_id
        self.assertEqual(game["r"], 1)  # rank


class GameDataVersionViewTests(TestCase):
    """Test the GameDataVersionView endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.game = models.Game.objects.create(
            name="Test Game",
            rank=1,
            year_of_release=2020,
            slug="test-game",
        )

    def test_version_endpoint_returns_version(self):
        """Test that version endpoint returns a version hash."""
        response = self.client.get("/api/games/version/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("version", data)
        self.assertIsInstance(data["version"], str)
        self.assertEqual(len(data["version"]), 12)  # MD5 hash truncated to 12 chars

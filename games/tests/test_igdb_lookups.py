"""The IGDB lookups a single game goes through, where they used to fail.

`IgbdApi.get_game_info_by_id`, `Game.get_igdb_data`, the admin's Save and
the importer's one-game path.
"""

import threading
from collections import OrderedDict
from unittest import mock

import requests
from django.contrib.admin.sites import AdminSite
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from core.models import User
from games import admin, igdb, models
from games.services import igdb_importer
from games.services.igdb_importer import IGDBImportService


class Response:
    """A `requests` response, as far as the client reads one."""

    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = [] if body is None else body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")


def bare_api():
    """An `IgbdApi` that has not authenticated or loaded its lookups."""
    api = igdb.IgbdApi.__new__(igdb.IgbdApi)
    api.headers = {}
    api.company_cache = OrderedDict()
    api.game_cache = OrderedDict()
    api.company_cache_max_size = 1000
    api.game_cache_max_size = 1000
    api.release_date_statuses = {}
    api.release_dates = {}
    api.themes = {}
    api.rate_limit_lock = threading.Lock()
    api.cache_lock = threading.Lock()
    api.use_pro_tier = False
    api.min_request_interval = 0
    api.last_request_time = 0.0
    return api


class RequestTests(SimpleTestCase):
    def test_a_request_carries_a_timeout(self):
        """IGDB accepting a connection and then stalling held the thread."""
        api = bare_api()
        with mock.patch.object(igdb.requests, "post", return_value=Response()) as post:
            api._make_request_with_retry("https://api.igdb.com/v4/games", "fields id;")
        self.assertEqual(post.call_args.kwargs["timeout"], igdb.REQUEST_TIMEOUT)


class GameInfoByIdTests(SimpleTestCase):
    def setUp(self):
        self.api = bare_api()

    def lookup(self, *responses):
        with mock.patch.object(
            self.api, "_make_request_with_retry", side_effect=list(responses)
        ) as request:
            result = self.api.get_game_info_by_id(7, cache_results=False)
        return result, request

    def test_a_401_after_a_new_token_is_not_asked_a_third_time(self):
        """It recursed for as long as IGDB went on answering 401."""
        with mock.patch.object(self.api, "_get_auth_token", return_value=True) as auth:
            result, request = self.lookup(Response(401), Response(401))
        self.assertIsNone(result)
        self.assertEqual(auth.call_count, 1)
        self.assertEqual(request.call_count, 2)

    def test_a_401_is_retried_once_with_a_new_token(self):
        game = {"id": 7, "slug": "seven", "involved_companies": []}
        with (
            mock.patch.object(self.api, "_get_auth_token", return_value=True),
            mock.patch.object(self.api, "get_companies_by_ids", return_value={}),
        ):
            result, request = self.lookup(Response(401), Response(200, [game]))
        self.assertEqual(result["slug"], "seven")
        self.assertEqual(request.call_count, 2)

    def test_an_error_body_is_not_read_as_games(self):
        """A 500's `{"message": ...}` counted as one game; a list of two
        error entries as a game IGDB had dropped."""
        for body in ({"message": "Internal error"}, [{"status": 500}, {"title": "x"}]):
            with self.subTest(body=body):
                result, _ = self.lookup(Response(500, body))
                self.assertIsNone(result)

    def test_a_body_that_is_no_list_is_not_read_as_games(self):
        result, _ = self.lookup(Response(200, {"message": "maintenance"}))
        self.assertIsNone(result)

    def test_an_id_igdb_has_dropped_is_still_named(self):
        with self.assertRaises(igdb.GameNotFound):
            self.lookup(Response(200, []))


class GetIgdbDataTests(TestCase):
    def setUp(self):
        self.game = models.Game.objects.create(
            name="Alpha Quest", rank=1, igdb_id=7, slug="alpha-quest"
        )
        self.studio = models.Developer.objects.create(name="Studio", igdb_id=70)
        self.game.developers.set([self.studio])

    def test_a_transient_failure_leaves_the_game_as_it_was(self):
        """A failed fetch answers None, which was then read with `.get`."""
        api = mock.Mock()
        api.get_game_info_by_id.return_value = None
        self.game.get_igdb_data(api_client=api)
        self.game.refresh_from_db()
        self.assertEqual(self.game.slug, "alpha-quest")
        self.assertEqual(list(self.game.developers.all()), [self.studio])

    def test_the_first_record_is_fetched_once(self):
        """It was fetched again for the developers: a request a game."""
        api = mock.Mock()
        api.get_game_info_by_id.return_value = {
            "slug": "alpha-quest",
            "cover": "co1",
            "url": "https://www.igdb.com/games/alpha-quest",
            "developers": [{"id": 71, "name": "Other Studio", "slug": "other"}],
            "series": [{"id": 5, "name": "Alpha", "slug": "alpha"}],
        }
        self.game.get_igdb_data(api_client=api)
        self.assertEqual(api.get_game_info_by_id.call_count, 1)
        self.assertEqual([d.name for d in self.game.developers.all()], ["Other Studio"])
        self.assertEqual([s.name for s in self.game.series.all()], ["Alpha"])
        self.game.refresh_from_db()
        self.assertEqual(self.game.primary_igdb_game_data.artwork_id, "co1")


class AdminSaveTests(TestCase):
    def setUp(self):
        self.admin = admin.GameAdmin(models.Game, AdminSite())

    def save(self, game, api):
        with (
            mock.patch.object(models.igdb, "get_api", return_value=api),
            mock.patch.object(self.admin, "message_user") as message_user,
        ):
            self.admin.save_model(request=None, obj=game, form=None, change=False)
        return message_user

    def test_an_id_igdb_has_dropped_keeps_the_edit_and_says_so(self):
        """`GameNotFound` was a 500, and the edit was lost with it."""
        game = models.Game.objects.create(name="Alpha Quest", rank=1, igdb_id=7)
        game.name = "Alpha Quest II"
        api = mock.Mock()
        api.get_game_info_by_id.side_effect = igdb.GameNotFound("0 games")

        message_user = self.save(game, api)

        game.refresh_from_db()
        self.assertEqual(game.name, "Alpha Quest II")
        self.assertIn("IGDB has no game under id 7", message_user.call_args.args[1])

    def test_a_game_can_be_added_with_an_igdb_id(self):
        """The fetch filed its record under a game that had no row yet."""
        api = mock.Mock()
        api.get_game_info_by_id.return_value = {
            "slug": "new-game",
            "cover": "co2",
            "url": "",
            "developers": [],
            "series": [],
        }
        game = models.Game(name="New Game", rank=2, igdb_id=8)

        message_user = self.save(game, api)

        game.refresh_from_db()
        self.assertEqual(game.slug, "new-game")
        self.assertEqual(game.primary_igdb_game_data.igdb_id, 8)
        message_user.assert_not_called()


class ImporterOneGamePathTests(TestCase):
    def test_an_id_igdb_has_dropped_is_named_not_logged_as_a_failure(self):
        game = models.Game.objects.create(name="Alpha Quest", rank=1, igdb_id=7)
        api = mock.MagicMock(max_batch_size=50)
        with mock.patch.object(igdb_importer, "get_api", return_value=api):
            service = IGDBImportService()
        with (
            mock.patch.object(
                models.Game, "get_igdb_data", side_effect=igdb.GameNotFound("0 games")
            ),
            self.assertNoLogs(igdb_importer.logger, level="WARNING"),
        ):
            success, _, error = service._process_game(game)
        self.assertFalse(success)
        self.assertEqual(error, igdb_importer.NOT_IN_IGDB)
        self.assertEqual(service.error_count, 1)


class MetadataChangelistQueryTests(TestCase):
    """The IGDB, Wikipedia and HLTB record lists name each row's game."""

    def setUp(self):
        staff = User.objects.create_superuser(
            username="staff", password="pw", email="staff@example.com"
        )
        self.client.force_login(staff)
        self.made = 0

    def keys(self, model):
        """The id column each record is keyed on: Wikipedia's has no IGDB id."""
        if model is models.WikipediaGameData:
            return {"wikidata_id": f"Q{self.made}"}
        return {"igdb_id": self.made}

    def add_rows(self, model, count):
        for _ in range(count):
            self.made += 1
            game = models.Game.objects.create(
                name=f"Game {self.made}", rank=self.made, igdb_id=self.made
            )
            model.objects.create(game=game, is_primary=True, **self.keys(model))

    def queries(self, url):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(captured)

    def test_a_row_costs_no_query_of_its_own(self):
        for model in (
            models.IGDBGameData,
            models.WikipediaGameData,
            models.HLTBGameData,
        ):
            with self.subTest(model=model.__name__):
                url = f"/admin/games/{model._meta.model_name}/"
                self.add_rows(model, 2)
                before = self.queries(url)
                self.add_rows(model, 6)
                self.assertEqual(self.queries(url), before)

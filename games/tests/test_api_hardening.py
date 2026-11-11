"""Requests the games API used to answer with a 500, or pay for too dearly."""

import json
from datetime import datetime

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from core.models import User
from core.tests.utils import clear_all_caches
from games import models
from games.models import SavedFilterSet


class MetaEndpointTests(TestCase):
    """`/api/meta/` over games the release gives no year."""

    def setUp(self):
        clear_all_caches()
        self.addCleanup(clear_all_caches)
        models.Game.objects.create(
            name="Dated", rank=1, igdb_id=1, slug="dated", year_of_release=1998
        )

    def games(self):
        response = self.client.get("/api/meta/")
        self.assertEqual(response.status_code, 200)
        return response.json()["games"]

    def test_a_game_without_a_year_is_not_a_500(self):
        models.Game.objects.create(name="Undated", rank=2, igdb_id=2, slug="undated")
        decades = self.games()["decades"]
        self.assertEqual(decades, [{"decade": "1990-99", "count": 1}])

    def test_the_current_year_is_listed(self):
        this_year = datetime.today().year
        models.Game.objects.create(
            name="New", rank=2, igdb_id=2, slug="new", year_of_release=this_year
        )
        years = self.games()["years"]
        self.assertEqual(years[-1], {"year": this_year, "count": 1})


class GenreListQueryTests(TestCase):
    """`/api/genres/` reads its genres in one query, however many have parents."""

    def setUp(self):
        clear_all_caches()
        self.addCleanup(clear_all_caches)
        self.root = models.WikipediaGenre.objects.create(
            name="Zeta Root", slug="zeta-root", level=0
        )

    def add_children(self, count, start=0):
        for i in range(start, start + count):
            models.WikipediaGenre.objects.create(
                name=f"Zeta Child {i}",
                slug=f"zeta-child-{i}",
                level=1,
                parent=self.root,
            )

    def queries(self):
        clear_all_caches()
        with CaptureQueriesContext(connection) as context:
            response = self.client.get("/api/genres/")
        self.assertEqual(response.status_code, 200)
        return len(context)

    def test_a_child_genre_costs_no_query_of_its_own(self):
        self.add_children(2)
        before = self.queries()
        self.add_children(6, start=2)
        self.assertEqual(self.queries(), before)

    def test_a_child_names_its_parent(self):
        self.add_children(1)
        rows = self.client.get("/api/genres/").json()["results"]
        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["Zeta Child 0"]["parent_id"], self.root.id)
        self.assertIsNone(by_name["Zeta Root"]["parent_id"])


class CachedApiKeepsNoCallerWrittenKeysTests(TestCase):
    """A query string is the caller's to write, so it is no cache key.

    Each distinct one was two rows in the shared cache, which holds 5,000
    and culls a quarter when full: a few thousand `?q=` values pushed out
    the generation keys and the metadata fetch's lock.
    """

    def setUp(self):
        clear_all_caches()
        self.addCleanup(clear_all_caches)
        self.game = models.Game.objects.create(
            name="Alpha Quest", rank=1, igdb_id=1, slug="alpha-quest"
        )

    def name(self, url):
        return self.client.get(url).json()["name"]

    def test_a_bare_path_is_still_kept(self):
        self.assertEqual(self.name("/api/games/alpha-quest/"), "Alpha Quest")
        models.Game.objects.filter(pk=self.game.pk).update(name="Renamed")
        self.assertEqual(self.name("/api/games/alpha-quest/"), "Alpha Quest")

    def test_a_request_with_a_query_string_is_not_kept(self):
        self.assertEqual(self.name("/api/games/alpha-quest/?x=1"), "Alpha Quest")
        models.Game.objects.filter(pk=self.game.pk).update(name="Renamed")
        self.assertEqual(self.name("/api/games/alpha-quest/?x=1"), "Renamed")

    def test_a_query_string_does_not_read_the_kept_copy_either(self):
        """`?x=1` is rendered, not answered from the bare path's entry."""
        self.assertEqual(self.name("/api/games/alpha-quest/"), "Alpha Quest")
        models.Game.objects.filter(pk=self.game.pk).update(name="Renamed")
        self.assertEqual(self.name("/api/games/alpha-quest/?x=1"), "Renamed")

    def rename(self):
        """Behind the data version's back, so a kept copy still answers."""
        models.Game.objects.filter(pk=self.game.pk).update(name="Renamed")

    def test_the_accept_header_makes_no_second_copy(self):
        """Django's `cache_page` keyed on it, through `Vary`, and it is the
        caller's to write: every distinct value was two more rows."""
        url = "/api/games/alpha-quest/"
        first = self.client.get(url, HTTP_ACCEPT="application/json")
        self.assertEqual(first.json()["name"], "Alpha Quest")
        self.rename()
        for accept in ("*/*", "application/json, */*"):
            with self.subTest(accept=accept):
                response = self.client.get(url, HTTP_ACCEPT=accept)
                self.assertEqual(response.json()["name"], "Alpha Quest")

    def test_a_port_in_the_host_makes_no_second_copy(self):
        """Heroku forwards the port a caller writes, and the key hashed the
        whole address, as the page cache's did until 2026-11-09."""
        url = "/api/games/alpha-quest/"
        self.assertEqual(self.name(url), "Alpha Quest")
        self.rename()
        response = self.client.get(url, HTTP_HOST="testserver:8443")
        self.assertEqual(response.json()["name"], "Alpha Quest")

    def test_an_answer_for_a_host_with_a_port_is_not_kept(self):
        """A paginated answer names its next page by absolute URL: kept,
        one caller's port would be in everyone's link."""
        url = "/api/games/alpha-quest/"
        response = self.client.get(url, HTTP_HOST="testserver:8443")
        self.assertEqual(response.json()["name"], "Alpha Quest")
        self.rename()
        self.assertEqual(self.name(url), "Renamed")

    def test_the_browsable_api_is_rendered_and_never_kept(self):
        url = "/api/games/alpha-quest/"
        page = self.client.get(url, HTTP_ACCEPT="text/html")
        self.assertEqual(page["Content-Type"].split(";")[0], "text/html")
        self.rename()
        self.assertEqual(self.name(url), "Renamed")
        models.Game.objects.filter(pk=self.game.pk).update(name="Renamed Again")
        self.assertEqual(self.name(url), "Renamed")
        page = self.client.get(url, HTTP_ACCEPT="text/html")
        self.assertContains(page, "Renamed Again")

    def test_json_with_parameters_is_negotiated_not_answered_from_the_cache(self):
        url = "/api/games/alpha-quest/"
        self.assertEqual(self.name(url), "Alpha Quest")
        self.rename()
        response = self.client.get(url, HTTP_ACCEPT="application/json; indent=4")
        self.assertEqual(response.json()["name"], "Renamed")

    def test_a_kept_answer_says_how_long_it_may_be_kept_and_what_it_varies_on(self):
        url = "/api/games/alpha-quest/"
        for _ in range(2):
            response = self.client.get(url)
            self.assertEqual(response["Content-Type"], "application/json")
            self.assertIn("max-age=1800", response["Cache-Control"])
            self.assertIn("Accept", response["Vary"])

    def test_head_is_answered_from_the_kept_copy_and_keeps_none(self):
        url = "/api/games/alpha-quest/"
        self.assertEqual(self.client.head(url).status_code, 200)
        self.rename()
        self.assertEqual(self.name(url), "Renamed")
        models.Game.objects.filter(pk=self.game.pk).update(name="Renamed Again")
        head = self.client.head(url)
        self.assertEqual(head.status_code, 200)
        self.assertIn("max-age=1800", head["Cache-Control"])

    def test_an_error_is_not_kept(self):
        url = "/api/games/no-such-game/"
        self.assertEqual(self.client.get(url).status_code, 404)
        models.Game.objects.filter(pk=self.game.pk).update(slug="no-such-game")
        self.assertEqual(self.name(url), "Alpha Quest")


class GameDetailQueryTests(TestCase):
    """Game detail reads its list appearances once, not once more to drop."""

    def setUp(self):
        clear_all_caches()
        self.addCleanup(clear_all_caches)
        self.game = models.Game.objects.create(
            name="Alpha Quest", rank=1, igdb_id=1, slug="alpha-quest"
        )
        publisher = models.Publication.objects.create(name="Edge")
        game_list = models.List.objects.create(
            publisher=publisher, name="Top 100", year=2020
        )
        models.ListMembership.objects.create(game=self.game, list=game_list, rank=3)

    def test_the_memberships_are_read_in_one_query(self):
        with CaptureQueriesContext(connection) as context:
            response = self.client.get("/api/games/alpha-quest/")
        self.assertEqual(response.json()["lists"][0]["rank"], 3)
        membership_reads = [
            query["sql"]
            for query in context.captured_queries
            if 'FROM "games_listmembership"' in query["sql"]
        ]
        self.assertEqual(len(membership_reads), 1, membership_reads)


class SavedFilterBodiesTests(TestCase):
    """A request body is the caller's to write: a wrong shape is a 400."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="reader", email="reader@example.com", password="pw-12345"
        )

    def setUp(self):
        self.client.force_login(self.user)

    def send(self, method, url, body):
        return getattr(self.client, method)(
            url, data=json.dumps(body), content_type="application/json"
        )

    def test_create_refuses_a_name_that_is_not_text(self):
        for name in (None, True, ["a"], {"a": 1}):
            with self.subTest(name=name):
                response = self.send(
                    "post", "/api/saved-filters/", {"name": name, "filters": {}}
                )
                self.assertEqual(response.status_code, 400)
        self.assertFalse(SavedFilterSet.objects.exists())

    def test_create_refuses_a_body_that_is_not_an_object(self):
        for body in (["name"], "name", 5):
            with self.subTest(body=body):
                response = self.send("post", "/api/saved-filters/", body)
                self.assertEqual(response.status_code, 400)

    def test_create_refuses_filters_that_are_not_an_object(self):
        response = self.send(
            "post", "/api/saved-filters/", {"name": "Mine", "filters": [1, 2]}
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SavedFilterSet.objects.exists())

    def test_create_still_takes_a_well_formed_body(self):
        response = self.send(
            "post", "/api/saved-filters/", {"name": " Mine ", "filters": {"q": "x"}}
        )
        self.assertEqual(response.status_code, 201)
        saved = SavedFilterSet.objects.get()
        self.assertEqual((saved.name, saved.filters), ("Mine", {"q": "x"}))

    def test_create_without_filters_saves_none(self):
        response = self.send("post", "/api/saved-filters/", {"name": "Mine"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(SavedFilterSet.objects.get().filters, {})

    def test_rename_refuses_a_name_that_is_not_text(self):
        saved = SavedFilterSet.objects.create(user=self.user, name="Mine", filters={})
        url = f"/api/saved-filters/{saved.pk}/"
        for body in ({"name": None}, {"name": True}, ["name"]):
            with self.subTest(body=body):
                self.assertEqual(self.send("patch", url, body).status_code, 400)
        saved.refresh_from_db()
        self.assertEqual(saved.name, "Mine")

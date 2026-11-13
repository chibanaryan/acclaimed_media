"""What each phase of `refresh_all_metadata` reads, sends and saves.

The Wikipedia phase asks Wikidata for a game's page and reads the page's
infobox for its genres; the HowLongToBeat phase looks a game up by the id
Wikidata holds, else by name. Until 2026-11-12 the tests reached neither
past its first request, so the weekly job's saves ran only in production.
"""

import asyncio
import itertools
import os
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections
from django.test import SimpleTestCase, TestCase, override_settings

from games import config
from games.management.commands import refresh_all_metadata
from games.management.commands.refresh_all_metadata import (
    infobox_genres,
    page_from_entity,
)
from games.models import Game, HLTBGameData, Platform, WikipediaGameData

COMMAND = "games.management.commands.refresh_all_metadata"


def claim(value, rank="normal"):
    """One Wikidata claim holding an external id."""
    return {
        "rank": rank,
        "mainsnak": {
            "snaktype": "value",
            "datavalue": {"value": value, "type": "string"},
        },
    }


def entity(title=None, hltb_id=None, steam_app_id=None):
    """A game's Wikidata entity, as ``wbgetentities`` gives it."""
    claims = {}
    if hltb_id:
        claims["P2816"] = [claim(hltb_id)]
    if steam_app_id:
        claims["P1733"] = [claim(steam_app_id)]
    sitelinks = {"enwiki": {"site": "enwiki", "title": title}} if title else {}
    return {"type": "item", "sitelinks": sitelinks, "claims": claims}


def infobox(rows):
    """A Wikipedia article with these rows in its infobox."""
    return (
        "<html><body><h1>An article</h1>"
        f'<table class="infobox ib-video-game hproduct">{rows}</table>'
        "<p>Genre is discussed in the text too.</p></body></html>"
    )


def genre_page(cell):
    """An article whose infobox has this in its Genre(s) cell."""
    return infobox(
        "<tr><th>Developer(s)</th><td>Nintendo EAD</td></tr>"
        f"<tr><th>Genre(s)</th><td>{cell}</td></tr>"
        "<tr><th>Mode(s)</th><td>Single-player</td></tr>"
    )


class PageFromEntityTests(SimpleTestCase):
    """What the Wikipedia phase keeps of a Wikidata entity."""

    def test_the_english_title_and_both_ids(self):
        self.assertEqual(
            page_from_entity(
                entity("Super Mario 64", hltb_id="9364", steam_app_id="620")
            ),
            {
                "page_title": "Super Mario 64",
                "hltb_id": "9364",
                "steam_app_id": "620",
                "lookup_source": "wikidata",
            },
        )

    def test_an_entity_with_no_ids_still_has_its_page(self):
        self.assertEqual(
            page_from_entity(entity("Super Mario 64")),
            {
                "page_title": "Super Mario 64",
                "hltb_id": None,
                "steam_app_id": None,
                "lookup_source": "wikidata",
            },
        )

    def test_an_entity_with_no_claims_at_all_still_has_its_page(self):
        """``props=sitelinks`` alone, or an entity nobody has described."""
        page = page_from_entity({"sitelinks": {"enwiki": {"title": "Pong"}}})
        self.assertEqual(page["page_title"], "Pong")
        self.assertIsNone(page["hltb_id"])

    def test_no_english_article_is_no_page(self):
        """Whatever ids it holds: the page is what the genres are read from."""
        for name, found in (
            ("an entity Wikidata did not return", {}),
            ("no sitelinks", entity(hltb_id="9364")),
            ("another language's only", {"sitelinks": {"jawiki": {"title": "ポン"}}}),
            ("a sitelink with no title", {"sitelinks": {"enwiki": {}}}),
            ("an empty title", {"sitelinks": {"enwiki": {"title": ""}}}),
        ):
            with self.subTest(name):
                self.assertIsNone(page_from_entity(found))

    def test_the_ids_are_the_best_ranked_claims_with_a_value(self):
        """As every other reader of the claims takes them
        (``core.services.wikidata_claims``)."""
        found = entity("Doom")
        found["claims"] = {
            "P2816": [
                {"rank": "preferred", "mainsnak": {"snaktype": "novalue"}},
                claim("2708", rank="deprecated"),
                claim("2701"),
            ],
            "P1733": [claim("379720"), claim("2280", rank="preferred")],
        }
        page = page_from_entity(found)
        self.assertEqual(page["hltb_id"], "2701")
        self.assertEqual(page["steam_app_id"], "2280")


class InfoboxGenresTests(SimpleTestCase):
    """The genres read off a Wikipedia page, by the shape of its Genre cell."""

    def test_linked_genres_separated_by_commas(self):
        self.assertEqual(
            infobox_genres(
                genre_page('<a href="/wiki/A">Action-adventure</a>, <a>stealth</a>')
            ),
            ["Action-adventure", "stealth"],
        )

    def test_a_link_followed_by_plain_text(self):
        """The comma belongs to the text after the link, and is dropped."""
        self.assertEqual(
            infobox_genres(genre_page("<a>Platform</a>, puzzle")),
            ["Platform", "puzzle"],
        )

    def test_plain_text_is_split_on_its_commas(self):
        self.assertEqual(
            infobox_genres(genre_page("Platform, puzzle , racing")),
            ["Platform", "puzzle", "racing"],
        )

    def test_a_single_genre(self):
        self.assertEqual(infobox_genres(genre_page("<a>Fighting</a>")), ["Fighting"])

    def test_line_breaks_separate_genres(self):
        self.assertEqual(
            infobox_genres(genre_page("<a>Role-playing</a><br><a>Shooter</a>")),
            ["Role-playing", "Shooter"],
        )

    def test_a_list_is_its_items(self):
        """An empty item, which the plainlist template leaves, is no genre."""
        self.assertEqual(
            infobox_genres(
                genre_page(
                    '<div class="plainlist"><ul>'
                    "<li><a>Survival horror</a></li><li>Third-person shooter</li>"
                    "<li> </li></ul></div>"
                )
            ),
            ["Survival horror", "Third-person shooter"],
        )

    def test_a_list_with_nothing_in_it_gives_way_to_the_cells_text(self):
        self.assertEqual(
            infobox_genres(genre_page("Platform<ul><li></li></ul>")), ["Platform"]
        )

    def test_footnote_markers_are_not_genres(self):
        """A ``<sup>`` is dropped whole, and so is anything else marked as
        a reference: "[1]" would otherwise be a genre of its own."""
        self.assertEqual(
            infobox_genres(
                genre_page(
                    '<a>Racing</a><sup id="cite_ref-1" class="reference">'
                    '<a href="#cite_note-1">[1]</a></sup>, '
                    '<a>vehicular combat</a><span class="reference">[a]</span>'
                )
            ),
            ["Racing", "vehicular combat"],
        )
        self.assertEqual(
            infobox_genres(
                genre_page("<ul><li>Racing<sup>[2]</sup></li><li>Sports</li></ul>")
            ),
            ["Racing", "Sports"],
        )

    def test_a_single_character_is_not_a_genre(self):
        """What is left of a stray separator between two links."""
        self.assertEqual(
            infobox_genres(genre_page("<a>Puzzle</a> / <a>Strategy</a>")),
            ["Puzzle", "Strategy"],
        )

    def test_the_row_is_found_by_its_heading_whatever_the_case(self):
        for heading in ("Genre", "Genres", "Genre(s)", "GENRE", "<a>Genre(s)</a>"):
            with self.subTest(heading):
                page = infobox(f"<tr><th>{heading}</th><td>Puzzle</td></tr>")
                self.assertEqual(infobox_genres(page), ["Puzzle"])

    def test_a_heading_with_no_cell_is_passed_over(self):
        """The search goes on to the next Genre row."""
        page = infobox(
            '<tr><th colspan="2">Genre(s)</th></tr>'
            "<tr><th>Genre</th><td>Puzzle</td></tr>"
        )
        self.assertEqual(infobox_genres(page), ["Puzzle"])

    def test_an_empty_cell_is_no_genres(self):
        for cell in ("", " ", "<sup>[1]</sup>", ","):
            with self.subTest(cell):
                self.assertIsNone(infobox_genres(genre_page(cell)))

    def test_an_infobox_with_no_genre_row_is_no_genres(self):
        page = infobox("<tr><th>Developer(s)</th><td>Nintendo EAD</td></tr>")
        self.assertIsNone(infobox_genres(page))

    def test_a_page_with_no_infobox_is_no_genres(self):
        """A Genre row in any other table is not the game's."""
        for page in (
            "",
            "<html><body><p>Genre: Puzzle</p></body></html>",
            '<table class="wikitable"><tr><th>Genre</th><td>Puzzle</td></tr></table>',
        ):
            with self.subTest(page):
                self.assertIsNone(infobox_genres(page))

    def test_only_the_first_infobox_is_read(self):
        """A page on a series can carry one a game."""
        page = (
            '<table class="infobox"><tr><th>Genre(s)</th><td>Puzzle</td></tr></table>'
            '<table class="infobox"><tr><th>Genre(s)</th><td>Racing</td></tr></table>'
        )
        self.assertEqual(infobox_genres(page), ["Puzzle"])


class FakeResponse:
    """As much of an aiohttp response as the command reads."""

    def __init__(self, status=200, json=None, text=""):
        self.status = status
        self._json = json
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json

    async def text(self):
        return self._text


class FakeWikimedia:
    """Stands in for ``aiohttp.ClientSession``, and answers for both sites.

    Wikidata's API answers with the entity it holds for the id asked about;
    any other address answers with the page kept for it, or a 404. Either
    answer can be a ``FakeResponse`` instead, for a status or a body of its
    own, or an exception, which the request raises as a timeout would.

    Every request is kept, with all it was sent with, to say what went where.
    """

    def __init__(self):
        self.entities = {}
        self.pages = {}
        self.opened_with = None
        self.requests = []

    def __call__(self, **kwargs):
        self.opened_with = kwargs
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def get(self, url, **kwargs):
        self.requests.append(SimpleNamespace(url=url, kwargs=kwargs))
        if url == config.WIKIDATA_API_URL:
            wikidata_id = kwargs["params"]["ids"]
            answer = self.entities.get(wikidata_id, {})
            if isinstance(answer, dict):
                answer = FakeResponse(json={"entities": {wikidata_id: answer}})
        else:
            answer = self.pages.get(url, FakeResponse(status=404))
            if isinstance(answer, str):
                answer = FakeResponse(text=answer)
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def wikidata_requests(self):
        return [r for r in self.requests if r.url == config.WIKIDATA_API_URL]

    @property
    def page_requests(self):
        return [r for r in self.requests if r.url != config.WIKIDATA_API_URL]

    @property
    def ids_asked_about(self):
        return [r.kwargs["params"]["ids"] for r in self.wikidata_requests]


def hltb_entry(game_id, name, similarity=None, **fields):
    """A HowLongToBeat entry, as howlongtobeatpy's search gives one. An id
    lookup's has no similarity."""
    found = SimpleNamespace(game_id=game_id, game_name=name, **fields)
    if similarity is not None:
        found.similarity = similarity
    return found


class PhaseTestCase(TestCase):
    """Runs the command with Wikidata, Wikipedia and HowLongToBeat replaced,
    no waiting, and its saves on the test's own database connection.

    The command saves through ``sync_to_async``, whose executor thread has
    a connection of its own. That one cannot see the rows a ``TestCase``
    has not committed. On SQLite every save then fails on a locked table,
    which the command counts as that game's error before carrying on, so a
    test of the output alone passes with nothing saved; on Postgres the
    thread does not find the game. So the saves run where they are awaited,
    on the connection the test holds.
    """

    def setUp(self):
        super().setUp()
        self.sleep = self.enterContext(
            mock.patch(f"{COMMAND}.asyncio.sleep", new=mock.AsyncMock())
        )
        self.test_connection = connections[DEFAULT_DB_ALIAS]
        self.enterContext(
            mock.patch(f"{COMMAND}.sync_to_async", self.on_the_tests_connection)
        )
        # Django refuses the ORM inside an event loop unless told otherwise
        self.enterContext(
            mock.patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        )
        self.wikimedia = FakeWikimedia()
        self.enterContext(mock.patch("aiohttp.ClientSession", self.wikimedia))
        self.hltb = mock.MagicMock()
        self.hltb.async_search = mock.AsyncMock(return_value=[])
        self.hltb.async_search_from_id = mock.AsyncMock(return_value=None)
        self.hltb_client = self.enterContext(
            mock.patch("howlongtobeatpy.HowLongToBeat", return_value=self.hltb)
        )
        self.out = StringIO()

    def on_the_tests_connection(self, function):
        """``sync_to_async``, without the thread.

        Inside an event loop Django keeps its connections apart from the
        thread's own, so the test's is handed over first.
        """

        async def call(*args, **kwargs):
            connections[DEFAULT_DB_ALIAS] = self.test_connection
            return function(*args, **kwargs)

        return call

    def refresh(self, **options):
        """Run the command and answer with what it printed, which
        ``self.output`` also holds after a run that raised."""
        call_command("refresh_all_metadata", stdout=self.out, no_color=True, **options)
        return self.output

    @property
    def output(self):
        return self.out.getvalue()

    def delays(self):
        """The seconds each wait between requests was to last."""
        return {call.args[0] for call in self.sleep.await_args_list}


class WikipediaPhaseTests(PhaseTestCase):
    def refresh(self, **options):
        return super().refresh(wikipedia_only=True, **options)

    def test_a_page_and_its_genres_are_saved(self):
        game = Game.objects.create(
            name="Ocarina of Time", rank=1, igdb_id=1029, wikidata_id="Q12393"
        )
        self.wikimedia.entities["Q12393"] = entity(
            "The Legend of Zelda: Ocarina of Time", hltb_id="10035", steam_app_id="77"
        )
        self.wikimedia.pages[
            "https://en.wikipedia.org/wiki/The_Legend_of_Zelda%3A_Ocarina_of_Time"
        ] = genre_page("<a>Action-adventure</a>, <a>puzzle</a><sup>[1]</sup>")

        output = self.refresh()

        page = WikipediaGameData.objects.get()
        self.assertEqual(page.game, game)
        self.assertEqual(page.page_title, "The Legend of Zelda: Ocarina of Time")
        self.assertEqual(page.lookup_source, "wikidata")
        self.assertEqual(page.wikidata_id, "Q12393")
        self.assertEqual(page.hltb_id, "10035")
        self.assertEqual(page.steam_app_id, "77")
        self.assertTrue(page.is_primary)
        # The genres in our spelling, the infobox's first as the primary
        self.assertEqual(page.primary_genre, "Action-Adventure")
        self.assertEqual(page.all_genres, "Action-Adventure, Puzzle")
        game.refresh_from_db()
        self.assertEqual(game.primary_wikipedia_game_data, page)
        self.assertEqual(
            sorted(game.wikipedia_genres.values_list("name", flat=True)),
            ["Action-Adventure", "Puzzle"],
        )

        self.assertIn(
            "Wikipedia Complete: 1 pages found, 1 genres scraped, 0 page errors",
            output,
        )
        self.assertIn("Wikipedia: 1/1 pages found (0 errors, 100.0%)", output)
        self.assertIn("Genres:    1/1 scraped (100.0%)", output)
        self.assertIn("Overall Status: SUCCESS", output)

    def test_wikidata_is_asked_for_the_english_page_and_the_claims(self):
        Game.objects.create(name="Pong", rank=1, wikidata_id="Q216293")
        self.wikimedia.entities["Q216293"] = entity("Pong")

        self.refresh()

        (request,) = self.wikimedia.wikidata_requests
        self.assertEqual(
            request.kwargs["params"],
            {
                "action": "wbgetentities",
                "format": "json",
                "props": "sitelinks|claims",
                "ids": "Q216293",
                "sitefilter": "enwiki",
            },
        )
        (page_request,) = self.wikimedia.page_requests
        self.assertEqual(page_request.url, "https://en.wikipedia.org/wiki/Pong")

    def test_a_page_title_is_written_into_its_address(self):
        """Spaces as underscores, and the rest percent-encoded."""
        for number, (title, address) in enumerate(
            (
                ("Super Mario 64", "Super_Mario_64"),
                ("Pokémon Red and Blue", "Pok%C3%A9mon_Red_and_Blue"),
                ("Half-Life (video game)", "Half-Life_%28video_game%29"),
                ("Who Framed Roger Rabbit?", "Who_Framed_Roger_Rabbit%3F"),
                ("AC/DC", "AC/DC"),
            ),
            start=1,
        ):
            Game.objects.create(name=title, rank=number, wikidata_id=f"Q{number}")
            self.wikimedia.entities[f"Q{number}"] = entity(title)
            with self.subTest(title):
                self.wikimedia.requests.clear()
                # The other games have their page already, so come later
                self.refresh(limit=1)
                (request,) = self.wikimedia.page_requests
                self.assertEqual(
                    request.url, f"https://en.wikipedia.org/wiki/{address}"
                )

    def test_the_session_names_us_and_gives_up_on_a_stalled_request(self):
        """aiohttp's own timeout is five minutes, and one stalled page held
        its slot for all of it."""
        Game.objects.create(name="Pong", rank=1, wikidata_id="Q216293")
        self.refresh()
        self.assertEqual(
            self.wikimedia.opened_with["headers"],
            {"User-Agent": config.WIKI_USER_AGENT},
        )
        self.assertEqual(self.wikimedia.opened_with["timeout"].total, 30)

    @override_settings(WIKIDATA_ACCESS_TOKEN="Site@bot:s3cret")
    def test_the_credentials_go_to_wikidata_and_never_to_wikipedia(self):
        """They are a Wikimedia login. Wikidata's API is where they raise
        the rate limit; the article is fetched as anyone would fetch it."""
        Game.objects.create(name="Pong", rank=1, wikidata_id="Q216293")
        self.wikimedia.entities["Q216293"] = entity("Pong")
        self.wikimedia.pages["https://en.wikipedia.org/wiki/Pong"] = genre_page(
            "Sports"
        )

        output = self.refresh()

        (to_wikidata,) = self.wikimedia.wikidata_requests
        sent = to_wikidata.kwargs["auth"]
        self.assertEqual((sent.login, sent.password), ("Site@bot", "s3cret"))
        (to_wikipedia,) = self.wikimedia.page_requests
        # Nothing but the address: no credentials, under any name
        self.assertEqual(to_wikipedia.kwargs, {})
        # Nor are they the session's, which both requests share
        self.assertEqual(set(self.wikimedia.opened_with), {"headers", "timeout"})
        self.assertNotIn("Authorization", self.wikimedia.opened_with["headers"])
        # And the page was read all the same
        self.assertEqual(WikipediaGameData.objects.get().primary_genre, "Sports")

        # The authenticated pace, which it has the credentials for
        self.assertIn(
            "Using authenticated Wikidata requests (1.5s delay, 2 concurrent)", output
        )
        self.assertEqual(self.delays(), {1.5})

    def test_without_credentials_it_sends_none_and_takes_the_slower_pace(self):
        """Until 2026-11-10 it took the faster pace for any token, and sent
        none."""
        Game.objects.create(name="Pong", rank=1, wikidata_id="Q216293")
        self.wikimedia.entities["Q216293"] = entity("Pong")

        for token in (None, "a-token-that-is-no-login"):
            with (
                self.subTest(token=token),
                override_settings(WIKIDATA_ACCESS_TOKEN=token),
            ):
                self.wikimedia.requests.clear()
                self.sleep.reset_mock()
                output = self.refresh()
                (to_wikidata,) = self.wikimedia.wikidata_requests
                self.assertIsNone(to_wikidata.kwargs["auth"])
                self.assertIn(
                    "Using unauthenticated Wikidata requests (4.0s delay, sequential)",
                    output,
                )
                self.assertEqual(self.delays(), {4.0})

    def test_a_game_with_no_wikidata_id_is_asked_about_nowhere(self):
        game = Game.objects.create(name="Homebrew Quest", rank=1)

        output = self.refresh()

        self.assertEqual(self.wikimedia.requests, [])
        self.assertFalse(WikipediaGameData.objects.exists())
        game.refresh_from_db()
        self.assertIsNone(game.primary_wikipedia_game_data)
        self.assertIn("Wikipedia: 0/1 pages found (1 errors, 0.0%)", output)
        self.assertIn("Overall Status: COMPLETED WITH ERRORS", output)
        # It still waits its turn, as a game that was asked about does
        self.assertEqual(self.delays(), {4.0})

    def test_a_game_wikidata_has_no_page_for_is_left_as_it_was(self):
        """Each is that game's alone: the next is still asked about, and no
        article is fetched for a title nobody gave."""
        answers = {
            "an error status": FakeResponse(status=500),
            "a request that timed out": asyncio.TimeoutError(),
            "an error in the body": FakeResponse(
                json={"error": {"code": "no-such-entity"}}
            ),
            "a body that is not JSON": FakeResponse(json=ValueError("<html>")),
            "an entity with no English article": entity(hltb_id="9364"),
        }
        for number, answer in enumerate(answers.values(), start=1):
            Game.objects.create(
                name=f"Game {number}", rank=number, wikidata_id=f"Q{number}"
            )
            self.wikimedia.entities[f"Q{number}"] = answer
        kept = Game.objects.get(rank=1)
        page = WikipediaGameData.objects.create(
            game=kept, page_title="Game 1", primary_genre="Puzzle", is_primary=True
        )
        Game.objects.filter(pk=kept.pk).update(primary_wikipedia_game_data=page)

        output = self.refresh()

        self.assertEqual(
            sorted(self.wikimedia.ids_asked_about), ["Q1", "Q2", "Q3", "Q4", "Q5"]
        )
        self.assertEqual(self.wikimedia.page_requests, [])
        # The page a game had before Wikidata failed is still its page
        page.refresh_from_db()
        self.assertTrue(page.is_primary)
        self.assertEqual(WikipediaGameData.objects.count(), 1)
        self.assertIn(
            "Wikipedia Complete: 0 pages found, 0 genres scraped, 5 page errors",
            output,
        )
        self.assertIn("Wikipedia: 0/5 pages found (5 errors, 0.0%)", output)
        self.assertNotIn("Genres:", output)

    def test_a_page_that_cannot_be_read_is_saved_without_genres(self):
        """Wikidata named the page, so the page is the game's. Only the
        genres are missing, and the summary says so."""
        missing = Game.objects.create(name="Missing", rank=1, wikidata_id="Q1")
        stalled = Game.objects.create(name="Stalled", rank=2, wikidata_id="Q2")
        bare = Game.objects.create(name="Bare", rank=3, wikidata_id="Q3")
        read = Game.objects.create(name="Read", rank=4, wikidata_id="Q4")
        for game in (missing, stalled, bare, read):
            self.wikimedia.entities[game.wikidata_id] = entity(game.name)
        wiki = "https://en.wikipedia.org/wiki/"
        self.wikimedia.pages[f"{wiki}Missing"] = FakeResponse(status=404)
        self.wikimedia.pages[f"{wiki}Stalled"] = asyncio.TimeoutError()
        self.wikimedia.pages[f"{wiki}Bare"] = "<html><body>No infobox</body></html>"
        self.wikimedia.pages[f"{wiki}Read"] = genre_page("Puzzle")

        output = self.refresh()

        for game in (missing, stalled, bare):
            with self.subTest(game.name):
                page = WikipediaGameData.objects.get(game=game)
                self.assertEqual(page.page_title, game.name)
                self.assertTrue(page.is_primary)
                self.assertIsNone(page.primary_genre)
                self.assertIsNone(page.all_genres)
                self.assertFalse(game.wikipedia_genres.exists())
        self.assertEqual(
            WikipediaGameData.objects.get(game=read).primary_genre, "Puzzle"
        )
        self.assertIn(
            "Wikipedia Complete: 4 pages found, 1 genres scraped, 0 page errors",
            output,
        )
        self.assertIn("Wikipedia: 4/4 pages found (0 errors, 100.0%)", output)
        self.assertIn("Genres:    1/4 scraped (25.0%)", output)
        # A page with no genres read is an error to the summary
        self.assertIn("Overall Status: COMPLETED WITH ERRORS", output)

    def test_a_page_that_cannot_be_read_leaves_the_genres_the_game_had(self):
        """One bad Sunday at Wikipedia must not empty the genre filter."""
        game = Game.objects.create(name="Tetris", rank=1, wikidata_id="Q71910")
        page = WikipediaGameData.objects.create(
            game=game,
            page_title="Tetris",
            primary_genre="Puzzle",
            all_genres="Puzzle",
            is_primary=True,
        )
        game.primary_wikipedia_game_data = page
        game.save()
        puzzle = refresh_all_metadata.get_or_create_genre("Puzzle")
        game.wikipedia_genres.set([puzzle])
        self.wikimedia.entities["Q71910"] = entity("Tetris")
        self.wikimedia.pages["https://en.wikipedia.org/wiki/Tetris"] = FakeResponse(
            status=503
        )

        self.refresh()

        page.refresh_from_db()
        self.assertEqual(page.primary_genre, "Puzzle")
        self.assertEqual(page.all_genres, "Puzzle")
        self.assertEqual(list(game.wikipedia_genres.all()), [puzzle])

    def test_a_refresh_replaces_the_genres_a_game_had(self):
        game = Game.objects.create(name="Tetris", rank=1, wikidata_id="Q71910")
        game.wikipedia_genres.set([refresh_all_metadata.get_or_create_genre("Racing")])
        self.wikimedia.entities["Q71910"] = entity("Tetris")
        self.wikimedia.pages["https://en.wikipedia.org/wiki/Tetris"] = genre_page(
            "<a>Puzzle</a>"
        )

        self.refresh()

        self.assertEqual(
            list(game.wikipedia_genres.values_list("name", flat=True)), ["Puzzle"]
        )

    def test_the_page_a_game_already_has_is_updated_in_place(self):
        """And keeps an id Wikidata has since dropped: only what the lookup
        found is written."""
        game = Game.objects.create(name="Doom", rank=1, wikidata_id="Q513867")
        page = WikipediaGameData.objects.create(
            game=game,
            page_title="Doom (1993 video game)",
            wikidata_id="Q513867",
            hltb_id="2701",
            lookup_source="opensearch_basic",
            is_primary=True,
        )
        game.primary_wikipedia_game_data = page
        game.save()
        self.wikimedia.entities["Q513867"] = entity(
            "Doom (1993 video game)", steam_app_id="2280"
        )

        self.refresh()

        saved = WikipediaGameData.objects.get()
        self.assertEqual(saved.pk, page.pk)
        self.assertEqual(saved.hltb_id, "2701")
        self.assertEqual(saved.steam_app_id, "2280")
        self.assertEqual(saved.lookup_source, "wikidata")
        self.assertTrue(saved.is_primary)

    def test_a_page_wikidata_now_names_differently_becomes_the_primary(self):
        """An article that was moved: the old record stays, but is no
        longer the one the game shows."""
        game = Game.objects.create(name="Doom", rank=1, wikidata_id="Q513867")
        old = WikipediaGameData.objects.create(
            game=game, page_title="Doom (video game)", is_primary=True
        )
        game.primary_wikipedia_game_data = old
        game.save()
        self.wikimedia.entities["Q513867"] = entity("Doom (1993 video game)")

        self.refresh()

        old.refresh_from_db()
        self.assertFalse(old.is_primary)
        new = WikipediaGameData.objects.get(page_title="Doom (1993 video game)")
        self.assertTrue(new.is_primary)
        game.refresh_from_db()
        self.assertEqual(game.primary_wikipedia_game_data, new)

    def test_a_save_that_fails_is_that_games_error(self):
        """The next game is still saved, and the log names the one that
        was not."""
        Game.objects.create(name="Alpha Quest", rank=1, wikidata_id="Q1")
        beta = Game.objects.create(name="Beta Quest", rank=2, wikidata_id="Q2")
        self.wikimedia.entities["Q1"] = entity("Alpha Quest")
        self.wikimedia.entities["Q2"] = entity("Beta Quest")
        real_upsert = WikipediaGameData.upsert_for_game

        def upsert(game, page_title, defaults):
            if page_title == "Alpha Quest":
                raise DatabaseError("connection lost")
            return real_upsert(game, page_title, defaults)

        with (
            mock.patch.object(WikipediaGameData, "upsert_for_game", upsert),
            self.assertLogs(refresh_all_metadata.logger, "WARNING") as logs,
        ):
            output = self.refresh()

        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Wikipedia processing failed for 'Alpha Quest': connection lost"],
        )
        self.assertEqual(WikipediaGameData.objects.get().game, beta)
        self.assertIn("1 page errors", output)
        self.assertIn("Overall Status: COMPLETED WITH ERRORS", output)

    def test_games_with_no_page_yet_come_first(self):
        """So a run cut short, or one under ``--limit``, has spent itself
        on what is missing."""
        has_page = Game.objects.create(name="Has a page", rank=1, wikidata_id="Q1")
        page = WikipediaGameData.objects.create(
            game=has_page, page_title="Has a page", is_primary=True
        )
        has_page.primary_wikipedia_game_data = page
        has_page.save()
        Game.objects.create(name="Has none", rank=2, wikidata_id="Q2")
        Game.objects.create(name="Has none either", rank=3, wikidata_id="Q3")

        output = self.refresh(limit=2)

        self.assertEqual(self.wikimedia.ids_asked_about, ["Q2", "Q3"])
        self.assertIn("Limiting to first 2 games", output)
        self.assertIn("Processing 2 games...", output)

    def test_progress_is_reported_every_hundred_games(self):
        Game.objects.bulk_create(
            Game(name=f"Game {number}", rank=number, wikidata_id=f"Q{number}")
            for number in range(1, 101)
        )
        for number in range(1, 101):
            self.wikimedia.entities[f"Q{number}"] = entity(f"Game {number}")

        output = self.refresh()

        self.assertIn("  [100/100] (", output)
        self.assertNotIn("[99/100]", output)
        self.assertEqual(WikipediaGameData.objects.count(), 100)

    def test_a_dry_run_asks_nothing_and_saves_nothing(self):
        Game.objects.create(name="Pong", rank=1, wikidata_id="Q216293")
        self.wikimedia.entities["Q216293"] = entity("Pong")

        output = self.refresh(dry_run=True)

        self.assertIn("DRY RUN: Would process Wikipedia data for games", output)
        self.assertIsNone(self.wikimedia.opened_with)
        self.assertFalse(WikipediaGameData.objects.exists())

    def test_with_no_games_there_is_nothing_to_report(self):
        output = self.refresh()
        self.assertIn("No games found", output)
        self.assertIsNone(self.wikimedia.opened_with)
        self.assertNotIn("Wikipedia:", output)
        self.assertIn("Overall Status: SUCCESS", output)

    def test_a_phase_that_cannot_start_fails_the_command(self):
        """After the summary, which names it."""
        Game.objects.create(name="Pong", rank=1, wikidata_id="Q216293")
        with (
            mock.patch("aiohttp.ClientSession", side_effect=RuntimeError("no loop")),
            self.assertLogs(refresh_all_metadata.logger, "ERROR"),
            self.assertRaisesMessage(CommandError, "failed outright for: Wikipedia"),
        ):
            self.refresh()
        self.assertIn("Wikipedia refresh failed: no loop", self.output)
        self.assertIn("Wikipedia: FAILED", self.output)
        self.assertNotIn("pages found", self.output)


class HLTBPhaseTests(PhaseTestCase):
    def refresh(self, **options):
        return super().refresh(hltb_only=True, **options)

    def game_with_page(self, name, rank, page_title=None, hltb_id=None, **fields):
        """A game whose Wikipedia record holds this title and HLTB id."""
        game = Game.objects.create(name=name, rank=rank, igdb_id=rank, **fields)
        page = WikipediaGameData.objects.create(
            game=game,
            page_title=page_title or name,
            hltb_id=hltb_id,
            is_primary=True,
        )
        game.primary_wikipedia_game_data = page
        game.save()
        return game

    def test_a_game_is_looked_up_by_the_id_wikidata_holds(self):
        game = self.game_with_page("Chrono Trigger", 1, hltb_id="1705")
        self.hltb.async_search_from_id.return_value = hltb_entry(
            1705,
            "Chrono Trigger",
            main_story=23.14,
            main_extra=27.4,
            completionist=41.6,
            json_content={
                "game_type": "game",
                "comp_lvl_combine": 0,
                "comp_main_count": 1200,
                "comp_plus_count": 900,
                "comp_100_count": 300,
            },
        )

        output = self.refresh()

        self.hltb.async_search_from_id.assert_awaited_once_with(1705)
        # By id, the name is never searched for
        self.hltb.async_search.assert_not_awaited()
        saved = HLTBGameData.objects.get()
        self.assertEqual(saved.game, game)
        self.assertEqual(saved.igdb_id, game.igdb_id)
        self.assertEqual(saved.hltb_id, "1705")
        self.assertEqual(saved.hltb_name, "Chrono Trigger")
        self.assertEqual(saved.fetch_method, "wikidata")
        # An id lookup is the entry itself, not a guess at it
        self.assertEqual(saved.similarity, Decimal("1.00"))
        self.assertEqual(saved.main_story_hours, Decimal("23.1"))
        self.assertEqual(saved.main_extra_hours, Decimal("27.4"))
        self.assertEqual(saved.completionist_hours, Decimal("41.6"))
        self.assertEqual(saved.game_type, "game")
        self.assertIs(saved.comp_lvl_combine, False)
        self.assertEqual(saved.main_story_count, 1200)
        self.assertEqual(saved.main_extra_count, 900)
        self.assertEqual(saved.completionist_count, 300)
        self.assertTrue(saved.is_primary)
        self.assertFalse(saved.is_open_ended)
        game.refresh_from_db()
        self.assertEqual(game.primary_hltb_game_data, saved)

        self.assertIn("HLTB Complete: 1 found, 0 not found", output)
        self.assertIn("HLTB:      1/1 found (0 not found, 100.0%)", output)
        self.assertIn("Overall Status: SUCCESS", output)

    def test_an_open_ended_entry_is_saved_as_one(self):
        """HLTB's own type for it is what hides the playtime (see
        "HowLongToBeat playtimes"), and the weekly job is what fills it in."""
        self.game_with_page("Rocket League", 1, hltb_id="26784")
        self.hltb.async_search_from_id.return_value = hltb_entry(
            26784, "Rocket League", main_story=5.0, json_content={"game_type": "multi"}
        )

        self.refresh()

        saved = HLTBGameData.objects.get()
        self.assertEqual(saved.game_type, "multi")
        self.assertTrue(saved.is_open_ended)

    def test_an_id_hltb_does_not_know_falls_back_to_the_name(self):
        """Wikipedia's title first, then ours, each with its numerals
        turned; and no further once one is found."""
        game = self.game_with_page(
            "Final Fantasy VII",
            1,
            page_title="Final Fantasy VII (1997 video game)",
            hltb_id="999999",
        )
        searched = []

        async def search(name):
            searched.append(name)
            if name == "Final Fantasy VII":
                return [
                    hltb_entry(3521, "Final Fantasy VII", similarity=1.0, main_story=36)
                ]
            return []

        self.hltb.async_search.side_effect = search

        self.refresh()

        self.hltb.async_search_from_id.assert_awaited_once_with(999999)
        self.assertEqual(
            searched,
            [
                "Final Fantasy VII (1997 video game)",
                "Final Fantasy 7 (1997 video game)",
                "Final Fantasy VII",
            ],
        )
        saved = HLTBGameData.objects.get()
        self.assertEqual(saved.game, game)
        self.assertEqual(saved.hltb_id, "3521")
        self.assertEqual(saved.fetch_method, "name_search")
        self.assertEqual(saved.main_story_hours, Decimal("36.0"))

    def test_an_id_lookup_that_fails_falls_back_to_the_name(self):
        """HLTB answers a burst with 429s, and an id Wikidata holds can be
        no number at all."""
        self.game_with_page("Portal", 1, hltb_id="7230")
        self.game_with_page("Braid", 2, hltb_id="not-a-number")
        self.hltb.async_search_from_id.side_effect = ConnectionError("429")
        self.hltb.async_search.side_effect = lambda name: [
            hltb_entry(len(name), name, similarity=0.97, main_story=3.2)
        ]

        output = self.refresh()

        # Only the one that is a number could be asked for
        self.hltb.async_search_from_id.assert_awaited_once_with(7230)
        self.assertEqual(
            sorted(
                HLTBGameData.objects.values_list(
                    "hltb_name", "fetch_method", "similarity"
                )
            ),
            [
                ("Braid", "name_search", Decimal("0.97")),
                ("Portal", "name_search", Decimal("0.97")),
            ],
        )
        self.assertIn("HLTB:      2/2 found (0 not found, 100.0%)", output)

    def test_a_game_with_no_wikipedia_record_is_searched_for_by_name(self):
        game = Game.objects.create(name="Wordle", rank=1, igdb_id=1)
        self.hltb.async_search.return_value = [
            hltb_entry(101906, "Wordle", similarity=1.0, main_story=0.1)
        ]

        self.refresh()

        self.hltb.async_search_from_id.assert_not_awaited()
        self.hltb.async_search.assert_awaited_once_with("Wordle")
        self.assertEqual(HLTBGameData.objects.get().game, game)

    def test_the_games_year_and_platforms_decide_between_entries(self):
        """Both reach the choice (``hltb_matching.choose_entry``): equally
        similar entries are otherwise settled by HLTB's order."""
        ps4 = Platform.objects.create(code="PS4", name="PlayStation 4")
        game_boy = Platform.objects.create(code="GB", name="Game Boy")
        god_of_war = Game.objects.create(
            name="God of War", rank=1, igdb_id=1, year_of_release=2018
        )
        god_of_war.platforms.add(ps4)
        tetris = Game.objects.create(
            name="Tetris", rank=2, igdb_id=2, year_of_release=1989
        )
        tetris.platforms.add(game_boy)
        entries = {
            "God of War": [
                hltb_entry(3978, "God of War", similarity=1.0, release_world=2005),
                hltb_entry(38050, "God of War", similarity=1.0, release_world=2018),
            ],
            "Tetris": [
                hltb_entry(
                    10277,
                    "Tetris",
                    similarity=1.0,
                    release_world=1989,
                    profile_platforms=["NES"],
                ),
                hltb_entry(
                    10276,
                    "Tetris",
                    similarity=1.0,
                    release_world=1989,
                    profile_platforms=["Game Boy"],
                ),
            ],
        }
        self.hltb.async_search.side_effect = lambda name: entries[name]

        self.refresh()

        self.assertEqual(god_of_war.hltb_game_data_set.get().hltb_id, "38050")
        self.assertEqual(tetris.hltb_game_data_set.get().hltb_id, "10276")

    def test_a_game_with_no_entry_similar_enough_keeps_what_it_had(self):
        """Under 0.85 is another game. A search can also answer None."""
        game = Game.objects.create(name="Ico", rank=1, igdb_id=1)
        had = HLTBGameData.objects.create(
            game=game, igdb_id=1, hltb_id="4567", is_primary=True
        )
        Game.objects.filter(pk=game.pk).update(primary_hltb_game_data=had)
        Game.objects.create(name="Rez", rank=2, igdb_id=2)
        answers = {"Ico": [hltb_entry(1, "Icon of Sin", similarity=0.84)], "Rez": None}
        self.hltb.async_search.side_effect = lambda name: answers[name]

        output = self.refresh()

        self.assertEqual(list(HLTBGameData.objects.all()), [had])
        had.refresh_from_db()
        self.assertEqual(had.hltb_id, "4567")
        self.assertTrue(had.is_primary)
        self.assertIn("HLTB Complete: 0 found, 2 not found", output)
        self.assertIn("HLTB:      0/2 found (2 not found, 0.0%)", output)
        self.assertIn("Overall Status: COMPLETED WITH ERRORS", output)

    def test_a_search_that_fails_is_that_games_alone(self):
        """The next game is still found, and the log names the one that
        was not."""
        Game.objects.create(name="Alpha Quest", rank=1, igdb_id=1)
        beta = Game.objects.create(name="Beta Quest", rank=2, igdb_id=2)

        async def search(name):
            if name == "Alpha Quest":
                raise ConnectionError("429 Too Many Requests")
            return [hltb_entry(77, name, similarity=1.0, main_story=8)]

        self.hltb.async_search.side_effect = search

        with self.assertLogs(refresh_all_metadata.logger, "WARNING") as logs:
            output = self.refresh()

        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Failed to fetch HLTB data for 'Alpha Quest': 429 Too Many Requests"],
        )
        self.assertEqual(HLTBGameData.objects.get().game, beta)
        self.assertIn("HLTB:      1/2 found (1 not found, 50.0%)", output)
        self.assertIn("Overall Status: COMPLETED WITH ERRORS", output)

    def test_games_with_no_playtime_yet_come_first(self):
        has_one = Game.objects.create(name="Has one", rank=1, igdb_id=1)
        had = HLTBGameData.objects.create(game=has_one, igdb_id=1, is_primary=True)
        Game.objects.filter(pk=has_one.pk).update(primary_hltb_game_data=had)
        Game.objects.create(name="Has none", rank=2, igdb_id=2)
        Game.objects.create(name="Has none either", rank=3, igdb_id=3)

        output = self.refresh(limit=2)

        self.assertEqual(
            [call.args[0] for call in self.hltb.async_search.await_args_list],
            ["Has none", "Has none either"],
        )
        self.assertIn("Processing 2 games (concurrency: 3, delay: 1.5s", output)

    def test_it_waits_between_games(self):
        Game.objects.create(name="Ico", rank=1, igdb_id=1)
        Game.objects.create(name="Rez", rank=2, igdb_id=2)
        self.refresh()
        self.assertEqual(self.sleep.await_count, 2)
        self.assertEqual(self.delays(), {1.5})

    def test_progress_is_reported_every_hundred_games(self):
        Game.objects.bulk_create(
            Game(name=f"Game {number}", rank=number, igdb_id=number)
            for number in range(1, 101)
        )
        output = self.refresh()
        self.assertIn("  [100/100] (", output)
        self.assertNotIn("[99/100]", output)
        self.assertIn("HLTB Complete: 0 found, 100 not found", output)

    def test_a_dry_run_asks_nothing(self):
        Game.objects.create(name="Ico", rank=1, igdb_id=1)
        output = self.refresh(dry_run=True)
        self.assertIn("DRY RUN: Would process HLTB data for games", output)
        self.hltb_client.assert_not_called()

    def test_with_no_games_there_is_nothing_to_report(self):
        output = self.refresh()
        self.assertIn("No games found", output)
        self.hltb_client.assert_not_called()
        self.assertNotIn("HLTB:", output)
        self.assertIn("Overall Status: SUCCESS", output)

    def test_a_phase_that_cannot_start_fails_the_command(self):
        """After the summary, which names it."""
        Game.objects.create(name="Ico", rank=1, igdb_id=1)
        self.hltb_client.side_effect = RuntimeError("no search key")
        with (
            self.assertLogs(refresh_all_metadata.logger, "ERROR"),
            self.assertRaisesMessage(CommandError, "failed outright for: HLTB"),
        ):
            self.refresh()
        self.assertIn("HLTB refresh failed: no search key", self.output)
        self.assertIn("HLTB:      FAILED", self.output)
        self.assertNotIn("not found,", self.output)


class EveryPhaseTests(PhaseTestCase):
    """The three phases in one run, and the summary under them."""

    def setUp(self):
        super().setUp()
        self.service = self.enterContext(mock.patch(f"{COMMAND}.IGDBImportService"))
        self.igdb = self.service.return_value
        self.igdb.batch_size = 50
        self.igdb.concurrency = 8
        self.igdb.api_client.use_pro_tier = False

    def igdb_finishes_with(self, processed, errors):
        """Have the IGDB import report its totals as the real one does: to
        the progress callback, before it returns."""

        def import_games(games):
            report = self.service.call_args.kwargs["progress_callback"]
            report(
                "complete",
                {
                    "total": processed + errors,
                    "processed": processed,
                    "errors": errors,
                    "elapsed_seconds": 5,
                },
            )

        self.igdb.import_games.side_effect = import_games

    def test_one_run_refreshes_all_three(self):
        """The Wikipedia phase's HLTB id is the one the HLTB phase then
        looks the game up by, in the same run."""
        game = Game.objects.create(
            name="Chrono Trigger", rank=1, igdb_id=1063, wikidata_id="Q752241"
        )
        self.igdb_finishes_with(processed=1, errors=0)
        self.wikimedia.entities["Q752241"] = entity("Chrono Trigger", hltb_id="1705")
        self.wikimedia.pages["https://en.wikipedia.org/wiki/Chrono_Trigger"] = (
            genre_page("<a>Role-playing</a>")
        )
        self.hltb.async_search_from_id.return_value = hltb_entry(
            1705, "Chrono Trigger", main_story=23.1
        )

        output = self.refresh()

        self.igdb.import_games.assert_called_once()
        self.hltb.async_search_from_id.assert_awaited_once_with(1705)
        game.refresh_from_db()
        self.assertEqual(game.primary_wikipedia_game_data.primary_genre, "Role-Playing")
        self.assertEqual(game.primary_hltb_game_data.main_story_hours, Decimal("23.1"))
        for line in (
            "IGDB:      1/1 success (0 errors, 100.0%)",
            "Wikipedia: 1/1 pages found (0 errors, 100.0%)",
            "Genres:    1/1 scraped (100.0%)",
            "HLTB:      1/1 found (0 not found, 100.0%)",
            "Overall Status: SUCCESS",
        ):
            with self.subTest(line):
                self.assertIn(line, output)

    def test_igdb_errors_on_some_games_are_counted_not_failed(self):
        Game.objects.create(name="Alpha Quest", rank=1, igdb_id=7)
        self.igdb_finishes_with(processed=3, errors=1)

        output = self.refresh(igdb_only=True)

        self.assertIn("IGDB Complete: 3 processed, 1 errors in 5s", output)
        self.assertIn("IGDB:      3/4 success (1 errors, 75.0%)", output)
        self.assertIn("Overall Status: COMPLETED WITH ERRORS", output)
        self.assertNotIn("FAILED", output)

    def test_a_phase_that_was_not_run_has_no_line(self):
        Game.objects.create(name="Alpha Quest", rank=1, igdb_id=7)
        self.igdb_finishes_with(processed=1, errors=0)

        output = self.refresh(igdb_only=True)

        self.assertIn("IGDB:      1/1 success (0 errors, 100.0%)", output)
        for phase in ("Wikipedia:", "Genres:", "HLTB:"):
            with self.subTest(phase):
                self.assertNotIn(phase, output)

    def test_each_phase_that_fails_leaves_the_others_to_run(self):
        """Each catches its own error. Until 2026-11-10 the job then exited
        0 with all three FAILED, which Sentry's cron monitor read as a good
        Sunday."""
        Game.objects.create(name="Alpha Quest", rank=1, igdb_id=7, wikidata_id="Q7")
        self.igdb.import_games.side_effect = RuntimeError("IGDB is down")
        self.hltb_client.side_effect = RuntimeError("HLTB is down")

        with (
            mock.patch("aiohttp.ClientSession", side_effect=RuntimeError("no loop")),
            self.assertLogs(refresh_all_metadata.logger, "ERROR") as logs,
            self.assertRaisesMessage(
                CommandError, "failed outright for: IGDB, Wikipedia, HLTB"
            ),
        ):
            self.refresh()

        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["IGDB refresh failed", "Wikipedia refresh failed", "HLTB refresh failed"],
        )
        for line in (
            "IGDB refresh failed: IGDB is down",
            "Wikipedia refresh failed: no loop",
            "HLTB refresh failed: HLTB is down",
            "IGDB:      FAILED",
            "Wikipedia: FAILED",
            "HLTB:      FAILED",
        ):
            with self.subTest(line):
                self.assertIn(line, self.output)

    def test_one_failed_phase_does_not_cost_the_others_their_saves(self):
        game = Game.objects.create(
            name="Chrono Trigger", rank=1, igdb_id=1063, wikidata_id="Q752241"
        )
        self.igdb.import_games.side_effect = RuntimeError("IGDB is down")
        self.wikimedia.entities["Q752241"] = entity("Chrono Trigger")
        self.hltb.async_search.return_value = [
            hltb_entry(1705, "Chrono Trigger", similarity=1.0, main_story=23.1)
        ]

        with (
            self.assertLogs(refresh_all_metadata.logger, "ERROR"),
            self.assertRaisesMessage(CommandError, "failed outright for: IGDB"),
        ):
            self.refresh()

        game.refresh_from_db()
        self.assertEqual(game.primary_wikipedia_game_data.page_title, "Chrono Trigger")
        self.assertEqual(game.primary_hltb_game_data.hltb_id, "1705")

    def test_a_long_run_is_timed_in_minutes(self):
        """The weekly job takes most of an hour; up to a minute and a half
        reads better in seconds."""
        Game.objects.create(name="Alpha Quest", rank=1, igdb_id=7)
        for elapsed, duration in (
            (42.4, "Total Duration: 42 seconds"),
            (90, "Total Duration: 90 seconds"),
            (90.5, "Total Duration: 1 minutes 30 seconds"),
            (2825, "Total Duration: 47 minutes 5 seconds"),
        ):
            with self.subTest(elapsed=elapsed), mock.patch(f"{COMMAND}.time") as clock:
                # The first reading is the start; every later one, the end
                clock.time.side_effect = itertools.chain(
                    [1000.0], itertools.repeat(1000.0 + elapsed)
                )
                self.out = StringIO()
                self.assertIn(duration, self.refresh(igdb_only=True))

    def test_a_data_version_that_cannot_be_moved_is_a_warning(self):
        """Not a failed refresh: the phases' work is saved, and only the
        cached pages are behind."""
        game = Game.objects.create(name="Alpha Quest", rank=1, igdb_id=7, slug="alpha")
        self.igdb.import_games.side_effect = lambda games: Game.objects.filter(
            pk=game.pk
        ).update(slug="alpha-quest")

        with mock.patch(
            f"{COMMAND}.post_import.move_data_version", return_value=False
        ) as move:
            output = self.refresh(igdb_only=True)

        move.assert_called_once_with()
        self.assertIn("The games data version could not be moved", output)
        self.assertIn("Overall Status: SUCCESS", output)

    def test_a_data_version_that_was_moved_is_not_mentioned(self):
        game = Game.objects.create(name="Alpha Quest", rank=1, igdb_id=7, slug="alpha")
        self.igdb.import_games.side_effect = lambda games: Game.objects.filter(
            pk=game.pk
        ).update(slug="alpha-quest")

        output = self.refresh(igdb_only=True)

        self.assertNotIn("could not be moved", output)

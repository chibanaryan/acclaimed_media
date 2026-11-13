"""The staff import page's Wikipedia lookup stream.

No test ran it until 2026-11-12: two hundred lines that look each game up,
save what was found, scrape its genres and report progress.
"""

import json
from unittest import mock

from django.test import TestCase

from core.tests.utils import NoHeartbeatMixin
from games import models
from games.services import import_handler, progress_stream
from games.services.wiki_genre_service import GenreResult, GenreSource
from games.services.wiki_page_lookup_service import PageLookupResult
from games.tests.test_imports import InlineImportThreadMixin

PAGE_SERVICE = "games.services.wiki_page_lookup_service.WikiPageLookupService"
GENRE_SERVICE = "games.services.wiki_genre_service.WikiGenreService"


def events_of(stream):
    """The JSON events a stream yields, keepalives left out."""
    return [
        json.loads(chunk.split("data: ", 1)[1].split("\n", 1)[0])
        for chunk in stream
        if chunk.startswith("data: ")
    ]


def page(name, title="Alpha Quest (video game)", **fields):
    return PageLookupResult(
        game_name=name, page_title=title, lookup_source="wikidata", **fields
    )


def genres(*names):
    return GenreResult(
        game_name="",
        source=GenreSource.WIKIPEDIA,
        primary_genre=names[0] if names else None,
        all_genres=list(names),
    )


class WikipediaStreamTests(NoHeartbeatMixin, InlineImportThreadMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.alpha = models.Game.objects.create(
            name="Alpha Quest", rank=1, wikidata_id="Q1", year_of_release=1998
        )
        self.beta = models.Game.objects.create(name="Beta Racer", rank=2)
        page_patch = mock.patch(PAGE_SERVICE)
        genre_patch = mock.patch(GENRE_SERVICE)
        self.pages = page_patch.start().return_value
        self.genres = genre_patch.start().return_value
        self.addCleanup(page_patch.stop)
        self.addCleanup(genre_patch.stop)
        self.pages.lookup_page.side_effect = lambda name, wikidata_id, year: page(
            name, f"{name} (video game)"
        )
        self.genres.get_genre_from_url.return_value = genres("Platform", "Puzzle")

    def run_stream(self, **kwargs):
        return events_of(import_handler.import_wikipedia_pages_with_progress(**kwargs))

    def test_a_found_page_is_saved_with_its_genres(self):
        events = self.run_stream()

        self.alpha.refresh_from_db()
        record = self.alpha.primary_wikipedia_game_data
        self.assertEqual(record.page_title, "Alpha Quest (video game)")
        self.assertEqual(record.wikidata_id, "Q1")
        self.assertEqual(record.primary_genre, "Platform")
        self.assertEqual(
            sorted(self.alpha.wikipedia_genres.values_list("name", flat=True)),
            ["Platform", "Puzzle"],
        )
        self.pages.lookup_page.assert_any_call("Alpha Quest", "Q1", 1998)
        self.genres.get_genre_from_url.assert_any_call(
            "Alpha Quest", "https://en.wikipedia.org/wiki/Alpha_Quest_(video_game)"
        )
        self.assertEqual(events[0], {"total": 2, "event": "start"})
        self.assertEqual(
            events[1],
            {
                "current": 1,
                "total": 2,
                "game_name": "Alpha Quest",
                "page_title": "Alpha Quest (video game)",
                "lookup_source": "wikidata",
                "successful": 1,
                "failed": 0,
                "event": "progress",
            },
        )
        self.assertEqual(
            events[-1], {"total": 2, "successful": 2, "failed": 0, "event": "complete"}
        )

    def test_both_services_are_closed_when_the_lookup_ends(self):
        """Each holds an HTTP session."""
        self.run_stream()
        self.pages.close.assert_called_once_with()
        self.genres.close.assert_called_once_with()

    def test_only_games_without_a_page_are_looked_up(self):
        record = models.WikipediaGameData.objects.create(
            game=self.alpha, page_title="Alpha Quest", is_primary=True
        )
        self.alpha.primary_wikipedia_game_data = record
        self.alpha.save()

        events = self.run_stream()

        self.assertEqual(events[0]["total"], 1)
        self.pages.lookup_page.assert_called_once_with("Beta Racer", None, None)

    def test_a_game_whose_record_names_no_page_is_looked_up(self):
        """A lookup that found nothing leaves a record with a blank title."""
        record = models.WikipediaGameData.objects.create(
            game=self.alpha, page_title="", is_primary=True
        )
        self.alpha.primary_wikipedia_game_data = record
        self.alpha.save()
        self.assertEqual(self.run_stream()[0]["total"], 2)

    def test_force_looks_every_game_up(self):
        record = models.WikipediaGameData.objects.create(
            game=self.alpha, page_title="Alpha Quest", is_primary=True
        )
        self.alpha.primary_wikipedia_game_data = record
        self.alpha.save()
        self.assertEqual(self.run_stream(force_refresh=True)[0]["total"], 2)

    def test_a_page_not_found_is_counted_and_said(self):
        self.pages.lookup_page.side_effect = [
            PageLookupResult(game_name="Alpha Quest", error_message="No page found"),
            page("Beta Racer", "Beta Racer"),
        ]
        events = self.run_stream()

        self.assertEqual(
            events[1],
            {
                "current": 1,
                "total": 2,
                "game_name": "Alpha Quest",
                "error": "No page found",
                "successful": 0,
                "failed": 1,
                "event": "progress",
            },
        )
        self.assertEqual(
            events[-1], {"total": 2, "successful": 1, "failed": 1, "event": "complete"}
        )
        self.alpha.refresh_from_db()
        self.assertIsNone(self.alpha.primary_wikipedia_game_data)

    def test_a_page_with_no_genres_is_still_saved(self):
        self.genres.get_genre_from_url.return_value = genres()
        events = self.run_stream()

        self.alpha.refresh_from_db()
        self.assertIsNone(self.alpha.primary_wikipedia_game_data.primary_genre)
        self.assertEqual(self.alpha.wikipedia_genres.count(), 0)
        self.assertEqual(events[-1]["successful"], 2)

    def test_a_genre_scrape_that_fails_keeps_the_page(self):
        self.genres.get_genre_from_url.side_effect = RuntimeError("no infobox")
        with self.assertLogs(import_handler.logger, level="WARNING") as logs:
            events = self.run_stream()

        self.assertIn("Failed to scrape genres for 'Alpha Quest'", logs.output[0])
        self.alpha.refresh_from_db()
        self.assertIsNotNone(self.alpha.primary_wikipedia_game_data)
        self.assertEqual(events[-1]["successful"], 2)

    def test_one_games_error_is_its_own_and_its_text_stays_in_the_log(self):
        """An exception's text can carry SQL and paths: the page gets a
        stock line, as the batch import's does. It was sent as raised."""
        self.pages.lookup_page.side_effect = [
            RuntimeError("secret /srv/path"),
            page("Beta Racer", "Beta Racer"),
        ]
        with self.assertLogs(import_handler.logger, level="ERROR") as logs:
            events = self.run_stream()

        self.assertIn("secret /srv/path", logs.output[0])
        self.assertNotIn("secret", json.dumps(events))
        self.assertEqual(events[1]["error"], import_handler.GAME_FAILED)
        self.assertEqual((events[1]["successful"], events[1]["failed"]), (0, 1))
        self.assertEqual(
            events[-1], {"total": 2, "successful": 1, "failed": 1, "event": "complete"}
        )

    def test_a_lookup_that_cannot_start_is_one_stock_error(self):
        with (
            mock.patch.object(
                progress_stream.ProgressEvents, "emit", side_effect=RuntimeError("boom")
            ),
            self.assertLogs(import_handler.logger, level="ERROR"),
        ):
            events = self.run_stream()

        self.assertEqual(
            events, [{"event": "error", "error": import_handler.WIKIPEDIA_FAILED}]
        )
        self.pages.close.assert_called_once_with()

    def test_services_that_cannot_be_built_are_one_stock_error(self):
        with (
            mock.patch(PAGE_SERVICE, side_effect=RuntimeError("no session")),
            self.assertLogs(import_handler.logger, level="ERROR"),
        ):
            events = self.run_stream()
        self.assertEqual(
            events, [{"event": "error", "error": import_handler.WIKIPEDIA_FAILED}]
        )

    def test_a_client_that_leaves_ends_the_lookup_at_the_next_game(self):
        made = []

        class Watched(progress_stream.ProgressEvents):
            def __init__(self):
                super().__init__()
                made.append(self)

        def leave_during_the_first(name, wikidata_id, year):
            made[0].stop()
            return page(name)

        self.pages.lookup_page.side_effect = leave_during_the_first
        with (
            mock.patch.object(import_handler, "ProgressEvents", Watched),
            self.assertLogs(import_handler.logger, level="INFO") as logs,
        ):
            stream = import_handler.import_wikipedia_pages_with_progress()
            first = next(stream)
            stream.close()

        self.assertIn('"event": "start"', first)
        self.pages.lookup_page.assert_called_once_with("Alpha Quest", "Q1", 1998)
        self.assertIn("Client disconnected from Wikipedia page lookup", logs.output[0])

    @mock.patch("queue.Queue")
    def test_half_an_hour_of_quiet_ends_the_stream(self, queue_class):
        import queue

        queue_class.return_value.get.side_effect = queue.Empty()
        chunks = list(import_handler.import_wikipedia_pages_with_progress())

        self.assertEqual(chunks[:-1], [": keepalive\n\n"] * 119)
        self.assertEqual(
            json.loads(chunks[-1].split("data: ", 1)[1]),
            {"event": "error", "error": "Lookup timeout - no progress for 30 minutes"},
        )

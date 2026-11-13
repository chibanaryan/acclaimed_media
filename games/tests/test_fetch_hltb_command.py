"""Tests for the fetch_hltb_data management command."""

import csv
import os
import tempfile
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.db import DEFAULT_DB_ALIAS, connections
from django.test import TestCase

from core.cache_helpers import forget_queued_drops
from games.models import Game, HLTBGameData, WikipediaGameData
from games.services import hltb_matching


class FetchHltbDataCommandTests(TestCase):
    """Tests for the fetch_hltb_data management command."""

    def setUp(self):
        """Set up test games."""
        # The command waits between HowLongToBeat requests to stay polite;
        # under test that was a real second a test
        patcher = mock.patch(
            "games.management.commands.fetch_hltb_data.asyncio.sleep",
            new=mock.AsyncMock(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.game_with_hltb_id = Game.objects.create(
            name="Test Game With HLTB ID",
            rank=1,
            wikidata_id="Q123456",
        )

        # Create Wikipedia data with HLTB ID
        wiki_data = WikipediaGameData.objects.create(
            game=self.game_with_hltb_id,
            page_title="Test Game With HLTB ID",
            hltb_id="12345",
            is_primary=True,
        )
        self.game_with_hltb_id.primary_wikipedia_game_data = wiki_data
        self.game_with_hltb_id.save()

        self.game_without_hltb_id = Game.objects.create(
            name="Test Game Without HLTB ID",
            rank=2,
        )

    def test_name_search_enabled_by_default(self):
        """Test that name search is enabled by default."""
        out = StringIO()

        with mock.patch("howlongtobeatpy.HowLongToBeat") as mock_hltb_class:
            mock_hltb = mock_hltb_class.return_value

            # Name search returns results
            mock_result = mock.MagicMock()
            mock_result.game_id = 99999
            mock_result.game_name = "Test Game Without HLTB ID"
            mock_result.main_story = 10.0
            mock_result.main_extra = 15.0
            mock_result.completionist = 20.0
            mock_result.similarity = 0.9
            mock_hltb.async_search = mock.AsyncMock(return_value=[mock_result])

            call_command(
                "fetch_hltb_data",
                "--game",
                "Test Game Without HLTB ID",
                stdout=out,
            )

        output = out.getvalue()

        # Name search should be called by default
        mock_hltb.async_search.assert_called()

        # Output should NOT indicate name search disabled
        self.assertNotIn("name search DISABLED", output)

    def test_name_search_disabled_with_flag(self):
        """Test that name search is disabled when --no-name-search is specified."""
        out = StringIO()

        # Mock HowLongToBeat at the module where it's imported
        with mock.patch("howlongtobeatpy.HowLongToBeat") as mock_hltb_class:
            mock_hltb = mock_hltb_class.return_value

            # Direct ID lookup succeeds for game with HLTB ID
            mock_result = mock.MagicMock()
            mock_result.game_id = 12345
            mock_result.game_name = "Test Game"
            mock_result.main_story = 10.0
            mock_result.main_extra = 15.0
            mock_result.completionist = 20.0
            mock_result.similarity = 1.0
            mock_hltb.async_search_from_id = mock.AsyncMock(return_value=mock_result)

            # Name search should NOT be called when --no-name-search is specified
            mock_hltb.async_search = mock.AsyncMock(return_value=[])

            call_command(
                "fetch_hltb_data",
                "--game",
                "Test Game Without HLTB ID",
                "--no-name-search",
                stdout=out,
            )

        output = out.getvalue()

        # Name search should not be called when --no-name-search is specified
        mock_hltb.async_search.assert_not_called()

        # Output should indicate name search is disabled
        self.assertIn("name search DISABLED", output)

        # Output should indicate no Wikidata HLTB ID
        self.assertIn("No Wikidata HLTB ID available", output)

    def test_wikidata_lookup_used_when_id_available(self):
        """Test that Wikidata HLTB ID is used for direct lookup."""
        out = StringIO()

        with mock.patch("howlongtobeatpy.HowLongToBeat") as mock_hltb_class:
            mock_hltb = mock_hltb_class.return_value

            mock_result = mock.MagicMock()
            mock_result.game_id = 12345
            mock_result.game_name = "Test Game"
            mock_result.main_story = 10.0
            mock_result.main_extra = 15.0
            mock_result.completionist = 20.0
            mock_result.similarity = 1.0
            mock_hltb.async_search_from_id = mock.AsyncMock(return_value=mock_result)

            call_command(
                "fetch_hltb_data",
                "--game",
                "Test Game With HLTB ID",
                stdout=out,
            )

        output = out.getvalue()

        # Should use Wikidata direct lookup
        mock_hltb.async_search_from_id.assert_called_once_with(12345)
        self.assertIn("Direct lookup via Wikidata HLTB ID", output)

    def test_error_message_when_wikidata_lookup_fails(self):
        """Test error message when Wikidata HLTB ID lookup fails."""
        out = StringIO()

        with mock.patch("howlongtobeatpy.HowLongToBeat") as mock_hltb_class:
            mock_hltb = mock_hltb_class.return_value

            # Direct lookup fails
            mock_hltb.async_search_from_id = mock.AsyncMock(return_value=None)

            call_command(
                "fetch_hltb_data",
                "--game",
                "Test Game With HLTB ID",
                "--no-name-search",  # Disable fallback to get the error message
                stdout=out,
            )

        output = out.getvalue()

        # Should indicate lookup failed
        self.assertIn("Wikidata HLTB ID(s) [12345] lookup failed", output)

    def test_multi_wikidata_fallback_to_alternate_hltb_id(self):
        """Test that command iterates through multiple WikipediaGameData records.

        When primary WikipediaGameData doesn't have an HLTB ID but an alternate
        record does (like Counter-Strike), the command should find and use it.
        """
        # Create a game with multiple WikipediaGameData records
        game = Game.objects.create(
            name="Counter-Strike",
            rank=100,
            igdb_id=99999,
        )

        # Primary record - NO HLTB ID (like Counter-Strike's main Wikidata entry)
        primary_wiki = WikipediaGameData.objects.create(
            game=game,
            page_title="Counter-Strike",
            wikidata_id="Q1111111",  # Main Wikidata entry without HLTB
            hltb_id=None,  # No HLTB ID
            is_primary=True,
        )
        game.primary_wikipedia_game_data = primary_wiki
        game.save()

        # Alternate record - HAS HLTB ID (specific version entry in Wikidata)
        WikipediaGameData.objects.create(
            game=game,
            page_title="Counter-Strike (video game)",
            wikidata_id="Q2222222",  # Alternate Wikidata entry with HLTB
            hltb_id="5555",  # Has HLTB ID
            is_primary=False,
        )

        out = StringIO()

        with mock.patch("howlongtobeatpy.HowLongToBeat") as mock_hltb_class:
            mock_hltb = mock_hltb_class.return_value

            # Direct lookup succeeds for the alternate HLTB ID
            # Create a proper mock object that won't create auto-attributes
            class MockHLTBResult:
                game_id = 5555
                game_name = "Counter-Strike"
                main_story = 0.0
                main_extra = 0.0
                completionist = 0.0
                similarity = 1.0
                release_world = None
                profile_platforms = None

            mock_result = MockHLTBResult()
            mock_hltb.async_search_from_id = mock.AsyncMock(return_value=mock_result)

            call_command(
                "fetch_hltb_data",
                "--game",
                "Counter-Strike",
                stdout=out,
            )

        output = out.getvalue()

        # Should find HLTB data via alternate record
        mock_hltb.async_search_from_id.assert_called_once_with(5555)
        self.assertIn("Direct lookup via Wikidata HLTB ID 5555", output)
        self.assertIn("via alternate Wikidata Q2222222", output)

    def test_multi_wikidata_primary_used_first(self):
        """Test that primary WikipediaGameData is checked first.

        If primary has an HLTB ID, it should be used without checking alternates.
        """
        # Create a game with multiple WikipediaGameData records
        game = Game.objects.create(
            name="Test Multi Game",
            rank=101,
            igdb_id=88888,
        )

        # Primary record - HAS HLTB ID
        primary_wiki = WikipediaGameData.objects.create(
            game=game,
            page_title="Test Multi Game",
            wikidata_id="Q3333333",
            hltb_id="1111",  # Primary has HLTB ID
            is_primary=True,
        )
        game.primary_wikipedia_game_data = primary_wiki
        game.save()

        # Alternate record - also has HLTB ID (but should not be used)
        WikipediaGameData.objects.create(
            game=game,
            page_title="Test Multi Game (alternate)",
            wikidata_id="Q4444444",
            hltb_id="2222",  # Alternate also has HLTB ID
            is_primary=False,
        )

        out = StringIO()

        with mock.patch("howlongtobeatpy.HowLongToBeat") as mock_hltb_class:
            mock_hltb = mock_hltb_class.return_value

            mock_result = mock.MagicMock()
            mock_result.game_id = 1111
            mock_result.game_name = "Test Multi Game"
            mock_result.main_story = 10.0
            mock_result.main_extra = 15.0
            mock_result.completionist = 20.0
            mock_result.similarity = 1.0
            mock_hltb.async_search_from_id = mock.AsyncMock(return_value=mock_result)

            call_command(
                "fetch_hltb_data",
                "--game",
                "Test Multi Game",
                stdout=out,
            )

        output = out.getvalue()

        # Should use primary's HLTB ID (1111), not alternate's (2222)
        mock_hltb.async_search_from_id.assert_called_once_with(1111)
        self.assertIn("Direct lookup via Wikidata HLTB ID 1111", output)
        # Should NOT mention alternate Wikidata
        self.assertNotIn("via alternate Wikidata", output)


COMMAND = "games.management.commands.fetch_hltb_data"


def hltb_entry(game_id, game_name, **values):
    """An entry as howlongtobeatpy gives one, holding what the command reads."""
    values = {
        "main_story": 10.0,
        "main_extra": 15.0,
        "completionist": 20.0,
        "similarity": 1.0,
        "json_content": None,
        **values,
    }
    return SimpleNamespace(game_id=game_id, game_name=game_name, **values)


def _on_connection(borrowed, function):
    """``function``, run on whatever thread calls it with the connection
    ``borrowed`` in place of that thread's own."""

    def call(*args, **kwargs):
        own = connections[DEFAULT_DB_ALIAS]
        connections[DEFAULT_DB_ALIAS] = borrowed
        try:
            return function(*args, **kwargs)
        finally:
            connections[DEFAULT_DB_ALIAS] = own
            # A save's signals queue cache drops for a commit that never comes
            forget_queued_drops()

    return call


class CommandTestCase(TestCase):
    """Runs the command against a HowLongToBeat that answers from two dicts."""

    def setUp(self):
        self.sleep = mock.AsyncMock()
        # The command saves through sync_to_async, on asgiref's executor
        # thread, which has a database connection of its own. That one cannot
        # see this test's uncommitted games (on SQLite their table is locked
        # to it), and on Postgres it would commit what it saved. So the save
        # borrows the test's connection, as a live server's thread does
        tests_connection = connections[DEFAULT_DB_ALIAS]
        tests_connection.inc_thread_sharing()
        self.addCleanup(tests_connection.dec_thread_sharing)
        patches = [
            mock.patch(f"{COMMAND}.asyncio.sleep", new=self.sleep),
            mock.patch(
                f"{COMMAND}.hltb_matching.save_entry",
                new=_on_connection(tests_connection, hltb_matching.save_entry),
            ),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_command(self, *args, by_id=None, by_name=None):
        """The command's output, with HLTB answering a lookup from ``by_id``
        and a search from ``by_name``; an exception there is raised."""

        def answer(answers, key, default):
            result = (answers or {}).get(key, default)
            if isinstance(result, Exception):
                raise result
            return result

        out = StringIO()
        with mock.patch("howlongtobeatpy.HowLongToBeat") as self.hltb_class:
            self.hltb = self.hltb_class.return_value
            self.hltb.async_search_from_id = mock.AsyncMock(
                side_effect=lambda hltb_id: answer(by_id, hltb_id, None)
            )
            self.hltb.async_search = mock.AsyncMock(
                side_effect=lambda name: answer(by_name, name, [])
            )
            call_command("fetch_hltb_data", *args, stdout=out)
        return out.getvalue()

    def searched_for(self):
        return [call.args[0] for call in self.hltb.async_search.call_args_list]

    def looked_up(self):
        return [call.args[0] for call in self.hltb.async_search_from_id.call_args_list]

    def game_with_hltb_ids(self, name, *hltb_ids, **fields):
        """A game whose Wikipedia records hold ``hltb_ids``, the first primary."""
        game = Game.objects.create(name=name, **{"rank": 1, **fields})
        for position, hltb_id in enumerate(hltb_ids):
            record = WikipediaGameData.objects.create(
                game=game,
                page_title=name,
                wikidata_id=f"Q{position + 1}",
                hltb_id=hltb_id,
                is_primary=position == 0,
            )
            if position == 0:
                game.primary_wikipedia_game_data = record
                game.save()
        return game


class WhichGamesTests(CommandTestCase):
    """What each selecting option hands to HowLongToBeat, and in what order."""

    def setUp(self):
        super().setUp()
        # Created out of rank order, and the second has its playtimes already
        self.alpha = Game.objects.create(name="Alpha", slug="alpha", rank=2)
        self.bravo = Game.objects.create(name="Bravo", slug="bravo", rank=1)
        self.charlie = Game.objects.create(name="Charlie", slug="charlie", rank=3)
        self.alpha.primary_hltb_game_data = HLTBGameData.objects.create(
            game=self.alpha, igdb_id=1, hltb_id="1", is_primary=True
        )
        self.alpha.save()

    def test_games_without_playtimes_are_fetched_in_rank_order(self):
        output = self.run_command()
        self.assertEqual(self.searched_for(), ["Bravo", "Charlie"])
        self.assertIn("Processing 2 games...", output)

    def test_force_fetches_the_games_that_have_playtimes_too(self):
        self.run_command("--force")
        self.assertEqual(self.searched_for(), ["Bravo", "Alpha", "Charlie"])

    def test_offset_skips_the_first_games(self):
        self.run_command("--force", "--offset", "1")
        self.assertEqual(self.searched_for(), ["Alpha", "Charlie"])

    def test_limit_stops_after_that_many(self):
        self.run_command("--force", "--limit", "2")
        self.assertEqual(self.searched_for(), ["Bravo", "Alpha"])

    def test_limit_counts_from_the_offset(self):
        output = self.run_command("--force", "--offset", "1", "--limit", "1")
        self.assertEqual(self.searched_for(), ["Alpha"])
        self.assertIn("Processing 1 games...", output)

    def test_slug_picks_one_game_whether_or_not_it_has_playtimes(self):
        self.run_command("--slug", "alpha")
        self.assertEqual(self.searched_for(), ["Alpha"])

    def test_id_picks_one_game_by_its_primary_key(self):
        self.run_command("--id", str(self.charlie.id))
        self.assertEqual(self.searched_for(), ["Charlie"])

    def test_a_name_nobody_has_is_reported_and_asks_hltb_nothing(self):
        output = self.run_command("--game", "Delta")
        self.assertIn("No games found to process", output)
        self.assertNotIn("Processing", output)
        self.hltb_class.assert_not_called()

    def test_each_game_is_followed_by_the_delay(self):
        self.run_command("--delay", "0.25")
        self.assertEqual(self.sleep.await_args_list, [mock.call(0.25)] * 2)


class SavingTests(CommandTestCase):
    def test_nothing_is_stored_without_save(self):
        self.game_with_hltb_ids("Portal", "111", igdb_id=71)
        output = self.run_command(by_id={111: hltb_entry(111, "Portal")})
        self.assertIn("HLTB data found: 1", output)
        self.assertNotIn("Results saved to database", output)
        self.assertFalse(HLTBGameData.objects.exists())

    def test_save_stores_a_direct_lookup_as_the_games_primary_record(self):
        game = self.game_with_hltb_ids("Rocket League", "111", igdb_id=71)
        found = hltb_entry(
            111,
            "Rocket League (2015)",
            main_story=5.04,
            main_extra=0,
            completionist=0,
            json_content={
                "game_type": "multi",
                "comp_lvl_combine": 1,
                "comp_main_count": 40,
                "comp_plus_count": 0,
                "comp_100_count": "x",
            },
        )

        output = self.run_command("--save", by_id={111: found})

        self.assertEqual(self.looked_up(), [111])
        self.assertEqual(self.searched_for(), [])
        row = HLTBGameData.objects.get()
        game.refresh_from_db()
        self.assertEqual(game.primary_hltb_game_data, row)
        self.assertEqual(
            (row.game, row.igdb_id, row.is_primary, row.fetch_method),
            (game, 71, True, "wikidata"),
        )
        self.assertEqual((row.hltb_id, row.hltb_name), ("111", "Rocket League (2015)"))
        self.assertEqual(row.similarity, Decimal("1.0"))
        # A time HLTB gives as 0 is no time
        self.assertEqual(
            (row.main_story_hours, row.main_extra_hours, row.completionist_hours),
            (Decimal("5.0"), None, None),
        )
        # HLTB's own description of the entry, which decides "open-ended"
        self.assertEqual((row.game_type, row.comp_lvl_combine), ("multi", True))
        self.assertEqual(
            (row.main_story_count, row.main_extra_count, row.completionist_count),
            (40, 0, None),
        )
        self.assertTrue(row.is_open_ended)
        self.assertIn("Results saved to database", output)

    def test_save_stores_a_name_search_with_its_similarity(self):
        game = Game.objects.create(name="Braid", rank=1, igdb_id=72)
        found = hltb_entry(222, "Braid", similarity=0.9)

        output = self.run_command("--save", by_name={"Braid": [found]})

        row = HLTBGameData.objects.get()
        self.assertEqual(
            (row.game, row.hltb_id, row.fetch_method, row.similarity),
            (game, "222", "name_search", Decimal("0.9")),
        )
        self.assertIn(
            "[1/1] ✓ Braid: Braid (0.90) - "
            "Main: 10.0h, Extra: 15.0h, Complete: 20.0h",
            output,
        )

    def test_a_save_that_fails_is_a_failure_and_not_a_game_found(self):
        Game.objects.create(name="Braid", rank=1, igdb_id=72)
        found = hltb_entry(222, "Braid")

        with (
            mock.patch(
                f"{COMMAND}.hltb_matching.save_entry",
                side_effect=RuntimeError("the database went away"),
            ),
            self.assertLogs(COMMAND, "WARNING"),
        ):
            output = self.run_command("--save", by_name={"Braid": [found]})

        self.assertIn("✗ Braid: the database went away", output)
        self.assertIn("HLTB data found: 0", output)
        self.assertIn("HLTB data not found: 1", output)


class LookupTests(CommandTestCase):
    def test_a_lookup_that_raises_gives_way_to_the_games_next_hltb_id(self):
        game = self.game_with_hltb_ids("Counter-Strike", "111", "222", igdb_id=73)
        answers = {111: OSError("timed out"), 222: hltb_entry(222, "Counter-Strike")}

        with self.assertLogs(COMMAND, "DEBUG") as logs:
            output = self.run_command("--save", by_id=answers)

        self.assertEqual(self.looked_up(), [111, 222])
        self.assertEqual(
            logs.output,
            [f"DEBUG:{COMMAND}:Direct HLTB lookup failed for ID 111: timed out"],
        )
        self.assertIn(
            "Direct lookup via Wikidata HLTB ID 222 (via alternate Wikidata Q2)",
            output,
        )
        self.assertEqual(HLTBGameData.objects.get(game=game).hltb_id, "222")
        self.assertIn("HLTB data found: 1", output)
        self.assertNotIn("HLTB data not found", output)

    def test_an_hltb_id_that_is_no_number_gives_way_to_the_name_search(self):
        game = self.game_with_hltb_ids("Braid", "not-a-number", igdb_id=72)
        found = hltb_entry(222, "Braid", similarity=0.9)

        with self.assertLogs(COMMAND, "DEBUG"):
            output = self.run_command("--save", by_name={"Braid": [found]})

        self.assertEqual(self.looked_up(), [])
        row = HLTBGameData.objects.get(game=game)
        self.assertEqual((row.hltb_id, row.fetch_method), ("222", "name_search"))
        # The match is named, as any name search's is
        self.assertIn("[1/1] ✓ Braid: Braid (0.90)", output)

    def test_wikipedias_title_is_searched_first_and_the_first_match_ends_it(self):
        game = Game.objects.create(name="Final Fantasy VII", rank=1, igdb_id=74)
        game.primary_wikipedia_game_data = WikipediaGameData.objects.create(
            game=game,
            page_title="Final Fantasy VII (1997 video game)",
            is_primary=True,
        )
        game.save()
        found = hltb_entry(333, "Final Fantasy VII")

        self.run_command("--save", by_name={"Final Fantasy VII": [found]})

        # "Final Fantasy 7", the last name to try, is never asked for
        self.assertEqual(
            self.searched_for(),
            [
                "Final Fantasy VII (1997 video game)",
                "Final Fantasy 7 (1997 video game)",
                "Final Fantasy VII",
            ],
        )
        self.assertEqual(HLTBGameData.objects.get(game=game).hltb_id, "333")

    def test_a_game_no_name_finds_is_reported_once_every_name_is_tried(self):
        Game.objects.create(name="Street Fighter 2", rank=1, igdb_id=75)

        output = self.run_command("--save")

        self.assertEqual(self.searched_for(), ["Street Fighter 2", "Street Fighter II"])
        self.assertIn(
            "[1/1] ✗ Street Fighter 2: No results found via name search", output
        )
        self.assertIn("HLTB data found: 0", output)
        self.assertIn("HLTB data not found: 1", output)
        self.assertFalse(HLTBGameData.objects.exists())

    def test_min_similarity_decides_which_entries_count(self):
        Game.objects.create(name="Braid", rank=1, igdb_id=72)
        loose = {"Braid": [hltb_entry(222, "Braid: Anniversary", similarity=0.5)]}

        self.run_command("--save", by_name=loose)
        self.assertFalse(HLTBGameData.objects.exists())

        self.run_command("--save", "--min-similarity", "0.4", by_name=loose)
        self.assertEqual(HLTBGameData.objects.get().hltb_name, "Braid: Anniversary")


class OneGameFailingTests(CommandTestCase):
    def test_the_other_games_are_still_fetched_and_saved(self):
        failing = Game.objects.create(name="Alpha", rank=1, igdb_id=81)
        fine = Game.objects.create(name="Bravo", rank=2, igdb_id=82)
        answers = {
            "Alpha": RuntimeError("HLTB said no. " + "x" * 200),
            "Bravo": [hltb_entry(222, "Bravo")],
        }

        with self.assertLogs(COMMAND, "WARNING") as logs:
            output = self.run_command("--save", by_name=answers)

        # The log has the whole error; the line printed, its first 100 characters
        self.assertEqual(len(logs.output), 1)
        self.assertIn(
            "Failed to fetch HLTB data for 'Alpha': HLTB said no.", logs.output[0]
        )
        self.assertTrue(logs.output[0].endswith("x" * 200))
        self.assertIn("[1/2] ✗ Alpha: HLTB said no. " + "x" * 86 + "\n", output)
        self.assertFalse(HLTBGameData.objects.filter(game=failing).exists())
        self.assertEqual(HLTBGameData.objects.get().game, fine)
        self.assertIn("Total games: 2", output)
        self.assertIn("HLTB data found: 1", output)
        self.assertIn("HLTB data not found: 1", output)


class CsvOutputTests(CommandTestCase):
    HEADER = [
        "Rank",
        "Game Name",
        "Year",
        "Fetch Method",
        "HLTB ID",
        "HLTB Name",
        "Similarity",
        "Main Story (h)",
        "Main + Extra (h)",
        "Completionist (h)",
        "Error",
    ]

    def test_output_writes_a_row_for_every_game_found_or_not(self):
        self.game_with_hltb_ids("Portal", "111", rank=1, year_of_release=2007)
        Game.objects.create(name="Braid", rank=2, year_of_release=2008)
        Game.objects.create(name="Alpha", rank=3)
        Game.objects.create(name="Bravo", rank=4)
        by_id = {111: hltb_entry(111, "Portal (2007)", completionist=0)}
        by_name = {
            "Braid": [hltb_entry(222, "Braid", similarity=0.9)],
            "Bravo": ValueError("HLTB said no"),
        }

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "hltb.csv")
            with self.assertLogs(COMMAND, "WARNING"):
                output = self.run_command(
                    "--output", path, by_id=by_id, by_name=by_name
                )
            with open(path, newline="", encoding="utf-8") as csv_file:
                rows = list(csv.reader(csv_file))

        self.assertEqual(
            rows,
            [
                self.HEADER,
                ["1", "Portal", "2007", "wikidata", "111", "Portal (2007)"]
                + ["1.00", "10.0", "15.0", "", ""],
                ["2", "Braid", "2008", "name_search", "222", "Braid"]
                + ["0.90", "10.0", "15.0", "20.0", ""],
                ["3", "Alpha", "", "", "", "", "", "", "", ""]
                + ["No results found via name search"],
                ["4", "Bravo", "", "", "", "", "", "", "", "", "HLTB said no"],
            ],
        )
        self.assertIn(f"Writing results to: {path}", output)
        self.assertIn(f"✓ Results written to {path}", output)
        # A CSV alone saves nothing
        self.assertFalse(HLTBGameData.objects.exists())

    def test_no_file_is_named_without_output(self):
        Game.objects.create(name="Braid", rank=1)
        output = self.run_command()
        self.assertNotIn("Writing results to", output)
        self.assertNotIn("Results written to", output)

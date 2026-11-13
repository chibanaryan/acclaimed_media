"""Parts of the import handler no test ran until 2026-11-12.

The two "clear metadata" actions on the staff page, a batch cancelled
between files, a stream whose import raises, the sequence reset after a
delete on Postgres, and an import taking back the HowLongToBeat row a game
had before it.
"""

import json
from io import StringIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from games import models
from games.services import import_handler
from games.tests.test_imports import InlineImportThreadMixin


def events_of(stream):
    return [
        json.loads(chunk.split("data: ", 1)[1].split("\n", 1)[0])
        for chunk in stream
        if chunk.startswith("data: ")
    ]


class StartImportThreadTests(TestCase):
    def test_an_import_runs_on_a_background_thread(self):
        """Every other test patches this name to run the import inline."""
        target = mock.Mock()
        with mock.patch.object(import_handler, "start_background_thread") as start:
            started = import_handler._start_import_thread(target)
        start.assert_called_once_with(target)
        self.assertIs(started, start.return_value)


class ClearMetadataTests(TestCase):
    """The staff form's "Clear IGDB metadata" and "Clear Wikipedia metadata"."""

    def setUp(self):
        self.game = models.Game.objects.create(name="Alpha Quest", rank=1, igdb_id=7)
        self.igdb = models.IGDBGameData.objects.create(
            game=self.game, igdb_id=7, url="https://igdb.example/alpha", is_primary=True
        )
        self.wiki = models.WikipediaGameData.objects.create(
            game=self.game, page_title="Alpha Quest", is_primary=True
        )
        self.hltb = models.HLTBGameData.objects.create(
            game=self.game, igdb_id=7, hltb_id="1", is_primary=True
        )
        self.game.primary_igdb_game_data = self.igdb
        self.game.primary_wikipedia_game_data = self.wiki
        self.game.primary_hltb_game_data = self.hltb
        self.game.save()
        self.game.developers.add(
            models.Developer.objects.create(name="Studio", slug="studio", igdb_id=3)
        )
        self.game.series.add(
            models.Series.objects.create(name="Quest", slug="quest", igdb_id=4)
        )
        models.WikipediaGenre.objects.all().delete()
        self.game.wikipedia_genres.add(
            models.WikipediaGenre.objects.create(name="Platform")
        )
        # An orphan, as an import leaves the records of a game it dropped
        models.IGDBGameData.objects.create(
            game=None, igdb_id=8, url="https://igdb.example/beta", is_primary=True
        )

    def test_clearing_igdb_takes_its_records_and_what_came_from_them(self):
        ok, message = import_handler.import_data({"clear_igdb_metadata": True})

        self.assertTrue(ok)
        self.assertEqual(message, "Cleared 2 IGDB records, 1 developers, 1 series")
        self.assertEqual(models.IGDBGameData.objects.count(), 0)
        self.assertEqual(models.Developer.objects.count(), 0)
        self.assertEqual(models.Series.objects.count(), 0)
        self.game.refresh_from_db()
        self.assertIsNone(self.game.primary_igdb_game_data)

    def test_clearing_igdb_leaves_the_game_and_its_other_metadata(self):
        import_handler.import_data({"clear_igdb_metadata": True})

        self.game.refresh_from_db()
        self.assertEqual(self.game.primary_wikipedia_game_data, self.wiki)
        self.assertEqual(self.game.primary_hltb_game_data, self.hltb)
        self.assertEqual(self.game.wikipedia_genres.count(), 1)

    def test_clearing_wikipedia_takes_its_records_and_the_genres(self):
        ok, message = import_handler.import_data({"clear_wikipedia_metadata": True})

        self.assertTrue(ok)
        self.assertEqual(message, "Cleared 1 Wikipedia records, 1 genres")
        self.assertEqual(models.WikipediaGameData.objects.count(), 0)
        self.assertEqual(models.WikipediaGenre.objects.count(), 0)
        self.game.refresh_from_db()
        self.assertIsNone(self.game.primary_wikipedia_game_data)

    def test_clearing_wikipedia_leaves_igdb_and_playtimes(self):
        import_handler.import_data({"clear_wikipedia_metadata": True})

        self.game.refresh_from_db()
        self.assertEqual(self.game.primary_igdb_game_data, self.igdb)
        self.assertEqual(self.game.primary_hltb_game_data, self.hltb)
        self.assertEqual(self.game.developers.count(), 1)
        self.assertEqual(self.game.series.count(), 1)


class DeleteResetsSequencesTests(TestCase):
    def test_postgres_restarts_each_deleted_tables_id_sequence(self):
        """SQLite's branch runs under every test; this is production's."""
        with mock.patch.object(import_handler, "connection") as connection:
            connection.vendor = "postgresql"
            connection.ops.quote_name.side_effect = lambda name: f'"{name}"'
            ok, _message = import_handler.delete_existing_data()

        self.assertTrue(ok)
        cursor = connection.cursor.return_value.__enter__.return_value
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn('ALTER SEQUENCE "games_game_id_seq" RESTART WITH 1;', statements)
        self.assertTrue(
            all(statement.startswith("ALTER SEQUENCE ") for statement in statements)
        )
        self.assertEqual(len(statements), len(set(statements)))


class CancelledBatchTests(TestCase):
    def test_a_batch_whose_page_has_gone_imports_nothing(self):
        platforms = SimpleUploadedFile("PlatformDB.txt", b"PC\tPC\r\n")
        result = import_handler._run_batch(
            {"platforms_file": platforms}, cancelled=lambda: True
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, import_handler.IMPORT_CANCELLED)
        self.assertIsNone(result.failed_file)
        self.assertFalse(models.Platform.objects.filter(code="PC").exists())


class BatchStreamFailureTests(InlineImportThreadMixin, TestCase):
    def test_an_import_that_raises_is_one_stock_error(self):
        """`_run_batch` is written never to raise; if it does, staff get
        the stock line and the log gets the exception."""
        with (
            mock.patch.object(
                import_handler, "_run_batch", side_effect=RuntimeError("secret")
            ),
            self.assertLogs(import_handler.logger, level="ERROR") as logs,
        ):
            events = events_of(import_handler.import_batch_with_progress({}))

        self.assertEqual(
            events, [{"event": "error", "message": import_handler.IMPORT_FAILED}]
        )
        self.assertIn("Batch import failed", logs.output[0])

    def test_a_failure_that_names_no_file_is_said_once(self):
        """A failed file is two events (which file, then that the batch
        was rolled back); a failure outside any file is one."""
        with (
            mock.patch.object(
                import_handler, "_import_sequence", side_effect=RuntimeError("secret")
            ),
            self.assertLogs(import_handler.logger, level="ERROR"),
        ):
            events = events_of(import_handler.import_batch_with_progress({}))

        self.assertEqual(
            events, [{"event": "error", "message": import_handler.IMPORT_FAILED}]
        )


class ImportTakesBackPlaytimesTests(TestCase):
    """HLTB rows outlive an import, which recreates every game."""

    FILE = "1\tAlpha Quest\t1998\tPC\t7,70\tQ1\r\n"

    def test_a_reimported_game_gets_its_hltb_row_back(self):
        import_handler.import_games(StringIO(self.FILE))
        first = models.Game.objects.get()
        row = models.HLTBGameData.objects.create(
            game=first, igdb_id=7, hltb_id="1", main_story_hours=12, is_primary=True
        )

        import_handler.import_games(StringIO(self.FILE))

        game = models.Game.objects.get()
        self.assertNotEqual(game.pk, first.pk)
        self.assertEqual(game.primary_hltb_game_data, row)
        row.refresh_from_db()
        self.assertEqual(row.game, game)

    def test_a_row_under_the_games_second_igdb_id_is_found(self):
        """IGDB re-keys games; the file lists every id a game has had."""
        row = models.HLTBGameData.objects.create(
            game=None, igdb_id=70, hltb_id="1", is_primary=True
        )
        import_handler.import_games(StringIO(self.FILE))
        self.assertEqual(models.Game.objects.get().primary_hltb_game_data, row)


class ImportTakesBackGenresTests(TestCase):
    def test_a_stored_genre_list_is_read_once_per_genre(self):
        """The record's own list can name one genre twice, or a word that
        is no genre: both spellings of Platform are one, "and" is none."""
        models.WikipediaGameData.objects.create(
            game=None,
            wikidata_id="Q1",
            page_title="Alpha Quest",
            all_genres="Platform, platform game, and, Puzzle",
            is_primary=True,
        )
        import_handler.import_games(StringIO("1\tAlpha Quest\t1998\tPC\t7\tQ1\r\n"))

        game = models.Game.objects.get()
        self.assertEqual(
            sorted(game.wikipedia_genres.values_list("name", flat=True)),
            ["Platform", "Puzzle"],
        )

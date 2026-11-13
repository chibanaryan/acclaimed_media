"""Tests for the get_wiki_genres management command."""

import contextlib
import csv
import os
import tempfile
from datetime import datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from games.management.commands.get_wiki_genres import Command
from games.models import Game, WikipediaGameData
from games.services.wiki_genre_service import GenreResult, GenreSource


class GetWikiGenresCommandTests(TestCase):
    """Tests for the get_wiki_genres management command."""

    def setUp(self):
        """Set up test games."""
        self.game1 = Game.objects.create(
            name="Test Game 1",
            rank=1,
        )
        self.game2 = Game.objects.create(
            name="Test Game 2",
            rank=2,
        )

    def test_command_processes_all_games(self):
        """Test command processes all games by default."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.get_wiki_genres.WikiGenreService"
        ) as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_genre.return_value = GenreResult(
                game_name="Test Game",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Action",
                all_genres=["Action", "Adventure"],
                source_url="https://en.wikipedia.org/wiki/Test_Game",
            )

            call_command("get_wiki_genres", "--no-output", stdout=out)

        # Should process both games
        self.assertEqual(mock_service.get_genre.call_count, 2)

    def test_command_processes_single_game_by_name(self):
        """Test command processes single game when --game is specified."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.get_wiki_genres.WikiGenreService"
        ) as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_genre.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Action",
                all_genres=["Action"],
                source_url="https://en.wikipedia.org/wiki/Test_Game_1",
            )

            call_command(
                "get_wiki_genres", "--game", "Test Game 1", "--no-output", stdout=out
            )

        # Should only process one game
        self.assertEqual(mock_service.get_genre.call_count, 1)
        mock_service.get_genre.assert_called_with("Test Game 1", year=None)

    def test_command_processes_single_game_by_id(self):
        """Test command processes single game when --id is specified."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.get_wiki_genres.WikiGenreService"
        ) as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_genre.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Action",
                all_genres=["Action"],
            )

            call_command(
                "get_wiki_genres", "--id", str(self.game1.id), "--no-output", stdout=out
            )

        self.assertEqual(mock_service.get_genre.call_count, 1)

    def test_command_respects_limit(self):
        """Test command respects --limit option."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.get_wiki_genres.WikiGenreService"
        ) as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_genre.return_value = GenreResult(
                game_name="Test Game",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Action",
                all_genres=["Action"],
            )

            call_command("get_wiki_genres", "--limit", "1", "--no-output", stdout=out)

        # Should only process 1 game due to limit
        self.assertEqual(mock_service.get_genre.call_count, 1)

    def test_command_saves_to_database_when_save_flag_set(self):
        """Test command saves results to database with --save flag."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.get_wiki_genres.WikiGenreService"
        ) as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_genre.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Action",
                all_genres=["Action", "Adventure", "RPG"],
                source_url="https://en.wikipedia.org/wiki/Test_Game_1",
            )

            call_command(
                "get_wiki_genres",
                "--game",
                "Test Game 1",
                "--save",
                "--no-output",
                stdout=out,
            )

        # Refresh from database and check WikipediaGameData was created
        self.game1.refresh_from_db()
        self.assertIsNotNone(self.game1.primary_wikipedia_game_data)
        wiki_data = self.game1.primary_wikipedia_game_data
        self.assertEqual(wiki_data.primary_genre, "Action")
        self.assertEqual(wiki_data.all_genres, "Action, Adventure, Role-Playing")

    def test_command_does_not_save_failed_results(self):
        """Test command does not save failed results to database."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.get_wiki_genres.WikiGenreService"
        ) as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_genre.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.FAILED,
                error_message="Not found",
            )

            call_command(
                "get_wiki_genres",
                "--game",
                "Test Game 1",
                "--save",
                "--no-output",
                stdout=out,
            )

        # Refresh from database - should not be updated
        self.game1.refresh_from_db()
        self.assertIsNone(self.game1.primary_wikipedia_game_data)

    def test_command_skips_existing_when_flag_set(self):
        """Test command skips games with existing data when --skip-existing is set."""
        # Set existing data on game1
        wiki_data = WikipediaGameData.objects.create(
            game=self.game1,
            page_title="Test Game 1",
            primary_genre="Existing Genre",
            is_primary=True,
        )
        self.game1.primary_wikipedia_game_data = wiki_data
        self.game1.save()

        out = StringIO()

        with mock.patch(
            "games.management.commands.get_wiki_genres.WikiGenreService"
        ) as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_genre.return_value = GenreResult(
                game_name="Test Game",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Action",
                all_genres=["Action"],
            )

            call_command(
                "get_wiki_genres", "--skip-existing", "--no-output", stdout=out
            )

        # Should only process game2 (game1 has existing data)
        self.assertEqual(mock_service.get_genre.call_count, 1)
        mock_service.get_genre.assert_called_with("Test Game 2", year=None)

    def test_command_writes_csv_output(self):
        """Test command writes CSV output file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
            output_path = tmp.name

        try:
            with mock.patch(
                "games.management.commands.get_wiki_genres.WikiGenreService"
            ) as mock_service_class:
                mock_service = mock_service_class.return_value
                mock_service.get_genre.return_value = GenreResult(
                    game_name="Test Game 1",
                    source=GenreSource.WIKIPEDIA,
                    primary_genre="Action",
                    all_genres=["Action", "Adventure"],
                    source_url="https://en.wikipedia.org/wiki/Test_Game_1",
                )

                call_command(
                    "get_wiki_genres",
                    "--game",
                    "Test Game 1",
                    "--output",
                    output_path,
                )

            # Check CSV was written
            with open(output_path, "r") as f:
                content = f.read()

            self.assertIn("Original Title", content)
            self.assertIn("Primary Genre", content)
            self.assertIn("All Genres", content)
            self.assertIn("Source URL", content)
            self.assertIn("Test Game 1", content)
            self.assertIn("Action", content)
            self.assertIn("Action, Adventure", content)

        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_command_handles_game_not_found(self):
        """Test command handles non-existent game gracefully."""
        out = StringIO()

        with mock.patch("games.management.commands.get_wiki_genres.WikiGenreService"):
            call_command(
                "get_wiki_genres",
                "--game",
                "NonExistentGame",
                "--no-output",
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("No games to process", output)

    def test_command_uses_custom_delay(self):
        """Test command uses custom delay when specified."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.get_wiki_genres.WikiGenreService"
        ) as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_genre.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Action",
                all_genres=["Action"],
            )

            call_command(
                "get_wiki_genres",
                "--game",
                "Test Game 1",
                "--delay",
                "2.5",
                "--no-output",
                stdout=out,
            )

        # Check service was initialized with custom delay
        mock_service_class.assert_called_once()
        call_kwargs = mock_service_class.call_args[1]
        self.assertEqual(call_kwargs["delay"], 2.5)

    def test_command_shows_progress_output(self):
        """Test command shows progress in output."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.get_wiki_genres.WikiGenreService"
        ) as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_genre.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Puzzle",
                all_genres=["Puzzle", "Strategy"],
            )

            call_command(
                "get_wiki_genres",
                "--game",
                "Test Game 1",
                "--no-output",
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("Test Game 1", output)
        self.assertIn("Puzzle", output)
        self.assertIn("2 genres", output)  # Shows genre count
        self.assertIn("successful", output)

    def test_command_shows_failure_output(self):
        """Test command shows failure messages in output."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.get_wiki_genres.WikiGenreService"
        ) as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_genre.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.FAILED,
                error_message="Page not found",
            )

            call_command(
                "get_wiki_genres",
                "--game",
                "Test Game 1",
                "--no-output",
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("FAILED", output)
        self.assertIn("Page not found", output)

    def test_command_no_games_to_process_with_skip_existing(self):
        """Test command message when all games already have data."""
        # Set existing data on both games
        wiki_data1 = WikipediaGameData.objects.create(
            game=self.game1,
            page_title="Test Game 1",
            primary_genre="Genre 1",
            is_primary=True,
        )
        self.game1.primary_wikipedia_game_data = wiki_data1
        self.game1.save()

        wiki_data2 = WikipediaGameData.objects.create(
            game=self.game2,
            page_title="Test Game 2",
            primary_genre="Genre 2",
            is_primary=True,
        )
        self.game2.primary_wikipedia_game_data = wiki_data2
        self.game2.save()

        out = StringIO()

        call_command("get_wiki_genres", "--skip-existing", "--no-output", stdout=out)

        output = out.getvalue()
        self.assertIn("No games to process", output)


SERVICE = "games.management.commands.get_wiki_genres.WikiGenreService"
HEADER = [
    "Rank",
    "Original Title",
    "Primary Genre",
    "All Genres",
    "IGDB Genres",
    "Source URL",
    "Error",
]


def found(game_name, year=None):
    """What the service answers for a game whose article it found."""
    return GenreResult(
        game_name=game_name,
        source=GenreSource.WIKIPEDIA,
        primary_genre="Action",
        all_genres=["Action", "Adventure"],
        source_url=f"https://en.wikipedia.org/wiki/{game_name.replace(' ', '_')}",
    )


class WikiGenreCommandTestCase(TestCase):
    """Two ranked games, and the command run against a patched service."""

    def setUp(self):
        self.game1 = Game.objects.create(
            name="Test Game 1", rank=1, slug="test-game-1", year_of_release=1998
        )
        self.game2 = Game.objects.create(name="Test Game 2", rank=2, slug="test-game-2")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def run_command(self, *args, lookup=found):
        """Run the command; return its output and the names it looked up."""
        out = StringIO()
        with mock.patch(SERVICE) as service_class:
            service_class.return_value.get_genre.side_effect = lookup
            call_command("get_wiki_genres", *args, stdout=out)
            calls = service_class.return_value.get_genre.call_args_list
        return out.getvalue(), [call.args[0] for call in calls]

    def path(self, name):
        return os.path.join(self.tmp, name)

    def rows(self, path):
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.reader(f))


class WhichGamesAreProcessedTests(WikiGenreCommandTestCase):
    """--slug and --offset, which no test reached."""

    def test_slug_selects_one_game(self):
        """--slug looks up that game alone, with its year to tell remakes apart."""
        out = StringIO()
        with mock.patch(SERVICE) as service_class:
            service_class.return_value.get_genre.side_effect = found
            call_command(
                "get_wiki_genres", "--slug", "test-game-1", "--no-output", stdout=out
            )

        service_class.return_value.get_genre.assert_called_once_with(
            "Test Game 1", year=1998
        )
        self.assertIn("Processing 1 games...", out.getvalue())

    def test_id_is_read_before_slug(self):
        """Given two selectors the command takes the id, as it always has."""
        _, looked_up = self.run_command(
            "--id", str(self.game2.id), "--slug", "test-game-1", "--no-output"
        )

        self.assertEqual(looked_up, ["Test Game 2"])

    def test_offset_without_limit_skips_the_top_of_the_ranking(self):
        """--offset alone processes every game from that position down."""
        Game.objects.create(name="Test Game 3", rank=3)

        output, looked_up = self.run_command("--offset", "1", "--no-output")

        self.assertEqual(looked_up, ["Test Game 2", "Test Game 3"])
        self.assertIn("Processing 2 games...", output)


class DefaultOutputFileTests(WikiGenreCommandTestCase):
    """With no --output the results go to a timestamped file where it was run."""

    def test_writes_a_timestamped_file_in_the_working_directory(self):
        """A found game and a failed one are each a row, the failure with its error."""

        def lookup(game_name, year=None):
            if game_name == "Test Game 2":
                return GenreResult(
                    game_name=game_name,
                    source=GenreSource.FAILED,
                    error_message="No Wikipedia article found",
                )
            return found(game_name)

        with (
            contextlib.chdir(self.tmp),
            mock.patch("games.management.commands.get_wiki_genres.datetime") as clock,
        ):
            clock.now.return_value = datetime(2026, 1, 2, 3, 4, 5)
            output, _ = self.run_command(lookup=lookup)

        self.assertEqual(os.listdir(self.tmp), ["wiki_genres_20260102_030405.csv"])
        self.assertEqual(
            self.rows(self.path("wiki_genres_20260102_030405.csv")),
            [
                HEADER,
                [
                    "1",
                    "Test Game 1",
                    "Action",
                    "Action, Adventure",
                    "",
                    "https://en.wikipedia.org/wiki/Test_Game_1",
                    "",
                ],
                ["2", "Test Game 2", "", "", "", "", "No Wikipedia article found"],
            ],
        )
        self.assertIn("Starting fresh run: wiki_genres_20260102_030405.csv", output)
        self.assertIn("Results saved to: wiki_genres_20260102_030405.csv", output)
        self.assertIn("1 successful, 1 failed", output)

    def test_help_names_the_file_the_command_writes(self):
        """--output's help named game_genres_ordered_..., which nothing writes."""
        parser = Command().create_parser("manage.py", "get_wiki_genres")
        output_help = next(a.help for a in parser._actions if a.dest == "output")

        self.assertIn("wiki_genres_TIMESTAMP.csv", output_help)
        self.assertNotIn("game_genres_ordered", output_help)


class ResumeTests(WikiGenreCommandTestCase):
    """--resume reads the ranks a CSV already holds and carries on in that file."""

    def write(self, name, lines):
        path = self.path(name)
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write("".join(line + "\r\n" for line in lines))
        return path

    def test_skips_the_ranks_in_the_file_and_appends_the_rest(self):
        """A resumed run looks up only what is missing and adds it to the same
        file, under the header it already has, wherever --output points."""
        earlier = "1,Test Game 1,Puzzle,Puzzle,,https://example.org/1,"
        resume = self.write("run.csv", [",".join(HEADER), earlier])
        elsewhere = self.path("elsewhere.csv")

        output, looked_up = self.run_command("--resume", resume, "--output", elsewhere)

        self.assertEqual(looked_up, ["Test Game 2"])
        self.assertEqual(
            self.rows(resume),
            [
                HEADER,
                [
                    "1",
                    "Test Game 1",
                    "Puzzle",
                    "Puzzle",
                    "",
                    "https://example.org/1",
                    "",
                ],
                [
                    "2",
                    "Test Game 2",
                    "Action",
                    "Action, Adventure",
                    "",
                    "https://en.wikipedia.org/wiki/Test_Game_2",
                    "",
                ],
            ],
        )
        self.assertFalse(os.path.exists(elsewhere))
        self.assertIn(f"Resuming from {resume}: 1 games already processed", output)
        self.assertIn(f"Appending to: {resume}", output)
        self.assertNotIn("Starting fresh run", output)
        # The skipped game is out of the progress total and in the summary.
        self.assertIn("[1/1] Test Game 2: Action (2 genres)", output)
        self.assertIn(
            "Completed 1 games in 0s: 1 successful, 0 failed, "
            "1 skipped (already processed)",
            output,
        )
        self.assertIn(f"Results saved to: {resume}", output)

    def test_rows_without_a_numeric_rank_are_not_taken_as_processed(self):
        """A blank line, an unranked game's row and a rank that is no number
        skip nothing; the one real rank does."""
        resume = self.write(
            "run.csv",
            [
                ",".join(HEADER),
                "",
                ",An Unranked Game,Action,Action,,,",
                "n/a,Test Game 1,Action,Action,,,",
                "2,Test Game 2,Action,Action,,,",
            ],
        )

        output, looked_up = self.run_command("--resume", resume)

        self.assertEqual(looked_up, ["Test Game 1"])
        self.assertIn(f"Resuming from {resume}: 1 games already processed", output)
        self.assertEqual(self.rows(resume)[-1][:2], ["1", "Test Game 1"])

    def test_a_file_that_does_not_exist_starts_fresh(self):
        """Nothing to resume from is said, and every game is looked up and
        written to the --output given."""
        missing = self.path("never-written.csv")
        target = self.path("out.csv")

        output, looked_up = self.run_command("--resume", missing, "--output", target)

        self.assertIn(f"No existing data in {missing}, starting fresh", output)
        self.assertNotIn("Resuming from", output)
        self.assertEqual(looked_up, ["Test Game 1", "Test Game 2"])
        self.assertEqual(
            [row[:2] for row in self.rows(target)],
            [HEADER[:2], ["1", "Test Game 1"], ["2", "Test Game 2"]],
        )
        self.assertNotIn("skipped", output)

    def test_a_file_that_cannot_be_read_is_reported_and_left_alone(self):
        """A CSV saved in another encoding (a spreadsheet's Latin-1) is named
        with the error, nothing is skipped on its account, and it is not
        written over."""
        unreadable = self.path("latin1.csv")
        content = ",".join(HEADER).encode() + b"\r\n1,Pok\xe9mon Red,RPG,RPG,,,\r\n"
        with open(unreadable, "wb") as f:
            f.write(content)

        output, looked_up = self.run_command("--resume", unreadable, "--no-output")

        self.assertIn(f"Error reading {unreadable}: 'utf-8' codec", output)
        self.assertIn(f"No existing data in {unreadable}, starting fresh", output)
        self.assertEqual(looked_up, ["Test Game 1", "Test Game 2"])
        with open(unreadable, "rb") as f:
            self.assertEqual(f.read(), content)

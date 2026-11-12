"""`refresh_all_metadata` fails when a phase could not run at all."""

from datetime import datetime, timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from games.management.commands import refresh_all_metadata
from games.models import Game
from games.services.data_version import compute_game_data_version

COMMAND = "games.management.commands.refresh_all_metadata"


class FailedPhasesFailTheCommandTests(TestCase):
    def setUp(self):
        Game.objects.create(name="Alpha Quest", rank=1, igdb_id=7)

    def run_command(self, **options):
        call_command("refresh_all_metadata", stdout=StringIO(), **options)

    @mock.patch(f"{COMMAND}.IGDBImportService")
    def test_a_refresh_that_raises_fails_the_command(self, service):
        service.return_value.import_games.side_effect = RuntimeError("boom")
        service.return_value.batch_size = 50
        service.return_value.concurrency = 1
        with (
            self.assertLogs(refresh_all_metadata.logger, level="ERROR"),
            self.assertRaisesMessage(CommandError, "failed outright for: IGDB"),
        ):
            self.run_command(igdb_only=True)

    @mock.patch(f"{COMMAND}.IGDBImportService")
    def test_errors_on_some_games_do_not(self, service):
        """A dropped id is an error on one game, not a failed refresh."""
        instance = service.return_value
        instance.batch_size = 50
        instance.concurrency = 1
        instance.api_client.use_pro_tier = False
        instance.processed_count = 3
        instance.error_count = 1
        self.run_command(igdb_only=True)

    @mock.patch(f"{COMMAND}.IGDBImportService")
    def test_the_weekly_run_fails_after_it_lets_the_lock_go(self, service):
        """Raised in the work, it left an import's owed fetch unrun."""
        service.side_effect = RuntimeError("no credentials")
        events = []

        def run_weekly(command, work):
            work()
            events.append("lock released")

        with (
            mock.patch("core.services.monitoring.datetime") as clock,
            mock.patch(f"{COMMAND}.post_import.run_weekly", run_weekly),
            mock.patch(f"{COMMAND}.weekly_job_monitor") as monitor,
        ):
            clock.now.return_value = datetime(2026, 10, 18)  # a Sunday
            try:
                self.run_command(weekly=True, igdb_only=True)
            except CommandError:
                events.append("command failed")

        self.assertEqual(events, ["lock released", "command failed"])
        # Inside the cron check-in, which reports only a run that raises
        exit_args = monitor.return_value.__exit__.call_args.args
        self.assertIs(exit_args[0], CommandError)


class RefreshMovesTheDataVersionTests(TestCase):
    """The refresh changes genres, slugs and artwork through saves that
    leave ``Game.modified`` alone, and nothing else the data version reads
    need move in a week. A reader's stored payload is kept for as long as
    its version is the page's, so until 2026-11-12 it could hold last
    week's genres and a slug IGDB had since renamed."""

    def setUp(self):
        game = Game.objects.create(name="Alpha Quest", rank=1, igdb_id=7)
        # `timezone.now` a second past the game's `modified`, so a move shows
        self.enterContext(
            mock.patch(
                "django.utils.timezone.now",
                return_value=game.modified + timedelta(seconds=1),
            )
        )

    def run_command(self, **options):
        with mock.patch(f"{COMMAND}.IGDBImportService") as service:
            instance = service.return_value
            instance.batch_size = 50
            instance.concurrency = 1
            instance.api_client.use_pro_tier = False
            instance.processed_count = 1
            instance.error_count = 0
            call_command(
                "refresh_all_metadata", stdout=StringIO(), igdb_only=True, **options
            )
            return instance

    def test_a_refresh_moves_it(self):
        before = compute_game_data_version()
        self.run_command()
        self.assertNotEqual(compute_game_data_version(), before)

    def test_a_dry_run_does_not(self):
        before = compute_game_data_version()
        self.run_command(dry_run=True)
        self.assertEqual(compute_game_data_version(), before)

    def test_a_phase_that_failed_part_way_still_moves_it(self):
        """What it wrote before it raised is in the pages all the same."""
        before = compute_game_data_version()
        with mock.patch(f"{COMMAND}.IGDBImportService") as service:
            service.return_value.import_games.side_effect = RuntimeError("boom")
            service.return_value.batch_size = 50
            service.return_value.concurrency = 1
            with (
                self.assertLogs(refresh_all_metadata.logger, level="ERROR"),
                self.assertRaises(CommandError),
            ):
                call_command("refresh_all_metadata", stdout=StringIO(), igdb_only=True)
        self.assertNotEqual(compute_game_data_version(), before)


class WikidataCredentialsTests(TestCase):
    """The async Wikipedia refresh paced itself as authenticated for any
    token, then sent none."""

    def test_a_bot_password_is_a_login_and_a_password(self):
        self.assertEqual(
            refresh_all_metadata.wikidata_credentials("Site@bot:s3cret:with:colons"),
            ("Site@bot", "s3cret:with:colons"),
        )

    def test_anything_else_is_no_credentials_and_the_slower_pace(self):
        for token in (None, "", "no-colon", ":password", "login:"):
            with self.subTest(token=token):
                self.assertIsNone(refresh_all_metadata.wikidata_credentials(token))

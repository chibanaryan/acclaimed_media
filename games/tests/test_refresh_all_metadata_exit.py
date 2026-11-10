"""`refresh_all_metadata` fails when a phase could not run at all."""

from datetime import datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from games.management.commands import refresh_all_metadata
from games.models import Game

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
            mock.patch(f"{COMMAND}.datetime") as clock,
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

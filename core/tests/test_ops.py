"""Health check, scheduled-job monitoring and logging."""

import logging
from contextlib import nullcontext
from datetime import datetime
from io import StringIO
from unittest import mock

from django.core.cache import caches
from django.core.management import call_command
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings

from core.services.monitoring import weekly_job_monitor
from games.config import RATE_LIMIT_CACHE_PREFIX

LOCMEM = {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}


class HealthzTests(TestCase):
    def test_ok_when_the_database_answers(self):
        response = self.client.get("/healthz/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_503_when_it_does_not(self):
        with mock.patch("core.views.connection") as connection:
            connection.cursor.side_effect = DatabaseError("gone")
            with self.assertLogs("core.views", "ERROR"):
                response = self.client.get("/healthz/")

        self.assertEqual(response.status_code, 503)

    @override_settings(
        CACHES={
            "default": LOCMEM,
            "local": dict(LOCMEM, LOCATION="local"),
            "ratelimit": dict(LOCMEM, LOCATION="ratelimit"),
        }
    )
    def test_a_rate_limited_monitor_still_gets_an_answer(self):
        caches["ratelimit"].set(f"{RATE_LIMIT_CACHE_PREFIX}:block:127.0.0.1", True)

        self.assertEqual(self.client.get("/healthz/").status_code, 200)
        self.assertEqual(self.client.get("/robots.txt").status_code, 200)


class WeeklyJobMonitorTests(SimpleTestCase):
    def test_a_manual_run_does_not_check_in(self):
        with mock.patch("core.services.monitoring.monitor") as monitor:
            context = weekly_job_monitor("job", enabled=False, max_runtime=60)

        self.assertIsInstance(context, nullcontext)
        monitor.assert_not_called()

    def test_a_weekly_run_checks_in_on_a_one_week_interval(self):
        with mock.patch("core.services.monitoring.monitor") as monitor:
            weekly_job_monitor("job", enabled=True, max_runtime=60)

        config = monitor.call_args.kwargs["monitor_config"]
        self.assertEqual(monitor.call_args.kwargs["monitor_slug"], "job")
        self.assertEqual(
            config["schedule"], {"type": "interval", "value": 1, "unit": "week"}
        )
        self.assertEqual(config["max_runtime"], 60)


class ScheduledJobsCheckInTests(SimpleTestCase):
    """Both jobs run their work inside the check-in, only past the gate."""

    def _run(self, command, module, weekday_date, **options):
        with mock.patch(f"{module}.datetime") as dt, mock.patch(
            f"{module}.weekly_job_monitor", return_value=nullcontext()
        ) as monitor, mock.patch(f"{module}.Command._run") as run:
            dt.now.return_value = weekday_date
            call_command(command, stdout=StringIO(), **options)
        return monitor, run

    def test_sunday_weekly_runs_check_in(self):
        sunday = datetime(2026, 10, 25)
        for command, module, slug in (
            (
                "refresh_all_metadata",
                "games.management.commands.refresh_all_metadata",
                "refresh-all-metadata",
            ),
            (
                "fetch_album_metadata",
                "music.management.commands.fetch_album_metadata",
                "fetch-album-metadata",
            ),
        ):
            with self.subTest(command=command):
                monitor, run = self._run(command, module, sunday, weekly=True)
                self.assertEqual(monitor.call_args.args[0], slug)
                self.assertTrue(monitor.call_args.kwargs["enabled"])
                run.assert_called_once()

    def test_a_skipped_weekday_never_checks_in(self):
        monitor, run = self._run(
            "fetch_album_metadata",
            "music.management.commands.fetch_album_metadata",
            datetime(2026, 10, 19),
            weekly=True,
        )
        monitor.assert_not_called()
        run.assert_not_called()


class AppLoggingTests(SimpleTestCase):
    def test_every_app_module_has_a_handler_on_the_way_up(self):
        """music.discogs and friends used to have none and lost INFO lines."""
        for name in ("music.discogs", "games.management.commands.refresh_all_metadata"):
            with self.subTest(name=name):
                logger = logging.getLogger(name)
                app = logging.getLogger(name.split(".")[0])
                self.assertTrue(logger.propagate)
                self.assertTrue(app.handlers)
                self.assertFalse(app.propagate)


class StartBackgroundThreadTests(SimpleTestCase):
    def test_runs_the_target_then_closes_the_threads_connection(self):
        from core.services.background import start_background_thread

        ran = []
        with mock.patch("core.services.background.connection") as connection:
            thread = start_background_thread(lambda: ran.append(True))
            thread.join(timeout=5)

        self.assertEqual(ran, [True])
        self.assertTrue(thread.daemon)
        connection.close.assert_called_once()

    def test_closes_the_connection_even_when_the_target_raises(self):
        from core.services.background import start_background_thread

        def boom():
            raise RuntimeError("boom")

        with mock.patch(
            "core.services.background.connection"
        ) as connection, mock.patch("threading.excepthook"):
            start_background_thread(boom).join(timeout=5)

        connection.close.assert_called_once()


class AllowedHostsTests(SimpleTestCase):
    def test_testserver_is_only_allowed_under_test(self):
        """It was in the base list, so production served requests naming it."""
        from pathlib import Path

        settings_source = (
            Path(__file__).resolve().parents[2] / "acclaimedgames" / "settings.py"
        ).read_text()
        base = settings_source[settings_source.index("ALLOWED_HOSTS = [") :]
        base = base[: base.index("]")]
        self.assertNotIn("testserver", base)


class BackgroundThreadDaemonTests(SimpleTestCase):
    def test_a_thread_can_ask_to_be_waited_for(self):
        from core.services.background import start_background_thread

        with mock.patch("core.services.background.connection"):
            thread = start_background_thread(lambda: None, daemon=False)
            thread.join(timeout=5)
        self.assertFalse(thread.daemon)


class HealthzDroppedConnectionTests(TestCase):
    def test_a_dropped_connection_is_a_503_not_a_500(self):
        """InterfaceError is a django.db.Error but not a DatabaseError."""
        from django.db import InterfaceError

        with mock.patch("core.views.connection") as connection:
            connection.cursor.side_effect = InterfaceError("connection already closed")
            with self.assertLogs("core.views", "ERROR"):
                response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 503)

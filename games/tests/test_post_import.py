"""A games import starts the metadata fetch for what it added."""

import asyncio
import itertools
import json
import threading
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.text import slugify

from core.models import User
from core.services import post_import as core_post_import
from games import models, utils
from games.services import post_import
from games.services.data_version import compute_game_data_version
from games.tests.test_imports import InlineImportThreadMixin

REFRESH = "games.services.post_import.refresh_after_import"
SCHEDULE = "games.services.post_import.schedule"


def _games_file():
    return SimpleUploadedFile(
        "Top1400.txt", b"1\tFirst Game\t1990\tPC\t101\tQ1\r\n", "text/plain"
    )


def _lists_file():
    return SimpleUploadedFile(
        "SourceLists.txt",
        b"Edge\t2024\tAll Time\tTop 100 Games\thttps://example.com/list\r\n",
        "text/plain",
    )


class RefreshAfterImportTests(TestCase):
    def setUp(self):
        # Closing connections here would close the test's own.
        patcher = mock.patch("games.services.post_import._close_async_connections")
        self.close_async = patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_pass_is_missing_only(self):
        """The import carries each kept game's slug, developers and series."""
        out = StringIO()
        with mock.patch("games.services.post_import.call_command") as command:
            self.assertEqual(post_import.refresh_after_import(out), [])
        self.assertEqual(
            command.call_args_list,
            [
                mock.call("get_igdb", stdout=out),
                mock.call("fetch_wikipedia_metadata", stdout=out, save=True),
                mock.call("fetch_hltb_data", stdout=out, save=True),
            ],
        )

    def test_a_failed_step_does_not_stop_the_rest(self):
        def run(name, **options):
            if name == "get_igdb":
                raise RuntimeError("IGDB down")

        with mock.patch(
            "games.services.post_import.call_command", side_effect=run
        ) as command:
            with self.assertLogs("games.services.post_import", "ERROR") as logs:
                failed = post_import.refresh_after_import(StringIO())
        self.assertEqual(failed, ["get_igdb"])
        self.assertEqual(command.call_count, 3)
        self.assertIn("get_igdb after a games import failed", logs.output[0])

    def igdb(self, restore=(), raises=False):
        """A call_command whose get_igdb gives ``restore`` their slugs back.

        It records the data version each later step starts under.
        """
        self.versions = {}

        def run(name, **options):
            if name == "get_igdb":
                for game in restore:
                    game.slug = slugify(game.name)
                    game.save(update_fields=["slug"])
                if raises:
                    raise RuntimeError("IGDB went away")
            else:
                self.versions[name] = compute_game_data_version()

        return mock.patch("games.services.post_import.call_command", side_effect=run)

    def games(self, count):
        return [
            models.Game.objects.create(name=f"Game {i}", rank=i, igdb_id=1000 + i)
            for i in range(1, count + 1)
        ]

    def later(self):
        """A ``timezone.now`` past every game's ``modified``, a second a call,
        so each bump shows."""
        start = models.Game.objects.latest("modified").modified
        ticks = (start + timedelta(seconds=n) for n in itertools.count(1))
        self.enterContext(
            mock.patch("django.utils.timezone.now", side_effect=lambda: next(ticks))
        )

    def test_an_igdb_pass_that_restored_no_slug_failed(self):
        """get_igdb reports a service it cannot start, and returns."""
        self.games(post_import.SLUGLESS_TOLERANCE + 1)
        with self.igdb():
            with self.assertLogs("games.services.post_import", "WARNING") as logs:
                failed = post_import.refresh_after_import(StringIO())
        self.assertEqual(failed, ["get_igdb"])
        self.assertIn("get_igdb left 11 games without a slug", logs.output[0])

    def test_an_igdb_pass_that_stopped_part_way_failed(self):
        """Its batches' errors are caught, so it returns as if it finished."""
        games = self.games(post_import.SLUGLESS_TOLERANCE + 3)
        with self.igdb(restore=games[:2]):
            with self.assertLogs("games.services.post_import", "WARNING"):
                failed = post_import.refresh_after_import(StringIO())
        self.assertEqual(failed, ["get_igdb"])

    def test_a_game_igdb_no_longer_returns_is_a_warning_not_a_failure(self):
        """Counted a failure, one dropped id would alert on every import."""
        doom, _gone = self.games(2)
        with self.igdb(restore=[doom]):
            with self.assertLogs("games.services.post_import", "WARNING") as logs:
                failed = post_import.refresh_after_import(StringIO())
        self.assertEqual(failed, [])
        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertIn("get_igdb left 1 games without a slug", logs.output[0])

    def test_a_raised_igdb_pass_is_named_once(self):
        self.games(1)
        with self.igdb(raises=True):
            with self.assertLogs("games.services.post_import", "ERROR"):
                failed = post_import.refresh_after_import(StringIO())
        self.assertEqual(failed, ["get_igdb"])

    def test_the_data_version_moves_as_soon_as_the_slugs_are_back(self):
        """get_igdb saves slugs without touching `modified`; Wikipedia and
        HLTB can take minutes more, with cached pages still on /games/None/."""
        games = self.games(1)
        before = compute_game_data_version()
        self.later()
        with self.igdb(restore=games):
            post_import.refresh_after_import(StringIO())
        self.assertNotEqual(self.versions["fetch_wikipedia_metadata"], before)

    def test_the_slugs_a_pass_restored_before_raising_move_it_too(self):
        games = self.games(2)
        before = compute_game_data_version()
        self.later()
        with self.igdb(restore=games[:1], raises=True):
            with self.assertLogs("games.services.post_import", "ERROR"):
                post_import.refresh_after_import(StringIO())
        self.assertNotEqual(self.versions["fetch_wikipedia_metadata"], before)

    def test_it_moves_again_once_wikipedia_has_tagged_the_new_games(self):
        """Their genres move nothing the version reads."""
        self.games(1)
        self.later()
        with self.igdb():
            with self.assertLogs("games.services.post_import", "WARNING"):
                post_import.refresh_after_import(StringIO())
        self.assertNotEqual(
            compute_game_data_version(), self.versions["fetch_hltb_data"]
        )

    def test_moving_it_touches_one_game(self):
        games = self.games(3)
        self.later()
        post_import._move_data_version()
        moved = [
            game.pk
            for game in games
            if models.Game.objects.get(pk=game.pk).modified != game.modified
        ]
        self.assertEqual(moved, [games[0].pk])

    def test_moving_it_with_no_games_does_nothing(self):
        post_import._move_data_version()
        self.assertFalse(models.Game.objects.exists())

    def test_a_failed_check_does_not_stop_the_later_steps(self):
        self.games(1)
        with self.igdb() as command:
            with mock.patch.object(
                post_import, "_slugless", side_effect=ConnectionError
            ):
                with self.assertLogs("games.services.post_import", "ERROR"):
                    failed = post_import.refresh_after_import(StringIO())
        self.assertEqual(failed, ["get_igdb"])
        self.assertEqual(command.call_count, 3)

    def test_a_version_that_will_not_move_is_named_with_the_steps_that_failed(self):
        """Raised, it took the names of the steps that failed with it."""

        def run(name, **options):
            if name == "fetch_wikipedia_metadata":
                raise RuntimeError("Wikidata down")

        with (
            mock.patch("games.services.post_import.call_command", side_effect=run),
            mock.patch.object(
                post_import.Game.objects, "order_by", side_effect=ConnectionError
            ),
        ):
            with self.assertLogs("games.services.post_import", "ERROR") as logs:
                failed = post_import.refresh_after_import(StringIO())
        self.assertEqual(failed, ["fetch_wikipedia_metadata", post_import.MOVE_VERSION])
        self.assertIn("Could not move the games data version", logs.output[0])

    def test_the_hltb_saves_connection_is_closed_after(self):
        with mock.patch("games.services.post_import.call_command"):
            post_import.refresh_after_import(StringIO())
        self.close_async.assert_called_once_with()

    def test_it_is_closed_even_when_the_fetch_fails(self):
        with mock.patch.object(post_import, "_run_igdb", side_effect=ConnectionError):
            with self.assertRaises(ConnectionError):
                post_import.refresh_after_import(StringIO())
        self.close_async.assert_called_once_with()

    def test_schedule_runs_it_for_the_games_section(self):
        with mock.patch.object(
            core_post_import, "schedule_after_commit", return_value="note"
        ) as schedule:
            self.assertEqual(post_import.schedule(), "note")
        schedule.assert_called_once_with("games", post_import.refresh_after_import)

    def test_the_commands_run_it_for_the_games_section(self):
        command = object()
        with mock.patch.object(core_post_import, "run_in_foreground") as run:
            post_import.run_in_foreground(command)
        run.assert_called_once_with("games", post_import.refresh_after_import, command)


class CloseAsyncConnectionsTests(TestCase):
    def test_they_are_closed_on_the_thread_that_opened_them(self):
        """fetch_hltb_data saves through sync_to_async's executor thread."""
        saved_on = []

        def save():
            saved_on.append(threading.current_thread())

        asyncio.run(sync_to_async(save)())
        closed_on = []
        with mock.patch("games.services.post_import.connections") as connections:
            connections.close_all.side_effect = lambda: closed_on.append(
                threading.current_thread()
            )
            post_import._close_async_connections()
        self.assertEqual(closed_on, saved_on)
        self.assertIsNot(closed_on[0], threading.current_thread())

    def test_a_failure_is_logged(self):
        with mock.patch("games.services.post_import.connections") as connections:
            connections.close_all.side_effect = RuntimeError
            with self.assertLogs("games.services.post_import", "ERROR"):
                post_import._close_async_connections()


class ImportPageStartsTheFetchTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="staff", password="pw", is_staff=True)
        self.client.login(username="staff", password="pw")
        models.Platform.objects.create(code="PC", name="Personal Computer")

    def post(self, data):
        response = self.client.post(reverse("import"), data)
        self.assertEqual(response.status_code, 302)
        return response.wsgi_request.session

    def test_a_games_file_starts_it_and_says_so(self):
        with mock.patch(SCHEDULE, return_value="Fetching now.") as schedule:
            session = self.post({"games_file": _games_file()})
        schedule.assert_called_once_with()
        self.assertTrue(session["import_success"].endswith("\nFetching now."))

    def test_a_lists_only_import_leaves_the_games_alone(self):
        with mock.patch(SCHEDULE) as schedule:
            session = self.post({"lists_file": _lists_file()})
        schedule.assert_not_called()
        self.assertIn("import_success", session)

    def test_a_failed_import_starts_nothing(self):
        with (
            mock.patch("games.utils.import_batch", return_value=(False, "bad row")),
            mock.patch(SCHEDULE) as schedule,
        ):
            session = self.post({"games_file": _games_file()})
        schedule.assert_not_called()
        self.assertEqual(session["import_errors"], ["bad row"])

    def test_the_bundled_data_starts_it(self):
        with (
            mock.patch("games.utils.import_batch", return_value=(True, "Loaded")),
            mock.patch(SCHEDULE, return_value="Fetching now.") as schedule,
        ):
            session = self.post({"seed_test_data": True})
        schedule.assert_called_once_with()
        self.assertIn("Fetching now.", session["import_success"])

    def test_with_the_setting_off_the_message_is_the_import_alone(self):
        session = self.post({"games_file": _games_file()})
        self.assertNotIn(
            "background", session["import_success"].lower(), session["import_success"]
        )


class StreamedImportStartsTheFetchTests(InlineImportThreadMixin, TestCase):
    def setUp(self):
        super().setUp()
        models.Platform.objects.create(code="PC", name="Personal Computer")

    def events(self, data):
        return [
            json.loads(line[len("data: ") :])
            for chunk in utils.import_batch_with_progress(data)
            for line in chunk.splitlines()
            if line.startswith("data: ")
        ]

    def test_an_imported_games_file_puts_the_note_on_the_stream(self):
        with mock.patch(SCHEDULE, return_value="Fetching now.") as schedule:
            events = self.events({"games_file": _games_file()})
        schedule.assert_called_once_with()
        self.assertIn({"event": "metadata", "message": "Fetching now."}, events)

    def test_a_failed_games_file_starts_nothing(self):
        bad = SimpleUploadedFile("Top1400.txt", b"not\ta\tgame\r\n", "text/plain")
        with mock.patch(SCHEDULE) as schedule:
            events = self.events({"games_file": bad})
        schedule.assert_not_called()
        self.assertTrue(any(event["event"] == "error" for event in events))

    def test_a_lists_only_import_starts_nothing(self):
        with mock.patch(SCHEDULE) as schedule:
            self.events({"lists_file": _lists_file()})
        schedule.assert_not_called()

    def test_with_the_setting_off_the_stream_carries_no_note(self):
        events = self.events({"games_file": _games_file()})
        self.assertNotIn("metadata", [event["event"] for event in events])


class ImportCommandFetchesTests(TestCase):
    FILES = {
        "platforms": ("PlatformDB.txt", "PC\tPersonal Computer\r\n"),
        "lists": (
            "SourceLists.txt",
            "Edge\t2024\tAll Time\tTop 100 Games\thttps://example.com/list\r\n",
        ),
        "games": ("Top1400.txt", "1\tFirst Game\t1990\tPC\t101\tQ1\r\n"),
        "positions": ("GamePositions.txt", "0:1\r\n"),
    }

    def setUp(self):
        self.dir = Path(self.enterContext(TemporaryDirectory()))
        self.paths = {}
        for key, (name, text) in self.FILES.items():
            (self.dir / name).write_text(text, encoding="utf-8", newline="")
            self.paths[key] = str(self.dir / name)
        cache.delete(core_post_import.lock_key("games"))
        heartbeat = mock.patch("core.services.post_import._start_heartbeat")
        heartbeat.start()
        self.addCleanup(heartbeat.stop)

    def run_command(self, refresh_result=(), **options):
        out = StringIO()
        with mock.patch(REFRESH, return_value=list(refresh_result)) as refresh:
            call_command("import_games_data", stdout=out, **self.paths, **options)
        return refresh, out.getvalue()

    @override_settings(METADATA_AFTER_IMPORT=True)
    def test_it_fetches_in_the_foreground_after_the_import(self):
        refresh, output = self.run_command()
        refresh.assert_called_once()
        self.assertIn("Fetching metadata", output)
        self.assertTrue(models.Game.objects.exists())

    @override_settings(METADATA_AFTER_IMPORT=True)
    def test_a_failed_step_is_named(self):
        with self.assertLogs("core.services.post_import", "ERROR"):
            _, output = self.run_command(refresh_result=["fetch_hltb_data"])
        self.assertIn("fetch_hltb_data failed; see the log", output)

    @override_settings(METADATA_AFTER_IMPORT=True)
    def test_no_metadata_skips_it(self):
        refresh, _ = self.run_command(metadata=False)
        refresh.assert_not_called()

    def test_the_setting_off_skips_it(self):
        refresh, _ = self.run_command()
        refresh.assert_not_called()


class LockWrappersTests(TestCase):
    def test_hold_resume_and_weekly_are_the_games_section_s(self):
        command, work = object(), object()
        with (
            mock.patch.object(core_post_import, "hold") as hold,
            mock.patch.object(core_post_import, "resume_if_cut_short") as resume,
            mock.patch.object(core_post_import, "run_weekly") as weekly,
        ):
            post_import.hold()
            post_import.resume()
            post_import.run_weekly(command, work)
        job = post_import.refresh_after_import
        hold.assert_called_once_with("games", job)
        resume.assert_called_once_with("games", job)
        weekly.assert_called_once_with("games", job, command, work)


class ImportPageResumesACutShortFetchTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="staff", password="pw", is_staff=True)
        self.client.login(username="staff", password="pw")

    def test_its_load_restarts_one_and_says_so(self):
        with mock.patch(
            "games.views.imports.post_import.resume", return_value="Restarted."
        ) as resume:
            response = self.client.get(reverse("import"))
        resume.assert_called_once_with()
        self.assertContains(response, "Restarted.")

    def test_with_nothing_to_restart_it_says_nothing(self):
        with mock.patch("games.views.imports.post_import.resume", return_value=None):
            response = self.client.get(reverse("import"))
        self.assertIsNone(response.context["metadata_resumed"])


class MetadataButtonsTakeTheLockTests(InlineImportThreadMixin, TestCase):
    """The IGDB and Wikipedia buttons never run beside a fetch."""

    LOCK = core_post_import.lock_key("games")

    def setUp(self):
        super().setUp()
        cache.delete(self.LOCK)
        self.addCleanup(cache.delete, self.LOCK)
        heartbeat = mock.patch("core.services.post_import._start_heartbeat")
        heartbeat.start()
        self.addCleanup(heartbeat.stop)
        models.Game.objects.create(name="Game", rank=1, igdb_id=1)

    def events(self, stream):
        return [
            json.loads(line[len("data: ") :])
            for chunk in stream
            for line in chunk.splitlines()
            if line.startswith("data: ")
        ]

    def test_a_button_pressed_during_a_fetch_says_so_and_starts_nothing(self):
        cache.add(self.LOCK, "theirs")
        for stream in (
            utils.import_igdb_with_progress,
            utils.import_wikipedia_pages_with_progress,
        ):
            with (
                self.subTest(stream=stream.__name__),
                mock.patch(
                    "games.services.import_handler._start_import_thread"
                ) as thread,
            ):
                events = self.events(stream())
                thread.assert_not_called()
                self.assertEqual(
                    events, [{"event": "error", "error": core_post_import.BUSY}]
                )
        self.assertEqual(cache.get(self.LOCK), "theirs")
        self.assertIsNone(cache.get(core_post_import.again_key("games")))

    @mock.patch("games.services.igdb_importer.IGDBImportService")
    def test_the_lock_is_held_while_the_work_runs_and_let_go_after(self, service):
        held = []
        service.return_value.import_games.side_effect = lambda games: held.append(
            cache.get(self.LOCK)
        )
        self.events(utils.import_igdb_with_progress())
        self.assertTrue(held[0])
        self.assertIsNone(cache.get(self.LOCK))

    @mock.patch("games.services.igdb_importer.IGDBImportService")
    def test_a_stream_that_started_no_work_lets_go(self, service):
        service.side_effect = RuntimeError("Failed to initialize IGDB API client")
        with self.assertLogs("games.services.import_handler", "ERROR"):
            events = self.events(utils.import_igdb_with_progress())
        self.assertEqual(events[-1]["event"], "error")
        self.assertIsNone(cache.get(self.LOCK))

    @mock.patch("games.services.igdb_importer.IGDBImportService")
    def test_an_import_during_the_work_gets_its_fetch_after(self, service):
        service.return_value.import_games.side_effect = lambda games: (
            core_post_import._start("games", mock.Mock(), {})
        )
        with mock.patch(REFRESH, return_value=[]) as refresh:
            self.events(utils.import_igdb_with_progress())
        refresh.assert_called_once()
        self.assertIsNone(cache.get(self.LOCK))


class WeeklyRefreshTakesTheLockTests(TestCase):
    COMMAND = "games.management.commands.refresh_all_metadata"

    def test_the_weekly_run_takes_it(self):
        from datetime import datetime

        with (
            mock.patch(f"{self.COMMAND}.datetime") as clock,
            mock.patch(f"{self.COMMAND}.post_import.run_weekly") as run_weekly,
        ):
            clock.now.return_value = datetime(2026, 10, 18)  # a Sunday
            call_command("refresh_all_metadata", weekly=True, stdout=StringIO())
        run_weekly.assert_called_once()

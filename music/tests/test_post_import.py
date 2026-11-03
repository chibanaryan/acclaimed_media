"""A music import starts the metadata fetch for what it left missing."""

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import User
from core.services import post_import as core_post_import
from music.services import post_import
from music.tests.site import setUpModule, tearDownModule  # noqa: F401
from music.tests.test_import_page import (
    ALBUMS_TSV,
    ARTISTS_TSV,
    LISTS_TSV,
    POSITIONS_TSV,
    _all_files,
)

REFRESH = "music.services.post_import.refresh_after_import"


class RefreshAfterImportTests(TestCase):
    def test_it_is_the_routine_run_with_musicbrainz(self):
        out = StringIO()
        with mock.patch("music.services.post_import.call_command") as command:
            self.assertEqual(post_import.refresh_after_import(out), [])
        command.assert_called_once_with(
            "fetch_album_metadata", with_musicbrainz=True, stdout=out
        )

    def test_a_failed_fetch_is_named_not_raised(self):
        with mock.patch(
            "music.services.post_import.call_command", side_effect=RuntimeError
        ):
            with self.assertLogs("music.services.post_import", "ERROR"):
                failed = post_import.refresh_after_import(StringIO())
        self.assertEqual(failed, ["fetch_album_metadata"])

    def test_schedule_runs_it_for_the_music_section(self):
        with mock.patch.object(
            core_post_import, "schedule_after_commit", return_value="note"
        ) as schedule:
            self.assertEqual(post_import.schedule(), "note")
        schedule.assert_called_once_with("music", post_import.refresh_after_import)

    def test_the_commands_run_it_for_the_music_section(self):
        command = object()
        with mock.patch.object(core_post_import, "run_in_foreground") as run:
            post_import.run_in_foreground(command)
        run.assert_called_once_with("music", post_import.refresh_after_import, command)


class LockWrappersTests(TestCase):
    def test_resume_and_weekly_are_the_music_section_s(self):
        command, work = object(), object()
        with (
            mock.patch.object(core_post_import, "resume_if_cut_short") as resume,
            mock.patch.object(core_post_import, "run_weekly") as weekly,
        ):
            post_import.resume()
            post_import.run_weekly(command, work)
        job = post_import.refresh_after_import
        resume.assert_called_once_with("music", job)
        weekly.assert_called_once_with("music", job, command, work)


class ImportPageResumesACutShortFetchTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="staff", password="pw", is_staff=True)
        self.client.login(username="staff", password="pw")

    def test_its_load_restarts_one_and_says_so(self):
        with mock.patch(
            "music.views.post_import.resume", return_value="Restarted."
        ) as resume:
            response = self.client.get(reverse("music:import"))
        resume.assert_called_once_with()
        self.assertContains(response, "Restarted.")

    def test_with_nothing_to_restart_it_says_nothing(self):
        with mock.patch("music.views.post_import.resume", return_value=None):
            response = self.client.get(reverse("music:import"))
        self.assertIsNone(response.context["metadata_resumed"])


class ImportPageStartsTheFetchTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="staff", password="pw", is_staff=True)
        self.client.login(username="staff", password="pw")
        self.url = reverse("music:import")

    def test_a_successful_import_starts_it_and_says_so(self):
        with mock.patch(
            "music.views.post_import.schedule", return_value="Fetching now."
        ) as schedule:
            response = self.client.post(self.url, _all_files())
        schedule.assert_called_once_with()
        self.assertContains(response, "Fetching now.")

    def test_a_failed_import_starts_nothing(self):
        with (
            mock.patch(
                "music.services.import_handler.import_batch",
                side_effect=ValueError("bad row"),
            ),
            mock.patch("music.views.post_import.schedule") as schedule,
        ):
            response = self.client.post(self.url, _all_files())
        self.assertEqual(response.context["error"], "bad row")
        schedule.assert_not_called()

    def test_with_the_setting_off_the_page_says_nothing_of_it(self):
        response = self.client.post(self.url, _all_files())
        self.assertIsNone(response.context["summary"]["metadata"])


class ImportCommandFetchesTests(TestCase):
    def setUp(self):
        self.dir = Path(self.enterContext(TemporaryDirectory()))
        self.paths = {}
        for key, name, text in (
            ("artists", "ArtistInfo.txt", ARTISTS_TSV),
            ("lists", "ListData.txt", LISTS_TSV),
            ("albums", "WebRankings.txt", ALBUMS_TSV),
            ("positions", "ListPositions.txt", POSITIONS_TSV),
        ):
            (self.dir / name).write_bytes(text)
            self.paths[key] = str(self.dir / name)
        cache.delete(core_post_import.lock_key("music"))
        heartbeat = mock.patch("core.services.post_import._start_heartbeat")
        heartbeat.start()
        self.addCleanup(heartbeat.stop)

    def run_command(self, refresh_result=(), **options):
        out = StringIO()
        with mock.patch(REFRESH, return_value=list(refresh_result)) as refresh:
            call_command("import_music_data", stdout=out, **self.paths, **options)
        return refresh, out.getvalue()

    @override_settings(METADATA_AFTER_IMPORT=True)
    def test_it_fetches_in_the_foreground_after_the_import(self):
        refresh, output = self.run_command()
        refresh.assert_called_once()
        self.assertIn("Fetching metadata", output)

    @override_settings(METADATA_AFTER_IMPORT=True)
    def test_a_failed_fetch_is_a_warning_after_a_committed_import(self):
        with self.assertLogs("core.services.post_import", "ERROR"):
            _, output = self.run_command(refresh_result=["fetch_album_metadata"])
        self.assertIn("fetch_album_metadata failed; see the log", output)
        self.assertIn("Albums: 1 (", output)

    @override_settings(METADATA_AFTER_IMPORT=True)
    def test_no_metadata_skips_it(self):
        refresh, _ = self.run_command(metadata=False)
        refresh.assert_not_called()

    @override_settings(METADATA_AFTER_IMPORT=True)
    def test_a_dry_run_skips_it(self):
        refresh, _ = self.run_command(dry_run=True)
        refresh.assert_not_called()

    def test_the_setting_off_skips_it(self):
        refresh, _ = self.run_command()
        refresh.assert_not_called()

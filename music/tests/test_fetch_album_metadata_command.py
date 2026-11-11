"""Tests for the metadata command's pass selection and its weekly guard.

The passes themselves are tested against the service in
``test_metadata_service.py``; these pin what the Heroku Scheduler job
(``--weekly --with-musicbrainz``) actually asks for.
"""

from datetime import datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.tests.utils import NoHeartbeatMixin
from music import models
from music.services.metadata_service import PassResult

COMMAND = "music.management.commands.fetch_album_metadata"


class FetchAlbumMetadataCommandTests(NoHeartbeatMixin, TestCase):
    def setUp(self):
        models.Album.objects.create(name="Pet Sounds", rank=1, slug="pet-sounds")

    def _run(self, **kwargs):
        out = StringIO()
        call_command("fetch_album_metadata", stdout=out, **kwargs)
        return out.getvalue()

    def _passes(self, **kwargs):
        output = self._run(dry_run=True, **kwargs)
        line = next(x for x in output.splitlines() if "Passes:" in x)
        return line.split("Passes:")[1].strip().split(", ")

    def test_the_default_omits_musicbrainz(self):
        self.assertEqual(self._passes(), ["wikidata", "covers", "discogs"])

    def test_musicbrainz_alone_runs_only_musicbrainz(self):
        self.assertEqual(self._passes(musicbrainz=True), ["musicbrainz"])

    def test_with_musicbrainz_adds_it_to_the_default(self):
        self.assertEqual(
            self._passes(with_musicbrainz=True),
            ["wikidata", "covers", "discogs", "musicbrainz"],
        )

    def test_with_musicbrainz_adds_it_to_an_explicit_selection(self):
        self.assertEqual(
            self._passes(with_musicbrainz=True, covers_only=True),
            ["covers", "musicbrainz"],
        )

    def test_with_musicbrainz_does_not_repeat_it(self):
        self.assertEqual(
            self._passes(with_musicbrainz=True, musicbrainz=True), ["musicbrainz"]
        )

    @mock.patch(f"{COMMAND}.AlbumMetadataService")
    @mock.patch("core.services.monitoring.datetime")
    def test_weekly_skips_on_any_day_but_sunday(self, mock_datetime, service):
        mock_datetime.now.return_value = datetime(2026, 10, 19)  # a Monday
        output = self._run(weekly=True)
        self.assertIn("Skipping: Today is Monday", output)
        service.assert_not_called()

    @mock.patch("core.services.monitoring.datetime")
    def test_weekly_runs_under_the_fetch_lock(self, mock_datetime):
        """Never beside an import's fetch, which is this command."""
        mock_datetime.now.return_value = datetime(2026, 10, 18)  # a Sunday
        with mock.patch(f"{COMMAND}.post_import.run_weekly") as run_weekly:
            self._run(weekly=True, dry_run=True)
        run_weekly.assert_called_once()

    @mock.patch("core.services.monitoring.datetime")
    def test_a_run_by_hand_takes_no_lock(self, mock_datetime):
        """The import's fetch runs this command while holding it."""
        with mock.patch(f"{COMMAND}.post_import.run_weekly") as run_weekly:
            output = self._run(dry_run=True)
        run_weekly.assert_not_called()
        self.assertIn("Fetching metadata for 1 album(s)", output)

    @mock.patch("core.services.monitoring.datetime")
    def test_weekly_runs_on_sunday(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 10, 18)  # a Sunday
        output = self._run(weekly=True, dry_run=True)
        self.assertNotIn("Skipping", output)
        self.assertIn("Fetching metadata for 1 album(s)", output)

    def test_refresh_stale_is_announced_for_the_musicbrainz_pass(self):
        output = self._run(dry_run=True, with_musicbrainz=True, refresh_stale=125)
        self.assertIn("Refreshing the 125 oldest MusicBrainz records", output)

    def test_refresh_stale_is_not_announced_without_the_musicbrainz_pass(self):
        output = self._run(dry_run=True, refresh_stale=125)
        self.assertNotIn("Refreshing", output)

    @mock.patch(f"{COMMAND}.AlbumMetadataService")
    def test_a_failed_cache_drop_warns_and_still_finishes(self, service):
        service.return_value.run_musicbrainz.return_value = mock.MagicMock(
            errors=[], summary=lambda: "MusicBrainz: 0 processed"
        )
        with (
            mock.patch(f"{COMMAND}.rebuild_album_genres"),
            mock.patch(f"{COMMAND}.write_report"),
            mock.patch(f"{COMMAND}.refresh_release_dates", return_value=0),
            mock.patch(
                f"{COMMAND}.caching.invalidate_music_caches", return_value=False
            ),
        ):
            output = self._run(musicbrainz=True)
        self.assertIn("Caches not cleared", output)
        self.assertIn("MusicBrainz: 0 processed", output)

    @mock.patch(f"{COMMAND}.AlbumMetadataService")
    def test_refresh_stale_reaches_the_service(self, service):
        service.return_value.run_musicbrainz.return_value = mock.MagicMock(
            errors=[], summary=lambda: "MusicBrainz: 0 processed"
        )
        with (
            mock.patch(f"{COMMAND}.rebuild_album_genres"),
            mock.patch(f"{COMMAND}.write_report"),
            mock.patch(f"{COMMAND}.refresh_release_dates", return_value=0),
        ):
            self._run(musicbrainz=True, refresh_stale=125)
        self.assertEqual(service.call_args.kwargs["refresh_stale"], 125)


class AnOutageFailsTheCommandTests(NoHeartbeatMixin, TestCase):
    """The Wikidata pass attempts every album on every run, so one that
    lands none could not run. The command exited 0 on it until 2026-11-10,
    which Sentry's cron monitor read as a good Sunday."""

    def setUp(self):
        models.Album.objects.create(name="Pet Sounds", rank=1, slug="pet-sounds")

    def run_with(self, weekly=False, **results):
        out = StringIO()
        with mock.patch(f"{COMMAND}.AlbumMetadataService") as service:
            for name, result in results.items():
                getattr(service.return_value, f"run_{name}").return_value = result
            call_command(
                "fetch_album_metadata",
                stdout=out,
                weekly=weekly,
                **{f"{name}_only": True for name in results},
            )
        return out.getvalue()

    def test_a_wikidata_pass_that_lands_nothing_fails_the_command(self):
        down = PassResult(name="Wikidata", errors=["Pet Sounds: nothing returned"])
        with self.assertRaisesMessage(CommandError, "failed outright for: Wikidata"):
            self.run_with(wikidata=down)

    def test_errors_on_some_albums_do_not(self):
        some = PassResult(name="Wikidata", processed=9, errors=["One album: gone"])
        self.assertIn("1 failed", self.run_with(wikidata=some))

    def test_a_pass_that_fills_only_what_is_missing_may_land_nothing(self):
        """A week's only cover work can be the albums with no cover
        anywhere: no outage."""
        gaps = PassResult(name="Cover art", errors=["One album: no front cover"])
        self.assertIn("1 failed", self.run_with(covers=gaps))

    def test_the_weekly_run_fails_inside_the_check_in_after_the_lock(self):
        down = PassResult(name="Wikidata", errors=["Pet Sounds: nothing returned"])
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
                self.run_with(weekly=True, wikidata=down)
            except CommandError:
                events.append("command failed")
        self.assertEqual(events, ["lock released", "command failed"])
        exit_args = monitor.return_value.__exit__.call_args.args
        self.assertIs(exit_args[0], CommandError)

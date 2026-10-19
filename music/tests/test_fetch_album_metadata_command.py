"""Tests for the metadata command's pass selection and its weekly guard.

The passes themselves are tested against the service in
``test_metadata_service.py``; these pin what the Heroku Scheduler job
(``--weekly --with-musicbrainz``) actually asks for.
"""

from datetime import datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from music import models

COMMAND = "music.management.commands.fetch_album_metadata"


class FetchAlbumMetadataCommandTests(TestCase):
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
    @mock.patch(f"{COMMAND}.datetime")
    def test_weekly_skips_on_any_day_but_sunday(self, mock_datetime, service):
        mock_datetime.now.return_value = datetime(2026, 10, 19)  # a Monday
        output = self._run(weekly=True)
        self.assertIn("Skipping: Today is Monday", output)
        service.assert_not_called()

    @mock.patch(f"{COMMAND}.datetime")
    def test_weekly_runs_on_sunday(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 10, 18)  # a Sunday
        output = self._run(weekly=True, dry_run=True)
        self.assertNotIn("Skipping", output)
        self.assertIn("Fetching metadata for 1 album(s)", output)

"""Tests for the staff music import page (form and view)."""

from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import User
from music import models
from music.views import BUNDLED_RELEASE_DIR
from music.forms import MusicImportForm
from music.tests.site import setUpModule, tearDownModule  # noqa: F401

FIXTURE_DIR = Path(settings.BASE_DIR) / "acclaimedgames" / "test_input_files" / "music"

LISTS_TSV = (
    b"Rolling Stone\t2023\tAll Time\tThe 500 Greatest Albums of All Time\t"
    b"https://rs.example\n"
)
ALBUMS_TSV = b"1\tPet Sounds\t3,0\t1966\tQ212863\n"
POSITIONS_TSV = b"0:1\n"
ARTISTS_TSV = b"3\t183048\tThe Beach Boys\n"


def _upload(name, content):
    return SimpleUploadedFile(name, content, content_type="text/plain")


def _all_files():
    return {
        "artists_file": _upload("ArtistInfo.txt", ARTISTS_TSV),
        "lists_file": _upload("ListData.txt", LISTS_TSV),
        "albums_file": _upload("WebRankings.txt", ALBUMS_TSV),
        "positions_file": _upload("ListPositions.txt", POSITIONS_TSV),
    }


class MusicImportFormTests(TestCase):
    def test_all_four_files_validate(self):
        form = MusicImportForm(data={}, files=_all_files())
        self.assertTrue(form.is_valid(), form.errors)

    def test_the_bundled_checkbox_alone_validates(self):
        form = MusicImportForm(data={"seed_bundled_data": "on"}, files={})
        self.assertTrue(form.is_valid(), form.errors)

    def test_nothing_supplied_is_rejected(self):
        form = MusicImportForm(data={}, files={})
        self.assertFalse(form.is_valid())
        self.assertIn("Upload all four release files", str(form.errors))

    def test_a_partial_upload_is_rejected_and_names_what_is_missing(self):
        files = _all_files()
        del files["positions_file"]
        del files["artists_file"]
        form = MusicImportForm(data={}, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("All four files are imported together", str(form.errors))
        self.assertIn("Album Positions", str(form.errors))
        self.assertIn("Artists (ArtistInfo.txt)", str(form.errors))

    def test_the_bundled_checkbox_skips_the_all_or_nothing_rule(self):
        files = _all_files()
        del files["positions_file"]
        form = MusicImportForm(data={"seed_bundled_data": "on"}, files=files)
        self.assertTrue(form.is_valid(), form.errors)

    def test_an_empty_lists_file_is_rejected(self):
        files = _all_files()
        files["lists_file"] = _upload("ListData.txt", b"")
        form = MusicImportForm(data={}, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("empty", str(form.errors["lists_file"]))

    def test_a_whitespace_only_lists_file_is_rejected(self):
        files = _all_files()
        files["lists_file"] = _upload("ListData.txt", b"\t\t\n")
        form = MusicImportForm(data={}, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("empty", str(form.errors["lists_file"]))

    def test_a_lists_file_with_too_few_columns_is_rejected(self):
        files = _all_files()
        files["lists_file"] = _upload("ListData.txt", b"Mojo\t1995\n")
        form = MusicImportForm(data={}, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("at least 4", str(form.errors["lists_file"]))

    def test_an_albums_file_with_too_few_columns_is_rejected(self):
        files = _all_files()
        files["albums_file"] = _upload("WebRankings.txt", b"1\tPet Sounds\n")
        form = MusicImportForm(data={}, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("at least 4", str(form.errors["albums_file"]))

    def test_an_artists_file_with_too_few_columns_is_rejected(self):
        files = _all_files()
        files["artists_file"] = _upload("ArtistInfo.txt", b"3\n")
        form = MusicImportForm(data={}, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("at least 2", str(form.errors["artists_file"]))

    def test_a_non_utf8_file_is_rejected(self):
        files = _all_files()
        files["lists_file"] = _upload("ListData.txt", b"\xff\xfe\x00bad\tdata\there\n")
        form = MusicImportForm(data={}, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("UTF-8", str(form.errors["lists_file"]))

    def test_an_empty_positions_file_is_rejected(self):
        files = _all_files()
        files["positions_file"] = _upload("ListPositions.txt", b"\n")
        form = MusicImportForm(data={}, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("empty", str(form.errors["positions_file"]))


class MusicImportViewTests(TestCase):
    def setUp(self):
        self.url = reverse("music:import")
        self.staff_user = User.objects.create_user(
            username="importstaff", password="importpass", is_staff=True
        )
        self.client.login(username="importstaff", password="importpass")

    def test_get_renders_the_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "music/import.html")
        self.assertContains(response, "Import Album Data")
        self.assertContains(response, "Use the bundled release files")

    def test_get_shows_the_current_row_counts(self):
        models.Album.objects.create(name="Kid A", rank=1)
        response = self.client.get(self.url)
        self.assertEqual(response.context["counts"]["albums"], 1)

    def test_anonymous_gets_404(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_a_non_staff_user_gets_404(self):
        User.objects.create_user(username="plain", password="plainpass")
        self.client.login(username="plain", password="plainpass")
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_posting_the_four_files_imports_them(self):
        response = self.client.post(self.url, _all_files())
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["error"])
        self.assertIn(
            "Albums: 1 (0 kept, 1 added, 0 removed)",
            response.context["summary"]["message"],
        )
        self.assertEqual(models.Album.objects.count(), 1)
        self.assertEqual(models.Artist.objects.get().source_id, 3)
        self.assertEqual(models.MusicList.objects.count(), 1)
        self.assertEqual(models.AlbumListMembership.objects.count(), 1)
        self.assertContains(response, "Import complete")

    def test_a_cache_error_after_the_commit_is_not_a_failed_import(self):
        with mock.patch("music.services.caching.cache") as broken:
            broken.delete_many.side_effect = ConnectionError
            with self.assertLogs("music.services.import_handler", "ERROR"):
                response = self.client.post(self.url, _all_files())

        self.assertIsNone(response.context["error"])
        summary = response.context["summary"]
        self.assertIn("Caches not cleared", summary["message"])
        self.assertTrue(models.Album.objects.exists())

    def test_a_failure_after_the_commit_does_not_claim_a_rollback(self):
        """The page would say the rankings are untouched, with the new ones live."""
        with mock.patch("music.views._music_counts", side_effect=ConnectionError):
            with self.assertRaises(ConnectionError):
                self.client.post(self.url, _all_files())

        self.assertTrue(models.Album.objects.exists())

    def test_posting_the_bundled_checkbox_imports_the_release(self):
        response = self.client.post(self.url, {"seed_bundled_data": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["error"])
        # However many the checked-in release holds; the point is that the
        # bundled files were the ones imported.
        self.assertEqual(
            models.Album.objects.count(),
            sum(
                1
                for _ in (BUNDLED_RELEASE_DIR / "WebRankings.txt").open(
                    encoding="utf-8-sig"
                )
            ),
        )
        self.assertEqual(
            models.MusicList.objects.count(),
            sum(
                1
                for _ in (BUNDLED_RELEASE_DIR / "ListData.txt").open(
                    encoding="utf-8-sig"
                )
            ),
        )
        # Every album lands on at least one list; the exact total is a
        # property of the release, not of the import page.
        self.assertGreater(models.AlbumListMembership.objects.count(), 0)
        self.assertEqual(models.Album.objects.filter(lists__isnull=True).count(), 0)
        self.assertEqual(
            models.Artist.objects.count(),
            sum(
                1
                for _ in (BUNDLED_RELEASE_DIR / "ArtistInfo.txt").open(
                    encoding="utf-8-sig"
                )
            ),
        )

    def test_posting_the_same_files_again_keeps_the_album(self):
        self.client.post(self.url, _all_files())
        album = models.Album.objects.get()
        response = self.client.post(self.url, _all_files())
        self.assertIn(
            "Albums: 1 (1 kept, 0 added, 0 removed)",
            response.context["summary"]["message"],
        )
        self.assertEqual(models.Album.objects.get().pk, album.pk)

    def test_the_page_says_albums_are_updated_in_place(self):
        response = self.client.get(self.url)
        self.assertContains(response, "matched to the ones already here by Wikidata id")
        self.assertNotContains(response, "Replaces all music ranking data")

    def test_the_summary_reports_the_new_counts(self):
        response = self.client.post(self.url, _all_files())
        self.assertEqual(response.context["summary"]["counts"]["albums"], 1)

    def test_an_invalid_form_reports_the_error_and_changes_nothing(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["summary"])
        self.assertEqual(models.Album.objects.count(), 0)
        self.assertContains(response, "Upload all four release files")

    def test_an_importer_failure_is_surfaced_and_rolls_back(self):
        models.Album.objects.create(name="Pre-existing", rank=1)
        files = _all_files()
        # More position rows than albums, so the join fails mid-import.
        files["positions_file"] = _upload("ListPositions.txt", b"0:1\n0:2\n")
        response = self.client.post(self.url, files)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["summary"])
        self.assertIn("no album at rank 2", response.context["error"])
        self.assertContains(response, "Import failed")
        # The transaction rolled back, so the previous album survives.
        self.assertEqual(models.Album.objects.count(), 1)
        self.assertEqual(models.Album.objects.first().name, "Pre-existing")

    def test_missing_bundled_files_are_reported_rather_than_crashing(self):
        with mock.patch("music.views.BUNDLED_RELEASE_DIR", Path("/nonexistent")):
            response = self.client.post(self.url, {"seed_bundled_data": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Bundled release files are missing", response.context["error"])

    def test_the_checkbox_is_disabled_when_the_bundled_files_are_absent(self):
        with mock.patch("music.views.BUNDLED_RELEASE_DIR", Path("/nonexistent")):
            response = self.client.get(self.url)
        self.assertFalse(response.context["bundled_available"])
        self.assertContains(response, "upload them instead")

    def test_bundled_files_are_listed_with_their_paths(self):
        response = self.client.get(self.url)
        self.assertTrue(response.context["bundled_available"])
        names = [entry["name"] for entry in response.context["bundled_files"]]
        self.assertEqual(
            names,
            ["ArtistInfo.txt", "ListData.txt", "WebRankings.txt", "ListPositions.txt"],
        )
        self.assertContains(response, "ListData.txt")

    def test_importing_clears_the_cached_filter_options(self):
        # The rankings page caches artist options and hero counts, so a stale
        # cache would survive an import and show the previous data.
        self.client.get(reverse("music:home"))
        self.client.post(self.url, _all_files())
        response = self.client.get(reverse("music:home"))
        self.assertEqual(response.context["album_count"], 1)
        self.assertEqual(
            [a["name"] for a in response.context["artists"]], ["The Beach Boys"]
        )

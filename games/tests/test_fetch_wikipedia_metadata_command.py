"""Tests for the fetch_wikipedia_metadata management command."""

import csv
import os
import tempfile
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from games.models import Game, WikipediaGameData, WikipediaGenre
from games.services.wiki_genre_service import GenreResult, GenreSource
from games.services.wiki_page_lookup_service import PageLookupResult

COMMAND = "games.management.commands.fetch_wikipedia_metadata"


def page_found(name, title=None, **fields):
    """The lookup's answer for a game whose page it found."""
    return PageLookupResult(
        game_name=name, page_title=title or name, lookup_source="wikidata", **fields
    )


def page_missing(name):
    """The lookup's answer for a game with no page."""
    return PageLookupResult(game_name=name, error_message="Page not found on Wikipedia")


class StandInServicesMixin:
    """Runs the command against stand-ins for the two services it reads.

    The network is closed under test, and what these tests are about is
    what the command does with an answer, not how the answer is fetched.
    """

    def run_command(self, *args, pages=None, alternates=None, genres=None):
        """Run the command; return what it printed and the page service.

        ``pages`` maps a game's name to its ``PageLookupResult`` (a game
        not named is found under its own name), ``alternates`` a Wikidata
        id to what ``_lookup_via_wikidata`` answers for it (an id not
        named gets ``None``, a failed lookup), and ``genres`` a game's
        name to the genres its page lists (none by default).
        """
        pages = pages or {}
        genres = genres or {}

        def lookup_page(name, wikidata_id, year):
            return pages.get(name) or page_found(name)

        def genre_from_url(name, url):
            found = genres.get(name, [])
            return GenreResult(
                game_name=name,
                source=GenreSource.WIKIPEDIA if found else GenreSource.FAILED,
                primary_genre=found[0] if found else None,
                all_genres=found,
            )

        out = StringIO()
        with mock.patch(f"{COMMAND}.WikiPageLookupService") as page_class, mock.patch(
            f"{COMMAND}.WikiGenreService"
        ) as genre_class:
            page_service = page_class.return_value
            page_service.lookup_page.side_effect = lookup_page
            page_service._lookup_via_wikidata.side_effect = (alternates or {}).get
            genre_class.return_value.get_genre_from_url.side_effect = genre_from_url
            call_command("fetch_wikipedia_metadata", *args, stdout=out)
        return out.getvalue(), page_service


class FetchWikipediaMetadataCommandTests(TestCase):
    """Tests for the fetch_wikipedia_metadata management command."""

    def setUp(self):
        """Set up test games."""
        self.game1 = Game.objects.create(
            name="Test Game 1",
            rank=1,
            wikidata_id="Q123456",
        )
        self.game2 = Game.objects.create(
            name="Test Game 2",
            rank=2,
        )

    def test_command_processes_all_games(self):
        """Test command processes all games by default."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class, mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiGenreService"
        ) as mock_genre_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game",
                page_title="Test Game",
                lookup_source="wikidata",
            )

            mock_genre_service = mock_genre_service_class.return_value
            mock_genre_service.get_genre_from_url.return_value = GenreResult(
                game_name="Test Game",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Action",
                all_genres=["Action", "Adventure"],
            )

            call_command("fetch_wikipedia_metadata", "--save", stdout=out)

        # Should process both games
        self.assertEqual(mock_page_service.lookup_page.call_count, 2)

    def test_command_processes_single_game_by_name(self):
        """Test command processes single game when --game is specified."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title="Test Game 1",
                lookup_source="wikidata",
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                stdout=out,
            )

        # Should only process one game
        self.assertEqual(mock_page_service.lookup_page.call_count, 1)

    def test_command_saves_page_data_and_genres_to_database(self):
        """Test command saves both page data and genres to database with --save flag."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class, mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiGenreService"
        ) as mock_genre_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title="Test Game 1",
                lookup_source="wikidata",
            )

            mock_genre_service = mock_genre_service_class.return_value
            mock_genre_service.get_genre_from_url.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Action",
                all_genres=["Action", "Adventure", "Puzzle"],
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--save",
                stdout=out,
            )

        # Refresh from database and check WikipediaGameData was created
        self.game1.refresh_from_db()
        self.assertIsNotNone(self.game1.primary_wikipedia_game_data)
        wiki_data = self.game1.primary_wikipedia_game_data
        self.assertEqual(wiki_data.page_title, "Test Game 1")
        self.assertEqual(wiki_data.lookup_source, "wikidata")
        self.assertEqual(wiki_data.primary_genre, "Action")
        self.assertEqual(wiki_data.all_genres, "Action, Adventure, Puzzle")

        # Check WikipediaGenre objects were created
        self.assertEqual(self.game1.wikipedia_genres.count(), 3)
        genre_names = set(self.game1.wikipedia_genres.values_list("name", flat=True))
        self.assertEqual(genre_names, {"Action", "Adventure", "Puzzle"})

    def test_command_handles_page_lookup_failure(self):
        """Test command handles page lookup failures gracefully."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title=None,
                error_message="Page not found",
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--save",
                stdout=out,
            )

        # Refresh from database - should not be updated
        self.game1.refresh_from_db()
        self.assertIsNone(self.game1.primary_wikipedia_game_data)

        output = out.getvalue()
        self.assertIn("Page not found", output)

    def test_command_handles_genre_scraping_failure(self):
        """Test command handles genre scraping failures gracefully."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class, mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiGenreService"
        ) as mock_genre_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title="Test Game 1",
                lookup_source="opensearch",
            )

            mock_genre_service = mock_genre_service_class.return_value
            mock_genre_service.get_genre_from_url.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.FAILED,
                primary_genre=None,
                all_genres=[],
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--save",
                stdout=out,
            )

        # Page data should be saved, but genres should be None
        self.game1.refresh_from_db()
        self.assertIsNotNone(self.game1.primary_wikipedia_game_data)
        wiki_data = self.game1.primary_wikipedia_game_data
        self.assertEqual(wiki_data.page_title, "Test Game 1")
        self.assertIsNone(wiki_data.primary_genre)

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
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 2",
                page_title="Test Game 2",
                lookup_source="wikidata",
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--skip-existing",
                stdout=out,
            )

        # Should only process game2 (game1 has existing data)
        self.assertEqual(mock_page_service.lookup_page.call_count, 1)

    def test_command_reconnects_orphaned_records(self):
        """Test command reconnects orphaned WikipediaGameData records."""
        # Create orphaned record (no game link)
        orphaned_record = WikipediaGameData.objects.create(
            game=None,
            page_title="Test Game 1",
            primary_genre="Action",
            lookup_source="wikidata",
            is_primary=True,
        )

        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class, mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiGenreService"
        ) as mock_genre_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title="Test Game 1",
                lookup_source="wikidata",
            )

            mock_genre_service = mock_genre_service_class.return_value
            mock_genre_service.get_genre_from_url.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Adventure",
                all_genres=["Adventure"],
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--save",
                stdout=out,
            )

        # Check orphaned record was reconnected
        orphaned_record.refresh_from_db()
        self.assertEqual(orphaned_record.game, self.game1)
        self.game1.refresh_from_db()
        self.assertEqual(self.game1.primary_wikipedia_game_data.id, orphaned_record.id)

    def test_command_writes_csv_output(self):
        """Test command writes CSV output file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
            output_path = tmp.name

        try:
            cmd = "games.management.commands.fetch_wikipedia_metadata"
            with mock.patch(
                f"{cmd}.WikiPageLookupService"
            ) as mock_page_service_class, mock.patch(
                f"{cmd}.WikiGenreService"
            ) as mock_genre_service_class:
                mock_page_service = mock_page_service_class.return_value
                mock_page_service.lookup_page.return_value = PageLookupResult(
                    game_name="Test Game 1",
                    page_title="Test Game 1",
                    lookup_source="opensearch",
                )

                mock_genre_service = mock_genre_service_class.return_value
                mock_genre_service.get_genre_from_url.return_value = GenreResult(
                    game_name="Test Game 1",
                    source=GenreSource.WIKIPEDIA,
                    primary_genre="Puzzle",
                    all_genres=["Puzzle", "Strategy"],
                )

                call_command(
                    "fetch_wikipedia_metadata",
                    "--game",
                    "Test Game 1",
                    "--save",
                    "--output",
                    output_path,
                )

            # Check CSV was written
            with open(output_path, "r") as f:
                content = f.read()

            self.assertIn("Game Name", content)
            self.assertIn("Wikipedia Page Title", content)
            self.assertIn("Primary Genre", content)
            self.assertIn("All Genres", content)
            self.assertIn("Test Game 1", content)
            self.assertIn("Puzzle", content)

        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_command_respects_limit(self):
        """Test command respects --limit option."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game",
                page_title="Test Game",
                lookup_source="wikidata",
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--limit",
                "1",
                stdout=out,
            )

        # Should only process 1 game due to limit
        self.assertEqual(mock_page_service.lookup_page.call_count, 1)

    def test_command_normalizes_genre_names(self):
        """Test command stores canonical genre names, not prettified raw labels."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class, mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiGenreService"
        ) as mock_genre_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title="Test Game 1",
                lookup_source="wikidata",
            )

            # Service returns lowercase genre names
            mock_genre_service = mock_genre_service_class.return_value
            mock_genre_service.get_genre_from_url.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="action-adventure",
                all_genres=["action-adventure", "rpg"],
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--save",
                stdout=out,
            )

        # Check genres were normalized to canonical labels
        self.game1.refresh_from_db()
        wiki_data = self.game1.primary_wikipedia_game_data
        self.assertEqual(wiki_data.primary_genre, "Action-Adventure")
        self.assertEqual(wiki_data.all_genres, "Action-Adventure, Role-Playing")

    def test_command_handles_genre_scraping_exception(self):
        """Test command handles exceptions during genre scraping."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class, mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiGenreService"
        ) as mock_genre_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title="Test Game 1",
                lookup_source="wikidata",
            )

            mock_genre_service = mock_genre_service_class.return_value
            mock_genre_service.get_genre_from_url.side_effect = Exception(
                "Network error"
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--save",
                stdout=out,
            )

        # Page data should still be saved even though genre scraping failed
        self.game1.refresh_from_db()
        self.assertIsNotNone(self.game1.primary_wikipedia_game_data)
        wiki_data = self.game1.primary_wikipedia_game_data
        self.assertEqual(wiki_data.page_title, "Test Game 1")
        self.assertIsNone(wiki_data.primary_genre)

        output = out.getvalue()
        self.assertIn("Genre scraping error", output)

    def test_command_no_games_to_process(self):
        """Test command message when no games match criteria."""
        out = StringIO()

        call_command(
            "fetch_wikipedia_metadata",
            "--game",
            "NonExistentGame",
            stdout=out,
        )

        output = out.getvalue()
        self.assertIn("No games found to process", output)

    def test_command_normalizes_genres(self):
        """Test command normalizes genre names to canonical forms."""
        from games.models import WikipediaGenre

        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class, mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiGenreService"
        ) as mock_genre_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title="Test Game 1",
                lookup_source="wikidata",
            )

            # Service returns non-canonical genres
            mock_genre_service = mock_genre_service_class.return_value
            mock_genre_service.get_genre_from_url.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Survival horror",
                all_genres=["Survival horror", "First-person shooter", "Action"],
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--save",
                stdout=out,
            )

        # Check genres were normalized
        self.game1.refresh_from_db()
        genre_names = set(self.game1.wikipedia_genres.values_list("name", flat=True))
        # "Survival horror" should normalize to "Horror"
        # "First-person shooter" should normalize to "First-Person Shooter"
        # "Action" stays as "Action"
        self.assertEqual(genre_names, {"Horror", "First-Person Shooter", "Action"})

        # Ensure only canonical genres exist in database
        self.assertFalse(WikipediaGenre.objects.filter(name="Survival horror").exists())
        self.assertTrue(WikipediaGenre.objects.filter(name="Horror").exists())

    def test_command_removes_duplicate_normalized_genres(self):
        """Test command removes duplicates after normalization."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class, mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiGenreService"
        ) as mock_genre_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title="Test Game 1",
                lookup_source="wikidata",
            )

            # Service returns genres that normalize to the same value
            mock_genre_service = mock_genre_service_class.return_value
            mock_genre_service.get_genre_from_url.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Platform",
                all_genres=["Platform", "Platformer", "Platform game"],
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--save",
                stdout=out,
            )

        # All three should normalize to "Platform" - only one genre should be linked
        self.game1.refresh_from_db()
        self.assertEqual(self.game1.wikipedia_genres.count(), 1)
        self.assertEqual(self.game1.wikipedia_genres.first().name, "Platform")

    def test_command_skips_invalid_genres(self):
        """Test command skips genres that map to None (invalid)."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class, mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiGenreService"
        ) as mock_genre_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title="Test Game 1",
                lookup_source="wikidata",
            )

            # Service returns genres including invalid ones
            mock_genre_service = mock_genre_service_class.return_value
            mock_genre_service.get_genre_from_url.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Action",
                all_genres=["Action", "(minigame)", "Various"],
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--save",
                stdout=out,
            )

        # Only the real genre is linked. (This test asserted nothing, so the
        # command could have linked all three.)
        self.game1.refresh_from_db()
        self.assertEqual(
            [genre.name for genre in self.game1.wikipedia_genres.all()], ["Action"]
        )
        for junk in ("(minigame)", "Various"):
            self.assertFalse(WikipediaGenre.objects.filter(name=junk).exists())

    def test_command_maps_orphan_root_labels_to_canonical_genres(self):
        """Test future Wikipedia fetches do not recreate orphan root genres."""
        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class, mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiGenreService"
        ) as mock_genre_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title="Test Game 1",
                lookup_source="wikidata",
            )

            mock_genre_service = mock_genre_service_class.return_value
            mock_genre_service.get_genre_from_url.return_value = GenreResult(
                game_name="Test Game 1",
                source=GenreSource.WIKIPEDIA,
                primary_genre="Action role-playing game",
                all_genres=["Action role-playing game", "First-person"],
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--save",
                stdout=out,
            )

        self.game1.refresh_from_db()
        wiki_data = self.game1.primary_wikipedia_game_data
        self.assertEqual(wiki_data.primary_genre, "Action RPG")
        self.assertEqual(wiki_data.all_genres, "Action RPG")
        self.assertEqual(self.game1.wikipedia_genres.count(), 1)
        self.assertEqual(self.game1.wikipedia_genres.first().name, "Action RPG")
        self.assertFalse(
            WikipediaGenre.objects.filter(name="Action role-playing game").exists()
        )
        self.assertFalse(WikipediaGenre.objects.filter(name="First-person").exists())

    def test_cleanup_orphans_flag_deletes_unlinked_genres(self):
        """Test --cleanup-orphans flag deletes WikipediaGenre records with no games."""
        from games.models import WikipediaGenre

        # Clear all pre-existing genres first
        WikipediaGenre.objects.all().delete()

        # Create orphan genres (not linked to any game)
        WikipediaGenre.objects.create(name="Orphan Genre 1")
        WikipediaGenre.objects.create(name="Orphan Genre 2")
        linked_genre = WikipediaGenre.objects.create(name="Linked Genre")
        self.game1.wikipedia_genres.add(linked_genre)

        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title=None,
                error_message="Not found",
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--cleanup-orphans",
                stdout=out,
            )

        output = out.getvalue()

        # Should delete orphan genres
        self.assertIn("Deleted 2 orphan WikipediaGenre records", output)
        self.assertFalse(WikipediaGenre.objects.filter(name="Orphan Genre 1").exists())
        self.assertFalse(WikipediaGenre.objects.filter(name="Orphan Genre 2").exists())
        # Linked genre should still exist
        self.assertTrue(WikipediaGenre.objects.filter(name="Linked Genre").exists())

    def test_cleanup_orphans_no_orphans_message(self):
        """Test --cleanup-orphans shows message when no orphans exist."""
        from games.models import WikipediaGenre

        # Clear all pre-existing genres first
        WikipediaGenre.objects.all().delete()

        out = StringIO()

        with mock.patch(
            "games.management.commands.fetch_wikipedia_metadata.WikiPageLookupService"
        ) as mock_page_service_class:
            mock_page_service = mock_page_service_class.return_value
            mock_page_service.lookup_page.return_value = PageLookupResult(
                game_name="Test Game 1",
                page_title=None,
                error_message="Not found",
            )

            call_command(
                "fetch_wikipedia_metadata",
                "--game",
                "Test Game 1",
                "--cleanup-orphans",
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("No orphan WikipediaGenre records found", output)


class WhichGamesTests(StandInServicesMixin, TestCase):
    """The options that pick the games, and what the run says of itself."""

    def setUp(self):
        self.first = Game.objects.create(name="Alpha Quest", rank=1, slug="alpha-quest")
        self.second = Game.objects.create(name="Beta Racer", rank=2, slug="beta-racer")
        self.third = Game.objects.create(name="Gamma Golf", rank=3, slug="gamma-golf")

    def looked_up(self, page_service):
        return [call.args[0] for call in page_service.lookup_page.call_args_list]

    def test_slug_picks_the_game_with_that_slug(self):
        output, page_service = self.run_command("--slug", "beta-racer")
        self.assertEqual(self.looked_up(page_service), ["Beta Racer"])
        self.assertIn("Processing 1 games", output)

    def test_id_picks_the_game_with_that_pk(self):
        output, page_service = self.run_command("--id", str(self.third.pk))
        self.assertEqual(self.looked_up(page_service), ["Gamma Golf"])

    def test_offset_skips_that_many_games_from_the_top_of_the_ranking(self):
        """With --limit it is how a long run is taken a slice at a time."""
        output, page_service = self.run_command("--offset", "1")
        self.assertEqual(self.looked_up(page_service), ["Beta Racer", "Gamma Golf"])

        output, page_service = self.run_command("--offset", "1", "--limit", "1")
        self.assertEqual(self.looked_up(page_service), ["Beta Racer"])

    def test_without_save_nothing_is_stored(self):
        """The default is a dry run: the page is printed and that is all."""
        output, page_service = self.run_command(
            alternates={"Q2": ("Alpha Quest II", "9", None, None)}
        )
        self.assertIn("Alpha Quest: Alpha Quest (wikidata)", output)
        self.assertNotIn("Results saved to database", output)
        self.assertFalse(WikipediaGameData.objects.exists())

    @override_settings(WIKIDATA_ACCESS_TOKEN="reader:secret")
    def test_says_when_its_requests_are_authenticated(self):
        """The delay between requests depends on it, so the run names it."""
        output, _ = self.run_command("--limit", "1")
        self.assertIn("Using authenticated Wikidata requests", output)
        self.assertNotIn("Set WIKIDATA_ACCESS_TOKEN", output)

    def test_says_when_its_requests_are_not_authenticated(self):
        output, _ = self.run_command("--limit", "1")
        self.assertIn("Using unauthenticated Wikidata requests", output)
        self.assertIn("Set WIKIDATA_ACCESS_TOKEN", output)

    def test_the_summary_counts_pages_found_and_not_found(self):
        output, _ = self.run_command(
            "--save",
            pages={"Beta Racer": page_missing("Beta Racer")},
            genres={"Alpha Quest": ["Action"]},
        )
        self.assertIn("Total games: 3", output)
        self.assertIn("Wikipedia pages found: 2", output)
        self.assertIn("Wikipedia pages not found: 1", output)
        self.assertIn("Genres found: 1", output)
        self.assertIn("Genres not found: 1", output)


class CsvOutputTests(StandInServicesMixin, TestCase):
    """--output writes a row a game; without it no file is written."""

    def setUp(self):
        Game.objects.create(name="Alpha Quest", rank=1, wikidata_id="Q1")
        Game.objects.create(name="Beta Racer", rank=2)

    def test_each_game_is_a_row_found_or_not(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "pages.csv")
            output, _ = self.run_command(
                "--save",
                "--output",
                path,
                pages={
                    "Alpha Quest": page_found(
                        "Alpha Quest", "Alpha Quest (video game)"
                    ),
                    "Beta Racer": page_missing("Beta Racer"),
                },
                genres={"Alpha Quest": ["Puzzle", "Strategy"]},
            )
            with open(path, newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))

        self.assertEqual(
            rows,
            [
                [
                    "Rank",
                    "Game Name",
                    "Wikipedia Page Title",
                    "Lookup Source",
                    "Primary Genre",
                    "All Genres",
                    "Wikipedia URL",
                    "Error",
                ],
                [
                    "1",
                    "Alpha Quest",
                    "Alpha Quest (video game)",
                    "wikidata",
                    "Puzzle",
                    "Puzzle, Strategy",
                    "https://en.wikipedia.org/wiki/Alpha_Quest_(video_game)",
                    "",
                ],
                ["2", "Beta Racer", "", "", "", "", "", "Page not found on Wikipedia"],
            ],
        )
        self.assertIn(f"Writing results to: {path}", output)
        self.assertIn(f"Results written to {path}", output)

    def test_without_output_no_file_is_opened(self):
        """The help once promised a timestamped file by default.

        No run ever wrote one: the path was only worked out once --output
        had been given.
        """
        with mock.patch(f"{COMMAND}.open", create=True) as opened:
            output, _ = self.run_command("--save")
        opened.assert_not_called()
        self.assertNotIn("Results written", output)
        self.assertIn("Results saved to database", output)


class AlternateWikidataRecordTests(StandInServicesMixin, TestCase):
    """A game's other Wikidata ids each get a record of their own.

    The release lists every Wikidata entity a game has (a remake's, a
    compilation's), the first being its own. HowLongToBeat ids are often
    on one of the others, and ``fetch_hltb_data`` reads every record a game
    has, so each alternate id is looked up and kept beside the primary.
    """

    def setUp(self):
        self.game = Game.objects.create(
            name="Alpha Quest",
            rank=1,
            wikidata_id="Q1",
            all_wikidata_ids=["Q1", "Q2"],
        )

    def records(self):
        """Each of the game's records as (id, page, primary, hltb, steam, quote)."""
        return list(
            WikipediaGameData.objects.filter(game=self.game)
            .order_by("wikidata_id")
            .values_list(
                "wikidata_id",
                "page_title",
                "is_primary",
                "hltb_id",
                "steam_app_id",
                "wikiquote_page_title",
            )
        )

    def stored_alternate(self, **fields):
        fields.setdefault("page_title", "Alpha Quest Remake")
        return WikipediaGameData.objects.create(
            game=self.game, wikidata_id="Q2", is_primary=False, **fields
        )

    def test_an_alternate_id_gets_a_record_beside_the_primary(self):
        output, page_service = self.run_command(
            "--save",
            alternates={"Q2": ("Alpha Quest Remake", "15544", "620", "Alpha Quest")},
        )

        self.assertEqual(
            self.records(),
            [
                ("Q1", "Alpha Quest", True, None, None, None),
                ("Q2", "Alpha Quest Remake", False, "15544", "620", "Alpha Quest"),
            ],
        )
        self.game.refresh_from_db()
        self.assertEqual(self.game.primary_wikipedia_game_data.wikidata_id, "Q1")
        # The primary id was the page lookup's: it is not read a second time
        page_service._lookup_via_wikidata.assert_called_once_with("Q2")
        self.assertIn(
            "Refreshed 1 alternate Wikidata record(s) (1 with HLTB ID)", output
        )

    def test_an_alternate_with_no_wikipedia_page_still_keeps_its_ids(self):
        """An entity with no English article can still hold the HLTB id."""
        self.run_command("--save", alternates={"Q2": (None, "15544", None, None)})
        self.assertEqual(
            self.records(),
            [
                ("Q1", "Alpha Quest", True, None, None, None),
                ("Q2", "", False, "15544", None, None),
            ],
        )

    def test_an_alternate_without_an_hltb_id_is_not_counted_as_having_one(self):
        output, _ = self.run_command(
            "--save", alternates={"Q2": ("Alpha Quest Remake", None, "620", None)}
        )
        self.assertEqual(
            self.records()[1], ("Q2", "Alpha Quest Remake", False, None, "620", None)
        )
        self.assertIn("Refreshed 1 alternate Wikidata record(s)\n", output)
        self.assertNotIn("with HLTB ID", output)

    def test_an_alternate_wikidata_does_not_answer_for_gets_no_record(self):
        """A failed lookup is ``None``: nothing is stored, nothing claimed."""
        output, page_service = self.run_command("--save", alternates={})
        page_service._lookup_via_wikidata.assert_called_once_with("Q2")
        self.assertEqual(
            self.records(), [("Q1", "Alpha Quest", True, None, None, None)]
        )
        self.assertNotIn("alternate Wikidata record", output)

    def test_blank_ids_are_not_looked_up(self):
        """The import strips them; the admin's JSON field can hold anything."""
        self.game.all_wikidata_ids = ["Q1", "", "   ", None, "Q2"]
        self.game.save()
        _, page_service = self.run_command(
            "--save", alternates={"Q2": ("Alpha Quest Remake", None, None, None)}
        )
        page_service._lookup_via_wikidata.assert_called_once_with("Q2")
        self.assertEqual([record[0] for record in self.records()], ["Q1", "Q2"])

    def test_a_game_with_one_id_has_no_alternates(self):
        for ids in (["Q1"], []):
            with self.subTest(all_wikidata_ids=ids):
                WikipediaGameData.objects.all().delete()
                self.game.all_wikidata_ids = ids
                self.game.save()
                output, page_service = self.run_command("--save", "--force")
                page_service._lookup_via_wikidata.assert_not_called()
                self.assertEqual(
                    self.records(), [("Q1", "Alpha Quest", True, None, None, None)]
                )
                self.assertNotIn("alternate Wikidata record", output)

    def test_a_stored_alternate_takes_what_wikidata_now_says(self):
        """Updated in place: a second run must not make a second record."""
        stored = self.stored_alternate(page_title="Alpha Quest HD", hltb_id="6571")
        output, _ = self.run_command(
            "--save",
            alternates={"Q2": ("Alpha Quest Remake", "15544", "620", "Alpha Quest")},
        )

        self.assertEqual(
            self.records(),
            [
                ("Q1", "Alpha Quest", True, None, None, None),
                ("Q2", "Alpha Quest Remake", False, "15544", "620", "Alpha Quest"),
            ],
        )
        self.assertEqual(WikipediaGameData.objects.get(wikidata_id="Q2").pk, stored.pk)
        self.assertIn(
            "Refreshed 1 alternate Wikidata record(s) (1 with HLTB ID)", output
        )

    def test_a_change_that_is_not_the_hltb_id_claims_no_hltb_id(self):
        self.stored_alternate(hltb_id="15544")
        output, _ = self.run_command(
            "--save",
            alternates={"Q2": ("Alpha Quest Remake", "15544", "620", None)},
        )
        self.assertEqual(
            self.records()[1],
            ("Q2", "Alpha Quest Remake", False, "15544", "620", None),
        )
        self.assertIn("Refreshed 1 alternate Wikidata record(s)\n", output)
        self.assertNotIn("with HLTB ID", output)

    def test_a_stored_alternate_that_has_not_changed_is_not_saved(self):
        stored = self.stored_alternate(
            hltb_id="15544", steam_app_id="620", wikiquote_page_title="Alpha Quest"
        )
        output, _ = self.run_command(
            "--save",
            alternates={"Q2": ("Alpha Quest Remake", "15544", "620", "Alpha Quest")},
        )
        saved_at = stored.updated_at
        stored.refresh_from_db()
        self.assertEqual(stored.updated_at, saved_at)
        self.assertNotIn("alternate Wikidata record", output)

    def test_what_wikidata_no_longer_holds_is_left_as_stored(self):
        """As for the primary: a lookup that finds less erases nothing."""
        self.stored_alternate(
            hltb_id="15544", steam_app_id="620", wikiquote_page_title="Alpha Quest"
        )
        output, _ = self.run_command(
            "--save", alternates={"Q2": (None, None, None, None)}
        )
        self.assertEqual(
            self.records()[1],
            ("Q2", "Alpha Quest Remake", False, "15544", "620", "Alpha Quest"),
        )
        self.assertNotIn("alternate Wikidata record", output)

    def test_alternates_are_read_when_the_primary_has_no_page(self):
        """The game's own entity may have no article while another has the
        HLTB id, and that is the id the playtime fetch needs."""
        output, _ = self.run_command(
            "--save",
            pages={"Alpha Quest": page_missing("Alpha Quest")},
            alternates={"Q2": ("Alpha Quest Remake", "15544", None, None)},
        )

        self.assertEqual(
            self.records(), [("Q2", "Alpha Quest Remake", False, "15544", None, None)]
        )
        # Still without a primary, so the next run tries its page again
        self.game.refresh_from_db()
        self.assertIsNone(self.game.primary_wikipedia_game_data)
        self.assertIn("✗ Alpha Quest: Page not found on Wikipedia", output)
        self.assertIn(
            "Refreshed 1 alternate Wikidata record(s) (1 with HLTB ID)", output
        )

    def test_a_missing_page_and_an_unchanged_alternate_claim_nothing(self):
        self.stored_alternate(hltb_id="15544")
        output, _ = self.run_command(
            "--save",
            pages={"Alpha Quest": page_missing("Alpha Quest")},
            alternates={"Q2": ("Alpha Quest Remake", "15544", None, None)},
        )
        self.assertNotIn("alternate Wikidata record", output)

    def test_skip_alternate_wikidata_reads_none(self):
        for pages in ({}, {"Alpha Quest": page_missing("Alpha Quest")}):
            with self.subTest(found=not pages):
                _, page_service = self.run_command(
                    "--save",
                    "--force",
                    "--skip-alternate-wikidata",
                    pages=pages,
                    alternates={"Q2": ("Alpha Quest Remake", "15544", None, None)},
                )
                page_service._lookup_via_wikidata.assert_not_called()
                self.assertFalse(
                    WikipediaGameData.objects.filter(wikidata_id="Q2").exists()
                )

    def test_without_save_no_alternate_is_read(self):
        for pages in ({}, {"Alpha Quest": page_missing("Alpha Quest")}):
            with self.subTest(found=not pages):
                _, page_service = self.run_command(
                    pages=pages,
                    alternates={"Q2": ("Alpha Quest Remake", "15544", None, None)},
                )
                page_service._lookup_via_wikidata.assert_not_called()
                self.assertFalse(WikipediaGameData.objects.exists())

    def test_two_alternates_on_one_page_each_keep_a_record(self):
        """Records are kept by Wikidata id, so a shared title merges nothing."""
        self.game.all_wikidata_ids = ["Q1", "Q2", "Q3"]
        self.game.save()
        output, _ = self.run_command(
            "--save",
            alternates={
                "Q2": ("Alpha Quest Collection", "15544", None, None),
                "Q3": ("Alpha Quest Collection", None, "620", None),
            },
        )
        self.assertEqual(
            self.records(),
            [
                ("Q1", "Alpha Quest", True, None, None, None),
                ("Q2", "Alpha Quest Collection", False, "15544", None, None),
                ("Q3", "Alpha Quest Collection", False, None, "620", None),
            ],
        )
        self.assertIn(
            "Refreshed 2 alternate Wikidata record(s) (1 with HLTB ID)", output
        )

    def test_an_alternate_on_the_primarys_page_does_not_take_its_place(self):
        """The game's own entity has no article, and the search finds the
        alternate's. A second run then meets two records of one page:
        ``attach_page`` keeps the older, the primary, and the alternate's
        is made again with its ids."""
        alternates = {"Q2": ("Alpha Quest", "15544", None, None)}
        self.run_command("--save", alternates=alternates)
        primary = WikipediaGameData.objects.get(wikidata_id="Q1")

        self.run_command("--save", "--force", alternates=alternates)

        self.assertEqual(
            self.records(),
            [
                ("Q1", "Alpha Quest", True, None, None, None),
                ("Q2", "Alpha Quest", False, "15544", None, None),
            ],
        )
        self.game.refresh_from_db()
        self.assertEqual(self.game.primary_wikipedia_game_data_id, primary.pk)

    def test_another_games_record_of_the_id_is_left_with_that_game(self):
        """Two games can list one entity (a compilation's). Each has its own
        record of it: the second game's must not be taken from the first."""
        other = Game.objects.create(name="Beta Racer", rank=2, wikidata_id="Q2")
        theirs = WikipediaGameData.objects.create(
            game=other, wikidata_id="Q2", page_title="Old title", is_primary=True
        )
        other.primary_wikipedia_game_data = theirs
        other.save()

        self.run_command(
            "--save", alternates={"Q2": ("Alpha Quest Remake", "15544", None, None)}
        )

        self.assertEqual(
            self.records()[1], ("Q2", "Alpha Quest Remake", False, "15544", None, None)
        )
        theirs.refresh_from_db()
        self.assertEqual(
            (theirs.game, theirs.page_title, theirs.is_primary, theirs.hltb_id),
            (other, "Old title", True, None),
        )


class WikiPageLookupServiceTests(TestCase):
    """Tests for WikiPageLookupService internal logic."""

    def test_skips_deprecated_hltb_ids(self):
        """Test that deprecated P2816 (HLTB ID) claims are skipped."""
        from games.services.wiki_page_lookup_service import WikiPageLookupService

        service = WikiPageLookupService(delay=0)

        # Mock the Wikidata API response for NHL '94 (Q607073)
        # which has deprecated IDs 6571 and 16527, and normal ID 15544
        mock_response_data = {
            "entities": {
                "Q607073": {
                    "sitelinks": {
                        "enwiki": {"title": "NHL 94"},
                    },
                    "claims": {
                        "P2816": [
                            {
                                "rank": "deprecated",
                                "mainsnak": {
                                    "datavalue": {"value": "6571"},
                                },
                            },
                            {
                                "rank": "normal",
                                "mainsnak": {
                                    "datavalue": {"value": "15544"},
                                },
                            },
                            {
                                "rank": "deprecated",
                                "mainsnak": {
                                    "datavalue": {"value": "16527"},
                                },
                            },
                        ],
                    },
                }
            }
        }

        with mock.patch.object(service, "_make_request") as mock_request:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_request.return_value = mock_response

            result = service._lookup_via_wikidata("Q607073")

        # Should return the normal (non-deprecated) HLTB ID
        self.assertIsNotNone(result)
        page_title, hltb_id, steam_app_id, wikiquote = result
        self.assertEqual(page_title, "NHL 94")
        self.assertEqual(hltb_id, "15544")  # The normal rank ID, not deprecated

    def test_prefers_preferred_rank_over_normal(self):
        """Test that 'preferred' rank P2816 claims take priority over 'normal'."""
        from games.services.wiki_page_lookup_service import WikiPageLookupService

        service = WikiPageLookupService(delay=0)

        mock_response_data = {
            "entities": {
                "Q12345": {
                    "sitelinks": {
                        "enwiki": {"title": "Test Game"},
                    },
                    "claims": {
                        "P2816": [
                            {
                                "rank": "normal",
                                "mainsnak": {
                                    "datavalue": {"value": "111"},
                                },
                            },
                            {
                                "rank": "preferred",
                                "mainsnak": {
                                    "datavalue": {"value": "222"},
                                },
                            },
                        ],
                    },
                }
            }
        }

        with mock.patch.object(service, "_make_request") as mock_request:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_request.return_value = mock_response

            result = service._lookup_via_wikidata("Q12345")

        # Should return the preferred HLTB ID
        self.assertIsNotNone(result)
        page_title, hltb_id, steam_app_id, wikiquote = result
        self.assertEqual(hltb_id, "222")  # Preferred rank

    def test_returns_none_when_all_hltb_ids_deprecated(self):
        """Test that None is returned for HLTB ID when all claims are deprecated."""
        from games.services.wiki_page_lookup_service import WikiPageLookupService

        service = WikiPageLookupService(delay=0)

        mock_response_data = {
            "entities": {
                "Q99999": {
                    "sitelinks": {
                        "enwiki": {"title": "All Deprecated Game"},
                    },
                    "claims": {
                        "P2816": [
                            {
                                "rank": "deprecated",
                                "mainsnak": {
                                    "datavalue": {"value": "111"},
                                },
                            },
                            {
                                "rank": "deprecated",
                                "mainsnak": {
                                    "datavalue": {"value": "222"},
                                },
                            },
                        ],
                    },
                }
            }
        }

        with mock.patch.object(service, "_make_request") as mock_request:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_request.return_value = mock_response

            result = service._lookup_via_wikidata("Q99999")

        # Page should be found but HLTB ID should be None
        self.assertIsNotNone(result)
        page_title, hltb_id, steam_app_id, wikiquote = result
        self.assertEqual(page_title, "All Deprecated Game")
        self.assertIsNone(hltb_id)  # No valid HLTB ID

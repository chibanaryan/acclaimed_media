import json
import os
import re
import subprocess

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.apps import apps
from django.db import connection, transaction

from games import open_ended
from games.models import (
    Article,
    Developer,
    Game,
    HLTBGameData,
    IGDBGameData,
    List,
    ListMembership,
    Platform,
    PlayedGame,
    Post,
    Publication,
    SavedFilterSet,
    Series,
    SiteMetadata,
    Snippet,
    WantToPlayGame,
    WikipediaGameData,
    WikipediaGenre,
)

# core/fixtures, gitignored
FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fixtures"
)


class Command(BaseCommand):
    help = "Sync production game and music data to local SQLite"

    # Per-user rows are never synced: they belong to production's accounts
    GAMES_DUMP = (
        "dumpdata games sites flatpages "
        "--exclude games.PlayedGame "
        "--exclude games.WantToPlayGame "
        "--exclude games.SavedFilterSet "
        "--indent 2"
    )
    # Includes the cover art bytes (~100 MB), so it is written to its own
    # fixture as-is rather than parsed like the games dump
    MUSIC_DUMP = (
        "dumpdata music "
        "--exclude music.ListenedAlbum "
        "--exclude music.WantToListenAlbum "
        "--exclude music.SavedAlbumFilterSet"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            type=str,
            default="acclaimedgames",
            help="Heroku app name (default: acclaimedgames)",
        )
        parser.add_argument(
            "--keep-fixture",
            action="store_true",
            help="Keep the two downloaded fixtures (the music one ~100 MB) in "
            "core/fixtures after import",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Skip confirmation prompt",
        )

    def handle(self, *args, **options):
        app_name = options["app"]
        keep_fixture = options["keep_fixture"]
        no_input = options["no_input"]

        self.stdout.write("Syncing production database to local SQLite...")
        self.stdout.write(f"Heroku app: {app_name}")

        # Confirmation prompt
        if not no_input:
            confirm = input(
                "\nThis will DELETE all local game and music data and replace "
                "it with production data. Continue? [y/N] "
            )
            if confirm.lower() != "y":
                self.stdout.write("Aborted.")
                return

        # Step 1: Dump production data via heroku run. The games dump is
        # checked before the slow music one starts, and both before anything
        # local is touched
        self.stdout.write("\n1. Dumping production data...")
        json_data = self._dump(app_name, self.GAMES_DUMP)
        if json_data is None:
            return

        # Strip author references (FKs to users, which aren't synced)
        try:
            fixture_data = json.loads(json_data)
            for item in fixture_data:
                if item.get("model") in ("games.post", "games.article"):
                    item["fields"].pop("author", None)
            json_data = json.dumps(fixture_data, indent=2)
        except json.JSONDecodeError as e:
            self.stderr.write(self.style.ERROR(f"Invalid JSON from Heroku: {e}"))
            return

        self.stdout.write("   Dumping music data, cover art included...")
        music_json = self._dump(app_name, self.MUSIC_DUMP)
        if music_json is None:
            return
        # Too big to parse just to check. This catches a truncated dump before
        # the local data is cleared; anything else fails inside loaddata, and
        # the transaction around it keeps the local data
        if not music_json.rstrip().endswith("]"):
            self.stderr.write(self.style.ERROR("Music dump is incomplete"))
            return

        # Step 2: Save to temporary fixture files
        fixtures_dir = FIXTURES_DIR
        os.makedirs(fixtures_dir, exist_ok=True)
        fixture_path = os.path.join(fixtures_dir, "prod_dump.json")
        music_fixture_path = os.path.join(fixtures_dir, "prod_music_dump.json")
        try:
            with open(fixture_path, "w", encoding="utf-8") as f:
                f.write(json_data)
            with open(music_fixture_path, "w", encoding="utf-8") as f:
                f.write(music_json)
            self.stdout.write(f"   Saved fixtures to {fixtures_dir}")
            loaded = self._replace_local_data(fixture_path, music_fixture_path)
        finally:
            # Step 5: Clean up, whether or not the load worked
            if keep_fixture:
                self.stdout.write(f"   Fixtures kept in: {fixtures_dir}")
            else:
                for path in (fixture_path, music_fixture_path):
                    if os.path.exists(path):
                        os.remove(path)
                self.stdout.write("   Cleaned up fixture files")
        if not loaded:
            return

        # Success message
        self.stdout.write(self.style.SUCCESS("\nSync complete!"))
        self.stdout.write(
            "\nNote: Admin users were not synced. Create a local superuser with:"
        )
        self.stdout.write(self.style.WARNING("  python3 manage.py createsuperuser"))

    def _replace_local_data(self, fixture_path, music_fixture_path):
        """
        Steps 2 to 4: migrate, then clear and load in one transaction, so a
        load that fails part way leaves the local data as it was rather than
        empty. Returns whether the load worked.
        """
        self.stdout.write("\n2. Running migrations...")
        call_command("migrate", verbosity=0)
        self.stdout.write("   Migrations complete")

        stage = "clear local"
        try:
            with transaction.atomic():
                self.stdout.write("\n3. Clearing local data...")
                self._clear_games_data()
                self.stdout.write("   Cleared all games app data")
                self._clear_music_data()
                self.stdout.write("   Cleared all music app data")

                stage = "load"
                self.stdout.write("\n4. Loading data into local database...")
                call_command("loaddata", fixture_path, music_fixture_path, verbosity=1)
                # Inside a transaction SQLite cannot switch foreign keys off,
                # so loaddata skips its own check and a bad key would only
                # fail at COMMIT, unnamed. This names the table and row.
                stage = "check loaded"
                connection.check_constraints()
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(
                    f"Failed to {stage} data: {e}\nLocal data was left as it was."
                )
            )
            return False

        # loaddata writes production's open-ended flags verbatim; apply this
        # checkout's calls, as a migrate would
        changed = open_ended.derive_all(HLTBGameData)
        if changed:
            self.stdout.write(f"   Re-derived is_open_ended on {changed} HLTB rows")
        return True

    def _dump(self, app_name, dumpdata):
        """
        Run ``dumpdata`` on a production one-off dyno and return its JSON, or
        None after reporting why there is none.
        """
        try:
            result = subprocess.run(
                [
                    "heroku",
                    "run",
                    "--app",
                    app_name,
                    "--no-tty",
                    "--",
                    f"python manage.py {dumpdata}",
                ],
                capture_output=True,
                encoding="utf-8",
                check=True,
            )
        except subprocess.CalledProcessError as e:
            self.stderr.write(self.style.ERROR(f"Failed to dump production data: {e}"))
            self.stderr.write(e.stderr)
            return None
        except FileNotFoundError:
            self.stderr.write(
                self.style.ERROR(
                    "Heroku CLI not found. Install it: brew install heroku/brew/heroku"
                )
            )
            return None

        # Filter out heroku run noise: the JSON starts at the first line that
        # opens with "[", not at a "[" inside a warning or log line
        start = re.search(r"^\[", result.stdout, re.MULTILINE)
        if start is None:
            self.stderr.write(self.style.ERROR("No JSON data found in output"))
            self.stderr.write(f"Output: {result.stdout[:500]}")
            return None
        return result.stdout[start.start() :]

    def _clear_games_data(self):
        """Delete local games data, in an order that respects foreign keys."""
        from django.contrib.flatpages.models import FlatPage
        from django.contrib.sites.models import Site

        # First: flatpages (depends on sites)
        FlatPage.objects.all().delete()
        Site.objects.all().delete()
        # Then: user-related models (not synced, but clear any local data)
        PlayedGame.objects.all().delete()
        WantToPlayGame.objects.all().delete()
        SavedFilterSet.objects.all().delete()
        # Then: models that reference Game
        ListMembership.objects.all().delete()
        IGDBGameData.objects.all().delete()
        WikipediaGameData.objects.all().delete()
        HLTBGameData.objects.all().delete()
        # Then: List and Publication
        List.objects.all().delete()
        Publication.objects.all().delete()
        # Then: Game (references Developer, Platform, Genre, Series)
        Game.objects.all().delete()
        # Then: referenced models
        Developer.objects.all().delete()
        Series.objects.all().delete()
        WikipediaGenre.objects.all().delete()
        Platform.objects.all().delete()
        # Finally: standalone models
        Post.objects.all().delete()
        Article.objects.all().delete()
        Snippet.objects.all().delete()
        SiteMetadata.objects.all().delete()

    def _clear_music_data(self):
        """
        Delete every local music row, model by model, so a model added later
        is cleared without being listed here. Per-user rows go too, as for
        games: their album pks would not survive the load. No music model
        uses PROTECT, so the order does not matter; deleting albums cascades
        to credits and list positions.
        """
        for model in apps.get_app_config("music").get_models():
            model.objects.all().delete()

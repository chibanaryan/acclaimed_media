"""Import the game rankings from the four TSV release files."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from games import models
from games.services import post_import
from games.services.import_handler import import_batch

DEFAULT_DIR = Path(settings.BASE_DIR) / "acclaimedgames" / "test_input_files"


class Command(BaseCommand):
    help = (
        "Import game rankings from the platforms, lists, games and positions "
        "TSV files, in a single transaction, as the staff import page does. "
        "Games are recreated; tracking rows and fetched metadata are "
        "reconnected to them. Then fetches IGDB for every game (it restores "
        "their slugs) and Wikipedia and HLTB for those missing them, unless "
        "--no-metadata."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--platforms",
            default=str(DEFAULT_DIR / "PlatformDB.txt"),
            help="TSV of platform codes and names",
        )
        parser.add_argument(
            "--lists",
            default=str(DEFAULT_DIR / "SourceLists.txt"),
            help="TSV of the published source lists",
        )
        parser.add_argument(
            "--games",
            default=str(DEFAULT_DIR / "Top1400.txt"),
            help="TSV of rank/name/year/platforms/IGDB id/Wikidata id",
        )
        parser.add_argument(
            "--positions",
            default=str(DEFAULT_DIR / "GamePositions.txt"),
            help="TSV of each game's positions in the source lists",
        )
        parser.add_argument(
            "--no-metadata",
            dest="metadata",
            action="store_false",
            help=(
                "Skip the metadata fetch that otherwise follows the import. "
                "Until IGDB is fetched again every game has no slug"
            ),
        )

    def handle(self, *args, **options):
        # import_batch's own names for the files, keyed by this command's.
        fields = {
            "platforms": "platforms_file",
            "lists": "lists_file",
            "games": "games_file",
            "positions": "memberships_file",
        }
        paths = {}
        for key in fields:
            path = Path(options[key])
            if not path.is_file():
                raise CommandError(f"--{key} file not found: {path}")
            paths[key] = path

        handles = {fields[key]: path.open("rb") for key, path in paths.items()}
        try:
            ok, message = import_batch(handles)
        finally:
            for handle in handles.values():
                handle.close()
        if not ok:
            raise CommandError(message)

        self.stdout.write(self.style.SUCCESS(message))
        self.stdout.write(
            "Games: {games} | Platforms: {platforms} | Lists: {lists} | "
            "Memberships: {members}".format(
                games=models.Game.objects.count(),
                platforms=models.Platform.objects.count(),
                lists=models.List.objects.count(),
                members=models.ListMembership.objects.count(),
            )
        )

        # In the foreground, unlike the staff page's thread: whoever ran the
        # import is watching, and a one-off dyno has no requests to serve.
        if options["metadata"]:
            post_import.run_in_foreground(self)

"""Import the album rankings from the four TSV release files."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core import constants as core_constants
from music import models
from music.services import import_handler

DEFAULT_DIR = Path(settings.BASE_DIR) / "acclaimedgames" / "test_input_files" / "music"


class Command(BaseCommand):
    help = (
        "Import album rankings from the artists, lists, albums and positions "
        "TSV files. "
        "Replaces all existing music ranking data in a single transaction."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--artists",
            default=str(DEFAULT_DIR / "ArtistInfo.txt"),
            help="TSV of id/name/tags/wikidata_id, one artist per row",
        )
        parser.add_argument(
            "--lists",
            default=str(DEFAULT_DIR / "ListData.txt"),
            help="TSV of publisher/year/name/url, one published list per row",
        )
        parser.add_argument(
            "--albums",
            default=str(DEFAULT_DIR / "WebRankings.txt"),
            help="TSV of rank/name/artist_ids/year/wikidata_ids, in rank order",
        )
        parser.add_argument(
            "--positions",
            default=str(DEFAULT_DIR / "ListPositions.txt"),
            help="TSV of listIndex:position pairs, one row per album",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the inferred list types and parsed counts, then stop",
        )

    def handle(self, *args, **options):
        paths = {}
        for key in ("artists", "lists", "albums", "positions"):
            path = Path(options[key])
            if not path.is_file():
                raise CommandError(f"--{key} file not found: {path}")
            paths[key] = path

        if options["dry_run"]:
            self._report_dry_run(paths)
            return

        with (
            paths["artists"].open(encoding="utf-8-sig", newline="") as artists_file,
            paths["lists"].open(encoding="utf-8-sig", newline="") as lists_file,
            paths["albums"].open(encoding="utf-8-sig", newline="") as albums_file,
            paths["positions"].open(encoding="utf-8-sig") as positions_file,
        ):
            _, message = import_handler.import_batch(
                lists_file, albums_file, positions_file, artists_file
            )

        self._print_inferred_types()
        self.stdout.write(self.style.SUCCESS(message))
        self.stdout.write(
            "Albums: {albums} | Artists: {artists} ({relations} relations) | "
            "Lists: {lists} | Publications: {pubs} | "
            "Memberships: {members}".format(
                albums=models.Album.objects.count(),
                artists=models.Artist.objects.count(),
                relations=models.ArtistRelation.objects.count(),
                lists=models.MusicList.objects.count(),
                pubs=models.MusicPublication.objects.count(),
                members=models.AlbumListMembership.objects.count(),
            )
        )

    def _report_dry_run(self, paths):
        """Show what would be imported without touching the database."""
        with paths["artists"].open(encoding="utf-8-sig", newline="") as f:
            artists = import_handler.parse_artists_file(f)
        tagged = [row for row in artists if row[2]]
        self.stdout.write(
            f"Artists file: {len(artists)} artists, {len(tagged)} with relations"
        )
        for source_id, name, tags, _ in tagged:
            described = ", ".join(f"{kind}:{target}" for kind, target in tags)
            self.stdout.write(f"  {source_id:>5} {name} [{described}]")

        with paths["lists"].open(encoding="utf-8-sig", newline="") as f:
            rows = [line.rstrip("\r\n").split("\t") for line in f if line.strip()]
        self.stdout.write(f"Lists file: {len(rows)} rows")
        for row in rows:
            list_type = import_handler.infer_list_type(row[2])
            label = core_constants.get_list_type_label(list_type)
            self.stdout.write(f"  {list_type} {label:<14} {row[0]} {row[1]} - {row[2]}")

        with paths["albums"].open(encoding="utf-8-sig", newline="") as f:
            album_rows = sum(1 for line in f if line.strip())
        with paths["positions"].open(encoding="utf-8-sig") as f:
            position_rows = sum(1 for line in f if line.strip())
        self.stdout.write(f"Albums file: {album_rows} rows")
        self.stdout.write(f"Positions file: {position_rows} rows")
        if album_rows != position_rows:
            self.stdout.write(
                self.style.WARNING(
                    "Albums and positions row counts differ; the positions "
                    "file must have one row per album, in rank order."
                )
            )

    def _print_inferred_types(self):
        """Summarize the stored list types so a bad inference is visible."""
        self.stdout.write("Inferred list types:")
        for code, label in core_constants.LIST_TYPES:
            count = models.MusicList.objects.filter(type=code).count()
            if count:
                self.stdout.write(f"  {label}: {count}")

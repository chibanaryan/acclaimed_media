"""Import the album rankings from the four TSV release files."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core import constants as core_constants
from music import models
from music.services import import_handler, post_import

DEFAULT_DIR = Path(settings.BASE_DIR) / "acclaimedgames" / "test_input_files" / "music"


class Command(BaseCommand):
    help = (
        "Import album rankings from the artists, lists, albums and positions "
        "TSV files, in a single transaction. Albums are matched to the ones "
        "already stored by Wikidata id and updated in place; lists and list "
        "positions are replaced. Then fetches the metadata the release left "
        "missing, unless --no-metadata."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--artists",
            default=str(DEFAULT_DIR / "ArtistInfo.txt"),
            help="TSV of id/wikidata_ids/name/variants..., one artist per row",
        )
        parser.add_argument(
            "--lists",
            default=str(DEFAULT_DIR / "ListData.txt"),
            help="TSV of publisher/year/type/name/url, one published list per row",
        )
        parser.add_argument(
            "--albums",
            default=str(DEFAULT_DIR / "WebRankings.txt"),
            help="TSV of rank/name/credits/year/wikidata_ids, in rank order",
        )
        parser.add_argument(
            "--positions",
            default=str(DEFAULT_DIR / "ListPositions.txt"),
            help="TSV of listIndex:position pairs, one row per album",
        )
        parser.add_argument(
            "--no-metadata",
            dest="metadata",
            action="store_false",
            help=(
                "Skip the metadata fetch that otherwise follows the import "
                "(fetch_album_metadata --with-musicbrainz)"
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Report the list types and which albums would be kept, "
                "added and removed, then stop"
            ),
        )

    def handle(self, *args, **options):
        paths = {}
        for key in ("artists", "lists", "albums", "positions"):
            path = Path(options[key])
            if not path.is_file():
                raise CommandError(f"--{key} file not found: {path}")
            paths[key] = path

        # A file the importer refuses is a ValueError written to be read, as
        # the staff page shows it: the message, not a traceback. Only the
        # lists file's was caught, and only in a dry run, until 2026-11-10.
        try:
            if options["dry_run"]:
                self._report_dry_run(paths)
                return
            message, warnings = self._import(paths)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self._print_list_types()
        self.stdout.write(self.style.SUCCESS(message))
        for warning in warnings:
            self.stdout.write(self.style.WARNING(warning))
        self.stdout.write(
            "Albums: {albums} | Artists: {artists} ({credits} credits) | "
            "Lists: {lists} | Publications: {pubs} | "
            "Memberships: {members}".format(
                albums=models.Album.objects.count(),
                artists=models.Artist.objects.count(),
                credits=models.AlbumCredit.objects.count(),
                lists=models.MusicList.objects.count(),
                pubs=models.MusicPublication.objects.count(),
                members=models.AlbumListMembership.objects.count(),
            )
        )

        # In the foreground, unlike the staff page's thread: whoever ran the
        # import is watching, and a one-off dyno has no requests to serve.
        if options["metadata"]:
            post_import.run_in_foreground(self)

    def _import(self, paths):
        with (
            paths["artists"].open(encoding="utf-8-sig", newline="") as artists_file,
            paths["lists"].open(encoding="utf-8-sig", newline="") as lists_file,
            paths["albums"].open(encoding="utf-8-sig", newline="") as albums_file,
            paths["positions"].open(encoding="utf-8-sig") as positions_file,
        ):
            return import_handler.import_batch(
                lists_file, albums_file, positions_file, artists_file
            )

    def _report_dry_run(self, paths):
        """Show what would be imported without touching the database."""
        with paths["artists"].open(encoding="utf-8-sig", newline="") as f:
            artists = import_handler.parse_artists_file(f)
        varied = [row for row in artists if len(row.names) > 1]
        self.stdout.write(
            f"Artists file: {len(artists)} artists, {len(varied)} with name variants"
        )
        for row in varied:
            variants = " | ".join(
                f"{index}: {name}" for index, name in enumerate(row.names)
            )
            self.stdout.write(f"  {row.source_id:>5} {variants}")
        for source_id, old, new in import_handler.suspected_reuses(artists):
            self.stdout.write(
                self.style.WARNING(
                    f"  ! {source_id} was {old!r}, now {new!r}: no shared "
                    "Wikidata id or name - a reused id?"
                )
            )
        slugs = import_handler.plan_import_slugs(artists)
        # Rows without a provider id are left out: the import adopts what it
        # can of them by Wikidata id or name, so they are not known losses.
        stored = models.Artist.objects.filter(source_id__isnull=False).order_by(
            "source_id"
        )
        for artist in stored:
            slug = slugs.get(artist.source_id)
            if slug is None:
                self.stdout.write(f"  - {artist.source_id} {artist.name} (removed)")
            elif artist.slug != slug:
                self.stdout.write(
                    f"  ~ {artist.source_id} slug {artist.slug} -> {slug}"
                )

        with paths["lists"].open(encoding="utf-8-sig", newline="") as f:
            lists = import_handler.parse_lists_file(f)
        self.stdout.write(f"Lists file: {len(lists)} rows")
        for row in lists:
            label = core_constants.get_list_type_label(row.type)
            self.stdout.write(
                f"  {row.type} {label:<14} {row.publisher} {row.year} - {row.name}"
            )

        with paths["albums"].open(encoding="utf-8-sig", newline="") as f:
            albums = import_handler.parse_albums_file(f)
        errors = import_handler.credit_errors(
            albums, {row.source_id: row.names for row in artists}
        )
        for error in errors:
            self.stdout.write(self.style.ERROR(f"  ! {error}"))
        match = import_handler.match_albums(albums, list(models.Album.objects.all()))
        self.stdout.write(
            f"Albums file: {len(albums)} rows - {len(match.kept)} kept, "
            f"{len(match.added)} added, {len(match.removed)} removed"
        )
        for row in match.added:
            qids = ", ".join(row.wikidata_ids) or "no Wikidata id"
            self.stdout.write(f"  + {row.rank:>5} {row.name} [{qids}]")
        for album in match.removed:
            qids = ", ".join(album.wikidata_qids) or "no Wikidata id"
            self.stdout.write(f"  - {album.rank:>5} {album.name} [{qids}]")
        # Kept by artists, title and year, not by id: their tracking rows
        # follow, so a wrong pairing is worth catching here.
        for row, album in match.by_identity:
            qids = ", ".join(row.wikidata_ids) or "no Wikidata id"
            self.stdout.write(
                f"  = {row.rank:>5} {row.name} [{qids}] keeps #{album.rank} by title"
            )

        with paths["positions"].open(encoding="utf-8-sig") as f:
            position_rows = sum(1 for line in f if line.strip())
        self.stdout.write(f"Positions file: {position_rows} rows")
        if len(albums) != position_rows:
            self.stdout.write(
                self.style.WARNING(
                    "Albums and positions row counts differ; the positions "
                    "file must have one row per album, in rank order."
                )
            )

    def _print_list_types(self):
        """Summarize the stored list types, as a check on the type column."""
        self.stdout.write("List types:")
        for code, label in core_constants.LIST_TYPES:
            count = models.MusicList.objects.filter(type=code).count()
            if count:
                self.stdout.write(f"  {label}: {count}")

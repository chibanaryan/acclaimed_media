"""
Rebuild every album's genres from the stored Discogs, Wikidata and
MusicBrainz metadata. No HTTP requests, so it takes seconds.

    python manage.py rebuild_album_genres --dry-run --report   # what would change
    python manage.py rebuild_album_genres                       # apply it

``fetch_album_metadata`` runs this at the end of its passes. Run it by hand
after changing the vocabulary in ``music/services/genre_normalizer.py``, and
use ``--report`` to see the labels it does not classify yet.
"""

from django.core.management.base import BaseCommand

from music.services import genre_normalizer as gn
from music.services.genre_rebuild import rebuild_album_genres


class Command(BaseCommand):
    help = "Rebuild album genres from stored metadata (no network)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change, change nothing",
        )
        parser.add_argument(
            "--report",
            action="store_true",
            help="List every changed album, pruned leaf and unclassified label",
        )

    def handle(self, *args, **options):
        report = rebuild_album_genres(dry_run=options["dry_run"])
        write_report(self, report, verbose=options["report"])
        if report.dry_run:
            self.stdout.write(self.style.WARNING("Dry run: nothing was changed."))


def write_report(command, report, verbose=False):
    """Print a rebuild report; shared with ``fetch_album_metadata``."""
    out = command.stdout
    style = command.style

    out.write(style.MIGRATE_HEADING("Album genres"))
    out.write(f"  {report.summary()}")
    out.write(
        f"  {report.genres_per_album:.2f} genres per album, "
        f"{report.albums_without_genres} album(s) with none"
    )
    if report.renamed:
        out.write(
            "  Renamed: " + ", ".join(f"{old} -> {new}" for old, new in report.renamed)
        )
    if report.deleted:
        out.write(f"  Deleted {len(report.deleted)} unused genre row(s)")
    if report.saved_filters_remapped:
        out.write(f"  Remapped {report.saved_filters_remapped} saved filter(s)")
    if report.unclassified:
        out.write(
            style.WARNING(
                f"  {len(report.unclassified)} label(s) the vocabulary does not "
                "classify yet (use --report to list them)"
            )
        )

    if not verbose:
        return

    if report.pruned:
        out.write(
            style.MIGRATE_HEADING(
                f"\nPruned leaves (fewer than {gn.MIN_LEAF_ALBUMS} albums)"
            )
        )
        out.write(
            "  "
            + ", ".join(
                f"{name} ({count})" for name, count in sorted(report.pruned.items())
            )
        )

    if report.unclassified:
        out.write(style.MIGRATE_HEADING("\nUnclassified labels"))
        for (source, label), count in report.unclassified.most_common():
            out.write(f"  {count:4d}  {source}: {label}")

    if report.changed:
        out.write(style.MIGRATE_HEADING("\nChanged albums"))
        for name, before, after in report.changed.values():
            removed = [genre for genre in before if genre not in after]
            added = [genre for genre in after if genre not in before]
            parts = []
            if removed:
                parts.append("- " + ", ".join(removed))
            if added:
                parts.append("+ " + ", ".join(added))
            out.write(f"  {name}: {'  '.join(parts)}")

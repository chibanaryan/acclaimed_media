"""
Fetch album metadata from Wikidata, the Cover Art Archive, Discogs and
MusicBrainz.

The passes are selectable because their costs differ enormously: the
Wikidata pass is about 25 batched requests, while Discogs is one request per
album at 25/minute on the anonymous tier. Set ``DISCOGS_TOKEN`` to raise
that; the client paces itself from the response headers either way.

    python manage.py fetch_album_metadata                   # all but MusicBrainz
    python manage.py fetch_album_metadata --wikidata-only
    python manage.py fetch_album_metadata --covers-only
    python manage.py fetch_album_metadata --discogs-only
    python manage.py fetch_album_metadata --musicbrainz
    python manage.py fetch_album_metadata --slug pet-sounds --force

Genres are rebuilt from the stored data at the end of any run that included
the Wikidata, Discogs or MusicBrainz pass; ``rebuild_album_genres`` does the
same thing on its own, with no network.
"""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from music import views as music_views
from music.management.commands.rebuild_album_genres import write_report
from music.models import Album
from music.services.genre_rebuild import rebuild_album_genres
from music.services.metadata_service import AlbumMetadataService

logger = logging.getLogger(__name__)

#: The passes that store something genres are derived from.
GENRE_SOURCE_PASSES = frozenset({"wikidata", "discogs", "musicbrainz"})


class Command(BaseCommand):
    help = "Fetch album metadata (Wikidata, cover art, Discogs, MusicBrainz)."

    def add_arguments(self, parser):
        parser.add_argument("--album", type=str, help="One album by name")
        parser.add_argument("--slug", type=str, help="One album by slug")
        parser.add_argument("--id", type=int, help="One album by primary key")
        parser.add_argument("--limit", type=int, help="Process at most N albums")
        parser.add_argument("--offset", type=int, default=0, help="Skip N albums")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-fetch albums that already have data",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Only albums with no Wikidata record yet (the default selection)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be fetched, change nothing",
        )
        parser.add_argument(
            "--wikidata-only", action="store_true", help="Run only the Wikidata pass"
        )
        parser.add_argument(
            "--covers-only", action="store_true", help="Run only the cover-art pass"
        )
        parser.add_argument(
            "--discogs-only", action="store_true", help="Run only the Discogs pass"
        )
        parser.add_argument(
            "--musicbrainz",
            action="store_true",
            help="Run the MusicBrainz enrichment pass (1 req/sec, ~9 min)",
        )

    def handle(self, *args, **options):
        albums = self._get_albums(options)
        if not albums:
            self.stdout.write(self.style.WARNING("No albums matched."))
            return

        passes = self._selected_passes(options)
        self._print_header(albums, passes, options)

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: nothing was changed."))
            return

        service = AlbumMetadataService(
            progress_callback=self._on_progress, force=options["force"]
        )
        runners = {
            "wikidata": service.run_wikidata,
            "covers": service.run_covers,
            "discogs": service.run_discogs,
            "musicbrainz": service.run_musicbrainz,
        }

        start = time.time()
        results = []
        for name in passes:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{name} pass"))
            # Re-read the albums so each pass sees what the last one wrote.
            fresh = list(Album.objects.filter(pk__in=[a.pk for a in albums]))
            result = runners[name](fresh)
            results.append(result)
            self.stdout.write(f"  {result.summary()}")
            for message in result.errors[:10]:
                self.stdout.write(self.style.ERROR(f"    {message}"))
            if len(result.errors) > 10:
                self.stdout.write(
                    self.style.ERROR(f"    ... and {len(result.errors) - 10} more")
                )

        # Genres are derived from what the passes stored, across the whole
        # corpus - rare leaves are pruned by count - so they are rebuilt once
        # here rather than album by album, and for every album even when only
        # one was fetched.
        if GENRE_SOURCE_PASSES.intersection(passes):
            self.stdout.write("")
            write_report(self, rebuild_album_genres())

        music_views._invalidate_music_caches()
        self._print_summary(results, time.time() - start)

    # ------------------------------------------------------------- selection

    def _get_albums(self, options):
        """The albums to process, honouring the single-record selectors."""
        if options["album"]:
            return list(Album.objects.filter(name__iexact=options["album"]))
        if options["slug"]:
            return list(Album.objects.filter(slug=options["slug"]))
        if options["id"]:
            return list(Album.objects.filter(pk=options["id"]))

        queryset = Album.objects.all().order_by("rank")
        if options["skip_existing"] and not options["force"]:
            queryset = queryset.filter(primary_wikipedia_album_data__isnull=True)

        albums = list(queryset[options["offset"] :])
        if options["limit"]:
            albums = albums[: options["limit"]]
        return albums

    @staticmethod
    def _selected_passes(options):
        """Which passes to run, in dependency order.

        Wikidata comes first because it is what supplies the MusicBrainz and
        Discogs identifiers the other passes are keyed by.
        """
        explicit = [
            name
            for name, flag in (
                ("wikidata", options["wikidata_only"]),
                ("covers", options["covers_only"]),
                ("discogs", options["discogs_only"]),
                ("musicbrainz", options["musicbrainz"]),
            )
            if flag
        ]
        if explicit:
            return explicit
        # The default omits MusicBrainz: it is enrichment, and its 1 req/sec
        # cap would triple the runtime of a routine refresh.
        return ["wikidata", "covers", "discogs"]

    # --------------------------------------------------------------- output

    def _print_header(self, albums, passes, options):
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"Fetching metadata for {len(albums)} album(s)")
        )
        self.stdout.write(f"  Passes: {', '.join(passes)}")
        if options["force"]:
            self.stdout.write("  Force: re-fetching records that already have data")
        if "discogs" in passes:
            if settings.DISCOGS_TOKEN:
                self.stdout.write(
                    self.style.SUCCESS("  ✓ Discogs token set (faster rate limit)")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "  ⚠ No DISCOGS_TOKEN: the anonymous tier allows 25 "
                        "requests/minute, so this pass takes roughly "
                        f"{len(albums) * 2.76 / 60:.0f} minutes"
                    )
                )

    def _on_progress(self, event_type, data):
        if event_type == "progress" and data["current"] % 25 == 0:
            self.stdout.write(f"  [{data['current']}/{data['total']}] {data['name']}")

    def _print_summary(self, results, elapsed):
        self.stdout.write(self.style.MIGRATE_HEADING("\nSummary"))
        for result in results:
            self.stdout.write(f"  {result.summary()}")
        self.stdout.write(self.style.SUCCESS(f"  Finished in {elapsed:.1f}s"))

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
    python manage.py fetch_album_metadata --with-musicbrainz  # all four passes
    python manage.py fetch_album_metadata --musicbrainz --refresh-stale 125

Heroku Scheduler runs it daily as
``--weekly --with-musicbrainz --refresh-stale 125``; ``--weekly`` exits at
once on any day but Sunday, as ``refresh_all_metadata``'s does. Without
``--force`` the cover, Discogs and MusicBrainz passes skip records that
already landed, so a routine run only fills what an import left missing -
plus, with ``--refresh-stale N``, a re-fetch of the N albums whose
MusicBrainz data is oldest, which cycles the 1000-album corpus every eight
weeks for about two minutes a run.

Genres are rebuilt from the stored data at the end of any run that included
the Wikidata, Discogs or MusicBrainz pass; ``rebuild_album_genres`` does the
same thing on its own, with no network. Release dates, which order a year's
albums in the year sort, are re-derived after any Wikidata or MusicBrainz pass.
"""

import logging
import time
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from core.services.monitoring import weekly_job_monitor
from music.management.commands.rebuild_album_genres import write_report
from music.models import Album
from music.services import caching
from music.services.artist_slugs import rebuild_artist_slugs
from music.services.genre_rebuild import rebuild_album_genres
from music.services.release_dates import refresh_release_dates
from music.services.metadata_service import AlbumMetadataService

logger = logging.getLogger(__name__)

#: The passes that store something genres are derived from.
GENRE_SOURCE_PASSES = frozenset({"wikidata", "discogs", "musicbrainz"})
# The passes that store a release date: Wikidata P577, MusicBrainz first release.
DATE_SOURCE_PASSES = frozenset({"wikidata", "musicbrainz"})


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
            help="Only albums with no Wikidata record yet",
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
            help="Run only the MusicBrainz enrichment pass (1 req/sec, ~17 min)",
        )
        parser.add_argument(
            "--with-musicbrainz",
            action="store_true",
            help="Add the MusicBrainz pass to the passes that would otherwise run",
        )
        parser.add_argument(
            "--refresh-stale",
            type=int,
            default=0,
            metavar="N",
            help=(
                "In the MusicBrainz pass, also re-fetch the N albums whose "
                "MusicBrainz data is oldest (1 req/sec each)"
            ),
        )
        parser.add_argument(
            "--weekly",
            action="store_true",
            help=(
                "Only run on Sundays (for daily Heroku Scheduler jobs). "
                "Exits silently on other days."
            ),
        )

    def handle(self, *args, **options):
        # 6 = Sunday in Python's weekday() (0=Monday, 6=Sunday)
        if options["weekly"] and datetime.now().weekday() != 6:
            self.stdout.write(
                f"Skipping: Today is {datetime.now().strftime('%A')} "
                "(weekly mode only runs on Sunday)"
            )
            return

        with weekly_job_monitor(
            "fetch-album-metadata", enabled=options.get("weekly"), max_runtime=120
        ):
            self._run(options)

    def _run(self, options):
        """Everything after the weekly gate, inside the cron check-in."""
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
            progress_callback=self._on_progress,
            force=options["force"],
            refresh_stale=options["refresh_stale"],
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

        # Corpus-wide for the same reason, and one query: see release_dates.
        if DATE_SOURCE_PASSES.intersection(passes):
            changed = refresh_release_dates()
            self.stdout.write(f"Release dates: {changed} updated")

        # New artists get their Wikipedia titles in that pass, and a title is
        # what tells same-named artists' slugs apart.
        if "wikidata" in passes:
            for source_id, old, new in rebuild_artist_slugs():
                self.stdout.write(f"Artist {source_id} slug: {old} -> {new}")

        if not caching.invalidate_music_caches():
            self.stdout.write(self.style.WARNING(caching.CACHES_NOT_CLEARED))
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
        # The default omits MusicBrainz: it is enrichment, and its 1 req/sec
        # cap would triple the runtime of a full refresh. A routine one skips
        # what already landed, which is why the scheduled job can afford it.
        passes = explicit or ["wikidata", "covers", "discogs"]
        if options["with_musicbrainz"] and "musicbrainz" not in passes:
            passes.append("musicbrainz")
        return passes

    # --------------------------------------------------------------- output

    def _print_header(self, albums, passes, options):
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"Fetching metadata for {len(albums)} album(s)")
        )
        self.stdout.write(f"  Passes: {', '.join(passes)}")
        if options["force"]:
            self.stdout.write("  Force: re-fetching records that already have data")
        elif options["refresh_stale"] and "musicbrainz" in passes:
            self.stdout.write(
                f"  Refreshing the {options['refresh_stale']} oldest MusicBrainz "
                "records"
            )
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

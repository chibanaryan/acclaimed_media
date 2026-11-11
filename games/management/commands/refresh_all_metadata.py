"""
Management command to refresh all metadata (IGDB + Wikipedia + HLTB) for games.

This command combines IGDB, Wikipedia, and HLTB data refreshes into one
unified operation, designed for weekly scheduled execution via Heroku Scheduler.

It performs:
1. IGDB data refresh (cover art, descriptions, studios, genres)
2. Wikipedia page lookup + genre scraping
3. HowLongToBeat playtime data

All operations force-refresh games regardless of existing data.
"""

import asyncio
import logging
import time
from datetime import datetime

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Case, IntegerField, Value, When

from core.services.monitoring import skips_today, weekly_job_monitor
from games import config
from games.models import Game, WikipediaGameData
from games.services import hltb_matching, post_import
from games.services.genre_normalizer import (
    canonicalize_genre_payload,
    get_or_create_genre,
)
from games.services.igdb_importer import IGDBImportService

logger = logging.getLogger(__name__)

# One request to Wikidata or Wikipedia may take this long. aiohttp's own
# default is five minutes, and one stalled page held a slot for all of it.
WIKI_REQUEST_TIMEOUT = 30


def wikidata_credentials(token):
    """A Wikimedia BotPassword, ``user@bot:password``, as ``(login,
    password)`` for HTTP basic auth, or None when there is none to send.

    The async Wikipedia refresh paces itself by whether it is
    authenticated. Until 2026-11-10 it took the faster pace for any token
    and then sent none, so the weekly job ran at four times the
    unauthenticated rate on unauthenticated requests.
    """
    if not token or ":" not in token:
        return None
    login, password = token.split(":", 1)
    if not login or not password:
        return None
    return (login, password)


class Command(BaseCommand):
    help = (
        "Weekly metadata refresh - force update IGDB, Wikipedia, and HLTB "
        "data for all games. Designed for Heroku Scheduler execution."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_time = None
        self.igdb_start_time = None
        self.wikipedia_start_time = None
        self.hltb_start_time = None

        # Statistics
        self.igdb_processed = 0
        self.igdb_errors = 0
        self.wikipedia_pages_found = 0
        self.wikipedia_pages_failed = 0
        self.genres_scraped = 0
        self.genres_failed = 0
        self.hltb_found = 0
        self.hltb_not_found = 0

    def add_arguments(self, parser):
        parser.add_argument(
            "--igdb-only",
            action="store_true",
            help="Only refresh IGDB data (skip Wikipedia and HLTB)",
        )
        parser.add_argument(
            "--wikipedia-only",
            action="store_true",
            help="Only refresh Wikipedia data (skip IGDB and HLTB)",
        )
        parser.add_argument(
            "--hltb-only",
            action="store_true",
            help="Only refresh HLTB data (skip IGDB and Wikipedia)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit number of games to process (for testing)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview operations without making database changes",
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=8,
            help="Number of concurrent IGDB requests (default: 8, max: 8)",
        )
        parser.add_argument(
            "--pro",
            action="store_true",
            help="Use IGDB Pro tier (3000 req/sec vs 4 req/sec)",
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
        """Main command handler - orchestrates IGDB and Wikipedia refreshes."""
        self.start_time = time.time()

        exclusive_flags = [
            options.get("igdb_only"),
            options.get("wikipedia_only"),
            options.get("hltb_only"),
        ]
        if sum(bool(f) for f in exclusive_flags) > 1:
            raise CommandError("Cannot use multiple --*-only flags together")

        if options.get("weekly") and skips_today(self):
            return

        with weekly_job_monitor(
            "refresh-all-metadata", enabled=options.get("weekly"), max_runtime=180
        ):
            if options.get("weekly"):
                # Never beside an import's fetch, or the rate limit is shared
                post_import.run_weekly(self, lambda: self._run(options))
            else:
                self._run(options)

            # A phase that failed outright fails the command, here: inside
            # the cron check-in, which reports a run only if it raises, and
            # after the lock is let go, so a fetch an import is owed still
            # runs. Each phase catches its own error so the others go on,
            # and until this the job exited 0 with all three FAILED, which
            # Sentry's monitor read as a good Sunday.
            failed = self._failed_phases()
            if failed:
                raise CommandError(
                    f"Metadata refresh failed outright for: {', '.join(failed)}"
                )

    def _failed_phases(self):
        """The phases that could not run at all, by name."""
        flags = (
            ("IGDB", self.igdb_errors),
            ("Wikipedia", self.wikipedia_pages_failed),
            ("HLTB", self.hltb_not_found),
        )
        return [name for name, flag in flags if flag == -1]

    def _run(self, options):
        """Everything after the weekly gate, inside the cron check-in."""
        # Print header
        self._print_header(options)

        # [1/3] IGDB Refresh
        if not options.get("wikipedia_only") and not options.get("hltb_only"):
            try:
                self._refresh_igdb(options)
            except Exception as e:
                logger.exception("IGDB refresh failed")
                self.stdout.write(self.style.ERROR(f"\n  IGDB refresh failed: {e}"))
                self.igdb_errors = -1  # Flag for total failure

        # [2/3] Wikipedia Refresh (now with asyncio concurrency)
        if not options.get("igdb_only") and not options.get("hltb_only"):
            try:
                # Prepare games data before async context (avoid ORM in async)
                # Prioritize games without Wikipedia metadata first
                games_qs = (
                    Game.objects.all()
                    .annotate(
                        has_metadata=Case(
                            When(
                                primary_wikipedia_game_data__isnull=False, then=Value(1)
                            ),
                            default=Value(0),
                            output_field=IntegerField(),
                        )
                    )
                    .order_by("has_metadata", "rank")
                )
                if options.get("limit"):
                    games_qs = games_qs[: options["limit"]]

                games_list = []
                for game in games_qs:
                    games_list.append(
                        {
                            "id": game.id,
                            "name": game.name,
                            "wikidata_id": game.wikidata_id,
                            "year_of_release": game.year_of_release,
                        }
                    )

                # Run async handler with pre-fetched data
                asyncio.run(self._refresh_wikipedia_async(games_list, options))
            except Exception as e:
                logger.exception("Wikipedia refresh failed")
                self.stdout.write(
                    self.style.ERROR(f"\n  Wikipedia refresh failed: {e}")
                )
                self.wikipedia_pages_failed = -1  # Flag for total failure

        # [3/3] HLTB Refresh
        run_hltb = not options.get("igdb_only") and not options.get("wikipedia_only")

        if run_hltb:
            try:
                # Prepare HLTB games data before async context
                # Prioritize games without HLTB metadata first
                hltb_games_list = []
                games_qs = (
                    Game.objects.prefetch_related("platforms")
                    .select_related("primary_wikipedia_game_data")
                    .annotate(
                        has_metadata=Case(
                            When(primary_hltb_game_data__isnull=False, then=Value(1)),
                            default=Value(0),
                            output_field=IntegerField(),
                        )
                    )
                    .order_by("has_metadata", "rank")
                )
                if options.get("limit"):
                    games_qs = games_qs[: options["limit"]]

                for game in games_qs:
                    # From the prefetch: `values_list` here was a query a game
                    platform_names = [p.name for p in game.platforms.all()]
                    hltb_games_list.append(
                        {
                            "id": game.id,
                            "name": game.name,
                            "rank": game.rank,
                            "year_of_release": game.year_of_release,
                            "igdb_id": game.igdb_id,
                            "platforms": platform_names,
                            "primary_wikipedia_game_data__hltb_id": (
                                game.primary_wikipedia_game_data.hltb_id
                                if game.primary_wikipedia_game_data
                                else None
                            ),
                            "primary_wikipedia_game_data__page_title": (
                                game.primary_wikipedia_game_data.page_title
                                if game.primary_wikipedia_game_data
                                else None
                            ),
                        }
                    )

                # Run HLTB refresh
                asyncio.run(self._refresh_hltb_async(hltb_games_list, options))
            except Exception as e:
                logger.exception("HLTB refresh failed")
                self.stdout.write(self.style.ERROR(f"\n  HLTB refresh failed: {e}"))
                self.hltb_not_found = -1

        # Print summary
        self._print_summary()

    def _print_header(self, options):
        """Print command execution header."""
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("Weekly Metadata Refresh"))
        self.stdout.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")

        if options.get("dry_run"):
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No database changes will be made")
            )

        if options.get("limit"):
            self.stdout.write(f"Limiting to first {options['limit']} games")

        self.stdout.write("=" * 70)

    def _refresh_igdb(self, options):
        """Refresh IGDB data for all games using IGDBImportService."""
        self.stdout.write("\n[1/3] Refreshing IGDB Data")
        self.stdout.write("-" * 40)

        self.igdb_start_time = time.time()

        # Initialize service with progress callback
        try:
            service = IGDBImportService(
                concurrency=options.get("concurrency", 8),
                batch_size=None,  # Auto-detect from tier
                use_pro_tier=options.get("pro"),
                progress_callback=self._igdb_progress_callback,
            )
        except RuntimeError as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to initialize IGDB service: {e}")
            )
            # Flagged as a failed phase. Left at 0 errors, the summary had
            # no IGDB line at all for a refresh that never started.
            self.igdb_errors = -1
            return

        # Show tier and mode info
        tier_name = "Pro" if service.api_client.use_pro_tier else "Free"
        self.stdout.write(f"Using IGDB {tier_name} tier")

        mode_desc = []
        if service.batch_size > 0:
            mode_desc.append(f"batch_games={service.batch_size}")
        if service.concurrency > 1:
            mode_desc.append(f"concurrency={service.concurrency}")

        # Get games to process (all with IGDB IDs)
        # Prioritize games without IGDB metadata first
        games = (
            Game.objects.exclude(igdb_id__isnull=True)
            .annotate(
                has_metadata=Case(
                    When(primary_igdb_game_data__isnull=False, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
            .order_by("has_metadata", "rank")
        )

        if options.get("limit"):
            games = games[: options["limit"]]

        total_games = games.count()

        if total_games == 0:
            self.stdout.write(self.style.WARNING("No games with IGDB IDs found"))
            return

        self.stdout.write(f"Processing {total_games} games ({', '.join(mode_desc)})")

        if options.get("dry_run"):
            self.stdout.write(
                self.style.WARNING("  DRY RUN: Would process IGDB data for games")
            )
            return

        # Run the import
        service.import_games(games)

    def _igdb_progress_callback(self, event_type: str, data: dict) -> None:
        """Handle IGDB service progress events."""
        if event_type == "progress":
            current = data.get("current", 0)
            total = data.get("total", 0)

            # Checkpoint every 100 games (less verbose than default 50)
            if current % 100 == 0:
                elapsed = time.time() - self.igdb_start_time
                rate = current / elapsed if elapsed > 0 else 0
                self.stdout.write(f"  [{current}/{total}] ({rate:.1f} games/sec)")

        elif event_type == "error":
            self.igdb_errors += 1
            game_name = data.get("game_name", "Unknown")
            message = data.get("message", "Unknown error")
            logger.warning("IGDB error for %s: %s", game_name, message)

        elif event_type == "complete":
            self.igdb_processed = data.get("processed", 0)
            self.igdb_errors = data.get("errors", 0)
            elapsed = data.get("elapsed_seconds", 0)

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n  IGDB Complete: {self.igdb_processed} processed, "
                    f"{self.igdb_errors} errors in {elapsed:.0f}s"
                )
            )

    async def _refresh_wikipedia_async(self, games_list, options):
        """
        Refresh Wikipedia data for all games using asyncio concurrency.

        Uses aiohttp for concurrent HTTP requests to Wikidata/Wikipedia APIs.
        This provides 3-5x speedup over sequential processing.
        """
        import aiohttp
        import urllib.parse
        from bs4 import BeautifulSoup

        self.stdout.write("\n[2/3] Refreshing Wikipedia Data (async)")
        self.stdout.write("-" * 40)

        self.wikipedia_start_time = time.time()

        # Determine delay and concurrency based on authentication
        # Rate limits: Auth=5000 req/hr (1.39/sec), Unauth=500 req/hr (0.14/sec)
        # Each game makes 2 requests (Wikidata + Wikipedia scrape)
        # Formula: concurrency / (http_time + delay) < rate_limit
        credentials = wikidata_credentials(settings.WIKIDATA_ACCESS_TOKEN)
        wikidata_auth = aiohttp.BasicAuth(*credentials) if credentials else None
        if wikidata_auth:
            delay = 1.5  # With 2 concurrent: 2/(0.5+1.5) = 1 req/sec < 1.39 limit
            concurrency = 2
            self.stdout.write(
                f"Using authenticated Wikidata requests "
                f"({delay}s delay, {concurrency} concurrent)"
            )
        else:
            # With 1 concurrent: 1/(0.5+4.0) = 0.22 req/sec.
            # Accounting for 2 requests/game => ~0.11 req/sec.
            delay = 4.0
            concurrency = 1  # Sequential to stay well under 0.14/sec limit
            self.stdout.write(
                self.style.WARNING(
                    f"Using unauthenticated Wikidata requests "
                    f"({delay}s delay, sequential)\n"
                    "  Set WIKIDATA_ACCESS_TOKEN for 4x faster processing"
                )
            )

        total_games = len(games_list)
        if total_games == 0:
            self.stdout.write(self.style.WARNING("No games found"))
            return

        self.stdout.write(f"Processing {total_games} games...")

        if options.get("dry_run"):
            self.stdout.write(
                self.style.WARNING("  DRY RUN: Would process Wikipedia data for games")
            )
            return

        # Create semaphore and locks for rate limiting
        semaphore = asyncio.Semaphore(concurrency)
        counter_lock = asyncio.Lock()
        processed_count = 0

        async def fetch_wikidata(session, wikidata_id):
            """Fetch Wikipedia page title and metadata from Wikidata API."""
            if not wikidata_id:
                return None

            params = {
                "action": "wbgetentities",
                "format": "json",
                "props": "sitelinks|claims",
                "ids": wikidata_id,
                "sitefilter": "enwiki",
            }

            try:
                url = config.WIKIDATA_API_URL
                # The credentials go to Wikidata's API alone, never to the
                # Wikipedia page scraped below
                async with session.get(
                    url, params=params, auth=wikidata_auth
                ) as response:
                    if response.status != 200:
                        return None
                    data = await response.json()

                    entities = data.get("entities", {})
                    entity = entities.get(wikidata_id, {})

                    # Get Wikipedia page title
                    sitelinks = entity.get("sitelinks", {})
                    enwiki = sitelinks.get("enwiki", {})
                    page_title = enwiki.get("title")

                    if not page_title:
                        return None

                    # Get HLTB ID from P2816 claim
                    # Filter out deprecated claims and prefer
                    # "preferred" rank over "normal"
                    claims = entity.get("claims", {})
                    hltb_id = None
                    p2816 = claims.get("P2816", [])
                    if p2816:
                        # Filter out deprecated claims and sort by rank preference
                        valid_claims = []
                        for claim in p2816:
                            rank = claim.get("rank", "normal")
                            if rank != "deprecated":
                                valid_claims.append((claim, rank))

                        if valid_claims:
                            # Sort by rank preference (preferred first, then normal)
                            valid_claims.sort(
                                key=lambda x: 0 if x[1] == "preferred" else 1
                            )
                            best_claim = valid_claims[0][0]
                            mainsnak = best_claim.get("mainsnak", {})
                            datavalue = mainsnak.get("datavalue", {})
                            hltb_id = datavalue.get("value")

                    # Get Steam AppID from P1733 claim
                    # Filter out deprecated claims and prefer
                    # "preferred" rank over "normal"
                    steam_app_id = None
                    p1733 = claims.get("P1733", [])
                    if p1733:
                        # Filter out deprecated claims and sort by rank preference
                        valid_claims = []
                        for claim in p1733:
                            rank = claim.get("rank", "normal")
                            if rank != "deprecated":
                                valid_claims.append((claim, rank))

                        if valid_claims:
                            # Sort by rank preference (preferred first, then normal)
                            valid_claims.sort(
                                key=lambda x: 0 if x[1] == "preferred" else 1
                            )
                            best_claim = valid_claims[0][0]
                            mainsnak = best_claim.get("mainsnak", {})
                            datavalue = mainsnak.get("datavalue", {})
                            steam_app_id = datavalue.get("value")

                    return {
                        "page_title": page_title,
                        "hltb_id": hltb_id,
                        "steam_app_id": steam_app_id,
                        "lookup_source": config.WIKI_LOOKUP_SOURCE_WIKIDATA,
                    }
            except Exception as e:
                logger.debug("Wikidata fetch failed for %s: %s", wikidata_id, e)
                return None

        async def scrape_genres(session, wikipedia_url):
            """Scrape genre list from Wikipedia infobox."""
            try:
                async with session.get(wikipedia_url) as response:
                    if response.status != 200:
                        return None
                    html = await response.text()

                soup = BeautifulSoup(html, "html.parser")

                # Find infobox
                infobox = soup.find("table", class_="infobox")
                if not infobox:
                    return None

                # Find Genre row
                for row in infobox.find_all("tr"):
                    header = row.find("th")
                    if header and "genre" in header.get_text().lower():
                        data_cell = row.find("td")
                        if not data_cell:
                            continue

                        # Remove reference markers
                        for sup in data_cell.find_all("sup"):
                            sup.decompose()
                        for ref in data_cell.find_all(class_="reference"):
                            ref.decompose()

                        # Check for list items
                        list_items = data_cell.find_all("li")
                        if list_items:
                            genres = [
                                li.get_text(strip=True)
                                for li in list_items
                                if li.get_text(strip=True)
                            ]
                            if genres:
                                return genres

                        # Fall back to text parsing
                        raw_text = data_cell.get_text(separator="|", strip=True)
                        if "|" in raw_text:
                            parts = raw_text.split("|")
                        else:
                            parts = raw_text.split(",")

                        genres = [
                            p.strip().strip(",").strip()
                            for p in parts
                            if p.strip() and len(p.strip()) > 1
                        ]
                        return genres if genres else None

                return None
            except Exception as e:
                logger.debug("Genre scraping failed for %s: %s", wikipedia_url, e)
                return None

        async def process_game(session, idx, game_data):
            """Process a single game with rate limiting."""
            nonlocal processed_count

            async with semaphore:
                game_id = game_data["id"]
                game_name = game_data["name"]
                wikidata_id = game_data["wikidata_id"]

                try:
                    # Step 1: Fetch from Wikidata
                    wikidata_result = await fetch_wikidata(session, wikidata_id)

                    if not wikidata_result:
                        async with counter_lock:
                            self.wikipedia_pages_failed += 1
                        await asyncio.sleep(delay)
                        return

                    async with counter_lock:
                        self.wikipedia_pages_found += 1

                    page_title = wikidata_result["page_title"]
                    wikipedia_url = (
                        f"https://en.wikipedia.org/wiki/"
                        f"{urllib.parse.quote(page_title.replace(' ', '_'))}"
                    )

                    # Step 2: Scrape genres from Wikipedia
                    genres = await scrape_genres(session, wikipedia_url)

                    if genres:
                        async with counter_lock:
                            self.genres_scraped += 1
                    else:
                        async with counter_lock:
                            self.genres_failed += 1

                    # Step 3: Save to database (sync operation)
                    await sync_to_async(self._save_wikipedia_data_async)(
                        game_id,
                        page_title,
                        wikidata_result.get("lookup_source"),
                        wikidata_id,
                        wikidata_result.get("hltb_id"),
                        wikidata_result.get("steam_app_id"),
                        genres,
                    )

                except Exception as e:
                    async with counter_lock:
                        self.wikipedia_pages_failed += 1
                    logger.warning(
                        "Wikipedia processing failed for '%s': %s", game_name, e
                    )

                # Progress checkpoint
                async with counter_lock:
                    processed_count += 1
                    if processed_count % 100 == 0:
                        elapsed = time.time() - self.wikipedia_start_time
                        rate = processed_count / elapsed if elapsed > 0 else 0
                        self.stdout.write(
                            f"  [{processed_count}/{total_games}] "
                            f"({rate:.1f} games/sec)"
                        )

                # Rate limiting
                await asyncio.sleep(delay)

        # Create aiohttp session with user agent
        headers = {"User-Agent": config.WIKI_USER_AGENT}
        timeout = aiohttp.ClientTimeout(total=WIKI_REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            tasks = [
                process_game(session, idx, game_data)
                for idx, game_data in enumerate(games_list, start=1)
            ]
            await asyncio.gather(*tasks)

        # Print completion
        elapsed = time.time() - self.wikipedia_start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"\n  Wikipedia Complete: {self.wikipedia_pages_found} pages found, "
                f"{self.genres_scraped} genres scraped, "
                f"{self.wikipedia_pages_failed} page errors in {elapsed:.0f}s"
            )
        )

    def _save_wikipedia_data_async(
        self,
        game_id,
        page_title,
        lookup_source,
        wikidata_id,
        hltb_id,
        steam_app_id,
        genres,
    ):
        """Save Wikipedia data to database (sync, called via sync_to_async)."""
        game = Game.objects.get(id=game_id)

        # Unset existing primary
        WikipediaGameData.objects.filter(game=game, is_primary=True).update(
            is_primary=False
        )

        # Create or update WikipediaGameData
        defaults = {
            "lookup_source": lookup_source,
            "is_primary": True,
        }
        if wikidata_id:
            defaults["wikidata_id"] = wikidata_id
        if hltb_id:
            defaults["hltb_id"] = hltb_id
        if steam_app_id:
            defaults["steam_app_id"] = steam_app_id

        wiki_game_data, created = WikipediaGameData.upsert_for_game(
            game, page_title, defaults
        )

        # Set primary relationship
        game.primary_wikipedia_game_data = wiki_game_data
        game.save(update_fields=["primary_wikipedia_game_data"])

        # Process genres if available
        if genres:
            normalized_primary, normalized_all, normalized_all_str = (
                canonicalize_genre_payload(genres[0], genres)
            )

            # Update WikipediaGameData
            wiki_game_data.primary_genre = normalized_primary
            wiki_game_data.all_genres = normalized_all_str
            wiki_game_data.save(update_fields=["primary_genre", "all_genres"])

            # Create WikipediaGenre objects
            wikipedia_genres = [
                get_or_create_genre(genre_name) for genre_name in normalized_all
            ]
            game.wikipedia_genres.set(wikipedia_genres)

        return wiki_game_data

    async def _refresh_hltb_async(self, games_list, options):
        """Refresh HLTB data for all games using HowLongToBeat API."""
        from howlongtobeatpy import HowLongToBeat

        self.stdout.write("\n[3/3] Refreshing HLTB Data")
        self.stdout.write("-" * 40)

        self.hltb_start_time = time.time()

        total_games = len(games_list)

        if total_games == 0:
            self.stdout.write(self.style.WARNING("No games found"))
            return

        self.stdout.write(
            f"Processing {total_games} games "
            f"(concurrency: 3, delay: 1.5s, min similarity: 0.85)"
        )

        if options.get("dry_run"):
            self.stdout.write(
                self.style.WARNING("  DRY RUN: Would process HLTB data for games")
            )
            return

        hltb = HowLongToBeat()
        # HLTB doesn't publish rate limits, but be respectful
        # 3 concurrent with 1.5s delay = ~2 req/sec
        concurrency = 3
        delay = 1.5
        min_similarity = 0.85

        # Create semaphore for rate limiting
        semaphore = asyncio.Semaphore(concurrency)
        counter_lock = asyncio.Lock()

        async def process_game(idx, game_data):
            """Process a single game with rate limiting."""
            async with semaphore:
                hltb_id = ""
                hltb_name = ""
                similarity = 0.0
                main_story = None
                main_extra = None
                completionist = None
                fetch_method = ""

                game_name = game_data["name"]
                game_year = game_data["year_of_release"]
                game_igdb_id = game_data["igdb_id"]
                game_id = game_data["id"]
                game_platforms = game_data.get("platforms", [])
                wikidata_hltb_id = game_data.get("primary_wikipedia_game_data__hltb_id")
                wiki_page_title = game_data.get(
                    "primary_wikipedia_game_data__page_title"
                )

                try:
                    best_match = None

                    # Try direct ID lookup if we have HLTB ID from Wikidata
                    if wikidata_hltb_id:
                        try:
                            direct_result = await hltb.async_search_from_id(
                                int(wikidata_hltb_id)
                            )
                            if direct_result:
                                best_match = direct_result
                                fetch_method = "wikidata"
                        except Exception as e:
                            logger.debug(
                                "Direct HLTB lookup failed for ID %s: %s",
                                wikidata_hltb_id,
                                e,
                            )

                    # Fall back to a name search: Wikipedia's title first,
                    # then ours, each with its numeral variants
                    # (games.services.hltb_matching)
                    if not best_match:
                        for search_name in hltb_matching.search_names(
                            game_name, wiki_page_title
                        ):
                            results = await hltb.async_search(search_name)
                            best_match = hltb_matching.choose_entry(
                                results or [],
                                min_similarity=min_similarity,
                                game_year=game_year,
                                game_platforms=game_platforms,
                            )
                            if best_match:
                                fetch_method = "name_search"
                                break

                    if best_match:
                        async with counter_lock:
                            self.hltb_found += 1
                        hltb_id = str(best_match.game_id)
                        hltb_name = best_match.game_name
                        similarity = getattr(best_match, "similarity", 1.0)

                        # Extract playtime values
                        main_story = hltb_matching.entry_hours(best_match, "main_story")
                        main_extra = hltb_matching.entry_hours(best_match, "main_extra")
                        completionist = hltb_matching.entry_hours(
                            best_match, "completionist"
                        )

                        # Save to database
                        await sync_to_async(hltb_matching.save_entry)(
                            game_id,
                            game_igdb_id,
                            hltb_id,
                            hltb_name,
                            fetch_method,
                            similarity,
                            main_story,
                            main_extra,
                            completionist,
                            profile=hltb_matching.entry_profile(best_match),
                        )
                    else:
                        async with counter_lock:
                            self.hltb_not_found += 1

                except Exception as e:
                    async with counter_lock:
                        self.hltb_not_found += 1
                    logger.warning(
                        "Failed to fetch HLTB data for '%s': %s", game_name, e
                    )

                # Progress checkpoint every 100 games
                if idx % 100 == 0:
                    elapsed = time.time() - self.hltb_start_time
                    rate = idx / elapsed if elapsed > 0 else 0
                    self.stdout.write(f"  [{idx}/{total_games}] ({rate:.1f} games/sec)")

                # Rate limiting delay
                await asyncio.sleep(delay)

        # Process all games concurrently
        tasks = [
            process_game(idx, game_data)
            for idx, game_data in enumerate(games_list, start=1)
        ]
        await asyncio.gather(*tasks)

        # Print HLTB completion
        elapsed = time.time() - self.hltb_start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"\n  HLTB Complete: {self.hltb_found} found, "
                f"{self.hltb_not_found} not found in {elapsed:.0f}s"
            )
        )

    def _print_summary(self):
        """Print final execution summary."""
        total_elapsed = time.time() - self.start_time

        # Convert to minutes if over 90 seconds
        if total_elapsed > 90:
            duration_str = (
                f"{int(total_elapsed // 60)} minutes {int(total_elapsed % 60)} seconds"
            )
        else:
            duration_str = f"{total_elapsed:.0f} seconds"

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("Summary"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Total Duration: {duration_str}")

        # IGDB stats
        if self.igdb_processed > 0 or self.igdb_errors != 0:
            if self.igdb_errors == -1:
                self.stdout.write(self.style.ERROR("IGDB:      FAILED"))
            else:
                total_igdb = self.igdb_processed + self.igdb_errors
                success_pct = (
                    (self.igdb_processed / total_igdb * 100) if total_igdb > 0 else 0
                )
                status = (
                    self.style.SUCCESS if self.igdb_errors == 0 else self.style.WARNING
                )
                self.stdout.write(
                    status(
                        f"IGDB:      {self.igdb_processed}/{total_igdb} success "
                        f"({self.igdb_errors} errors, {success_pct:.1f}%)"
                    )
                )

        # Wikipedia stats
        if self.wikipedia_pages_found > 0 or self.wikipedia_pages_failed != 0:
            if self.wikipedia_pages_failed == -1:
                self.stdout.write(self.style.ERROR("Wikipedia: FAILED"))
            else:
                total_wiki = self.wikipedia_pages_found + self.wikipedia_pages_failed
                success_pct = (
                    (self.wikipedia_pages_found / total_wiki * 100)
                    if total_wiki > 0
                    else 0
                )
                status = (
                    self.style.SUCCESS
                    if self.wikipedia_pages_failed == 0
                    else self.style.WARNING
                )
                self.stdout.write(
                    status(
                        f"Wikipedia: {self.wikipedia_pages_found}/{total_wiki} "
                        f"pages found ({self.wikipedia_pages_failed} errors, "
                        f"{success_pct:.1f}%)"
                    )
                )

                # Genre stats
                if self.genres_scraped > 0 or self.genres_failed > 0:
                    total_genres = self.genres_scraped + self.genres_failed
                    genre_pct = (
                        (self.genres_scraped / total_genres * 100)
                        if total_genres > 0
                        else 0
                    )
                    self.stdout.write(
                        f"Genres:    {self.genres_scraped}/{total_genres} scraped "
                        f"({genre_pct:.1f}%)"
                    )

        # HLTB stats
        if self.hltb_found > 0 or self.hltb_not_found != 0:
            if self.hltb_not_found == -1:
                self.stdout.write(self.style.ERROR("HLTB:      FAILED"))
            else:
                total_hltb = self.hltb_found + self.hltb_not_found
                success_pct = (
                    (self.hltb_found / total_hltb * 100) if total_hltb > 0 else 0
                )
                status = (
                    self.style.SUCCESS
                    if self.hltb_not_found == 0
                    else self.style.WARNING
                )
                self.stdout.write(
                    status(
                        f"HLTB:      {self.hltb_found}/{total_hltb} found "
                        f"({self.hltb_not_found} not found, {success_pct:.1f}%)"
                    )
                )

        # Overall status
        has_errors = (
            self.igdb_errors > 0
            or self.wikipedia_pages_failed > 0
            or self.genres_failed > 0
            or self.hltb_not_found > 0
        )
        overall_status = "SUCCESS" if not has_errors else "COMPLETED WITH ERRORS"
        style = self.style.SUCCESS if not has_errors else self.style.WARNING

        self.stdout.write(f"\nOverall Status: {style(overall_status)}")
        self.stdout.write(
            f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
        self.stdout.write("=" * 70)

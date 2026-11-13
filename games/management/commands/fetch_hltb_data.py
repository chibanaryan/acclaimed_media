"""
Management command to fetch HowLongToBeat playtime data for games.

Uses the howlongtobeatpy library to search for games and retrieve
completion time estimates (main story, main+extras, completionist).
"""

import asyncio
import csv
import logging
import time

from django.core.management.base import BaseCommand

from games.models import Game
from games.services import hltb_matching

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch HowLongToBeat playtime data for games"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_time = None

    def add_arguments(self, parser):
        parser.add_argument(
            "--game",
            type=str,
            help="Process specific game by name (case-insensitive)",
        )
        parser.add_argument(
            "--slug",
            type=str,
            help="Process specific game by slug",
        )
        parser.add_argument(
            "--id",
            type=int,
            help="Process specific game by database ID",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit number of games to process",
        )
        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            help="Skip first N games (default: 0)",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=1.0,
            help="Delay between requests in seconds (default: 1.0)",
        )
        parser.add_argument(
            "--min-similarity",
            type=float,
            default=0.85,
            help="Minimum similarity score for matching (default: 0.85)",
        )
        parser.add_argument(
            "--output",
            type=str,
            help="Also write a CSV, to this path (none is written without it)",
        )
        parser.add_argument(
            "--save",
            action="store_true",
            help="Save results to database (default: CSV only)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force refresh all games (ignore existing data)",
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=5,
            help="Number of concurrent requests (default: 5, max 10 recommended)",
        )
        parser.add_argument(
            "--no-name-search",
            action="store_true",
            help="Disable name search fallback. By default, name search is used "
            "when Wikidata HLTB ID is not available or lookup fails.",
        )

    def handle(self, *args, **options):
        self.start_time = time.time()

        # Get games to process (do this synchronously before async context)
        games_qs = self._get_games(options)

        if not games_qs.exists():
            self.stdout.write(self.style.ERROR("No games found to process"))
            return

        # Convert to list to avoid async ORM issues
        # Include Wikidata HLTB ID for direct lookup when available
        # Also include Wikipedia page title for fallback search
        # Prefetch platforms for better matching
        games_qs = games_qs.prefetch_related("platforms")

        # WikipediaGameData for all games: every record, and the primary
        games_qs = games_qs.prefetch_related("wikipedia_game_data_set")
        games_qs = games_qs.select_related("primary_wikipedia_game_data")

        # Convert to list with platform data and all Wikidata HLTB IDs
        games_list = []
        for game in games_qs:
            # From the prefetch: `values_list` here was a query a game
            platform_names = [platform.name for platform in game.platforms.all()]

            # Collect HLTB IDs from ALL WikipediaGameData records (not just primary)
            # This allows fallback when primary record doesn't have an HLTB ID
            # Order: primary first (if it has hltb_id), then other records
            all_hltb_ids = []
            all_wikidata_ids = []  # Track which Wikidata IDs the HLTB IDs came from
            is_from_primary = []  # Track whether each HLTB ID is from primary

            # Track primary's wikidata_id for display purposes
            primary_wikidata_id = (
                game.primary_wikipedia_game_data.wikidata_id
                if game.primary_wikipedia_game_data
                else None
            )

            # First add primary if it has an HLTB ID
            if (
                game.primary_wikipedia_game_data
                and game.primary_wikipedia_game_data.hltb_id
            ):
                all_hltb_ids.append(game.primary_wikipedia_game_data.hltb_id)
                all_wikidata_ids.append(game.primary_wikipedia_game_data.wikidata_id)
                is_from_primary.append(True)

            # Then add other WikipediaGameData records that have HLTB IDs
            for wiki_data in game.wikipedia_game_data_set.all():
                if wiki_data.hltb_id and wiki_data.hltb_id not in all_hltb_ids:
                    all_hltb_ids.append(wiki_data.hltb_id)
                    all_wikidata_ids.append(wiki_data.wikidata_id)
                    is_from_primary.append(False)

            games_list.append(
                {
                    "id": game.id,
                    "name": game.name,
                    "slug": game.slug,
                    "rank": game.rank,
                    "year_of_release": game.year_of_release,
                    "igdb_id": game.igdb_id,
                    # Backwards compatible: primary hltb_id (if any)
                    "primary_wikipedia_game_data__hltb_id": (
                        all_hltb_ids[0] if all_hltb_ids else None
                    ),
                    # New: all HLTB IDs from all WikipediaGameData records
                    "all_wikidata_hltb_ids": all_hltb_ids,
                    "all_wikidata_ids": all_wikidata_ids,
                    "is_from_primary": is_from_primary,  # Track which are from primary
                    "primary_wikidata_id": primary_wikidata_id,
                    "primary_wikipedia_game_data__page_title": (
                        game.primary_wikipedia_game_data.page_title
                        if game.primary_wikipedia_game_data
                        else None
                    ),
                    "platforms": platform_names,
                }
            )
        game_count = len(games_list)

        # Run async handler with pre-fetched data
        asyncio.run(self._async_handle(games_list, game_count, *args, **options))

    async def _async_handle(self, games_list, game_count, *args, **options):
        from asgiref.sync import sync_to_async
        from howlongtobeatpy import HowLongToBeat

        delay = options.get("delay", 1.0)
        min_similarity = options.get("min_similarity", 0.85)
        concurrency = options.get("concurrency", 1)
        use_name_search = not options.get("no_name_search", False)

        self.stdout.write(f"\nProcessing {game_count} games...")
        self.stdout.write(
            f"Delay: {delay}s, Min similarity: {min_similarity}, "
            f"Concurrency: {concurrency}"
        )
        if not use_name_search:
            self.stdout.write(" (name search DISABLED)")
        self.stdout.write("\n")

        # Prepare CSV output - only if explicitly requested with --output
        # (CSV was mainly for testing; production uses --save for database)
        csv_file = None
        csv_writer = None
        csv_path = None
        if options.get("output"):
            csv_path = options["output"]
            csv_file = open(csv_path, "w", newline="", encoding="utf-8")
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(
                [
                    "Rank",
                    "Game Name",
                    "Year",
                    "Fetch Method",
                    "HLTB ID",
                    "HLTB Name",
                    "Similarity",
                    "Main Story (h)",
                    "Main + Extra (h)",
                    "Completionist (h)",
                    "Error",
                ]
            )
            self.stdout.write(f"Writing results to: {csv_path}\n")

        # Process games with concurrency
        success_count = 0
        failure_count = 0
        hltb = HowLongToBeat()

        # Create locks for thread-safe operations
        csv_lock = asyncio.Lock()
        counter_lock = asyncio.Lock()

        # Create semaphore for rate limiting
        semaphore = asyncio.Semaphore(concurrency)

        async def process_game(idx, game_data):
            """Process a single game with rate limiting."""
            nonlocal success_count, failure_count

            async with semaphore:
                hltb_id = ""
                hltb_name = ""
                similarity = 0.0
                main_story = None
                main_extra = None
                completionist = None
                error_message = ""
                fetch_method = ""

                game_name = game_data["name"]
                game_year = game_data["year_of_release"]
                game_rank = game_data["rank"]
                game_igdb_id = game_data["igdb_id"]
                game_id = game_data["id"]
                game_platforms = game_data.get("platforms", [])
                # Get all HLTB IDs from all WikipediaGameData records
                all_wikidata_hltb_ids = game_data.get("all_wikidata_hltb_ids", [])
                all_wikidata_ids = game_data.get("all_wikidata_ids", [])
                is_from_primary_list = game_data.get("is_from_primary", [])
                wiki_page_title = game_data.get(
                    "primary_wikipedia_game_data__page_title"
                )
                # Track which wikidata ID was used for successful lookup
                used_wikidata_id = None

                try:
                    best_match = None

                    # Try direct ID lookup with ALL HLTB IDs from Wikidata
                    # Iterates through the list until one works (handles cases
                    # like Counter-Strike where primary doesn't have HLTB ID)
                    for idx_hltb, wikidata_hltb_id in enumerate(all_wikidata_hltb_ids):
                        try:
                            direct_result = await hltb.async_search_from_id(
                                int(wikidata_hltb_id)
                            )
                            if direct_result:
                                best_match = direct_result
                                fetch_method = "wikidata"
                                # `handle` lists an id, the Wikidata record
                                # it came from and whether that is the
                                # primary one side by side
                                used_wikidata_id = all_wikidata_ids[idx_hltb]
                                is_from_primary = is_from_primary_list[idx_hltb]
                                # Log which Wikidata ID was used (especially useful
                                # when it's not the primary)
                                extra_info = ""
                                if not is_from_primary:
                                    extra_info = (
                                        f" (via alternate Wikidata {used_wikidata_id})"
                                    )
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"[{idx}/{game_count}] ★ {game_name}: "
                                        f"Direct lookup via Wikidata HLTB ID "
                                        f"{wikidata_hltb_id}{extra_info}"
                                    )
                                )
                                break  # Found a working HLTB ID, stop iterating
                        except Exception as e:
                            logger.debug(
                                "Direct HLTB lookup failed for ID %s: %s",
                                wikidata_hltb_id,
                                e,
                            )
                            # Continue to next HLTB ID in the list

                    # Fall back to name search if direct lookup failed
                    # (only if --use-name-search was specified)
                    if not best_match and use_name_search:
                        # Wikipedia's title first, then ours, each with its
                        # numeral variants; the first name with an entry
                        # similar enough wins (games.services.hltb_matching)
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
                        hltb_id = str(best_match.game_id)
                        hltb_name = best_match.game_name
                        similarity = getattr(best_match, "similarity", 1.0)

                        # Extract playtime values
                        main_story = hltb_matching.entry_hours(best_match, "main_story")
                        main_extra = hltb_matching.entry_hours(best_match, "main_extra")
                        completionist = hltb_matching.entry_hours(
                            best_match, "completionist"
                        )

                        # Only print match details if not from direct Wikidata
                        # lookup, which has printed its own line. Asked of the
                        # game's ids until 2026-11-12, so a game whose ids all
                        # failed and whose name then matched printed nothing
                        if fetch_method != "wikidata":
                            self.stdout.write(
                                f"[{idx}/{game_count}] \u2713 {game_name}: "
                                f"{hltb_name} ({similarity:.2f}) - "
                                f"Main: {main_story}h, Extra: {main_extra}h, "
                                f"Complete: {completionist}h"
                            )

                        # Save to database if requested
                        if options.get("save"):
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

                        # Counted once it is saved: a save that raises is
                        # counted below, and was counted here as well
                        async with counter_lock:
                            success_count += 1
                    else:
                        async with counter_lock:
                            failure_count += 1
                        if all_wikidata_hltb_ids:
                            # Tried all Wikidata HLTB IDs but none worked
                            ids_tried = ", ".join(all_wikidata_hltb_ids)
                            error_message = (
                                f"Wikidata HLTB ID(s) [{ids_tried}] lookup failed"
                            )
                        elif use_name_search:
                            error_message = "No results found via name search"
                        else:
                            error_message = "No Wikidata HLTB ID available"
                        self.stdout.write(
                            self.style.WARNING(
                                f"[{idx}/{game_count}] \u2717 {game_name}: "
                                f"{error_message}"
                            )
                        )

                except Exception as e:
                    async with counter_lock:
                        failure_count += 1
                    error_message = str(e)[:100]
                    logger.warning(
                        "Failed to fetch HLTB data for '%s': %s",
                        game_name,
                        e,
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f"[{idx}/{game_count}] \u2717 {game_name}: {error_message}"
                        )
                    )

                # Write to CSV (thread-safe)
                if csv_writer:
                    async with csv_lock:
                        csv_writer.writerow(
                            [
                                game_rank,
                                game_name,
                                game_year or "",
                                fetch_method,
                                hltb_id,
                                hltb_name,
                                f"{similarity:.2f}" if similarity else "",
                                main_story or "",
                                main_extra or "",
                                completionist or "",
                                error_message,
                            ]
                        )
                        csv_file.flush()

                # Rate limiting delay
                await asyncio.sleep(delay)

        try:
            # Process all games concurrently
            tasks = [
                process_game(idx, game_data)
                for idx, game_data in enumerate(games_list, start=1)
            ]
            await asyncio.gather(*tasks)

        finally:
            if csv_file:
                csv_file.close()

        # Summary
        elapsed = time.time() - self.start_time
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS(f"\nCompleted in {elapsed:.1f} seconds"))
        self.stdout.write(f"\nTotal games: {game_count}")
        self.stdout.write(self.style.SUCCESS(f"HLTB data found: {success_count}"))
        if failure_count > 0:
            self.stdout.write(
                self.style.WARNING(f"HLTB data not found: {failure_count}")
            )

        if options.get("save"):
            self.stdout.write(self.style.SUCCESS("\n\u2713 Results saved to database"))
        if csv_path:
            self.stdout.write(f"\n\u2713 Results written to {csv_path}")

    def _get_games(self, options):
        """Get queryset of games to process based on options."""
        # Single game by name
        if options.get("game"):
            return Game.objects.filter(name__iexact=options["game"])

        # Single game by slug
        if options.get("slug"):
            return Game.objects.filter(slug=options["slug"])

        # Single game by ID
        if options.get("id"):
            return Game.objects.filter(id=options["id"])

        # All games with filtering
        games = Game.objects.all().order_by("rank")

        # Only games without HLTB data, unless forced
        if not options.get("force"):
            games = games.filter(primary_hltb_game_data__isnull=True)

        # Apply offset
        if options.get("offset"):
            games = games[options["offset"] :]

        # Apply limit
        if options.get("limit"):
            games = games[: options["limit"]]

        return games

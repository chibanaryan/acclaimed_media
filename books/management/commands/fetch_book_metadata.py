"""
Search Open Library and Hardcover for book metadata, by title or ISBN.

It prints what it finds, or writes it to a CSV; it saves nothing. Until
2026-11-10 it also took ``--book``, ``--save``, ``--skip-existing``,
``--force``, ``--concurrency`` and ``--delay``: the first two reached a stub
that said "not yet implemented" and exited 0, and the rest were read by
nothing.
"""

import csv
import logging
import time
from typing import Any, Dict, List

from django.core.management.base import BaseCommand

from books import book_metadata

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch book metadata from Open Library and Hardcover APIs"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_time = None

    def add_arguments(self, parser):
        parser.add_argument(
            "--search",
            type=str,
            help="Search for books by title",
        )
        parser.add_argument(
            "--author",
            type=str,
            help="Filter search by author name",
        )
        parser.add_argument(
            "--isbn",
            type=str,
            help="Look up book by ISBN",
        )

        # Processing arguments
        parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help="Limit number of results (default: 10)",
        )
        # Source selection
        parser.add_argument(
            "--source",
            type=str,
            choices=["openlibrary", "hardcover", "both"],
            default="openlibrary",
            help="Data source to use (default: openlibrary)",
        )

        # Output arguments
        parser.add_argument(
            "--output",
            type=str,
            help="Output CSV file path",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output results as JSON",
        )

    def handle(self, *args, **options):
        self.start_time = time.time()

        # Standalone search mode
        if options.get("search") or options.get("isbn"):
            return self._handle_search(options)

        # Default: show help
        self.stdout.write(
            self.style.WARNING(
                "No action specified. Use --search or --isbn.\n"
                "Run with --help for usage information."
            )
        )

    def _handle_search(self, options):
        """Handle standalone search mode."""
        service = book_metadata.get_service(
            use_hardcover=(options.get("source") in ["hardcover", "both"]),
        )

        # ISBN lookup
        if options.get("isbn"):
            self.stdout.write(f"Looking up ISBN: {options['isbn']}\n")
            result = service.get_book_info(
                title="",  # Not used for ISBN lookup
                isbn=options["isbn"],
            )
            if result:
                self._print_book_result(result)
            else:
                self.stdout.write(self.style.ERROR("Book not found"))
            return

        # Title/author search
        query = options["search"]
        author = options.get("author")
        limit = options.get("limit", 10)
        source = options.get("source", "openlibrary")

        self.stdout.write(f"\nSearching for: {query}")
        if author:
            self.stdout.write(f" by {author}")
        self.stdout.write(f" (source: {source}, limit: {limit})\n\n")

        if author:
            # Use get_book_info for title + author search
            result = service.get_book_info(title=query, author=author)
            if result:
                self._print_book_result(result)
            else:
                self.stdout.write(self.style.WARNING("No results found"))
        else:
            # Use search_books for general search
            results = service.search_books(
                query=query,
                limit=limit,
                source=source if source != "both" else None,
            )

            if results:
                self._print_search_results(results, options)
            else:
                self.stdout.write(self.style.WARNING("No results found"))

        elapsed = time.time() - self.start_time
        self.stdout.write(f"\nCompleted in {elapsed:.1f} seconds\n")

    def _print_book_result(self, result: Dict[str, Any]):
        """Print a single book result."""
        self.stdout.write(self.style.SUCCESS(f"\n{result.get('title', 'Unknown')}"))

        if result.get("authors"):
            self.stdout.write(f"  Authors: {', '.join(result['authors'])}")

        if result.get("year"):
            self.stdout.write(f"  Year: {result['year']}")

        if result.get("isbn"):
            isbns = result["isbn"][:3]  # Show first 3
            self.stdout.write(f"  ISBN: {', '.join(str(i) for i in isbns)}")

        if result.get("pages"):
            self.stdout.write(f"  Pages: {result['pages']}")

        if result.get("genres"):
            genres = result["genres"][:5]  # Show first 5
            self.stdout.write(f"  Genres: {', '.join(genres)}")

        if result.get("description"):
            desc = result["description"][:200]
            if len(result["description"]) > 200:
                desc += "..."
            self.stdout.write(f"  Description: {desc}")

        if result.get("cover_url"):
            self.stdout.write(f"  Cover: {result['cover_url']}")

        self.stdout.write(f"  Source: {result.get('source', 'unknown')}")
        self.stdout.write("")

    def _print_search_results(
        self, results: List[Dict[str, Any]], options: Dict[str, Any]
    ):
        """Print search results."""
        # JSON output
        if options.get("json"):
            import json

            self.stdout.write(json.dumps(results, indent=2, default=str))
            return

        # CSV output
        if options.get("output"):
            self._write_csv(results, options["output"])
            self.stdout.write(f"Results written to: {options['output']}\n")
            return

        # Console output
        for idx, result in enumerate(results, 1):
            title = result.get("title", "Unknown")
            authors = result.get("author_name", result.get("authors", []))
            if isinstance(authors, list):
                authors = ", ".join(authors[:2])
            year = result.get("first_publish_year", result.get("year", ""))
            source = result.get("source", "unknown")

            self.stdout.write(f"  {idx}. {title} ({year}) - {authors} [{source}]")

        self.stdout.write(f"\nTotal results: {len(results)}")

    def _write_csv(self, results: List[Dict[str, Any]], output_path: str):
        """Write results to CSV file."""
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Title",
                    "Authors",
                    "Year",
                    "ISBN",
                    "Subjects",
                    "Source",
                ]
            )

            for result in results:
                authors = result.get("author_name", result.get("authors", []))
                if isinstance(authors, list):
                    authors = "; ".join(authors)

                isbns = result.get("isbn", [])
                if isinstance(isbns, list):
                    isbns = "; ".join(str(i) for i in isbns[:3])

                subjects = result.get("subject", result.get("genres", []))
                if isinstance(subjects, list):
                    subjects = "; ".join(subjects[:5])

                writer.writerow(
                    [
                        result.get("title", ""),
                        authors,
                        result.get("first_publish_year", result.get("year", "")),
                        isbns,
                        subjects,
                        result.get("source", ""),
                    ]
                )

"""Tests for the fetch_book_metadata management command.

The command looks books up through ``BookMetadataService`` and prints what it
finds, or writes it to a CSV. Every test replaces the service where the command
reads it, since the real one calls Open Library and Hardcover.
"""

import csv
import json
import os
import tempfile
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase

from books.book_metadata import BookMetadataService

GET_SERVICE = "books.management.commands.fetch_book_metadata.book_metadata.get_service"

# A search row as Open Library's search.json gives it, with the source the
# service adds
OPEN_LIBRARY_ROW = {
    "title": "Dune",
    "author_name": ["Frank Herbert", "Brian Herbert", "Kevin J. Anderson"],
    "first_publish_year": 1965,
    "isbn": ["9780441172719", "0441172717", "9780340960196", "9780575081505"],
    "subject": ["Science fiction", "Deserts", "Ecology", "Politics", "Fate", "Spice"],
    "source": "openlibrary",
}

# One in the service's own vocabulary: authors, year and genres
NORMALISED_ROW = {
    "title": "Neuromancer",
    "authors": ["William Gibson"],
    "year": 1984,
    "isbn": ["9780441569595"],
    "genres": ["Cyberpunk"],
    "source": "hardcover",
}


class CommandTestCase(SimpleTestCase):
    """Runs the command against a stand-in for the metadata service."""

    def setUp(self):
        # Autospecced, so a call the real service would refuse (a keyword it
        # does not take) fails here too
        self.service = mock.create_autospec(BookMetadataService, instance=True)
        patcher = mock.patch(GET_SERVICE, return_value=self.service)
        self.get_service = patcher.start()
        self.addCleanup(patcher.stop)

    def run_command(self, *args):
        out = StringIO()
        call_command("fetch_book_metadata", *args, stdout=out)
        return out.getvalue()


class NoActionTests(CommandTestCase):
    def test_no_action_says_which_options_to_pass(self):
        """Without --search or --isbn there is nothing to look up: the command
        says so and builds no service, which would start the Hardcover client."""
        output = self.run_command()

        self.assertIn("No action specified. Use --search or --isbn.", output)
        self.assertIn("Run with --help for usage information.", output)
        self.get_service.assert_not_called()

    def test_an_author_alone_is_no_action(self):
        """--author narrows a title search; on its own it searches nothing."""
        output = self.run_command("--author", "Frank Herbert")

        self.assertIn("No action specified", output)
        self.get_service.assert_not_called()


class IsbnLookupTests(CommandTestCase):
    def test_a_hit_prints_every_field_it_has(self):
        """The ISBN lookup prints the book the service found: at most three
        ISBNs, five genres and 200 characters of description."""
        self.service.get_book_info.return_value = {
            "title": "Dune",
            "authors": ["Frank Herbert", "Brian Herbert"],
            "year": 1965,
            "isbn": ["9780441172719", "0441172717", "9780340960196", "9780575081505"],
            "pages": 612,
            "genres": [
                "Science fiction",
                "Deserts",
                "Ecology",
                "Politics",
                "Fate",
                "X",
            ],
            "description": "A" * 200 + "B",
            "cover_url": "https://covers.openlibrary.org/b/id/1-L.jpg",
            "source": "openlibrary",
        }

        output = self.run_command("--isbn", "9780441172719")

        self.assertEqual(
            output.splitlines(),
            [
                "Looking up ISBN: 9780441172719",
                "",
                "Dune",
                "  Authors: Frank Herbert, Brian Herbert",
                "  Year: 1965",
                "  ISBN: 9780441172719, 0441172717, 9780340960196",
                "  Pages: 612",
                "  Genres: Science fiction, Deserts, Ecology, Politics, Fate",
                "  Description: " + "A" * 200 + "...",
                "  Cover: https://covers.openlibrary.org/b/id/1-L.jpg",
                "  Source: openlibrary",
                "",
            ],
        )
        self.service.get_book_info.assert_called_once_with(
            title="", isbn="9780441172719"
        )
        self.service.search_books.assert_not_called()

    def test_a_hit_with_little_to_say_prints_no_empty_lines(self):
        """A field the source did not give is left out rather than printed
        empty, a short description is not given an ellipsis, and ISBNs that
        arrive as numbers are still joined."""
        self.service.get_book_info.return_value = {
            "authors": [],
            "year": None,
            "isbn": [441172717],
            "description": "Short.",
        }

        output = self.run_command("--isbn", "0441172717")

        self.assertEqual(
            output.splitlines(),
            [
                "Looking up ISBN: 0441172717",
                "",
                "Unknown",
                "  ISBN: 441172717",
                "  Description: Short.",
                "  Source: unknown",
                "",
            ],
        )

    def test_a_miss_says_the_book_was_not_found(self):
        self.service.get_book_info.return_value = None

        output = self.run_command("--isbn", "0000000000")

        self.assertEqual(
            output.splitlines(), ["Looking up ISBN: 0000000000", "Book not found"]
        )

    def test_an_isbn_beats_a_search(self):
        """Given both, the ISBN is the precise one: the title is not searched."""
        self.service.get_book_info.return_value = None

        self.run_command("--isbn", "0000000000", "--search", "Dune")

        self.service.get_book_info.assert_called_once_with(title="", isbn="0000000000")
        self.service.search_books.assert_not_called()

    def test_hardcover_is_started_only_when_asked_for(self):
        """The default source is Open Library alone; `hardcover` and `both`
        turn Hardcover's client on."""
        self.service.get_book_info.return_value = None

        for source, use_hardcover in (
            (None, False),
            ("openlibrary", False),
            ("hardcover", True),
            ("both", True),
        ):
            with self.subTest(source=source):
                self.get_service.reset_mock()
                args = ["--source", source] if source else []

                self.run_command("--isbn", "0000000000", *args)

                self.get_service.assert_called_once_with(use_hardcover=use_hardcover)


class TitleAndAuthorTests(CommandTestCase):
    def test_a_hit_prints_the_one_book(self):
        """With an author the command asks for the single best match, not a
        list, and prints it as the ISBN lookup does."""
        self.service.get_book_info.return_value = {
            "title": "Nineteen Eighty-Four",
            "authors": ["George Orwell"],
            "year": 1949,
            "source": "openlibrary",
        }

        output = self.run_command("--search", "1984", "--author", "George Orwell")

        self.assertIn(
            "\nNineteen Eighty-Four\n"
            "  Authors: George Orwell\n"
            "  Year: 1949\n"
            "  Source: openlibrary\n",
            output,
        )
        self.assertRegex(output, r"\nCompleted in \d+\.\d seconds\n$")
        self.service.get_book_info.assert_called_once_with(
            title="1984", author="George Orwell"
        )
        self.service.search_books.assert_not_called()

    def test_a_miss_says_no_results(self):
        self.service.get_book_info.return_value = None

        output = self.run_command("--search", "1984", "--author", "Nobody")

        self.assertIn("No results found\n", output)
        self.assertRegex(output, r"\nCompleted in \d+\.\d seconds\n$")

    def test_what_is_searched_for_is_one_line(self):
        """The title, the author and the source read as one line. Each part
        was written on its own, and a write ends its line, so they came out
        as three."""
        self.service.get_book_info.return_value = None

        output = self.run_command("--search", "1984", "--author", "George Orwell")

        self.assertIn(
            "Searching for: 1984 by George Orwell (source: openlibrary, limit: 10)\n",
            output,
        )


class SearchListTests(CommandTestCase):
    def test_results_are_numbered_with_year_authors_and_source(self):
        """A title search lists what the service returned, whichever names a
        row uses for its authors and year: Open Library's search rows say
        `author_name` and `first_publish_year`, the service's own `authors`
        and `year`. Two authors are named at most."""
        self.service.search_books.return_value = [OPEN_LIBRARY_ROW, NORMALISED_ROW]

        output = self.run_command("--search", "dune")

        self.assertIn(
            "  1. Dune (1965) - Frank Herbert, Brian Herbert [openlibrary]\n"
            "  2. Neuromancer (1984) - William Gibson [hardcover]\n"
            "\n"
            "Total results: 2\n",
            output,
        )
        self.assertRegex(output, r"\nCompleted in \d+\.\d seconds\n$")
        self.service.get_book_info.assert_not_called()

    def test_a_row_with_nothing_but_a_title_is_still_listed(self):
        self.service.search_books.return_value = [{"title": "Untitled"}, {}]

        output = self.run_command("--search", "untitled")

        self.assertIn("  1. Untitled () -  [unknown]\n", output)
        self.assertIn("  2. Unknown () -  [unknown]\n", output)

    def test_what_is_searched_for_is_one_line(self):
        self.service.search_books.return_value = []

        output = self.run_command("--search", "dune", "--limit", "3")

        self.assertIn("Searching for: dune (source: openlibrary, limit: 3)\n", output)

    def test_no_results_says_so(self):
        self.service.search_books.return_value = []

        output = self.run_command("--search", "zzzz")

        self.assertIn("No results found\n", output)
        self.assertNotIn("Total results", output)

    def test_the_limit_and_the_source_reach_the_service(self):
        """`both` is the service's "no one source", which it spells None."""
        self.service.search_books.return_value = []

        for args, expected in (
            ([], {"limit": 10, "source": "openlibrary"}),
            (["--limit", "50"], {"limit": 50, "source": "openlibrary"}),
            (["--source", "hardcover"], {"limit": 10, "source": "hardcover"}),
            (["--source", "both"], {"limit": 10, "source": None}),
        ):
            with self.subTest(args=args):
                self.service.search_books.reset_mock()

                self.run_command("--search", "dune", *args)

                self.service.search_books.assert_called_once_with(
                    query="dune", **expected
                )

    def test_json_prints_the_rows_as_the_service_gave_them(self):
        """--json prints the rows whole, not the console's summary of them."""
        self.service.search_books.return_value = [OPEN_LIBRARY_ROW, NORMALISED_ROW]

        output = self.run_command("--search", "dune", "--json")

        printed = output[output.index("[") : output.rindex("]") + 1]
        self.assertEqual(json.loads(printed), [OPEN_LIBRARY_ROW, NORMALISED_ROW])
        self.assertNotIn("Total results", output)


class CsvOutputTests(CommandTestCase):
    def write_csv(self, rows):
        """Run a search with --output; the command's output and the file's rows."""
        self.service.search_books.return_value = rows
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "books.csv")
            output = self.run_command("--search", "dune", "--output", path)
            with open(path, newline="", encoding="utf-8") as f:
                return output, path, list(csv.reader(f))

    def test_the_file_holds_a_header_and_a_row_a_result(self):
        """--output writes the results to the file instead of listing them:
        every author, three ISBNs and five subjects, under either set of
        names a row uses."""
        output, path, rows = self.write_csv([OPEN_LIBRARY_ROW, NORMALISED_ROW])

        self.assertEqual(
            rows,
            [
                ["Title", "Authors", "Year", "ISBN", "Subjects", "Source"],
                [
                    "Dune",
                    "Frank Herbert; Brian Herbert; Kevin J. Anderson",
                    "1965",
                    "9780441172719; 0441172717; 9780340960196",
                    "Science fiction; Deserts; Ecology; Politics; Fate",
                    "openlibrary",
                ],
                [
                    "Neuromancer",
                    "William Gibson",
                    "1984",
                    "9780441569595",
                    "Cyberpunk",
                    "hardcover",
                ],
            ],
        )
        self.assertIn(f"Results written to: {path}\n", output)
        self.assertNotIn("Total results", output)
        self.assertNotIn("1. Dune", output)

    def test_a_row_with_nothing_in_it_is_a_row_of_empty_cells(self):
        _, _, rows = self.write_csv([{}])

        self.assertEqual(rows[1], ["", "", "", "", "", ""])

    def test_a_title_that_reads_as_a_formula_is_written_as_text(self):
        """Titles and names come from Open Library and Hardcover, which anyone
        can edit, and a cell starting `=`, `+`, `-` or `@` is run as a formula
        by the spreadsheet that opens the file. Each is prefixed with an
        apostrophe, as the site's CSV downloads are."""
        _, _, rows = self.write_csv(
            [
                {
                    "title": '=HYPERLINK("http://evil.example","Dune")',
                    "author_name": ["+1 Author", "Another"],
                    "first_publish_year": 1965,
                    "isbn": ["-1"],
                    "subject": ["@SUM(A1:A9)"],
                    "source": "openlibrary",
                },
                {"title": "+1", "source": "openlibrary"},
            ]
        )

        self.assertEqual(
            rows[1:],
            [
                [
                    '\'=HYPERLINK("http://evil.example","Dune")',
                    "'+1 Author; Another",
                    "1965",
                    "'-1",
                    "'@SUM(A1:A9)",
                    "openlibrary",
                ],
                ["'+1", "", "", "", "", "openlibrary"],
            ],
        )

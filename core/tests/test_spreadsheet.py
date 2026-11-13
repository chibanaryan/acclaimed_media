"""CSV downloads open as text in a spreadsheet, never as a formula."""

import io
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from core.services.spreadsheet import SafeWriter, neutralise


class NeutraliseTests(SimpleTestCase):
    def test_a_formula_is_text(self):
        for value in ('=HYPERLINK("x")', "+", "-ism", "@SUM(A1)", "\t=1"):
            with self.subTest(value=value):
                self.assertEqual(neutralise(value), "'" + value)

    def test_anything_else_is_as_it_was(self):
        for value in ("Abbey Road", "", "1999", 5, -3, 1.5, None):
            with self.subTest(value=value):
                self.assertEqual(neutralise(value), value)

    def test_the_writer_writes_every_cell_through_it(self):
        stream = io.StringIO()
        SafeWriter(stream).writerow([1, "=", "Kid A"])
        self.assertEqual(stream.getvalue().strip(), "1,'=,Kid A")


class EveryCsvIsWrittenSafelyTests(SimpleTestCase):
    """No module writes a CSV round `SafeWriter`.

    The two downloads have gone through it since the fourth pass. Three
    games commands' `--output` reports, of HowLongToBeat's names, Wikipedia's
    titles and the release's own, still wrote with `csv.writer` until
    2026-11-12, as books' did: a name starting "=" or "+" is a formula to
    whoever opens the file.
    """

    def test_csv_writer_is_named_in_one_place(self):
        base = Path(settings.BASE_DIR)
        writers = []
        for app in ("games", "music", "books", "core"):
            for path in (base / app).rglob("*.py"):
                parts = path.relative_to(base).parts
                if "tests" in parts or "migrations" in parts:
                    continue
                if "csv.writer(" in path.read_text():
                    writers.append("/".join(parts))
        self.assertEqual(writers, ["core/services/spreadsheet.py"])

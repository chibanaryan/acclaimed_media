"""CSV downloads open as text in a spreadsheet, never as a formula."""

import io

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

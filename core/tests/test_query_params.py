"""Tests for the query-string parsers."""

from django.test import SimpleTestCase

from core.services.query_params import MAX_INT, parse_id_list, parse_int, parse_limit


class ParseIntTests(SimpleTestCase):
    def test_parses_an_integer(self):
        self.assertEqual(parse_int("1994"), 1994)
        self.assertEqual(parse_int(" -3 "), -3)

    def test_malformed_values_give_the_default(self):
        for raw in (None, "", "abc", "1.5", "1,2", "²"):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_int(raw))
                self.assertEqual(parse_int(raw, 7), 7)

    def test_a_value_no_database_column_can_hold_gives_the_default(self):
        self.assertEqual(parse_int(str(MAX_INT)), MAX_INT)
        self.assertIsNone(parse_int(str(MAX_INT + 1)))
        self.assertIsNone(parse_int(str(-MAX_INT - 1)))


class ParseIdListTests(SimpleTestCase):
    def test_parses_comma_separated_ids(self):
        self.assertEqual(parse_id_list("3, 1,2"), [3, 1, 2])

    def test_skips_anything_that_is_not_an_id(self):
        raw = f"abc,1.5,-5,,²,{MAX_INT + 1},4"
        self.assertEqual(parse_id_list(raw), [4])

    def test_a_huge_digit_string_is_skipped_not_raised(self):
        # int() refuses more than 4300 digits outright
        self.assertEqual(parse_id_list("1" * 4400 + ",5"), [5])
        self.assertIsNone(parse_int("1" * 4400))

    def test_empty_values_give_an_empty_list(self):
        self.assertEqual(parse_id_list(None), [])
        self.assertEqual(parse_id_list(""), [])


class ParseLimitTests(SimpleTestCase):
    def test_clamps_to_the_range(self):
        self.assertEqual(parse_limit("0", default=5), 1)
        self.assertEqual(parse_limit("-5", default=5), 1)
        self.assertEqual(parse_limit("500", default=5), 20)
        self.assertEqual(parse_limit("500", default=5, maximum=50), 50)
        self.assertEqual(parse_limit("8", default=5), 8)

    def test_malformed_values_give_the_default(self):
        for raw in (None, "", "abc", "1.5"):
            with self.subTest(raw=raw):
                self.assertEqual(parse_limit(raw, default=5), 5)

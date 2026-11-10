"""`core.services.request_body`: a body of any shape, read without raising."""

from django.test import SimpleTestCase

from core.services.request_body import read_saved_filter


class ReadSavedFilterTests(SimpleTestCase):
    def test_a_well_formed_body(self):
        body = {"name": "  Rock  ", "filters": {"genres": [1]}}
        self.assertEqual(read_saved_filter(body), ("Rock", {"genres": [1]}))

    def test_filters_default_to_none_sent(self):
        self.assertEqual(read_saved_filter({"name": "Rock"}), ("Rock", {}))

    def test_a_number_is_a_name(self):
        self.assertEqual(read_saved_filter({"name": 1975}), ("1975", {}))
        self.assertEqual(read_saved_filter({"name": 19.5}), ("19.5", {}))

    def test_a_name_that_is_neither_text_nor_a_number_is_no_name(self):
        for name in (None, True, ["Rock"], {"n": 1}):
            with self.subTest(name=name):
                self.assertEqual(read_saved_filter({"name": name}), ("", {}))

    def test_filters_that_are_not_an_object_are_refused(self):
        for filters in (None, [1], "q=x", 5):
            with self.subTest(filters=filters):
                body = {"name": "Rock", "filters": filters}
                self.assertEqual(read_saved_filter(body), ("Rock", None))

    def test_a_body_that_is_not_an_object(self):
        for body in ([], ["name"], "name", 5, None):
            with self.subTest(body=body):
                self.assertEqual(read_saved_filter(body), ("", None))

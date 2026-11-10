"""The `tojson` filter is marked safe, so its output has to be."""

import json

from django.template import Context, Template
from django.test import SimpleTestCase

from core.templatetags.core_filters import tojson


class ToJsonTests(SimpleTestCase):
    def test_numbers_and_structures_are_plain_json(self):
        value = {"1990": 12, "bins": [1, 2.5, None, True]}
        self.assertEqual(json.loads(tojson(value)), value)
        self.assertEqual(tojson([1, 2]), "[1, 2]")

    def test_a_string_cannot_end_the_script_it_is_written_into(self):
        value = {"name": "</script><script>alert(1)</script>"}
        rendered = Template(
            '{% load core_filters %}<script type="application/json">'
            "{{ value|tojson }}</script>"
        ).render(Context({"value": value}))
        body = rendered[len('<script type="application/json">') : -len("</script>")]
        self.assertNotIn("<", body)
        self.assertEqual(json.loads(body), value)

    def test_a_string_cannot_end_the_attribute_it_is_written_into(self):
        value = ["it's", 'say "hi"', "a & b"]
        rendered = Template(
            "{% load core_filters %}<div data-bins='{{ value|tojson }}'></div>"
        ).render(Context({"value": value}))
        attribute = rendered[len("<div data-bins='") : -len("'></div>")]
        self.assertNotIn("'", attribute)
        self.assertNotIn("&", attribute)
        self.assertEqual(json.loads(attribute), value)

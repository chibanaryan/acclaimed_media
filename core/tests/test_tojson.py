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


class JsonForScriptTests(SimpleTestCase):
    """The same escapes for a view that serialises once and keeps the
    string: the developer page wrote four maps into a script body through
    bare ``json.dumps`` and ``|safe``."""

    def test_it_escapes_as_tojson_does_and_takes_decimals(self):
        from decimal import Decimal

        from core.templatetags.core_filters import json_for_script

        text = json_for_script({"1": {"pt": Decimal("12.5")}, "n": "</script>"})
        self.assertNotIn("<", text)
        self.assertEqual(json.loads(text), {"1": {"pt": "12.5"}, "n": "</script>"})

    def test_the_developer_page_serialises_through_it(self):
        from pathlib import Path

        from django.conf import settings

        source = (Path(settings.BASE_DIR) / "games/views/developers.py").read_text()
        self.assertNotIn("json.dumps(", source)
        self.assertEqual(source.count("= json_for_script("), 4)

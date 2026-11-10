"""The renderers' HTML escaper against Django's.

Client-rendered rows interpolate names into attributes as well as text:
``title="..."``, ``data-tip="..."``, ``aria-label="..."``, twenty-odd places.
The escaper went through ``textContent``, which leaves quotes alone, so a
name with one in it ended its attribute early: 'Bonnie "Prince" Billy' as a
title was ``title="Bonnie "``. One site worked around it by hand.
"""

import json
from django.test import SimpleTestCase
from django.utils.html import escape

from core.tests.node import require_node, run_node

CASES = [
    'Bonnie "Prince" Billy',
    "Guns N' Roses",
    "AC/DC <Live> & Loud",
    "a&amp;b",
    "plain",
    "",
]


class EscapeHtmlParityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_node()
        cls.output = run_node("escape_html.js", json.dumps(CASES + [None, 0, 1999]))

    def test_it_escapes_what_django_escapes_as_django_does(self):
        self.assertEqual(self.output[: len(CASES)], [escape(case) for case in CASES])

    def test_a_quote_cannot_end_an_attribute(self):
        for escaped in self.output:
            self.assertNotIn('"', escaped)
            self.assertNotIn("'", escaped)

    def test_nothing_is_an_empty_string_and_a_number_its_digits(self):
        self.assertEqual(self.output[len(CASES) :], ["", "", "1999"])

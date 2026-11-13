"""``core.tests.utils.select_all``: a selector that sees inside templates.

A plain ``select`` does not, from soupsieve 4.0. These hold on 3 as well,
which looked inside and would have found each match twice here."""

from bs4 import BeautifulSoup
from django.test import SimpleTestCase
from soupsieve import SelectorSyntaxError

from core.tests.utils import select_all

PAGE = """
<ul id="list">
  <template x-for="row in rows">
    <li class="row" data-n="1">
      <template x-if="row.open"><span class="row" data-n="2"></span></template>
    </li>
  </template>
  <li class="row" data-n="3"></li>
</ul>
<template id="clone"><li class="row" data-n="4"></li></template>
"""


class SelectAllTests(SimpleTestCase):
    def setUp(self):
        self.soup = BeautifulSoup(PAGE, "html.parser")

    def numbers(self, found):
        return [tag["data-n"] for tag in found]

    def test_it_finds_every_match_once_in_document_order(self):
        self.assertEqual(
            self.numbers(select_all(self.soup, ".row")), ["1", "2", "3", "4"]
        )

    def test_it_searches_below_the_element_it_is_given(self):
        found = select_all(self.soup.find(id="list"), ".row")
        self.assertEqual(self.numbers(found), ["1", "2", "3"])

    def test_it_starts_from_an_element_inside_a_template(self):
        row = select_all(self.soup, "li.row")[0]
        self.assertEqual(self.numbers(select_all(row, ".row")), ["2"])

    def test_a_selector_crosses_a_templates_edge(self):
        """An ancestor outside, the match inside: searching each template on
        its own found nothing, so an ``assertFalse`` over it always passed."""
        self.assertEqual(
            self.numbers(select_all(self.soup, "#list .row")), ["1", "2", "3"]
        )
        self.assertEqual(self.numbers(select_all(self.soup, "li .row")), ["2"])
        self.assertEqual(self.numbers(select_all(self.soup, "#clone .row")), ["4"])

    def test_a_selector_can_name_a_template(self):
        (found,) = select_all(self.soup, "template#clone")
        self.assertEqual(found.name, "template")

    def test_the_templates_keep_their_name(self):
        select_all(self.soup, ".row")
        self.assertEqual(len(self.soup.find_all("template")), 3)
        with self.assertRaises(SelectorSyntaxError):
            select_all(self.soup, "li >")  # a selector that does not parse
        self.assertEqual(len(self.soup.find_all("template")), 3)

    def test_nothing_matching_is_an_empty_list(self):
        self.assertEqual(select_all(self.soup, ".absent"), [])

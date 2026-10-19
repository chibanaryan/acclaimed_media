"""Tests for core.template_loaders: template indentation stripped at load."""

import re
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.template.loaders import filesystem
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core import template_loaders
from core.template_loaders import strip_indentation
from core.tests.utils import clear_all_caches
from games.models import Game


class StripIndentationTests(SimpleTestCase):
    def test_leading_spaces_and_tabs_are_removed(self):
        source = "<ul>\n    <li>A</li>\n\t\t<li>B</li>\n</ul>\n"
        self.assertEqual(
            strip_indentation(source), "<ul>\n<li>A</li>\n<li>B</li>\n</ul>\n"
        )

    def test_blank_lines_collapse_to_one_newline(self):
        source = "<p>A</p>\n\n    \n\t\n<p>B</p>\n"
        self.assertEqual(strip_indentation(source), "<p>A</p>\n<p>B</p>\n")

    def test_the_newline_between_inline_elements_survives(self):
        # It is what renders as the space between them; removing it would
        # join "A" and "B" into one word.
        source = "<a>A</a>\n        <a>B</a>"
        self.assertEqual(strip_indentation(source), "<a>A</a>\n<a>B</a>")

    def test_whitespace_inside_a_line_is_untouched(self):
        source = '<div>\n    <span class="a  b">x   y</span>'
        self.assertEqual(
            strip_indentation(source), '<div>\n<span class="a  b">x   y</span>'
        )


class LoaderTests(SimpleTestCase):
    def _contents(self, template_name, source):
        loader = template_loaders.FilesystemLoader(engine=mock.Mock())
        origin = SimpleNamespace(template_name=template_name)
        with mock.patch.object(filesystem.Loader, "get_contents", return_value=source):
            return loader.get_contents(origin)

    def test_html_templates_are_stripped(self):
        self.assertEqual(self._contents("a.html", "<p>\n    x\n</p>"), "<p>\nx\n</p>")

    def test_non_html_templates_are_left_as_written(self):
        # Email bodies and robots.txt are plain text, where indentation shows.
        source = "Hello,\n\n    indented\n"
        self.assertEqual(self._contents("email/body.txt", source), source)

    def test_preformatted_elements_are_left_as_written(self):
        for open_tag, close_tag in (
            ("<pre>", "</pre>"),
            ('<pre class="x">', "</pre>"),
            ("<PRE>", "</PRE>"),
            ('<textarea name="m">', "</textarea>"),
        ):
            with self.subTest(tag=open_tag):
                element = f"{open_tag}one\n    two\n\n  three{close_tag}"
                source = f"<div>\n    {element}\n    <p>x</p>\n</div>"
                self.assertEqual(
                    self._contents("a.html", source),
                    f"<div>\n{element}\n<p>x</p>\n</div>",
                )

    def test_text_after_a_preformatted_element_keeps_its_space(self):
        # The space after </pre> on the same line renders; only indentation
        # at the start of a line is removed.
        source = "<pre>a</pre> <span>b</span>\n    <i>c</i>"
        self.assertEqual(
            self._contents("a.html", source), "<pre>a</pre> <span>b</span>\n<i>c</i>"
        )

    def test_several_preformatted_elements(self):
        source = "<pre>\n  a</pre>\n    <p/>\n<textarea>\n  b</textarea>\n    <p/>"
        self.assertEqual(
            self._contents("a.html", source),
            "<pre>\n  a</pre>\n<p/>\n<textarea>\n  b</textarea>\n<p/>",
        )

    def test_both_settings_branches_use_the_stripping_loaders(self):
        # A dev server rendering unstripped pages would hide a template that
        # depends on its indentation until it reached production.
        loaders = settings.TEMPLATES[0]["OPTIONS"]["loaders"]
        flat = [
            name
            for entry in loaders
            for name in (entry[1] if isinstance(entry, tuple) else [entry])
        ]
        self.assertEqual(
            flat,
            [
                "core.template_loaders.FilesystemLoader",
                "core.template_loaders.AppDirectoriesLoader",
            ],
        )


class RenderedPageTests(TestCase):
    def setUp(self):
        clear_all_caches()

    def test_the_rankings_rows_carry_no_indentation(self):
        # The rows are where the bytes were: 100 games, two copies each.
        game = Game.objects.create(name="Indented", rank=1, slug="indented", igdb_id=1)
        html = self.client.get(reverse("home")).content.decode()
        start = html.index(f'id="game-{game.pk}"')
        rows = html[start : html.index("<template", start)]
        self.assertIn(f'id="game-{game.pk}-mobile"', rows)
        self.assertIsNone(re.search(r"^[ \t]+\S", rows, re.MULTILINE))

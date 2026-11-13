"""No style names a colour variable the theme does not define.

DaisyUI 4 published its colours as bare channel triples under short names
(`--bc`, `--b1`, `--p`), written `oklch(var(--bc) / 0.2)`. DaisyUI 5
publishes whole colours as `--color-base-content` and so on, and defines
none of the old names. A declaration that reads one is invalid, and the
browser drops it without a word.

Until 2026-11-12 thirty-six did. The sidebar's scrollbar took the
browser's colour, the rank chart's tooltip had no arrow, the untracked
star did not brighten on hover, and the staff import page's progress bar
had no fill, no track and no border.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)
SKIPPED_DIRS = {
    "node_modules",
    "staticfiles",
    "venv",
    "vendor",
    "dist",
    "tests",
    "migrations",
    ".context",
    ".git",
    ".claude",
}
# DaisyUI 4's names: base, primary, secondary, accent, neutral and the four
# states, each with its "-content", and the `--fallback-*` wrappers
OLD_NAME = re.compile(
    r"var\(\s*--(?:b[123c]|pc?|sc?|ac?|nc?|inc?|suc?|wac?|erc?|fallback-[a-z0-9]+)"
    r"\s*[,)]"
)


def sources():
    for pattern in ("*.html", "*.css", "*.js"):
        for path in BASE.rglob(pattern):
            if SKIPPED_DIRS.intersection(path.relative_to(BASE).parts):
                continue
            if path.name.endswith(".min.js"):
                continue
            yield path


class NoDaisyUiFourVariablesTests(SimpleTestCase):
    def test_no_source_reads_a_variable_daisyui_5_does_not_define(self):
        found = []
        for path in sources():
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if OLD_NAME.search(line):
                    found.append(f"{path.relative_to(BASE)}:{number}: {line.strip()}")
        self.assertEqual(found, [], "\n".join(found))

    def test_the_search_reads_the_pages_and_the_stylesheet(self):
        """A pattern that matches no file would pass the test above."""
        names = {path.relative_to(BASE).as_posix() for path in sources()}
        self.assertIn("theme/static_src/src/styles.css", names)
        self.assertIn("games/templates/import.html", names)
        self.assertIn("games/static/games/js/utils-base.js", names)

    def test_the_pattern_knows_the_old_names_and_not_the_new(self):
        for old in (
            "oklch(var(--bc) / 0.2)",
            "oklch(var(--b1))",
            "var(--fallback-b3, oklch(var(--b1)))",
            "hsl(var(--p))",
            "oklch(var(--suc))",
        ):
            with self.subTest(old=old):
                self.assertRegex(old, OLD_NAME)
        for new in (
            "var(--color-base-content)",
            "var(--color-primary)",
            "var(--heatmap-opacity)",
            "var(--tile-heat)",
            "var(--spacing)",
        ):
            with self.subTest(new=new):
                self.assertNotRegex(new, OLD_NAME)

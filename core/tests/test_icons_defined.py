"""Every icon class the site uses has a glyph mapped to it.

The icon font is a subset, and the only `.mdi-<name>::before` rules are the
inline ones in base.html (and their copy in mdi-subset.css, which the subset
build also reads). A class with no rule renders as nothing, with no error
anywhere: until 2026-11-10 fourteen did, among them the sign-up button's, the
email-verification screens', the source lists' "collapse all" and most of the
staff import page's.

This checks the mappings, not the font file: after adding one, rebuild the
font with scripts/build_mdi_subset.sh (.agent/skills/icons/SKILL.md).
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)
ICON = re.compile(r"\bmdi-[a-z0-9]+(?:-[a-z0-9]+)*")
RULE = re.compile(r"\.(mdi-[a-z0-9-]+)::before\s*\{\s*content:\s*\"\\([0-9A-Fa-f]+)\"")

# The books section is left as it is, and these directories hold no page.
SKIPPED_DIRS = {
    "books",
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
# Not icons: the font's own helper classes, and names in prose
NOT_ICONS = {"mdi-set", "mdi-subset"}


def _sources():
    for pattern in ("*.html", "*.js", "*.py"):
        for path in BASE.rglob(pattern):
            parts = set(path.relative_to(BASE).parts[:-1])
            if parts & SKIPPED_DIRS or path.name.endswith(".min.js"):
                continue
            yield path


def _used():
    used = {}
    for path in _sources():
        for name in ICON.findall(path.read_text(encoding="utf-8", errors="ignore")):
            used.setdefault(name, str(path.relative_to(BASE)))
    return used


class IconsAreDefinedTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base = (BASE / "games/templates/base.html").read_text(encoding="utf-8")
        cls.subset = (BASE / "games/static/games/css/mdi-subset.css").read_text(
            encoding="utf-8"
        )
        cls.styles = (BASE / "theme/static_src/src/styles.css").read_text(
            encoding="utf-8"
        )
        cls.defined = dict(RULE.findall(cls.base))

    def test_every_icon_class_in_use_has_a_rule(self):
        # An icon drawn in the stylesheet (mdi-record-plus, an SVG mask) or
        # given a size there needs no glyph
        drawn = set(re.findall(r"\.(mdi-[a-z0-9-]+)", self.styles))
        sizes = set(re.findall(r"\.(mdi-\d+px)", self.base))
        missing = {
            name: where
            for name, where in _used().items()
            if name not in self.defined
            and name not in drawn
            and name not in sizes
            and name not in NOT_ICONS
        }
        self.assertEqual(
            missing,
            {},
            "Icon classes with no rule in base.html, which render as nothing. "
            "Add each as .agent/skills/icons/SKILL.md describes.",
        )

    def test_the_sweep_sees_the_icons_it_is_there_for(self):
        """If the sweep's pattern or its directories break, it finds nothing
        and the test above passes on an empty set."""
        used = _used()
        for name in (
            "mdi-account-plus",  # a template's class attribute
            "mdi-unfold-less-horizontal",  # inside an Alpine :class expression
            "mdi-record-plus",  # a Python config value
            "mdi-check-circle-outline",  # a JavaScript renderer's string
        ):
            self.assertIn(name, used)

    def test_the_subset_file_lists_every_icon_the_page_defines(self):
        """It is "the subset's source mappings" (the icons skill), and had
        fallen 43 behind base.html. The font was right all along, since the
        build reads both, but the file said less than the page showed."""
        subset = dict(RULE.findall(self.subset))
        self.assertEqual(sorted(set(self.defined) - set(subset)), [])
        self.assertEqual(sorted(set(subset) - set(self.defined)), [])

    def test_the_subset_file_agrees_on_every_codepoint_it_repeats(self):
        """The build reads both files: a name mapped two ways is two glyphs,
        and the page shows base.html's."""
        differing = {
            name: (code, self.defined[name])
            for name, code in RULE.findall(self.subset)
            if name in self.defined and code.upper() != self.defined[name].upper()
        }
        self.assertEqual(differing, {})

    def test_no_codepoint_is_mapped_to_two_names(self):
        """A pasted line with the wrong codepoint shows another icon."""
        seen = {}
        for name, code in self.defined.items():
            seen.setdefault(code.upper(), []).append(name)
        self.assertEqual({c: n for c, n in seen.items() if len(n) > 1}, {})

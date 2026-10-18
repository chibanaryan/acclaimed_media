"""Tests for the client-side filtering bundles.

Two failures shipped in the books bundle and went unnoticed because nothing
tested either: the template referenced a filename the build script does not
write, and the bundle omitted the base class its renderer extends - which
throws a ReferenceError as the bundle loads, so nothing declared after that
point registers either. Both are checked here for every app at once, because
both are mistakes a reader cannot see.
"""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

TEMPLATE_DIRS = ["games", "books", "music", "core"]

# `{% static 'app/js/x.bundle.min.js' %}`, either quote style.
BUNDLE_REFERENCE = re.compile(
    r"""{%\s*static\s*['"]([^'"]+\.bundle\.min\.js)['"]\s*%}"""
)
CLASS_DECLARATION = re.compile(r"class\s+(\w+)(?:\s+extends\s+(\w+))?")


def _referenced_bundles():
    """Every bundle path referenced from a template, with its template."""
    found = []
    for app in TEMPLATE_DIRS:
        root = Path(settings.BASE_DIR) / app / "templates"
        if not root.exists():
            continue
        for template in root.rglob("*.html"):
            for match in BUNDLE_REFERENCE.finditer(template.read_text()):
                found.append((template, match.group(1)))
    return found


class ReferencedBundlesExistTests(SimpleTestCase):
    """A bundle a template asks for has to be a file that exists.

    Under production's manifest static storage, a `{% static %}` name missing
    from the manifest raises while rendering rather than 404ing, so a typo
    here takes the page down rather than degrading it.
    """

    def test_some_bundles_are_referenced(self):
        # Guards the regex: an empty sweep would make the test below vacuous.
        self.assertTrue(_referenced_bundles())

    def test_every_referenced_bundle_is_findable(self):
        for template, path in _referenced_bundles():
            with self.subTest(template=template.name, path=path):
                self.assertIsNotNone(
                    finders.find(path),
                    f"{template} references {path}, which no app serves. "
                    f"The name must match the bundle scripts/minify_js.sh "
                    f"writes.",
                )


class BundleContentsTests(SimpleTestCase):
    """A bundle must carry the base classes its own members extend."""

    def test_base_classes_are_declared_before_their_subclasses(self):
        bundles = {path for _, path in _referenced_bundles()}
        self.assertTrue(bundles)

        for path in sorted(bundles):
            with self.subTest(bundle=path):
                source = Path(finders.find(path)).read_text()
                positions = {}
                extends = []
                for match in CLASS_DECLARATION.finditer(source):
                    name, base = match.group(1), match.group(2)
                    positions.setdefault(name, match.start())
                    if base:
                        extends.append((name, base, match.start()))

                for name, base, at in extends:
                    self.assertIn(
                        base,
                        positions,
                        f"{path} declares `class {name} extends {base}` but "
                        f"never defines {base}: the bundle throws a "
                        f"ReferenceError on load. Add its file to this "
                        f"bundle's sources in scripts/minify_js.sh.",
                    )
                    self.assertLess(
                        positions[base],
                        at,
                        f"{path} defines {base} after {name} extends it; "
                        f"reorder the bundle sources so the base class "
                        f"comes first.",
                    )


class RowGenreClickReachesTheHeadingTests(SimpleTestCase):
    """A genre clicked in an album row has to reach the Alpine controls.

    `album-client-filtering.js` answers `add-genre` by writing the hidden
    `genres` select and re-rendering from the engine, which filters the list
    and pushes the URL. But `filters` lives on `mediaListControls`, and both
    the heading and the sidebar's genre tree are built from it - so setting
    the select alone filtered the list while the heading went on naming the
    unfiltered page. Reloading appeared to fix it, because the server then
    composed the heading from the URL.

    The two halves are in different files and neither reads the other, so
    this checks the event name still joins them up. A rename on one side
    only would leave the list filtering with a stale heading again, and
    nothing else in the suite would notice.
    """

    EVENT = "genres-selected"

    def _source(self, relative_path):
        path = Path(settings.BASE_DIR) / relative_path
        self.assertTrue(path.exists(), f"missing {relative_path}")
        return path.read_text()

    def test_the_row_handler_announces_the_selection(self):
        source = self._source("music/static/music/js/album-client-filtering.js")
        handler = source.split("'add-genre'", 1)
        self.assertEqual(len(handler), 2, "no add-genre handler to check")
        self.assertIn(
            self.EVENT,
            handler[1][:900],
            "the add-genre handler no longer announces the selection, so the "
            "heading and the genre tree will not follow it",
        )

    def test_the_controls_component_listens_and_updates_the_title(self):
        source = self._source("core/static/core/js/media-list-controls.js")
        self.assertIn(f"'{self.EVENT}'", source)
        listener = source.split("_genresSelectedListener = ", 1)
        self.assertEqual(len(listener), 2, "no listener to check")
        body = listener[1][:500]
        self.assertIn("filters.genres", body)
        self.assertIn("_applyTitle", body)

    def test_the_listener_is_registered_and_torn_down(self):
        source = self._source("core/static/core/js/media-list-controls.js")
        self.assertIn(f"addEventListener(\n                '{self.EVENT}'", source)
        self.assertIn(
            f"removeEventListener(\n                    '{self.EVENT}'", source
        )

    def test_the_minified_copies_carry_it(self):
        # The page loads the minified files, so a stale `.min.js` would ship
        # the bug with the fix sitting in the source beside it.
        for path in (
            "core/static/core/js/media-list-controls.min.js",
            "music/static/music/js/album-client-filtering.min.js",
            "music/static/music/js/music-client-side-filtering.bundle.min.js",
        ):
            with self.subTest(path=path):
                self.assertIn(self.EVENT, self._source(path))

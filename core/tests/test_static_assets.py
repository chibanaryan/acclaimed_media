"""Every minified script a template asks for has to exist.

`test_static_bundles.py` covers the `*.bundle.min.js` files, which is where
two silent failures had already shipped. The standalone minified scripts -
the Alpine subcomponents and the tracking listener, loaded outside any bundle
because they must run before Alpine - were not covered by anything: forget to
run `scripts/minify_js.sh` and the name resolves to nothing. Under
production's manifest static storage that *raises* while rendering rather than
404ing, so the page goes down rather than degrading.
"""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

TEMPLATE_DIRS = ["games", "books", "music", "core"]

# `{% static 'app/js/x.min.js' %}`, either quote style.
MIN_JS_REFERENCE = re.compile(r"""{%\s*static\s*['"]([^'"]+\.min\.js)['"]\s*%}""")


def _referenced_scripts():
    """Every minified script name referenced from a template, with its file."""
    found = []
    for app in TEMPLATE_DIRS:
        root = Path(settings.BASE_DIR) / app
        for template in root.rglob("*.html"):
            for path in MIN_JS_REFERENCE.findall(template.read_text()):
                found.append((template, path))
    return found


class ReferencedScriptsExistTests(SimpleTestCase):
    def test_some_scripts_are_referenced(self):
        # Guards the regex: an empty sweep would make the test below vacuous.
        self.assertTrue(_referenced_scripts())

    def test_every_referenced_script_is_findable(self):
        for template, path in _referenced_scripts():
            with self.subTest(template=template.name, path=path):
                self.assertIsNotNone(
                    finders.find(path),
                    f"{template} references {path}, which no app serves. "
                    f"Run scripts/minify_js.sh - the minified file is "
                    f"generated from its source and is not in git until then.",
                )

    def test_every_minified_script_has_a_source(self):
        # The other direction: a stale .min.js whose source was deleted or
        # renamed keeps working until someone edits the source that is gone.
        for template, path in _referenced_scripts():
            if ".bundle.min.js" in path:
                continue  # bundles are assembled, not minified from one file
            if "/vendor/" in path:
                continue  # third-party libraries ship minified already
            with self.subTest(path=path):
                found = finders.find(path)
                source = Path(found).with_suffix("").with_suffix(".js")
                self.assertTrue(source.exists(), f"{path} has no source at {source}")


# A quote or backtick, then a site-absolute static path: '/static/x.png'.
LITERAL_STATIC_PATH = re.compile(r"""['"`]/static/""")


class NoHardcodedStaticPathsTests(SimpleTestCase):
    """Static URLs go through ``{% static %}``, never a literal path.

    Production keeps only the content-hashed copies
    (``WHITENOISE_KEEP_ONLY_HASHED_FILES``), so ``/static/css/dist/styles.css``
    404s there while working in development and under test, which use plain
    storage. The admin article preview loaded its stylesheet that way.

    Books is left out: it is unlaunched, and its renderer's placeholder paths
    name a file that does not exist in any storage.
    """

    def _sources(self):
        for app in ("games", "core", "music"):
            root = Path(settings.BASE_DIR) / app
            for path in list(root.rglob("*.js")) + list(root.rglob("*.html")):
                if path.name.endswith(".min.js") or "vendor" in path.parts:
                    continue
                yield path

    def test_no_source_hardcodes_a_static_path(self):
        offenders = [
            str(path.relative_to(settings.BASE_DIR))
            for path in self._sources()
            if LITERAL_STATIC_PATH.search(path.read_text())
        ]
        self.assertEqual(offenders, [])

    def test_the_sweep_covers_the_admin_preview(self):
        # Guards the walk: the file that had the bug must be in it.
        names = {path.name for path in self._sources()}
        self.assertIn("markdown-preview.js", names)


class NoHandMaintainedCacheBustersTests(SimpleTestCase):
    """``{% static %}`` URLs carry no ``?v=N``.

    Production's manifest storage puts a content hash in every static name,
    so a changed file is already a new URL, and development serves static
    files with no max-age. The 22 hand-bumped literals did nothing but
    demand a bump, pinned by six tests, on every JavaScript change.
    """

    def test_no_template_appends_a_version(self):
        busted = re.compile(r"""{%\s*static\s*['"][^'"]+['"]\s*%}\?v=""")
        offenders = [
            str(template.relative_to(settings.BASE_DIR))
            for app in TEMPLATE_DIRS
            for template in (Path(settings.BASE_DIR) / app).rglob("*.html")
            if busted.search(template.read_text())
        ]
        self.assertEqual(offenders, [])

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

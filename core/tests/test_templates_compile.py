"""Every template the project ships parses.

A template's syntax error is found when something renders it, and not every
template is rendered by a test: an include behind a rare branch, an email,
an error page. Compiling costs nothing and names the file.
"""

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase

SUFFIXES = {".html", ".txt", ".xml"}


def project_templates():
    """``(app label, template name)`` for each template in the project's
    own apps, as a view or an include would name it."""
    base = Path(settings.BASE_DIR)
    for config in apps.get_app_configs():
        directory = Path(config.path) / "templates"
        if base not in directory.parents or not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in SUFFIXES:
                yield config.label, str(path.relative_to(directory))


class EveryTemplateCompilesTests(SimpleTestCase):
    def test_each_template_parses(self):
        names = list(project_templates())
        # A wrong walk that found none would pass as easily
        self.assertGreater(len(names), 100)
        for label, name in names:
            with self.subTest(app=label, template=name):
                get_template(name)

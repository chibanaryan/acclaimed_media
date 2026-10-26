"""Every model change has its migration."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase


class MissingMigrationsTests(TestCase):
    def test_no_model_change_is_missing_a_migration(self):
        """The release phase runs ``migrate``, which applies only what exists:
        a model field without its migration deploys cleanly and fails on the
        first query that touches it."""
        out = StringIO()
        try:
            call_command(
                "makemigrations", check=True, dry_run=True, stdout=out, stderr=out
            )
        except SystemExit:
            self.fail(f"Models have changes with no migration:\n{out.getvalue()}")

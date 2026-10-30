"""Rename the Sites framework's site to Acclaimed Media.

One name for the landing page, the games site and the music site. allauth
reads Site.name for the site name in its emails and pages, and it was still
"Acclaimed Video Games". Only a row with the old name is renamed, so a name
staff have changed in the admin is left alone.
"""

from django.db import migrations

NEW_NAME = "Acclaimed Media"
OLD_NAME = "Acclaimed Video Games"


def _rename(apps, old, new):
    apps.get_model("sites", "Site").objects.filter(name=old).update(name=new)


def forwards(apps, schema_editor):
    _rename(apps, OLD_NAME, NEW_NAME)


def backwards(apps, schema_editor):
    _rename(apps, NEW_NAME, OLD_NAME)


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0122_site_domain_acclaimedmedia"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

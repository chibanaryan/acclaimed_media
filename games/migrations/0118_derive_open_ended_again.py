"""
Re-derive ``HLTBGameData.is_open_ended`` after revising the calls in
``games/open_ended.py``: games whose HLTB data exists in production but was
missing from the copy the first list was drawn from (Escape from Tarkov,
Warhawk, FIFA 17, ...), and arcade sports with a finite ladder moved back to
showing their hours.
"""

from django.db import migrations

from games import open_ended


def derive_open_ended(apps, schema_editor):
    open_ended.derive_all(apps.get_model("games", "HLTBGameData"))


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0117_derive_open_ended"),
    ]

    operations = [
        migrations.RunPython(derive_open_ended, migrations.RunPython.noop),
    ]

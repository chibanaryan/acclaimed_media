"""
Re-derived ``HLTBGameData.is_open_ended`` after revising the calls in
``games/open_ended.py``. Superseded by 0120, which moved the calls onto the
records; it does nothing now.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0117_derive_open_ended"),
    ]

    operations = [
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]

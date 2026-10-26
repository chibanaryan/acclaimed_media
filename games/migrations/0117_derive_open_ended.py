"""
Derived ``HLTBGameData.is_open_ended`` from the editorial calls in
``games/open_ended.py``. Superseded: the calls now live on the records as
``open_ended_override`` (0120, which also re-derives every row), and the
module this imported is gone, so it does nothing.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0116_hltb_open_ended"),
    ]

    operations = [
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]

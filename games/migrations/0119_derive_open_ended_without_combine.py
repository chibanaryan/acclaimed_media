"""
Superseded by 0120 (which re-derives every row from the calls it moves onto
the records); its re-derivation is now a no-op. It still carries its
help-text change.

Re-derive ``HLTBGameData.is_open_ended`` now that ``comp_lvl_combine`` no
longer counts: production's first full HLTB refresh showed it marks any game
with a co-op or versus mode (Sam & Max, Gunstar Heroes, Dear Esther), so it
was hiding story games' playtimes. Adds Snake and the multiplayer-first
shooters (Battlefield 1942, Titanfall...), and lists the co-op story games
HLTB types "multi" (It Takes Two, Split Fiction, A Way Out) as finishable.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0118_derive_open_ended_again"),
    ]

    operations = [
        migrations.AlterField(
            model_name="hltbgamedata",
            name="open_ended_override",
            field=models.BooleanField(
                blank=True,
                help_text="Staff decision on whether the game has a finish line. "
                "Leave unknown to use the editorial calls in games/open_ended.py, "
                "then HLTB's game type.",
                null=True,
            ),
        ),
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]

"""
Derive ``HLTBGameData.is_open_ended`` for every existing row, now that the
editorial calls in ``games/open_ended.py`` exist. A historical model has no
custom ``save()``, so this restates ``HLTBGameData.derive_open_ended`` as
queries, applied lowest precedence first: HLTB's flags, then the calls, then
any staff override. ``games/tests/test_playtime.py`` checks the two agree.

Superseded: a list edit now needs no migration, because
``games.signals.rederive_open_ended`` runs ``open_ended.derive_all`` after
every ``migrate``.
"""

from django.db import migrations
from django.db.models import Q

from games import open_ended


def derive_open_ended(apps, schema_editor):
    rows = apps.get_model("games", "HLTBGameData").objects.all()
    rows.update(is_open_ended=False)
    rows.filter(
        Q(game_type__in=open_ended.OPEN_ENDED_GAME_TYPES) | Q(comp_lvl_combine=True)
    ).update(is_open_ended=True)
    rows.filter(igdb_id__in=open_ended.OPEN_ENDED_IGDB_IDS).update(is_open_ended=True)
    rows.filter(igdb_id__in=open_ended.FINISHABLE_IGDB_IDS).update(is_open_ended=False)
    for override in (True, False):
        rows.filter(open_ended_override=override).update(is_open_ended=override)


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0116_hltb_open_ended"),
    ]

    operations = [
        # Backwards there is nothing to undo: 0116's reverse drops the field
        migrations.RunPython(derive_open_ended, migrations.RunPython.noop),
    ]

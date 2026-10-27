from django.db import migrations, models
from unidecode import unidecode


def fill_normalized_names(apps, schema_editor):
    """unidecode(name).lower() for every existing row, as save() now does.

    Written out rather than imported from games.models, because a migration
    must keep working after the model code changes.
    """
    for model_name in ("Developer", "Series"):
        model = apps.get_model("games", model_name)
        rows = list(model.objects.only("id", "name"))
        for row in rows:
            # Cut to the column's 200: unidecode can lengthen CJK names
            row.name_normalized = unidecode(row.name or "").lower().strip()[:200]
        model.objects.bulk_update(rows, ["name_normalized"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0120_open_ended_calls_to_admin"),
    ]

    operations = [
        migrations.AddField(
            model_name="developer",
            name="name_normalized",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="series",
            name="name_normalized",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.RunPython(fill_normalized_names, migrations.RunPython.noop),
    ]

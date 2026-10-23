"""Artists from ArtistInfo.txt: provider ids, relations, ordered credits.

Django cannot add ``through=`` to an existing M2M, so the album's artists
move to the new ``AlbumCredit`` table by hand: create it, copy the old auto
table's rows into it, then swap the field. The copy keeps production's
albums credited between this migration and the reimport that follows it.

``Artist.parent`` goes: ``ArtistRelation`` replaces the single-parent tree,
and nothing but the admin ever set it.
"""

import django.db.models.deletion
from django.db import migrations, models


def copy_album_artists(apps, schema_editor):
    """Carry the old M2M rows over, numbered in the old (name) order."""
    Album = apps.get_model("music", "Album")
    AlbumCredit = apps.get_model("music", "AlbumCredit")
    through = Album.artists.through

    credits = []
    positions = {}
    rows = through.objects.order_by("album_id", "artist__name", "artist_id")
    for album_id, artist_id in rows.values_list("album_id", "artist_id"):
        position = positions.get(album_id, 0)
        positions[album_id] = position + 1
        credits.append(
            AlbumCredit(album_id=album_id, artist_id=artist_id, position=position)
        )
    AlbumCredit.objects.bulk_create(credits, batch_size=1000)


class Migration(migrations.Migration):

    dependencies = [
        ("music", "0007_listenedalbum_owned"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlbumCredit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("position", models.PositiveSmallIntegerField(default=0)),
                (
                    "album",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credits",
                        to="music.album",
                    ),
                ),
                (
                    "artist",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="album_credits",
                        to="music.artist",
                    ),
                ),
            ],
            options={
                "db_table": "music_albumcredit",
                "ordering": ["position", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="albumcredit",
            constraint=models.UniqueConstraint(
                fields=("album", "artist"), name="unique_album_credit"
            ),
        ),
        migrations.RunPython(copy_album_artists, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="album",
            name="artists",
        ),
        migrations.AddField(
            model_name="album",
            name="artists",
            field=models.ManyToManyField(
                blank=True,
                related_name="albums",
                through="music.AlbumCredit",
                to="music.artist",
            ),
        ),
        migrations.AlterField(
            model_name="album",
            name="artist_credit",
            field=models.CharField(
                blank=True,
                help_text=(
                    "The credited artists' names as one line, e.g. 'Paul "
                    "McCartney & Wings', or 'Various Artists'. Derived on "
                    "import from the artist ids; kept as text for search, "
                    "slugs, meta tags and the CSV export."
                ),
                max_length=300,
            ),
        ),
        migrations.RemoveField(
            model_name="artist",
            name="parent",
        ),
        migrations.AddField(
            model_name="artist",
            name="source_id",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="The data provider's permanent artist index (ArtistInfo.txt)",
                null=True,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="artist",
            name="slug",
            field=models.SlugField(
                blank=True,
                help_text="URL-friendly identifier, fixed once assigned",
                max_length=210,
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="ArtistRelation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("A", "Alias of"),
                            ("P", "Project of"),
                            ("C", "Collaboration with"),
                            ("F", "Featuring"),
                            ("B", "Backed by"),
                        ],
                        max_length=1,
                    ),
                ),
                (
                    "position",
                    models.PositiveSmallIntegerField(
                        default=0, help_text="Order of the tag in the file"
                    ),
                ),
                (
                    "artist",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="relations",
                        to="music.artist",
                    ),
                ),
                (
                    "related",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inbound_relations",
                        to="music.artist",
                    ),
                ),
            ],
            options={
                "db_table": "music_artistrelation",
                "ordering": ["artist", "position"],
            },
        ),
        migrations.AddConstraint(
            model_name="artistrelation",
            constraint=models.UniqueConstraint(
                fields=("artist", "related", "kind"), name="unique_artist_relation"
            ),
        ),
    ]

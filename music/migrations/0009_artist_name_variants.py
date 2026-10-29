"""Artist name variants replace the relation tags (the 2026-10-28 release).

ArtistInfo.txt now gives every artist its list of names, and a credit in
WebRankings.txt names the artist and which of those names it uses. So
"Prince and the Revolution" is no longer an artist tagged as a project of
Prince but Prince's second name, and ``ArtistRelation`` goes.

Existing credits get variant 0 and a blank name, meaning the artist's own,
which is what they were; the reimport that follows writes the real ones.
"""

from django.db import migrations, models


def fill_artist_names(apps, schema_editor):
    """Give every existing artist its one name and Wikidata id as lists."""
    Artist = apps.get_model("music", "Artist")

    artists = list(Artist.objects.all())
    for artist in artists:
        artist.name_variants = [artist.name]
        artist.all_wikidata_ids = [artist.wikidata_id] if artist.wikidata_id else []
    Artist.objects.bulk_update(
        artists, ["name_variants", "all_wikidata_ids"], batch_size=1000
    )


class Migration(migrations.Migration):

    dependencies = [
        ("music", "0008_artist_relations_and_album_credits"),
    ]

    operations = [
        migrations.DeleteModel(name="ArtistRelation"),
        migrations.AddField(
            model_name="artist",
            name="all_wikidata_ids",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Every Wikidata ID for this artist; the first is primary",
            ),
        ),
        migrations.AddField(
            model_name="artist",
            name="name_variants",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "Every name the release credits this artist under, in file "
                    "order; the first is the name. Some are unused by the "
                    "ranked albums"
                ),
            ),
        ),
        migrations.AddField(
            model_name="album",
            name="various_artists",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "The credit ends in 'Various Artists': a compilation, or a "
                    "soundtrack credited to an artist and others"
                ),
            ),
        ),
        migrations.AlterField(
            model_name="album",
            name="artist_credit",
            field=models.CharField(
                blank=True,
                help_text=(
                    "The credited names as one line, e.g. 'Paul McCartney and "
                    "Wings', 'Jimmy Cliff & Various Artists' or 'Various "
                    "Artists'. Derived on import from the credits; kept as text "
                    "for search, slugs, meta tags and the CSV export."
                ),
                max_length=300,
            ),
        ),
        migrations.AddField(
            model_name="albumcredit",
            name="variant",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Index into the artist's name variants; 0 is the name",
            ),
        ),
        migrations.AddField(
            model_name="albumcredit",
            name="credited_name",
            field=models.CharField(
                blank=True,
                help_text=(
                    "The name the album is credited under; blank is the " "artist's own"
                ),
                max_length=200,
            ),
        ),
        migrations.RunPython(fill_artist_names, migrations.RunPython.noop),
    ]

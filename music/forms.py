"""Forms for the music app."""

import csv
from io import TextIOWrapper

from django import forms

# Minimum column counts for each release file. The importer tolerates a
# missing trailing column (url on lists, wikidata ids on albums), so these
# are floors rather than exact counts.
ARTISTS_MIN_COLUMNS = 2
LISTS_MIN_COLUMNS = 3
ALBUMS_MIN_COLUMNS = 4


class MusicImportForm(forms.Form):
    """Upload the four album-ranking release files, or seed the bundled ones.

    Mirrors ``games.forms.ImportForm``, trimmed to what the music importer
    needs: there is no platforms file, and metadata fetching has no pipeline
    yet.
    """

    artists_file = forms.FileField(
        required=False,
        label="Artists (ArtistInfo.txt)",
        help_text="Tab-separated: id, name, tags (e.g. P:8,F:22), wikidata id",
    )
    lists_file = forms.FileField(
        required=False,
        label="Source Lists (ListData.txt)",
        help_text="Tab-separated: publisher, year, name, url",
    )
    albums_file = forms.FileField(
        required=False,
        label="Albums (WebRankings.txt)",
        help_text="Tab-separated: rank, name, artist ids, year, wikidata ids",
    )
    positions_file = forms.FileField(
        required=False,
        label="Album Positions (ListPositions.txt)",
        help_text=(
            "Tab-separated listIndex:position pairs, one row per album in " "rank order"
        ),
    )
    seed_bundled_data = forms.BooleanField(
        required=False,
        label="Use the bundled release files",
        help_text=(
            "Import from acclaimedgames/test_input_files/music/ instead of "
            "uploading. This is the current 1000-album release."
        ),
    )

    # Each is also ``import_handler.import_batch``'s keyword for that file.
    FILE_FIELDS = ("artists_file", "lists_file", "albums_file", "positions_file")

    def _validate_tsv_file(self, file_obj, min_columns):
        """Check the first row looks like TSV with enough columns."""
        if not file_obj:
            return

        try:
            file_obj.seek(0)
            wrapper = TextIOWrapper(file_obj, encoding="utf-8-sig")
            rows = csv.reader(wrapper, delimiter="\t")
            first_row = next(rows, None)

            if not first_row or not any(cell.strip() for cell in first_row):
                raise forms.ValidationError("File is empty.")

            if len(first_row) < min_columns:
                raise forms.ValidationError(
                    f"Invalid format: expected at least {min_columns} "
                    f"tab-separated columns, got {len(first_row)}."
                )

            wrapper.detach()
        except UnicodeDecodeError:
            raise forms.ValidationError("File must be UTF-8 encoded text.")
        finally:
            file_obj.seek(0)

    def clean_artists_file(self):
        file_obj = self.cleaned_data.get("artists_file")
        self._validate_tsv_file(file_obj, ARTISTS_MIN_COLUMNS)
        return file_obj

    def clean_lists_file(self):
        file_obj = self.cleaned_data.get("lists_file")
        self._validate_tsv_file(file_obj, LISTS_MIN_COLUMNS)
        return file_obj

    def clean_albums_file(self):
        file_obj = self.cleaned_data.get("albums_file")
        self._validate_tsv_file(file_obj, ALBUMS_MIN_COLUMNS)
        return file_obj

    def clean_positions_file(self):
        file_obj = self.cleaned_data.get("positions_file")
        # Column count varies by album, so only check it is not empty.
        if file_obj:
            file_obj.seek(0)
            first_line = file_obj.readline()
            file_obj.seek(0)
            if not first_line.strip():
                raise forms.ValidationError("File is empty.")
        return file_obj

    def clean(self):
        """Require either all four files or the bundled-data checkbox.

        A partial upload is rejected rather than half-applied: the four
        files are one release, positions are meaningless against a different
        set of lists or albums, and album credits against different artists.
        """
        cleaned = super().clean()
        if cleaned.get("seed_bundled_data"):
            return cleaned

        supplied = [field for field in self.FILE_FIELDS if cleaned.get(field)]
        if not supplied:
            raise forms.ValidationError(
                "Upload all four release files, or tick "
                "“Use the bundled release files”."
            )
        if len(supplied) != len(self.FILE_FIELDS):
            missing = [
                self.fields[field].label
                for field in self.FILE_FIELDS
                if not cleaned.get(field)
            ]
            raise forms.ValidationError(
                "All four files are imported together. Still missing: "
                + ", ".join(missing)
            )
        return cleaned

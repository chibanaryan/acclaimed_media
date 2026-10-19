"""
Derive each album's ``release_date`` from the metadata already stored.

The year sort orders by ``year_released`` and then, within a year, by this
date, so a year's albums read in the order they came out rather than by rank.
The year stays the published one: the heatmap, the decade pages and the row
all show ``year_released``, and a sort that let Wikidata's date move an album
into a neighbouring year would disagree with every one of them.

Two sources, in order:

* Wikidata P577, ``WikipediaAlbumData.release_date``. Already a date, at day
  or month precision (a month is stored as its first day); year-precision
  claims are dropped when they are fetched.
* MusicBrainz's ``first_release_date`` on the release group, a partial date
  string. A bare year adds nothing to ``year_released`` and is ignored. It
  also supplies the day when Wikidata knows only the month and agrees on it.

``release_date_precision`` says which: "day", "month", or blank when a
Wikidata row predates the precision being stored. The artist page shows
"May 16, 1966" only for "day" - the 1st of a month-precise date is not a day.

Like ``genre_rebuild``, this is an offline pass over stored rows, run at the
end of ``fetch_album_metadata``: no HTTP, one query and one bulk update.
"""

from datetime import date
from typing import Optional, Tuple

from django.utils import timezone

from music import models


Dated = Tuple[Optional[date], str]
UNDATED: Dated = (None, "")


def parse_partial_date(text: Optional[str]) -> Dated:
    """'1966-05-16' as a day, '1966-05' as a month; a bare year or junk as none."""
    parts = (text or "").split("-")
    if len(parts) not in (2, 3):
        return UNDATED
    try:
        numbers = [int(part) for part in parts]
        day = numbers[2] if len(numbers) == 3 else 1
        return date(numbers[0], numbers[1], day), (
            "day" if len(parts) == 3 else "month"
        )
    except ValueError:
        return UNDATED


def pick_release_date(wikidata_date, wikidata_precision, musicbrainz_text) -> Dated:
    """Wikidata's date when it has one, else MusicBrainz's.

    MusicBrainz's day is taken over a Wikidata date that is not day-precise
    only when the two agree on the month, so a disagreement keeps Wikidata.
    """
    musicbrainz = parse_partial_date(musicbrainz_text)
    if not wikidata_date:
        return musicbrainz
    if wikidata_precision != "day" and musicbrainz[1] == "day":
        if musicbrainz[0].replace(day=1) == wikidata_date.replace(day=1):
            return musicbrainz
    return wikidata_date, wikidata_precision


def refresh_release_dates() -> int:
    """Rewrite every album's ``release_date`` that has changed; return how many.

    ``modified`` is bumped on each changed album, by hand because
    ``bulk_update`` skips ``auto_now``: the client holds the ``all/`` payload
    under a version hashed from ``Max(modified)``, and would otherwise go on
    sorting by the dates it already had.
    """
    albums = models.Album.objects.select_related(
        "primary_wikipedia_album_data", "primary_musicbrainz_album_data"
    ).only(
        "release_date",
        "release_date_precision",
        "primary_wikipedia_album_data__release_date",
        "primary_wikipedia_album_data__release_date_precision",
        "primary_musicbrainz_album_data__first_release_date",
    )
    now = timezone.now()
    changed = []
    for album in albums:
        wikidata = album.primary_wikipedia_album_data
        musicbrainz = album.primary_musicbrainz_album_data
        picked = pick_release_date(
            wikidata.release_date if wikidata else None,
            wikidata.release_date_precision if wikidata else "",
            musicbrainz.first_release_date if musicbrainz else None,
        )
        if picked != (album.release_date, album.release_date_precision):
            album.release_date, album.release_date_precision = picked
            album.modified = now
            changed.append(album)
    models.Album.objects.bulk_update(
        changed,
        ["release_date", "release_date_precision", "modified"],
        batch_size=500,
    )
    return len(changed)

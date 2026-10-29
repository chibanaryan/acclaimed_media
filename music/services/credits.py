"""Album credits: the credit line, and which albums are whose.

A credit in ``WebRankings.txt`` names an artist and one of that artist's
name variants: Purple Rain is Prince's, credited as "Prince and the
Revolution". So an album belongs to exactly the artists it credits, under
whatever name, and no walk is needed to find an artist's albums - one
fetch of the credit table answers it for everybody. The table is about a
thousand rows, so nothing here is cached.
"""

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from django.db.models import F, Q

from music import config, models


def credit_separator(index: int, count: int) -> str:
    """The text before name ``index`` of ``count`` in a credit line.

    "A", "A & B", "A, B & C" - the house style for a joint credit, which
    ``credit_text``, the ``artist_links`` tag and the client renderer's
    ``_artistCreditHtml`` all follow.
    """
    if index == 0:
        return ""
    if index == count - 1:
        return " & "
    return ", "


def credit_text(names: List[str], various_artists: bool = False) -> str:
    """Join credited names into one line.

    ``various_artists`` adds "Various Artists" as the last name ("Jimmy
    Cliff & Various Artists"), and no names at all is a compilation, which
    reads "Various Artists" whether or not the flag says so.
    """
    if various_artists or not names:
        names = [*names, config.VARIOUS_ARTISTS]
    return "".join(
        credit_separator(index, len(names)) + name for index, name in enumerate(names)
    )


def artist_summary(albums_count: int) -> str:
    """How much of the ranking an artist accounts for: "1 album", "5 albums"."""
    return f"{albums_count} album{'' if albums_count == 1 else 's'}"


def artists_matching(q: str):
    """Artists named ``q``, or credited under a name that contains it.

    The one rule for an artist search, page and API alike: "Revolution"
    finds Prince through Purple Rain's credit. Only names a credit uses, as
    "Also credited as" shows.
    """
    return models.Artist.objects.filter(
        Q(name__icontains=q) | Q(album_credits__credited_name__icontains=q)
    ).distinct()


def album_ids_by_artist() -> Dict[int, Set[int]]:
    """Every credited artist's albums, from one query of the credit table."""
    result: Dict[int, Set[int]] = defaultdict(set)
    for artist_id, album_id in models.AlbumCredit.objects.values_list(
        "artist_id", "album_id"
    ):
        result[artist_id].add(album_id)
    return dict(result)


def split_by_credit(albums, artist_id: int) -> Tuple[list, list]:
    """``albums``, in their order, as credited to ``artist_id`` alone or with others.

    What the artist page lists apart under "With other artists": Getz/Gilberto
    on Stan Getz's. A various-artists tail names nobody else, so Jimmy Cliff's
    soundtrack is his alone. Reads the prefetched credits; no query.
    """
    solo, joint = [], []
    for album in albums:
        alone = all(credit.artist_id == artist_id for credit in album.credits.all())
        (solo if alone else joint).append(album)
    return solo, joint


def variant_names_by_artist(
    artist_ids: Optional[List[int]] = None,
) -> Dict[int, List[str]]:
    """The names other than their own that ranked albums credit artists as.

    "Also credited as" on an artist's page and row. Only the names a credit
    actually uses: the release keeps variants no ranked album carries (some
    leftovers, some for albums outside the ranking), and a name nobody can
    find an album under is no help to a reader. Best-ranked use first.
    """
    credits = models.AlbumCredit.objects.exclude(
        credited_name=F("artist__name")
    ).exclude(credited_name="")
    if artist_ids is not None:
        credits = credits.filter(artist_id__in=artist_ids)
    result: Dict[int, List[str]] = defaultdict(list)
    for artist_id, name in credits.order_by("album__rank", "position").values_list(
        "artist_id", "credited_name"
    ):
        if name not in result[artist_id]:
            result[artist_id].append(name)
    return dict(result)


def variant_names_of(artist_id: int) -> List[str]:
    """``variant_names_by_artist`` for one artist."""
    return variant_names_by_artist([artist_id]).get(artist_id, [])

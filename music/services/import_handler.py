"""
Import handler for the music rankings.

Ingests the three TSV files that make up an album ranking release:

- **lists**: ``publisher<TAB>year<TAB>name<TAB>url`` - one published list per
  row. Unlike the games equivalent there is no type column, so
  :func:`infer_list_type` derives it from the title.
- **albums**: ``rank<TAB>name<TAB>artist_credit<TAB>year<TAB>wikidata_ids`` -
  one album per row, already in aggregate rank order.
- **positions**: one row per album, in the same order as the albums file,
  holding tab-separated ``listIndex:position`` pairs. ``listIndex`` is
  0-based against the lists file, matching ``MusicList.order - 1``.

An import replaces everything: the files are the source of truth, exactly as
in ``games/services/import_handler.py``.
"""

import csv
import logging
import re
from typing import Callable, Dict, List, Optional, Tuple

from django.db import transaction
from django.utils.text import slugify

from core import constants as core_constants
from core.services.ranking import update_year_decade_ranks
from music import config, models

logger = logging.getLogger(__name__)

# Acts whose own name contains a comma, so the comma must not be read as a
# credit separator. Checked against the whole credit string before splitting.
ARTISTS_WITH_COMMAS = frozenset(
    {
        "Blood, Sweat & Tears",
        "Crosby, Stills & Nash",
        "Crosby, Stills, Nash & Young",
        "Earth, Wind & Fire",
        "Emerson, Lake & Palmer",
        "Peter, Paul and Mary",
    }
)

# Title patterns that pin a list to a type. Order matters: the first match
# wins, so the narrow decade and era patterns are tried before "all time".
_DECADE_PATTERNS = (
    r"\b(19|20)\d0s\b",  # "1990s", "2010s"
    r"\bof the (’|')?\d0s\b",  # "of the '90s", "of the 90s"
    r"\bof the decade\b",
    r"\b(eighties|nineties|seventies|sixties|fifties|aughts)\b",
    r"\bd(e|er) (\d0|\d0-?er)\b",  # "der 10-er Jahre"
    r"\bannées (19|20)\d0\b",  # "années 2010"
)

_ERA_PATTERNS = (
    r"\bpast \d+ years\b",
    r"\blast \d+ years\b",
    r"\b\d{4}\s*-\s*\d{4}\b",  # "1969 - 2009", "2000-2015"
    r"\b21st century\b",
    r"\blifetime\b",
    r"\bannées \d{4} ?- ?\d{4}\b",
)

_ALLTIME_PATTERNS = (
    r"\ball[- ]time\b",
    r"\bof all time\b",
    r"\balbums ever\b",
    r"\bever made\b",
    r"\bgreatest albums ever\b",
    r"\bmust hear before you die\b",
)


def infer_list_type(name: str) -> str:
    """Classify a list by its title into one of the shared type codes.

    The supplied lists file has no type column, so the title is all there is
    to go on. Decade and era wording is checked first because titles like
    "The 100 Best Albums of the 1990s" would otherwise be swallowed by a
    looser all-time match.

    An unqualified title ("Top 100 Albums", "Apple Music 100 Best Albums")
    falls back to all-time rather than end-of-year: every album list in this
    corpus is retrospective, and a ranking with no period in its name is
    making an all-time claim.

    Returns one of ``core.constants`` ``LIST_ALLTIME``, ``LIST_DECADE`` or
    ``LIST_MISC``.
    """
    haystack = (name or "").lower()

    for pattern in _DECADE_PATTERNS:
        if re.search(pattern, haystack):
            return core_constants.LIST_DECADE
    for pattern in _ERA_PATTERNS:
        if re.search(pattern, haystack):
            return core_constants.LIST_MISC
    for pattern in _ALLTIME_PATTERNS:
        if re.search(pattern, haystack):
            return core_constants.LIST_ALLTIME
    return core_constants.LIST_ALLTIME


def split_artist_credit(credit: str) -> List[str]:
    """Split a published credit into individual artist names.

    Commas usually separate collaborators (``Neil Young, Crazy Horse``) but
    sometimes belong to a single act (``Crosby, Stills & Nash``), so the whole
    string is checked against :data:`ARTISTS_WITH_COMMAS` first. The later
    Wikidata pass (P175) can correct anything this misses.
    """
    credit = (credit or "").strip()
    if not credit:
        return []
    if credit in ARTISTS_WITH_COMMAS:
        return [credit]

    names = []
    for part in credit.split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    return names


def _rows(file_obj) -> list:
    """Read a TSV file object into a list of non-empty rows."""
    reader = csv.reader(file_obj, delimiter="\t")
    return [row for row in reader if any(cell.strip() for cell in row)]


def import_lists(
    file_obj, progress_callback: Optional[Callable[[str, Dict], None]] = None
) -> Tuple[bool, str]:
    """Replace every list and publication from a TSV file.

    Columns: publisher, year, name, url. The type is inferred from the name.
    ``order`` is the 1-based row number and is the join key the positions
    file relies on, so row order is significant.
    """
    rows = _rows(file_obj)
    total = len(rows)

    if progress_callback:
        progress_callback("start", {"total": total, "file": "Source Lists"})

    lists_deleted = models.MusicList.objects.count()
    pubs_deleted = models.MusicPublication.objects.count()
    models.MusicList.objects.all().delete()
    models.MusicPublication.objects.all().delete()

    count = 0
    inferred = []
    for index, row in enumerate(rows):
        if len(row) < 3:
            raise ValueError(
                f"Lists row {index + 1} has {len(row)} columns, expected at "
                "least 3 (publisher, year, name[, url])"
            )
        publisher_name, year, name = (cell.strip() for cell in row[:3])
        url = row[3].strip() if len(row) > 3 else ""

        publisher, _ = models.MusicPublication.objects.get_or_create(
            name=publisher_name
        )
        list_type = infer_list_type(name)
        models.MusicList.objects.create(
            publisher=publisher,
            year=year,
            name=name,
            order=index + 1,
            url=url or None,
            type=list_type,
        )
        count += 1
        inferred.append((list_type, publisher_name, year, name))

        if progress_callback:
            progress_callback(
                "progress",
                {
                    "current": index + 1,
                    "total": total,
                    "list_name": name,
                    "type": list_type,
                },
            )

    if progress_callback:
        progress_callback(
            "complete",
            {
                "count": count,
                "lists_deleted": lists_deleted,
                "publications_deleted": pubs_deleted,
                "inferred": inferred,
            },
        )

    return (
        True,
        f"Lists: {count} created (deleted {lists_deleted} old); "
        f"Publications: recreated (deleted {pubs_deleted} old)",
    )


def import_albums(
    file_obj, progress_callback: Optional[Callable[[str, Dict], None]] = None
) -> Tuple[bool, str]:
    """Replace every album from a TSV file, then recompute derived ranks.

    Columns: rank, name, artist_credit, year, wikidata_ids (comma-separated,
    first is primary). Artists are created as needed from the credit.
    """
    rows = _rows(file_obj)
    total = len(rows)

    if progress_callback:
        progress_callback("start", {"total": total, "file": "Albums"})

    deleted_count = models.Album.objects.count()
    models.Album.objects.all().delete()

    artist_cache: Dict[str, models.Artist] = {}
    count = 0
    for index, row in enumerate(rows):
        if len(row) < 4:
            raise ValueError(
                f"Albums row {index + 1} has {len(row)} columns, expected at "
                "least 4 (rank, name, artist, year[, wikidata_ids])"
            )
        rank, name, artist_credit, year = (cell.strip() for cell in row[:4])
        wikidata_raw = row[4].strip() if len(row) > 4 else ""

        all_wikidata_ids = [x.strip() for x in wikidata_raw.split(",") if x.strip()]
        primary_wikidata_id = all_wikidata_ids[0] if all_wikidata_ids else None

        album = models.Album.objects.create(
            rank=int(rank),
            name=name,
            artist_credit=artist_credit,
            year_released=int(year) if year else None,
            wikidata_id=primary_wikidata_id,
            all_wikidata_ids=all_wikidata_ids,
        )

        artist_objs = []
        for artist_name in split_artist_credit(artist_credit):
            artist = artist_cache.get(artist_name)
            if artist is None:
                artist, _ = models.Artist.objects.get_or_create(
                    name=artist_name,
                    parent=None,
                    defaults={"slug": _unique_artist_slug(artist_name)},
                )
                artist_cache[artist_name] = artist
            artist_objs.append(artist)
        album.artists.set(artist_objs)
        count += 1

        if progress_callback:
            progress_callback(
                "progress",
                {"current": index + 1, "total": total, "album_name": name},
            )

    albums_ranked, years_processed = update_year_decade_ranks(
        models.Album, "music_album", "year_released"
    )

    if progress_callback:
        progress_callback(
            "complete",
            {
                "count": count,
                "deleted": deleted_count,
                "ranked": albums_ranked,
                "years": years_processed,
            },
        )

    return (
        True,
        f"Albums: {count} created (deleted {deleted_count} old), "
        f"{albums_ranked} ranks calculated",
    )


def _unique_artist_slug(name: str) -> str:
    """Slugify an artist name, adding a numeric tail on collision."""
    base = slugify(name) or "artist"
    if not models.Artist.objects.filter(slug=base).exists():
        return base
    suffix = 2
    while models.Artist.objects.filter(slug=f"{base}-{suffix}").exists():
        suffix += 1
    return f"{base}-{suffix}"


def import_listmemberships(
    file_obj, progress_callback: Optional[Callable[[str, Dict], None]] = None
) -> Tuple[bool, str]:
    """Replace every membership from the positions file.

    Row N holds the appearances of the album at aggregate rank N. Each cell
    is ``listIndex:position``, where ``listIndex`` is 0-based against the
    lists file and ``position`` is the album's place on that list (always 1
    for an unranked list). Indices with no matching list are skipped, which
    is how a positions file wider than its lists file degrades.
    """
    models.AlbumListMembership.objects.all().delete()

    list_map = {x.order: x for x in models.MusicList.objects.all()}
    album_map = {a.rank: a for a in models.Album.objects.all()}

    lines = [line for line in file_obj if line.strip()]
    total = len(lines)

    if progress_callback:
        progress_callback("start", {"total": total, "file": "Album Positions"})

    memberships = []
    total_created = 0
    skipped_lists = 0
    batch_size = config.IMPORT_BATCH_SIZE

    for line_number, line in enumerate(lines):
        album = album_map.get(line_number + 1)
        if album is None:
            raise ValueError(
                f"Positions row {line_number + 1} has no album at rank "
                f"{line_number + 1}; import the albums file first"
            )

        for cell in line.strip().split("\t"):
            cell = cell.strip()
            if not cell:
                continue
            list_index, position = (int(x) for x in cell.split(":"))
            source_list = list_map.get(list_index + 1)
            if not source_list:
                skipped_lists += 1
                continue
            memberships.append(
                models.AlbumListMembership(list=source_list, album=album, rank=position)
            )

        if len(memberships) >= batch_size:
            created = models.AlbumListMembership.objects.bulk_create(memberships)
            total_created += len(created)
            memberships.clear()

        if progress_callback:
            progress_callback(
                "progress",
                {"current": line_number + 1, "total": total},
            )

    if memberships:
        created = models.AlbumListMembership.objects.bulk_create(memberships)
        total_created += len(created)
        memberships.clear()

    if skipped_lists:
        logger.warning(
            "Skipped %s position(s) referencing a list index that is not in "
            "the lists file",
            skipped_lists,
        )

    if progress_callback:
        progress_callback(
            "complete", {"count": total_created, "skipped": skipped_lists}
        )

    return (True, f"Album list memberships: {total_created} created")


def import_batch(
    lists_file,
    albums_file,
    positions_file,
    progress_callback: Optional[Callable[[str, Dict], None]] = None,
) -> Tuple[bool, str]:
    """Run the three importers in dependency order, in one transaction.

    Lists must exist before positions can join against them, and albums
    before positions can find a row's album, so the order is fixed. Any
    failure rolls the whole import back rather than leaving the rankings
    half-replaced.
    """
    messages = []
    with transaction.atomic():
        _, message = import_lists(lists_file, progress_callback)
        messages.append(message)

        _, message = import_albums(albums_file, progress_callback)
        messages.append(message)

        if not models.MusicList.objects.exists():
            raise ValueError("No lists were imported; cannot import positions")
        if not models.Album.objects.exists():
            raise ValueError("No albums were imported; cannot import positions")

        _, message = import_listmemberships(positions_file, progress_callback)
        messages.append(message)

    return (True, " | ".join(messages))

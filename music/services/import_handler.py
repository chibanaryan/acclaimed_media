"""
Import handler for the music rankings.

Ingests the four TSV files that make up an album ranking release:

- **artists**: ``id<TAB>name<TAB>tags<TAB>wikidata_id`` - every artist under
  the data provider's own permanent index. ``tags`` is comma-separated
  ``KIND:id`` pairs naming how the artist is made up (``P:8``, a project of
  artist 8), with the kinds in ``ArtistRelation.KIND_CHOICES``; the Wikidata
  id may be blank, since not every act has one.
- **lists**: ``publisher<TAB>year<TAB>name<TAB>url`` - one published list per
  row. Unlike the games equivalent there is no type column, so
  :func:`infer_list_type` derives it from the title.
- **albums**: ``rank<TAB>name<TAB>artist_ids<TAB>year<TAB>wikidata_ids`` -
  one album per row, already in aggregate rank order. ``artist_ids`` are
  comma-separated indexes into the artists file, in credit order; blank for
  a various-artists compilation.
- **positions**: one row per album, in the same order as the albums file,
  holding tab-separated ``listIndex:position`` pairs. ``listIndex`` is
  0-based against the lists file, matching ``MusicList.order - 1``.

An import replaces everything: the files are the source of truth, exactly as
in ``games/services/import_handler.py``. Artists are the one table updated in
place rather than recreated, keyed on the provider's index, so their pks and
slugs - and every link to an artist page - survive an import.
"""

import csv
import logging
import re
from typing import Callable, Dict, List, Optional, Tuple

from django.db import transaction
from django.utils.text import slugify

from core import constants as core_constants
from core.services.ranking import update_year_decade_ranks
from games.models import SiteMetadata
from music import config, models
from music.services import user_tracking_service
from music.services.artist_graph import credit_text
from music.services.caching import invalidate_music_caches

logger = logging.getLogger(__name__)

#: Tokens that carry no distinguishing information in a band name.
_ARTIST_NOISE_TOKENS = frozenset({"the"})

_RELATION_KINDS = frozenset(kind for kind, _ in models.ArtistRelation.KIND_CHOICES)

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


def normalize_artist_name(name: str) -> str:
    """A comparison key for an artist name.

    Collapses the three ways the same act gets spelled across sources:
    ampersand against 'and', a leading or internal 'the', and punctuation.
    'Bob Marley & The Wailers' and 'Bob Marley and the Wailers' both become
    'bobmarleyandwailers'.
    """
    lowered = name.casefold().replace("&", " and ")
    tokens = re.split(r"[^a-z0-9]+", lowered)
    return "".join(
        token for token in tokens if token and token not in _ARTIST_NOISE_TOKENS
    )


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


def parse_artists_file(file_obj) -> List[Tuple[int, str, list, str]]:
    """Validate the artists file into ``(id, name, tags, wikidata_id)``.

    ``tags`` is a list of ``(kind, related_id)``. Everything is checked
    before anything is written, so a bad file names its first bad row
    instead of half-applying.
    """
    parsed = []
    seen = set()
    for index, row in enumerate(_rows(file_obj), start=1):
        if len(row) < 2:
            raise ValueError(
                f"Artists row {index} has {len(row)} columns, expected at "
                "least 2 (id, name[, tags, wikidata_id])"
            )
        raw_id, name = row[0].strip(), row[1].strip()
        tags_raw = row[2].strip() if len(row) > 2 else ""
        wikidata_id = row[3].strip() if len(row) > 3 else ""
        if not raw_id.isdigit():
            raise ValueError(f"Artists row {index}: id {raw_id!r} is not a number")
        source_id = int(raw_id)
        if source_id in seen:
            raise ValueError(f"Artists row {index}: id {source_id} appears twice")
        if not name:
            raise ValueError(f"Artists row {index}: artist {source_id} has no name")
        seen.add(source_id)

        tags = []
        for tag in filter(None, (t.strip() for t in tags_raw.split(","))):
            kind, _, target = tag.partition(":")
            kind, target = kind.strip().upper(), target.strip()
            if kind not in _RELATION_KINDS or not target.isdigit():
                raise ValueError(
                    f"Artists row {index}: tag {tag!r} on {name!r} is not "
                    f"KIND:id with KIND one of {', '.join(sorted(_RELATION_KINDS))}"
                )
            if int(target) == source_id:
                raise ValueError(
                    f"Artists row {index}: {name!r} is tagged as related to itself"
                )
            tags.append((kind, int(target)))
        parsed.append((source_id, name, tags, wikidata_id))

    for source_id, name, tags, _ in parsed:
        for kind, target in tags:
            if target not in seen:
                raise ValueError(
                    f"Artist {source_id} ({name}) is tagged {kind}:{target}, "
                    "but there is no artist with that id"
                )
    return parsed


def import_artists(
    file_obj, progress_callback: Optional[Callable[[str, Dict], None]] = None
) -> Tuple[bool, str]:
    """Upsert every artist and rebuild their relations from the artists file.

    Artists are matched on ``source_id``. A row that predates the provider's
    ids (the earlier releases named artists only in the credit text) is
    adopted on first sight by Wikidata id, then exact name, then a
    normalized name, so it keeps its pk and slug. An artist the file no
    longer lists is deleted, which also clears the leftovers of guessing
    artists from a credit string.

    A slug is assigned once and never rewritten, so a renamed act keeps its
    URL; staff can change it in the admin.
    """
    parsed = parse_artists_file(file_obj)
    total = len(parsed)

    if progress_callback:
        progress_callback("start", {"total": total, "file": "Artists"})

    existing = list(models.Artist.objects.all())
    by_source = {a.source_id: a for a in existing if a.source_id is not None}
    unclaimed = [a for a in existing if a.source_id is None]

    def adopt(name: str, wikidata_id: str) -> Optional[models.Artist]:
        key = normalize_artist_name(name)
        for matches in (
            lambda a: wikidata_id and a.wikidata_id == wikidata_id,
            lambda a: a.name == name,
            lambda a: key and normalize_artist_name(a.name) == key,
        ):
            for artist in unclaimed:
                if matches(artist):
                    unclaimed.remove(artist)
                    return artist
        return None

    created = 0
    artists_by_source: Dict[int, models.Artist] = {}
    for index, (source_id, name, _, wikidata_id) in enumerate(parsed, start=1):
        artist = by_source.get(source_id) or adopt(name, wikidata_id)
        if artist is None:
            artist = models.Artist(slug=_unique_artist_slug(name))
            created += 1
        if (artist.wikidata_id or "") != wikidata_id:
            # A different entity's MusicBrainz id would be wrong, not stale;
            # the next Wikidata pass reads the right one.
            artist.musicbrainz_id = None
        artist.source_id = source_id
        artist.name = name
        artist.wikidata_id = wikidata_id or None
        if not artist.slug:
            artist.slug = _unique_artist_slug(name)
        artist.save()
        artists_by_source[source_id] = artist

        if progress_callback:
            progress_callback(
                "progress", {"current": index, "total": total, "artist_name": name}
            )

    # `exclude` keeps NULL in the result, so this also drops every row the
    # file never claimed.
    _, deleted_by_model = models.Artist.objects.exclude(
        source_id__in=list(artists_by_source)
    ).delete()
    removed = deleted_by_model.get(models.Artist._meta.label, 0)

    models.ArtistRelation.objects.all().delete()
    relations = [
        models.ArtistRelation(
            artist=artists_by_source[source_id],
            related=artists_by_source[target],
            kind=kind,
            position=position,
        )
        for source_id, _, tags, _ in parsed
        for position, (kind, target) in enumerate(dict.fromkeys(tags))
    ]
    models.ArtistRelation.objects.bulk_create(relations)

    if progress_callback:
        progress_callback(
            "complete",
            {"count": total, "created": created, "relations": len(relations)},
        )

    return (
        True,
        f"Artists: {total} ({created} new, {removed} removed), "
        f"{len(relations)} relations",
    )


def _parse_artist_ids(cell: str, row_number: int) -> List[int]:
    """Column 3 of the albums file: comma-separated artist ids, or blank."""
    ids = []
    for part in filter(None, (p.strip() for p in cell.split(","))):
        if not part.isdigit():
            raise ValueError(
                f"Albums row {row_number}: column 3 should be artist ids from "
                f"ArtistInfo.txt, not {cell!r} (is this a pre-2026-10 release file?)"
            )
        if int(part) not in ids:
            ids.append(int(part))
    return ids


def import_albums(
    file_obj, progress_callback: Optional[Callable[[str, Dict], None]] = None
) -> Tuple[bool, str]:
    """Replace every album from a TSV file, then recompute derived ranks.

    Columns: rank, name, artist_ids, year, wikidata_ids (comma-separated,
    first is primary). The artist ids must already be imported by
    :func:`import_artists`; ``artist_credit`` is derived from their names.
    """
    rows = _rows(file_obj)
    total = len(rows)

    if progress_callback:
        progress_callback("start", {"total": total, "file": "Albums"})

    deleted_count = models.Album.objects.count()
    models.Album.objects.all().delete()

    artists_by_source = {
        a.source_id: a for a in models.Artist.objects.filter(source_id__isnull=False)
    }
    credits: List[models.AlbumCredit] = []
    # Every Wikidata id each album carries, for the tracking reconnection
    # pass below. Built here because the loop already has the ids parsed.
    id_to_album: Dict[str, models.Album] = {}
    count = 0
    for index, row in enumerate(rows):
        if len(row) < 4:
            raise ValueError(
                f"Albums row {index + 1} has {len(row)} columns, expected at "
                "least 4 (rank, name, artist_ids, year[, wikidata_ids])"
            )
        rank, name, artist_ids_raw, year = (cell.strip() for cell in row[:4])
        wikidata_raw = row[4].strip() if len(row) > 4 else ""

        artists = []
        for artist_id in _parse_artist_ids(artist_ids_raw, index + 1):
            artist = artists_by_source.get(artist_id)
            if artist is None:
                raise ValueError(
                    f"Albums row {index + 1} ({name}) credits artist "
                    f"{artist_id}, which is not in the artists file"
                )
            artists.append(artist)

        all_wikidata_ids = [x.strip() for x in wikidata_raw.split(",") if x.strip()]
        primary_wikidata_id = all_wikidata_ids[0] if all_wikidata_ids else None

        album = models.Album.objects.create(
            rank=int(rank),
            name=name,
            artist_credit=credit_text([artist.name for artist in artists]),
            year_released=int(year) if year else None,
            wikidata_id=primary_wikidata_id,
            all_wikidata_ids=all_wikidata_ids,
        )

        for wikidata_id in all_wikidata_ids:
            id_to_album[wikidata_id] = album

        credits.extend(
            models.AlbumCredit(album=album, artist=artist, position=position)
            for position, artist in enumerate(artists)
        )
        count += 1

        if progress_callback:
            progress_callback(
                "progress",
                {"current": index + 1, "total": total, "album_name": name},
            )

    models.AlbumCredit.objects.bulk_create(credits, batch_size=config.IMPORT_BATCH_SIZE)

    # The delete above orphaned every tracking row; re-adopt them by the
    # external id they kept. Guarded by one cheap query, because the common
    # case is a database where nobody has tracked anything yet.
    if (
        models.ListenedAlbum.objects.exists()
        or models.WantToListenAlbum.objects.exists()
    ):
        user_tracking_service.reconnect_tracking_records(id_to_album)

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
    artists_file,
    progress_callback: Optional[Callable[[str, Dict], None]] = None,
) -> Tuple[bool, str]:
    """Run the four importers in dependency order, in one transaction.

    Artists must exist before an album can be credited to them, lists before
    positions can join against them, and albums before positions can find a
    row's album, so the order is fixed. Any failure rolls the whole import
    back rather than leaving the rankings half-replaced.
    """
    messages = []
    with transaction.atomic():
        _, message = import_artists(artists_file, progress_callback)
        messages.append(message)

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

        # Stamp when the rankings were last replaced, which the album
        # rankings heading shows the way the games home page shows its own.
        SiteMetadata.stamp_update(config.SITE_METADATA_KEY)

    # Outside the transaction: the cached counts describe rows that no longer
    # exist, and dropping them inside would race a reader that repopulates
    # the cache from the pre-commit state.
    invalidate_music_caches()

    return (True, " | ".join(messages))

"""
Import handler for the music rankings.

Ingests the four TSV files that make up an album ranking release:

- **artists**: ``id<TAB>wikidata_ids<TAB>name<TAB>[variant...]`` - every
  artist under the data provider's own permanent index. ``wikidata_ids`` is
  comma-separated entity numbers without the ``Q`` (``7542,519725``), first
  primary, and may be blank. The names after it are the artist's name
  variants, the first being the name itself: Prince's row goes on with
  "Prince and the Revolution" and "Prince & the New Power Generation". The
  ids describe the artist, not the names, so there need not be one per name.
- **lists**: ``publisher<TAB>year<TAB>name<TAB>url`` - one published list per
  row. Unlike the games equivalent there is no type column, so
  :func:`infer_list_type` derives it from the title.
- **albums**: ``rank<TAB>name<TAB>credits<TAB>year<TAB>wikidata_ids`` - one
  album per row, already in aggregate rank order. ``credits`` is
  ``;``-separated, in credit order: each ``artist_id,variant``, indexes into
  the artists file and that artist's names (``8,1`` is Prince credited as
  "Prince and the Revolution"), then ``VA`` last for various artists - alone
  on a compilation.
- **positions**: one row per album, in the same order as the albums file,
  holding tab-separated ``listIndex:position`` pairs. ``listIndex`` is
  0-based against the lists file, matching ``MusicList.order - 1``.

The files are the source of truth, exactly as in
``games/services/import_handler.py``: lists, memberships and credits are
replaced outright. Artists and albums are updated in place instead -
artists keyed on the provider's index, albums on their Wikidata ids - so their
pks and slugs survive an import, and with an album's pk everything attached
to it: metadata, genres, covers and tracking rows.
"""

import csv
import logging
import re
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

from django.db import transaction
from django.utils.text import slugify

from core import constants as core_constants
from core.services.ranking import update_year_decade_ranks
from games.models import SiteMetadata
from music import config, models
from music.services import user_tracking_service
from music.services.credits import credit_text
from music.services.caching import invalidate_listen_caches, invalidate_music_caches

logger = logging.getLogger(__name__)

#: Tokens that carry no distinguishing information in a band name.
_ARTIST_NOISE_TOKENS = frozenset({"the"})

# Column 2 of the artists file: comma-separated Wikidata entity numbers, with
# or without their "Q". Anything else there is a pre-2026-10-28 file, whose
# second column was the name.
_ARTIST_QIDS = re.compile(r"^(Q?\d+)?(\s*,\s*Q?\d+)*$", re.IGNORECASE)

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
    # QUOTE_NONE: the files are plain TSV, and a title is quoted as written -
    # Bowie's "Heroes" kept its quotes only once csv stopped reading them as
    # field delimiters.
    reader = csv.reader(file_obj, delimiter="\t", quoting=csv.QUOTE_NONE)
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


class ArtistRow(NamedTuple):
    """One validated row of the artists file."""

    source_id: int
    names: List[str]
    wikidata_ids: List[str]


def _parse_qids(cell: str, row_number: int) -> List[str]:
    """Column 2 of the artists file as ``Q``-prefixed ids, first primary."""
    if not _ARTIST_QIDS.match(cell):
        raise ValueError(
            f"Artists row {row_number}: column 2 should be Wikidata ids, not "
            f"{cell!r} (is this a pre-2026-10-28 release file, with the name "
            "second?)"
        )
    qids = []
    for part in filter(None, (p.strip() for p in cell.split(","))):
        qid = "Q" + part.upper().lstrip("Q")
        if qid not in qids:
            qids.append(qid)
    return qids


def parse_artists_file(file_obj) -> List[ArtistRow]:
    """Validate the artists file into rows, before anything is written.

    Everything is checked first, so a bad file names its first bad row
    instead of half-applying.
    """
    parsed = []
    seen = set()
    for index, row in enumerate(_rows(file_obj), start=1):
        if len(row) < 3:
            raise ValueError(
                f"Artists row {index} has {len(row)} columns, expected at "
                "least 3 (id, wikidata_ids, name[, variants...])"
            )
        raw_id = row[0].strip()
        if not raw_id.isdigit():
            raise ValueError(f"Artists row {index}: id {raw_id!r} is not a number")
        source_id = int(raw_id)
        if source_id in seen:
            raise ValueError(f"Artists row {index}: id {source_id} appears twice")
        seen.add(source_id)
        wikidata_ids = _parse_qids(row[1].strip(), index)
        # Kept positionally: a credit's variant is an index into these, so
        # a blank or repeated name still holds its place.
        names = [cell.strip() for cell in row[2:]]
        while len(names) > 1 and not names[-1]:
            names.pop()
        if not names[0]:
            raise ValueError(f"Artists row {index}: artist {source_id} has no name")
        parsed.append(
            ArtistRow(source_id=source_id, names=names, wikidata_ids=wikidata_ids)
        )
    return parsed


def import_artists(
    file_obj, progress_callback: Optional[Callable[[str, Dict], None]] = None
) -> Tuple[bool, str]:
    """Upsert every artist, with their name variants, from the artists file.

    Artists are matched on ``source_id``. A row that predates the provider's
    ids (the earlier releases named artists only in the credit text) is
    adopted on first sight by any of its Wikidata ids, then exact name, then
    a normalized name, so it keeps its pk and slug. An artist the file no
    longer lists is deleted - including the acts an earlier release listed
    separately and this one folds into another's variants, such as Prince
    and the Revolution.

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

    def adopt(name: str, wikidata_ids: List[str]) -> Optional[models.Artist]:
        key = normalize_artist_name(name)
        for matches in (
            lambda a: set(a.all_wikidata_ids or [a.wikidata_id]) & set(wikidata_ids),
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
    for index, row in enumerate(parsed, start=1):
        name = row.names[0]
        artist = by_source.get(row.source_id) or adopt(name, row.wikidata_ids)
        if artist is None:
            artist = models.Artist(slug=_unique_artist_slug(name))
            created += 1
        primary = row.wikidata_ids[0] if row.wikidata_ids else None
        if artist.wikidata_id != primary:
            # A different entity's MusicBrainz id would be wrong, not stale;
            # the next Wikidata pass reads the right one.
            artist.musicbrainz_id = None
        artist.source_id = row.source_id
        artist.name = name
        artist.name_variants = row.names
        artist.wikidata_id = primary
        artist.all_wikidata_ids = row.wikidata_ids
        if not artist.slug:
            artist.slug = _unique_artist_slug(name)
        artist.save()
        artists_by_source[row.source_id] = artist

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

    variants = sum(len(row.names) - 1 for row in parsed)
    if progress_callback:
        progress_callback(
            "complete",
            {"count": total, "created": created, "variants": variants},
        )

    return (
        True,
        f"Artists: {total} ({created} new, {removed} removed), "
        f"{variants} name variants",
    )


def _parse_credits(cell: str, row_number: int) -> Tuple[List[Tuple[int, int]], bool]:
    """Column 3 of the albums file: ``(artist_id, variant)`` pairs, and VA.

    ``8,1;56,0`` credits artist 8 under its second name, then artist 56 under
    its own; a ``VA`` token adds "Various Artists". An artist named twice
    keeps its first credit.
    """
    credits: List[Tuple[int, int]] = []
    various_artists = False
    for token in filter(None, (t.strip() for t in cell.split(";"))):
        if various_artists:
            raise ValueError(
                f"Albums row {row_number}: {config.VARIOUS_ARTISTS_TOKEN} must be "
                f"the last credit, not followed by {token!r} in {cell!r}"
            )
        if token.upper() == config.VARIOUS_ARTISTS_TOKEN:
            various_artists = True
            continue
        artist_id, _, variant = (part.strip() for part in token.partition(","))
        if not (artist_id.isdigit() and variant.isdigit()):
            raise ValueError(
                f"Albums row {row_number}: column 3 should be artist_id,variant "
                f"pairs separated by ';', or VA, not {cell!r} (is this a "
                "pre-2026-10-28 release file?)"
            )
        if all(int(artist_id) != credited for credited, _ in credits):
            credits.append((int(artist_id), int(variant)))
    if not credits and not various_artists:
        raise ValueError(
            f"Albums row {row_number}: column 3 credits nobody; a compilation "
            f"is credited {config.VARIOUS_ARTISTS_TOKEN}"
        )
    return credits, various_artists


class AlbumRow(NamedTuple):
    """One validated row of the albums file."""

    rank: int
    name: str
    credits: List[Tuple[int, int]]
    various_artists: bool
    year: Optional[int]
    wikidata_ids: List[str]


class AlbumMatch(NamedTuple):
    """How an albums file lines up against the albums already stored."""

    kept: List[Tuple[AlbumRow, models.Album]]
    added: List[AlbumRow]
    removed: List[models.Album]


def parse_albums_file(file_obj) -> List[AlbumRow]:
    """Validate the albums file into rows, before anything is written.

    Columns: rank, name, credits, year, wikidata_ids (comma-separated, first
    is primary). Whether the credited artists and their variants exist is
    checked by :func:`import_albums`, since that needs the database.
    """
    parsed = []
    for index, row in enumerate(_rows(file_obj), start=1):
        if len(row) < 4:
            raise ValueError(
                f"Albums row {index} has {len(row)} columns, expected at "
                "least 4 (rank, name, credits, year[, wikidata_ids])"
            )
        rank, name, credits_raw, year = (cell.strip() for cell in row[:4])
        wikidata_raw = row[4].strip() if len(row) > 4 else ""
        credits, various_artists = _parse_credits(credits_raw, index)
        parsed.append(
            AlbumRow(
                rank=int(rank),
                name=name,
                credits=credits,
                various_artists=various_artists,
                year=int(year) if year else None,
                wikidata_ids=[x.strip() for x in wikidata_raw.split(",") if x.strip()],
            )
        )
    return parsed


def match_albums(rows: List[AlbumRow], existing) -> AlbumMatch:
    """Pair each row with the stored album it describes, by Wikidata id.

    A row claims the first album found under any of its ids, primary first,
    and an album can be claimed once: a release that splits one album into
    two rows keeps the album for the first and creates the second, rather
    than having both write to one row. A row without an id cannot be
    matched, so it is always new. Nothing is written.
    """
    by_qid: Dict[str, models.Album] = {}
    for album in existing:
        for qid in album.wikidata_qids:
            by_qid.setdefault(qid, album)

    claimed = set()
    kept, added = [], []
    for row in rows:
        album = next(
            (
                by_qid[qid]
                for qid in row.wikidata_ids
                if qid in by_qid and by_qid[qid].pk not in claimed
            ),
            None,
        )
        if album is None:
            added.append(row)
        else:
            claimed.add(album.pk)
            kept.append((row, album))

    removed = [album for album in existing if album.pk not in claimed]
    return AlbumMatch(kept=kept, added=added, removed=removed)


def credit_errors(rows: List[AlbumRow], names_by_source: Dict[int, List[str]]):
    """Every credit in ``rows`` naming an artist or a name that is not there.

    ``names_by_source`` is each artist's names by provider id. The import
    raises on the first; ``--dry-run`` lists them all.
    """
    errors = []
    for index, row in enumerate(rows, start=1):
        for artist_id, variant in row.credits:
            names = names_by_source.get(artist_id)
            if names is None:
                errors.append(
                    f"Albums row {index} ({row.name}) credits artist "
                    f"{artist_id}, which is not in the artists file"
                )
            elif variant >= len(names) or not names[variant]:
                errors.append(
                    f"Albums row {index} ({row.name}) credits artist "
                    f"{artist_id} ({names[0]}) as name {variant}, but the "
                    f"artists file gives it {len(names)} name(s), numbered from 0"
                )
    return errors


def import_albums(
    file_obj, progress_callback: Optional[Callable[[str, Dict], None]] = None
) -> Tuple[bool, str]:
    """Upsert every album from a TSV file, then recompute derived ranks.

    Albums are matched on Wikidata id (:func:`match_albums`). A matched album
    is updated in place - rank, name, year, ids and credits - so it keeps
    its pk and slug, and with them its metadata rows, genres, release date,
    covers and tracking rows: a new release needs no metadata refresh for
    the albums it shares with the last one. An album the file no longer
    lists is deleted, and a new one created.

    The artists must already be imported by :func:`import_artists`; each
    credit's name is the variant it names, and ``artist_credit`` is those
    names joined.
    """
    rows = parse_albums_file(file_obj)
    total = len(rows)

    if progress_callback:
        progress_callback("start", {"total": total, "file": "Albums"})

    artists_by_source = {
        a.source_id: a for a in models.Artist.objects.filter(source_id__isnull=False)
    }
    errors = credit_errors(
        rows,
        {
            source_id: artist.name_variants or [artist.name]
            for source_id, artist in artists_by_source.items()
        },
    )
    if errors:
        raise ValueError(errors[0])
    # (artist, variant, the name it is credited as) per row; `credit_errors`
    # has checked every variant exists.
    row_credits: Dict[int, List[Tuple[models.Artist, int, str]]] = {}
    for index, row in enumerate(rows, start=1):
        row_credits[index] = []
        for artist_id, variant in row.credits:
            artist = artists_by_source[artist_id]
            name = artist.name_variants[variant] if variant else artist.name
            row_credits[index].append((artist, variant, name))

    match = match_albums(rows, list(models.Album.objects.all()))

    # Deleted first, so a new album can take a removed one's slug. Their
    # tracking rows survive on SET_NULL; the users' cached id sets would
    # still name the deleted pks, so those are dropped below.
    orphaned_users = set()
    if match.removed:
        removed_pks = [album.pk for album in match.removed]
        for model_class in (models.ListenedAlbum, models.WantToListenAlbum):
            orphaned_users.update(
                model_class.objects.filter(album_id__in=removed_pks).values_list(
                    "user_id", flat=True
                )
            )
        models.Album.objects.filter(pk__in=removed_pks).delete()

    # Keyed on identity: each parsed row is its own object, and two rows may
    # be equal (a release listing one album twice).
    kept_by_row = {id(row): album for row, album in match.kept}
    models.AlbumCredit.objects.filter(
        album__in=[album for _, album in match.kept]
    ).delete()

    credits: List[models.AlbumCredit] = []
    # Every Wikidata id each album carries, for the tracking reconnection
    # pass below. Built here because the loop already has the ids parsed.
    id_to_album: Dict[str, models.Album] = {}
    for index, row in enumerate(rows, start=1):
        credited = row_credits[index]
        album = kept_by_row.get(id(row)) or models.Album()
        album.rank = row.rank
        album.name = row.name
        # MediaItemBase.save sets this only for a name with non-ASCII in it,
        # so a kept album renamed to plain ASCII would keep its old one.
        album.name_normalized = None
        album.artist_credit = credit_text(
            [name for _, _, name in credited], row.various_artists
        )
        album.various_artists = row.various_artists
        album.year_released = row.year
        album.wikidata_id = row.wikidata_ids[0] if row.wikidata_ids else None
        album.all_wikidata_ids = row.wikidata_ids
        # The slug is built only when empty, so a kept album's URL never
        # changes, renamed or not.
        album.save()

        for wikidata_id in row.wikidata_ids:
            id_to_album[wikidata_id] = album

        credits.extend(
            models.AlbumCredit(
                album=album,
                artist=artist,
                position=position,
                variant=variant,
                # Blank for the artist's own name, which then follows a
                # rename in the admin rather than freezing the old one.
                credited_name=name if variant else "",
            )
            for position, (artist, variant, name) in enumerate(credited)
        )

        if progress_callback:
            progress_callback(
                "progress",
                {"current": index, "total": total, "album_name": row.name},
            )

    models.AlbumCredit.objects.bulk_create(credits, batch_size=config.IMPORT_BATCH_SIZE)

    # Kept albums keep their tracking rows outright. This pass is the safety
    # net for the rest: a row orphaned when its album left an earlier
    # release and has now come back, or one stored under a secondary id.
    # Guarded by one cheap query, because the common case is a database
    # where nobody has tracked anything yet.
    if (
        models.ListenedAlbum.objects.exists()
        or models.WantToListenAlbum.objects.exists()
    ):
        user_tracking_service.reconnect_tracking_records(id_to_album)

    for user_id in orphaned_users:
        invalidate_listen_caches(user_id)

    albums_ranked, years_processed = update_year_decade_ranks(
        models.Album, "music_album", "year_released"
    )

    kept, added, removed = len(match.kept), len(match.added), len(match.removed)
    if progress_callback:
        progress_callback(
            "complete",
            {
                "count": total,
                "kept": kept,
                "added": added,
                "removed": removed,
                "ranked": albums_ranked,
                "years": years_processed,
            },
        )

    return (
        True,
        f"Albums: {total} ({kept} kept, {added} added, {removed} removed), "
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

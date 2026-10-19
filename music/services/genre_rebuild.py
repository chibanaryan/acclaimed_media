"""
Rebuild every album's genres from the metadata already stored.

Genres used to be written one album at a time, as the Discogs pass fetched
each master. Two of the rules in ``genre_normalizer`` cannot work that way:
the sources vote, so an album's genres depend on all three of its rows, and
rare leaves are pruned, which needs a count across the whole corpus. So the
passes now only store what they fetch, and this module turns the stored
``DiscogsAlbumData``, ``WikipediaAlbumData`` and ``MusicBrainzAlbumData`` rows
into genres in one offline pass. It makes no HTTP requests, so a change to the
vocabulary can be tried, reported on, and applied in seconds.

Genre ids are visible outside the database - in ``?genres=`` URLs and in
``SavedAlbumFilterSet.filters`` - so the rebuild works to keep them:

* a row whose name is an alias of a vocabulary leaf ("Glam" for "Glam Rock")
  is **renamed** rather than replaced, so its id carries over;
* a saved filter pointing at a row that is deleted is **remapped** to the
  genre that row's name now means, or failing that to its old root.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.text import slugify

from music import models
from music.services import caching
from music.services import genre_normalizer as gn

logger = logging.getLogger(__name__)


@dataclass
class RebuildReport:
    """What a rebuild did, or would do on a dry run."""

    albums: int = 0
    dry_run: bool = False
    #: album id -> (name, genre names before, genre names after)
    changed: Dict[int, Tuple[str, List[str], List[str]]] = field(default_factory=dict)
    leaves_before: int = 0
    leaves_after: int = 0
    single_album_leaves_before: int = 0
    single_album_leaves_after: int = 0
    albums_without_genres: int = 0
    genres_per_album: float = 0.0
    pruned: Dict[str, int] = field(default_factory=dict)
    #: (source, label) -> how many albums carry it
    unclassified: Counter = field(default_factory=Counter)
    renamed: List[Tuple[str, str]] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    saved_filters_remapped: int = 0

    def summary(self) -> str:
        verb = "would change" if self.dry_run else "changed"
        return (
            f"{self.albums} albums, {len(self.changed)} {verb}; "
            f"leaves {self.leaves_before} -> {self.leaves_after}, "
            f"single-album leaves {self.single_album_leaves_before} -> "
            f"{self.single_album_leaves_after}"
        )


def _primary(rows, primary_id):
    """The album's primary row of one source, or its first."""
    rows = list(rows)
    for row in rows:
        if row.pk == primary_id:
            return row
    return rows[0] if rows else None


def _split(joined: Optional[str]) -> List[str]:
    return [label.strip() for label in (joined or "").split(",") if label.strip()]


def album_votes(album) -> List[gn.SourceVotes]:
    """Each source's vote for one album, in priority order.

    Expects the three metadata sets to be prefetched, as ``plan_genres``
    does; on a bare album it costs three queries.
    """
    votes = []

    discogs = _primary(
        album.discogs_album_data_set.all(), album.primary_discogs_album_data_id
    )
    if discogs is not None:
        votes.append(gn.discogs_votes(discogs.styles, discogs.genres))

    wikidata = _primary(
        album.wikipedia_album_data_set.all(), album.primary_wikipedia_album_data_id
    )
    if wikidata is not None:
        votes.append(gn.votes_from_labels("wikidata", _split(wikidata.all_genres)))

    musicbrainz = _primary(
        album.musicbrainz_album_data_set.all(),
        album.primary_musicbrainz_album_data_id,
    )
    if musicbrainz is not None:
        labels = _split(musicbrainz.all_genres)[: gn.MAX_MUSICBRAINZ_GENRES]
        votes.append(gn.votes_from_labels("musicbrainz", labels))

    return votes


def plan_genres():
    """Choose every album's genres, without writing anything.

    Returns ``(albums, assignments, pruned, unclassified)``: the albums with
    their current genres prefetched, album id -> ``AlbumGenres`` after
    pruning, the pruned leaves with their counts, and the labels no part of
    the vocabulary classifies.
    """
    albums = list(
        models.Album.objects.order_by("rank").prefetch_related(
            "genres",
            "discogs_album_data_set",
            "wikipedia_album_data_set",
            "musicbrainz_album_data_set",
        )
    )

    assignments = {}
    unclassified = Counter()
    for album in albums:
        votes = album_votes(album)
        for source in votes:
            for label in source.unclassified:
                unclassified[(source.name, label)] += 1
        assignments[album.id] = gn.choose_album_genres(votes)

    assignments, pruned = gn.prune_rare_leaves(assignments, gn.MIN_LEAF_ALBUMS)
    return albums, assignments, pruned, unclassified


def rebuild_album_genres(dry_run: bool = False) -> RebuildReport:
    """Recompute and (unless ``dry_run``) store every album's genres."""
    albums, assignments, pruned, unclassified = plan_genres()

    report = RebuildReport(
        albums=len(albums),
        dry_run=dry_run,
        pruned=pruned,
        unclassified=unclassified,
    )

    current_counts = Counter(
        genre.name for album in albums for genre in album.genres.all() if genre.level
    )
    report.leaves_before = len(current_counts)
    report.single_album_leaves_before = sum(
        1 for count in current_counts.values() if count == 1
    )

    after_counts = Counter(
        leaf for genres in assignments.values() for leaf in genres.leaves
    )
    report.leaves_after = len(after_counts)
    report.single_album_leaves_after = sum(
        1 for count in after_counts.values() if count == 1
    )
    report.albums_without_genres = sum(
        1 for genres in assignments.values() if not genres.names
    )
    if albums:
        report.genres_per_album = sum(
            len(genres.names) for genres in assignments.values()
        ) / len(albums)

    for album in albums:
        before = sorted(genre.name for genre in album.genres.all())
        after = sorted(assignments[album.id].names)
        if before != after:
            report.changed[album.id] = (album.name, before, after)

    if dry_run:
        return report

    with transaction.atomic():
        _write(albums, assignments, report)
        transaction.on_commit(caching.invalidate_music_caches)

    return report


def _write(albums, assignments, report: RebuildReport) -> None:
    used = []
    for genres in assignments.values():
        for name in genres.names:
            if name not in used:
                used.append(name)

    rows = {}
    for name in sorted(used, key=lambda n: (n in gn.LEAF_PARENT, n)):
        rows[name] = _ensure_row(name, report)

    by_album = {album.id: album for album in albums}
    for album_id in report.changed:
        by_album[album_id].genres.set(
            [rows[name] for name in assignments[album_id].names]
        )

    # Album.modified feeds the client payload's data version, and setting an
    # M2M does not touch it, so a client would keep its stale genres without
    # this. update() bypasses auto_now, hence the explicit value.
    models.Album.objects.filter(pk__in=list(report.changed)).update(
        modified=timezone.now()
    )

    _delete_unused_genres(report)


def _ensure_row(name: str, report: RebuildReport):
    """The row for a vocabulary name, renaming an alias's row to keep its id."""
    if not models.MusicGenre.objects.filter(name=name).exists():
        alias_row = _row_for_alias_of(name)
        if alias_row is not None:
            report.renamed.append((alias_row.name, name))
            alias_row.name = name
            slug = slugify(name)
            if not (
                models.MusicGenre.objects.filter(slug=slug)
                .exclude(pk=alias_row.pk)
                .exists()
            ):
                alias_row.slug = slug
            alias_row.save(update_fields=["name", "slug"])
    return gn.get_or_create_canonical_genre(name)


def _row_for_alias_of(name: str):
    """The busiest existing row whose own name is an alias of ``name``."""
    candidates = []
    queryset = models.MusicGenre.objects.exclude(name__in=gn.ROOT_GENRES).annotate(
        album_count=Count("albums")
    )
    for row in queryset:
        if row.name in gn.LEAF_PARENT:
            continue
        canonical = gn.canonicalize(row.name)
        if canonical is not None and canonical.leaf == name:
            candidates.append(row)
    if not candidates:
        return None
    return max(candidates, key=lambda row: (row.album_count, -row.pk))


def _delete_unused_genres(report: RebuildReport) -> None:
    """Delete rows no album uses, remapping the saved filters that named them.

    ``MusicGenre.parent`` cascades, so a row is kept while any descendant of
    it is in use, and the deepest rows go first.
    """
    genres = list(models.MusicGenre.objects.annotate(album_count=Count("albums")))
    by_id = {genre.id: genre for genre in genres}

    in_use = set()
    for genre in genres:
        if genre.album_count:
            node = genre
            while node is not None and node.id not in in_use:
                in_use.add(node.id)
                node = by_id.get(node.parent_id)

    doomed = [genre for genre in genres if genre.id not in in_use]
    if not doomed:
        return

    survivors_by_name = {genre.name: genre.id for genre in genres if genre.id in in_use}
    replacement = {
        genre.id: _replacement_id(genre, by_id, survivors_by_name) for genre in doomed
    }
    report.saved_filters_remapped = _remap_saved_filters(replacement)

    for genre in sorted(doomed, key=lambda genre: -genre.level):
        report.deleted.append(genre.name)
        models.MusicGenre.objects.filter(pk=genre.pk).delete()


def _replacement_id(genre, by_id, survivors_by_name) -> Optional[int]:
    """What a saved filter naming a deleted genre should name instead."""
    canonical = gn.canonicalize(genre.name)
    if canonical is not None:
        if canonical.leaf in survivors_by_name:
            return survivors_by_name[canonical.leaf]
        for root in canonical.roots:
            if root in survivors_by_name:
                return survivors_by_name[root]

    node = by_id.get(genre.parent_id)
    while node is not None:
        if node.name in survivors_by_name:
            return survivors_by_name[node.name]
        node = by_id.get(node.parent_id)
    return None


def _remap_saved_filters(replacement: Dict[int, Optional[int]]) -> int:
    """Point saved filters at surviving genres; return how many changed."""
    changed = 0
    for saved in models.SavedAlbumFilterSet.objects.all():
        filters = saved.filters if isinstance(saved.filters, dict) else {}
        ids = filters.get("genres")
        if not isinstance(ids, list) or not ids:
            continue

        remapped = []
        for value in ids:
            try:
                genre_id = int(value)
            except (TypeError, ValueError):
                remapped.append(value)
                continue
            if genre_id in replacement:
                new_id = replacement[genre_id]
                if new_id is None:
                    continue
                value = str(new_id) if isinstance(value, str) else new_id
            if value not in remapped:
                remapped.append(value)

        if remapped != ids:
            saved.filters = {**filters, "genres": remapped}
            saved.save(update_fields=["filters"])
            changed += 1
    return changed

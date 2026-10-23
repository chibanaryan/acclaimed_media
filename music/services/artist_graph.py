"""Which albums belong to which artist, from ``ArtistRelation``.

An album is credited to the artists ``WebRankings.txt`` names, and through
the relation tags it also belongs to others: Purple Rain is credited to
Prince and the Revolution, a project of Prince, so it is Prince's too; Déjà
Vu is credited to CSNY, a project of CSN and a collaboration with Neil
Young, so it is both of theirs. Those principal kinds (alias, project,
collaboration) are followed transitively. The supporting kinds (featuring,
backed by) only make the related artist *appear on* the albums - Crazy Horse
appears on Neil Young & Crazy Horse's records without them being its own.

Built the way ``core.services.genre_tree`` answers the genre hierarchy: one
fetch of the relation rows and an in-memory walk, with no ORM recursion and
no cache. The table is a few dozen rows; the credits about a thousand.
"""

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

from core.services.genre_tree import descendants_by_id
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


def credit_text(names: List[str]) -> str:
    """Join credited names into one line; no names is "Various Artists"."""
    if not names:
        return config.VARIOUS_ARTISTS
    return "".join(
        credit_separator(index, len(names)) + name for index, name in enumerate(names)
    )


def artist_summary(albums_count: int, appears_on_count: int = 0) -> str:
    """How much of the ranking an artist accounts for, in a few words.

    "5 albums", "1 album", or for an act that only features on or backs
    other records (Crazy Horse), "appears on 3 albums" - so a search result
    never passes someone else's albums off as theirs.
    """
    if albums_count or not appears_on_count:
        return f"{albums_count} album{'' if albums_count == 1 else 's'}"
    return f"appears on {appears_on_count} album{'' if appears_on_count == 1 else 's'}"


class ArtistGraph:
    """The relation tags, and optionally the credits, held for one request.

    ``relations`` is ``(artist_id, related_id, kind)`` triples and
    ``credits`` ``(album_id, artist_id)`` pairs; ``load()`` fetches both.
    Filtering needs only the relations, so the credits are optional.
    """

    def __init__(
        self,
        relations: Iterable[Tuple[int, int, str]],
        credits: Optional[Iterable[Tuple[int, int]]] = None,
    ):
        self._principal_up: Dict[int, List[int]] = defaultdict(list)
        self._supporting_down: Dict[int, List[int]] = defaultdict(list)
        pairs = []
        related_ids = []
        for artist_id, related_id, kind in relations:
            if kind in config.PRINCIPAL_RELATION_KINDS:
                self._principal_up[artist_id].append(related_id)
                pairs.append((artist_id, related_id))
                related_ids.append(related_id)
            elif kind in config.SUPPORTING_RELATION_KINDS:
                self._supporting_down[related_id].append(artist_id)
        # `descendants_by_id` reads a pair as (node, parent): a derived act
        # under each artist it rolls up into. An act with several parents
        # (CSNY) arrives once per parent, which the walk handles; a parent
        # only ever named as one still has to be a node to get an entry.
        walk = descendants_by_id(pairs + [(rid, None) for rid in related_ids])
        self._derived: Dict[int, List[int]] = {
            node: list(dict.fromkeys(ids)) for node, ids in walk.items() if ids
        }

        self._credited: Optional[Dict[int, Set[int]]] = None
        if credits is not None:
            self._credited = defaultdict(set)
            for album_id, artist_id in credits:
                self._credited[artist_id].add(album_id)

    @classmethod
    def load(cls, with_credits: bool = True) -> "ArtistGraph":
        relations = models.ArtistRelation.objects.values_list(
            "artist_id", "related_id", "kind"
        )
        credits = (
            models.AlbumCredit.objects.values_list("album_id", "artist_id")
            if with_credits
            else None
        )
        return cls(relations, credits)

    # ----- the relation walk -------------------------------------------------

    def derived_ids(self, artist_id: int) -> List[int]:
        """Artists whose albums roll up into ``artist_id``, excluding itself."""
        return self._derived.get(artist_id, [])

    def derived_map(self) -> Dict[int, List[int]]:
        """``derived_ids`` for every artist that has any."""
        return self._derived

    def expand(self, artist_ids: Iterable[int]) -> Set[int]:
        """``artist_ids`` plus everything that rolls up into them.

        What ``?artists=`` filters on, so picking Prince finds Purple Rain.
        """
        expanded: Set[int] = set()
        for artist_id in artist_ids:
            expanded.add(artist_id)
            expanded.update(self.derived_ids(artist_id))
        return expanded

    def roots(self, artist_ids: Iterable[int]) -> List[int]:
        """The artists ``artist_ids`` roll up into, at the top of the walk.

        Purple Rain's Prince and the Revolution gives Prince; Déjà Vu's CSNY
        gives CSN and Neil Young; an artist with no principal relation is
        its own root. In first-seen order, without duplicates.
        """
        result: List[int] = []
        seen: Set[int] = set()
        stack = list(reversed(list(artist_ids)))
        while stack:
            artist_id = stack.pop()
            if artist_id in seen:
                continue
            seen.add(artist_id)
            ups = self._principal_up.get(artist_id)
            if not ups:
                result.append(artist_id)
                continue
            stack.extend(reversed(ups))
        return result

    # ----- albums ---------------------------------------------------------------

    def _require_credits(self) -> Dict[int, Set[int]]:
        if self._credited is None:
            raise ValueError("ArtistGraph was loaded without credits")
        return self._credited

    def album_ids(self, artist_id: int) -> Set[int]:
        """Albums that are ``artist_id``'s own: credited, or rolled up."""
        credited = self._require_credits()
        album_ids = set(credited.get(artist_id, ()))
        for derived_id in self.derived_ids(artist_id):
            album_ids.update(credited.get(derived_id, ()))
        return album_ids

    def appears_on_ids(self, artist_id: int) -> Set[int]:
        """Albums ``artist_id`` features on or backs, but that are not its own.

        Crazy Horse backs Neil Young & Crazy Horse, so it appears on every
        album that act owns.
        """
        album_ids: Set[int] = set()
        for host_id in self._supporting_down.get(artist_id, ()):
            album_ids.update(self.album_ids(host_id))
        return album_ids - self.album_ids(artist_id)

    def appears_on_by_artist(self) -> Dict[int, Set[int]]:
        """``appears_on_ids`` for every artist that appears on anything."""
        result = {}
        for artist_id in self._supporting_down:
            album_ids = self.appears_on_ids(artist_id)
            if album_ids:
                result[artist_id] = album_ids
        return result

    def album_ids_by_artist(self) -> Dict[int, Set[int]]:
        """``album_ids`` for every artist that owns at least one album."""
        credited = self._require_credits()
        owners = set(credited) | set(self._derived)
        result = {}
        for artist_id in owners:
            album_ids = self.album_ids(artist_id)
            if album_ids:
                result[artist_id] = album_ids
        return result

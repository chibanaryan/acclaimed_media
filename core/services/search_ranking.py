"""How well a search box query matches a name, and which group it shows first.

Both sections' unified searches answer in groups - games, developers and
series; albums and artists - and the group holding the better match leads.
Before this the dropdowns always listed their groups in a fixed order, and
an album matches on its credit line as well as its title - so "Beatles"
filled the five album rows with Beatles albums and The Beatles themselves
sat below the dropdown's fold. "Beach Boys", with three ranked albums, left
room for its artist row, which is why only some artists seemed missing.

A score is the best of these, lowest first:

- ``EXACT``: the whole name, ignoring case, accents and a leading "The"
  ("beatles" is The Beatles exactly);
- ``WORD_START``: a word in the name starts with the query ("zep");
- ``SUBSTRING``: the query is somewhere in the name;
- ``INDIRECT``: found through another field - an album through its credit
  line - which is always weaker than any match on the name itself.

The scores order the groups and the creator-like rows (artists, developers,
series). Albums and games stay in rank order but for an exact title, since
a title that merely contains the query is no reason to put #820 above #4.
"""

import re
from typing import Dict, Iterable, List, Optional, Sequence

from django.db.models import Case, IntegerField, Q, Value, When
from unidecode import unidecode

EXACT = 0
WORD_START = 1
SUBSTRING = 2
INDIRECT = 3

#: How many of a creator-like group's matches are read to be scored. The
#: search runs on every keystroke, and a two-letter query matches hundreds of
#: rows; reading them all to show three grew with the catalogue.
#: ``exact_first`` orders exact names ahead, so the cap never hides one.
CANDIDATES = 50


def _fold(text: str) -> str:
    """Lower-cased, unaccented and single-spaced, as a comparison form."""
    return " ".join(unidecode(text or "").casefold().split())


def _bare(folded: str) -> str:
    """A folded name without its leading "the", for the exact test only."""
    return folded[4:] if folded.startswith("the ") else folded


def match_quality(q: str, names: Iterable[str]) -> Optional[int]:
    """The best score ``q`` gets against any of ``names``, or None for none."""
    needle = _fold(q)
    if not needle:
        return None
    word_start = re.compile(r"(?:^|\W)" + re.escape(needle))
    best = None
    for name in names:
        haystack = _fold(name)
        if haystack and _bare(haystack) == _bare(needle):
            return EXACT
        if needle not in haystack:
            continue
        score = WORD_START if word_start.search(haystack) else SUBSTRING
        best = score if best is None else min(best, score)
    return best


def exact_name_q(**names: str) -> Q:
    """A filter for rows ``match_quality`` would call ``EXACT``.

    Each keyword is a field and the query as that field stores it - the name
    as typed, the accent-folded copy for ``name_normalized`` - matched
    case-insensitively with and without a leading "the".
    """
    query = Q()
    for field, value in names.items():
        name = " ".join((value or "").split())
        bare = name[4:] if name.lower().startswith("the ") else name
        for variant in (bare, f"the {bare}"):
            query |= Q(**{f"{field}__iexact": variant})
    return query


def exact_first(queryset, *then: str, **names: str):
    """``queryset`` with exact names (``exact_name_q(**names)``) first.

    Then ordered by ``then``. In the database, so a slice of it is both
    bounded and right: for games and albums, ranked with an exact title
    first, it is the whole answer in one query.
    """
    return queryset.annotate(
        search_exact=Case(
            When(exact_name_q(**names), then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by("search_exact", *then)


def quality_or(q: str, names: Iterable[str], fallback: int) -> int:
    """``match_quality`` for a row the database already matched.

    A miss here means the database matched on something the names do not
    show - an album's credit line, for ``INDIRECT`` - or folded the text
    differently, for ``SUBSTRING``: still a match, of the weakest kind.
    """
    score = match_quality(q, names)
    return fallback if score is None else score


def group_order(bests: Dict[str, Optional[int]], tie_order: Sequence[str]) -> List[str]:
    """The groups best match first, ``tie_order`` breaking ties.

    ``bests`` holds each group's best score among the rows it shows (None
    for an empty group), so a group never leads for a reason nobody can
    see. Empty groups go last, in ``tie_order``.
    """
    return sorted(
        tie_order,
        key=lambda group: (
            bests.get(group) is None,
            bests.get(group) or 0,
            tie_order.index(group),
        ),
    )

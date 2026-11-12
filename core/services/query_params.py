"""Query-string parsing that never raises.

A query string is the visitor's to write, so ``/?genres=abc`` or
``/api/games/?limit=1.5`` is not an error in our code. Each helper here
answers a malformed value the way an absent one would be answered, rather
than letting a bare ``int()`` turn it into a 500.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional

from django.db.models import Q, QuerySet

# SQLite stores integers in eight bytes and raises OverflowError on anything
# wider, so a twenty-digit "id" crashed the query rather than matching nothing.
MAX_INT = 2**63 - 1


def parse_int(raw, default=None):
    """An integer parameter, or ``default`` if it is missing or malformed."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if -MAX_INT <= value <= MAX_INT else default


def parse_id_list(raw):
    """A comma-separated id parameter, ignoring anything that is not an id."""
    if not raw:
        return []
    ids = []
    for part in raw.split(","):
        part = part.strip()
        # isascii: str.isdigit() also accepts "²", which int() then rejects.
        # The length check comes before int(), which refuses any string of
        # more than 4300 digits with a ValueError; 19 digits hold MAX_INT.
        if (
            part.isascii()
            and part.isdigit()
            and len(part) <= 19
            and int(part) <= MAX_INT
        ):
            ids.append(int(part))
    return ids


def ordered_range(start, end):
    """``(start, end)`` the right way round; either may be None, an open side."""
    if start is not None and end is not None and start > end:
        return end, start
    return start, end


def parse_direction(raw, default):
    """A sort direction, ``"asc"`` or ``"desc"``, else ``default``.

    Pages render the direction into Alpine expressions, where anything but a
    known value is script (AGENTS.md, "Content Security Policy").
    """
    return raw if raw in ("asc", "desc") else default


def parse_limit(raw, default, maximum=20):
    """A result limit, clamped to ``1..maximum`` and never raising."""
    value = parse_int(raw)
    if value is None:
        return default
    return max(1, min(value, maximum))


@dataclass
class Filter:
    """One query parameter an API list view filters by.

    Games' and books' list views both declare these; it lived in games'
    ``query_filters`` until 2026-11-12, and books imported it from there.
    """

    param: str
    fields: List[str]
    coerce: type = str
    label: Callable[[str], str] = lambda x: x

    def filter_queryset(self, qs: QuerySet, param_val: Optional[str]) -> QuerySet:
        """
        Filter a queryset based on parameter value.

        Args:
            qs: The Django queryset to filter
            param_val: The parameter value to filter by

        Returns:
            The filtered queryset
        """
        if not param_val:
            return qs

        try:
            param_val = self.coerce(param_val.strip())
        except (TypeError, ValueError):
            # A malformed value filters nothing rather than raising a 500.
            return qs
        if isinstance(param_val, int) and abs(param_val) > MAX_INT:
            return qs
        # Any field may match. A filter with none filters nothing: `query`
        # was left unbound there, an UnboundLocalError
        query = Q()
        for field in self.fields:
            query |= Q(**{field: param_val})
        return qs.filter(query)

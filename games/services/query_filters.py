"""
Query filter utilities for Acclaimed Games.

Provides reusable filtering functions for Django querysets,
including genre, platform, and year filtering with caching support.
"""

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from django.db.models import Q, QuerySet

from core.cache_helpers import cached
from core.services.query_params import MAX_INT, ordered_range, parse_int
from games import config


def genre_descendant_map() -> Dict[int, List[int]]:
    """Map every WikipediaGenre id to the ids below it, from one query.

    Deliberately uncached, as music's equivalent is: the table is ~60 rows,
    and in production the shared cache is itself a Postgres table, so a hit
    costs a query too. The per-genre cache this replaced also went stale -
    its keys were not the ones the invalidation signal deleted, so a
    re-parented genre kept filtering by its old tree for 24 hours.
    """
    from core.services.genre_tree import fetch_descendants_by_id
    from games.models import WikipediaGenre

    return fetch_descendants_by_id(WikipediaGenre.objects.all())


def apply_genre_filter(
    queryset: QuerySet,
    genre_ids: List[int],
    match_all: bool = True,
    expand_hierarchy: bool = True,
    descendants: Optional[Dict[int, List[int]]] = None,
) -> QuerySet:
    """
    Filter queryset by Wikipedia genres with any/all matching.

    When using Wikipedia genres with hierarchy expansion, selecting a parent
    genre will automatically include all games tagged with child genres.

    Args:
        queryset: The queryset to filter
        genre_ids: List of genre IDs to filter by
        match_all: If True, games must match ALL selected genres (each can be
                   satisfied by itself or any descendant). If False, ANY match.
        expand_hierarchy: If True, expand parent genres to include all
                          descendants. If False, filter by exact genre IDs only.
        descendants: A ``genre_descendant_map()`` to reuse. A caller filtering
                     more than once per request builds it once and passes it.

    Returns:
        Filtered queryset
    """
    if not genre_ids:
        return queryset

    genre_field = "wikipedia_genres"

    # For Wikipedia genres with hierarchy expansion
    # Each selected genre expands to include its descendants
    # match_all: game must have at least one from EACH expanded group
    # match_any: game must have at least one from ANY expanded group
    if expand_hierarchy:
        if descendants is None:
            descendants = genre_descendant_map()
        expanded_groups = [
            _expand_single_genre_with_descendants(genre_id, descendants)
            for genre_id in genre_ids
        ]

        if match_all:
            # Game must have at least one genre from EACH group
            for group in expanded_groups:
                q = Q()
                for gid in group:
                    q |= Q(**{genre_field: gid})
                queryset = queryset.filter(q)
        else:
            # Game must have at least one genre from ANY group
            q = Q()
            for group in expanded_groups:
                for gid in group:
                    q |= Q(**{genre_field: gid})
            queryset = queryset.filter(q)
    else:
        # No hierarchy expansion - exact matching
        if match_all:
            for genre_id in genre_ids:
                queryset = queryset.filter(**{genre_field: genre_id})
        else:
            q = Q()
            for genre_id in genre_ids:
                q |= Q(**{genre_field: genre_id})
            queryset = queryset.filter(q)

    # Use distinct() to avoid duplicate rows from M2M joins
    return queryset.distinct()


def _expand_single_genre_with_descendants(
    genre_id: int, descendants: Optional[Dict[int, List[int]]] = None
) -> List[int]:
    """
    Expand a single genre ID to include itself and all descendant IDs.

    Args:
        genre_id: A single genre ID to expand
        descendants: A ``genre_descendant_map()``; built here if not given

    Returns:
        List containing the genre ID and all its descendant IDs. An unknown
        ID expands to itself alone.
    """
    if descendants is None:
        descendants = genre_descendant_map()
    return [genre_id, *descendants.get(genre_id, ())]


def apply_platform_filter(queryset: QuerySet, platform_ids: List[int]) -> QuerySet:
    """
    Filter queryset by platforms (any match).

    Args:
        queryset: The queryset to filter
        platform_ids: List of platform IDs to filter by

    Returns:
        Filtered queryset
    """
    if not platform_ids:
        return queryset

    return queryset.filter(platforms__in=platform_ids).distinct()


def apply_series_filter(queryset: QuerySet, series_ids: List[int]) -> QuerySet:
    """
    Filter queryset by series (any match).

    Args:
        queryset: The queryset to filter
        series_ids: List of series IDs to filter by

    Returns:
        Filtered queryset with distinct() to avoid duplicates from M2M join
    """
    if not series_ids:
        return queryset

    return queryset.filter(series__in=series_ids).distinct()


def get_or_set_cache(
    cache_key: str,
    queryset: QuerySet,
    fields: List[str],
    timeout: int = config.CACHE_TIMEOUT_DEFAULT,
    order_by: Optional[str] = None,
    transform_id: bool = False,
    generation_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get cached list or build and cache from queryset.

    Args:
        cache_key: Key to use for caching
        queryset: Queryset to build list from if not cached
        fields: List of field names to include in each dict
        timeout: Cache timeout in seconds (default from config)
        order_by: Optional field to order by
        transform_id: If True, convert 'id' field to string
        generation_key: The family's generation, for a value something drops

    Returns:
        List of dictionaries with requested fields
    """

    def build():
        qs = queryset.order_by(order_by) if order_by else queryset
        rows = list(qs.values(*fields))
        if transform_id and "id" in fields:
            rows = [{**item, "id": str(item["id"])} for item in rows]
        return rows

    # Through `cached`, which guards the save with ``generation_key`` when a
    # drop names one (a games import drops the release's lists)
    return cached(cache_key, build, timeout, generation_key)


# A decade as the links spell it, "1990-99": the browser reads the same
# shape (`currentFilterParams` in utils-base.js)
DECADE = re.compile(r"(\d{3}0)-\d{2}")


def resolve_year_range(decade=None, year=None, start=None, end=None):
    """``(start, end)`` for the four year parameters; None is an open side.

    A start or an end beats a year, which beats a decade: the rule the
    browser reads a URL by, so the engine's list is the server's. Until
    2026-11-10 three readers each had their own. The list took a decade
    over a year and narrowed it by start and end, the heading took start
    and end first, and the CSV's file name a decade first, so
    ``?decade=1990-99&year=1995`` listed the 1990s under a heading that
    said 1995. Only a hand-written URL carries two of them.

    A value that is not a year is no value, though an unreadable start or
    end still outranks a year, as it does in the browser. A range written
    backwards (``?start=2000&end=1990``, by hand: no control writes one) is
    the range; it listed nothing under a heading reading "2000-1990".
    """
    if start or end:
        return ordered_range(parse_int(start), parse_int(end))
    year = parse_int(year)
    if year is not None:
        return year, year
    match = DECADE.fullmatch(decade or "")
    if match:
        return int(match[1]), int(match[1]) + 9
    return None, None


def apply_year_filters(
    queryset: QuerySet,
    decade: Optional[str] = None,
    year: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> QuerySet:
    """
    Apply year/decade filtering to a Game queryset.

    Args:
        queryset: The queryset to filter
        decade: Decade string like "1990-99" or "2000-09"
        year: Single year as string
        start: Start year range as string
        end: End year range as string

    Returns:
        The queryset, filtered to the one range ``resolve_year_range`` reads
        the four as.
    """
    first, last = resolve_year_range(decade, year, start, end)
    if first is not None:
        queryset = queryset.filter(year_of_release__gte=first)
    if last is not None:
        queryset = queryset.filter(year_of_release__lte=last)

    return queryset


@dataclass
class Filter:
    """Generic filter class for API views."""

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

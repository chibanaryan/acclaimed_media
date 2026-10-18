"""Shared ranking helpers for the multi-media platform.

The global ``rank`` on a media item is supplied by the import files, not
computed here. What this module derives is the per-year and per-decade
position implied by that global rank.
"""

import math

from collections import defaultdict
from typing import Tuple

from django.db import connection, transaction


def year_to_decade(year: int) -> int:
    """Convert a year to its decade (e.g. 1985 -> 1980)."""
    return int(year / 10) * 10


def update_year_decade_ranks(model, table: str, year_field: str) -> Tuple[int, int]:
    """Bulk update ``year_rank`` and ``decade_rank`` for every row of ``model``.

    Call this after importing or re-ranking a media type. Both ranks are
    derived from the global ``rank`` column, so the ordering is whatever the
    import file specified.

    On PostgreSQL this is two window-function UPDATEs. SQLite has no such
    support in an UPDATE, so it falls back to chunked Python processing.

    Args:
        model: The concrete media model (e.g. ``games.models.Game``).
        table: Its database table name, for the raw PostgreSQL statements.
        year_field: The release-year field name (e.g. ``"year_of_release"``).

    Returns:
        Tuple of (rows_updated, years_processed).
    """
    if connection.vendor == "postgresql":
        return _update_postgres(model, table, year_field)
    return _update_chunked(model, year_field)


def _update_postgres(model, table: str, year_field: str) -> Tuple[int, int]:
    """Window-function path. ``table`` and ``year_field`` are caller-supplied
    identifiers, never user input."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {table}
                SET year_rank = subquery.row_num
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY {year_field}
                               ORDER BY rank ASC
                           ) as row_num
                    FROM {table}
                ) AS subquery
                WHERE {table}.id = subquery.id
                """
            )
            cursor.execute(
                f"""
                UPDATE {table}
                SET decade_rank = subquery.row_num
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY ({year_field} / 10) * 10
                               ORDER BY rank ASC
                           ) as row_num
                    FROM {table}
                ) AS subquery
                WHERE {table}.id = subquery.id
                """
            )

    rows_updated = model.objects.count()
    years_count = model.objects.values(year_field).distinct().count()
    return (rows_updated, years_count)


def _update_chunked(model, year_field: str) -> Tuple[int, int]:
    """SQLite path: collect ids per year and per decade, then update in bulk."""
    year_items = defaultdict(list)
    decade_items = defaultdict(list)
    years = set()

    chunk_size = 1000
    total = model.objects.count()

    # First pass: items by year, already ordered for year_rank.
    for offset in range(0, total, chunk_size):
        chunk = model.objects.order_by(year_field, "rank")[offset : offset + chunk_size]
        for item in chunk:
            year = getattr(item, year_field)
            year_items[year].append(item.id)
            years.add(year)

    # Second pass: items by decade, ordered by global rank.
    for offset in range(0, total, chunk_size):
        chunk = model.objects.order_by("rank")[offset : offset + chunk_size]
        for item in chunk:
            year = getattr(item, year_field)
            # A missing year forms its own group, matching how PostgreSQL
            # partitions NULLs together on the window-function path.
            decade = None if year is None else year_to_decade(year)
            decade_items[decade].append(item.id)

    items_updated = 0
    with transaction.atomic():
        for _, item_ids in year_items.items():
            for rank_position, item_id in enumerate(item_ids, 1):
                model.objects.filter(id=item_id).update(year_rank=rank_position)
                items_updated += 1

        for _, item_ids in decade_items.items():
            for rank_position, item_id in enumerate(item_ids, 1):
                model.objects.filter(id=item_id).update(decade_rank=rank_position)

    return (items_updated, len(years))


def rank_distribution(ranks, max_rank, bin_count):
    """Bucket ranks into ``bin_count`` even bins across 1..``max_rank``.

    What the rank distribution chart draws: where the items matching the
    current filters sit across the whole ranking. Bins are built from the
    global maximum rather than the filtered one, so the shape of a filtered
    set is read against the same axis every time.
    """
    if not max_rank or bin_count < 1:
        return []

    bin_size = math.ceil(max_rank / bin_count)
    counts = [0] * bin_count
    for rank in ranks:
        if not rank:
            continue
        index = (rank - 1) // bin_size
        if 0 <= index < bin_count:
            counts[index] += 1

    return [
        {
            "binStart": index * bin_size + 1,
            "binEnd": min((index + 1) * bin_size, max_rank),
            "count": counts[index],
        }
        for index in range(bin_count)
    ]

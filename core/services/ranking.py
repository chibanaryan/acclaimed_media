"""Shared ranking helpers for the multi-media platform.

The global ``rank`` on a media item is supplied by the import files, not
computed here. What this module derives is the per-year and per-decade
position implied by that global rank.
"""

import math

from collections import Counter
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

    On PostgreSQL this is two window-function UPDATEs. Elsewhere (SQLite, in
    development and the tests) the positions are counted in Python.

    Args:
        model: The concrete media model (e.g. ``games.models.Game``).
        table: Its database table name, for the raw PostgreSQL statements.
        year_field: The release-year field name (e.g. ``"year_of_release"``).

    Returns:
        Tuple of (rows_updated, years_processed).
    """
    if connection.vendor == "postgresql":
        return _update_postgres(model, table, year_field)
    return _update_in_python(model, year_field)


def _update_postgres(model, table: str, year_field: str) -> Tuple[int, int]:
    """Window-function path. ``table`` and ``year_field`` are caller-supplied
    identifiers, never user input."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"""
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
                """)
            cursor.execute(f"""
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
                """)

    rows_updated = model.objects.count()
    years_count = model.objects.values(year_field).distinct().count()
    return (rows_updated, years_count)


def _update_in_python(model, year_field: str) -> Tuple[int, int]:
    """Any other database: one read in rank order, counted here, one bulk
    update.

    A missing year forms its own group, as PostgreSQL partitions NULLs
    together. Until 2026-11-10 this paged with OFFSET over `(year, rank)`,
    which no rule made a total order, and wrote a statement a row.
    """
    rows = model.objects.order_by("rank", "id").values_list("id", year_field)
    in_year = Counter()
    in_decade = Counter()
    ranked = []
    for item_id, year in rows:
        decade = None if year is None else year_to_decade(year)
        in_year[year] += 1
        in_decade[decade] += 1
        ranked.append(
            model(id=item_id, year_rank=in_year[year], decade_rank=in_decade[decade])
        )
    model.objects.bulk_update(ranked, ["year_rank", "decade_rank"], batch_size=500)
    return (len(ranked), len(in_year))


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

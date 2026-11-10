"""Counting a page's options in one query."""

from django.db.models import Count


def count_by(queryset, field):
    """How many of ``queryset``'s rows have each value of ``field``.

    One grouped query, where a count per option was one each: the source
    lists pages counted their four list types four times over.

    Returns:
        ``{value: count}``, with no entry for a value no row has.
    """
    # order_by(): a default ordering would join the GROUP BY and split a group
    return dict(queryset.order_by().values_list(field).annotate(count=Count("pk")))

"""The API's default pagination."""

from rest_framework.pagination import LimitOffsetPagination


class CappedLimitOffsetPagination(LimitOffsetPagination):
    """``LimitOffsetPagination`` with a ceiling on ``?limit=``.

    DRF's ``max_limit`` defaults to none, so ``/api/games/?limit=100000``
    serialised the whole catalogue in one response. A larger request is
    clamped, not refused; ``/api/games/all/`` is the endpoint for everything.
    """

    max_limit = 500

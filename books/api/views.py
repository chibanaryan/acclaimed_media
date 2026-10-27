"""
Books API views.

These views follow the same patterns as games/api/views.py.
They will be fully functional once the books models are created in Phase 4.2.
"""

from datetime import datetime

from django.db import connection
from django.db.models import Count, F, Min, Prefetch
from django.db.models.functions import Lower
from rest_framework.authentication import SessionAuthentication
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.views import APIView, Response

from games import utils  # Shared utilities

from core.permissions import IsStaffOrHide
from core.services import genre_tree
from core.services.query_params import parse_id_list, parse_limit

from .. import models
from . import serializers

# Note on caching: these endpoints are deliberately uncached. `cache_page`
# wraps `dispatch`, so it is consulted *before* permissions run - a response
# generated for a staff member is then replayed to anonymous callers, which
# defeats `IsStaffOrHide` entirely. Eight endpoints carried it until
# 2026-10-17, `BookAllDataView` (the whole dataset) among them. Any future
# caching must vary on the user. The same reasoning is recorded in
# music/api/views.py, which never had the decorators.


class StaffReadAPIMixin:
    """Authenticate by session, then allow staff only.

    ``DEFAULT_AUTHENTICATION_CLASSES`` is empty project-wide, so a DRF view
    that does not name an authenticator sees every request as anonymous -
    which, combined with ``IsStaffOrHide``, 404s even for a logged-in staff
    member holding a valid session cookie. Every read view here used to carry
    a bare ``permission_classes = [IsStaffOrHide]``, so the whole read API was
    unreachable from a browser; the client-side filtering bundle's fetch of
    ``/api/books/all/`` would have 404'd. Tests missed it because
    ``APIClient.force_authenticate`` bypasses authentication entirely.

    Every view using this mixin is read-only, so CSRF enforcement on unsafe
    methods never comes into play. ``music.api.views`` has the same mixin for
    the same reason.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsStaffOrHide]


class BookListView(StaffReadAPIMixin, ListAPIView):
    """
    List all books with filtering and search.

    Supports filtering by:
    - q: Search query (title search)
    - author: Author ID
    - start/end: Year range
    - genres: Comma-separated genre IDs
    """

    serializer_class = serializers.BookSummarySerializer
    # Build search fields based on database vendor
    search_fields = ["name_normalized__icontains", "name__icontains"]
    if connection.vendor == "postgresql":
        search_fields = [
            "name_normalized__search",
            "name__search",
        ] + search_fields
    filters = [
        utils.Filter(
            param="q",
            fields=search_fields,
        ),
        utils.Filter(param="author", fields=["authors__goodreads_id"], coerce=int),
        utils.Filter(param="start", fields=["year_published__gte"], coerce=int),
        utils.Filter(param="end", fields=["year_published__lte"], coerce=int),
    ]

    ORDERING_FIELDS = {"rank", "name", "year_published", "year_rank", "decade_rank"}

    def get_queryset(self):
        qs = models.Book.objects.with_relations()

        for filter in self.filters:
            param_val = self.request.GET.get(filter.param)
            qs = filter.filter_queryset(qs, param_val)

        # Genre filtering
        genre_ids = parse_id_list(self.request.GET.get("genres"))
        if genre_ids:
            qs = qs.filter(genres__id__in=genre_ids)

        # Only listed columns, as games' list does: order_by() follows
        # relations, and an unknown field was a 500.
        order_by = self.request.GET.get("order_by", "")
        if order_by.removeprefix("-") in self.ORDERING_FIELDS:
            qs = qs.order_by(order_by)

        return qs.distinct()


class BookDetailView(StaffReadAPIMixin, RetrieveAPIView):
    """Get detailed book information including list appearances."""

    lookup_field = "slug"
    serializer_class = serializers.BookDetailSerializer
    queryset = models.Book.objects.select_related(
        "primary_wikipedia_book_data",
    ).prefetch_related(
        Prefetch(
            "lists",
            queryset=models.BookListMembership.objects.select_related(
                "list__publisher",
            ),
        )
    )


class AuthorDetailView(StaffReadAPIMixin, RetrieveAPIView):
    """API endpoint for author details."""

    lookup_field = "slug"
    serializer_class = serializers.AuthorSerializer
    queryset = models.Author.objects.all()


class AuthorListView(StaffReadAPIMixin, ListAPIView):
    """API endpoint for listing authors."""

    serializer_class = serializers.AuthorSerializer
    search_fields = ["name__icontains"]
    if connection.vendor == "postgresql":
        search_fields = ["name__search"] + search_fields
    filters = [
        utils.Filter(
            param="q",
            fields=search_fields,
        )
    ]

    def get_queryset(self):
        qs = (
            models.Author.objects.annotate(
                books_count=Count("books"),
            )
            .filter(books_count__gt=0)  # Only show authors with books
            .order_by(Lower("name"))
            .distinct()
        )

        for filter in self.filters:
            param_val = self.request.GET.get(filter.param)
            qs = filter.filter_queryset(qs, param_val)

        return qs


class AuthorDetailByIdView(StaffReadAPIMixin, RetrieveAPIView):
    """API endpoint for author details by GoodReads ID."""

    lookup_field = "goodreads_id"
    serializer_class = serializers.AuthorSerializer
    queryset = models.Author.objects.annotate(
        books_count=Count("books"),
    )


class BookListListView(StaffReadAPIMixin, ListAPIView):
    """List all book lists/rankings."""

    serializer_class = serializers.BookListSerializer
    filters = [
        utils.Filter(param="publisher", fields=["publisher_id"], coerce=int),
        utils.Filter(param="year", fields=["year"], coerce=int),
        utils.Filter(param="type", fields=["type"], coerce=str),
    ]

    def get_queryset(self):
        qs = models.BookList.objects.select_related(
            "publisher",
        ).order_by(
            "publisher",
            "year",
            "name",
        )

        for filter in self.filters:
            param_val = self.request.GET.get(filter.param)
            qs = filter.filter_queryset(qs, param_val)

        return qs


class BookMetaView(StaffReadAPIMixin, APIView):
    """
    Metadata about the books database.

    Returns counts, year ranges, and statistics.
    """

    def get(self, *args, **kwargs):
        data = {}

        # Book lists
        book_lists = models.BookList.objects.all()
        list_year_counts = (
            book_lists.order_by("year")
            .values("year")
            .annotate(count=Count("id"))
            .values("year", "count")
        )

        data["lists"] = {
            "years": list_year_counts,
            "total_count": book_lists.count(),
        }

        # Books
        book_stats = models.Book.objects.aggregate(
            min_year=Min("year_published"),
        )
        min_year = book_stats["min_year"] or 1900
        max_year = datetime.today().year
        all_years = range(min_year, max_year)
        year_count_map = {
            entry["year_published"]: entry["count"]
            for entry in models.Book.objects.values("year_published")
            .annotate(count=Count("id"))
            .order_by("year_published")
        }

        all_years_with_counts = [
            {"year": x, "count": year_count_map.get(x, 0)} for x in all_years
        ]

        # Calculate counts for each decade
        from django.db.models.functions import Floor

        # Books with no year form a NULL decade, and formatting it raises
        # TypeError, so this endpoint 500s as soon as one such book exists.
        decades_data = (
            models.Book.objects.exclude(year_published__isnull=True)
            .annotate(decade_start=Floor(F("year_published") / 10) * 10)
            .values("decade_start")
            .annotate(count=Count("id"))
            .order_by("decade_start")
        )

        decades_with_counts = [
            {
                "decade": (
                    f"{item['decade_start']}-{str(item['decade_start'] + 9)[2:4]}"
                ),
                "count": item["count"],
            }
            for item in decades_data
        ]

        data["books"] = {
            "years": all_years_with_counts,
            "decades": decades_with_counts,
        }

        # Authors
        data["authors"] = {
            "total_count": models.Author.objects.count(),
        }

        return Response(data)


class BookGenreListView(StaffReadAPIMixin, ListAPIView):
    """List all book genres (flat list with hierarchy metadata)."""

    serializer_class = serializers.BookGenreSerializer
    queryset = models.BookGenre.objects.all().order_by("level", "display_order", "name")


class BookGenreTreeView(StaffReadAPIMixin, ListAPIView):
    """List book genres as hierarchical tree structure."""

    serializer_class = serializers.BookGenreTreeSerializer

    def get_queryset(self):
        """Return only root categories for tree building."""
        return models.BookGenre.objects.filter(parent=None).order_by(
            "display_order", "name"
        )


class BookSearchAPIView(StaffReadAPIMixin, APIView):
    """
    API endpoint for navbar search - returns JSON list of books matching query.
    """

    def get(self, request):
        from django.http import JsonResponse

        q = request.GET.get("q", "").strip()
        limit = parse_limit(request.GET.get("limit"), default=5)

        if len(q) < 2:
            return JsonResponse({"results": [], "count": 0})

        books = (
            models.Book.objects.filter(name__icontains=q)
            .only(
                "id",
                "name",
                "slug",
                "year_published",
                "rank",
                "cover_image_url",
            )
            .order_by("rank")[:limit]
        )

        results = []
        for book in books:
            results.append(
                {
                    "id": book.id,
                    "name": book.name,
                    "slug": book.slug,
                    "year_published": book.year_published,
                    "rank": book.rank,
                    "cover_image_url": book.thumbnail,
                }
            )

        return JsonResponse({"results": results, "count": len(results)})


class UnifiedBookSearchView(StaffReadAPIMixin, APIView):
    """
    Unified search endpoint for navbar - returns both authors and books.
    """

    def get(self, request):
        from django.http import JsonResponse

        q = request.GET.get("q", "").strip()
        book_limit = parse_limit(request.GET.get("book_limit"), default=5)
        author_limit = parse_limit(request.GET.get("author_limit"), default=3)

        if len(q) < 2:
            return JsonResponse({"authors": [], "books": []})

        # Search authors
        authors = (
            models.Author.objects.filter(name__icontains=q)
            .annotate(books_count=Count("books"))
            .filter(books_count__gt=0)
            .order_by("-books_count")[:author_limit]
        )

        author_results = [
            {
                "id": author.id,
                "name": author.name,
                "slug": author.slug,
                "books_count": author.books_count,
            }
            for author in authors
        ]

        # Search books
        books = (
            models.Book.objects.filter(name__icontains=q)
            .only(
                "id",
                "name",
                "slug",
                "year_published",
                "rank",
                "cover_image_url",
            )
            .order_by("rank")[:book_limit]
        )

        book_results = [
            {
                "id": book.id,
                "name": book.name,
                "slug": book.slug,
                "year_published": book.year_published,
                "rank": book.rank,
                "cover_image_url": book.thumbnail,
            }
            for book in books
        ]

        return JsonResponse(
            {
                "authors": author_results,
                "books": book_results,
            }
        )


def _compute_book_data_version():
    """
    Compute a version hash for cache invalidation.

    Uses schema version, max modified timestamp of books, and genre count.
    """
    import hashlib

    SCHEMA_VERSION = "1"

    latest_book = models.Book.objects.order_by("-modified").first()
    book_modified = latest_book.modified.isoformat() if latest_book else ""

    genre_count = models.BookGenre.objects.count()

    version_string = f"{SCHEMA_VERSION}:{book_modified}:{genre_count}"
    return hashlib.md5(version_string.encode()).hexdigest()[:12]


class BookDataVersionView(StaffReadAPIMixin, APIView):
    """Lightweight endpoint returning only the data version hash."""

    def get(self, request):
        return Response({"version": _compute_book_data_version()})


class BookAllDataView(StaffReadAPIMixin, APIView):
    """
    Complete book data endpoint for client-side filtering.

    Returns all books with minimal payload for efficient client-side filtering.
    """

    def get(self, request):
        version = _compute_book_data_version()

        # Fetch all books with required relations
        books = (
            models.Book.objects.prefetch_related(
                "authors",
                "genres",
            )
            .with_list_count()
            .order_by("rank")
        )

        # Build books list with minimal field names
        books_data = []
        authors_dict = {}

        for book in books:
            # Collect author IDs
            author_ids = []
            for author in book.authors.all():
                author_ids.append(author.id)
                if author.id not in authors_dict:
                    authors_dict[author.id] = {
                        "n": author.name,
                        "s": author.slug,
                    }

            # Collect genre IDs
            genre_ids = [g.id for g in book.genres.all()]

            books_data.append(
                {
                    "id": book.id,
                    "gi": book.goodreads_id,  # GoodReads ID for read book tracking
                    "n": book.name,
                    "s": book.slug,
                    "r": book.rank,
                    "y": book.year_published,
                    "c": book.cover_image_url,  # Cover image URL
                    "au": author_ids,  # Author IDs
                    "g": genre_ids,  # Genre IDs
                    "lc": book.list_count,  # List count
                    "pc": book.page_count,  # Page count
                }
            )

        # One fetch for the table, one in-memory walk for the descendants.
        # Recursing through `children` instead cost a query per genre, and
        # `values()` keeps the manager's ordering, so "d" comes out exactly
        # as it did - depth first, excluding the genre itself.
        genre_rows = list(
            models.BookGenre.objects.values("id", "name", "slug", "parent_id", "level")
        )
        descendants = genre_tree.descendants_by_id(
            (row["id"], row["parent_id"]) for row in genre_rows
        )
        genres_data = [
            {
                "id": row["id"],
                "n": row["name"],
                "s": row["slug"],
                "p": row["parent_id"],
                "l": row["level"],
                "d": descendants.get(row["id"], []),
            }
            for row in genre_rows
        ]

        return Response(
            {
                "version": version,
                "data": {
                    "books": books_data,
                    "authors": authors_dict,
                    "genres": genres_data,
                },
            }
        )

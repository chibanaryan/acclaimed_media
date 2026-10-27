"""
Tests for books app API endpoints.

Tests for BookListView, BookDetailView, AuthorListView, AuthorDetailView,
BookMetaView, BookGenreListView, ReadBookListCreateView, and other API views.

Note: All book API views require staff access (IsStaffOrHide permission).
Tests must use staff users to access these endpoints.
"""

import importlib
import unittest
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from core.tests.utils import clear_all_caches
from books import models

User = get_user_model()


class StaffAPITestMixin:
    """Mixin that provides a staff user and authenticates them for API tests."""

    def setUp(self):
        super().setUp()
        # Books' home view caches hero counts and the reader's book
        # ids, so a test that renders it leaves entries behind for the
        # next one. pytest's conftest clears caches between tests;
        # this keeps the suite correct under Django's runner too.
        clear_all_caches()
        self.client = APIClient()
        # Create staff user for accessing books API
        self.staff_user = User.objects.create_user(
            username="staffuser",
            password="staffpass",
            is_staff=True,
        )
        # Use force_authenticate for reliable DRF authentication
        self.client.force_authenticate(user=self.staff_user)


class BookListAPITests(StaffAPITestMixin, TestCase):
    """Tests for the BookListView API endpoint."""

    def setUp(self):
        super().setUp()
        self.author = models.Author.objects.create(
            name="Test Author", slug="test-author", goodreads_id="100"
        )
        self.genre = models.BookGenre.objects.create(name="Fiction")

        self.book1 = models.Book.objects.create(
            name="Alpha Book",
            rank=1,
            slug="alpha-book",
            year_published=2020,
            goodreads_id="111",
        )
        self.book1.authors.add(self.author)
        self.book1.genres.add(self.genre)

        self.book2 = models.Book.objects.create(
            name="Beta Book",
            rank=2,
            slug="beta-book",
            year_published=2015,
            goodreads_id="222",
        )
        self.book2.authors.add(self.author)

    def test_list_books(self):
        """Test GET /api/books/ returns books."""
        response = self.client.get("/api/books/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["results"]), 2)

    def test_filter_by_search_query(self):
        """Test filtering by search query."""
        response = self.client.get("/api/books/", {"q": "Alpha"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["name"], "Alpha Book")

    def test_filter_by_year_start(self):
        """Test filtering by year start."""
        response = self.client.get("/api/books/", {"start": 2018})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["name"], "Alpha Book")

    def test_filter_by_year_end(self):
        """Test filtering by year end."""
        response = self.client.get("/api/books/", {"end": 2016})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["name"], "Beta Book")

    def test_filter_by_genres(self):
        """Test filtering by genres."""
        response = self.client.get("/api/books/", {"genres": str(self.genre.id)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["name"], "Alpha Book")

    def test_order_by_parameter(self):
        """Test order_by parameter."""
        response = self.client.get("/api/books/", {"order_by": "-year_published"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["results"][0]["name"], "Alpha Book")
        self.assertEqual(data["results"][1]["name"], "Beta Book")


class BookDetailAPITests(StaffAPITestMixin, TestCase):
    """Tests for the BookDetailView API endpoint."""

    def setUp(self):
        super().setUp()
        self.author = models.Author.objects.create(
            name="Test Author", slug="test-author"
        )
        self.book = models.Book.objects.create(
            name="Test Book",
            rank=1,
            slug="test-book",
            year_published=2020,
            goodreads_id="12345",
        )
        self.book.authors.add(self.author)

    def test_get_book_detail(self):
        """Test GET /api/books/<slug>/ returns book details."""
        response = self.client.get("/api/books/test-book/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "Test Book")
        self.assertEqual(data["slug"], "test-book")

    def test_nonexistent_book_returns_404(self):
        """Test GET for nonexistent book returns 404."""
        response = self.client.get("/api/books/nonexistent/")
        self.assertEqual(response.status_code, 404)


class AuthorListAPITests(StaffAPITestMixin, TestCase):
    """Tests for the AuthorListView API endpoint."""

    def setUp(self):
        super().setUp()
        self.author1 = models.Author.objects.create(name="Alpha Author", slug="alpha")
        self.author2 = models.Author.objects.create(name="Beta Author", slug="beta")

        self.book = models.Book.objects.create(name="Test Book", rank=1)
        self.book.authors.add(self.author1)

    def test_list_authors(self):
        """Test GET /api/books/authors/ returns authors with books."""
        response = self.client.get("/api/books/authors/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Only author1 has books
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["name"], "Alpha Author")

    def test_filter_by_search_query(self):
        """Test filtering by search query."""
        response = self.client.get("/api/books/authors/", {"q": "Alpha"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)


class AuthorDetailAPITests(StaffAPITestMixin, TestCase):
    """Tests for the AuthorDetailView API endpoint."""

    def setUp(self):
        super().setUp()
        self.author = models.Author.objects.create(
            name="Test Author",
            slug="test-author",
            bio="Test biography",
        )

    def test_get_author_detail(self):
        """Test GET /api/books/authors/<slug>/ returns author details."""
        response = self.client.get("/api/books/authors/test-author/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "Test Author")

    def test_nonexistent_author_returns_404(self):
        """Test GET for nonexistent author returns 404."""
        response = self.client.get("/api/books/authors/nonexistent/")
        self.assertEqual(response.status_code, 404)


class AuthorDetailByIdAPITests(StaffAPITestMixin, TestCase):
    """Tests for the AuthorDetailByIdView API endpoint."""

    def setUp(self):
        super().setUp()
        self.author = models.Author.objects.create(
            name="Test Author",
            slug="test-author",
            goodreads_id="12345",
        )

    def test_get_author_by_goodreads_id(self):
        """Test GET /api/books/author-aliases/<goodreads_id>/ returns author."""
        response = self.client.get("/api/books/authors/by-id/12345/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "Test Author")

    def test_nonexistent_id_returns_404(self):
        """Test GET for nonexistent ID returns 404."""
        response = self.client.get("/api/books/authors/by-id/99999/")
        self.assertEqual(response.status_code, 404)


class BookListListAPITests(StaffAPITestMixin, TestCase):
    """Tests for the BookListListView API endpoint."""

    def setUp(self):
        super().setUp()
        self.publication = models.BookPublication.objects.create(name="Test Pub")
        self.book_list = models.BookList.objects.create(
            publisher=self.publication,
            name="Best Books 2024",
            year=2024,
            type="A",
        )

    def test_list_book_lists(self):
        """Test GET /api/books/lists/ returns book lists."""
        response = self.client.get("/api/books/lists/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["name"], "Best Books 2024")

    def test_filter_by_year(self):
        """Test filtering by year."""
        response = self.client.get("/api/books/lists/", {"year": 2024})
        self.assertEqual(response.status_code, 200)


class BookMetaAPITests(StaffAPITestMixin, TestCase):
    """Tests for the BookMetaView API endpoint."""

    def setUp(self):
        super().setUp()
        self.publication = models.BookPublication.objects.create(name="Test Pub")
        models.BookList.objects.create(
            publisher=self.publication,
            name="Best Books",
            year=2024,
            type="A",
        )
        models.Book.objects.create(name="Test Book", rank=1, year_published=2020)
        models.Author.objects.create(name="Test Author", slug="test")

    def test_get_meta(self):
        """Test GET /api/books/meta/ returns metadata."""
        response = self.client.get("/api/books/meta/")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check structure
        self.assertIn("lists", data)
        self.assertIn("books", data)
        self.assertIn("authors", data)

        # Check lists data
        self.assertIn("years", data["lists"])
        self.assertIn("total_count", data["lists"])

        # Check books data
        self.assertIn("years", data["books"])
        self.assertIn("decades", data["books"])

        # Check authors data
        self.assertIn("total_count", data["authors"])


class BookGenreListAPITests(StaffAPITestMixin, TestCase):
    """Tests for the BookGenreListView API endpoint."""

    def setUp(self):
        super().setUp()
        self.fiction = models.BookGenre.objects.create(name="Fiction")
        self.scifi = models.BookGenre.objects.create(
            name="Science Fiction", parent=self.fiction
        )

    def test_list_genres(self):
        """Test GET /api/books/genres/ returns genres."""
        response = self.client.get("/api/books/genres/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)


class BookGenreTreeAPITests(StaffAPITestMixin, TestCase):
    """Tests for the BookGenreTreeView API endpoint."""

    def setUp(self):
        super().setUp()
        self.fiction = models.BookGenre.objects.create(name="Fiction")
        self.scifi = models.BookGenre.objects.create(
            name="Science Fiction", parent=self.fiction
        )

    def test_get_genre_tree(self):
        """Test GET /api/books/genres/tree/ returns tree structure."""
        response = self.client.get("/api/books/genres/tree/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should only return root genres
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["name"], "Fiction")


class BookSearchAPITests(StaffAPITestMixin, TestCase):
    """Tests for the BookSearchAPIView."""

    def setUp(self):
        super().setUp()
        self.book = models.Book.objects.create(
            name="Harry Potter", rank=1, slug="harry-potter"
        )

    def test_search_books(self):
        """Test GET /api/books/search/ returns matching books."""
        response = self.client.get("/api/books/search/", {"q": "Harry"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["name"], "Harry Potter")

    def test_short_query_returns_empty(self):
        """Test short query returns empty results."""
        response = self.client.get("/api/books/search/", {"q": "H"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 0)


class UnifiedBookSearchAPITests(StaffAPITestMixin, TestCase):
    """Tests for the UnifiedBookSearchView."""

    def setUp(self):
        super().setUp()
        self.author = models.Author.objects.create(name="J.K. Rowling", slug="jk")
        self.book = models.Book.objects.create(
            name="Harry Potter", rank=1, slug="harry-potter"
        )
        self.book.authors.add(self.author)

    def test_unified_search(self):
        """Test GET /api/books/unified-search/ returns authors and books."""
        response = self.client.get("/api/books/unified-search/", {"q": "Harry"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("authors", data)
        self.assertIn("books", data)

    def test_short_query_returns_empty(self):
        """Test short query returns empty results."""
        response = self.client.get("/api/books/unified-search/", {"q": "H"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["authors"], [])
        self.assertEqual(data["books"], [])


class BookDataVersionAPITests(StaffAPITestMixin, TestCase):
    """Tests for the BookDataVersionView."""

    def setUp(self):
        super().setUp()
        models.Book.objects.create(name="Test Book", rank=1)

    def test_get_version(self):
        """Test GET /api/books/data-version/ returns version hash."""
        response = self.client.get("/api/books/version/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("version", data)
        # Version should be a 12-character hash
        self.assertEqual(len(data["version"]), 12)


class BookAllDataAPIViewTests(StaffAPITestMixin, TestCase):
    """Tests for the BookAllDataView endpoint."""

    def setUp(self):
        super().setUp()
        self.author = models.Author.objects.create(
            name="All Data Author", slug="all-data"
        )
        self.genre_root = models.BookGenre.objects.create(
            name="Speculative Fiction", slug="spec-fic"
        )
        self.genre_child = models.BookGenre.objects.create(
            name="Epic Fantasy",
            slug="epic-fantasy",
            parent=self.genre_root,
            level=1,
        )
        publication = models.BookPublication.objects.create(name="NYT Books")
        book_list = models.BookList.objects.create(
            name="Top Books 2025",
            publisher=publication,
            year=2025,
            type="A",
        )

        self.book = models.Book.objects.create(
            name="All Data Book",
            rank=1,
            slug="all-data-book",
            goodreads_id="12345",
            year_published=2020,
            page_count=321,
            cover_image_url="https://example.com/cover.jpg",
        )
        self.book.authors.add(self.author)
        self.book.genres.add(self.genre_root, self.genre_child)
        models.BookListMembership.objects.create(list=book_list, book=self.book, rank=1)

    def test_get_all_data_returns_books_authors_and_genres(self):
        response = self.client.get("/api/books/all/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertIn("version", payload)
        self.assertEqual(len(payload["version"]), 12)
        self.assertIn("data", payload)
        self.assertIn("books", payload["data"])
        self.assertIn("authors", payload["data"])
        self.assertIn("genres", payload["data"])

        books = payload["data"]["books"]
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["n"], "All Data Book")
        self.assertEqual(books[0]["gi"], "12345")
        self.assertEqual(books[0]["pc"], 321)
        self.assertEqual(books[0]["lc"], 1)

        authors = payload["data"]["authors"]
        self.assertIn(str(self.author.id), authors)
        self.assertEqual(authors[str(self.author.id)]["n"], "All Data Author")

        genres = {g["id"]: g for g in payload["data"]["genres"]}
        self.assertIn(self.genre_root.id, genres)
        self.assertIn(self.genre_child.id, genres)
        self.assertIn(self.genre_child.id, genres[self.genre_root.id]["d"])

    def test_genre_hierarchy_is_one_query_and_keeps_descendant_order(self):
        """The genre payload reads the table once, however deep the tree.

        Walking `children` per genre cost a query per node. `"d"` must still
        come out as `get_descendant_ids` orders it.
        """
        for index in range(3):
            middle = models.BookGenre.objects.create(
                name=f"Middle {index}",
                slug=f"middle-{index}",
                parent=self.genre_child,
                level=2,
                display_order=3 - index,
            )
            models.BookGenre.objects.create(
                name=f"Leaf {index}", slug=f"leaf-{index}", parent=middle, level=3
            )

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get("/api/books/all/")
        self.assertEqual(response.status_code, 200)

        # The books' own genres arrive by a prefetch join and the data version
        # counts the table; the remaining read is the hierarchy.
        hierarchy_reads = [
            query["sql"]
            for query in captured.captured_queries
            if 'FROM "books_bookgenre"' in query["sql"]
            and "INNER JOIN" not in query["sql"]
            and "COUNT(" not in query["sql"]
        ]
        self.assertEqual(len(hierarchy_reads), 1)

        genres = {g["id"]: g for g in response.json()["data"]["genres"]}
        for genre in models.BookGenre.objects.all():
            self.assertEqual(genres[genre.id]["d"], genre.get_descendant_ids())


@unittest.skip("GoodreadsBookData model removed")
class BookAllDataAPITests(StaffAPITestMixin, TestCase):
    """Tests for the BookAllDataView."""

    def setUp(self):
        super().setUp()
        self.author = models.Author.objects.create(name="Test Author", slug="test")
        self.genre = models.BookGenre.objects.create(name="Fiction")
        self.book = models.Book.objects.create(
            name="Test Book", rank=1, goodreads_id="123"
        )
        self.book.authors.add(self.author)
        self.book.genres.add(self.genre)
        self.goodreads_data = models.GoodreadsBookData.objects.create(
            book=self.book,
            goodreads_id="123",
            cover_image_url="https://example.com/cover.jpg",
            is_primary=True,
        )
        self.book.primary_goodreads_book_data = self.goodreads_data
        self.book.save()

    def test_get_all_data(self):
        """Test GET /api/books/all/ returns complete data."""
        response = self.client.get("/api/books/all/")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("version", data)
        self.assertIn("data", data)
        self.assertIn("books", data["data"])
        self.assertIn("authors", data["data"])
        self.assertIn("genres", data["data"])

        # Check book structure
        books = data["data"]["books"]
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["n"], "Test Book")
        self.assertEqual(books[0]["c"], "https://example.com/cover.jpg")


class PostgresSearchFieldsTests(TestCase):
    """Tests for PostgreSQL-specific search fields."""

    def test_postgres_search_fields_added(self):
        """Test postgres vendor adds full-text search fields."""
        import books.api.views as views

        with mock.patch("django.db.connection.vendor", "postgresql"):
            importlib.reload(views)
            self.assertIn("name__search", views.BookListView.search_fields)
            self.assertIn("name__search", views.AuthorListView.search_fields)

        importlib.reload(views)


class StaffOnlyResponsesAreNotCachedTests(TestCase):
    """The books API must not cache staff responses.

    ``cache_page`` wraps ``dispatch``, so it is consulted before DRF calls
    ``check_permissions``. Eight of these endpoints carried a ``cache_page``
    decorator until 2026-10-17, which meant a response generated for a staff
    member was stored and replayed to anonymous callers - defeating
    ``IsStaffOrHide`` entirely. ``BookAllDataView`` served the whole dataset
    that way, cached for an hour.
    """

    #: One per endpoint that used to be decorated.
    PREVIOUSLY_CACHED_PATHS = [
        "/api/books/",
        "/api/books/meta/",
        "/api/books/genres/",
        "/api/books/genres/tree/",
        "/api/books/version/",
        "/api/books/all/",
    ]

    def setUp(self):
        super().setUp()
        self.staff_user = User.objects.create_user(
            username="cachestaff", password="cachepass", is_staff=True
        )
        models.Book.objects.create(name="Cached", slug="cached", rank=1)

    def test_no_endpoint_replays_a_staff_response_to_anonymous_callers(self):
        staff_client = APIClient()
        staff_client.force_authenticate(user=self.staff_user)
        anonymous = APIClient()

        for path in self.PREVIOUSLY_CACHED_PATHS:
            with self.subTest(path=path):
                warmed = staff_client.get(path)
                self.assertEqual(warmed.status_code, 200)

                response = anonymous.get(path)
                self.assertEqual(response.status_code, 404)

    def test_the_detail_endpoints_do_not_replay_either(self):
        staff_client = APIClient()
        staff_client.force_authenticate(user=self.staff_user)
        anonymous = APIClient()

        path = "/api/books/cached/"
        self.assertEqual(staff_client.get(path).status_code, 200)
        self.assertEqual(anonymous.get(path).status_code, 404)

    def test_no_view_module_applies_cache_page(self):
        """A decorator added back later must fail here, not in production."""
        with open("books/api/views.py", encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("cache_page", source.replace("# ", "").split("Note on")[0])


class SessionAuthenticatedAccessTests(TestCase):
    """The read API has to work for a browser holding a session cookie.

    Every other test in this module authenticates with
    `APIClient.force_authenticate`, which bypasses authentication entirely -
    so none of them noticed that these views named `IsStaffOrHide` without
    naming an authenticator. With `DEFAULT_AUTHENTICATION_CLASSES` empty
    project-wide, DRF saw every caller as anonymous and 404'd the whole read
    API, including the `all/` endpoint the client-side filtering bundle
    fetches. `StaffReadAPIMixin` is what fixes it; this is the test that
    would have caught it.
    """

    READ_PATHS = [
        "/api/books/",
        "/api/books/all/",
        "/api/books/version/",
        "/api/books/meta/",
        "/api/books/genres/",
        "/api/books/genres/tree/",
        "/api/books/authors/",
        "/api/books/lists/",
        "/api/books/search/?q=alpha",
    ]

    def setUp(self):
        clear_all_caches()
        self.staff_user = User.objects.create_user(
            username="sessionstaff", password="sessionpass", is_staff=True
        )
        models.Book.objects.create(name="Alpha Book", rank=1, slug="alpha-book")

    def test_a_staff_session_reaches_every_read_endpoint(self):
        self.client.login(username="sessionstaff", password="sessionpass")
        for path in self.READ_PATHS:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_an_anonymous_session_gets_404_everywhere(self):
        for path in self.READ_PATHS:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_a_non_staff_session_gets_404_everywhere(self):
        User.objects.create_user(username="reader", password="readerpass")
        self.client.login(username="reader", password="readerpass")
        for path in self.READ_PATHS:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class BookAPIMalformedParamsTests(StaffAPITestMixin, TestCase):
    """Malformed query strings answer like absent ones, as games' API does."""

    def test_no_malformed_value_is_a_server_error(self):
        for url in (
            "/api/books/?genres=abc",
            "/api/books/?genres=1,x",
            "/api/books/?order_by=nope",
            "/api/books/?order_by=--rank",
            "/api/books/?order_by=authors__name",
            "/api/books/search/?q=alpha&limit=x",
            "/api/books/unified-search/?q=alpha&book_limit=x&author_limit=1.5",
        ):
            with self.subTest(url=url):
                self.assertLess(self.client.get(url).status_code, 500)

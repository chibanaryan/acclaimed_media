"""
Basic tests for books app admin configuration.
"""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.test import TestCase

from books import models
from books.admin import (
    AuthorAdmin,
    BookAdmin,
    BookGenreAdmin,
    BookListMembershipAdmin,
    BookSeriesAdmin,
    ReadBookAdmin,
    WantToReadBookAdmin,
    WikipediaBookDataAdmin,
)


class AdminRegistrationTests(TestCase):
    """Test that all admin classes are properly registered."""

    def test_author_admin_registered(self):
        """Author model should be registered with AuthorAdmin."""
        self.assertIn(models.Author, admin.site._registry)
        self.assertIsInstance(admin.site._registry[models.Author], AuthorAdmin)

    def test_book_admin_registered(self):
        """Book model should be registered with BookAdmin."""
        self.assertIn(models.Book, admin.site._registry)
        self.assertIsInstance(admin.site._registry[models.Book], BookAdmin)

    def test_book_genre_admin_registered(self):
        """BookGenre model should be registered with BookGenreAdmin."""
        self.assertIn(models.BookGenre, admin.site._registry)
        self.assertIsInstance(admin.site._registry[models.BookGenre], BookGenreAdmin)

    def test_book_series_admin_registered(self):
        """BookSeries model should be registered with BookSeriesAdmin."""
        self.assertIn(models.BookSeries, admin.site._registry)
        self.assertIsInstance(admin.site._registry[models.BookSeries], BookSeriesAdmin)

    def test_wikipedia_book_data_admin_registered(self):
        """WikipediaBookData model should be registered."""
        self.assertIn(models.WikipediaBookData, admin.site._registry)
        self.assertIsInstance(
            admin.site._registry[models.WikipediaBookData], WikipediaBookDataAdmin
        )

    def test_book_list_membership_admin_registered(self):
        """BookListMembership model should be registered."""
        self.assertIn(models.BookListMembership, admin.site._registry)
        self.assertIsInstance(
            admin.site._registry[models.BookListMembership], BookListMembershipAdmin
        )

    def test_read_book_admin_registered(self):
        """ReadBook model should be registered with ReadBookAdmin."""
        self.assertIn(models.ReadBook, admin.site._registry)
        self.assertIsInstance(admin.site._registry[models.ReadBook], ReadBookAdmin)

    def test_want_to_read_book_admin_registered(self):
        """WantToReadBook model should be registered."""
        self.assertIn(models.WantToReadBook, admin.site._registry)
        self.assertIsInstance(
            admin.site._registry[models.WantToReadBook], WantToReadBookAdmin
        )


class AdminConfigurationTests(TestCase):
    """Test admin configuration options."""

    def test_book_admin_list_display(self):
        """BookAdmin should have expected list_display fields."""
        admin_instance = admin.site._registry[models.Book]
        expected_fields = ["name", "slug", "rank", "year_published", "goodreads_id"]
        for field in expected_fields:
            self.assertIn(
                field,
                admin_instance.list_display,
                f"{field} should be in BookAdmin.list_display",
            )

    def test_book_admin_search_fields(self):
        """BookAdmin should allow searching by name and IDs."""
        admin_instance = admin.site._registry[models.Book]
        expected_fields = ["name", "goodreads_id", "isbn"]
        for field in expected_fields:
            self.assertIn(
                field,
                admin_instance.search_fields,
                f"{field} should be in BookAdmin.search_fields",
            )

    def test_author_admin_has_inline(self):
        """AuthorAdmin should have SubsidiaryAuthorInline."""
        admin_instance = admin.site._registry[models.Author]
        self.assertTrue(
            len(admin_instance.inlines) > 0,
            "AuthorAdmin should have at least one inline",
        )


class AdminBehaviorCoverageTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/")
        self.user = get_user_model().objects.create_user(
            username="books-admin-user",
            email="books-admin@example.com",
            password="pass",
            is_staff=True,
            is_superuser=True,
        )
        self.request.user = self.user

    def test_author_admin_get_queryset_and_fallback_count(self):
        author = models.Author.objects.create(name="Author Admin", slug="author-admin")
        book = models.Book.objects.create(name="Book Admin", slug="book-admin", rank=1)
        book.authors.add(author)
        admin_instance = admin.site._registry[models.Author]
        qs = admin_instance.get_queryset(self.request)
        obj = qs.get(pk=author.pk)
        self.assertEqual(obj._book_count, 1)
        self.assertEqual(admin_instance.book_count(author), 1)

    def test_book_genre_admin_book_count(self):
        genre = models.BookGenre.objects.create(name="Genre Admin", slug="genre-admin")
        book = models.Book.objects.create(name="Genre Book", slug="genre-book", rank=2)
        book.genres.add(genre)
        admin_instance = admin.site._registry[models.BookGenre]
        self.assertEqual(admin_instance.book_count(genre), 1)

    def test_book_series_admin_get_queryset_and_fallback_count(self):
        series = models.BookSeries.objects.create(
            name="Series Admin", slug="series-admin"
        )
        book = models.Book.objects.create(
            name="Series Book", slug="series-book", rank=3, series=series
        )
        admin_instance = admin.site._registry[models.BookSeries]
        qs = admin_instance.get_queryset(self.request)
        obj = qs.get(pk=series.pk)
        self.assertEqual(obj._book_count, 1)
        self.assertEqual(admin_instance.book_count(series), 1)
        self.assertEqual(book.series_id, series.id)

    def test_book_admin_queryset_and_helpers(self):
        genre = models.BookGenre.objects.create(name="Admin Genre", slug="admin-genre")
        book = models.Book.objects.create(
            name="Admin Book",
            slug="admin-book",
            rank=4,
        )
        book.genres.add(genre)
        wiki = models.WikipediaBookData.objects.create(
            book=book, page_title="Admin Book Page", all_genres="Drama"
        )
        book.primary_wikipedia_book_data = wiki
        book.save(update_fields=["primary_wikipedia_book_data"])

        admin_instance = admin.site._registry[models.Book]
        qs = admin_instance.get_queryset(self.request)
        obj = qs.get(pk=book.pk)
        self.assertIn("Admin Genre", admin_instance._genres_display(obj))
        link = admin_instance._wikipedia_data_link(obj)
        self.assertIn("/admin/books/wikipediabookdata/", link)
        self.assertIn("View", link)

    def test_book_admin_wikipedia_link_returns_dash_when_missing(self):
        book = models.Book.objects.create(
            name="No Wiki Book",
            slug="no-wiki-book",
            rank=40,
        )
        admin_instance = admin.site._registry[models.Book]
        self.assertEqual(admin_instance._wikipedia_data_link(book), "-")

    def test_wikipedia_book_data_admin_helpers(self):
        book = models.Book.objects.create(name="Wiki Book", slug="wiki-book", rank=5)
        data = models.WikipediaBookData.objects.create(
            book=book,
            page_title="Wiki Book",
            all_genres="Action, RPG",
        )
        admin_instance = admin.site._registry[models.WikipediaBookData]
        self.assertEqual(admin_instance._all_genres_preview(data), "Action, RPG")
        link = admin_instance._wikipedia_link(data)
        self.assertIn("Wiki Book", link)
        self.assertIn("<a href=", link)

    def test_wikipedia_book_data_admin_empty_helpers(self):
        book = models.Book.objects.create(
            name="No Meta Book", slug="no-meta-book", rank=41
        )
        data = models.WikipediaBookData.objects.create(
            book=book,
            page_title="",
            all_genres="",
        )
        admin_instance = admin.site._registry[models.WikipediaBookData]
        self.assertEqual(admin_instance._all_genres_preview(data), "-")
        self.assertEqual(admin_instance._wikipedia_link(data), "-")

    def test_read_and_want_admin_connected_status_and_name(self):
        book = models.Book.objects.create(
            name="Tracked Book", slug="tracked-book", rank=6
        )
        read = models.ReadBook.objects.create(
            user=self.user, book=book, goodreads_id="10"
        )
        want = models.WantToReadBook.objects.create(
            user=self.user, book=book, goodreads_id="11"
        )
        read_admin = admin.site._registry[models.ReadBook]
        want_admin = admin.site._registry[models.WantToReadBook]
        self.assertEqual(read_admin.book_name(read), "Tracked Book")
        self.assertEqual(read_admin.book_status(read), "Connected")
        self.assertEqual(want_admin.book_name(want), "Tracked Book")
        self.assertEqual(want_admin.book_status(want), "Connected")

    def test_read_and_want_admin_orphaned_status_and_name(self):
        read = models.ReadBook.objects.create(
            user=self.user, book=None, goodreads_id="12"
        )
        want = models.WantToReadBook.objects.create(
            user=self.user, book=None, goodreads_id="13"
        )
        read_admin = admin.site._registry[models.ReadBook]
        want_admin = admin.site._registry[models.WantToReadBook]
        self.assertEqual(read_admin.book_name(read), "(orphaned) Goodreads:12")
        self.assertEqual(read_admin.book_status(read), "Orphaned")
        self.assertEqual(want_admin.book_name(want), "(orphaned) Goodreads:13")
        self.assertEqual(want_admin.book_status(want), "Orphaned")

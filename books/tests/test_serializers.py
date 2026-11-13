"""
Tests for books app serializers.
"""

from django.db.models import Count
from django.test import TestCase

from books import models
from books.api import serializers


class BookGenreTreeSerializerTests(TestCase):
    """Tests for BookGenreTreeSerializer helpers."""

    def test_book_count_uses_annotation(self):
        genre = models.BookGenre.objects.create(name="Fiction")
        book = models.Book.objects.create(name="Test Book", rank=1)
        book.genres.add(genre)

        annotated_genre = models.BookGenre.objects.annotate(
            book_count_annotated=Count("books")
        ).get(id=genre.id)

        data = serializers.BookGenreTreeSerializer(annotated_genre).data

        self.assertEqual(data["book_count"], 1)

    def test_a_genre_serialized_on_its_own_asks_for_its_children(self):
        """The tree view hands the serializer every genre by parent; with
        no such map it reads each node's children, in display order."""
        root = models.BookGenre.objects.create(name="Fiction")
        models.BookGenre.objects.create(name="Second", parent=root, display_order=2)
        models.BookGenre.objects.create(name="First", parent=root, display_order=1)

        data = serializers.BookGenreTreeSerializer(root).data

        self.assertEqual(
            [child["name"] for child in data["children"]], ["First", "Second"]
        )
        self.assertEqual(data["children"][0]["children"], [])

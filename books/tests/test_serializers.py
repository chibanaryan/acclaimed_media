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

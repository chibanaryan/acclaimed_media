"""
Books API serializers.

These serializers follow the same patterns as games/api/serializers.py.
"""

from django.db.models import F
from rest_framework import serializers

from .. import models


class IdNameSerializer(serializers.Serializer):
    """Generic serializer for objects with id and name."""

    id = serializers.SerializerMethodField()
    name = serializers.CharField()

    def get_id(self, obj):
        if hasattr(obj, "goodreads_id"):
            return obj.goodreads_id
        return obj.id


class IdSlugNameSerializer(IdNameSerializer):
    """Adds slug field to IdNameSerializer."""

    slug = serializers.CharField()


# Field definitions for book serializers
book_fields = [
    "id",
    "decade_rank",
    "description",
    "authors",
    "genres",
    "goodreads_id",
    "name",
    "name_normalized",
    "cover_image_url",
    "rank",
    "slug",
    "year_published",
    "year_rank",
    "page_count",
]


class BookSummarySerializer(serializers.ModelSerializer):
    """
    Summary serializer for book list views.

    Returns minimal fields needed for list/grid displays.
    """

    id = serializers.IntegerField(source="goodreads_id")
    authors = IdNameSerializer(many=True)
    genres = IdNameSerializer(many=True)

    class Meta:
        model = models.Book
        fields = book_fields


class BookDetailSerializer(BookSummarySerializer):
    """
    Detail serializer for book detail views.

    Includes list appearances in addition to summary fields.
    """

    lists = serializers.SerializerMethodField()

    class Meta:
        model = models.Book
        fields = book_fields + ["lists"]

    def get_lists(self, obj):
        """Get all list appearances for this book."""
        return obj.lists.order_by(
            "list__publisher__name",
            "list__year",
        ).values(
            "rank",
            name=F("list__name"),
            publication=F("list__publisher__name"),
            type=F("list__type"),
            url=F("list__url"),
            year=F("list__year"),
        )


class AuthorSerializer(serializers.ModelSerializer):
    """
    Serializer for Author model.

    Authors are similar to Developers - they can have hierarchical
    relationships (e.g., pen names, collaborators).
    """

    id = serializers.IntegerField(source="goodreads_id")
    books_count = serializers.SerializerMethodField()

    class Meta:
        model = models.Author
        fields = [
            "id",
            "name",
            "slug",
            "books_count",
        ]

    def get_books_count(self, obj):
        """Get books count (may be annotated or computed)."""
        if hasattr(obj, "books_count"):
            return obj.books_count
        return obj.books.count()


class BookGenreSerializer(serializers.ModelSerializer):
    """Basic book genre serializer with hierarchy fields."""

    # The column itself: `parent.id` loaded each genre's parent to read it
    parent_id = serializers.IntegerField(allow_null=True)

    class Meta:
        model = models.BookGenre
        fields = [
            "id",
            "name",
            "slug",
            "level",
            "display_order",
            "path",
            "parent_id",
            "icon_name",
        ]


class BookGenreTreeSerializer(serializers.ModelSerializer):
    """
    Book genre serializer with nested children for tree structure.

    Returns genres in a hierarchical format suitable for tree-based UI.
    """

    children = serializers.SerializerMethodField()
    book_count = serializers.SerializerMethodField()

    class Meta:
        model = models.BookGenre
        fields = [
            "id",
            "name",
            "slug",
            "level",
            "display_order",
            "path",
            "icon_name",
            "children",
            "book_count",
        ]

    def get_children(self, obj):
        """Recursively serialize child genres.

        `BookGenreTreeView` passes every genre, already counted, as
        ``genre_children`` (parent id to children, in display order), as
        games' tree view does: asking each node for its children and its
        count was two queries a genre. Without that map (a genre serialized
        on its own), each node is asked.
        """
        children_by_parent = self.context.get("genre_children")
        if children_by_parent is not None:
            children = children_by_parent.get(obj.id, [])
        else:
            children = obj.children.all().order_by("display_order", "name")
        return BookGenreTreeSerializer(children, many=True, context=self.context).data

    def get_book_count(self, obj):
        """Get count of books with this genre."""
        if hasattr(obj, "book_count_annotated"):
            return obj.book_count_annotated
        return obj.books.count()


class BookListSerializer(serializers.ModelSerializer):
    """Serializer for book lists (uses books.BookList)."""

    # A list can have no publisher: without the default, DRF raised on it,
    # and the lists API was a 500 (music's copy has had it)
    publication = serializers.CharField(source="publisher.name", default="")

    class Meta:
        model = models.BookList
        fields = [
            "id",
            "name",
            "publication",
            "year",
            "type",
            "url",
        ]

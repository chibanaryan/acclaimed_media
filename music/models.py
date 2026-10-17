"""
Music models for the multi-media platform.

Albums are the media item; Artist plays the role Developer plays for games
and Author plays for books. Everything shared lives in ``core.models``, so
this module only adds what is specific to recorded music.
"""

from functools import cached_property
from typing import Any, List, Optional

from django.db import models
from django.db.models import Count
from django.urls import reverse
from django.utils.text import slugify

from core.models import (
    CreatorBase,
    ListBase,
    ListMembershipBase,
    MediaItemBase,
    PublicationBase,
)


class Artist(CreatorBase):
    """
    A recording artist: a band, a solo performer, or a collaborating act.

    Inherits ``name``, ``slug`` and the self-referential ``parent`` hierarchy
    from ``CreatorBase``. The hierarchy models membership and side projects -
    Crazy Horse under Neil Young, Plastic Ono Band under John Lennon - the
    same way subsidiary studios sit under their parent for games. Only root
    artists carry slugs, which ``CreatorBase.save()`` enforces.
    """

    musicbrainz_id = models.CharField(
        max_length=36,
        null=True,
        blank=True,
        db_index=True,
        help_text="MusicBrainz artist MBID",
    )
    wikidata_id = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        db_index=True,
        help_text="Wikidata entity ID (e.g., 'Q1299')",
    )

    class Meta:
        db_table = "music_artist"
        ordering = ["name"]
        verbose_name = "Artist"
        verbose_name_plural = "Artists"
        indexes = [
            models.Index(fields=["musicbrainz_id"]),
            models.Index(fields=["wikidata_id"]),
        ]

    def get_absolute_url(self) -> str:
        return reverse("music:artist-detail", kwargs={"slug": self.slug})


class MusicGenre(models.Model):
    """
    A hierarchical music genre with a denormalized path.

    Mirrors ``books.models.BookGenre``: a parent FK plus a cached ``level``
    and ``path`` so a filter UI can render the tree without walking it. Rows
    arrive from the Wikidata/MusicBrainz metadata pass; the supplied ranking
    files carry no genre data, so this starts empty.
    """

    name = models.CharField(max_length=100, unique=True, db_index=True)
    slug = models.SlugField(max_length=110, unique=True, null=True, blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        help_text="Parent genre in the hierarchy",
    )
    level = models.PositiveSmallIntegerField(
        default=0, help_text="Depth in the hierarchy (0 = root)"
    )
    display_order = models.PositiveSmallIntegerField(
        default=0, help_text="Sort order within the same level"
    )
    path = models.CharField(
        max_length=300,
        blank=True,
        db_index=True,
        help_text="Denormalized ancestry, e.g. 'Rock > Punk Rock > Post-Punk'",
    )
    description = models.TextField(blank=True)
    icon_name = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = "music_musicgenre"
        ordering = ["level", "display_order", "name"]
        verbose_name = "Music Genre"
        verbose_name_plural = "Music Genres"
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["parent", "level"]),
            models.Index(fields=["level", "display_order"]),
        ]

    def __str__(self) -> str:
        return self.path or self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Populate the slug, then recompute level and path from the parent."""
        if not self.slug:
            self.slug = slugify(self.name)
        if self.parent:
            self.level = self.parent.level + 1
            self.path = f"{self.parent.path} > {self.name}"
        else:
            self.level = 0
            self.path = self.name
        super().save(*args, **kwargs)

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def is_leaf(self) -> bool:
        return not self.children.exists()

    def get_descendants(self, include_self: bool = False) -> List["MusicGenre"]:
        """Return every genre below this one, depth first."""
        descendants = []
        if include_self:
            descendants.append(self)
        for child in self.children.all():
            descendants.append(child)
            descendants.extend(child.get_descendants(include_self=False))
        return descendants

    def get_descendant_ids(self, include_self: bool = False) -> List[int]:
        """Return the ids of every genre below this one (for filtering)."""
        ids = []
        if include_self:
            ids.append(self.id)
        for child in self.children.all():
            ids.append(child.id)
            ids.extend(child.get_descendant_ids(include_self=False))
        return ids


class AlbumQuerySet(models.QuerySet):
    """Chainable query helpers that keep album list views off the N+1 path."""

    def with_relations(self) -> "AlbumQuerySet":
        """Prefetch everything an album row renders."""
        return self.prefetch_related("artists", "artists__parent", "genres")

    def with_list_count(self) -> "AlbumQuerySet":
        """Annotate how many source lists each album appears on."""
        return self.annotate(list_count=Count("lists", distinct=True))


class Album(MediaItemBase):
    """
    A studio album, ranked by aggregating published critics' lists.

    ``rank`` comes from the import file, as it does for games; ``year_rank``
    and ``decade_rank`` are derived from it by
    ``core.services.ranking.update_year_decade_ranks``.
    """

    objects = AlbumQuerySet.as_manager()

    year_released = models.PositiveSmallIntegerField(
        null=True, blank=True, db_index=True
    )
    artist_credit = models.CharField(
        max_length=300,
        blank=True,
        help_text=(
            "The credit exactly as published, e.g. 'Neil Young, Crazy Horse'. "
            "Shown verbatim; the artists M2M holds the parsed performers."
        ),
    )
    artists = models.ManyToManyField(Artist, blank=True, related_name="albums")
    genres = models.ManyToManyField(MusicGenre, blank=True, related_name="albums")
    musicbrainz_release_group_id = models.CharField(
        max_length=36,
        null=True,
        blank=True,
        db_index=True,
        help_text="MusicBrainz release-group MBID (Wikidata P436)",
    )
    cover_image_url = models.URLField(null=True, blank=True)
    all_wikidata_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="Every Wikidata ID for this album; the first is primary",
    )

    class Meta:
        db_table = "music_album"
        ordering = ["rank"]
        verbose_name = "Album"
        verbose_name_plural = "Albums"
        indexes = [
            models.Index(fields=["year_released", "rank"]),
            models.Index(fields=["musicbrainz_release_group_id"]),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Generate a unique slug, then defer to MediaItemBase for the rest."""
        if not self.slug:
            self.slug = self._build_unique_slug()
        super().save(*args, **kwargs)

    def _build_unique_slug(self) -> str:
        """Slugify the title, disambiguating with the artist then a counter.

        Album titles collide far more than game titles do - several acts have
        a record called '1999' - so fall back to the credit before resorting
        to a numeric tail.
        """
        base = slugify(self.name) or "album"
        candidates = [base]
        if self.artist_credit:
            with_artist = slugify(f"{self.name} {self.artist_credit}")
            if with_artist and with_artist != base:
                candidates.append(with_artist)

        taken = Album.objects.exclude(pk=self.pk) if self.pk else Album.objects.all()
        for candidate in candidates:
            if not taken.filter(slug=candidate).exists():
                return candidate

        suffix = 2
        while taken.filter(slug=f"{base}-{suffix}").exists():
            suffix += 1
        return f"{base}-{suffix}"

    def get_absolute_url(self) -> str:
        return reverse("music:album-detail", kwargs={"slug": self.slug})

    @cached_property
    def decade(self) -> Optional[int]:
        """The release decade, e.g. 1967 -> 1960."""
        if self.year_released is None:
            return None
        return (self.year_released // 10) * 10

    @cached_property
    def year(self) -> Optional[int]:
        """Alias for ``year_released``.

        ``core/includes/_base_media_row.html`` renders ``item.year``, so a
        media item has to expose the release year under that name to use the
        shared row template.
        """
        return self.year_released

    @cached_property
    def thumbnail(self) -> Optional[str]:
        return self.cover_image_url

    @cached_property
    def image(self) -> Optional[str]:
        return self.cover_image_url

    def get_display_artists(self, max_count: Optional[int] = None) -> list:
        """Return the album's artists, dropping any that parent another.

        When a record is credited to both Neil Young and Crazy Horse, showing
        both is right; when it is credited to an act and its own parent, the
        parent is redundant. Mirrors ``Book.get_display_authors``.
        """
        artists = list(self.artists.all())
        parent_ids = {a.parent_id for a in artists if a.parent_id is not None}
        display = [a for a in artists if a.id not in parent_ids]
        if max_count is not None:
            display = display[:max_count]
        return display


class MusicPublication(PublicationBase):
    """
    A magazine, site or broadcaster that publishes album rankings.

    Carries ``reputation_score`` like ``games.Publication`` does: the music
    lists come from Rolling Stone, Pitchfork, NME and the like, and the same
    editorial-weighting debate applies. The score is staff-edited and does
    not affect ordering.
    """

    reputation_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Editorial reputation score, staff-edited. Display only.",
    )

    class Meta:
        db_table = "music_musicpublication"
        ordering = ["name"]
        verbose_name = "Music Publication"
        verbose_name_plural = "Music Publications"


class MusicList(ListBase):
    """A published album ranking, e.g. 'The 500 Greatest Albums of All Time'."""

    publisher = models.ForeignKey(
        "MusicPublication",
        null=True,
        blank=True,
        related_name="lists",
        on_delete=models.CASCADE,
    )

    class Meta:
        db_table = "music_musiclist"
        ordering = ["order", "type", "publisher", "year", "name"]
        unique_together = ["publisher", "name", "year"]
        indexes = [models.Index(fields=["type", "year"])]
        verbose_name = "Music List"
        verbose_name_plural = "Music Lists"


class AlbumListMembership(ListMembershipBase):
    """One album's position on one list.

    Unranked lists (a '1001 albums' book, an alphabetical hundred) record
    every member at rank 1, matching the convention the games data uses.
    """

    list = models.ForeignKey(
        "MusicList",
        on_delete=models.CASCADE,
        help_text="The list this album appears on",
    )
    album = models.ForeignKey(
        "Album",
        on_delete=models.CASCADE,
        related_name="lists",
        help_text="The album appearing in the list",
    )

    class Meta:
        db_table = "music_albumlistmembership"
        indexes = [
            models.Index(fields=["list", "rank"]),
            models.Index(fields=["album", "list"]),
        ]
        unique_together = [("list", "album")]
        verbose_name = "Album List Membership"
        verbose_name_plural = "Album List Memberships"

    def __str__(self) -> str:
        return f"{self.list} - {self.album} - {self.rank}"

"""Tests for the music template filters and tags."""

import re

from django.template import Context, Template
from django.test import TestCase

from core import constants as core_constants
from music import models
from music.templatetags import music_filters


class SharedFilterReExportTests(TestCase):
    """`{% load music_filters %}` alone must cover the shared filters too."""

    def test_shared_filters_are_registered_on_this_library(self):
        for name in [
            "from_now",
            "tojson",
            "format_duration",
            "markdown",
            "format_decade",
        ]:
            with self.subTest(name=name):
                self.assertIn(name, music_filters.register.filters)

    def test_shared_tags_are_registered_on_this_library(self):
        for name in ["pagination_pages", "pagination_url"]:
            with self.subTest(name=name):
                self.assertIn(name, music_filters.register.tags)

    def test_a_shared_filter_renders_through_the_music_library(self):
        rendered = Template("{% load music_filters %}{{ value|format_decade }}").render(
            Context({"value": "1960-69"})
        )
        self.assertEqual(rendered.strip(), "1960s")


class ListTypeFilterTests(TestCase):
    def test_label_comes_from_core_constants(self):
        self.assertEqual(
            music_filters.get_list_type_label(core_constants.LIST_ALLTIME), "All time"
        )
        self.assertEqual(
            music_filters.get_list_type_label(core_constants.LIST_DECADE), "Decade"
        )
        self.assertEqual(
            music_filters.get_list_type_label(core_constants.LIST_MISC),
            "Miscellaneous",
        )
        self.assertEqual(
            music_filters.get_list_type_label(core_constants.LIST_EOY), "End of year"
        )

    def test_an_unknown_code_returns_itself(self):
        self.assertEqual(music_filters.get_list_type_label("Z"), "Z")

    def test_badge_class_per_type_matches_the_games_page(self):
        # Same colour per list type across the whole site.
        self.assertEqual(
            music_filters.get_list_type_badge_class(core_constants.LIST_ALLTIME),
            "badge-info",
        )
        self.assertEqual(
            music_filters.get_list_type_badge_class(core_constants.LIST_DECADE),
            "badge-success",
        )
        self.assertEqual(
            music_filters.get_list_type_badge_class(core_constants.LIST_MISC),
            "badge-warning",
        )
        self.assertEqual(
            music_filters.get_list_type_badge_class(core_constants.LIST_EOY),
            "badge-error",
        )

    def test_an_unknown_code_gets_the_ghost_badge(self):
        self.assertEqual(music_filters.get_list_type_badge_class("Z"), "badge-ghost")


class MusicGenreIconTests(TestCase):
    def test_a_mapped_root_genre_gets_its_icon(self):
        genre = models.MusicGenre.objects.create(name="Jazz")
        self.assertEqual(music_filters.music_genre_icon(genre), "mdi-saxophone")

    def test_a_child_genre_inherits_the_root_icon(self):
        rock = models.MusicGenre.objects.create(name="Rock")
        punk = models.MusicGenre.objects.create(name="Punk Rock", parent=rock)
        self.assertEqual(music_filters.music_genre_icon(punk), "mdi-guitar-electric")

    def test_an_explicit_icon_name_wins(self):
        genre = models.MusicGenre.objects.create(name="Jazz", icon_name="mdi-custom")
        self.assertEqual(music_filters.music_genre_icon(genre), "mdi-custom")

    def test_an_unmapped_genre_falls_back(self):
        genre = models.MusicGenre.objects.create(name="Bubblegum Bass")
        self.assertEqual(
            music_filters.music_genre_icon(genre), music_filters.DEFAULT_GENRE_ICON
        )

    def test_a_string_genre_name_is_accepted(self):
        self.assertEqual(music_filters.music_genre_icon("Metal"), "mdi-skull")
        self.assertEqual(
            music_filters.music_genre_icon("Unknown"),
            music_filters.DEFAULT_GENRE_ICON,
        )

    def test_none_falls_back(self):
        self.assertEqual(
            music_filters.music_genre_icon(None), music_filters.DEFAULT_GENRE_ICON
        )

    def test_every_root_gets_its_own_glyph(self):
        """Two roots sharing an icon makes the column decoration, not data.

        Rock and Metal both carried mdi-guitar-electric, and Blues and Folk
        both mdi-guitar-acoustic. The fallback is held out too: R&B was
        mapped to it, so a genre that had dropped out of the map looked
        exactly like one that had not.
        """
        icons = list(music_filters.MUSIC_GENRE_CATEGORY_ICONS.values())
        duplicated = sorted({icon for icon in icons if icons.count(icon) > 1})
        self.assertEqual(duplicated, [])
        self.assertNotIn(music_filters.DEFAULT_GENRE_ICON, icons)

    def test_every_mapped_icon_is_declared_in_the_font_subset(self):
        """Every genre icon must have a codepoint, or it renders as a box.

        This asserts over the whole map rather than just the fallback: when
        it only checked the fallback, 13 of the 15 genre icons were missing
        from the subset and nothing noticed, because MusicGenre was empty so
        no badge had ever rendered.
        """
        with open("games/static/games/css/mdi-subset.css", encoding="utf-8") as handle:
            subset = handle.read()

        expected = set(music_filters.MUSIC_GENRE_CATEGORY_ICONS.values())
        expected.add(music_filters.DEFAULT_GENRE_ICON)
        missing = sorted(name for name in expected if f".{name}::before" not in subset)
        self.assertEqual(
            missing,
            [],
            f"Icons missing from mdi-subset.css: {missing}. "
            "Add them and re-run scripts/build_mdi_subset.sh.",
        )

    def test_the_subset_css_and_base_template_agree_on_codepoints(self):
        """base.html serves the runtime CSS; a drift there means a blank box."""
        with open("games/static/games/css/mdi-subset.css", encoding="utf-8") as handle:
            subset = handle.read()
        with open("games/templates/base.html", encoding="utf-8") as handle:
            base = handle.read()

        pattern = r"\.{}::before\s*{{\s*content:\s*\"(\\F[0-9A-Fa-f]+)\""
        mismatched = []
        for name in sorted(set(music_filters.MUSIC_GENRE_CATEGORY_ICONS.values())):
            in_subset = re.search(pattern.format(re.escape(name)), subset)
            in_base = re.search(pattern.format(re.escape(name)), base)
            if not in_base:
                mismatched.append(f"{name}: absent from base.html")
            elif in_subset and in_subset.group(1).upper() != in_base.group(1).upper():
                mismatched.append(f"{name}: {in_subset.group(1)} != {in_base.group(1)}")
        self.assertEqual(mismatched, [])


class ArtistDisplayTests(TestCase):
    def setUp(self):
        self.parent = models.Artist.objects.create(name="Neil Young", slug="neil-young")

    def test_a_root_artist_shows_its_bare_name(self):
        self.assertEqual(music_filters.artist_display_name(self.parent), "Neil Young")

    def test_a_subsidiary_is_qualified_by_its_parent(self):
        child = models.Artist.objects.create(name="Crazy Horse", parent=self.parent)
        self.assertEqual(
            music_filters.artist_display_name(child), "Crazy Horse (Neil Young)"
        )


class FormatArtistListTests(TestCase):
    def _artists(self, *names):
        return [models.Artist(name=name) for name in names]

    def test_no_artists_gives_an_empty_string(self):
        self.assertEqual(music_filters.format_artist_list([]), "")

    def test_one_artist(self):
        self.assertEqual(
            music_filters.format_artist_list(self._artists("Nico")), "Nico"
        )

    def test_two_artists_are_joined_with_an_ampersand(self):
        self.assertEqual(
            music_filters.format_artist_list(self._artists("Brian Eno", "David Byrne")),
            "Brian Eno & David Byrne",
        )

    def test_three_artists_list_in_full(self):
        self.assertEqual(
            music_filters.format_artist_list(self._artists("A", "B", "C")),
            "A, B & C",
        )

    def test_more_than_the_maximum_summarizes_the_tail(self):
        self.assertEqual(
            music_filters.format_artist_list(self._artists("A", "B", "C", "D", "E")),
            "A, B, C & 2 more",
        )

    def test_the_maximum_is_configurable(self):
        self.assertEqual(
            music_filters.format_artist_list(self._artists("A", "B", "C"), 1),
            "A & 2 more",
        )


class ArtistLinksTests(TestCase):
    def setUp(self):
        self.album = models.Album.objects.create(
            name="Rust Never Sleeps",
            rank=1,
            artist_credit="Neil Young, Crazy Horse",
        )

    def test_links_every_artist_with_a_slug(self):
        young = models.Artist.objects.create(name="Neil Young", slug="neil-young")
        horse = models.Artist.objects.create(name="Crazy Horse", slug="crazy-horse")
        self.album.artists.set([young, horse])
        rendered = music_filters.artist_links(self.album)
        self.assertIn('href="/music/artists/neil-young/"', rendered)
        self.assertIn('href="/music/artists/crazy-horse/"', rendered)
        self.assertIn("Neil Young", rendered)
        self.assertIn("Crazy Horse", rendered)

    def test_falls_back_to_the_raw_credit_when_no_artist_has_a_slug(self):
        # A subsidiary artist has its slug cleared, so it cannot be linked.
        young = models.Artist.objects.create(name="Neil Young", slug="neil-young")
        horse = models.Artist.objects.create(name="Crazy Horse", parent=young)
        self.album.artists.set([horse])
        self.assertEqual(
            music_filters.artist_links(self.album), "Neil Young, Crazy Horse"
        )

    def test_falls_back_to_the_raw_credit_with_no_artists_at_all(self):
        self.assertEqual(
            music_filters.artist_links(self.album), "Neil Young, Crazy Horse"
        )

    def test_a_name_with_markup_characters_is_escaped(self):
        artist = models.Artist.objects.create(name="A & B <x>", slug="a-b")
        self.album.artists.set([artist])
        rendered = music_filters.artist_links(self.album)
        self.assertIn("A &amp; B &lt;x&gt;", rendered)
        self.assertNotIn("<x>", rendered)


class AlbumUrlTagTests(TestCase):
    def setUp(self):
        self.album = models.Album.objects.create(
            name="Pet Sounds",
            rank=1,
            artist_credit="The Beach Boys",
            year_released=1966,
        )

    def test_rank_url_highlights_the_album(self):
        self.assertEqual(
            music_filters.album_rank_url(self.album),
            f"/music/?highlight={self.album.id}",
        )

    def test_year_url_filters_to_the_release_year(self):
        self.assertEqual(
            music_filters.album_year_url(self.album),
            f"/music/?start=1966&end=1966&highlight={self.album.id}",
        )

    def test_year_url_falls_back_to_the_bare_rankings_without_a_year(self):
        album = models.Album.objects.create(name="Undated", rank=2)
        self.assertEqual(music_filters.album_year_url(album), "/music/")

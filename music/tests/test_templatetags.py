"""Tests for the music template filters and tags."""

import re

from django.template import Context, Template
from django.test import TestCase

from core import constants as core_constants
from music import models
from music.templatetags import music_filters
from music.tests.site import setUpModule, tearDownModule  # noqa: F401


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


class ArtistLinksTests(TestCase):
    def setUp(self):
        self.album = models.Album.objects.create(
            name="Apollo", rank=1, artist_credit="Brian Eno, Daniel Lanois & Roger Eno"
        )

    def _credit(self, *names):
        for position, name in enumerate(names):
            artist = models.Artist.objects.create(
                name=name, slug=name.lower().replace(" ", "-")
            )
            models.AlbumCredit.objects.create(
                album=self.album, artist=artist, position=position
            )

    def test_links_every_credited_artist(self):
        self._credit("Neil Young", "Crazy Horse")
        rendered = music_filters.artist_links(self.album)
        self.assertIn('href="/artists/neil-young/"', rendered)
        self.assertIn('href="/artists/crazy-horse/"', rendered)

    def test_the_credit_style_and_order(self):
        # Credit order, not alphabetical, joined "A, B & C" with the
        # separators dimmed - what the client's _artistCreditHtml writes too.
        self._credit("Roger Eno", "Daniel Lanois", "Brian Eno")
        rendered = str(music_filters.artist_links(self.album))
        self.assertLess(rendered.index("Roger Eno"), rendered.index("Daniel Lanois"))
        self.assertLess(rendered.index("Daniel Lanois"), rendered.index("Brian Eno"))
        self.assertIn('<span class="text-base-content/30">, </span>', rendered)
        self.assertIn('<span class="text-base-content/30"> &amp; </span>', rendered)

    def test_two_artists_take_only_the_ampersand(self):
        self._credit("Paul McCartney", "Wings")
        rendered = str(music_filters.artist_links(self.album))
        self.assertNotIn(", </span>", rendered)
        self.assertIn(" &amp; </span>", rendered)

    def test_a_compilation_shows_its_credit_text_unlinked(self):
        self.album.artist_credit = "Various Artists"
        self.album.various_artists = True
        self.assertEqual(music_filters.artist_links(self.album), "Various Artists")

    def test_a_credit_under_another_name_links_to_the_artist(self):
        prince = models.Artist.objects.create(name="Prince", slug="prince")
        models.AlbumCredit.objects.create(
            album=self.album,
            artist=prince,
            variant=1,
            credited_name="Prince and the Revolution",
        )
        self.assertEqual(
            str(music_filters.artist_links(self.album)),
            '<a href="/artists/prince/" class="link link-hover" '
            'title="Prince">Prince and the Revolution</a>',
        )

    def test_various_artists_follows_the_named_artists_unlinked(self):
        self._credit("Jimmy Cliff")
        self.album.various_artists = True
        rendered = str(music_filters.artist_links(self.album))
        self.assertTrue(
            rendered.endswith(
                '<span class="text-base-content/30"> &amp; </span>Various Artists'
            )
        )
        self.assertEqual(rendered.count("<a "), 1)

    def test_artist_names_uses_their_own_names(self):
        prince = models.Artist.objects.create(name="Prince", slug="prince")
        nico = models.Artist.objects.create(name="Nico")
        rendered = str(music_filters.artist_names([prince, nico], "link"))
        self.assertEqual(
            rendered,
            '<a href="/artists/prince/" class="link">Prince</a>'
            '<span class="text-base-content/30"> &amp; </span>Nico',
        )

    def test_an_artist_without_a_slug_is_plain_text(self):
        artist = models.Artist.objects.create(name="Unslugged")
        models.AlbumCredit.objects.create(album=self.album, artist=artist)
        rendered = str(music_filters.artist_links(self.album))
        self.assertEqual(rendered, "Unslugged")

    def test_a_name_with_markup_characters_is_escaped(self):
        artist = models.Artist.objects.create(name="A & B <x>", slug="a-b")
        models.AlbumCredit.objects.create(album=self.album, artist=artist)
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
            f"/?highlight={self.album.id}",
        )

    def test_year_url_filters_to_the_release_year(self):
        self.assertEqual(
            music_filters.album_year_url(self.album),
            f"/?start=1966&end=1966&highlight={self.album.id}",
        )

    def test_year_url_falls_back_to_the_bare_rankings_without_a_year(self):
        album = models.Album.objects.create(name="Undated", rank=2)
        self.assertEqual(music_filters.album_year_url(album), "/")

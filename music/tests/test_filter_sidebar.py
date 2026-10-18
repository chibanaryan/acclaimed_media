"""The album rankings sidebar uses the shared filter components.

It used to carry a row of decade chips and a flat <select> of every genre,
where a root genre and one of its styles were indistinguishable. It now
renders `core/includes/_year_grid.html` and `core/includes/_genre_filter.html`
- the same two the games rankings page renders - which need their data in a
particular shape, and need facet counts that respond to the other filters.
"""

from bs4 import BeautifulSoup
from django.test import TestCase
from django.urls import reverse

from music import models, views
from music.tests.test_views import MusicDataMixin


class GenreTreeDataTests(MusicDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.electronic = models.MusicGenre.objects.create(name="Electronic")
        self.ambient = models.MusicGenre.objects.create(
            name="Ambient", parent=self.electronic, level=1
        )
        self.kid_a.genres.set([self.electronic, self.ambient])

    def test_options_carry_the_shape_the_shared_tree_reads(self):
        options = {option["name"]: option for option in views.genre_tree_options()}
        self.assertEqual(options["Ambient"]["level"], 1)
        self.assertEqual(options["Ambient"]["parent_id"], self.electronic.id)
        # The tree calls it item_count; games' payload calls it game_count.
        self.assertEqual(options["Ambient"]["item_count"], 1)

    def test_the_page_renders_the_tree_and_not_a_flat_select(self):
        page = self.client.get(reverse("music:home")).content.decode()
        soup = BeautifulSoup(page, "html.parser")
        self.assertTrue(soup.select(".genre-filter"))
        self.assertTrue(soup.select(".genre-tree"))
        self.assertIsNone(soup.select_one('select[name="genres"]'))
        # The form still carries the selection, as a field HTMX can send.
        self.assertEqual(
            soup.select_one('#album-filters [name="genres"]')["type"], "hidden"
        )

    def test_the_tree_gets_the_music_icon_map(self):
        page = self.client.get(reverse("music:home")).content.decode()
        soup = BeautifulSoup(page, "html.parser")
        block = soup.select_one("#genre-icons-data")
        self.assertIsNotNone(block, "the genre tree has no icon map")
        self.assertIn("Electronic", block.text)


class YearGridTests(MusicDataMixin, TestCase):
    def test_the_page_renders_the_heatmap(self):
        page = self.client.get(reverse("music:home")).content.decode()
        soup = BeautifulSoup(page, "html.parser")
        self.assertTrue(soup.select(".year-grid-wrapper"))
        self.assertTrue(soup.select("#year-counts-data"))

    def test_the_year_range_is_carried_by_hidden_fields(self):
        page = self.client.get(reverse("music:home")).content.decode()
        soup = BeautifulSoup(page, "html.parser")
        for name in ("start", "end"):
            with self.subTest(field=name):
                field = soup.select_one(f'#album-filters [name="{name}"]')
                self.assertEqual(field["type"], "hidden")

    def test_the_grid_counts_albums_per_year(self):
        response = self.client.get(reverse("music:home"))
        counts = {row["year"]: row["count"] for row in response.context["year_counts"]}
        self.assertEqual(counts[1966], 1)
        self.assertEqual(counts[2000], 1)


class FacetCountTests(MusicDataMixin, TestCase):
    """A facet count answers "how many would this leave me"."""

    def test_year_counts_ignore_the_year_filter_itself(self):
        # Otherwise every cell outside the selected range would read zero and
        # there would be no way to widen the range from the grid.
        response = self.client.get(reverse("music:home"), {"start": 1966, "end": 1966})
        counts = {row["year"]: row["count"] for row in response.context["year_counts"]}
        self.assertEqual(counts[1979], 1)
        self.assertEqual(counts[2000], 1)

    def test_year_counts_do_respect_the_other_filters(self):
        response = self.client.get(reverse("music:home"), {"q": "revolver"})
        counts = {row["year"]: row["count"] for row in response.context["year_counts"]}
        self.assertEqual(counts, {1966: 1})

    def test_genre_counts_ignore_the_genre_filter_itself(self):
        electronic = models.MusicGenre.objects.create(name="Electronic")
        self.kid_a.genres.set([electronic])
        response = self.client.get(reverse("music:home"), {"genres": str(self.rock.id)})
        counts = response.context["genre_counts"]
        self.assertEqual(counts[str(electronic.id)], 1)

    def test_genre_counts_respect_the_year_filter(self):
        response = self.client.get(reverse("music:home"), {"start": 1990})
        self.assertEqual(response.context["genre_counts"], {})

    def test_the_counts_are_rendered_for_the_sidebar_to_pick_up(self):
        page = self.client.get(reverse("music:home")).content.decode()
        soup = BeautifulSoup(page, "html.parser")
        self.assertTrue(soup.select("#year-counts-update"))
        self.assertTrue(soup.select("#genre-counts-update"))


class FilterStateTests(MusicDataMixin, TestCase):
    def test_the_component_starts_from_the_servers_filter_state(self):
        response = self.client.get(
            reverse("music:home"),
            {"q": "rust", "start": 1970, "end": 1979, "genres": str(self.rock.id)},
        )
        filters = response.context["filters"]
        self.assertEqual(filters["q"], "rust")
        self.assertEqual(filters["start"], 1970)
        self.assertEqual(filters["end"], 1979)
        self.assertEqual(filters["genres"], [str(self.rock.id)])

    def test_an_absent_year_range_becomes_the_full_range(self):
        # The grid spells "no year filter" as the whole range selected; the
        # URL spells it as no parameters at all.
        response = self.client.get(reverse("music:home"))
        filters = response.context["filters"]
        self.assertEqual(filters["start"], response.context["min_year"])
        self.assertEqual(filters["end"], response.context["max_year"])

    def test_the_state_is_rendered_as_json_for_the_component(self):
        page = self.client.get(reverse("music:home")).content.decode()
        soup = BeautifulSoup(page, "html.parser")
        self.assertTrue(soup.select("#filters-data"))
        self.assertTrue(soup.select("#genres-data"))


class ApplyAlbumFiltersTests(MusicDataMixin, TestCase):
    """The filter function the page and its facet counts share."""

    def _names(self, queryset):
        return sorted(queryset.values_list("name", flat=True))

    def test_every_dimension_applies(self):
        base = models.Album.objects.all()
        self.assertEqual(
            self._names(views.apply_album_filters(base, {"q": "revolver"})),
            ["Revolver"],
        )
        self.assertEqual(
            self._names(views.apply_album_filters(base, {"start": "2000"})),
            ["Kid A"],
        )
        self.assertEqual(
            self._names(views.apply_album_filters(base, {"genres": str(self.rock.id)})),
            ["Revolver"],
        )
        self.assertEqual(
            self._names(
                views.apply_album_filters(base, {"artists": str(self.young.id)})
            ),
            ["Rust Never Sleeps"],
        )

    def test_a_skipped_dimension_is_left_out(self):
        base = models.Album.objects.all()
        params = {"q": "revolver", "start": "2000"}
        self.assertEqual(self._names(views.apply_album_filters(base, params)), [])
        self.assertEqual(
            self._names(views.apply_album_filters(base, params, skip=("year",))),
            ["Revolver"],
        )
        self.assertEqual(
            self._names(views.apply_album_filters(base, params, skip=("q",))),
            ["Kid A"],
        )


class GenreHierarchyTests(MusicDataMixin, TestCase):
    """Selecting a genre includes its styles, as the games filter does."""

    def setUp(self):
        super().setUp()
        self.classical = models.MusicGenre.objects.create(name="Classical")
        self.modern = models.MusicGenre.objects.create(
            name="Modern Classical", parent=self.classical, level=1
        )
        # One album, carrying both the root and the style - the shape that
        # made the sidebar claim Classical had two albums.
        self.kid_a.genres.set([self.classical, self.modern])

    def test_selecting_a_root_matches_its_styles(self):
        response = self.client.get(
            reverse("music:home"), {"genres": str(self.classical.id)}
        )
        self.assertEqual(
            [album.name for album in response.context["albums"]], ["Kid A"]
        )

    def test_a_style_only_matches_itself(self):
        other = models.Album.objects.create(name="Orchestral", rank=9)
        other.genres.set([self.classical])
        response = self.client.get(
            reverse("music:home"), {"genres": str(self.modern.id)}
        )
        self.assertEqual(
            [album.name for album in response.context["albums"]], ["Kid A"]
        )

    def test_an_album_is_counted_once_per_subtree(self):
        counts = self.client.get(reverse("music:home")).context["genre_counts"]
        self.assertEqual(counts[str(self.classical.id)], 1)
        self.assertEqual(counts[str(self.modern.id)], 1)

    def test_the_unfiltered_tree_counts_match(self):
        options = {o["name"]: o["item_count"] for o in views.genre_tree_options()}
        self.assertEqual(options["Classical"], 1)
        self.assertEqual(options["Modern Classical"], 1)

    def test_a_root_count_sums_distinct_albums_across_its_styles(self):
        jazz = models.Album.objects.create(name="Ascension", rank=8)
        jazz.genres.set([self.modern])
        counts = self.client.get(reverse("music:home")).context["genre_counts"]
        self.assertEqual(counts[str(self.classical.id)], 2)


class AlbumDownloadTests(MusicDataMixin, TestCase):
    """The CSV the sidebar offers, as the games sidebar does."""

    def _rows(self, **params):
        response = self.client.get(reverse("music:download"), params)
        self.assertEqual(response.status_code, 200)
        return response.content.decode().splitlines()

    def test_the_csv_carries_a_header_and_every_album(self):
        rows = self._rows()
        self.assertTrue(rows[0].startswith("Filtered Rank,Global Rank,Name,Year"))
        self.assertEqual(len(rows), 4)

    def test_it_respects_the_current_filters(self):
        rows = self._rows(q="revolver")
        self.assertEqual(len(rows), 2)
        self.assertIn("Revolver", rows[1])

    def test_the_filename_is_the_heading(self):
        response = self.client.get(
            reverse("music:download"), {"start": 1970, "end": 1979}
        )
        self.assertIn(
            "most-acclaimed-albums-of-the-1970s.csv",
            response["Content-Disposition"],
        )

    def test_anonymous_callers_get_404(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("music:download")).status_code, 404)

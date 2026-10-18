"""Tests for the shared year/decade ranking service.

The service is parameterized by model, table and year field so each media
type can share it; these tests drive it through both the music and games
models, and cover the PostgreSQL window-function path with mocks.
"""

from unittest import mock

from django.test import SimpleTestCase, TestCase

from core.services import ranking
from core.services.ranking import update_year_decade_ranks, year_to_decade
from games import models as game_models
from music import models as music_models


class YearToDecadeTests(TestCase):
    def test_converts_a_year_to_its_decade(self):
        self.assertEqual(year_to_decade(1985), 1980)
        self.assertEqual(year_to_decade(1990), 1990)
        self.assertEqual(year_to_decade(2009), 2000)


class UpdateYearDecadeRanksTests(TestCase):
    """The SQLite path, exercised through the Album model."""

    def _album(self, name, rank, year):
        return music_models.Album.objects.create(
            name=name, rank=rank, year_released=year
        )

    def test_ranks_within_each_year(self):
        self._album("Best of 1966", 1, 1966)
        self._album("Second of 1966", 5, 1966)
        self._album("Only 1979", 3, 1979)

        updated, years = update_year_decade_ranks(
            music_models.Album, "music_album", "year_released"
        )
        self.assertEqual(updated, 3)
        self.assertEqual(years, 2)

        ranks = {
            album.name: album.year_rank for album in music_models.Album.objects.all()
        }
        self.assertEqual(ranks["Best of 1966"], 1)
        self.assertEqual(ranks["Second of 1966"], 2)
        self.assertEqual(ranks["Only 1979"], 1)

    def test_ranks_within_each_decade(self):
        self._album("Early sixties", 2, 1963)
        self._album("Late sixties", 1, 1968)
        self._album("Seventies", 4, 1975)

        update_year_decade_ranks(music_models.Album, "music_album", "year_released")
        ranks = {
            album.name: album.decade_rank for album in music_models.Album.objects.all()
        }
        # Decade rank follows the global rank, not the year.
        self.assertEqual(ranks["Late sixties"], 1)
        self.assertEqual(ranks["Early sixties"], 2)
        self.assertEqual(ranks["Seventies"], 1)

    def test_an_empty_table_is_handled(self):
        updated, years = update_year_decade_ranks(
            music_models.Album, "music_album", "year_released"
        )
        self.assertEqual(updated, 0)
        self.assertEqual(years, 0)

    def test_an_item_with_no_year_forms_its_own_group(self):
        # PostgreSQL partitions NULLs together; the Python path must not raise.
        music_models.Album.objects.create(name="Undated", rank=1)
        music_models.Album.objects.create(name="Also undated", rank=2)
        self._album("Dated", 3, 1999)

        updated, years = update_year_decade_ranks(
            music_models.Album, "music_album", "year_released"
        )
        self.assertEqual(updated, 3)
        self.assertEqual(years, 2)
        undated = music_models.Album.objects.get(name="Undated")
        self.assertEqual(undated.decade_rank, 1)
        self.assertEqual(
            music_models.Album.objects.get(name="Also undated").decade_rank, 2
        )

    def test_it_also_drives_the_game_model(self):
        game_models.Game.objects.create(name="Older", rank=2, year_of_release=1998)
        game_models.Game.objects.create(name="Newer", rank=1, year_of_release=1998)
        updated, years = update_year_decade_ranks(
            game_models.Game, "games_game", "year_of_release"
        )
        self.assertEqual(updated, 2)
        self.assertEqual(years, 1)
        self.assertEqual(game_models.Game.objects.get(name="Newer").year_rank, 1)
        self.assertEqual(game_models.Game.objects.get(name="Older").year_rank, 2)

    def test_several_years_each_get_their_own_ranking(self):
        for index in range(5):
            self._album(f"Album {index}", index + 1, 1990 + index)
        updated, years = update_year_decade_ranks(
            music_models.Album, "music_album", "year_released"
        )
        self.assertEqual(updated, 5)
        self.assertEqual(years, 5)
        self.assertEqual(
            set(music_models.Album.objects.values_list("year_rank", flat=True)), {1}
        )


class PostgresPathTests(TestCase):
    """The window-function path, which SQLite cannot run."""

    @mock.patch("core.services.ranking.connection")
    def test_runs_two_window_function_updates(self, mock_connection):
        mock_connection.vendor = "postgresql"
        mock_cursor = mock.MagicMock()
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        mock_model = mock.MagicMock()
        mock_model.objects.count.return_value = 7
        mock_values = mock_model.objects.values.return_value
        mock_values.distinct.return_value.count.return_value = 3

        updated, years = update_year_decade_ranks(
            mock_model, "music_album", "year_released"
        )

        self.assertEqual(updated, 7)
        self.assertEqual(years, 3)
        self.assertEqual(mock_cursor.execute.call_count, 2)

    @mock.patch("core.services.ranking.connection")
    def test_the_statements_target_the_given_table_and_year_field(
        self, mock_connection
    ):
        mock_connection.vendor = "postgresql"
        mock_cursor = mock.MagicMock()
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        mock_model = mock.MagicMock()
        mock_model.objects.count.return_value = 1
        mock_values = mock_model.objects.values.return_value
        mock_values.distinct.return_value.count.return_value = 1

        update_year_decade_ranks(mock_model, "music_album", "year_released")

        statements = " ".join(
            call.args[0] for call in mock_cursor.execute.call_args_list
        )
        self.assertIn("UPDATE music_album", statements)
        self.assertIn("PARTITION BY year_released", statements)
        self.assertIn("(year_released / 10) * 10", statements)
        self.assertIn("SET year_rank", statements)
        self.assertIn("SET decade_rank", statements)


class RankDistributionTests(SimpleTestCase):
    """Binning for the rank distribution chart, shared by both sections."""

    def test_bins_span_the_whole_ranking(self):
        bins = ranking.rank_distribution([1, 50, 100], max_rank=100, bin_count=10)
        self.assertEqual(len(bins), 10)
        self.assertEqual(bins[0]["binStart"], 1)
        self.assertEqual(bins[-1]["binEnd"], 100)

    def test_each_rank_lands_in_one_bin(self):
        bins = ranking.rank_distribution([1, 2, 11, 100], max_rank=100, bin_count=10)
        self.assertEqual(sum(entry["count"] for entry in bins), 4)
        self.assertEqual(bins[0]["count"], 2)
        self.assertEqual(bins[1]["count"], 1)
        self.assertEqual(bins[9]["count"], 1)

    def test_the_axis_does_not_move_with_the_filtered_set(self):
        # Bins come from the global maximum, so a filtered chart is read
        # against the same axis as an unfiltered one.
        bins = ranking.rank_distribution([5], max_rank=1000, bin_count=10)
        self.assertEqual(bins[-1]["binEnd"], 1000)
        self.assertEqual(sum(entry["count"] for entry in bins), 1)

    def test_ranks_outside_the_axis_are_dropped(self):
        bins = ranking.rank_distribution([0, None, 5000], max_rank=100, bin_count=10)
        self.assertEqual(sum(entry["count"] for entry in bins), 0)

    def test_an_empty_ranking_has_no_bins(self):
        self.assertEqual(ranking.rank_distribution([1, 2], 0, 10), [])
        self.assertEqual(ranking.rank_distribution([1, 2], 100, 0), [])

    def test_a_ranking_smaller_than_the_bin_count_still_bins(self):
        bins = ranking.rank_distribution([1, 2, 3], max_rank=3, bin_count=10)
        self.assertEqual(sum(entry["count"] for entry in bins), 3)

"""Tests for migration 0113 remapping the leftover Other genres."""

import importlib

from django.test import TestCase
from django.utils.text import slugify

from games.models import Game, WikipediaGameData, WikipediaGenre


class _FakeApps:
    """Minimal apps registry shim for calling RunPython helpers in tests."""

    MODELS = {
        ("games", "Game"): Game,
        ("games", "WikipediaGameData"): WikipediaGameData,
        ("games", "WikipediaGenre"): WikipediaGenre,
    }

    def get_model(self, app_label, model_name):
        return self.MODELS[(app_label, model_name)]


class RemapOtherGenreLeftoversMigrationTests(TestCase):
    """Tests for moving the leftover Other genres to canonical genres."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = importlib.import_module(
            "games.migrations.0113_remap_other_genre_leftovers"
        )

    def _genre(self, name, parent=None):
        genre, _ = WikipediaGenre.objects.get_or_create(
            name=name,
            defaults={
                "slug": slugify(name),
                "parent": parent,
                "level": parent.level + 1 if parent else 0,
                "path": f"{parent.path} > {name}" if parent else name,
            },
        )
        return genre

    def _game(self, name, rank, genres, primary, all_genres):
        game = Game.objects.create(name=name, rank=rank)
        game.wikipedia_genres.add(*genres)
        WikipediaGameData.objects.create(
            game=game,
            page_title=name,
            primary_genre=primary,
            all_genres=all_genres,
            is_primary=True,
        )
        return game

    def setUp(self):
        self.other = self._genre("Other")
        self.dating_sim = self._genre("dating sim", self.other)
        self.word_game = self._genre("Word game", self.other)
        self.level_editor = self._genre("Level editor and platformer", self.other)

    def _names(self, game):
        return set(game.wikipedia_genres.values_list("name", flat=True))

    def test_forwards_moves_dating_sim_to_life_simulation(self):
        adventure = self._genre("Adventure")
        game = self._game(
            "Thirsty Suitors",
            1,
            [self.dating_sim, adventure],
            "Adventure",
            "Adventure, dating sim, Role-Playing",
        )

        self.migration.forwards(_FakeApps(), None)

        game.refresh_from_db()
        self.assertEqual(self._names(game), {"Adventure", "Life Simulation"})
        life_sim = WikipediaGenre.objects.get(name="Life Simulation")
        self.assertEqual(life_sim.path, "Simulation > Life Simulation")

        metadata = WikipediaGameData.objects.get(game=game)
        self.assertEqual(metadata.primary_genre, "Adventure")
        self.assertEqual(
            metadata.all_genres, "Adventure, Life Simulation, Role-Playing"
        )
        self.assertFalse(WikipediaGenre.objects.filter(name="dating sim").exists())

    def test_forwards_moves_word_game_to_puzzle(self):
        game = self._game("Wordle", 2, [self.word_game], "Word game", "Word game")

        self.migration.forwards(_FakeApps(), None)

        game.refresh_from_db()
        self.assertEqual(self._names(game), {"Puzzle"})
        puzzle = WikipediaGenre.objects.get(name="Puzzle")
        self.assertEqual(puzzle.parent.name, "Puzzle & Casual")

        metadata = WikipediaGameData.objects.get(game=game)
        self.assertEqual(metadata.primary_genre, "Puzzle")
        self.assertEqual(metadata.all_genres, "Puzzle")
        self.assertFalse(WikipediaGenre.objects.filter(name="Word game").exists())

    def test_forwards_deletes_unused_level_editor_genre(self):
        self.migration.forwards(_FakeApps(), None)

        self.assertFalse(
            WikipediaGenre.objects.filter(name="Level editor and platformer").exists()
        )
        # The fallback root stays - the normalizer still assigns unknowns to it
        self.assertTrue(WikipediaGenre.objects.filter(name="Other").exists())

    def test_forwards_leaves_other_unknown_genres_alone(self):
        unknown = self._genre("Rhythm Adventure", self.other)
        game = self._game(
            "Unknown", 3, [unknown], "Rhythm Adventure", "Rhythm Adventure"
        )

        self.migration.forwards(_FakeApps(), None)

        game.refresh_from_db()
        self.assertEqual(self._names(game), {"Rhythm Adventure"})
        unknown.refresh_from_db()
        self.assertEqual(unknown.parent, self.other)

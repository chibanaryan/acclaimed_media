"""`MediaItemBase.save` keeps `name_normalized` true to the current name."""

from django.test import TestCase

from games.models import Game
from music.models import Album


class NameNormalizedFollowsTheNameTests(TestCase):
    def test_an_accented_name_is_folded(self):
        game = Game.objects.create(name="Pokémon X", rank=1)
        self.assertEqual(game.name_normalized, "Pokemon X")

    def test_a_plain_name_has_no_copy(self):
        game = Game.objects.create(name="Tetris", rank=1)
        self.assertIsNone(game.name_normalized)

    def test_a_rename_to_a_plain_name_drops_the_old_copy(self):
        """It stayed, and a search for the old name went on finding the game."""
        game = Game.objects.create(name="Pokémon X", rank=1)
        game.name = "Pokemon Y"
        game.save()
        game.refresh_from_db()
        self.assertIsNone(game.name_normalized)
        self.assertFalse(Game.objects.filter(name_normalized__icontains="X").exists())

    def test_a_rename_to_another_accented_name_follows_it(self):
        game = Game.objects.create(name="Pokémon X", rank=1)
        game.name = "Pokémon Y"
        game.save()
        self.assertEqual(game.name_normalized, "Pokemon Y")

    def test_a_copy_longer_than_the_column_is_cut_to_it(self):
        """unidecode lengthens some scripts: a `DataError` on Postgres."""
        name = "坂本龍一" * 50  # 200 characters, about 800 once folded
        album = Album.objects.create(name=name, rank=1)
        limit = Album._meta.get_field("name_normalized").max_length
        self.assertEqual(len(album.name_normalized), limit)
        album.refresh_from_db()
        self.assertEqual(len(album.name_normalized), limit)

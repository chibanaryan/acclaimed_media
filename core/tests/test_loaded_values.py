"""`core.loaded_values`: a row's previous value, known without a query."""

from django.test import TestCase

from core import loaded_values
from games.models import Game


class LoadedValuesTests(TestCase):
    def setUp(self):
        Game.objects.create(name="Alpha", rank=1, year_of_release=1998)
        self.game = Game.objects.get()

    def test_an_unchanged_value_has_no_previous(self):
        self.assertFalse(loaded_values.changed(self.game, "year_of_release"))
        self.assertIs(
            loaded_values.previous(self.game, "year_of_release"), loaded_values.UNKNOWN
        )

    def test_a_changed_value_names_what_the_row_held(self):
        self.game.year_of_release = 2001
        self.assertEqual(loaded_values.previous(self.game, "year_of_release"), 1998)

    def test_a_value_changed_from_none_is_a_change(self):
        Game.objects.update(year_of_release=None)
        game = Game.objects.get()
        game.year_of_release = 2001
        self.assertIsNone(loaded_values.previous(game, "year_of_release"))
        self.assertTrue(loaded_values.changed(game, "year_of_release"))

    def test_a_save_makes_the_new_value_the_remembered_one(self):
        self.game.year_of_release = 2001
        self.game.save()
        self.assertFalse(loaded_values.changed(self.game, "year_of_release"))

    def test_a_save_of_other_fields_leaves_the_old_value_remembered(self):
        self.game.year_of_release = 2001
        self.game.save(update_fields=["name"])
        self.assertEqual(loaded_values.previous(self.game, "year_of_release"), 1998)

    def test_an_instance_built_by_hand_knows_no_previous_value(self):
        game = Game(name="Beta", rank=2, year_of_release=1990)
        game.year_of_release = 1991
        self.assertFalse(loaded_values.changed(game, "year_of_release"))

    def test_a_created_instance_remembers_what_it_was_saved_with(self):
        game = Game.objects.create(name="Beta", rank=2, year_of_release=1990)
        game.year_of_release = 1991
        self.assertEqual(loaded_values.previous(game, "year_of_release"), 1990)

    def test_a_deferred_field_is_unknown(self):
        game = Game.objects.defer("year_of_release").get()
        self.assertFalse(loaded_values.changed(game, "year_of_release"))

    def test_a_save_that_leaves_the_field_out_has_not_changed_it(self):
        self.game.year_of_release = 2001
        self.assertFalse(
            loaded_values.changed(self.game, "year_of_release", update_fields=["name"])
        )
        self.assertTrue(
            loaded_values.changed(
                self.game, "year_of_release", update_fields=["year_of_release"]
            )
        )

    def test_loading_a_row_passes_djangos_own_arguments_on(self):
        """`from_db` without Django 6.1's `fetch_mode` keyword is a
        deprecation warning on every row loaded, and drops the queryset's
        fetch mode."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            game = Game.objects.get()
        self.assertEqual(game._loaded_values, {"year_of_release": 1998})

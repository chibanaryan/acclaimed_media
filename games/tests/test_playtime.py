"""
Open-ended games (no finish line) and the playtimes the site shows.

HLTB's averages for League of Legends or World of Warcraft are time invested,
not time to beat, so those games carry ``HLTBGameData.is_open_ended`` and are
left out of every playtime row, sort, filter, count and total.
"""

import csv
import io
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.text import slugify

from core.tests.utils import clear_all_caches
from games.management.commands import fetch_hltb_data, refresh_all_metadata
from core.models import User
from games.models import Game, HLTBGameData, WantToPlayGame
from games.services import playtime


def make_game(name, rank, main, completionist, igdb_id=None, **hltb):
    igdb_id = igdb_id or rank
    game = Game.objects.create(
        name=name, slug=slugify(name), rank=rank, igdb_id=igdb_id
    )
    data = HLTBGameData.objects.create(
        game=game,
        igdb_id=igdb_id,
        hltb_id=str(rank),
        main_story_hours=main,
        completionist_hours=completionist,
        is_primary=True,
        **hltb,
    )
    game.primary_hltb_game_data = data
    game.save()
    return game


class DeriveOpenEndedTests(TestCase):
    def test_hltb_game_types_without_a_finish_line(self):
        for game_type in ("multi", "endless", "sports"):
            self.assertTrue(HLTBGameData(game_type=game_type).derive_open_ended())

    def test_pooled_play_styles_alone_are_not_open_ended(self):
        """HLTB pools the modes of Sam & Max and Gunstar Heroes too."""
        data = HLTBGameData(game_type="game", comp_lvl_combine=True)
        self.assertFalse(data.derive_open_ended())

    def test_ordinary_and_unfetched_games_are_not(self):
        self.assertFalse(
            HLTBGameData(game_type="game", comp_lvl_combine=False).derive_open_ended()
        )
        self.assertFalse(HLTBGameData().derive_open_ended())

    def test_staff_override_wins_both_ways(self):
        self.assertTrue(HLTBGameData(open_ended_override=True).derive_open_ended())
        self.assertFalse(
            HLTBGameData(
                game_type="multi", open_ended_override=False
            ).derive_open_ended()
        )

    def test_empty_update_fields_still_writes_nothing(self):
        game = make_game("Portal", 1, 3, 10)
        data = game.primary_hltb_game_data
        with mock.patch("django.db.models.signals.post_save.send") as sent:
            data.save(update_fields=[])
        sent.assert_not_called()

    def test_save_stores_the_derivation(self):
        game = make_game("League of Legends", 1, 1161, 3262, game_type="multi")
        data = game.primary_hltb_game_data
        self.assertTrue(data.is_open_ended)

        data.open_ended_override = False
        data.save(update_fields=["open_ended_override"])
        data.refresh_from_db()
        self.assertFalse(data.is_open_ended)


class EntryProfileTests(TestCase):
    def test_reads_flags_and_counts_off_the_raw_row(self):
        entry = SimpleNamespace(
            json_content={
                "game_type": "multi",
                "comp_lvl_combine": 1,
                "comp_main_count": 54,
                "comp_plus_count": "25",
                "comp_100_count": 36,
            }
        )
        self.assertEqual(
            fetch_hltb_data.entry_profile(entry),
            {
                "game_type": "multi",
                "comp_lvl_combine": True,
                "main_story_count": 54,
                "main_extra_count": 25,
                "completionist_count": 36,
            },
        )

    def test_missing_or_malformed_values(self):
        entry = SimpleNamespace(
            json_content={"game_type": "x" * 40, "comp_main_count": -1}
        )
        self.assertEqual(
            fetch_hltb_data.entry_profile(entry),
            {
                "game_type": "x" * 20,
                "comp_lvl_combine": None,
                "main_story_count": None,
                "main_extra_count": None,
                "completionist_count": None,
            },
        )

    def test_entry_without_a_raw_row(self):
        self.assertEqual(fetch_hltb_data.entry_profile(mock.MagicMock()), {})
        self.assertEqual(fetch_hltb_data.entry_profile(object()), {})


class SaveProfileTests(TestCase):
    """Both commands' save paths record the profile, new row or orphan."""

    PROFILE = {"game_type": "multi", "comp_lvl_combine": True, "main_story_count": 9}

    def _save(self, command_module, game):
        return command_module.Command()._save_hltb_data(
            game.id, game.igdb_id, "77", "Name", "wikidata", 1.0, 10, 20, 30,
            profile=self.PROFILE,
        )  # fmt: skip

    def test_new_row(self):
        for rank, module in enumerate((fetch_hltb_data, refresh_all_metadata), 1):
            game = Game.objects.create(name=f"G{rank}", rank=rank, igdb_id=rank)
            data = self._save(module, game)
            self.assertEqual(data.game_type, "multi")
            self.assertEqual(data.main_story_count, 9)
            self.assertTrue(data.is_open_ended)

    def test_reconnected_orphan(self):
        for rank, module in enumerate((fetch_hltb_data, refresh_all_metadata), 1):
            orphan = HLTBGameData.objects.create(
                game=None, igdb_id=rank, hltb_id="77", is_primary=True
            )
            game = Game.objects.create(name=f"G{rank}", rank=rank, igdb_id=rank)
            data = self._save(module, game)
            self.assertEqual(data.pk, orphan.pk)
            self.assertTrue(data.comp_lvl_combine)
            self.assertTrue(data.is_open_ended)

    def test_a_rekeyed_game_keeps_its_staff_call(self):
        """IGDB re-keys a game: the new HLTB row inherits the call."""
        for rank, module in enumerate((fetch_hltb_data, refresh_all_metadata), 1):
            game = make_game(
                f"G{rank}", rank, 0.8, 2.5, game_type="game", open_ended_override=True
            )
            old = game.primary_hltb_game_data
            game.igdb_id = 1000 + rank
            game.save()
            command = module.Command()
            data = command._save_hltb_data(
                game.id, game.igdb_id, "77", "Name", "wikidata", 1.0, 1, 2, 3,
                profile={"game_type": "game"},
            )  # fmt: skip
            self.assertNotEqual(data.pk, old.pk)
            self.assertIs(data.open_ended_override, True)
            self.assertTrue(data.is_open_ended)


class PlaytimeServiceTests(TestCase):
    def test_hours_field(self):
        self.assertEqual(
            playtime.hours_field("completionist"),
            "primary_hltb_game_data__completionist_hours",
        )
        self.assertEqual(
            playtime.hours_field(None), "primary_hltb_game_data__main_story_hours"
        )
        self.assertEqual(playtime.hours_field("main", prefix=""), "main_story_hours")

    def test_shown_hours(self):
        data = HLTBGameData(main_story_hours=10, completionist_hours=20)
        self.assertEqual(playtime.shown_hours(data), 10)
        self.assertEqual(playtime.shown_hours(data, "completionist"), 20)
        data.is_open_ended = True
        self.assertIsNone(playtime.shown_hours(data))
        self.assertIsNone(playtime.shown_hours(None))


class OpenEndedGamesInRankingsTests(TestCase):
    def setUp(self):
        # The home page caches whole rendered responses for anonymous users
        clear_all_caches()
        self.short = make_game("Portal", 1, 3, 10)
        self.long = make_game("Persona 5", 2, 100, 150)
        self.moba = make_game("League of Legends", 3, 1161, 3262, game_type="multi")
        self.pacman = make_game("Pac-Man", 4, 0.8, 4.6, game_type="endless")
        # Open-ended only through the staff call: HLTB types it "game"
        self.cars = make_game(
            "Rocket League", 5, 4.7, 105, game_type="game", open_ended_override=True
        )

    def _ids(self, **params):
        response = self.client.get(reverse("home"), params)
        return [g.id for g in response.context["games"]]

    def test_playtime_sort_leaves_them_out(self):
        self.assertEqual(
            self._ids(sort="playtime", dir="desc"), [self.long.id, self.short.id]
        )
        self.assertEqual(
            self._ids(sort="playtime", hltb_mode="completionist"),
            [self.short.id, self.long.id],
        )

    def test_playtime_filters_leave_them_out(self):
        self.assertEqual(self._ids(hltb_preset="short"), [self.short.id])
        self.assertEqual(self._ids(hltb_preset="long"), [self.long.id])
        self.assertEqual(
            self._ids(pt_min=1, pt_max=5000), [self.short.id, self.long.id]
        )

    def test_unfiltered_list_still_lists_them(self):
        self.assertIn(self.moba.id, self._ids())

    def test_preset_counts_leave_them_out(self):
        response = self.client.get(reverse("home"))
        counts = response.context["hltb_counts_json"]
        self.assertEqual(counts["main"], {"short": 1, "medium": 0, "long": 1})
        self.assertEqual(counts["completionist"], {"short": 0, "medium": 1, "long": 1})

    def test_rows_render_no_playtime_for_them(self):
        content = self.client.get(reverse("home")).content.decode()
        self.assertIn('data-playtime-main="~100h"', content)
        self.assertNotIn("~1161h", content)
        self.assertNotIn("~3262h", content)
        self.assertNotIn("~5h", content)  # Rocket League, Pac-Man's 100%
        self.assertNotIn("~48m", content)  # Pac-Man
        self.assertNotIn("~105h", content)  # Rocket League's 100%

    def test_all_data_payload_sends_no_playtime_for_them(self):
        games = {
            g["id"]: g
            for g in self.client.get(reverse("games-api:game-all-data")).json()["data"][
                "games"
            ]
        }
        self.assertEqual(games[self.long.id]["pt"], 100.0)
        self.assertIsNone(games[self.moba.id]["pt"])
        self.assertIsNone(games[self.moba.id]["ptc"])
        self.assertIsNone(games[self.cars.id]["pt"])
        self.assertIsNone(games[self.pacman.id]["pt"])

    def test_payload_version_moves_when_staff_mark_a_game(self):
        from games.api.views import _compute_game_data_version

        before = _compute_game_data_version()
        data = self.long.primary_hltb_game_data
        data.open_ended_override = True
        data.save()
        self.assertNotEqual(_compute_game_data_version(), before)

    def test_payload_version_ignores_a_refresh_that_changes_nothing(self):
        """The weekly refresh saves every HLTB row, changed or not."""
        from games.api.views import _compute_game_data_version

        before = _compute_game_data_version()
        for data in HLTBGameData.objects.all():
            data.save()
        self.assertEqual(_compute_game_data_version(), before)

        data = self.long.primary_hltb_game_data
        data.main_story_hours = 101
        data.save()
        self.assertNotEqual(_compute_game_data_version(), before)

    def test_detail_page_labels_their_hours(self):
        response = self.client.get(reverse("game-detail", args=[self.moba.slug]))
        content = response.content.decode()
        self.assertIn("No finish line: hours players put in", content)
        self.assertIn("Main: ~1161h", content)

        content = self.client.get(
            reverse("game-detail", args=[self.long.slug])
        ).content.decode()
        self.assertNotIn("No finish line", content)

    def test_csv_export_blanks_their_hours(self):
        response = self.client.get(reverse("games-download"))
        rows = {
            row["Name"]: row
            for row in csv.DictReader(io.StringIO(response.content.decode()))
        }
        self.assertEqual(rows["Persona 5"]["HLTB Main (hours)"], "100.0")
        self.assertEqual(rows["League of Legends"]["HLTB Main (hours)"], "")
        self.assertEqual(rows["League of Legends"]["HLTB 100% (hours)"], "")

    def test_backlog_total_leaves_them_out(self):
        user = get_user_model().objects.create_user(
            username="reader", email="r@example.com", password="pw-123456"
        )
        for game in (self.long, self.moba):
            WantToPlayGame.objects.create(user=user, game=game, igdb_id=game.igdb_id)
        totals = playtime.backlog_hours(user, 2)
        self.assertEqual(totals["main"], 100)
        self.assertEqual(totals["completionist"], 150)
        self.assertEqual(
            playtime.backlog_hours(user, 0), {"main": None, "completionist": None}
        )


class OpenEndedCallsMigrationTests(TestCase):
    """0120 moves the editorial calls from code onto the records."""

    def setUp(self):
        from importlib import import_module

        from django.db import connection
        from django.db.migrations.loader import MigrationLoader

        self.migration = import_module(
            "games.migrations.0120_open_ended_calls_to_admin"
        )
        self.historical = (
            MigrationLoader(connection)
            .project_state(("games", "0120_open_ended_calls_to_admin"))
            .apps
        )
        self.galaga = make_game("Galaga", 1, 0.8, 2.5, igdb_id=2751)
        self.ffxiv = make_game("FFXIV", 2, 97.5, 3465, igdb_id=386, game_type="multi")
        self.zelda = make_game("Zelda", 3, 50, 194)
        # A listed game staff have already ruled on keeps their call
        self.tetris = make_game(
            "Tetris", 4, 3.1, 12.8, igdb_id=130749, open_ended_override=False
        )
        HLTBGameData.objects.update(open_ended_override=None, is_open_ended=False)
        HLTBGameData.objects.filter(game=self.tetris).update(open_ended_override=False)

    def _state(self):
        return [
            (
                HLTBGameData.objects.get(game=game).open_ended_override,
                HLTBGameData.objects.get(game=game).is_open_ended,
            )
            for game in (self.galaga, self.ffxiv, self.zelda, self.tetris)
        ]

    def test_seeds_the_calls_and_derives_every_row(self):
        self.migration.seed_overrides(self.historical, None)
        self.assertEqual(
            self._state(),
            [(True, True), (False, False), (None, False), (False, False)],
        )
        for data in HLTBGameData.objects.all():
            self.assertEqual(data.is_open_ended, data.derive_open_ended())

    def test_reverse_clears_only_its_own_calls(self):
        self.migration.seed_overrides(self.historical, None)
        self.migration.clear_overrides(self.historical, None)
        # FFXIV falls back to HLTB's "multi"; the staff call on Tetris stays
        self.assertEqual(
            self._state(),
            [(None, False), (None, True), (None, False), (False, False)],
        )

    def test_its_derivation_matches_the_model_for_every_input(self):
        HLTBGameData.objects.all().delete()
        # Orphans (game=None) via bulk_create, so no save() derives the flag
        HLTBGameData.objects.bulk_create(
            HLTBGameData(
                igdb_id=1, hltb_id="1", game_type=game_type, open_ended_override=call
            )
            for game_type in ("multi", "endless", "sports", "game", "compil", "")
            for call in (True, False, None)
        )
        for start in (True, False):
            HLTBGameData.objects.update(is_open_ended=start)
            self.migration.derive(self.historical.get_model("games", "HLTBGameData"))
            for data in HLTBGameData.objects.all():
                self.assertEqual(data.is_open_ended, data.derive_open_ended())

    def test_lists_do_not_overlap(self):
        self.assertFalse(
            set(self.migration.OPEN_ENDED_IGDB_IDS)
            & set(self.migration.FINISHABLE_IGDB_IDS)
        )


class OpenEndedAdminTests(TestCase):
    """Staff make the calls in the admin, one record or many."""

    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser("admin", "a@example.com", "pw")
        )
        self.moba = make_game("League of Legends", 1, 1161, 3262, game_type="multi")
        self.story = make_game("It Takes Two", 2, 12.8, 20, game_type="multi")
        self.sim = make_game("SimCity", 3, 15, 31, game_type="game")

    def _act(self, action, *games):
        return self.client.post(
            reverse("admin:games_hltbgamedata_changelist"),
            {
                "action": action,
                "_selected_action": [g.primary_hltb_game_data.pk for g in games],
            },
            follow=True,
        )

    def _open(self, game):
        return HLTBGameData.objects.get(game=game).is_open_ended

    def test_bulk_actions_set_the_call_and_the_flag(self):
        before = HLTBGameData.objects.get(game=self.sim).updated_at
        response = self._act("mark_open_ended", self.sim)
        self.assertContains(response, "Marked open-ended: 1 game. Visitors see it")
        self.assertTrue(self._open(self.sim))
        self.assertGreater(HLTBGameData.objects.get(game=self.sim).updated_at, before)

        self._act("mark_finishable", self.story)
        self.assertFalse(self._open(self.story))

        response = self._act("clear_open_ended_call", self.sim, self.story)
        self.assertContains(response, "Cleared the call on 2 games.")
        self.assertEqual([self._open(self.sim), self._open(self.story)], [False, True])

    def test_change_form_explains_the_rule(self):
        response = self.client.get(
            reverse(
                "admin:games_hltbgamedata_change",
                args=[self.sim.primary_hltb_game_data.pk],
            )
        )
        self.assertContains(response, "does it have an ending that HLTB")

    def test_game_admin_shows_the_flag(self):
        response = self.client.get(reverse("admin:games_game_changelist"))
        self.assertContains(response, "Open-ended")
        no_data = Game.objects.create(name="No HLTB", slug="no-hltb", rank=9)
        from games.admin import GameAdmin
        from django.contrib import admin as django_admin

        # Games HLTB has not matched can be found, to mark once it does
        response = self.client.get(
            reverse("admin:games_game_changelist"),
            {"primary_hltb_game_data__isempty": "1"},
        )
        self.assertEqual(list(response.context["cl"].result_list), [no_data])

        game_admin = GameAdmin(Game, django_admin.site)
        self.assertTrue(game_admin._open_ended(self.moba))
        self.assertFalse(game_admin._open_ended(self.sim))
        self.assertIsNone(game_admin._open_ended(no_data))

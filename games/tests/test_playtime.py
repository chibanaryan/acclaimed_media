"""
Open-ended games (no finish line) and the playtimes the site shows.

HLTB's averages for League of Legends or World of Warcraft are time invested,
not time to beat, so those games carry ``HLTBGameData.is_open_ended`` and are
left out of every playtime row, sort, filter, count and total.
"""

import csv
import io
from itertools import product
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.text import slugify

from core.tests.utils import clear_all_caches
from games.management.commands import fetch_hltb_data, refresh_all_metadata
from games import open_ended
from games.models import Game, HLTBGameData, WantToPlayGame
from games.services import playtime


def make_game(name, rank, main, completionist, **hltb):
    game = Game.objects.create(name=name, slug=slugify(name), rank=rank, igdb_id=rank)
    data = HLTBGameData.objects.create(
        game=game,
        igdb_id=rank,
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

    def test_pooled_play_styles_are_open_ended(self):
        """Rocket League is filed as a "game" but pools its modes."""
        data = HLTBGameData(game_type="game", comp_lvl_combine=True)
        self.assertTrue(data.derive_open_ended())

    def test_ordinary_and_unfetched_games_are_not(self):
        self.assertFalse(
            HLTBGameData(game_type="game", comp_lvl_combine=False).derive_open_ended()
        )
        self.assertFalse(HLTBGameData().derive_open_ended())

    def test_editorial_calls_beat_hltb_flags(self):
        """Galaga is filed as a "game"; FFXIV's main scenario ends."""
        self.assertTrue(
            HLTBGameData(igdb_id=2751, game_type="game").derive_open_ended()
        )
        self.assertFalse(
            HLTBGameData(igdb_id=386, game_type="multi").derive_open_ended()
        )

    def test_staff_override_beats_editorial_calls(self):
        self.assertFalse(
            HLTBGameData(igdb_id=2751, open_ended_override=False).derive_open_ended()
        )
        self.assertTrue(
            HLTBGameData(igdb_id=386, open_ended_override=True).derive_open_ended()
        )

    def test_editorial_lists_do_not_overlap(self):
        self.assertFalse(
            open_ended.OPEN_ENDED_IGDB_IDS & open_ended.FINISHABLE_IGDB_IDS
        )

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
        self.cars = make_game("Rocket League", 4, 4.7, 105, comp_lvl_combine=True)

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
        self.assertNotIn("~105h", content)

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


class DeriveOpenEndedMigrationTests(TestCase):
    """0117 and 0118 restate derive_open_ended as queries; all must agree."""

    def test_migrations_match_the_model_for_every_combination(self):
        from importlib import import_module

        from django.db import connection
        from django.db.migrations.loader import MigrationLoader

        listed_open = next(iter(open_ended.OPEN_ENDED_IGDB_IDS))
        listed_finishable = next(iter(open_ended.FINISHABLE_IGDB_IDS))
        # Orphans (game=None) via bulk_create, so no save() derives the flag
        HLTBGameData.objects.bulk_create(
            HLTBGameData(
                igdb_id=igdb_id,
                hltb_id="1",
                game_type=game_type,
                comp_lvl_combine=combine,
                open_ended_override=override,
            )
            for igdb_id, game_type, combine, override in product(
                (listed_open, listed_finishable, 1),
                ("multi", "game", ""),
                (True, False, None),
                (True, False, None),
            )
        )
        loader = MigrationLoader(connection)
        for name in ("0117_derive_open_ended", "0118_derive_open_ended_again"):
            migration = import_module(f"games.migrations.{name}")
            historical = loader.project_state(("games", name)).apps
            for start in (True, False):
                HLTBGameData.objects.update(is_open_ended=start)
                migration.derive_open_ended(historical, None)
                rows = list(HLTBGameData.objects.all())
                self.assertEqual(len(rows), 81)
                for row in rows:
                    self.assertEqual(
                        row.is_open_ended, row.derive_open_ended(), (name, row.__dict__)
                    )

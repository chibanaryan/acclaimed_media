"""Slugs and IGDB ids are unique in the database, as the code reads them.

`get_object_or_404(Game, igdb_id=...)`, the detail pages' slug lookups and
`update_or_create(igdb_id=...)` each took one row for granted; a second was
a `MultipleObjectsReturned`, a 500, from then on.
"""

import json
from io import StringIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase

from games import models, utils
from games.services.import_handler import ImportFileError
from games.tests.test_imports import InlineImportThreadMixin
from music.models import Album


class UniqueInTheDatabaseTests(TestCase):
    def assert_refused(self, create):
        with self.assertRaises(IntegrityError), transaction.atomic():
            create()

    def test_two_games_cannot_share_an_igdb_id(self):
        models.Game.objects.create(name="One", rank=1, igdb_id=7)
        self.assert_refused(
            lambda: models.Game.objects.create(name="Two", rank=2, igdb_id=7)
        )

    def test_two_games_cannot_share_a_slug(self):
        models.Game.objects.create(name="One", rank=1, slug="one")
        self.assert_refused(
            lambda: models.Game.objects.create(name="Two", rank=2, slug="one")
        )

    def test_games_without_an_igdb_id_or_a_slug_are_as_many_as_they_like(self):
        """Every game, between an import and its IGDB fetch."""
        for rank in (1, 2, 3):
            models.Game.objects.create(name=f"Game {rank}", rank=rank)
        models.Game.objects.create(name="Blank", rank=4, slug="")
        models.Game.objects.create(name="Blank too", rank=5, slug="")
        self.assertEqual(models.Game.objects.count(), 5)

    def test_two_developers_cannot_share_an_igdb_id_or_a_slug(self):
        models.Developer.objects.create(name="One", igdb_id=7, slug="one")
        self.assert_refused(
            lambda: models.Developer.objects.create(name="Two", igdb_id=7)
        )
        self.assert_refused(
            lambda: models.Developer.objects.create(name="Three", slug="one")
        )

    def test_subsidiaries_share_having_no_slug(self):
        """Stored as NULL by the IGDB fetch and as "" in 294 older rows."""
        root = models.Developer.objects.create(name="Root", igdb_id=1, slug="root")
        for number, slug in enumerate((None, None, "", ""), start=2):
            models.Developer.objects.create(
                name=f"Studio {number}", igdb_id=number, slug=slug, parent=root
            )
        self.assertEqual(models.Developer.objects.count(), 5)

    def test_two_albums_cannot_share_a_slug(self):
        Album.objects.create(name="One", rank=1, slug="one")
        self.assert_refused(
            lambda: Album.objects.create(name="Two", rank=2, slug="one")
        )

    def test_an_album_still_builds_itself_a_free_slug(self):
        first = Album.objects.create(name="Blue", rank=1)
        second = Album.objects.create(name="Blue", rank=2)
        self.assertNotEqual(first.slug, second.slug)


class SlugGivenByIgdbTests(TestCase):
    def fetched(self, game, slug):
        data = {"slug": slug, "cover": "", "url": "", "developers": [], "series": []}
        game.get_igdb_data(data=data, api_client=object())
        game.refresh_from_db()
        return game.slug

    def test_a_slug_another_game_holds_takes_the_igdb_id(self):
        """A refresh can hand a game the slug IGDB has moved from one not
        yet refreshed. It was two games on one slug; refused outright, the
        game would fail its refresh."""
        models.Game.objects.create(name="Holder", rank=1, igdb_id=1, slug="chrono")
        game = models.Game.objects.create(name="Newcomer", rank=2, igdb_id=2)
        self.assertEqual(self.fetched(game, "chrono"), "chrono-2")

    def test_it_takes_the_plain_slug_once_that_is_free(self):
        holder = models.Game.objects.create(
            name="Holder", rank=1, igdb_id=1, slug="chrono"
        )
        game = models.Game.objects.create(name="Newcomer", rank=2, igdb_id=2)
        self.fetched(game, "chrono")
        self.fetched(holder, "chrono-trigger")
        self.assertEqual(self.fetched(game, "chrono"), "chrono")

    def test_a_games_own_slug_is_not_taken_by_itself(self):
        game = models.Game.objects.create(name="Solo", rank=1, igdb_id=1, slug="solo")
        self.assertEqual(self.fetched(game, "solo"), "solo")

    def test_a_slug_made_from_the_name_is_kept_apart_too(self):
        models.Game.objects.create(name="Holder", rank=1, igdb_id=1, slug="tetris")
        game = models.Game.objects.create(name="Tetris", rank=2, igdb_id=2)
        self.assertEqual(self.fetched(game, None), "tetris-2")

    def test_a_name_that_makes_no_slug_is_left_without_one(self):
        """Nothing to keep apart: games without a slug are as many as they
        like, and "-2" alone would be a slug that names nothing."""
        models.Game.objects.create(name="!!!", rank=1, igdb_id=1, slug="")
        game = models.Game.objects.create(name="???", rank=2, igdb_id=2)
        self.assertEqual(self.fetched(game, None), "")

    def test_a_slug_that_has_not_moved_costs_no_query(self):
        """The weekly refresh is every game, and nearly none has moved."""
        game = models.Game.objects.create(name="Solo", rank=1, igdb_id=1, slug="solo")
        with self.assertNumQueries(0):
            self.assertEqual(game._free_slug("solo"), "solo")

    def test_a_game_with_no_igdb_id_is_told_apart_by_its_pk(self):
        models.Game.objects.create(name="Holder", rank=1, igdb_id=1, slug="tetris")
        game = models.Game.objects.create(name="Tetris", rank=2)
        self.assertEqual(game._free_slug("tetris"), f"tetris-{game.pk}")


class DeveloperSlugGivenByIgdbTests(TestCase):
    """IGDB can move a slug from one company to another between refreshes."""

    def developer(self, igdb_id, slug, name="Acme"):
        return models.Game._get_or_create_developer_with_parents(
            {"id": igdb_id, "name": name, "slug": slug}
        )

    def test_a_slug_another_developer_holds_takes_the_igdb_id(self):
        """Refused outright, the game being refreshed failed with it, on
        every refresh, and the admin's Save on that game was a 500."""
        stale = self.developer(10, "acme", "Acme (old)")
        newcomer = self.developer(30, "acme")
        self.assertEqual((stale.slug, newcomer.slug), ("acme", "acme-30"))

    def test_a_game_credited_to_it_still_refreshes(self):
        self.developer(10, "acme", "Acme (old)")
        game = models.Game.objects.create(name="Alpha", rank=1, igdb_id=7)
        game.get_igdb_data(
            data={
                "slug": "alpha",
                "cover": "",
                "url": "",
                "developers": [{"id": 30, "name": "Acme", "slug": "acme"}],
                "series": [],
            },
            api_client=object(),
        )
        game.refresh_from_db()
        self.assertEqual(game.slug, "alpha")
        self.assertEqual([d.slug for d in game.developers.all()], ["acme-30"])

    def test_it_takes_the_plain_slug_once_that_is_free(self):
        self.developer(10, "acme", "Acme (old)")
        self.developer(30, "acme")
        self.developer(10, "acme-holdings", "Acme Holdings")
        self.assertEqual(self.developer(30, "acme").slug, "acme")

    def test_a_developer_refreshed_again_keeps_its_own_slug(self):
        first = self.developer(10, "acme")
        again = self.developer(10, "acme")
        self.assertEqual((first.pk, again.slug), (again.pk, "acme"))

    def test_a_subsidiary_has_no_slug_to_collide(self):
        self.developer(10, "acme")
        child = models.Game._get_or_create_developer_with_parents(
            {
                "id": 31,
                "name": "Acme Studio",
                "slug": "acme",
                "parent": {"id": 10, "name": "Acme", "slug": "acme"},
            }
        )
        self.assertFalse(child.slug)
        self.assertEqual(child.parent.slug, "acme")

    def test_a_refusal_that_is_not_about_the_slug_is_not_hidden(self):
        """Only a slug has a second spelling to try."""
        with mock.patch.object(
            models.Developer.objects,
            "update_or_create",
            side_effect=IntegrityError("some other constraint"),
        ) as write:
            with self.assertRaises(IntegrityError):
                self.developer(10, None)
        self.assertEqual(write.call_count, 1)


class ImportRefusesASharedIgdbIdTests(TestCase):
    ROWS = (
        "1\tAlpha\t2000\tPC\t101\tQ1\r\n"
        "2\tBeta\t2001\tPC\t102\tQ2\r\n"
        "3\tAlpha Remastered\t2015\tPC\t101,301\tQ3\r\n"
    )

    def test_two_rows_starting_with_one_igdb_id_are_named(self):
        """The constraint's own error names neither row."""
        events = []
        with self.assertRaises(ImportFileError) as raised, transaction.atomic():
            utils.import_games(
                StringIO(self.ROWS), lambda event, data: events.append((event, data))
            )
        message = str(raised.exception)
        self.assertIn("rows 1 (Alpha) and 3 (Alpha Remastered)", message)
        self.assertIn("IGDB id 101", message)
        # The staff page is told in the same words, not "see the server logs"
        self.assertEqual(events[-1], ("error", {"message": message}))

    def test_a_refused_file_leaves_the_games_that_were_there(self):
        models.Game.objects.create(name="Before", rank=1, igdb_id=9, slug="before")
        with self.assertRaises(ImportFileError), transaction.atomic():
            utils.import_games(StringIO(self.ROWS))
        self.assertEqual(
            list(models.Game.objects.values_list("name", flat=True)), ["Before"]
        )

    def test_a_shared_secondary_id_is_not_refused(self):
        """Only the first id is a game's own: the others list every edition."""
        rows = "1\tAlpha\t2000\tPC\t101,900\tQ1\r\n2\tBeta\t2001\tPC\t102,900\tQ2\r\n"
        success, _ = utils.import_games(StringIO(rows))
        self.assertTrue(success)
        self.assertEqual(models.Game.objects.count(), 2)


class StreamedImportStopsBehindARefusedGamesFileTests(
    InlineImportThreadMixin, TestCase
):
    """The staff page's import goes on to the next file after one fails.

    Positions are attached to games by rank, so behind a games file that
    was not imported they went onto the previous release's games, and were
    committed there.
    """

    def setUp(self):
        super().setUp()
        models.Platform.objects.create(code="PC", name="PC")
        publication = models.Publication.objects.create(name="Edge")
        models.List.objects.create(publisher=publication, name="Top 100", year=2020)
        models.Game.objects.create(name="Before", rank=1, igdb_id=9, slug="before")

    def stream(self, games_rows):
        data = {
            "games_file": SimpleUploadedFile("Top1400.txt", games_rows.encode()),
            "memberships_file": SimpleUploadedFile("GamePositions.txt", b"0:1\r\n"),
        }
        with mock.patch(
            "games.services.import_handler.import_listmemberships",
            return_value=(True, "positions"),
        ) as positions:
            events = [
                json.loads(chunk.split("data: ", 1)[1].split("\n", 1)[0])
                for chunk in utils.import_batch_with_progress(data)
                if chunk.startswith("data: ")
            ]
        return events, positions

    def test_positions_are_not_imported_behind_a_refused_games_file(self):
        events, positions = self.stream(ImportRefusesASharedIgdbIdTests.ROWS)

        positions.assert_not_called()
        errors = {e.get("file"): e["message"] for e in events if e["event"] == "error"}
        self.assertIn("rows 1 (Alpha) and 3 (Alpha Remastered)", errors["Games"])
        self.assertIn("Not imported", errors["Game Positions"])
        self.assertEqual(
            list(models.Game.objects.values_list("name", flat=True)), ["Before"]
        )

    def test_positions_follow_a_games_file_that_imported(self):
        rows = "1\tAlpha\t2000\tPC\t101\tQ1\r\n"
        events, positions = self.stream(rows)
        positions.assert_called_once()
        self.assertFalse([e for e in events if e["event"] == "error"])

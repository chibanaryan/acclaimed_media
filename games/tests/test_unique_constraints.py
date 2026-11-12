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

from games import models
from games.services import import_handler
from games.services.import_handler import (
    BATCH_ROLLED_BACK,
    IMPORT_FAILED,
    ImportFileError,
)
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

    def slugs(self):
        return dict(models.Developer.objects.values_list("igdb_id", "slug"))

    def test_the_developer_igdb_gives_the_slug_to_takes_it(self):
        """The row that held it may never be refreshed again: developers
        are, only through a game that credits them. Refused outright, the
        game being refreshed failed with it on every refresh, and the
        admin's Save on that game was a 500."""
        self.developer(10, "acme", "Acme (old)")
        self.developer(30, "acme")
        self.assertEqual(self.slugs(), {10: "acme-10", 30: "acme"})

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
        self.assertEqual([d.slug for d in game.developers.all()], ["acme"])

    def test_the_row_that_gave_it_up_takes_its_own_new_slug_when_refreshed(self):
        self.developer(10, "acme", "Acme (old)")
        self.developer(30, "acme")
        self.developer(10, "acme-holdings", "Acme Holdings")
        self.assertEqual(self.slugs(), {10: "acme-holdings", 30: "acme"})

    def test_a_developer_refreshed_again_keeps_its_own_slug(self):
        first = self.developer(10, "acme")
        again = self.developer(10, "acme")
        self.assertEqual((first.pk, again.slug), (again.pk, "acme"))
        self.assertEqual(self.slugs(), {10: "acme"})

    def test_a_holder_with_no_igdb_id_is_told_apart_by_its_pk(self):
        holder = models.Developer.objects.create(name="By hand", slug="acme")
        self.developer(30, "acme")
        holder.refresh_from_db()
        self.assertEqual(holder.slug, f"acme-{holder.pk}")

    def test_the_slug_it_is_moved_to_is_a_free_one(self):
        """Its IGDB id tells it apart from every slug but one that ends in
        it, and a refused write there failed the game's refresh."""
        holder = self.developer(10, "acme", "Acme (old)")
        models.Developer.objects.create(name="Acme 10", igdb_id=11, slug="acme-10")
        self.developer(30, "acme")
        self.assertEqual(
            self.slugs(), {10: f"acme-10-{holder.pk}", 11: "acme-10", 30: "acme"}
        )

    def test_the_row_that_gave_it_up_no_longer_links_to_the_others_igdb_page(self):
        holder = self.developer(10, "acme", "Acme (old)")
        self.assertEqual(holder.igdb_url, "https://www.igdb.com/companies/acme")
        newcomer = self.developer(30, "acme")
        holder.refresh_from_db()
        self.assertIsNone(holder.igdb_url)
        self.assertEqual(newcomer.igdb_url, "https://www.igdb.com/companies/acme")

    def test_a_subsidiary_has_no_slug_to_take(self):
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
        self.assertEqual(self.slugs()[10], "acme")


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
            import_handler.import_games(
                StringIO(self.ROWS), lambda event, data: events.append((event, data))
            )
        message = str(raised.exception)
        self.assertIn("rows 1 (Alpha) and 3 (Alpha Remastered)", message)
        self.assertIn("IGDB id 101", message)
        # Said by the caller, with the file's name: not here as well, and
        # not as "see the server logs"
        self.assertNotIn("error", [event for event, _ in events])

    def test_a_refused_file_leaves_the_games_that_were_there(self):
        models.Game.objects.create(name="Before", rank=1, igdb_id=9, slug="before")
        with self.assertRaises(ImportFileError), transaction.atomic():
            import_handler.import_games(StringIO(self.ROWS))
        self.assertEqual(
            list(models.Game.objects.values_list("name", flat=True)), ["Before"]
        )

    def test_a_shared_secondary_id_is_not_refused(self):
        """Only the first id is a game's own: the others list every edition."""
        rows = "1\tAlpha\t2000\tPC\t101,900\tQ1\r\n2\tBeta\t2001\tPC\t102,900\tQ2\r\n"
        success, _ = import_handler.import_games(StringIO(rows))
        self.assertTrue(success)
        self.assertEqual(models.Game.objects.count(), 2)


class StreamedImportIsAllOrNothingTests(InlineImportThreadMixin, TestCase):
    """The staff page's import went on to the next file after one failed,
    and committed the rest.

    Behind a refused games file the lists were replaced, which deletes
    every list appearance, and positions were attached by rank to the
    previous release's games. `import_batch` has always rolled the whole
    batch back.
    """

    LISTS = "Edge\t2021\tAll Time\tThe New Top 100\thttps://example.org/new\r\n"

    def setUp(self):
        super().setUp()
        models.Platform.objects.create(code="PC", name="PC")
        publication = models.Publication.objects.create(name="Edge")
        self.old_list = models.List.objects.create(
            publisher=publication, name="Top 100", year=2020
        )
        self.before = models.Game.objects.create(
            name="Before", rank=1, igdb_id=9, slug="before"
        )
        models.ListMembership.objects.create(
            list=self.old_list, game=self.before, rank=1
        )

    def stream(self, games_rows, lists_rows=None, positions=(True, "positions")):
        data = {
            "games_file": SimpleUploadedFile("Top1400.txt", games_rows.encode()),
            "memberships_file": SimpleUploadedFile("GamePositions.txt", b"0:1\r\n"),
        }
        if lists_rows is not None:
            data["lists_file"] = SimpleUploadedFile(
                "SourceLists.txt", lists_rows.encode()
            )
        with mock.patch(
            "games.services.import_handler.import_listmemberships",
            side_effect=[positions] if isinstance(positions, tuple) else positions,
        ) as positions_import:
            events = [
                json.loads(chunk.split("data: ", 1)[1].split("\n", 1)[0])
                for chunk in import_handler.import_batch_with_progress(data)
                if chunk.startswith("data: ")
            ]
        return events, positions_import

    def errors(self, events):
        return [(e.get("file"), e["message"]) for e in events if e["event"] == "error"]

    def assert_nothing_changed(self):
        self.assertEqual(
            list(models.Game.objects.values_list("name", flat=True)), ["Before"]
        )
        self.assertEqual(
            list(models.List.objects.values_list("name", flat=True)), ["Top 100"]
        )
        self.assertEqual(models.ListMembership.objects.count(), 1)

    def test_a_refused_games_file_rolls_back_the_lists_imported_before_it(self):
        """They were committed: every list replaced, every appearance gone."""
        events, positions = self.stream(
            ImportRefusesASharedIgdbIdTests.ROWS, lists_rows=self.LISTS
        )

        positions.assert_not_called()
        (file, message), rolled_back = self.errors(events)
        self.assertEqual(file, "Games")
        self.assertIn("rows 1 (Alpha) and 3 (Alpha Remastered)", message)
        self.assertEqual(rolled_back, (None, BATCH_ROLLED_BACK))
        self.assert_nothing_changed()

    def test_a_failure_is_said_once_with_the_files_name(self):
        """A real bad row, no handler mocked: the handler sent its own
        "Import failed" before the batch named the file, three rows in all."""
        events, _ = self.stream("1\tAlpha\t2000\tPC\t101\tQ1\r\n2\tShort row\r\n")

        self.assertEqual(
            self.errors(events), [("Games", IMPORT_FAILED), (None, BATCH_ROLLED_BACK)]
        )
        self.assert_nothing_changed()

    def test_a_lists_file_that_fails_keeps_the_games_file_out_too(self):
        """Committed alone, the new games had no list appearances at all."""
        with mock.patch(
            "games.services.import_handler.import_lists",
            side_effect=RuntimeError("bad lists file"),
        ):
            events, positions = self.stream(
                "1\tAlpha\t2000\tPC\t101\tQ1\r\n", lists_rows=self.LISTS
            )

        positions.assert_not_called()
        self.assertEqual(
            self.errors(events),
            [("Source Lists", IMPORT_FAILED), (None, BATCH_ROLLED_BACK)],
        )
        self.assert_nothing_changed()

    def test_a_failure_in_the_last_file_rolls_back_the_games_before_it(self):
        events, _ = self.stream(
            "1\tAlpha\t2000\tPC\t101\tQ1\r\n",
            positions=RuntimeError("bad positions"),
        )
        self.assertEqual(
            self.errors(events),
            [("Game Positions", IMPORT_FAILED), (None, BATCH_ROLLED_BACK)],
        )
        self.assert_nothing_changed()

    def test_a_rolled_back_batch_starts_no_metadata_fetch(self):
        with mock.patch(
            "games.services.import_handler.post_import.schedule"
        ) as schedule:
            self.stream(
                "1\tAlpha\t2000\tPC\t101\tQ1\r\n",
                positions=RuntimeError("bad positions"),
            )
        schedule.assert_not_called()

    def test_a_batch_whose_files_all_import_is_committed(self):
        with mock.patch(
            "games.services.import_handler.post_import.schedule", return_value=None
        ):
            events, positions = self.stream("1\tAlpha\t2000\tPC\t101\tQ1\r\n")
        positions.assert_called_once()
        self.assertEqual(self.errors(events), [])
        self.assertEqual(
            list(models.Game.objects.values_list("name", flat=True)), ["Alpha"]
        )

    def test_a_committed_games_file_moves_the_updated_date(self):
        """The heading's "Updated:" kept the previous release's date after
        an import from the staff page: only the other import path set it."""
        before = models.SiteMetadata.get_instance().last_full_update
        with mock.patch(
            "games.services.import_handler.post_import.schedule", return_value=None
        ):
            self.stream("1\tAlpha\t2000\tPC\t101\tQ1\r\n")
        after = models.SiteMetadata.get_instance().last_full_update
        self.assertIsNotNone(after)
        self.assertNotEqual(after, before)

    def test_a_rolled_back_batch_leaves_the_updated_date(self):
        before = models.SiteMetadata.get_instance().last_full_update
        self.stream(
            "1\tAlpha\t2000\tPC\t101\tQ1\r\n",
            positions=RuntimeError("bad positions"),
        )
        self.assertEqual(models.SiteMetadata.get_instance().last_full_update, before)

"""Tests for migration 0127, which drops the two columns 0126 stopped naming.

The migration has run against the test database by the time these run, so
they read the end state, then drive its two functions to show that each
looks before it acts and that the rows outlive both. What only Postgres
does, the wait for a lock, is read where the suite runs on Postgres (CI's
`django-tests` job).
"""

import importlib
from unittest import skipUnless

from django.db import connection
from django.test import TestCase

from games.models import IGDBGameData, WikipediaGameData


class _SchemaEditor:
    """All the migration's functions read of a schema editor."""

    connection = connection


def _columns(table):
    with connection.cursor() as cursor:
        return {
            field.name: field
            for field in connection.introspection.get_table_description(cursor, table)
        }


class DropVideoAndWikiquoteColumnsMigrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = importlib.import_module(
            "games.migrations.0127_drop_video_and_wikiquote_columns"
        )

    def _drop(self):
        self.migration.drop_columns(None, _SchemaEditor())

    def _restore(self):
        self.migration.restore_columns(None, _SchemaEditor())

    def assertColumns(self, present):
        for table, column, _ in self.migration.COLUMNS:
            with self.subTest(table=table, column=column):
                self.assertEqual(column in _columns(table), present)

    def test_the_columns_are_the_two_0126_forgot(self):
        self.assertEqual(
            [(table, column) for table, column, _ in self.migration.COLUMNS],
            [
                (IGDBGameData._meta.db_table, "youtube_video_id"),
                (WikipediaGameData._meta.db_table, "wikiquote_page_title"),
            ],
        )

    def test_the_columns_are_gone(self):
        self.assertColumns(present=False)

    def test_dropping_them_again_does_nothing(self):
        self._drop()
        self.assertColumns(present=False)

    def test_undoing_it_puts_them_back_nullable(self):
        self._restore()
        self.assertColumns(present=True)
        for table, column, _ in self.migration.COLUMNS:
            with self.subTest(table=table, column=column):
                self.assertTrue(_columns(table)[column].null_ok)

    def test_restoring_them_again_does_nothing(self):
        self._restore()
        self._restore()
        self.assertColumns(present=True)

    def test_the_rows_outlive_both_directions(self):
        igdb = IGDBGameData.objects.create(
            igdb_id=127001, url="https://www.igdb.com/games/kept", summary="Kept"
        )
        wikipedia = WikipediaGameData.objects.create(
            wikidata_id="Q127001", page_title="Kept"
        )
        # Postgres will not alter a table whose deferred foreign-key checks
        # are still waiting, as these rows' are until the test's transaction
        # ends. A migration writes no rows of its own.
        connection.check_constraints()
        self._restore()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT youtube_video_id FROM games_igdbgamedata WHERE id = %s",
                [igdb.pk],
            )
            self.assertEqual(cursor.fetchone(), (None,))
        # A row written while the columns are there, as the release before
        # 0126 would on a database rolled back to it
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE games_igdbgamedata SET youtube_video_id = %s WHERE id = %s",
                ["dQw4w9WgXcQ", igdb.pk],
            )
        connection.check_constraints()
        self._drop()
        self.assertColumns(present=False)
        igdb.refresh_from_db()
        wikipedia.refresh_from_db()
        self.assertEqual((igdb.summary, wikipedia.page_title), ("Kept", "Kept"))

    def test_one_table_stripped_already_is_finished(self):
        """A run that gave up waiting for the second table's lock has
        dropped the first's column, and the next run meets that."""
        self._restore()
        table, column, _ = self.migration.COLUMNS[0]
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        self._drop()
        self.assertColumns(present=False)

    @skipUnless(connection.vendor == "postgresql", "SQLite has no lock to wait for")
    def test_it_waits_ten_seconds_for_a_lock_and_no_longer(self):
        # `SET LOCAL` lasts the transaction, which here is the test's own
        self._drop()
        with connection.cursor() as cursor:
            cursor.execute("SHOW lock_timeout")
            self.assertEqual(cursor.fetchone(), (self.migration.LOCK_TIMEOUT,))

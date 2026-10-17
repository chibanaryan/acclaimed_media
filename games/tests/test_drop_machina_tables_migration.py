"""Tests for migration 0115 dropping the django-machina forum tables.

The migration has already run against the test database by the time these
tests execute, so they assert the end state and then drive the helper again
to prove it is idempotent, orders its work safely, and leaves the rest of
the schema alone.
"""

import importlib

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase

from games.models import Game, Publication


class _FakeApps:
    """Minimal apps registry shim for calling the RunPython helper."""

    MODELS = {
        ("contenttypes", "ContentType"): ContentType,
        ("auth", "Group"): Group,
    }

    def get_model(self, app_label, model_name):
        return self.MODELS[(app_label, model_name)]


class _FakeSchemaEditor:
    def __init__(self):
        self.connection = connection


class DropMachinaTablesMigrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = importlib.import_module(
            "games.migrations.0115_drop_machina_tables"
        )

    def _run(self):
        self.migration.drop_machina_tables(_FakeApps(), _FakeSchemaEditor())

    def test_no_forum_tables_remain(self):
        tables = set(connection.introspection.table_names())
        for table in self.migration.MACHINA_TABLES:
            with self.subTest(table=table):
                self.assertNotIn(table, tables)

    def test_no_machina_content_types_remain(self):
        self.assertFalse(
            ContentType.objects.filter(
                app_label__in=self.migration.MACHINA_APP_LABELS
            ).exists()
        )

    def test_the_moderators_group_is_gone(self):
        self.assertFalse(
            Group.objects.filter(name=self.migration.MODERATORS_GROUP_NAME).exists()
        )

    def test_no_machina_migration_records_remain(self):
        with connection.cursor() as cursor:
            placeholders = ", ".join(["%s"] * len(self.migration.MACHINA_APP_LABELS))
            cursor.execute(
                f"SELECT COUNT(*) FROM django_migrations WHERE app IN ({placeholders})",
                self.migration.MACHINA_APP_LABELS,
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_running_it_again_is_a_no_op(self):
        # Tables are already absent, so the DROP loop must skip them rather
        # than raise.
        self._run()
        self._run()
        tables = set(connection.introspection.table_names())
        self.assertNotIn("forum_forum", tables)

    def test_it_removes_a_recreated_moderators_group(self):
        Group.objects.create(name=self.migration.MODERATORS_GROUP_NAME)
        self._run()
        self.assertFalse(
            Group.objects.filter(name=self.migration.MODERATORS_GROUP_NAME).exists()
        )

    def test_it_removes_machina_content_types_and_their_permissions(self):
        content_type = ContentType.objects.create(
            app_label="forum_conversation", model="topic"
        )
        Permission.objects.create(
            content_type=content_type, codename="can_see_forum", name="Can see forum"
        )
        self._run()
        self.assertFalse(ContentType.objects.filter(pk=content_type.pk).exists())
        self.assertFalse(Permission.objects.filter(codename="can_see_forum").exists())

    def test_it_leaves_other_groups_and_content_types_alone(self):
        keeper = Group.objects.create(name="Editors")
        games_type = ContentType.objects.get_for_model(Game)
        self._run()
        self.assertTrue(Group.objects.filter(pk=keeper.pk).exists())
        self.assertTrue(ContentType.objects.filter(pk=games_type.pk).exists())

    def test_it_leaves_the_games_schema_and_data_alone(self):
        Publication.objects.create(name="Edge", reputation_score=90)
        Game.objects.create(name="Tetris", rank=1, year_of_release=1985)
        self._run()
        self.assertEqual(Game.objects.count(), 1)
        self.assertEqual(Publication.objects.get(name="Edge").reputation_score, 90)
        tables = set(connection.introspection.table_names())
        self.assertIn("games_game", tables)
        self.assertIn("games_publication", tables)

    def test_the_table_list_drops_children_before_their_parents(self):
        # forum_forum is the root of the machina schema, so it must be last.
        tables = self.migration.MACHINA_TABLES
        self.assertEqual(tables[-1], "forum_forum")
        self.assertLess(
            tables.index("forum_conversation_post"),
            tables.index("forum_conversation_topic"),
        )
        self.assertLess(
            tables.index("forum_polls_topicpollvote"),
            tables.index("forum_polls_topicpoll"),
        )

    def test_the_migration_is_not_reversible_into_empty_tables(self):
        from django.db import migrations as django_migrations

        operation = self.migration.Migration.operations[0]
        self.assertIs(operation.reverse_code, django_migrations.RunPython.noop)

"""Drop the django-machina forum tables.

The forum was removed in 2026-10-17; its apps are no longer installed, so
Django no longer manages these tables and they would sit in the database
indefinitely. This is destructive and irreversible: it deletes every forum,
topic, post, poll and read-tracking row, along with the per-forum
permissions, the "Forum Moderators" group and the machina content types and
migration records.

Ordering matters. The tables go first so that deleting the content types
cannot trip a foreign key still pointed at them, and the machina rows in
django_migrations go last so a future reinstall of machina would start from
a clean slate rather than believing its migrations were already applied.
"""

from django.db import migrations

# Child tables first so the drops are safe even where foreign keys are
# enforced. Names are the ones machina's own migrations created.
MACHINA_TABLES = [
    "forum_attachments_attachment",
    "forum_polls_topicpollvote",
    "forum_polls_topicpolloption",
    "forum_polls_topicpoll",
    "forum_tracking_topicreadtrack",
    "forum_tracking_forumreadtrack",
    "forum_conversation_topic_subscribers",
    "forum_conversation_post",
    "forum_conversation_topic",
    "forum_permission_userforumpermission",
    "forum_permission_groupforumpermission",
    "forum_permission_forumpermission",
    "forum_member_forumprofile",
    "forum_forum",
]

MACHINA_APP_LABELS = [
    "forum",
    "forum_attachments",
    "forum_conversation",
    "forum_feeds",
    "forum_member",
    "forum_moderation",
    "forum_permission",
    "forum_polls",
    "forum_search",
    "forum_tracking",
    "machina",
]

MODERATORS_GROUP_NAME = "Forum Moderators"


def drop_machina_tables(apps, schema_editor):
    connection = schema_editor.connection
    existing = set(connection.introspection.table_names())
    cascade = " CASCADE" if connection.vendor == "postgresql" else ""

    with connection.cursor() as cursor:
        for table in MACHINA_TABLES:
            if table in existing:
                cursor.execute(f'DROP TABLE IF EXISTS "{table}"{cascade}')

    # Content types cascade to their auth_permission rows.
    ContentType = apps.get_model("contenttypes", "ContentType")
    ContentType.objects.filter(app_label__in=MACHINA_APP_LABELS).delete()

    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=MODERATORS_GROUP_NAME).delete()

    # Clear machina's migration history last.
    with connection.cursor() as cursor:
        placeholders = ", ".join(["%s"] * len(MACHINA_APP_LABELS))
        cursor.execute(
            f"DELETE FROM django_migrations WHERE app IN ({placeholders})",
            MACHINA_APP_LABELS,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("games", "0114_drop_forum_references"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(
            drop_machina_tables,
            # Irreversible: the forum data is gone, and recreating empty
            # tables would misrepresent that as a working forum.
            migrations.RunPython.noop,
        ),
    ]

from django.db import migrations, transaction

# (table, column, the type it had): IGDB's first video (`0070`) and the
# Wikiquote title (`0075`), both nullable.
COLUMNS = (
    ("games_igdbgamedata", "youtube_video_id", "varchar(50)"),
    ("games_wikipediagamedata", "wikiquote_page_title", "varchar(300)"),
)
LOCK_TIMEOUT = "10s"


def _has_column(connection, table, column):
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table)
    return any(field.name == column for field in description)


def _alter_each_table(connection, wanted, statement):
    """Run ``statement`` for each column that is not yet as ``wanted`` (there
    or not), a table to a transaction.

    Both tables are read by every game page, and Postgres queues every other
    query on a table behind an `ALTER TABLE` that is itself waiting for one
    to finish. So the wait is ten seconds at most, after which the release
    fails and is run again, where the site would have stalled; and a table's
    lock is let go before the next is asked for, where one transaction would
    hold the first through the wait for the second.
    """
    quote = connection.ops.quote_name
    for table, column, column_type in COLUMNS:
        with transaction.atomic(using=connection.alias):
            with connection.cursor() as cursor:
                if connection.vendor == "postgresql":
                    cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
                if _has_column(connection, table, column) != wanted:
                    cursor.execute(
                        statement.format(
                            table=quote(table), column=quote(column), type=column_type
                        )
                    )


def drop_columns(apps, schema_editor):
    _alter_each_table(
        schema_editor.connection,
        wanted=False,
        statement="ALTER TABLE {table} DROP COLUMN {column}",
    )


def restore_columns(apps, schema_editor):
    _alter_each_table(
        schema_editor.connection,
        wanted=True,
        statement="ALTER TABLE {table} ADD COLUMN {column} {type} NULL",
    )


class Migration(migrations.Migration):
    """Drop the two columns `0126` stopped naming.

    `0126` took them out of Django's state and left the tables alone, so
    that the release before it, whose queries name every column, kept
    working through the deploy and after a rollback. This one ships a
    release later, when the dynos serving through the release phase no
    longer read them. After it, a rollback past the release that carried
    `0126` fails on every game page.

    Not atomic: each table is altered in a transaction of its own
    (`_alter_each_table`). So a run that gave up waiting for the second
    table has already dropped the first, and each column is looked for
    before it is touched: the next run finishes the job. Undoing it puts
    the columns back, empty.
    """

    atomic = False

    dependencies = [
        ("games", "0126_drop_video_and_wikiquote"),
    ]

    operations = [
        migrations.RunPython(drop_columns, restore_columns),
    ]

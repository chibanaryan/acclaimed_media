"""The metadata fetch a games import starts (see ``core.services.post_import``).

A games import recreates every ``Game``. It reattaches the stored IGDB,
Wikipedia and HLTB rows, but the slug, developers and series live on
``Game`` and only ``Game.get_igdb_data`` writes them, so until IGDB is
fetched again every game links to ``/games/None/``. Hence a *forced* IGDB
pass: the missing-only one skips every reattached game. Wikipedia and HLTB
are missing-only, which after an import means the games it added, and the
few neither has ever matched.
"""

import asyncio
import logging

from asgiref.sync import sync_to_async
from django.core.management import call_command
from django.db import connections
from django.utils import timezone

from core.services import post_import
from games.models import Game

logger = logging.getLogger(__name__)

IGDB = "get_igdb"
MOVE_VERSION = "Moving the games data version"

# After the forced IGDB pass, which restores the slugs the pages link by.
MISSING_ONLY = (
    ("fetch_wikipedia_metadata", {"save": True}),
    ("fetch_hltb_data", {"save": True}),
)

# More games than this left without a slug means the IGDB pass failed, part
# way or wholly. Fewer is IGDB no longer returning a game or two, which
# would otherwise alert on every import.
SLUGLESS_TOLERANCE = 10


def refresh_after_import(stdout):
    """Run each step; the ones that failed. A failure does not stop the next."""
    failed = []
    try:
        if not _run_igdb(stdout):
            failed.append(IGDB)
        for name, options in MISSING_ONLY:
            if not _run_step(name, options, stdout):
                failed.append(name)
        # Wikipedia's genres for the added games move nothing the data
        # version reads, so cached pages would go on showing them without.
        if not _move_data_version():
            failed.append(MOVE_VERSION)
    finally:
        _close_async_connections()
    return failed


def _run_step(name, options, stdout):
    """Run one command; whether it finished."""
    try:
        call_command(name, stdout=stdout, **options)
    except Exception:
        logger.exception("%s after a games import failed", name)
        return False
    return True


def _run_igdb(stdout):
    """The forced IGDB pass; whether it gave the games their slugs back.

    ``get_igdb`` reports a service it cannot start (expired credentials, say)
    on its output and returns, and one whose requests start failing part way
    catches each batch's error, so the slugs are the test of whether it ran.
    """
    ran = _run_step(IGDB, {"force": True}, stdout)
    # Even after a pass that raised part way: the slugs it did restore are
    # hidden behind cached pages until the version moves. A move that fails
    # here is tried again, and named, at the end.
    _move_data_version()
    try:
        after = _slugless()
    except Exception:
        logger.exception("Could not check what %s restored", IGDB)
        return False
    if after:
        logger.warning("%s left %d games without a slug", IGDB, after)
    return ran and after <= SLUGLESS_TOLERANCE


def _slugless():
    return Game.objects.filter(slug__isnull=True, igdb_id__isnull=False).count()


def _move_data_version():
    """Move the games data version, which reads ``Max(modified)``.

    ``get_igdb`` saves slugs with update_fields, which leaves ``modified``
    alone, so a page or /api/games/all/ cached during the fetch would go on
    serving /games/None/ links. One row moves the maximum as well as all
    1400 would. Whether it moved; a failure is logged, not raised, so the
    steps that failed are still named.
    """
    try:
        pk = Game.objects.order_by("pk").values_list("pk", flat=True).first()
        if pk is not None:
            Game.objects.filter(pk=pk).update(modified=timezone.now())
    except Exception:
        logger.exception("Could not move the games data version")
        return False
    return True


def _close_async_connections():
    """Close the connection fetch_hltb_data's saves opened, and leave open.

    It saves through ``sync_to_async``, which outside an async server runs
    on asgiref's one executor thread for the life of the process, so the
    connection it opens there outlives the fetch, a Postgres slot per web
    worker that ran one. Closing it takes a call on that same thread.
    """
    try:
        asyncio.run(sync_to_async(connections.close_all)())
    except Exception:
        logger.exception("Could not close the HLTB fetch's connection")


def schedule():
    """Start the fetch on a background thread; the line to show staff."""
    return post_import.schedule_after_commit("games", refresh_after_import)


def run_in_foreground(command):
    """Run the fetch on an import command's output."""
    post_import.run_in_foreground("games", refresh_after_import, command)

"""The metadata fetch a games import starts (see ``core.services.post_import``).

A games import recreates every ``Game``, reattaching the stored IGDB,
Wikipedia and HLTB rows and carrying across the slug, developers and series
IGDB wrote on the old one. So every pass is missing-only, which after an
import means the games it added, and the few a source has never matched.
For IGDB that includes a game left without a slug (``needing_igdb``), which
the slugs it links by cannot do without.
"""

import asyncio
import hashlib
import json
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

# After the IGDB pass, which gives the added games the slugs pages link by.
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
        if not move_data_version():
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
    """The IGDB pass; whether it gave every game a slug.

    ``get_igdb`` reports a service it cannot start (expired credentials, say)
    on its output and returns, and one whose requests start failing part way
    catches each batch's error, so the slugs are the test of whether it ran.
    """
    ran = _run_step(IGDB, {}, stdout)
    # Even after a pass that raised part way: the slugs it did restore are
    # hidden behind cached pages until the version moves. A move that fails
    # here is tried again, and named, at the end.
    move_data_version()
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


def payload_fingerprint():
    """A hash of what `/api/games/all/` serves, or None if it cannot be read.

    For a job that writes through saves the data version does not see (the
    weekly refresh: genres, slugs, artwork) to say whether it changed what
    a page or a reader's stored payload shows. The version is left alone
    when it did not: moved every Sunday regardless, it would have every
    returning reader download the payload again for nothing, which is why
    the version fingerprints the playtimes rather than reading
    ``updated_at`` (``data_version.py``).
    """
    # Here, not at the top: the API layer imports the services
    from games.api.views import GameAllDataView

    try:
        payload = GameAllDataView()._payload("")
        text = json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        logger.exception("Could not fingerprint the games payload")
        return None
    return hashlib.md5(text.encode()).hexdigest()


def move_data_version():
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


def hold():
    """The lock for other metadata work (``post_import.hold``), or ``None``."""
    return post_import.hold("games", refresh_after_import)


def resume():
    """Restart a fetch its worker took down; the line to show staff, or ``None``."""
    return post_import.resume_if_cut_short("games", refresh_after_import)


def run_weekly(command, work):
    """The weekly job's ``work``, never beside a fetch."""
    post_import.run_weekly("games", refresh_after_import, command, work)

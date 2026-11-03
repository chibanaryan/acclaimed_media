"""The metadata fetch an import starts once it has committed.

An import leaves metadata missing: music's added albums have no covers or
genres, and a games import recreates every game without the slug,
developers and series only IGDB supplies. Each section's ``post_import``
module names the fetch, a ``job(stdout)`` returning the names of the steps
that failed; this one runs it after the import's transaction commits, on a
background thread for the staff pages and in the foreground for the import
commands.

One fetch per section runs at a time, across every worker and dyno: the lock
is a ``cache.add`` on the shared ``default`` alias, holding a token only its
fetch renews. An import while one runs starts none but asks the running one
to go round again when it finishes, since that one works from the rows it
read as it began: a games import recreates every game, so the forced IGDB
pass of the last one would leave the new ones without slugs.

The lock lives ``LOCK_SECONDS`` and a heartbeat renews it, so a fetch killed
with its worker (a deploy, ``--max-requests``; see
``start_background_thread``) frees it within two minutes, where a lock for
the longest fetch told every import for hours that a dead one would cover
it, and a round outliving its lock let a second fetch start. The heartbeat
only touches the lock: renewing it with a ``set`` could put it back just
after the fetch released it. So a lock the cache culls stays culled, and a
second fetch can start beside the first.
"""

import logging
import threading
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction

from core.services.background import start_background_thread

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 30
LOCK_SECONDS = 120
# A request to go again needs only to outlive the round it waits on, which
# the heartbeat keeps alive however long it runs.
AGAIN_SECONDS = 2 * 60 * 60

STARTED = "Fetching metadata in the background; reload this page to see it land."
ALREADY_RUNNING = (
    "A metadata fetch is already running; it will run again for this import "
    "once it finishes."
)
NOT_STARTED = (
    "The metadata fetch could not start; run it by hand, or leave it to the "
    "Sunday scheduled job."
)
# The step name reported when a job raises rather than naming its failures.
FETCH = "The metadata fetch"


def lock_key(section):
    return f"post-import-metadata:{section}"


def again_key(section):
    return f"post-import-metadata:{section}:again"


class LogStream:
    """A file-like ``stdout`` for ``call_command`` that logs each line."""

    def __init__(self, log=logger):
        self.log = log
        self._buffer = ""

    def write(self, text):
        self._buffer += text
        *lines, self._buffer = self._buffer.split("\n")
        for line in lines:
            if line.strip():
                self.log.info(line)

    def flush(self):
        if self._buffer.strip():
            self.log.info(self._buffer)
        self._buffer = ""


def schedule_after_commit(section, job):
    """Run ``job`` on a background thread once the import commits.

    Returns the line to show staff, or ``None`` when imports do not fetch
    (``METADATA_AFTER_IMPORT`` is off). It never raises: the import has
    committed, and a fetch that cannot start is logged and said so. Called
    outside a transaction, as after ``import_batch`` returns, the callback
    runs at once and the line reports what happened; inside one, the line is
    written before the commit and says only that the fetch was asked for.
    """
    if not settings.METADATA_AFTER_IMPORT:
        return None
    # The status is known only once the callback has run, which is now when
    # there is no transaction open and at the commit when there is.
    status = {"message": STARTED}
    transaction.on_commit(lambda: _start(section, job, status))
    return status["message"]


def run_in_foreground(section, job, command):
    """An import command's fetch: on its own output, under the same lock.

    Never raises, as the release is live by now: a failure is a warning on
    the command's output, not a failed import.
    """
    if not settings.METADATA_AFTER_IMPORT:
        return
    command.stdout.write(command.style.MIGRATE_HEADING("\nFetching metadata"))
    try:
        token = _acquire(section)
        if token is None:
            command.stdout.write(command.style.WARNING(ALREADY_RUNNING))
            return
        failed = _rounds(section, job, token, command.stdout)
    except Exception:
        logger.exception("The %s metadata fetch after an import failed", section)
        failed = [FETCH]
    for name in failed:
        command.stdout.write(command.style.WARNING(f"{name} failed; see the log"))


def _acquire(section):
    """The lock's new token, or ``None`` with the running fetch told to go again."""
    token = uuid.uuid4().hex
    if cache.add(lock_key(section), token, LOCK_SECONDS):
        return token
    logger.info("%s metadata fetch already running; it will go again", section)
    cache.set(again_key(section), True, AGAIN_SECONDS)
    # The running fetch may have made its last check between the add and the
    # set, and let go: then nothing would read the request, so run it here.
    if cache.add(lock_key(section), token, LOCK_SECONDS):
        return token
    return None


def _start(section, job, status):
    token = None
    try:
        token = _acquire(section)
        if token is None:
            status["message"] = ALREADY_RUNNING
            return
        start_background_thread(lambda: _run(section, job, token))
    except Exception:
        # The import has committed, so this must not read as its failure.
        # With no thread, nothing but this releases the lock.
        logger.exception("Could not start the %s metadata fetch", section)
        if token is not None:
            _release(lock_key(section), token)
        status["message"] = NOT_STARTED


def _run(section, job, token):
    stream = LogStream()
    try:
        _rounds(section, job, token, stream)
    except Exception:
        logger.exception("The %s metadata fetch after an import failed", section)
    finally:
        stream.flush()


def _rounds(section, job, token, stdout):
    """Run ``job`` until no import is waiting on it; the last round's failures."""
    key = lock_key(section)
    stop = threading.Event()
    try:
        _start_heartbeat(key, stop)
        while True:
            # Cleared before the round reads anything, so an import that
            # commits during it gets one more.
            cache.delete(again_key(section))
            failed = _one_round(section, job, stdout)
            if cache.get(again_key(section)):
                logger.info("%s metadata fetch going again for a later import", section)
                continue
            _release(key, token)
            # An import that found the lock held just before the release
            # asked for a round nothing would run: take the lock back for it,
            # unless an import since has started a fetch of its own.
            if not cache.get(again_key(section)) or not cache.add(
                key, token, LOCK_SECONDS
            ):
                return failed
            logger.info("%s metadata fetch going again for a later import", section)
    finally:
        stop.set()
        _release(key, token)


def _one_round(section, job, stdout):
    try:
        failed = list(job(stdout) or [])
    except Exception:
        logger.exception("The %s metadata fetch after an import failed", section)
        return [FETCH]
    if failed:
        # At ERROR so Sentry hears of it: staff were told it was under way.
        logger.error(
            "The %s metadata fetch after an import: %s failed",
            section,
            ", ".join(failed),
        )
    return failed


def _release(key, token):
    """Delete the lock if it is still this fetch's."""
    if cache.get(key) == token:
        cache.delete(key)


def _start_heartbeat(key, stop):
    start_background_thread(lambda: _keep_alive(key, stop))


def _keep_alive(key, stop):
    """Extend the lock's life until ``stop``; never recreate it.

    The shared cache is a Postgres table, so each touch opens a connection;
    it is closed after, not held for the length of the fetch.
    """
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            cache.touch(key, LOCK_SECONDS)
        except Exception:
            logger.exception("Could not renew the metadata fetch's lock")
        finally:
            connection.close()

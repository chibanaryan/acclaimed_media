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
read as it began, and would leave what the later import added unfetched.

The lock lives ``LOCK_SECONDS`` and a heartbeat renews it, so a fetch killed
with its worker (a deploy, ``--max-requests``; see
``start_background_thread``) frees it within two minutes, where a lock for
the longest fetch told every import for hours that a dead one would cover
it, and a round outliving its lock let a second fetch start. The heartbeat
only touches the lock: renewing it with a ``set`` could put it back just
after the fetch released it. So a lock the cache culls stays culled, and a
second fetch can start beside the first.

A fetch so killed leaves its ``pending_key`` behind, set before each round
and cleared after, and an import page's next load restarts it
(``resume_if_cut_short``): staff are told to reload that page anyway.

Other metadata work takes the same lock through ``hold``, so that it never
runs beside a fetch: the import page's IGDB and Wikipedia buttons and the
weekly scheduled jobs. Each would otherwise be a second pass at the same
rate limit and connections. One that held the lock while an import asked
for a fetch runs that fetch before letting go.
"""

import logging
import threading
import time
import uuid

from django.conf import settings
from django.core.cache import cache, caches
from django.core.cache.backends.db import DatabaseCache
from django.db import connection, connections, router, transaction
from django.utils import timezone

from core.services.background import start_background_thread

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 30
LOCK_SECONDS = 120
# A request to go again needs only to outlive the round it waits on, which
# the heartbeat keeps alive however long it runs.
AGAIN_SECONDS = 2 * 60 * 60
# Long enough to outlast a weekend: the Sunday job does the work too.
PENDING_SECONDS = 7 * 24 * 60 * 60
# How long a weekly job waits for a running fetch before giving up the week.
WEEKLY_WAIT_SECONDS = 60 * 60

STARTED = "Fetching metadata in the background; reload this page to see it land."
ALREADY_RUNNING = (
    "A metadata fetch is already running; it will run again for this import "
    "once it finishes."
)
NOT_STARTED = (
    "The metadata fetch could not start; run it by hand, or leave it to the "
    "Sunday scheduled job."
)
RESUMED = (
    "The last import's metadata fetch was cut short; it has been restarted in "
    "the background."
)
BUSY = "A metadata fetch is already running; try again once it finishes."
# The step name reported when a job raises rather than naming its failures.
FETCH = "The metadata fetch"


def lock_key(section):
    return f"post-import-metadata:{section}"


def again_key(section):
    return f"post-import-metadata:{section}:again"


def pending_key(section):
    return f"post-import-metadata:{section}:pending"


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


def resume_if_cut_short(section, job):
    """Restart a fetch that died with its worker; the line to show staff.

    ``None`` when there is nothing to restart, or imports do not fetch. A
    fetch leaves its pending marker only while it holds the lock, so the
    marker without the lock is a fetch that never finished. Never raises:
    it is called from the import page's GET.
    """
    if not settings.METADATA_AFTER_IMPORT:
        return None
    try:
        if not cache.get(pending_key(section)) or cache.get(lock_key(section)):
            return None
    except Exception:
        logger.exception("Could not check for a cut-short %s metadata fetch", section)
        return None
    logger.warning("Restarting a %s metadata fetch that was cut short", section)
    status = {"message": RESUMED}
    _start(section, job, status)
    return status["message"]


class Hold:
    """The section's lock, held for metadata work other than an import's.

    ``end`` lets it go, running the fetch first if an import asked for one
    meanwhile, since the import found the lock held and started none.
    """

    def __init__(self, section, job, token):
        self.section = section
        self.job = job
        self.token = token
        self.stop = threading.Event()

    def end(self, stdout, *, covers=False, background=False):
        """Let go of the lock. Never raises.

        ``covers`` says the work done under it was the fetch's and more (the
        weekly jobs), so a fetch cut short needs no restart. Otherwise one
        cut short is run now, as an import's would be. ``background`` runs
        that fetch on a thread, for a caller that cannot wait for it.
        """
        self.stop.set()
        try:
            section = self.section
            asked = bool(cache.get(again_key(section)))
            if not asked and covers:
                cache.delete(pending_key(section))
            elif not asked:
                asked = bool(cache.get(pending_key(section)))
            if asked and background:
                start_background_thread(lambda: self._finish(LogStream(), first=True))
            else:
                self._finish(stdout, first=asked)
        except Exception:
            logger.exception("Could not let go of the %s metadata lock", self.section)
            _release(lock_key(self.section), self.token)

    def _finish(self, stdout, *, first):
        try:
            _rounds(self.section, self.job, self.token, stdout, first=first)
        except Exception:
            logger.exception(
                "The %s metadata fetch after an import failed", self.section
            )


def hold(section, job, *, wait=0):
    """Take the section's lock for other metadata work; a ``Hold``, or ``None``.

    ``None`` once ``wait`` seconds have passed with a fetch holding it. Unlike
    an import, this asks the holder for nothing: its work is not the fetch.
    """
    key = lock_key(section)
    deadline = time.monotonic() + wait
    while True:
        token = uuid.uuid4().hex
        if _add(key, token):
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(HEARTBEAT_SECONDS, remaining))
    taken = Hold(section, job, token)
    try:
        _start_heartbeat(key, taken.stop)
    except Exception:
        _release(key, token)
        raise
    return taken


def run_weekly(section, job, command, work):
    """A weekly job's ``work``, under the section's lock.

    It waits up to ``WEEKLY_WAIT_SECONDS`` for a fetch to finish, and with
    the lock still held gives up the week, at ERROR so Sentry hears of it.
    Its work covers the fetch's, so a fetch cut short needs no restart after.
    """
    taken = hold(section, job, wait=WEEKLY_WAIT_SECONDS)
    if taken is None:
        logger.error(
            "The weekly %s metadata job gave up waiting for a fetch to finish",
            section,
        )
        command.stdout.write(
            command.style.WARNING(
                "A metadata fetch held the lock for an hour; skipping this week."
            )
        )
        return
    try:
        work()
    finally:
        taken.end(command.stdout, covers=True)


def _add(key, token):
    """``cache.add`` the lock, which two callers cannot both win.

    On the database cache an ``add`` over an expired row is a SELECT then an
    UPDATE, so two at once could both take it. Deleting the row only if it
    has expired leaves an INSERT, and the table's primary key fails the
    second, which the backend reports as ``False``. LocMem's ``add`` holds a
    lock and needs none of this.
    """
    backend = caches["default"]
    if isinstance(backend, DatabaseCache):
        db = router.db_for_write(backend.cache_model_class)
        conn = connections[db]
        quote_name = conn.ops.quote_name
        now = timezone.now().replace(microsecond=0)
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM %s WHERE %s = %%s AND %s < %%s"
                % (
                    quote_name(backend._table),
                    quote_name("cache_key"),
                    quote_name("expires"),
                ),
                [
                    backend.make_and_validate_key(key),
                    conn.ops.adapt_datetimefield_value(now),
                ],
            )
    return cache.add(key, token, LOCK_SECONDS)


def _acquire(section):
    """The lock's new token, or ``None`` with the running fetch told to go again."""
    token = uuid.uuid4().hex
    if _add(lock_key(section), token):
        return token
    logger.info("%s metadata fetch already running; it will go again", section)
    cache.set(again_key(section), True, AGAIN_SECONDS)
    # The running fetch may have made its last check between the add and the
    # set, and let go: then nothing would read the request, so run it here.
    if _add(lock_key(section), token):
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


def _rounds(section, job, token, stdout, *, first=True):
    """Run ``job`` until no import is waiting on it; the last round's failures.

    With ``first`` false the lock was held for other work (``Hold``), and a
    round runs only if an import has asked for one.
    """
    key = lock_key(section)
    stop = threading.Event()
    failed = []
    try:
        _start_heartbeat(key, stop)
        go = first
        while True:
            if go or cache.get(again_key(section)):
                # Left behind if this worker dies mid-round, for the import
                # page to restart; cleared before the release, so it never
                # stands beside a live fetch's lock.
                cache.set(pending_key(section), True, PENDING_SECONDS)
                while True:
                    # Cleared before the round reads anything, so an import
                    # that commits during it gets one more.
                    cache.delete(again_key(section))
                    failed = _one_round(section, job, stdout)
                    if not cache.get(again_key(section)):
                        break
                    logger.info(
                        "%s metadata fetch going again for a later import", section
                    )
                cache.delete(pending_key(section))
            _release(key, token)
            # An import that found the lock held just before the release
            # asked for a round nothing would run: take the lock back for it,
            # unless an import since has started a fetch of its own.
            if not cache.get(again_key(section)) or not _add(key, token):
                return failed
            go = True
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

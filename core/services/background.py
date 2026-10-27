"""Work that outlives the request that started it."""

import threading

from django.db import connection


def start_background_thread(target, *, daemon=True):
    """Run ``target`` on a daemon thread that closes its DB connection after.

    Django's connections are per thread, and one opened here outlives its
    thread until the cyclic garbage collector gets to the thread's wrapper,
    holding a Postgres slot meanwhile. Under gunicorn's gthread workers the
    web threads already account for workers x threads of those slots.

    A daemon thread dies with its worker: a restart mid-run (a deploy,
    ``--max-requests``) cuts the work short, so callers record what must
    not happen twice before they start one. ``daemon=False`` makes a
    graceful shutdown wait for it instead - the interpreter does not exit
    while one runs - up to the platform's kill (30 s on Heroku).
    """

    def run():
        try:
            target()
        finally:
            connection.close()

    thread = threading.Thread(target=run, daemon=daemon)
    thread.start()
    return thread

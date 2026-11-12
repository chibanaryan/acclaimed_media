"""A progress stream: the events a worker thread reports, as server-sent events.

The staff import page watches three long jobs over SSE: the IGDB fetch, the
Wikipedia lookup and the batch import. Each runs on a thread that reports
its progress, while the request's generator turns those reports into frames
for the browser. Until 2026-11-12 each carried its own copy of the queue and
of the loop that drains it, and the copies had drifted: the IGDB stream sent
no keepalives, so a batch that took IGDB more than 55 seconds to answer was
a connection Heroku's router closed.
"""

import json
import queue
import threading

# Whitespace after a frame, so no proxy holds it back waiting for more
PADDING = " " * 2048
# A comment line, which EventSource ignores, to keep the connection open
KEEPALIVE = ": keepalive\n\n"
# Well inside the 55 seconds Heroku's router allows an idle connection
POLL_SECONDS = 15
# 120 polls of 15 seconds: half an hour with nothing reported
MAX_IDLE_POLLS = 120


def frame(event_json):
    """One event as an SSE frame, padded so it is flushed at once."""
    return f"data: {event_json}\n\n" + PADDING + "\n"


class ProgressEvents:
    """What a job has reported and its page has not yet been sent.

    Bounded, so a slow or departed client cannot grow it without limit: a
    report that finds it full replaces the oldest one.
    """

    def __init__(self, maxsize=1000):
        self._queue = queue.Queue(maxsize=maxsize)
        self._stopped = threading.Event()

    def put(self, payload):
        """Queue a serialised event, or ``None`` to end the stream."""
        if self.stopped():
            return
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(payload)
            except (queue.Empty, queue.Full):
                # Another thread emptied or refilled it in between
                return

    def emit(self, event_type, data):
        """A service's progress callback: ``data``, named ``event_type``."""
        data.setdefault("event", event_type)
        self.put(json.dumps(data))

    def send(self, event_type, **data):
        """Queue one event built here."""
        self.put(json.dumps({"event": event_type, **data}))

    def finish(self):
        """The job is done: end the stream once what is queued has gone."""
        self.put(None)

    def stop(self):
        """The client has gone: queue nothing more."""
        self._stopped.set()

    def stopped(self):
        return self._stopped.is_set()

    def get(self, timeout):
        return self._queue.get(timeout=timeout)


def drain(
    events,
    *,
    idle_event,
    poll=POLL_SECONDS,
    max_idle_polls=MAX_IDLE_POLLS,
    on_disconnect=None,
):
    """Yield ``events`` as SSE frames until the job finishes.

    A keepalive goes out for every ``poll`` seconds with nothing reported,
    and after ``max_idle_polls`` of those in a row the job is taken for
    stalled: ``idle_event`` is sent and the stream ends. A client that
    disconnects stops the queue, so the job's later reports are dropped.
    """
    idle = 0
    try:
        while True:
            try:
                event_json = events.get(timeout=poll)
            except queue.Empty:
                idle += 1
                if idle >= max_idle_polls:
                    yield f"data: {json.dumps(idle_event)}\n\n"
                    return
                yield KEEPALIVE
                continue
            if event_json is None:
                return
            idle = 0
            yield frame(event_json)
    except GeneratorExit:
        events.stop()
        if on_disconnect:
            on_disconnect()
        raise

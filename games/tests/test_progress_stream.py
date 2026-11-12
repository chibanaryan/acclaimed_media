"""The queue and the drain loop the three import streams share."""

import json
import queue
from unittest import mock

from django.test import SimpleTestCase

from games.services import progress_stream
from games.services.progress_stream import KEEPALIVE, ProgressEvents, drain, frame

IDLE = {"event": "error", "error": "stalled"}


def drained(events, **kwargs):
    kwargs.setdefault("idle_event", IDLE)
    kwargs.setdefault("poll", 0)
    return list(drain(events, **kwargs))


class FrameTests(SimpleTestCase):
    def test_a_frame_is_one_padded_data_line(self):
        self.assertEqual(frame('{"a": 1}'), 'data: {"a": 1}\n\n' + " " * 2048 + "\n")


class ProgressEventsTests(SimpleTestCase):
    def test_emit_names_the_event(self):
        events = ProgressEvents()
        events.emit("progress", {"current": 1})
        self.assertEqual(
            json.loads(events.get(timeout=0)), {"current": 1, "event": "progress"}
        )

    def test_emit_keeps_a_name_the_service_gave(self):
        events = ProgressEvents()
        events.emit("progress", {"event": "start"})
        self.assertEqual(json.loads(events.get(timeout=0)), {"event": "start"})

    def test_send_builds_an_event(self):
        events = ProgressEvents()
        events.send("error", message="No")
        self.assertEqual(
            json.loads(events.get(timeout=0)), {"event": "error", "message": "No"}
        )

    def test_a_full_queue_drops_its_oldest_event(self):
        events = ProgressEvents(maxsize=2)
        for payload in ("one", "two", "three"):
            events.put(payload)
        self.assertEqual(
            [events.get(timeout=0), events.get(timeout=0)], ["two", "three"]
        )

    def test_a_queue_emptied_in_between_drops_the_event(self):
        """Another thread took the last one as this one made room."""
        events = ProgressEvents(maxsize=1)
        events.put("one")
        with mock.patch.object(
            events._queue, "get_nowait", side_effect=queue.Empty
        ) as taken:
            events.put("two")
        taken.assert_called_once_with()
        self.assertEqual(events.get(timeout=0), "one")

    def test_nothing_is_queued_once_the_client_has_gone(self):
        events = ProgressEvents()
        self.assertFalse(events.stopped())
        events.stop()
        self.assertTrue(events.stopped())
        events.put("late")
        events.finish()
        with self.assertRaises(queue.Empty):
            events.get(timeout=0)


class DrainTests(SimpleTestCase):
    def test_events_are_framed_until_the_job_finishes(self):
        events = ProgressEvents()
        events.put("one")
        events.put("two")
        events.finish()
        events.put("after the end")
        self.assertEqual(drained(events), [frame("one"), frame("two")])

    def test_a_quiet_job_gets_keepalives_then_the_idle_event(self):
        frames = drained(ProgressEvents(), max_idle_polls=3)
        self.assertEqual(
            frames, [KEEPALIVE, KEEPALIVE, f"data: {json.dumps(IDLE)}\n\n"]
        )

    def test_an_event_starts_the_idle_count_again(self):
        get = mock.Mock(side_effect=[queue.Empty, "one", queue.Empty, None])
        events = mock.Mock(get=get)
        frames = drained(events, max_idle_polls=2)
        self.assertEqual(frames, [KEEPALIVE, frame("one"), KEEPALIVE])

    def test_the_queue_is_polled_at_the_interval_given(self):
        events = mock.Mock(get=mock.Mock(return_value=None))
        list(drain(events, idle_event=IDLE))
        events.get.assert_called_once_with(timeout=progress_stream.POLL_SECONDS)

    def test_a_client_that_leaves_stops_the_queue(self):
        events = ProgressEvents()
        events.put("one")
        left = mock.Mock()
        stream = drain(events, idle_event=IDLE, poll=0, on_disconnect=left)
        self.assertEqual(next(stream), frame("one"))
        stream.close()
        self.assertTrue(events.stopped())
        left.assert_called_once_with()

    def test_leaving_needs_no_callback(self):
        events = ProgressEvents()
        events.put("one")
        stream = drain(events, idle_event=IDLE, poll=0)
        next(stream)
        stream.close()
        self.assertTrue(events.stopped())

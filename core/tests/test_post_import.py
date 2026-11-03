"""The metadata fetch an import starts once it commits."""

import threading
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.cache import cache, caches
from django.core.management.base import BaseCommand
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.services import post_import
from core.tests.utils import DatabaseCacheTestCase

THREAD = "core.services.post_import.start_background_thread"
HEARTBEAT = "core.services.post_import._start_heartbeat"
LOCK = post_import.lock_key("test")
AGAIN = post_import.again_key("test")
PENDING = post_import.pending_key("test")


def _run_inline(target, **kwargs):
    target()


class PostImportTestCase(TestCase):
    def setUp(self):
        # Django's runner does not clear caches between tests.
        for key in (LOCK, AGAIN, PENDING):
            cache.delete(key)
            self.addCleanup(cache.delete, key)
        # Inline, a heartbeat would beat until its fetch stopped it, and the
        # fetch is waiting on it to return.
        patcher = mock.patch(HEARTBEAT)
        self.heartbeat = patcher.start()
        self.addCleanup(patcher.stop)
        self.job = mock.Mock(return_value=[])

    def run_inline(self, job=None):
        with mock.patch(THREAD, side_effect=_run_inline):
            with self.captureOnCommitCallbacks(execute=True):
                return post_import.schedule_after_commit("test", job or self.job)


@override_settings(METADATA_AFTER_IMPORT=True)
class ScheduleAfterCommitTests(PostImportTestCase):
    def test_nothing_is_scheduled_with_the_setting_off(self):
        with override_settings(METADATA_AFTER_IMPORT=False):
            with self.captureOnCommitCallbacks() as callbacks:
                self.assertIsNone(post_import.schedule_after_commit("test", self.job))
        self.assertEqual(callbacks, [])

    def test_the_fetch_waits_for_the_commit(self):
        with mock.patch(THREAD) as thread:
            with self.captureOnCommitCallbacks() as callbacks:
                message = post_import.schedule_after_commit("test", self.job)
                thread.assert_not_called()
            self.assertEqual(message, post_import.STARTED)
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
        thread.assert_called_once()

    def test_a_rolled_back_import_starts_nothing(self):
        with mock.patch(THREAD) as thread:
            with self.captureOnCommitCallbacks(execute=False):
                post_import.schedule_after_commit("test", self.job)
        thread.assert_not_called()

    def test_the_job_runs_with_a_logging_stdout_and_releases_the_lock(self):
        self.run_inline()
        self.job.assert_called_once()
        self.assertIsInstance(self.job.call_args.args[0], post_import.LogStream)
        self.assertIsNone(cache.get(LOCK))

    def test_a_dead_fetchs_lock_lapses_within_minutes(self):
        """A lock for the longest fetch told imports for hours a dead one ran."""
        self.assertLessEqual(post_import.LOCK_SECONDS, 5 * 60)
        self.assertGreater(post_import.LOCK_SECONDS, 2 * post_import.HEARTBEAT_SECONDS)

    def test_the_lock_is_kept_alive_while_the_fetch_runs(self):
        self.run_inline()
        self.heartbeat.assert_called_once()
        key, stop = self.heartbeat.call_args.args
        self.assertEqual(key, LOCK)
        self.assertTrue(stop.is_set())

    def test_a_job_that_raises_is_logged_and_releases_the_lock(self):
        self.job.side_effect = RuntimeError("IGDB down")
        with self.assertLogs("core.services.post_import", "ERROR") as logs:
            self.run_inline()
        self.assertIn("test metadata fetch after an import failed", logs.output[0])
        self.assertIsNone(cache.get(LOCK))

    def test_failed_steps_are_logged_as_errors(self):
        """Staff were told it was under way, so Sentry hears it was not."""
        self.job.return_value = ["get_igdb"]
        with self.assertLogs("core.services.post_import", "ERROR") as logs:
            self.run_inline()
        self.assertIn("get_igdb failed", logs.output[0])

    def test_a_running_fetch_is_asked_to_go_again_rather_than_joined(self):
        status = {}
        cache.add(LOCK, "theirs")
        with mock.patch(THREAD) as thread:
            post_import._start("test", self.job, status)
        thread.assert_not_called()
        self.assertEqual(status["message"], post_import.ALREADY_RUNNING)
        self.assertTrue(cache.get(AGAIN))
        # The running fetch's lock is left for it to release.
        self.assertEqual(cache.get(LOCK), "theirs")

    def test_an_import_during_a_round_gets_another(self):
        """A games import recreates every game the running round is fetching."""
        rounds = []

        def job(stdout):
            rounds.append(cache.get(LOCK))
            if len(rounds) == 1:
                # A second import lands while this round runs.
                post_import._start("test", mock.Mock(), {})
            return []

        self.run_inline(job)
        self.assertEqual(len(rounds), 2)
        self.assertEqual(rounds[0], rounds[1])
        self.assertIsNone(cache.get(LOCK))
        self.assertIsNone(cache.get(AGAIN))

    def test_an_import_as_the_lock_is_released_still_gets_its_round(self):
        """It found the lock held, so it started nothing of its own."""
        rounds = []
        delete = cache.delete

        def delete_then_import(key, *args, **kwargs):
            delete(key, *args, **kwargs)
            if key == LOCK and len(rounds) == 1:
                cache.set(AGAIN, True)

        def job(stdout):
            rounds.append(1)
            return []

        with mock.patch.object(post_import.cache, "delete", delete_then_import):
            self.run_inline(job)
        self.assertEqual(len(rounds), 2)
        self.assertIsNone(cache.get(LOCK))

    def test_a_fetch_started_since_the_release_is_left_to_run_alone(self):
        rounds = []
        delete = cache.delete

        def delete_then_another_starts(key, *args, **kwargs):
            delete(key, *args, **kwargs)
            if key == LOCK and len(rounds) == 1:
                cache.set(AGAIN, True)
                cache.add(LOCK, "theirs")

        def job(stdout):
            rounds.append(1)
            return []

        with mock.patch.object(post_import.cache, "delete", delete_then_another_starts):
            self.run_inline(job)
        self.assertEqual(len(rounds), 1)
        self.assertEqual(cache.get(LOCK), "theirs")

    def test_a_failed_round_still_goes_again(self):
        calls = []

        def job(stdout):
            calls.append(stdout)
            if len(calls) == 1:
                cache.set(AGAIN, True)
                raise RuntimeError("IGDB down")
            return []

        with self.assertLogs("core.services.post_import", "ERROR"):
            self.run_inline(job)
        self.assertEqual(len(calls), 2)

    def test_a_lock_taken_over_after_it_lapsed_is_not_released(self):
        """The heartbeat's fetch died; another holds it now."""

        def job(stdout):
            cache.set(LOCK, "theirs")
            return []

        self.run_inline(job)
        self.assertEqual(cache.get(LOCK), "theirs")

    def test_a_cache_error_mid_fetch_is_logged(self):
        with mock.patch.object(post_import.cache, "get", side_effect=ConnectionError):
            with self.assertLogs("core.services.post_import", "ERROR") as logs:
                self.run_inline()
        self.assertIn("test metadata fetch after an import failed", logs.output[-1])

    def test_a_request_that_lands_after_the_last_check_runs_here(self):
        """The running fetch let go between this import's add and its ask."""
        with mock.patch.object(
            post_import.cache, "add", side_effect=[False, True]
        ) as add:
            token = post_import._acquire("test")
        self.assertIsNotNone(token)
        self.assertEqual(add.call_count, 2)

    def test_a_request_to_a_live_fetch_leaves_it_the_lock(self):
        with mock.patch.object(post_import.cache, "add", side_effect=[False, False]):
            self.assertIsNone(post_import._acquire("test"))
        self.assertTrue(cache.get(AGAIN))

    def test_a_heartbeat_that_will_not_start_releases_the_lock(self):
        self.heartbeat.side_effect = RuntimeError("can't start new thread")
        with self.assertLogs("core.services.post_import", "ERROR"):
            self.run_inline()
        self.job.assert_not_called()
        self.assertIsNone(cache.get(LOCK))

    def test_a_thread_that_will_not_start_releases_the_lock(self):
        status = {}
        with mock.patch(THREAD, side_effect=RuntimeError("can't start new thread")):
            with self.assertLogs("core.services.post_import", "ERROR"):
                post_import._start("test", self.job, status)
        self.assertEqual(status["message"], post_import.NOT_STARTED)
        self.assertIsNone(cache.get(LOCK))

    def test_a_lock_that_will_not_release_is_not_a_failed_import(self):
        status = {}
        with (
            mock.patch(THREAD, side_effect=RuntimeError("can't start new thread")),
            mock.patch.object(post_import, "_release", side_effect=ConnectionError),
            self.assertLogs("core.services.post_import", "ERROR"),
        ):
            post_import._start("test", self.job, status)
        self.assertEqual(status["message"], post_import.NOT_STARTED)

    def test_a_cache_error_is_not_a_failed_import(self):
        status = {}
        with mock.patch.object(post_import.cache, "add", side_effect=ConnectionError):
            with self.assertLogs("core.services.post_import", "ERROR"):
                post_import._start("test", self.job, status)
        self.assertEqual(status["message"], post_import.NOT_STARTED)


@override_settings(METADATA_AFTER_IMPORT=True)
class CutShortFetchTests(PostImportTestCase):
    """A fetch killed with its worker leaves a marker the import page reads."""

    def test_a_round_is_marked_pending_while_it_runs(self):
        seen = []
        self.job.side_effect = lambda stdout: seen.append(cache.get(PENDING)) or []
        self.run_inline()
        self.assertEqual(seen, [0])  # an import's own fetch, never restarted
        self.assertIsNone(cache.get(PENDING))

    def test_a_round_that_raised_is_not_pending(self):
        """Its failure was reported; running it again would fail again."""
        self.job.side_effect = RuntimeError("IGDB down")
        with self.assertLogs("core.services.post_import", "ERROR"):
            self.run_inline()
        self.assertIsNone(cache.get(PENDING))

    def resume(self):
        with mock.patch(THREAD, side_effect=_run_inline):
            return post_import.resume_if_cut_short("test", self.job)

    def test_a_fetch_cut_short_is_restarted_once(self):
        cache.set(PENDING, 0)
        seen = []
        self.job.side_effect = lambda stdout: seen.append(cache.get(PENDING)) or []
        with self.assertLogs("core.services.post_import", "WARNING"):
            self.assertEqual(self.resume(), post_import.RESUMED)
        self.assertEqual(seen, [1])  # marked as a restart while it runs
        self.assertIsNone(cache.get(PENDING))
        self.assertIsNone(self.resume())
        self.job.assert_called_once()

    def test_a_restart_cut_short_too_is_left_to_sunday_and_said_once(self):
        """One that takes its worker down would take one down on every
        reload; and staff reloading are told, once."""
        cache.set(PENDING, 1)
        with self.assertLogs("core.services.post_import", "ERROR"):
            self.assertEqual(self.resume(), post_import.GAVE_UP)
        self.job.assert_not_called()
        self.assertIsNone(cache.get(PENDING))
        self.assertIsNone(cache.get(LOCK))
        self.assertIsNone(self.resume())

    def test_a_later_imports_fetch_cut_short_is_restarted_too(self):
        """It is not the restart that died."""
        cache.set(PENDING, 0)
        with self.assertLogs("core.services.post_import", "WARNING"):
            self.resume()
        cache.set(PENDING, 0)
        with self.assertLogs("core.services.post_import", "WARNING"):
            self.assertEqual(self.resume(), post_import.RESUMED)
        self.assertEqual(self.job.call_count, 2)

    def test_an_import_after_a_restart_starts_from_none(self):
        """The rounds an import asks for while a restart runs are its own."""
        seen = []

        def job(stdout):
            seen.append(cache.get(PENDING))
            if len(seen) == 1:
                cache.set(AGAIN, True)
            return []

        cache.set(PENDING, 0)
        with self.assertLogs("core.services.post_import", "WARNING"):
            with mock.patch(THREAD, side_effect=_run_inline):
                post_import.resume_if_cut_short("test", job)
        self.assertEqual(seen, [1, 0])

    def test_a_load_during_a_live_fetch_writes_nothing(self):
        """Staff reload the page to watch one land."""
        cache.set(PENDING, 0)
        cache.add(LOCK, "theirs")
        with mock.patch.object(post_import, "_add") as add:
            self.assertIsNone(self.resume())
        add.assert_not_called()

    def test_an_imports_request_restarts_it_afresh(self):
        """A failed restart's count must not give up on a new import's fetch."""
        cache.set(PENDING, 1)
        cache.set(AGAIN, True)
        seen = []
        self.job.side_effect = lambda stdout: seen.append(cache.get(PENDING)) or []
        with self.assertLogs("core.services.post_import", "WARNING"):
            self.assertEqual(self.resume(), post_import.RESUMED)
        self.assertEqual(seen, [0])

    def test_an_import_asking_as_it_gives_up_gets_its_fetch(self):
        cache.set(PENDING, 1)
        release = post_import._release
        calls = []

        def release_then_import(key, token):
            release(key, token)
            calls.append(key)
            if len(calls) == 1:
                cache.set(AGAIN, True)

        with (
            mock.patch.object(post_import, "_release", side_effect=release_then_import),
            self.assertLogs("core.services.post_import", "ERROR"),
        ):
            self.assertEqual(self.resume(), post_import.GAVE_UP)
        self.job.assert_called_once()

    def test_two_loads_at_once_restart_it_once(self):
        """Both read the marker before either took the lock."""
        cache.set(PENDING, 0)
        with mock.patch(THREAD) as thread:
            with self.assertLogs("core.services.post_import", "WARNING"):
                self.assertEqual(
                    post_import.resume_if_cut_short("test", self.job),
                    post_import.RESUMED,
                )
            self.assertIsNone(post_import.resume_if_cut_short("test", self.job))
        self.assertEqual(thread.call_count, 1)
        self.assertIsNone(cache.get(AGAIN))  # no import asked for anything

    def test_a_fetch_finished_between_the_reads_is_not_restarted(self):
        cache.set(PENDING, 0)
        add = post_import._add

        def finish_then_add(key, token):
            cache.delete(PENDING)
            return add(key, token)

        with mock.patch.object(post_import, "_add", side_effect=finish_then_add):
            self.assertIsNone(self.resume())
        self.job.assert_not_called()
        self.assertIsNone(cache.get(LOCK))

    def test_a_fetch_started_between_the_reads_keeps_its_marker(self):
        cache.set(PENDING, 1)
        add = post_import._add

        def start_then_add(key, token):
            cache.add(LOCK, "theirs")
            cache.set(PENDING, 0)
            return add(key, token)

        with mock.patch.object(post_import, "_add", side_effect=start_then_add):
            self.assertIsNone(self.resume())
        self.assertEqual(cache.get(PENDING), 0)
        self.assertEqual(cache.get(LOCK), "theirs")

    def test_a_restart_that_will_not_start_lets_go(self):
        cache.set(PENDING, 0)
        with (
            mock.patch(THREAD, side_effect=RuntimeError("can't start new thread")),
            self.assertLogs("core.services.post_import", "WARNING"),
        ):
            self.assertEqual(
                post_import.resume_if_cut_short("test", self.job),
                post_import.NOT_STARTED,
            )
        self.assertIsNone(cache.get(LOCK))

    def test_a_live_fetch_is_left_alone(self):
        """Its marker stands beside its lock."""
        cache.set(PENDING, 0)
        cache.add(LOCK, "theirs")
        self.assertIsNone(self.resume())
        self.job.assert_not_called()
        self.assertIsNone(cache.get(AGAIN))

    def test_nothing_to_restart(self):
        self.assertIsNone(self.resume())
        self.job.assert_not_called()

    def test_nothing_with_the_setting_off(self):
        cache.set(PENDING, 0)
        with override_settings(METADATA_AFTER_IMPORT=False):
            self.assertIsNone(self.resume())
        self.job.assert_not_called()

    def test_a_cache_error_does_not_break_the_page(self):
        with mock.patch.object(
            post_import.cache, "get_many", side_effect=ConnectionError
        ):
            with self.assertLogs("core.services.post_import", "ERROR"):
                self.assertIsNone(self.resume())

    def test_a_cache_error_under_the_lock_lets_it_go(self):
        cache.set(PENDING, 0)
        get = cache.get
        reads = []

        def second_read_fails(key, *args):
            reads.append(key)
            if len(reads) == 2:
                raise ConnectionError
            return get(key, *args)

        with (
            mock.patch.object(post_import.cache, "get", side_effect=second_read_fails),
            self.assertLogs("core.services.post_import", "ERROR"),
        ):
            self.assertIsNone(self.resume())
        self.assertIsNone(cache.get(LOCK))

    def test_a_lock_that_will_not_release_does_not_break_the_page(self):
        cache.set(PENDING, 0)
        with (
            mock.patch.object(post_import, "_read_owed", side_effect=ConnectionError),
            mock.patch.object(post_import, "_release", side_effect=ConnectionError),
            self.assertLogs("core.services.post_import", "ERROR") as logs,
        ):
            self.assertIsNone(self.resume())
        self.assertIn("Could not release", logs.output[-1])


class HoldTests(PostImportTestCase):
    """Other metadata work takes the same lock, and owes the fetch it delays."""

    def test_a_free_lock_is_taken_and_kept_alive(self):
        taken = post_import.hold("test", self.job)
        self.assertEqual(cache.get(LOCK), taken.token)
        self.heartbeat.assert_called_once_with(LOCK, taken.stop)
        taken.end(StringIO())
        self.assertTrue(taken.stop.is_set())
        self.assertIsNone(cache.get(LOCK))
        self.job.assert_not_called()

    def test_a_held_lock_is_not_taken_nor_asked_for_a_round(self):
        """A button's IGDB pass is not the fetch an import needs."""
        cache.add(LOCK, "theirs")
        self.assertIsNone(post_import.hold("test", self.job))
        self.assertEqual(cache.get(LOCK), "theirs")
        self.assertIsNone(cache.get(AGAIN))

    def test_it_waits_for_the_lock_when_asked(self):
        with (
            mock.patch.object(post_import.cache, "add", side_effect=[False, True]),
            mock.patch.object(post_import.time, "sleep") as sleep,
        ):
            self.assertIsNotNone(post_import.hold("test", self.job, wait=60))
        sleep.assert_called_once_with(post_import.HEARTBEAT_SECONDS)

    def test_it_gives_up_once_the_wait_is_over(self):
        clock = iter([0, 10, 70])
        with (
            mock.patch.object(post_import.cache, "add", return_value=False),
            mock.patch.object(post_import.time, "monotonic", lambda: next(clock)),
            mock.patch.object(post_import.time, "sleep") as sleep,
        ):
            self.assertIsNone(post_import.hold("test", self.job, wait=60))
        self.assertEqual(sleep.call_args_list, [mock.call(30)])

    def test_a_heartbeat_that_will_not_start_releases_it(self):
        self.heartbeat.side_effect = RuntimeError("can't start new thread")
        with self.assertRaises(RuntimeError):
            post_import.hold("test", self.job)
        self.assertIsNone(cache.get(LOCK))

    def test_an_import_that_asked_meanwhile_gets_its_fetch(self):
        """It found the lock held, so it started none of its own."""
        taken = post_import.hold("test", self.job)
        post_import._start("test", mock.Mock(), {})
        taken.end(StringIO())
        self.job.assert_called_once()
        self.assertIsNone(cache.get(LOCK))
        self.assertIsNone(cache.get(AGAIN))

    def test_a_fetch_cut_short_is_finished_after(self):
        cache.set(PENDING, 0)
        seen = []
        self.job.side_effect = lambda stdout: seen.append(cache.get(PENDING)) or []
        taken = post_import.hold("test", self.job)
        taken.end(StringIO())
        self.assertEqual(seen, [1])
        self.assertIsNone(cache.get(PENDING))

    def test_a_restart_cut_short_too_is_left_for_the_page_to_report(self):
        cache.set(PENDING, 1)
        taken = post_import.hold("test", self.job)
        taken.end(StringIO())
        self.job.assert_not_called()
        self.assertEqual(cache.get(PENDING), 1)
        self.assertIsNone(cache.get(LOCK))
        with (
            mock.patch(THREAD, side_effect=_run_inline),
            override_settings(METADATA_AFTER_IMPORT=True),
            self.assertLogs("core.services.post_import", "ERROR"),
        ):
            self.assertEqual(
                post_import.resume_if_cut_short("test", self.job),
                post_import.GAVE_UP,
            )
        self.job.assert_not_called()

    def test_an_imports_request_starts_the_count_afresh(self):
        """A failed restart's count must not give up on a new import's fetch."""
        cache.set(PENDING, 1)
        taken = post_import.hold("test", self.job)
        cache.set(AGAIN, True)
        taken.end(StringIO(), owed=post_import.LEAVE_TO_THE_PAGE)
        self.assertEqual(cache.get(PENDING), 0)

    def test_a_weekly_that_did_the_work_drops_a_given_up_marker(self):
        """Or the page would report, days later, work the job had done."""
        cache.set(PENDING, 1)
        taken = post_import.hold("test", self.job)
        taken.end(StringIO(), did_the_work=True)
        self.job.assert_not_called()
        self.assertIsNone(cache.get(PENDING))

    def import_asks_as_it_lets_go(self):
        release = post_import._release
        calls = []

        def release_then_import(key, token):
            release(key, token)
            calls.append(key)
            if len(calls) == 1:
                cache.set(AGAIN, True)

        return mock.patch.object(
            post_import, "_release", side_effect=release_then_import
        )

    def test_a_late_request_runs_on_a_thread_when_asked_to(self):
        """The stream that never started work cannot wait for a fetch."""
        taken = post_import.hold("test", self.job)
        with self.import_asks_as_it_lets_go(), mock.patch(THREAD) as thread:
            taken.end(StringIO(), owed=post_import.RUN_ON_A_THREAD)
        self.job.assert_not_called()
        thread.call_args.args[0]()
        self.job.assert_called_once()

    def test_a_late_request_is_left_to_the_page_when_asked_to(self):
        taken = post_import.hold("test", self.job)
        with self.import_asks_as_it_lets_go():
            taken.end(StringIO(), owed=post_import.LEAVE_TO_THE_PAGE)
        self.job.assert_not_called()
        self.assertEqual(cache.get(PENDING), 0)
        self.assertIsNone(cache.get(LOCK))

    def test_a_late_request_runs_here_by_default(self):
        taken = post_import.hold("test", self.job)
        with self.import_asks_as_it_lets_go():
            taken.end(StringIO())
        self.job.assert_called_once()
        self.assertIsNone(cache.get(LOCK))

    def test_an_imports_request_runs_whatever_the_old_count(self):
        cache.set(PENDING, 1)
        seen = []
        self.job.side_effect = lambda stdout: seen.append(cache.get(PENDING)) or []
        taken = post_import.hold("test", self.job)
        cache.set(AGAIN, True)
        taken.end(StringIO())
        self.assertEqual(seen, [0])
        self.assertIsNone(cache.get(PENDING))

    def test_a_fetch_owed_can_be_left_to_the_page(self):
        """An import's request becomes a marker the page restarts."""
        taken = post_import.hold("test", self.job)
        cache.set(AGAIN, True)
        taken.end(StringIO(), owed=post_import.LEAVE_TO_THE_PAGE)
        self.job.assert_not_called()
        self.assertEqual(cache.get(PENDING), 0)
        self.assertIsNone(cache.get(AGAIN))
        self.assertIsNone(cache.get(LOCK))

    def test_a_cut_short_fetch_left_to_the_page_keeps_its_count(self):
        cache.set(PENDING, 0)
        taken = post_import.hold("test", self.job)
        taken.end(StringIO(), owed=post_import.LEAVE_TO_THE_PAGE)
        self.job.assert_not_called()
        self.assertEqual(cache.get(PENDING), 0)

    def test_a_fetch_owed_can_run_on_a_thread(self):
        taken = post_import.hold("test", self.job)
        cache.set(AGAIN, True)
        with mock.patch(THREAD) as thread:
            taken.end(StringIO(), owed=post_import.RUN_ON_A_THREAD)
        self.job.assert_not_called()
        thread.call_args.args[0]()
        self.job.assert_called_once()
        self.assertIsNone(cache.get(LOCK))

    def test_a_fetch_owed_that_raises_is_logged(self):
        taken = post_import.hold("test", self.job)
        cache.set(AGAIN, True)
        with (
            mock.patch.object(post_import, "_rounds", side_effect=ConnectionError),
            self.assertLogs("core.services.post_import", "ERROR"),
        ):
            taken.end(StringIO())

    def test_a_cache_that_stays_down_does_not_raise(self):
        """It is called from finally blocks: a weekly job's, a stream's."""
        taken = post_import.hold("test", self.job)
        with (
            mock.patch.object(post_import.cache, "get", side_effect=ConnectionError),
            self.assertLogs("core.services.post_import", "ERROR"),
        ):
            taken.end(StringIO())

    def test_nothing_owed_starts_no_heartbeat(self):
        taken = post_import.hold("test", self.job)
        self.heartbeat.reset_mock()
        taken.end(StringIO())
        self.heartbeat.assert_not_called()
        self.assertIsNone(cache.get(LOCK))

    def test_a_cache_error_still_lets_go(self):
        taken = post_import.hold("test", self.job)
        with (
            mock.patch.object(
                post_import.cache, "get", side_effect=[ConnectionError, taken.token]
            ),
            self.assertLogs("core.services.post_import", "ERROR"),
        ):
            taken.end(StringIO())
        self.assertIsNone(cache.get(LOCK))


class RunWeeklyTests(PostImportTestCase):
    def test_the_work_runs_under_the_lock_then_any_fetch_owed(self):
        """Every pass of the fetch is missing-only, so after the weekly
        work it costs little; and the weekly's own failures are warnings,
        which cannot say whether it did the fetch's work."""
        cache.set(PENDING, 0)
        seen = []
        post_import.run_weekly(
            "test", self.job, _Command(), lambda: seen.append(cache.get(LOCK))
        )
        self.assertTrue(seen[0])
        self.job.assert_called_once()
        self.assertIsNone(cache.get(LOCK))
        self.assertIsNone(cache.get(PENDING))

    def test_work_that_raises_still_lets_go(self):
        def work():
            raise RuntimeError("IGDB down")

        with self.assertRaises(RuntimeError):
            post_import.run_weekly("test", self.job, _Command(), work)
        self.assertIsNone(cache.get(LOCK))

    def test_a_cache_error_does_not_skip_the_week(self):
        """The refresh matters more than the lock that keeps it apart."""
        work = mock.Mock()
        with (
            mock.patch.object(post_import, "hold", side_effect=ConnectionError),
            self.assertLogs("core.services.post_import", "ERROR"),
        ):
            post_import.run_weekly("test", self.job, _Command(), work)
        work.assert_called_once_with()

    def test_work_that_raised_leaves_the_fetch_owed_to_the_page(self):
        """Run now, it would hold the job's error back behind a whole fetch,
        likely against the same failing service."""
        cache.set(AGAIN, True)

        def work():
            raise RuntimeError("IGDB down")

        with self.assertRaises(RuntimeError):
            post_import.run_weekly("test", self.job, _Command(), work)
        self.job.assert_not_called()
        self.assertEqual(cache.get(PENDING), 0)
        self.assertIsNone(cache.get(LOCK))

    def test_an_imports_request_outlives_the_longest_weekly_hold(self):
        """Lapsed, the hold's end would read nothing asked, and the import's
        fetch would never run."""
        longest_weekly = post_import.WEEKLY_WAIT_SECONDS + 3 * 60 * 60
        self.assertGreater(post_import.AGAIN_SECONDS, longest_weekly)

    def test_a_fetch_that_outlasts_the_wait_skips_the_week(self):
        command = _Command()
        work = mock.Mock()
        with (
            mock.patch.object(post_import, "hold", return_value=None) as hold,
            self.assertLogs("core.services.post_import", "ERROR"),
        ):
            post_import.run_weekly("test", self.job, command, work)
        self.assertEqual(hold.call_args.kwargs["wait"], post_import.WEEKLY_WAIT_SECONDS)
        work.assert_not_called()
        self.assertIn("skipping this week", command.output())


class DatabaseCacheLockTests(DatabaseCacheTestCase):
    """On the shared cache, an ``add`` over an expired row is a SELECT then
    an UPDATE, which two callers at once can both win."""

    def expire(self, key):
        backend = caches["default"]
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE cache_table SET expires = %s WHERE cache_key = %s",
                [
                    connection.ops.adapt_datetimefield_value(
                        timezone.now() - timedelta(minutes=5)
                    ),
                    backend.make_and_validate_key(key),
                ],
            )

    def test_an_expired_lock_is_deleted_so_the_add_must_insert(self):
        cache.add(LOCK, "dead")
        self.expire(LOCK)
        with CaptureQueriesContext(connection) as captured:
            self.assertTrue(post_import._add(LOCK, "mine"))
        sqls = [q["sql"] for q in captured]
        self.assertTrue([sql for sql in sqls if sql.startswith("INSERT")])
        self.assertFalse([sql for sql in sqls if sql.startswith("UPDATE")])
        self.assertEqual(cache.get(LOCK), "mine")

    def test_a_live_lock_is_left_to_its_holder(self):
        cache.add(LOCK, "theirs")
        self.assertFalse(post_import._add(LOCK, "mine"))
        self.assertEqual(cache.get(LOCK), "theirs")


class HeartbeatTests(TestCase):
    def setUp(self):
        cache.delete(LOCK)
        self.addCleanup(cache.delete, LOCK)
        # Closing the test's own connection would end its transaction.
        patcher = mock.patch("core.services.post_import.connection")
        self.connection = patcher.start()
        self.addCleanup(patcher.stop)

    def test_it_holds_no_connection_between_beats(self):
        """The shared cache is a Postgres table: a held touch is a held slot."""
        stop = mock.Mock()
        stop.wait.side_effect = [False, False, True]
        with mock.patch.object(post_import.cache, "touch"):
            post_import._keep_alive(LOCK, stop)
        self.assertEqual(self.connection.close.call_count, 2)

    def test_it_touches_the_lock_until_stopped(self):
        stop = mock.Mock()
        stop.wait.side_effect = [False, False, True]
        with mock.patch.object(post_import.cache, "touch") as touch:
            post_import._keep_alive(LOCK, stop)
        self.assertEqual(
            touch.call_args_list, [mock.call(LOCK, post_import.LOCK_SECONDS)] * 2
        )
        stop.wait.assert_called_with(post_import.HEARTBEAT_SECONDS)

    def test_it_never_recreates_a_released_lock(self):
        """Renewed with a set, it could put the lock back just after release."""
        stop = mock.Mock()
        stop.wait.side_effect = [False, True]
        post_import._keep_alive(LOCK, stop)
        self.assertIsNone(cache.get(LOCK))

    def test_a_cache_error_does_not_stop_it(self):
        stop = mock.Mock()
        stop.wait.side_effect = [False, False, True]
        with mock.patch.object(
            post_import.cache, "touch", side_effect=[ConnectionError, True]
        ) as touch:
            with self.assertLogs("core.services.post_import", "ERROR"):
                post_import._keep_alive(LOCK, stop)
        self.assertEqual(touch.call_count, 2)

    def test_it_runs_on_its_own_thread(self):
        stop = threading.Event()
        with mock.patch(THREAD) as thread:
            post_import._start_heartbeat(LOCK, stop)
        target = thread.call_args.args[0]
        stop.set()
        with mock.patch.object(post_import, "_keep_alive") as keep_alive:
            target()
        keep_alive.assert_called_once_with(LOCK, stop)


class _Command(BaseCommand):
    def __init__(self):
        super().__init__(stdout=StringIO())

    def output(self):
        return self.stdout._out.getvalue()


@override_settings(METADATA_AFTER_IMPORT=True)
class RunInForegroundTests(PostImportTestCase):
    def test_the_job_writes_to_the_command_and_releases_the_lock(self):
        command = _Command()
        self.job.side_effect = lambda stdout: stdout.write("wikidata pass") or []
        post_import.run_in_foreground("test", self.job, command)
        self.assertIn("Fetching metadata", command.output())
        self.assertIn("wikidata pass", command.output())
        self.assertIsNone(cache.get(LOCK))

    def test_failed_steps_are_warnings_not_a_failure(self):
        command = _Command()
        self.job.return_value = ["fetch_hltb_data"]
        with self.assertLogs("core.services.post_import", "ERROR"):
            post_import.run_in_foreground("test", self.job, command)
        self.assertIn("fetch_hltb_data failed; see the log", command.output())

    def test_a_cache_error_is_a_warning_not_a_failed_import(self):
        command = _Command()
        with mock.patch.object(post_import.cache, "add", side_effect=ConnectionError):
            with self.assertLogs("core.services.post_import", "ERROR"):
                post_import.run_in_foreground("test", self.job, command)
        self.assertIn("The metadata fetch failed; see the log", command.output())

    def test_a_running_fetch_is_asked_to_go_again(self):
        """The command's import replaced the rows the running fetch is on."""
        command = _Command()
        cache.add(LOCK, "theirs")
        post_import.run_in_foreground("test", self.job, command)
        self.job.assert_not_called()
        self.assertTrue(cache.get(AGAIN))
        self.assertIn(post_import.ALREADY_RUNNING, command.output())

    def test_nothing_with_the_setting_off(self):
        command = _Command()
        with override_settings(METADATA_AFTER_IMPORT=False):
            post_import.run_in_foreground("test", self.job, command)
        self.job.assert_not_called()
        self.assertEqual(command.output(), "")


class LogStreamTests(TestCase):
    def test_each_line_is_logged_once_complete(self):
        log = mock.Mock()
        stream = post_import.LogStream(log)
        stream.write("wikidata pass\n  12 albums")
        log.info.assert_called_once_with("wikidata pass")
        stream.write(" processed\n\n")
        self.assertEqual(log.info.call_args.args, ("  12 albums processed",))
        self.assertEqual(log.info.call_count, 2)

    def test_flush_logs_an_unfinished_line(self):
        log = mock.Mock()
        stream = post_import.LogStream(log)
        stream.write("Done")
        stream.flush()
        stream.flush()
        log.info.assert_called_once_with("Done")

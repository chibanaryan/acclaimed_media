"""The metadata fetch an import starts once it commits."""

import threading
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.test import TestCase, override_settings

from core.services import post_import

THREAD = "core.services.post_import.start_background_thread"
HEARTBEAT = "core.services.post_import._start_heartbeat"
LOCK = post_import.lock_key("test")
AGAIN = post_import.again_key("test")


def _run_inline(target, **kwargs):
    target()


class PostImportTestCase(TestCase):
    def setUp(self):
        # Django's runner does not clear caches between tests.
        for key in (LOCK, AGAIN):
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

    def test_a_cache_error_is_not_a_failed_import(self):
        status = {}
        with mock.patch.object(post_import.cache, "add", side_effect=ConnectionError):
            with self.assertLogs("core.services.post_import", "ERROR"):
                post_import._start("test", self.job, status)
        self.assertEqual(status["message"], post_import.NOT_STARTED)


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

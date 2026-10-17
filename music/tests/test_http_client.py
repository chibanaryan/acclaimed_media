"""Tests for the shared rate-limited HTTP client.

Every music metadata client sits on this, so its retry and pacing rules are
the ones that decide whether a 500-album run finishes. Nothing here touches
the network: the session is a mock.
"""

from unittest import mock

import requests
from django.test import SimpleTestCase

from music import config
from music.services.http_client import RateLimitedClient


def fake_response(status_code=200, json_body=None, content=b"", headers=None):
    """A stand-in for a requests.Response."""
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.headers = headers or {}
    response.content = content
    if json_body is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_body
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} error"
        )
    else:
        response.raise_for_status.return_value = None
    return response


class ClientTestCase(SimpleTestCase):
    """Builds a client whose session and sleeping are both mocked out."""

    client_class = RateLimitedClient

    def build(self, **kwargs):
        with mock.patch("music.services.http_client.requests.Session") as session_cls:
            session = mock.MagicMock()
            session_cls.return_value = session
            client = self.client_class(**kwargs)
        self.addCleanup(client.close)
        # Never actually sleep in a test.
        patcher = mock.patch("music.services.http_client.time.sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)
        return client, session


class ConstructionTests(ClientTestCase):
    def test_the_user_agent_is_set_once_on_the_session(self):
        client, session = self.build()
        session.headers.update.assert_called_once_with(
            {"User-Agent": config.MUSIC_USER_AGENT}
        )

    def test_an_explicit_delay_wins_over_the_class_default(self):
        client, _ = self.build(delay=0.25)
        self.assertEqual(client.delay, 0.25)

    def test_the_class_default_is_used_when_no_delay_is_given(self):
        client, _ = self.build()
        self.assertEqual(client.delay, RateLimitedClient.default_delay)

    def test_a_custom_user_agent_is_honoured(self):
        client, session = self.build(user_agent="Probe/1.0")
        self.assertEqual(client.user_agent, "Probe/1.0")
        session.headers.update.assert_called_once_with({"User-Agent": "Probe/1.0"})

    def test_close_releases_the_session_and_is_idempotent(self):
        client, session = self.build()
        client.close()
        session.close.assert_called_once()
        self.assertIsNone(client.session)
        client.close()
        session.close.assert_called_once()

    def test_it_works_as_a_context_manager(self):
        client, session = self.build()
        with client as entered:
            self.assertIs(entered, client)
        session.close.assert_called_once()

    def test_exiting_does_not_swallow_an_exception(self):
        client, _ = self.build()
        self.assertFalse(client.__exit__(ValueError, ValueError("x"), None))


class RateLimitTests(ClientTestCase):
    def test_it_waits_out_the_remainder_of_the_delay(self):
        client, _ = self.build(delay=10.0)
        with mock.patch(
            "music.services.http_client.time.time", side_effect=[100.0, 100.0]
        ):
            client.last_request_time = 96.0
            client._wait_for_rate_limit()
        self.sleep.assert_called_once()
        self.assertAlmostEqual(self.sleep.call_args[0][0], 6.0, places=3)

    def test_it_does_not_wait_when_the_delay_has_already_passed(self):
        client, _ = self.build(delay=1.0)
        with mock.patch(
            "music.services.http_client.time.time", side_effect=[100.0, 100.0]
        ):
            client.last_request_time = 50.0
            client._wait_for_rate_limit()
        self.sleep.assert_not_called()

    def test_observe_response_is_a_no_op_by_default(self):
        client, _ = self.build()
        self.assertIsNone(client._observe_response(fake_response()))


class GetJsonTests(ClientTestCase):
    def test_a_successful_response_is_decoded(self):
        client, session = self.build()
        session.get.return_value = fake_response(json_body={"ok": True})
        self.assertEqual(client.get_json("https://example.test/"), {"ok": True})

    def test_params_and_headers_are_passed_through(self):
        client, session = self.build()
        session.get.return_value = fake_response(json_body={})
        client.get_json(
            "https://example.test/", params={"a": 1}, headers={"X-Test": "y"}
        )
        self.assertEqual(session.get.call_args.kwargs["params"], {"a": 1})
        self.assertEqual(session.get.call_args.kwargs["headers"], {"X-Test": "y"})

    def test_a_404_is_a_clean_miss(self):
        client, session = self.build()
        session.get.return_value = fake_response(status_code=404)
        self.assertIsNone(client.get_json("https://example.test/"))
        self.assertEqual(session.get.call_count, 1)

    def test_a_body_that_is_not_json_returns_none(self):
        client, session = self.build()
        session.get.return_value = fake_response(json_body=None)
        self.assertIsNone(client.get_json("https://example.test/"))

    def test_an_http_error_that_is_not_retryable_returns_none(self):
        client, session = self.build()
        session.get.return_value = fake_response(status_code=403)
        self.assertIsNone(client.get_json("https://example.test/"))
        self.assertEqual(session.get.call_count, 1)

    def test_a_transient_connection_error_is_retried_then_succeeds(self):
        # delay=0 so the only sleeps recorded are the retry backoffs.
        client, session = self.build(delay=0)
        session.get.side_effect = [
            requests.ConnectionError("boom"),
            fake_response(json_body={"ok": 1}),
        ]
        self.assertEqual(client.get_json("https://example.test/"), {"ok": 1})
        self.assertEqual(session.get.call_count, 2)
        self.sleep.assert_called_once_with(client.initial_retry_delay)

    def test_a_connection_error_that_never_clears_returns_none(self):
        client, session = self.build()
        session.get.side_effect = requests.ConnectionError("boom")
        self.assertIsNone(client.get_json("https://example.test/"))
        self.assertEqual(session.get.call_count, client.max_retries)

    def test_a_non_retryable_request_exception_is_not_retried(self):
        client, session = self.build()
        session.get.side_effect = requests.TooManyRedirects("loop")
        self.assertIsNone(client.get_json("https://example.test/"))
        self.assertEqual(session.get.call_count, 1)

    def test_a_throttle_is_retried_with_doubling_backoff(self):
        client, session = self.build(delay=0)
        session.get.side_effect = [
            fake_response(status_code=429),
            fake_response(status_code=429),
            fake_response(json_body={"ok": 1}),
        ]
        self.assertEqual(client.get_json("https://example.test/"), {"ok": 1})
        self.assertEqual(
            [call[0][0] for call in self.sleep.call_args_list],
            [client.initial_retry_delay, client.initial_retry_delay * 2],
        )

    def test_a_server_error_is_retried_too(self):
        """A 500 from the Cover Art Archive is usually transient."""
        client, session = self.build()
        session.get.side_effect = [
            fake_response(status_code=500),
            fake_response(json_body={"ok": 1}),
        ]
        self.assertEqual(client.get_json("https://example.test/"), {"ok": 1})
        self.assertEqual(session.get.call_count, 2)

    def test_a_persistent_server_error_gives_up_and_returns_none(self):
        client, session = self.build()
        session.get.return_value = fake_response(status_code=500)
        self.assertIsNone(client.get_json("https://example.test/"))
        self.assertEqual(session.get.call_count, client.max_retries)

    def test_every_retryable_status_is_retried(self):
        for status in sorted(RateLimitedClient.RETRYABLE_STATUSES):
            with self.subTest(status=status):
                client, session = self.build()
                session.get.side_effect = [
                    fake_response(status_code=status),
                    fake_response(json_body={"ok": status}),
                ]
                self.assertEqual(
                    client.get_json("https://example.test/"), {"ok": status}
                )

    def test_observe_response_sees_every_response(self):
        client, session = self.build()
        session.get.return_value = fake_response(json_body={})
        with mock.patch.object(client, "_observe_response") as observe:
            client.get_json("https://example.test/")
        observe.assert_called_once()


class GetBytesTests(ClientTestCase):
    def test_a_successful_download_returns_body_and_type(self):
        client, session = self.build()
        session.get.return_value = fake_response(
            content=b"\x89PNG", headers={"Content-Type": "image/png; charset=binary"}
        )
        self.assertEqual(
            client.get_bytes("https://example.test/x.png"), (b"\x89PNG", "image/png")
        )

    def test_the_content_type_defaults_to_jpeg(self):
        client, session = self.build()
        session.get.return_value = fake_response(content=b"\xff\xd8")
        self.assertEqual(
            client.get_bytes("https://example.test/x.jpg"), (b"\xff\xd8", "image/jpeg")
        )

    def test_an_empty_body_is_not_an_image(self):
        client, session = self.build()
        session.get.return_value = fake_response(content=b"")
        self.assertIsNone(client.get_bytes("https://example.test/x.jpg"))

    def test_a_non_200_status_returns_none(self):
        client, session = self.build()
        session.get.return_value = fake_response(status_code=404, content=b"x")
        self.assertIsNone(client.get_bytes("https://example.test/x.jpg"))

    def test_a_transient_error_is_retried(self):
        client, session = self.build()
        session.get.side_effect = [
            fake_response(status_code=500),
            fake_response(content=b"ok"),
        ]
        self.assertEqual(
            client.get_bytes("https://example.test/x.jpg"), (b"ok", "image/jpeg")
        )

    def test_a_persistent_server_error_gives_up(self):
        client, session = self.build()
        session.get.return_value = fake_response(status_code=503)
        self.assertIsNone(client.get_bytes("https://example.test/x.jpg"))
        self.assertEqual(session.get.call_count, client.max_retries)

    def test_a_connection_error_is_retried_then_abandoned(self):
        client, session = self.build()
        session.get.side_effect = requests.Timeout("slow")
        self.assertIsNone(client.get_bytes("https://example.test/x.jpg"))
        self.assertEqual(session.get.call_count, client.max_retries)

    def test_a_connection_error_that_clears_succeeds(self):
        client, session = self.build()
        session.get.side_effect = [
            requests.Timeout("slow"),
            fake_response(content=b"ok"),
        ]
        self.assertEqual(
            client.get_bytes("https://example.test/x.jpg"), (b"ok", "image/jpeg")
        )

    def test_a_non_retryable_exception_returns_none_immediately(self):
        client, session = self.build()
        session.get.side_effect = requests.TooManyRedirects("loop")
        self.assertIsNone(client.get_bytes("https://example.test/x.jpg"))
        self.assertEqual(session.get.call_count, 1)

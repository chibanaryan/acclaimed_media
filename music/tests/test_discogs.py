"""Tests for the Discogs client.

The pacing logic gets the most attention here: pacing even slightly under
Discogs' published average earns a run of 429s a few dozen requests in, which
is exactly what happened the first time this client was pointed at the real
API.
"""

from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from music import config
from music.discogs import (
    RATE_LIMIT_HEADROOM,
    RATE_LIMIT_NEARLY_SPENT,
    DiscogsClient,
    DiscogsMaster,
)


def headers_response(headers):
    response = mock.MagicMock(spec=requests.Response)
    response.headers = headers
    return response


class DiscogsClientTestCase(SimpleTestCase):
    def build(self, **kwargs):
        with mock.patch("music.services.http_client.requests.Session") as session_cls:
            self.session = mock.MagicMock()
            session_cls.return_value = self.session
            client = DiscogsClient(**kwargs)
        self.addCleanup(client.close)
        return client


@override_settings(DISCOGS_TOKEN=None)
class ConstructionTests(DiscogsClientTestCase):
    def test_without_a_token_no_authorization_header_is_sent(self):
        self.assertIsNone(self.build().token)
        header_calls = [
            call.args[0] for call in self.session.headers.update.call_args_list
        ]
        self.assertTrue(all("Authorization" not in call for call in header_calls))

    def test_the_default_delay_comes_from_config(self):
        client = self.build()
        self.assertEqual(client.delay, config.DISCOGS_REQUEST_DELAY)

    def test_an_explicit_token_is_sent_as_a_discogs_header(self):
        self.build(token="abc123")
        self.session.headers.update.assert_any_call(
            {"Authorization": "Discogs token=abc123"}
        )

    @override_settings(DISCOGS_TOKEN="from-settings")
    def test_the_token_falls_back_to_settings(self):
        client = self.build()
        self.assertEqual(client.token, "from-settings")

    def test_an_empty_token_is_treated_as_absent(self):
        self.build(token="")
        header_calls = [
            call.args[0] for call in self.session.headers.update.call_args_list
        ]
        self.assertTrue(all("Authorization" not in call for call in header_calls))


@override_settings(DISCOGS_TOKEN=None)
class PacingTests(DiscogsClientTestCase):
    def test_the_delay_is_derived_from_the_reported_limit(self):
        client = self.build()
        client._observe_response(
            headers_response(
                {"X-Discogs-Ratelimit": "25", "X-Discogs-Ratelimit-Remaining": "20"}
            )
        )
        self.assertAlmostEqual(client.delay, (60 / 25) * RATE_LIMIT_HEADROOM, places=4)

    def test_the_delay_is_never_faster_than_the_window_average(self):
        """The bug that caused a run of 429s was a headroom factor below one."""
        client = self.build()
        client._observe_response(
            headers_response(
                {"X-Discogs-Ratelimit": "25", "X-Discogs-Ratelimit-Remaining": "20"}
            )
        )
        self.assertGreaterEqual(client.delay, 60 / 25)

    def test_a_nearly_spent_window_doubles_the_delay(self):
        client = self.build()
        client._observe_response(
            headers_response(
                {
                    "X-Discogs-Ratelimit": "25",
                    "X-Discogs-Ratelimit-Remaining": str(RATE_LIMIT_NEARLY_SPENT),
                }
            )
        )
        self.assertAlmostEqual(
            client.delay, (60 / 25) * RATE_LIMIT_HEADROOM * 2, places=4
        )

    def test_a_token_tier_limit_paces_faster_but_still_safely(self):
        client = self.build()
        client._observe_response(
            headers_response(
                {"X-Discogs-Ratelimit": "60", "X-Discogs-Ratelimit-Remaining": "55"}
            )
        )
        self.assertAlmostEqual(client.delay, (60 / 60) * RATE_LIMIT_HEADROOM, places=4)
        self.assertGreaterEqual(client.delay, 1.0)

    def test_missing_headers_leave_the_delay_alone(self):
        client = self.build()
        before = client.delay
        client._observe_response(headers_response({}))
        self.assertEqual(client.delay, before)

    def test_a_nonsense_limit_leaves_the_delay_alone(self):
        client = self.build()
        before = client.delay
        client._observe_response(headers_response({"X-Discogs-Ratelimit": "nope"}))
        self.assertEqual(client.delay, before)

    def test_a_zero_limit_leaves_the_delay_alone(self):
        client = self.build()
        before = client.delay
        client._observe_response(headers_response({"X-Discogs-Ratelimit": "0"}))
        self.assertEqual(client.delay, before)

    def test_a_missing_remaining_header_still_paces(self):
        client = self.build()
        client._observe_response(headers_response({"X-Discogs-Ratelimit": "25"}))
        self.assertAlmostEqual(client.delay, (60 / 25) * RATE_LIMIT_HEADROOM, places=4)

    def test_an_unparseable_remaining_header_still_paces(self):
        client = self.build()
        client._observe_response(
            headers_response(
                {"X-Discogs-Ratelimit": "25", "X-Discogs-Ratelimit-Remaining": "x"}
            )
        )
        self.assertAlmostEqual(client.delay, (60 / 25) * RATE_LIMIT_HEADROOM, places=4)

    def test_it_is_more_patient_than_the_base_client(self):
        """A spent Discogs window refills over a rolling minute."""
        self.assertGreater(DiscogsClient.initial_retry_delay, 10)
        self.assertGreater(DiscogsClient.max_retries, 3)


@override_settings(DISCOGS_TOKEN=None)
class FetchMasterTests(DiscogsClientTestCase):
    def test_a_master_is_parsed(self):
        client = self.build()
        payload = {
            "title": "Pet Sounds",
            "year": 1966,
            "genres": ["Rock", "Pop"],
            "styles": ["Pop Rock", "Art Rock"],
        }
        with mock.patch.object(client, "get_json", return_value=payload) as get:
            master = client.fetch_master(17217)
        get.assert_called_once_with(f"{config.DISCOGS_API_URL}/masters/17217")
        self.assertEqual(
            master,
            DiscogsMaster(
                master_id=17217,
                title="Pet Sounds",
                year=1966,
                genres=["Rock", "Pop"],
                styles=["Pop Rock", "Art Rock"],
            ),
        )

    def test_a_missing_master_is_none(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=None):
            self.assertIsNone(client.fetch_master(999))

    def test_a_non_dict_payload_is_none(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=["unexpected"]):
            self.assertIsNone(client.fetch_master(999))

    def test_missing_fields_become_empty_defaults(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value={}):
            master = client.fetch_master(1)
        self.assertEqual(master.title, "")
        self.assertIsNone(master.year)
        self.assertEqual(master.genres, [])
        self.assertEqual(master.styles, [])

    def test_a_zero_or_non_integer_year_is_discarded(self):
        client = self.build()
        for year in (0, "1966", None):
            with self.subTest(year=year):
                with mock.patch.object(client, "get_json", return_value={"year": year}):
                    self.assertIsNone(client.fetch_master(1).year)

    def test_blank_genres_and_styles_are_filtered_out(self):
        client = self.build()
        payload = {"genres": ["Rock", "", None], "styles": [None, "Punk"]}
        with mock.patch.object(client, "get_json", return_value=payload):
            master = client.fetch_master(1)
        self.assertEqual(master.genres, ["Rock"])
        self.assertEqual(master.styles, ["Punk"])

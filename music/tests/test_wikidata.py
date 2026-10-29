"""Tests for the Wikidata album metadata client."""

from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from music import config
from music.wikidata import (
    AlbumMetadata,
    ArtistMetadata,
    WikidataClient,
    _claim_values,
    _entity_ids,
    _date_precision,
    _first_claim_value,
    _parse_time_value,
)


def entity_claim(value, rank="normal"):
    return {"rank": rank, "mainsnak": {"datavalue": {"value": value}}}


def time_value(timestamp, precision=11):
    return {"time": timestamp, "precision": precision}


class ClaimReadingTests(SimpleTestCase):
    def test_deprecated_claims_are_dropped(self):
        claims = {"P1": [entity_claim("keep"), entity_claim("drop", "deprecated")]}
        self.assertEqual(_claim_values(claims, "P1"), ["keep"])

    def test_preferred_claims_sort_first(self):
        claims = {
            "P1": [entity_claim("normal"), entity_claim("best", "preferred")],
        }
        self.assertEqual(_claim_values(claims, "P1"), ["best", "normal"])

    def test_a_claim_with_no_datavalue_is_skipped(self):
        claims = {"P1": [{"rank": "normal", "mainsnak": {}}, entity_claim("ok")]}
        self.assertEqual(_claim_values(claims, "P1"), ["ok"])

    def test_a_missing_property_yields_nothing(self):
        self.assertEqual(_claim_values({}, "P1"), [])
        self.assertIsNone(_first_claim_value({}, "P1"))

    def test_first_claim_value_takes_the_best_ranked(self):
        claims = {"P1": [entity_claim("a"), entity_claim("b", "preferred")]}
        self.assertEqual(_first_claim_value(claims, "P1"), "b")

    def test_entity_ids_reads_only_entity_shaped_values(self):
        claims = {
            "P1": [
                entity_claim({"id": "Q1"}),
                entity_claim("a plain string"),
                entity_claim({"no-id": True}),
                entity_claim({"id": "Q2"}),
            ]
        }
        self.assertEqual(_entity_ids(claims, "P1"), ["Q1", "Q2"])


class TimeParsingTests(SimpleTestCase):
    def test_a_day_precision_date_is_parsed(self):
        self.assertEqual(
            _parse_time_value(time_value("+1966-05-16T00:00:00Z")), date(1966, 5, 16)
        )

    def test_a_month_precision_date_becomes_the_first(self):
        self.assertEqual(
            _parse_time_value(time_value("+1966-05-00T00:00:00Z", 10)),
            date(1966, 5, 1),
        )

    def test_a_year_precision_date_is_rejected(self):
        """Album.year_released already holds the year, so this adds nothing."""
        self.assertIsNone(_parse_time_value(time_value("+1966-00-00T00:00:00Z", 9)))

    def test_a_zero_day_at_day_precision_becomes_the_first(self):
        self.assertEqual(
            _parse_time_value(time_value("+1966-05-00T00:00:00Z", 11)),
            date(1966, 5, 1),
        )

    def test_a_zero_month_is_rejected(self):
        self.assertIsNone(_parse_time_value(time_value("+1966-00-01T00:00:00Z", 11)))

    def test_a_zero_year_is_rejected(self):
        self.assertIsNone(_parse_time_value(time_value("+0000-01-01T00:00:00Z", 11)))

    def test_a_non_dict_value_is_rejected(self):
        self.assertIsNone(_parse_time_value("1966"))
        self.assertIsNone(_parse_time_value(None))

    def test_a_malformed_timestamp_is_rejected(self):
        self.assertIsNone(_parse_time_value(time_value("+1966")))

    def test_a_non_numeric_timestamp_is_rejected(self):
        self.assertIsNone(_parse_time_value(time_value("+aaaa-bb-ccT00:00:00Z")))


class DatePrecisionTests(SimpleTestCase):
    """What the parsed date can be trusted to: a day is only shown if "day"."""

    def test_a_day(self):
        self.assertEqual(_date_precision(time_value("+1966-05-16T00:00:00Z")), "day")

    def test_a_month(self):
        self.assertEqual(
            _date_precision(time_value("+1966-05-00T00:00:00Z", 10)), "month"
        )

    def test_a_zero_day_at_day_precision_is_a_month(self):
        self.assertEqual(
            _date_precision(time_value("+1966-05-00T00:00:00Z", 11)), "month"
        )

    def test_nothing_parsed_has_no_precision(self):
        self.assertEqual(_date_precision(time_value("+1966-00-00T00:00:00Z", 9)), "")
        self.assertEqual(_date_precision(None), "")

    def test_an_impossible_date_is_rejected(self):
        self.assertIsNone(_parse_time_value(time_value("+1966-02-31T00:00:00Z")))


class WikidataClientTestCase(SimpleTestCase):
    def build(self):
        with mock.patch("music.services.http_client.requests.Session") as session_cls:
            session_cls.return_value = mock.MagicMock()
            client = WikidataClient(delay=0)
        self.addCleanup(client.close)
        return client


class FetchEntitiesTests(WikidataClientTestCase):
    def test_ids_are_batched_and_deduplicated(self):
        client = self.build()
        qids = [f"Q{i}" for i in range(120)] + ["Q0"]
        with mock.patch.object(
            client, "get_json", return_value={"entities": {}}
        ) as get:
            client.fetch_entities(qids)
        self.assertEqual(get.call_count, 3)
        sent = [call.kwargs["params"]["ids"].split("|") for call in get.call_args_list]
        self.assertEqual([len(batch) for batch in sent], [50, 50, 20])

    def test_entities_from_every_batch_are_merged(self):
        client = self.build()
        with mock.patch.object(
            client,
            "get_json",
            side_effect=[
                {"entities": {"Q1": {"a": 1}}},
                {"entities": {"Q2": {"b": 2}}},
            ],
        ):
            result = client.fetch_entities([f"Q{i}" for i in range(60)])
        self.assertEqual(set(result), {"Q1", "Q2"})

    def test_a_failed_batch_is_skipped_not_fatal(self):
        client = self.build()
        with mock.patch.object(
            client, "get_json", side_effect=[None, {"entities": {"Q2": {}}}]
        ):
            result = client.fetch_entities([f"Q{i}" for i in range(60)])
        self.assertEqual(set(result), {"Q2"})

    def test_a_payload_without_entities_is_skipped(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value={"error": "nope"}):
            self.assertEqual(client.fetch_entities(["Q1"]), {})

    def test_extra_params_are_merged_in(self):
        client = self.build()
        with mock.patch.object(
            client, "get_json", return_value={"entities": {}}
        ) as get:
            client.fetch_entities(
                ["Q1"], props="claims|sitelinks", extra_params={"sitefilter": "enwiki"}
            )
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["props"], "claims|sitelinks")
        self.assertEqual(params["sitefilter"], "enwiki")
        self.assertEqual(params["format"], "json")

    def test_no_ids_means_no_requests(self):
        client = self.build()
        with mock.patch.object(client, "get_json") as get:
            self.assertEqual(client.fetch_entities([]), {})
        get.assert_not_called()


class FetchAlbumMetadataTests(WikidataClientTestCase):
    def full_entity(self):
        return {
            "claims": {
                config.WIKIDATA_PERFORMER_PROPERTY: [entity_claim({"id": "Q1299"})],
                config.WIKIDATA_GENRE_PROPERTY: [
                    entity_claim({"id": "Q11399"}),
                    entity_claim({"id": "Q3071"}),
                ],
                config.WIKIDATA_RELEASE_DATE_PROPERTY: [
                    entity_claim(time_value("+1969-09-26T00:00:00Z"))
                ],
                config.WIKIDATA_LABEL_PROPERTY: [entity_claim({"id": "Q213710"})],
                config.WIKIDATA_MUSICBRAINZ_RELEASE_GROUP_PROPERTY: [
                    entity_claim("9162580e-5df4-32de-80cc-f45a8d8a9b1d")
                ],
                config.WIKIDATA_DISCOGS_MASTER_PROPERTY: [entity_claim("24047")],
                config.WIKIDATA_SPOTIFY_PROPERTY: [entity_claim("0ETFjACtuP2ADo6")],
            },
            "sitelinks": {"enwiki": {"title": "Abbey Road"}},
        }

    def test_every_property_is_read(self):
        client = self.build()
        with mock.patch.object(
            client, "fetch_entities", return_value={"Q173643": self.full_entity()}
        ):
            result = client.fetch_album_metadata(["Q173643"])

        meta = result["Q173643"]
        self.assertEqual(meta.page_title, "Abbey Road")
        self.assertEqual(meta.release_date, date(1969, 9, 26))
        self.assertEqual(meta.release_date_precision, "day")
        self.assertEqual(meta.record_label_qid, "Q213710")
        self.assertEqual(meta.spotify_album_id, "0ETFjACtuP2ADo6")
        self.assertEqual(
            meta.musicbrainz_release_group_id, "9162580e-5df4-32de-80cc-f45a8d8a9b1d"
        )
        self.assertEqual(meta.discogs_master_id, 24047)
        self.assertEqual(meta.performer_qids, ["Q1299"])
        self.assertEqual(meta.genre_qids, ["Q11399", "Q3071"])

    def test_an_empty_entity_yields_empty_metadata(self):
        client = self.build()
        with mock.patch.object(client, "fetch_entities", return_value={"Q1": {}}):
            meta = client.fetch_album_metadata(["Q1"])["Q1"]
        self.assertEqual(meta.page_title, "")
        self.assertIsNone(meta.release_date)
        self.assertEqual(meta.release_date_precision, "")
        self.assertIsNone(meta.discogs_master_id)
        self.assertEqual(meta.performer_qids, [])

    def test_a_missing_entity_is_skipped(self):
        client = self.build()
        with mock.patch.object(
            client, "fetch_entities", return_value={"Q1": {"missing": ""}}
        ):
            self.assertEqual(client.fetch_album_metadata(["Q1"]), {})

    def test_a_non_numeric_discogs_id_is_discarded(self):
        client = self.build()
        entity = {
            "claims": {
                config.WIKIDATA_DISCOGS_MASTER_PROPERTY: [entity_claim("not-a-number")]
            }
        }
        with mock.patch.object(client, "fetch_entities", return_value={"Q1": entity}):
            self.assertIsNone(
                client.fetch_album_metadata(["Q1"])["Q1"].discogs_master_id
            )

    def test_the_sitefilter_is_requested(self):
        client = self.build()
        with mock.patch.object(client, "fetch_entities", return_value={}) as fetch:
            client.fetch_album_metadata(["Q1"])
        self.assertEqual(fetch.call_args.kwargs["props"], "claims|sitelinks")
        self.assertEqual(
            fetch.call_args.kwargs["extra_params"], {"sitefilter": "enwiki"}
        )


class FetchLabelsTests(WikidataClientTestCase):
    def test_english_labels_are_returned(self):
        client = self.build()
        entities = {"Q11399": {"labels": {"en": {"value": "rock music"}}}}
        with mock.patch.object(client, "fetch_entities", return_value=entities):
            self.assertEqual(client.fetch_labels(["Q11399"]), {"Q11399": "rock music"})

    def test_an_entity_with_no_english_label_is_omitted(self):
        """Q3071 (punk rock) genuinely has no English label."""
        client = self.build()
        entities = {
            "Q3071": {"labels": {"de": {"value": "Punk"}}},
            "Q9759": {"labels": {"en": {"value": "blues"}}},
        }
        with mock.patch.object(client, "fetch_entities", return_value=entities):
            self.assertEqual(
                client.fetch_labels(["Q3071", "Q9759"]), {"Q9759": "blues"}
            )

    def test_a_null_english_label_is_omitted(self):
        client = self.build()
        with mock.patch.object(
            client, "fetch_entities", return_value={"Q1": {"labels": {"en": None}}}
        ):
            self.assertEqual(client.fetch_labels(["Q1"]), {})


class FetchArtistsTests(WikidataClientTestCase):
    def test_a_name_and_musicbrainz_id_are_read(self):
        client = self.build()
        entities = {
            "Q1299": {
                "labels": {"en": {"value": "The Beatles"}},
                "claims": {
                    config.WIKIDATA_ARTIST_MUSICBRAINZ_PROPERTY: [
                        entity_claim("b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d")
                    ]
                },
            }
        }
        with mock.patch.object(client, "fetch_entities", return_value=entities):
            artists = client.fetch_artists(["Q1299"])
        self.assertEqual(
            artists["Q1299"],
            ArtistMetadata(
                wikidata_id="Q1299",
                name="The Beatles",
                musicbrainz_id="b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d",
            ),
        )

    def test_the_english_wikipedia_title_is_read_from_the_sitelink(self):
        client = self.build()
        entities = {
            "Q11649": {
                "labels": {"en": {"value": "Nirvana"}},
                "claims": {},
                "sitelinks": {"enwiki": {"title": "Nirvana (band)"}},
            }
        }
        with mock.patch.object(
            client, "fetch_entities", return_value=entities
        ) as fetch:
            artist = client.fetch_artists(["Q11649"])["Q11649"]
        self.assertEqual(artist.wikipedia_title, "Nirvana (band)")
        self.assertIn("sitelinks", fetch.call_args.kwargs["props"])
        self.assertEqual(
            fetch.call_args.kwargs["extra_params"], {"sitefilter": "enwiki"}
        )

    def test_an_artist_without_a_musicbrainz_id_still_resolves(self):
        client = self.build()
        entities = {"Q1": {"labels": {"en": {"value": "Someone"}}, "claims": {}}}
        with mock.patch.object(client, "fetch_entities", return_value=entities):
            artist = client.fetch_artists(["Q1"])["Q1"]
        self.assertEqual(artist.name, "Someone")
        self.assertIsNone(artist.musicbrainz_id)

    def test_an_artist_with_no_english_label_is_skipped(self):
        client = self.build()
        with mock.patch.object(
            client, "fetch_entities", return_value={"Q1": {"labels": {}}}
        ):
            self.assertEqual(client.fetch_artists(["Q1"]), {})


class DataclassTests(SimpleTestCase):
    def test_album_metadata_defaults_are_independent_lists(self):
        first = AlbumMetadata(wikidata_id="Q1")
        second = AlbumMetadata(wikidata_id="Q2")
        first.performer_qids.append("Q9")
        self.assertEqual(second.performer_qids, [])

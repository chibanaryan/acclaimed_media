"""Tests for the MusicBrainz and Cover Art Archive clients."""

from unittest import mock

from django.test import SimpleTestCase

from music import config
from music.musicbrainz import (
    MIN_SEARCH_SCORE,
    CoverArt,
    CoverArtArchiveClient,
    MusicBrainzClient,
)

RG_MBID = "fdd96703-7b21-365e-bdea-38029fbeb84e"
RELEASE_MBID = "f04cce33-b9a0-4bed-af11-f84d649652b2"


class ClientTestCase(SimpleTestCase):
    client_class = MusicBrainzClient

    def build(self):
        with mock.patch("music.services.http_client.requests.Session") as session_cls:
            session_cls.return_value = mock.MagicMock()
            client = self.client_class(delay=0)
        self.addCleanup(client.close)
        return client


class ReleaseGroupTests(ClientTestCase):
    def payload(self):
        return {
            "title": "Pet Sounds",
            "primary-type": "Album",
            "secondary-types": ["Compilation"],
            "first-release-date": "1966-05-16",
            "rating": {"value": 4.3, "votes-count": 39},
            "genres": [
                {"name": "pop", "count": 7},
                {"name": "baroque pop", "count": 5},
                {"name": "rock", "count": 4},
            ],
            "artist-credit": [
                {
                    "name": "The Velvet Underground",
                    "joinphrase": " & ",
                    "artist": {"id": "abc"},
                },
                {"name": "Nico", "joinphrase": "", "artist": {"id": "def"}},
            ],
        }

    def test_a_release_group_is_parsed(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=self.payload()) as get:
            group = client.fetch_release_group(RG_MBID)
        self.assertEqual(
            get.call_args.args[0],
            f"{config.MUSICBRAINZ_API_URL}/release-group/{RG_MBID}",
        )
        self.assertEqual(group.title, "Pet Sounds")
        self.assertEqual(group.primary_type, "Album")
        self.assertEqual(group.secondary_types, ["Compilation"])
        self.assertEqual(group.first_release_date, "1966-05-16")
        self.assertEqual(group.rating, 4.3)
        self.assertEqual(group.rating_votes, 39)

    def test_genres_come_back_most_voted_first(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=self.payload()):
            group = client.fetch_release_group(RG_MBID)
        self.assertEqual(group.genres, ["pop", "baroque pop", "rock"])

    def test_join_phrases_are_preserved(self):
        """The join phrase is the authoritative credit separator."""
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=self.payload()):
            group = client.fetch_release_group(RG_MBID)
        self.assertEqual(
            group.artist_credit,
            [
                {
                    "name": "The Velvet Underground",
                    "joinphrase": " & ",
                    "artist_mbid": "abc",
                },
                {"name": "Nico", "joinphrase": "", "artist_mbid": "def"},
            ],
        )

    def test_a_genre_with_no_name_is_skipped(self):
        client = self.build()
        payload = {"genres": [{"count": 3}, {"name": "jazz", "count": 1}]}
        with mock.patch.object(client, "get_json", return_value=payload):
            self.assertEqual(client.fetch_release_group(RG_MBID).genres, ["jazz"])

    def test_a_genre_with_no_count_sorts_last(self):
        client = self.build()
        payload = {"genres": [{"name": "a"}, {"name": "b", "count": 2}]}
        with mock.patch.object(client, "get_json", return_value=payload):
            self.assertEqual(client.fetch_release_group(RG_MBID).genres, ["b", "a"])

    def test_an_empty_payload_yields_empty_defaults(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value={}):
            group = client.fetch_release_group(RG_MBID)
        self.assertEqual(group.title, "")
        self.assertIsNone(group.rating)
        self.assertEqual(group.genres, [])
        self.assertEqual(group.artist_credit, [])

    def test_a_missing_release_group_is_none(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=None):
            self.assertIsNone(client.fetch_release_group(RG_MBID))

    def test_an_artist_credit_entry_without_an_artist_is_tolerated(self):
        client = self.build()
        payload = {"artist-credit": [{"name": "Someone"}]}
        with mock.patch.object(client, "get_json", return_value=payload):
            credit = client.fetch_release_group(RG_MBID).artist_credit
        self.assertEqual(
            credit, [{"name": "Someone", "joinphrase": "", "artist_mbid": ""}]
        )


class BrowseReleasesTests(ClientTestCase):
    def test_releases_are_returned_earliest_first(self):
        client = self.build()
        payload = {
            "releases": [
                {"id": "later", "date": "1990"},
                {"id": "earliest", "date": "1966-05-16"},
                {"id": "middle", "date": "1972"},
            ]
        }
        with mock.patch.object(client, "get_json", return_value=payload):
            self.assertEqual(
                client.browse_release_mbids(RG_MBID), ["earliest", "middle", "later"]
            )

    def test_an_undated_release_sorts_last(self):
        client = self.build()
        payload = {"releases": [{"id": "undated"}, {"id": "dated", "date": "1980"}]}
        with mock.patch.object(client, "get_json", return_value=payload):
            self.assertEqual(client.browse_release_mbids(RG_MBID), ["dated", "undated"])

    def test_a_release_without_an_id_is_skipped(self):
        client = self.build()
        payload = {"releases": [{"date": "1980"}, {"id": "ok", "date": "1981"}]}
        with mock.patch.object(client, "get_json", return_value=payload):
            self.assertEqual(client.browse_release_mbids(RG_MBID), ["ok"])

    def test_a_failed_request_yields_no_releases(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=None):
            self.assertEqual(client.browse_release_mbids(RG_MBID), [])

    def test_the_release_group_is_passed_as_a_filter(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value={}) as get:
            client.browse_release_mbids(RG_MBID)
        self.assertEqual(get.call_args.kwargs["params"]["release-group"], RG_MBID)


class SearchReleaseGroupTests(ClientTestCase):
    def test_an_album_is_preferred_over_a_single_of_the_same_name(self):
        client = self.build()
        payload = {
            "release-groups": [
                {
                    "id": "single-id",
                    "score": 100,
                    "primary-type": "Single",
                    "first-release-date": "1967-02-10",
                },
                {
                    "id": "album-id",
                    "score": 100,
                    "primary-type": "Album",
                    "first-release-date": "1967-03-10",
                },
            ]
        }
        with mock.patch.object(client, "get_json", return_value=payload):
            self.assertEqual(
                client.search_release_group("I Never Loved a Man", "Aretha Franklin"),
                "album-id",
            )

    def test_the_closest_year_wins_among_albums(self):
        client = self.build()
        payload = {
            "release-groups": [
                {
                    "id": "far",
                    "score": 100,
                    "primary-type": "Album",
                    "first-release-date": "1980",
                },
                {
                    "id": "near",
                    "score": 100,
                    "primary-type": "Album",
                    "first-release-date": "1967",
                },
            ]
        }
        with mock.patch.object(client, "get_json", return_value=payload):
            self.assertEqual(client.search_release_group("X", "Y", year=1967), "near")

    def test_a_higher_score_breaks_a_remaining_tie(self):
        client = self.build()
        payload = {
            "release-groups": [
                {"id": "low", "score": 92, "primary-type": "Album"},
                {"id": "high", "score": 99, "primary-type": "Album"},
            ]
        }
        with mock.patch.object(client, "get_json", return_value=payload):
            self.assertEqual(client.search_release_group("X"), "high")

    def test_a_low_scoring_match_is_rejected(self):
        client = self.build()
        payload = {"release-groups": [{"id": "weak", "score": MIN_SEARCH_SCORE - 1}]}
        with mock.patch.object(client, "get_json", return_value=payload):
            self.assertIsNone(client.search_release_group("X"))

    def test_a_candidate_without_an_id_is_rejected(self):
        client = self.build()
        with mock.patch.object(
            client, "get_json", return_value={"release-groups": [{"score": 100}]}
        ):
            self.assertIsNone(client.search_release_group("X"))

    def test_no_results_is_none(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value={"release-groups": []}):
            self.assertIsNone(client.search_release_group("X"))

    def test_a_failed_request_is_none(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=None):
            self.assertIsNone(client.search_release_group("X"))

    def test_an_empty_title_makes_no_request(self):
        client = self.build()
        with mock.patch.object(client, "get_json") as get:
            self.assertIsNone(client.search_release_group(""))
        get.assert_not_called()

    def test_the_artist_term_is_omitted_when_unknown(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value={}) as get:
            client.search_release_group("Kid A")
        self.assertEqual(get.call_args.kwargs["params"]["query"], 'release:"Kid A"')

    def test_lucene_syntax_in_a_title_is_escaped(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value={}) as get:
            client.search_release_group('Title (with) "quotes" + more')
        query = get.call_args.kwargs["params"]["query"]
        self.assertIn("\\(", query)
        self.assertIn('\\"', query)
        self.assertIn("\\+", query)

    def test_a_non_numeric_date_does_not_break_year_preference(self):
        client = self.build()
        payload = {
            "release-groups": [
                {
                    "id": "a",
                    "score": 100,
                    "primary-type": "Album",
                    "first-release-date": "unknown",
                }
            ]
        }
        with mock.patch.object(client, "get_json", return_value=payload):
            self.assertEqual(client.search_release_group("X", year=1970), "a")


class CoverArtArchiveTests(ClientTestCase):
    client_class = CoverArtArchiveClient

    def listing(self, front=True, image_id="25254108559"):
        url = f"http://coverartarchive.org/release/{RELEASE_MBID}/{image_id}.jpg"
        return {"images": [{"id": image_id, "front": front, "image": url}]}

    def test_the_front_cover_is_found(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=self.listing()) as get:
            art = client.fetch_front_cover(RG_MBID)
        self.assertEqual(
            get.call_args.args[0],
            f"{config.COVER_ART_ARCHIVE_URL}/release-group/{RG_MBID}",
        )
        self.assertEqual(
            art, CoverArt(release_mbid=RELEASE_MBID, image_id="25254108559")
        )

    def test_a_listing_with_no_front_image_is_rejected(self):
        """Having images is not the same as having a front cover."""
        client = self.build()
        with mock.patch.object(
            client, "get_json", return_value=self.listing(front=False)
        ):
            self.assertIsNone(client.fetch_front_cover(RG_MBID))

    def test_an_empty_listing_is_none(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value={"images": []}):
            self.assertIsNone(client.fetch_front_cover(RG_MBID))

    def test_a_failed_request_is_none(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=None):
            self.assertIsNone(client.fetch_front_cover(RG_MBID))

    def test_a_non_dict_payload_is_none(self):
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=[]):
            self.assertIsNone(client.fetch_front_cover(RG_MBID))

    def test_an_image_without_an_id_is_rejected(self):
        client = self.build()
        listing = {
            "images": [
                {"front": True, "image": f"http://x/release/{RELEASE_MBID}/1.jpg"}
            ]
        }
        with mock.patch.object(client, "get_json", return_value=listing):
            self.assertIsNone(client.fetch_front_cover(RG_MBID))

    def test_an_image_url_without_a_release_segment_is_rejected(self):
        client = self.build()
        listing = {
            "images": [{"id": "1", "front": True, "image": "http://x/other/1.jpg"}]
        }
        with mock.patch.object(client, "get_json", return_value=listing):
            self.assertIsNone(client.fetch_front_cover(RG_MBID))

    def test_an_image_with_no_url_is_rejected(self):
        client = self.build()
        listing = {"images": [{"id": "1", "front": True}]}
        with mock.patch.object(client, "get_json", return_value=listing):
            self.assertIsNone(client.fetch_front_cover(RG_MBID))

    def test_an_empty_release_mbid_in_the_url_is_rejected(self):
        client = self.build()
        listing = {
            "images": [{"id": "1", "front": True, "image": "http://x/release//1.jpg"}]
        }
        with mock.patch.object(client, "get_json", return_value=listing):
            self.assertIsNone(client.fetch_front_cover(RG_MBID))

    def test_the_release_level_endpoint_is_also_supported(self):
        """The fallback for release groups the archive errors on."""
        client = self.build()
        with mock.patch.object(client, "get_json", return_value=self.listing()) as get:
            art = client.fetch_release_front_cover(RELEASE_MBID)
        self.assertEqual(
            get.call_args.args[0],
            f"{config.COVER_ART_ARCHIVE_URL}/release/{RELEASE_MBID}",
        )
        self.assertEqual(art.image_id, "25254108559")

    def test_an_integer_image_id_becomes_a_string(self):
        client = self.build()
        listing = {
            "images": [
                {
                    "id": 12345,
                    "front": True,
                    "image": f"http://x/release/{RELEASE_MBID}/12345.jpg",
                }
            ]
        }
        with mock.patch.object(client, "get_json", return_value=listing):
            self.assertEqual(client.fetch_front_cover(RG_MBID).image_id, "12345")

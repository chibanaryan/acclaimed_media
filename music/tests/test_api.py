"""Tests for the music API.

Every endpoint is staff-only. These tests use the ordinary Django test client
with a session login rather than DRF's ``force_authenticate``, because
session authentication is exactly what the mixin exists to make work: the
project sets ``DEFAULT_AUTHENTICATION_CLASSES`` to an empty list, so a view
that does not name an authenticator sees a logged-in staff member as
anonymous and 404s.
"""

import json

from django.test import TestCase
from django.urls import reverse

from core import constants as core_constants
from core.models import User
from music import models


class MusicAPITestMixin:
    def setUp(self):
        super().setUp()
        self.staff_user = User.objects.create_user(
            username="apistaff", password="apipass", is_staff=True
        )
        self.client.login(username="apistaff", password="apipass")

        self.artist = models.Artist.objects.create(
            name="Radiohead", slug="radiohead", wikidata_id="Q4075"
        )
        self.genre = models.MusicGenre.objects.create(name="Rock")
        self.child_genre = models.MusicGenre.objects.create(
            name="Art Rock", parent=self.genre
        )

        self.kid_a = models.Album.objects.create(
            name="Kid A",
            rank=1,
            artist_credit="Radiohead",
            year_released=2000,
            wikidata_id="Q202698",
        )
        self.kid_a.artists.set([self.artist])
        self.kid_a.genres.set([self.genre])

        self.ok_computer = models.Album.objects.create(
            name="OK Computer",
            rank=2,
            artist_credit="Radiohead",
            year_released=1997,
        )
        self.ok_computer.artists.set([self.artist])

        self.publication = models.MusicPublication.objects.create(name="Pitchfork")
        self.source = models.MusicList.objects.create(
            name="The Best Albums of the 1990s",
            year=2022,
            publisher=self.publication,
            order=1,
            type=core_constants.LIST_DECADE,
        )
        models.AlbumListMembership.objects.create(
            list=self.source, album=self.kid_a, rank=3
        )

    def payload(self, path, **params):
        response = self.client.get(path, params)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)


class AlbumListAPITests(MusicAPITestMixin, TestCase):
    def test_lists_albums_in_rank_order(self):
        data = self.payload(reverse("music-api:album-list"))
        self.assertEqual([a["rank"] for a in data["results"]], [1, 2])

    def test_anonymous_gets_404(self):
        self.client.logout()
        response = self.client.get(reverse("music-api:album-list"))
        self.assertEqual(response.status_code, 404)

    def test_non_staff_gets_404(self):
        User.objects.create_user(username="plain", password="plainpass")
        self.client.login(username="plain", password="plainpass")
        response = self.client.get(reverse("music-api:album-list"))
        self.assertEqual(response.status_code, 404)

    def test_search_matches_title_or_credit(self):
        data = self.payload(reverse("music-api:album-list"), q="kid")
        self.assertEqual([a["name"] for a in data["results"]], ["Kid A"])
        data = self.payload(reverse("music-api:album-list"), q="radiohead")
        self.assertEqual(len(data["results"]), 2)

    def test_artist_slug_filter(self):
        data = self.payload(reverse("music-api:album-list"), artist="radiohead")
        self.assertEqual(len(data["results"]), 2)
        data = self.payload(reverse("music-api:album-list"), artist="nobody")
        self.assertEqual(len(data["results"]), 0)

    def test_genre_filter(self):
        data = self.payload(reverse("music-api:album-list"), genres=str(self.genre.id))
        self.assertEqual([a["name"] for a in data["results"]], ["Kid A"])

    def test_a_non_numeric_genre_filter_is_ignored(self):
        data = self.payload(reverse("music-api:album-list"), genres="abc")
        self.assertEqual(len(data["results"]), 2)

    def test_year_range_filter(self):
        data = self.payload(reverse("music-api:album-list"), start="1999", end="2001")
        self.assertEqual([a["name"] for a in data["results"]], ["Kid A"])

    def test_a_non_numeric_year_filter_is_ignored(self):
        data = self.payload(reverse("music-api:album-list"), start="x", end="y")
        self.assertEqual(len(data["results"]), 2)

    def test_the_summary_payload_carries_the_expected_fields(self):
        data = self.payload(reverse("music-api:album-list"))
        album = data["results"][0]
        for field in [
            "id",
            "name",
            "slug",
            "rank",
            "year_rank",
            "decade_rank",
            "year_released",
            "artist_credit",
            "artists",
            "genres",
            "cover_image_url",
            "wikidata_id",
            "musicbrainz_release_group_id",
            "list_count",
        ]:
            self.assertIn(field, album)
        self.assertEqual(album["artists"][0]["slug"], "radiohead")
        self.assertEqual(album["list_count"], 1)

    def test_list_count_is_zero_for_an_album_on_no_lists(self):
        data = self.payload(reverse("music-api:album-list"))
        by_name = {a["name"]: a for a in data["results"]}
        self.assertEqual(by_name["OK Computer"]["list_count"], 0)


class AlbumDetailAPITests(MusicAPITestMixin, TestCase):
    def test_returns_the_album_with_its_list_appearances(self):
        data = self.payload(reverse("music-api:album-detail", kwargs={"slug": "kid-a"}))
        self.assertEqual(data["name"], "Kid A")
        self.assertEqual(data["list_count"], 1)
        self.assertEqual(len(data["lists"]), 1)
        entry = data["lists"][0]
        self.assertEqual(entry["name"], "The Best Albums of the 1990s")
        self.assertEqual(entry["publication"], "Pitchfork")
        self.assertEqual(entry["type"], core_constants.LIST_DECADE)
        self.assertEqual(entry["year"], 2022)
        self.assertEqual(entry["rank"], 3)

    def test_includes_the_description_field(self):
        data = self.payload(reverse("music-api:album-detail", kwargs={"slug": "kid-a"}))
        self.assertIn("description", data)

    def test_anonymous_gets_404(self):
        self.client.logout()
        response = self.client.get(
            reverse("music-api:album-detail", kwargs={"slug": "kid-a"})
        )
        self.assertEqual(response.status_code, 404)

    def test_a_staff_response_is_not_replayed_to_anonymous_callers(self):
        # cache_page wraps dispatch and would be consulted before permissions
        # run, so these endpoints must stay uncached.
        self.payload(reverse("music-api:album-detail", kwargs={"slug": "kid-a"}))
        self.client.logout()
        response = self.client.get(
            reverse("music-api:album-detail", kwargs={"slug": "kid-a"})
        )
        self.assertEqual(response.status_code, 404)

    def test_unknown_slug_is_404(self):
        response = self.client.get(
            reverse("music-api:album-detail", kwargs={"slug": "nope"})
        )
        self.assertEqual(response.status_code, 404)


class AlbumSearchAPITests(MusicAPITestMixin, TestCase):
    def test_returns_matching_albums_unpaginated(self):
        data = self.payload(reverse("music-api:album-search"), q="kid")
        self.assertIsInstance(data, list)
        self.assertEqual([a["name"] for a in data], ["Kid A"])

    def test_matches_the_artist_credit(self):
        data = self.payload(reverse("music-api:album-search"), q="radiohead")
        self.assertEqual(len(data), 2)

    def test_no_query_returns_an_empty_list(self):
        data = self.payload(reverse("music-api:album-search"))
        self.assertEqual(data, [])

    def test_anonymous_gets_404(self):
        self.client.logout()
        response = self.client.get(reverse("music-api:album-search"), {"q": "kid"})
        self.assertEqual(response.status_code, 404)


class ArtistAPITests(MusicAPITestMixin, TestCase):
    def test_lists_artists_with_album_counts(self):
        data = self.payload(reverse("music-api:artist-list"))
        self.assertEqual(data["results"][0]["name"], "Radiohead")
        self.assertEqual(data["results"][0]["albums_count"], 2)

    def test_excludes_artists_with_no_albums(self):
        models.Artist.objects.create(name="Nobody", slug="nobody")
        data = self.payload(reverse("music-api:artist-list"))
        self.assertEqual([a["name"] for a in data["results"]], ["Radiohead"])

    def test_search_filters_by_name(self):
        data = self.payload(reverse("music-api:artist-list"), q="radio")
        self.assertEqual(len(data["results"]), 1)
        data = self.payload(reverse("music-api:artist-list"), q="zzz")
        self.assertEqual(len(data["results"]), 0)

    def test_detail_includes_the_artist_albums(self):
        data = self.payload(
            reverse("music-api:artist-detail", kwargs={"slug": "radiohead"})
        )
        self.assertEqual(data["name"], "Radiohead")
        self.assertEqual(data["wikidata_id"], "Q4075")
        self.assertEqual(data["albums_count"], 2)
        self.assertEqual([a["rank"] for a in data["albums"]], [1, 2])

    def test_detail_unknown_slug_is_404(self):
        response = self.client.get(
            reverse("music-api:artist-detail", kwargs={"slug": "nope"})
        )
        self.assertEqual(response.status_code, 404)

    def test_anonymous_gets_404_on_both_endpoints(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse("music-api:artist-list")).status_code, 404
        )
        self.assertEqual(
            self.client.get(
                reverse("music-api:artist-detail", kwargs={"slug": "radiohead"})
            ).status_code,
            404,
        )

    def test_albums_count_falls_back_to_a_count_without_the_annotation(self):
        from music.api.serializers import ArtistSerializer

        artist = models.Artist.objects.get(slug="radiohead")
        self.assertEqual(ArtistSerializer(artist).data["albums_count"], 2)


class MusicListAPITests(MusicAPITestMixin, TestCase):
    def test_lists_sources_in_order(self):
        data = self.payload(reverse("music-api:musiclist-list"))
        self.assertEqual(data["results"][0]["name"], "The Best Albums of the 1990s")
        self.assertEqual(data["results"][0]["publication"], "Pitchfork")
        self.assertEqual(data["results"][0]["order"], 1)

    def test_type_filter(self):
        data = self.payload(
            reverse("music-api:musiclist-list"), type=core_constants.LIST_DECADE
        )
        self.assertEqual(len(data["results"]), 1)
        data = self.payload(
            reverse("music-api:musiclist-list"), type=core_constants.LIST_ALLTIME
        )
        self.assertEqual(len(data["results"]), 0)

    def test_an_unknown_type_filter_is_ignored(self):
        data = self.payload(reverse("music-api:musiclist-list"), type="Z")
        self.assertEqual(len(data["results"]), 1)

    def test_a_list_without_a_publisher_serializes(self):
        models.MusicList.objects.create(name="Unattributed", year=2001, order=2)
        data = self.payload(reverse("music-api:musiclist-list"))
        by_name = {entry["name"]: entry for entry in data["results"]}
        self.assertEqual(by_name["Unattributed"]["publication"], "")

    def test_anonymous_gets_404(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse("music-api:musiclist-list")).status_code, 404
        )


class MusicGenreAPITests(MusicAPITestMixin, TestCase):
    def test_lists_genres_ordered_for_tree_reassembly(self):
        data = self.payload(reverse("music-api:genre-list"))
        self.assertEqual([g["name"] for g in data], ["Rock", "Art Rock"])
        self.assertEqual(data[0]["level"], 0)
        self.assertIsNone(data[0]["parent_id"])
        self.assertEqual(data[1]["parent_id"], self.genre.id)
        self.assertEqual(data[1]["path"], "Rock > Art Rock")

    def test_anonymous_gets_404(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse("music-api:genre-list")).status_code, 404
        )


class MusicMetaAPITests(MusicAPITestMixin, TestCase):
    def test_reports_album_counts_and_year_bounds(self):
        data = self.payload(reverse("music-api:meta"))
        self.assertEqual(data["albums"]["total_count"], 2)
        self.assertEqual(data["albums"]["min_year"], 1997)
        self.assertEqual(data["albums"]["max_year"], 2000)
        self.assertEqual(
            data["albums"]["years"],
            [
                {"year_released": 1997, "count": 1},
                {"year_released": 2000, "count": 1},
            ],
        )

    def test_reports_decade_buckets(self):
        data = self.payload(reverse("music-api:meta"))
        self.assertEqual(
            data["albums"]["decades"],
            [{"decade": "1990-99", "count": 1}, {"decade": "2000-09", "count": 1}],
        )

    def test_an_album_with_no_year_is_left_out_of_the_distributions(self):
        models.Album.objects.create(name="Undated", rank=3)
        data = self.payload(reverse("music-api:meta"))
        self.assertEqual(data["albums"]["total_count"], 3)
        self.assertEqual(len(data["albums"]["years"]), 2)

    def test_reports_artist_list_and_publication_counts(self):
        data = self.payload(reverse("music-api:meta"))
        self.assertEqual(data["artists"]["total_count"], 1)
        self.assertEqual(data["lists"]["total_count"], 1)
        self.assertEqual(data["publications"]["total_count"], 1)
        self.assertEqual(data["lists"]["years"], [{"year": 2022, "count": 1}])

    def test_reports_list_counts_by_type_in_importance_order(self):
        data = self.payload(reverse("music-api:meta"))
        by_type = data["lists"]["by_type"]
        self.assertEqual(
            [entry["type"] for entry in by_type],
            list(core_constants.LIST_TYPE_IMPORTANCE_ORDER),
        )
        counts = {entry["type"]: entry["count"] for entry in by_type}
        self.assertEqual(counts[core_constants.LIST_DECADE], 1)
        self.assertEqual(counts[core_constants.LIST_ALLTIME], 0)
        labels = {entry["type"]: entry["label"] for entry in by_type}
        self.assertEqual(labels[core_constants.LIST_DECADE], "Decade")

    def test_anonymous_gets_404(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("music-api:meta")).status_code, 404)

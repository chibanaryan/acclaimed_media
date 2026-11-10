"""Requests the music API and pages used to answer with a 500."""

import json
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from core.models import User
from music import models
from music.api import views as api_views
from music.tests.site import setUpModule, tearDownModule  # noqa: F401
from music.tests.test_api import MusicAPITestMixin


class AlbumListParametersTests(MusicAPITestMixin, TestCase):
    """`str.isdigit()` takes "²" and `int()` refuses it: that was a 500."""

    def names(self, **params):
        data = self.payload(reverse("music-api:album-list"), **params)
        return [album["name"] for album in data["results"]]

    def test_a_superscript_year_is_ignored(self):
        self.assertEqual(self.names(start="²"), ["Kid A", "OK Computer"])
        self.assertEqual(self.names(end="²"), ["Kid A", "OK Computer"])

    def test_a_superscript_genre_is_ignored(self):
        self.assertEqual(self.names(genres="²"), ["Kid A", "OK Computer"])
        self.assertEqual(self.names(genres=f"²,{self.genre.id}"), ["Kid A"])

    def test_a_year_too_long_to_be_one_is_ignored(self):
        self.assertEqual(self.names(start="9" * 5000), ["Kid A", "OK Computer"])

    def test_a_year_range_still_filters(self):
        self.assertEqual(self.names(start="1999", end="2001"), ["Kid A"])


class PayloadAcrossAnImportTests(MusicAPITestMixin, TestCase):
    """`/api/all/` reads its name order and its albums in two queries."""

    def test_an_album_committed_between_the_reads_sorts_last(self):
        real = api_views._name_order

        def name_order_then_an_import():
            order = real()
            models.Album.objects.create(name="Amnesiac", rank=3)
            return order

        with mock.patch.object(api_views, "_name_order", name_order_then_an_import):
            data = self.payload(reverse("music-api:album-all-data"))

        positions = {album["n"]: album["ni"] for album in data["albums"]}
        self.assertEqual(positions, {"Kid A": 0, "OK Computer": 1, "Amnesiac": 2})


class ArtistListAcrossAnImportTests(MusicAPITestMixin, TestCase):
    """The artists page reads credits, ranks and albums in three queries."""

    def artists(self, album_ids):
        with mock.patch("music.views.album_ids_by_artist", return_value=album_ids):
            response = self.client.get(reverse("music:artist-list"))
        self.assertEqual(response.status_code, 200)
        return list(response.context["artists"])

    def test_an_album_gone_by_the_second_read_is_left_out(self):
        gone = self.kid_a.pk + self.ok_computer.pk + 1000
        artists = self.artists({self.artist.id: [self.ok_computer.pk, gone]})
        self.assertEqual([a.name for a in artists], ["Radiohead"])
        self.assertEqual(artists[0].albums_count, 1)
        self.assertEqual(artists[0].top_album, self.ok_computer)

    def test_an_artist_whose_albums_have_all_gone_is_left_out(self):
        gone = self.kid_a.pk + self.ok_computer.pk + 1000
        self.assertEqual(self.artists({self.artist.id: [gone]}), [])


class SavedFilterBodiesTests(TestCase):
    """A request body is the caller's to write: a wrong shape is a 400."""

    def setUp(self):
        self.user = User.objects.create_user(username="reader", password="pw-12345")
        self.client.force_login(self.user)
        self.list_url = reverse("music-api:saved-filter-list")

    def send(self, method, url, body):
        return getattr(self.client, method)(
            url, data=json.dumps(body), content_type="application/json"
        )

    def test_create_refuses_a_name_that_is_not_text(self):
        """`null` was saved as a filter named "None"."""
        for name in (None, True, ["a"]):
            with self.subTest(name=name):
                response = self.send("post", self.list_url, {"name": name})
                self.assertEqual(response.status_code, 400)
        self.assertFalse(models.SavedAlbumFilterSet.objects.exists())

    def test_create_refuses_a_body_that_is_not_an_object(self):
        for body in (["name"], "name", 5):
            with self.subTest(body=body):
                response = self.send("post", self.list_url, body)
                self.assertEqual(response.status_code, 400)

    def test_create_refuses_filters_that_are_not_an_object(self):
        response = self.send("post", self.list_url, {"name": "Mine", "filters": [1, 2]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Filters must be an object.")

    def test_create_still_takes_a_well_formed_body(self):
        response = self.send(
            "post", self.list_url, {"name": " Mine ", "filters": {"q": "x"}}
        )
        self.assertEqual(response.status_code, 201)
        saved = models.SavedAlbumFilterSet.objects.get()
        self.assertEqual((saved.name, saved.filters), ("Mine", {"q": "x"}))

    def test_rename_refuses_a_name_that_is_not_text(self):
        saved = models.SavedAlbumFilterSet.objects.create(
            user=self.user, name="Mine", filters={}
        )
        url = reverse("music-api:saved-filter-detail", args=[saved.pk])
        for body in ({"name": None}, {"name": True}, ["name"]):
            with self.subTest(body=body):
                self.assertEqual(self.send("patch", url, body).status_code, 400)
        saved.refresh_from_db()
        self.assertEqual(saved.name, "Mine")


class CoverIsOnlyEverAnImageTests(TestCase):
    """A cover is served from this origin with the type it was stored with."""

    def cover_url(self, content_type):
        cover = models.AlbumCover.objects.create(
            release_mbid="f04cce33-b9a0-4bed-af11-f84d649652b2",
            image_id="25254108559",
            size=250,
            data=b"<script>alert(1)</script>",
            content_type=content_type,
            byte_size=25,
        )
        return reverse(
            "music:cover",
            kwargs={
                "release_mbid": cover.release_mbid,
                "image_id": cover.image_id,
                "size": 250,
            },
        )

    def test_a_row_stored_as_html_is_not_served(self):
        self.assertEqual(self.client.get(self.cover_url("text/html")).status_code, 404)

    def test_an_image_is_served_and_not_sniffed(self):
        response = self.client.get(self.cover_url("image/png"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

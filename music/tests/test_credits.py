"""Tests for ``music.services.credits``: the credit line and whose albums are whose."""

from django.test import SimpleTestCase, TestCase

from music import models
from music.services.credits import (
    album_ids_by_artist,
    artist_summary,
    credit_separator,
    credit_text,
    split_by_credit,
    variant_names_by_artist,
)


class CreditTextTests(SimpleTestCase):
    def test_the_house_style(self):
        self.assertEqual(credit_text(["A"]), "A")
        self.assertEqual(credit_text(["A", "B"]), "A & B")
        self.assertEqual(credit_text(["A", "B", "C"]), "A, B & C")

    def test_no_names_is_various_artists(self):
        self.assertEqual(credit_text([]), "Various Artists")
        self.assertEqual(credit_text([], various_artists=True), "Various Artists")

    def test_various_artists_comes_last(self):
        self.assertEqual(
            credit_text(["Jimmy Cliff"], various_artists=True),
            "Jimmy Cliff & Various Artists",
        )
        self.assertEqual(
            credit_text(["A", "B"], various_artists=True), "A, B & Various Artists"
        )

    def test_separators(self):
        self.assertEqual(
            [credit_separator(i, 4) for i in range(4)], ["", ", ", ", ", " & "]
        )


class ArtistSummaryTests(SimpleTestCase):
    def test_counts_albums(self):
        self.assertEqual(artist_summary(1), "1 album")
        self.assertEqual(artist_summary(5), "5 albums")
        self.assertEqual(artist_summary(0), "0 albums")


class CreditQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.prince = models.Artist.objects.create(
            name="Prince",
            slug="prince",
            name_variants=[
                "Prince",
                "Prince and the Revolution",
                "Prince & the New Power Generation",
            ],
        )
        cls.nico = models.Artist.objects.create(name="Nico", slug="nico")
        cls.purple_rain = models.Album.objects.create(name="Purple Rain", rank=2)
        cls.sign = models.Album.objects.create(name="Sign o' the Times", rank=1)
        cls.parade = models.Album.objects.create(name="Parade", rank=3)
        models.AlbumCredit.objects.create(
            album=cls.purple_rain,
            artist=cls.prince,
            variant=1,
            credited_name="Prince and the Revolution",
        )
        models.AlbumCredit.objects.create(
            album=cls.sign, artist=cls.prince, credited_name="Prince"
        )
        models.AlbumCredit.objects.create(
            album=cls.parade,
            artist=cls.prince,
            variant=1,
            credited_name="Prince and the Revolution",
        )
        # A credit written without a name, as `album.artists.set()` leaves it.
        models.AlbumCredit.objects.create(album=cls.sign, artist=cls.nico, position=1)

    def test_album_ids_by_artist_counts_every_name(self):
        with self.assertNumQueries(1):
            result = album_ids_by_artist()
        self.assertEqual(
            result,
            {
                self.prince.id: {self.purple_rain.id, self.sign.id, self.parade.id},
                self.nico.id: {self.sign.id},
            },
        )

    def test_variant_names_are_the_used_ones_once_each(self):
        # The New Power Generation is a variant no album here uses.
        with self.assertNumQueries(1):
            result = variant_names_by_artist()
        self.assertEqual(result, {self.prince.id: ["Prince and the Revolution"]})

    def test_variant_names_for_some_artists(self):
        self.assertEqual(variant_names_by_artist([self.nico.id]), {})
        self.assertEqual(
            variant_names_by_artist([self.prince.id]),
            {self.prince.id: ["Prince and the Revolution"]},
        )

    def test_a_credit_names_itself(self):
        credits = {c.album_id: c for c in models.AlbumCredit.objects.all()}
        purple = credits[self.purple_rain.id]
        self.assertEqual(purple.name, "Prince and the Revolution")
        self.assertTrue(purple.uses_variant)
        nico = models.AlbumCredit.objects.get(artist=self.nico)
        self.assertEqual(nico.name, "Nico")
        self.assertFalse(nico.uses_variant)


class SplitByCreditTests(TestCase):
    def test_solo_and_joint_albums_keep_their_order(self):
        a = models.Artist.objects.create(name="A", slug="a")
        b = models.Artist.objects.create(name="B", slug="b")
        solo = models.Album.objects.create(name="Solo", rank=1, various_artists=True)
        joint = models.Album.objects.create(name="Joint", rank=2)
        later = models.Album.objects.create(name="Later", rank=3)
        for album in (solo, joint, later):
            models.AlbumCredit.objects.create(album=album, artist=a)
        models.AlbumCredit.objects.create(album=joint, artist=b, position=1)
        albums = list(models.Album.objects.with_relations().order_by("rank"))
        with self.assertNumQueries(0):
            self.assertEqual(split_by_credit(albums, a.id), ([solo, later], [joint]))

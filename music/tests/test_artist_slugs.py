"""Tests for ``music.services.artist_slugs``: names, then Wikipedia titles."""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from music import models
from music.services.metadata_service import PassResult
from music.services.artist_slugs import (
    SlugSource,
    plan_artist_slugs,
    rebuild_artist_slugs,
)


def plan(*entries):
    return plan_artist_slugs(SlugSource(*entry) for entry in entries)


class PlanArtistSlugsTests(SimpleTestCase):
    def test_a_unique_name_gets_its_plain_slug(self):
        self.assertEqual(
            plan((1, "The Beatles", "The Beatles"), (2, "Nico", "")),
            {1: "the-beatles", 2: "nico"},
        )

    def test_the_primary_topic_keeps_the_plain_slug_and_others_take_titles(self):
        # Wikipedia's own split: the band is "Nirvana (band)" there, but in
        # a corpus where one act's title is the bare name, it keeps it.
        self.assertEqual(
            plan(
                (12, "Nirvana", "Nirvana (British band)"),
                (90, "Nirvana", "Nirvana"),
            ),
            {90: "nirvana", 12: "nirvana-british-band"},
        )

    def test_with_no_primary_topic_the_lowest_id_keeps_the_plain_slug(self):
        # So the plain URL is never left empty by a pair of titles.
        self.assertEqual(
            plan(
                (12, "Nirvana", "Nirvana (band)"),
                (90, "Nirvana", "Nirvana (British band)"),
            ),
            {12: "nirvana", 90: "nirvana-british-band"},
        )

    def test_an_artist_without_a_title_is_numbered_by_provider_id(self):
        self.assertEqual(
            plan((90, "Nirvana", ""), (12, "Nirvana", ""), (50, "Nirvana", "")),
            {12: "nirvana", 50: "nirvana-2", 90: "nirvana-3"},
        )

    def test_a_title_another_artist_already_owns_is_not_taken(self):
        # "Nico Band" is an artist of its own, so a "Nico (band)" title
        # cannot give a second act that slug.
        self.assertEqual(
            plan((1, "Nico", ""), (2, "Nico", "Nico (band)"), (3, "Nico Band", "")),
            {1: "nico", 2: "nico-2", 3: "nico-band"},
        )

    def test_two_primary_topics_fall_back_to_numbers(self):
        self.assertEqual(
            plan((1, "Nico", "Nico"), (2, "Nico", "Nico")),
            {1: "nico", 2: "nico-2"},
        )

    def test_a_tail_never_takes_another_artists_own_slug(self):
        self.assertEqual(
            plan((1, "Nico", ""), (2, "Nico", ""), (3, "Nico 2", "")),
            {1: "nico", 2: "nico-3", 3: "nico-2"},
        )

    def test_names_are_transliterated_and_trimmed(self):
        slugs = plan(
            (1, "Røyksopp", ""),
            (2, "サカナクション", ""),
            (3, "!!!", ""),
            (4, "東京事変" * 20, ""),
        )
        self.assertEqual(slugs[1], "royksopp")
        self.assertEqual(slugs[2], "sakanakushiyon")
        self.assertEqual(slugs[3], "artist")
        self.assertLessEqual(len(slugs[4]), 200)
        self.assertFalse(slugs[4].endswith("-"))


class RebuildArtistSlugsTests(TestCase):
    def setUp(self):
        self.us = models.Artist.objects.create(
            name="Nirvana", slug="nirvana", source_id=12
        )
        self.uk = models.Artist.objects.create(
            name="Nirvana", slug="nirvana-2", source_id=90
        )

    def test_a_new_title_moves_the_slug_and_reports_it(self):
        models.Artist.objects.filter(pk=self.uk.pk).update(
            wikipedia_title="Nirvana (British band)"
        )
        models.Artist.objects.filter(pk=self.us.pk).update(wikipedia_title="Nirvana")
        album = models.Album.objects.create(name="Local Anaesthetic", rank=1)
        models.AlbumCredit.objects.create(album=album, artist=self.uk)
        before = models.Album.objects.get(pk=album.pk).modified
        self.assertEqual(
            rebuild_artist_slugs(), [(90, "nirvana-2", "nirvana-british-band")]
        )
        self.uk.refresh_from_db()
        self.assertEqual(self.uk.slug, "nirvana-british-band")
        # So the bulk payload, keyed by slug, gets a new version.
        self.assertGreater(models.Album.objects.get(pk=album.pk).modified, before)

    def test_nothing_changed_reports_nothing(self):
        self.assertEqual(rebuild_artist_slugs(), [])

    def test_the_metadata_command_rebuilds_after_the_wikidata_pass(self):
        models.Artist.objects.filter(pk=self.uk.pk).update(
            wikipedia_title="Nirvana (British band)"
        )
        models.Artist.objects.filter(pk=self.us.pk).update(wikipedia_title="Nirvana")
        models.Album.objects.create(name="Nevermind", rank=1, wikidata_id="Q1")
        out = StringIO()
        with mock.patch(
            "music.management.commands.fetch_album_metadata.AlbumMetadataService"
        ) as service:
            service.return_value.run_wikidata.return_value = PassResult(name="Wikidata")
            call_command("fetch_album_metadata", "--wikidata-only", stdout=out)
        self.assertIn(
            "Artist 90 slug: nirvana-2 -> nirvana-british-band", out.getvalue()
        )

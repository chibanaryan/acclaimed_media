"""Tests for re-adopting tracking rows after an album reimport.

An import deletes the albums a release drops, which leaves their tracking
rows pointing at nothing. These cover the pass that reconnects them when an
album comes back, including the case where two rows end up aimed at one
album and the unique constraint would reject the second.
"""

from datetime import datetime

from django.core.cache import cache
from django.test import TestCase

from core.models import User
from music import config, models
from music.services import user_tracking_service


class ReconnectTrackingRecordsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="listener", password="pw")
        self.album = models.Album.objects.create(
            name="Doolittle",
            rank=1,
            slug="doolittle",
            wikidata_id="Q123",
            all_wikidata_ids=["Q123"],
        )

    def _id_map(self, *albums):
        mapping = {}
        for album in albums:
            for wikidata_id in album.all_wikidata_ids or []:
                mapping[wikidata_id] = album
        return mapping

    def test_an_orphaned_row_is_pointed_at_the_new_album(self):
        row = models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q123"
        )
        stats = user_tracking_service.reconnect_tracking_records(
            self._id_map(self.album)
        )
        row.refresh_from_db()
        self.assertEqual(row.album, self.album)
        self.assertEqual(stats["listened_reconnected"], 1)
        self.assertEqual(stats["listened_merged"], 0)

    def test_both_models_are_reconnected(self):
        listened = models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q123"
        )
        wanted_album = models.Album.objects.create(
            name="Surfer Rosa",
            rank=2,
            slug="surfer-rosa",
            wikidata_id="Q456",
            all_wikidata_ids=["Q456"],
        )
        wanted = models.WantToListenAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q456"
        )

        stats = user_tracking_service.reconnect_tracking_records(
            self._id_map(self.album, wanted_album)
        )

        listened.refresh_from_db()
        wanted.refresh_from_db()
        self.assertEqual(listened.album, self.album)
        self.assertEqual(wanted.album, wanted_album)
        self.assertEqual(stats["want_reconnected"], 1)

    def test_a_secondary_id_is_normalized_to_the_primary(self):
        # A user tracked the album when the release listed it under its other
        # Wikidata entity. The row has to end up on the primary id, or the
        # next import would orphan it again.
        self.album.all_wikidata_ids = ["Q123", "Q999"]
        self.album.save()
        row = models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q999"
        )

        user_tracking_service.reconnect_tracking_records(self._id_map(self.album))

        row.refresh_from_db()
        self.assertEqual(row.album, self.album)
        self.assertEqual(row.wikidata_id, "Q123")

    def test_two_rows_aimed_at_one_album_are_merged(self):
        # The trap: both normalize to Q123, which unique_together on
        # (user, wikidata_id) forbids. The duplicate has to go before the
        # survivor is updated, not after.
        self.album.all_wikidata_ids = ["Q123", "Q999"]
        self.album.save()
        keeper = models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q123"
        )
        models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q999"
        )

        stats = user_tracking_service.reconnect_tracking_records(
            self._id_map(self.album)
        )

        self.assertEqual(models.ListenedAlbum.objects.count(), 1)
        survivor = models.ListenedAlbum.objects.get()
        self.assertEqual(survivor.pk, keeper.pk)
        self.assertEqual(survivor.album, self.album)
        self.assertEqual(stats["listened_merged"], 1)

    def test_the_merge_keeps_the_earliest_record(self):
        # The later row is an artefact of the id change; the earlier one is
        # when the user actually said they had listened.
        self.album.all_wikidata_ids = ["Q123", "Q999"]
        self.album.save()
        first = models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q999"
        )
        second = models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q123"
        )
        # `created` is auto_now_add, so it is set past the model.
        models.ListenedAlbum.objects.filter(pk=first.pk).update(
            created=datetime(2020, 1, 1)
        )
        models.ListenedAlbum.objects.filter(pk=second.pk).update(
            created=datetime(2024, 1, 1)
        )

        user_tracking_service.reconnect_tracking_records(self._id_map(self.album))

        self.assertEqual(models.ListenedAlbum.objects.get().pk, first.pk)

    def test_the_merge_keeps_ownership_from_a_later_row(self):
        # The earliest row is kept for its timestamp, but "Have" is a fact
        # about the user, not about which of the album's ids they marked.
        self.album.all_wikidata_ids = ["Q123", "Q999"]
        self.album.save()
        first = models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q999"
        )
        second = models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q123", owned=True
        )
        models.ListenedAlbum.objects.filter(pk=first.pk).update(
            created=datetime(2020, 1, 1)
        )
        models.ListenedAlbum.objects.filter(pk=second.pk).update(
            created=datetime(2024, 1, 1)
        )

        user_tracking_service.reconnect_tracking_records(self._id_map(self.album))

        survivor = models.ListenedAlbum.objects.get()
        self.assertEqual(survivor.pk, first.pk)
        self.assertTrue(survivor.owned)

    def test_two_users_tracking_one_album_are_both_kept(self):
        # Grouping is per user; these are not duplicates of each other.
        other = User.objects.create_user(username="other", password="pw")
        models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q123"
        )
        models.ListenedAlbum.objects.create(user=other, album=None, wikidata_id="Q123")

        stats = user_tracking_service.reconnect_tracking_records(
            self._id_map(self.album)
        )

        self.assertEqual(models.ListenedAlbum.objects.count(), 2)
        self.assertEqual(stats["listened_merged"], 0)
        self.assertEqual(stats["users_affected"], 2)

    def test_a_row_for_an_album_no_longer_in_the_release_is_left_alone(self):
        # Still orphaned, still kept: the album may come back next release.
        row = models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q-gone"
        )
        user_tracking_service.reconnect_tracking_records(self._id_map(self.album))
        row.refresh_from_db()
        self.assertIsNone(row.album)
        self.assertEqual(row.wikidata_id, "Q-gone")

    def test_nothing_happens_when_there_is_nothing_to_reconnect(self):
        stats = user_tracking_service.reconnect_tracking_records(
            self._id_map(self.album)
        )
        self.assertEqual(stats["listened_reconnected"], 0)
        self.assertEqual(stats["want_reconnected"], 0)
        self.assertEqual(stats["users_affected"], 0)

    def test_it_drops_the_affected_users_caches(self):
        key = config.CACHE_KEY_LISTENED_ALBUMS.format(user_id=self.user.id)
        cache.set(key, [999], 300)
        models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q123"
        )

        user_tracking_service.reconnect_tracking_records(self._id_map(self.album))

        self.assertIsNone(cache.get(key))

    def test_an_already_connected_row_is_harmless(self):
        # The pass runs over every row whose id is in the map, not only the
        # orphans, so a connected row has to survive it unchanged.
        row = models.ListenedAlbum.objects.create(
            user=self.user, album=self.album, wikidata_id="Q123"
        )
        user_tracking_service.reconnect_tracking_records(self._id_map(self.album))
        row.refresh_from_db()
        self.assertEqual(row.album, self.album)
        self.assertEqual(models.ListenedAlbum.objects.count(), 1)

    def test_an_already_connected_row_is_not_counted_or_its_caches_dropped(self):
        # Every row on a kept album is like this after an import; rewriting
        # them all would drop every tracker's caches for nothing.
        models.ListenedAlbum.objects.create(
            user=self.user, album=self.album, wikidata_id="Q123"
        )
        key = config.CACHE_KEY_LISTENED_ALBUMS.format(user_id=self.user.id)
        cache.set(key, [self.album.id], 300)

        stats = user_tracking_service.reconnect_tracking_records(
            self._id_map(self.album)
        )

        self.assertEqual(stats["listened_reconnected"], 0)
        self.assertEqual(stats["users_affected"], 0)
        self.assertEqual(cache.get(key), [self.album.id])

    def test_a_connected_row_under_a_secondary_id_is_still_normalized(self):
        self.album.all_wikidata_ids = ["Q123", "Q456"]
        self.album.save()
        row = models.ListenedAlbum.objects.create(
            user=self.user, album=self.album, wikidata_id="Q456"
        )

        stats = user_tracking_service.reconnect_tracking_records(
            self._id_map(self.album)
        )

        row.refresh_from_db()
        self.assertEqual(row.wikidata_id, "Q123")
        self.assertEqual(stats["listened_reconnected"], 1)

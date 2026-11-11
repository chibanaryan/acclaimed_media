"""What a change made outside the site's own paths drops from the cache.

The toggle, the bulk command and an import each drop what they change. An
edit in the admin, or a deleted user, album or list, went through none of
them: the listener counts lagged an hour, a reader's id sets five minutes,
and the heading's counts a day.
"""

from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from core.models import User
from core.tests.utils import CommitHooksRunNowMixin, clear_all_caches
from music import config
from music.models import (
    Album,
    AlbumCredit,
    Artist,
    ListenedAlbum,
    MusicList,
    MusicPublication,
    WantToListenAlbum,
)
from music.tests.site import setUpModule, tearDownModule  # noqa: F401


class TrackingRowSignalTests(CommitHooksRunNowMixin, TestCase):
    def setUp(self):
        clear_all_caches()
        self.user = User.objects.create_user(username="reader", password="pw")
        self.other = User.objects.create_user(username="other", password="pw")
        self.album = Album.objects.create(
            name="Signals", rank=1, year_released=1999, wikidata_id="Q1"
        )

    def _keys(self, user):
        return [
            template.format(user_id=user.id)
            for template in config.PER_USER_CACHE_KEY_TEMPLATES
        ]

    def _fill(self):
        for key in (
            config.CACHE_KEY_LISTENER_COUNTS,
            *self._keys(self.user),
            *self._keys(self.other),
        ):
            cache.set(key, "stale", 60)

    def assert_dropped_for_the_reader_alone(self):
        self.assertIsNone(cache.get(config.CACHE_KEY_LISTENER_COUNTS))
        for key in self._keys(self.user):
            self.assertIsNone(cache.get(key), key)
        for key in self._keys(self.other):
            self.assertEqual(cache.get(key), "stale", key)

    def test_a_row_saved_outside_the_toggle_drops_its_readers_sets(self):
        for model in (ListenedAlbum, WantToListenAlbum):
            with self.subTest(model=model.__name__):
                self._fill()
                row = model.objects.create(
                    user=self.user, album=self.album, wikidata_id="Q1"
                )
                self.assert_dropped_for_the_reader_alone()
                self._fill()
                row.save()  # an edit, as the admin makes
                self.assert_dropped_for_the_reader_alone()
                self._fill()
                row.delete()
                self.assert_dropped_for_the_reader_alone()

    def test_deleting_a_reader_drops_the_listener_counts(self):
        ListenedAlbum.objects.create(user=self.user, album=self.album, wikidata_id="Q1")
        self._fill()
        self.user.delete()
        self.assertIsNone(cache.get(config.CACHE_KEY_LISTENER_COUNTS))


class ReleaseRowSignalTests(CommitHooksRunNowMixin, TestCase):
    def setUp(self):
        clear_all_caches()

    def _fill(self):
        for key in config.CACHE_KEYS:
            cache.set(key, "stale", 60)

    def assert_all_dropped(self):
        for key in config.CACHE_KEYS:
            self.assertIsNone(cache.get(key), key)

    def assert_all_kept(self):
        for key in config.CACHE_KEYS:
            self.assertEqual(cache.get(key), "stale", key)

    def test_an_album_added_or_deleted_drops_the_sections_counts(self):
        """A deleted album's tracking rows go SET_NULL, which sends no signal
        of their own, so the listener counts are among them."""
        self._fill()
        album = Album.objects.create(name="Counted", rank=1, year_released=1999)
        self.assert_all_dropped()
        self._fill()
        album.delete()
        self.assert_all_dropped()

    def test_an_album_saved_again_drops_nothing(self):
        """Every metadata pass saves albums; the counts are no different for it."""
        album = Album.objects.create(name="Counted", rank=1, year_released=1999)
        self._fill()
        album.save()
        self.assert_all_kept()

    def test_a_list_or_publication_added_or_deleted_drops_them_too(self):
        self._fill()
        publication = MusicPublication.objects.create(name="Signals Weekly")
        self.assert_all_dropped()
        self._fill()
        source = MusicList.objects.create(
            name="Best of 1999", publisher=publication, year=1999, type="A"
        )
        self.assert_all_dropped()
        self._fill()
        source.save()
        publication.save()
        self.assert_all_kept()
        source.delete()
        self.assert_all_dropped()
        self._fill()
        publication.delete()
        self.assert_all_dropped()

    def test_an_artist_or_a_credit_added_or_deleted_drops_them_too(self):
        """The heading counts artists, and the artist filter lists them."""
        album = Album.objects.create(name="Credited", rank=1, year_released=1999)
        self._fill()
        artist = Artist.objects.create(name="Signal Band", slug="signal-band")
        self.assert_all_dropped()
        self._fill()
        credit = AlbumCredit.objects.create(album=album, artist=artist, position=0)
        self.assert_all_dropped()
        self._fill()
        artist.save()
        credit.save()
        self.assert_all_kept()
        credit.delete()
        self.assert_all_dropped()
        self._fill()
        artist.delete()
        self.assert_all_dropped()

    def test_a_genre_renamed_or_deleted_drops_them_too(self):
        """The filter offers genres by name and the landing pages list them:
        a rename or a delete in the admin lasted a day, and a deleted
        genre's id led to an empty page."""
        from music.models import MusicGenre

        self._fill()
        genre = MusicGenre.objects.create(name="Shoegaze", slug="shoegaze")
        self.assert_all_dropped()
        self._fill()
        genre.name = "Dream Pop"
        genre.save()
        self.assert_all_dropped()
        self._fill()
        genre.delete()
        self.assert_all_dropped()


class SignalDropsWaitForTheCommitTests(TestCase):
    """Dropped inside an import's transaction, a page load before the commit
    would refill the keys from the old rows, with nothing left to drop them."""

    def setUp(self):
        clear_all_caches()

    def test_a_count_is_dropped_only_once_its_row_is_committed(self):
        key = config.CACHE_KEY_HERO_STATS
        cache.set(key, "stale", 60)
        with self.captureOnCommitCallbacks() as callbacks:
            Album.objects.create(name="Pending", rank=1, year_released=1999)
            self.assertEqual(cache.get(key), "stale")
        self.assertEqual(cache.get(key), "stale")
        for callback in callbacks:
            callback()
        self.assertIsNone(cache.get(key))

    def test_a_readers_sets_are_dropped_only_once_their_row_is_committed(self):
        user = User.objects.create_user(username="reader", password="pw")
        album = Album.objects.create(name="Pending", rank=1, year_released=1999)
        key = config.CACHE_KEY_LISTENED_ALBUMS.format(user_id=user.id)
        cache.set(key, "stale", 60)
        with self.captureOnCommitCallbacks() as callbacks:
            ListenedAlbum.objects.create(user=user, album=album, wikidata_id="Q1")
        self.assertEqual(cache.get(key), "stale")
        for callback in callbacks:
            callback()
        self.assertIsNone(cache.get(key))


class OneDropAWriteTests(TransactionTestCase):
    """The site's own writes drop what they change themselves, and the
    signals hear their rows as well: the two are folded into one drop.

    Each drop is a generation write and a delete, several queries on
    production's `DatabaseCache`, and quick-mark makes a toggle a click. A
    `TestCase` cannot see the difference: its own transaction folds anything.
    """

    def setUp(self):
        clear_all_caches()
        self.user = User.objects.create_user(username="reader", password="pw")
        self.album = Album.objects.create(
            name="Signals", rank=1, year_released=1999, wikidata_id="Q1"
        )

    def test_a_toggle_drops_once(self):
        self.client.force_login(self.user)
        for status in ("want", "listened", "none"):
            with self.subTest(status=status):
                with mock.patch(
                    "core.cache_helpers.drop_keys", return_value=True
                ) as drop:
                    response = self.client.post(
                        reverse("music:toggle-listened", args=[self.album.id])
                        + f"?status={status}"
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(drop.call_count, 1)

    def test_the_bulk_command_drops_once(self):
        WantToListenAlbum.objects.create(
            user=self.user, album=self.album, wikidata_id="Q1"
        )
        with mock.patch("core.cache_helpers.drop_keys", return_value=True) as drop:
            call_command("mark_albums_listened", user="reader", ids="Q1", verbosity=0)
        self.assertEqual(drop.call_count, 1)
        self.assertTrue(ListenedAlbum.objects.filter(user=self.user).exists())

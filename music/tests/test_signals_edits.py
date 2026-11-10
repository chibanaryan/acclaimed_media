"""Edits the signals used to miss: a changed year, changed genres, a tracking
row given to another reader, and an album deleted with rows on it.

Each waited out a TTL until 2026-11-10: a day for the year counts and the
landing lists, five minutes for a reader's id sets.
"""

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from core.models import User
from core.tests.utils import CommitHooksRunNowMixin, clear_all_caches
from music import config
from music.models import Album, ListenedAlbum, MusicGenre, WantToListenAlbum
from music.tests.site import setUpModule, tearDownModule  # noqa: F401


class SectionKeysMixin(CommitHooksRunNowMixin):
    def setUp(self):
        super().setUp()
        clear_all_caches()
        self.addCleanup(clear_all_caches)

    def fill(self):
        for key in config.CACHE_KEYS:
            cache.set(key, "stale", 60)

    def kept(self):
        return all(cache.get(key) == "stale" for key in config.CACHE_KEYS)

    def dropped(self):
        return all(cache.get(key) is None for key in config.CACHE_KEYS)


class AlbumYearSignalTests(SectionKeysMixin, TestCase):
    def setUp(self):
        super().setUp()
        Album.objects.create(name="Dated", rank=1, year_released=1999)
        self.album = Album.objects.get()  # as the admin reads it

    def test_a_changed_year_drops_the_sections_counts(self):
        self.fill()
        self.album.year_released = 2001
        self.album.save()
        self.assertTrue(self.dropped())

    def test_a_year_set_on_an_undated_album_drops_them_too(self):
        Album.objects.filter(pk=self.album.pk).update(year_released=None)
        album = Album.objects.get()
        self.fill()
        album.year_released = 1975
        album.save()
        self.assertTrue(self.dropped())

    def test_a_save_that_leaves_the_year_alone_drops_nothing(self):
        """Every metadata pass saves every album."""
        self.fill()
        self.album.name = "Renamed"
        self.album.save()
        self.assertTrue(self.kept())

    def test_a_second_save_of_the_same_change_drops_nothing(self):
        self.album.year_released = 2001
        self.album.save()
        self.fill()
        self.album.save()
        self.assertTrue(self.kept())

    def test_a_change_not_among_the_saved_fields_drops_nothing_yet(self):
        """`update_fields` left the year out, so the row still holds 1999."""
        self.album.year_released = 2001
        self.fill()
        self.album.save(update_fields=["name"])
        self.assertTrue(self.kept())
        self.album.save()
        self.assertTrue(self.dropped())

    def test_seeing_the_change_costs_no_query(self):
        """No read of the old row before the save, as a `pre_save` needs."""
        with CaptureQueriesContext(connection) as plain:
            self.album.save()
        self.album.year_released = 2001
        with CaptureQueriesContext(connection) as changed:
            self.album.save()
        selects = [q for q in changed.captured_queries if q["sql"].startswith("SELECT")]
        self.assertEqual(selects, [])
        self.assertEqual(
            len([q for q in plain.captured_queries if q["sql"].startswith("SELECT")]),
            0,
        )

    def test_an_album_whose_year_was_never_read_drops_nothing(self):
        """A deferred year is unknown, so no change can be seen in it."""
        album = Album.objects.defer("year_released").get()
        self.fill()
        album.name = "Renamed"
        album.save(update_fields=["name"])
        self.assertTrue(self.kept())


class AlbumGenreSignalTests(SectionKeysMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.album = Album.objects.create(name="Tagged", rank=1, year_released=1999)
        self.rock = MusicGenre.objects.create(name="Rock")
        self.jazz = MusicGenre.objects.create(name="Jazz")

    def test_a_genre_added_removed_or_cleared_drops_the_sections_counts(self):
        changes = (
            lambda: self.album.genres.add(self.rock),
            lambda: self.album.genres.set([self.jazz]),
            lambda: self.album.genres.remove(self.jazz),
            lambda: self.album.genres.add(self.rock) or self.fill(),
            lambda: self.album.genres.clear(),
        )
        for number, change in enumerate(changes):
            with self.subTest(change=number):
                self.fill()
                change()
                if number != 3:  # the fourth only sets up the clear
                    self.assertTrue(self.dropped())

    def test_setting_the_genres_it_already_has_drops_nothing(self):
        self.album.genres.set([self.rock])
        self.fill()
        self.album.genres.set([self.rock])
        self.assertTrue(self.kept())


class TrackingRowMovesSignalTests(CommitHooksRunNowMixin, TestCase):
    def setUp(self):
        clear_all_caches()
        self.addCleanup(clear_all_caches)
        self.reader = User.objects.create_user(username="reader", password="pw")
        self.other = User.objects.create_user(username="other", password="pw")
        self.bystander = User.objects.create_user(username="bystander", password="pw")
        self.album = Album.objects.create(
            name="Signals", rank=1, year_released=1999, wikidata_id="Q1"
        )

    def keys(self, user):
        return [
            template.format(user_id=user.id)
            for template in config.PER_USER_CACHE_KEY_TEMPLATES
        ]

    def fill(self):
        for user in (self.reader, self.other, self.bystander):
            for key in self.keys(user):
                cache.set(key, "stale", 60)

    def is_dropped(self, user):
        return all(cache.get(key) is None for key in self.keys(user))

    def is_kept(self, user):
        return all(cache.get(key) == "stale" for key in self.keys(user))

    def test_a_row_given_to_another_reader_drops_both_readers_sets(self):
        """The reader it left went on having the album for five minutes."""
        for model in (ListenedAlbum, WantToListenAlbum):
            with self.subTest(model=model.__name__):
                model.objects.create(
                    user=self.reader, album=self.album, wikidata_id="Q1"
                )
                row = model.objects.get()  # as the admin reads it
                self.fill()
                row.user = self.other
                row.save()
                self.assertTrue(self.is_dropped(self.reader))
                self.assertTrue(self.is_dropped(self.other))
                self.assertTrue(self.is_kept(self.bystander))
                row.delete()

    def test_deleting_an_album_drops_its_readers_sets(self):
        """Their rows stay, orphaned, and their sets named a deleted pk."""
        ListenedAlbum.objects.create(
            user=self.reader, album=self.album, wikidata_id="Q1"
        )
        WantToListenAlbum.objects.create(
            user=self.other, album=self.album, wikidata_id="Q1"
        )
        self.fill()
        self.album.delete()
        self.assertTrue(self.is_dropped(self.reader))
        self.assertTrue(self.is_dropped(self.other))
        self.assertTrue(self.is_kept(self.bystander))
        self.assertEqual(ListenedAlbum.objects.get().album, None)

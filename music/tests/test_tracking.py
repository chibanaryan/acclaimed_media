"""Tests for the album listen-status toggle.

The endpoint answers with the re-rendered button, which HTMX swaps in place,
so these tests check both the rows it writes and the markup it sends back.
"""

import re
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import User
from music import config, models


class ToggleListenedAlbumViewTests(TestCase):
    """Setting a status, and the markup that comes back."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="staffer", password="pw", is_staff=True
        )
        self.client.login(username="staffer", password="pw")
        self.album = models.Album.objects.create(
            name="Doolittle", rank=1, slug="doolittle", wikidata_id="Q123"
        )
        self.url = reverse("music:toggle-listened", args=[self.album.pk])

    def _post(self, status, **params):
        query = "&".join([f"status={status}"] + [f"{k}={v}" for k, v in params.items()])
        return self.client.post(f"{self.url}?{query}")

    def _listened(self):
        return models.ListenedAlbum.objects.filter(
            user=self.user, album=self.album
        ).exists()

    def _wanted(self):
        return models.WantToListenAlbum.objects.filter(
            user=self.user, album=self.album
        ).exists()

    def test_setting_listened_creates_the_row(self):
        response = self._post("listened")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._listened())
        self.assertFalse(self._wanted())

    def test_setting_want_creates_the_row(self):
        response = self._post("want")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._wanted())
        self.assertFalse(self._listened())

    def test_setting_listened_clears_a_want(self):
        # The two are mutually exclusive, and nothing in the schema spans
        # both tables, so this view is where that holds.
        self._post("want")
        self._post("listened")
        self.assertTrue(self._listened())
        self.assertFalse(self._wanted())

    def test_setting_want_clears_a_listen(self):
        self._post("listened")
        self._post("want")
        self.assertTrue(self._wanted())
        self.assertFalse(self._listened())

    def test_setting_none_clears_both(self):
        self._post("listened")
        self._post("none")
        self.assertFalse(self._listened())
        self.assertFalse(self._wanted())

    def test_setting_none_on_an_untracked_album_is_harmless(self):
        response = self._post("none")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self._listened())

    def test_posting_the_same_status_twice_is_idempotent(self):
        # A double-click. `update_or_create` is what keeps the second post
        # from colliding with the unique_together the first created.
        self._post("listened")
        response = self._post("listened")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(models.ListenedAlbum.objects.count(), 1)

    def test_a_post_re_adopts_a_row_orphaned_by_a_reimport(self):
        # The row survived an import with its album NULL. Toggling should
        # reconnect it rather than fail on the unique id, which is what a
        # plain `create` would do.
        models.ListenedAlbum.objects.create(
            user=self.user, album=None, wikidata_id="Q123"
        )
        response = self._post("listened")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(models.ListenedAlbum.objects.count(), 1)
        row = models.ListenedAlbum.objects.get()
        self.assertEqual(row.album, self.album)

    def test_an_unknown_status_is_rejected(self):
        response = self.client.post(f"{self.url}?status=sideways")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self._listened())

    def test_a_missing_status_is_rejected(self):
        # There is no cycle form, unlike games': the dropdown always names a
        # status, so a bare post is a mistake rather than a shortcut.
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)

    def test_an_album_with_no_wikidata_id_is_rejected(self):
        # The tracking row is keyed on that id, so there is nothing to store.
        album = models.Album.objects.create(
            name="Unknown", rank=2, slug="unknown", wikidata_id=None
        )
        url = reverse("music:toggle-listened", args=[album.pk])
        response = self.client.post(f"{url}?status=listened")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(models.ListenedAlbum.objects.count(), 0)

    def test_an_unknown_album_is_a_404(self):
        url = reverse("music:toggle-listened", args=[999999])
        self.assertEqual(self.client.post(f"{url}?status=listened").status_code, 404)

    def test_the_response_is_the_rerendered_button(self):
        response = self._post("listened")
        html = response.content.decode()
        self.assertIn('data-status="listened"', html)
        self.assertIn(f'data-item-id="{self.album.pk}"', html)
        self.assertIn('data-tracking-scope="album"', html)
        self.assertIn("mdi-album", html)
        self.assertIn("You have listened to this album!", html)

    def test_the_untracked_response_shows_the_outline_record(self):
        # Untracked and listened differ in shape, not only in colour.
        html = self._post("none").content.decode()
        self.assertIn("mdi-record-circle-outline", html)
        self.assertIn('data-status="none"', html)

    def test_the_want_response_shows_the_filled_record(self):
        # The three states are one record at three fills; the backlog is the
        # solid disc between the hollow ring and the labelled record.
        # The full class string, because "mdi-record-circle" is a prefix of
        # "mdi-record-circle-outline" - which the dropdown also renders, so a
        # substring check here would pass on the wrong icon.
        html = self._post("want").content.decode()
        self.assertIn("mdi mdi-record-circle text-2xl text-warning", html)
        self.assertIn('data-status="want"', html)

    def test_the_response_animates_the_new_state(self):
        self.assertIn("star-appear", self._post("listened").content.decode())

    def test_the_response_offers_the_states_it_is_not_in(self):
        html = self._post("listened").content.decode()
        self.assertIn("status=want", html)
        self.assertIn("status=none", html)
        self.assertNotIn("status=listened", html)

    def test_the_response_does_not_push_a_url(self):
        # A button swap is not navigation; without this the address bar
        # would end up pointing at the toggle endpoint.
        self.assertEqual(self._post("listened")["HX-Push-Url"], "false")

    def test_the_large_size_is_echoed_back(self):
        # The detail page's button has to stay large across a swap, so the
        # size rides along in the query string.
        html = self._post("listened", size="large").content.decode()
        self.assertIn("h-12 w-12", html)
        self.assertIn("top-full", html)
        self.assertIn("size=large", html)

    def test_a_row_sized_button_opens_its_menu_upward(self):
        html = self._post("listened").content.decode()
        self.assertIn("bottom-full", html)
        self.assertNotIn("top-full", html)

    def test_the_response_ships_no_inline_script(self):
        # The sync is one delegated listener, not a script per swap.
        self.assertNotIn("<script", self._post("listened").content.decode())

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_the_toggle_drops_the_cached_id_sets(self):
        # The invalidation is deferred to transaction.on_commit, so that a
        # rolled-back write cannot clear a cache it did not change. Nothing
        # commits inside a TestCase, hence captureOnCommitCallbacks.
        from music import views

        views._get_listened_album_ids(self.user)
        views._get_want_to_listen_album_ids(self.user)
        listened_key = config.CACHE_KEY_LISTENED_ALBUMS.format(user_id=self.user.id)
        wanted_key = config.CACHE_KEY_WANT_TO_LISTEN_ALBUMS.format(user_id=self.user.id)
        self.assertIsNotNone(cache.get(listened_key))
        self.assertIsNotNone(cache.get(wanted_key))

        with self.captureOnCommitCallbacks(execute=True):
            self._post("listened")

        # Both, because a status change moves an album between them.
        self.assertIsNone(cache.get(listened_key))
        self.assertIsNone(cache.get(wanted_key))

    def test_the_invalidation_waits_for_the_commit(self):
        # Spelled out because it is easy to "simplify" into an inline call,
        # which games does - it has no transaction to be wrong about.
        from music import views

        views._get_listened_album_ids(self.user)
        key = config.CACHE_KEY_LISTENED_ALBUMS.format(user_id=self.user.id)

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self._post("listened")
        self.assertEqual(len(callbacks), 1)
        self.assertIsNotNone(cache.get(key))

    def test_one_users_toggle_does_not_touch_another(self):
        other = User.objects.create_user(username="other", password="pw", is_staff=True)
        self._post("listened")
        self.assertFalse(models.ListenedAlbum.objects.filter(user=other).exists())


class ToggleListenedAccessTests(TestCase):
    """The section is hidden, so the toggle is too."""

    def setUp(self):
        self.album = models.Album.objects.create(
            name="Doolittle", rank=1, slug="doolittle", wikidata_id="Q123"
        )
        self.url = reverse("music:toggle-listened", args=[self.album.pk])

    def test_an_anonymous_user_gets_404_not_a_login_redirect(self):
        # StaffOnlyMixin runs first on purpose: a redirect would advertise
        # that the URL exists.
        response = self.client.post(f"{self.url}?status=listened")
        self.assertEqual(response.status_code, 404)

    def test_a_signed_in_non_staff_user_gets_404(self):
        User.objects.create_user(username="plain", password="pw")
        self.client.login(username="plain", password="pw")
        response = self.client.post(f"{self.url}?status=listened")
        self.assertEqual(response.status_code, 404)

    def test_no_row_is_written_for_someone_who_cannot_see_the_section(self):
        User.objects.create_user(username="plain", password="pw")
        self.client.login(username="plain", password="pw")
        self.client.post(f"{self.url}?status=listened")
        self.assertEqual(models.ListenedAlbum.objects.count(), 0)


class FilterSuppressorSourceTests(SimpleTestCase):
    """The client-side filter must not swallow the toggle's POST.

    `album-client-filtering.js` cancels HTMX requests once the engine can
    answer them locally, and it does so with listeners on the filter form
    and on `#album-results-container`. Every row lives inside that
    container, so a row's listen-status POST bubbles through the same
    listener - and cancelling it made the button do nothing at all, but only
    after the bundle had finished loading, which is why it looked
    intermittent. Only GETs may be suppressed.
    """

    def setUp(self):
        self.source = (
            Path(settings.BASE_DIR) / "music/static/music/js/album-client-filtering.js"
        ).read_text()

    def test_the_suppressor_only_cancels_gets(self):
        suppressor = re.search(
            r"const suppressHtmx = event => \{(.*?)\n    \};", self.source, re.S
        )
        self.assertIsNotNone(suppressor, "suppressHtmx is gone or reshaped")
        body = suppressor.group(1)
        self.assertIn("verb", body)
        self.assertIn("'get'", body)
        self.assertIn("return", body)

    def test_the_suppressor_still_guards_on_readiness(self):
        # Without the bundle there is nothing to answer locally, so the
        # server must keep filtering - this is the progressive-enhancement
        # half of the same function.
        suppressor = re.search(
            r"const suppressHtmx = event => \{(.*?)\n    \};", self.source, re.S
        )
        self.assertIn("ready", suppressor.group(1))

    def test_the_toggle_is_a_post(self):
        # The premise of the test above: if the toggle were ever made a GET
        # it would start being suppressed again.
        button = (
            Path(settings.BASE_DIR)
            / "core/templates/core/includes/_tracking_button.html"
        ).read_text()
        self.assertIn("hx-post=", button)
        self.assertNotIn("hx-get=", button)

"""The import page's GET streams start work, so they ask who is asking."""

from unittest import mock

from django.test import TestCase

from core.models import User

STREAMS = {
    "/import/igdb-progress/?force=true": "games.utils.import_igdb_with_progress",
    "/import/wikipedia-page-progress/?force=true": (
        "games.utils.import_wikipedia_pages_with_progress"
    ),
}


class StreamsAnswerOnlyThisSitesPageTests(TestCase):
    def setUp(self):
        staff = User.objects.create_user(username="staff", password="pw", is_staff=True)
        self.client.force_login(staff)

    def get(self, url, patch, **headers):
        with mock.patch(patch, return_value=iter(["data: {}\n\n"])) as job:
            response = self.client.get(url, **headers)
        return response, job

    def test_a_link_followed_from_another_site_starts_nothing(self):
        """A top-level GET carries the Lax session cookie."""
        for url, patch in STREAMS.items():
            for origin in ("cross-site", "same-site", "none"):
                with self.subTest(url=url, origin=origin):
                    response, job = self.get(url, patch, HTTP_SEC_FETCH_SITE=origin)
                    self.assertEqual(response.status_code, 403)
                    job.assert_not_called()

    def test_the_import_pages_own_request_starts_the_job(self):
        for url, patch in STREAMS.items():
            with self.subTest(url=url):
                response, job = self.get(url, patch, HTTP_SEC_FETCH_SITE="same-origin")
                self.assertEqual(response.status_code, 200)
                job.assert_called_once()

    def test_a_browser_that_sends_no_such_header_is_let_through(self):
        for url, patch in STREAMS.items():
            with self.subTest(url=url):
                response, job = self.get(url, patch)
                self.assertEqual(response.status_code, 200)
                job.assert_called_once()

    def test_a_visitor_who_is_not_staff_still_gets_a_404(self):
        self.client.logout()
        for url, patch in STREAMS.items():
            with self.subTest(url=url):
                response, job = self.get(url, patch, HTTP_SEC_FETCH_SITE="cross-site")
                self.assertEqual(response.status_code, 404)

"""A theme chosen is the theme the next page shows, on every kind of host.

The head's script keeps the choice in a cookie as well as `localStorage`,
and the cookie wins. It named the cookie's domain from the last two parts
of the host name, which for `127.0.0.1` is `.0.1`: no browser keeps that,
so on an address the cookie was never written. A `theme` cookie already
there (an address's cookies are shared by every port, so anything served
on it before could have left one) could then never be changed, and decided
every page: a reader who switched to dark was put back on light by the next
page they opened. Run under Node on the template's own script.
"""

from django.test import SimpleTestCase

from core.tests.node import require_node, run_node


class ThemeCookieTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_node()
        cls.output = run_node("theme_cookie.js")

    def test_a_choice_is_the_next_pages_on_every_kind_of_host(self):
        for host in (
            "127.0.0.1",
            "[::1]",
            "localhost",
            "games.localhost",
            "games.acclaimedmedia.org",
            "acclaimedmedia.org",
        ):
            with self.subTest(host=host):
                self.assertEqual(self.output[host]["first"], "forest")
                self.assertEqual(self.output[host]["next"], "lofi")

    def test_the_cookie_is_the_hosts_own_where_there_is_no_parent_to_share(self):
        """An address, a bare name and `*.localhost`: a cookie may name no
        parent of any of them, and one that tries is not kept at all."""
        for host in ("127.0.0.1", "[::1]", "localhost", "games.localhost"):
            with self.subTest(host=host):
                self.assertEqual(self.output[host]["cookies"], ["theme=lofi"])

    def test_the_cookie_is_the_whole_domains_in_production(self):
        for host in ("games.acclaimedmedia.org", "acclaimedmedia.org"):
            with self.subTest(host=host):
                self.assertEqual(
                    self.output[host]["cookies"],
                    ["theme=lofi; domain=acclaimedmedia.org"],
                )
        self.assertEqual(
            self.output["acrossSites"], {"music": "lofi", "landing": "lofi"}
        )

    def test_a_cookie_already_on_an_address_can_be_changed(self):
        stale = self.output["stale on 127.0.0.1"]
        self.assertEqual(stale["before"], "lofi")
        self.assertEqual(stale["next"], "forest")
        self.assertEqual(stale["cookies"], ["theme=forest"])

    def test_a_hosts_own_cookie_does_not_outlive_the_shared_one(self):
        """A browser sends both, the older first, and the script reads the
        first: left beside the domain's cookie, a host's own would decide
        every page on that host whatever was chosen."""
        stale = self.output["stale on games.acclaimedmedia.org"]
        self.assertEqual(stale["before"], "lofi")
        self.assertEqual(stale["next"], "forest")
        self.assertEqual(stale["cookies"], ["theme=forest; domain=acclaimedmedia.org"])

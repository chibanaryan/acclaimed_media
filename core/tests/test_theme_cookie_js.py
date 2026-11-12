"""A theme chosen is the theme the next page shows, on every kind of host.

The head's script keeps the choice in a cookie as well as `localStorage`,
and the cookie wins. It named the cookie's domain from the last two parts
of the host name, which for `127.0.0.1` is `.0.1`: no browser keeps that,
so on an address the cookie was never written. A `theme` cookie already
there (an address's cookies are shared by every port, so anything served
on it before could have left one) could then never be changed, and decided
every page: a reader who switched to dark was put back on light by the next
page they opened.

The script now asks for the domain's cookie and writes the host's own if
the browser did not keep it. Run under Node on the template's own script,
against a cookie jar with a browser's rules (`core/tests/js/theme_cookie.js`);
`scripts/browser_smoke.js` has the address's case in Chrome.
"""

from django.test import SimpleTestCase

from core.tests.node import require_node, run_node

# Where a cookie may name no parent: the browser refuses one for an address,
# for `*.localhost`, and for a public suffix (a trailing dot's, Heroku's)
NO_PARENT = (
    "127.0.0.1",
    "localhost",
    "games.localhost",
    "games.acclaimedmedia.org.",
    "acclaimedgames.herokuapp.com",
)
SHARED = ("games.acclaimedmedia.org", "acclaimedmedia.org")


class ThemeCookieTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_node()
        cls.output = run_node("theme_cookie.js")

    def test_a_choice_is_the_next_pages_on_every_kind_of_host(self):
        for host in (*NO_PARENT, *SHARED):
            with self.subTest(host=host):
                self.assertEqual(self.output[host]["first"], "forest")
                self.assertEqual(self.output[host]["next"], "lofi")

    def test_the_cookie_is_the_hosts_own_where_there_is_no_parent_to_share(self):
        """One cookie, which no other site is sent. `games.localhost`'s last
        two parts are its own name, so its cookie names itself."""
        for host in NO_PARENT:
            own = "theme=lofi"
            if host == "games.localhost":
                own += "; domain=games.localhost"
            with self.subTest(host=host):
                self.assertEqual(self.output[host]["cookies"], [own])

    def test_the_cookie_is_the_whole_domains_in_production(self):
        for host in SHARED:
            with self.subTest(host=host):
                self.assertEqual(
                    self.output[host]["cookies"],
                    ["theme=lofi; domain=acclaimedmedia.org"],
                )
        self.assertEqual(
            self.output["acrossSites"], {"music": "lofi", "landing": "lofi"}
        )

    def test_a_cookie_already_on_the_host_can_be_changed(self):
        for host, kept in (
            ("127.0.0.1", "theme=forest"),
            ("games.localhost", "theme=forest; domain=games.localhost"),
        ):
            with self.subTest(host=host):
                stale = self.output[f"stale on {host}"]
                self.assertEqual(stale["before"], "lofi")
                self.assertEqual(stale["next"], "forest")
                self.assertEqual(stale["cookies"], [kept])

    def test_a_hosts_own_cookie_does_not_outlive_the_shared_one(self):
        """A browser sends both, the older first, and the script reads the
        first: left beside the domain's cookie, a host's own would decide
        every page on that host whatever was chosen there."""
        stale = self.output["stale on games.acclaimedmedia.org"]
        self.assertEqual(stale["before"], "lofi")
        self.assertEqual(stale["next"], "forest")
        self.assertEqual(stale["cookies"], ["theme=forest; domain=acclaimedmedia.org"])

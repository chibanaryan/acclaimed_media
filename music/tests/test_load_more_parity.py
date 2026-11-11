"""The end of the album list reads the same from the server and the engine.

`_album_load_more.html` prints a button while there is more and "All N
results loaded" once there is not. The engine rebuilds that container when
it takes the page over, and until 2026-11-10 it removed it at the end of a
list, so the note was there or not depending on which side rendered last.
"""

import json

from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from core.tests.node import require_node, run_node
from music.tests.site import setUpModule, tearDownModule  # noqa: F401

STATES = [
    # (total, loaded): the last page, a page with more below, an empty result
    (1234, 1234),
    (3, 3),
    (1000, 100),
    (0, 0),
]


def words(html):
    return " ".join(BeautifulSoup(html, "html.parser").get_text().split())


def classes(html):
    soup = BeautifulSoup(html, "html.parser")
    return sorted(
        {name for tag in soup.find_all(True) for name in tag.get("class", [])}
    )


class LoadMoreMarkupParityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_node()
        states = [
            {
                "total": total,
                "hasMore": loaded < total,
                "remaining": total - loaded,
                "maxLoaded": loaded >= total,
            }
            for total, loaded in STATES
        ]
        cls.client_markup = run_node("load_more_markup.js", json.dumps(states))

    def server_markup(self, total, loaded):
        html = render_to_string(
            "music/includes/_album_load_more.html",
            {
                "has_more": loaded < total,
                "total_count": total,
                "loaded_count": loaded,
                "remaining_count": total - loaded,
                "next_page": 2,
            },
        )
        # The container is the server's; the engine fills one it keeps
        container = BeautifulSoup(html, "html.parser").find(id="load-more-container")
        return container.decode_contents() if container else ""

    def test_both_sides_say_the_same_thing(self):
        for (total, loaded), client in zip(STATES, self.client_markup):
            with self.subTest(total=total, loaded=loaded):
                server = self.server_markup(total, loaded)
                self.assertEqual(words(client), words(server))
                self.assertEqual(classes(client), classes(server))

    def test_the_end_of_a_list_is_said(self):
        self.assertEqual(words(self.client_markup[0]), "All 1,234 results loaded")

    def test_an_empty_result_says_nothing(self):
        self.assertEqual(self.client_markup[3], "")

"""The page's one live region, and what is said into it.

A rankings page's result count has `role="status"`, but it sits inside the
list a server render replaces, and a live region that arrives with its text
already in it is usually not read out. The entity lists' counts
(`#results-count`) were in no live region at all. `announce()` in
utils-base.js writes to `#live-announcer`, which base.html keeps outside
every swapped container. Run under Node on the real file.
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.tests.node import require_node, run_node
from core.tests.utils import clear_all_caches

BASE = Path(settings.BASE_DIR)


class AnnounceTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_node()
        cls.output = run_node("announce.js")

    def test_a_page_without_the_region_is_left_alone(self):
        self.assertEqual(self.output["withoutRegion"], "no throw")

    def test_the_words_arrive_with_their_whitespace_collapsed(self):
        self.assertEqual(self.output["beforeTheTimer"], "")
        self.assertEqual(self.output["said"], "Showing 100 of 432")

    def test_the_same_words_twice_are_still_a_change(self):
        """A live region is read when its text changes: two filters that
        leave the same count would otherwise say nothing the second time."""
        self.assertEqual(self.output["emptiedForARepeat"], "")
        self.assertEqual(self.output["repeated"], "Showing 100 of 432")

    def test_a_burst_says_only_its_last(self):
        self.assertEqual(self.output["burst"], "Showing 100 of 50")

    def test_nothing_to_say_empties_the_region(self):
        self.assertEqual(self.output["nothingToSay"], "")

    def test_a_rankings_list_is_announced_in_its_desktop_wording(self):
        """The mobile copy reads "100 of 1,400", which says less aloud."""
        self.assertEqual(self.output["rankings"], "Showing 100 of 1,400")

    def test_an_entity_list_is_announced_by_its_heading(self):
        self.assertEqual(self.output["entityList"], "Showing 25 of 60 artists")

    def test_a_swap_with_no_count_says_nothing(self):
        self.assertEqual(self.output["noCount"], "kept")

    def test_the_games_server_render_announces_its_count(self):
        """filter-component.js's server path writes the list through
        `updateDomElements`, with no htmx event to hear."""
        self.assertEqual(
            self.output["afterUpdateDomElements"],
            {"html": "<div>rows</div>", "said": "Showing 100 of 77"},
        )

    def test_an_htmx_swap_that_brings_a_count_announces_it(self):
        self.assertEqual(self.output["afterSettle"], "3 publications (9 lists)")

    def test_a_load_more_count_sent_out_of_band_is_announced(self):
        self.assertEqual(self.output["outOfBandCount"], "Showing 50 of 60 artists")

    def test_other_out_of_band_swaps_say_nothing(self):
        """A rankings page's `#loaded-count` is inside a `role="status"` that
        stayed where it was, and announces itself."""
        self.assertEqual(self.output["outOfBandElsewhere"], "kept")

    def test_a_count_the_server_rendered_becomes_a_live_region_after_it_is_said(self):
        """Carrying `role="status"` in its markup, a swapped-in count was a
        region inserted with its text: a reader that reads those heard it
        twice, there and from `#live-announcer`."""
        self.assertEqual(
            self.output["madeLive"],
            {
                "roles": [[0, "role", "status"], [1, "role", "status"]],
                "said": "Showing 9 of 9",
            },
        )


class LiveRegionTests(TestCase):
    def setUp(self):
        clear_all_caches()

    def test_a_result_count_carries_no_role_in_its_markup(self):
        html = self.client.get(reverse("home")).content.decode()
        self.assertEqual(html.count("data-result-count="), 2)
        self.assertNotIn('role="status"', html)
        source = (BASE / "games/static/games/js/utils-base.js").read_text()
        self.assertIn("markResultCountsLive(document)", source)

    def test_every_page_has_one_outside_the_swapped_containers(self):
        html = self.client.get(reverse("home")).content.decode()
        marker = '<div id="live-announcer" class="sr-only" aria-live="polite"'
        self.assertEqual(html.count(marker), 1)
        self.assertLess(html.index(marker), html.index('id="main-content"'))

    def test_the_entity_lists_say_their_new_count(self):
        """Their heading is rewritten by script, in no live region."""
        developers = (
            BASE / "games/templates/developers/developer_list.html"
        ).read_text(encoding="utf-8")
        self.assertIn("announce(resultsCount.textContent)", developers)
        load_more = (BASE / "core/static/core/js/entity-load-more.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("announce(heading.textContent)", load_more)

    def test_the_client_renderers_do_not_announce_as_well(self):
        """They rewrite a `role="status"` that stayed in the page, which
        announces itself: calling `announce` there would say it twice."""
        for path in (
            "core/static/core/js/base-renderer.js",
            "games/static/games/js/game-list-renderer.js",
            "games/static/games/js/client-filtering.js",
            "music/static/music/js/album-list-renderer.js",
            "music/static/music/js/album-client-filtering.js",
        ):
            with self.subTest(path=path):
                source = (BASE / path).read_text(encoding="utf-8")
                self.assertNotIn("announce(", source)

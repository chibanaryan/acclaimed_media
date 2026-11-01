"""The year heatmap keeps the whole corpus as its colour scale.

The grid scaled its colours to the counts the page rendered with. Loaded
with a filter (`/music/?listened=no`, top count 1) that meant a 20-album
year asked for 1620% opacity once the filter was cleared, which the CSS
rejects, and only the previously filtered years stayed coloured. The page
now renders the corpus's counts as `year-baseline-counts-data` for the grid
to scale by, and the grid caps the opacity.
"""

import unittest

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.tests.node import node_available, run_node
from music import config, models
from music.services.caching import invalidate_music_caches
from music.tests.site import music_site
from music.tests.test_views import MusicDataMixin


class YearGridScaleTests(SimpleTestCase):
    """The real grid under Node (`core/tests/js/year_grid_baseline.js`)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not node_available():
            raise unittest.SkipTest("Node is not installed")
        cls.output = run_node("year_grid_baseline.js")

    def test_the_page_baseline_sets_the_scale(self):
        grid = self.output["withBaseline"]
        self.assertEqual((grid["maxCount"], grid["originalMaxCount"]), (20, 20))
        # The cells still show the page's own, filtered counts.
        self.assertEqual(grid["current"], [1, 0, 0])
        self.assertEqual(grid["cells"], [1970, 1971, 1972])

    def test_without_one_the_rendered_counts_are_the_scale(self):
        # Games sends none, and keeps its old behaviour.
        grid = self.output["withoutBaseline"]
        self.assertEqual((grid["maxCount"], grid["originalMaxCount"]), (1, 1))

    def test_a_count_above_the_scale_is_full_colour_not_invalid(self):
        self.assertEqual(self.output["opacityAboveScale"], "100%")

    def test_a_neighbour_is_a_tile_the_grid_drew(self):
        # A tile paints the gaps to its left and above alone, so a cell the
        # grid filled in has to count as a neighbour, and a cell or a decade
        # row it never drew must not, whatever the URL's range names.
        self.assertEqual(
            self.output["neighbours"],
            {
                "rightOntoFilledCell": True,
                "belowOntoFilledCell": True,
                "aboveOntoFilledCell": True,
                "rightOntoNoCell": False,
                "decadeBelowRow": True,
                "decadeAboveNoRow": False,
                "decadeBelowNoRow": False,
                "firstColumnLeftIsTheLabel": True,
            },
        )

    def test_shift_extending_downward_keeps_the_anchors_end(self):
        # The anchor was only its first year, so the 1970s then the 1960s gave
        # 1960-1970 and lost the rest of the decade clicked first.
        self.assertEqual(self.output["decadeThenLowerDecade"], [1960, 1979])
        self.assertEqual(self.output["decadeThenLowerYear"], [1962, 1979])
        self.assertEqual(self.output["yearThenLowerYear"], [1962, 1975])

    def test_shift_inside_or_above_the_anchor_ends_at_the_pick(self):
        self.assertEqual(self.output["decadeThenYearInside"], [1970, 1975])
        self.assertEqual(self.output["decadeThenHigherYear"], [1960, 1975])

    def test_shift_extends_what_a_drag_chose(self):
        self.assertEqual(self.output["shiftAfterDrag"], [1961, 1992])
        # A pick that overlaps the drag's low end still keeps its high end.
        self.assertEqual(self.output["shiftOverlappingADrag"], [1960, 1985])
        # No click reaches a tile here, and the last pick is still this one.
        self.assertEqual(self.output["labelReleasedOffItsTile"], [1970, 1985])

    def test_shift_extends_the_range_on_screen_however_it_got_there(self):
        # An anchor kept apart from the filters went stale, or was missing, for
        # a range from a link, a saved filter or the back button.
        self.assertEqual(self.output["shiftFromARangeItDidNotPick"], [1970, 1985])

    def test_a_shift_drag_needs_no_click(self):
        # Released on another tile, the browser sends none.
        self.assertEqual(self.output["shiftDragWithNoClick"], [1970, 1981])

    def test_the_range_stays_lit_while_shift_is_pressed(self):
        # It began to fade out under the press, and back in on the release.
        self.assertEqual(
            self.output["whileShiftIsDown"],
            {"stillLit": True, "labelStillLit": False, "pressedLit": True},
        )

    def test_a_click_with_no_press_picks_as_the_keyboard_does(self):
        self.assertEqual(
            self.output["clickAlone"],
            {"picked": [1970, 1979], "again": [1950, 1999]},
        )

    def test_a_full_gesture_is_applied_once_however_it_was_sent(self):
        # Reading `detail` here selected the year and cleared it in one action.
        self.assertEqual(self.output["fullGestureFromAssistiveTech"], [1975, 1975])

    def test_a_label_stays_dark_under_a_shift_press_that_will_not_light_it(self):
        # 1962-1979 is no decade, so it would fade in and straight back out.
        self.assertFalse(self.output["shiftPressOnALabel"])

    def test_a_drag_abandoned_off_the_grid_changes_nothing(self):
        # Back on the tile, the release still sends a click, and it is no pick.
        self.assertEqual(self.output["pressThenLeave"], [1975, 1975])

    def test_a_press_ends_with_its_release_and_no_sooner(self):
        self.assertEqual(
            self.output["timing"],
            {
                # Released on another tile, nothing lingers for the next click
                "bareClickPicks": [1980, 1980],
                # A quick second press keeps its own, and its release ends it
                "stillPressed": True,
                "dragEnded": True,
                "rightClickDrags": False,
                "controlClickDrags": False,
            },
        )

    def test_a_label_previews_what_the_release_will_do(self):
        self.assertEqual(
            self.output["labelDraggedOntoAYear"],
            {"pressed": True, "dragged": False, "acrossDecades": [True, True]},
        )

    def test_the_mobile_sheet_shows_the_years_there_are(self):
        self.assertEqual(
            self.output["sheet"],
            {
                # A range or a year outside the data shows "A range", not a year
                "singleYear": [1990, None, None, 2026],
                # Each end pushes the other along
                "fromPastTo": [1990, 1990],
                "toBeforeFrom": [1975, 1975],
                # Complete years, and the data's latest where those stop earlier
                "lastFiveOfOldData": [2015, 2019],
                "lastFiveOfCurrentData": True,
                "lastHundredOfOldData": [1952, 2019],
                "pastTheEnd": [2020, 2026],
                "beforeTheStart": [1971, 1979],
                # Nothing to stop at: as the heading does, say what was asked
                "aboveEverything": [2030, 2035],
                "belowEverything": [1900, 1950],
                "firstYearAndLast": [2026, 1971],
                # "All Years" clears, and the first year is a year like any other
                "allYears": [1971, 2026],
                "firstYear": [1971, 1971],
            },
        )

    def test_a_second_click_on_a_lone_year_clears_it(self):
        self.assertEqual(self.output["secondClickClears"], [1950, 1999])

    def test_a_drag_across_the_whole_grid_is_the_bounds(self):
        # It ended at the last decade's 9, past the last year, which every
        # exact comparison read as a filter while the page reported none.
        self.assertEqual(self.output["wholeDrag"], [1960, 1982])
        # Past one end only, a decade keeps its 9, so its label stays lit.
        self.assertEqual(self.output["partialDrag"], [1970, 1989])

    def test_a_link_from_an_old_drag_lights_nothing(self):
        self.assertTrue(self.output["oldLinkLightsNothing"])

    def test_rows_run_newest_first(self):
        # The gaps' ownership rests on it: a tile owns the gap above because the
        # row above painted first. Ascending rows would bring back the hairlines.
        self.assertEqual(self.output["rowOrder"], [1980, 1970, 1960])


@music_site
class AlbumYearBaselineTests(MusicDataMixin, TestCase):
    def baseline(self, **params):
        response = self.client.get(reverse("music:home"), params)
        return response, {
            entry["year"]: entry["count"]
            for entry in response.context["year_baseline_counts"]
            if entry["count"]
        }

    def test_a_filtered_page_scales_by_the_whole_corpus(self):
        response, baseline = self.baseline(q="revolver")
        self.assertEqual(baseline, {1966: 1, 1979: 1, 2000: 1})
        current = {e["year"]: e["count"] for e in response.context["year_counts"]}
        self.assertEqual(current[1979], 0)
        self.assertContains(response, 'id="year-baseline-counts-data"')

    def test_a_page_whose_counts_are_the_corpus_sends_no_second_copy(self):
        for params in ({}, {"start": "1970", "end": "1980"}):
            with self.subTest(params=params):
                response = self.client.get(reverse("music:home"), params)
                self.assertNotIn("year_baseline_counts", response.context)
                self.assertNotContains(response, 'id="year-baseline-counts-data"')

    def test_partial_and_load_more_responses_skip_it(self):
        for params, headers in (
            ({"q": "revolver"}, {"HTTP_HX_REQUEST": "true"}),
            ({"q": "revolver", "append": "true", "page": "1"}, {}),
        ):
            with self.subTest(params=params):
                response = self.client.get(reverse("music:home"), params, **headers)
                self.assertNotIn("year_baseline_counts", response.context)

    def test_new_bounds_rebuild_the_baseline(self):
        self.baseline(q="revolver")
        models.Album.objects.create(name="Early", rank=9, year_released=1950)
        # The bounds are cached apart; dropped alone, as their expiry would.
        cache.delete(config.CACHE_KEY_YEAR_STATS)
        _, baseline = self.baseline(q="revolver")
        self.assertEqual(baseline[1950], 1)

    def test_the_baseline_is_cached_and_dropped_on_import(self):
        self.baseline(genres=str(self.rock.id))
        models.Album.objects.create(name="Late", rank=9, year_released=1966)
        _, cached = self.baseline(genres=str(self.rock.id))
        self.assertEqual(cached[1966], 1)
        invalidate_music_caches()  # what an import and a metadata run call
        _, fresh = self.baseline(genres=str(self.rock.id))
        self.assertEqual(fresh[1966], 2)

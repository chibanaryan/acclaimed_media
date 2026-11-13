"""A game page describes its game.

Every fetch asked IGDB for `summary` and dropped it, so each game's meta
description and JSON-LD were one stock sentence (until
2026-11-12). The summary is stored on the IGDB record, which outlives an
import, and the page leads with the rank and goes on in IGDB's words.
"""

import json
import re
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.services import seo
from core.tests.utils import clear_all_caches
from games.models import Game, IGDBGameData

LD_JSON = re.compile(
    r'<script type="application/ld\+json"[^>]*>\s*(.*?)\s*</script>', re.S
)
META = re.compile(r'<meta name="description" content="([^"]*)"')
OG = re.compile(r'<meta property="og:description" content="([^"]*)"')

SUMMARY = (
    "A lone courier crosses a ruined country, reconnecting its scattered "
    "cities one delivery at a time while something watches from the rain."
)


def answer(**fields):
    data = {
        "slug": "alpha-quest",
        "cover": "co1",
        "url": "https://igdb.example/alpha",
        "youtube_video_id": None,
        "developers": [],
        "series": [],
    }
    data.update(fields)
    return data


class MetaDescriptionTests(SimpleTestCase):
    def test_short_text_is_left_as_it_is(self):
        self.assertEqual(seo.meta_description("A short one."), "A short one.")

    def test_whitespace_is_collapsed(self):
        self.assertEqual(
            seo.meta_description(" Two\n\nlines \t here "), "Two lines here"
        )

    def test_long_text_is_cut_at_a_word_and_marked(self):
        cut = seo.meta_description(SUMMARY, 60)
        self.assertLessEqual(len(cut), 60)
        self.assertTrue(cut.endswith("…"))
        self.assertTrue(SUMMARY.startswith(cut[:-1]))
        # The word before the cut is whole
        self.assertEqual(SUMMARY[len(cut) - 1], " ")

    def test_punctuation_is_not_left_before_the_mark(self):
        self.assertEqual(
            seo.meta_description("One, two, three, four, five", 11), "One, two…"
        )

    def test_a_word_longer_than_the_limit_is_cut_through(self):
        self.assertEqual(seo.meta_description("a" * 30, 10), "a" * 9 + "…")

    def test_text_exactly_at_the_limit_is_whole(self):
        self.assertEqual(seo.meta_description("abcde fghi", 10), "abcde fghi")

    def test_nothing_is_nothing(self):
        self.assertEqual(seo.meta_description(None), "")
        self.assertEqual(seo.meta_description("  "), "")


class TheFetchKeepsTheSummaryTests(TestCase):
    def fetch(self, game, **fields):
        api = mock.Mock()
        api.get_game_info_by_id.return_value = answer(**fields)
        game.get_igdb_data(igdb_ids=7, api_client=api, cache_results=False)
        return IGDBGameData.objects.get(igdb_id=7)

    def test_a_new_record_holds_it(self):
        game = Game.objects.create(name="Alpha Quest", rank=1)
        self.assertEqual(self.fetch(game, summary=SUMMARY).summary, SUMMARY)

    def test_a_refetch_replaces_it(self):
        game = Game.objects.create(name="Alpha Quest", rank=1)
        self.fetch(game, summary="Old words.")
        self.assertEqual(self.fetch(game, summary=SUMMARY).summary, SUMMARY)

    def test_a_record_taken_back_after_an_import_gets_it(self):
        """The orphan branch saves a named list of fields."""
        IGDBGameData.objects.create(
            game=None, igdb_id=7, url="https://igdb.example/old", is_primary=True
        )
        game = Game.objects.create(name="Alpha Quest", rank=1)
        record = self.fetch(game, summary=SUMMARY)
        self.assertEqual(record.game, game)
        self.assertEqual(record.summary, SUMMARY)

    def test_a_game_igdb_has_no_summary_for_holds_an_empty_one(self):
        game = Game.objects.create(name="Alpha Quest", rank=1)
        self.assertEqual(self.fetch(game, summary=None).summary, "")
        self.assertEqual(self.fetch(game).summary, "")

    def test_no_summary_is_not_a_reason_to_fetch_again(self):
        """IGDB has none for some games: counted as missing, the import
        page's count would never reach zero."""
        game = Game.objects.create(name="Alpha Quest", rank=1)
        self.fetch(game)
        self.assertFalse(Game.objects.needing_igdb().filter(pk=game.pk).exists())


class TheGamePageUsesItTests(TestCase):
    def setUp(self):
        clear_all_caches()
        self.game = Game.objects.create(
            name="Alpha Quest", slug="alpha-quest", rank=12, year_of_release=1998
        )

    def give_summary(self, summary):
        record = IGDBGameData.objects.create(
            game=self.game,
            igdb_id=7,
            url="https://igdb.example/alpha",
            is_primary=True,
            summary=summary,
        )
        self.game.primary_igdb_game_data = record
        self.game.save()

    def page(self):
        response = self.client.get(
            reverse("game-detail", kwargs={"slug": "alpha-quest"})
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_description_leads_with_the_rank_then_igdbs_words(self):
        self.give_summary(SUMMARY)
        description = META.search(self.page()).group(1)
        self.assertTrue(
            description.startswith(
                "#12 of the most critically acclaimed video games. A lone courier"
            ),
            description,
        )
        self.assertLessEqual(len(description), 160)
        self.assertTrue(description.endswith("…"))

    def test_the_share_card_says_the_same(self):
        self.give_summary(SUMMARY)
        html = self.page()
        self.assertEqual(OG.search(html).group(1), META.search(html).group(1))

    def test_a_game_without_one_keeps_the_stock_sentences(self):
        html = self.page()
        self.assertIn(
            "Alpha Quest (1998) - Ranked #12 among", META.search(html).group(1)
        )
        self.assertIn("Alpha Quest (1998) is ranked #12", OG.search(html).group(1))

    def test_a_record_with_an_empty_summary_keeps_them_too(self):
        self.give_summary("")
        self.assertIn("Ranked #12 among", META.search(self.page()).group(1))

    def test_the_structured_data_carries_the_whole_summary(self):
        self.give_summary(SUMMARY)
        data = json.loads(LD_JSON.search(self.page()).group(1))
        self.assertEqual(data["description"], SUMMARY)

    def test_a_description_staff_wrote_comes_before_igdbs(self):
        self.give_summary(SUMMARY)
        self.game.description = "Staff's own words about the game."
        self.game.save()
        html = self.page()
        self.assertEqual(
            META.search(html).group(1),
            "#12 of the most critically acclaimed video games. "
            "Staff&#x27;s own words about the game.",
        )
        data = json.loads(LD_JSON.search(html).group(1))
        self.assertEqual(data["description"], "Staff's own words about the game.")

    def test_a_summary_cannot_break_out_of_the_page(self):
        self.give_summary('He said "run" </script><script>alert(1)</script> & ran')
        html = self.page()
        self.assertNotIn("<script>alert(1)</script>", html)
        description = META.search(html).group(1)
        self.assertIn("&quot;run&quot;", description)
        data = json.loads(LD_JSON.search(html).group(1))
        self.assertIn('"run" </script>', data["description"])

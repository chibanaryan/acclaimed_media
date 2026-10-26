"""The VideoGame JSON-LD on a game's detail page."""

import json
import re

from django.test import TestCase
from django.urls import reverse

from core.tests.utils import clear_all_caches
from games.models import Game, IGDBGameData

LD_JSON = re.compile(
    r'<script type="application/ld\+json"[^>]*>\s*(.*?)\s*</script>', re.S
)


class GameStructuredDataTests(TestCase):
    def setUp(self):
        clear_all_caches()

    def _ld(self, game):
        response = self.client.get(reverse("game-detail", kwargs={"slug": game.slug}))
        self.assertEqual(response.status_code, 200)
        blocks = LD_JSON.findall(response.content.decode())
        self.assertEqual(len(blocks), 1)
        return blocks[0], json.loads(blocks[0])

    def test_names_are_json_not_html_entities(self):
        game = Game.objects.create(
            name="Assassin's Creed </script> & Co",
            slug="assassins-creed",
            rank=1,
            year_of_release=2007,
        )

        raw, data = self._ld(game)

        self.assertEqual(data["@type"], "VideoGame")
        self.assertEqual(data["name"], "Assassin's Creed </script> & Co")
        self.assertNotIn("&#x27;", raw)
        self.assertNotIn("</script>", raw)
        self.assertEqual(data["datePublished"], "2007")
        self.assertTrue(data["url"].endswith(f"/game/{game.slug}/"))

    def test_publishes_no_rating_and_no_missing_values(self):
        game = Game.objects.create(
            name="Tetris", slug="tetris", rank=2, year_of_release=None
        )

        raw, data = self._ld(game)

        self.assertNotIn("aggregateRating", data)
        self.assertNotIn("image", data)
        self.assertNotIn("datePublished", data)
        self.assertNotIn("None", raw)
        self.assertTrue(data["description"])

    def test_carries_the_cover_when_there_is_one(self):
        game = Game.objects.create(
            name="Doom", slug="doom", rank=3, igdb_id=7, year_of_release=1993
        )
        igdb = IGDBGameData.objects.create(game=game, igdb_id=7, artwork_id="co1abc")
        game.primary_igdb_game_data = igdb
        game.save()

        _, data = self._ld(game)

        self.assertEqual(data["image"], game.image_og)
        self.assertTrue(data["image"].startswith("https://"))

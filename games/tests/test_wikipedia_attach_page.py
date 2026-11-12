"""`WikipediaGameData.attach_page`: what a page lookup found, saved.

The staff page's stream and `fetch_wikipedia_metadata` each had a copy of
it until 2026-11-12.
"""

from django.test import TestCase

from games.models import Game, WikipediaGameData
from games.services.wiki_page_lookup_service import PageLookupResult


def found(**fields):
    fields.setdefault("page_title", "Alpha Quest (video game)")
    fields.setdefault("lookup_source", "wikidata")
    return PageLookupResult(game_name="Alpha Quest", **fields)


class AttachPageTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create(name="Alpha Quest", rank=1, slug="alpha-quest")

    def test_a_new_page_becomes_the_games_primary_record(self):
        record = WikipediaGameData.attach_page(
            self.game,
            found(hltb_id="123", steam_app_id="620", wikiquote_page_title="Alpha"),
            "Q1",
        )
        self.game.refresh_from_db()
        self.assertEqual(self.game.primary_wikipedia_game_data, record)
        self.assertTrue(record.is_primary)
        self.assertEqual(
            (
                record.page_title,
                record.lookup_source,
                record.wikidata_id,
                record.hltb_id,
                record.steam_app_id,
                record.wikiquote_page_title,
            ),
            ("Alpha Quest (video game)", "wikidata", "Q1", "123", "620", "Alpha"),
        )

    def test_the_games_own_record_of_the_page_is_updated_not_doubled(self):
        first = WikipediaGameData.attach_page(self.game, found(), "Q1")
        again = WikipediaGameData.attach_page(self.game, found(hltb_id="9"), "Q1")
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(again.hltb_id, "9")
        self.assertEqual(WikipediaGameData.objects.count(), 1)

    def test_a_record_of_another_page_stops_being_primary(self):
        old = WikipediaGameData.attach_page(self.game, found(page_title="Old"), "Q1")
        new = WikipediaGameData.attach_page(self.game, found(page_title="New"), "Q1")
        old.refresh_from_db()
        self.assertFalse(old.is_primary)
        self.assertTrue(new.is_primary)

    def test_an_orphaned_record_of_the_page_is_taken_back_with_its_genres(self):
        """An import recreates every game; its records wait with no game."""
        orphan = WikipediaGameData.objects.create(
            game=None,
            page_title="Alpha Quest (video game)",
            is_primary=True,
            lookup_source="search",
            primary_genre="Platform",
            hltb_id="77",
        )
        record = WikipediaGameData.attach_page(self.game, found(steam_app_id="5"), "Q1")
        self.assertEqual(record.pk, orphan.pk)
        record.refresh_from_db()
        self.assertEqual(record.game, self.game)
        self.assertEqual(record.primary_genre, "Platform")
        self.assertEqual(
            (record.lookup_source, record.wikidata_id, record.steam_app_id),
            ("wikidata", "Q1", "5"),
        )
        self.game.refresh_from_db()
        self.assertEqual(self.game.primary_wikipedia_game_data, record)

    def test_what_the_lookup_did_not_find_is_left_as_it_was(self):
        """No HLTB id this time is not "the game has none"."""
        WikipediaGameData.objects.create(
            game=None,
            page_title="Alpha Quest (video game)",
            is_primary=True,
            wikidata_id="Q9",
            hltb_id="77",
        )
        record = WikipediaGameData.attach_page(self.game, found(), "")
        record.refresh_from_db()
        self.assertEqual((record.hltb_id, record.wikidata_id), ("77", "Q9"))

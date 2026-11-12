"""Reading a Wikidata entity's claims, for games and music alike."""

from django.test import SimpleTestCase

from core.services.wikidata_claims import claim_values, first_claim_value


def claim(value, rank="normal"):
    return {"rank": rank, "mainsnak": {"datavalue": {"value": value}}}


class ClaimValuesTests(SimpleTestCase):
    def test_deprecated_claims_are_dropped(self):
        claims = {"P1": [claim("keep"), claim("drop", "deprecated")]}
        self.assertEqual(claim_values(claims, "P1"), ["keep"])

    def test_preferred_claims_sort_first(self):
        claims = {"P1": [claim("normal"), claim("best", "preferred")]}
        self.assertEqual(claim_values(claims, "P1"), ["best", "normal"])

    def test_claims_of_one_rank_keep_their_order(self):
        claims = {"P1": [claim("first"), claim("second")]}
        self.assertEqual(claim_values(claims, "P1"), ["first", "second"])

    def test_a_claim_with_no_datavalue_is_skipped(self):
        """A "no value" or "unknown value" snak carries none."""
        claims = {"P1": [{"rank": "normal", "mainsnak": {}}, claim("ok")]}
        self.assertEqual(claim_values(claims, "P1"), ["ok"])

    def test_a_null_datavalue_is_skipped(self):
        claims = {
            "P1": [{"rank": "preferred", "mainsnak": {"datavalue": None}}, claim("ok")]
        }
        self.assertEqual(claim_values(claims, "P1"), ["ok"])

    def test_a_claim_with_no_rank_is_normal(self):
        claims = {"P1": [{"mainsnak": {"datavalue": {"value": "unranked"}}}]}
        self.assertEqual(claim_values(claims, "P1"), ["unranked"])

    def test_a_missing_property_yields_nothing(self):
        self.assertEqual(claim_values({}, "P1"), [])
        self.assertIsNone(first_claim_value({}, "P1"))

    def test_first_claim_value_takes_the_best_ranked(self):
        claims = {"P1": [claim("a"), claim("b", "preferred")]}
        self.assertEqual(first_claim_value(claims, "P1"), "b")

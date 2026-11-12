"""Reading the claims of a Wikidata entity.

``wbgetentities`` answers each property with a list of claims, each with a
rank and, unless it is a "no value" or "unknown value" statement, a
datavalue. Games read the HowLongToBeat and Steam ids this way and music the
MusicBrainz, Discogs and release-date claims. Games had four inline copies
until 2026-11-12, which took the single best-ranked claim and answered None
when it carried no value, whatever the next one held.
"""

from typing import Any, Dict, List, Optional


def claim_values(claims: Dict[str, Any], prop: str) -> List[Any]:
    """Every usable datavalue for ``prop``, best rank first.

    Deprecated claims are dropped, preferred ones sort ahead of normal ones,
    and claims of one rank keep the order Wikidata gave them. A claim with no
    datavalue is skipped.
    """
    ranked = [
        claim
        for claim in claims.get(prop, [])
        if claim.get("rank", "normal") != "deprecated"
    ]
    ranked.sort(key=lambda claim: 0 if claim.get("rank") == "preferred" else 1)

    values = []
    for claim in ranked:
        datavalue = claim.get("mainsnak", {}).get("datavalue")
        if datavalue is not None and "value" in datavalue:
            values.append(datavalue["value"])
    return values


def first_claim_value(claims: Dict[str, Any], prop: str) -> Optional[Any]:
    """The best-ranked datavalue for ``prop``, or None."""
    values = claim_values(claims, prop)
    return values[0] if values else None

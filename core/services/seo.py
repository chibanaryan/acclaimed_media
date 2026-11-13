"""
Structured data shared by the sections' SEO ranking pages.

Lifted from ``games.views._landing_itemlist_json`` for music's landing pages;
games' landing pages build theirs through it too.
"""

import json

from core import sites


def json_ld(payload):
    """Serialise ``payload`` for a ``<script type="application/ld+json">``.

    Built with ``json.dumps`` rather than written into the template: there,
    autoescaping turned "Assassin's Creed" into ``Assassin&#x27;s Creed``,
    which a script body never decodes, and a missing value into ``"None"``.
    "<" is escaped so the JSON can never close the ``<script>`` tag.
    """
    return json.dumps(payload).replace("<", "\\u003c")


def meta_description(text, limit=155):
    """``text`` as a meta description: one line, cut at a word near ``limit``.

    Search results show about 155 characters. Text over the limit is cut
    at the last whole word that leaves room for an ellipsis, without the
    comma or dash the cut would leave hanging; a single word longer than
    the limit is cut through. Django's ``Truncator.chars`` cuts mid-word.
    """
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    room = limit - 1
    cut = text[:room]
    if text[room] != " " and " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,;:-\u2013\u2014") + "\u2026"


def itemlist_json(name, entries, site):
    """A schema.org ItemList for ``entries``, an iterable of ``(name, path)``.

    The paths are on ``site`` (core/sites.py), whose public origin makes
    them absolute. Positions follow the iteration order. "<" is escaped so
    the JSON can never close the ``<script>`` tag it is rendered into.
    """
    elements = [
        {
            "@type": "ListItem",
            "position": position,
            "name": item_name,
            "url": sites.canonical_url(site, path),
        }
        for position, (item_name, path) in enumerate(entries, start=1)
    ]
    payload = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": name,
        "numberOfItems": len(elements),
        "itemListElement": elements,
    }
    return json_ld(payload)

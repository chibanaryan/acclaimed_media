"""
Structured data shared by the sections' SEO ranking pages.

Lifted from ``games.views._landing_itemlist_json`` for music's landing pages;
games still carries its own copy and can move onto this one unchanged.
"""

import json

# Production base for absolute URLs in structured data (matches base.html's
# canonical link).
SITE_BASE = "https://www.acclaimedvideogames.com"


def itemlist_json(name, entries):
    """A schema.org ItemList for ``entries``, an iterable of ``(name, path)``.

    Positions follow the iteration order. "<" is escaped so the JSON can
    never close the ``<script>`` tag it is rendered into.
    """
    elements = [
        {
            "@type": "ListItem",
            "position": position,
            "name": item_name,
            "url": SITE_BASE + path,
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
    return json.dumps(payload).replace("<", "\\u003c")

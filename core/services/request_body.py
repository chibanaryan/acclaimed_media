"""Request-body parsing that never raises.

A JSON body is the caller's to write, as a query string is
(``core.services.query_params``): an array has no ``.get`` and a name of
``5`` or ``null`` has no ``.strip``, and each was a 500 in the saved-filter
APIs.
"""

import io

from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


def read_saved_filter(data):
    """``(name, filters)`` from a saved-filter request body.

    ``name`` is the stripped text, or ``""`` when the body has none: no
    name, one that is neither text nor a number, or a body that is not an
    object. The views answer an empty name with their "required" message. A
    number is taken as its digits ("1975" is a fair name for a filter);
    ``null`` is not, which was saved as a filter called "None".

    ``filters`` is the object sent, ``{}`` when none was, and ``None`` when
    what was sent is not an object, which no filter component could apply.
    """
    if not isinstance(data, dict):
        return "", None
    name = data.get("name")
    if isinstance(name, (int, float)) and not isinstance(name, bool):
        name = str(name)
    filters = data.get("filters", {})
    return (
        name.strip() if isinstance(name, str) else "",
        filters if isinstance(filters, dict) else None,
    )


# A saved filter is a few hundred bytes; the largest a real filter
# component writes (every genre, every platform) is a few kilobytes.
MAX_SAVED_FILTER_BYTES = 16 * 1024


class SavedFilterJSONParser(JSONParser):
    """JSON, refused past ``MAX_SAVED_FILTER_BYTES`` before it is parsed.

    DRF reads the body from the stream itself, so Django's
    ``DATA_UPLOAD_MAX_MEMORY_SIZE`` never applied to it: a signed-in caller
    could have a worker parse, and the table keep, any size of object.
    Reads one byte past the cap, never the rest.
    """

    def parse(self, stream, media_type=None, parser_context=None):
        raw = stream.read(MAX_SAVED_FILTER_BYTES + 1) if stream else b""
        if len(raw) > MAX_SAVED_FILTER_BYTES:
            raise ParseError("The saved filter is too large.")
        return super().parse(io.BytesIO(raw), media_type, parser_context)

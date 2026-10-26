"""Query-string parsing that never raises.

A query string is the visitor's to write, so ``/?genres=abc`` or
``/api/games/?limit=1.5`` is not an error in our code. Each helper here
answers a malformed value the way an absent one would be answered, rather
than letting a bare ``int()`` turn it into a 500.
"""

# SQLite stores integers in eight bytes and raises OverflowError on anything
# wider, so a twenty-digit "id" crashed the query rather than matching nothing.
MAX_INT = 2**63 - 1


def parse_int(raw, default=None):
    """An integer parameter, or ``default`` if it is missing or malformed."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if -MAX_INT <= value <= MAX_INT else default


def parse_id_list(raw):
    """A comma-separated id parameter, ignoring anything that is not an id."""
    if not raw:
        return []
    ids = []
    for part in raw.split(","):
        part = part.strip()
        # isascii: str.isdigit() also accepts "²", which int() then rejects.
        # The length check comes before int(), which refuses any string of
        # more than 4300 digits with a ValueError; 19 digits hold MAX_INT.
        if (
            part.isascii()
            and part.isdigit()
            and len(part) <= 19
            and int(part) <= MAX_INT
        ):
            ids.append(int(part))
    return ids


def parse_limit(raw, default, maximum=20):
    """A result limit, clamped to ``1..maximum`` and never raising."""
    value = parse_int(raw)
    if value is None:
        return default
    return max(1, min(value, maximum))

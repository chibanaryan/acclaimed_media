"""Heading text for a filtered ranking page.

The games rankings page composes its heading from the filter state -
"Nintendo Switch Action Games of the 1990s" - and derives the page title, the
og:title and the CSV filename from it. The album page had a much smaller
version of its own that knew only about the search box and the year range,
so filtering by genre left the heading saying "Most Acclaimed Albums" with no
hint of what was being shown.

These are the pieces both share. Phrasing avoids "best" and "top": the
rankings aggregate other people's lists, and the headings say so.

A heading takes three forms (``keyword_title``, the heading itself and
``short_title``); CLAUDE.md's "The rankings heading and the tab title" says
which goes where.
"""

ALL_TIME = "All Time"

# What a rankings page's title says for search engines and shared links.
KEYWORD_PREFIX = "Most Acclaimed"


def join_names(names):
    """Join names with commas and an "and" before the last."""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def build_time_window(start_year, end_year, min_year, max_year):
    """A human-readable time window for headings and filenames.

    A range covering everything reads "All Time"; a whole decade reads "the
    1990s"; a single year is itself; any other range stops at the years there are.
    """
    if start_year is None or end_year is None:
        return ""
    if start_year <= min_year and end_year >= max_year:
        return ALL_TIME
    if start_year == end_year:
        return str(start_year)
    if start_year % 10 == 0 and end_year == start_year + 9:
        return f"the {start_year}s"
    # A drag to a decade's label runs to its 9, past a last year of 2026, and
    # a heading should not name years with nothing in them. A range with nothing
    # in it at all says what was asked for.
    overlaps = end_year >= min_year and start_year <= max_year
    first = max(start_year, min_year) if overlaps else start_year
    last = min(end_year, max_year) if overlaps else end_year
    return str(first) if first == last else f"{first}-{last}"


def keyword_title(heading, is_search=False):
    """The heading as search engines and shared links see it.

    The prefix carries the words people search for ("most acclaimed albums of
    the 1990s"), so it stays on the ``<title>`` of the URLs Google indexes -
    the bare rankings page and the SEO landing pages - on ``og:title``, the
    ItemList and the CSV filename, which all leave the page's context. The
    on-page heading and the tab of a filtered page, whose canonical link is
    the bare path, go without it. A search's heading is left as it is.
    """
    return heading if is_search else f"{KEYWORD_PREFIX} {heading}"


def short_title(subjects, window, statuses=""):
    """The tab title of a filtered page: its filters, most telling first.

    "Rock · 1960s · Heard". The repeated prefix and noun are what made every
    tab read "Most Acclaimed Al..." whatever was filtered, so this keeps only
    what differs between pages; the site's name follows in the suffix. A
    range covering everything is said only when nothing else is.
    """
    subjects = [subject for subject in subjects if subject]
    if window == ALL_TIME and (subjects or statuses):
        window = ""
    window = window.removeprefix("the ")
    return " · ".join(part for part in (*subjects, window, statuses) if part) or (
        ALL_TIME
    )

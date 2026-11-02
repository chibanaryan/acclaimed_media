"""Heading text for a filtered ranking page.

The games rankings page composes its heading from the filter state - "Most
Acclaimed Nintendo Switch Action Games of the 1990s" - and reuses it as the
page title, the og:title and the CSV filename. The album page had a much
smaller version of its own that knew only about the search box and the year
range, so filtering by genre left the heading saying "Most Acclaimed Albums"
with no hint of what was being shown.

These are the pieces both share. Phrasing avoids "best" and "top": the
rankings aggregate other people's lists, and the headings say so.
"""


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
        return "All Time"
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


# The tab title of a filtered page lists its facets, the distinguishing part
# first, where the heading phrases them as a sentence. Only the indexable
# pages - unfiltered, or a landing page showing its own filters - need the
# heading's "Most Acclaimed ..." wording in the tab: every query-string state
# canonicalizes to its bare path, so its title is never what a search shows.
SHORT_TITLE_SEPARATOR = " · "


def short_time_window(start_year, end_year, min_year, max_year):
    """``build_time_window`` for a tab title: "1990s", and nothing for all time."""
    window = build_time_window(start_year, end_year, min_year, max_year)
    if window == "All Time":
        return ""
    return window.removeprefix("the ")


def short_title(parts):
    """Join a filtered page's facet labels, leaving out the empty ones."""
    return SHORT_TITLE_SEPARATOR.join(part for part in parts if part)

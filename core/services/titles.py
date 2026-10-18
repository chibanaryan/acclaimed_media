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
    1990s"; a single year is itself.
    """
    if start_year is None or end_year is None:
        return ""
    if start_year <= min_year and end_year >= max_year:
        return "All Time"
    if start_year == end_year:
        return str(start_year)
    if start_year % 10 == 0 and end_year == start_year + 9:
        return f"the {start_year}s"
    return f"{start_year}-{end_year}"

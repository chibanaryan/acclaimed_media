"""CSV that a spreadsheet opens as text, never as a formula.

A cell starting ``=``, ``+``, ``-`` or ``@`` (or a tab or carriage return
before one) is run as a formula by Excel, LibreOffice and Google Sheets when
the download is opened. Names come from the release files and from IGDB and
Wikidata, which the site does not write: Ed Sheeran's "+" and "=" are real
albums. Such a cell is prefixed with an apostrophe, which the spreadsheets
take as "text" and do not show (OWASP's advice for CSV injection).
"""

import csv

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def neutralise(value):
    """``value``, made safe to open: text only, numbers as they are."""
    if isinstance(value, str) and value.startswith(FORMULA_STARTS):
        return "'" + value
    return value


class SafeWriter:
    """`csv.writer`, with every cell passed through `neutralise`."""

    def __init__(self, stream):
        self._writer = csv.writer(stream)

    def writerow(self, row):
        return self._writer.writerow([neutralise(cell) for cell in row])

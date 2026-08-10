"""Read the tabular files in this pipeline.

Three shapes turn up:

* the HTML file OOTP writes for `Report -> Write report to disk`;
* that same table copied out of the browser - tab-separated, occasionally
  comma-separated if you exported it that way;
* the calculator's `*-projections.csv` download - comma-separated.

All three are read here so format guessing lives in one place. Reading the
HTML directly means the OOTP export can be used as-is, with no copy step.
"""

from __future__ import annotations

import csv
import io
from html.parser import HTMLParser


class _TableParser(HTMLParser):
    """Collect every <table> in a document as lists of cell text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            # &nbsp; arrives as U+00A0 and would otherwise survive stripping.
            self._row.append("".join(self._cell).replace("\xa0", " ").strip())
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_html(text: str) -> tuple[list[str], list[list[str]]]:
    """Pull the player table out of an OOTP HTML report.

    OOTP's reports wrap the real table in layout tables, so the widest one
    wins - the player grid has far more columns than any chrome around it.
    """
    parser = _TableParser()
    parser.feed(text)
    tables = [t for t in parser.tables if len(t) >= 2]
    if not tables:
        raise ValueError("no table with a header and at least one row was found "
                         "in this HTML file")

    def width(table: list[list[str]]) -> int:
        return max(len(row) for row in table)

    best = max(tables, key=lambda t: (width(t), len(t)))
    columns = width(best)
    header = best[0]
    rows = [row for row in best[1:] if any(cell for cell in row)]
    # Layout wrappers sometimes prepend a title row narrower than the grid.
    if len(header) < columns:
        for index, row in enumerate(best):
            if len(row) == columns:
                header, rows = row, [r for r in best[index + 1:] if any(r)]
                break
    return header, rows


def looks_like_html(text: str) -> bool:
    """Markup starts with a tag; a CSV or TSV never does.

    Deliberately not "does it contain <table> anywhere" - a CSV cell can hold
    the literal text, and misrouting real data to the HTML parser loses it.
    """
    return text.lstrip().startswith("<")


def read_table(path: str) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows) from an OOTP HTML report, a CSV, or a TSV."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as handle:
        text = handle.read()
    return parse_table(text)


def parse_table(text: str) -> tuple[list[str], list[list[str]]]:
    if not text.strip():
        raise ValueError("file is empty")

    if looks_like_html(text):
        return parse_html(text)

    first_line = text.splitlines()[0]
    # A tab anywhere in the header settles it; OOTP's report tables are pasted
    # tab-separated and their names can legitimately contain commas.
    delimiter = "\t" if "\t" in first_line else ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if row]
    if not rows:
        raise ValueError("file has no rows")
    return rows[0], rows[1:]


def write_tsv(path: str, headers: list[str], rows: list[list[str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write("\t".join(headers) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")

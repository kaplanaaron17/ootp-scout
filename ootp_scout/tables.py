"""Read the tabular files in this pipeline.

Two shapes turn up:

* the OOTP report you copy out of the browser - tab-separated, occasionally
  comma-separated if you exported it that way;
* the calculator's `*-projections.csv` download - comma-separated.

Both are read here so delimiter guessing lives in one place.
"""

from __future__ import annotations

import csv
import io


def read_table(path: str) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows) from a CSV or TSV file."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as handle:
        text = handle.read()
    return parse_table(text)


def parse_table(text: str) -> tuple[list[str], list[list[str]]]:
    if not text.strip():
        raise ValueError("file is empty")

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

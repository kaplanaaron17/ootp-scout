"""Read the WAR projections downloaded from ootpcalculator.com."""

from __future__ import annotations

from dataclasses import dataclass

from . import tables


@dataclass
class Projection:
    name: str
    position: str
    war: float
    stats: dict[str, str]


def _find(headers: list[str], *wanted: str) -> int | None:
    lowered = [h.strip().lower() for h in headers]
    for target in wanted:
        if target.lower() in lowered:
            return lowered.index(target.lower())
    return None


def load_projections(path: str) -> tuple[list[Projection], list[tuple[int, str]]]:
    headers, rows = tables.read_table(path)

    war_index = _find(headers, "WAR")
    name_index = _find(headers, "Name")
    if war_index is None or name_index is None:
        raise ValueError(
            f"{path} has no {'WAR' if war_index is None else 'Name'} column - "
            "this should be the *-projections.csv downloaded from "
            "ootpcalculator.com with the 'Download CSV' button. "
            f"Found: {', '.join(headers)}")
    position_index = _find(headers, "Pos", "POS", "Position")

    projections: list[Projection] = []
    problems: list[tuple[int, str]] = []

    for line_number, cells in enumerate(rows, start=2):
        if len(cells) != len(headers):
            # The calculator builds its CSV by joining on commas without
            # quoting, so a player whose name contains a comma splits into an
            # extra column. Say so plainly rather than silently dropping him.
            problems.append((line_number, f"{len(cells)} columns, expected "
                                          f"{len(headers)} (a comma in a "
                                          "player name will do this)"))
            continue
        name = cells[name_index].strip()
        raw_war = cells[war_index].strip()
        try:
            war = float(raw_war)
        except ValueError:
            problems.append((line_number, f"{name or 'row'}: WAR={raw_war!r} "
                                          "is not a number"))
            continue
        projections.append(Projection(
            name=name,
            position=cells[position_index].strip() if position_index is not None else "",
            war=war,
            stats={h.strip(): c.strip() for h, c in zip(headers, cells)},
        ))
    return projections, problems


def index_by_name(projections: list[Projection]) -> tuple[dict[str, Projection],
                                                          set[str]]:
    """Index projections by lowercased name, reporting duplicates.

    Duplicate names are dropped from the index rather than resolved by guessing;
    the caller reports them so the human can rename or split the pool.
    """
    index: dict[str, Projection] = {}
    duplicates: set[str] = set()
    for projection in projections:
        key = projection.name.strip().lower()
        if key in index:
            duplicates.add(projection.name)
        index[key] = projection
    for name in duplicates:
        index.pop(name.strip().lower(), None)
    return index, duplicates

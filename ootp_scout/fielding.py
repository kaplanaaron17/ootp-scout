"""Fielding at every position, from OOTP's own position ratings.

The calculator projects a hitter's glove from one number, the DEF rating the
batting views carry, and charges it at whatever position he is listed at. OOTP
also rates every player at every position - C, 1B, 2B, 3B, SS, LF, CF, RF -
on the same scale as everything else, folding range, arm, error and the rest
into one figure per position. That is exactly the input the calculator's zone
rating formula takes, so each position is run through it in turn:

    Fld at X     = zone runs from his X rating
    PosAdj at X  = the positional adjustment for X
    WAR at X     = his WAR, with his Fld + PosAdj swapped for X's

Everything else about the hitter - his bat, his legs, his playing time - is
the same wherever he stands, so only the defensive terms move.

The ratings arrive either as extra columns on a batting ratings view (a custom
view in OOTP) or from a separate Fielding Ratings export, which is matched to
the hitters already stored by name.
"""

from __future__ import annotations

from .projection import (FORMULA_BATTING, POSITION_RUNS, convert_rating)

POSITIONS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")

# Headings OOTP might use for a position rating. The plain abbreviation is
# what its fielding ratings view writes; the others cover custom views.
ALIASES = {position: (position, f"{position} RAT", f"{position} Rating")
           for position in POSITIONS}


def zone_runs(rating_1to250: float) -> float:
    """Runs saved over a 550 at-bat season by a glove of this rating.

    The calculator's own formula, the one that turns DEF into Fld.
    """
    f = FORMULA_BATTING["zr"]
    index = int(rating_1to250 > 100)
    return rating_1to250 * f["slope"][index] + f["intercept"][index]


def _number(raw) -> float | None:
    text = str(raw or "").strip()
    if not text or text in {"-", "--", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _clean(header: str) -> str:
    return header.replace("▾", "").replace("▴", "").strip()


def find_columns(headers) -> dict[str, str]:
    """Which export column carries each position's rating, if any."""
    present = {_clean(h).upper(): _clean(h) for h in headers}
    found = {}
    for position, names in ALIASES.items():
        for name in names:
            if name.upper() in present:
                found[position] = present[name.upper()]
                break
    return found


def is_fielding_export(headers) -> bool:
    """A report carrying every position's rating and a player name."""
    cleaned = {_clean(h) for h in headers}
    return "Name" in cleaned and len(find_columns(headers)) == len(POSITIONS)


def read_ratings(values: dict, columns: dict[str, str]) -> dict[str, float]:
    """A player's displayed position ratings. A blank or 0 means he cannot
    play there, and is left out rather than projected as a dreadful one."""
    out = {}
    for position, column in columns.items():
        number = _number(values.get(column))
        if number is not None and number > 0:
            out[position] = number
    return out


def position_fields(stored: dict, ratings: dict[str, float],
                    scale: str) -> dict[str, float]:
    """Fld, PosAdj and WAR at each position, ready to store with his line.

    `stored` is his projected season as statline keeps it; `ratings` his
    displayed position ratings on `scale`. Positions whose rating does not
    convert - off the scale entirely - are skipped.
    """
    at_bats = stored.get("at_bats")
    war = stored.get("war")
    if not ratings or not at_bats or war is None:
        return {}
    season = at_bats / 550
    current = ((stored.get("fielding_runs") or 0.0)
               + (stored.get("position_runs") or 0.0))
    out: dict[str, float] = {}
    for position, displayed in ratings.items():
        try:
            internal = convert_rating(scale, displayed)
        except (ValueError, KeyError):
            continue
        fld = zone_runs(internal) * season
        adjustment = POSITION_RUNS[position] * season
        out[f"rating_{position}"] = displayed
        out[f"fld_{position}"] = round(fld, 4)
        out[f"def_{position}"] = round(fld + adjustment, 4)
        out[f"war_{position}"] = round(war + (fld + adjustment - current) / 10,
                                       4)
    return out


def stored_ratings(stored: dict | None) -> dict[str, float]:
    """The position ratings a stored line was projected from."""
    if not stored:
        return {}
    return {p: stored[f"rating_{p}"] for p in POSITIONS
            if stored.get(f"rating_{p}") is not None}


def best_position(stored: dict | None) -> tuple[str, float] | None:
    """Where he projects for the most WAR, and how much."""
    if not stored:
        return None
    options = [(stored[f"war_{p}"], p) for p in POSITIONS
               if stored.get(f"war_{p}") is not None]
    if not options:
        return None
    war, position = max(options)
    return position, war


def table(stored: dict | None) -> list[tuple[str, float, float, float, float]]:
    """(position, rating, Fld, Def, WAR) for every position he can play,
    best first."""
    if not stored:
        return []
    rows = [(p, stored[f"rating_{p}"], stored[f"fld_{p}"], stored[f"def_{p}"],
             stored[f"war_{p}"])
            for p in POSITIONS if stored.get(f"war_{p}") is not None]
    return sorted(rows, key=lambda r: r[4], reverse=True)

"""The four OOTP report views ootpcalculator.com accepts.

These header lists are the calculator's own contract, taken from its client-side
validation. Matching them exactly beats fuzzy header-guessing: an export that
does not match one of these four is an export the calculator will reject anyway,
so it is better to say so up front than to half-parse it.

Note `CON` is Contact in the batter views and Control in the pitcher views. The
column name alone is ambiguous; only the view it appears in disambiguates it.
That is the main reason parsing is view-based rather than column-based.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BATTER = "batter"
PITCHER = "pitcher"
CURRENT = "current"
POTENTIAL = "potential"


@dataclass(frozen=True)
class View:
    role: str
    mode: str
    headers: tuple[str, ...]
    optional: tuple[str, ...]
    grade_column: str
    rating_columns: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.role}-{self.mode}"

    @property
    def ootp_view_name(self) -> str:
        kind = "Batting" if self.role == BATTER else "Pitching"
        return f"{kind} Ratings" + (" (Potential)" if self.mode == POTENTIAL else "")

    @property
    def calculator_type(self) -> str:
        """What the site calls this, which is also its download filename.

        Not the same word as `role`: the site says "batting"/"pitching" and
        names its export <type>-projections.csv, so telling the user to look
        for "batter-projections.csv" sends them after a file that never exists.
        """
        return "batting" if self.role == BATTER else "pitching"


VIEWS: tuple[View, ...] = (
    View(
        role=BATTER, mode=CURRENT,
        headers=("POS", "#", "Name", "Inf", "Age", "B", "T", "OVR", "CON", "GAP",
                 "POW", "EYE", "K's", "CON vL", "POW vL", "CON vR", "POW vR",
                 "BUN", "BFH", "SPE", "STE", "DEF", "SctAcc"),
        optional=("BABIP", "SR"),
        grade_column="OVR",
        rating_columns=("CON", "GAP", "POW", "EYE", "K's", "CON vL", "POW vL",
                        "CON vR", "POW vR", "BUN", "BFH", "SPE", "STE", "DEF"),
    ),
    View(
        role=BATTER, mode=POTENTIAL,
        headers=("POS", "#", "Name", "Inf", "Age", "B", "T", "POT", "CON P",
                 "GAP P", "POW P", "EYE P", "K P", "SPE", "STE", "RUN", "DEF",
                 "SctAcc"),
        optional=("BABIP", "SR"),
        grade_column="POT",
        rating_columns=("CON P", "GAP P", "POW P", "EYE P", "K P", "SPE", "STE",
                        "RUN", "DEF"),
    ),
    View(
        role=PITCHER, mode=CURRENT,
        headers=("POS", "#", "Name", "Inf", "Age", "B", "T", "OVR", "STU", "MOV",
                 "CON", "STU vL", "STU vR", "VELO", "STM", "G/F", "HLD", "SctAcc"),
        optional=("HRA", "BABIP"),
        grade_column="OVR",
        rating_columns=("STU", "MOV", "CON", "STU vL", "STU vR", "STM", "HLD"),
    ),
    View(
        role=PITCHER, mode=POTENTIAL,
        headers=("POS", "#", "Name", "Inf", "Age", "B", "T", "POT", "STU P",
                 "MOV P", "CON P", "VELO", "STM", "G/F", "HLD", "SctAcc"),
        optional=("HRA", "BABIP"),
        grade_column="POT",
        rating_columns=("STU P", "MOV P", "CON P", "STM", "HLD"),
    ),
)

# Scales the calculator offers. The 20-80 scale additionally requires every
# rating to be a multiple of 5 - OOTP rounds to the nearest grade when it
# displays that scale, so it carries strictly less information than 1-100.
SCALES = ("1 to 5", "2 to 8", "1 to 10", "1 to 20", "20 to 80", "1 to 100")
SCALE_STEP_5 = "20 to 80"


@dataclass
class ExportRow:
    """One player as exported from OOTP."""

    name: str
    position: str
    grade: float | None
    values: dict[str, str] = field(default_factory=dict)
    line_number: int = 0

    @property
    def scouting_accuracy(self) -> str:
        return self.values.get("SctAcc", "").strip() or "unknown"

    @property
    def age(self) -> str:
        return self.values.get("Age", "").strip()

    @property
    def is_pitcher(self) -> bool:
        return self.position.upper() in {"SP", "RP", "CL", "P", "MR", "SR"}

    @property
    def meta(self) -> dict[str, str]:
        return {"scouting_accuracy": self.scouting_accuracy, "age": self.age}


def _clean(header: str) -> str:
    return header.replace("▾", "").replace("▴", "").strip()


def identify_view(headers: list[str]) -> View:
    """Pick the view whose required headers are all present.

    OOTP's report tables may carry extra columns and a sort arrow glyph on the
    sorted column; both are tolerated. Ambiguity is resolved toward the view
    that matches more of its optional columns too.
    """
    cleaned = [_clean(h) for h in headers]
    present = set(cleaned)

    candidates = [v for v in VIEWS if set(v.headers) <= present]
    if not candidates:
        best = max(VIEWS, key=lambda v: len(set(v.headers) & present))
        missing = [h for h in best.headers if h not in present]
        raise ValueError(
            "these columns do not match any view the calculator accepts. "
            f"Closest is the {best.ootp_view_name} view, which is missing: "
            f"{', '.join(missing)}. In OOTP, switch to that view before "
            "writing the report to disk.")
    if len(candidates) > 1:
        candidates.sort(key=lambda v: len(set(v.optional) & present), reverse=True)
    return candidates[0]


def _to_float(raw: str) -> float | None:
    text = (raw or "").strip()
    if not text or text in {"-", "--", "-  ", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_rows(headers: list[str], rows: list[list[str]], view: View
               ) -> tuple[list[ExportRow], list[tuple[int, str]]]:
    """Turn raw cells into ExportRows, reporting rows that could not be used."""
    cleaned = [_clean(h) for h in headers]
    index = {h: i for i, h in enumerate(cleaned)}
    parsed: list[ExportRow] = []
    problems: list[tuple[int, str]] = []

    for line_number, cells in enumerate(rows, start=2):
        if not any(cell.strip() for cell in cells):
            continue
        if len(cells) < len(cleaned):
            problems.append((line_number, f"has {len(cells)} columns, "
                                          f"expected {len(cleaned)}"))
            continue
        values = {header: cells[position] for header, position in index.items()
                  if position < len(cells)}
        name = values.get("Name", "").strip()
        if not name:
            problems.append((line_number, "no Name value"))
            continue
        parsed.append(ExportRow(
            name=name,
            position=values.get("POS", "").strip(),
            grade=_to_float(values.get(view.grade_column, "")),
            values=values,
            line_number=line_number,
        ))
    return parsed, problems


MLB_LEVELS = {"MLB", "ML", "MAJ", "MAJORS", ""}


def levels_present(rows: list[ExportRow]) -> dict[str, int]:
    """Count the levels in the export, if it carries a Lev column.

    Matters because OOTP can display ratings *relative to the player's own
    level*. Under that setting a AAA player's 60 means "60 for AAA", and the
    calculator - which projects MLB production from whatever numbers it is
    given - would read it as MLB talent and badly overrate every minor leaguer.
    The tool cannot see the setting, so it surfaces the exposure instead.
    """
    counts: dict[str, int] = {}
    for row in rows:
        level = (row.values.get("Lev") or row.values.get("Level") or "").strip()
        if level:
            counts[level] = counts.get(level, 0) + 1
    return counts


def non_mlb_levels(rows: list[ExportRow]) -> dict[str, int]:
    return {level: count for level, count in levels_present(rows).items()
            if level.upper() not in MLB_LEVELS}


def validate_ratings(rows: list[ExportRow], view: View, scale: str
                     ) -> list[tuple[str, str]]:
    """Pre-check the rules the calculator enforces, so failures are legible.

    The site rejects the whole paste on the first bad cell with a generic
    message; catching it here names the player and the column instead.
    """
    complaints: list[tuple[str, str]] = []
    if scale != SCALE_STEP_5:
        return complaints
    for row in rows:
        for column in view.rating_columns:
            raw = row.values.get(column, "").strip()
            if not raw or raw == "-":
                continue
            value = _to_float(raw)
            if value is None:
                complaints.append((row.name, f"{column}={raw!r} is not a number"))
            elif value % 5 != 0:
                complaints.append(
                    (row.name, f"{column}={raw} is not a multiple of 5"))
    return complaints

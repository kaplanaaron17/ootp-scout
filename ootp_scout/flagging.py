"""Find players whose projection outruns their scouting grade.

The point is deliberately *not* "rank by projected WAR" - that just re-lists the
players you already know are good. Instead, fit projected WAR against the
overall grade across the whole pool, then rank by residual: how far a player
sits above the WAR his grade predicts. Those are the players the grade
underrates, which is what "undervalued" has to mean if it is to mean anything.

Two things are held constant while measuring that gap:

* **role** - hitters and pitchers are fit separately by default; their WAR
  distributions and their relationship to the grade differ enough that pooling
  them leaks one group's shape into the other's residuals.
* **position** - each position gets its own intercept shift within the fit, so
  a catcher is measured against catchers rather than against first basemen.
  Positions share one slope, which is what makes this work on thin positions:
  fitting DH separately on four players would produce noise, but a DH offset on
  a shared slope is a single well-supported number.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from statistics import fmean, pstdev

# A position needs at least this many players before it earns its own offset.
# Below it, the player is measured against the group's reference position - a
# bounded error, and better than fitting a term to two data points.
MIN_PLAYERS_PER_POSITION = 4

_POSITION_ALIASES = {"CL": "RP", "MR": "RP", "SR": "RP", "P": "SP"}


def normalize_position(position: str) -> str:
    text = (position or "").strip().upper()
    return _POSITION_ALIASES.get(text, text)


@dataclass
class Subject:
    """A player carrying both his grade and his projected WAR."""

    name: str
    position: str
    grade: float
    war: float
    is_pitcher: bool = False
    meta: dict[str, str] = field(default_factory=dict)
    # Runs-allowed WAR, for pitchers whose projection carried IP and R.
    rwar: float | None = None
    # The player's raw tool ratings, keyed by the export's own column names.
    ratings: dict[str, str] = field(default_factory=dict)

    @property
    def war_gap(self) -> float | None:
        """rWAR minus WAR. Negative means runs allowed lag the peripherals."""
        return None if self.rwar is None else self.rwar - self.war

    @property
    def normalized_position(self) -> str:
        return normalize_position(self.position)


def solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for a small dense system."""
    size = len(matrix)
    augmented = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]

    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot][col]) < 1e-9:
            raise ValueError("system is singular - a predictor is constant or "
                             "duplicated across every player in this group")
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        for row in range(col + 1, size):
            factor = augmented[row][col] / augmented[col][col]
            for k in range(col, size + 1):
                augmented[row][k] -= factor * augmented[col][k]

    result = [0.0] * size
    for row in reversed(range(size)):
        total = augmented[row][size] - sum(augmented[row][c] * result[c]
                                           for c in range(row + 1, size))
        result[row] = total / augmented[row][row]
    return result


def least_squares(design: list[list[float]], targets: list[float]) -> list[float]:
    """Solve the normal equations for an arbitrary design matrix."""
    if not design:
        raise ValueError("no rows to fit")
    width = len(design[0])
    if len(design) <= width:
        raise ValueError(f"need more than {width} players to fit {width} terms")
    normal = [[sum(row[i] * row[j] for row in design) for j in range(width)]
              for i in range(width)]
    rhs = [sum(row[i] * target for row, target in zip(design, targets))
           for i in range(width)]
    return solve(normal, rhs)


def fit_polynomial(xs: list[float], ys: list[float], degree: int = 1) -> list[float]:
    """Least-squares polynomial fit, returned lowest-order coefficient first."""
    if len(xs) != len(ys):
        raise ValueError("xs and ys must be the same length")
    design = [[x ** power for power in range(degree + 1)] for x in xs]
    return least_squares(design, ys)


def evaluate(coefficients: list[float], x: float) -> float:
    return sum(c * (x ** i) for i, c in enumerate(coefficients))


@dataclass
class GroupFit:
    """The model fitted to one role group."""

    group: str
    count: int
    coefficients: list[float]
    residual_sd: float
    degree: int = 1
    positions: list[str] = field(default_factory=list)
    reference_position: str = ""
    note: str = ""

    @property
    def slope(self) -> float:
        return self.coefficients[1] if len(self.coefficients) > 1 else 0.0

    @property
    def position_offsets(self) -> dict[str, float]:
        """Wins added or removed for each position, versus the reference."""
        start = self.degree + 1
        return {name: self.coefficients[start + i]
                for i, name in enumerate(self.positions)}

    def predict(self, grade: float, position: str) -> float:
        value = sum(self.coefficients[power] * (grade ** power)
                    for power in range(self.degree + 1))
        offsets = self.position_offsets
        return value + offsets.get(normalize_position(position), 0.0)


@dataclass
class Finding:
    subject: Subject
    expected_war: float
    residual: float
    z_score: float
    group: str
    note: str = ""

    @property
    def scouting_accuracy(self) -> str:
        return self.subject.meta.get("scouting_accuracy", "") or "unknown"


@dataclass
class Analysis:
    findings: list[Finding]
    fits: list[GroupFit]


def _choose_positions(members: list[Subject]) -> tuple[list[str], str]:
    """Positions that earn their own offset, plus the reference position.

    The most common position is the reference and gets no term of its own -
    including every position alongside an intercept would make the design
    matrix singular.
    """
    counts = Counter(s.normalized_position for s in members if s.normalized_position)
    if not counts:
        return [], ""
    reference = counts.most_common(1)[0][0]
    positions = sorted(name for name, count in counts.items()
                       if name != reference and count >= MIN_PLAYERS_PER_POSITION)
    return positions, reference


def _fit_group(members: list[Subject], degree: int, position_adjust: bool
               ) -> GroupFit:
    grades = [s.grade for s in members]
    wars = [s.war for s in members]

    positions, reference = ([], "")
    if position_adjust:
        positions, reference = _choose_positions(members)

    # Walk the model down until it is supported by the data: full model, then
    # without position terms, then a lower degree, then the group mean.
    attempts: list[tuple[int, list[str], str]] = []
    for candidate_degree in range(degree, 0, -1):
        if positions:
            attempts.append((candidate_degree, positions, ""))
        attempts.append((candidate_degree, [], "" if not positions else
                         "position offsets dropped (not enough players)"))

    for candidate_degree, candidate_positions, note in attempts:
        design = []
        for subject in members:
            row = [subject.grade ** power for power in range(candidate_degree + 1)]
            row += [1.0 if subject.normalized_position == name else 0.0
                    for name in candidate_positions]
            design.append(row)
        try:
            coefficients = least_squares(design, wars)
        except ValueError:
            continue
        fit = GroupFit(group="", count=len(members), coefficients=coefficients,
                       residual_sd=0.0, degree=candidate_degree,
                       positions=candidate_positions,
                       reference_position=reference if candidate_positions else "",
                       note=note)
        if candidate_degree < degree and not note:
            fit.note = f"degree reduced to {candidate_degree}"
        return fit

    # Nothing could be fitted - compare against the mean, which is still a
    # defensible baseline and keeps the ranking meaningful.
    return GroupFit(group="", count=len(members), coefficients=[fmean(wars)],
                    residual_sd=0.0, degree=0, positions=[],
                    note="flat baseline (the grade column carries no signal here)")


def analyze(subjects: list[Subject], degree: int = 1,
            split_by_role: bool = True, position_adjust: bool = True) -> Analysis:
    """Fit WAR against the grade and score every player's residual."""
    groups: dict[str, list[Subject]] = {}
    for subject in subjects:
        key = ("pitchers" if subject.is_pitcher else "hitters") if split_by_role else "all"
        groups.setdefault(key, []).append(subject)

    findings: list[Finding] = []
    fits: list[GroupFit] = []

    for group, members in sorted(groups.items()):
        fit = _fit_group(members, degree, position_adjust)
        fit.group = group

        residuals = [s.war - fit.predict(s.grade, s.position) for s in members]
        fit.residual_sd = pstdev(residuals) if len(residuals) > 1 else 0.0
        fits.append(fit)

        for subject, residual in zip(members, residuals):
            findings.append(Finding(
                subject=subject,
                expected_war=fit.predict(subject.grade, subject.position),
                residual=residual,
                z_score=residual / fit.residual_sd if fit.residual_sd > 1e-9 else 0.0,
                group=group,
                note=fit.note))

    findings.sort(key=lambda f: f.residual, reverse=True)
    return Analysis(findings=findings, fits=fits)


def select(findings: list[Finding], limit: int | None = None,
           min_z: float | None = None) -> list[Finding]:
    chosen = findings
    if min_z is not None:
        chosen = [f for f in chosen if f.z_score >= min_z]
    if limit is not None:
        chosen = chosen[:limit]
    return chosen


def select_overrated(findings: list[Finding], limit: int | None = None,
                     max_z: float | None = None) -> list[Finding]:
    """The other end of the same list: worst shortfall first.

    A player here projects well below what his grade implies - the grade is
    flattering him. Useful in the opposite direction from the targets list:
    these are the ones to trade away, or to stop paying up for.
    """
    chosen = sorted(findings, key=lambda f: f.residual)
    if max_z is not None:
        chosen = [f for f in chosen if f.z_score <= max_z]
    if limit is not None:
        chosen = chosen[:limit]
    return chosen

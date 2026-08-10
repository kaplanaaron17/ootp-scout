"""Find players whose projection outruns their scouting grade.

The point is deliberately *not* "rank by projected WAR" - that just re-lists the
players you already know are good. Instead, fit projected WAR against the
overall grade across the whole pool, then rank by residual: how far a player
sits above the WAR his grade predicts. Those are the players the grade
underrates, which is what "undervalued" has to mean if it is to mean anything.

Hitters and pitchers are fit separately by default; their WAR distributions and
their relationship to the overall grade are different enough that pooling them
would leak one group's shape into the other's residuals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean, pstdev


@dataclass
class Subject:
    """A player carrying both his grade and his projected WAR."""

    name: str
    position: str
    grade: float
    war: float
    is_pitcher: bool = False
    meta: dict[str, str] = field(default_factory=dict)


def solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for a small dense system."""
    size = len(matrix)
    augmented = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]

    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            raise ValueError("system is singular - the grade column is probably "
                             "constant across every player in this group")
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


def fit_polynomial(xs: list[float], ys: list[float], degree: int = 1) -> list[float]:
    """Least-squares polynomial fit, returned lowest-order coefficient first."""
    if len(xs) != len(ys):
        raise ValueError("xs and ys must be the same length")
    if len(xs) <= degree:
        raise ValueError(f"need more than {degree} points to fit degree {degree}")

    size = degree + 1
    power_sums = [sum(x ** p for x in xs) for p in range(2 * degree + 1)]
    matrix = [[power_sums[i + j] for j in range(size)] for i in range(size)]
    rhs = [sum(y * (x ** i) for x, y in zip(xs, ys)) for i in range(size)]
    return solve(matrix, rhs)


def evaluate(coefficients: list[float], x: float) -> float:
    return sum(c * (x ** i) for i, c in enumerate(coefficients))


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
class GroupFit:
    group: str
    count: int
    coefficients: list[float]
    residual_sd: float


@dataclass
class Analysis:
    findings: list[Finding]
    fits: list[GroupFit]


def analyze(subjects: list[Subject], degree: int = 1,
            split_by_role: bool = True) -> Analysis:
    """Fit WAR against the overall grade and score every player's residual."""
    groups: dict[str, list[Subject]] = {}
    for subject in subjects:
        key = ("pitchers" if subject.is_pitcher else "hitters") if split_by_role else "all"
        groups.setdefault(key, []).append(subject)

    findings: list[Finding] = []
    fits: list[GroupFit] = []

    for group, members in sorted(groups.items()):
        xs = [s.grade for s in members]
        ys = [s.war for s in members]

        effective_degree = degree
        while effective_degree > 0 and len(members) <= effective_degree + 1:
            effective_degree -= 1

        try:
            coefficients = fit_polynomial(xs, ys, effective_degree)
        except ValueError as error:
            # Not enough spread or not enough players: fall back to comparing
            # against the group mean, which is still a defensible baseline.
            coefficients = [fmean(ys)]
            note = f"flat baseline ({error})"
        else:
            note = ""

        residuals = [s.war - evaluate(coefficients, s.grade) for s in members]
        spread = pstdev(residuals) if len(residuals) > 1 else 0.0
        fits.append(GroupFit(group=group, count=len(members),
                             coefficients=coefficients, residual_sd=spread))

        for subject, residual in zip(members, residuals):
            findings.append(Finding(
                subject=subject,
                expected_war=evaluate(coefficients, subject.grade),
                residual=residual,
                z_score=residual / spread if spread > 1e-9 else 0.0,
                group=group,
                note=note))

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

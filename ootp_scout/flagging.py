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

from dataclasses import dataclass
from statistics import fmean, pstdev

from .loading import Player


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
    # Normal equations: (X'X) b = X'y, built from power sums.
    power_sums = [sum(x ** p for x in xs) for p in range(2 * degree + 1)]
    matrix = [[power_sums[i + j] for j in range(size)] for i in range(size)]
    rhs = [sum(y * (x ** i) for x, y in zip(xs, ys)) for i in range(size)]
    return solve(matrix, rhs)


def evaluate(coefficients: list[float], x: float) -> float:
    return sum(c * (x ** i) for i, c in enumerate(coefficients))


@dataclass
class Finding:
    player: Player
    war: float
    baseline: float
    expected_war: float
    residual: float
    z_score: float
    group: str
    note: str = ""

    @property
    def scouting_accuracy(self) -> str:
        return self.player.meta.get("scouting_accuracy", "") or "unknown"


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
    excluded: list[tuple[str, str]]


def _group_of(player: Player) -> str:
    return "pitchers" if player.is_pitcher else "hitters"


def analyze(scored: list[tuple[Player, float]], mode: str, degree: int = 1,
            split_by_role: bool = True) -> Analysis:
    """Fit WAR against the overall grade and score every player's residual.

    `scored` pairs each player with the WAR projection already computed for him.
    """
    excluded: list[tuple[str, str]] = []
    usable: list[tuple[Player, float, float]] = []

    for player, war in scored:
        baseline = player.baseline(mode)
        if baseline is None:
            label = "POT" if mode == "potential" else "OVR"
            excluded.append((player.name, f"no {label} value to compare against"))
            continue
        usable.append((player, war, baseline))

    groups: dict[str, list[tuple[Player, float, float]]] = {}
    for entry in usable:
        key = _group_of(entry[0]) if split_by_role else "all"
        groups.setdefault(key, []).append(entry)

    findings: list[Finding] = []
    fits: list[GroupFit] = []

    for group, entries in sorted(groups.items()):
        xs = [baseline for _p, _w, baseline in entries]
        ys = [war for _p, war, _b in entries]

        effective_degree = degree
        while effective_degree > 0 and len(entries) <= effective_degree + 1:
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

        residuals = [war - evaluate(coefficients, baseline)
                     for _p, war, baseline in entries]
        spread = pstdev(residuals) if len(residuals) > 1 else 0.0
        fits.append(GroupFit(group=group, count=len(entries),
                             coefficients=coefficients, residual_sd=spread))

        for (player, war, baseline), residual in zip(entries, residuals):
            expected = evaluate(coefficients, baseline)
            z_score = residual / spread if spread > 1e-9 else 0.0
            findings.append(Finding(player=player, war=war, baseline=baseline,
                                    expected_war=expected, residual=residual,
                                    z_score=z_score, group=group, note=note))

    findings.sort(key=lambda f: f.residual, reverse=True)
    return Analysis(findings=findings, fits=fits, excluded=excluded)


def select(findings: list[Finding], limit: int | None = None,
           min_z: float | None = None) -> list[Finding]:
    chosen = findings
    if min_z is not None:
        chosen = [f for f in chosen if f.z_score >= min_z]
    if limit is not None:
        chosen = chosen[:limit]
    return chosen

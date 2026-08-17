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
    grade_min: float = 0.0
    grade_max: float = 0.0
    # When present, the baseline is this curve rather than the polynomial.
    curve: "MonotoneCurve | None" = None

    @property
    def slope(self) -> float:
        if self.curve is not None:
            return self.curve.slope
        return self.coefficients[1] if len(self.coefficients) > 1 else 0.0

    @property
    def position_offsets(self) -> dict[str, float]:
        """Wins added or removed for each position, versus the reference."""
        start = self.degree + 1
        return {name: self.coefficients[start + i]
                for i, name in enumerate(self.positions)}

    def predict(self, grade: float, position: str) -> float:
        offset = self.position_offsets.get(normalize_position(position), 0.0)
        if self.curve is not None:
            return self.curve.value(grade) + offset
        value = sum(self.coefficients[power] * (grade ** power)
                    for power in range(self.degree + 1))
        return value + offset

    def implied_grade(self, war: float, position: str) -> float | None:
        """The grade this WAR would carry if the fit were read backwards.

        `predict` answers "what WAR does this grade imply". This answers the
        reverse - so a player graded 35 whose projection implies 72 has the gap
        stated in the units the grade is actually written in, which is easier
        to argue with than a differential in wins.

        None when the fit carries no grade term (a flat baseline), since then
        every grade implies the same WAR and the question has no answer.
        """
        offset = self.position_offsets.get(normalize_position(position), 0.0)
        target = war - offset
        if self.curve is not None:
            return self.curve.invert(target)

        # The question is answerable when the fit depends on grade at all, not
        # merely when it has a linear term: a curve through y = k*g^2 has a
        # near-zero slope coefficient and is still perfectly invertible.
        grade_terms = self.coefficients[1:self.degree + 1]
        if self.degree < 1 or all(abs(c) < 1e-9 for c in grade_terms):
            return None
        if self.degree == 1:
            return (target - self.coefficients[0]) / self.coefficients[1]

        # Quadratic: c2*g^2 + c1*g + (c0 - target) = 0.
        c0, c1, c2 = self.coefficients[0], self.coefficients[1], self.coefficients[2]
        if abs(c2) < 1e-12:
            return (target - c0) / c1
        discriminant = c1 * c1 - 4.0 * c2 * (c0 - target)
        if discriminant < 0:
            # The curve never reaches this WAR at any grade.
            return None
        root = discriminant ** 0.5
        candidates = [(-c1 + root) / (2.0 * c2), (-c1 - root) / (2.0 * c2)]
        # Both roots are mathematically valid; the meaningful one is the branch
        # the observed grades actually sit on.
        inside = [g for g in candidates if self.grade_min <= g <= self.grade_max]
        if inside:
            return max(inside)
        midpoint = (self.grade_min + self.grade_max) / 2.0
        return min(candidates, key=lambda g: abs(g - midpoint))


@dataclass
class Finding:
    subject: Subject
    expected_war: float
    residual: float
    z_score: float
    group: str
    note: str = ""
    # The grade this player's projected WAR implies, read off the same fit.
    implied_grade: float | None = None

    @property
    def grade_gap(self) -> float | None:
        """Implied grade minus actual. Positive means the grade is too low."""
        if self.implied_grade is None:
            return None
        return self.implied_grade - self.subject.grade

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


def _fit_monotone_group(members: list[Subject], linear: GroupFit) -> GroupFit:
    """Replace a linear baseline with a monotone curve of the same shape.

    Position offsets come from the linear fit first, are subtracted off, and
    the curve is fitted to what remains. Estimating both at once would need an
    iterative scheme for very little gain: the offsets are differences between
    positions, which the overall shape barely disturbs.
    """
    offsets = linear.position_offsets
    adjusted = [s.war - offsets.get(s.normalized_position, 0.0) for s in members]
    curve = fit_monotone([s.grade for s in members], adjusted)
    return GroupFit(group=linear.group, count=linear.count,
                    coefficients=linear.coefficients,
                    residual_sd=0.0, degree=linear.degree,
                    positions=linear.positions,
                    reference_position=linear.reference_position,
                    note=linear.note, grade_min=linear.grade_min,
                    grade_max=linear.grade_max, curve=curve)


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
            split_by_role: bool = True, position_adjust: bool = True,
            shape: str = "linear") -> Analysis:
    """Fit WAR against the grade and score every player's residual.

    `shape` is "linear" for a straight line or "monotone" for a non-decreasing
    curve through binned means. The curve exists because the real relationship
    is concave: a line over-predicts at the top, which marks every high-graded
    player as overrated for no reason but the shape of the model.
    """
    groups: dict[str, list[Subject]] = {}
    for subject in subjects:
        key = ("pitchers" if subject.is_pitcher else "hitters") if split_by_role else "all"
        groups.setdefault(key, []).append(subject)

    findings: list[Finding] = []
    fits: list[GroupFit] = []

    for group, members in sorted(groups.items()):
        fit = _fit_group(members, degree, position_adjust)
        fit.group = group
        fit.grade_min = min(s.grade for s in members)
        fit.grade_max = max(s.grade for s in members)
        if shape == "monotone" and len(members) > MIN_PLAYERS_PER_POSITION:
            fit = _fit_monotone_group(members, fit)

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
                note=fit.note,
                implied_grade=fit.implied_grade(subject.war, subject.position)))

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


# --- monotone baseline -------------------------------------------------------
#
# A straight line through grade and WAR is wrong in a specific, measurable way:
# the relationship is concave, so the line over-predicts at both ends. On real
# league data every player above grade 60 drew a negative residual purely from
# that mis-shape - the model called them overrated because it expected too much
# of them, not because anything about them was disappointing.
#
# Raising the polynomial degree does not fix it. A quadratic fitted to the same
# data peaks near grade 68 and turns downward, asserting that a 75 is worse
# than a 65, and cannot be inverted above its own maximum.
#
# What is wanted is a curve that follows the data's shape while never going
# down. Grades are binned, each bin's mean is taken, and the sequence of means
# is made non-decreasing by pooling adjacent violators. Binning keeps the
# sparse top end - five players at grade 70 - from dictating a wild tail, and
# monotonicity keeps the result invertible, which the implied grade needs.

BIN_WIDTH = 5.0
MIN_BIN = 3


def pool_adjacent_violators(values: list[float], weights: list[float]
                            ) -> list[float]:
    """Least-squares fit subject to the result never decreasing.

    Walks left to right; whenever a value would dip below the block before it,
    the two blocks merge and take their weighted mean. Each block records how
    many original points it covers so it can be expanded back out at the end.
    """
    # Each block is [weighted total, weight, count].
    blocks: list[list[float]] = []
    for value, weight in zip(values, weights):
        blocks.append([value * weight, weight, 1])
        while len(blocks) > 1:
            previous, current = blocks[-2], blocks[-1]
            if previous[0] / previous[1] <= current[0] / current[1]:
                break
            blocks[-2:] = [[previous[0] + current[0],
                            previous[1] + current[1],
                            previous[2] + current[2]]]

    result: list[float] = []
    for total, weight, count in blocks:
        result.extend([total / weight] * int(count))
    return result


@dataclass
class MonotoneCurve:
    """A non-decreasing piecewise-linear baseline through binned means."""

    grades: list[float]
    wars: list[float]

    @property
    def slope(self) -> float:
        if len(self.grades) < 2:
            return 0.0
        return ((self.wars[-1] - self.wars[0])
                / (self.grades[-1] - self.grades[0]))

    def _edge_slope(self, at_start: bool) -> float:
        if len(self.grades) < 2:
            return 0.0
        i, j = (0, 1) if at_start else (-2, -1)
        span = self.grades[j] - self.grades[i]
        return (self.wars[j] - self.wars[i]) / span if span else 0.0

    def value(self, grade: float) -> float:
        if not self.grades:
            return 0.0
        if grade <= self.grades[0]:
            return self.wars[0] + (grade - self.grades[0]) * self._edge_slope(True)
        if grade >= self.grades[-1]:
            return self.wars[-1] + (grade - self.grades[-1]) * self._edge_slope(False)
        for index in range(len(self.grades) - 1):
            low, high = self.grades[index], self.grades[index + 1]
            if low <= grade <= high:
                span = high - low
                if span == 0:
                    return self.wars[index]
                share = (grade - low) / span
                return self.wars[index] + share * (self.wars[index + 1]
                                                   - self.wars[index])
        return self.wars[-1]

    def invert(self, war: float) -> float | None:
        """The grade whose baseline is `war`.

        Flat stretches map a whole range of grades to one WAR. The midpoint of
        that range is returned, because no grade inside it is a better answer
        than any other - and the flat run is found first, so a plateau at
        either end is treated as a plateau rather than as the edge.
        """
        if not self.grades:
            return None

        tolerance = 1e-9
        matching = [index for index, value in enumerate(self.wars)
                    if abs(value - war) <= tolerance]
        if matching:
            return (self.grades[matching[0]] + self.grades[matching[-1]]) / 2.0

        if war < self.wars[0]:
            slope = self._edge_slope(True)
            if abs(slope) < tolerance:
                return self.grades[0]
            return self.grades[0] + (war - self.wars[0]) / slope
        if war > self.wars[-1]:
            slope = self._edge_slope(False)
            if abs(slope) < tolerance:
                return self.grades[-1]
            return self.grades[-1] + (war - self.wars[-1]) / slope

        for index in range(len(self.grades) - 1):
            low, high = self.wars[index], self.wars[index + 1]
            if low <= war <= high and high - low > tolerance:
                share = (war - low) / (high - low)
                return self.grades[index] + share * (self.grades[index + 1]
                                                     - self.grades[index])
        return self.grades[-1]


def fit_monotone(grades: list[float], wars: list[float],
                 bin_width: float = BIN_WIDTH) -> MonotoneCurve:
    """Bin by grade, average, then force the sequence never to decrease."""
    buckets: dict[float, list[float]] = {}
    for grade, war in zip(grades, wars):
        key = round(grade / bin_width) * bin_width
        buckets.setdefault(key, []).append(war)

    # Fold bins too thin to mean anything into their neighbour, so a lone
    # player at the top cannot define the tail on his own.
    keys = sorted(buckets)
    merged: list[tuple[float, list[float]]] = []
    for key in keys:
        if merged and len(buckets[key]) < MIN_BIN:
            merged[-1][1].extend(buckets[key])
        else:
            merged.append((key, list(buckets[key])))
    while len(merged) > 1 and len(merged[0][1]) < MIN_BIN:
        merged[1][1].extend(merged[0][1])
        merged.pop(0)

    centres = [key for key, _values in merged]
    means = [sum(values) / len(values) for _key, values in merged]
    weights = [float(len(values)) for _key, values in merged]
    return MonotoneCurve(grades=centres,
                         wars=pool_adjacent_violators(means, weights))

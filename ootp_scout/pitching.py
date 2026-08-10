"""A runs-allowed WAR to sit beside the calculator's.

The calculator reports one WAR for pitchers, alongside FIP - so it is the
fielding-independent kind, built from strikeouts, walks and home runs. The
useful companion is the Baseball-Reference flavour: WAR from runs actually
allowed, which credits or blames a pitcher for everything that happened.

The output carries R and IP, so RA9 is available directly rather than inferred
from ERA - unearned runs included, which is the whole point of the distinction.

Where the two disagree is the interesting part. A pitcher whose rWAR badly
trails his WAR gave up more runs than his peripherals imply; over a projection
that usually means his BABIP or home-run rate is doing the damage rather than
his strikeout and walk skills.

Scale
-----
Runs-above-replacement needs a replacement baseline and a runs-per-win rate,
neither of which the calculator exposes. Rather than import numbers from a
different run environment, the replacement baseline is solved so that the
pool's mean rWAR equals its mean WAR. The two columns then sit on one scale by
construction, and the per-pitcher difference - which is what is being asked -
is not contaminated by an arbitrary level shift.

That makes rWAR here explicitly pool-relative. It is not Baseball-Reference's
number and should not be quoted as one; it is "the same pool, measured by runs
allowed instead of peripherals".
"""

from __future__ import annotations

from dataclasses import dataclass

# Runs per win. Around ten in a normal run environment.
#
# It is not a pure scale factor here. Substituting the solved baseline gives
#
#     rWAR_i = IP_i * (total_WAR / total_IP)  +  (1/RPW) * (IP_i * R_rate - R_i)
#
# so the first term rewards workload and the second rewards runs prevented,
# and RPW sets the balance between them. Lowering it weights run prevention
# more heavily, which can lift a stingy reliever past an innings-eating
# starter. Ten is the conventional value and the ordering is stable near it,
# but it is a real modelling choice, not cosmetic.
RUNS_PER_WIN = 10.0


@dataclass
class PitcherLine:
    name: str
    innings: float
    runs: float
    war: float

    @property
    def ra9(self) -> float:
        return 9.0 * self.runs / self.innings if self.innings else 0.0


def _number(raw: str) -> float | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_lines(projections) -> list[PitcherLine]:
    """Pull IP, R and WAR out of calculator rows that carry them."""
    lines: list[PitcherLine] = []
    for projection in projections:
        innings = _number(projection.stats.get("IP", ""))
        runs = _number(projection.stats.get("R", ""))
        if innings is None or runs is None or innings <= 0:
            continue
        lines.append(PitcherLine(name=projection.name, innings=innings,
                                 runs=runs, war=projection.war))
    return lines


def replacement_ra9(lines: list[PitcherLine],
                    runs_per_win: float = RUNS_PER_WIN) -> float:
    """The baseline that puts mean rWAR on the pool's mean WAR.

    rWAR_i = (baseline - RA9_i) / runs_per_win * IP_i / 9, and RA9_i * IP_i / 9
    is just R_i, so summing and solving for the baseline is exact:

        baseline = (runs_per_win * total_WAR + total_R) * 9 / total_IP
    """
    total_innings = sum(line.innings for line in lines)
    if total_innings <= 0:
        raise ValueError("no innings pitched in this pool")
    total_runs = sum(line.runs for line in lines)
    total_war = sum(line.war for line in lines)
    return (runs_per_win * total_war + total_runs) * 9.0 / total_innings


def compute_rwar(projections, runs_per_win: float = RUNS_PER_WIN
                 ) -> dict[str, float]:
    """Map lowercased player name to runs-allowed WAR.

    Returns an empty mapping when the rows carry no innings - the batter
    export has no IP column, so this is simply not applicable there.
    """
    lines = read_lines(projections)
    if not lines:
        return {}
    try:
        baseline = replacement_ra9(lines, runs_per_win)
    except ValueError:
        return {}

    result: dict[str, float] = {}
    for line in lines:
        wins = (baseline - line.ra9) / runs_per_win * line.innings / 9.0
        result[line.name.strip().lower()] = wins
    return result

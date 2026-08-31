"""What the application does, without deciding how to say it.

The command line and the window both need the same four operations: import an
export, rank what is stored, look a player up, weigh a trade. Each returns
structured results, so the window can put them in a sortable table and the
terminal can print them, without either re-implementing the other or scraping
the other's output.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import (database, flagging, pitching, projection, tables, views)

# Below this many players there is nothing to fit a baseline against.
MIN_PLAYERS = 5
# Rating scales, and what an implied grade may not exceed on each.
SCALE_BOUNDS = {"20 to 80": (20.0, 80.0), "1 to 100": (1.0, 100.0),
                "1 to 20": (1.0, 20.0), "1 to 10": (1.0, 10.0),
                "2 to 8": (2.0, 8.0), "1 to 5": (1.0, 5.0)}


class ScoutError(RuntimeError):
    """Something the user needs to fix, phrased for them rather than for a log."""


@dataclass
class ImportResult:
    league: str
    tag: str
    scale: str
    view_name: str
    players: int
    added: int
    updated: int
    skipped: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class RankingResult:
    league: str
    mode: str
    grade_label: str
    fits: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    fitted_on: int = 0
    shown: int = 0
    notes: list[str] = field(default_factory=list)


def _bounds(scale: str | None):
    return SCALE_BOUNDS.get((scale or "").strip())


def import_export(path: str, *, league: str | None = None, tag: str = "",
                  mode: str | None = None, db: str | None = None
                  ) -> ImportResult:
    """Read an OOTP export, project every player, and record them."""
    if not os.path.exists(path):
        raise ScoutError(f"No such file: {path}")
    try:
        headers, raw = tables.read_table(path)
        view = views.identify_view(headers, mode=mode)
        rows, problems = views.parse_rows(headers, raw, view)
    except (OSError, ValueError) as error:
        raise ScoutError(str(error)) from error

    scale, reason = views.infer_scale(rows, view)
    if scale is None:
        raise ScoutError(f"Could not work out the rating scale - {reason}.")

    projected, trouble = projection.project_rows(rows, view, scale)
    if len(projected) < MIN_PLAYERS:
        raise ScoutError(
            f"Only {len(projected)} of {len(rows)} players could be projected. "
            + (trouble[0][1] if trouble else "Check the export."))

    by_name = {p.name.strip().lower(): p for p in projected}
    rwar = _runs_allowed_war(projected)

    from . import reports as report_finder
    resolved_league = (league or report_finder.league_from_path(path)
                       or "default")

    observations = []
    for row in rows:
        found = by_name.get(row.name.strip().lower())
        if found is None or row.grade is None:
            continue
        age = row.age
        observations.append(database.Observation(
            name=row.name, mode=view.mode, role=view.role,
            league=resolved_league, tag=tag or "",
            team=row.team, position=row.position,
            age=int(age) if age.isdigit() else None,
            grade=row.grade, war=found.war,
            rwar=rwar.get(row.name.strip().lower()),
            scouting_accuracy=row.scouting_accuracy, scale=scale,
            ratings={c: row.values.get(c, "") for c in view.rating_columns}))

    connection = database.connect(db)
    try:
        added, updated = database.record(connection, observations,
                                         source=os.path.basename(path))
    finally:
        connection.close()

    return ImportResult(league=resolved_league, tag=tag, scale=scale,
                        view_name=view.ootp_view_name, players=len(observations),
                        added=added, updated=updated,
                        skipped=trouble + [(f"line {n}", d) for n, d in problems])


def _runs_allowed_war(projected) -> dict[str, float]:
    """rWAR for whichever of these carried innings."""
    arms = [p for p in projected if p.innings and p.innings > 0]
    if not arms:
        return {}
    total_ip = sum(p.innings for p in arms)
    total_runs = sum(p.runs for p in arms)
    total_war = sum(p.war for p in arms)
    baseline = ((pitching.RUNS_PER_WIN * total_war + total_runs) * 9.0
                / total_ip)
    return {p.name.strip().lower():
            (baseline - 9.0 * p.runs / p.innings) / pitching.RUNS_PER_WIN
            * p.innings / 9.0
            for p in arms}


def leagues(db: str | None = None) -> list[dict]:
    connection = database.connect(db)
    try:
        return database.leagues(connection)
    finally:
        connection.close()


def tags(league: str | None = None, db: str | None = None):
    connection = database.connect(db)
    try:
        return database.tags(connection, league)
    finally:
        connection.close()


def teams(league: str | None = None, db: str | None = None):
    connection = database.connect(db)
    try:
        return database.teams(connection, league)
    finally:
        connection.close()


def rank(*, league: str | None = None, mode: str | None = None,
         role: str | None = None, team: str | None = None,
         tag: str | None = None, fit_on_tag: bool = False,
         min_grade: float | None = None, degree: int = 1,
         shape: str = "monotone", position_adjust: bool = True,
         split_starters: bool = True, pool_roles: bool = False,
         db: str | None = None) -> RankingResult:
    """Fit everything stored and rank it. The window's main view."""
    connection = database.connect(db)
    notes: list[str] = []
    try:
        held = database.leagues(connection)
        if not held:
            raise ScoutError("Nothing recorded yet - import an export first.")
        if league is None:
            if len(held) > 1:
                names = ", ".join(repr(e["league"]) for e in held)
                raise ScoutError(
                    "This database holds several leagues, which are never "
                    f"combined. Choose one: {names}")
            league = held[0]["league"]

        if mode is None:
            counts: dict[str, int] = {}
            for row in database.latest(connection, league=league):
                counts[row["mode"]] = counts.get(row["mode"], 0) + 1
            if not counts:
                raise ScoutError(f"Nothing recorded for {league}.")
            mode = max(counts, key=counts.get)

        tagged = set()
        if tag:
            tagged = {r["name_key"] for r in
                      database.latest(connection, mode=mode, league=league,
                                      tag=tag)}
            if not tagged:
                raise ScoutError(f"No players tagged {tag!r} in {league}.")

        rows = database.latest(connection, mode=mode, role=role, team=team,
                               league=league, tag=tag if fit_on_tag else None)
        scales = {r["scale"] for r in rows if r["scale"]}
    finally:
        connection.close()

    subjects = [
        flagging.Subject(
            name=r["name"], position=r["position"] or "", grade=r["grade"],
            war=r["war"], is_pitcher=r["role"] == views.PITCHER,
            rwar=r["rwar"],
            meta={"scouting_accuracy": r["scouting_accuracy"] or "",
                  "age": str(r["age"]) if r["age"] is not None else "",
                  "team": r["team"] or ""},
            ratings=database.to_ratings(r))
        for r in rows if r["grade"] is not None and r["war"] is not None]

    if role:
        pitching_positions = {"SP", "RP", "CL", "P", "MR", "SR"}
        wanted = role == views.PITCHER
        before = len(subjects)
        subjects = [s for s in subjects
                    if (flagging.normalize_position(s.position)
                        in pitching_positions) == wanted]
        if before != len(subjects):
            notes.append(f"Ignored {before - len(subjects)} player(s) whose "
                         "position belongs to the other role.")

    if min_grade is not None:
        before = len(subjects)
        subjects = [s for s in subjects if s.grade >= min_grade]
        if before != len(subjects):
            notes.append(f"Ignored {before - len(subjects)} player(s) graded "
                         f"below {min_grade:.0f}.")
    else:
        below = sum(1 for s in subjects if s.war < 0)
        if subjects and below / len(subjects) > 0.35:
            notes.append(
                f"{below / len(subjects):.0%} of these project below "
                "replacement. They never take the field but they set the "
                "baseline, which flattens everyone above them. Consider a "
                "grade floor.")

    if len(subjects) < MIN_PLAYERS:
        raise ScoutError(f"Only {len(subjects)} player(s) left to fit against.")

    analysis = flagging.analyze(
        subjects, degree=degree, split_by_role=not pool_roles,
        position_adjust=position_adjust, shape=shape,
        split_starters=split_starters,
        grade_bounds=_bounds(next(iter(scales)) if len(scales) == 1 else None))

    findings = analysis.findings
    if tag and not fit_on_tag:
        findings = [f for f in findings
                    if f.subject.name.strip().lower() in tagged]
        notes.append(f"Showing {len(findings)} tagged {tag!r}, measured "
                     f"against all {len(subjects)}.")

    return RankingResult(
        league=league, mode=mode,
        grade_label="POT" if mode == views.POTENTIAL else "OVR",
        fits=analysis.fits, findings=findings, fitted_on=len(subjects),
        shown=len(findings), notes=notes)


def history(name: str, league: str | None = None, db: str | None = None):
    """One player's observations, oldest first, plus near-matches."""
    connection = database.connect(db)
    try:
        matches = database.search(connection, name)
        if not matches:
            return [], []
        exact = [m for m in matches
                 if m["name"].strip().lower() == name.strip().lower()]
        chosen = exact[0]["name"] if exact else matches[0]["name"]
        return database.history(connection, chosen, league=league), matches
    finally:
        connection.close()


def compare(side_a: list[str], side_b: list[str], **kwargs) -> dict:
    """Weigh two packages against one ranking."""
    ranking = rank(**kwargs)
    by_name = {f.subject.name.strip().lower(): f for f in ranking.findings}

    def resolve(names):
        found, missing = [], []
        for raw in names:
            key = raw.strip().lower()
            if not key:
                continue
            if key in by_name:
                found.append(by_name[key])
                continue
            partial = [f for k, f in by_name.items() if key in k]
            if len(partial) == 1:
                found.append(partial[0])
            else:
                missing.append(raw)
        return found, missing

    a, missing_a = resolve(side_a)
    b, missing_b = resolve(side_b)
    if missing_a or missing_b:
        raise ScoutError("No single player matches: "
                         + ", ".join(missing_a + missing_b))
    if not a and not b:
        raise ScoutError("Name at least one player on one side.")

    return {
        "ranking": ranking,
        "a": a, "b": b,
        "a_war": sum(f.subject.war for f in a),
        "b_war": sum(f.subject.war for f in b),
        "a_gap": sum(f.residual for f in a),
        "b_gap": sum(f.residual for f in b),
    }

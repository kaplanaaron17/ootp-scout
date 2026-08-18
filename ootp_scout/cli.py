"""Command line entry point.

Two steps, because the calculator is a website with no API:

    prepare  OOTP report  ->  a paste-ready block for ootpcalculator.com
    flag     OOTP report + the calculator's CSV  ->  undervalued players
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys

from datetime import datetime

from . import (clipboard, database, flagging, pitching, projections,
               reports, spreadsheet, tables, views)

BATTER_URL = "https://ootpcalculator.com/batter-projections"
PITCHER_URL = "https://ootpcalculator.com/pitcher-projections"

REPORT_FIELDS = [
    "rank", "name", "team", "position", "age", "group", "grade", "implied_grade",
    "grade_gap", "projected_war", "rwar", "rwar_minus_war", "expected_war",
    "residual", "z_score", "scouting_accuracy",
]

# What each rating scale can express. An implied grade outside these is not a
# grade at all, so it is reported at the boundary instead.
SCALE_BOUNDS = {"20 to 80": (20.0, 80.0), "1 to 100": (1.0, 100.0),
                "1 to 20": (1.0, 20.0), "1 to 10": (1.0, 10.0),
                "2 to 8": (2.0, 8.0), "1 to 5": (1.0, 5.0)}


def bounds_for(scale: str | None) -> tuple[float, float] | None:
    return SCALE_BOUNDS.get((scale or "").strip())


# Below this many matched players there is no pool to fit against.
MIN_MATCHES = 5
# When more than this share of a pool projects below replacement, the fit is
# being shaped by players who would never take the field.
BELOW_REPLACEMENT_SHARE = 0.35
# Below this share of the report matching, say so loudly but still rank.
LOW_MATCH_RATE = 0.5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ootp-scout",
        description="Flag OOTP players whose projected WAR outruns their grade.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare", help="check an OOTP report and emit a paste-ready block")
    prepare.add_argument("report", nargs="?",
                         help="the OOTP report (HTML/TSV/CSV). Omit it and pass "
                              "--latest to use the report OOTP wrote most "
                              "recently.")
    prepare.add_argument("--latest", action="store_true",
                         help="use the most recent report OOTP wrote to disk")
    prepare.add_argument("--out", help="write the paste block here "
                                       "(default: alongside the report)")
    prepare.add_argument("--scale", default="auto",
                         choices=("auto",) + views.SCALES,
                         help="the rating scale your export uses. The default "
                              "works it out from the ratings themselves and "
                              "tells you which to pick on the site.")
    prepare.add_argument("--mode", choices=("current", "potential"),
                         default=None,
                         help="pick current or potential ratings when the "
                              "export carries both (a custom OOTP view often "
                              "does)")
    prepare.add_argument("--no-copy", dest="copy", action="store_false",
                         help="do not put the paste block on the clipboard")
    prepare.set_defaults(copy=True)

    flag = subparsers.add_parser(
        "flag", help="join a report with calculator projections and rank")
    flag.add_argument("report", help="the same OOTP report you pasted in; the "
                                     "word 'latest' resolves to the most recent "
                                     "report OOTP wrote")
    flag.add_argument("projections",
                      help="the CSV downloaded from the calculator; the word "
                           "'latest' finds the newest *-projections.csv in your "
                           "Downloads folder")
    flag.add_argument("--out", help="write the flagged players here; a .xlsx "
                                    "name gets a formatted, highlighted "
                                    "spreadsheet, anything else a plain CSV")
    flag.add_argument("--mode", choices=("current", "potential"), default=None,
                      help="pick current or potential ratings when the export "
                           "carries both (a custom OOTP view often does)")
    flag.add_argument("--limit", type=int, default=25,
                      help="how many players to report (default: 25)")
    flag.add_argument("--min-z", type=float, default=None,
                      help="only report players at least this many standard "
                           "deviations above their expected WAR")
    flag.add_argument("--degree", type=int, default=1,
                      help="polynomial degree for the grade-to-WAR fit "
                           "(default: 1; try 2 if the relationship curves)")
    flag.add_argument("--pool", action="store_true",
                      help="fit hitters and pitchers together")
    flag.add_argument("--no-position", dest="position_adjust",
                      action="store_false",
                      help="do not give each position its own baseline")
    flag.set_defaults(position_adjust=True)
    flag.add_argument("--overrated", type=int, default=10, metavar="N",
                      help="also list the N most overrated players - those "
                           "projecting furthest below their grade (default: "
                           "10; 0 turns it off)")
    flag.add_argument("--shape", choices=("monotone", "linear"),
                    default="monotone",
                    help="monotone follows the curve in the data; linear "
                         "forces a straight line, which over-predicts at the "
                         "top and marks high-graded players overrated for no "
                         "reason")
    flag.add_argument("--min-grade", type=float, default=None,
                    help="ignore players graded below this when fitting; a pool "
                         "full of players who would never take the field drags "
                         "the baseline down and compresses everyone above")
    flag.add_argument("--league", default=None,
                      help="which league this pool belongs to. Taken from the "
                           "save the report came out of when not given.")
    flag.add_argument("--no-save", dest="save", action="store_false",
                      help="do not record this run in the database")
    flag.set_defaults(save=True)
    flag.add_argument("--db", default=None,
                      help="database file (default: ootp_scout.db beside the "
                           "tool)")
    flag.add_argument("--highlight-z", type=float, default=spreadsheet.STRONG_Z,
                      help="differential (in standard deviations) that counts "
                           "as a strong flag in the spreadsheet "
                           f"(default: {spreadsheet.STRONG_Z})")
    lookup = subparsers.add_parser(
        "lookup", help="look a player up in the database")
    lookup.add_argument("name", help="full or partial player name")
    lookup.add_argument("--league", default=None,
                        help="restrict to one league")
    lookup.add_argument("--db", default=None)

    report = subparsers.add_parser(
        "report", help="rank everything in the database, refitted together")
    report.add_argument("--out", help="write a spreadsheet or CSV here")
    report.add_argument("--mode", choices=("current", "potential"),
                        default=None,
                        help="restrict to one grade column (default: whichever "
                             "the database holds most of)")
    report.add_argument("--role", choices=("batter", "pitcher"), default=None,
                        help="restrict to hitters or pitchers")
    report.add_argument("--league", default=None,
                        help="which league to report on. Required when the "
                             "database holds more than one, since leagues use "
                             "different rating scales and must not be mixed.")
    report.add_argument("--shape", choices=("monotone", "linear"),
                    default="monotone",
                    help="monotone follows the curve in the data; linear "
                         "forces a straight line, which over-predicts at the "
                         "top and marks high-graded players overrated for no "
                         "reason")
    report.add_argument("--min-any-grade", action="store_true",
                        help="with --min-grade, keep a player whose OTHER "
                             "grade clears the floor - a low-rated prospect "
                             "with high potential survives a current-ratings "
                             "floor. Off by default, because in a current fit "
                             "those players are the ones who never play.")
    report.add_argument("--min-grade", type=float, default=None,
                    help="ignore players graded below this when fitting; a pool "
                         "full of players who would never take the field drags "
                         "the baseline down and compresses everyone above")
    report.add_argument("--team", default=None,
                        help="restrict to one organisation (partial names "
                             "match, so 'louisville' is enough)")
    report.add_argument("--limit", type=int, default=25)
    report.add_argument("--overrated", type=int, default=10, metavar="N")
    report.add_argument("--min-z", type=float, default=None)
    report.add_argument("--degree", type=int, default=1)
    report.add_argument("--pool", action="store_true")
    report.add_argument("--no-position", dest="position_adjust",
                        action="store_false")
    report.set_defaults(position_adjust=True)
    report.add_argument("--highlight-z", type=float,
                        default=spreadsheet.STRONG_Z)
    report.add_argument("--db", default=None)

    stats = subparsers.add_parser(
        "stats", help="what the database currently holds")
    stats.add_argument("--db", default=None)

    compare = subparsers.add_parser(
        "compare", help="weigh two sides of a hypothetical trade")
    compare.add_argument("side_a", metavar="SIDE-A",
                         help="comma-separated player names")
    compare.add_argument("side_b", metavar="SIDE-B",
                         help="comma-separated player names")
    compare.add_argument("--shape", choices=("monotone", "linear"),
                    default="monotone",
                    help="monotone follows the curve in the data; linear "
                         "forces a straight line, which over-predicts at the "
                         "top and marks high-graded players overrated for no "
                         "reason")
    compare.add_argument("--min-grade", type=float, default=None,
                    help="ignore players graded below this when fitting; a pool "
                         "full of players who would never take the field drags "
                         "the baseline down and compresses everyone above")
    compare.add_argument("--league", default=None)
    compare.add_argument("--mode", choices=("current", "potential"),
                         default=None,
                         help="value on current ratings or on potential")
    compare.add_argument("--degree", type=int, default=1)
    compare.add_argument("--pool", action="store_true")
    compare.add_argument("--no-position", dest="position_adjust",
                         action="store_false")
    compare.set_defaults(position_adjust=True)
    compare.add_argument("--db", default=None)

    leagues = subparsers.add_parser(
        "leagues", help="list the leagues in the database")
    leagues.add_argument("--db", default=None)

    forget = subparsers.add_parser(
        "forget", help="delete a league and everything recorded for it")
    forget.add_argument("league", help="exact league name, as `leagues` lists it")
    forget.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    forget.add_argument("--db", default=None)

    return parser


def resolve_report(value: str | None, use_latest: bool = False) -> str:
    """Turn the report argument into a path, honouring 'latest'."""
    wants_latest = use_latest or (value or "").lower() == "latest"
    if not wants_latest:
        if not value:
            raise SystemExit("error: give a report file, or use --latest for the "
                             "one OOTP wrote most recently")
        return value
    found = reports.find_latest()
    stamp = datetime.fromtimestamp(found.modified).strftime("%Y-%m-%d %H:%M")
    print(f"Using the most recent report: {found.save}, written {stamp}")
    print(f"  {found.path}")
    return found.path


def _load_report(path: str, mode: str | None = None
                 ) -> tuple[views.View, list[views.ExportRow], list]:
    headers, raw_rows = tables.read_table(path)
    view = views.identify_view(headers, mode=mode)
    if mode is None and len({v.mode for v in views.candidate_views(headers)}) > 1:
        print(f"NOTE: this export carries both current and potential ratings. "
              f"Using {view.mode} - pass --mode to choose the other.",
              file=sys.stderr)
    rows, problems = views.parse_rows(headers, raw_rows, view)
    return view, rows, problems


def command_prepare(args: argparse.Namespace) -> int:
    try:
        report = resolve_report(args.report, args.latest)
        view, rows, problems = _load_report(report, args.mode)
        headers, raw_rows = tables.read_table(report)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Detected the {view.ootp_view_name} view "
          f"({view.role}, {view.mode}) - {len(rows)} players.")

    scale = args.scale
    if scale == "auto":
        detected, reason = views.infer_scale(rows, view)
        if detected is None:
            print(f"error: could not work out the rating scale - {reason}. "
                  "Pass --scale explicitly.", file=sys.stderr)
            return 1
        scale = detected
        print(f"Rating scale: {scale} ({reason})")

    complaints = views.validate_ratings(rows, view, scale)
    if complaints:
        print(f"\n{len(complaints)} value(s) the calculator will reject on the "
              f"{scale} scale:", file=sys.stderr)
        for name, detail in complaints[:15]:
            print(f"  {name}: {detail}", file=sys.stderr)
        if len(complaints) > 15:
            print(f"  ... and {len(complaints) - 15} more", file=sys.stderr)
        if scale == views.SCALE_STEP_5:
            print("\nThe 20-80 scale only accepts multiples of 5, so this export "
                  "is almost certainly not on that scale. If OOTP is set to "
                  "1-100, re-run with --scale \"1 to 100\" and set the site's "
                  "RATINGS SCALE dropdown to match.", file=sys.stderr)
        return 1

    for line_number, detail in problems:
        print(f"  skipped line {line_number}: {detail}", file=sys.stderr)

    # Emit exactly the required columns, in the calculator's own order.
    cleaned = [views._clean(h) for h in headers]
    keep = [h for h in view.headers] + [h for h in view.optional if h in cleaned]
    out_rows = [[row.values.get(h, "") for h in keep] for row in rows]

    destination = args.out or f"{report.rsplit('.', 1)[0]}.paste.tsv"
    tables.write_tsv(destination, keep, out_rows)

    copied = False
    if args.copy:
        block = "\t".join(keep) + "\n" + "".join(
            "\t".join(row) + "\n" for row in out_rows)
        try:
            clipboard.copy(block)
            copied = True
        except clipboard.ClipboardError as error:
            print(f"(could not copy to the clipboard: {error})", file=sys.stderr)

    url = BATTER_URL if view.role == views.BATTER else PITCHER_URL
    print(f"\nWrote {len(out_rows)} rows to {destination}\n")
    print("Next:")
    print(f"  1. Open {url}")
    print(f"  2. Set RATINGS SCALE to '{scale}', then click BATCH INPUT")
    if copied:
        print("  3. Press Ctrl+V - the paste block is already on your "
              "clipboard - then click SUBMIT")
    else:
        print(f"  3. Paste the whole contents of {destination}, click SUBMIT")
    print(f"  4. Click DOWNLOAD CSV (it saves as "
          f"{view.calculator_type}-projections.csv)")
    print("  5. python -m ootp_scout flag latest latest --out targets.xlsx")
    return 0


def command_flag(args: argparse.Namespace) -> int:
    try:
        report = resolve_report(args.report)
        view, rows, problems = _load_report(report, args.mode)
    except (OSError, ValueError) as error:
        print(f"error reading {args.report}: {error}", file=sys.stderr)
        return 1
    try:
        projections_path = args.projections
        if projections_path.lower() == "latest":
            projections_path = reports.find_latest_projections()
            print(f"Using projections: {projections_path}")
        projected, projection_problems = projections.load_projections(projections_path)
    except (OSError, ValueError) as error:
        print(f"error reading {args.projections}: {error}", file=sys.stderr)
        return 1

    index, duplicates = projections.index_by_name(projected)
    rwar_by_name = pitching.compute_rwar(projected)

    subjects: list[flagging.Subject] = []
    unmatched: list[str] = []
    ungraded: list[str] = []

    for row in rows:
        projection = index.get(row.name.strip().lower())
        if projection is None:
            unmatched.append(row.name)
            continue
        if row.grade is None:
            ungraded.append(row.name)
            continue
        subjects.append(flagging.Subject(
            name=row.name, position=row.position, grade=row.grade,
            war=projection.war, is_pitcher=row.is_pitcher, meta=row.meta,
            rwar=rwar_by_name.get(row.name.strip().lower()),
            ratings={column: row.values.get(column, "")
                     for column in view.rating_columns}))

    # A fit needs a pool. Matching a handful of names usually means the report
    # and the projections came from two different exports, and fitting a line
    # to whatever overlapped would dress up noise as a ranking.
    if len(subjects) < MIN_MATCHES:
        print(f"error: only {len(subjects)} of {len(rows)} players in the "
              f"report matched a projection by name.", file=sys.stderr)
        print(f"  report:      {len(rows)} players - {report}", file=sys.stderr)
        print(f"  projections: {len(projected)} players - {projections_path}",
              file=sys.stderr)
        print("\nThese look like two different pools. Re-run the calculator "
              "with the paste block from this report, download that CSV, and "
              "try again.", file=sys.stderr)
        return 1

    match_rate = len(subjects) / len(rows) if rows else 0.0
    if match_rate < LOW_MATCH_RATE:
        print(f"WARNING: only {len(subjects)} of {len(rows)} report players "
              f"({match_rate:.0%}) matched a projection. The ranking below "
              f"covers just those {len(subjects)}.\n", file=sys.stderr)

    detected_scale, _reason = views.infer_scale(rows, view)
    subjects = drop_cross_role(subjects, view.role)
    subjects = apply_grade_floor(subjects, args.min_grade, view.grade_column)
    if len(subjects) < MIN_MATCHES:
        print(f"error: only {len(subjects)} player(s) left above the grade "
              "floor - not enough to fit against.", file=sys.stderr)
        return 1

    analysis = flagging.analyze(subjects, degree=args.degree,
                                split_by_role=not args.pool,
                                position_adjust=args.position_adjust,
                                shape=args.shape,
                                grade_bounds=bounds_for(detected_scale))
    findings = flagging.select(analysis.findings, limit=args.limit,
                               min_z=args.min_z)

    print(f"View: {view.ootp_view_name}   Grade column: {view.grade_column}   "
          f"Matched: {len(subjects)} of {len(rows)} players")
    for fit in analysis.fits:
        print(f"  fit[{fit.group}] n={fit.count} slope={fit.slope:+.4f} "
              f"WAR per grade point, residual sd={fit.residual_sd:.2f}"
              + (f" ({fit.note})" if fit.note else ""))
        offsets = fit.position_offsets
        if offsets:
            shown = ", ".join(f"{name} {value:+.2f}" for name, value
                              in sorted(offsets.items(), key=lambda p: -p[1]))
            print(f"    position offsets vs {fit.reference_position}: {shown}")
    print()

    if not findings:
        print("No player cleared the threshold.")
    else:
        print("MOST UNDERRATED - projecting above what their grade implies")
        print(_format_table(findings, view.grade_column))

    overrated: list[flagging.Finding] = []
    if args.overrated > 0:
        overrated = flagging.select_overrated(analysis.findings,
                                              limit=args.overrated)
        if overrated:
            print("\nMOST OVERRATED - projecting below what their grade implies")
            print(_format_table(overrated, view.grade_column))

    for label, names in (("unmatched by name", unmatched),
                         (f"no {view.grade_column} value", ungraded),
                         ("duplicate names, dropped", sorted(duplicates))):
        if names:
            print(f"\n{len(names)} {label}: {', '.join(names[:8])}"
                  + (" ..." if len(names) > 8 else ""))
    for line_number, detail in problems + projection_problems:
        print(f"  line {line_number}: {detail}", file=sys.stderr)

    if args.save:
        league = args.league or reports.league_from_path(report) or "default"
        scale, _reason = views.infer_scale(rows, view)
        try:
            connection = database.connect(args.db)
            observations = [
                database.Observation(
                    name=subject.name, mode=view.mode, role=view.role,
                    league=league, scale=scale or "",
                    team=subject.meta.get("team", ""),
                    position=subject.position,
                    age=(int(subject.meta["age"])
                         if subject.meta.get("age", "").isdigit() else None),
                    grade=subject.grade, war=subject.war, rwar=subject.rwar,
                    scouting_accuracy=subject.meta.get("scouting_accuracy", ""),
                    ratings=subject.ratings)
                for subject in subjects]
            added, refreshed = database.record(connection, observations,
                                               source=os.path.basename(report))
            connection.close()
            print(f"\nDatabase: {added} new, {refreshed} updated in league "
                  f"{league!r} ({args.db or database.default_path()})")
        except sqlite3.Error as error:
            print(f"(could not write to the database: {error})", file=sys.stderr)

    if args.out:
        if args.out.lower().endswith((".xlsx", ".xlsm")):
            try:
                # The spreadsheet gets the whole pool regardless of --limit:
                # the middle of the distribution is what makes the highlighted
                # extremes legible.
                spreadsheet.write_xlsx(args.out, analysis.findings,
                                       analysis.fits,
                                       grade_label=view.grade_column,
                                       strong_z=args.highlight_z,
                                       rating_columns=list(view.rating_columns))
            except spreadsheet.SpreadsheetUnavailable as error:
                print(f"error: {error}", file=sys.stderr)
                return 1
            except OSError as error:
                print(f"error writing {args.out}: {error}. If it is open in "
                      "Excel, close it and run again.", file=sys.stderr)
                return 1
            up = sum(1 for f in analysis.findings
                     if f.z_score >= args.highlight_z)
            down = sum(1 for f in analysis.findings
                       if f.z_score <= -args.highlight_z)
            print(f"\nWrote all {len(analysis.findings)} players to {args.out} "
                  f"({up} underrated, {down} overrated at |z| >= "
                  f"{args.highlight_z})")
        else:
            _write_csv(args.out, findings)
            print(f"\nWrote {len(findings)} rows to {args.out}")
    return 0


def _format_table(findings: list[flagging.Finding], grade_label: str) -> str:
    # rWAR only exists for pitchers, so the columns appear only when some row
    # actually has one - a batter table stays as narrow as it was.
    show_rwar = any(f.subject.rwar is not None for f in findings)
    show_implied = any(f.implied_grade is not None for f in findings)
    show_team = any(f.subject.meta.get("team") for f in findings)
    header = f"{'#':>3}  {'Player':<24} "
    if show_team:
        header += f"{'Team':<14} "
    header += f"{'Pos':<4} {'Age':>3} {grade_label:>5} "
    if show_implied:
        header += f"{'Impl':>5} {'+/-':>5} "
    header += f"{'WAR':>6} "
    if show_rwar:
        header += f"{'rWAR':>6} {'R-W':>6} "
    header += f"{'Exp':>6} {'Diff':>6} {'z':>5}  Scouting"

    lines = [header, "-" * len(header)]
    for rank, finding in enumerate(findings, start=1):
        subject = finding.subject
        row = f"{rank:>3}  {subject.name[:24]:<24} "
        if show_team:
            row += f"{subject.meta.get('team', '')[:14]:<14} "
        row += (f"{subject.position[:4]:<4} "
                f"{subject.meta.get('age', ''):>3} {subject.grade:>5.0f} ")
        if show_implied:
            if finding.implied_grade is None:
                row += f"{'-':>5} {'-':>5} "
            else:
                row += f"{finding.implied_grade:>5.0f} {finding.grade_gap:>+5.0f} "
        row += f"{subject.war:>6.2f} "
        if show_rwar:
            if subject.rwar is None:
                row += f"{'-':>6} {'-':>6} "
            else:
                row += f"{subject.rwar:>6.2f} {subject.war_gap:>+6.2f} "
        row += (f"{finding.expected_war:>6.2f} {finding.residual:>+6.2f} "
                f"{finding.z_score:>5.2f}  {finding.scouting_accuracy}")
        lines.append(row)
    return "\n".join(lines)


def _write_csv(path: str, findings: list[flagging.Finding]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        for rank, finding in enumerate(findings, start=1):
            subject = finding.subject
            writer.writerow({
                "rank": rank,
                "name": subject.name,
                "team": subject.meta.get("team", ""),
                "position": subject.position,
                "age": subject.meta.get("age", ""),
                "group": finding.group,
                "grade": f"{subject.grade:.0f}",
                "implied_grade": ("" if finding.implied_grade is None
                                  else f"{finding.implied_grade:.0f}"),
                "grade_gap": ("" if finding.grade_gap is None
                              else f"{finding.grade_gap:+.0f}"),
                "projected_war": f"{subject.war:.2f}",
                "rwar": "" if subject.rwar is None else f"{subject.rwar:.2f}",
                "rwar_minus_war": ("" if subject.war_gap is None
                                   else f"{subject.war_gap:+.2f}"),
                "expected_war": f"{finding.expected_war:.2f}",
                "residual": f"{finding.residual:+.2f}",
                "z_score": f"{finding.z_score:.2f}",
                "scouting_accuracy": finding.scouting_accuracy,
            })


def resolve_league(connection, requested: str | None) -> str | None:
    """Which league to work on. None means "stop, and a message was printed".

    Leagues are never merged. Different leagues run different rating scales,
    so a 55 in one is not a 55 in another and a fit spanning both would be
    meaningless. With one league the choice is obvious; with several the user
    has to say, because guessing wrong is invisible in the output.
    """
    held = database.leagues(connection)
    if not held:
        print("The database is empty. Run `flag` first.", file=sys.stderr)
        return None
    if requested:
        names = [entry["league"] for entry in held]
        if requested not in names:
            close = [n for n in names if requested.lower() in n.lower()]
            if len(close) == 1:
                return close[0]
            print(f"No league named {requested!r}. Held: "
                  + ", ".join(repr(n) for n in names), file=sys.stderr)
            return None
        return requested
    if len(held) == 1:
        return held[0]["league"]

    print(f"The database holds {len(held)} leagues. They are never combined - "
          "each has its own talent pool and run environment, and they may use "
          "different rating scales - so pass --league:", file=sys.stderr)
    for entry in held:
        scales = ", ".join(entry["scales"]) or "scale unknown"
        print(f"  {entry['league']!r}  {entry['players']} players  ({scales})",
              file=sys.stderr)
    return None


PITCHING_POSITIONS = {"SP", "RP", "CL", "P", "MR", "SR"}


def drop_cross_role(subjects, role):
    """Remove players whose position belongs to the other role.

    A pitcher turns up in a Batting Ratings export carrying batting ratings and
    a grade that describes his pitching. Measuring his hitting against that
    grade is a category error, and a loud one: on real data a starting pitcher
    led the overrated list purely because his OVR reflected an arm his bat was
    never going to match.
    """
    wanted_pitchers = role == views.PITCHER
    kept = [s for s in subjects
            if (flagging.normalize_position(s.position) in PITCHING_POSITIONS)
            == wanted_pitchers]
    dropped = len(subjects) - len(kept)
    if dropped:
        other = "position players" if wanted_pitchers else "pitchers"
        print(f"Ignoring {dropped} {other} found in this pool; their grade "
              f"describes the other half of their game.")
    return kept


def apply_grade_floor(subjects, min_grade, label="OVR", other_grades=None,
                      spare_on_other=False):
    """Drop players below `min_grade`, and warn when the pool looks unusable.

    The fit assumes one straight relationship between grade and WAR. Across a
    full roster export that assumption breaks: the bottom two thirds of a
    league project below replacement and never play, and including them makes
    the line far steeper than it is among players who actually appear. A
    steeper line compresses the top - real data had a six-WAR hitter reading
    an implied 60 with no floor and 78 with one.
    """
    if min_grade is not None:
        other = other_grades or {}

        def usable(subject):
            if subject.grade >= min_grade:
                return True
            # Only when explicitly asked: a high-potential teenager belongs in
            # a prospect fit, but in a current-ratings fit he is one of the
            # players who would never take the field, and letting him back in
            # recreates exactly the distortion the floor exists to remove.
            if not spare_on_other:
                return False
            return other.get(subject.name.strip().lower(), -1e9) >= min_grade

        kept = [s for s in subjects if usable(s)]
        dropped = len(subjects) - len(kept)
        if dropped:
            spared = sum(1 for s in kept if s.grade < min_grade)
            extra = (f", keeping {spared} whose other grade clears it"
                     if spared else "")
            print(f"Ignoring {dropped} player(s) graded below {min_grade:.0f}"
                  f"{extra}; fitting on the remaining {len(kept)}.")
        return kept

    below = sum(1 for s in subjects if s.war < 0)
    if subjects and below / len(subjects) > BELOW_REPLACEMENT_SHARE:
        share = below / len(subjects)
        print(f"NOTE: {share:.0%} of this pool projects below replacement. "
              f"Those players never take the field, but they are setting the "
              f"slope, which flattens the {label} implied for everyone above "
              f"them. Consider --min-grade to fit on players who would "
              f"actually play.", file=sys.stderr)
    return subjects


def _subjects_from_rows(rows) -> list[flagging.Subject]:
    return [
        flagging.Subject(
            name=row["name"], position=row["position"] or "",
            grade=row["grade"], war=row["war"],
            is_pitcher=row["role"] == views.PITCHER,
            rwar=row["rwar"],
            meta={"scouting_accuracy": row["scouting_accuracy"] or "",
                  "age": str(row["age"]) if row["age"] is not None else "",
                  "team": row["team"] or ""},
            ratings=database.to_ratings(row))
        for row in rows
        if row["grade"] is not None and row["war"] is not None]


def command_lookup(args: argparse.Namespace) -> int:
    connection = database.connect(args.db)
    try:
        league = None
        if args.league:
            league = resolve_league(connection, args.league)
            if league is None:
                return 1
        matches = database.search(connection, args.name)
        if not matches:
            print(f"No player matching {args.name!r} in the database. "
                  "Run `flag` on a pool that contains him first.",
                  file=sys.stderr)
            return 1
        if len(matches) > 1:
            exact = [m for m in matches
                     if m["name"].strip().lower() == args.name.strip().lower()]
            if not exact:
                print(f"{len(matches)} players match {args.name!r}:")
                for match in matches:
                    print(f"  {match['name']}  ({match['mode']}, "
                          f"{match['records']} record(s), last seen "
                          f"{match['seen_at'][:10]})")
                return 0
            matches = exact

        name = matches[0]["name"]
        records = database.history(connection, name, league=league)
        print(f"{name} - {len(records)} observation(s)\n")
        header = (f"  {'Seen':<12} {'Mode':<10} {'Team':<16} {'Pos':<4} "
                  f"{'Age':>3} {'Grade':>6} {'WAR':>6} {'Scouting':<12} "
                  f"Ratings")
        print(header)
        print("  " + "-" * (len(header) - 2))
        for row in records:
            ratings = database.to_ratings(row)
            shown = " ".join(f"{k} {v}" for k, v in list(ratings.items())[:6])
            print(f"  {row['seen_at'][:10]:<12} {row['mode']:<10} "
                  f"{(row['team'] or '')[:16]:<16} "
                  f"{(row['position'] or ''):<4} "
                  f"{(row['age'] if row['age'] is not None else ''):>3} "
                  f"{(row['grade'] if row['grade'] is not None else 0):>6.0f} "
                  f"{(row['war'] if row['war'] is not None else 0):>6.2f} "
                  f"{(row['scouting_accuracy'] or ''):<12} {shown}")

        # Movement between the first and last look is the reason to keep history.
        if len(records) > 1:
            first, last = records[0], records[-1]
            if first["grade"] is not None and last["grade"] is not None:
                print(f"\n  Grade {first['grade']:.0f} -> {last['grade']:.0f} "
                      f"({last['grade'] - first['grade']:+.0f}) between "
                      f"{first['seen_at'][:10]} and {last['seen_at'][:10]}")
            if first["war"] is not None and last["war"] is not None:
                print(f"  WAR   {first['war']:.2f} -> {last['war']:.2f} "
                      f"({last['war'] - first['war']:+.2f})")
        return 0
    finally:
        connection.close()


def command_report(args: argparse.Namespace) -> int:
    connection = database.connect(args.db)
    try:
        league = resolve_league(connection, args.league)
        if league is None:
            return 1
        mode = args.mode
        if mode is None:
            counts = {}
            for row in database.latest(connection, league=league):
                counts[row["mode"]] = counts.get(row["mode"], 0) + 1
            if not counts:
                print(f"Nothing recorded for league {league!r}.",
                      file=sys.stderr)
                return 1
            mode = max(counts, key=counts.get)
            if len(counts) > 1:
                print(f"NOTE: the database holds "
                      + ", ".join(f"{n} {m}" for m, n in sorted(counts.items()))
                      + f". Using {mode} - pass --mode to choose.",
                      file=sys.stderr)
        rows = database.latest(connection, mode=mode, role=args.role,
                               team=args.team, league=league)
        # A grade floor should not discard a prospect who is unusable today
        # and excellent later, so the other mode's grade is fetched and the
        # better of the two decides. "Below 38 now and below 38 ever" is a
        # different claim from "below 38 now".
        scales = {r["scale"] for r in rows if r["scale"]}
        other = views.POTENTIAL if mode == views.CURRENT else views.CURRENT
        best_other = {r["name_key"]: r["grade"]
                      for r in database.latest(connection, mode=other,
                                               league=league)
                      if r["grade"] is not None}
    finally:
        connection.close()

    subjects = _subjects_from_rows(rows)
    if len(subjects) < MIN_MATCHES:
        scope = f" for team {args.team!r}" if args.team else ""
        print(f"error: only {len(subjects)} usable {mode} player(s) in the "
              f"database{scope} - not enough to fit against.", file=sys.stderr)
        if args.team:
            print("A one-team fit is thin anyway; consider dropping --team so "
                  "the baseline comes from the whole league.", file=sys.stderr)
        return 1

    if args.team:
        print(f"NOTE: fitting within {args.team!r} only, so the baseline is "
              "that organisation rather than the league.", file=sys.stderr)

    grade_label = "POT" if mode == views.POTENTIAL else "OVR"
    if args.role:
        subjects = drop_cross_role(subjects, args.role)
    subjects = apply_grade_floor(subjects, args.min_grade, grade_label,
                                 best_other, args.min_any_grade)
    if len(subjects) < MIN_MATCHES:
        print(f"error: only {len(subjects)} player(s) left above the grade "
              "floor - not enough to fit against.", file=sys.stderr)
        return 1

    grade_bounds = bounds_for(next(iter(scales))) if len(scales) == 1 else None
    analysis = flagging.analyze(subjects, degree=args.degree,
                                split_by_role=not args.pool,
                                position_adjust=args.position_adjust,
                                shape=args.shape, grade_bounds=grade_bounds)
    findings = flagging.select(analysis.findings, limit=args.limit,
                               min_z=args.min_z)

    print(f"Database report: {league} - {len(subjects)} players, "
          f"{mode} ratings, refitted together")
    for fit in analysis.fits:
        print(f"  fit[{fit.group}] n={fit.count} slope={fit.slope:+.4f} "
              f"WAR per grade point, residual sd={fit.residual_sd:.2f}"
              + (f" ({fit.note})" if fit.note else ""))
        offsets = fit.position_offsets
        if offsets:
            shown = ", ".join(f"{name} {value:+.2f}" for name, value
                              in sorted(offsets.items(), key=lambda p: -p[1]))
            print(f"    position offsets vs {fit.reference_position}: {shown}")
    print()

    if findings:
        print("MOST UNDERRATED - projecting above what their grade implies")
        print(_format_table(findings, grade_label))

    overrated = []
    if args.overrated > 0:
        overrated = flagging.select_overrated(analysis.findings,
                                              limit=args.overrated)
        if overrated:
            print("\nMOST OVERRATED - projecting below what their grade implies")
            print(_format_table(overrated, grade_label))

    if args.out:
        rating_columns = sorted({key for s in subjects for key in s.ratings})
        if args.out.lower().endswith((".xlsx", ".xlsm")):
            try:
                spreadsheet.write_xlsx(args.out, analysis.findings,
                                       analysis.fits, grade_label=grade_label,
                                       strong_z=args.highlight_z,
                                       rating_columns=rating_columns)
            except (spreadsheet.SpreadsheetUnavailable, OSError) as error:
                print(f"error writing {args.out}: {error}", file=sys.stderr)
                return 1
        else:
            _write_csv(args.out, analysis.findings)
        print(f"\nWrote all {len(analysis.findings)} players to {args.out}")
    return 0


def command_stats(args: argparse.Namespace) -> int:
    connection = database.connect(args.db)
    try:
        summary = database.stats(connection)
    finally:
        connection.close()
    path = args.db or database.default_path()
    print(f"Database: {path}")
    if not summary["observations"]:
        print("  empty - run `flag` to record a pool")
        return 0
    print(f"  {summary['players']} players, {summary['observations']} "
          f"observations")
    print(f"  first seen {summary['first_seen'][:10]}, "
          f"last seen {summary['last_seen'][:10]}")
    for mode, role, players in summary["by_mode"]:
        print(f"    {mode:<10} {role:<8} {players} players")
    for entry in summary.get("leagues") or []:
        scales = ", ".join(entry["scales"]) or "scale unknown"
        print(f"  league {entry['league']!r}: {entry['players']} players "
              f"({scales})")
    held = summary.get("teams") or []
    if held:
        print(f"  {len(held)} organisation(s):")
        for name, players in held[:15]:
            print(f"    {name:<24} {players} players")
        if len(held) > 15:
            print(f"    ... and {len(held) - 15} more")
    else:
        print("  no team column in the exports so far - add one in OOTP to "
              "search by organisation")
    return 0


def _split_names(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def command_compare(args: argparse.Namespace) -> int:
    """Two packages of players, measured against the same fit.

    Without contract data this cannot report surplus value, so it reports what
    it can defend: projected production, and how far each player sits from the
    grade an opponent is probably pricing him by. That gap is the edge - a
    player whose projection beats his grade is one the other side will let go
    cheaply.
    """
    connection = database.connect(args.db)
    try:
        league = resolve_league(connection, args.league)
        if league is None:
            return 1
        mode = args.mode
        if mode is None:
            counts = {}
            for row in database.latest(connection, league=league):
                counts[row["mode"]] = counts.get(row["mode"], 0) + 1
            if not counts:
                print(f"Nothing recorded for league {league!r}.",
                      file=sys.stderr)
                return 1
            mode = max(counts, key=counts.get)
        rows = database.latest(connection, mode=mode, league=league)
    finally:
        connection.close()

    subjects = _subjects_from_rows(rows)
    if len(subjects) < MIN_MATCHES:
        print(f"error: only {len(subjects)} usable player(s) in {league!r} - "
              "not enough to measure anyone against.", file=sys.stderr)
        return 1

    subjects = apply_grade_floor(
        subjects, args.min_grade,
        "POT" if mode == views.POTENTIAL else "OVR")
    if len(subjects) < MIN_MATCHES:
        print(f"error: only {len(subjects)} player(s) left above the grade "
              "floor - not enough to measure anyone against.", file=sys.stderr)
        return 1

    analysis = flagging.analyze(subjects, degree=args.degree,
                                split_by_role=not args.pool,
                                position_adjust=args.position_adjust,
                                shape=args.shape)
    by_name = {f.subject.name.strip().lower(): f for f in analysis.findings}

    def resolve(names: list[str]) -> tuple[list, list[str]]:
        found, missing = [], []
        for name in names:
            key = name.strip().lower()
            if key in by_name:
                found.append(by_name[key])
                continue
            partial = [f for k, f in by_name.items() if key in k]
            if len(partial) == 1:
                found.append(partial[0])
            else:
                missing.append(name)
        return found, missing

    side_a, missing_a = resolve(_split_names(args.side_a))
    side_b, missing_b = resolve(_split_names(args.side_b))
    for name in missing_a + missing_b:
        print(f"error: no single player in {league!r} matches {name!r}. "
              "Try `lookup` to find the exact name.", file=sys.stderr)
    if missing_a or missing_b:
        return 1
    if not side_a and not side_b:
        print("error: name at least one player on one side.", file=sys.stderr)
        return 1

    grade_label = "POT" if mode == views.POTENTIAL else "OVR"
    print(f"{league} - valued on {mode} ratings, fitted across "
          f"{len(subjects)} players\n")

    def show(title: str, findings: list) -> tuple[float, float]:
        print(title)
        if not findings:
            print("  (nobody)")
            return 0.0, 0.0
        header = (f"  {'Player':<24} {'Pos':<4} {'Age':>3} {grade_label:>5} "
                  f"{'Impl':>5} {'WAR':>6} {'Diff':>7}")
        print(header)
        print("  " + "-" * (len(header) - 2))
        war = surplus_gap = 0.0
        for finding in findings:
            subject = finding.subject
            implied = ("-" if finding.implied_grade is None
                       else f"{finding.implied_grade:.0f}")
            print(f"  {subject.name[:24]:<24} {subject.position[:4]:<4} "
                  f"{subject.meta.get('age', ''):>3} {subject.grade:>5.0f} "
                  f"{implied:>5} {subject.war:>6.2f} "
                  f"{finding.residual:>+7.2f}")
            war += subject.war
            surplus_gap += finding.residual
        print(f"  {'TOTAL':<24} {'':<4} {'':>3} {'':>5} {'':>5} "
              f"{war:>6.2f} {surplus_gap:>+7.2f}")
        return war, surplus_gap

    war_a, gap_a = show("YOU GIVE UP", side_a)
    print()
    war_b, gap_b = show("YOU RECEIVE", side_b)

    print(f"\n{'':-<60}")
    print(f"Projected WAR      {war_b - war_a:+.2f} in your favour"
          if war_b >= war_a else
          f"Projected WAR      {war_b - war_a:+.2f} against you")
    print(f"Versus the grades  {gap_b - gap_a:+.2f} wins")
    if gap_b > gap_a:
        print("  You are receiving the players the grades underrate more, so "
              "an opponent pricing by OVR should find this easy to accept.")
    elif gap_b < gap_a:
        print("  You are giving up the players the grades underrate more - "
              "cheap by the opponent's pricing, but the ones worth keeping.")

    print("\nNo salaries or contract lengths are recorded, so this is "
          "production only, not surplus value. A cheap young player and an "
          "expensive old one with the same projection look identical here.")
    return 0


def command_leagues(args: argparse.Namespace) -> int:
    connection = database.connect(args.db)
    try:
        held = database.leagues(connection)
    finally:
        connection.close()
    if not held:
        print("No leagues recorded yet. Run `flag` on a pool first.")
        return 0
    header = (f"{'League':<28} {'Players':>8} {'Records':>8} "
              f"{'Last seen':<12} Scale")
    print(header)
    print("-" * len(header))
    for entry in held:
        scales = ", ".join(entry["scales"]) or "unknown"
        print(f"{entry['league'][:28]:<28} {entry['players']:>8} "
              f"{entry['observations']:>8} {entry['last_seen'][:10]:<12} "
              f"{scales}")
    if len(held) > 1:
        scales = {scale for entry in held for scale in entry["scales"]}
        print("\nLeagues are always fitted separately, so their numbers are "
              "not comparable with each other.")
        if len(scales) > 1:
            print("These are on different rating scales (" +
                  ", ".join(sorted(scales)) + "), so a grade in one is not a "
                  "grade in another either.")
    return 0


def command_forget(args: argparse.Namespace) -> int:
    connection = database.connect(args.db)
    try:
        held = {entry["league"]: entry for entry in database.leagues(connection)}
        if args.league not in held:
            print(f"No league named {args.league!r}. Held: "
                  + (", ".join(repr(n) for n in held) or "none"),
                  file=sys.stderr)
            return 1
        entry = held[args.league]
        print(f"This will delete {entry['observations']} record(s) covering "
              f"{entry['players']} player(s) in league {args.league!r}.")
        print("It cannot be undone - the observations are not recoverable "
              "without re-exporting and re-running the calculator.")
        if not args.yes:
            answer = input("Type the league name to confirm: ").strip()
            if answer != args.league:
                print("Not deleted.")
                return 1
        removed = database.forget(connection, args.league)
        print(f"Deleted {removed} record(s) for {args.league!r}.")
        return 0
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "prepare":
        return command_prepare(args)
    if args.command == "lookup":
        return command_lookup(args)
    if args.command == "report":
        return command_report(args)
    if args.command == "stats":
        return command_stats(args)
    if args.command == "compare":
        return command_compare(args)
    if args.command == "leagues":
        return command_leagues(args)
    if args.command == "forget":
        return command_forget(args)
    return command_flag(args)


if __name__ == "__main__":
    raise SystemExit(main())

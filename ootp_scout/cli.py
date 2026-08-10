"""Command line entry point.

Two steps, because the calculator is a website with no API:

    prepare  OOTP report  ->  a paste-ready block for ootpcalculator.com
    flag     OOTP report + the calculator's CSV  ->  undervalued players
"""

from __future__ import annotations

import argparse
import csv
import sys

from datetime import datetime

from . import (clipboard, flagging, projections, reports, spreadsheet,
               tables, views)

BATTER_URL = "https://ootpcalculator.com/batter-projections"
PITCHER_URL = "https://ootpcalculator.com/pitcher-projections"

REPORT_FIELDS = [
    "rank", "name", "position", "age", "group", "grade", "projected_war",
    "expected_war", "residual", "z_score", "scouting_accuracy",
]

# Below this many matched players there is no pool to fit against.
MIN_MATCHES = 5
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
    flag.add_argument("--highlight-z", type=float, default=spreadsheet.STRONG_Z,
                      help="differential (in standard deviations) that counts "
                           "as a strong flag in the spreadsheet "
                           f"(default: {spreadsheet.STRONG_Z})")
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


def _load_report(path: str) -> tuple[views.View, list[views.ExportRow], list]:
    headers, raw_rows = tables.read_table(path)
    view = views.identify_view(headers)
    rows, problems = views.parse_rows(headers, raw_rows, view)
    return view, rows, problems


def command_prepare(args: argparse.Namespace) -> int:
    try:
        report = resolve_report(args.report, args.latest)
        view, rows, problems = _load_report(report)
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
        view, rows, problems = _load_report(report)
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
            war=projection.war, is_pitcher=row.is_pitcher, meta=row.meta))

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

    analysis = flagging.analyze(subjects, degree=args.degree,
                                split_by_role=not args.pool,
                                position_adjust=args.position_adjust)
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
        print(_format_table(findings, view.grade_column))

    for label, names in (("unmatched by name", unmatched),
                         (f"no {view.grade_column} value", ungraded),
                         ("duplicate names, dropped", sorted(duplicates))):
        if names:
            print(f"\n{len(names)} {label}: {', '.join(names[:8])}"
                  + (" ..." if len(names) > 8 else ""))
    for line_number, detail in problems + projection_problems:
        print(f"  line {line_number}: {detail}", file=sys.stderr)

    if args.out:
        _write_csv(args.out, findings)
        print(f"\nWrote {len(findings)} rows to {args.out}")
    return 0


def _format_table(findings: list[flagging.Finding], grade_label: str) -> str:
    header = (f"{'#':>3}  {'Player':<24} {'Pos':<4} {'Age':>3} {grade_label:>5} "
              f"{'WAR':>6} {'Exp':>6} {'Diff':>6} {'z':>5}  Scouting")
    lines = [header, "-" * len(header)]
    for rank, finding in enumerate(findings, start=1):
        subject = finding.subject
        lines.append(
            f"{rank:>3}  {subject.name[:24]:<24} {subject.position[:4]:<4} "
            f"{subject.meta.get('age', ''):>3} {subject.grade:>5.0f} "
            f"{subject.war:>6.2f} {finding.expected_war:>6.2f} "
            f"{finding.residual:>+6.2f} {finding.z_score:>5.2f}  "
            f"{finding.scouting_accuracy}")
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
                "position": subject.position,
                "age": subject.meta.get("age", ""),
                "group": finding.group,
                "grade": f"{subject.grade:.0f}",
                "projected_war": f"{subject.war:.2f}",
                "expected_war": f"{finding.expected_war:.2f}",
                "residual": f"{finding.residual:+.2f}",
                "z_score": f"{finding.z_score:.2f}",
                "scouting_accuracy": finding.scouting_accuracy,
            })


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "prepare":
        return command_prepare(args)
    return command_flag(args)


if __name__ == "__main__":
    raise SystemExit(main())

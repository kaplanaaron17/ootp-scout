"""Command line entry point.

Two steps, because the calculator is a website with no API:

    prepare  OOTP report  ->  a paste-ready block for ootpcalculator.com
    flag     OOTP report + the calculator's CSV  ->  undervalued players
"""

from __future__ import annotations

import argparse
import csv
import sys

from . import clipboard, flagging, projections, tables, views

BATTER_URL = "https://ootpcalculator.com/batter-projections"
PITCHER_URL = "https://ootpcalculator.com/pitcher-projections"

REPORT_FIELDS = [
    "rank", "name", "position", "age", "group", "grade", "projected_war",
    "expected_war", "residual", "z_score", "scouting_accuracy",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ootp-scout",
        description="Flag OOTP players whose projected WAR outruns their grade.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare", help="check an OOTP report and emit a paste-ready block")
    prepare.add_argument("report", help="the OOTP report saved to disk (TSV/CSV)")
    prepare.add_argument("--out", help="write the paste block here "
                                       "(default: alongside the report)")
    prepare.add_argument("--scale", default="20 to 80", choices=views.SCALES,
                         help="the rating scale your export uses "
                              "(default: 20 to 80)")
    prepare.add_argument("--no-copy", dest="copy", action="store_false",
                         help="do not put the paste block on the clipboard")
    prepare.set_defaults(copy=True)

    flag = subparsers.add_parser(
        "flag", help="join a report with calculator projections and rank")
    flag.add_argument("report", help="the same OOTP report you pasted in")
    flag.add_argument("projections", help="*-projections.csv from the calculator")
    flag.add_argument("--out", help="write the flagged players to this CSV")
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
    return parser


def _load_report(path: str) -> tuple[views.View, list[views.ExportRow], list]:
    headers, raw_rows = tables.read_table(path)
    view = views.identify_view(headers)
    rows, problems = views.parse_rows(headers, raw_rows, view)
    return view, rows, problems


def command_prepare(args: argparse.Namespace) -> int:
    try:
        view, rows, problems = _load_report(args.report)
        headers, raw_rows = tables.read_table(args.report)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Detected the {view.ootp_view_name} view "
          f"({view.role}, {view.mode}) - {len(rows)} players.")

    complaints = views.validate_ratings(rows, view, args.scale)
    if complaints:
        print(f"\n{len(complaints)} value(s) the calculator will reject on the "
              f"{args.scale} scale:", file=sys.stderr)
        for name, detail in complaints[:15]:
            print(f"  {name}: {detail}", file=sys.stderr)
        if len(complaints) > 15:
            print(f"  ... and {len(complaints) - 15} more", file=sys.stderr)
        if args.scale == views.SCALE_STEP_5:
            print("\nThe 20-80 scale only accepts multiples of 5. Switch OOTP to "
                  "the 1-100 scale and re-export - it keeps the resolution that "
                  "20-80 rounds away.", file=sys.stderr)
        return 1

    for line_number, detail in problems:
        print(f"  skipped line {line_number}: {detail}", file=sys.stderr)

    # Emit exactly the required columns, in the calculator's own order.
    cleaned = [views._clean(h) for h in headers]
    keep = [h for h in view.headers] + [h for h in view.optional if h in cleaned]
    out_rows = [[row.values.get(h, "") for h in keep] for row in rows]

    destination = args.out or f"{args.report.rsplit('.', 1)[0]}.paste.tsv"
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
    print(f"  2. Set RATINGS SCALE to '{args.scale}', then click BATCH INPUT")
    if copied:
        print("  3. Press Ctrl+V - the paste block is already on your "
              "clipboard - then click SUBMIT")
    else:
        print(f"  3. Paste the whole contents of {destination}, click SUBMIT")
    print("  4. Click DOWNLOAD CSV")
    print(f"  5. python -m ootp_scout flag {args.report} "
          f"{view.role}-projections.csv")
    return 0


def command_flag(args: argparse.Namespace) -> int:
    try:
        view, rows, problems = _load_report(args.report)
    except (OSError, ValueError) as error:
        print(f"error reading {args.report}: {error}", file=sys.stderr)
        return 1
    try:
        projected, projection_problems = projections.load_projections(args.projections)
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

    if not subjects:
        print("error: no player in the report matched a projection by name. "
              "Check that both files came from the same pool.", file=sys.stderr)
        return 1

    analysis = flagging.analyze(subjects, degree=args.degree,
                                split_by_role=not args.pool)
    findings = flagging.select(analysis.findings, limit=args.limit,
                               min_z=args.min_z)

    print(f"View: {view.ootp_view_name}   Grade column: {view.grade_column}   "
          f"Matched: {len(subjects)} of {len(rows)} players")
    for fit in analysis.fits:
        slope = fit.coefficients[1] if len(fit.coefficients) > 1 else 0.0
        print(f"  fit[{fit.group}] n={fit.count} slope={slope:+.4f} "
              f"WAR per grade point, residual sd={fit.residual_sd:.2f}")
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

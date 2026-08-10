"""Command line entry point."""

from __future__ import annotations

import argparse
import csv
import sys

from . import flagging, loading, war_model
from .loading import Player

REPORT_FIELDS = [
    "rank", "name", "position", "age", "group", "grade", "projected_war",
    "expected_war", "residual", "z_score", "scouting_accuracy", "signability",
    "demand", "nationality", "note",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ootp-scout",
        description="Flag OOTP players whose projected WAR outruns their "
                    "overall grade.")
    parser.add_argument("csv_path", help="OOTP CSV export")
    parser.add_argument(
        "--mode", choices=("current", "potential"), default="current",
        help="'current' compares against OVR using current ratings (players to "
             "target now); 'potential' compares against POT using potential "
             "ratings (prospects). Default: current.")
    parser.add_argument("--out", help="write the flagged players to this CSV")
    parser.add_argument("--limit", type=int, default=25,
                        help="how many players to report (default: 25)")
    parser.add_argument("--min-z", type=float, default=None,
                        help="only report players at least this many standard "
                             "deviations above their expected WAR")
    parser.add_argument("--degree", type=int, default=1,
                        help="polynomial degree for the grade-to-WAR fit "
                             "(default: 1; try 2 if the relationship curves)")
    parser.add_argument("--scale", choices=("20-80", "1-100"), default=None,
                        help="override rating-scale auto-detection")
    parser.add_argument("--war-column", default=None,
                        help="use an existing WAR column from the CSV instead "
                             "of the built-in provisional model")
    parser.add_argument("--pool", action="store_true",
                        help="fit hitters and pitchers together instead of "
                             "separately")
    return parser


def _load_war_column(path: str, column: str, players: list[Player]) -> None:
    """Attach raw values from an external WAR column onto each player."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if column not in (rows[0].keys() if rows else {}):
        available = ", ".join(rows[0].keys()) if rows else "none"
        raise SystemExit(f"error: no column {column!r} in {path}. "
                         f"Available columns: {available}")
    by_row = {index: row for index, row in enumerate(rows, start=2)}
    for player in players:
        row = by_row.get(player.row_number)
        if row is not None:
            player.meta["_war_column_value"] = row.get(column, "")


def _format_table(findings: list[flagging.Finding], mode: str) -> str:
    label = "POT" if mode == "potential" else "OVR"
    header = (f"{'#':>3}  {'Player':<24} {'Pos':<4} {'Age':>3} {label:>5} "
              f"{'WAR':>6} {'Exp':>6} {'Diff':>6} {'z':>5}  Scouting")
    lines = [header, "-" * len(header)]
    for rank, finding in enumerate(findings, start=1):
        player = finding.player
        lines.append(
            f"{rank:>3}  {player.name[:24]:<24} {player.position[:4]:<4} "
            f"{player.meta.get('age', ''):>3} {finding.baseline:>5.0f} "
            f"{finding.war:>6.2f} {finding.expected_war:>6.2f} "
            f"{finding.residual:>+6.2f} {finding.z_score:>5.2f}  "
            f"{finding.scouting_accuracy}")
    return "\n".join(lines)


def _write_csv(path: str, findings: list[flagging.Finding]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        for rank, finding in enumerate(findings, start=1):
            player = finding.player
            writer.writerow({
                "rank": rank,
                "name": player.name,
                "position": player.position,
                "age": player.meta.get("age", ""),
                "group": finding.group,
                "grade": f"{finding.baseline:.0f}",
                "projected_war": f"{finding.war:.2f}",
                "expected_war": f"{finding.expected_war:.2f}",
                "residual": f"{finding.residual:+.2f}",
                "z_score": f"{finding.z_score:.2f}",
                "scouting_accuracy": finding.scouting_accuracy,
                "signability": player.meta.get("signability", ""),
                "demand": player.meta.get("demand", ""),
                "nationality": player.meta.get("nationality", ""),
                "note": finding.note,
            })


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        loaded = loading.load_csv(args.csv_path, scale=args.scale)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.war_column:
        model = war_model.ExternalWarModel(args.war_column)
        _load_war_column(args.csv_path, args.war_column, loaded.players)
    else:
        model = war_model.ProvisionalModel()

    scored: list[tuple[Player, float]] = []
    unscored: list[tuple[str, str]] = []
    for player in loaded.players:
        tools = player.tools(args.mode)
        needed = war_model.required_tools(player)
        if not args.war_column and not needed <= set(tools):
            absent = ", ".join(sorted(needed - set(tools)))
            unscored.append((player.name, f"missing {absent}"))
            continue
        try:
            projection = model.project(player, tools, loaded.scale)
        except ValueError as error:
            unscored.append((player.name, str(error)))
            continue
        scored.append((player, projection.war))

    if not scored:
        print("error: no player could be projected - check that the export "
              "carries ratings columns for the mode you asked for",
              file=sys.stderr)
        return 1

    analysis = flagging.analyze(scored, mode=args.mode, degree=args.degree,
                                split_by_role=not args.pool)
    findings = flagging.select(analysis.findings, limit=args.limit,
                               min_z=args.min_z)

    print(f"Mode: {args.mode}   Scale: {loaded.scale}   "
          f"Model: {model.name}   Projected: {len(scored)} players")
    if args.mode == "potential" and not loaded.used_potential_tools:
        print("NOTE: this export has no potential-ratings columns, so current "
              "ratings were used against the POT grade. Add potential ratings "
              "to the export view for a real prospect run.")
    if model.name == "provisional":
        print("NOTE: WAR comes from the provisional placeholder model, not a "
              "calibrated calculator. Treat the ordering as indicative only.")
    for fit in analysis.fits:
        slope = fit.coefficients[1] if len(fit.coefficients) > 1 else 0.0
        print(f"  fit[{fit.group}] n={fit.count} slope={slope:+.4f} "
              f"WAR/grade-point, residual sd={fit.residual_sd:.2f}")
    print()

    if not findings:
        print("No player cleared the threshold.")
    else:
        print(_format_table(findings, args.mode))

    if unscored:
        print(f"\nNot projected ({len(unscored)}):")
        for name, reason in unscored[:10]:
            print(f"  {name}: {reason}")
        if len(unscored) > 10:
            print(f"  ... and {len(unscored) - 10} more")
    for name, reason in analysis.excluded[:10]:
        print(f"  excluded {name}: {reason}")

    if args.out:
        _write_csv(args.out, findings)
        print(f"\nWrote {len(findings)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

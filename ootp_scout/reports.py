"""Locate the report OOTP just wrote.

`Report -> Write report to disk` does not prompt for a location. It drops a
timestamped file in the save's own temp folder and opens it in the browser:

    <Documents>/Out of the Park Developments/OOTP Baseball NN/
        saved_games/<save>.lg/news/html/temp/YYYY-MM-DD-HH-MM-SS.html

So the useful gesture is "the one I just made", not a path the user has to go
hunting for. The search is a bounded glob rather than a recursive walk - these
folders can sit in OneDrive, where a deep scan takes minutes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from glob import glob

RELATIVE_PATTERN = os.path.join(
    "OOTP Baseball *", "saved_games", "*", "news", "html", "temp", "*.htm*")


@dataclass
class FoundReport:
    path: str
    modified: float
    save: str


def candidate_roots() -> list[str]:
    """Places 'Out of the Park Developments' is likely to live."""
    home = os.path.expanduser("~")
    roots = [
        os.path.join(home, "Documents", "Out of the Park Developments"),
        os.path.join(home, "OneDrive", "Documents",
                     "Out of the Park Developments"),
    ]
    onedrive = os.environ.get("OneDrive")
    if onedrive:
        roots.append(os.path.join(onedrive, "Documents",
                                  "Out of the Park Developments"))
    # Preserve order while dropping duplicates and anything absent.
    seen: set[str] = set()
    found: list[str] = []
    for root in roots:
        key = os.path.normcase(os.path.abspath(root))
        if key not in seen and os.path.isdir(root):
            seen.add(key)
            found.append(root)
    return found


def find_reports(roots: list[str] | None = None) -> list[FoundReport]:
    """Every OOTP-written report, newest first."""
    reports: list[FoundReport] = []
    for root in (roots if roots is not None else candidate_roots()):
        for path in glob(os.path.join(root, RELATIVE_PATTERN)):
            try:
                modified = os.path.getmtime(path)
            except OSError:
                continue
            # .../saved_games/<save>/news/html/temp/<file>
            parts = path.split(os.sep)
            save = parts[-5] if len(parts) >= 5 else "?"
            reports.append(FoundReport(path=path, modified=modified, save=save))
    reports.sort(key=lambda r: r.modified, reverse=True)
    return reports


def download_folders() -> list[str]:
    home = os.path.expanduser("~")
    folders = [os.path.join(home, "Downloads"),
               os.path.join(home, "OneDrive", "Downloads")]
    return [f for f in folders if os.path.isdir(f)]


def find_latest_projections(folders: list[str] | None = None) -> str:
    """The newest *-projections.csv the calculator has downloaded.

    The site names its export after its own word for the player type -
    batting-projections.csv or pitching-projections.csv - and browsers append
    " (1)", " (2)" and so on when you download it again. Matching the pattern
    beats making the user retype whichever variant they ended up with.
    """
    candidates: list[tuple[float, str]] = []
    for folder in (folders if folders is not None else download_folders()):
        for pattern in ("*-projections*.csv", "*projections*.csv"):
            for path in glob(os.path.join(folder, pattern)):
                try:
                    candidates.append((os.path.getmtime(path), path))
                except OSError:
                    continue
            if candidates:
                break
    if not candidates:
        searched = ", ".join(folders if folders is not None else download_folders())
        raise FileNotFoundError(
            "no *-projections.csv found in " + (searched or "any Downloads "
            "folder") + ". Download it from ootpcalculator.com with the "
            "'Download CSV' button, or pass the file path directly.")
    return max(candidates)[1]


def find_latest(roots: list[str] | None = None) -> FoundReport:
    reports = find_reports(roots)
    if not reports:
        raise FileNotFoundError(
            "no OOTP report found. In OOTP, switch to a ratings view and use "
            "Report -> Write report to disk, then try again. If your saves are "
            "somewhere unusual, pass the file path directly instead of --latest.")
    return reports[0]

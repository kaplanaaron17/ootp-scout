"""Build the standalone Windows application.

    python -m pip install pyinstaller openpyxl
    python build_exe.py

Produces dist/OOTP-Scout.exe - one file, no Python needed on the machine that
runs it. openpyxl must be installed *here* so it can be bundled; the person
running the exe installs nothing.

Two deliberate choices:

* windowed, not console - the exe opens the window, and a console flashing
  behind it looks like something went wrong;
* one file, because a folder of DLLs is something people unzip wrongly, and
  the startup cost of unpacking is a second on a tool used a few times a day.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

NAME = "OOTP-Scout"
ENTRY = "run_gui.py"


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run:\n"
              "    python -m pip install pyinstaller openpyxl", file=sys.stderr)
        return 1

    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("openpyxl is not installed here, so the built application would "
              "not be able to write spreadsheets. Run:\n"
              "    python -m pip install openpyxl", file=sys.stderr)
        return 1

    for folder in ("build", "dist"):
        shutil.rmtree(os.path.join(root, folder), ignore_errors=True)

    command = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onefile",
        "--windowed",
        "--noconfirm",
        # openpyxl reaches for these lazily, so PyInstaller cannot see them.
        "--hidden-import", "openpyxl.cell._writer",
        ENTRY,
    ]
    icon = os.path.join(root, "icon.ico")
    if os.path.exists(icon):
        command[-1:-1] = ["--icon", icon]

    print(" ".join(command))
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        return result.returncode

    built = os.path.join(root, "dist", NAME + ".exe")
    if os.path.exists(built):
        size = os.path.getsize(built) / (1024 * 1024)
        print(f"\nBuilt {built}  ({size:.0f} MB)")
        print("Give people that single file. Windows SmartScreen will warn on "
              "first run because it is unsigned - More info, then Run anyway.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

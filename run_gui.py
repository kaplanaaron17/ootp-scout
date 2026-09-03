"""Entry point for the built application.

PyInstaller needs a plain script rather than a module, and a windowed build
has nowhere to print a traceback - so a failure during startup is shown in a
dialog instead of vanishing.

`--self-check` exists because that same missing stderr once hid a broken
window behind a perfectly normal-looking one. It opens the window, drives it,
writes what happened to a file and exits, so a build can be verified without a
person sitting in front of it - and so "it doesn't work" from someone else can
come back as something more specific than that.
"""

import sys


def self_check(out: str | None = None) -> int:
    """Open the window, drive it, and report. Returns 0 if it works."""
    import os
    import tempfile
    import time
    import traceback

    lines: list[str] = []
    ok = True

    def check(name, test):
        nonlocal ok
        try:
            detail = test()
        except Exception:                                        # noqa: BLE001
            ok = False
            lines.append(f"FAIL  {name}\n{traceback.format_exc()}")
        else:
            if detail is True or detail is None:
                lines.append(f"ok    {name}")
            else:
                ok = False
                lines.append(f"FAIL  {name}: {detail}")

    import tkinter

    from ootp_scout import database, gui, reports

    def names():
        """The window may not reuse a name tkinter uses internally."""
        clash = {n for n in vars(gui.ScoutWindow)
                 if not n.startswith("__")} & set(dir(tkinter.Tk))
        return sorted(clash) or True

    check("no method shadows tkinter", names)

    folder = tempfile.mkdtemp(prefix="ootp-self-check-")
    window = None

    def opens():
        nonlocal window
        window = gui.ScoutWindow(db=os.path.join(folder, "check.db"))
        window.update()
        return True

    check("the window opens", opens)

    def works():
        """Every button routes through _run, and _run calls config()."""
        landed = []
        window._run(lambda: "reached", landed.append, "Checking…")
        end = time.time() + 15
        while time.time() < end and not landed:
            window.update()
            time.sleep(0.02)
        return True if landed == ["reached"] else "background work never landed"

    if window is not None:
        check("a button's work runs and comes back", works)

    lines.append("")
    lines.append(f"database would be: {database.default_path()}")
    try:
        found = reports.find_latest()
        lines.append(f"newest OOTP report: {found.save}, {found.path}")
    except Exception as error:                                   # noqa: BLE001
        lines.append(f"no OOTP report found: {error}")

    if window is not None:
        window.destroy()

    report = "\n".join(lines) + "\n"
    out = out or os.path.join(tempfile.gettempdir(), "ootp-scout-self-check.txt")
    try:
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(report)
    except OSError:
        pass
    if sys.stdout is not None:
        print(report, end="")
    else:
        try:
            from tkinter import messagebox
            messagebox.showinfo("OOTP Scout", report)
        except Exception:                                        # noqa: BLE001
            pass
    return 0 if ok else 1


def main() -> int:
    try:
        if "--self-check" in sys.argv:
            where = sys.argv[sys.argv.index("--self-check") + 1:]
            return self_check(where[0] if where else None)
        from ootp_scout.gui import main as run
        return run()
    except Exception as error:                                   # noqa: BLE001
        import traceback
        detail = traceback.format_exc()
        try:
            import tkinter
            from tkinter import messagebox
            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("OOTP Scout", f"{error}\n\n{detail}")
        except Exception:                                        # noqa: BLE001
            print(detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

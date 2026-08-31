"""Entry point for the built application.

PyInstaller needs a plain script rather than a module, and a windowed build
has nowhere to print a traceback - so a failure during startup is shown in a
dialog instead of vanishing.
"""

import sys


def main() -> int:
    try:
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

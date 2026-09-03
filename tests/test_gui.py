"""The window, driven the way a person drives it.

These exist because of one bug. A method here was called `_options`, which is
also a private method of `tkinter.Misc` that `config()` calls on every widget
update. Overriding it meant the window opened, looked completely normal, and
did nothing at all - every button raised deep inside tkinter, into a callback
handler that writes to stderr, which a windowed .exe does not have. Importing
the module and constructing the window both passed. Only pressing a button
found it.
"""

import gc
import os
import tempfile
import time
import unittest

try:
    import tkinter
    from tkinter import messagebox
    _root = tkinter.Tk()
    _root.destroy()
    HAS_DISPLAY = True
except Exception:                                            # noqa: BLE001
    HAS_DISPLAY = False

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
BATTERS = os.path.join(FIXTURES, "pool_batters.tsv")


@unittest.skipUnless(HAS_DISPLAY, "no display to open a window on")
class NamesTest(unittest.TestCase):
    def test_nothing_shadows_tkinter(self):
        """A window method may not take a name tkinter already uses.

        `dir(Tk)` is every name the toolkit reaches for internally. Colliding
        with one does not fail loudly - it fails in whatever tkinter was doing
        at the time, which is nowhere near the code that caused it.
        """
        from ootp_scout import gui
        theirs = set(dir(tkinter.Tk))
        ours = {name for name in vars(gui.ScoutWindow)
                if not name.startswith("__")}
        self.assertEqual(sorted(ours & theirs), [])


@unittest.skipUnless(HAS_DISPLAY, "no display to open a window on")
class WindowTest(unittest.TestCase):
    def setUp(self):
        from ootp_scout import gui
        self.gui = gui
        self.folder = tempfile.TemporaryDirectory()
        self.said = []
        self._info, self._error = messagebox.showinfo, messagebox.showerror
        messagebox.showinfo = lambda t, m, **k: self.said.append(("info", m))
        messagebox.showerror = lambda t, m, **k: self.said.append(("error", m))
        self.window = gui.ScoutWindow(
            db=os.path.join(self.folder.name, "window.db"))
        self.settle()

    def tearDown(self):
        messagebox.showinfo, messagebox.showerror = self._info, self._error
        # Let queued work land first. A worker thread holding the last
        # reference to the window would otherwise free Tk from the wrong
        # thread, which aborts the whole test process rather than failing.
        self.pump(5.0, until=lambda: self.window._busy == 0)
        self.window.destroy()
        self.window = None
        gc.collect()
        self.folder.cleanup()

    def pump(self, seconds=8.0, until=None):
        """Run the event loop, so queued background work lands."""
        end = time.time() + seconds
        while time.time() < end:
            self.window.update()
            if until is not None and until():
                return
            time.sleep(0.02)

    def settle(self, seconds=8.0):
        """Wait for the window to finish whatever it has started.

        Not a fixed sleep: the window reads the database on a timer and then
        off-thread, so how long that takes depends on the machine and on what
        else the suite is doing. Waiting on the window's own idea of being
        busy is the only version of this that does not go flaky under load.
        """
        self.pump(seconds, until=lambda: (
            self.window._busy == 0
            and self.window.status.get() != "Import an export to begin."
            and not self.window.status.get().startswith("Reading")))

    def rows(self):
        return self.window.tree.get_children()

    def test_an_empty_database_says_so_rather_than_looking_broken(self):
        self.assertIn("Nothing stored", self.window.status.get())
        self.assertEqual(self.rows(), ())

    def test_importing_fills_the_table(self):
        self.window._import(BATTERS)
        self.settle()
        self.assertEqual(len(self.rows()), 41)
        self.assertEqual(self.window.league.get(), "default")
        self.assertEqual(self.said, [])

    def test_the_most_underrated_player_is_first(self):
        self.window._import(BATTERS)
        self.settle()
        first = self.window.tree.item(self.rows()[0])["values"]
        self.assertIn("Sleeper Sam", first)

    def test_extremes_are_tinted_and_the_middle_is_not(self):
        self.window._import(BATTERS)
        self.settle()
        tags = [self.window.tree.item(r)["tags"] for r in self.rows()]
        flat = [t[0] for t in tags if t]
        self.assertIn("strong_up", flat)
        self.assertLess(len(flat), len(tags))

    def test_a_grade_floor_narrows_the_pool(self):
        self.window._import(BATTERS)
        self.settle()
        everyone = len(self.rows())
        self.window.floor.set(45)
        self.window.refresh_ranking()
        self.settle()
        self.assertLess(len(self.rows()), everyone)

    def test_sorting_by_a_column_reorders(self):
        self.window._import(BATTERS)
        self.settle()
        before = [self.window.tree.item(r)["values"][1] for r in self.rows()]
        self.window.sort_by("name")
        after = [self.window.tree.item(r)["values"][1] for r in self.rows()]
        self.assertNotEqual(before, after)
        self.assertEqual(sorted(after), after)

    def test_a_filter_matching_nobody_complains_instead_of_raising(self):
        self.window._import(BATTERS)
        self.settle()
        self.window.floor.set(99)
        self.window.refresh_ranking()
        self.settle()
        self.assertTrue(self.said)
        self.assertEqual(self.said[0][0], "info")

    def test_every_toolbar_button_survives_being_pressed(self):
        """The bug this file exists for broke on `config`, not on the work.

        So press the things that only touch widgets, and assert nothing lands
        in the error dialog - a traceback there is the failure signature.
        """
        self.window._import(BATTERS)
        self.settle()
        self.window.refresh_sources()
        self.settle()
        self.window.refresh_tags()
        self.window.refresh_ranking()
        self.settle()
        self.assertEqual([k for k, _m in self.said if k == "error"], [])


@unittest.skipUnless(HAS_DISPLAY, "no display to open a window on")
class SelfCheckTest(unittest.TestCase):
    """`OOTP-Scout.exe --self-check` is what a stranger runs when the window
    misbehaves, so it has to keep working when nothing else does."""

    def setUp(self):
        import run_gui
        self.run_gui = run_gui
        self.folder = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.folder.name, "check.txt")

    def tearDown(self):
        gc.collect()
        self.folder.cleanup()

    def read(self):
        with open(self.out, encoding="utf-8") as handle:
            return handle.read()

    def test_passes_on_a_healthy_build(self):
        self.assertEqual(self.run_gui.self_check(self.out), 0)
        report = self.read()
        self.assertNotIn("FAIL", report)
        self.assertIn("the window opens", report)

    def test_it_says_where_the_database_would_be(self):
        self.run_gui.self_check(self.out)
        self.assertIn("database would be:", self.read())

    def test_it_catches_a_shadowed_tkinter_name(self):
        """The bug it was written for. Put it back, and it must fail."""
        from ootp_scout import gui
        gui.ScoutWindow._options = lambda self: {}
        try:
            self.assertEqual(self.run_gui.self_check(self.out), 1)
            report = self.read()
            self.assertIn("FAIL", report)
            self.assertIn("_options", report)
        finally:
            del gui.ScoutWindow._options


if __name__ == "__main__":
    unittest.main()

"""End-to-end tests over real ootpcalculator.com output.

`tests/fixtures/pool_batters.tsv` is a 41-player Batting Ratings export.
`tests/fixtures/batter-projections.csv` is what ootpcalculator.com actually
returned for it. The pool contains one planted player, Sleeper Sam, whose tools
are elite but whose OVR is 35 - the case the whole tool exists to catch.

The projections file also carries three players that are not in the report,
left over from a separate session, which is exactly the kind of mismatch a real
workflow produces.
"""

import io
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout

from ootp_scout import clipboard, cli

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
REPORT = os.path.join(FIXTURES, "pool_batters.tsv")
PROJECTIONS = os.path.join(FIXTURES, "batter-projections.csv")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


@contextmanager
def captured_clipboard(fail_with=None):
    """Intercept clipboard writes so tests never touch the real clipboard."""
    recorded = []
    original = cli.clipboard.copy

    def fake(text):
        if fail_with is not None:
            raise fail_with
        recorded.append(text)

    cli.clipboard.copy = fake
    try:
        yield recorded
    finally:
        cli.clipboard.copy = original


class FlagCommandTest(unittest.TestCase):
    def test_planted_sleeper_ranks_first(self):
        code, out, _ = run(["flag", REPORT, PROJECTIONS, "--limit", "5"])
        self.assertEqual(code, 0)
        body = out.splitlines()
        first_row = next(line for line in body if line.strip().startswith("1 "))
        self.assertIn("Sleeper Sam", first_row)

    def test_scouting_accuracy_is_shown_for_the_flagged_player(self):
        _, out, _ = run(["flag", REPORT, PROJECTIONS, "--limit", "5"])
        sleeper = next(line for line in out.splitlines() if "Sleeper Sam" in line)
        self.assertIn("Low", sleeper)

    def test_every_report_player_matches_a_projection(self):
        _, out, _ = run(["flag", REPORT, PROJECTIONS])
        self.assertIn("Matched: 41 of 41", out)

    def test_projection_only_players_do_not_appear(self):
        """Three players in the CSV are not in the report and must be ignored."""
        _, out, _ = run(["flag", REPORT, PROJECTIONS, "--limit", "50"])
        for absent in ("Cy Charlie", "Bo Bravo", "Al Alpha"):
            self.assertNotIn(absent, out)

    def test_min_z_filters(self):
        """--min-z applies to the underrated list, not the overrated one."""
        _, out, _ = run(["flag", REPORT, PROJECTIONS, "--min-z", "3",
                         "--overrated", "0"])
        rows = [line for line in out.splitlines()
                if line.strip() and line.strip()[0].isdigit()]
        self.assertEqual(len(rows), 1)
        self.assertIn("Sleeper Sam", rows[0])

    def test_writes_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "flagged.csv")
            code, _, _ = run(["flag", REPORT, PROJECTIONS, "--limit", "3",
                              "--out", destination])
            self.assertEqual(code, 0)
            with open(destination, encoding="utf-8") as handle:
                content = handle.read()
        self.assertIn("scouting_accuracy", content.splitlines()[0])
        self.assertIn("Sleeper Sam", content)

    def test_overrated_leaderboard_is_printed(self):
        _, out, _ = run(["flag", REPORT, PROJECTIONS, "--limit", "3",
                         "--overrated", "3"])
        self.assertIn("MOST UNDERRATED", out)
        self.assertIn("MOST OVERRATED", out)
        overrated_block = out.split("MOST OVERRATED")[1]
        rows = [line for line in overrated_block.splitlines()
                if line.strip() and line.strip()[0].isdigit()]
        self.assertEqual(len(rows), 3)
        # The worst shortfall leads, so the differential column is negative.
        self.assertIn("-", rows[0].split()[-3])

    def test_overrated_zero_turns_it_off(self):
        _, out, _ = run(["flag", REPORT, PROJECTIONS, "--overrated", "0"])
        self.assertNotIn("MOST OVERRATED", out)

    def test_overrated_gets_its_own_sheet(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl is not installed")
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "targets.xlsx")
            run(["flag", REPORT, PROJECTIONS, "--limit", "4", "--overrated", "4",
                 "--out", destination])
            book = openpyxl.load_workbook(destination)
            try:
                self.assertIn("Overrated", book.sheetnames)
                sheet = book["Overrated"]
                self.assertEqual(sheet.max_row, 5)
                worst = sheet.cell(row=2, column=9).value
                self.assertLess(worst, 0)
                # Strong negatives are tinted red, not green.
                self.assertEqual(sheet.cell(row=2, column=2).fill.fgColor.rgb,
                                 "FFFFC7CE")
            finally:
                book.close()

    def test_no_overrated_sheet_when_disabled(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl is not installed")
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "targets.xlsx")
            run(["flag", REPORT, PROJECTIONS, "--overrated", "0",
                 "--out", destination])
            book = openpyxl.load_workbook(destination)
            try:
                self.assertNotIn("Overrated", book.sheetnames)
            finally:
                book.close()

    def test_xlsx_out_writes_a_real_spreadsheet(self):
        """--out foo.xlsx must produce a workbook, not CSV text renamed.

        An earlier version wrote CSV to the .xlsx path. Excel then refused to
        open it, and nothing caught it because the spreadsheet tests called
        write_xlsx directly and never went through the CLI.
        """
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "targets.xlsx")
            code, out, _ = run(["flag", REPORT, PROJECTIONS, "--limit", "5",
                                "--out", destination])
            self.assertEqual(code, 0)
            with open(destination, "rb") as handle:
                magic = handle.read(4)
        # Every .xlsx is a zip archive.
        self.assertEqual(magic, b"PK\x03\x04")
        self.assertIn("highlighted", out)

    def test_xlsx_out_is_readable_as_a_workbook(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl is not installed")
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "targets.xlsx")
            run(["flag", REPORT, PROJECTIONS, "--limit", "5",
                 "--out", destination])
            book = openpyxl.load_workbook(destination)
            try:
                self.assertIn("Targets", book.sheetnames)
                self.assertIn("How this was calculated", book.sheetnames)
                sheet = book["Targets"]
                self.assertEqual(sheet.max_row, 6)  # header plus 5 players
                self.assertEqual(sheet.cell(row=1, column=6).value, "OVR")
            finally:
                book.close()

    def test_csv_out_still_writes_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "targets.csv")
            run(["flag", REPORT, PROJECTIONS, "--limit", "3",
                 "--out", destination])
            with open(destination, encoding="utf-8") as handle:
                first = handle.readline()
        self.assertTrue(first.startswith("rank,name,position"))

    def test_mismatched_projections_file_fails_clearly(self):
        code, _, err = run(["flag", REPORT, REPORT])
        self.assertEqual(code, 1)
        self.assertIn("Download CSV", err)

    def test_projections_from_a_different_pool_are_refused(self):
        """Two unrelated exports must not produce a confident-looking ranking."""
        with tempfile.TemporaryDirectory() as folder:
            other = os.path.join(folder, "other-projections.csv")
            with open(PROJECTIONS, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
            renamed = [lines[0]]
            for index, line in enumerate(lines[1:]):
                cells = line.split(",")
                cells[0] = f"Nobody {index}"
                renamed.append(",".join(cells))
            with open(other, "w", encoding="utf-8") as handle:
                handle.write("\n".join(renamed) + "\n")
            code, _, err = run(["flag", REPORT, other])
        self.assertEqual(code, 1)
        self.assertIn("two different pools", err)
        self.assertIn("41 players", err)

    def test_a_partial_match_warns_but_still_ranks(self):
        with tempfile.TemporaryDirectory() as folder:
            partial = os.path.join(folder, "partial-projections.csv")
            with open(PROJECTIONS, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
            keep = [lines[0]]
            for index, line in enumerate(lines[1:]):
                cells = line.split(",")
                if index % 3:                      # drop two thirds of them
                    cells[0] = f"Nobody {index}"
                keep.append(",".join(cells))
            with open(partial, "w", encoding="utf-8") as handle:
                handle.write("\n".join(keep) + "\n")
            code, out, err = run(["flag", REPORT, partial, "--limit", "3"])
        self.assertEqual(code, 0)
        self.assertIn("WARNING", err)
        self.assertIn("matched a projection", err)
        self.assertTrue(any(line.strip().startswith("1 ")
                            for line in out.splitlines()))


class PrepareCommandTest(unittest.TestCase):
    def test_detects_the_view_and_writes_a_paste_block(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "paste.tsv")
            with captured_clipboard():
                code, out, _ = run(["prepare", REPORT, "--out", destination])
            self.assertEqual(code, 0)
            with open(destination, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        self.assertIn("Batting Ratings", out)
        self.assertIn("batting-projections.csv", out)
        self.assertEqual(len(lines), 42)  # header plus 41 players
        self.assertTrue(lines[0].startswith("POS\t#\tName"))

    def test_paste_block_goes_to_the_clipboard_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "paste.tsv")
            with captured_clipboard() as recorded:
                _, out, _ = run(["prepare", REPORT, "--out", destination])
        self.assertEqual(len(recorded), 1)
        self.assertIn("Ctrl+V", out)
        with open(REPORT, encoding="utf-8") as handle:
            expected_players = len(handle.read().splitlines()) - 1
        self.assertEqual(len(recorded[0].strip().splitlines()),
                         expected_players + 1)
        self.assertTrue(recorded[0].startswith("POS\t#\tName"))

    def test_no_copy_leaves_the_clipboard_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "paste.tsv")
            with captured_clipboard() as recorded:
                _, out, _ = run(["prepare", REPORT, "--out", destination,
                                 "--no-copy"])
        self.assertEqual(recorded, [])
        self.assertNotIn("Ctrl+V", out)
        self.assertIn("Paste the whole contents", out)

    def test_a_clipboard_failure_is_reported_but_not_fatal(self):
        """A locked clipboard must not lose the run - the file is still there."""
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "paste.tsv")
            failure = clipboard.ClipboardError("clipboard busy")
            with captured_clipboard(fail_with=failure):
                code, out, err = run(["prepare", REPORT, "--out", destination])
            self.assertTrue(os.path.exists(destination))
        self.assertEqual(code, 0)
        self.assertIn("clipboard busy", err)
        self.assertIn("Paste the whole contents", out)

    def test_rejects_values_the_calculator_would_reject(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = os.path.join(folder, "bad.tsv")
            with open(REPORT, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
            cells = lines[1].split("\t")
            cells[8] = "52"  # CON, not a multiple of 5
            lines[1] = "\t".join(cells)
            with open(bad, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
            code, _, err = run(["prepare", bad, "--scale", "20 to 80"])
        self.assertEqual(code, 1)
        self.assertIn("multiple of 5", err)
        self.assertIn('--scale "1 to 100"', err)

    def test_same_values_pass_on_the_1_100_scale(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "paste.tsv")
            with captured_clipboard():
                code, _, _ = run(["prepare", REPORT, "--scale", "1 to 100",
                                  "--out", destination])
        self.assertEqual(code, 0)

    def test_draft_pool_export_is_rejected_with_guidance(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "draft.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("POS,#,Name,Inf,DOB,Age,NAT,HT,WT,B,T,OVR,POT,"
                             "Prone,DEM,Sign,SctAcc\n")
                handle.write("SP,14,Nicolas Arnaud,,02/20/2010,21,CAN,6' 2\","
                             "185 lbs,Right,Right,40,80,Normal,-,Easy,High\n")
            code, _, err = run(["prepare", path])
        self.assertEqual(code, 1)
        self.assertIn("Ratings view", err)


if __name__ == "__main__":
    unittest.main()

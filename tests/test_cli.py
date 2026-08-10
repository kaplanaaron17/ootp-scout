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
from contextlib import redirect_stderr, redirect_stdout

from ootp_scout import cli

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
REPORT = os.path.join(FIXTURES, "pool_batters.tsv")
PROJECTIONS = os.path.join(FIXTURES, "batter-projections.csv")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


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
        _, out, _ = run(["flag", REPORT, PROJECTIONS, "--min-z", "3"])
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

    def test_mismatched_projections_file_fails_clearly(self):
        code, _, err = run(["flag", REPORT, REPORT])
        self.assertEqual(code, 1)
        self.assertIn("Download CSV", err)


class PrepareCommandTest(unittest.TestCase):
    def test_detects_the_view_and_writes_a_paste_block(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "paste.tsv")
            code, out, _ = run(["prepare", REPORT, "--out", destination])
            self.assertEqual(code, 0)
            with open(destination, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        self.assertIn("Batting Ratings", out)
        self.assertIn("batter-projections", out)
        self.assertEqual(len(lines), 42)  # header plus 41 players
        self.assertTrue(lines[0].startswith("POS\t#\tName"))

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
        self.assertIn("1-100", err)

    def test_same_values_pass_on_the_1_100_scale(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = os.path.join(folder, "paste.tsv")
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

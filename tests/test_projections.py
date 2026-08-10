import os
import tempfile
import unittest

from ootp_scout import projections, tables

CALC_CSV = """Name,Team,Pos,Bats,G,PA,AB,H,2B,3B,HR,BB,SO,AVG,OBP,SLG,ISO,OPS,OPS+,BABIP,WAR,SB,CS
Cy Charlie,-,SS,R,150,600,527,161,34,4,33,67,98,.306,.390,.573,.267,.964,166,.324,7.6,11,4
Bo Bravo,-,1B,L,150,600,537,156,33,1,34,56,162,.291,.365,.543,.252,.908,150,.359,3.5,0,0
"""


class TempFile:
    def __init__(self, text, suffix=".csv"):
        self.text, self.suffix = text, suffix

    def __enter__(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=self.suffix,
                                             delete=False, newline="",
                                             encoding="utf-8")
        handle.write(self.text)
        handle.close()
        self.path = handle.name
        return self.path

    def __exit__(self, *exc):
        os.unlink(self.path)


class LoadProjectionsTest(unittest.TestCase):
    def test_reads_name_position_and_war(self):
        with TempFile(CALC_CSV) as path:
            loaded, problems = projections.load_projections(path)
        self.assertEqual(problems, [])
        self.assertEqual([p.name for p in loaded], ["Cy Charlie", "Bo Bravo"])
        self.assertEqual(loaded[0].war, 7.6)
        self.assertEqual(loaded[0].position, "SS")
        self.assertEqual(loaded[0].stats["OPS"], ".964")

    def test_missing_war_column_raises_with_guidance(self):
        with TempFile("Name,Pos\nAl,CF\n") as path:
            with self.assertRaises(ValueError) as caught:
                projections.load_projections(path)
        self.assertIn("Download CSV", str(caught.exception))

    def test_comma_in_name_is_reported_not_dropped_silently(self):
        broken = CALC_CSV + "Ken Griffey, Jr.,-,CF,L,150,600,530,150,30,2,30,60,100,.283,.360,.520,.237,.880,140,.310,5.0,5,1\n"
        with TempFile(broken) as path:
            loaded, problems = projections.load_projections(path)
        self.assertEqual(len(loaded), 2)
        self.assertIn("comma in a player name", problems[0][1])

    def test_non_numeric_war_is_reported(self):
        bad = CALC_CSV.replace(",7.6,", ",n/a,")
        with TempFile(bad) as path:
            loaded, problems = projections.load_projections(bad_path := path)
        self.assertEqual(len(loaded), 1)
        self.assertIn("not a number", problems[0][1])


class IndexByNameTest(unittest.TestCase):
    def _projection(self, name, war):
        return projections.Projection(name=name, position="CF", war=war, stats={})

    def test_indexes_case_insensitively(self):
        index, duplicates = projections.index_by_name(
            [self._projection("Al Alpha", 3.0)])
        self.assertEqual(duplicates, set())
        self.assertEqual(index["al alpha"].war, 3.0)

    def test_duplicates_are_dropped_and_reported(self):
        index, duplicates = projections.index_by_name([
            self._projection("Al Alpha", 3.0),
            self._projection("Al Alpha", 5.0),
            self._projection("Bo Bravo", 1.0),
        ])
        self.assertEqual(duplicates, {"Al Alpha"})
        self.assertNotIn("al alpha", index)
        self.assertIn("bo bravo", index)


class TablesTest(unittest.TestCase):
    def test_detects_tab_delimiter(self):
        headers, rows = tables.parse_table("A\tB\n1\t2\n")
        self.assertEqual(headers, ["A", "B"])
        self.assertEqual(rows, [["1", "2"]])

    def test_detects_comma_delimiter(self):
        headers, rows = tables.parse_table("A,B\n1,2\n")
        self.assertEqual(headers, ["A", "B"])

    def test_tab_wins_so_names_may_contain_commas(self):
        headers, rows = tables.parse_table("Name\tB\nGriffey, Jr.\t2\n")
        self.assertEqual(rows[0][0], "Griffey, Jr.")

    def test_empty_file_raises(self):
        with self.assertRaises(ValueError):
            tables.parse_table("   ")


if __name__ == "__main__":
    unittest.main()

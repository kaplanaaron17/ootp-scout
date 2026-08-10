"""Reading OOTP's `Write report to disk` HTML directly."""

import os
import tempfile
import unittest

from ootp_scout import tables, views

# Shaped like an OOTP report: the player grid nested inside a layout table.
REPORT_HTML = """<html><head><title>Batting Ratings</title></head><body>
<table><tr><td>
  <table class="data">
    <tr><th>POS</th><th>#</th><th>Name</th><th>Inf</th><th>Age</th><th>B</th>
        <th>T</th><th>OVR</th><th>CON</th><th>GAP</th><th>POW</th><th>EYE</th>
        <th>K's</th><th>CON vL</th><th>POW vL</th><th>CON vR</th><th>POW vR</th>
        <th>BUN</th><th>BFH</th><th>SPE</th><th>STE</th><th>DEF</th>
        <th>SctAcc</th></tr>
    <tr><td>CF</td><td>14</td><td>Al Alpha</td><td>&nbsp;</td><td>22</td>
        <td>R</td><td>R</td><td>45</td><td>55</td><td>50</td><td>45</td>
        <td>50</td><td>50</td><td>55</td><td>45</td><td>55</td><td>45</td>
        <td>30</td><td>30</td><td>60</td><td>55</td><td>60</td>
        <td>High</td></tr>
    <tr><td>1B</td><td>7</td><td>Bo Bravo</td><td>&nbsp;</td><td>24</td>
        <td>L</td><td>L</td><td>60</td><td>70</td><td>60</td><td>70</td>
        <td>55</td><td>45</td><td>70</td><td>70</td><td>70</td><td>70</td>
        <td>20</td><td>20</td><td>30</td><td>25</td><td>40</td>
        <td>Normal</td></tr>
  </table>
</td></tr></table>
</body></html>"""


class ParseHtmlTest(unittest.TestCase):
    def test_extracts_the_widest_table_not_the_layout_wrapper(self):
        headers, rows = tables.parse_table(REPORT_HTML)
        self.assertEqual(headers[0], "POS")
        self.assertEqual(len(headers), 23)
        self.assertEqual(len(rows), 2)

    def test_cell_values_survive_intact(self):
        headers, rows = tables.parse_table(REPORT_HTML)
        record = dict(zip(headers, rows[0]))
        self.assertEqual(record["Name"], "Al Alpha")
        self.assertEqual(record["OVR"], "45")
        self.assertEqual(record["SctAcc"], "High")
        self.assertEqual(record["K's"], "50")

    def test_nbsp_becomes_blank_not_a_stray_character(self):
        headers, rows = tables.parse_table(REPORT_HTML)
        self.assertEqual(dict(zip(headers, rows[0]))["Inf"], "")

    def test_the_result_feeds_straight_into_view_detection(self):
        headers, rows = tables.parse_table(REPORT_HTML)
        view = views.identify_view(headers)
        self.assertEqual((view.role, view.mode), (views.BATTER, views.CURRENT))
        parsed, problems = views.parse_rows(headers, rows, view)
        self.assertEqual(problems, [])
        self.assertEqual([p.name for p in parsed], ["Al Alpha", "Bo Bravo"])
        self.assertEqual(parsed[0].grade, 45.0)

    def test_read_table_handles_an_html_file_on_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.html")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(REPORT_HTML)
            headers, rows = tables.read_table(path)
        self.assertEqual(headers[2], "Name")
        self.assertEqual(len(rows), 2)

    def test_html_without_a_table_raises_clearly(self):
        with self.assertRaises(ValueError) as caught:
            tables.parse_table("<html><body><p>No table here</p></body></html>")
        self.assertIn("no table", str(caught.exception).lower())

    def test_tsv_is_still_read_as_tsv(self):
        headers, rows = tables.parse_table("A\tB\n1\t2\n")
        self.assertEqual((headers, rows), (["A", "B"], [["1", "2"]]))

    def test_a_csv_mentioning_html_is_not_treated_as_html(self):
        headers, _ = tables.parse_table("Name,Note\nAl,likes <table> tags\n")
        self.assertEqual(headers, ["Name", "Note"])


class LooksLikeHtmlTest(unittest.TestCase):
    def test_positive_cases(self):
        for text in ("<!DOCTYPE html><html>", "<html><table>", "  <table><tr>"):
            with self.subTest(text=text):
                self.assertTrue(tables.looks_like_html(text))

    def test_negative_cases(self):
        for text in ("POS\t#\tName", "Name,WAR", ""):
            with self.subTest(text=text):
                self.assertFalse(tables.looks_like_html(text))


if __name__ == "__main__":
    unittest.main()

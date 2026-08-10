"""The formatted .xlsx output."""

import os
import tempfile
import unittest

from ootp_scout import flagging, spreadsheet

try:
    import openpyxl
except ImportError:  # pragma: no cover - environment dependent
    openpyxl = None


def finding(name, z, position="CF", grade=50.0, war=3.0, accuracy="High"):
    subject = flagging.Subject(name=name, position=position, grade=grade,
                               war=war, meta={"scouting_accuracy": accuracy,
                                              "age": "22"})
    return flagging.Finding(subject=subject, expected_war=war - z,
                            residual=z, z_score=z, group="hitters")


def sample_fit():
    return flagging.GroupFit(group="hitters", count=40,
                             coefficients=[-10.0, 0.22, 0.8], residual_sd=1.9,
                             degree=1, positions=["C"], reference_position="1B")


@unittest.skipIf(openpyxl is None, "openpyxl is not installed")
class WriteXlsxTest(unittest.TestCase):
    def setUp(self):
        self.findings = [finding("Strong Guy", 3.1), finding("Notable Guy", 1.4),
                         finding("Ordinary Guy", 0.2), finding("Weak Guy", -1.8)]
        self.folder = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.folder.name, "targets.xlsx")
        spreadsheet.write_xlsx(self.path, self.findings, [sample_fit()],
                               grade_label="OVR")
        self.book = openpyxl.load_workbook(self.path)

    def tearDown(self):
        self.book.close()
        self.folder.cleanup()

    def test_file_is_written_and_opens(self):
        self.assertTrue(os.path.exists(self.path))
        self.assertIn("Targets", self.book.sheetnames)

    def test_header_uses_the_grade_label(self):
        sheet = self.book["Targets"]
        headers = [cell.value for cell in sheet[1]]
        self.assertEqual(headers[5], "OVR")
        self.assertIn("Differential", headers)
        self.assertIn("Scouting Accuracy", headers)

    def test_rows_are_in_order_with_values(self):
        sheet = self.book["Targets"]
        names = [sheet.cell(row=r, column=2).value
                 for r in range(2, sheet.max_row + 1)]
        self.assertEqual(names, ["Strong Guy", "Notable Guy", "Ordinary Guy",
                                 "Weak Guy"])
        self.assertEqual(sheet.cell(row=2, column=1).value, 1)
        self.assertEqual(sheet.cell(row=2, column=10).value, 3.1)

    def test_strong_rows_are_highlighted_green(self):
        sheet = self.book["Targets"]
        fill = sheet.cell(row=2, column=2).fill
        self.assertEqual(fill.fgColor.rgb, "FFC7EFCE")

    def test_notable_rows_are_highlighted_amber(self):
        sheet = self.book["Targets"]
        self.assertEqual(sheet.cell(row=3, column=2).fill.fgColor.rgb,
                         "FFFFF2CC")

    def test_ordinary_and_weak_rows_are_not_highlighted(self):
        sheet = self.book["Targets"]
        for row in (4, 5):
            self.assertNotIn(sheet.cell(row=row, column=2).fill.fgColor.rgb,
                             ("FFC7EFCE", "FFFFF2CC"))

    def test_threshold_is_configurable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "strict.xlsx")
            spreadsheet.write_xlsx(path, self.findings, [sample_fit()],
                                   strong_z=5.0)
            book = openpyxl.load_workbook(path)
            try:
                sheet = book["Targets"]
                # Nobody clears z >= 5, so no green anywhere.
                greens = [r for r in range(2, sheet.max_row + 1)
                          if sheet.cell(row=r, column=2).fill.fgColor.rgb
                          == "FFC7EFCE"]
                self.assertEqual(greens, [])
            finally:
                book.close()

    def test_method_sheet_records_the_fit(self):
        sheet = self.book["How this was calculated"]
        text = "\n".join(str(cell.value) for row in sheet.iter_rows()
                         for cell in row if cell.value is not None)
        self.assertIn("0.22", text)          # slope
        self.assertIn("1.9", text)           # residual sd
        self.assertIn("C", text)             # the position with an offset
        self.assertIn("Scouting accuracy", text)

    def test_freeze_panes_and_filter_are_set(self):
        sheet = self.book["Targets"]
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertIsNotNone(sheet.auto_filter.ref)

    def test_empty_findings_still_produce_a_readable_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "empty.xlsx")
            spreadsheet.write_xlsx(path, [], [sample_fit()])
            book = openpyxl.load_workbook(path)
            try:
                self.assertEqual(book["Targets"].max_row, 1)
            finally:
                book.close()


if __name__ == "__main__":
    unittest.main()

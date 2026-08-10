"""Finding the report OOTP just wrote."""

import os
import tempfile
import time
import unittest

from ootp_scout import reports


def make_report(root, version, save, filename, age_seconds=0):
    folder = os.path.join(root, version, "saved_games", save, "news", "html",
                          "temp")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("<html><table><tr><th>POS</th></tr></table></html>")
    if age_seconds:
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
    return path


class FindReportsTest(unittest.TestCase):
    def test_finds_reports_in_the_ootp_layout(self):
        with tempfile.TemporaryDirectory() as root:
            expected = make_report(root, "OOTP Baseball 27", "Top Shelf.lg",
                                   "2026-08-09-23-55-57.html")
            found = reports.find_reports([root])
        self.assertEqual([f.path for f in found], [expected])

    def test_newest_wins(self):
        with tempfile.TemporaryDirectory() as root:
            make_report(root, "OOTP Baseball 27", "Top Shelf.lg", "old.html",
                        age_seconds=3600)
            newest = make_report(root, "OOTP Baseball 27", "Top Shelf.lg",
                                 "new.html")
            self.assertEqual(reports.find_latest([root]).path, newest)

    def test_reports_the_save_name_not_the_folder_above_it(self):
        with tempfile.TemporaryDirectory() as root:
            make_report(root, "OOTP Baseball 27", "Top Shelf Baseball.lg",
                        "a.html")
            self.assertEqual(reports.find_latest([root]).save,
                             "Top Shelf Baseball.lg")

    def test_searches_across_versions_and_saves(self):
        with tempfile.TemporaryDirectory() as root:
            make_report(root, "OOTP Baseball 26", "Old League.lg", "a.html",
                        age_seconds=7200)
            make_report(root, "OOTP Baseball 27", "New League.lg", "b.html",
                        age_seconds=3600)
            newest = make_report(root, "OOTP Baseball 27", "Other.lg", "c.html")
            found = reports.find_reports([root])
        self.assertEqual(len(found), 3)
        self.assertEqual(found[0].path, newest)

    def test_htm_extension_is_matched_too(self):
        with tempfile.TemporaryDirectory() as root:
            expected = make_report(root, "OOTP Baseball 27", "S.lg", "a.htm")
            self.assertEqual(reports.find_latest([root]).path, expected)

    def test_nothing_found_raises_with_instructions(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(FileNotFoundError) as caught:
                reports.find_latest([root])
        message = str(caught.exception)
        self.assertIn("Write report to disk", message)

    def test_unrelated_html_elsewhere_is_ignored(self):
        """Only the report temp folder counts; league news must not match."""
        with tempfile.TemporaryDirectory() as root:
            stray = os.path.join(root, "OOTP Baseball 27", "saved_games",
                                 "S.lg", "news", "html", "leagues")
            os.makedirs(stray)
            with open(os.path.join(stray, "transactions.html"), "w",
                      encoding="utf-8") as handle:
                handle.write("<html></html>")
            self.assertEqual(reports.find_reports([root]), [])

    def test_missing_root_is_skipped_not_fatal(self):
        self.assertEqual(reports.find_reports(["Z:\\definitely\\not\\here"]), [])


class FindLatestProjectionsTest(unittest.TestCase):
    def _write(self, folder, name, age_seconds=0):
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("Name,WAR\nAl,3.0\n")
        if age_seconds:
            stamp = time.time() - age_seconds
            os.utime(path, (stamp, stamp))
        return path

    def test_finds_the_sites_actual_filename(self):
        """The site exports batting-/pitching-, not batter-/pitcher-."""
        with tempfile.TemporaryDirectory() as folder:
            expected = self._write(folder, "batting-projections.csv")
            self.assertEqual(reports.find_latest_projections([folder]), expected)

    def test_finds_pitching_too(self):
        with tempfile.TemporaryDirectory() as folder:
            expected = self._write(folder, "pitching-projections.csv")
            self.assertEqual(reports.find_latest_projections([folder]), expected)

    def test_browser_duplicate_suffix_is_matched(self):
        with tempfile.TemporaryDirectory() as folder:
            self._write(folder, "batting-projections.csv", age_seconds=600)
            newest = self._write(folder, "batting-projections (2).csv")
            self.assertEqual(reports.find_latest_projections([folder]), newest)

    def test_newest_wins_across_types(self):
        with tempfile.TemporaryDirectory() as folder:
            self._write(folder, "batting-projections.csv", age_seconds=3600)
            newest = self._write(folder, "pitching-projections.csv")
            self.assertEqual(reports.find_latest_projections([folder]), newest)

    def test_unrelated_csvs_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            self._write(folder, "statsplus.csv")
            with self.assertRaises(FileNotFoundError):
                reports.find_latest_projections([folder])

    def test_nothing_found_raises_with_instructions(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError) as caught:
                reports.find_latest_projections([folder])
        self.assertIn("Download CSV", str(caught.exception))


class CandidateRootsTest(unittest.TestCase):
    def test_only_returns_directories_that_exist(self):
        for root in reports.candidate_roots():
            self.assertTrue(os.path.isdir(root))

    def test_no_duplicates(self):
        found = [os.path.normcase(r) for r in reports.candidate_roots()]
        self.assertEqual(len(found), len(set(found)))


if __name__ == "__main__":
    unittest.main()

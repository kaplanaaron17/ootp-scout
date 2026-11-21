"""One-click import: the overwrite, the old-report cleanup, and what it shows.

Three things an import now does by default in the window - replace the list
before it, compact the store, delete the reports OOTP left behind - and the
Projections tabs it lands on, including the fielding terms WAR is built from.
"""

import os
import sqlite3
import tempfile
import time
import unittest

from ootp_scout import database, projection, reports, service, statline

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
BATTERS = os.path.join(FIXTURES, "pool_batters.tsv")
PITCHERS = os.path.join(FIXTURES, "groundfly_pitchers.tsv")

AVERAGE = dict(contact=100, gap=100, power=100, eye=100, avoid_ks=100,
               speed=100, stealing=100)


class WarBreakdownTest(unittest.TestCase):
    """Bat, BsR, Fld and PosAdj are WAR's own terms, not a second model."""

    def test_the_terms_add_up_to_the_war(self):
        line = projection.project_batter(defense=140, position="SS", **AVERAGE)
        replacement = projection.WAR_PA * line.plate_appearances
        runs = (line.batting_runs + line.baserunning_runs
                + line.fielding_runs + line.position_runs)
        self.assertAlmostEqual(runs / 10 + replacement, line.war, places=6)

    def test_a_better_glove_saves_more_runs(self):
        poor = projection.project_batter(defense=60, position="SS", **AVERAGE)
        good = projection.project_batter(defense=180, position="SS", **AVERAGE)
        self.assertGreater(good.fielding_runs, poor.fielding_runs)
        self.assertGreater(good.war, poor.war)
        self.assertAlmostEqual(good.batting_runs, poor.batting_runs)

    def test_the_position_adjustment_follows_the_position(self):
        catcher = projection.project_batter(defense=100, position="C",
                                            **AVERAGE)
        first = projection.project_batter(defense=100, position="1B",
                                          **AVERAGE)
        self.assertGreater(catcher.position_runs, 0)
        self.assertLess(first.position_runs, 0)

    def test_no_defense_rating_means_no_fielding_projection(self):
        """Not 0.0, which would read as an exactly average glove."""
        line = projection.project_batter(defense=None, position="LF",
                                         **AVERAGE)
        self.assertIsNone(line.fielding_runs)
        stored = statline.fields(line, False)
        self.assertNotIn("fielding_runs", stored)
        self.assertNotIn("defense_runs", statline.derive(stored, False))

    def test_def_is_fielding_plus_position(self):
        line = projection.project_batter(defense=150, position="CF",
                                         **AVERAGE)
        full = statline.derive(statline.fields(line, False), False)
        self.assertAlmostEqual(full["defense_runs"],
                               line.fielding_runs + line.position_runs,
                               places=3)

    def test_the_card_shows_the_fielding_terms(self):
        line = projection.project_batter(defense=150, position="CF",
                                         **AVERAGE)
        headings = [h for h, _v in statline.display(
            statline.fields(line, False), False)]
        for wanted in ("Bat", "BsR", "Fld", "PosAdj", "Def", "wRC+", "WAR"):
            self.assertIn(wanted, headings)

    def test_an_older_stored_line_still_reads(self):
        """Recorded before the breakdown was kept: no Def, nothing broken."""
        old = {"plate_appearances": 600, "hits": 150, "avg": .27, "slg": .45}
        self.assertNotIn("defense_runs", statline.derive(old, False))


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.folder.name, "store.db")

    def tearDown(self):
        self.folder.cleanup()

    def _import(self, path=BATTERS, **kwargs):
        kwargs.setdefault("league", "Demo")
        return service.import_export(path, db=self.db, **kwargs)

    def _count(self):
        connection = database.connect(self.db)
        try:
            return connection.execute(
                "SELECT COUNT(*) FROM observations").fetchone()[0]
        finally:
            connection.close()

    def _shorter(self, keep_players):
        with open(BATTERS, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        path = os.path.join(self.folder.name, "short.tsv")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines[:keep_players + 1]) + "\n")
        return path

    def _age_everything(self, seconds=5):
        """Make the stored rows older than the next import's stamp."""
        connection = database.connect(self.db)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                              time.gmtime(time.time() - seconds))
        connection.execute("UPDATE observations SET seen_at = ?", (stamp,))
        connection.commit()
        connection.close()


class OverwriteTest(ServiceTest):
    def test_a_second_list_the_same_day_replaces_the_first(self):
        """forget_before kept same-day leftovers; an overwrite must not."""
        self._import()
        self._age_everything()
        result = self._import(self._shorter(10), replace=True)
        self.assertEqual(result.removed, 31)
        self.assertEqual(self._count(), 10)

    def test_without_it_the_leftovers_stay(self):
        self._import()
        self._age_everything()
        self._import(self._shorter(10))
        self.assertEqual(self._count(), 41)

    def test_the_file_shrinks_after_an_overwrite(self):
        self._import()
        self._age_everything()
        before = os.path.getsize(self.db)
        self._import(self._shorter(6), replace=True)
        self.assertLess(os.path.getsize(self.db), before)

    def test_the_result_says_which_role_was_imported(self):
        self.assertEqual(self._import().role, "batter")
        self.assertEqual(self._import(PITCHERS).role, "pitcher")


class ProjectionsTest(ServiceTest):
    def test_hitters_and_pitchers_come_back_apart(self):
        self._import()
        self._import(PITCHERS)
        table = service.projections(db=self.db)
        self.assertEqual(len(table.hitters), 41)
        self.assertEqual(len(table.pitchers), 5)
        self.assertFalse(any(s.is_pitcher for s in table.hitters))
        self.assertTrue(all(s.is_pitcher for s in table.pitchers))

    def test_best_first_by_war(self):
        self._import()
        wars = [s.war for s in service.projections(db=self.db).hitters]
        self.assertEqual(wars, sorted(wars, reverse=True))

    def test_every_stat_asked_for_is_there(self):
        self._import()
        self._import(PITCHERS)
        table = service.projections(db=self.db)
        bat = statline.derive(table.hitters[0].projected, False)
        for key in ("wrc_plus", "fielding_runs", "defense_runs", "war"):
            self.assertIn(key, bat)
        arm = statline.derive(table.pitchers[0].projected, True)
        for key in ("era", "starts", "innings", "war"):
            self.assertIn(key, arm)

    def test_a_pool_too_small_to_fit_still_projects(self):
        """Projection needs no baseline, so five is not a minimum here."""
        self._import(self._shorter(5))
        connection = database.connect(self.db)
        connection.execute(
            "DELETE FROM observations WHERE id NOT IN "
            "(SELECT id FROM observations LIMIT 2)")
        connection.commit()
        connection.close()
        self.assertEqual(len(service.projections(db=self.db).hitters), 2)

    def test_nothing_stored_is_a_readable_complaint(self):
        with self.assertRaises(service.ScoutError):
            service.projections(db=self.db)


def ootp_folder(root):
    folder = os.path.join(root, "OOTP Baseball 27", "saved_games",
                          "Top Shelf.lg", "news", "html", "temp")
    os.makedirs(folder, exist_ok=True)
    return folder


def write(folder, name, age_seconds=0, body="x" * 2000):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    if age_seconds:
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
    return path


class PruneTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.folder = ootp_folder(self.root.name)

    def tearDown(self):
        self.root.cleanup()

    def test_older_reports_go_and_the_imported_one_stays(self):
        old = write(self.folder, "2026-11-01-10-00-00.html", age_seconds=600)
        older = write(self.folder, "2026-10-01-10-00-00.html",
                      age_seconds=6000)
        current = write(self.folder, "2026-11-21-10-00-00.html")
        pruned = reports.prune_older(current)
        self.assertEqual(pruned.files, 2)
        self.assertEqual(pruned.bytes, 4000)
        self.assertTrue(os.path.exists(current))
        self.assertFalse(os.path.exists(old))
        self.assertFalse(os.path.exists(older))

    def test_a_newer_report_survives(self):
        """One written while this one was being read is not ours to delete."""
        current = write(self.folder, "2026-11-21-10-00-00.html",
                        age_seconds=600)
        newer = write(self.folder, "2026-11-21-10-10-00.html")
        reports.prune_older(current)
        self.assertTrue(os.path.exists(newer))

    def test_only_files_named_the_way_ootp_names_them(self):
        mine = write(self.folder, "my notes.html", age_seconds=600)
        sheet = write(self.folder, "2026-11-01-10-00-00.csv", age_seconds=600)
        current = write(self.folder, "2026-11-21-10-00-00.html")
        self.assertEqual(reports.prune_older(current).files, 0)
        self.assertTrue(os.path.exists(mine))
        self.assertTrue(os.path.exists(sheet))

    def test_nothing_outside_the_ootp_temp_folder_is_touched(self):
        elsewhere = os.path.join(self.root.name, "Downloads")
        os.makedirs(elsewhere)
        old = write(elsewhere, "2026-11-01-10-00-00.html", age_seconds=600)
        current = write(elsewhere, "2026-11-21-10-00-00.html")
        self.assertEqual(reports.prune_older(current).files, 0)
        self.assertTrue(os.path.exists(old))

    def test_the_folder_shape_is_recognised(self):
        self.assertTrue(reports.is_ootp_temp_folder(self.folder))
        self.assertFalse(reports.is_ootp_temp_folder(self.root.name))
        self.assertFalse(reports.is_ootp_temp_folder(
            os.path.join(self.root.name, "news", "html", "temp")))

    def test_an_import_can_prune_as_it_goes(self):
        with open(BATTERS, encoding="utf-8") as handle:
            body = handle.read()
        old = write(self.folder, "2026-11-01-10-00-00.html", age_seconds=600,
                    body=body)
        renamed = write(self.folder, "2026-11-21-10-00-00.html", body=body)
        db = os.path.join(self.root.name, "store.db")
        result = service.import_export(renamed, prune_reports=True, db=db)
        self.assertEqual(result.pruned_files, 1)
        self.assertEqual(result.league, "Top Shelf")
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(renamed))

    def test_an_import_does_not_prune_unless_asked(self):
        with open(BATTERS, encoding="utf-8") as handle:
            body = handle.read()
        old = write(self.folder, "2026-11-01-10-00-00.html", age_seconds=600,
                    body=body)
        current = write(self.folder, "2026-11-21-10-00-00.html", body=body)
        db = os.path.join(self.root.name, "store.db")
        result = service.import_export(current, db=db)
        self.assertEqual(result.pruned_files, 0)
        self.assertTrue(os.path.exists(old))


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.connection = database.connect(
            os.path.join(self.folder.name, "t.db"))

    def tearDown(self):
        self.connection.close()
        self.folder.cleanup()

    def _add(self, name, seen_at, role="batter", league="L"):
        database.record(self.connection, [database.Observation(
            name=name, mode="current", role=role, league=league, grade=50.0,
            war=1.0, seen_at=seen_at)])

    def test_forget_older_than_is_scoped_and_to_the_second(self):
        self._add("Early", "2026-11-21T09:00:00+00:00")
        self._add("Late", "2026-11-21T10:00:00+00:00")
        self._add("Arm", "2026-11-21T09:00:00+00:00", role="pitcher")
        self._add("Other", "2026-11-21T09:00:00+00:00", league="M")
        stamp = database.newest_stamp(self.connection, "L", "current",
                                      "batter")
        self.assertEqual(stamp, "2026-11-21T10:00:00+00:00")
        removed = database.forget_older_than(self.connection, "L", "current",
                                             "batter", stamp)
        self.assertEqual(removed, 1)
        names = {r["name"] for r in self.connection.execute(
            "SELECT name FROM observations")}
        self.assertEqual(names, {"Late", "Arm", "Other"})

    def test_compact_runs_on_an_open_connection(self):
        self._add("Early", "2026-11-21T09:00:00+00:00")
        database.compact(self.connection)
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM observations").fetchone()[0], 1)
        self.assertIsInstance(self.connection, sqlite3.Connection)


class LaunchTest(unittest.TestCase):
    def test_no_arguments_opens_the_window(self):
        """A stand-in window, so this runs where tkinter is not installed."""
        import sys
        import types
        from unittest import mock

        import ootp_scout
        from ootp_scout import cli

        opened = []
        fake = types.ModuleType("ootp_scout.gui")
        fake.main = lambda db=None: opened.append(db) or 0
        with mock.patch.dict(sys.modules, {"ootp_scout.gui": fake}), \
                mock.patch.object(ootp_scout, "gui", fake, create=True):
            self.assertEqual(cli.main([]), 0)
        self.assertEqual(opened, [None])

if __name__ == "__main__":
    unittest.main()

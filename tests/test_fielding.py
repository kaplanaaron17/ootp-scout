"""Fielding at every position, from OOTP's position ratings."""

import os
import tempfile
import time
import unittest

from ootp_scout import database, fielding, projection, service, statline, tables

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
BATTERS = os.path.join(FIXTURES, "pool_batters.tsv")
PITCHERS = os.path.join(FIXTURES, "groundfly_pitchers.tsv")

# A shortstop who can really play short, a statue anywhere on the dirt, and
# nobody who can catch.
SPREAD = {"C": "-", "1B": 55, "2B": 65, "3B": 60, "SS": 70, "LF": 50,
          "CF": 45, "RF": 50}


def with_positions(folder, ratings_for, name="positions.tsv"):
    """The batting fixture with position-rating columns added."""
    headers, rows = tables.read_table(BATTERS)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\t".join(headers + list(fielding.POSITIONS)) + "\n")
        for cells in rows:
            player = cells[headers.index("Name")]
            ratings = ratings_for(player)
            handle.write("\t".join(list(cells) + [
                str(ratings.get(p, "-")) for p in fielding.POSITIONS]) + "\n")
    return path


def fielding_report(folder, ratings_for, names, name="fielding.tsv"):
    """A stand-alone Fielding Ratings export: no hitting ratings at all."""
    headers = (["POS", "#", "Name", "Inf", "Age", "B", "T", "IF RNG",
                "IF ERR", "IF ARM", "TDP", "OF RNG", "OF ERR", "OF ARM"]
               + list(fielding.POSITIONS))
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\t".join(headers) + "\n")
        for number, (player, pos) in enumerate(names, start=1):
            ratings = ratings_for(player)
            handle.write("\t".join(
                [pos, str(number), player, "", "25", "R", "R"]
                + ["50"] * 7
                + [str(ratings.get(p, "-")) for p in fielding.POSITIONS])
                + "\n")
    return path


class MathTest(unittest.TestCase):
    def line(self, position="SS", defense=100):
        line = projection.project_batter(
            contact=100, gap=100, power=100, eye=100, avoid_ks=100,
            speed=100, stealing=100, defense=defense, position=position)
        return statline.fields(line, False)

    def test_his_own_position_at_his_def_rating_reproduces_his_war(self):
        """The same glove at the same spot cannot change anything."""
        stored = self.line("SS", defense=120)
        displayed = 20 + 120 * 60 / 200            # internal 120 on 20-80
        out = fielding.position_fields(stored, {"SS": displayed}, "20 to 80")
        self.assertAlmostEqual(out["war_SS"], stored["war"], places=3)
        self.assertAlmostEqual(out["fld_SS"], stored["fielding_runs"],
                               places=3)

    def test_a_better_rating_saves_more_runs(self):
        stored = self.line()
        out = fielding.position_fields(stored, {"SS": 45, "2B": 70},
                                       "20 to 80")
        self.assertGreater(out["fld_2B"], out["fld_SS"])

    def test_the_position_adjustment_moves_war(self):
        """The same glove is worth more behind the plate than at first."""
        stored = self.line()
        out = fielding.position_fields(stored, {"C": 50, "1B": 50},
                                       "20 to 80")
        self.assertAlmostEqual(out["fld_C"], out["fld_1B"])
        self.assertGreater(out["war_C"], out["war_1B"])
        self.assertAlmostEqual(out["def_C"] - out["def_1B"],
                               (projection.POSITION_RUNS["C"]
                                - projection.POSITION_RUNS["1B"])
                               * stored["at_bats"] / 550, places=3)

    def test_blank_and_zero_mean_he_cannot_play_there(self):
        columns = fielding.find_columns(list(fielding.POSITIONS))
        ratings = fielding.read_ratings({"C": "-", "1B": "0", "SS": "60"},
                                        columns)
        self.assertEqual(ratings, {"SS": 60.0})

    def test_best_position_and_the_table(self):
        stored = self.line()
        stored.update(fielding.position_fields(
            stored, {"SS": 70, "1B": 70, "LF": 40}, "20 to 80"))
        self.assertEqual(fielding.best_position(stored)[0], "SS")
        self.assertEqual([r[0] for r in fielding.table(stored)][0], "SS")
        self.assertEqual(len(fielding.table(stored)), 3)

    def test_a_fielding_export_is_recognised(self):
        self.assertTrue(fielding.is_fielding_export(
            ["POS", "Name"] + list(fielding.POSITIONS)))
        self.assertFalse(fielding.is_fielding_export(
            ["POS", "Name", "C", "1B"]))


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.folder.name, "f.db")

    def tearDown(self):
        self.folder.cleanup()

    def hitter(self, name="Player 00"):
        table = service.projections(db=self.db)
        return next(s for s in table.hitters if s.name == name)

    def test_position_columns_on_the_batting_view_are_used(self):
        path = with_positions(self.folder.name, lambda p: SPREAD)
        service.import_export(path, league="L", db=self.db)
        stored = self.hitter().projected
        self.assertEqual(fielding.best_position(stored)[0], "SS")
        self.assertNotIn("war_C", stored)
        self.assertIn("war_RF", stored)

    def test_a_fielding_report_fills_in_the_hitters_already_stored(self):
        service.import_export(BATTERS, league="L", db=self.db)
        self.assertIsNone(fielding.best_position(self.hitter().projected))
        report = fielding_report(self.folder.name, lambda p: SPREAD,
                                 [("Player 00", "RF"), ("Player 01", "C"),
                                  ("GF NEU", "SP")])
        result = service.import_export(report, league="L", db=self.db)
        self.assertEqual(result.view_name, "Fielding Ratings")
        self.assertEqual(result.players, 2)
        self.assertEqual(result.skipped, [])
        self.assertEqual(fielding.best_position(self.hitter().projected)[0],
                         "SS")

    def test_a_fielding_report_first_says_what_to_import(self):
        report = fielding_report(self.folder.name, lambda p: SPREAD,
                                 [("Player 00", "RF")])
        with self.assertRaises(service.ScoutError) as caught:
            service.import_export(report, league="L", db=self.db)
        self.assertIn("Batting Ratings", str(caught.exception))

    def test_overwriting_the_batters_keeps_the_fielding(self):
        """A later batting import without the columns must not drop them."""
        service.import_export(BATTERS, league="L", db=self.db)
        report = fielding_report(self.folder.name, lambda p: SPREAD,
                                 [("Player 00", "RF")])
        service.import_export(report, league="L", db=self.db)
        connection = database.connect(self.db)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                              time.gmtime(time.time() - 5))
        connection.execute("UPDATE observations SET seen_at = ?", (stamp,))
        connection.commit()
        connection.close()
        service.import_export(BATTERS, league="L", replace=True, db=self.db)
        self.assertEqual(fielding.best_position(self.hitter().projected)[0],
                         "SS")

    def test_pitchers_get_no_positions(self):
        service.import_export(PITCHERS, league="L", db=self.db)
        table = service.projections(db=self.db)
        self.assertIsNone(fielding.best_position(table.pitchers[0].projected))


if __name__ == "__main__":
    unittest.main()

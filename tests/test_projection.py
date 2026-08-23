"""The projection port, checked against the site it was ported from.

The fixtures are real exports paired with the output ootpcalculator.com
actually returned for them. That is the only check worth having: the port's
purpose is to reproduce the site, so agreement with the site is the
specification and anything else is opinion.

The site displays WAR to one decimal, so agreement is asserted to 0.05 - half
a display step - rather than to floating-point equality.
"""

import os
import unittest

from ootp_scout import projection as P
from ootp_scout import tables, views

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
DISPLAY_TOLERANCE = 0.05


def load(report_name, projections_name):
    headers, raw = tables.read_table(os.path.join(FIXTURES, report_name))
    view = views.identify_view(headers)
    rows, _ = views.parse_rows(headers, raw, view)
    h2, r2 = tables.read_table(os.path.join(FIXTURES, projections_name))
    site = {dict(zip(h2, c))["Name"]: dict(zip(h2, c)) for c in r2}
    return view, rows, site


class ScaleConversionTest(unittest.TestCase):
    def test_the_ends_of_the_20_80_scale(self):
        self.assertEqual(P.convert_rating("20 to 80", 20), 0)
        self.assertEqual(P.convert_rating("20 to 80", 80), 200)

    def test_the_ends_of_the_1_100_scale(self):
        self.assertEqual(P.convert_rating("1 to 100", 1), 0)
        self.assertEqual(P.convert_rating("1 to 100", 100), 200)

    def test_the_same_relative_rating_converts_alike(self):
        self.assertEqual(P.convert_rating("20 to 80", 50),
                         P.convert_rating("1 to 100", 50.5))

    def test_stuff_may_exceed_the_ordinary_ceiling(self):
        """Stuff is allowed past 250 where other ratings are not."""
        with self.assertRaises(ValueError):
            P.convert_rating("20 to 80", 100)
        self.assertGreater(P.convert_rating("20 to 80", 100, stuff=True), 250)

    def test_a_rating_below_the_scale_is_refused(self):
        with self.assertRaises(ValueError):
            P.convert_rating("20 to 80", 10)


class LookupTest(unittest.TestCase):
    def test_interpolates_between_points(self):
        table = [(0, 0.0), (100, 1.0)]
        self.assertAlmostEqual(P.lookup(table, 50), 0.5)

    def test_hits_the_points(self):
        table = [(0, 0.0), (100, 1.0)]
        self.assertAlmostEqual(P.lookup(table, 100), 1.0)

    def test_flat_past_the_end(self):
        table = [(0, 0.0), (100, 1.0)]
        self.assertAlmostEqual(P.lookup(table, 500), 1.0)

    def test_250_to_600_hits_its_anchors(self):
        self.assertAlmostEqual(P.convert_250_to_600(0), 100)
        self.assertAlmostEqual(P.convert_250_to_600(100), 400)
        self.assertAlmostEqual(P.convert_250_to_600(250), 600)


class BatterAgainstTheSiteTest(unittest.TestCase):
    """Forty-one hitters, against what the site returned for them."""

    @classmethod
    def setUpClass(cls):
        cls.view, cls.rows, cls.site = load("pool_batters.tsv",
                                            "batter-projections.csv")

    def _project(self, row):
        conv = lambda v: P.convert_rating("20 to 80", float(v))
        v = row.values
        return P.project_batter(
            contact=conv(v["CON"]), gap=conv(v["GAP"]), power=conv(v["POW"]),
            eye=conv(v["EYE"]), avoid_ks=conv(v["K's"]), speed=conv(v["SPE"]),
            stealing=conv(v["STE"]), defense=conv(v["DEF"]),
            position=row.position, bats=v.get("B", "R"))

    def test_every_war_matches_the_site(self):
        for row in self.rows:
            with self.subTest(player=row.name):
                line = self._project(row)
                self.assertAlmostEqual(line.war,
                                       float(self.site[row.name]["WAR"]),
                                       delta=DISPLAY_TOLERANCE)

    def test_ops_matches_to_three_decimals(self):
        for row in self.rows:
            with self.subTest(player=row.name):
                line = self._project(row)
                self.assertAlmostEqual(line.ops,
                                       float(self.site[row.name]["OPS"]),
                                       delta=0.001)

    def test_ops_plus_matches(self):
        for row in self.rows[:10]:
            with self.subTest(player=row.name):
                line = self._project(row)
                self.assertAlmostEqual(line.ops_plus,
                                       float(self.site[row.name]["OPS+"]),
                                       delta=0.6)

    def test_home_runs_match(self):
        for row in self.rows[:10]:
            with self.subTest(player=row.name):
                line = self._project(row)
                self.assertAlmostEqual(line.home_runs,
                                       float(self.site[row.name]["HR"]),
                                       delta=0.6)


class PitcherAgainstTheSiteTest(unittest.TestCase):
    """Every ground/fly setting, starter and reliever."""

    @classmethod
    def setUpClass(cls):
        cls.view, cls.rows, cls.site = load("groundfly_pitchers.tsv",
                                            "groundfly-projections.csv")

    def _project(self, row):
        conv = lambda v, s=False: P.convert_rating("20 to 80", float(v), s)
        v = row.values
        return P.project_pitcher(
            stuff=conv(v["STU"], True), movement=conv(v["MOV"]),
            control=conv(v["CON"]), stamina=conv(v["STM"]),
            hold=conv(v["HLD"]), ground_fly=v["G/F"], position=row.position)

    def test_every_war_matches_the_site(self):
        for row in self.rows:
            with self.subTest(player=row.name):
                self.assertAlmostEqual(self._project(row).war,
                                       float(self.site[row.name]["WAR"]),
                                       delta=DISPLAY_TOLERANCE)

    def test_fip_matches_to_two_decimals(self):
        for row in self.rows:
            with self.subTest(player=row.name):
                self.assertAlmostEqual(self._project(row).fip,
                                       float(self.site[row.name]["FIP"]),
                                       delta=0.005)

    def test_babip_matches_to_three_decimals(self):
        for row in self.rows:
            with self.subTest(player=row.name):
                self.assertAlmostEqual(self._project(row).babip,
                                       float(self.site[row.name]["BABIP"]),
                                       delta=0.0005)

    def test_ground_ball_pitchers_allow_fewer_home_runs(self):
        by_name = {r.name: self._project(r) for r in self.rows}
        self.assertLess(by_name["GF EXGB"].home_runs, by_name["GF FB"].home_runs)

    def test_a_reliever_throws_far_fewer_innings_than_a_starter(self):
        by_name = {r.name: self._project(r) for r in self.rows}
        self.assertLess(by_name["Reliever NEU"].innings,
                        by_name["GF NEU"].innings / 2)


class ProjectRowsTest(unittest.TestCase):
    def test_projects_a_whole_export(self):
        view, rows, site = load("pool_batters.tsv", "batter-projections.csv")
        projected, problems = P.project_rows(rows, view, "20 to 80")
        self.assertEqual(problems, [])
        self.assertEqual(len(projected), len(rows))
        by_name = {p.name: p for p in projected}
        self.assertAlmostEqual(by_name["Sleeper Sam"].war,
                               float(site["Sleeper Sam"]["WAR"]),
                               delta=DISPLAY_TOLERANCE)

    def test_pitchers_come_back_with_innings_and_runs_for_rwar(self):
        view, rows, _ = load("groundfly_pitchers.tsv",
                             "groundfly-projections.csv")
        projected, problems = P.project_rows(rows, view, "20 to 80")
        self.assertEqual(problems, [])
        self.assertTrue(all(p.innings and p.runs for p in projected))

    def test_batters_carry_no_innings(self):
        view, rows, _ = load("pool_batters.tsv", "batter-projections.csv")
        projected, _ = P.project_rows(rows, view, "20 to 80")
        self.assertTrue(all(p.innings is None for p in projected))

    def test_an_invalid_ground_fly_is_refused_not_guessed(self):
        """The site accepts it and returns nonsense.

        A numeric G/F on the live site produced four home runs and 9.1 WAR for
        an arm that, with NEU, produced fifteen and 6.7. Reproducing that would
        be faithful and useless.
        """
        view, rows, _ = load("groundfly_pitchers.tsv",
                             "groundfly-projections.csv")
        rows[0].values["G/F"] = "50"
        projected, problems = P.project_rows(rows, view, "20 to 80")
        self.assertEqual(len(projected), len(rows) - 1)
        self.assertIn("G/F", problems[0][1])

    def test_a_missing_rating_is_reported_by_player(self):
        view, rows, _ = load("pool_batters.tsv", "batter-projections.csv")
        rows[0].values["POW"] = ""
        projected, problems = P.project_rows(rows, view, "20 to 80")
        self.assertEqual(len(projected), len(rows) - 1)
        self.assertEqual(problems[0][0], rows[0].name)
        self.assertIn("power", problems[0][1])


if __name__ == "__main__":
    unittest.main()

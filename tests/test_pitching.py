"""Runs-allowed WAR alongside the calculator's own."""

import os
import unittest

from ootp_scout import pitching, projections

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
PITCHING = os.path.join(FIXTURES, "pitching-projections.csv")
BATTING = os.path.join(FIXTURES, "batter-projections.csv")


def line(name, innings, runs, war):
    return pitching.PitcherLine(name=name, innings=innings, runs=runs, war=war)


class PitcherLineTest(unittest.TestCase):
    def test_ra9(self):
        self.assertAlmostEqual(line("A", 180.0, 80.0, 3.0).ra9, 4.0)

    def test_zero_innings_does_not_divide_by_zero(self):
        self.assertEqual(line("A", 0.0, 0.0, 0.0).ra9, 0.0)


class ReadLinesTest(unittest.TestCase):
    def test_reads_real_pitcher_output(self):
        loaded, _ = projections.load_projections(PITCHING)
        lines = pitching.read_lines(loaded)
        self.assertEqual(len(lines), len(loaded))
        ace = next(x for x in lines if x.name == "Ace Sleeper")
        self.assertAlmostEqual(ace.innings, 191.2)
        self.assertAlmostEqual(ace.runs, 44.0)
        self.assertAlmostEqual(ace.war, 9.1)

    def test_batter_output_yields_nothing(self):
        """Batter rows have no IP column, so rWAR simply does not apply."""
        loaded, _ = projections.load_projections(BATTING)
        self.assertEqual(pitching.read_lines(loaded), [])


class ReplacementBaselineTest(unittest.TestCase):
    def test_mean_rwar_matches_mean_war_by_construction(self):
        loaded, _ = projections.load_projections(PITCHING)
        rwar = pitching.compute_rwar(loaded)
        mean_war = sum(p.war for p in loaded) / len(loaded)
        mean_rwar = sum(rwar.values()) / len(rwar)
        self.assertAlmostEqual(mean_war, mean_rwar, places=6)

    def test_baseline_is_worse_than_the_pool_average(self):
        """A replacement pitcher must allow more runs than the field."""
        loaded, _ = projections.load_projections(PITCHING)
        lines = pitching.read_lines(loaded)
        baseline = pitching.replacement_ra9(lines)
        pool_ra9 = (9.0 * sum(x.runs for x in lines)
                    / sum(x.innings for x in lines))
        self.assertGreater(baseline, pool_ra9)

    def test_no_innings_raises(self):
        with self.assertRaises(ValueError):
            pitching.replacement_ra9([])


class ComputeRwarTest(unittest.TestCase):
    def setUp(self):
        loaded, _ = projections.load_projections(PITCHING)
        self.projections = loaded
        self.rwar = pitching.compute_rwar(loaded)

    def test_every_pitcher_gets_a_value(self):
        self.assertEqual(len(self.rwar), len(self.projections))

    def test_fewer_runs_allowed_means_more_rwar_at_equal_innings(self):
        stingy = line("Stingy", 180.0, 60.0, 4.0)
        leaky = line("Leaky", 180.0, 90.0, 4.0)
        baseline = pitching.replacement_ra9([stingy, leaky])
        wins = lambda x: (baseline - x.ra9) / pitching.RUNS_PER_WIN * x.innings / 9
        self.assertGreater(wins(stingy), wins(leaky))

    def test_more_innings_at_the_same_rate_means_more_rwar(self):
        short = line("Short", 90.0, 40.0, 2.0)
        long = line("Long", 180.0, 80.0, 4.0)
        baseline = pitching.replacement_ra9([short, long])
        wins = lambda x: (baseline - x.ra9) / pitching.RUNS_PER_WIN * x.innings / 9
        self.assertGreater(wins(long), wins(short))

    def test_names_are_indexed_lowercased(self):
        self.assertIn("ace sleeper", self.rwar)

    def test_the_two_measures_disagree_per_pitcher(self):
        """If rWAR just tracked WAR there would be no point printing it."""
        gaps = [self.rwar[p.name.lower()] - p.war for p in self.projections]
        self.assertGreater(max(gaps) - min(gaps), 1.0)

    def test_a_strikeout_heavy_arm_scores_lower_on_runs_allowed(self):
        """Ace Sleeper's peripherals flatter him next to runs actually allowed."""
        ace = next(p for p in self.projections if p.name == "Ace Sleeper")
        self.assertLess(self.rwar["ace sleeper"], ace.war)

    def test_empty_input_is_not_an_error(self):
        self.assertEqual(pitching.compute_rwar([]), {})

    def test_runs_per_win_preserves_the_mean_at_any_value(self):
        mean_war = sum(p.war for p in self.projections) / len(self.projections)
        for runs_per_win in (8.0, 10.0, 14.0):
            rwar = pitching.compute_rwar(self.projections, runs_per_win)
            with self.subTest(runs_per_win=runs_per_win):
                self.assertAlmostEqual(sum(rwar.values()) / len(rwar), mean_war,
                                       places=6)

    def test_runs_per_win_rebalances_workload_against_run_prevention(self):
        """It is a modelling choice, not a scale factor.

        The solved baseline makes rWAR a sum of an innings term and a
        runs-saved term weighted by 1/RPW, so lowering RPW favours pitchers
        who prevent runs over pitchers who absorb innings, and the ordering
        can genuinely change.
        """
        tight = pitching.compute_rwar(self.projections, runs_per_win=6.0)
        loose = pitching.compute_rwar(self.projections, runs_per_win=16.0)
        order = lambda d: [n for n, _ in sorted(d.items(), key=lambda p: -p[1])]
        self.assertNotEqual(order(tight), order(loose))
        # Relievers save runs in few innings, so they rise as RPW falls.
        reliever = "pitcher 27"
        self.assertLess(order(tight).index(reliever),
                        order(loose).index(reliever))

    def test_the_conventional_value_is_stable_against_small_changes(self):
        near = pitching.compute_rwar(self.projections, runs_per_win=9.5)
        base = pitching.compute_rwar(self.projections, runs_per_win=10.0)
        top = lambda d: {n for n, _ in sorted(d.items(),
                                              key=lambda p: -p[1])[:5]}
        self.assertEqual(top(near), top(base))


if __name__ == "__main__":
    unittest.main()

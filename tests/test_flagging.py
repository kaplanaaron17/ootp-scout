import unittest

from ootp_scout import flagging
from ootp_scout.loading import Player


def make_player(name, position="CF", **meta):
    player = Player(name=name, position=position)
    player.meta.update({"name": name, "position": position})
    player.meta.update(meta)
    return player


class FitTest(unittest.TestCase):
    def test_recovers_a_known_line(self):
        xs = [20.0, 40.0, 60.0, 80.0]
        ys = [2.0 * x + 5.0 for x in xs]
        intercept, slope = flagging.fit_polynomial(xs, ys, degree=1)
        self.assertAlmostEqual(intercept, 5.0, places=6)
        self.assertAlmostEqual(slope, 2.0, places=6)

    def test_recovers_a_known_parabola(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [3.0 + 2.0 * x + 0.5 * x * x for x in xs]
        c0, c1, c2 = flagging.fit_polynomial(xs, ys, degree=2)
        self.assertAlmostEqual(c0, 3.0, places=5)
        self.assertAlmostEqual(c1, 2.0, places=5)
        self.assertAlmostEqual(c2, 0.5, places=5)

    def test_rejects_too_few_points(self):
        with self.assertRaises(ValueError):
            flagging.fit_polynomial([1.0], [1.0], degree=1)

    def test_singular_system_raises(self):
        with self.assertRaises(ValueError):
            flagging.fit_polynomial([5.0, 5.0, 5.0], [1.0, 2.0, 3.0], degree=1)

    def test_evaluate(self):
        self.assertAlmostEqual(flagging.evaluate([1.0, 2.0], 3.0), 7.0)


class AnalyzeTest(unittest.TestCase):
    def _linear_pool(self):
        """Nine players exactly on a line, plus one deliberate outlier."""
        scored = []
        for grade in range(40, 76, 4):
            player = make_player(f"On Line {grade}")
            player.overall_current = float(grade)
            scored.append((player, 0.1 * grade))
        sleeper = make_player("Sleeper")
        sleeper.overall_current = 45.0
        scored.append((sleeper, 0.1 * 45 + 3.0))
        return scored

    def test_ranks_the_outlier_first(self):
        analysis = flagging.analyze(self._linear_pool(), mode="current")
        self.assertEqual(analysis.findings[0].player.name, "Sleeper")
        self.assertGreater(analysis.findings[0].residual, 2.0)
        self.assertGreater(analysis.findings[0].z_score, 1.0)

    def test_high_grade_high_war_player_is_not_flagged(self):
        """A great player who is graded great has no residual to speak of."""
        analysis = flagging.analyze(self._linear_pool(), mode="current")
        by_name = {f.player.name: f for f in analysis.findings}
        best_graded = by_name["On Line 72"]
        self.assertLess(abs(best_graded.residual), 0.5)
        self.assertGreater(by_name["Sleeper"].residual, best_graded.residual)

    def test_players_without_a_grade_are_excluded_not_crashed_on(self):
        scored = self._linear_pool()
        ungraded = make_player("No Grade")
        scored.append((ungraded, 5.0))
        analysis = flagging.analyze(scored, mode="current")
        self.assertIn("No Grade", [name for name, _ in analysis.excluded])
        self.assertNotIn("No Grade", [f.player.name for f in analysis.findings])

    def test_potential_mode_uses_pot(self):
        player = make_player("Prospect")
        player.overall_current = 20.0
        player.overall_potential = 65.0
        other = make_player("Other")
        other.overall_current = 30.0
        other.overall_potential = 45.0
        analysis = flagging.analyze([(player, 4.0), (other, 1.0)],
                                    mode="potential")
        grades = {f.player.name: f.baseline for f in analysis.findings}
        self.assertEqual(grades["Prospect"], 65.0)

    def test_hitters_and_pitchers_are_fit_separately(self):
        scored = []
        for grade in range(40, 70, 5):
            hitter = make_player(f"H{grade}", position="CF")
            hitter.overall_current = float(grade)
            scored.append((hitter, 0.1 * grade))
            pitcher = make_player(f"P{grade}", position="SP")
            pitcher.overall_current = float(grade)
            scored.append((pitcher, 0.05 * grade))
        analysis = flagging.analyze(scored, mode="current")
        groups = {fit.group for fit in analysis.fits}
        self.assertEqual(groups, {"hitters", "pitchers"})
        # Each group sits on its own line, so nothing looks anomalous.
        self.assertLess(max(abs(f.residual) for f in analysis.findings), 0.01)

    def test_pool_option_fits_everyone_together(self):
        scored = []
        for grade in range(40, 70, 5):
            hitter = make_player(f"H{grade}", position="CF")
            hitter.overall_current = float(grade)
            scored.append((hitter, 0.1 * grade))
        analysis = flagging.analyze(scored, mode="current", split_by_role=False)
        self.assertEqual([fit.group for fit in analysis.fits], ["all"])

    def test_flat_fallback_when_grades_are_constant(self):
        scored = []
        for index in range(4):
            player = make_player(f"Flat {index}")
            player.overall_potential = 80.0
            scored.append((player, float(index)))
        analysis = flagging.analyze(scored, mode="potential")
        self.assertTrue(all(f.note for f in analysis.findings))
        # Ranking still works: it falls back to comparing against the mean.
        self.assertEqual(analysis.findings[0].player.name, "Flat 3")

    def test_scouting_accuracy_rides_along(self):
        player = make_player("Fuzzy", scouting_accuracy="Low")
        player.overall_current = 40.0
        other = make_player("Clear", scouting_accuracy="Very High")
        other.overall_current = 60.0
        analysis = flagging.analyze([(player, 3.0), (other, 3.0)],
                                    mode="current")
        accuracies = {f.player.name: f.scouting_accuracy
                      for f in analysis.findings}
        self.assertEqual(accuracies["Fuzzy"], "Low")
        self.assertEqual(accuracies["Clear"], "Very High")

    def test_missing_scouting_accuracy_reads_unknown(self):
        player = make_player("Anon")
        player.overall_current = 50.0
        other = make_player("Anon2")
        other.overall_current = 60.0
        analysis = flagging.analyze([(player, 1.0), (other, 2.0)],
                                    mode="current")
        self.assertEqual(analysis.findings[0].scouting_accuracy, "unknown")


class SelectTest(unittest.TestCase):
    def _findings(self):
        out = []
        for index, z in enumerate([3.0, 2.0, 1.0, 0.0]):
            player = make_player(f"P{index}")
            out.append(flagging.Finding(player=player, war=1.0, baseline=50.0,
                                        expected_war=0.0, residual=z,
                                        z_score=z, group="hitters"))
        return out

    def test_limit(self):
        self.assertEqual(len(flagging.select(self._findings(), limit=2)), 2)

    def test_min_z(self):
        chosen = flagging.select(self._findings(), min_z=1.5)
        self.assertEqual([f.z_score for f in chosen], [3.0, 2.0])

    def test_no_filters_returns_everything(self):
        self.assertEqual(len(flagging.select(self._findings())), 4)


if __name__ == "__main__":
    unittest.main()

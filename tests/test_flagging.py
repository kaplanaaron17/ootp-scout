import unittest

from ootp_scout import flagging


def subject(name, grade, war, position="CF", **meta):
    return flagging.Subject(name=name, position=position, grade=grade, war=war,
                            is_pitcher=position in ("SP", "RP"), meta=dict(meta))


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
        pool = [subject(f"On Line {grade}", float(grade), 0.1 * grade)
                for grade in range(40, 76, 4)]
        pool.append(subject("Sleeper", 45.0, 0.1 * 45 + 3.0))
        return pool

    def test_ranks_the_outlier_first(self):
        analysis = flagging.analyze(self._linear_pool())
        self.assertEqual(analysis.findings[0].subject.name, "Sleeper")
        self.assertGreater(analysis.findings[0].residual, 2.0)
        self.assertGreater(analysis.findings[0].z_score, 1.0)

    def test_high_grade_high_war_player_is_not_flagged(self):
        """A great player who is graded great has no residual to speak of."""
        analysis = flagging.analyze(self._linear_pool())
        by_name = {f.subject.name: f for f in analysis.findings}
        best_graded = by_name["On Line 72"]
        self.assertLess(abs(best_graded.residual), 0.5)
        self.assertGreater(by_name["Sleeper"].residual, best_graded.residual)

    def test_hitters_and_pitchers_are_fit_separately(self):
        pool = []
        for grade in range(40, 70, 5):
            pool.append(subject(f"H{grade}", float(grade), 0.1 * grade))
            pool.append(subject(f"P{grade}", float(grade), 0.05 * grade,
                                position="SP"))
        analysis = flagging.analyze(pool)
        self.assertEqual({fit.group for fit in analysis.fits},
                         {"hitters", "pitchers"})
        # Each group sits on its own line, so nothing looks anomalous.
        self.assertLess(max(abs(f.residual) for f in analysis.findings), 0.01)

    def test_pooling_the_roles_makes_the_lines_interfere(self):
        """The reason splitting is the default: pooled, both groups look off."""
        pool = []
        for grade in range(40, 70, 5):
            pool.append(subject(f"H{grade}", float(grade), 0.1 * grade))
            pool.append(subject(f"P{grade}", float(grade), 0.05 * grade,
                                position="SP"))
        analysis = flagging.analyze(pool, split_by_role=False)
        self.assertEqual([fit.group for fit in analysis.fits], ["all"])
        self.assertGreater(max(abs(f.residual) for f in analysis.findings), 0.1)

    def test_flat_fallback_when_grades_are_constant(self):
        pool = [subject(f"Flat {index}", 80.0, float(index)) for index in range(4)]
        analysis = flagging.analyze(pool)
        self.assertTrue(all(f.note for f in analysis.findings))
        # Ranking still works: it falls back to comparing against the mean.
        self.assertEqual(analysis.findings[0].subject.name, "Flat 3")

    def test_degree_is_reduced_when_there_are_too_few_players(self):
        """Two players cannot support a curve.

        The degree is walked down until the fit has headroom, which for two
        players lands on a flat mean baseline. That is deliberate: a degree-1
        fit through exactly two points interpolates them, forcing both
        residuals to zero and hiding whatever gap is there.
        """
        pool = [subject("A", 40.0, 1.0), subject("B", 60.0, 2.0)]
        analysis = flagging.analyze(pool, degree=2)
        self.assertEqual(len(analysis.fits[0].coefficients), 1)
        self.assertNotEqual(analysis.findings[0].residual, 0.0)

    def test_scouting_accuracy_rides_along(self):
        pool = [subject("Fuzzy", 40.0, 3.0, scouting_accuracy="Low"),
                subject("Clear", 60.0, 3.0, scouting_accuracy="Very High")]
        analysis = flagging.analyze(pool)
        accuracies = {f.subject.name: f.scouting_accuracy
                      for f in analysis.findings}
        self.assertEqual(accuracies["Fuzzy"], "Low")
        self.assertEqual(accuracies["Clear"], "Very High")

    def test_missing_scouting_accuracy_reads_unknown(self):
        analysis = flagging.analyze([subject("Anon", 50.0, 1.0),
                                     subject("Anon2", 60.0, 2.0)])
        self.assertEqual(analysis.findings[0].scouting_accuracy, "unknown")

    def test_low_grade_high_war_beats_high_grade_high_war(self):
        """The core claim: the flag is about the gap, not the raw WAR."""
        pool = [subject(f"On Line {grade}", float(grade), 0.1 * grade)
                for grade in range(40, 76, 4)]
        pool.append(subject("Cheap", 35.0, 6.0))
        pool.append(subject("Expensive", 75.0, 7.5))
        analysis = flagging.analyze(pool)
        self.assertEqual(analysis.findings[0].subject.name, "Cheap")
        cheap, expensive = analysis.findings[0], next(
            f for f in analysis.findings if f.subject.name == "Expensive")
        self.assertLess(cheap.subject.war, expensive.subject.war)
        self.assertGreater(cheap.residual, expensive.residual)


class SelectOverratedTest(unittest.TestCase):
    def _pool(self):
        pool = [subject(f"On Line {grade}", float(grade), 0.1 * grade)
                for grade in range(40, 76, 4)]
        pool.append(subject("Sleeper", 45.0, 0.1 * 45 + 3.0))
        pool.append(subject("Bust", 70.0, 0.1 * 70 - 4.0))
        return pool

    def test_worst_shortfall_comes_first(self):
        analysis = flagging.analyze(self._pool(), position_adjust=False)
        overrated = flagging.select_overrated(analysis.findings)
        self.assertEqual(overrated[0].subject.name, "Bust")
        self.assertLess(overrated[0].residual, 0)

    def test_it_is_the_opposite_end_of_the_same_ranking(self):
        analysis = flagging.analyze(self._pool(), position_adjust=False)
        best = flagging.select(analysis.findings, limit=1)[0]
        worst = flagging.select_overrated(analysis.findings, limit=1)[0]
        self.assertEqual(best.subject.name, "Sleeper")
        self.assertEqual(worst.subject.name, "Bust")
        self.assertGreater(best.residual, worst.residual)

    def test_limit(self):
        analysis = flagging.analyze(self._pool(), position_adjust=False)
        self.assertEqual(len(flagging.select_overrated(analysis.findings,
                                                       limit=3)), 3)

    def test_max_z_filters_to_the_genuinely_overrated(self):
        analysis = flagging.analyze(self._pool(), position_adjust=False)
        chosen = flagging.select_overrated(analysis.findings, max_z=-1.0)
        self.assertTrue(all(f.z_score <= -1.0 for f in chosen))
        self.assertIn("Bust", [f.subject.name for f in chosen])

    def test_does_not_disturb_the_original_ordering(self):
        analysis = flagging.analyze(self._pool(), position_adjust=False)
        before = [f.subject.name for f in analysis.findings]
        flagging.select_overrated(analysis.findings)
        self.assertEqual([f.subject.name for f in analysis.findings], before)


class SelectTest(unittest.TestCase):
    def _findings(self):
        return [flagging.Finding(subject=subject(f"P{index}", 50.0, 1.0),
                                 expected_war=0.0, residual=z, z_score=z,
                                 group="hitters")
                for index, z in enumerate([3.0, 2.0, 1.0, 0.0])]

    def test_limit(self):
        self.assertEqual(len(flagging.select(self._findings(), limit=2)), 2)

    def test_min_z(self):
        chosen = flagging.select(self._findings(), min_z=1.5)
        self.assertEqual([f.z_score for f in chosen], [3.0, 2.0])

    def test_no_filters_returns_everything(self):
        self.assertEqual(len(flagging.select(self._findings())), 4)


if __name__ == "__main__":
    unittest.main()

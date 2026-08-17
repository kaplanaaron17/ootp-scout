"""The monotone baseline, and why a straight line was not enough."""

import unittest

from ootp_scout import flagging


class PoolAdjacentViolatorsTest(unittest.TestCase):
    def test_an_increasing_sequence_is_untouched(self):
        self.assertEqual(
            flagging.pool_adjacent_violators([1.0, 2.0, 3.0], [1.0] * 3),
            [1.0, 2.0, 3.0])

    def test_a_dip_is_pooled_with_its_neighbour(self):
        self.assertEqual(
            flagging.pool_adjacent_violators([1.0, 3.0, 2.0, 5.0], [1.0] * 4),
            [1.0, 2.5, 2.5, 5.0])

    def test_a_decreasing_sequence_flattens_to_its_mean(self):
        self.assertEqual(
            flagging.pool_adjacent_violators([5.0, 4.0, 3.0], [1.0] * 3),
            [4.0, 4.0, 4.0])

    def test_the_result_never_decreases(self):
        values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
        fitted = flagging.pool_adjacent_violators(values, [1.0] * len(values))
        self.assertEqual(fitted, sorted(fitted))

    def test_weights_pull_the_pooled_mean(self):
        light = flagging.pool_adjacent_violators([5.0, 1.0], [1.0, 1.0])
        heavy = flagging.pool_adjacent_violators([5.0, 1.0], [1.0, 9.0])
        self.assertGreater(light[0], heavy[0])

    def test_length_is_preserved(self):
        values = [4.0, 2.0, 7.0, 1.0]
        self.assertEqual(
            len(flagging.pool_adjacent_violators(values, [1.0] * 4)), 4)


class MonotoneCurveTest(unittest.TestCase):
    def setUp(self):
        self.curve = flagging.MonotoneCurve(grades=[40.0, 50.0, 60.0],
                                            wars=[0.0, 2.0, 3.0])

    def test_interpolates_between_points(self):
        self.assertAlmostEqual(self.curve.value(45.0), 1.0)
        self.assertAlmostEqual(self.curve.value(55.0), 2.5)

    def test_hits_the_points_themselves(self):
        for grade, war in zip(self.curve.grades, self.curve.wars):
            self.assertAlmostEqual(self.curve.value(grade), war)

    def test_extrapolates_off_each_end(self):
        self.assertLess(self.curve.value(30.0), 0.0)
        self.assertGreater(self.curve.value(70.0), 3.0)

    def test_inverts_back_to_the_grade(self):
        for grade in (42.0, 50.0, 58.0):
            self.assertAlmostEqual(self.curve.invert(self.curve.value(grade)),
                                   grade, places=6)

    def test_inverts_beyond_both_ends(self):
        self.assertLess(self.curve.invert(-1.0), 40.0)
        self.assertGreater(self.curve.invert(4.0), 60.0)

    def test_a_flat_stretch_inverts_to_its_midpoint(self):
        flat = flagging.MonotoneCurve(grades=[40.0, 50.0, 60.0],
                                      wars=[1.0, 2.0, 2.0])
        self.assertAlmostEqual(flat.invert(2.0), 55.0)

    def test_slope_is_the_overall_rise(self):
        self.assertAlmostEqual(self.curve.slope, 3.0 / 20.0)


class FitMonotoneTest(unittest.TestCase):
    def test_it_follows_a_concave_shape(self):
        grades, wars = [], []
        for grade in range(40, 76, 5):
            for _ in range(5):
                grades.append(float(grade))
                # Concave: rises fast early, flattens later.
                wars.append(((grade - 40) ** 0.5) * 1.2)
        curve = flagging.fit_monotone(grades, wars)
        early = curve.value(50) - curve.value(45)
        late = curve.value(70) - curve.value(65)
        self.assertGreater(early, late)

    def test_the_result_never_decreases(self):
        grades, wars = [], []
        for grade in range(40, 71, 5):
            for _ in range(4):
                grades.append(float(grade))
                wars.append(3.0 if grade == 55 else float(grade) / 20.0)
        curve = flagging.fit_monotone(grades, wars)
        self.assertEqual(curve.wars, sorted(curve.wars))

    def test_a_thin_top_bin_is_folded_into_its_neighbour(self):
        """One player at the top must not be allowed to define the tail."""
        grades = [40.0] * 20 + [45.0] * 20 + [70.0]
        wars = [0.0] * 20 + [1.0] * 20 + [99.0]
        curve = flagging.fit_monotone(grades, wars)
        self.assertLess(max(curve.wars), 99.0)


class AnalyzeShapeTest(unittest.TestCase):
    def _concave_pool(self):
        """WAR rising with grade but flattening - the real-world shape."""
        subjects = []
        for grade in range(40, 76, 5):
            for index in range(8):
                war = ((grade - 40) ** 0.5) * 1.2
                subjects.append(flagging.Subject(
                    name=f"P{grade}-{index}", position="CF",
                    grade=float(grade), war=war))
        return subjects

    def _bias_at_top(self, analysis):
        top = [f.residual for f in analysis.findings if f.subject.grade >= 65]
        return sum(top) / len(top)

    def test_a_straight_line_marks_the_top_overrated(self):
        analysis = flagging.analyze(self._concave_pool(), shape="linear",
                                    position_adjust=False)
        self.assertLess(self._bias_at_top(analysis), -0.1)

    def test_the_monotone_curve_removes_that_bias(self):
        analysis = flagging.analyze(self._concave_pool(), shape="monotone",
                                    position_adjust=False)
        self.assertAlmostEqual(self._bias_at_top(analysis), 0.0, places=6)

    def test_monotone_still_finds_a_genuine_outlier(self):
        pool = self._concave_pool()
        pool.append(flagging.Subject(name="Sleeper", position="CF",
                                     grade=45.0, war=9.0))
        analysis = flagging.analyze(pool, shape="monotone",
                                    position_adjust=False)
        self.assertEqual(analysis.findings[0].subject.name, "Sleeper")

    def test_monotone_implied_grades_stay_invertible(self):
        analysis = flagging.analyze(self._concave_pool(), shape="monotone",
                                    position_adjust=False)
        self.assertTrue(all(f.implied_grade is not None
                            for f in analysis.findings))

    def test_position_offsets_survive_the_curve(self):
        pool = []
        for grade in range(40, 71, 5):
            for index in range(5):
                pool.append(flagging.Subject(
                    name=f"C{grade}-{index}", position="C", grade=float(grade),
                    war=grade * 0.1 + 2.0))
                pool.append(flagging.Subject(
                    name=f"F{grade}-{index}", position="1B",
                    grade=float(grade), war=grade * 0.1))
        analysis = flagging.analyze(pool, shape="monotone")
        offsets = analysis.fits[0].position_offsets
        self.assertTrue(offsets)
        self.assertAlmostEqual(abs(list(offsets.values())[0]), 2.0, places=1)

    def test_a_tiny_group_falls_back_rather_than_curving(self):
        pool = [flagging.Subject(name=f"P{i}", position="CF",
                                 grade=40.0 + i * 5, war=float(i))
                for i in range(4)]
        analysis = flagging.analyze(pool, shape="monotone",
                                    position_adjust=False)
        self.assertEqual(len(analysis.findings), 4)


if __name__ == "__main__":
    unittest.main()

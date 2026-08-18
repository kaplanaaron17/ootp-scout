"""Position adjustment inside the fit."""

import unittest

from ootp_scout import flagging


def subject(name, grade, war, position="CF"):
    return flagging.Subject(name=name, position=position, grade=grade, war=war,
                            is_pitcher=position in ("SP", "RP", "CL"))


class NormalizePositionTest(unittest.TestCase):
    def test_relievers_collapse_together(self):
        for raw in ("CL", "MR", "SR"):
            self.assertEqual(flagging.normalize_position(raw), "RP")

    def test_case_and_whitespace(self):
        self.assertEqual(flagging.normalize_position(" ss "), "SS")

    def test_unknown_positions_pass_through(self):
        self.assertEqual(flagging.normalize_position("DH"), "DH")


class PositionOffsetTest(unittest.TestCase):
    def _pool(self, catcher_bonus):
        """Two positions on the same slope, catchers shifted by a constant."""
        pool = []
        for grade in range(40, 76, 5):
            pool.append(subject(f"1B{grade}", float(grade), 0.1 * grade,
                                position="1B"))
            pool.append(subject(f"C{grade}", float(grade),
                                0.1 * grade + catcher_bonus, position="C"))
        return pool

    def test_a_constant_position_shift_is_absorbed(self):
        """Catchers projecting +2 across the board is a position effect."""
        analysis = flagging.analyze(self._pool(2.0))
        self.assertLess(max(abs(f.residual) for f in analysis.findings), 0.01)

    def test_without_adjustment_the_same_shift_shows_up_as_residual(self):
        analysis = flagging.analyze(self._pool(2.0), position_adjust=False)
        self.assertGreater(max(abs(f.residual) for f in analysis.findings), 0.5)

    def test_the_offset_recovers_the_shift(self):
        analysis = flagging.analyze(self._pool(2.0))
        fit = analysis.fits[0]
        offsets = fit.position_offsets
        self.assertEqual(len(offsets), 1)
        name, value = next(iter(offsets.items()))
        # Whichever position became the reference, the gap is 2 wins.
        self.assertAlmostEqual(abs(value), 2.0, places=6)
        self.assertNotEqual(name, fit.reference_position)

    def test_reference_position_has_no_offset_of_its_own(self):
        analysis = flagging.analyze(self._pool(2.0))
        fit = analysis.fits[0]
        self.assertNotIn(fit.reference_position, fit.position_offsets)

    def test_a_genuinely_underrated_player_still_stands_out(self):
        """Adjustment must not launder away a real individual gap."""
        pool = self._pool(2.0)
        pool.append(subject("Sleeper", 40.0, 9.0, position="1B"))
        analysis = flagging.analyze(pool)
        self.assertEqual(analysis.findings[0].subject.name, "Sleeper")
        self.assertGreater(analysis.findings[0].z_score, 2.0)

    def test_thin_positions_do_not_get_their_own_term(self):
        pool = [subject(f"1B{g}", float(g), 0.1 * g, position="1B")
                for g in range(40, 76, 3)]
        pool.append(subject("Lonely DH", 50.0, 5.0, position="DH"))
        analysis = flagging.analyze(pool)
        self.assertNotIn("DH", analysis.fits[0].position_offsets)
        # And he is still measured, against the reference position.
        self.assertIn("Lonely DH",
                      [f.subject.name for f in analysis.findings])

    def test_predict_uses_the_offset(self):
        analysis = flagging.analyze(self._pool(2.0))
        fit = analysis.fits[0]
        catcher = fit.predict(60.0, "C")
        first = fit.predict(60.0, "1B")
        self.assertAlmostEqual(abs(catcher - first), 2.0, places=6)

    def test_pitcher_positions_are_adjusted_separately_from_hitters(self):
        pool = []
        for grade in range(40, 76, 5):
            pool.append(subject(f"SP{grade}", float(grade), 0.1 * grade,
                                position="SP"))
            pool.append(subject(f"RP{grade}", float(grade), 0.1 * grade - 1.5,
                                position="RP"))
            pool.append(subject(f"SS{grade}", float(grade), 0.2 * grade,
                                position="SS"))
        analysis = flagging.analyze(pool)
        groups = {fit.group: fit for fit in analysis.fits}
        self.assertEqual(set(groups), {"hitters", "starters", "relievers"})
        self.assertLess(max(abs(f.residual) for f in analysis.findings), 0.01)

    def test_fit_degrades_rather_than_crashing_on_a_tiny_group(self):
        pool = [subject("A", 40.0, 1.0, position="C"),
                subject("B", 60.0, 2.0, position="1B")]
        analysis = flagging.analyze(pool)
        self.assertEqual(len(analysis.findings), 2)


class StarterRelieverSplitTest(unittest.TestCase):
    """A widening gap cannot be an offset, so the two are fitted apart."""

    def _pool(self):
        # Starters improve with grade; relievers barely do. The gap therefore
        # widens, which is what a constant offset cannot express.
        pool = []
        for grade in range(40, 76, 5):
            for index in range(5):
                pool.append(subject(f"SP{grade}-{index}", float(grade),
                                    (grade - 40) * 0.14, position="SP"))
                pool.append(subject(f"RP{grade}-{index}", float(grade),
                                    (grade - 40) * 0.02, position="RP"))
        return pool

    def test_they_land_in_separate_groups(self):
        analysis = flagging.analyze(self._pool())
        self.assertEqual({fit.group for fit in analysis.fits},
                         {"starters", "relievers"})

    def test_split_apart_neither_group_shows_false_residuals(self):
        analysis = flagging.analyze(self._pool(), shape="monotone")
        self.assertLess(max(abs(f.residual) for f in analysis.findings), 0.2)

    def test_forcing_them_together_distorts_both(self):
        analysis = flagging.analyze(self._pool(), shape="monotone",
                                    split_starters=False)
        self.assertEqual({fit.group for fit in analysis.fits}, {"pitchers"})
        self.assertGreater(max(abs(f.residual) for f in analysis.findings), 0.5)

    def test_the_starter_curve_reaches_higher_than_the_reliever_curve(self):
        analysis = flagging.analyze(self._pool(), shape="monotone")
        curves = {fit.group: fit.curve for fit in analysis.fits}
        self.assertGreater(curves["starters"].wars[-1],
                           curves["relievers"].wars[-1])

    def test_closers_are_grouped_with_relievers(self):
        pool = self._pool()
        pool.append(subject("Closer", 60.0, 1.0, position="CL"))
        analysis = flagging.analyze(pool)
        closer = next(f for f in analysis.findings
                      if f.subject.name == "Closer")
        self.assertEqual(closer.group, "relievers")

    def test_a_pitcher_with_no_position_is_folded_in_rather_than_alone(self):
        pool = self._pool()
        pool.append(flagging.Subject(name="Mystery", position="", grade=55.0,
                                     war=2.0, is_pitcher=True))
        analysis = flagging.analyze(pool)
        self.assertNotIn("pitchers", {fit.group for fit in analysis.fits})
        self.assertIn("Mystery", [f.subject.name for f in analysis.findings])

    def test_hitters_are_untouched_by_the_split(self):
        pool = self._pool()
        for grade in range(40, 76, 5):
            for index in range(5):
                pool.append(subject(f"H{grade}-{index}", float(grade),
                                    (grade - 40) * 0.1, position="CF"))
        analysis = flagging.analyze(pool)
        self.assertIn("hitters", {fit.group for fit in analysis.fits})


if __name__ == "__main__":
    unittest.main()

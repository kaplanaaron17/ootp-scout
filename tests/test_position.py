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
        self.assertEqual(set(groups), {"hitters", "pitchers"})
        self.assertLess(max(abs(f.residual) for f in analysis.findings), 0.01)

    def test_fit_degrades_rather_than_crashing_on_a_tiny_group(self):
        pool = [subject("A", 40.0, 1.0, position="C"),
                subject("B", 60.0, 2.0, position="1B")]
        analysis = flagging.analyze(pool)
        self.assertEqual(len(analysis.findings), 2)


if __name__ == "__main__":
    unittest.main()

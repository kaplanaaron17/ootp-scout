import unittest

from ootp_scout import ratings as R


class NormalizeHeaderTest(unittest.TestCase):
    def test_strips_punctuation_and_case(self):
        self.assertEqual(R.normalize_header("  Avoid K's  "), "avoid ks")
        self.assertEqual(R.normalize_header("B/T"), "b t")
        self.assertEqual(R.normalize_header("SctAcc"), "sctacc")


class ClassifyHeaderTest(unittest.TestCase):
    def test_bare_pot_is_overall_potential_not_a_tool(self):
        role = R.classify_header("POT")
        self.assertEqual(role, R.ColumnRole("overall", "overall", True))

    def test_bare_ovr_is_overall_current(self):
        role = R.classify_header("OVR")
        self.assertEqual(role, R.ColumnRole("overall", "overall", False))

    def test_tool_aliases_map_to_canonical_names(self):
        for header, expected in [("Con", "contact"), ("Pow", "power"),
                                 ("Eye", "eye"), ("Ks", "avoid_k"),
                                 ("Stu", "stuff"), ("Ctl", "control"),
                                 ("DF", "defense")]:
            with self.subTest(header=header):
                role = R.classify_header(header)
                self.assertEqual(role.kind, "tool")
                self.assertEqual(role.field, expected)
                self.assertFalse(role.is_potential)

    def test_potential_prefix_and_suffix(self):
        for header in ("POT Contact", "Contact Potential"):
            with self.subTest(header=header):
                role = R.classify_header(header)
                self.assertEqual(role, R.ColumnRole("tool", "contact", True))

    def test_unknown_headers_are_ignored(self):
        self.assertEqual(R.classify_header("Prone").kind, "ignored")
        self.assertEqual(R.classify_header("").kind, "ignored")

    def test_meta_headers(self):
        self.assertEqual(R.classify_header("SctAcc").field, "scouting_accuracy")
        self.assertEqual(R.classify_header("Name").field, "name")


class ScaleTest(unittest.TestCase):
    def test_detects_twenty_eighty(self):
        self.assertEqual(R.detect_scale([20, 45, 80]), R.SCALE_20_80)

    def test_detects_one_hundred(self):
        self.assertEqual(R.detect_scale([12, 55, 97]), R.SCALE_1_100)

    def test_rejects_coarse_scales(self):
        with self.assertRaises(ValueError) as caught:
            R.detect_scale([1, 5, 8])
        self.assertIn("re-export", str(caught.exception))

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            R.detect_scale([])

    def test_to_unit_endpoints(self):
        self.assertAlmostEqual(R.to_unit(20, R.SCALE_20_80), 0.0)
        self.assertAlmostEqual(R.to_unit(80, R.SCALE_20_80), 1.0)
        self.assertAlmostEqual(R.to_unit(1, R.SCALE_1_100), 0.0)
        self.assertAlmostEqual(R.to_unit(100, R.SCALE_1_100), 1.0)


if __name__ == "__main__":
    unittest.main()

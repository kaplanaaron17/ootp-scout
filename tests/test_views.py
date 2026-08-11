import unittest

from ootp_scout import views

BATTER_CURRENT = list(views.VIEWS[0].headers)
BATTER_POTENTIAL = list(views.VIEWS[1].headers)
PITCHER_CURRENT = list(views.VIEWS[2].headers)
PITCHER_POTENTIAL = list(views.VIEWS[3].headers)


def row_for(headers, **overrides):
    cells = []
    for header in headers:
        if header == "Name":
            cells.append(overrides.get("Name", "Al Alpha"))
        elif header == "POS":
            cells.append(overrides.get("POS", "CF"))
        elif header in ("OVR", "POT"):
            cells.append(overrides.get(header, "45"))
        elif header == "SctAcc":
            cells.append(overrides.get("SctAcc", "High"))
        elif header in ("Age",):
            cells.append(overrides.get("Age", "22"))
        elif header in ("#", "Inf", "B", "T", "G/F"):
            cells.append(overrides.get(header, ""))
        else:
            cells.append(overrides.get(header, "50"))
    return cells


class IdentifyViewTest(unittest.TestCase):
    def test_identifies_each_of_the_four_views(self):
        cases = [
            (BATTER_CURRENT, views.BATTER, views.CURRENT),
            (BATTER_POTENTIAL, views.BATTER, views.POTENTIAL),
            (PITCHER_CURRENT, views.PITCHER, views.CURRENT),
            (PITCHER_POTENTIAL, views.PITCHER, views.POTENTIAL),
        ]
        for headers, role, mode in cases:
            with self.subTest(role=role, mode=mode):
                view = views.identify_view(headers)
                self.assertEqual((view.role, view.mode), (role, mode))

    def test_tolerates_extra_columns_and_sort_glyphs(self):
        headers = ["OVR▾" if h == "OVR" else h for h in BATTER_CURRENT]
        headers += ["BABIP", "SR", "Some Other Column"]
        view = views.identify_view(headers)
        self.assertEqual((view.role, view.mode), (views.BATTER, views.CURRENT))

    def test_draft_pool_view_is_rejected_with_guidance(self):
        headers = ["POS", "#", "Name", "Inf", "DOB", "Age", "NAT", "HT", "WT",
                   "B", "T", "OVR", "POT", "Prone", "DEM", "Sign", "SctAcc"]
        with self.assertRaises(ValueError) as caught:
            views.identify_view(headers)
        message = str(caught.exception)
        self.assertIn("Ratings view", message)
        self.assertIn("CON", message)

    def test_batter_and_pitcher_views_are_not_confused(self):
        """CON appears in both; only the view disambiguates it."""
        batter = views.identify_view(BATTER_CURRENT)
        pitcher = views.identify_view(PITCHER_CURRENT)
        self.assertIn("CON", batter.rating_columns)
        self.assertIn("CON", pitcher.rating_columns)
        self.assertNotEqual(batter.role, pitcher.role)
        self.assertIn("GAP", batter.headers)
        self.assertNotIn("GAP", pitcher.headers)


class CombinedViewTest(unittest.TestCase):
    """A custom OOTP view can hold current and potential ratings at once."""

    def setUp(self):
        # Union of the two batter views, as a custom view would produce.
        combined = list(BATTER_CURRENT)
        for header in BATTER_POTENTIAL:
            if header not in combined:
                combined.append(header)
        self.headers = combined

    def test_both_views_are_candidates(self):
        modes = {v.mode for v in views.candidate_views(self.headers)}
        self.assertEqual(modes, {views.CURRENT, views.POTENTIAL})

    def test_mode_selects_potential(self):
        view = views.identify_view(self.headers, mode=views.POTENTIAL)
        self.assertEqual(view.mode, views.POTENTIAL)
        self.assertEqual(view.grade_column, "POT")

    def test_mode_selects_current(self):
        view = views.identify_view(self.headers, mode=views.CURRENT)
        self.assertEqual(view.grade_column, "OVR")

    def test_asking_for_a_mode_the_export_lacks_says_so(self):
        with self.assertRaises(ValueError) as caught:
            views.identify_view(BATTER_CURRENT, mode=views.POTENTIAL)
        self.assertIn("no potential ratings columns", str(caught.exception))

    def test_a_single_mode_export_has_one_candidate(self):
        modes = {v.mode for v in views.candidate_views(BATTER_CURRENT)}
        self.assertEqual(modes, {views.CURRENT})

    def test_mode_is_ignored_when_it_changes_nothing(self):
        view = views.identify_view(BATTER_CURRENT, mode=views.CURRENT)
        self.assertEqual(view.mode, views.CURRENT)


class CalculatorTypeTest(unittest.TestCase):
    def test_matches_the_sites_download_filename(self):
        """The site says batting/pitching; 'batter'/'pitcher' names no file."""
        cases = [(BATTER_CURRENT, "batting"), (BATTER_POTENTIAL, "batting"),
                 (PITCHER_CURRENT, "pitching"), (PITCHER_POTENTIAL, "pitching")]
        for headers, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(views.identify_view(headers).calculator_type,
                                 expected)


class ParseRowsTest(unittest.TestCase):
    def test_parses_grade_from_the_view_specific_column(self):
        view = views.identify_view(BATTER_POTENTIAL)
        rows, problems = views.parse_rows(
            BATTER_POTENTIAL, [row_for(BATTER_POTENTIAL, POT="65")], view)
        self.assertEqual(problems, [])
        self.assertEqual(rows[0].grade, 65.0)
        self.assertEqual(rows[0].name, "Al Alpha")
        self.assertEqual(rows[0].scouting_accuracy, "High")

    def test_missing_grade_is_none_not_an_error(self):
        view = views.identify_view(BATTER_CURRENT)
        rows, _ = views.parse_rows(BATTER_CURRENT,
                                   [row_for(BATTER_CURRENT, OVR="-")], view)
        self.assertIsNone(rows[0].grade)

    def test_short_row_is_reported(self):
        view = views.identify_view(BATTER_CURRENT)
        rows, problems = views.parse_rows(BATTER_CURRENT, [["CF", "1"]], view)
        self.assertEqual(rows, [])
        self.assertIn("expected", problems[0][1])

    def test_nameless_row_is_reported(self):
        view = views.identify_view(BATTER_CURRENT)
        rows, problems = views.parse_rows(
            BATTER_CURRENT, [row_for(BATTER_CURRENT, Name="")], view)
        self.assertEqual(rows, [])
        self.assertIn("no Name", problems[0][1])

    def test_blank_rows_are_skipped_silently(self):
        view = views.identify_view(BATTER_CURRENT)
        rows, problems = views.parse_rows(
            BATTER_CURRENT, [[""] * len(BATTER_CURRENT)], view)
        self.assertEqual((rows, problems), ([], []))

    def test_pitcher_position_detection(self):
        view = views.identify_view(PITCHER_CURRENT)
        rows, _ = views.parse_rows(PITCHER_CURRENT,
                                   [row_for(PITCHER_CURRENT, POS="SP")], view)
        self.assertTrue(rows[0].is_pitcher)

    def test_missing_scouting_accuracy_reads_unknown(self):
        view = views.identify_view(BATTER_CURRENT)
        rows, _ = views.parse_rows(
            BATTER_CURRENT, [row_for(BATTER_CURRENT, SctAcc="")], view)
        self.assertEqual(rows[0].scouting_accuracy, "unknown")


class InferScaleTest(unittest.TestCase):
    def setUp(self):
        self.view = views.identify_view(BATTER_CURRENT)

    def _rows(self, *value_sets):
        raw = []
        for values in value_sets:
            overrides = {column: str(value) for column, value
                         in zip(self.view.rating_columns, values)}
            raw.append(row_for(BATTER_CURRENT, **overrides))
        rows, _ = views.parse_rows(BATTER_CURRENT, raw, self.view)
        return rows

    def test_all_multiples_of_five_within_range_reads_as_20_80(self):
        rows = self._rows([25] * 14, [50] * 14, [80] * 14)
        scale, reason = views.infer_scale(rows, self.view)
        self.assertEqual(scale, views.SCALE_STEP_5)
        self.assertIn("multiple of 5", reason)

    def test_one_off_grid_value_rules_out_20_80(self):
        rows = self._rows([25] * 14, [50] * 13 + [52])
        scale, _ = views.infer_scale(rows, self.view)
        self.assertEqual(scale, views.SCALE_1_100)

    def test_a_single_rating_above_80_does_not_flip_the_scale(self):
        """OOTP really does show a 90 Stealing on the 20-80 scale.

        Taken from a real export: 2,296 ratings, all multiples of 5, one STE
        of 90. Reading that as 1-100 would send the user to the wrong dropdown.
        """
        rows = self._rows([50] * 14, [25] * 13 + [90])
        scale, reason = views.infer_scale(rows, self.view)
        self.assertEqual(scale, views.SCALE_STEP_5)
        self.assertIn("90", reason)

    def test_values_beyond_the_calculators_ceiling_read_as_1_100(self):
        rows = self._rows([100] * 14, [45] * 14)
        scale, _ = views.infer_scale(rows, self.view)
        self.assertEqual(scale, views.SCALE_1_100)

    def test_real_world_range_reads_as_1_100(self):
        """36-73 as continuous integers is what a 1-100 save looks like."""
        rows = self._rows(list(range(36, 50)), list(range(51, 65)))
        scale, reason = views.infer_scale(rows, self.view)
        self.assertEqual(scale, views.SCALE_1_100)
        self.assertIn("not multiples of 5", reason)

    def test_out_of_range_values_are_refused_rather_than_guessed(self):
        rows = self._rows([150] * 14)
        scale, reason = views.infer_scale(rows, self.view)
        self.assertIsNone(scale)
        self.assertIn("matches no OOTP scale", reason)

    def test_no_ratings_returns_none(self):
        rows = self._rows()
        scale, reason = views.infer_scale(rows, self.view)
        self.assertIsNone(scale)
        self.assertIn("no rating values", reason)

    def test_detected_20_80_then_passes_validation(self):
        rows = self._rows([25] * 14, [60] * 14)
        scale, _ = views.infer_scale(rows, self.view)
        self.assertEqual(views.validate_ratings(rows, self.view, scale), [])


class ValidateRatingsTest(unittest.TestCase):
    def setUp(self):
        self.view = views.identify_view(BATTER_CURRENT)

    def _rows(self, **overrides):
        rows, _ = views.parse_rows(BATTER_CURRENT,
                                   [row_for(BATTER_CURRENT, **overrides)],
                                   self.view)
        return rows

    def test_flags_non_multiples_of_five_on_20_80(self):
        complaints = views.validate_ratings(self._rows(CON="52"), self.view,
                                            "20 to 80")
        self.assertEqual(len(complaints), 1)
        self.assertIn("multiple of 5", complaints[0][1])

    def test_multiples_of_five_pass(self):
        self.assertEqual(
            views.validate_ratings(self._rows(CON="55"), self.view, "20 to 80"),
            [])

    def test_other_scales_are_not_step_checked(self):
        self.assertEqual(
            views.validate_ratings(self._rows(CON="52"), self.view, "1 to 100"),
            [])

    def test_non_numeric_rating_is_flagged(self):
        complaints = views.validate_ratings(self._rows(CON="abc"), self.view,
                                            "20 to 80")
        self.assertIn("not a number", complaints[0][1])

    def test_dash_placeholder_is_allowed(self):
        self.assertEqual(
            views.validate_ratings(self._rows(CON="-"), self.view, "20 to 80"),
            [])

    def test_grade_column_is_not_step_checked(self):
        """OVR is not fed to the calculator, so its value must not block a run."""
        self.assertEqual(
            views.validate_ratings(self._rows(OVR="47"), self.view, "20 to 80"),
            [])


if __name__ == "__main__":
    unittest.main()

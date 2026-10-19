"""Projected seasons, written the way baseball writes them."""

import unittest

from ootp_scout import statline

BATTER = {
    "games": 150, "plate_appearances": 600, "at_bats": 522, "hits": 160,
    "doubles": 34, "triples": 4, "home_runs": 33, "walks": 72,
    "strikeouts": 97, "stolen_bases": 11, "caught_stealing": 4,
    "avg": 0.306, "obp": 0.396, "slg": 0.573, "ops": 0.970, "ops_plus": 168,
    "babip": 0.324, "war": 7.34,
}
PITCHER = {
    "games": 30, "starts": 30, "innings": 185.6, "hits": 147, "home_runs": 15,
    "runs": 64, "earned_runs": 59, "walks": 44, "strikeouts": 224,
    "era": 2.85, "whip": 1.03, "fip": 2.59, "era_plus": 146, "babip": 0.292,
    "war": 6.86,
}


class DeriveTest(unittest.TestCase):
    def test_isolated_power_is_slugging_over_average(self):
        self.assertAlmostEqual(statline.derive(BATTER, False)["iso"],
                               0.573 - 0.306, places=6)

    def test_walk_and_strikeout_rates_are_per_plate_appearance(self):
        full = statline.derive(BATTER, False)
        self.assertAlmostEqual(full["bb_rate"], 72 / 600 * 100, places=6)
        self.assertAlmostEqual(full["k_rate"], 97 / 600 * 100, places=6)

    def test_pitcher_rates_are_per_nine_innings(self):
        full = statline.derive(PITCHER, True)
        self.assertAlmostEqual(full["k_9"], 224 * 9 / 185.6, places=6)
        self.assertAlmostEqual(full["bb_9"], 44 * 9 / 185.6, places=6)
        self.assertAlmostEqual(full["hr_9"], 15 * 9 / 185.6, places=6)

    def test_strikeouts_per_walk(self):
        self.assertAlmostEqual(statline.derive(PITCHER, True)["k_bb"],
                               224 / 44, places=6)

    def test_the_stored_stats_survive_untouched(self):
        full = statline.derive(PITCHER, True)
        for key, value in PITCHER.items():
            self.assertEqual(full[key], value)

    def test_nothing_in_nothing_out(self):
        self.assertEqual(statline.derive({}, False), {})
        self.assertEqual(statline.derive({}, True), {})

    def test_a_pitcher_who_throws_no_innings_gets_no_rate_stats(self):
        """Dividing by zero innings would be an infinity, not a stat."""
        full = statline.derive({"strikeouts": 0, "innings": 0}, True)
        self.assertNotIn("k_9", full)

    def test_a_hitter_with_no_plate_appearances_gets_no_rates(self):
        full = statline.derive({"walks": 0, "plate_appearances": 0}, False)
        self.assertNotIn("bb_rate", full)

    def test_a_partial_line_derives_only_what_it_can(self):
        """A row stored by an older version may be missing fields."""
        full = statline.derive({"innings": 100.0, "strikeouts": 90}, True)
        self.assertAlmostEqual(full["k_9"], 8.1)
        self.assertNotIn("bb_9", full)
        self.assertNotIn("k_bb", full)


class FormatTest(unittest.TestCase):
    def test_rates_drop_the_leading_zero(self):
        self.assertEqual(statline.format_value("avg", 0.306, 3), ".306")
        self.assertEqual(statline.format_value("babip", 0.292, 3), ".292")

    def test_but_era_keeps_its_digit(self):
        self.assertEqual(statline.format_value("era", 2.85, 2), "2.85")

    def test_a_rate_over_one_keeps_its_digit_too(self):
        self.assertEqual(statline.format_value("ops", 1.024, 3), "1.024")

    def test_percentages_are_marked(self):
        self.assertEqual(statline.format_value("k_rate", 16.1667, 1), "16.2%")

    def test_counting_stats_are_whole_numbers(self):
        self.assertEqual(statline.format_value("home_runs", 33.0, 0), "33")

    def test_large_counts_are_grouped(self):
        self.assertEqual(statline.format_value("plate_appearances", 1200, 0),
                         "1,200")

    def test_a_missing_stat_is_blank_not_a_zero(self):
        self.assertEqual(statline.format_value("era", None, 2), "")


class DisplayTest(unittest.TestCase):
    def test_a_hitters_line_reads_in_order(self):
        pairs = statline.display(BATTER, False)
        headings = [heading for heading, _value in pairs]
        self.assertEqual(headings[:4], ["G", "PA", "AB", "H"])
        self.assertIn("OPS+", headings)
        self.assertIn("ISO", headings)

    def test_a_pitchers_line_carries_what_was_asked_for(self):
        headings = [h for h, _v in statline.display(PITCHER, True)]
        for wanted in ("IP", "ERA", "FIP", "WHIP", "K/9", "BB/9", "ERA+"):
            self.assertIn(wanted, headings)

    def test_the_two_roles_do_not_share_a_layout(self):
        self.assertNotEqual([h for h, _v in statline.display(BATTER, False)],
                            [h for h, _v in statline.display(PITCHER, True)])

    def test_absent_stats_are_left_out_rather_than_shown_empty(self):
        pairs = statline.display({"innings": 100.0, "era": 3.5}, True)
        self.assertEqual([h for h, _v in pairs], ["IP", "ERA"])

    def test_an_empty_line_displays_as_nothing(self):
        self.assertEqual(statline.display({}, False), [])


class SummaryTest(unittest.TestCase):
    def test_a_pitcher_leads_with_innings_and_era(self):
        text = statline.summary(PITCHER, True)
        self.assertTrue(text.startswith("IP 185.6"))
        self.assertIn("ERA 2.85", text)

    def test_a_hitter_leads_with_appearances_and_the_slash(self):
        text = statline.summary(BATTER, False)
        self.assertIn("AVG .306", text)
        self.assertIn("SLG .573", text)

    def test_an_empty_line_summarises_as_nothing(self):
        self.assertEqual(statline.summary({}, True), "")


class SlashTest(unittest.TestCase):
    def test_the_slash_line(self):
        self.assertEqual(statline.slash(BATTER), ".306/.396/.573")

    def test_a_missing_piece_means_no_slash_line(self):
        self.assertEqual(statline.slash({"avg": 0.3, "obp": 0.4}), "")


class FieldsTest(unittest.TestCase):
    def test_it_takes_what_the_projection_produced(self):
        from ootp_scout import projection

        line = projection.project_pitcher(
            stuff=160, movement=140, control=150, stamina=150, hold=120,
            ground_fly="NEU", position="SP")
        stored = statline.fields(line, True)
        self.assertEqual(set(stored), set(statline.PITCHER_FIELDS))
        self.assertAlmostEqual(stored["era"], round(line.era, 4))

    def test_and_keeps_the_two_roles_apart(self):
        from ootp_scout import projection

        line = projection.project_batter(
            contact=150, gap=140, power=160, eye=130, avoid_ks=140,
            speed=120, stealing=110, defense=120, position="CF")
        stored = statline.fields(line, False)
        self.assertIn("obp", stored)
        self.assertNotIn("era", stored)


if __name__ == "__main__":
    unittest.main()

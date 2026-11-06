"""Projected seasons, written the way baseball writes them."""

import unittest

from ootp_scout import statline

BATTER = {
    "games": 150, "plate_appearances": 600, "at_bats": 522, "hits": 160,
    "doubles": 34, "triples": 4, "home_runs": 33, "walks": 72,
    "strikeouts": 97, "stolen_bases": 11, "caught_stealing": 4,
    "hit_by_pitches": 6.3,
    "avg": 0.306, "obp": 0.396, "slg": 0.573, "ops": 0.970, "ops_plus": 168,
    "babip": 0.324, "war": 7.34,
}
PITCHER = {
    "games": 30, "starts": 30, "innings": 185.6, "hits": 147, "home_runs": 15,
    "runs": 64, "earned_runs": 59, "walks": 44, "strikeouts": 224,
    "batters_faced": 724, "hit_by_pitches": 2.1,
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




class WobaTest(unittest.TestCase):
    def test_the_scale_is_derived_so_league_woba_equals_league_obp(self):
        """That is wOBA's definition, not a convention layered on top."""
        from ootp_scout.projection import LEAGUE_TOTALS as t

        appearances = t["at_bats"] + t["walks"] + t["hit_by_pitches"]
        on_base = (t["hits"] + t["walks"] + t["hit_by_pitches"]) / appearances
        self.assertAlmostEqual(statline.LEAGUE_WOBA, on_base, places=9)

    def test_the_derived_weights_match_the_published_ones_in_shape(self):
        """Every weight lands within a few percent, and all by the same
        factor - the shape is right, and the offset is the scale alone."""
        published = {"walks": .690, "hit_by_pitches": .719, "singles": .870,
                     "doubles": 1.217, "triples": 1.529, "home_runs": 1.940}
        offsets = [statline.RUNS_ABOVE_OUT[name] * statline.WOBA_SCALE
                   / published[name] for name in published]
        self.assertLess(max(offsets) - min(offsets), 0.01)
        for offset in offsets:
            self.assertAlmostEqual(offset, 1.0, delta=0.05)

    def test_a_good_hitter_beats_the_league(self):
        self.assertGreater(statline.woba(BATTER), statline.LEAGUE_WOBA)

    def test_an_average_line_comes_out_near_100(self):
        from ootp_scout.projection import LEAGUE_TOTALS as t

        appearances = t["at_bats"] + t["walks"] + t["hit_by_pitches"]
        league = {
            "plate_appearances": appearances, "hits": t["hits"],
            "doubles": t["doubles"], "triples": t["triples"],
            "home_runs": t["home_runs"], "walks": t["walks"],
            "hit_by_pitches": t["hit_by_pitches"],
        }
        self.assertAlmostEqual(statline.wrc_plus(league), 100.0, places=6)

    def test_wrc_plus_is_not_a_copy_of_ops_plus(self):
        """They track each other but weight events differently."""
        full = statline.derive(BATTER, False)
        self.assertNotAlmostEqual(full["wrc_plus"], full["ops_plus"], places=1)
        self.assertAlmostEqual(full["wrc_plus"], full["ops_plus"], delta=12)

    def test_wrc_plus_does_not_move_with_the_scale(self):
        """The scale cancels, so a revised one cannot shift the rating."""
        before = statline.wrc_plus(BATTER)
        original = statline.WOBA_SCALE
        try:
            statline.WOBA_SCALE = original * 1.1
            statline.LEAGUE_WOBA = statline.LEAGUE_WOBA / original * (
                original * 1.1)
            self.assertAlmostEqual(statline.wrc_plus(BATTER), before, places=6)
        finally:
            statline.LEAGUE_WOBA = statline.LEAGUE_WOBA / (original * 1.1) * original
            statline.WOBA_SCALE = original

    def test_a_line_without_hit_by_pitches_gets_no_woba(self):
        """Rather than one about six points light on every player."""
        older = {k: v for k, v in BATTER.items() if k != "hit_by_pitches"}
        self.assertIsNone(statline.woba(older))
        self.assertIsNone(statline.wrc_plus(older))
        self.assertNotIn("wOBA", [h for h, _v in statline.display(older, False)])


class PitcherRatesTest(unittest.TestCase):
    def test_strikeout_and_walk_rates_are_per_batter_faced(self):
        full = statline.derive(PITCHER, True)
        self.assertAlmostEqual(full["k_rate"], 224 / 724 * 100, places=6)
        self.assertAlmostEqual(full["bb_rate"], 44 / 724 * 100, places=6)

    def test_a_line_without_batters_faced_gets_no_rate(self):
        older = {k: v for k, v in PITCHER.items() if k != "batters_faced"}
        self.assertNotIn("k_rate", statline.derive(older, True))

    def test_war_per_200_separates_effectiveness_from_innings(self):
        full = statline.derive(PITCHER, True)
        self.assertAlmostEqual(full["war_200"], 6.86 / 185.6 * 200, places=6)

    def test_two_pitchers_with_one_rate_and_different_innings(self):
        """The whole point: same arm, different workload, different WAR."""
        long_man = dict(PITCHER, innings=200.0, war=7.4)
        short = dict(PITCHER, innings=70.0, war=2.59)
        self.assertGreater(statline.derive(long_man, True)["war"],
                           statline.derive(short, True)["war"])
        self.assertAlmostEqual(statline.derive(long_man, True)["war_200"],
                               statline.derive(short, True)["war_200"],
                               delta=0.1)

    def test_the_pitching_line_carries_what_was_asked_for(self):
        headings = [h for h, _v in statline.display(PITCHER, True)]
        for wanted in ("ERA", "HR/9", "BB%", "K%", "WAR/200"):
            self.assertIn(wanted, headings)


if __name__ == "__main__":
    unittest.main()

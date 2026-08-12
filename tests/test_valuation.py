"""Surplus value: production priced against cost."""

import unittest

from ootp_scout import valuation

MILLION = 1_000_000
PER_WAR = 9 * MILLION


class AgingTest(unittest.TestCase):
    def test_this_season_is_the_projection_itself(self):
        self.assertEqual(valuation.aged_war(4.0, 25, 0), 4.0)

    def test_a_young_player_improves(self):
        self.assertGreater(valuation.aged_war(3.0, 22, 3), 3.0)

    def test_an_old_player_declines(self):
        self.assertLess(valuation.aged_war(3.0, 34, 3), 3.0)

    def test_decline_steepens_past_the_late_thirties(self):
        early = valuation.aged_war(5.0, 29, 1) - valuation.aged_war(5.0, 29, 0)
        late = valuation.aged_war(5.0, 35, 1) - valuation.aged_war(5.0, 35, 0)
        self.assertLess(late, early)

    def test_value_never_goes_negative(self):
        self.assertEqual(valuation.aged_war(0.5, 38, 10), 0.0)

    def test_unknown_age_holds_the_projection_flat(self):
        self.assertEqual(valuation.aged_war(3.0, None, 5), 3.0)


class DollarsPerWarTest(unittest.TestCase):
    def test_payroll_over_production(self):
        self.assertAlmostEqual(
            valuation.derive_dollars_per_war(900 * MILLION, 100.0), 9 * MILLION)

    def test_zero_war_refuses_rather_than_dividing(self):
        with self.assertRaises(ValueError) as caught:
            valuation.derive_dollars_per_war(900 * MILLION, 0.0)
        self.assertIn("cannot price a win", str(caught.exception))

    def test_zero_payroll_refuses(self):
        with self.assertRaises(ValueError):
            valuation.derive_dollars_per_war(0.0, 100.0)


class ValueTest(unittest.TestCase):
    def test_a_bargain_contract_has_positive_surplus(self):
        result = valuation.value(war=4.0, age=27, contract_years=3,
                                 salary=8 * MILLION, dollars_per_war=PER_WAR,
                                 include_control=False)
        self.assertGreater(result.surplus, 0)
        self.assertEqual(len(result.years), 3)

    def test_the_total_is_aged_not_the_projection_repeated(self):
        """A 27-year-old is already at the plateau, so years two and three
        decline. Summing a flat projection would overstate him."""
        result = valuation.value(war=4.0, age=27, contract_years=3,
                                 salary=8 * MILLION, dollars_per_war=PER_WAR,
                                 include_control=False)
        self.assertLess(result.total_war, 4.0 * 3)
        self.assertAlmostEqual(result.total_war, 4.0 + 3.7 + 3.4, places=6)

    def test_an_overpay_has_negative_surplus(self):
        result = valuation.value(war=1.0, age=33, contract_years=4,
                                 salary=25 * MILLION, dollars_per_war=PER_WAR,
                                 include_control=False)
        self.assertLess(result.surplus, 0)

    def test_later_years_are_discounted(self):
        one = valuation.value(4.0, None, 1, 0.0, PER_WAR, include_control=False)
        two = valuation.value(4.0, None, 2, 0.0, PER_WAR, include_control=False)
        second_year = two.production_value - one.production_value
        self.assertLess(second_year, one.production_value)

    def test_control_years_add_value(self):
        without = valuation.value(3.0, 23, 1, 700_000, PER_WAR,
                                  control_years=3, include_control=False)
        with_control = valuation.value(3.0, 23, 1, 700_000, PER_WAR,
                                       control_years=3, include_control=True)
        self.assertGreater(with_control.surplus, without.surplus)

    def test_arbitration_costs_rise_year_on_year(self):
        result = valuation.value(4.0, 25, 0, 0.0, PER_WAR, control_years=3)
        salaries = [year.resolved_salary(PER_WAR) for year in result.years]
        self.assertEqual(len(salaries), 3)
        self.assertLess(salaries[0], salaries[1])
        self.assertLess(salaries[1], salaries[2])

    def test_arbitration_still_leaves_surplus_for_a_good_player(self):
        """The cheap-young-player case the in-game value tends to miss."""
        result = valuation.value(4.0, 23, 0, 0.0, PER_WAR, control_years=3)
        self.assertGreater(result.surplus, 0)

    def test_a_replacement_level_player_on_a_big_deal_is_a_liability(self):
        result = valuation.value(0.0, 34, 3, 20 * MILLION, PER_WAR,
                                 include_control=False)
        self.assertLess(result.surplus, -40 * MILLION)

    def test_no_years_is_worth_nothing(self):
        result = valuation.value(5.0, 25, 0, 0.0, PER_WAR,
                                 include_control=False)
        self.assertEqual(result.surplus, 0.0)
        self.assertEqual(result.total_war, 0.0)


class CompareTest(unittest.TestCase):
    def _player(self, war, age, years, salary, control=0):
        return valuation.value(war, age, years, salary, PER_WAR,
                               control_years=control)

    def test_the_better_package_comes_out_ahead(self):
        star = ("Star", self._player(5.0, 26, 4, 10 * MILLION))
        filler = ("Filler", self._player(0.5, 31, 2, 9 * MILLION))
        result = valuation.compare([star], [filler])
        self.assertGreater(result["difference"], 0)
        self.assertGreater(result["a_surplus"], result["b_surplus"])

    def test_two_for_one_can_beat_one(self):
        one = [("Ace", self._player(4.0, 29, 2, 20 * MILLION))]
        two = [("Kid A", self._player(2.5, 23, 1, 700_000, control=3)),
               ("Kid B", self._player(2.0, 24, 1, 700_000, control=3))]
        result = valuation.compare(one, two)
        self.assertLess(result["difference"], 0)

    def test_war_totals_are_reported_alongside(self):
        result = valuation.compare(
            [("A", self._player(3.0, 27, 2, MILLION))],
            [("B", self._player(1.0, 27, 2, MILLION))])
        self.assertGreater(result["a_war"], result["b_war"])

    def test_an_empty_side_is_a_pure_giveaway(self):
        result = valuation.compare(
            [("A", self._player(3.0, 27, 2, MILLION))], [])
        self.assertEqual(result["b_surplus"], 0.0)
        self.assertGreater(result["difference"], 0)


if __name__ == "__main__":
    unittest.main()

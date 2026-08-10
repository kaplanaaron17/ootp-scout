import unittest

from ootp_scout import ratings as R
from ootp_scout import war_model
from ootp_scout.loading import Player


def hitter(**tools):
    player = Player(name="H", position="CF")
    player.current.update(tools)
    return player


def pitcher(**tools):
    player = Player(name="P", position="SP")
    player.current.update(tools)
    return player


class ProvisionalModelTest(unittest.TestCase):
    def setUp(self):
        self.model = war_model.ProvisionalModel()

    def test_better_ratings_produce_more_war(self):
        weak = hitter(contact=30, power=30)
        strong = hitter(contact=70, power=70)
        weak_war = self.model.project(weak, weak.current, R.SCALE_20_80).war
        strong_war = self.model.project(strong, strong.current, R.SCALE_20_80).war
        self.assertGreater(strong_war, weak_war)

    def test_monotone_in_every_hitting_tool(self):
        base = dict(contact=50, power=50, eye=50, gap=50, avoid_k=50,
                    speed=50, defense=50, arm=50, range=50, stealing=50)
        baseline = self.model.project(hitter(**base), base, R.SCALE_20_80).war
        for tool in base:
            bumped = dict(base, **{tool: 60})
            war = self.model.project(hitter(**bumped), bumped, R.SCALE_20_80).war
            with self.subTest(tool=tool):
                self.assertGreater(war, baseline)

    def test_pitcher_uses_pitching_weights(self):
        weak = pitcher(stuff=30, control=30, movement=30, stamina=30)
        strong = pitcher(stuff=70, control=70, movement=70, stamina=70)
        self.assertGreater(
            self.model.project(strong, strong.current, R.SCALE_20_80).war,
            self.model.project(weak, weak.current, R.SCALE_20_80).war)

    def test_position_adjustment_favors_up_the_middle(self):
        tools = dict(contact=50, power=50)
        catcher = Player(name="C", position="C")
        first = Player(name="1B", position="1B")
        catcher_war = self.model.project(catcher, tools, R.SCALE_20_80).war
        first_war = self.model.project(first, tools, R.SCALE_20_80).war
        self.assertGreater(catcher_war, first_war)

    def test_missing_tools_are_reported_not_guessed(self):
        projection = self.model.project(hitter(contact=50, power=50),
                                        {"contact": 50, "power": 50},
                                        R.SCALE_20_80)
        self.assertIn("eye", projection.missing)
        self.assertNotIn("eye", projection.components)

    def test_scale_independence(self):
        """The same relative rating gives the same WAR on either scale."""
        top_20_80 = {"contact": 80, "power": 80}
        top_1_100 = {"contact": 100, "power": 100}
        a = self.model.project(hitter(**top_20_80), top_20_80, R.SCALE_20_80).war
        b = self.model.project(hitter(**top_1_100), top_1_100, R.SCALE_1_100).war
        self.assertAlmostEqual(a, b, places=6)


class ExternalWarModelTest(unittest.TestCase):
    def test_reads_the_column_value(self):
        model = war_model.ExternalWarModel("WAR")
        player = hitter(contact=50)
        player.meta["_war_column_value"] = "4.5"
        self.assertEqual(model.project(player, {}, R.SCALE_20_80).war, 4.5)

    def test_non_numeric_value_raises(self):
        model = war_model.ExternalWarModel("WAR")
        player = hitter(contact=50)
        player.meta["_war_column_value"] = "n/a"
        with self.assertRaises(ValueError):
            model.project(player, {}, R.SCALE_20_80)


class RequiredToolsTest(unittest.TestCase):
    def test_role_specific(self):
        self.assertEqual(war_model.required_tools(pitcher()), {"stuff", "control"})
        self.assertEqual(war_model.required_tools(hitter()), {"contact", "power"})


if __name__ == "__main__":
    unittest.main()

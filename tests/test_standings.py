"""Team WAR from a depth chart, and the standings that follow from it."""

import unittest

from ootp_scout import flagging, standings

BATTING_SPOTS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH")


def batter(name, position, war, team="Louisville Bats", appearances=600.0):
    return flagging.Subject(
        name=name, position=position, grade=50.0, war=war, is_pitcher=False,
        meta={"team": team},
        projected={"plate_appearances": appearances, "war": war})


def arm(name, position, war, team="Louisville Bats", innings=200.0):
    return flagging.Subject(
        name=name, position=position, grade=50.0, war=war, is_pitcher=True,
        meta={"team": team}, projected={"innings": innings, "war": war})


def roster(team="Louisville Bats", bat_war=2.0, arm_war=2.0, depth=3):
    """A team with `depth` players at every position, all equally good."""
    players = []
    for spot in ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"):
        for number in range(depth):
            players.append(batter(f"{team} {spot}{number}", spot,
                                  bat_war - number * 0.1, team))
    for number in range(8):
        players.append(arm(f"{team} SP{number}", "SP",
                           arm_war - number * 0.1, team))
    for number in range(12):
        players.append(arm(f"{team} RP{number}", "RP",
                           arm_war - number * 0.1, team, innings=70.0))
    return players


class BudgetTest(unittest.TestCase):
    def test_plate_appearances_come_from_the_league_totals(self):
        """Derived from the same season the projection model is built on."""
        self.assertAlmostEqual(standings.PA_PER_GAME, 37.1, places=1)
        self.assertAlmostEqual(standings.PA_PER_GAME * 162, 6014, delta=5)

    def test_a_team_pitches_nine_innings_a_game(self):
        self.assertAlmostEqual(standings.INNINGS_PER_GAME * 162, 1458)


class TeamTest(unittest.TestCase):
    def test_every_slot_is_filled_when_there_is_depth(self):
        team = standings.project_team("Louisville Bats", roster())
        self.assertEqual(team.unfilled, [])
        self.assertEqual(len(team.lineup), 9)
        self.assertEqual(len(team.rotation), 5)
        self.assertEqual(len(team.bullpen), 8)

    def test_each_lineup_slot_gets_a_player_who_plays_there(self):
        team = standings.project_team("Louisville Bats", roster())
        for slot in team.lineup:
            if slot.label == "DH":
                continue
            self.assertEqual(
                flagging.normalize_position(slot.player.position), slot.label)

    def test_the_best_player_at_a_position_takes_the_slot(self):
        players = roster()
        players.append(batter("Star Shortstop", "SS", 9.0))
        team = standings.project_team("Louisville Bats", players)
        shortstop = next(s for s in team.lineup if s.label == "SS")
        self.assertEqual(shortstop.name, "Star Shortstop")

    def test_nobody_fills_two_slots(self):
        team = standings.project_team("Louisville Bats", roster())
        names = [s.name for s in team.slots if s.player]
        self.assertEqual(len(names), len(set(names)))

    def test_a_position_nobody_plays_is_left_empty(self):
        players = [p for p in roster()
                   if flagging.normalize_position(p.position) != "C"]
        team = standings.project_team("Louisville Bats", players)
        self.assertIn("C", team.unfilled)

    def test_an_empty_slot_is_worth_replacement_level(self):
        """Nothing above replacement, which is exactly nothing - not a penalty."""
        players = [p for p in roster()
                   if flagging.normalize_position(p.position) != "C"]
        team = standings.project_team("Louisville Bats", players)
        catcher = next(s for s in team.lineup if s.label == "C")
        self.assertEqual(catcher.war, 0.0)

    def test_a_reliever_is_not_pressed_into_the_rotation(self):
        """His stamina says he cannot throw 175 innings, so he must not be
        credited with them."""
        players = [p for p in roster()
                   if flagging.normalize_position(p.position) != "SP"]
        team = standings.project_team("Louisville Bats", players)
        self.assertEqual(team.unfilled.count("SP1"), 1)
        self.assertTrue(all(s.player is None for s in team.rotation))

    def test_war_is_scaled_to_the_playing_time_the_slot_carries(self):
        """A regular projected over 600 PA who gets 568 keeps 568/600 of it."""
        team = standings.project_team(
            "Louisville Bats",
            roster() + [batter("Even Eddie", "SS", 6.0, appearances=600.0)])
        shortstop = next(s for s in team.lineup if s.label == "SS")
        self.assertAlmostEqual(shortstop.war,
                               6.0 * shortstop.playing_time / 600.0, places=6)

    def test_a_bench_bat_contributes_a_fraction_of_a_season(self):
        team = standings.project_team("Louisville Bats", roster())
        bench = team.bench[0]
        self.assertLess(bench.war, bench.full_season_war / 2)

    def test_a_sub_replacement_player_costs_more_the_more_he_plays(self):
        bad = batter("Bad Barry", "SS", -3.0, appearances=600.0)
        regular = standings._fill("SS", bad, 600.0)
        part_time = standings._fill("BN1", bad, 180.0)
        self.assertLess(regular.war, part_time.war)
        self.assertLess(regular.war, 0)

    def test_a_player_with_no_stored_line_keeps_his_war_as_projected(self):
        """Rather than inventing the innings behind it."""
        unknown = flagging.Subject(name="Old Record", position="SP",
                                   grade=50.0, war=4.0, is_pitcher=True,
                                   meta={"team": "Louisville Bats"})
        slot = standings._fill("SP1", unknown, 175.0)
        self.assertEqual(slot.war, 4.0)

    def test_batting_and_pitching_add_up_to_the_total(self):
        team = standings.project_team("Louisville Bats", roster())
        self.assertAlmostEqual(team.war,
                               team.batting_war + team.pitching_war, places=6)

    def test_a_whole_organisation_does_not_inflate_the_total(self):
        """The bug this module exists for: 120 players, 26 of whom play."""
        deep = roster(depth=12) + [
            arm(f"Filler {n}", "RP", -4.0, innings=200.0) for n in range(60)]
        team = standings.project_team("Louisville Bats", deep)
        self.assertEqual(team.considered, len(deep))
        self.assertLess(team.war, 80)
        self.assertGreater(team.war, 0)


class StandingsTest(unittest.TestCase):
    def setUp(self):
        self.players = (roster("Alpha", bat_war=4.0, arm_war=4.0)
                        + roster("Bravo", bat_war=2.0, arm_war=2.0)
                        + roster("Charlie", bat_war=0.5, arm_war=0.5))

    def test_the_wins_must_total_half_the_games_played(self):
        """Every game has a winner. This is what fixes replacement level."""
        table = standings.project_standings(self.players, games=162)
        self.assertAlmostEqual(sum(t.wins for t in table.teams),
                               162 * len(table.teams) / 2, places=6)

    def test_losses_are_the_rest_of_the_season(self):
        table = standings.project_standings(self.players, games=162)
        for team in table.teams:
            self.assertAlmostEqual(team.wins + team.losses, 162, places=6)

    def test_the_better_team_finishes_higher(self):
        table = standings.project_standings(self.players)
        self.assertEqual([t.team for t in table.teams],
                         ["Alpha", "Bravo", "Charlie"])

    def test_replacement_level_is_derived_not_assumed(self):
        table = standings.project_standings(self.players, games=162)
        average = sum(t.war for t in table.teams) / len(table.teams)
        self.assertAlmostEqual(table.replacement_wins, 81 - average, places=6)

    def test_a_shorter_season_scales_the_whole_thing(self):
        short = standings.project_standings(self.players, games=100)
        self.assertAlmostEqual(sum(t.wins for t in short.teams),
                               100 * 3 / 2, places=6)
        for team in short.teams:
            self.assertAlmostEqual(team.wins + team.losses, 100, places=6)

    def test_players_without_a_team_are_left_off_every_roster(self):
        free = batter("Free Agent", "SS", 8.0, team="")
        table = standings.project_standings(self.players + [free])
        every = [s.name for t in table.teams for s in t.slots if s.player]
        self.assertNotIn("Free Agent", every)
        self.assertIn("carry no team", " ".join(table.notes))

    def test_a_pool_with_no_teams_at_all_says_what_is_missing(self):
        table = standings.project_standings([batter("Al", "SS", 3.0, team="")])
        self.assertEqual(table.teams, [])
        self.assertIn("ORG", " ".join(table.notes))

    def test_thin_rosters_are_flagged_rather_than_quietly_ranked(self):
        table = standings.project_standings(
            self.players + [batter("Lonely Guy", "SS", 3.0, team="Delta")])
        self.assertIn("fewer than 26", " ".join(table.notes))

    def test_unfilled_slots_are_reported(self):
        thin = [p for p in self.players
                if not (p.meta["team"] == "Alpha"
                        and flagging.normalize_position(p.position) == "C")]
        table = standings.project_standings(thin)
        self.assertIn("could not fill", " ".join(table.notes))


class RoleTest(unittest.TestCase):
    def test_a_position_player_recorded_as_a_pitcher_is_treated_as_one(self):
        """The recorded role wins, since the export is what produced it."""
        player = flagging.Subject(name="Two Way", position="RP", grade=50.0,
                                 war=2.0, is_pitcher=True, meta={})
        self.assertTrue(standings.is_pitcher(player))

    def test_and_the_position_decides_when_the_role_is_silent(self):
        player = flagging.Subject(name="Arm", position="SP", grade=50.0,
                                 war=2.0, is_pitcher=False, meta={})
        self.assertTrue(standings.is_pitcher(player))
        bat = flagging.Subject(name="Bat", position="CF", grade=50.0,
                               war=2.0, is_pitcher=False, meta={})
        self.assertFalse(standings.is_pitcher(bat))


if __name__ == "__main__":
    unittest.main()

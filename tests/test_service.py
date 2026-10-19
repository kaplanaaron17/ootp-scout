"""The operations both the window and the command line call.

The window itself is barely tested - it is a shell that asks, shows and
complains. Everything it could get wrong about *meaning* lives here.
"""

import os
import tempfile
import unittest

from ootp_scout import service

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
BATTERS = os.path.join(FIXTURES, "pool_batters.tsv")
PITCHERS = os.path.join(FIXTURES, "groundfly_pitchers.tsv")
ORGS = os.path.join(FIXTURES, "pool_batters_orgs.tsv")
OVER_100 = os.path.join(FIXTURES, "scale_1_100_over.tsv")


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.folder.name, "service.db")

    def tearDown(self):
        self.folder.cleanup()

    def _import(self, path=BATTERS, **kwargs):
        kwargs.setdefault("league", "Demo")
        return service.import_export(path, db=self.db, **kwargs)


class ImportTest(ServiceTest):
    def test_imports_and_reports_what_it_did(self):
        result = self._import()
        self.assertEqual(result.players, 41)
        self.assertEqual(result.added, 41)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.scale, "20 to 80")
        self.assertEqual(result.view_name, "Batting Ratings")

    def test_a_second_import_of_the_same_day_updates(self):
        self._import()
        again = self._import()
        self.assertEqual(again.added, 0)
        self.assertEqual(again.updated, 41)

    def test_the_league_is_taken_from_the_path_when_not_given(self):
        result = service.import_export(BATTERS, db=self.db)
        self.assertEqual(result.league, "default")

    def test_a_tag_is_recorded(self):
        self._import(tag="2033 draft")
        self.assertEqual(service.tags(db=self.db), [("2033 draft", 41)])

    def test_a_missing_file_is_a_readable_complaint(self):
        with self.assertRaises(service.ScoutError) as caught:
            service.import_export("nowhere.tsv", db=self.db)
        self.assertIn("No such file", str(caught.exception))

    def test_an_unusable_export_complains_rather_than_raising_raw(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "wrong.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("Name,Age\nAl,22\n")
            with self.assertRaises(service.ScoutError):
                service.import_export(path, db=self.db)

    def test_pitchers_get_runs_allowed_war(self):
        self._import(PITCHERS)
        result = service.rank(db=self.db)
        self.assertTrue(any(f.subject.rwar is not None
                            for f in result.findings))


class RankTest(ServiceTest):
    def test_ranks_what_was_imported(self):
        self._import()
        result = service.rank(db=self.db)
        self.assertEqual(result.league, "Demo")
        self.assertEqual(result.mode, "current")
        self.assertEqual(result.fitted_on, 41)
        self.assertEqual(result.findings[0].subject.name, "Sleeper Sam")

    def test_an_empty_database_says_so(self):
        with self.assertRaises(service.ScoutError) as caught:
            service.rank(db=self.db)
        self.assertIn("import an export", str(caught.exception))

    def test_it_refuses_to_choose_between_leagues(self):
        self._import(league="One")
        self._import(PITCHERS, league="Two")
        with self.assertRaises(service.ScoutError) as caught:
            service.rank(db=self.db)
        self.assertIn("never combined", str(caught.exception))

    def test_naming_the_league_resolves_it(self):
        self._import(league="One")
        self._import(PITCHERS, league="Two")
        self.assertEqual(service.rank(db=self.db, league="Two").league, "Two")

    def test_a_grade_floor_is_applied_and_noted(self):
        self._import()
        result = service.rank(db=self.db, min_grade=45)
        self.assertLess(result.fitted_on, 41)
        self.assertTrue(any("Ignored" in n for n in result.notes))

    def test_a_pool_of_sub_replacement_players_is_noted(self):
        self._import()
        result = service.rank(db=self.db)
        self.assertTrue(any("below replacement" in n for n in result.notes))

    def test_a_tag_narrows_the_output_but_not_the_fit(self):
        self._import(tag="draft")
        self._import(PITCHERS, tag=None)
        result = service.rank(db=self.db, tag="draft")
        self.assertEqual(result.shown, 41)
        self.assertGreater(result.fitted_on, result.shown)

    def test_fit_on_tag_narrows_both(self):
        self._import(tag="draft")
        self._import(PITCHERS)
        result = service.rank(db=self.db, tag="draft", fit_on_tag=True)
        self.assertEqual(result.fitted_on, result.shown)

    def test_an_unknown_tag_complains(self):
        self._import()
        with self.assertRaises(service.ScoutError):
            service.rank(db=self.db, tag="nope")

    def test_restricting_to_a_role_drops_the_other(self):
        self._import()
        self._import(PITCHERS)
        arms = service.rank(db=self.db, role="pitcher")
        self.assertTrue(all(f.subject.is_pitcher for f in arms.findings))

    def test_too_few_players_complains_rather_than_fitting(self):
        self._import()
        with self.assertRaises(service.ScoutError) as caught:
            service.rank(db=self.db, min_grade=99)
        self.assertIn("left to fit", str(caught.exception))


class TeamTest(ServiceTest):
    def test_the_clubs_held_come_back_with_counts(self):
        self._import(ORGS)
        held = dict(service.teams("Demo", self.db))
        self.assertEqual(sum(held.values()), 41)
        self.assertIn("Louisville Bats", held)

    def test_one_club_can_be_singled_out(self):
        self._import(ORGS)
        only = service.rank(db=self.db, team="Louisville Bats")
        clubs = {f.subject.meta["team"] for f in only.findings}
        self.assertEqual(clubs, {"Louisville Bats"})
        self.assertLess(only.shown, 41)

    def test_a_partial_club_name_is_enough(self):
        self._import(ORGS)
        self.assertTrue(service.rank(db=self.db, team="louisville").findings)

    def test_the_fit_still_spans_the_league(self):
        """Ranking a club against its own 14 players answers nothing.

        The question is whether a player is underrated against the league, so
        the club narrows who is listed and not who he is measured against.
        """
        self._import(ORGS)
        only = service.rank(db=self.db, team="Louisville Bats")
        self.assertEqual(only.fitted_on, 41)
        self.assertLess(only.shown, 41)
        self.assertIn("measured against all 41", " ".join(only.notes))

    def test_fitting_inside_the_club_is_available_if_asked_for(self):
        self._import(ORGS)
        inside = service.rank(db=self.db, team="Louisville Bats",
                              fit_on_team=True)
        self.assertEqual(inside.fitted_on, inside.shown)
        self.assertLess(inside.fitted_on, 41)

    def test_a_club_nobody_is_on_complains(self):
        self._import(ORGS)
        with self.assertRaises(service.ScoutError) as caught:
            service.rank(db=self.db, team="Akron Aeros")
        self.assertIn("Akron Aeros", str(caught.exception))

    def test_a_player_keeps_his_league_wide_rank(self):
        """His position in the ranking is a league fact, not a club one."""
        self._import(ORGS)
        league = [f.subject.name for f in service.rank(db=self.db).findings]
        club = service.rank(db=self.db, team="Louisville Bats").findings
        order = [league.index(f.subject.name) for f in club]
        self.assertEqual(order, sorted(order))


class SeenTest(ServiceTest):
    """A player who has left must stop showing up as being on the roster.

    His last observation is still his latest one, so without a recency cutoff
    a traded player sits on your team forever.
    """

    def _two_dates(self, keep=10):
        """Import everyone, backdate them, then import a shortened roster."""
        import datetime as dt

        from ootp_scout import database

        self._import()
        connection = database.connect(self.db)
        old = (dt.date.today() - dt.timedelta(days=200)).isoformat()
        connection.execute("UPDATE observations SET seen_at = ?",
                           (old + "T12:00:00",))
        connection.commit()
        connection.close()

        lines = open(BATTERS, encoding="utf-8").read().splitlines()
        short = os.path.join(self.folder.name, "after.tsv")
        with open(short, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines[:keep + 1]) + "\n")
        self._import(short)
        return old

    def test_without_a_cutoff_everyone_is_still_listed(self):
        self._two_dates()
        self.assertEqual(service.rank(db=self.db).shown, 41)

    def test_but_it_says_the_stale_ones_may_have_left(self):
        self._two_dates()
        notes = " ".join(service.rank(db=self.db).notes)
        self.assertIn("may have left", notes)

    def test_the_newest_import_shows_only_who_is_still_there(self):
        self._two_dates(keep=10)
        result = service.rank(db=self.db, seen="newest import")
        self.assertEqual(result.shown, 10)
        self.assertIn("Hid 31", " ".join(result.notes))

    def test_a_days_window_does_the_same(self):
        self._two_dates(keep=10)
        self.assertEqual(service.rank(db=self.db, seen="last 30 days").shown, 10)

    def test_a_window_wide_enough_keeps_everyone(self):
        self._two_dates(keep=10)
        self.assertEqual(service.rank(db=self.db, seen="last year").shown, 41)

    def test_an_unknown_window_is_ignored_rather_than_crashing(self):
        self._two_dates()
        self.assertEqual(service.rank(db=self.db, seen="whenever").shown, 41)

    def test_the_date_each_player_was_seen_comes_through(self):
        self._import()
        result = service.rank(db=self.db)
        seen = result.findings[0].subject.meta.get("seen")
        self.assertRegex(seen, r"^\d{4}-\d{2}-\d{2}$")


class RatingsPast100Test(ServiceTest):
    """A 1-100 league that displays above 100 used to be refused outright."""

    def test_it_imports(self):
        result = self._import(OVER_100)
        self.assertEqual(result.scale, "1 to 100")
        self.assertEqual(result.players, 41)
        self.assertEqual(result.skipped, [])

    def test_and_ranks_with_the_planted_player_on_top(self):
        self._import(OVER_100)
        result = service.rank(db=self.db)
        self.assertEqual(result.findings[0].subject.name, "Sleeper Sam")

    def test_implied_grades_stay_on_the_1_100_scale(self):
        self._import(OVER_100)
        for finding in service.rank(db=self.db).findings:
            if finding.implied_grade is not None:
                self.assertGreaterEqual(finding.implied_grade, 1)
                self.assertLessEqual(finding.implied_grade, 100)


class ProjectedLineTest(ServiceTest):
    """The projected season used to be computed and thrown away."""

    def test_a_hitters_line_is_stored(self):
        self._import()
        result = service.rank(db=self.db)
        line = result.findings[0].subject.projected
        self.assertIn("obp", line)
        self.assertIn("home_runs", line)
        self.assertGreater(line["plate_appearances"], 0)

    def test_a_pitchers_line_carries_era_and_innings(self):
        self._import(PITCHERS)
        result = service.rank(db=self.db)
        line = result.findings[0].subject.projected
        self.assertIn("era", line)
        self.assertIn("innings", line)
        self.assertGreater(line["innings"], 0)

    def test_the_stored_war_matches_the_ranked_war(self):
        """Two copies of the same number must not drift."""
        self._import()
        for finding in service.rank(db=self.db).findings:
            self.assertAlmostEqual(finding.subject.projected["war"],
                                   finding.subject.war, places=2)

    def test_a_row_stored_before_lines_were_kept_still_ranks(self):
        from ootp_scout import database

        self._import()
        connection = database.connect(self.db)
        connection.execute("UPDATE observations SET projected = NULL")
        connection.commit()
        connection.close()
        result = service.rank(db=self.db)
        self.assertEqual(result.shown, 41)
        self.assertEqual(result.findings[0].subject.projected, {})


class HistoryTest(ServiceTest):
    def test_finds_a_player(self):
        self._import()
        rows, matches = service.history("Sleeper Sam", db=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Sleeper Sam")

    def test_a_partial_name_returns_candidates(self):
        self._import()
        rows, matches = service.history("sleeper", db=self.db)
        self.assertTrue(matches)

    def test_an_unknown_player_returns_nothing_rather_than_raising(self):
        self._import()
        rows, matches = service.history("Nobody", db=self.db)
        self.assertEqual((rows, matches), ([], []))


class CompareTest(ServiceTest):
    def test_weighs_two_sides(self):
        self._import()
        result = service.compare(["Sleeper Sam"], ["Player 00"], db=self.db)
        self.assertGreater(result["a_war"], result["b_war"])
        self.assertEqual(len(result["a"]), 1)

    def test_partial_names_resolve(self):
        self._import()
        result = service.compare(["sleeper sam"], ["Player 02"], db=self.db)
        self.assertEqual(result["a"][0].subject.name, "Sleeper Sam")

    def test_an_unknown_player_complains(self):
        self._import()
        with self.assertRaises(service.ScoutError) as caught:
            service.compare(["Nobody At All"], ["Player 00"], db=self.db)
        self.assertIn("Nobody At All", str(caught.exception))

    def test_an_empty_trade_complains(self):
        self._import()
        with self.assertRaises(service.ScoutError):
            service.compare([""], [""], db=self.db)


class DatabaseLocationTest(unittest.TestCase):
    def test_an_override_wins(self):
        from ootp_scout import database
        original = os.environ.get("OOTP_SCOUT_DB")
        os.environ["OOTP_SCOUT_DB"] = r"X:\somewhere\scout.db"
        try:
            self.assertEqual(database.default_path(), r"X:\somewhere\scout.db")
        finally:
            if original is None:
                del os.environ["OOTP_SCOUT_DB"]
            else:
                os.environ["OOTP_SCOUT_DB"] = original

    def test_the_user_data_directory_is_outside_the_package(self):
        """An installed application must not write inside its own folder."""
        from ootp_scout import database
        package = os.path.dirname(os.path.abspath(database.__file__))
        self.assertFalse(database.user_data_dir().startswith(package))


if __name__ == "__main__":
    unittest.main()

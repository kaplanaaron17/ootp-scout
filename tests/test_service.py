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

"""The persistent observation store."""

import os
import tempfile
import unittest

from ootp_scout import database


def observation(name, mode="current", role="batter", grade=50.0, war=3.0,
                seen_at="2026-04-01T12:00:00+00:00", **kwargs):
    return database.Observation(name=name, mode=mode, role=role, grade=grade,
                                war=war, seen_at=seen_at, **kwargs)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.folder.name, "test.db")
        self.connection = database.connect(self.path)

    def tearDown(self):
        self.connection.close()
        self.folder.cleanup()

    def test_records_and_reads_back(self):
        added, updated = database.record(self.connection,
                                         [observation("Al Alpha")])
        self.assertEqual((added, updated), (1, 0))
        rows = database.latest(self.connection)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Al Alpha")

    def test_rerunning_the_same_day_corrects_rather_than_duplicates(self):
        database.record(self.connection, [observation("Al Alpha", war=3.0)])
        added, updated = database.record(self.connection,
                                         [observation("Al Alpha", war=4.0)])
        self.assertEqual((added, updated), (0, 1))
        rows = database.latest(self.connection)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["war"], 4.0)

    def test_a_later_date_is_a_new_observation(self):
        database.record(self.connection,
                        [observation("Al Alpha", grade=45.0,
                                     seen_at="2026-04-01T12:00:00+00:00")])
        database.record(self.connection,
                        [observation("Al Alpha", grade=55.0,
                                     seen_at="2027-04-01T12:00:00+00:00")])
        history = database.history(self.connection, "Al Alpha")
        self.assertEqual(len(history), 2)
        self.assertEqual([r["grade"] for r in history], [45.0, 55.0])

    def test_latest_returns_the_newest_per_player(self):
        database.record(self.connection,
                        [observation("Al Alpha", grade=45.0,
                                     seen_at="2026-04-01T12:00:00+00:00")])
        database.record(self.connection,
                        [observation("Al Alpha", grade=55.0,
                                     seen_at="2027-04-01T12:00:00+00:00")])
        rows = database.latest(self.connection)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["grade"], 55.0)

    def test_current_and_potential_are_kept_apart(self):
        database.record(self.connection, [
            observation("Al Alpha", mode="current", grade=45.0),
            observation("Al Alpha", mode="potential", grade=65.0),
        ])
        rows = database.latest(self.connection)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["mode"]: r["grade"] for r in rows},
                         {"current": 45.0, "potential": 65.0})

    def test_latest_can_filter_by_mode_and_role(self):
        database.record(self.connection, [
            observation("Hitter", mode="current", role="batter"),
            observation("Arm", mode="current", role="pitcher"),
            observation("Prospect", mode="potential", role="batter"),
        ])
        self.assertEqual(len(database.latest(self.connection, mode="current")), 2)
        self.assertEqual(
            len(database.latest(self.connection, mode="current",
                                role="pitcher")), 1)

    def test_ratings_round_trip(self):
        database.record(self.connection,
                        [observation("Al Alpha",
                                     ratings={"CON": "60", "POW": "55"})])
        row = database.latest(self.connection)[0]
        self.assertEqual(database.to_ratings(row), {"CON": "60", "POW": "55"})

    def test_names_match_case_insensitively(self):
        database.record(self.connection, [observation("Al Alpha")])
        self.assertEqual(len(database.history(self.connection, "al alpha")), 1)

    def test_search_finds_partial_names(self):
        database.record(self.connection, [observation("Sleeper Sam"),
                                          observation("Ace Sleeper"),
                                          observation("Someone Else")])
        found = database.search(self.connection, "sleeper")
        self.assertEqual({r["name"] for r in found},
                         {"Sleeper Sam", "Ace Sleeper"})

    def test_search_reports_how_many_records_each_player_has(self):
        database.record(self.connection,
                        [observation("Al Alpha",
                                     seen_at="2026-04-01T12:00:00+00:00")])
        database.record(self.connection,
                        [observation("Al Alpha",
                                     seen_at="2027-04-01T12:00:00+00:00")])
        self.assertEqual(database.search(self.connection, "alpha")[0]["records"],
                         2)

    def test_stats_summarise_the_store(self):
        database.record(self.connection, [
            observation("Hitter", role="batter"),
            observation("Arm", role="pitcher"),
        ])
        summary = database.stats(self.connection)
        self.assertEqual(summary["players"], 2)
        self.assertEqual(summary["observations"], 2)
        self.assertIn(("current", "batter", 1), summary["by_mode"])

    def test_stats_on_an_empty_store(self):
        summary = database.stats(self.connection)
        self.assertEqual(summary["observations"], 0)
        self.assertEqual(summary["players"], 0)

    def test_a_missing_file_is_created(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "brand-new.db")
            connection = database.connect(path)
            try:
                self.assertTrue(os.path.exists(path))
                self.assertEqual(database.stats(connection)["players"], 0)
            finally:
                connection.close()

    def test_corrupt_ratings_json_does_not_raise(self):
        database.record(self.connection, [observation("Al Alpha")])
        self.connection.execute("UPDATE observations SET ratings = 'not json'")
        row = database.latest(self.connection)[0]
        self.assertEqual(database.to_ratings(row), {})


if __name__ == "__main__":
    unittest.main()

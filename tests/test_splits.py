"""Splits: each player projected against each hand, then blended.

OOTP rates a hitter's contact and power separately against left- and
right-handed pitching, and a pitcher's stuff separately against left- and
right-handed batters. The calculator projects from the overall ratings only;
these project each side as its own season and blend the two by how much of a
season falls on it.
"""

import os
import tempfile
import unittest

from ootp_scout import projection, service, statline, tables, views

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
BATTERS = os.path.join(FIXTURES, "pool_batters.tsv")
PITCHERS = os.path.join(FIXTURES, "groundfly_pitchers.tsv")


def rewrite(path, folder, name, changes):
    """A copy of an export with some cells changed: {player: {column: v}}."""
    headers, rows = tables.read_table(path)
    out = os.path.join(folder, os.path.basename(path))
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("\t".join(headers) + "\n")
        for cells in rows:
            cells = list(cells)
            wanted = changes.get(cells[headers.index("Name")], {})
            for column, value in wanted.items():
                cells[headers.index(column)] = str(value)
            handle.write("\t".join(cells) + "\n")
    return out


def project(path):
    headers, raw = tables.read_table(path)
    view = views.identify_view(headers)
    rows, _ = views.parse_rows(headers, raw, view)
    scale, _ = views.infer_scale(rows, view)
    found, _ = projection.project_rows(rows, view, scale)
    return {p.name: p for p in found}, view


class SplitTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.folder.cleanup()

    def test_a_platoon_bat_projects_worse_against_lefties(self):
        path = rewrite(BATTERS, self.folder.name, "b",
                       {"Player 00": {"CON vL": 35, "POW vL": 35}})
        found, _ = project(path)
        stored = statline.stored_line(found["Player 00"], False)
        self.assertLess(stored["war_vl"], stored["war_vr"])
        self.assertLess(stored["wrc_plus_vl"], stored["wrc_plus_vr"])
        self.assertLess(stored["ops_vl"], stored["ops_vr"])

    def test_war_splits_blends_by_the_share_against_lefties(self):
        path = rewrite(BATTERS, self.folder.name, "b",
                       {"Player 00": {"CON vL": 35, "POW vL": 35}})
        found, _ = project(path)
        stored = statline.stored_line(found["Player 00"], False)
        share = projection.SHARE_VS_LHP
        self.assertAlmostEqual(
            stored["war_split"],
            share * stored["war_vl"] + (1 - share) * stored["war_vr"],
            places=3)
        self.assertLess(stored["war_split"], stored["war"])

    def test_even_splits_agree_with_the_overall_projection(self):
        """Player 00 is 60 everywhere, so every side is the same hitter."""
        found, _ = project(BATTERS)
        stored = statline.stored_line(found["Player 00"], False)
        self.assertAlmostEqual(stored["war_vl"], stored["war_vr"], places=3)
        self.assertAlmostEqual(stored["war_split"], stored["war"], places=3)

    def test_the_overall_war_still_matches_the_calculator(self):
        """Splits sit beside the site's number; they do not replace it."""
        plain, _ = project(BATTERS)
        path = rewrite(BATTERS, self.folder.name, "b",
                       {"Player 00": {"CON vL": 35, "POW vL": 35}})
        split, _ = project(path)
        self.assertAlmostEqual(plain["Player 00"].war,
                               split["Player 00"].war, places=9)

    def test_a_pitcher_with_worse_stuff_against_lefties(self):
        path = rewrite(PITCHERS, self.folder.name, "p",
                       {"GF NEU": {"STU vL": 45}})
        found, _ = project(path)
        stored = statline.stored_line(found["GF NEU"], True)
        self.assertGreater(stored["era_vl"], stored["era_vr"])
        self.assertLess(stored["k_rate_vl"], stored["k_rate_vr"])
        self.assertLess(stored["war_vl"], stored["war_vr"])

    def test_a_pitchers_mix_of_batters_follows_his_own_hand(self):
        self.assertEqual(projection.share_of_left_handed_batters("R"),
                         projection.SHARE_LHB_VS_RHP)
        self.assertEqual(projection.share_of_left_handed_batters("L"),
                         projection.SHARE_LHB_VS_LHP)
        self.assertGreater(projection.SHARE_LHB_VS_RHP,
                           projection.SHARE_LHB_VS_LHP)
        path = rewrite(PITCHERS, self.folder.name, "p",
                       {"GF NEU": {"T": "L"}})
        found, _ = project(path)
        self.assertEqual(found["GF NEU"].share_vl,
                         projection.SHARE_LHB_VS_LHP)

    def test_no_split_columns_means_no_split_stats(self):
        path = os.path.join(self.folder.name, "no_splits.tsv")
        headers, rows = tables.read_table(BATTERS)
        drop = {headers.index(c) for c in ("CON vL", "POW vL")}
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\t".join(headers) + "\n")
            for cells in rows:
                handle.write("\t".join(
                    "-" if i in drop else c for i, c in enumerate(cells))
                    + "\n")
        found, _ = project(path)
        stored = statline.stored_line(found["Player 00"], False)
        self.assertNotIn("war_split", stored)
        self.assertNotIn("war_vl", stored)

    def test_splits_reach_the_card(self):
        found, _ = project(BATTERS)
        headings = [h for h, _v in statline.display(
            statline.stored_line(found["Player 00"], False), False)]
        for wanted in ("wRC+ vL", "wRC+ vR", "WAR splits"):
            self.assertIn(wanted, headings)

    def test_splits_are_stored_by_an_import(self):
        db = os.path.join(self.folder.name, "s.db")
        service.import_export(BATTERS, db=db)
        service.import_export(PITCHERS, db=db)
        table = service.projections(db=db)
        self.assertIn("war_split", table.hitters[0].projected)
        self.assertIn("era_vl", table.pitchers[0].projected)


if __name__ == "__main__":
    unittest.main()

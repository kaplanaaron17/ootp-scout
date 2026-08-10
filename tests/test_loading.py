import os
import tempfile
import unittest

from ootp_scout import loading

RATINGS_CSV = """Name,POS,Age,OVR,POT,Con,Pow,Eye,Ks,DF,SctAcc
Al Alpha,CF,22,45,60,55,50,45,50,60,High
Bo Bravo,SP,24,50,55,,,,,,Low
"""

PITCHER_CSV = """Name,POS,Age,OVR,POT,Stu,Mov,Ctl,Sta,SctAcc
Bo Bravo,SP,24,50,55,60,45,55,50,Low
"""

DRAFT_POOL_CSV = """POS,#,Name,Inf,DOB,Age,NAT,HT,WT,B,T,OVR,POT,Prone,DEM,Sign,SctAcc
SP,14,Nicolas Arnaud,,02/20/2010,21,CAN,"6' 2'",185 lbs,Right,Right,40,80,Normal,-,Easy,High
"""

POTENTIAL_CSV = """Name,POS,OVR,POT,Con,Pow,POT Con,POT Pow
Al Alpha,CF,45,60,40,45,70,65
"""


class TempCsv:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                             newline="", encoding="utf-8")
        handle.write(self.text)
        handle.close()
        self.path = handle.name
        return self.path

    def __exit__(self, *exc):
        os.unlink(self.path)


class LoadCsvTest(unittest.TestCase):
    def test_parses_players_and_meta(self):
        with TempCsv(RATINGS_CSV) as path:
            result = loading.load_csv(path)
        self.assertEqual(len(result.players), 1)  # Bo Bravo has no ratings
        player = result.players[0]
        self.assertEqual(player.name, "Al Alpha")
        self.assertEqual(player.position, "CF")
        self.assertEqual(player.overall_current, 45)
        self.assertEqual(player.overall_potential, 60)
        self.assertEqual(player.current["contact"], 55)
        self.assertEqual(player.meta["scouting_accuracy"], "High")
        self.assertEqual(len(result.skipped), 1)

    def test_draft_pool_export_raises_actionable_error(self):
        with TempCsv(DRAFT_POOL_CSV) as path:
            with self.assertRaises(ValueError) as caught:
                loading.load_csv(path)
        message = str(caught.exception)
        self.assertIn("no ratings columns", message)
        self.assertIn("re-export", message)

    def test_potential_columns_are_kept_separate(self):
        with TempCsv(POTENTIAL_CSV) as path:
            result = loading.load_csv(path)
        player = result.players[0]
        self.assertTrue(result.used_potential_tools)
        self.assertEqual(player.current["contact"], 40)
        self.assertEqual(player.potential["contact"], 70)
        self.assertEqual(player.tools("potential")["power"], 65)
        self.assertEqual(player.tools("current")["power"], 45)

    def test_tools_fall_back_to_current_when_no_potential_columns(self):
        with TempCsv(RATINGS_CSV) as path:
            result = loading.load_csv(path)
        player = result.players[0]
        self.assertFalse(result.used_potential_tools)
        self.assertEqual(player.tools("potential"), player.current)

    def test_baseline_follows_mode(self):
        with TempCsv(RATINGS_CSV) as path:
            player = loading.load_csv(path).players[0]
        self.assertEqual(player.baseline("current"), 45)
        self.assertEqual(player.baseline("potential"), 60)

    def test_scale_override(self):
        with TempCsv(RATINGS_CSV) as path:
            result = loading.load_csv(path, scale="1-100")
        self.assertEqual(result.scale, "1-100")

    def test_pitcher_detection(self):
        with TempCsv(PITCHER_CSV) as path:
            player = loading.load_csv(path).players[0]
        self.assertTrue(player.is_pitcher)
        self.assertEqual(player.current["stuff"], 60)


if __name__ == "__main__":
    unittest.main()

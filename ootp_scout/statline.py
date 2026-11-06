"""Projected seasons, as a stat line a baseball reader already knows.

The projection produces counting stats and the three slash rates. The rest of
what you would read off a FanGraphs page - ISO, BB%, K%, K/9, BB/9, HR/9,
K/BB - are ratios of those, so they are derived here rather than stored. A
stored ratio is a second copy of the same fact, free to disagree with the
first.

Everything here takes and returns plain dicts. What the database holds is
whatever `fields` produced, so a line recorded by an older version is still
readable: a stat that was not stored comes back absent, not wrong.
"""

from __future__ import annotations

from .projection import LEAGUE_TOTALS, RUN_PA

# --- wOBA, and wRC+ from it -------------------------------------------------
#
# Linear weights in runs above an out. These are the one thing here that comes
# from outside: deriving them needs a run-expectancy matrix, which an OOTP
# export does not carry. They are the standard values for a modern run
# environment, and the scale that turns them into wOBA is derived below rather
# than copied, so everything downstream stays tied to the league the
# projections are actually built on.
RUNS_ABOVE_OUT = {
    "walks": 0.596,
    "hit_by_pitches": 0.621,
    "singles": 0.752,
    "doubles": 1.052,
    "triples": 1.322,
    "home_runs": 1.677,
}


def _raw_woba(events: dict[str, float], appearances: float) -> float | None:
    """Runs above an out per plate appearance, before scaling."""
    if not appearances:
        return None
    return sum(RUNS_ABOVE_OUT[name] * events.get(name, 0.0)
               for name in RUNS_ABOVE_OUT) / appearances


def _league() -> tuple[float, float]:
    """(league wOBA, wOBA scale), derived from the league the model uses.

    wOBA is defined to sit on the same scale as on-base percentage, so the
    scale is whatever makes the league's wOBA equal its OBP. Deriving it means
    the weights above can be revised without a second constant falling out of
    step with them - and it reproduces the published wOBA weights closely,
    which is the check that the derivation is the right one.
    """
    totals = LEAGUE_TOTALS
    singles = (totals["hits"] - totals["doubles"] - totals["triples"]
               - totals["home_runs"])
    appearances = (totals["at_bats"] + totals["walks"]
                   + totals["hit_by_pitches"])
    raw = _raw_woba({"walks": totals["walks"],
                     "hit_by_pitches": totals["hit_by_pitches"],
                     "singles": singles,
                     "doubles": totals["doubles"],
                     "triples": totals["triples"],
                     "home_runs": totals["home_runs"]}, appearances)
    on_base = (totals["hits"] + totals["walks"]
               + totals["hit_by_pitches"]) / appearances
    scale = on_base / raw
    return raw * scale, scale


LEAGUE_WOBA, WOBA_SCALE = _league()


def woba(stored: dict) -> float | None:
    """A hitter's wOBA, on the same scale as on-base percentage."""
    appearances = stored.get("plate_appearances")
    hits = stored.get("hits")
    if not appearances or hits is None:
        return None
    if "hit_by_pitches" not in stored:
        # A line recorded before hit-by-pitches were kept. Treating the field
        # as zero would put wOBA about six points low on every such player,
        # which is worse than leaving the column empty until a re-import.
        return None
    extra = (stored.get("doubles", 0.0) + stored.get("triples", 0.0)
             + stored.get("home_runs", 0.0))
    raw = _raw_woba({"walks": stored.get("walks", 0.0),
                     "hit_by_pitches": stored.get("hit_by_pitches", 0.0),
                     "singles": hits - extra,
                     "doubles": stored.get("doubles", 0.0),
                     "triples": stored.get("triples", 0.0),
                     "home_runs": stored.get("home_runs", 0.0)}, appearances)
    return None if raw is None else raw * WOBA_SCALE


def wrc_plus(stored: dict) -> float | None:
    """Runs created per plate appearance against the league, 100 average.

    Not the same number as OPS+, though the two track each other closely.
    OPS+ weights a walk and a single by how they move on-base and slugging;
    wRC+ weights them by the runs they actually produce.
    """
    mine = woba(stored)
    if mine is None:
        return None
    above_average = (mine - LEAGUE_WOBA) / WOBA_SCALE
    return 100 * (above_average + RUN_PA) / RUN_PA


# What gets stored, per role. Counting stats and the rates the model produces
# directly - no ratios of other stored numbers.
BATTER_FIELDS = (
    "games", "plate_appearances", "at_bats", "hits", "doubles", "triples",
    "home_runs", "walks", "hit_by_pitches", "strikeouts", "stolen_bases",
    "caught_stealing", "avg", "obp", "slg", "ops", "ops_plus", "babip", "war",
)
PITCHER_FIELDS = (
    "games", "starts", "innings", "batters_faced", "hits", "home_runs",
    "runs", "earned_runs", "walks", "hit_by_pitches", "strikeouts",
    "era", "whip", "fip", "era_plus", "babip", "war",
)

# How each stat is shown, as (key, heading, decimals). None means an integer.
# Rates that are conventionally written without a leading zero - .284, not
# 0.284 - are marked by a leading dot in the heading's own format below.
BATTER_DISPLAY = (
    ("games", "G", 0),
    ("plate_appearances", "PA", 0),
    ("at_bats", "AB", 0),
    ("hits", "H", 0),
    ("doubles", "2B", 0),
    ("triples", "3B", 0),
    ("home_runs", "HR", 0),
    ("walks", "BB", 0),
    ("strikeouts", "SO", 0),
    ("stolen_bases", "SB", 0),
    ("caught_stealing", "CS", 0),
    ("avg", "AVG", 3),
    ("obp", "OBP", 3),
    ("slg", "SLG", 3),
    ("ops", "OPS", 3),
    ("iso", "ISO", 3),
    ("woba", "wOBA", 3),
    ("babip", "BABIP", 3),
    ("bb_rate", "BB%", 1),
    ("k_rate", "K%", 1),
    ("ops_plus", "OPS+", 0),
    ("wrc_plus", "wRC+", 0),
    ("war", "WAR", 1),
)
PITCHER_DISPLAY = (
    ("games", "G", 0),
    ("starts", "GS", 0),
    ("innings", "IP", 1),
    ("hits", "H", 0),
    ("home_runs", "HR", 0),
    ("earned_runs", "ER", 0),
    ("walks", "BB", 0),
    ("strikeouts", "SO", 0),
    ("era", "ERA", 2),
    ("fip", "FIP", 2),
    ("whip", "WHIP", 2),
    ("k_rate", "K%", 1),
    ("bb_rate", "BB%", 1),
    ("k_9", "K/9", 1),
    ("bb_9", "BB/9", 1),
    ("hr_9", "HR/9", 1),
    ("k_bb", "K/BB", 2),
    ("babip", "BABIP", 3),
    ("era_plus", "ERA+", 0),
    ("war", "WAR", 1),
    ("war_200", "WAR/200", 1),
)

# Rates written without the leading zero, the way box scores do.
_DROP_LEADING_ZERO = {"avg", "obp", "slg", "ops", "iso", "babip", "woba"}
# Stats shown as a percentage of plate appearances.
_PERCENTAGES = {"bb_rate", "k_rate"}


def fields(line, is_pitcher: bool) -> dict[str, float]:
    """The part of a projected season worth storing, as a plain dict."""
    wanted = PITCHER_FIELDS if is_pitcher else BATTER_FIELDS
    out = {}
    for name in wanted:
        value = getattr(line, name, None)
        if value is not None:
            out[name] = round(float(value), 4)
    return out


def _ratio(top: float | None, bottom: float | None) -> float | None:
    """A ratio, or None when the denominator makes it meaningless."""
    if top is None or not bottom:
        return None
    return top / bottom


def derive(stored: dict, is_pitcher: bool) -> dict[str, float]:
    """The stored line plus the ratios a reader expects to see with it."""
    if not stored:
        return {}
    out = dict(stored)
    if is_pitcher:
        innings = stored.get("innings")
        out["k_9"] = _ratio(stored.get("strikeouts"), innings)
        out["bb_9"] = _ratio(stored.get("walks"), innings)
        out["hr_9"] = _ratio(stored.get("home_runs"), innings)
        for key in ("k_9", "bb_9", "hr_9"):
            if out[key] is not None:
                out[key] *= 9
        out["k_bb"] = _ratio(stored.get("strikeouts"), stored.get("walks"))
        # Per batter faced, which is how strikeout and walk rates are read -
        # per nine confounds them with how long he stays in the game.
        faced = stored.get("batters_faced")
        out["k_rate"] = _ratio(stored.get("strikeouts"), faced)
        out["bb_rate"] = _ratio(stored.get("walks"), faced)
        for key in ("k_rate", "bb_rate"):
            if out[key] is not None:
                out[key] *= 100
        # WAR is exactly linear in innings here, so dividing it out separates
        # how good he is from how much of him there is. Two arms at 2.0 WAR
        # are not the same pitcher if one took 200 innings and the other 70.
        out["war_200"] = _ratio(stored.get("war"), innings)
        if out["war_200"] is not None:
            out["war_200"] *= 200
    else:
        appearances = stored.get("plate_appearances")
        out["bb_rate"] = _ratio(stored.get("walks"), appearances)
        out["k_rate"] = _ratio(stored.get("strikeouts"), appearances)
        for key in ("bb_rate", "k_rate"):
            if out[key] is not None:
                out[key] *= 100
        slug, avg = stored.get("slg"), stored.get("avg")
        out["iso"] = None if slug is None or avg is None else slug - avg
        out["woba"] = woba(stored)
        out["wrc_plus"] = wrc_plus(stored)
    return {k: v for k, v in out.items() if v is not None}


def format_value(key: str, value: float | None, decimals: int) -> str:
    """One stat, written the way baseball writes it."""
    if value is None:
        return ""
    if decimals == 0:
        return f"{value:,.0f}"
    text = f"{value:.{decimals}f}"
    if key in _DROP_LEADING_ZERO and text.startswith("0."):
        text = text[1:]
    if key in _PERCENTAGES:
        text += "%"
    return text


def display(stored: dict, is_pitcher: bool) -> list[tuple[str, str]]:
    """The whole line as (heading, value) pairs, in reading order."""
    full = derive(stored, is_pitcher)
    if not full:
        return []
    layout = PITCHER_DISPLAY if is_pitcher else BATTER_DISPLAY
    return [(heading, format_value(key, full.get(key), decimals))
            for key, heading, decimals in layout
            if full.get(key) is not None]


def summary(stored: dict, is_pitcher: bool) -> str:
    """One line of the stats that matter most, for a status bar or a list."""
    full = derive(stored, is_pitcher)
    if not full:
        return ""
    if is_pitcher:
        picks = (("innings", "IP", 1), ("era", "ERA", 2), ("fip", "FIP", 2),
                 ("k_rate", "K%", 1), ("bb_rate", "BB%", 1),
                 ("war_200", "WAR/200", 1))
    else:
        picks = (("plate_appearances", "PA", 0), ("avg", "AVG", 3),
                 ("obp", "OBP", 3), ("slg", "SLG", 3), ("woba", "wOBA", 3),
                 ("wrc_plus", "wRC+", 0))
    return "  ".join(
        f"{heading} {format_value(key, full[key], decimals)}"
        for key, heading, decimals in picks if full.get(key) is not None)


def slash(stored: dict) -> str:
    """A hitter's AVG/OBP/SLG, the way it is always written."""
    parts = [format_value(key, stored.get(key), 3)
             for key in ("avg", "obp", "slg")]
    return "/".join(parts) if all(parts) else ""

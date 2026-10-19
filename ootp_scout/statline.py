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

# What gets stored, per role. Counting stats and the rates the model produces
# directly - no ratios of other stored numbers.
BATTER_FIELDS = (
    "games", "plate_appearances", "at_bats", "hits", "doubles", "triples",
    "home_runs", "walks", "strikeouts", "stolen_bases", "caught_stealing",
    "avg", "obp", "slg", "ops", "ops_plus", "babip", "war",
)
PITCHER_FIELDS = (
    "games", "starts", "innings", "hits", "home_runs", "runs", "earned_runs",
    "walks", "strikeouts", "era", "whip", "fip", "era_plus", "babip", "war",
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
    ("babip", "BABIP", 3),
    ("bb_rate", "BB%", 1),
    ("k_rate", "K%", 1),
    ("ops_plus", "OPS+", 0),
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
    ("k_9", "K/9", 1),
    ("bb_9", "BB/9", 1),
    ("hr_9", "HR/9", 1),
    ("k_bb", "K/BB", 2),
    ("babip", "BABIP", 3),
    ("era_plus", "ERA+", 0),
    ("war", "WAR", 1),
)

# Rates written without the leading zero, the way box scores do.
_DROP_LEADING_ZERO = {"avg", "obp", "slg", "ops", "iso", "babip"}
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
    else:
        appearances = stored.get("plate_appearances")
        out["bb_rate"] = _ratio(stored.get("walks"), appearances)
        out["k_rate"] = _ratio(stored.get("strikeouts"), appearances)
        for key in ("bb_rate", "k_rate"):
            if out[key] is not None:
                out[key] *= 100
        slug, avg = stored.get("slg"), stored.get("avg")
        out["iso"] = None if slug is None or avg is None else slug - avg
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
                 ("whip", "WHIP", 2), ("k_9", "K/9", 1))
    else:
        picks = (("plate_appearances", "PA", 0), ("avg", "AVG", 3),
                 ("obp", "OBP", 3), ("slg", "SLG", 3), ("home_runs", "HR", 0))
    return "  ".join(
        f"{heading} {format_value(key, full[key], decimals)}"
        for key, heading, decimals in picks if full.get(key) is not None)


def slash(stored: dict) -> str:
    """A hitter's AVG/OBP/SLG, the way it is always written."""
    parts = [format_value(key, stored.get(key), 3)
             for key in ("avg", "obp", "slg")]
    return "/".join(parts) if all(parts) else ""

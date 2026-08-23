"""Ratings to projected stats and WAR, in Python.

A port of the projection maths from ootpcalculator.com, whose source Daniel
C. Seguin publishes under the MIT licence at

    https://github.com/danseguin23/ootp-calculator

Everything here - the lookup tables, the intermediate estimators, the league
totals, the WAR constants - is his work, translated rather than invented. The
port exists so the tool can produce projections without a browser round trip;
it is not an attempt to improve on the model, and where the two disagree the
site is right and this is wrong.

The port is checked against the site rather than trusted: the fixtures in
tests/ are real exports paired with the projections the live site returned for
them, and the tests assert agreement to a tolerance.

The season shape - 150 games, 550 at-bats, 60 pitching appearances - is
reproduced unchanged so that comparisons with the site stay like for like.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- scale conversion --------------------------------------------------------

SCALE_BOUNDS = {"1 to 5": (1, 5), "2 to 8": (2, 8), "1 to 10": (1, 10),
                "1 to 20": (1, 20), "20 to 80": (20, 80), "1 to 100": (1, 100)}


def convert_rating(scale: str, rating: float, stuff: bool = False) -> int:
    """Put a displayed rating on the internal 1-250 scale."""
    low, high = SCALE_BOUNDS[scale]
    converted = (rating - low) * 200 / (high - low)
    ceiling = 350 if stuff else 250
    if converted < 0 or converted > ceiling:
        raise ValueError(f"rating {rating} is outside the {scale} scale")
    return round(converted)


def convert_250_to_600(value: float) -> float:
    """The 1-250 scale stretched onto the 1-600 one the lookups are built on."""
    points = [(0, 100), (100, 400), (200, 500), (250, 600)]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if x1 <= value <= x2:
            slope = (y2 - y1) / (x2 - x1)
            return y1 - slope * x1 + slope * value
    return value


def lookup(table: list[tuple[float, float]], rating: float) -> float:
    """Piecewise-linear read of a lookup table, flat past the last point."""
    for (x1, y1), (x2, y2) in zip(table, table[1:]):
        if x1 <= rating <= x2:
            slope = (y2 - y1) / (x2 - x1)
            return y1 - slope * x1 + slope * rating
    return table[-1][1]


# --- constants, all from the calculator --------------------------------------

INTERMEDIATE = {
    "babip": (1.4, -0.697, 29.7),
    "aggressiveness": (0.4934, 0.541, -41.3),
    "pbabip": (0.379, 5.1, 51.9),
    "hra": (1.07, -3.08, -0.0999),
}

FORMULA_BATTING = {
    "h3": {"slope": (0.000844, 0.000567), "intercept": (-0.00906, 0.0187)},
    "sba": {"slope": (0.000947, 0.00145), "intercept": (-0.00904, -0.0598)},
    "sb": {"slope": (0.00671, 0.00221), "intercept": (-0.00988, 0.44)},
    "zr": {"slope": (0.24, 0.12), "intercept": (-26, -14)},
}

FORMULA_PITCHING = {
    "gssp": {"slope": (0.01, 0), "intercept": (0, 1)},
    "gsrp": {"slope": (0, 0.005), "intercept": (0, -0.5)},
    "absp": {"slope": (0.0275, 0.0216), "intercept": (7.32, 7.91)},
    "abrp": {"slope": (0.0339, 0.0339), "intercept": (3.27, 3.27)},
    "wsb": {"slope": (-0.012, -0.006), "intercept": (1.2, 0.6)},
}

LOOKUP_BATTING = {
    "babip": [(0, 0.15), (150, 0.225), (300, 0.27), (400, 0.3), (500, 0.36),
              (600, 0.45)],
    "so": [(0, 350), (150, 200), (300, 155), (400, 110), (500, 50), (600, 20)],
    "gap": [(0, 0), (150, 0.05), (300, 0.15), (400, 0.2), (500, 0.3),
            (600, 0.6)],
    "hr": [(0, 0), (150, 2), (300, 8), (400, 15), (500, 35), (600, 75)],
    "bb": [(0, 5), (150, 10), (300, 30), (400, 50), (500, 85), (600, 175)],
}

LOOKUP_PITCHING = {
    "so": [(0, 5), (150, 35), (300, 85), (400, 110), (500, 155), (600, 245)],
    "bb": [(0, 175), (150, 100), (300, 70), (400, 45), (500, 25), (600, 5)],
    "hr": [(0, 60), (150, 35), (300, 20), (400, 12), (500, 6), (600, 2)],
    "babip": [(0, 0.32), (100, 0.3), (150, 0.29), (250, 0.275)],
}

# League-average displayed ratings are not always 50.
AVERAGE_BATTING = {"avoidKs": 51, "babip": 52, "gap": 51, "power": 51,
                   "eye": 49}
AVERAGE_PITCHING = {"stuff": 48, "babip": 50, "hra": 48, "control": 50}

GROUND_FLY = {"EX GB": 0, "GB": 1, "NEU": 2, "FB": 3, "EX FB": 4}

POSITION_RUNS = {"SP": -14, "RP": -14, "CL": -14, "DH": -14, "C": 10,
                 "1B": -10, "2B": 2, "3B": 2, "SS": 6, "LF": -6, "CF": 2,
                 "RF": -6}

LEAGUE_TOTALS = {"at_bats": 163664, "hits": 40138, "doubles": 7745,
                 "triples": 628, "home_runs": 5650, "walks": 14823,
                 "hit_by_pitches": 1928, "strikeouts": 40645}

_T = LEAGUE_TOTALS
LEAGUE = {
    "babip": (_T["hits"] - _T["home_runs"])
             / (_T["at_bats"] - _T["home_runs"] - _T["strikeouts"]),
    "so": _T["strikeouts"] / _T["at_bats"] * 550,
    "gap": (_T["doubles"] + _T["triples"]) / (_T["hits"] - _T["home_runs"]),
    "hr": _T["home_runs"] / _T["at_bats"] * 550,
    "bb": _T["walks"] / _T["at_bats"] * 550,
    "obp": (_T["hits"] + _T["walks"] + _T["hit_by_pitches"])
           / (_T["at_bats"] + _T["walks"] + _T["hit_by_pitches"]),
    "slg": (_T["hits"] + _T["doubles"] + 2 * _T["triples"]
            + 3 * _T["home_runs"]) / _T["at_bats"],
}

RUN_PA, RUN_SB, RUN_CS, RUN_OB, WAR_PA = 0.118, 0.2, -0.41, -0.0072, 0.0034
RS_FACTOR, ADD_OUTS = 1.235, 10
LG_ERA, LG_RA9, C_FIP, WAR_IP = 4.15, 4.45, 3.13, 0.004

HBP_PER_550 = _T["hit_by_pitches"] / _T["at_bats"] * 550


@dataclass(frozen=True)
class Park:
    """Park factors. The calculator's "No Team" is neutral in every direction."""

    avg_overall: float = 1.0
    avg_lhb: float = 1.0
    avg_rhb: float = 1.0
    doubles: float = 1.0
    triples: float = 1.0
    hr_overall: float = 1.0
    hr_lhb: float = 1.0
    hr_rhb: float = 1.0
    obp: float = 1.0
    slg: float = 1.0
    era: float = 1.0
    fip: float = 1.0


NEUTRAL_PARK = Park()


def adjusted_rate(rating_1to250: float, league_display_rating: float,
                  league_average: float, table: list[tuple[float, float]],
                  per_550: bool = False, keep_1to250: bool = False) -> float:
    """Read the lookup, then re-centre it on the league's actual average.

    The lookup gives a raw rate for a rating. The league's average player is
    not necessarily a 50, so the raw rate is blended toward the real league
    average by an odds-ratio adjustment. Kept verbatim from the calculator,
    since reproducing its output is the whole point.
    """
    league_1to250 = convert_rating("20 to 80", league_display_rating)
    if keep_1to250:
        rate = rating_1to250
        at_average = lookup(table, league_1to250)
    else:
        rate = convert_250_to_600(rating_1to250)
        at_average = lookup(table, convert_250_to_600(league_1to250))
    raw = lookup(table, rate)
    if per_550:
        raw /= 550
        league_average /= 550
        at_average /= 550
    return ((raw * league_average * (1 - at_average))
            / (raw * league_average - at_average * raw
               - at_average * league_average + at_average))


@dataclass
class BatterLine:
    """A projected season for one hitter."""

    games: float = 150.0
    plate_appearances: float = 0.0
    at_bats: float = 0.0
    hits: float = 0.0
    doubles: float = 0.0
    triples: float = 0.0
    home_runs: float = 0.0
    walks: float = 0.0
    strikeouts: float = 0.0
    stolen_bases: float = 0.0
    caught_stealing: float = 0.0
    avg: float = 0.0
    obp: float = 0.0
    slg: float = 0.0
    ops: float = 0.0
    ops_plus: float = 0.0
    babip: float = 0.0
    war: float = 0.0


def project_batter(*, contact: float, gap: float, power: float, eye: float,
                   avoid_ks: float, speed: float, stealing: float,
                   defense: float | None, position: str, bats: str = "R",
                   babip_input: float | None = None,
                   steal_tendency: float | None = None,
                   park: Park = NEUTRAL_PARK) -> BatterLine:
    """Project a hitter's season. Ratings are on the internal 1-250 scale."""
    if bats == "R":
        park_avg, park_hr = park.avg_rhb, park.hr_rhb
    elif bats == "L":
        park_avg, park_hr = park.avg_lhb, park.hr_lhb
    elif bats == "S":
        park_avg = (2 * park.avg_lhb + park.avg_rhb) / 3
        park_hr = (2 * park.hr_lhb + park.hr_rhb) / 3
    else:
        park_avg, park_hr = park.avg_overall, park.hr_overall

    c = INTERMEDIATE["babip"]
    xbabip = (babip_input if babip_input is not None
              else max(contact * c[0] + avoid_ks * c[1] + c[2], 0))
    c = INTERMEDIATE["aggressiveness"]
    xagg = (steal_tendency if steal_tendency is not None
            else max(speed * c[0] + stealing * c[1] + c[2], 0))

    h3_index = int(speed > 100)
    sb_index = int(stealing > 100)
    sba_index = int(xagg > 100)
    has_defense = defense is not None
    zr_index = int(defense > 100) if has_defense else 0

    babip = adjusted_rate(xbabip, AVERAGE_BATTING["babip"], LEAGUE["babip"],
                          LOOKUP_BATTING["babip"])
    so_adj = adjusted_rate(avoid_ks, AVERAGE_BATTING["avoidKs"], LEAGUE["so"],
                           LOOKUP_BATTING["so"], per_550=True)
    gap_adj = adjusted_rate(gap, AVERAGE_BATTING["gap"], LEAGUE["gap"],
                            LOOKUP_BATTING["gap"])
    hr_adj = adjusted_rate(power, AVERAGE_BATTING["power"], LEAGUE["hr"],
                           LOOKUP_BATTING["hr"], per_550=True)
    bb_adj = adjusted_rate(eye, AVERAGE_BATTING["eye"], LEAGUE["bb"],
                           LOOKUP_BATTING["bb"], per_550=True)

    f = FORMULA_BATTING
    h3_pct = speed * f["h3"]["slope"][h3_index] + f["h3"]["intercept"][h3_index]
    sba_pct = max(xagg * f["sba"]["slope"][sba_index]
                  + f["sba"]["intercept"][sba_index], 0)
    sb_pct = max(stealing * f["sb"]["slope"][sb_index]
                 + f["sb"]["intercept"][sb_index], 0)
    zr = (defense * f["zr"]["slope"][zr_index] + f["zr"]["intercept"][zr_index]
          if has_defense else 0.0)

    hr = hr_adj * 550 * park_hr
    bb = bb_adj * 550
    so = so_adj * 550
    hits = (babip * (550 - hr - so) + hr) * park_avg
    gap_hits = gap_adj * (hits - hr)
    doubles = gap_hits * (1 - h3_pct) * park.doubles
    triples = gap_hits * h3_pct * park.triples
    sba = sba_pct * (hits - doubles - triples - hr + bb)
    stolen = sba * sb_pct
    caught = sba * (1 - sb_pct)
    plate = 550 + bb + HBP_PER_550

    avg = hits / 550
    obp = (hits + bb + HBP_PER_550) / plate
    slg = (hits + doubles + 2 * triples + 3 * hr) / 550
    ops_plus = (obp / LEAGUE["obp"] / park.obp
                + slg / LEAGUE["slg"] / park.slg - 1) * 100

    bat = RUN_PA * (ops_plus / 100 - 1) * plate
    bsr = (RUN_SB * stolen + RUN_CS * caught
           + RUN_OB * (hits - doubles - triples - hr + bb))
    war = (bat + bsr + zr + POSITION_RUNS.get(position, 0)) / 10 + WAR_PA * plate

    games = 150.0
    projected_pa = 4 * games
    at_bats = projected_pa / plate * 550
    scale = at_bats / 550
    return BatterLine(
        games=games, plate_appearances=projected_pa, at_bats=at_bats,
        hits=hits * scale, doubles=doubles * scale, triples=triples * scale,
        home_runs=hr * scale, walks=bb * scale, strikeouts=so * scale,
        stolen_bases=stolen * scale, caught_stealing=caught * scale,
        avg=avg, obp=obp, slg=slg, ops=obp + slg, ops_plus=ops_plus,
        babip=babip, war=war * scale)


@dataclass
class PitcherLine:
    """A projected season for one pitcher."""

    games: float = 0.0
    starts: float = 0.0
    innings: float = 0.0
    hits: float = 0.0
    home_runs: float = 0.0
    runs: float = 0.0
    earned_runs: float = 0.0
    walks: float = 0.0
    strikeouts: float = 0.0
    era: float = 0.0
    whip: float = 0.0
    fip: float = 0.0
    era_plus: float = 0.0
    babip: float = 0.0
    war: float = 0.0


def project_pitcher(*, stuff: float, movement: float, control: float,
                    stamina: float, hold: float, ground_fly: str,
                    position: str, hra_input: float | None = None,
                    babip_input: float | None = None,
                    park: Park = NEUTRAL_PARK) -> PitcherLine:
    """Project a pitcher's season. Ratings are on the internal 1-250 scale."""
    gf = GROUND_FLY.get((ground_fly or "NEU").strip().upper(), 2)

    c = INTERMEDIATE["pbabip"]
    xbabip = (babip_input if babip_input is not None
              else max(movement * c[0] + gf * c[1] + c[2], 0))
    c = INTERMEDIATE["hra"]
    xhra = (hra_input if hra_input is not None
            else max(movement * c[0] + gf * c[1] + c[2], 0))

    babip = adjusted_rate(xbabip, AVERAGE_PITCHING["babip"], LEAGUE["babip"],
                          LOOKUP_PITCHING["babip"], keep_1to250=True)
    hr_adj = adjusted_rate(xhra, AVERAGE_PITCHING["hra"], LEAGUE["hr"],
                           LOOKUP_PITCHING["hr"], per_550=True)
    so_adj = adjusted_rate(stuff, AVERAGE_PITCHING["stuff"], LEAGUE["so"],
                           LOOKUP_PITCHING["so"], per_550=True)
    bb_adj = adjusted_rate(control, AVERAGE_PITCHING["control"], LEAGUE["bb"],
                           LOOKUP_PITCHING["bb"], per_550=True)

    ab_index = int(stamina > 100)
    wsb_index = int(hold > 100)
    f = FORMULA_PITCHING
    key_ab, key_gs = ("absp", "gssp") if position == "SP" else ("abrp", "gsrp")
    at_bats = (stamina * f[key_ab]["slope"][ab_index]
               + f[key_ab]["intercept"][ab_index])
    starts_ratio = (stamina * f[key_gs]["slope"][ab_index]
                    + f[key_gs]["intercept"][ab_index])
    games = 60 * (1 - starts_ratio / (1 + starts_ratio))
    at_bats *= 60

    so = so_adj * 550
    hr = hr_adj * 550 * park.hr_overall
    bb = bb_adj * 550
    wsb = hold * f["wsb"]["slope"][wsb_index] + f["wsb"]["intercept"][wsb_index]
    hits = babip * (550 - hr - so) + hr
    avg = hits / 550
    innings = (550 - hits + ADD_OUTS) / 3
    runs = avg * RS_FACTOR * (hits - hr + bb + HBP_PER_550) + hr + wsb
    earned = LG_ERA / LG_RA9 * runs
    era = earned / innings * 9
    fip = (13 * hr + 3 * (bb + HBP_PER_550) - 2 * so) / innings + C_FIP

    scale = at_bats / 550
    line = PitcherLine(
        games=games, starts=60 - games, innings=innings * scale,
        hits=hits * scale, home_runs=hr * scale, runs=runs * scale,
        earned_runs=earned * scale, walks=bb * scale, strikeouts=so * scale,
        era=era, whip=(bb + hits) / innings, fip=fip,
        era_plus=LG_ERA / (era / park.era) * 100, babip=babip)

    # WAR, FanGraphs style: FIP measured against the league, converted at a
    # runs-per-win rate that itself depends on how deep into games he goes.
    fipr9 = fip / park.fip + (LG_RA9 - LG_ERA)
    innings_per_game = line.innings / line.games if line.games else 0.0
    runs_per_win = (((18 - innings_per_game) * LG_RA9
                     + innings_per_game * fipr9) / 18 + 2) * 1.5
    start_share = line.starts / line.games if line.games else 0.0
    replacement = 0.03 * (1 - start_share) + 0.12 * start_share
    line.war = (((LG_RA9 - fipr9) / runs_per_win + replacement)
                * line.innings / 9 + WAR_IP * line.innings)
    return line


# --- projecting a whole export ----------------------------------------------

@dataclass
class Projected:
    """What the rest of the tool needs back: a WAR, plus rWAR's inputs."""

    name: str
    war: float
    innings: float | None = None
    runs: float | None = None


def _number(raw: str) -> float | None:
    text = (raw or "").strip()
    if not text or text in {"-", "--", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def project_rows(rows, view, scale: str,
                 park: Park = NEUTRAL_PARK) -> tuple[list[Projected],
                                                     list[tuple[str, str]]]:
    """Project every row of a parsed export.

    Returns the projections and a list of (player, reason) for rows that could
    not be projected, so a bad cell is reported rather than silently dropped.
    """
    columns = view.projection_columns or {}
    projected: list[Projected] = []
    problems: list[tuple[str, str]] = []

    for row in rows:
        values = row.values

        def rating(field: str, stuff: bool = False):
            column = columns.get(field)
            raw = values.get(column, "") if column else ""
            number = _number(raw)
            if number is None:
                return None
            return convert_rating(scale, number, stuff)

        try:
            if view.role == "batter":
                required = ("contact", "gap", "power", "eye", "avoid_ks",
                            "speed", "stealing")
                inputs = {name: rating(name) for name in required}
                missing = [n for n, v in inputs.items() if v is None]
                if missing:
                    problems.append((row.name, "missing " + ", ".join(missing)))
                    continue
                line = project_batter(
                    defense=rating("defense"), position=row.position,
                    bats=(values.get("B") or "R").strip() or "R",
                    babip_input=rating("babip_input"),
                    steal_tendency=rating("steal_tendency"),
                    park=park, **inputs)
                projected.append(Projected(name=row.name, war=line.war))
            else:
                stuff = rating("stuff", stuff=True)
                inputs = {name: rating(name) for name in
                          ("movement", "control", "stamina", "hold")}
                missing = ([] if stuff is not None else ["stuff"]) + [
                    n for n, v in inputs.items() if v is None]
                if missing:
                    problems.append((row.name, "missing " + ", ".join(missing)))
                    continue
                ground_fly = (values.get(columns.get("ground_fly", ""), "")
                              or "").strip()
                if ground_fly.upper() not in GROUND_FLY:
                    # The site accepts this and returns nonsense - a numeric
                    # G/F produced 4 home runs and 9.1 WAR where the same arm
                    # with NEU produced 15 and 6.7. Refuse rather than repeat.
                    problems.append((row.name,
                                     f"G/F is {ground_fly!r}; expected one of "
                                     + ", ".join(sorted(GROUND_FLY))))
                    continue
                line = project_pitcher(
                    stuff=stuff, ground_fly=ground_fly, position=row.position,
                    hra_input=rating("hra_input"),
                    babip_input=rating("babip_input"), park=park, **inputs)
                projected.append(Projected(name=row.name, war=line.war,
                                           innings=line.innings,
                                           runs=line.runs))
        except (ValueError, KeyError) as error:
            problems.append((row.name, str(error)))
    return projected, problems

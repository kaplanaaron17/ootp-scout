"""Column-name normalization and rating-scale handling for OOTP exports.

OOTP lets the user build their own export views, so header names are not stable
between one person's export and the next ("Con" vs "Contact" vs "Contact Rating").
Everything downstream works on the canonical names defined here.
"""

from __future__ import annotations

import re

# --- canonical tool names ---------------------------------------------------

HITTER_TOOLS = ("contact", "gap", "power", "eye", "avoid_k")
HITTER_EXTRAS = ("speed", "stealing", "defense", "arm", "range")
PITCHER_TOOLS = ("stuff", "movement", "control")
PITCHER_EXTRAS = ("stamina",)

ALL_TOOLS = HITTER_TOOLS + HITTER_EXTRAS + PITCHER_TOOLS + PITCHER_EXTRAS

# Identity columns we carry through to the report untouched.
META_FIELDS = ("name", "position", "age", "nationality", "scouting_accuracy",
               "signability", "demand", "team", "player_id", "bats_throws")

# --- alias table ------------------------------------------------------------
# Keys are already normalized (see normalize_header).

_ALIASES: dict[str, str] = {
    # identity
    "name": "name", "player": "name", "player name": "name",
    "pos": "position", "position": "position",
    "age": "age",
    "nat": "nationality", "nation": "nationality", "nationality": "nationality",
    "sctacc": "scouting_accuracy", "sct acc": "scouting_accuracy",
    "scouting accuracy": "scouting_accuracy", "scout accuracy": "scouting_accuracy",
    "sign": "signability", "signability": "signability",
    "dem": "demand", "demand": "demand",
    "org": "team", "team": "team",
    "id": "player_id", "player id": "player_id",
    "bt": "bats_throws", "b t": "bats_throws",

    # hitting
    "con": "contact", "contact": "contact", "ba": "contact",
    "gap": "gap", "gap power": "gap",
    "pow": "power", "power": "power", "hr": "power",
    "eye": "eye", "bb": "eye", "plate discipline": "eye",
    "ks": "avoid_k", "k": "avoid_k", "avk": "avoid_k",
    "avoid k": "avoid_k", "avoid ks": "avoid_k", "avoid strikeouts": "avoid_k",

    # running / defense
    "spe": "speed", "spd": "speed", "speed": "speed",
    "ste": "stealing", "stealing": "stealing", "steal": "stealing",
    "df": "defense", "def": "defense", "defense": "defense", "fielding": "defense",
    "arm": "arm", "of arm": "arm", "c arm": "arm",
    "range": "range", "ran": "range",

    # pitching
    "stu": "stuff", "stuff": "stuff",
    "mov": "movement", "movement": "movement", "hra": "movement",
    "ctl": "control", "control": "control", "cmd": "control",
    "sta": "stamina", "stamina": "stamina", "endurance": "stamina",
}

# Tokens marking a column as a *potential* rather than *current* rating.
_POTENTIAL_MARKERS = ("pot", "potential", "ceiling")

# Bare overall columns, handled before tool lookup so that a lone "POT" is read
# as overall-potential and never as a potential-flavored tool rating.
_OVERALL_CURRENT = {"ovr", "overall", "overall rating", "cur", "current"}
_OVERALL_POTENTIAL = {"pot", "potential", "overall potential", "pot ovr"}


def normalize_header(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = raw.strip().lower()
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class ColumnRole:
    """What a single CSV column means."""

    __slots__ = ("kind", "field", "is_potential")

    def __init__(self, kind: str, field: str, is_potential: bool = False):
        # kind: "meta" | "overall" | "tool" | "ignored"
        self.kind = kind
        self.field = field
        self.is_potential = is_potential

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        suffix = " (potential)" if self.is_potential else ""
        return f"<{self.kind}:{self.field}{suffix}>"

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, ColumnRole)
                and (self.kind, self.field, self.is_potential)
                == (other.kind, other.field, other.is_potential))


def classify_header(raw: str) -> ColumnRole:
    """Map one raw CSV header to its role."""
    norm = normalize_header(raw)
    if not norm:
        return ColumnRole("ignored", raw)

    if norm in _OVERALL_POTENTIAL:
        return ColumnRole("overall", "overall", is_potential=True)
    if norm in _OVERALL_CURRENT:
        return ColumnRole("overall", "overall", is_potential=False)

    # Strip a leading/trailing potential marker, e.g. "pot contact",
    # "contact potential". A marker in the middle is not a convention OOTP uses.
    tokens = norm.split()
    is_potential = False
    if len(tokens) > 1 and tokens[0] in _POTENTIAL_MARKERS:
        is_potential, tokens = True, tokens[1:]
    elif len(tokens) > 1 and tokens[-1] in _POTENTIAL_MARKERS:
        is_potential, tokens = True, tokens[:-1]

    key = " ".join(tokens)
    if key in _ALIASES:
        field = _ALIASES[key]
        kind = "meta" if field in META_FIELDS else "tool"
        if kind == "meta" and is_potential:
            # e.g. a stray "potential name" column - not meaningful.
            return ColumnRole("ignored", raw)
        return ColumnRole(kind, field, is_potential)

    return ColumnRole("ignored", raw)


# --- rating scales ----------------------------------------------------------

SCALE_20_80 = "20-80"
SCALE_1_100 = "1-100"


def detect_scale(values: list[float]) -> str:
    """Infer which rating scale an export uses.

    OOTP can display ratings as 20-80, 1-100, 1-20 or stars. Only the two
    numeric scales that carry enough resolution to project from are supported;
    anything else raises so the caller can tell the user to change the setting
    rather than silently producing nonsense.
    """
    if not values:
        raise ValueError("no rating values found - check that the export "
                         "actually contains ratings columns")
    top = max(values)
    bottom = min(values)
    if top > 100 or bottom < 0:
        raise ValueError(f"ratings span {bottom}-{top}, which matches no known "
                         "OOTP scale")
    if top > 80:
        return SCALE_1_100
    if top <= 20:
        raise ValueError(
            f"ratings top out at {top}; this looks like OOTP's 1-20 or star "
            "scale. Switch the game to the 20-80 or 1-100 rating scale and "
            "re-export - the coarse scales lose too much resolution to project "
            "from.")
    return SCALE_20_80


def to_unit(value: float, scale: str) -> float:
    """Map a rating onto 0.0-1.0 so the model is scale-independent."""
    if scale == SCALE_20_80:
        return (value - 20.0) / 60.0
    if scale == SCALE_1_100:
        return (value - 1.0) / 99.0
    raise ValueError(f"unknown scale {scale!r}")

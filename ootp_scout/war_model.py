"""Turn ratings into a WAR projection.

READ THIS BEFORE TRUSTING A NUMBER FROM HERE
--------------------------------------------
`ProvisionalModel` is a placeholder. Its coefficients are hand-set to be
*monotone and plausibly weighted*, not calibrated against OOTP's engine. It is
here so the pipeline runs end to end and so the flagging logic can be tested;
it is not a substitute for a real ratings-to-WAR calculator.

Two ways to replace it, both already supported:

1. `ExternalWarModel` - if your CSV already carries a WAR column (paste the
   calculator's output into the export, or export the game's own projection),
   pass `--war-column` and this module does no math at all.
2. Write a new class with a `project(player, tools, scale) -> Projection`
   method once the real calculator's formula is known, and register it below.

The flagging in `flagging.py` is independent of which model is used, so
swapping the model does not disturb anything downstream.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import ratings as R
from .loading import Player

# Weights are in "wins away from an average regular", applied to a rating
# normalized to 0.0-1.0 and centered at 0.5. A tool at the very top of the
# scale contributes +w/2; at the very bottom, -w/2.
_HITTER_WEIGHTS = {
    "contact": 3.0,
    "power": 3.4,
    "eye": 2.0,
    "gap": 1.2,
    "avoid_k": 1.0,
    "speed": 0.8,
    "stealing": 0.3,
    "defense": 2.2,
    "arm": 0.6,
    "range": 1.4,
}

_PITCHER_WEIGHTS = {
    "stuff": 4.0,
    "movement": 2.6,
    "control": 3.0,
    "stamina": 1.6,
}

# Positional value, in wins, relative to an average defensive position.
_POSITION_ADJUSTMENT = {
    "C": 1.0, "SS": 0.7, "2B": 0.3, "3B": 0.3, "CF": 0.3,
    "LF": -0.7, "RF": -0.7, "1B": -1.0, "DH": -1.5,
    "SP": 0.0, "RP": -0.8, "CL": -0.6,
}

# An average everyday regular is worth roughly this much above replacement.
_REPLACEMENT_BASELINE = 2.0


@dataclass(frozen=True)
class Projection:
    war: float
    components: dict[str, float]
    missing: tuple[str, ...]


class ExternalWarModel:
    """Use a WAR value already present in the CSV."""

    name = "external"

    def __init__(self, column: str):
        self.column = column

    def project(self, player: Player, tools: dict[str, float], scale: str) -> Projection:
        raw = player.meta.get("_war_column_value", "")
        try:
            war = float(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError(
                f"{player.name}: column {self.column!r} holds {raw!r}, not a number")
        return Projection(war=war, components={}, missing=())


class ProvisionalModel:
    """Transparent linear placeholder - see the module docstring."""

    name = "provisional"

    def __init__(self, replacement_baseline: float = _REPLACEMENT_BASELINE):
        self.replacement_baseline = replacement_baseline

    def project(self, player: Player, tools: dict[str, float], scale: str) -> Projection:
        weights = _PITCHER_WEIGHTS if player.is_pitcher else _HITTER_WEIGHTS
        components: dict[str, float] = {}
        missing: list[str] = []

        for tool, weight in weights.items():
            if tool not in tools:
                missing.append(tool)
                continue
            unit = R.to_unit(tools[tool], scale)
            components[tool] = weight * (unit - 0.5)

        position_adjustment = _POSITION_ADJUSTMENT.get(player.position.upper(), 0.0)
        components["position"] = position_adjustment

        war = self.replacement_baseline + sum(components.values())
        return Projection(war=war, components=components, missing=tuple(missing))


def required_tools(player: Player) -> set[str]:
    """The tools that carry most of the weight for this player's role."""
    return {"stuff", "control"} if player.is_pitcher else {"contact", "power"}

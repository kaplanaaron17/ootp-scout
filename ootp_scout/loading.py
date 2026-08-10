"""Read an OOTP CSV export into Player records."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field

from . import ratings as R


@dataclass
class Player:
    name: str
    position: str
    meta: dict[str, str] = field(default_factory=dict)
    current: dict[str, float] = field(default_factory=dict)
    potential: dict[str, float] = field(default_factory=dict)
    overall_current: float | None = None
    overall_potential: float | None = None
    row_number: int = 0

    def tools(self, mode: str) -> dict[str, float]:
        """Ratings for the requested mode.

        Falls back to current ratings when an export carries only one set of
        tool columns, which is the common case: OOTP's default views show
        current ratings plus a single overall-potential number. The caller is
        told about the fallback so the report can say so.
        """
        if mode == "potential" and self.potential:
            return self.potential
        return self.current

    def baseline(self, mode: str) -> float | None:
        """The scouting grade this player's projection is measured against."""
        return self.overall_potential if mode == "potential" else self.overall_current

    @property
    def is_pitcher(self) -> bool:
        return self.position.upper() in {"SP", "RP", "CL", "P", "SR", "MR"}


@dataclass
class LoadResult:
    players: list[Player]
    scale: str
    columns: dict[str, R.ColumnRole]
    used_potential_tools: bool
    skipped: list[tuple[int, str]]

    @property
    def tool_columns(self) -> list[str]:
        return sorted({role.field for role in self.columns.values()
                       if role.kind == "tool"})


def _to_float(raw: str) -> float | None:
    text = (raw or "").strip().replace("%", "")
    if not text or text in {"-", "--", "N/A", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_csv(path: str, scale: str | None = None) -> LoadResult:
    """Parse an OOTP export.

    `scale` overrides scale auto-detection when an export is small enough or
    compressed enough that the observed range is misleading.
    """
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} is empty")
        columns = {name: R.classify_header(name) for name in reader.fieldnames}
        rows = list(reader)

    tool_cols = [(name, role) for name, role in columns.items() if role.kind == "tool"]
    if not tool_cols:
        recognized = sorted({r.field for r in columns.values() if r.kind != "ignored"})
        raise ValueError(
            f"{path} has no ratings columns - only {recognized or 'nothing'} was "
            "recognized. OOTP's default draft-pool view exports OVR and POT "
            "only; add the individual ratings columns to the view in-game and "
            "re-export.")

    # Detect scale across every rating cell in the file, not per row.
    observed: list[float] = []
    for row in rows:
        for name, _role in tool_cols:
            value = _to_float(row.get(name, ""))
            if value is not None:
                observed.append(value)
    resolved_scale = scale or R.detect_scale(observed)

    players: list[Player] = []
    skipped: list[tuple[int, str]] = []
    used_potential_tools = False

    for index, row in enumerate(rows, start=2):  # row 1 is the header
        player = Player(name="", position="", row_number=index)
        for name, role in columns.items():
            raw = row.get(name, "")
            if role.kind == "meta":
                player.meta[role.field] = (raw or "").strip()
            elif role.kind == "overall":
                value = _to_float(raw)
                if role.is_potential:
                    player.overall_potential = value
                else:
                    player.overall_current = value
            elif role.kind == "tool":
                value = _to_float(raw)
                if value is None:
                    continue
                target = player.potential if role.is_potential else player.current
                target[role.field] = value

        player.name = player.meta.get("name", "") or f"row {index}"
        player.position = player.meta.get("position", "")
        if player.potential:
            used_potential_tools = True

        if not player.current and not player.potential:
            skipped.append((index, f"{player.name}: no usable ratings"))
            continue
        players.append(player)

    return LoadResult(players=players, scale=resolved_scale, columns=columns,
                      used_potential_tools=used_potential_tools, skipped=skipped)

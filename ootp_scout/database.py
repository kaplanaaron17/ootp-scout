"""A persistent store of everything the tool has seen.

Why observations rather than results
------------------------------------
The obvious design is to write each run's ranking into a table. That would be
wrong. A residual is measured against whoever else was in that run: a +2.0
differential inside a 41-player draft class and a +2.0 across 800 league
players are not the same claim, and storing both in one table invites
comparing them.

So this stores only what was *observed* - grade, projected WAR, ratings, age,
on a date - and the analysis is recomputed across whatever set is queried. Ask
for the whole league and you get a league-wide fit; ask for one organisation
and you get that organisation's.

Every observation is kept rather than overwritten, so a player accumulates a
history. In a save played over many seasons that history is the interesting
part: a prospect whose POW went 45 -> 55 -> 60 is telling you something no
single snapshot can.

sqlite3 is in the standard library, so this adds no dependency.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

DEFAULT_FILENAME = "ootp_scout.db"

TABLE = """
CREATE TABLE IF NOT EXISTS observations (
    id                INTEGER PRIMARY KEY,
    league            TEXT    NOT NULL DEFAULT '',
    name_key          TEXT    NOT NULL,
    name              TEXT    NOT NULL,
    mode              TEXT    NOT NULL,
    role              TEXT    NOT NULL,
    team              TEXT,
    position          TEXT,
    age               INTEGER,
    grade             REAL,
    war               REAL,
    rwar              REAL,
    scouting_accuracy TEXT,
    scale             TEXT,
    ratings           TEXT,
    seen_at           TEXT    NOT NULL,
    source            TEXT
);
"""

# Kept separate from TABLE and applied *after* migration: an index naming a
# column that a migration has yet to add would fail on an older database, and
# take the connection down with it.
INDEXES = """
CREATE INDEX IF NOT EXISTS observations_by_name ON observations (name_key);
CREATE INDEX IF NOT EXISTS observations_by_mode ON observations (mode, role);
CREATE INDEX IF NOT EXISTS observations_by_team ON observations (team);
CREATE INDEX IF NOT EXISTS observations_by_league ON observations (league);
-- One row per player per mode per day: re-running the same export should
-- correct that day's record rather than pile up duplicates, while a run on a
-- later date is a genuinely new observation worth keeping.
-- Scoped by league: the same name in two leagues is two different players.
CREATE UNIQUE INDEX IF NOT EXISTS observations_unique
    ON observations (league, name_key, mode, substr(seen_at, 1, 10));
"""


def default_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        DEFAULT_FILENAME)


@dataclass
class Observation:
    name: str
    mode: str
    role: str
    league: str = ""
    team: str = ""
    position: str = ""
    age: int | None = None
    grade: float | None = None
    war: float | None = None
    rwar: float | None = None
    scouting_accuracy: str = ""
    scale: str = ""
    ratings: dict[str, str] | None = None
    seen_at: str = ""
    source: str = ""

    @property
    def name_key(self) -> str:
        return self.name.strip().lower()


# Columns added after the first release, as (name, declaration). A database
# created by an earlier version is migrated in place rather than rejected -
# the whole point of the store is that it accumulates over a save.
MIGRATIONS = (("team", "TEXT"),
              ("league", "TEXT NOT NULL DEFAULT ''"),
              ("scale", "TEXT"))


def connect(path: str | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(path or default_path())
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(TABLE)
        migrate(connection)
        connection.executescript(INDEXES)
    except Exception:
        # Leaving a half-opened connection behind locks the file on Windows,
        # which turns a schema problem into an unopenable database.
        connection.close()
        raise
    return connection


def migrate(connection: sqlite3.Connection) -> list[str]:
    """Add any columns missing from an older database. Returns what it added."""
    existing = {row["name"] for row in
                connection.execute("PRAGMA table_info(observations)")}
    added = []
    for column, declaration in MIGRATIONS:
        if column not in existing:
            connection.execute(
                f"ALTER TABLE observations ADD COLUMN {column} {declaration}")
            added.append(column)
    if added:
        connection.commit()
    return added


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record(connection: sqlite3.Connection, observations: list[Observation],
           source: str = "") -> tuple[int, int]:
    """Store observations. Returns (inserted, updated)."""
    stamp = _now()
    inserted = updated = 0
    for observation in observations:
        seen_at = observation.seen_at or stamp
        day = seen_at[:10]
        existing = connection.execute(
            "SELECT id FROM observations WHERE league = ? AND name_key = ? "
            "AND mode = ? AND substr(seen_at, 1, 10) = ?",
            (observation.league, observation.name_key, observation.mode,
             day)).fetchone()
        values = (
            observation.league,
            observation.name_key, observation.name, observation.mode,
            observation.role, observation.team, observation.position,
            observation.age,
            observation.grade, observation.war, observation.rwar,
            observation.scouting_accuracy, observation.scale,
            json.dumps(observation.ratings or {}, sort_keys=True),
            seen_at, observation.source or source,
        )
        if existing:
            connection.execute(
                "UPDATE observations SET league=?, name_key=?, name=?, "
                "mode=?, role=?, team=?, position=?, age=?, grade=?, war=?, "
                "rwar=?, scouting_accuracy=?, scale=?, ratings=?, seen_at=?, "
                "source=? WHERE id=?", values + (existing["id"],))
            updated += 1
        else:
            connection.execute(
                "INSERT INTO observations (league, name_key, name, mode, "
                "role, team, position, age, grade, war, rwar, "
                "scouting_accuracy, scale, ratings, seen_at, source) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
            inserted += 1
    connection.commit()
    return inserted, updated


def latest(connection: sqlite3.Connection, mode: str | None = None,
           role: str | None = None, team: str | None = None,
           league: str | None = None) -> list[sqlite3.Row]:
    """The most recent observation of each player, one row per player."""
    clauses, params = [], []
    if league is not None:
        clauses.append("league = ?")
        params.append(league)
    if mode:
        clauses.append("mode = ?")
        params.append(mode)
    if role:
        clauses.append("role = ?")
        params.append(role)
    if team:
        # Substring so "Louisville" finds it without exact-matching whatever
        # OOTP writes, and case-insensitive so the user need not match it.
        clauses.append("LOWER(team) LIKE ?")
        params.append(f"%{team.strip().lower()}%")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    # id breaks ties within a day, so "latest" is deterministic.
    return connection.execute(
        f"""SELECT o.* FROM observations o
            JOIN (SELECT league, name_key, mode, MAX(seen_at) AS seen_at,
                         MAX(id) AS id
                  FROM observations {where}
                  GROUP BY league, name_key, mode) newest
              ON o.league = newest.league AND o.name_key = newest.name_key
             AND o.mode = newest.mode AND o.id = newest.id
            ORDER BY o.name""", params).fetchall()


def history(connection: sqlite3.Connection, name: str,
            league: str | None = None) -> list[sqlite3.Row]:
    """Every observation of one player, oldest first."""
    if league is None:
        return connection.execute(
            "SELECT * FROM observations WHERE name_key = ? "
            "ORDER BY seen_at, id", (name.strip().lower(),)).fetchall()
    return connection.execute(
        "SELECT * FROM observations WHERE name_key = ? AND league = ? "
        "ORDER BY seen_at, id", (name.strip().lower(), league)).fetchall()


def search(connection: sqlite3.Connection, fragment: str,
           limit: int = 25) -> list[sqlite3.Row]:
    """Players whose name contains `fragment`, most recently seen first."""
    pattern = f"%{fragment.strip().lower()}%"
    return connection.execute(
        """SELECT name, mode, role, MAX(seen_at) AS seen_at, COUNT(*) AS records
           FROM observations WHERE name_key LIKE ?
           GROUP BY name_key, mode ORDER BY seen_at DESC, name LIMIT ?""",
        (pattern, limit)).fetchall()


def leagues(connection: sqlite3.Connection) -> list[dict[str, object]]:
    """Every league held, with size, scale and when it was last updated."""
    rows = connection.execute(
        """SELECT league,
                  COUNT(DISTINCT name_key) AS players,
                  COUNT(*)                 AS observations,
                  MAX(seen_at)             AS last_seen
           FROM observations GROUP BY league ORDER BY players DESC, league"""
    ).fetchall()
    result = []
    for row in rows:
        scales = connection.execute(
            "SELECT DISTINCT scale FROM observations WHERE league = ? "
            "AND scale IS NOT NULL AND scale != ''",
            (row["league"],)).fetchall()
        result.append({
            "league": row["league"],
            "players": row["players"],
            "observations": row["observations"],
            "last_seen": row["last_seen"],
            "scales": sorted(s["scale"] for s in scales),
        })
    return result


def forget(connection: sqlite3.Connection, league: str) -> int:
    """Delete every observation from one league. Returns rows removed."""
    cursor = connection.execute("DELETE FROM observations WHERE league = ?",
                                (league,))
    connection.commit()
    return cursor.rowcount


def teams(connection: sqlite3.Connection,
          league: str | None = None) -> list[tuple[str, int]]:
    """Every team held, with how many players each has."""
    clause = "AND league = ?" if league is not None else ""
    params = (league,) if league is not None else ()
    rows = connection.execute(
        f"""SELECT team, COUNT(DISTINCT name_key) AS players
            FROM observations WHERE team IS NOT NULL AND team != '' {clause}
            GROUP BY team ORDER BY players DESC, team""", params).fetchall()
    return [(row["team"], row["players"]) for row in rows]


def stats(connection: sqlite3.Connection) -> dict[str, object]:
    row = connection.execute(
        """SELECT COUNT(*) AS observations,
                  COUNT(DISTINCT name_key) AS players,
                  MIN(seen_at) AS first_seen,
                  MAX(seen_at) AS last_seen
           FROM observations""").fetchone()
    by_mode = connection.execute(
        """SELECT mode, role, COUNT(DISTINCT name_key) AS players
           FROM observations GROUP BY mode, role ORDER BY mode, role""").fetchall()
    return {
        "leagues": leagues(connection),
        "teams": teams(connection),
        "observations": row["observations"],
        "players": row["players"],
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "by_mode": [(r["mode"], r["role"], r["players"]) for r in by_mode],
    }


def to_ratings(row: sqlite3.Row) -> dict[str, str]:
    try:
        return json.loads(row["ratings"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}

"""Team WAR and projected standings, built from a depth chart.

Summing a team's projected WAR does not work, and the reason is worth stating
because it shapes everything here: every player is projected as a full-season
major leaguer. An organisation's export runs to 120-odd players, most of them
in the minors, and charging a Low-A arm for 200 major-league innings he will
never throw produces team totals around -300 WAR. The numbers are not wrong;
the question being asked of them is.

So a roster is constructed instead. One player per lineup slot, five starters,
a bullpen, a bench - and each one's WAR is scaled to the playing time that slot
actually carries. The budgets come from a real league season rather than from
taste: plate appearances from the same league totals the projection model is
built on, innings from the arithmetic of a nine-inning game.

Wins follow from team WAR against a replacement baseline, and that baseline is
derived rather than written down. Every game has a winner, so a league's wins
must total games x teams / 2. That pins the baseline exactly, and makes the
standings zero-sum the way real ones are.

What this cannot know is who is actually on the roster. Nothing in the export
says so, so the best player at each position is assumed to play. The chosen
depth chart is returned alongside the total for exactly that reason - it is the
assumption most likely to be wrong, so it should be the easiest thing to check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .flagging import Subject, normalize_position
from .projection import LEAGUE_TOTALS

# The batting side of a season, per team per game, from the same league totals
# the projection model uses. Those cover a 30-team, 162-game season.
_SEASON_TEAMS, _SEASON_GAMES = 30, 162
_LEAGUE_PA = (LEAGUE_TOTALS["at_bats"] + LEAGUE_TOTALS["walks"]
              + LEAGUE_TOTALS["hit_by_pitches"])
PA_PER_GAME = _LEAGUE_PA / _SEASON_TEAMS / _SEASON_GAMES

# A team pitches nine innings a game, give or take: fewer when it wins at home
# and bats eighth, more in extras. The two very nearly cancel.
INNINGS_PER_GAME = 9.0

# The eight fielding positions plus a designated hitter. Order is the order
# slots are filled, hardest to replace first - a shortstop who can be moved to
# second costs more than the reverse, so he should be claimed by short.
LINEUP = ("C", "SS", "CF", "2B", "3B", "RF", "LF", "1B", "DH")
BENCH_SIZE = 5
ROTATION_SIZE = 5
BULLPEN_SIZE = 8

# How the season divides. A team's nine regulars take the great majority of its
# plate appearances and its rotation most of its innings; neither takes all.
LINEUP_SHARE = 0.85
ROTATION_SHARE = 0.60

PITCHING_POSITIONS = {"SP", "RP", "CL", "P", "MR", "SR"}
STARTER_POSITIONS = {"SP"}

# What a projected line calls its playing time, per role.
_PLAYING_TIME = {False: "plate_appearances", True: "innings"}
# What the model projects when a line was not stored. A batter's season is
# fixed at 600 plate appearances by the projection itself; a pitcher's depends
# on his stamina, so there is no honest default and his WAR is taken as given.
_ASSUMED_BATTER_PA = 600.0


@dataclass
class Slot:
    """One roster spot, and who fills it."""

    label: str
    player: Subject | None = None
    playing_time: float = 0.0
    war: float = 0.0

    @property
    def name(self) -> str:
        return self.player.name if self.player else "(nobody)"

    @property
    def full_season_war(self) -> float:
        """What he is projected for over a whole season, before scaling."""
        return self.player.war if self.player else 0.0


@dataclass
class TeamProjection:
    team: str
    lineup: list[Slot] = field(default_factory=list)
    bench: list[Slot] = field(default_factory=list)
    rotation: list[Slot] = field(default_factory=list)
    bullpen: list[Slot] = field(default_factory=list)
    considered: int = 0
    wins: float = 0.0
    losses: float = 0.0

    @property
    def slots(self) -> list[Slot]:
        return self.lineup + self.bench + self.rotation + self.bullpen

    @property
    def batting_war(self) -> float:
        return sum(s.war for s in self.lineup + self.bench)

    @property
    def pitching_war(self) -> float:
        return sum(s.war for s in self.rotation + self.bullpen)

    @property
    def war(self) -> float:
        return self.batting_war + self.pitching_war

    @property
    def unfilled(self) -> list[str]:
        """Slots nobody could be found for. Each is worth replacement level."""
        return [s.label for s in self.slots if s.player is None]


@dataclass
class Standings:
    league: str
    teams: list[TeamProjection]
    games: int
    replacement_wins: float
    notes: list[str] = field(default_factory=list)


def _playing_time(player: Subject) -> float | None:
    """How much of a season the projection gave him, or None if unknown."""
    key = _PLAYING_TIME[player.is_pitcher]
    value = (player.projected or {}).get(key)
    if value:
        return float(value)
    return None if player.is_pitcher else _ASSUMED_BATTER_PA


def _fill(label: str, player: Subject | None, allocated: float) -> Slot:
    """Scale a player's season to the playing time this slot carries.

    WAR is a counting stat, so it scales with playing time - which is also why
    a sub-replacement player given more of it costs his team more, exactly as
    he should.
    """
    if player is None:
        return Slot(label=label, playing_time=allocated, war=0.0)
    projected = _playing_time(player)
    if not projected:
        # No line stored and no honest default: take the WAR as projected
        # rather than inventing the innings behind it.
        return Slot(label=label, player=player, playing_time=allocated,
                    war=player.war)
    return Slot(label=label, player=player, playing_time=allocated,
                war=player.war * allocated / projected)


def is_pitcher(player: Subject) -> bool:
    """Trust the role recorded, and fall back to the position written down."""
    return (player.is_pitcher
            or normalize_position(player.position) in PITCHING_POSITIONS)


def project_team(team: str, players: list[Subject], *,
                 games: int = _SEASON_GAMES) -> TeamProjection:
    """Build the best roster this team could field, and total it."""
    batters = sorted((p for p in players if not is_pitcher(p)),
                     key=lambda p: -p.war)
    arms = sorted((p for p in players if is_pitcher(p)), key=lambda p: -p.war)

    pa_budget = PA_PER_GAME * games
    innings_budget = INNINGS_PER_GAME * games

    projection = TeamProjection(team=team, considered=len(players))

    # The lineup, hardest position to fill first. A slot nobody can fill is
    # left empty rather than handed to someone who cannot play there.
    taken: set[int] = set()
    per_regular = pa_budget * LINEUP_SHARE / len(LINEUP)
    for label in LINEUP:
        chosen = None
        for index, player in enumerate(batters):
            if index in taken:
                continue
            position = normalize_position(player.position)
            if label == "DH" or position == label:
                chosen, chosen_index = player, index
                break
        if chosen is not None:
            taken.add(chosen_index)
        projection.lineup.append(_fill(label, chosen, per_regular))

    remaining = [p for i, p in enumerate(batters) if i not in taken]
    per_reserve = pa_budget * (1 - LINEUP_SHARE) / BENCH_SIZE
    for number in range(BENCH_SIZE):
        player = remaining[number] if number < len(remaining) else None
        projection.bench.append(_fill(f"BN{number + 1}", player, per_reserve))

    # The rotation takes genuine starters; a reliever pushed into it would be
    # credited with innings his stamina says he cannot throw.
    starters = [p for p in arms
                if normalize_position(p.position) in STARTER_POSITIONS]
    per_starter = innings_budget * ROTATION_SHARE / ROTATION_SIZE
    for number in range(ROTATION_SIZE):
        player = starters[number] if number < len(starters) else None
        projection.rotation.append(
            _fill(f"SP{number + 1}", player, per_starter))

    used = {id(p) for p in starters[:ROTATION_SIZE]}
    relievers = [p for p in arms if id(p) not in used]
    per_reliever = innings_budget * (1 - ROTATION_SHARE) / BULLPEN_SIZE
    for number in range(BULLPEN_SIZE):
        player = relievers[number] if number < len(relievers) else None
        projection.bullpen.append(
            _fill(f"RP{number + 1}", player, per_reliever))

    return projection


def project_standings(players: list[Subject], *, league: str = "",
                      games: int = _SEASON_GAMES) -> Standings:
    """Every team's roster, totalled and turned into a record."""
    by_team: dict[str, list[Subject]] = {}
    unplaced = 0
    for player in players:
        team = (player.meta.get("team") or "").strip()
        if not team:
            unplaced += 1
            continue
        by_team.setdefault(team, []).append(player)

    teams = [project_team(team, roster, games=games)
             for team, roster in sorted(by_team.items())]
    notes: list[str] = []
    if not teams:
        return Standings(league=league, teams=[], games=games,
                         replacement_wins=games / 2,
                         notes=["No player carries a team, so there are no "
                                "rosters to build. The export needs its ORG "
                                "column."])

    # Every game has a winner, so the league's wins must total games x teams
    # / 2. That is what fixes replacement level - no constant required.
    average = sum(t.war for t in teams) / len(teams)
    replacement = games / 2 - average
    for team in teams:
        team.wins = replacement + team.war
        team.losses = games - team.wins
    teams.sort(key=lambda t: -t.wins)

    if unplaced:
        notes.append(f"{unplaced} player(s) carry no team - free agents and "
                     "the draft pool - and are not on any roster.")
    short = [t.team for t in teams if t.unfilled]
    if short:
        notes.append(f"{len(short)} team(s) could not fill every slot; the "
                     "gaps count as replacement level.")
    thin = [t for t in teams if t.considered < 26]
    if thin:
        notes.append(f"{len(thin)} team(s) have fewer than 26 players on "
                     "record, so their rosters are guesses.")
    notes.append(f"Replacement level is {replacement:.1f} wins, derived from "
                 f"this pool rather than assumed.")
    return Standings(league=league, teams=teams, games=games,
                     replacement_wins=replacement, notes=notes)

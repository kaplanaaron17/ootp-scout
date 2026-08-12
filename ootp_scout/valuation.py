"""Turning a WAR projection into money.

Surplus value is production value minus cost. The production side comes from
the projection; the cost side from the contract. Neither is worth much alone,
and the gap between them is what a trade is actually about.

Everything here is deliberately explicit and adjustable, because every constant
below is a modelling choice rather than a fact:

* **$/WAR** is derived from the league rather than imported. Total payroll
  divided by total projected WAR self-calibrates to the run environment and the
  salary cap of the save, which a number borrowed from real baseball would not.
* **The aging curve** is conventional - improvement into the mid-twenties, a
  plateau, decline after thirty. It is the least defensible part of the model
  and the easiest to swap.
* **The discount rate** expresses that a win this season is worth more than a
  win in four years, because rosters and plans change.

None of this is calibrated against OOTP's own trade engine on purpose. The
point is to disagree with that engine in a documented way, not to reproduce it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Age at which a player is assumed to stop improving and start holding.
PEAK_AGE = 27
# WAR added per year of age below the plateau, and lost per year above it.
GROWTH_PER_YEAR = 0.25
DECLINE_PER_YEAR = 0.30
# Decline accelerates; past this age it runs at the steeper rate.
STEEP_DECLINE_AGE = 33
STEEP_DECLINE_PER_YEAR = 0.55
# A win now beats a win later: rosters, plans and money all change.
DISCOUNT_RATE = 0.08
# Players under team control but not yet arbitration-eligible cost close to
# nothing, so their surplus is nearly the whole value of their production.
# Arbitration years cost a rising share of open-market price.
ARBITRATION_SHARE = (0.25, 0.40, 0.60)


def aged_war(war: float, age: int | None, seasons_ahead: int) -> float:
    """Projected WAR `seasons_ahead` from now for a player currently `age`.

    A flat projection would badly overvalue a 34-year-old's fourth year and
    undervalue a 22-year-old's. Returns are floored at zero: a player who has
    aged into negative value gets released rather than played.
    """
    if seasons_ahead <= 0:
        return war
    if age is None:
        return max(0.0, war)

    projected = war
    for step in range(1, seasons_ahead + 1):
        year_age = age + step
        if year_age <= PEAK_AGE:
            projected += GROWTH_PER_YEAR
        elif year_age <= STEEP_DECLINE_AGE:
            projected -= DECLINE_PER_YEAR
        else:
            projected -= STEEP_DECLINE_PER_YEAR
    return max(0.0, projected)


def derive_dollars_per_war(total_payroll: float, total_war: float) -> float:
    """League payroll divided by league production.

    Raises when there is not enough to divide, so a caller cannot silently
    calibrate against a tenth of the league.
    """
    if total_payroll <= 0:
        raise ValueError("total payroll must be positive")
    if total_war <= 0:
        raise ValueError("total projected WAR must be positive - a league whose "
                         "players collectively project at or below replacement "
                         "cannot price a win")
    return total_payroll / total_war


@dataclass
class ContractYear:
    """One season of a player's future.

    Contract years carry a known salary. Arbitration years instead carry a
    `salary_share` - the fraction of open-market price the player will cost -
    because the money cannot be worked out until the price of a win is known.
    """

    seasons_ahead: int
    war: float
    salary: float = 0.0
    salary_share: float | None = None
    kind: str = "contract"      # contract | arbitration

    @property
    def discount(self) -> float:
        return (1.0 + DISCOUNT_RATE) ** self.seasons_ahead

    def resolved_salary(self, dollars_per_war: float) -> float:
        if self.salary_share is None:
            return self.salary
        return self.salary_share * self.war * dollars_per_war


@dataclass
class Valuation:
    years: list[ContractYear] = field(default_factory=list)
    dollars_per_war: float = 0.0

    @property
    def production_value(self) -> float:
        return sum(year.war * self.dollars_per_war / year.discount
                   for year in self.years)

    @property
    def cost(self) -> float:
        return sum(year.resolved_salary(self.dollars_per_war) / year.discount
                   for year in self.years)

    @property
    def surplus(self) -> float:
        return self.production_value - self.cost

    @property
    def total_war(self) -> float:
        return sum(year.war for year in self.years)


def build_years(war: float, age: int | None, contract_years: int,
                salary: float, control_years: int = 0,
                include_control: bool = True) -> list[ContractYear]:
    """The seasons a player is worth something to the team that holds him.

    `contract_years` are seasons at a known salary. `control_years` are the
    seasons after that where he is still not a free agent - the cheap years the
    in-game trade value tends to miss. Arbitration salaries are estimated as a
    rising share of what his production would fetch on the open market.
    """
    years: list[ContractYear] = []
    for step in range(contract_years):
        years.append(ContractYear(seasons_ahead=step,
                                  war=aged_war(war, age, step),
                                  salary=salary, kind="contract"))
    if not include_control:
        return years

    for index in range(control_years):
        step = contract_years + index
        share = (ARBITRATION_SHARE[index] if index < len(ARBITRATION_SHARE)
                 else ARBITRATION_SHARE[-1])
        years.append(ContractYear(seasons_ahead=step,
                                  war=aged_war(war, age, step),
                                  salary_share=share, kind="arbitration"))
    return years


def value(war: float, age: int | None, contract_years: int, salary: float,
          dollars_per_war: float, control_years: int = 0,
          include_control: bool = True) -> Valuation:
    """Surplus value for one player."""
    years = build_years(war, age, contract_years, salary, control_years,
                        include_control)
    return Valuation(years=years, dollars_per_war=dollars_per_war)


def compare(side_a: list[tuple[str, Valuation]],
            side_b: list[tuple[str, Valuation]]) -> dict[str, float]:
    """Two packages of players, and who comes out ahead."""
    a_surplus = sum(v.surplus for _name, v in side_a)
    b_surplus = sum(v.surplus for _name, v in side_b)
    return {
        "a_surplus": a_surplus,
        "b_surplus": b_surplus,
        "difference": a_surplus - b_surplus,
        "a_war": sum(v.total_war for _name, v in side_a),
        "b_war": sum(v.total_war for _name, v in side_b),
    }

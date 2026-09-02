# ootp-scout

Finds baseball players whose projected production outruns the scouting grade
attached to them — the ones a league's own valuation underrates.

Built for [Out of the Park Baseball](https://www.ootpdevelopments.com/), a
simulation game whose in-game trade values are priced off a single overall
rating. That rating is a lossy summary of a player's underlying tools, so it
misprices players systematically. This tool finds the gap and puts a number
on it.

```
MOST UNDERRATED - projecting above what their grade implies
  #  Player                   Pos  Age   OVR  Impl   +/-    WAR    Exp   Diff     z  Scouting
  1  Sleeper Sam              CF    20    35    72   +37   7.30  -0.75  +8.05  4.92  Low
  2  Player 00                RF    28    55    62    +7   2.30   0.82  +1.48  0.91  High
```

*OVR 35, but his projection implies a 72.*

Standard library only — no install step. `openpyxl` is used for spreadsheet
output if present; everything else works without it. Developed and tested on
Python 3.14.

## What it does

1. Reads a player export straight out of the game's HTML report
2. Converts ratings into projected season stats and WAR
3. **Fits projected WAR against the scouting grade across the whole pool, and
   ranks by residual** — how far each player sits above the WAR his grade
   predicts
4. Accumulates it all in a local database you can query during a trade

Step 3 is the point. Ranking by raw projected WAR just re-lists the players
everyone already knows are good. The residual finds the *mispriced* ones.

Step 2 is a Python port of the projection maths from
[ootpcalculator.com](https://ootpcalculator.com), whose source is MIT licensed.
It reproduces the site to within its own display rounding — the tests assert
that against real output — which means no browser, no clipboard, and no
downloaded CSV. Passing a downloaded CSV still works if you would rather use
the site directly.

## Get it

**Windows, no Python needed:** download `OOTP-Scout.exe` from the
[latest release](https://github.com/kaplanaaron17/ootp-scout/releases) and
double-click it. One file, nothing to install. It is not code-signed, so
Windows warns on first run — **More info → Run anyway**.

The window imports an export and shows the whole pool in a sortable, tinted
table, with tagging, player history, trades and spreadsheet export on the
toolbar.

**From a checkout**, which also gets you the commands:

```bash
git clone https://github.com/kaplanaaron17/ootp-scout
cd ootp-scout
python -m ootp_scout gui          # the same window
python build_exe.py               # rebuild the exe (needs pyinstaller)
```

Your database lives in `%LOCALAPPDATA%\ootp-scout` (or the equivalent on macOS
and Linux), so replacing the application never touches your history.
`OOTP_SCOUT_DB` overrides it, and a database already sitting beside a checkout
keeps being used.

## Quick start

```bash
python -m ootp_scout flag latest             # project, rank, record
python -m ootp_scout lookup "Ted Williams"   # consult during a trade
python -m ootp_scout compare "A, B" "C"      # weigh a hypothetical trade
python -m ootp_scout report --out league.xlsx
```

That first line is the whole loop: it finds the newest export the game wrote,
projects every player, ranks them and records the lot.

`OOTP-Scout.bat` wraps all of it in a menu for people who would rather not use
a terminal. Full operational detail is in [USAGE.md](USAGE.md).

## Design decisions

**The model is fitted per pool, not hard-coded.** Nothing assumes a fixed
relationship between grade and WAR. Each run regresses WAR on the grade across
whoever is present and measures residuals against that. Different leagues,
rating scales and run environments therefore need no configuration.

**Position is a term in the fit, not a separate model.** Each position gets its
own intercept shift while sharing one slope. Fitting each position separately
would put four data points behind a designated hitter's baseline; a shared
slope with a per-position offset is one well-supported number instead. On real
data this dropped residual spread from 1.90 to 1.64 and materially reordered
the results.

**The database stores observations, not rankings.** A residual is only
meaningful against the pool it was computed in — a +2.0 inside a 41-player
draft class is not a +2.0 across 800 league players. Storing rankings would
invite comparing incomparable numbers, so the store keeps raw facts and every
query refits. Observations are kept rather than overwritten, so players
accumulate a history across seasons.

**Leagues are never combined, and the tool refuses to guess between them.**
Every other ambiguity here picks a sensible default and says so. This one asks,
because a fit spanning a 20-80 league and a 1-100 league produces a ranking
that looks completely normal and means nothing.

**The site's contract is derived from its own code, not guessed.** The
calculator accepts exactly four export layouts, which the tool matches
verbatim. That resolves ambiguities no heuristic could: `CON` means Contact in
the batting views and Control in the pitching views, and only the view
disambiguates it.

## Notable problems solved

- **Rating scale detection.** The game exports on either a 20-80 or 1-100
  scale, and the calculator must be told which. It is inferred from the data:
  20-80 rounds to grades, so every value lands on a multiple of five, while
  1-100 produces off-grid values immediately. Real exports then showed ratings
  *above* the nominal 20-80 ceiling — a 90 Stealing — so the detector matches
  the calculator's actual limit rather than the nominal one.
- **Runs-allowed WAR for pitchers.** The calculator's WAR sits beside FIP, so
  it is fielding-independent. Its output also carries innings and runs, which
  is enough to compute the runs-allowed flavour alongside it. The replacement
  baseline is solved so the pool's mean matches, putting both on one scale by
  construction — the per-pitcher disagreement is the signal, and a level shift
  would only obscure it.
- **An invalid ground/fly setting.** The site accepts a numeric `G/F` and
  returns nonsense — the same arm read 4 home runs and 9.1 WAR against 15 and
  6.7 with a valid setting. The port refuses it instead, because reproducing
  that faithfully would be useless.
- **Mismatched inputs.** Pairing a report with projections from a different
  export used to fit a line through whatever few names overlapped and present
  it as a ranking. It now refuses below five matches and names both files.

## Testing

```bash
python -m unittest discover -s tests -t . -p "test_*.py"
```

374 tests. Fixtures in `tests/fixtures/` are real exports paired with the
projections the calculator actually returned for them, including a planted
player whose tools are elite and whose grade is 35 — he must come out first.

The projection port is tested against those same fixtures: every player's WAR
must match the site to within its own display rounding, and OPS, FIP and BABIP
to three decimals. That is the only specification worth having, since the
port's purpose is to reproduce the site.

Several tests exist because they caught real bugs: a `.xlsx` filename that
silently wrote CSV, a quadratic fit whose inverse bailed out because its linear
coefficient was near zero, a schema migration that created an index on a column
it had not yet added, and a suite that was writing into the user's own database
and taking twenty times longer for it.

## Layout

| Module | Responsibility |
| --- | --- |
| `views.py` | The four export layouts, scale detection, validation |
| `tables.py` | Reading HTML, TSV and CSV |
| `reports.py` | Locating game exports and downloads on disk |
| `flagging.py` | Least-squares fit, position offsets, residual ranking |
| `pitching.py` | Runs-allowed WAR |
| `projection.py` | Ratings to stats and WAR, ported from the calculator |
| `valuation.py` | Surplus value: aging curve, discounting, $/WAR |
| `database.py` | SQLite store, migrations, queries |
| `spreadsheet.py` | Formatted, colour-coded workbook output |
| `service.py` | The operations the window and the commands share |
| `gui.py` | The window |
| `cli.py` | Commands |

## Status

Working and in use. Surplus value is modelled and tested but not yet wired to
live data — it needs salary and contract columns that the export does not carry
by default. Until then `compare` reports production and the grade gap, and says
plainly that it is not surplus value rather than implying the cost side has
been handled.

## Licence

MIT.

`projection.py` is a port of the projection maths from
[danseguin23/ootp-calculator](https://github.com/danseguin23/ootp-calculator)
by Daniel C. Seguin, used under its MIT licence. The lookup tables, estimators
and WAR constants there are his work.

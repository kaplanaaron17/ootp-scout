# Using ootp-scout

Operational detail. See [README.md](README.md) for what the project is
and why it is built the way it is.

## The window

Double-click **`OOTP-Scout.exe`** and you get a window: import an export, and
the whole pool comes back in a sortable table, tinted the same way the
spreadsheet is. The toolbar covers importing, tagging, player history, trades
and exporting a sheet; the row under it filters by league, ratings mode, role,
tag and grade.

Nothing needs to be installed to run it — no Python, no libraries. Windows will
warn the first time, because the file is not code-signed: **More info →
Run anyway**.

From a checkout, the same window opens with:

```bash
python -m ootp_scout gui
```

Everything below is the terminal equivalent, and does more: the window covers
the common loop, the commands cover all of it.


## Workflow

In OOTP: pick your player list, switch to one of the ratings views below, then
**Report → Write report to disk**. OOTP does not prompt for a location — it
writes a timestamped file into the save's own folder and opens it in your
browser, which you can ignore. So just ask for the newest one:

```bash
python -m ootp_scout flag latest
```

That is the whole loop. It reads OOTP's HTML directly, works out the rating
scale, projects every player, ranks them by residual and records the lot in the
database. No browser, no clipboard, no download.

Or double-click **`OOTP-Scout.bat`**, which walks through it and returns to a
menu afterwards rather than closing:

```
  ADD TO THE DATABASE
    [1]  Scout           export -> database, no browser needed
    [T]  Scout + tag     same, labelled (a draft class, say)
    [2]  Prepare only    copy a paste block for ootpcalculator.com
    [3]  Record only     you have already downloaded the CSV

  USE THE DATABASE
    [4]  Look up a player
    [5]  League report   spreadsheet of one league
    [6]  Prospect report same, graded against POT
    [7]  What is stored
    [8]  List leagues
    [9]  Test a trade

    [W]  Open the window
```

Recording a pool does not write a spreadsheet. Everything accumulates in the
database, and options 5 and 6 build a sheet from it when you want one.

### Using the site instead

The projection maths is a port of [ootpcalculator.com](https://ootpcalculator.com),
so the site is no longer needed — but it stays supported, in case you would
rather see its own numbers or the port falls behind a game update.

```bash
python -m ootp_scout prepare --latest
```

puts the paste block **on your clipboard**. Then:

1. Open the [batter](https://ootpcalculator.com/batter-projections) or
   [pitcher](https://ootpcalculator.com/pitcher-projections) projections page
2. Set **RATINGS SCALE** to the scale `prepare` reported, then click **BATCH INPUT**
3. **Ctrl+V**, click **SUBMIT**
4. Click **DOWNLOAD CSV**

```bash
python -m ootp_scout flag latest latest --out targets.xlsx
```

The first `latest` is the newest report, the second is the newest
`*-projections*.csv` in your Downloads. A path works anywhere `latest` does.
If the two do not correspond, `flag` says so rather than ranking the handful
of names that happened to overlap.

HTML, TSV and CSV are all accepted wherever a report is expected, so if you
prefer to select the table in the browser and copy it yourself, paste it into a
`.tsv` and pass that instead. `--no-copy` skips the clipboard step.

## Output

```
View: Batting Ratings   Grade column: OVR   Matched: 41 of 41 players
  fit[hitters] n=41 slope=+0.2201 WAR per grade point, residual sd=1.64
    position offsets vs C: CF +2.24, SS +1.51, 3B +0.69, 2B -0.41, RF -0.60, 1B -0.89

MOST UNDERRATED - projecting above what their grade implies
  #  Player                   Pos  Age   OVR  Impl   +/-    WAR    Exp   Diff     z  Scouting
---------------------------------------------------------------------------------------------
  1  Sleeper Sam              CF    20    35    72   +37   7.30  -0.75  +8.05  4.92  Low
  2  Player 00                RF    28    55    62    +7   2.30   0.82  +1.48  0.91  High
  3  Player 26                C     21    55    60    +5   2.60   1.41  +1.19  0.73  High
```

Name the output `.xlsx` and you get a formatted spreadsheet instead of a CSV.
It holds **every player in the pool**, best differential first, with each
player's tool ratings alongside the analysis columns — so it doubles as a
scouting sheet you can filter and sort. Rows are tinted in both directions:

| Colour | Meaning |
| --- | --- |
| Green | Underrated, z ≥ 2.0 |
| Amber | Underrated, z ≥ 1.0 |
| Peach | Overrated, z ≤ −1.0 |
| Red | Overrated, z ≤ −2.0 |
| None | Within a standard deviation — grade and projection agree |

`--limit` only trims the tables printed to the terminal; the sheet always keeps
everyone, because the uncoloured middle is what makes the highlighted extremes
legible. `--highlight-z` moves the strong threshold. A second sheet records the
fitted line, the position offsets and the thresholds, so the numbers can be
argued with rather than just trusted. Writing `.xlsx` needs `openpyxl`; a `.csv`
name stays dependency-free.


## The database

Every `flag` run records what it saw into `ootp_scout.db` (SQLite, standard
library, gitignored). Over a save this accumulates into a reference you can
consult instead of regenerating a spreadsheet each time.

```bash
python -m ootp_scout lookup "Sleeper Sam"     # one player, with his history
python -m ootp_scout report --out league.xlsx # rank everything held
python -m ootp_scout stats                    # what is in there
```

```bash
python -m ootp_scout report --team louisville    # one organisation
python -m ootp_scout report --role pitcher       # arms only
```

`--team` matches partially and ignores case, so `louisville` finds whatever
OOTP actually writes. It needs an organisation column in your export — add
`ORG` or `TM` to the view and it is picked up automatically; `stats` lists the
organisations held. Fitting inside one organisation says so, because a
fourteen-player baseline is far noisier than a league-wide one and the
resulting numbers are not comparable with a full-league run.

`lookup` takes a partial name and lists candidates if more than one matches.
When a player has been seen more than once it shows how his grade and
projection moved between the first look and the latest — in a save played over
seasons, that movement is the part no single snapshot can give you.

**What is stored is observations, not rankings.** A residual is measured
against whoever else was in that run, so a +2.0 inside a 41-player draft class
and a +2.0 across 800 league players are not the same claim. Storing both in
one table would invite comparing them. Instead the database keeps the raw facts
— grade, projected WAR, ratings, age, on a date — and `report` refits across
whatever you ask for. Query the whole league and you get a league-wide fit;
`--role pitcher` fits only arms.

Re-running the same export on the same day corrects that day's record rather
than piling up duplicates; a run on a later date is a genuinely new
observation. `--no-save` skips recording entirely.


## Testing a trade

```bash
python -m ootp_scout compare "Sleeper Sam, Player 15" "Player 02, Player 28"
```

Names are comma-separated, partial names resolve, and an ambiguous one is
refused rather than guessed. Both sides are measured against the same fit:

```
Projected WAR      +5.50 in your favour
Versus the grades  -2.13 wins
  You are giving up the players the grades underrate more - cheap by the
  opponent's pricing, but the ones worth keeping.
```

Two numbers because they answer different questions. **Projected WAR** is who
gets more production. **Versus the grades** is the arbitrage: an opponent
pricing by OVR — as the in-game trade value does — will happily give up players
whose projection beats their grade, and overcharge for the reverse. Winning the
first and losing the second means you took the deal the other side wanted.

**This is production, not surplus value.** No salaries or contract lengths are
recorded, so a cheap 23-year-old and an expensive 34-year-old with the same
projection look identical. Adding the contract columns to your OOTP view is
what closes that gap.


## Unusable players will wreck the fit

Exporting a whole league includes hundreds of players who would never take the
field. They are not outliers to be shrugged off - they are most of the pool,
and they set the slope.

The relationship between grade and WAR is not one straight line across the full
range. On real data, including everyone made the fitted slope 0.38 WAR per
grade point; fitting only players graded 40 and up made it 0.20. That
difference compresses the top: a six-WAR hitter read an implied **60** with no
floor and **78** with one.

```bash
python -m ootp_scout report --min-grade 40
```

The tool warns on its own when more than a third of a pool projects below
replacement. A quadratic fit does not rescue it - on real data the curve peaks
around grade 68 and turns downward, claiming a 75 is worse than a 65, and
cannot be inverted at all above its maximum.

`--min-grade` applies to the grade being fitted. A prospect graded 25 now with
a potential of 65 is therefore excluded from a *current* report — which is
right, because he would never take the field this season and including him
recreates the distortion. `--min-any-grade` keeps such players when you want
them.

Pick the floor by where your league's players actually stop being usable, and
keep it the same between runs - changing it changes every number.

## Why high-graded players were all showing red

A straight line through grade and WAR is wrong in a measurable way: the real
relationship is concave, so a line over-predicts at the top. On real league
data, mean residual by grade under a linear fit ran

```
OVR 45  +0.29      OVR 60  -0.25
OVR 50  +0.26      OVR 65  -0.71
```

Every player above 60 was marked overrated by the shape of the model, not by
anything about the player. The baseline is therefore fitted as a **monotone
curve** through binned means rather than a straight line — it follows the shape
in the data while never going down, which keeps the implied grade invertible.
That took the bias at OVR 65 from -0.71 to -0.05.

`--shape linear` restores the old behaviour. Raising `--degree` does not help
and should not be used for this: a quadratic on the same data peaks near grade
68 and turns downward, claiming a 75 is worse than a 65.

## Implied grades that make no sense

Two ways this went wrong, both now handled.

**Absurd highs.** The curve is inverted to get an implied grade, and inverting
past its top end divides by the slope of the last segment. Real pitcher data
had a top bin rising 0.06 WAR across five grade points, so a 5.66-WAR arm came
out at an implied **227**. Extrapolation now uses a slope held to at least half
the curve's overall rise, and the result is clamped to what the rating scale
can actually express — 20-80 or 1-100, taken from the league itself. Armando
Nunez went from 227 to 80.

Batters were unaffected because their top segment rises healthily; this was a
pitcher problem, which is why it looked like pitchers were "weird".

**Absurd lows.** Same mechanism at the bottom, same fix. Nothing reads below
the scale's floor now.

**Pitchers in the batting pool.** OOTP puts pitchers in a Batting Ratings
export with their hitting ratings and their *pitching* grade. Measuring a
pitcher's bat against a grade that describes his arm is a category error, and a
loud one — a starter led the overrated list because of it. Players whose
position belongs to the other role are dropped from the fit and reported.

## Implied grade is within a role, not across them

A pitcher and a hitter with the same projected WAR will not show the same
implied grade, and should not. Each is measured against his own group's curve,
because a grade of 70 does not mean the same number of wins for a starter, a
reliever and a shortstop — which is equally true of OOTP's own OVR.

**Use WAR to compare across roles. Use the implied grade and the differential
to compare within one.**

Starters and relievers are fitted apart from each other for the same reason,
and it matters more than it sounds. On real league data the gap between them
ran 0.54 wins at grade 40 and 4.22 at grade 70 — a starter's innings scale with
his quality and a reliever's do not. A position offset is a constant and cannot
express a gap that widens, so forcing one curve through both flattened its top,
and every good pitcher fell off the end of the scale. Split apart, the starter
curve reaches 4.94 WAR where the blended one stopped at 2.50.

`--no-split-starters` puts them back together if you want to see it.

## Tagging a batch, like a draft class

Label an import, then report on just that batch:

```bash
python -m ootp_scout flag latest --tag "2033 draft"
python -m ootp_scout report --tag "2033 draft" --out draft2033.xlsx
```

`stats` lists the tags held.

**The fit still uses the whole league.** That is the point, and it is not a
detail: a draft class measured against itself only tells you who is the best of
a bad bunch. Measured against the league they are joining, an OVR 35 teenager
whose projection implies a 63 is visible as what he is. The report says which
it did:

```
Database report: Top Shelf - 54 players, current ratings, refitted together
  showing 13 tagged '2033 draft', measured against all 54
```

`--fit-on-tag` restricts the fit as well, if you really do want a
within-class ranking.

Tags are scoped to a league, so the same label can be reused across saves.

## Multiple leagues

If you play in several online leagues, each is kept separate:

```bash
python -m ootp_scout leagues                        # what is held
python -m ootp_scout report --league "Sim Nation"   # one league
python -m ootp_scout forget "Old League"            # remove one
```

The league is taken from the save the report came out of — OOTP writes reports
inside `saved_games/<save>.lg/`, so it identifies itself and you need not say.
`--league` overrides when a report has been moved somewhere else.

**Leagues are never combined, and `report` refuses to guess between them.**
Each has its own talent pool and run environment, and they may run different
rating scales — a 55 on 20-80 is not a 55 on 1-100. A fit spanning both would
be meaningless, and the output would look perfectly normal, so the tool asks
rather than picking. With a single league in the database no flag is needed.

The scale is recorded per league, and `leagues` shows it. `forget` deletes a
league and everything recorded for it; it asks you to type the name to confirm,
or takes `--yes`.


## rWAR, for pitchers

The calculator reports one WAR for pitchers, sitting next to FIP — so it is the
fielding-independent kind, built from strikeouts, walks and home runs. Its
output also carries **IP** and **R**, which is everything a runs-allowed WAR
needs, so pitcher runs show an **rWAR** column and the **rWAR − WAR** gap
beside it.

Where they disagree is the point. A pitcher whose rWAR trails his WAR gave up
more runs than his peripherals imply — usually his BABIP or home-run rate doing
the damage rather than his strikeout and walk skills. In the fixture pool, Ace
Sleeper projects 9.10 WAR but 7.80 rWAR.

Runs-above-replacement needs a replacement baseline, which the calculator does
not expose. Rather than import a number from a different run environment, the
baseline is solved so the pool's mean rWAR equals its mean WAR. The two columns
then sit on one scale by construction and the per-pitcher gap is not
contaminated by a level shift. **This is pool-relative and is not
Baseball-Reference's rWAR** — do not quote it as one.

The columns appear only when the projections carry innings, so batter runs are
unaffected.


## The implied grade

Beside each player's actual grade sits the grade his projection *implies* —
the same fitted line read backwards. Instead of "this player is +8.05 wins
above expectation", it says **OVR 35, implied 72**, which is the gap stated in
the units the grade is written in.

```
  #  Player                   Pos  Age   OVR  Impl   +/-    WAR    Exp   Diff     z  Scouting
  1  Sleeper Sam              CF    20    35    72   +37   7.30  -0.75  +8.05  4.92  Low
```

It undoes the position offset too, so two players with the same WAR at
different positions imply different grades — exactly as they should.

Two caveats. It can land outside the rating scale: a dreadful projection on a
20-80 save can imply a grade below 20, because the line keeps going where the
scale stops. And it is blank when the fit has no grade term at all (a pool where
every grade is identical), since then every grade implies the same WAR and the
question has no answer.


## Both ends of the ranking

Both ends of the ranking are printed. **Most underrated** are the players to
target; **most overrated** are the same fit read downwards — players projecting
below what their grade implies, which is who to trade away or stop paying up
for. `--overrated N` sets how many appear in the terminal (default 10; `0`
turns it off). The spreadsheet shows both ends by colour on one sheet.

Useful flags on `flag`: `--limit`, `--min-z 1.5`, `--degree 2` (fit a curve),
`--pool` (fit hitters and pitchers together), `--no-position`.


## Getting the export out of OOTP

In OOTP, find the players you want, switch to one of these four views, then
**Report → Write report to disk**. The calculator accepts exactly these column
sets and nothing else:

| View | Grade | Ratings |
| --- | --- | --- |
| Batting Ratings | OVR | CON, GAP, POW, EYE, K's, CON/POW vL/vR, BUN, BFH, SPE, STE, DEF |
| Batting Ratings (potential) | POT | CON P, GAP P, POW P, EYE P, K P, SPE, STE, RUN, DEF |
| Pitching Ratings | OVR | STU, MOV, CON, STU vL/vR, VELO, STM, G/F, HLD |
| Pitching Ratings (potential) | POT | STU P, MOV P, CON P, VELO, STM, G/F, HLD |

All four also want `POS, #, Name, Inf, Age, B, T, SctAcc`, and optionally
`BABIP`/`SR` for batters or `HRA`/`BABIP` for pitchers. Extra columns and the
sort-arrow glyph on the sorted column are tolerated.

The **default draft-pool view will not work** — it exports OVR and POT and no
underlying ratings, so there is nothing to project from. `prepare` says so and
names the view you want instead.

### Custom views, and pages that will not take a view

Some OOTP pages (the organization view among them) have a fixed layout and will
not let you pick a ratings view. Use a page that does — a player list filtered
to the organization, minors included — and build a **custom view** with the
columns above. Extra columns are tolerated, so one custom view can hold
everything you like.

If a custom view carries current *and* potential ratings, both definitions match
and the tool says so, defaulting to current:

```
NOTE: this export carries both current and potential ratings. Using current - pass --mode to choose the other.
```

`--mode potential` (or `--mode current`) picks. That means one export can feed
both analyses: run `prepare`/`flag` once per mode, pasting each into the
calculator separately.

### Rating scales

The scale is detected from the ratings themselves and printed — match the
site's RATINGS SCALE dropdown to what it says. `--scale` overrides it.

The tell is arithmetic: OOTP's 20-80 display rounds to the nearest grade, so
every rating lands on a multiple of 5, while a 1-100 export produces off-grid
values almost immediately. Note that OOTP shows some ratings above the nominal
top of the 20-80 scale — a 90 Stealing turns up in real exports — so the
detector allows up to 95, matching the calculator's own limit.

If you have a choice, 1-100 carries more resolution than 20-80 and makes the
residual ranking finer — a 20-80 pool puts many players on identical grades,
which flattens the fit. It is a marginal gain, not a reason to change a save
you are happy with.


## How the flagging works

Ranking by projected WAR would just re-list the players you already know are
good. Instead the tool fits projected WAR against the grade across the whole
pool, then ranks by **residual** — how far a player sits above the WAR his grade
predicts.

Two things are held constant while measuring that gap:

- **Role** — hitters and pitchers are fit separately; their WAR distributions
  differ enough that pooling them leaks one group's shape into the other's
  residuals. `--pool` overrides.
- **Position** — each position gets its own intercept shift, so a catcher is
  measured against catchers. Positions share one slope, which is what makes
  this survive thin positions: fitting DH separately on four players would be
  noise, but a DH offset on a shared slope is one well-supported number. A
  position needs at least 4 players to earn an offset; below that the player is
  measured against the group's reference position. `--no-position` overrides.

The fitted offsets are printed each run and recorded in the spreadsheet, so you
can see what the adjustment actually did.

`z_score` is the residual in standard deviations, so it is comparable across
runs and across pools of different sizes. If the grade is constant across a
group (a draft pool where everyone's POT is 80), the fit falls back to the group
mean and every row is annotated saying so.

**Scouting accuracy is reported, never filtered on.** Every flagged player
carries his `SctAcc` into the output, so a hit off a Low-accuracy report is
visible as one and you can discount it yourself.


## Things that will bite you

- **`CON` means Contact in the batter views and Control in the pitcher views.**
  The column name alone is ambiguous, which is why parsing is view-based rather
  than column-based.
- **The calculator's CSV is not quoted.** It joins fields with commas, so a
  player whose name contains a comma splits into an extra column. `flag` reports
  those rows by line number instead of dropping them silently.
- **Joins are by name.** Duplicate names are dropped and reported rather than
  resolved by guessing.
- The calculator states it is tuned for 2026 MLB saves; a very different league
  environment will shift the WAR scale. That mostly cancels out in the residual,
  since every player is measured against the same fitted line.

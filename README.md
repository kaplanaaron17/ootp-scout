# ootp-scout

Finds OOTP players whose WAR projection outruns their scouting grade — the ones
the OVR/POT number underrates. WAR comes from
[ootpcalculator.com](https://ootpcalculator.com); this tool prepares the input,
then ranks the output by how far each player beats his grade.

Two systems, one per grade column:

- **Players to target** — current ratings vs **OVR**
- **Prospects** — potential ratings vs **POT**

Which one you get is determined by the OOTP view you export; the tool detects it.

Standard library only, except that writing `.xlsx` uses `openpyxl` if you
have it. CSV output needs nothing at all.

## Workflow

The calculator is a website with no API, so there is one manual paste in the
middle. It is per *pool*, not per player — a few clicks for a whole draft class.

In OOTP: pick your player list, switch to one of the ratings views below, then
**Report → Write report to disk**. OOTP does not prompt for a location — it
writes a timestamped file into the save's own folder and opens it in your
browser, which you can ignore. So just ask for the newest one:

```bash
python -m ootp_scout prepare --latest
```

This reads OOTP's HTML directly, works out the rating scale, checks the export
against what the calculator accepts, and puts the paste block **on your
clipboard**. Then:

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

Or double-click **`OOTP-Scout.bat`**, which walks through all of the above.

HTML, TSV and CSV are all accepted wherever a report is expected, so if you
prefer to select the table in the browser and copy it yourself, paste it into a
`.tsv` and pass that instead. `--no-copy` skips the clipboard step.

`capture.ps1` wraps the same thing and can read the clipboard as input, but
Windows blocks `.ps1` files by default (`running scripts is disabled on this
system`). The Python commands above need no such permission, so prefer them.

Output:

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

## Tests

```bash
python -m unittest discover -s tests -t . -p "test_*.py"
```

174 tests. `tests/fixtures/` holds a 41-player batting export and a 31-player
pitching export, each with the projections ootpcalculator.com actually returned
for them. Both pools contain a planted player whose tools are elite and whose
OVR is 35 — he must come out first.

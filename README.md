# ootp-scout

Finds OOTP players whose WAR projection outruns their scouting grade — the ones
the OVR/POT number underrates. WAR comes from
[ootpcalculator.com](https://ootpcalculator.com); this tool prepares the input,
then ranks the output by how far each player beats his grade.

Two systems, one per grade column:

- **Players to target** — current ratings vs **OVR**
- **Prospects** — potential ratings vs **POT**

Which one you get is determined by the OOTP view you export; the tool detects it.

Pure standard library. No install, no dependencies.

## Workflow

The calculator is a website with no API, so there is one manual paste in the
middle. It is per *pool*, not per player — a few clicks for a whole draft class.

In OOTP: pick your player list, switch to one of the ratings views below, then
**Report → Write report to disk**. That saves an HTML file (and opens it in your
browser — you can ignore the browser window). Then:

```bash
.\capture.ps1 -Report "path\to\that\report.html"
```

This reads OOTP's HTML directly, checks it, and puts the paste block **on your
clipboard**. Then:

1. Open the [batter](https://ootpcalculator.com/batter-projections) or
   [pitcher](https://ootpcalculator.com/pitcher-projections) projections page
2. Set **RATINGS SCALE** to match your export, then click **BATCH INPUT**
3. **Ctrl+V**, click **SUBMIT**
4. Click **DOWNLOAD CSV**

```bash
python -m ootp_scout flag report.html "$env:USERPROFILE\Downloads\batter-projections.csv" --out targets.csv
```

`capture.ps1` with no `-Report` reads the clipboard instead, for when you have
selected the table in the browser and copied it yourself. Both paths end the
same way. The Python commands work standalone too:

```bash
python -m ootp_scout prepare report.html --scale "20 to 80"
```

HTML, TSV and CSV are all accepted wherever a report is expected.

Output:

```
View: Batting Ratings   Grade column: OVR   Matched: 41 of 41 players
  fit[hitters] n=41 slope=+0.2191 WAR per grade point, residual sd=1.90

  #  Player                   Pos  Age   OVR    WAR    Exp   Diff     z  Scouting
---------------------------------------------------------------------------------
  1  Sleeper Sam              CF    20    35   7.30  -2.80 +10.10  5.32  Low
  2  Player 28                SS    21    55   3.80   1.58  +2.22  1.17  High
  3  Player 03                SS    19    50   2.70   0.49  +2.21  1.17  Normal
```

Useful flags on `flag`: `--limit`, `--min-z 1.5`, `--degree 2` (fit a curve),
`--pool` (fit hitters and pitchers together).

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

### Rating scales

Pass `--scale` to match whatever OOTP is set to; it defaults to `20 to 80`.
Whatever you choose here must match the RATINGS SCALE dropdown on the site.

On the 20-80 scale the calculator rejects any rating that is not a multiple of
5. OOTP's own 20-80 display works in fives, so a real export should pass, but
`prepare` checks before you paste and names the player and column at fault
rather than letting the site reject the whole batch with a generic message.

If you have a choice, 1-100 carries more resolution than 20-80 and makes the
residual ranking finer — a 20-80 pool puts many players on identical grades,
which flattens the fit. It is a marginal gain, not a reason to change a save
you are happy with.

## How the flagging works

Ranking by projected WAR would just re-list the players you already know are
good. Instead the tool fits projected WAR against the grade across the whole
pool, then ranks by **residual** — how far a player sits above the WAR his grade
predicts.

Hitters and pitchers are fit separately by default; their WAR distributions
differ enough that pooling them leaks one group's shape into the other's
residuals.

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

55 tests. `tests/fixtures/` holds a 41-player export and the projections
ootpcalculator.com actually returned for it, including a planted player whose
tools are elite and whose OVR is 35 — he must come out first.

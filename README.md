# ootp-scout

Takes an OOTP CSV export and flags players whose WAR projection outruns their
overall grade — the ones the scouting number underrates. Two modes:

- `--mode current` — current ratings vs **OVR**: players to target now.
- `--mode potential` — potential ratings vs **POT**: prospects.

Pure standard library. No install, no dependencies.

## Usage

```bash
python -m ootp_scout draft_pool.csv --mode potential --limit 25 --out prospects.csv
```

Useful flags:

| Flag | What it does |
| --- | --- |
| `--war-column WAR` | Use a WAR column already in the CSV instead of the built-in model |
| `--min-z 1.5` | Only report players this many standard deviations above expected |
| `--degree 2` | Fit a curve instead of a line, if the grade-to-WAR relationship bends |
| `--scale 20-80` | Override rating-scale auto-detection |
| `--pool` | Fit hitters and pitchers together instead of separately |

## What the export needs

The default `draft_pool_default` view **will not work**. It exports:

```
POS, #, Name, Inf, DOB, Age, NAT, HT, WT, B, T, OVR, POT, Prone, DEM, Sign, SctAcc
```

OVR and POT are the *outputs* of the game's own rating weights, not inputs — there
is nothing to project from. Edit the view in-game to add the individual ratings,
then re-export:

- **Hitters** — Contact, Gap, Power, Eye, Avoid K's, Speed, Stealing, Defense, Arm, Range
- **Pitchers** — Stuff, Movement, Control, Stamina
- **Keep** OVR and POT (the baselines the flag measures against) and SctAcc
- For a real prospect run, add the **potential** ratings columns too. Without them
  `--mode potential` falls back to current ratings against the POT grade and says so.

Header names are matched loosely (`Con` / `Contact` / `Contact Rating` all work), so
you don't have to match any exact naming. Unrecognized columns are ignored.

Set the game's rating scale to **20-80** or **1-100**. The 1-20 and star scales are
rejected with an explanation rather than silently used — they lose too much
resolution to project from.

## How the flagging works

Ranking by projected WAR would just re-list the players you already know are good.
Instead the tool fits projected WAR against the overall grade across the whole pool,
then ranks by **residual** — how far a player sits above the WAR his grade predicts.

Hitters and pitchers are fit separately by default; their WAR distributions differ
enough that pooling them leaks one group's shape into the other's residuals.

`z_score` is the residual in standard deviations, so it's comparable across runs and
across pools of different sizes. If the grade column is constant across a group (a
draft pool where everyone's POT is 80), the fit falls back to the group mean and
every row is annotated with a note saying so.

**Scouting accuracy is reported, never filtered on.** Every flagged player carries
his `SctAcc` value into the output, so a hit on a Low-accuracy report is visible as
such and you can discount it yourself.

## The WAR model is a placeholder

`war_model.py` ships a `ProvisionalModel` whose coefficients are hand-set to be
monotone and plausibly weighted — **not** calibrated against OOTP's engine. It exists
so the pipeline runs end to end and so the flagging logic can be tested. Do not treat
its WAR values as accurate.

One artifact to be aware of: the placeholder applies a positional adjustment (catcher
+1.0 wins, first base −1.0) that OVR does not, so catchers drift to the top of a
current-mode run. That is the model disagreeing with the grade, not a scouting error.
A calibrated model would not do this.

Two ways to replace it, both already wired:

1. **`--war-column`** — put real WAR numbers in the CSV (paste in a calculator's
   output, or export the game's own projection) and no math is done here at all.
2. **Write a new model class** with a `project(player, tools, scale) -> Projection`
   method once the real calculator's formula is known.

The flagging in `flagging.py` doesn't care which model produced the WAR value, so
swapping the model disturbs nothing downstream.

## Tests

```bash
python -m unittest discover -s tests -t . -p "test_*.py"
```

45 tests. `sample_pool.csv` is a generated fixture containing a deliberately planted
sleeper (elite tools, OVR 35) used to confirm the flagging surfaces him.

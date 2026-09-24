# NFL missing-history source recovery and sensitivity

## Verified source results

All twelve missing player-games affecting the four selected currently quoted players have explicit ESPN game statistics reporting **zero receptions and zero receiving yards**. Each result passes the existing final-evidence validator: exact published GSIS/ESPN/PFR identity, completed regular-season game, date/week/team/opponent, both event rosters, played full-game statistics and independent positive offensive snaps. Zeroes are read from explicit stat fields, never inferred from missing box-score rows or participation.

The new archive retains 58 free ESPN responses (scoreboard discovery, final summaries, event rosters and athlete statistics), collected through 2026-09-24 00:17:36 UTC. It reuses the previously archived crosswalk by SHA-256. No odds-provider requests or credits were used.

## Measured effect using the unchanged estimator

The comparison uses the September 23 01:43:06 UTC quote snapshot, the exclusive September 24 game-date cutoff, a 2024 season floor, and the most recent forty non-null observations after filtering. It calls the existing Jeffreys predictive mean / Wilson interval implementation and preserves pushes and executor rounding. Only the twelve explicit receiving observations are overlaid in memory.

| Retained research selection | Recorded games | With recovered games | Recorded probability | Augmented-history probability | Change |
| --- | ---: | ---: | ---: | ---: | ---: |
| Austin Hooper over 0.5 receptions | 31 | 35 | 95.31% | 84.72% | -10.59 pp |
| Jahan Dotson under 1.5 receptions | 31 | 36 | 73.44% | 77.03% | +3.59 pp |
| Christian Watson under 4.5 receptions | 26 | 27 | 87.04% | 87.50% | +0.46 pp |
| Chris Brooks under 7.5 receiving yards | 30 | 32 | 69.35% | 71.21% | +1.86 pp |

Hooper's mean receptions changes from 2.19 to 1.94; the lower Wilson probability bound for over 0.5 changes from 83.81% to 70.62%. This is a material sensitivity to omitted played zero-result games. It is not proof that 84.72% is calibrated or profitable.

The full report contains 60 book/line/side comparisons across four players. These are correlated selections, not sixty independent evaluation games. The selected cohort does not establish league-wide missingness or model accuracy. Evidence was recovered after the retained quote capture, so these are **retrospective sensitivity estimates**, never prospective forecasts or new qualified picks. Rushing/passing overlays are not supplied by the receiving-result validator and remain outside this analysis.

## Reproduction

```powershell
python -m sportsbet.quant.nfl_history_sensitivity --history docs/verification/2026-09-23-nfl-history-coverage-input.json.gz --recovery docs/verification/2026-09-24-nfl-missing-history-sources.json.gz --identity-bundle docs/verification/2026-09-23-nfl-final-sources.json.gz --quotes docs/verification/2026-09-24-nfl-history-sensitivity-quotes.json
```

Every input file digest is retained in `2026-09-24-nfl-history-sensitivity.json`. The CLI has no network, database write, history ingestion, model promotion or pick-publication path. Tests cover the material archived result, immutable inputs, cross-archive mismatches, exact market terms and chronology, null/cutoff/window order, empty cohorts and pushes.

## Collection checkpoint

At 2026-09-24 00:21 UTC, hosted read-only verification showed daily reserved credits **0/20** after UTC reset and rolling **310/450**. The latest scan was still the September 23 23:54 run: one NFL and four CFB eligible events deferred under the staged pregame reserve; zero NBA events. No post-reset scan or new frozen shadow capture was observed. Do not describe a successful scheduler run as successful quote collection.

## Next implementation checkpoint

1. Build a separately versioned, explicit-source history overlay for prospective research, with complete participating-game coverage checks and clear unresolved categories. Preserve existing stored history, predictions and frozen shadow versions.
2. Compare the versioned candidate against the unchanged baseline and matching market prices prospectively. Recovering missing data alone does not validate the estimator's assumption that prior seasons/roles are comparable to the next game.
3. Verify the next normal post-reset scheduled collection and its per-game quotes, availability and gating. Preserve the staged reserve, 20/450 limits and the unapproved status of PR #194.

Production history, model formulas, qualification gates and historical forecast/settlement records are unchanged. No money or bets were involved.

# Reception replay offer audit, 2026-09-22

The published reception replays predict a fixed 4.5-reception research threshold.
This audit checks whether the restricted quote archive contains the same pregame
player, line, and side. It does not turn a retrospective forecast into a bet.

## Scope and matching rule

The input rows are `frontend/data/nfl-week1-2025-receptions.json`,
`frontend/data/nfl-week2-2025-receptions.json`, and
`frontend/data/nfl-week1-2026.json` (receptions only). A directional call uses
Over when `model_probability >= 0.5` and Under otherwise. The previously
published conviction view requires `max(p_over, 1 - p_over) >= 0.6`.

The archive query was read-only against `player_prop_snapshots`, requiring
`sport = 'nfl'`, `prop_type = 'player_receptions'`, a quote captured before the
stored kickoff, an exact player name, side, and line 4.5. ESPN replay event IDs
and Odds API event IDs use different namespaces. The one possible event match
below shares the exact kickoff and player names, but this database does not
retain an explicit cross-provider event crosswalk. Treat it as a candidate match
until that identity is independently verified. The archive has no sportsbook
settlement-rule text or proof that a displayed quote was fillable.

## Coverage and directional baseline

| Replay | Evaluated | Calls at >=60% | Model correct | Always Under correct | Candidate exact offers among >=60% calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2025 Week 1 | 122 | 103 | 89 | 91 | 0 |
| 2025 Week 2 | 128 | 110 | 91 | 90 | 0 |
| 2026 Week 1 | 146 | 122 | 100 | 94 | 1 |
| **Total** | **396** | **335** | **280** | **275** | **1** |

The archive contained 43,406 `player_prop_snapshots` rows at query time, from
2026-03-27 through 2026-09-21. The first stored NFL `player_receptions` event
starts on 2026-09-15, so neither 2025 replay has price coverage. Of the 2026
replay's 15 games, only the 2026-09-15 00:15 UTC kickoff has archived reception
quotes: 403 rows across 15 players, captured from 20:59 to 21:52 UTC before
kickoff. Seven of the replay's >=60% calls are in that game. One has a 4.5 line,
five have offers at other lines, and one has no offer. The other 115 selected
calls have no archived matching game quote. Across all 396 evaluated reception
forecasts, including the lower-confidence ones, two have candidate 4.5 offers.

The model's 280/335 directional score exceeds always Under's 275/335 by five
calls. Both use the same selected rows. This is a fixed-threshold accuracy
comparison, not a priced strategy return.

## The candidate priced row

Jaylen Waddle's replay row for ESPN event `401872931` has `p_over = 0.390625`,
so the >=60% call is Under 4.5. The final stat is one reception. The earliest
candidate matching archived quote is Odds API event
`5ad8135dc2b5f27de0b777acd317855a`, Bovada Under 4.5 at **+105**, captured
2026-09-14 20:59:33 UTC for a 2026-09-15 00:15 UTC kickoff. Its stored quote
row ID is `18341`; the paired Over was -135 in row `18340`. The Under price
implies 48.78% break-even probability, or 45.92% after normalizing both sides'
raw implied probabilities. The retrospective model's Under estimate is 60.94%.
An always-Under rule chooses this same side and has the same observed result.

The 2026 replay file was retrieved on 2026-09-16, after kickoff. It contains no
pregame model-generation timestamp for this selection. A hypothetical unit
stake at the archived +105 price would have won 1.05 units, but neither model
availability before that quote nor actual book settlement or execution is
verified. There is one selected candidate offer, so no meaningful selected
strategy ROI, calibration against offered prices, CLV, or game/player-cluster
interval can be estimated from these replay cohorts.

## Reproduction boundary

The replay files and their source/dataset commitments are tracked in the repo.
The quote inventory is in the restricted database, not in Git. To reproduce
the archive coverage, query `player_prop_snapshots` with the exact predicate
above and inspect distinct event IDs, kickoffs, player names, sides, lines,
prices, and `snapped_at`. Keep missing games and nonmatching lines in the
denominator. Do not select only the winning quote or substitute a different
offered line for the replay's 4.5 threshold.

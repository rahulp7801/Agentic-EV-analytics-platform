# Historical settlement backlog and bounded catch-up repair

Observed 2026-09-23 at 21:00 UTC using a read-only hosted ledger and three free ESPN scoreboard requests (September 14, 20 and 21). Aggregate evidence is in `2026-09-23-settlement-backlog.json`.

## Findings

The ledger contains 921 unresolved NFL forecasts for games that started more than six hours before the observation. None were accepted picks. These are raw forecasts, including repeated observations and opposing sides; they are not independent samples.

- 708 September 14 forecasts lack their recorded home/away team identities. Current final stats exist for those players, but current sources cannot supply the missing immutable forecast evidence. They remain excluded from verified results.
- 213 September 20/21 forecasts across ten players have an exact completed schedule match but no matching player-stat row in the current NFL history. There were no immediately settleable rows in this backlog.
- A separate name-based diagnostic of existing snap records finds positive offensive snaps for eight of the ten names in the corresponding week. Puka Nacua and Jauan Jennings have no corresponding week-two snap row. Neither observation establishes final receiving totals or a sportsbook void. Exact source-ID bindings and complete final-stat evidence are still required before a repair can settle these cases.

Missing outcomes among players with apparent participation may bias a complete-case model comparison. The absence of a stat row must not be treated as a zero, a DNP, a win, or a loss. The current prospective cutoff is September 23, after all these forecasts; none enter that prospective cohort. Historical comparisons still require this missing-outcome limitation.

## Concrete fix

The old catch-up planner selected every unresolved date, even when the retained prediction could never pass the settlement identity or chronology checks. Each such date used one of seven bounded extra schedule slots. Seven invalid older dates could therefore crowd out a valid newer unresolved date, and the real September 14 backlog repeatedly requested an unhelpful extra scoreboard.

The planner now shares the existing settlement checks for sport/market, direction, finite nonnegative line, distinct nonempty teams, date, and capture-before-start chronology. Invalid forecasts cannot allocate an extra catch-up slot. Valid forecasts without final stats and unverified automatic outcomes remain retryable. The normal recent-week schedule collection and settlement validation are unchanged.

This change does not repair or delete old forecasts, settle missing outcomes, change qualification thresholds, or alter frozen models/evaluations. It makes the bounded retry process useful for records that additional source evidence can resolve.

## Verification

- 59 settlement and daily-pipeline tests passed locally.
- Ten regression cases each put seven invalid older dates ahead of one valid unresolved date. The valid date retains its retry slot; invalid-only inputs request no extra date; input records stay unchanged.
- Existing tests retain oldest-first ordering, seven-date bounds, manual-result preservation, valid automatic-result exclusion, unverified automatic-result retries, exact final identity, and source-hash checks.
- The live comparison returned `[-9]` before the fix and `[]` after it: September 14 no longer causes an extra request. September 20/21 still use the normal recent-week schedule collection.
- The aggregate JSON records the old/new planner comparison against a single read-only hosted snapshot of the catch-up window. A preliminary unrestricted ledger read hit its statement timeout; the bounded date-window query avoids fetching unrelated forecast payloads.

## Next evidence checkpoint

1. Review the next routine history refresh for the ten missing-stat players listed in the JSON. Resolve only with exact game/player identity and committed final-stat evidence. If a zero-stat completion path is implemented, require independently verified participation plus complete source evidence; preserve DNP/void uncertainty and existing frozen history commitments.
2. At the September 24 00:00 UTC daily credit reset, inspect the next ordinary scheduled scan for new NFL/CFB coverage and frozen shadow captures. Do not bypass the staged reserve or collect redundant quotes.
3. Preserve the September 24 pregame checkpoints: CFB T120 at 21:30 UTC and NFL T120 at 22:15 UTC, followed by their existing T60 board locks. Qualification and prospective edge requirements remain unchanged.

No odds requests, purchases, bets, quota increases, or production result writes were performed for this investigation. PR #194 remains separately unapproved.

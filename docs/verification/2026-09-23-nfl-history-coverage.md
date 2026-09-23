# NFL participation versus model-history coverage

## Verified finding

A read-only hosted snapshot at **2026-09-23 22:48 UTC** compares 24 selected players: 14 from the retained upcoming GB/ATL quote/forecast scope (including the previously verified Brian Robinson Jr. binding), plus the ten recent missing-result cases. The scope is selected for operational relevance and is not league-wide or an unbiased player sample.

With a 2024 season floor and exclusive September 24 cutoff, the audit validates **585 stat rows** and **627 positive-offensive-snap rows**, excluding three zero-offense rows. It finds **43 player-games with verified offensive participation and no matching history stat row**. Eight of those games have separately verified receiving totals from PR #210; this audit describes history-table coverage and does not insert those outcomes into frozen model inputs.

Four players from the upcoming quote scope account for 12 missing games:

| Player | Recorded stat games | Verified offensive games | Missing stat games |
| --- | ---: | ---: | ---: |
| Jahan Dotson | 31 | 36 | 5 |
| Austin Hooper | 31 | 35 | 4 |
| Chris Brooks | 30 | 32 | 2 |
| Christian Watson | 26 | 27 | 1 |

Every one of these 12 gaps falls inside the corresponding recorded-history date span. No stat row in this audit has a null receiving category. Thus the observed gap concerns absent player-game rows, rather than null reception columns in existing rows.

These counts establish a coverage problem, not the missing outcomes or the size/direction of a probability correction. The recent explicit-zero recovery demonstrates why participation-only omissions deserve investigation. Unknown outcomes remain unknown.

## Reusable diagnostic

`python -m sportsbet.quant.nfl_history_coverage --input INPUT.json` validates source row hashes, provider commitments, observation times, exact GSIS/PFR crosswalk bindings, game/week/team/opponent identities, duplicate player-weeks and the exclusive cutoff. It reports both recorded-history coverage and a forty-game union of recorded rows and verified offensive participation. The union is a diagnostic, not a replacement estimator or a proposed betting strategy.

An input can reuse the previously retained identity bundle with `--identity-bundle docs/verification/2026-09-23-nfl-final-sources.json.gz`; its `identity_source_sha256` must match the archive. The default command has no database/network writes, collection or publication capability. Frozen models, shadow formulas, qualification gates and production queries are unchanged.

Fourteen focused tests passed locally before the workspace outage. Tests cover exact identity, source tampering, duplicate rows, future observations, exclusive cutoff, zero-offense exclusion, unknown outcomes, immutable inputs and rolling-window boundaries.

## Retained and reproduced source snapshot

The workspace drive returned. The original read-only input SHA-256 was verified as `61a91836b77beae78229582b65f855b53239ccdc6aa31b023017927e63c6e84c`. The full snapshot is now archived as `2026-09-23-nfl-history-coverage-input.json.gz`, reusing the exact identity crosswalk from the final-source archive through its SHA-256 commitment.

Replaying the retained input with the command below reproduced the entire original detailed report (apart from the input-file digest, because the archive is compressed). The committed JSON now contains that full reproduced report.

```powershell
python -m sportsbet.quant.nfl_history_coverage --input docs/verification/2026-09-23-nfl-history-coverage-input.json.gz --identity-bundle docs/verification/2026-09-23-nfl-final-sources.json.gz
```

The transient workspace outage did not lose the audit or change any production data.

## Collection and next checkpoints

The latest observed all-sport run, `35922127836`, completed successfully. Its 21:24 UTC scan (`c4fc9a8b722949f5a4c8dfb7e521c11c`) attempted no quotes: one NFL and two CFB events were deferred by the pregame reserve; NBA had zero eligible games. CFB coverage now includes Coastal Carolina/Liberty (September 24 23:30 UTC) and Temple/Army (September 25 20:00 UTC). No redundant scan was dispatched.

The intended fresh ledger/budget/shadow check was prevented by the workspace outage, so earlier prospective counts must not be relabeled as newly verified. The next scheduled quote checkpoint remains **September 24 00:00 UTC**, with normal reserve and 20/450 credit limits.

Next useful work:

1. Refresh scan/budget/frozen-shadow counts at the next scheduled collection checkpoint. Source retention and independent reproduction are complete.
2. Obtain explicit final stats for the 12 missing games affecting the four current quoted players, using exact archived GSIS/ESPN/PFR bindings and independently verified participation. Do not infer zeroes from snaps.
3. Measure the effect in a separately versioned research/shadow dataset before proposing a history-policy change. Existing frozen inputs and prospective gates remain unchanged.

No money, API-key quota, bets, production results, model inputs or qualification thresholds were changed by this audit. PR #194 remains separately unapproved.

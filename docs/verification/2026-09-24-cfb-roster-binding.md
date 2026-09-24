# CFB roster identity and late pregame evidence — September 24, 2026

## Concrete identity failure and fix

The 21:45 UTC CFB scan recorded five forecasts for Dominic Knicely with unavailable roster evidence. The history athlete ID is ESPN `5203477`; the current Coastal Carolina roster names that same ID **Dominic Lee-Knicely**. Name-only matching incorrectly rejected this identity.

CFB availability now binds a supplied history ID directly to the exact ESPN roster ID. It requires one unique match, a matching roster name, a fresh observation, and a valid college-football roster URL/hash. Missing or duplicate IDs, invalid commitments, wrong-sport sources, and incomplete injury coverage fail closed. It never falls back to a name when a history ID is supplied. Injury and teammate risk checks still run against the matched roster name. No probability, sample threshold, or qualification policy changes.

The public projection requires the alias commitment to equal the roster commitment and its athlete ID to match the forecast's history ID. Existing NFL crosswalk behavior is unchanged. Prior forecasts are immutable and were not rewritten. Knicely's eight receiving and sixteen rushing samples still fall below the existing minimum; this fix does not manufacture a qualified pick.

## Verification

- 57 focused backend tests and 26 public-projection tests passed.
- The exact ESPN response bytes are retained in `2026-09-24-cfb-roster-324.json.gz`; the uncompressed SHA256 is recorded in `2026-09-24-cfb-roster-binding.json`.
- Offline replay `2026-09-24-cfb-roster-binding-replay.py` verifies the hash and reproduces the change from unavailable name-only evidence to observed exact-ID evidence. No network requests or database writes are made by the replay.
- CI and release results are recorded on the linked pull request. No current forecast was rerun solely to test the fix.

## New prospective evidence

Normal workflow [36063407291](https://github.com/rahulp7801/agentic-sports-forecaster/actions/runs/36063407291) collected Liberty–Coastal Carolina before the one-hour board lock: 80 source-committed quotes, 66 modeled selections, 11 resolved players, no scan failures. Gates: 60 insufficient sample, five no positive edge, one insufficient confidence. None qualified. An audit of all 18 player/market sample combinations reproduced every sample count. All 158 relevant player/game rows in the retained 2024–2026 source files were present with unchanged core statistics; the database contained four additional rows. Missing categories were not filled with zero.

The new reserve field was present on 41 CFB events and the NFL event in the production scan. At 23:17 UTC public slate responses correctly withheld it because those scan observations were stale.

No NFL scan had run during the 22:15–23:15 UTC pre-lock stage, and no data workflow was active at recovery dispatch. A normal NFL-only scan [36072080795](https://github.com/rahulp7801/agentic-sports-forecaster/actions/runs/36072080795) used the remaining four existing API-key credits after the final reserve release, without a targeted reserve bypass. It completed scan `84cde3a3cb834d93b022a268f89cf745` at 23:21:02 UTC, adding 234 forecasts. One raw forecast (Skyy Moore receiving yards under 10.5 at the retained -109 price) passed the model/risk gates. Its capture at 23:19:41 UTC was after the 23:15 board lock: the recorded current pick board correctly remains empty. This is pending prospective evidence, not a current consumer recommendation or demonstrated edge. Both sides of its matching market price and source commitments are retained in the evidence JSON.

Frozen workload evaluation now has 36 pending paired thresholds (34 receiving-yards, two receptions). Frozen role evaluation has 23 (18 receiving-yards, five receptions). These are thresholds from one future NFL game, not independent settled games. Both still have zero decided paired games and no promotion evidence. Earlier invalid attempts remain retained; frozen versions and thresholds are unchanged.

The delayed free NFL history refresh was recovered separately in [36072417807](https://github.com/rahulp7801/agentic-sports-forecaster/actions/runs/36072417807); it completed at 23:23:21 UTC with no odds requests. Current-season snap history remains 2,994 rows.

## Next checkpoint

Daily quota is now **20/20**, rolling **330/450**. Do not trigger more odds collection for this UTC day. PR #194 remains excluded. No purchases, card use, or bets occurred.

Check authenticated final statuses and exact player statistics after the games end (next postgame evidence check: **September 25, 04:30 UTC**, or the first follow-up after final status is available). CFB kicked off September 24 23:30 UTC; NFL kicks off September 25 00:15 UTC. Preserve unresolved results as pending if source identity/stat evidence is unavailable. Verify the next natural CFB scan carries the new exact-ID binding; do not rewrite today's five affected records or unlock the board. Scheduler lateness remains a separate coverage limitation.

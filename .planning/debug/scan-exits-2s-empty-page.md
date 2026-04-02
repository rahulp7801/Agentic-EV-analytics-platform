---
status: resolved
trigger: "scan_game_ev.py exits in ~2 seconds showing no props; frontend shows empty page after scan completes"
created: 2026-03-31T00:00:00Z
updated: 2026-03-31T21:00:00Z
---

## Current Focus

hypothesis: CONFIRMED AND FIXED — PrizePicks API blocked by PerimeterX. Fixed by wiring Odds API as primary source with PrizePicks as fallback. Also fixed empty-slate behavior to write informative scan_note to cache instead of aborting silently.
test: Ran scan manually after fix — stage 3 now fetches 992 props from Odds API, correctly identifies "no slate yet" for SAC/TOR, writes scan_note to cache.
expecting: User confirms scan completes without 2-second exit and frontend shows meaningful message
next_action: Awaiting human verification

## Symptoms

expected: Scan runs 60-120s, populates EV signals for the selected game
actual: Scan exits in ~2 seconds, signals_cache.json is written with empty signals[], frontend shows empty page
errors: Unknown — subprocess uses stdio:'ignore' so no stderr visible
reproduction: Select any NBA game in Arbitrage tab → click Run Scan → progress bar briefly appears → scan exits → empty results
started: After recent changes (clearing signals_cache.json at scan start + progress file writing)

## Eliminated

- hypothesis: DATE FORMAT MISMATCH — games/route.ts formatDate() strips dashes → returns YYYYMMDD correctly.
  evidence: Verified formatDate() in games/route.ts; ESPN confirmed 9 events for YYYYMMDD, 0 for YYYY-MM-DD
  timestamp: 2026-03-31T20:30:00Z

- hypothesis: IMPORT ERROR — json/pathlib were already available at module level
  evidence: Stages 1+2 run successfully in manual test
  timestamp: 2026-03-31T20:30:00Z

- hypothesis: PROGRESS FILE CLEANUP crash
  evidence: Manual run shows stage 1+2 complete without error
  timestamp: 2026-03-31T20:30:00Z

- hypothesis: DATABASE URL broken
  evidence: database_url uses postgresql+psycopg (not asyncpg). replace('+asyncpg','') is a no-op but URL is already correct for psycopg v3 + SQLAlchemy 2.0
  timestamp: 2026-03-31T20:35:00Z

## Evidence

- timestamp: 2026-03-31T20:30:00Z
  checked: Manual run scan_game_ev.py --team-a SAC --team-b TOR --date 20260401
  found: Stages 1+2 succeed; stage 3 fails — "PrizePicks API unreachable" (ConnectError) → "0 props — aborting"
  implication: Failure at fetch_all_snapshots() in stage 3

- timestamp: 2026-03-31T20:35:00Z
  checked: Direct PrizePicks API test with verify=False
  found: HTTP 403 with PerimeterX captcha page ("px-captcha")
  implication: PrizePicks deployed bot protection that blocks plain httpx; ConnectError in normal mode is TLS-level rejection

- timestamp: 2026-03-31T20:38:00Z
  checked: DraftKings poller test
  found: HTTP 403 Forbidden
  implication: Cannot use DraftKings as fallback

- timestamp: 2026-03-31T20:39:00Z
  checked: ESPN props poller (ESPNPropsPoller)
  found: ESPN finds 7 games but all propBets endpoints return 404
  implication: ESPN Core API propBets endpoint is inaccessible

- timestamp: 2026-03-31T20:40:00Z
  checked: The Odds API player props per-event endpoint
  found: 200 OK, 2 bookmakers, 30 outcomes per event, 499 credits remaining
  implication: Odds API is the only working prop source

- timestamp: 2026-03-31T21:00:00Z
  checked: Post-fix manual run
  found: Stage 3 fetches 992 props from Odds API across 6 events; correctly identifies SAC/TOR not on current slate; writes scan_note to signals_cache.json
  implication: Fix working correctly

## Resolution

root_cause: PrizePicks API blocked by PerimeterX bot protection (HTTP 403 with captcha page, manifests as ConnectError in httpx). scan_game_ev.py fetch_all_snapshots() only tried PrizePicksPoller with no fallback; on 0 results it hard-aborted ("aborting" return at line 463). DraftKings (403) and ESPN props (404) were both dead. The Odds API (working, 500 credits) was never wired into the scan prop-fetch path.

fix: |
  1. Added _normalize_raw_events() helper shared by all sources
  2. Added _fetch_odds_api_snapshots() using The Odds API per-event /events/{id}/odds endpoint (1 credit/event, supports player_points/rebounds/assists/threes/steals/blocks)
  3. Replaced fetch_all_snapshots() with cascade: Odds API → PrizePicks → empty list (no hard abort)
  4. Replaced hard abort on empty snapshot list with _write_no_slate_cache() that writes a scan_note to signals_cache.json
  5. Fixed roster-fallback: if ESPN roster fetch fails (all_players empty), uses full prop slate filtered to Over side
  6. Fixed sportsbook field in DB INSERT and JSON cache export (was hardcoded "PrizePicks", now uses snap.sportsbook)
  7. Added snap_sportsbook key to result dict from run_ev_for_player()
  8. Updated Arbitrage.tsx to read scan_note from cache and display it when signals are empty

verification: Manual run post-fix confirms stage 3 successfully fetches 992 props from Odds API. SAC/TOR game correctly identified as "not on current slate yet" with descriptive scan_note written to cache. Frontend will show note instead of blank page.

files_changed:
  - scan_game_ev.py (fetch_all_snapshots cascade, _normalize_raw_events, _fetch_odds_api_snapshots, hard-abort removal, sportsbook field fix)
  - frontend/components/Arbitrage.tsx (scanNote state, display when empty)

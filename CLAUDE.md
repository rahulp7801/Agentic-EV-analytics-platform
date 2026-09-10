# Maintained implementation knowledge

## Working agreement

- Canonical repository: https://github.com/rahulp7801/Agentic-EV-analytics-platform, origin/master. All commits, CI, and deployment integration belong here.
- Make frequent verified commits. Do not add assistant co-author/contributor trailers. Keep this file current.
- User priorities: working model/LangGraph, accurate metrics, security, GitHub CI/CD, Vercel, NFL/NBA season readiness. Visual redesign is deferred.
- Stay grounded in executed code. Never invent source data, model confidence, settled outcomes, performance, service health, or successful deployment.
- Keep implementation details out of product-facing messages; retain actionable diagnostic detail in developer documentation without credentials.
- Preserve parameterized SQL, validated inputs, stale-data gates, and exposure limits. Never trade security/correctness for a shorter implementation.

## Runtime and development

- User requested removal/hiding of generated workspace clutter. Disposable root .test-tmp-* artifacts are removed where accessible, otherwise excluded from the local editor file tree (Windows denies delete/move/attribute/ACL access on15 old pytest directories); tooling directories retain their existing paths but use Windows Hidden attributes. Future test output/cache lives under ignored hidden .local/ via pytest defaults. Do not create new root test-output files or scatter temporary directories. Preserve .env, source, migrations, lockfiles and audit data.

- Python 3.12, uv 0.11.32, Node 24, Next.js 16.3.4, PostgreSQL 16. Python dependencies are locked in uv.lock; npm in frontend/package-lock.json.
- Graph nodes are deterministic Python, not LLM calls. No OpenAI/Anthropic key is consumed. Runtime requires langgraph and langgraph-checkpoint-sqlite.
- Windows: use .venv/Scripts/python.exe and npm.cmd. Pytest temp/cache paths default under .local/. Local tooling/cache files are ignored; do not create root .test-tmp directories.
- Read frontend/AGENTS.md and relevant installed Next documentation before frontend edits.
- Tests must opt into SPORTSBET_TEST_DATABASE_URL pointing to a disposable DB; never fall back to runtime credentials.
- Alembic respects explicit test URLs and escapes percent characters. Async DB factory preserves exact provider host/user/password/SSL mode; no guessed pooler or region rewrite.

## Deployment and credentials

- User explicitly approved exporting the local ODDS_API_KEY to this repository. It was successfully stored as an encrypted GitHub Actions repository secret and its presence verified without displaying the value. Worker database secrets and reachable production database setup remain outstanding; scheduled scans stay disabled until readiness checks pass.

- Production URL: https://agentic-ev-analytics-platform.vercel.app.
- Vercel project agentic-ev-analytics-platform under rahulp7801s-projects; rootDirectory frontend. IDs are repository Actions variables; VERCEL_TOKEN is a repository secret.
- Project-scoped token works. Vercel CLI 59.15.1 pull fails during team metadata lookup (vercel/vercel#17506); direct deploy --yes --prod supports owner-lookup fallback. Do not request a broader token or export/reuse interactive OAuth credentials.
- CI deploy depends on backend, frontend and isolated PostgreSQL checks. Automatic Vercel git deployments disabled in frontend/vercel.json. Vercel performs the hosted build. .vercelignore limits uploads to frontend sources, excluding environment files, build outputs and legacy signal cache.
- First full deployment success: GitHub run 34538930708 (eb728ef). Runs34539302175 (bdadfa1) and34540128712 (87c55e1) also passed. Verified homepage 200, security headers, public scan POST 403, sanitized signals/metrics 503 while DB is unconfigured.
- Runtime database from local .env remains unreachable (previous DNS failures; latest connection OperationalError). Odds API catalog probe previously passed HTTP 200. Never print secret values. Vercel production DATABASE_URL still needs a reachable dedicated read-only role.
- Worker needs repository secrets DATABASE_URL, DATABASE_URL_ASYNC, ODDS_API_KEY. ANALYTICS_DATABASE_URL uses writable DATABASE_URL in Actions. .env.example and README distinguish Python, Vercel and GitHub settings.
- GitHub secret scanning and push protection enabled. Dependabot security updates enabled. CodeQL extended default setup configured for Python, JS/TS and Actions. Latest completed analysis at87c55e1 passed with no open alerts; this is not proof of complete security.

## Data and orchestration

- Hosted dashboard reads dashboard_snapshots via server-only PostgreSQL. Python publishes snapshots; no local subprocesses/files are relied upon on Vercel.
- Public scan POST is always forbidden, including local mode: Host header checks were spoofable. Only authenticated CLI/Actions workers spend provider credits and write audit data.
- sportsbet.scan routes NBA/NFL through the actual LangGraph, passes exclusive as_of_date and last_n_games=40. GraphState must declare these fields or LangGraph silently drops them.
- Quotes match event/player/market/line/side exactly; evaluate alternate lines separately and support Under-only listings. Resolve exact distinct player identity; unknown/ambiguous names skip instead of borrowing history.
- Require provider quote timestamps and actual start times. Recheck quote age after model computation. No recommendations after start or quote age >5 minutes. Synthetic PrizePicks pricing is rejected. Missing prop listings do not imply injury.
- Stat upserts apply provider corrections and make repeat refreshes safe. Migration 0011 adds NFL player_name and analytics.api_usage. Exact NFL names are sourced from player_display_name.
- sportsbet.refresh --backfill loads NFL current/prior two season years, NBA current/prior. Daily refresh loads current season. NFL schedules are required for cutoffs. Root scan_game_ev.py remains a local NBA scanner, not the hosted worker.
- Market data Actions workflow supports scan/refresh/backfill. Scheduled refresh daily and scan every30min remain disabled unless DATA_PIPELINE_ENABLED=true. Do not enable until reachable DB, migrations, backfill, provider budget and live output are verified.
- Persistent API budget default25 credits/day is a ceiling, not complete slate coverage. It reserves before a request, does not refund failed calls, and stops additional events when exhausted. Choose coverage/budget deliberately before enabling.

## Model and pricing contracts

- Dated NBA queries count pre-game logs, excluding target/future dates before taking recent games. Empty situational samples broaden to pre-game logs, never season totals. Actual double-double counts include steals/blocks.
- NFL cutoff matches each player's own team/week schedule, not the earliest game in the week. Latest-N queries apply situational filters before LIMIT.
- Unfitted home/rest/pace/defense/kinematic adjustments default off. Experimental changes discard incompatible CIs and do not adjust push markets. Neutral defense/pace are placeholders, not measured features.
- Shared prop policy requires >=20 games and exact matched odds. Legacy unconditional NFL executor has a30-game gate; conditional paths report intervals before shared policy gates. The 15pp edge cap is an operational review gate, not calibrated evidence.
- Generic NFL QuantResult measures play_success; arbitrage rejects it without explicit market_outcome scope. Do not treat pass/play success as game-win probability.
- American price determines break-even, payout, expected_return and fractional Kelly. ev_pct/ev_percentage retain legacy probability-edge semantics (percentage points). Dollar expected profit = stake * expected_return, never stake * edge.
- Pushes are separate: pUnder=1-pOver-pPush, expected return=win*payout-loss, Kelly conditional on nonpush. Complement Under CI only when push=0; do not invent push-market intervals.

## Audit, exposure and evaluation

- Ledger uses local .checkpoints/analytics.sqlite by default; ANALYTICS_DATABASE_URL switches default-path storage to PostgreSQL analytics schema (migration0010).
- Immutable per-scan prediction IDs, append-only quotes, explicit settlements. Every successfully evaluated selection is recorded, including rejected/nonpositive estimates. Missing model results are skipped.
- Atomic recommendation exposure default5% per UTC day; rescans idempotent, one exposure per player/game blocks conflicting/correlated selections. PostgreSQL advisory transaction lock preserves cross-process limits. This is recommended exposure, not executed bets or drawdown.
- Reports deduplicate selections, separate all-prediction and accepted-recommendation cohorts. CLV is raw same-book/same-line implied probability movement, requiring entry < last observed closing quote < actual start.
- ROI excludes pending/void stakes; pushes refund. Hit rate, Brier/log loss exclude pushes. Calibration uses model probabilities only. No settlement is inferred from absent records.
- CLI sportsbet.ledger --list exports IDs; --settlements accepts ID->true/false/push/void/null. Hosted metrics snapshots update on the next successful worker run.
- Frontend signalMetrics revalidates model version, probabilities, price, sample, stake, freshness and start time. Legacy/stale/synthetic estimates cannot recommend. No invented CI, strength rating or service health.
- Parlay calculator uses user-supplied gross payout, independent scenarios and dependence bounds; no fitted joint probability or Kelly recommendation. NBA/NFL filtering is wired to dashboard/EV alerts; Under is preserved.

## Verification and remaining gaps

- Production NFL schedule smoke test returned an empty list despite a successful local provider response. Schedule route now formats YYYYMMDD explicitly and distinguishes complete upstream failure (503) from a valid empty schedule, with sanitized server diagnostics. At87c55e1, a cache-busted deployed request returned503/partial=true while the same Node handler locally returned2 NFL games. Provider access from Vercel remains unresolved; do not claim live schedule coverage.

- Latest local full Python suite:290 passed,15 DB skips,2 pre-existing expected failures. Real PostgreSQL CI passed model SQL through both graphs, target-game exclusion, repeatable upserts, migrations and concurrent exposure reservation. Nine frontend metric/access/schedule tests, TypeScript and production build passed.
- npm audit zero vulnerabilities; pip-audit2.10.1 found no known Python vulnerabilities and is now a CI gate. Passing audits cannot prove all security gaps closed.
- Need reachable production DB, migration/backfill, read-only Vercel role, worker secrets and measured quota/coverage before live readiness. Do not claim season readiness from deployment alone.
- Automatic settlement and out-of-sample calibration/profitability remain incomplete. Historical injury/roster conditioning is not fully point-in-time; current hosted baseline does not apply it. Legacy undated NBA aggregate estimates remain low-level paths.
- Generic context odds extraction still needs explicit event/selection matching beyond the play_success gate. NFL schedule ingestion ignores corrections, and home_away enrichment remains incomplete. NFL game-log UI is still unavailable.
- Two expected-failure gamelog/injury tests import obsolete modules; replace with real-builder regression coverage rather than hiding failures. Ledger malformed/naive timestamp validation and reporting by model-version cohort still need hardening.

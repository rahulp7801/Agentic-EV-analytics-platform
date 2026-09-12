# Agentic EV Analytics

NFL/NBA player-prop research with a deterministic LangGraph pipeline, PostgreSQL game history, and a Next.js dashboard. The graph estimates historical outcome frequencies and evaluates real bookmaker payouts. No LLM API key is currently consumed. These estimates have not established predictive profitability.

Production: https://agentic-ev-analytics-platform.vercel.app

## Setup

Use Python 3.12, uv 0.11.32, Node 24, and PostgreSQL 16. Copy `.env.example` to `.env`, then supply the exact database URLs from your provider and an Odds API key. URL-encode password characters and preserve the provider's SSL settings; the application does not rewrite your endpoint.

```sh
uv sync --locked --extra dev
uv run alembic upgrade head
cd frontend
npm ci
npm run dev
```

On Windows use `npm.cmd` if PowerShell blocks npm.ps1. Backend commands run from the repository root.

## Environment settings

| Setting | Where | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Python `.env`; GitHub Actions secret for workers | Writable SQLAlchemy URL, `postgresql+psycopg://...` |
| `DATABASE_URL_ASYNC` | Python `.env`; GitHub Actions secret for workers | Same database, `postgresql+asyncpg://...` |
| `ODDS_API_KEY` | Python `.env`; GitHub Actions secret for workers | Live bookmaker quotes |
| `ANALYTICS_DATABASE_URL` | Python `.env` for hosted workers | Writable PostgreSQL audit/exposure storage; unset uses local SQLite. Actions sets this from `DATABASE_URL`. |
| `DATABASE_URL` | Vercel production environment | Server-only connection using a dedicated read-only database role, `postgresql://...` |
| `VERCEL_TOKEN` | GitHub Actions repository secret | Project-scoped deployment token |
| `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | GitHub Actions repository variables | Vercel team/project identifiers |
| `DATA_PIPELINE_ENABLED` | GitHub Actions repository variable | Set `true` only after migration, backfill, and live-data checks |
| `PUBLIC_DATA_PIPELINE_ENABLED` | GitHub Actions repository variable | Enable verified public-only Kalshi/schedule collection and daily stat refresh without supplying `ODDS_API_KEY` |
| `ODDS_DAILY_CREDIT_LIMIT` | GitHub Actions repository variable | Persistent provider credit ceiling; default 25 |

Optional Python settings are documented in `.env.example`: bankroll, Kelly multiplier, vig method, and experimental adjustments (off by default). Never use `NEXT_PUBLIC_` for credentials. Local `.env` files are not automatically uploaded to GitHub or Vercel.

The Vercel role needs SELECT only on `dashboard_snapshots` and the `dashboard_gamelogs` view; access to underlying game-log tables is denied. It does not need write or migration privileges. Keep owner/migration, restricted worker and read-only dashboard credentials separate.

## Data operations

After migrating, backfill the history before the first scan:

```sh
uv run python -m sportsbet.refresh --sport both --backfill
uv run python -m sportsbet.scan --sport both --daily-credit-limit 25
```

`refresh` selects season years from the current date, uses regular-season samples, and upserts stats to apply provider corrections. Initial NFL backfill covers three season years; NBA covers current/prior season. Daily refresh covers the active season. NFL schedules must be present for pre-game cutoffs.

The **Market data** Actions workflow offers `scan`, `refresh`, and `backfill` dispatches. When explicitly enabled, it refreshes stats daily and attempts scans every 30 minutes. Scans share a persistent daily credit budget and recommendation-exposure ledger. The default 25-credit ceiling does **not** cover a full slate repeatedly; a capped worker stops requesting additional events. Establish an appropriate provider plan and measured coverage before enabling schedules. Published quotes older than five minutes cannot recommend a stake.

The public website only reads results. It cannot start scans or spend provider credits. The older `scan_game_ev.py` remains a local NBA CLI; use `sportsbet.scan` for durable hosted snapshots.

## Model and metric contract

- The current `empirical-jeffreys-v3` cohort uses one shared NBA/NFL finite-sample estimator for per-game prop outcomes. It preserves observed push mass and uses a fixed Jeffreys half-count for decided Over/Under outcomes, preventing exact 0%/100% forecasts from finite histories. See [model and validation details](docs/model-validation.md).
- Target-date queries use only earlier game dates; the most recent 40 qualifying games are selected after filters. Missing or ambiguous player identities are skipped.
- Quotes must match player, event, market, line and Over/Under side. Synthetic PrizePicks payouts are not treated as bookmaker prices.
- `ev_pct` is probability edge, displayed in percentage points. `expected_return` is expected net return per unit stake at the quoted payout, including push refunds. Dollar expected profit is stake times expected return.
- A prop recommendation requires the requested side's 95% interval to clear the push-adjusted break-even probability. Fractional Kelly uses that interval's lower bound and the actual price; the displayed point expected return remains the model estimate. Missing, invalid, or overlapping uncertainty is audited without a recommendation. Exposure reservations are durable, atomic, and capped across rescans; recommendations are not executed bets.
- Every successfully evaluated selection is audited, including rejected estimates. Current-model predictions carry the verified provider-event and normalized quote-row commitments plus an explicit generation time; incomplete current-model evidence cannot enter metrics. Missing samples, expired quotes, started events, and risk gates cannot recommend stakes.
- ROI, hit rate, Brier score, log loss, calibration bins and CLV use explicit denominators and real settlements. No result is inferred from missing data. Pending, push and void outcomes are distinct.
- Hosted performance snapshots are filtered to the exact model version used by the scanner and display that cohort. The audit CLI can still inspect another explicit version or the combined history.
- Daily grading requires an exact final ESPN schedule team/date match and exactly one player-ID/stat match. Daily modes always use the previous seven Eastern dates and add at most seven unresolved older dates per run from a bounded 30-day ledger window, oldest first; monitor modes retain the current three-day schedule window. The dashboard receives only yesterday/today/tomorrow even when grading uses older evidence. New NBA.com and nflverse rows carry a canonical batch commitment and a reproducible typed settlement-row hash; ESPN fallback rows retain the raw-response hash and add the same row hash. Grading recomputes the row hash and retains the canonical schedule/stat evidence with provider, both hashes, observation time, stat-row identity, actual value, and final schedule identity. Performance reporting re-hashes that retained proof and recomputes the outcome from the exact stat, line, and side. Missing, manual, legacy, tampered, pregame, future, DNP, ambiguous, and nonfinal evidence stays pending. Canonical batch commitments bind normalized ingested records but cannot authenticate provider origin or replay unavailable raw provider bytes. This is observed-stat backtest grading; it does not confirm a sportsbook account settlement or cross-venue rule equivalence.
- Brier reports include fixed 0%, 50%, and 100% probability benchmarks plus the positive-outcome count on exactly the model-scored cohort. These expose class imbalance without fitting a reference to held-out labels. In unpriced Over-threshold checks, 0% means always Under and 100% means always Over. No scored forecasts means unavailable benchmarks, not zero error.
- Generic NFL play-success probability cannot be substituted for game-win probability. Experimental pace/rest/kinematic adjustments default off.

To export prediction IDs or record manual audit outcomes:

```sh
uv run python -m sportsbet.ledger --list
uv run python -m sportsbet.ledger --settlements outcomes.json
uv run python -m sportsbet.ledger --recommendations-only
uv run python -m sportsbet.ledger --model-version empirical-jeffreys-v3
```

`outcomes.json` maps prediction IDs to `true`, `false`, `"push"`, `"void"`, or `null`. Manual CLI settlements retain the input file hash for audit but stay unverified and cannot enter hosted performance metrics. Hosted metrics snapshots refresh on the next successful daily or scan worker run.
Reports retain the earliest eligible prediction per selection within the chosen
cohort. Audit timestamps require explicit timezones; conflicting retries cannot
replace recorded predictions. ROI is hypothetical recorded-stake replay, not
realized account profit. Model-version filtering keeps comparisons reproducible.

## Verification and deployment

Kalshi, sportsbook hedge, and PrizePicks entry analysis now share a separate
`market_analysis` LangGraph route with explicit payoff states, fee/capacity gates,
and bounded integer-lot optimization. See [market analysis architecture and research](docs/market-analysis.md)
for the read-only Kalshi collector, typed input contract, replay commands, and
remaining integration limits. These scenario results are not executed bets.

All commits and workflows belong to https://github.com/rahulp7801/Agentic-EV-analytics-platform. Work on feature branches, open a PR, then merge to `master` after required checks pass. Direct pushes and protection bypasses are prohibited. Production jobs only run from `master`.

Historical quote replay requires explicit input; it never generates example wins or prices:

```sh
uv run python -m sportsbet.quant.backtest --snapshots-file quotes.json --outcomes-file outcomes.json
# Or read recorded database quotes:
uv run python -m sportsbet.quant.backtest --database --outcomes-file outcomes.json
```

Quote rows require unique `id`, `game_id`, `sportsbook`, `market_type`, `outcome_name`, `price` (American), and timezone-aware `snapped_at`/`game_start_time`. Props additionally require `player_name` and `line`. Outcomes map the earliest snapshot ID for each exact selection to `true`, `false`, `"push"`, `"void"`, or `null`. Optional `model_probability` requires a `model_version` and timezone-aware `model_generated_at` no later than the entry quote; include `push_probability` for push markets. Missing probabilities cannot produce calibration. Optional `stake` defaults to one unit.

New player-prop rows must also contain a valid `Over`/`Under` side and a quote
time strictly before game start. The database enforces this for new writes with
an unvalidated check constraint, so historical incomplete rows remain preserved
but cannot be mistaken for replayable quotes.

The scheduled scanner appends each complete provider quote batch before it runs
the LangGraph model. If that archive write fails, the event cannot publish model
output. This builds a point-in-time dataset from future scans; it does not repair
or infer fields for old rows, and collection must remain disabled until its
credential and quota are ready.

Reports include input hashes, sample coverage, and an explicit evaluation scope. Empty usable datasets exit unsuccessfully with null performance metrics. Replay evaluates the supplied selections; it does not rerun the current model historically or establish profitability. Unit-test fixtures verify arithmetic only.

CI runs the Python suite, dependency audits, frontend metric/access tests, TypeScript/build checks, and an isolated PostgreSQL service for migrations, concurrency, stat upserts, and actual NFL/NBA graph SQL. Production deployment depends on these jobs. Its post-deploy gate requires public market, schedule, and game-log endpoints whenever public or full collection is enabled; paid signal, metric, scan, and prop-screen endpoints become mandatory with full collection. Vercel's root directory is `frontend`; automatic Git deployments are disabled so they cannot bypass CI. The CLI uses direct deployment because `vercel pull` currently rejects project-scoped tokens during team lookup.

```sh
uv run pytest -q
cd frontend
npm test
npx tsc --noEmit
npm run build
```

PostgreSQL tests require `SPORTSBET_TEST_DATABASE_URL` pointing to a **disposable** database. Tests never fall back to the runtime database. Pytest stores generated temporary files and cache under ignored `.local/` by default.

## Readiness still requiring evidence

Read-only market monitoring and reproducible observation replay:

```sh
uv run python -m sportsbet.market_watch --sport nfl --game-limit 20 --publish
uv run python -m sportsbet.market_watch --replay .local/market-watch/CAPTURE.json
uv run python -m sportsbet.ingestion.prizepicks --sport nba
```

Replay checks the evidence digest and recomputes comparisons without network
requests or publishing. A comparison mismatch exits with code2; preserve the
original archive and investigate the computation version before using that
report as validation evidence.

The dashboard's Arbitrage view reads published market observations. The monitor
captures one US sportsbook h2h request per sport (one budgeted Odds API credit),
up to 20 Kalshi games within seven days by default (configurable up to 40), and
one PrizePicks projection page. Kalshi discovery follows at most three pages of
500 milestones, then inspects at most three active markets per selected game.
Coverage reports discovered, inspected, quoted and failed games; discovery or
sampling limits remain explicit. A failed event or market preserves other valid
observations. It also reports bounded open player-prop inventory for four core NFL
and three core NBA series, linked only through structured milestone event IDs.
The private worker handoff retains those exact prop quotes and public Kalshi fee
terms for sportsbook comparison. The public prop-screen API exposes only fresh,
exact, non-executable gross gaps and validated one-contract fee-cost scenarios;
it never reports fee-adjusted or realized profit. Aggregate counts remain coverage
evidence. Quote freshness uses each comparison's oldest leg, not collection
completion time. Team matching uses captured
Kalshi structured targets, an ESPN team directory, and exact home/away/start
agreement. Matching names does not establish settlement equivalence. Gross gaps
exclude fees and tie/void scenarios; all comparisons remain unverified and no
orders are supported. PrizePicks HTTP403 remains an access limitation, never a
reason to substitute synthetic odds.

Daily prop scans publish per-league coverage at `/api/scans`: attempted/completed
games, missing estimates, budget exclusions, failures, and completion time. A
provider/model failure is isolated so other games and the other league continue.
Saved attempt times rotate limited credits across games and leagues; a successful
empty slate differs from a failed or interrupted scan. The dashboard marks old
scan reports stale and refreshes the signal ticker every30 seconds. This is
budgeted coverage, not a promise that every available market is scanned.

GitHub's **Market data → daily** operation runs a deterministic LangGraph workflow:
history refresh and market collection run independently, then eligible prop scans
run after both finish. A failed history refresh blocks that league's prop scan.
The half-hourly `monitor` operation refreshes market observations and requires a
successful history refresh within36 hours before running props. Market collection
continues when history is unavailable; interrupted refreshes still block props.
Each full run requests one budgeted sportsbook h2h snapshot per league before
props use the remaining daily/rolling allowance. Kalshi and PrizePicks collection
continue when that allowance is exhausted, and budget omissions remain degraded.
Both daily and monitor evidence archives pass the same secret gate before upload.
A completed refresh records a successful ingestion attempt; it does not
prove that the upstream provider has supplied every recently completed game.

Run it locally with `uv run python -m sportsbet.daily --sport both --mode daily`.
Per-stage results are persisted for diagnosis; degraded coverage makes the worker
exit unsuccessfully. Manual `scan` remains a maintenance operation that bypasses
the refresh-age gate. Scheduled daily/monitor runs remain disabled until hosted
database access and a manual production run are verified.

The independent `public_daily` and `public_monitor` operations use the same graph
without sportsbook requests or prop recommendations. Both publish ESPN schedules
and bounded public Kalshi observations; `public_daily` also refreshes NBA/NFL
history. Unrequested venues and partial sampling remain explicit. An `observed`
public run means the requested collection succeeded, not full market coverage or
season readiness. Provider failures still exit unsuccessfully.

After both manual public operations pass, set the repository variable
`PUBLIC_DATA_PIPELINE_ENABLED=true` to run `public_daily` at 13:17 UTC and
`public_monitor` at :07/:37 each hour. These jobs receive restricted database
credentials but no Odds API or Kalshi trading key. Full collection takes
precedence if `DATA_PIPELINE_ENABLED=true`; the public flag does not enable
sportsbook, PrizePicks or prop scans. Clear the public flag to stop its schedule.
Clean evidence passes the credential/secret scan before public artifact upload.
GitHub's periodic schedule is not continuous or low-latency arbitrage monitoring;
the dashboard continues to identify stale quotes between captures.

Paid requests share both a daily ceiling and `ODDS_ROLLING_CREDIT_LIMIT` (default450
credits across31 UTC dates), enforced atomically in the persistent ledger. This
counts this application's reservations, including failed requests, not usage by
other clients of the same API key or the provider's billing cycle. The free plan's
500 monthly credits cannot provide continuous full-slate prop coverage; see the
[provider's plans](https://the-odds-api.com/). Set limits deliberately for the
subscribed plan and measured coverage. Never clear usage records to reset a budget.

GitHub's **Market data → watch** operation publishes snapshots and retains public
evidence artifacts for90 days. Download archives for longer retention. Replay
checks the capture hash and recomputes the same comparisons without network
access; it does not infer fills or returns. Scheduled watch polling is not yet
enabled. The existing30-minute schedule is unsuitable for short-lived arbitrage.

Hosted credentials must use restricted roles from `python -m sportsbet.db.access`:
the dashboard receives only the reader's `DATABASE_URL`; the worker receives
its own `DATABASE_URL` and `DATABASE_URL_ASYNC` as repository secrets. Keep owner
credentials local. For IPv4-only Vercel/GitHub runners, use the provider's exact
Supabase **Session pooler** host and role/project username, with verified TLS;
the local direct IPv6 endpoint cannot serve these runners. Never commit generated
credentials or private keys.

The hosted game-log browser reads `dashboard_gamelogs`, a restricted view of public
NBA/NFL statistics (migration0012). It cannot read the underlying stat tables or
prediction audit. Local Next.js development also requires a database URL with
permission to read this view. Displayed over frequency excludes missing stats and
ties and applies only to the shown rows; it is not a model performance metric.

Hosted schedules come from worker-published ESPN snapshots, refreshed by daily
and monitor operations. Missing, failed, wrong-date or older-than90-minute
snapshots return unavailable status. The browser does not rely on Vercel reaching
the upstream schedule service. Hosted NBA and NFL refreshes have completed, but
each current run still fails closed if its league refresh is unavailable.

Free historical outcomes can be collected and used to verify the actual graph:

```sh
uv run python -m sportsbet.ingestion.espn_history --sport nba --start 2026-01-28 --end 2026-01-28 --output .local/history/nba
uv run python -m sportsbet.quant.walkforward --dataset .local/history/nba/dataset.json --prop points --threshold 20.5 --output .local/history/nba-report.json
```

The collector caches ESPN final box scores with source URLs, retrieval times and hashes; requests cover at most31 days at a time. `walkforward` requires the corresponding PostgreSQL history and runs the same LangGraph quant nodes used by scans. Its threshold is an explicit research benchmark, not an invented sportsbook line. It reports excluded identities/small samples, calibration, dataset/code hashes, and null ROI/CLV. A small pilot is not proof of an edge.

The site and protected CI/CD deployment are live. Supabase is migrated with
separate restricted worker and read-only dashboard roles, NBA history is
preserved, and2023-2025NFL stats are backfilled. Public-only hosted monitoring
has replayed exactly against production. Full sportsbook collection still needs
verified Odds-key rotation, a suitable quota, and measured slate coverage; the
GitHub scheduler has not demonstrated reliable30-minute cadence.

Venue-specific settlement equivalence, robust historical injury/roster context, NFL game-log presentation, full-slate refresh coverage, and out-of-sample calibration/profitability remain unfinished. A green deployment or unit test is not evidence of model accuracy. Maintain current findings and constraints in `CLAUDE.md`.

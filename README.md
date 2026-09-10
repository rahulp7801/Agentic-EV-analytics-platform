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
| `ODDS_DAILY_CREDIT_LIMIT` | GitHub Actions repository variable | Persistent provider credit ceiling; default 25 |

Optional Python settings are documented in `.env.example`: bankroll, Kelly multiplier, vig method, and experimental adjustments (off by default). Never use `NEXT_PUBLIC_` for credentials. Local `.env` files are not automatically uploaded to GitHub or Vercel.

The Vercel role needs SELECT on `dashboard_snapshots` and the game-log tables exposed by read routes; it does not need write or migration privileges. Create/configure that role through your database provider. Keep the migration/worker credential separate.

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

- Target-date queries use only earlier game dates; the most recent 40 qualifying games are selected after filters. Missing or ambiguous player identities are skipped.
- Quotes must match player, event, market, line and Over/Under side. Synthetic PrizePicks payouts are not treated as bookmaker prices.
- `ev_pct` is probability edge, displayed in percentage points. `expected_return` is expected net return per unit stake at the quoted payout, including push refunds. Dollar expected profit is stake times expected return.
- Fractional Kelly uses the actual price. Exposure reservations are durable, atomic, and capped across rescans; recommendations are not executed bets.
- Every successfully evaluated selection is audited, including rejected estimates. Missing samples, expired quotes, started events, and risk gates cannot recommend stakes.
- ROI, hit rate, Brier score, log loss, calibration bins and CLV use explicit denominators and real settlements. No result is inferred from missing data. Pending, push and void outcomes are distinct.
- Generic NFL play-success probability cannot be substituted for game-win probability. Experimental pace/rest/kinematic adjustments default off.

To export prediction IDs or record independently verified settlements:

```sh
uv run python -m sportsbet.ledger --list
uv run python -m sportsbet.ledger --settlements outcomes.json
uv run python -m sportsbet.ledger --recommendations-only
```

`outcomes.json` maps prediction IDs to `true`, `false`, `"push"`, `"void"`, or `null`. Hosted metrics snapshots refresh on the next successful worker run.

## Verification and deployment

All commits and workflows belong to https://github.com/rahulp7801/Agentic-EV-analytics-platform. Work on feature branches, open a PR, then merge to `master` after required checks pass. Direct pushes and protection bypasses are prohibited. Production jobs only run from `master`.

Historical quote replay requires explicit input; it never generates example wins or prices:

```sh
uv run python -m sportsbet.quant.backtest --snapshots-file quotes.json --outcomes-file outcomes.json
# Or read recorded database quotes:
uv run python -m sportsbet.quant.backtest --database --outcomes-file outcomes.json
```

Quote rows require unique `id`, `game_id`, `sportsbook`, `market_type`, `outcome_name`, `price` (American), and timezone-aware `snapped_at`/`game_start_time`. Props additionally require `player_name` and `line`. Outcomes map the earliest snapshot ID for each exact selection to `true`, `false`, `"push"`, `"void"`, or `null`. Optional `model_probability` requires a `model_version` and timezone-aware `model_generated_at` no later than the entry quote; include `push_probability` for push markets. Missing probabilities cannot produce calibration. Optional `stake` defaults to one unit.

Reports include input hashes, sample coverage, and an explicit evaluation scope. Empty usable datasets exit unsuccessfully with null performance metrics. Replay evaluates the supplied selections; it does not rerun the current model historically or establish profitability. Unit-test fixtures verify arithmetic only.

CI runs the Python suite, dependency audits, frontend metric/access tests, TypeScript/build checks, and an isolated PostgreSQL service for migrations, concurrency, stat upserts, and actual NFL/NBA graph SQL. Production deployment depends on these jobs. Vercel's root directory is `frontend`; automatic Git deployments are disabled so they cannot bypass CI. The CLI uses direct deployment because `vercel pull` currently rejects project-scoped tokens during team lookup.

```sh
uv run pytest -q
cd frontend
npm test
npx tsc --noEmit
npm run build
```

PostgreSQL tests require `SPORTSBET_TEST_DATABASE_URL` pointing to a **disposable** database. Tests never fall back to the runtime database. Pytest stores generated temporary files and cache under ignored `.local/` by default.

## Readiness still requiring evidence

The site and CI/CD deploy successfully. Live-data readiness requires a reachable production database, migrated/backfilled data, the Vercel read-only URL, and worker secrets. At the last verification the supplied runtime database was unreachable; data APIs correctly returned a generic unavailable response.

Automatic settlement, robust historical injury/roster context, NFL game-log presentation, full-slate refresh coverage, and out-of-sample calibration/profitability remain unfinished. A green deployment or unit test is not evidence of model accuracy. Maintain current findings and constraints in `CLAUDE.md`.

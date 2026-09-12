# Python worker deployment

Vercel continues to serve the read-only frontend. `Dockerfile.worker` packages the existing Python CLI and LangGraph computation for a separate container scheduler. It introduces no second model implementation, web server, custom cron loop, or order endpoint.

The current GitHub schedule has produced successful runs but also multi-hour gaps. An active workflow and one successful automatic run do not prove reliable cadence. GitHub documents that scheduled jobs can be [delayed or dropped under load](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule). Keep the dashboard's freshness gates enabled.

## Image contract

- Immutable official Python and uv image digests; runtime dependencies resolved from `uv.lock` with `--locked`, no editable install or development dependencies.
- Non-root UID/GID `10001`; package files are root-owned. Public database CA included. Source checkout, frontend, Git history and credentials are absent from the final image.
- Default-deny `.dockerignore` admits only the packaging files, named Python package directories, Python source and public CA. Add new package directories explicitly. CI injects harmless secret-shaped files and tests the actual Docker build context excludes them.
- `.local/` is the working evidence/cache directory. Supply durable private storage at `/app/.local` when captures must survive container replacement. The image does not upload arbitrary files or expose this directory over HTTP.
- Runtime needs outbound HTTPS to the supported public providers and verified PostgreSQL connectivity. No listening port is needed.
- CI runs the final image with networking disabled, a read-only root filesystem, dropped capabilities and writable temporary evidence storage. It imports the real CLIs and executes the actual LangGraph/SciPy solver on an explicitly synthetic arithmetic fixture. This test is not a provider test or return estimate.

```sh
docker build --file Dockerfile.worker --tag sportsbet-worker:reviewed .
docker run --rm --init --cap-drop ALL --security-opt no-new-privileges \
  --env-file /secure/worker.env \
  --mount type=bind,src=/secure/worker-evidence,dst=/app/.local \
  sportsbet-worker:reviewed
```

Provision the private evidence directory for UID/GID `10001` before starting the container. Do not mount the repository or the development `.env`. Set only the restricted **sportsbet_worker** connection strings:

| Variable | Required value |
| --- | --- |
| `DATABASE_URL` | Worker synchronous URL with verified TLS and `sslrootcert=certs/supabase-prod-ca-2021.crt` |
| `DATABASE_URL_ASYNC` | Matching worker asynchronous URL |
| `ANALYTICS_DATABASE_URL` | Same restricted synchronous URL, to prevent local SQLite fallback |
| `EXPERIMENTAL_PROBABILITY_ADJUSTMENTS` | `false` |

No Odds API or Kalshi trading credential is required for public-only operation. Do not supply the development owner credentials. The previously exposed Odds key must remain unused; full-provider activation requires verified replacement and provider readiness.

## Scheduled commands and cutover

The default command performs one `public_monitor` run for both sports and exits. Configure the host to run it periodically; successful completion does not leave a daemon running. A separate daily command refreshes history as well:

```sh
python -m sportsbet.daily --mode public_monitor --sport both
python -m sportsbet.daily --mode public_daily --sport both
```

Use one active scheduler and serialize the two commands. Do not independently run two scheduler services that can overlap. On an existing server, one OS scheduler with a common process lock can supervise both. Configure bounded execution time, failure notifications and private evidence retention. These obligations are not implemented by a Docker image alone.

Cut over only after a hosted public monitor and daily refresh both pass, their archives replay, production matches the captures, and an automatic host-triggered run is observed. Then unset `PUBLIC_DATA_PIPELINE_ENABLED` in GitHub to stop duplicate scheduled collection; keep manual Actions runs available for recovery. Keep `DATA_PIPELINE_ENABLED` off until full-provider readiness is verified. Roll back by disabling the new schedule before restoring the public GitHub flag.

## Hosting decision remains open

No new service, billing plan or credential transfer has been activated by this change. A portable image can run on an existing server or a managed container host. As a possible managed option, [Render cron jobs](https://render.com/docs/cronjobs) support Docker and prevent overlap within one job; that guarantee does not serialize two separate jobs. Render currently bills for active compute with a $1/month minimum **per cron service**, plus any applicable workspace/platform charges. A continuously running background worker has different costs. Confirm the selected design and total cost before activation.

CI validates image behavior; actual host startup, scheduling, resource usage, durable evidence storage and provider connectivity must still be verified after a host is selected. No continuous monitoring or deployment readiness is inferred from a successful image build.

# Collection readiness beside the pick board — 2026-09-23

## Production findings (read-only)

The latest recorded scan finished around 13:33 UTC. NBA had zero eligible events;
NFL and CFB each had one event waiting for a permitted quote check. Their stored
check times were 13:43 UTC and 17:07 UTC respectively. Both were already due at
inspection. The later 15:09 workflow run updated history/player profiles rather
than producing a newer scan snapshot. Existing quota usage was 11 credits against
the configured daily cap of 20; no quota or holdback change was made.

These observations identify missing recent collection, not a new verdict about
model quality. They do not establish why GitHub has not run a newer scanner.

## Consumer changes

- Place the selected league's collection status directly above the pick board,
  with responsive desktop/mobile layout. It no longer requires opening a details
  disclosure. The disclosure still contains the market-source explanation.
- Keep a due quote check visible as overdue after the scan snapshot becomes stale.
  Display its date and time. This is an earliest permitted check, not a promise
  that a scheduler will run at that exact time.
- Describe an empty board without implying the model evaluated and rejected
  every line. Point to collection status, missing quotes, and evidence gates.
- Bound status requests to 15 seconds and continue using the existing minute poll.
  These read the existing dashboard endpoint; they do not start provider scans.

## Status contract hardening

Missing coverage or missing model counts remain null, rather than being summed
as zero. Malformed coverage cannot crash the shared league-status endpoint.
Counts must be safe nonnegative integers. Per-event model funnels must be valid;
contradictions cannot cancel out when totals are combined. Completed events with
no retained coverage are unknown; an explicit zero-quote record remains distinct.
Timestamp parsing requires a timezone and quote-check dates are bounded relative
to their originating scan. Missing, interrupted, stale, failed, budget-limited,
scheduled, overdue, no-game, and no-quote states remain distinct.

## Verification

- Four newly failing regression groups reproduced the original status defects.
- All 168 frontend tests pass locally; typecheck and lint pass.
- Isolated browser checks at 1440px and 390px show one visible status rail with the
  details disclosure closed, the overdue date, and the neutral empty state.
  No page errors, document overflow, or status-rail overflow. Both screenshots
  were visually inspected. Browser API responses were synthetic and all external
  requests were blocked.
- Full backend, PostgreSQL, worker-image, build, security, and production readiness
  checks gate release through the existing pipeline.

## Limits

This phase makes collection delays and incomplete evidence visible. It does not
repair GitHub scheduling, issue a paid refresh, spend credits, change the frozen
model, lower qualification thresholds, or create new evidence of an edge. The
existing scheduled collector must still capture fresh prospective samples.

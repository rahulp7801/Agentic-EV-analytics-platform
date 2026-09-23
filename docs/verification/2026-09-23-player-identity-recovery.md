# Source-backed NFL player resolution — 2026-09-23

## Observed production gap

The latest retained NFL event contained 111 selections for 14 quoted players.
The scanner resolved 13 players and modeled 107 selections. Four selections were
excluded as `unknown_or_ambiguous_player` because the quote said **Brian Robinson
Jr.** while the database retained **Brian Robinson** under GSIS `00-0037746`.
A read-only query found 48 history rows for that ID.

A fresh check of free ESPN roster and nflverse identity sources at
2026-09-23T18:40:17.431296+00:00 confirmed the exact chain:

- Quoted roster name: Brian Robinson Jr..
- Event roster team: Atlanta Falcons.
- ESPN roster ID: 4241474.
- Published crosswalk GSIS ID: 00-0037746.
- Roster source: https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/1/roster.
- Roster SHA-256: `d419f764aa1e61ad84918698cd3d150f5373c4630d0bee42f4c0faffc891f83a`.
- Identity source: https://github.com/nflverse/nflverse-data/releases/download/players/players.csv.
- Identity SHA-256: `4dd70f328f31b0bb7cbf043412298d5a325863e27b8f2eeea22c9e925c808dee`.

This is present-day identity evidence. It does not backdate a forecast, assert
historical source availability, or establish that the player's offers qualify.

## Repair

NFL quote scans load the existing free crosswalk whenever quoted player names
are supplied, including when those names already match ESPN rosters. The scanner
binds an exact roster display name to GSIS through that crosswalk, with fresh
source timestamps, expected source URLs and digests, exact event teams, and
bounded one-to-one mappings. No suffix stripping or fuzzy name search is used.

One batched history lookup accepts either the existing exact name or the verified
GSIS ID. A recovered identity must actually have history. Conflicting name/ID
matches and ambiguous histories stay excluded. Two different quoted names that
resolve to one athlete are excluded together, so aliases cannot acquire separate
risk allocations. Existing exact-name resolution remains available when no
verified roster binding exists.

The immutable prediction retains the roster/crosswalk binding and source digests
as `player_identity_evidence`. The original quoted name and quote commitment stay
intact; the stable history ID continues through the model and settlement paths.
All sample, quote-age, availability, teammate-context, edge and risk gates remain.
Frozen shadow coefficients, implementation files and board cutoff are unchanged.

## Verification and limits

- 82 focused identity, scheduled-model, and availability tests passed locally.
- Tests cover stale/future/missing evidence, incorrect sources and teams, malformed
  or duplicate IDs, ambiguous names, absent history, conflicting identities,
  duplicate quoted aliases, immutable source evidence, and blocked subject or
  teammate availability.
- The real free-source identity check resolved the observed missing player to
  those 48 history rows. Provider quote APIs were not called and the production
  database was accessed only through explicitly read-only transactions.
- Full CI checks the broader backend, PostgreSQL, frontend and worker packaging
  before release. New live model coverage must be observed on a later ordinary
  scan; existing expired quotes are not relabeled as current.

No purchase, card use, odds-credit consumption, wager, budget increase, fabricated
history, lowered qualification threshold, or model-edge claim occurred.

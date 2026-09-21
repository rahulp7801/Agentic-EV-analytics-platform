# Slip builder checkpoint

## Product contract

The slip builder is a read-only decision aid for the pregame pick board. It never
submits an order, refreshes a provider, or creates a pick. Every selectable leg
must already have passed the server-side `pregame-t60-v1` board contract and the
`confidence-floor-v2` recommendation policy.

The first release supports NFL, NBA, and CFB and keeps the existing `#sport/parlay`
URL for bookmarked links. The visible product name is **Slip builder**.

## Assistance

The assistant is deterministic and evidence-grounded:

- **Balanced** ranks the confidence-floor margin first, prefers separate games, and
  keeps the build to three legs.
- **Conservative** uses at most two of the highest model-probability approved legs.
- **Diversified** maximizes distinct games before using another leg from a game.
- At most four legs are selected. Duplicate player/game exposure is rejected.
- The explanation names the actual selection rule, model probabilities, evidence
  state, and any same-game or same-team dependence that the model has not estimated.

The assistant is not a chat model and does not infer an injury adjustment. Injury,
roster, and teammate evidence remains visible as screening evidence only unless a
future validated model explicitly adjusts the probability.

## Probability and price rules

- Individual model probabilities remain visible with their confidence floors.
- A multi-leg view shows the Fréchet lower/upper dependence bounds and labels the
  product of probabilities as an independence scenario, not a joint forecast.
- Expected return appears only after the user enters an offered total return for
  the exact slip. Recorded single-leg prices are never silently combined into a
  currently executable payout.
- Recorded picks require repricing. Locked picks stay frozen at T-60. Started
  games cannot enter the public pick board.

## Security and scale

- State is local to the page and is not persisted or sent to a new endpoint.
- The feature performs one bounded same-origin `/api/picks?sport=` read and does
  not fan out to providers or consume paid quota.
- User input is numeric, bounded, and rendered as text. No HTML injection, dynamic
  URL, credential, database write, or order path is introduced.
- Loading uses skeletons; empty and error states fail closed.

## Verification gate

Unit tests cover candidate validation, mode selection, exposure limits, dependence
warnings, and payout bounds. The frontend typecheck, lint, production build, full
test suite, dependency audits, static security scans, and a production-mode
Playwright pass at desktop and mobile widths must pass before merge.

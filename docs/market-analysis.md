# Market analysis architecture and evidence

Research reviewed September 10, 2026. This is a software platform: historical
evaluation validates the same production computation paths, rather than becoming
a separate strategy implementation. No live order execution is authorized or implemented.

## Decisions

Keep LangGraph, PostgreSQL, and the existing Python worker / Next.js separation.
Use typed, bounded specialist workflows for sportsbook hedges, Kalshi comparisons,
and PrizePicks entries. Reuse deterministic payoff and risk computation across
specialists. Model-based EV and matched-portfolio arbitrage are different outputs;
the legacy `arbitrage_agent` name currently describes model EV, not a hedge.

The exchange reader archives market metadata, original parsed order books, hash,
request-start / receive timestamps, fractional depth, and the pagination cursor.
Observation timestamps are not provider update timestamps. YES asks derive from
NO bids; counting both representations as separate liquidity would be wrong.
Only GET requests to fixed official hosts are implemented, with redirects disabled.
Production and demo credentials never fall back to one another. Public data needs
no credentials. RSA signing uses cryptography rather than homemade cryptography.
See [Kalshi authentication](https://docs.kalshi.com/getting_started/api_keys) and
[order-book schema](https://docs.kalshi.com/getting_started/orderbook_responses).

```powershell
.venv/Scripts/python.exe -m sportsbet.ingestion.kalshi --series KXNFLGAME --limit 5 --check-auth
```

Output defaults to a unique timestamped archive under ignored `.local/kalshi/`.
Explicit output paths must be new files; repeated captures never overwrite history.
This is a bounded
sample, not complete coverage, a historical replay, or evidence of an executable hedge.

## Implemented specialist route

`request_type="market_analysis"` on the existing graph validates a
`MarketAnalysisRequest`, runs sportsbook, Kalshi, and PrizePicks specialists in
parallel, then joins their reports. Each candidate belongs to exactly one specialist;
mixed PrizePicks entries take priority, then Kalshi comparisons, then sportsbook-only
portfolios. These are deterministic specialists, not autonomous LLM traders.

Candidate failures are isolated within each specialist. An optimizer exception,
incomplete solve, or invalid returned solution marks that candidate failed and
the report degraded, while preserving other candidates. The CLI writes the
partial report and exits2 for technical failures; stdout contains the JSON status
and graph diagnostics go to stderr. Missing fees/capacity or settlement review
are explicit blocked analyses, not technical failures or zero-profit estimates.

The model routes likewise return stable failure codes and log exception types,
without raw validation/driver messages or tracebacks. Invalid prop input clears
the earlier estimate in graph state; downstream prop analysis suppresses signals
while an error is present. A request that enters with an existing error clears
previous signal outputs before the router terminates. The caller must explicitly
clear a prior error when beginning a fresh request; these fixes do not silently
treat a failed request as successful or change valid model probabilities.

`arbitrage/portfolio.py` solves a bounded long-only integer-lot payoff problem with
SciPy/HiGHS. It maximizes the minimum supplied-state profit under the candidate
budget, per-tranche capacity, unit steps, and explicit fee upper bounds. The
input contract supports unit steps of at least 0.0001, with bounded amounts and
at most 16 legs / 256 states per candidate to constrain solver resource use. The
two-second solver deadline fails closed. Decimal recomputation checks the returned
budget, depth, and payoffs. There is no assumed short sale or reuse of capital.
Each solve uses one native HiGHS thread: the graph already parallelizes independent
work. Default native scheduling stalled repeated mixed graph/direct calls on
Windows; 60 graph invocations / 200 mixed solves completed after this change.
A subprocess regression bounds repeated worker lifecycles. This follows the
[HiGHS parallelism guidance](https://ergo-code.github.io/HiGHS/dev/parallel/);
it does not claim the solver's own time limit can interrupt every native failure.

Each leg requires venue/account/quote identity, source hash, rule reference,
observation and availability times, actual event start, cost, unit step, and a
payout for every supplied settlement state. Unknown fees, capacity, or coverage
review block analysis. So do stale/future quotes, excessive time skew, and started
events. A coverage reference is trusted caller evidence, **not automatic proof**
of complete rules. Independent candidate results cannot be summed into portfolio
profit. Even a positive `scenario_edge` always has `execution_ready=false`.

```powershell
# Explicit, locally reviewed payoff inputs; current-clock freshness checks:
.venv/Scripts/python.exe -m sportsbet.market_analysis --input .local/candidates.json
# Same graph, archived clock and explicit outcome evidence:
.venv/Scripts/python.exe -m sportsbet.market_analysis --input .local/candidates.json --replay --settlements .local/settlements.json
```

The input schema is `MarketAnalysisRequest` in `arbitrage/portfolio.py`. Settlements
map candidate IDs to `state`, `source_ref`, and timezone-aware `resolved_at`. The
replay reports individual simulated payoff bounds, source/code hashes, and missing
settlements; realized ROI remains null. It does not invent fills or execution latency.
Synthetic test fixtures validate arithmetic and graph routing only. The production
scanner now creates exact, non-executable price screens for sportsbook pairs and
Kalshi/sportsbook props. It still does not turn those screens into optimizer
candidates because account capacity and settlement-state equivalence are unresolved.
PrizePicks entries are not automatically converted. Raw Kalshi archives must not
be described as executable inputs.

## Research that changes implementation

| Primary source | Finding and engineering consequence |
| --- | --- |
| [Unravelling the Probabilistic Forest](https://arxiv.org/abs/2508.03474) | Within-market and related-market payoff relationships can expose discrepancies. Candidate retrieval can be approximate; payout equivalence must be checked explicitly. This Polymarket study is not evidence of Kalshi returns. |
| [Arbitrage Analysis in Polymarket NBA Markets](https://arxiv.org/html/2605.00864v1) | In-game opportunities were rare, brief, and depth constrained; postgame artifacts distort apparent results. Use contemporaneous executable asks, depth, and pregame cutoffs. A 30-minute Actions schedule cannot compete for second-scale opportunities. |
| [Executable Arbitrage and Market Efficiency](https://arxiv.org/html/2608.00666v1) | Algebraically equivalent payoffs do not imply available, reversible protocol operations. Do not assume shorting, cross-venue netting, instantaneous settlement, or capital reuse. |
| [Prices, Probabilities, and Parlays](https://arxiv.org/abs/2607.14430) | Calibration depends on time horizon and product; multiplying marginal probabilities is not a validated joint model. Test calibration on held-out periods, and keep dependence assumptions explicit. |

These are research findings, not validated performance of this repository.

## Settlement and fees are part of the contract

The live KXNFLGAME series points to
[FOOTBALLGAMEWIN terms](https://assets.kalshi.com/contract_terms/FOOTBALLGAMEWIN.pdf).
Full-game overtime is included. A two-team tie can resolve team strikes at 0.50;
a separately listed tie strike changes that behavior. Some cancellations,
postponements and venue changes resolve at a Kalshi-determined fair market price.
Therefore a team name and kickoff match alone cannot establish equivalence to a
sportsbook moneyline. Archive the exact market rules and include exceptional
states or conservative payout bounds. Unknown rules must block an arbitrage claim.

The [July 7, 2026 fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf)
uses quadratic fees with series multipliers and differing maker/taker treatment.
Its centicent rounding text and cent-rounded example tables warrant explicit
verification before implementing exact fee accounting. The reader records live
series fee metadata; it does not infer zero fees or use one universal constant.

September 11 follow-up: the official [fee rounding guide](https://docs.kalshi.com/getting_started/fee_rounding)
explains the difference: direct accounts align balances to $0.0001; non-direct
accounts align to $0.01. The trade fee first rounds upward to six decimal dollars,
then the total signed balance change is aligned. An order accumulator rebates
rounding across fills. The dashboard now shows separate single-fill exchange-cost
scenarios for both account types, with zero prior accumulator, one contract per
Kalshi leg and sufficient displayed depth. These use the documented July 7
quadratic taker formula. They exclude sportsbook, FCM, funding and exceptional
settlement charges and are not profit bounds or inputs to the optimizer's
`fee_per_unit_bound`. Multi-fill execution needs actual accumulator evidence.

[Event fee overrides](https://docs.kalshi.com/api-reference/events/get-event-fee-changes)
take precedence over series metadata. The collector captures public series fee
history and event changes; a remaining event-history cursor, conflicting changes,
stale/future context or an unknown fee model disables the scenario. A latest
effective null/null event change clears the override. Future changes cannot be
applied early, and a series transition during collection requires a refresh.
Current fee metadata is not historical evidence for old quotes. The scenario
declares the formula's effective date; formula changes need a reviewed code update.
Direct retrieval of the PDF returned HTTP429 during this check; no access-control
bypass or invented document hash was used. The current PDF and rounding rules
were readable through the public documentation browser.

PrizePicks Player Picks are whole entries, not independently priced sportsbook
legs. Require the actual entry payout schedule, product, selection types, rules,
and observation time. [Current potential outcomes](https://www.prizepicks.com/help-center/potential-outcomes)
include product-specific conditions. [DNPs, Reboots and Ties](https://www.prizepicks.com/help-center/dnps-reboots-and-ties)
affect payouts differently, including More-only reboot treatment and lineup
eligibility. Never turn an unavailable price into -110 or assume independent legs.
Unknown entry payouts or joint outcomes must remain unavailable, not estimated
using a generic payout table. PrizePicks Team/Culture contracts are a separate product.

## GitHub projects reviewed

- [TradingAgents](https://github.com/TauricResearch/TradingAgents) already uses
  LangGraph. Borrow structured specialist outputs, traceability, and point-in-time
  discipline; importing another trading framework would duplicate orchestration.
- [AutoHedge](https://github.com/The-Swarm-Corporation/AutoHedge) appeared on the
  [weekly Python trending list](https://github.com/trending/python?since=weekly).
  Its quant/risk/execution separation is useful, but its venues and dependency
  stack do not directly solve NFL/NBA market matching. No wholesale dependency added.
- [prediction-market-arbitrage-bot](https://github.com/realfishsam/prediction-market-arbitrage-bot)
  illustrates candidate matching; its README explicitly omits fees and slippage.
  Do not adopt that execution policy or treat fuzzy matching as settlement proof.

## Runtime boundaries and remaining work

Version-2 market-watch captures include size scenarios for 1, 10 and 100
contracts per Kalshi leg. The calculation consumes the captured asks from best
to worse prices and omits any size without enough displayed depth. Each consumed
level is modeled as one taker fill. The exchange's
[order-wide fee accumulator](https://docs.kalshi.com/getting_started/fee_rounding)
carries rounding overpayment between fills; rebates are limited by each fill's
fees. Each leg has a separate accumulator, initially zero. Direct and non-direct
balance precision remain separate scenarios, not an inferred account setting.

These are conditional cost simulations. Actual fill fragmentation can change
fees even at the same price; displayed depth is not a fill commitment. Sportsbook
prices are scaled to the comparison's payoff size without asserting available
limits. FCM/funding fees and exceptional settlement charges are excluded. Do not
pass these costs to the optimizer as guaranteed fee bounds or report them as
realized profit. Version-1 captures retain their original comparison behavior
for reproducible replay.

The read-only `sportsbet.market_watch` collector now publishes source status and
price-screening comparisons to `/api/markets`. It archives the source evidence
before publication and supports hash-checked offline observation replay. This
screening stage does not supply invented fees, capacities, or settlement payouts
to the optimizer. Reviewed payoff candidates still use the existing LangGraph
analysis route. Source failures are independent and visible.

Kalshi [milestones and structured targets](https://docs.kalshi.com/getting_started/targets_and_milestones)
provide start times and team identities. A live probe found the documented
`competition=Pro Football` example returned no milestones while `competition=NFL`
returned31; the reader uses league codes and validates the returned league.
Exact captured team-directory aliases and start times produced real cross-venue
matches. No ticker-date parsing, fuzzy name matching, or close-time-as-kickoff
substitution is used. Matching events still require separate settlement review.

The periodic collector also inventories the core player-prop series already used
by the historical collector: NFL passing yards, rushing yards, receiving yards,
and receptions; NBA points, rebounds, and assists. It follows at most three pages
of 1,000 open markets per series, validates active binary one-dollar market and
event identities, and links events only through each selected structured game
milestone's `related_event_tickers`. The dashboard reports series, market, and
linked-event counts plus whether every cursor was exhausted. Full provider pages
are hashed and discarded. The immutable research archive retains the exact primary
and secondary settlement rules for each linked contract so its rule hash remains
reproducible. The compact hosted worker handoff strips that text and keeps the hash.
A compact quote record for every linked contract also
retains the structured player/team target IDs, numeric strike, milestone kickoff,
market occurrence time, request interval, raw-market/rule/page hashes, and listed
top-of-book ask price and size. The asks are checked against complementary bids as
specified by Kalshi's [order-book documentation](https://docs.kalshi.com/getting_started/orderbook_responses).
This uses the already-fetched [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets)
pages, avoiding thousands of extra order-book calls. Missing one-sided liquidity
is preserved as missing; inconsistent prices, identities, UUIDs, rules, or pages
degrade the source instead of producing a quote.

A September 12 NFL capture retained and hash-verified exact rules for all 3,081
linked prop quotes while the stripped worker handoff remained about 3.1 MB. The
rules describe a fair-market-price resolution when an active player never takes a
snap. Overtime, stat corrections, and sportsbook-specific void treatment still
need explicit matching, so this evidence does not establish settlement equivalence.

Each linked prop event also gets a bounded public fee-evidence read before its
market quotes. The internal version-2 handoff retains only current series terms,
historical scheduled changes, event overrides, timestamps, and source hashes.
Fee reads use at most eight concurrent requests. Missing fee evidence is reported
separately and preserves the gross quote inventory. When the fee history is
complete, unambiguous, older than the quote, and fresh, the exact prop matcher
adds direct-account and non-direct-account cost scenarios for one displayed
contract. Active fee waivers and displayed size below one contract suppress the
scenario. The public API exposes only the modeled Kalshi exchange fee, combined
cost, and scope; it does not expose raw fee evidence or label the result profit.
Settlement equivalence, sportsbook limits, actual fills, and realized profit
remain false or unavailable.

`occurrence_datetime` is retained as market metadata and is not used as kickoff.
In a real NFL sample it was three hours after the linked milestone start. The
milestone remains the documented structured game relationship. The collector
resolves every distinct player UUID with one public bulk structured-target request,
requires the exact requested ID set with no cursor, and validates player type,
league, and team before retaining the canonical Kalshi name. Targets are stored
once by UUID rather than copied into every contract. Cross-provider identity and
settlement equivalence remain unresolved: a later exact sportsbook match must
re-fetch and review the contract rules and check DNP/void and stat-provider
treatment. One listed level is displayed depth, not a fill, and every normalized
record has `settlement_equivalent=false` and `execution_ready=false`.

On September 12, 2026, a real public NFL run exhausted all four series and found
3,073 open contracts across 56 prop events, all linked to 15 upcoming structured
games. A later run through the normalized quote path retained all 3,073 records;
2,878 had top-of-book liquidity on both sides and 195 were one-sided. The compact
uncompressed evidence was about 3.15 MB and required only the four paginated series
reads. One sampled list quote matched the full public order book. The three core
NBA series were empty during the offseason. These observations establish source
coverage and schema consistency at that time, not an edge or profitability.

Research agents may eventually propose mappings and summarize rules with source
references. They must not invent prices, probability calibration, fills, or
settlement equivalence. The current graph uses deterministic Python specialists,
not LLM calls. No LLM provider key is currently required.

Vercel serves the read-only dashboard. Python workers collect data and run models;
PostgreSQL stores append-only observations, decisions, settlements, and exposure.
A continuously running worker with WebSocket reconnect/sequence recovery is needed
before low-latency arbitrage monitoring. Do not run that worker in a Vercel request.
SQLite checkpoints remain local-only; distributed workers need durable checkpoint
storage and idempotent writes before multiple replicas are enabled.

When publication is requested, the collector also writes `kalshi-props:{sport}`
as an internal worker snapshot in PostgreSQL. It contains only normalized prop
quotes, player targets, exact milestone context, and exact team aliases; raw game
markets, full order books, and the ESPN directory are omitted. The public markets
API reads a different fixed snapshot key and does not expose this payload. The
handoff has its own schema version and evidence hash. A Kalshi failure replaces it
with an unavailable record instead of allowing a later sportsbook scan to reuse
stale quotes. A real NFL collection produced 3,073 quotes, 190 normalized player
targets, and complete exact aliases for all 15 game contexts in about 3.24 MB.
Every handoff remains `execution_ready=false`.

Automatic cross-venue contract mapping, sportsbook account limits, exact fee
reconciliation, PrizePicks entry ingestion, joint calibration, and fill simulation
remain prerequisites for executable recommendations. Quoted size is not a fill.
Multiple independently optimized candidates must not share the same bankroll or
liquidity without a portfolio-level reservation.

The paid sportsbook scan now performs a bounded prop price screen against that
internal handoff before running the slower model graph. A handoff is rejected if
it is stale, future-dated, incomplete, hash-mismatched, or not fully observed.
Events require one exact home/away/start match. Players use case-folded and
whitespace-normalized canonical names only; duplicate names are ambiguous rather
than guessed. Stat type, line, and complementary outcome must be exact, and quote
observations may differ by at most30seconds. Only half-point lines are screened,
because an integer-stat push prevents the two legs from being simple complements.
Current-scan results replace `prop-screens:{sport}` so an empty or degraded run
does not leave an old candidate looking current. Positive rows are explicitly
gross price gaps: Kalshi fees, sportsbook limits, fills, DNP/void/stat rules, and
settlement equivalence remain unset, and `execution_ready` is always false.
The NFL paid scan requests all four corresponding core markets: passing yards,
rushing yards, receiving yards, and receptions. API credits are reserved for all
four before the provider request; partial affordability skips the event.
The read-only `/api/prop-screens?sport=nfl|nba` response omits internal scan,
milestone, and evidence identifiers. It revalidates the complementary legs and
price arithmetic at the public boundary and removes candidates more than five
minutes after observation. Captured counts remain visible when candidates expire.
Gross-positive Kalshi/sportsbook counts are separate from the number with a
complete one-contract fee model and the number whose modeled combined cost stays
below one dollar for direct and non-direct account precision. These are cost
coverage metrics. They remain independent of settlement equivalence, sportsbook
limits and fills, so none is labeled arbitrage or profit.

Exact archived Kalshi rule text is classified into a compact worker profile only
when its explicit language says an active player with no snap receives a pregame
fair-market-price settlement and a player with one snap settles on the recorded
stat. Changed templates remain unclassified. The public screen reports classified
rule coverage and the corresponding participation risk, while sportsbook rules,
overtime, stat corrections, and stat source remain unavailable or unspecified.
This explains the blocker; it does not clear settlement equivalence.

The same scan also screens sportsbook Over and Under prices for the identical
event, canonical player, stat, and half-point line. Legs must come from distinct
books and their provider observation times must be within30seconds. American odds
are converted to the cost of one dollar of total payout; the cheapest valid pair
is retained only when its gross cost is below one dollar. DNP/void/stat rules,
limits, acceptance, and price movement remain unreviewed, so these rows are also
unverified and non-executable with null profit fields.

Every new persisted sportsbook prop quote carries two commitments: one to the
canonical provider event response and one to the exact normalized quote row. The
writer recomputes the row commitment before opening a transaction, and PostgreSQL
rejects future rows without correctly shaped source evidence. Existing rows are
retained as legacy observations rather than being assigned invented provenance.
Scan coverage reports how many quotes carry these commitments. A commitment proves
internal integrity and common batch origin; it does not prove bookmaker settlement
rules, account eligibility, limits, or fills.

Free ESPN data provides outcomes and current projection targets, not player-prop
prices. A live NFL schema check found roughly 180 pages per game with no price
field. The optional LangGraph context agent therefore stops after a priced
sportsbook-provider failure instead of crawling those pages or assigning sides
from response order. The former DraftKings fallback is also removed: its endpoint
currently returns HTTP403 and its records could not be joined to the requested
event by exact provider identity. Missing priced props remain missing. Current real
walk-forward pilots exercise the actual model graph at explicitly chosen research
thresholds. They have no priced ROI or CLV. Build forward timestamped quote history
and evaluate genuinely held-out dates before any profitability claim.

Additional unchanged-model check: free ESPN final box scores for NFL2025-09-14
contained13 games and348 stat records. At the previously specified200.5 passing
yard threshold,16 of32 cases had sufficient prior history. Brier was0.2373145728
and log loss0.6686442102. The combined33 evaluated cases across the two pilot
dates still perform worse than a constant50% Brier baseline. This is a small,
dependent cohort with16 exclusions on the new date, not priced betting evidence.
No parameters were tuned against these outcomes; ROI and CLV remain null.

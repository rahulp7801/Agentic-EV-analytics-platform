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
Synthetic test fixtures validate arithmetic and graph routing only. Automatic
conversion of live sportsbook/Kalshi/PrizePicks feeds to reviewed candidates is
not yet implemented; raw Kalshi archives must not be described as executable inputs.

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

Automatic cross-venue contract mapping, sportsbook account limits, exact fee
reconciliation, PrizePicks entry ingestion, joint calibration, and fill simulation
remain prerequisites for executable recommendations. Quoted size is not a fill.
Multiple independently optimized candidates must not share the same bankroll or
liquidity without a portfolio-level reservation.

Free ESPN data provides outcomes, not historical player-prop prices. Current real
walk-forward pilots exercise the actual model graph at explicitly chosen research
thresholds. They have no priced ROI or CLV. Build forward timestamped quote history
and evaluate genuinely held-out dates before any profitability claim.

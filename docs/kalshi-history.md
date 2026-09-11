# Public Kalshi player-prop history

The read-only collector builds replayable evidence for **1–20 explicitly selected settled contracts** on one past Eastern calendar date. It does not discover a complete universe or select a representative backtest sample. The selection must be fixed before evaluating a strategy.

```sh
python -m sportsbet.ingestion.kalshi_history --sport nfl --date 2026-02-08 --ticker KXNFLPASSYDS-26FEB08SEANE-SEASDARNOLD14-350
python -m sportsbet.ingestion.kalshi_history --sport nba --date 2026-06-13 --ticker KXNBAPTS-26JUN13NYKSAS-SASVWEMBANYAMA1-40
python -m sportsbet.ingestion.kalshi_history --replay .local/kalshi-history/ARCHIVE.json
```

Repeat `--ticker` for additional contracts. `--output` accepts a new archive path; existing files are never overwritten. Default captures stay under ignored `.local/kalshi-history/`. No API key, database write, publication, or order capability is needed.

The collector queries recent and archived settled-market metadata and at most three 500-record milestone pages. An exact related-event link, unique milestone, sport/date, market/event identity, team membership and structured player identity are required. It uses the milestone's **scheduled start**, not the market's `occurrence_datetime`. Even settled NFL games can have a stale `scheduled` milestone status; this field is not evidence of actual kickoff.

For each eligible contract it requests one hour of one-minute candles ending 15 minutes before that scheduled start. The last bar must end within 60 seconds of the cutoff and contain finite, strictly interior, non-crossed bid/ask dollar strings. Duplicate, unordered, out-of-window and mismatched candles fail validation. Null quotes, boundary quotes and missing history are never filled from trade prices. A contract that opened after the cutoff or had already closed is excluded. Current player-profile statistics and team assignments do not become historical outcomes or affiliations.

Archives contain the raw response evidence, retrieval interval, normalized records, SHA-256 evidence digest, and per-contract exclusions. The normalized row retains Kalshi's strike type/floor and contract settlement; it does not reinterpret a structured strike as an ESPN stat result. Only consistent binary YES/NO settlements are admitted; void, split and other unsupported settlements remain excluded in the raw evidence.

Collection exits 2 when any selected contract is excluded or no records are usable. Replay makes no network calls, never writes or publishes, and exits 2 on a mismatch. A matching replay of an incomplete capture exits 0 **only to attest reproducibility**, retaining its incomplete status.

These are retrospective provider bars, not order-book snapshots or executable offers. Bar-end age does not establish quote-update age. Volume/open interest do not prove depth. Metadata may reflect corrections after the event. Fees, account limits, actual starts, settlement equivalence across venues, slippage and fill fragmentation are unverified. ROI and CLV stay null. Do not pass these rows into an executable arbitrage optimizer or merge them with athlete outcomes by name alone.

The two captured markets' own `rules_secondary` specify fair-market-price settlement when an active player never participates. NFL participation includes a snap nullified by a penalty; NBA participation requires entering the game. This can differ from another venue's void/refund rule. Preserve these rules in the evidence and review participation/cancellation scenarios before any cross-venue payoff comparison. The generic contract-term PDFs were not retrieved during this verification; market-specific metadata alone does not establish complete rule equivalence.

Verified on September 11, 2026: the two commands above each produced one usable real contract and exact offline replay. A recent Drew Lock passing-yards contract opened after the cutoff and correctly produced zero usable records. These hand-selected checks validate ingestion, not strategy returns.

Primary API references: [historical market metadata](https://docs.kalshi.com/api-reference/historical/get-historical-markets), [historical candles](https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks), and [recent candles](https://docs.kalshi.com/api-reference/market/get-market-candlesticks). Recent candles use `close_dollars`; archived candles use dollar strings in `close`. No cents heuristic or synthetic carry-forward bar is used.

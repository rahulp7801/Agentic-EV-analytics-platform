# Retained NFL cross-book price checkpoint — 2026-09-23

Read-only replay of the repository's existing `screen_sportsbooks` logic against the 16 NFL `the_odds_api` event responses still retained in `public.provider_response_cache`. Each response was replayed at its recorded `captured_at` time. The screen required valid source-hashed pregame prop quotes, no more than five minutes of quote age, at most 30 seconds of Over/Under observation skew, the same player/market/line, and distinct sportsbooks. It examines the best priced opposite-side pair per exact market.

| Measure | Result |
| --- | ---: |
| Retained event batches | 16 |
| Eligible quotes | 6,446 |
| Exact markets | 1,662 |
| Markets with a distinct-book, time-matched opposite pair | 529 |
| Positive gross gaps (`cost < $1` for a $1 payout) | **0** |
| Lowest gross cost | $1.0000 |
| Median best-pair gross cost | $1.0545 |

Two pairs were exactly gross break-even. No pair established a positive gross spread, before accounting for sportsbook limits, stale or moving prices, void/DNP differences, funding or fills. The retained cache covers only these 16 event responses, so this does not rule out gaps at other times. The code already screens and publishes such gaps when fresh provider responses arrive; this checkpoint does not add a new trading rule or claim executed profit.

The existing model-based route remains the primary prospective experiment. Cross-book gaps can be measured separately as observed prices if future screens find any, but they need rule equivalence and executable fills before they can establish realized edge.

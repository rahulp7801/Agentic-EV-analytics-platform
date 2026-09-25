# Collector credit defaults aligned to the deployed allowance

Read-only repository-variable inspection confirms `ODDS_DAILY_CREDIT_LIMIT=20`. The workflow fallback, three collector CLI defaults, and both ledger reservation defaults were still 25. No over-limit production use was observed in this check, but an omitted argument or missing variable could select the larger allowance.

All five Python defaults now use one `DEFAULT_DAILY_CREDIT_LIMIT=20` constant; the scheduled workflow fallback is also 20. Explicit configured limits and the existing atomic budget algorithm remain intact. Production's existing 20-credit variable was not changed. The 450-credit rolling cap, staged reserve and existing cadence rules are unchanged. No workflow was dispatched or quote collected to test this patch. There are no purchases, billing changes or bets.

Regression tests execute all three CLI argument parsers with fake collectors to prove default 20 and explicit lower 8 reach the worker; an actual temporary SQLite ledger proves that 12 credits plus an eight-credit reserve blocks further early use, then permits those eight and refuses credit 21. Existing cadence/reserve tests provide the remaining policy regression checks. CI and deployment evidence is recorded on the pull request.

# Consumer dashboard deployment

## Live failures reproduced

The NFL dashboard's watchlist showed Austin Hooper over 0.5 receptions, while Explore the players showed under 0.5. Constructing a Map from every ranked row retained the last value for a repeated player. The preview now preserves the first ranked record and prioritizes the same watchlist records visible above it. The same issue affected Christian Watson and Jahan Dotson.

Upcoming schedules were hidden behind a disclosure after the research panels. CFB and NBA therefore appeared empty without explaining their different situations. The dashboard now shows the nearest three fixtures with source links and local kickoff times, an expandable schedule, and navigation to player forecasts. Schedule fetch failures have an explicit retry and are never presented as zero games.

## Verification

- Existing 169 frontend tests passed; a new focused regression checks ranking, opposite-side rows, bounded results, empty input and input immutability.
- Local production build, TypeScript and lint passed.
- Browser verification with unchanged live API responses passed at 1440px and 390px for NFL, plus 390px for CFB and NBA. No horizontal page overflow or axe WCAG A/AA violations in those views.
- All three displayed NFL watchlist/preview leans agree; automated checks specifically assert Hooper's exact side/line and kickoff.
- Actual responses showed 16 NFL fixtures, 31 CFB fixtures and zero NBA fixtures in the seven-day window. These are schedules, not qualified picks.
- Desktop and mobile screenshots were inspected locally.

## Remaining product evidence

The last captured NFL quotes were expired and no current qualified selection was available. Source-backed research remains labeled accordingly. CFB had fixtures but no published forecasts. This release improves discovery and correctness; it does not establish a profitable strategy or manufacture actionable selections.

No model, qualification threshold, frozen evaluation, collection cadence, reserve, API allowance or stored prediction changed. No paid collection or bets were triggered. The separate reserve bypass in PR #194 remains unapproved.

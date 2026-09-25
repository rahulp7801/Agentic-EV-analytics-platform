# Complete CFB roster requests

## Confirmed source gap

The default ESPN college roster response returned exactly 100 athletes per team. The same free endpoint with `?limit=1000` returned 121, 124, and 106 athletes for three inspected teams. Four players missing from the default responses appeared in the expanded responses. This identifies a source truncation issue; blank public team fields alone were not sufficient evidence of its cause.

The expanded live responses carried older provider timestamps outside the existing one-hour freshness bound when inspected. Their membership is diagnostic evidence only. They must not be treated as fresh eligibility evidence or retroactively attached to earlier forecasts. A subsequent naturally scheduled scan still requires fresh provider timestamps and all other qualification checks.

## Change

CFB requests the existing two roster endpoints with an explicit limit of 1000. The directory, injury feed and roster request count are unchanged. Archived raw responses retain their exact URL and response hash, including the query parameter. Backend identity binding and frontend public projection accept exactly the legacy roster URL or that same URL with `?limit=1000`; other queries, fragments, changed sport, mismatched identity/hash and stale evidence remain invalid. NFL and NBA roster requests are unchanged.

This recovers late roster entries and their injury reports. Expanded membership never means confirmed game-day participation, a probability boost, an accepted pick, or a demonstrated edge. Prior forecasts, frozen evaluations, source checks, model versions, qualification thresholds, and history remain unchanged.

## Verification

A mock provider reproduces the 100-player default cutoff. The regression verifies a subject and an injured teammate after that cutoff, exact identity binding, preserved source URL and hash in the immutable archive, the teammate risk gate, subject injury gate, unchanged request count, and rejection of stale expanded responses. Boundary tests reject unsupported query variants and retain legacy source compatibility. Local verification: 44 focused backend tests and all 194 frontend tests pass, with TypeScript and focused ESLint passing. Broader local history tests could not collect because pandas is absent from the recovery host; full backend CI remains required. CI and deployment results are recorded on the pull request.

No quote collection is triggered to validate this change. At the next normally scheduled CFB collection, inspect committed roster URLs, provider timestamps, recovered identities, and resulting gates. Do not rewrite old unavailable evidence or bypass source freshness. The retained staged reserve, 20 daily / 450 rolling limits and PR #194 exclusion remain in force. The next authenticated final-result checkpoint is September 25 at 04:30 UTC, with the next CFB slate checkpoint September 26 at 04:30 UTC.

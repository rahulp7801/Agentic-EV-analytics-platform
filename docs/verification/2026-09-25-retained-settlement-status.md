# Retained verified settlement status

## Failure

The daily settlement report counts a candidate as pending whenever its refreshed schedule or primary stat lookup cannot produce a new settlement. This also happens for independently verified stored results recovered from a different authenticated source. The ledger retains those results correctly, while the dashboard reports them as pending. Read-only verification confirmed the retained recovered proofs remain valid.

## Change

When a recheck cannot resolve a candidate, verify the complete retained settlement proof using the existing ledger verifier. Count a valid retained automatic result as `retained_verified` and disclose its recheck reason separately. Only genuinely unresolved or invalid retained evidence counts as pending. Keep `settled` for results verified through the current stat lookup. The invariant is `candidates = settled + retained_verified + pending`.

This is a reporting correction. Candidate scope, stat lookup, source validation, outcome writes, correction behavior, manual-result exclusion and catch-up policy are unchanged. A missing refreshed source does not erase an existing authenticated result; a later authenticated correction can still replace it. No forecast, price, frozen model, history row or prior outcome is rewritten by this change.

The public projection supports older reports with zero retained results and validates both the total and the retained-reason count. The dashboard separates results verified in this pass, previously verified results, and pending records. It explains incomplete source rechecks without treating them as new settlements. Cached older API responses remain renderable.

## Verification and checkpoint

Regression cases cover missing primary rows, invalid refreshed stat commitments, incomplete current schedules, invalid stored proofs, exact preservation of stored results on failed rechecks, and later authenticated corrections. Frontend tests cover legacy compatibility, inconsistent totals, missing or inconsistent reason counts and redaction of unsupported fields. The full CI/deployment record is attached to the PR.

The next ordinary daily settlement run will publish the new counters. Existing stored pipeline reports retain their original meaning until refreshed; deployment alone does not recompute them. No quote collection or paid service is triggered. At the September 25 04:30 UTC final-result checkpoint, inspect authenticated outcomes and both frozen prospective reports. Current prospective evidence remains insufficient to claim an edge. Preserve all qualification thresholds, staged reserve, 20 daily / 450 rolling limits and the exclusion of PR #194.

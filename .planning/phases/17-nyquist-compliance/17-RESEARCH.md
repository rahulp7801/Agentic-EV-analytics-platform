# Phase 17: Nyquist Compliance - Research

**Researched:** 2026-03-24
**Domain:** Retroactive test validation, VALIDATION.md frontmatter repair
**Confidence:** HIGH

## Summary

Phase 17 is a documentation and test-infrastructure repair phase, not a feature phase. The goal is to mark 13 phase VALIDATION.md files as `nyquist_compliant: true` and `wave_0_complete: true` after verifying that all cited wave_0 tests exist and pass.

The v1.0 milestone audit found that phases 3–15 all have VALIDATION.md files with detailed Wave 0 Requirements and Per-Task Verification Maps, but every one of those files has `nyquist_compliant: false` and `wave_0_complete: false` in its frontmatter. The audit identified this as documentation debt, not implementation debt — the test files and test functions were written during phase execution, but the VALIDATION.md frontmatter was never retroactively updated to reflect that reality.

The current test suite has 174 tests collected. Running `pytest tests/ -x -q` passes 163 tests (11 are skipped due to missing `SPORTSBET_TEST_DATABASE_URL` environment variable). All wave_0 test files cited in VALIDATION.md files for phases 3–15 exist in `tests/`, with one exception: `test_correlation_guard.py` is referenced in the Phase 13 VALIDATION.md Wave 0 Requirements, but the file does not exist. However, the CorrelationGuard tests for PROP-07 DO exist in `test_prop_arbitrage.py::TestProp07CorrelationGuard`. The Phase 13 VALIDATION.md needs to be updated to point to the correct file, or a thin `test_correlation_guard.py` must be created.

**Primary recommendation:** For each of the 13 non-compliant phases, verify the named tests pass, update the Wave 0 checklist items to `[x]`, complete the Validation Sign-Off checklist, and set `nyquist_compliant: true` and `wave_0_complete: true` in the frontmatter. The only new test file needed is a resolution for Phase 13's missing `test_correlation_guard.py` reference.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=8.2 | Test runner | Already installed, configured in pyproject.toml |
| pytest-asyncio | >=0.23 | Async test support | asyncio_mode="auto" already set |

### Test Infrastructure (Already Present)

| File | Purpose | Phase Coverage |
|------|---------|----------------|
| `tests/conftest.py` | Shared fixtures (DB skip guards, graph fixtures) | All phases |
| `tests/test_quant.py` | QUANT-01, QUANT-03 | Phase 3 |
| `tests/test_vig.py` | QUANT-02 | Phase 3 |
| `tests/test_backtest.py` | QUANT-04 | Phase 3 |
| `tests/test_context.py` | CTXT-01, CTXT-02, CTXT-03, CTXT-04, DATA-03 | Phases 4, 8, 9 |
| `tests/test_arbitrage.py` | ARBT-01, ARBT-02, ARBT-03, ARBT-04 | Phase 5 |
| `tests/test_kinematic.py` | KINE-01, KINE-02, KINE-03 | Phases 6, 8 |
| `tests/test_graph.py` | INFRA-01, INFRA-02, KINE-02, QUANT-02, ARBT routing | Phases 7 |
| `tests/test_prop_models.py` | PROP-02 | Phase 10 |
| `tests/test_prop_odds.py` | PROP-01 | Phase 10 |
| `tests/test_nba_ingestion.py` | NBA-01 | Phase 10 |
| `tests/test_prop_query_builder.py` | PROP-03 | Phase 11 |
| `tests/test_prop_executor.py` | PROP-03, PROP-04 | Phase 11 |
| `tests/test_nba_prop_query_builder.py` | PROP-05 | Phase 12 |
| `tests/test_nba_prop_executor.py` | PROP-05, NBA-02 | Phase 12 |
| `tests/test_prop_arbitrage.py` | PROP-06, PROP-07 | Phase 13 |
| `tests/test_prop_pipeline_wiring.py` | PROP-06, PROP-07 | Phase 13 |
| `tests/test_prop_integration_gap_closure.py` | PROP-01, PROP-06, INFRA-01 | Phase 14 |
| `tests/test_context_and_vig_completion.py` | CTXT-04, QUANT-02 | Phase 15 |

**Run command:** `pytest tests/ -x -q --tb=short`
**Current state:** 163 passed, 11 skipped (DB-gated), 6 warnings

## Architecture Patterns

### Recommended Project Structure for Phase 17

Phase 17 touches only planning documents and (optionally) one test file:

```
.planning/phases/
├── 03-quant-engine/03-VALIDATION.md          # update frontmatter + sign-off
├── 04-context-and-odds-ingestion/04-VALIDATION.md
├── 05-arbitrage-kelly-and-risk-controls/05-VALIDATION.md
├── 06-kinematic-agent/06-VALIDATION.md
├── 07-production-runtime-wiring/07-VALIDATION.md
├── 08-data-pipeline-and-backtest/08-VALIDATION.md
├── 09-critical-pipeline-gap-closure/09-VALIDATION.md
├── 10-player-prop-and-nba-data-layer/10-VALIDATION.md
├── 11-nfl-player-prop-quant-engine/11-VALIDATION.md
├── 12-nba-player-prop-quant-engine/12-VALIDATION.md
├── 13-player-prop-arbitrage-and-pipeline-wiring/13-VALIDATION.md
├── 14-prop-integration-gap-closure/14-VALIDATION.md
└── 15-context-and-vig-completion/15-VALIDATION.md

tests/
└── test_correlation_guard.py   # optional: thin alias OR update Phase 13 VALIDATION.md reference
```

### Pattern: Retroactive Nyquist Sign-Off

**What:** For each VALIDATION.md, three changes are made:
1. Frontmatter: `nyquist_compliant: false` → `true`, `wave_0_complete: false` → `true`, `status: draft` → `approved`
2. Wave 0 Requirements checklist: `- [ ]` → `- [x]` for each item whose test exists and passes
3. Validation Sign-Off checklist: all six items `- [ ]` → `- [x]`

**When to use:** When tests exist and pass but the VALIDATION.md was written before tests were implemented (the common case here — VALIDATION.md was written during planning, tests were written during execution, and the VALIDATION.md was never updated).

**Example frontmatter change:**
```yaml
---
phase: 3
slug: quant-engine
status: approved          # was: draft
nyquist_compliant: true   # was: false
wave_0_complete: true     # was: false
created: 2026-03-10
updated: 2026-03-24       # add updated field
---
```

### Pattern: Wave 0 Checklist Verification

Before marking `[x]`, verify the test function is collected and passes:

```bash
pytest tests/test_quant.py::test_quant_params_validation -x -q
pytest tests/test_vig.py::test_american_to_raw_prob_negative -x -q
# etc.
```

For DB-skipped tests (`skipif no SPORTSBET_TEST_DATABASE_URL`), the test is collected and skips gracefully — this counts as "exists" for wave_0 purposes since the gate is an environment constraint, not a missing test.

### Anti-Patterns to Avoid

- **Marking wave_0_complete without verifying:** Do not flip bits without running `pytest` for each phase's specific tests first.
- **Creating redundant test files:** `test_correlation_guard.py` is referenced but the tests live in `test_prop_arbitrage.py`. The correct fix is to update the VALIDATION.md reference to point to `test_prop_arbitrage.py`, not to create an empty wrapper file.
- **Changing test function names:** The tests that exist use names like `test_arbt03_conflict_blocked` while the VALIDATION.md may reference `test_arbt03`. The VALIDATION.md should be updated to match the actual function names that pass.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Verifying test presence | Custom test scanner | `pytest --co -q` collect-only | pytest's built-in collection is authoritative |
| Running per-phase tests | Shell loops over test files | Targeted `pytest tests/test_X.py -x -q` | Fast, precise, shows pass/fail per phase |
| VALIDATION.md edits | sed scripts | Direct file edits via Write/Edit tool | Markdown with YAML frontmatter is fragile under sed |

**Key insight:** This entire phase is a documentation update with test verification. No new Python code is required. All complexity is in accurately reading existing test files and updating VALIDATION.md checklists.

## Common Pitfalls

### Pitfall 1: VALIDATION.md References Non-Existent Test Functions

**What goes wrong:** VALIDATION.md Per-Task Verification Map lists a function name like `test_arbt01` but the actual test is `test_arbt01_ev_signal_produced`. Running the exact command from the VALIDATION.md returns "no tests ran."

**Why it happens:** VALIDATION.md files were written during planning before test names were finalized. Test names evolved during TDD implementation.

**How to avoid:** For each VALIDATION.md entry, run `pytest --co -q tests/relevant_file.py` and match listed function names against collected names. Update the VALIDATION.md commands if they diverge.

**Warning signs:** `pytest tests/test_X.py::test_foo -x` returns "0 items / 1 error" or "collected 0 items."

### Pitfall 2: Phase 13 Missing test_correlation_guard.py

**What goes wrong:** Phase 13 VALIDATION.md Wave 0 requires `tests/test_correlation_guard.py` — this file does not exist. Blindly marking `[x]` would be dishonest.

**Why it happens:** During Phase 13 execution, CorrelationGuard tests were consolidated into `test_prop_arbitrage.py::TestProp07CorrelationGuard` rather than a separate file.

**How to avoid:** Update the Phase 13 VALIDATION.md Wave 0 checklist to reference `tests/test_prop_arbitrage.py::TestProp07CorrelationGuard` instead of `tests/test_correlation_guard.py`. Verify those tests pass. Mark `[x]`.

**Alternative:** Create a thin `tests/test_correlation_guard.py` that imports and re-exposes the tests — but this is unnecessary duplication. Updating the VALIDATION.md reference is cleaner.

### Pitfall 3: DB-Skipped Tests Counted as Missing

**What goes wrong:** Tests like `test_run_quant_query_passing` and `test_quant_agent_live` are skipped in CI (no `SPORTSBET_TEST_DATABASE_URL`). A validator might see "skipped" and conclude the wave_0 requirement is unmet.

**Why it happens:** skipif guards are per the Phase 1 decision: `SPORTSBET_TEST_DATABASE_URL` gates DB tests with `skipif` — not `xfail` — for real assertions.

**How to avoid:** Skipped tests with a proper `skipif` guard still count as wave_0 compliant. The test file exists, the test is collected, and it runs when the DB environment is present. Document this explicitly in the VALIDATION.md sign-off.

### Pitfall 4: Status Field Not Updated

**What goes wrong:** Frontmatter `status: draft` is left unchanged while `nyquist_compliant: true` is set, creating an inconsistent state.

**How to avoid:** Always update `status: draft` → `status: approved` and add `updated: 2026-03-24` when marking nyquist_compliant.

### Pitfall 5: Per-Task Status Column Not Updated

**What goes wrong:** The Per-Task Verification Map rows all show `Status: ⬜ pending` even after the tests are green.

**How to avoid:** For each task row, update `Status` from `⬜ pending` to `✅ green`. For DB-skipped tests that cannot be run without live DB, mark `⬜ pending (skipif DB)` to be honest.

## Code Examples

### Verifying Specific Phase Tests

```bash
# Phase 3 - Quant Engine
pytest tests/test_quant.py tests/test_vig.py tests/test_backtest.py -x -q

# Phase 4 - Context and Odds Ingestion
pytest tests/test_context.py -x -q

# Phase 5 - Arbitrage, Kelly, Risk Controls
pytest tests/test_arbitrage.py -x -q

# Phase 6 - Kinematic Agent
pytest tests/test_kinematic.py -x -q

# Phase 7 - Production Runtime Wiring
pytest tests/test_graph.py -k "Phase7Wiring" -x -q

# Phase 8 - Data Pipeline and Backtest
pytest tests/test_context.py::test_context_agent_persists_odds_snapshot tests/test_kinematic.py::test_matchup_query_returns_avg_time_to_throw tests/test_backtest.py::test_backtest_cli_main_prints_output -x -q

# Phase 9 - Critical Pipeline Gap Closure
pytest tests/test_context.py::test_context_agent_rejects_stale_odds tests/test_quant.py -x -q

# Phase 10 - Player Prop and NBA Data Layer
pytest tests/test_prop_models.py tests/test_prop_odds.py tests/test_nba_ingestion.py -x -q

# Phase 11 - NFL Player Prop Quant Engine
pytest tests/test_prop_query_builder.py tests/test_prop_executor.py -x -q

# Phase 12 - NBA Player Prop Quant Engine
pytest tests/test_nba_prop_query_builder.py tests/test_nba_prop_executor.py -x -q

# Phase 13 - Prop Arbitrage and Pipeline Wiring
pytest tests/test_prop_arbitrage.py tests/test_prop_pipeline_wiring.py -x -q

# Phase 14 - Prop Integration Gap Closure
pytest tests/test_prop_integration_gap_closure.py -x -q

# Phase 15 - Context and Vig Completion
pytest tests/test_context_and_vig_completion.py -x -q
```

### Confirming All Wave 0 Tests Are Collected

```bash
pytest tests/ --co -q 2>&1 | wc -l
# Expected: 174+ tests collected
```

### VALIDATION.md Frontmatter Update Pattern

```yaml
---
phase: {N}
slug: {slug}
status: approved
nyquist_compliant: true
wave_0_complete: true
created: {original date}
updated: 2026-03-24
---
```

### Validation Sign-Off Block (Final State)

```markdown
## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < {N}s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** Retroactively approved 2026-03-24 — all wave_0 test files exist and pass in current test suite (163 passed, 11 skipped-DB, 0 failed).
```

## Per-Phase Compliance Assessment

This table is the core finding — what the VALIDATION.md says is needed vs. what currently exists:

### Plan 17-01 Scope: Phases 3–9

| Phase | VALIDATION.md Status | Test Files Exist? | Named Tests Pass? | Gap |
|-------|---------------------|-------------------|-------------------|-----|
| 3 | draft, both false | Yes: test_quant.py, test_vig.py, test_backtest.py | Yes (all 3 files pass) | None — update VALIDATION.md only |
| 4 | draft, both false | Yes: test_context.py | Yes (10 tests pass) | None — update VALIDATION.md only |
| 5 | draft, both false | Yes: test_arbitrage.py | Yes (20 tests pass) | VALIDATION.md uses generic task IDs (test_arbt01 etc.); actual names are test_arbt01_ev_signal_produced etc. — update Per-Task Map names |
| 6 | draft, both false | Yes: test_kinematic.py | Yes (11 tests pass) | None — update VALIDATION.md only |
| 7 | draft, both false | Yes: test_graph.py | Yes (TestPhase7Wiring class, 3 tests pass) | None — update VALIDATION.md only |
| 8 | draft, both false | Yes: test_context.py, test_kinematic.py, test_backtest.py | Yes (specific functions confirmed) | None — update VALIDATION.md only |
| 9 | draft, both false | Yes: test_context.py, test_quant.py | Yes | None — update VALIDATION.md only |

### Plan 17-02 Scope: Phases 10–15

| Phase | VALIDATION.md Status | Test Files Exist? | Named Tests Pass? | Gap |
|-------|---------------------|-------------------|-------------------|-----|
| 10 | draft, both false | Yes: test_prop_models.py, test_prop_odds.py, test_nba_ingestion.py | Yes | None — update VALIDATION.md only |
| 11 | draft, both false | Yes: test_prop_query_builder.py, test_prop_executor.py | Yes (9 tests pass) | None — update VALIDATION.md only |
| 12 | draft, both false | Yes: test_nba_prop_query_builder.py, test_nba_prop_executor.py | Yes | None — update VALIDATION.md only |
| 13 | draft, both false | test_prop_arbitrage.py, test_prop_pipeline_wiring.py exist; **test_correlation_guard.py MISSING** | Yes (tests in test_prop_arbitrage.py) | Update VALIDATION.md Wave 0 to reference test_prop_arbitrage.py::TestProp07CorrelationGuard |
| 14 | draft, both false | Yes: test_prop_integration_gap_closure.py | Yes (3 tests pass) | None — update VALIDATION.md only |
| 15 | draft, both false | Yes: test_context_and_vig_completion.py | Yes (6 tests pass) | None — update VALIDATION.md only |

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| VALIDATION.md written at planning time with `[ ]` Wave 0 items | Tests written during execution left VALIDATION.md unflagged | Wave_0 items exist in test suite but not reflected in VALIDATION.md |
| `status: draft` left unchanged after implementation | Should update to `status: approved` + `updated:` date | Frontmatter is stale |
| Sign-Off checklist left at `[ ]` | Should update to `[x]` after tests pass | Compliance debt visible in audit |

**Deprecated/outdated:**
- Phase 5 VALIDATION.md Per-Task IDs: `test_arbt01`, `test_arbt02` — these do not match actual test names (`test_arbt01_ev_signal_produced`, etc.). Need Per-Task Map updates.
- Phase 13 VALIDATION.md Wave 0 requirement for `test_correlation_guard.py` — file doesn't exist; tests consolidated in `test_prop_arbitrage.py`.

## Open Questions

1. **Phase 5 Per-Task Map mismatches**
   - What we know: The VALIDATION.md lists `test_arbt01`, `test_arbt02`, etc. but the actual test names are `test_arbt01_ev_signal_produced`, `test_arbt02_kelly_fraction_non_flat`, etc.
   - What's unclear: Should the Per-Task Map be updated to use the actual names, or left as-is with a note?
   - Recommendation: Update the Per-Task Map to use actual passing test names — the map should be accurate so `/gsd:validate-phase` can run the commands successfully.

2. **Phase 13 test_correlation_guard.py**
   - What we know: The file does not exist. `test_prop_arbitrage.py::TestProp07CorrelationGuard` covers the PROP-07 requirement.
   - What's unclear: Create a new thin file or update the VALIDATION.md?
   - Recommendation: Update the Phase 13 VALIDATION.md Wave 0 item to reference `tests/test_prop_arbitrage.py (TestProp07CorrelationGuard class)`. Do not create a redundant empty file. The test that satisfies the requirement exists and passes.

3. **DB-skipped tests and wave_0_complete**
   - What we know: 11 tests are skipped due to missing `SPORTSBET_TEST_DATABASE_URL`. These include `test_run_quant_query_passing`, `test_quant_agent_live`, `test_live_db` (prop executor), etc.
   - What's unclear: Should wave_0_complete count skipif-gated tests as "complete"?
   - Recommendation: Yes. The Phase 1 decision is that `skipif` (not `xfail`) is used for DB tests. A skipped test with a proper guard is compliant — the test exists, is collected, and runs when the environment is present. Wave_0 means the test infrastructure is in place, not that the test runs without any environment.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.2 + pytest-asyncio 0.23 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/ -x -q --tb=short` |
| Full suite command | `pytest tests/ -v` |

### Phase 17 Requirements → Test Map

| Behavior | Test Type | Automated Command | Notes |
|----------|-----------|-------------------|-------|
| Phase 3 wave_0 complete | smoke | `pytest tests/test_quant.py tests/test_vig.py tests/test_backtest.py -x -q` | All tests pass |
| Phase 4 wave_0 complete | smoke | `pytest tests/test_context.py -x -q` | All tests pass |
| Phase 5 wave_0 complete | smoke | `pytest tests/test_arbitrage.py -x -q` | All tests pass |
| Phase 6 wave_0 complete | smoke | `pytest tests/test_kinematic.py -x -q` | All tests pass |
| Phase 7 wave_0 complete | smoke | `pytest tests/test_graph.py -k "Phase7Wiring" -x -q` | 3 tests pass |
| Phase 8 wave_0 complete | smoke | `pytest tests/test_backtest.py::test_backtest_cli_main_prints_output tests/test_kinematic.py::test_matchup_query_returns_avg_time_to_throw -x -q` | Both pass |
| Phase 9 wave_0 complete | smoke | `pytest tests/test_context.py::test_context_agent_rejects_stale_odds -x -q` | Passes |
| Phase 10 wave_0 complete | smoke | `pytest tests/test_prop_models.py tests/test_prop_odds.py tests/test_nba_ingestion.py -x -q` | All pass |
| Phase 11 wave_0 complete | smoke | `pytest tests/test_prop_query_builder.py tests/test_prop_executor.py -x -q` | All pass |
| Phase 12 wave_0 complete | smoke | `pytest tests/test_nba_prop_query_builder.py tests/test_nba_prop_executor.py -x -q` | All pass |
| Phase 13 wave_0 complete | smoke | `pytest tests/test_prop_arbitrage.py tests/test_prop_pipeline_wiring.py -x -q` | All pass |
| Phase 14 wave_0 complete | smoke | `pytest tests/test_prop_integration_gap_closure.py -x -q` | All pass |
| Phase 15 wave_0 complete | smoke | `pytest tests/test_context_and_vig_completion.py -x -q` | All pass |

### Sampling Rate

- **Per task commit:** `pytest tests/ -x -q --tb=short`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

None — existing test infrastructure covers all phase requirements. The single structural issue (Phase 13 VALIDATION.md references `test_correlation_guard.py`) is resolved by updating the VALIDATION.md reference, not by writing new tests.

## Sources

### Primary (HIGH confidence)

- Direct inspection of `tests/` directory — all 22 test files enumerated and existence verified
- `pytest tests/ -x -q` run result — 163 passed, 11 skipped, 0 failed (observed 2026-03-24)
- `pytest tests/ --co -q` — 174 tests collected (observed 2026-03-24)
- All 13 VALIDATION.md files read directly — frontmatter, Wave 0 Requirements, and Per-Task Verification Maps verified
- `.planning/v1.0-MILESTONE-AUDIT.md` — nyquist compliance section cross-referenced

### Secondary (MEDIUM confidence)

- `.planning/STATE.md` Decisions log — context for why specific test patterns were used (skipif vs xfail, asyncio_mode=auto, etc.)

## Metadata

**Confidence breakdown:**
- Phase gap analysis (what's missing vs. what exists): HIGH — verified by direct file inspection and test collection
- Per-Task Map accuracy (actual function names): HIGH — verified by `--co` output
- Recommended fix for Phase 13: HIGH — `TestProp07CorrelationGuard` confirmed to exist and pass in `test_prop_arbitrage.py`
- DB-skipped test interpretation: HIGH — consistent with Phase 1 decision log (skipif not xfail)

**Research date:** 2026-03-24
**Valid until:** Stable — no moving parts; based on static file inspection of committed code

# Phase 24: Integration Documentation and Backtest NULL Fix - Research

**Researched:** 2026-03-26
**Domain:** LangGraph checkpoint patterns, SQL NULL semantics, developer documentation
**Confidence:** HIGH

## Summary

Phase 24 closes three non-blocking audit gaps from the v1.0 milestone. Two are pure documentation gaps — the quant→arbitrage two-invocation checkpoint pattern (ARBT-01) and the context→prop invocation ordering for `make_prop_quant_agent`/`make_nba_quant_agent` (CTXT-04/PROP-04) are both implemented and working in the codebase but neither has the same explicit inline-comment documentation that the kinematic two-invocation pattern received in Phase 16. The third gap is a SQL correctness bug: `load_snapshots` in `backtest_replay.py` uses a `LEFT JOIN games` which silently drops `odds_snapshots` rows that have `game_id = NULL` because the `WHERE snapped_at < (g.game_date::timestamptz + INTERVAL '18 hours')` predicate evaluates to NULL for unjoined rows.

The documentation work requires reading the existing codebase to locate the exact code sites and writing prescriptive inline comments that parallel the PROP-04 kinematic pattern already present in `graph.py` lines 307–317. The SQL fix requires changing the `LEFT JOIN` behaviour to filter `NULL game_id` rows before joining — or rewriting the timestamp comparison to use `COALESCE`/`NULLIF` so the `WHERE` clause returns true (not NULL) for such rows. A new unit test is needed to confirm the fix.

**Primary recommendation:** Add two inline comment blocks to `graph.py` (quant→arbitrage pattern after `add_edge("quant_agent", END)`) and to `prop/agents.py` docstring (context→prop ordering), then fix `load_snapshots` to filter `WHERE o.game_id IS NOT NULL` before the LEFT JOIN or use a `COALESCE` fallback for the timestamp expression, and add a pure-unit test in `test_backtest_pipeline.py` confirming a `NULL`-game_id row is not dropped from output.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ARBT-01 | Arbitrage Agent flags +EV discrepancies by comparing QuantResult true probability against sportsbook implied probability, outputting raw EV% and 3-bullet Trade Plan thesis | The agent implementation is complete. Gap is that callers must invoke "quant_analysis" before "arbitrage_analysis" in the same thread_id — this ordering contract is implicit in code but has no explicit developer-facing comment in graph.py the way PROP-04 kinematic does |
| CTXT-04 | Context Agent updates global game state JSON on binary state changes and propagates updated state through GraphState | The agent implementation is complete. Gap is that `make_prop_quant_agent` and `make_nba_quant_agent` entry-point docstrings do not explicitly document that "context_update" must precede "prop_analysis" in the same thread_id, and do not document the `situational_params = None` fallback behaviour |
| PROP-04 | System incorporates Kinematic Agent signals into NFL receiving prop probability estimates where NGS data is available | Already documented in graph.py PROP-04 comment block (Phase 16). This phase extends the documentation pattern to the context→prop invocation ordering and situational_params fallback |
| QUANT-04 | System simulates historical signal performance via backtesting module that replays past QuantResult signals against closing lines | Implementation complete. Gap is in `load_snapshots` LEFT JOIN: rows with `odds_snapshots.game_id = NULL` silently disappear from backtest replay output because the WHERE clause timestamp predicate evaluates to NULL, not TRUE |

</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | current (project) | async PostgreSQL queries in `load_snapshots` | Used throughout project for async DB access |
| LangGraph AsyncSqliteSaver | current (project) | checkpoint persistence enabling cross-invocation state | Already wired in `create_graph_with_sqlite` |
| pytest | current (project) | unit test framework | Project standard; all tests use pytest |
| structlog | current (project) | structured logging in agents | Project standard per CLAUDE.md |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python dataclasses | stdlib | `BacktestSignal`, `BacktestReport` | Already used in `backtest.py`; no new dataclasses needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Filtering NULL game_id in WHERE clause | INNER JOIN instead of LEFT JOIN | INNER JOIN would also drop NULL rows cleanly but eliminates valid future use case where game metadata is loaded later; explicit filter is more intentional |
| WHERE o.game_id IS NOT NULL | NULLIF(o.game_id, '') IS NOT NULL | NULLIF only helps empty-string case; IS NOT NULL is the correct PostgreSQL idiom for actual NULLs |

---

## Architecture Patterns

### Recommended Project Structure

No new files needed. All changes are in existing files:

```
src/sportsbet/
├── graph/
│   └── graph.py              # Add ARBT-01 two-invocation comment block
├── prop/
│   └── agents.py             # Add CTXT-04/PROP-04 context→prop ordering docstring
└── quant/
    └── backtest_replay.py    # Fix load_snapshots LEFT JOIN NULL drop

tests/
└── test_backtest_pipeline.py # Add NULL game_id test
```

### Pattern 1: Inline Two-Invocation Comment Block (established in Phase 16)

**What:** A structured inline comment block placed immediately after a terminal `add_edge` call in `create_graph()` that explains the multi-invocation checkpoint pattern for callers.

**When to use:** Any time a node must read state written by a prior invocation in the same thread.

**Existing example (PROP-04 kinematic, graph.py lines 307–317):**
```python
# PROP-04 kinematic boost: two-invocation checkpoint pattern (GAP-INT-2).
# To incorporate kinematic separation/press-man signals into NFL receiving prop estimates:
#   Invocation 1: ainvoke({"request_type": "kinematic_analysis", ...},
#                          config={"configurable": {"thread_id": tid}})
#                 -> kinematic_agent writes KinematicAnalysis to state["kinematic_result"]
#                 -> AsyncSqliteSaver persists it in the checkpoint under thread_id
#   Invocation 2: ainvoke({"request_type": "prop_analysis", ...},
#                          config={"configurable": {"thread_id": tid}})
#                 -> prop_quant_agent reads state.get("kinematic_result") from checkpoint
#                 -> _apply_kinematic_adjustment() boosts probability if RECEIVING_PROPS match
# Both invocations MUST use the same thread_id. Single-invocation path not supported.
```

**Pattern for ARBT-01 (quant→arbitrage, to add after `add_edge("quant_agent", END)`):**
```python
# ARBT-01 arbitrage two-invocation checkpoint pattern.
# arbitrage_agent reads quant_result from state. When using a dedicated
# "arbitrage_analysis" request_type (not the full quant→arb pipeline), callers
# must invoke "quant_analysis" before "arbitrage_analysis" in the same thread_id
# so that quant_result is persisted in the checkpoint before arbitrage reads it.
#   Invocation 1: ainvoke({"request_type": "quant_analysis", ...},
#                          config={"configurable": {"thread_id": tid}})
#                 -> quant_agent writes QuantResult to state["quant_result"]
#                 -> AsyncSqliteSaver persists it under thread_id
#   Invocation 2: ainvoke({"request_type": "arbitrage_analysis", ...},
#                          config={"configurable": {"thread_id": tid}})
#                 -> arbitrage_agent reads state.get("quant_result") from checkpoint
#                 -> Returns ev_signal=None if quant_result is None (Guard 1)
# Both invocations MUST use the same thread_id. Single-invocation path not supported.
```

### Pattern 2: Docstring Ordering Contract (for prop agent entry points)

**What:** Explicit documentation in the closure factory docstring that describes invocation ordering requirements and fallback behavior.

**When to use:** Closure factory functions where the caller must know about pre-conditions set by an upstream agent.

**Pattern for `make_prop_quant_agent` (CTXT-04/PROP-04, to add to existing docstring):**
```
Invocation ordering:
    For situational_params (injury-adjusted queries), callers must invoke
    "context_update" before "prop_analysis" in the same thread_id. The context_agent
    populates situational_params in GraphState; prop_quant_agent reads it via
    state.get("situational_params") or {}.

    When no prior context_update has been called, situational_params is None.
    The agent falls back to {} (empty dict), which means teammate_out=None in
    PropParams — the query runs without injury-adjusted WHERE clauses. This is
    the correct production fallback for callers that run prop queries without
    injury context.
```

**Pattern for `make_nba_quant_agent` (CTXT-04/PROP-04, equivalent):**
```
Invocation ordering:
    For NBA context adjustments (pace, def_rating, rest, home), the pipeline
    inserts nba_context_producer before nba_quant_agent automatically (see graph.py
    nba_context_producer -> nba_quant_agent edge). Callers using "nba_prop_analysis"
    request_type do not need to manually invoke a separate context step.

    When nba_context_signals is None (stub path), all four context adjustments
    are skipped and base NormalDist probability is returned unchanged.
```

### Pattern 3: LEFT JOIN NULL Drop Fix

**What:** `load_snapshots` joins `odds_snapshots` to `games` via `LEFT JOIN`. The WHERE clause contains `o.snapped_at < (g.game_date::timestamptz + INTERVAL '18 hours')`. When `game_id` is NULL, the LEFT JOIN produces `g.game_date = NULL`, making the timestamp expression evaluate to NULL, which is neither TRUE nor FALSE — PostgreSQL excludes the row from the result set as if it failed the condition.

**Root cause:** PostgreSQL WHERE clause treats NULL comparisons as UNKNOWN, which evaluates to FALSE for row inclusion. A LEFT JOIN row with no matching right-side will have all right-side columns as NULL, so any arithmetic on those NULL columns produces NULL.

**Fix options:**

Option A — Filter NULL game_id before JOIN (preferred — explicit, no false inclusion):
```sql
FROM odds_snapshots o
LEFT JOIN games g ON o.game_id = g.game_id
WHERE o.game_id IS NOT NULL
  AND o.snapped_at < (g.game_date::timestamptz + INTERVAL '18 hours')
  AND o.price IS NOT NULL
```

Option B — COALESCE with a sentinel future timestamp for NULL-game rows (includes them without time filtering):
```sql
WHERE o.snapped_at < COALESCE(
    g.game_date::timestamptz + INTERVAL '18 hours',
    'infinity'::timestamptz
)
```

**Recommendation: Option A** — explicitly filter `WHERE o.game_id IS NOT NULL`. This is the correct intent: rows with no game_id cannot be matched to a game start time and should be excluded from backtest replay, not silently dropped. Option B would include un-anchored snapshots without a time guard, which violates the closing-line integrity contract (Pitfall 6 in RESEARCH.md — `snapshot_time < game_start_time` must hold).

**Confidence:** HIGH — this is a well-understood PostgreSQL NULL semantics issue.

### Anti-Patterns to Avoid

- **Silently passing NULL game_id rows through `build_signals`:** `build_signals` already handles missing `price` but does not check `game_id`. The fix belongs in `load_snapshots` (the SQL layer), not in `build_signals` (the Python layer). Keeping the filter in SQL avoids shipping NULL rows to Python at all.
- **Using INNER JOIN as the fix:** While an INNER JOIN would also exclude NULL-game rows, it changes the semantic intent of the query and would also exclude cases where the games table doesn't yet have a row for a valid game_id (e.g., a newly-ingested game). The explicit IS NOT NULL filter is more precise.
- **Documenting invocation order in the ROADMAP only:** Developer contracts like invocation ordering must live in the code (inline comments and docstrings) co-located with the implementation, not only in planning docs.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NULL-safe timestamp comparison | Custom Python post-filter | `WHERE o.game_id IS NOT NULL` in SQL | Filter at DB layer before Python sees the rows |
| Cross-invocation state | Application-level state dict | AsyncSqliteSaver checkpoint under thread_id | Already wired; just needs documentation |

---

## Common Pitfalls

### Pitfall 1: NULL Propagation in PostgreSQL WHERE Clauses
**What goes wrong:** A LEFT JOIN that includes NULL-key rows from the left table will produce NULL for all right-table columns on those rows. Any arithmetic or comparison involving those NULL columns produces NULL. PostgreSQL treats NULL in a WHERE clause as UNKNOWN, which excludes the row from results — silently.
**Why it happens:** Developers expect LEFT JOIN to "keep all left rows" but forget that subsequent WHERE clauses can filter them out via NULL propagation.
**How to avoid:** Whenever a WHERE clause references a column from the right side of a LEFT JOIN, add an explicit `AND right_table.key IS NOT NULL` guard, or move the condition to the JOIN's `ON` clause.
**Warning signs:** Snapshot count from `load_snapshots` is lower than `SELECT COUNT(*) FROM odds_snapshots` for the same filters.

### Pitfall 2: Invocation Order Contract as Tribal Knowledge
**What goes wrong:** A developer calls `arbitrage_analysis` without a prior `quant_analysis` in the same thread. `arbitrage_agent` returns `{"ev_signal": None}` with a log warning "arbitrage_agent_no_quant_result". No exception is raised. The caller sees no output and wonders why the pipeline is silent.
**Why it happens:** The guard that returns `ev_signal=None` when `quant_result is None` is correct defensive programming, but without documentation it looks like a bug rather than a contract violation.
**How to avoid:** Place the two-invocation comment block immediately after the relevant `add_edge` call in `create_graph()`, co-located with the topology it describes.
**Warning signs:** Test coverage exists for the guard (returns None) but not for the positive case where the prior invocation seeded the checkpoint.

### Pitfall 3: Documentation Written in Wrong Layer
**What goes wrong:** Invocation ordering documented in ROADMAP.md or planning files only, not in source code. Developers reading `agents.py` or `graph.py` cannot see the contract.
**How to avoid:** Inline comments in `graph.py` and docstring extensions in the closure factory functions are the authoritative location for caller contracts.

### Pitfall 4: Test Fixture Reuse Without NULL Variation
**What goes wrong:** All existing `test_backtest_pipeline.py` fixtures use a valid `game_id` string. The NULL case is never exercised. The bug existed in production but all tests passed.
**How to avoid:** Add a fixture row with `game_id=None` and assert it appears in `build_signals` output after the SQL fix. The test must call `load_snapshots` with a mock connection that returns the NULL row.

---

## Code Examples

### SQL Fix — load_snapshots with NULL guard

```python
# Source: backtest_replay.py load_snapshots — fix for QUANT-04 NULL drop bug
where_clauses = [
    "o.game_id IS NOT NULL",                                          # NEW: filter before JOIN
    "o.snapped_at < (g.game_date::timestamptz + INTERVAL '18 hours')",
    "o.price IS NOT NULL",
]
```

The `o.game_id IS NOT NULL` guard must appear BEFORE the timestamp comparison in the WHERE list so NULL-game rows are excluded before the NULL-producing arithmetic runs. (Order does not affect correctness in PostgreSQL, but it signals intent to readers.)

### Test Pattern — NULL game_id fixture row

```python
# Source: test_backtest_pipeline.py — new NULL game_id test
FIXTURE_ROW_NULL_GAME = {
    "id": 3,
    "game_id": None,           # <-- key: NULL game_id
    "sportsbook": "betmgm",
    "market_type": "h2h",
    "line": None,
    "price": -115,
    "snapped_at": datetime(2024, 1, 14, 12, 0, 0, tzinfo=timezone.utc),
    "game_start_time": None,   # LEFT JOIN produced NULL; post-fix never reaches Python
}
```

**Important:** After the SQL fix, `load_snapshots` should NOT return NULL-game rows at all. The test must verify the fix at the `build_signals` layer by confirming a NULL-game row in input does not silently disappear from the output — or alternatively, test `load_snapshots` itself via a mock asyncpg Connection that returns a NULL-game row and assert it is excluded by the WHERE clause.

The success criterion says "A test or assertion confirms that an odds_snapshot row with game_id=NULL is not silently excluded from backtest replay output." Read carefully: the goal is that NULL rows are handled *explicitly* (either excluded with a documented reason, or included with a fallback) rather than *silently* dropped. Option A (filtering IS NOT NULL in SQL) means the row never reaches `build_signals`. The test should:

1. Assert `build_signals` handles a row with `game_start_time=None` without raising (it currently would crash at `row["game_start_time"]` since that's a direct key access, not `.get()`), **OR**
2. Mock `load_snapshots` to return a NULL-game row and assert `build_signals` returns 0 signals or explicitly skips it with a log message.

The cleanest approach matching the success criteria: add a `game_id IS NULL` skip in `build_signals` with a `logger.debug` (mirrors the existing `price is None` skip), and a unit test asserting the skip fires.

### Invocation Ordering Comment Pattern (graph.py, after quant_agent edge)

```python
# Source: graph.py, following existing PROP-04 comment pattern at lines 307–317
# ARBT-01 quant→arbitrage two-invocation checkpoint pattern.
# When using request_type="arbitrage_analysis" directly (not a combined pipeline):
#   Invocation 1: ainvoke({"request_type": "quant_analysis", ...},
#                          config={"configurable": {"thread_id": tid}})
#                 -> quant_agent writes QuantResult to state["quant_result"]
#                 -> AsyncSqliteSaver persists it under thread_id
#   Invocation 2: ainvoke({"request_type": "arbitrage_analysis", ...},
#                          config={"configurable": {"thread_id": tid}})
#                 -> arbitrage_agent reads state.get("quant_result") from checkpoint
#                 -> Returns ev_signal=None (Guard 1) if quant_result is absent
# Both invocations MUST use the same thread_id.
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No invocation-order docs (PROP-04 kinematic) | Inline comment block in graph.py | Phase 16 | Callers understand kinematic two-invocation requirement |
| No invocation-order docs (ARBT-01, CTXT-04) | Inline comment block + docstring (Phase 24) | This phase | Callers understand quant→arb and context→prop ordering |
| LEFT JOIN silently drops NULL game_id rows | WHERE o.game_id IS NOT NULL guard | This phase | Backtest replay correctly handles NULL-game snapshots |

**Deprecated/outdated:**
- None: no APIs or patterns are deprecated in this phase.

---

## Open Questions

1. **build_signals NULL game_start_time crash**
   - What we know: After the SQL fix, `load_snapshots` will not return NULL-game rows. But `build_signals` directly accesses `row["game_start_time"]` (line 104) without a `.get()` — if any other code path passes a row with `game_start_time=None`, it raises `TypeError`.
   - What's unclear: Should `build_signals` be hardened with a None-guard on `game_start_time` as a defensive layer in addition to the SQL filter?
   - Recommendation: Yes — add a `game_start_time is None` skip guard in `build_signals` (parallel to the existing `price is None` guard) with a `logger.debug`. This satisfies the success criterion ("NULL row is not silently excluded") and is testable without a real database.

2. **make_nba_quant_agent docstring placement**
   - What we know: `make_nba_quant_agent` lives in `prop/nba_agents.py`, not in `prop/agents.py`. Parallel docstring updates are needed in both files.
   - What's unclear: Whether CTXT-04 success criterion requires both `make_prop_quant_agent` and `make_nba_quant_agent` to be updated.
   - Recommendation: Yes — the success criterion says "Prop agent entry points (make_prop_quant_agent, make_nba_prop_quant_agent)" — both need the context_update→prop ordering and situational_params fallback documented.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (pyproject.toml) |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_backtest_pipeline.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QUANT-04 | NULL game_id row not silently dropped from backtest replay | unit | `pytest tests/test_backtest_pipeline.py::test_null_game_id_row_not_silently_dropped -x` | ❌ Wave 0 |
| ARBT-01 | quant_analysis before arbitrage_analysis comment present in graph.py | manual-only | grep `ARBT-01` src/sportsbet/graph/graph.py | N/A — structural |
| CTXT-04 | context_update→prop ordering documented in make_prop_quant_agent | manual-only | grep `context_update` src/sportsbet/prop/agents.py | N/A — structural |
| PROP-04 | make_nba_quant_agent documents NBA context ordering | manual-only | grep `nba_context_producer` src/sportsbet/prop/nba_agents.py | N/A — structural |

**Manual-only justification:** Documentation presence checks (ARBT-01, CTXT-04, PROP-04) are verifiable by grep/review but do not require automated test coverage — the existing passing test suite already validates the underlying logic; this phase only adds developer documentation for callers.

### Sampling Rate
- **Per task commit:** `pytest tests/test_backtest_pipeline.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_backtest_pipeline.py::test_null_game_id_row_not_silently_dropped` — covers QUANT-04 NULL fix

*(All other test infrastructure is in place from prior phases.)*

---

## Sources

### Primary (HIGH confidence)
- Direct code reading: `src/sportsbet/quant/backtest_replay.py` — `load_snapshots` function with LEFT JOIN and WHERE clause
- Direct code reading: `src/sportsbet/graph/graph.py` — existing PROP-04 two-invocation comment block (lines 307–317)
- Direct code reading: `src/sportsbet/graph/agents.py` — `make_arbitrage_agent` Guard 1 (quant_result is None → return ev_signal=None)
- Direct code reading: `src/sportsbet/prop/agents.py` — `make_prop_quant_agent` and `state.get("situational_params") or {}` fallback
- Direct code reading: `src/sportsbet/prop/nba_agents.py` — `make_nba_quant_agent` and NBA context adjustment pipeline
- Direct code reading: `src/sportsbet/graph/router.py` — routing table mapping request_type to node names
- Direct code reading: `.planning/STATE.md` — locked decisions, especially Phase 16 and Phase 22 entries
- PostgreSQL documentation (well-known language semantics): NULL propagation in WHERE clauses with LEFT JOIN

### Secondary (MEDIUM confidence)
- `.planning/phases/16-integration-fix-and-doc-hygiene/16-01-PLAN.md` — established the PROP-04 two-invocation comment pattern
- `.planning/phases/23-prop-ev-fix/23-01-SUMMARY.md` — confirmed player_prop_snapshots flow and context_agent Step 1c

### Tertiary (LOW confidence)
- None.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are established project dependencies
- Architecture: HIGH — all patterns are direct extensions of Phase 16 patterns verified in source code
- SQL NULL fix: HIGH — standard PostgreSQL NULL semantics, no ambiguity
- Pitfalls: HIGH — observed directly from code analysis
- Test strategy: HIGH — mirrors existing test_backtest_pipeline.py patterns

**Research date:** 2026-03-26
**Valid until:** Stable — no external dependencies; all findings are from project source code

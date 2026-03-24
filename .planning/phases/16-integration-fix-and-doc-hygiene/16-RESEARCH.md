# Phase 16: Integration Fix & Documentation Hygiene - Research

**Researched:** 2026-03-24
**Domain:** Python source code repair + documentation/frontmatter hygiene
**Confidence:** HIGH

## Summary

Phase 16 is a focused cleanup phase with two distinct workstreams: (1) a one-line code fix for GAP-INT-1 and a documentation comment addition for GAP-INT-2, and (2) systematic repair of stale documentation across REQUIREMENTS.md, ROADMAP.md, and 7 SUMMARY files. All findings are based on direct inspection of the codebase — no external libraries or APIs are involved.

The code changes are minimal and low-risk. The audit has already identified the exact file, line, and fix for GAP-INT-1. GAP-INT-2 requires only a comment addition to `graph.py`. The documentation work is purely mechanical: updating checkbox states, traceability status labels, and adding `requirements_completed` frontmatter fields to SUMMARY files that are missing or have the wrong key name.

**Primary recommendation:** Single plan (16-01) covering both the code fix and the documentation sweep. No new modules, no new tests required — the existing test suite already validates the corrected behavior, and documentation changes carry no regression risk.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROP-01 | System ingests live NFL and NBA player prop odds from The Odds API and writes timestamped PlayerPropSnapshot rows | GAP-INT-1 fix ensures NBA sport value is passed to fetch_player_props() — corrects the path that was always fetching NFL props regardless of sport state |
| CTXT-04 | Context Agent updates global game state JSON on binary state changes and propagates updated state through GraphState | GAP-INT-1 also touches CTXT-04 — the sport routing in make_context_agent already works for game odds (Phase 15); prop snapshot ingestion now needs the same sport variable |
| PROP-04 | System incorporates Kinematic Agent signals into NFL receiving prop probability estimates where NGS data is available | GAP-INT-2 documents the two-invocation checkpoint pattern in graph.py that enables PROP-04 — no code change needed, only a descriptive comment |
</phase_requirements>

---

## Standard Stack

### Core (all pre-installed, no additions needed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12 | Language | Project standard |
| LangGraph | 1.1.0 | Graph state management | Project standard (all agent wiring) |
| Pydantic v2 | current | Model validation | Non-negotiable per CLAUDE.md |
| structlog | current | Structured logging in agents | Established pattern across all phases |

### No New Dependencies
Phase 16 makes no changes that require new packages. All code and documentation edits touch existing files only.

---

## Architecture Patterns

### GAP-INT-1: One-Line Fix in agents.py

**What:** `make_context_agent` in `src/sportsbet/graph/agents.py` has a Step 1c that fetches player prop snapshots. At line 246, `fetch_player_props("nfl")` is hardcoded. The `sport` variable (already resolved earlier in the same closure at line 187) must be passed instead.

**Current code (line 246):**
```python
raw_props = await poller.fetch_player_props("nfl")
```

**Corrected code:**
```python
raw_props = await poller.fetch_player_props(sport)
```

**Context:** The `sport` variable is already in scope at line 246 — it was assigned at line 187 via `sport = state.get("sport") or "nfl"`. The fix requires no new variables, no new imports, and no structural changes.

**Verification:** The comment at line 241 already says "Scoped to NFL only in Phase 14; NBA prop ingestion is Phase 15 territory." This comment must also be updated to remove the "NFL only" scope note.

**Test impact:** Existing tests in `tests/test_context_and_vig_completion.py` and `tests/test_prop_integration_gap_closure.py` already mock `fetch_player_props`. The fix must be verified by adding or updating a test that passes `sport="nba"` and confirms `fetch_player_props` is called with `"nba"`, not `"nfl"`. This is the minimal test addition for PROP-01 NBA path.

### GAP-INT-2: Two-Invocation Checkpoint Comment in graph.py

**What:** The `graph.py` module docstring and/or the `create_graph()` function body needs a comment documenting that PROP-04 kinematic boost uses a two-invocation pattern:

1. First `ainvoke` with `request_type="kinematic_analysis"` and a `thread_id` — populates `kinematic_result` in checkpoint state
2. Second `ainvoke` with `request_type="prop_analysis"` using the **same `thread_id`** — `_apply_kinematic_adjustment` in `prop/agents.py` reads `state.get("kinematic_result")` from the persisted checkpoint

**Where to add the comment:** The module-level docstring in `graph.py` already documents each phase's updates in a structured way (lines 1-51). Add a Phase 16 update section there. Also add an inline comment near the `kinematic_agent -> END` edge definition (line 275) pointing to the PROP-04 pattern.

**Pattern to document:**
```python
# PROP-04 kinematic boost: two-invocation checkpoint pattern.
# To use kinematic signals in NFL receiving prop probability:
#   1. ainvoke({"request_type": "kinematic_analysis", ...}, config={"configurable": {"thread_id": tid}})
#      → populates state["kinematic_result"] in the AsyncSqliteSaver checkpoint
#   2. ainvoke({"request_type": "prop_analysis", ...}, config={"configurable": {"thread_id": tid}})
#      → _apply_kinematic_adjustment() reads state.get("kinematic_result") from checkpoint
# Both calls MUST use the same thread_id. Single-invocation kinematic+prop is not supported.
```

### REQUIREMENTS.md Documentation Fix

**Stale entries identified by audit (all require manual text edits):**

| REQ-ID | Current (Stale) | Correct Value |
|--------|----------------|---------------|
| DATA-03 | `[ ]` checkbox | `[x]` checkbox |
| DATA-03 | traceability: "Pending" | "Complete" |
| QUANT-01 | `[ ]` checkbox | `[x]` checkbox |
| QUANT-01 | traceability: "Pending" | "Complete" |
| QUANT-03 | `[ ]` checkbox | `[x]` checkbox |
| QUANT-03 | traceability: "Pending" | "Complete" |
| CTXT-02 | `[ ]` checkbox | `[x]` checkbox |
| CTXT-02 | traceability: "Pending" | "Complete" |
| DATA-01 | traceability: "Pending" | "Complete" |

**Evidence from audit:** REQUIREMENTS.md lines 101-143 contain the traceability table. The audit confirmed all 32 requirements are SATISFIED in VERIFICATION.md files. No checkbox should be `[ ]`.

**Additional fix:** The "Pending (gap closure phases 14–15): 5" note at line 138 is stale. After Phase 15 completion, all listed requirements are closed. This footnote should be updated or removed.

### ROADMAP.md Documentation Fix

**Stale entries identified by audit:**

| Item | Current | Correct |
|------|---------|---------|
| Phase 2 header | `[ ]` | `[x]` completed 2026-03-10 |
| Phase 1 plan `01-03-PLAN.md` | `[ ]` | `[x]` |

**Current ROADMAP.md lines 63-65:**
```markdown
- [ ] 02-01-PLAN.md — Pydantic v2 I/O models...
- [ ] 02-02-PLAN.md — GraphState TypedDict...
- [ ] 02-03-PLAN.md — SqliteSaver checkpointing...
```
All Phase 2 plan checkboxes are `[ ]`. All should be `[x]`.

**Current ROADMAP.md line 49:**
```markdown
- [ ] 01-03-PLAN.md — nflreadpy PBP/NGS/player-stats ingestion...
```
Should be `[x]`.

**Note:** The audit also notes Phase 2 `[ ]` in the phase header (line 16 area). Verified: line 16 of ROADMAP.md shows `- [x] **Phase 2: Agent Infrastructure**` — this is already checked. The unchecked items are the plan sub-items within Phase 2.

### SUMMARY Files Documentation Fix

The audit identified 7 SUMMARY files with missing or empty `requirements_completed` frontmatter. Inspection reveals the situation is more nuanced — some already have the field, some use a different key name.

**Current state of each flagged SUMMARY file:**

| File | Current Field | Actual Value | Issue |
|------|--------------|--------------|-------|
| `03-02-SUMMARY.md` | `requirements-completed` | `[QUANT-02]` | Already present and correct — audit may have flagged an earlier version |
| `03-03-SUMMARY.md` | `requirements-completed` | `[QUANT-04]` | Already present and correct |
| `05-02-SUMMARY.md` | absent | (none) | Missing field — ARBT-03 and ARBT-04 are partially covered here (CorrelationGuard + Aggregator classes, wired in 05-03) |
| `10-01-SUMMARY.md` | absent | (none) | Missing field — PROP-01 and PROP-02 listed in `provides` but not in `requirements_completed` |
| `13-01-SUMMARY.md` | absent | (none) | Missing field — PROP-06 and PROP-07 listed in narrative but not in frontmatter |
| `14-01-SUMMARY.md` | `requirements_closed` | `[PROP-01, PROP-06, INFRA-01]` | Wrong key name — convention is `requirements_completed` |
| `15-01-SUMMARY.md` | absent | (none) | Missing field — QUANT-02, CTXT-01, CTXT-04 satisfied per VERIFICATION |

**Correct `requirements_completed` values to add/fix:**

| File | Value to Set |
|------|-------------|
| `05-02-SUMMARY.md` | `[]` (ARBT-03/ARBT-04 completed in 05-03, not 05-02 directly) OR omit if convention is to only list what this specific plan closes |
| `10-01-SUMMARY.md` | `[PROP-01, PROP-02]` (PropParams/PropResult models + PlayerPropSnapshot ORM + fetch_player_props are the PROP-01/PROP-02 deliverables) |
| `13-01-SUMMARY.md` | `[PROP-06, PROP-07]` (PropArbitrageAgent + CorrelationGuard extension) |
| `14-01-SUMMARY.md` | rename `requirements_closed` → `requirements_completed`, keep `[PROP-01, PROP-06, INFRA-01]` |
| `15-01-SUMMARY.md` | `[QUANT-02, CTXT-01, CTXT-04]` |

**Note on 05-02-SUMMARY.md:** The audit says "covered by 05-03 SUMMARY." If the convention is that a plan SUMMARY only lists requirements fully satisfied by that plan (not just partially addressed), then `05-02-SUMMARY.md` should receive `requirements_completed: []` or the field may be omitted with a note. The safer choice is to add the field with an empty list and a comment, or omit it if no requirement is fully satisfied by 05-02 alone.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Test for NBA prop sport routing | New test infrastructure | Extend `tests/test_context_and_vig_completion.py` or `tests/test_prop_integration_gap_closure.py` | Pattern established in Phase 14/15 |
| Documentation format | Custom format | Existing frontmatter YAML convention used in all prior SUMMARY files | Consistency with planner/verifier tooling |

---

## Common Pitfalls

### Pitfall 1: Updating the Wrong `sport` Variable in agents.py
**What goes wrong:** There are two places in `make_context_agent` that use the word "sport" — the parameter to `make_context_agent()` itself (if any) and the local variable `sport = state.get("sport") or "nfl"` at line 187. Only the local variable is in scope at line 246 where `fetch_player_props("nfl")` is called.
**How to avoid:** Replace the string literal `"nfl"` with the variable `sport` that is already in scope. Do not introduce a new parameter.

### Pitfall 2: Missing Comment Update in Step 1c
**What goes wrong:** Line 241 says "Scoped to NFL only in Phase 14; NBA prop ingestion is Phase 15 territory." After the fix, this comment is false.
**How to avoid:** Update the Step 1c comment block to reflect that sport routing is now dynamic.

### Pitfall 3: Wrong YAML Key in SUMMARY Frontmatter
**What goes wrong:** 14-01-SUMMARY.md uses `requirements_closed` — other tools or the planner may look for `requirements_completed`. Using inconsistent key names means the field is invisible to automated tooling.
**How to avoid:** Rename `requirements_closed` to `requirements_completed` in 14-01-SUMMARY.md.

### Pitfall 4: Over-Counting SUMMARY Files
**What goes wrong:** The audit lists 7 SUMMARY files. Direct inspection shows that 03-02 and 03-03 already have `requirements-completed` (with hyphen, not underscore). If the convention is underscore, these may also need to be renamed. Verify the exact key format used in SUMMARY files that the planner/verifier consumes.
**How to avoid:** Check existing correct SUMMARYs (e.g., 03-02, 03-03, which have `requirements-completed:`) to determine if the hyphen or underscore convention is what tooling expects. If both exist, standardize to one form.

### Pitfall 5: Stale Footnote in REQUIREMENTS.md
**What goes wrong:** The "Pending (gap closure phases 14–15): 5" footnote at line 138 will remain stale if only the checkboxes are updated but not this summary line.
**How to avoid:** Update or remove the coverage footnote after all checkboxes are corrected to `[x]`.

### Pitfall 6: Breaking Existing Tests When Updating agents.py
**What goes wrong:** `tests/test_context.py` and `tests/test_prop_integration_gap_closure.py` mock `fetch_player_props`. If the mock only checks call count but not call arguments, the test will still pass with the wrong argument. A new assertion `assert mock_fetch_player_props.call_args == call("nba")` is needed.
**How to avoid:** Add an explicit assertion on the argument passed to `fetch_player_props` for the NBA sport path.

---

## Code Examples

### Pattern: agents.py GAP-INT-1 fix context
```python
# Source: src/sportsbet/graph/agents.py lines 184-187 (existing, correct)
sport = state.get("sport") or "nfl"  # already resolved

# Line 246 — current (buggy):
raw_props = await poller.fetch_player_props("nfl")

# Line 246 — corrected:
raw_props = await poller.fetch_player_props(sport)
```

### Pattern: graph.py two-invocation comment placement
```python
# Source: src/sportsbet/graph/graph.py line 274 (existing)
# kinematic_agent always terminates at END (independent pipeline)
builder.add_edge("kinematic_agent", END)

# After line 275 — add comment block:
# PROP-04 kinematic boost: two-invocation checkpoint pattern (GAP-INT-2).
# To incorporate kinematic separation/press-man signals into NFL receiving prop estimates:
#   Invocation 1: ainvoke({"request_type": "kinematic_analysis", ...},
#                          config={"configurable": {"thread_id": tid}})
#                 → kinematic_agent writes KinematicAnalysis to state["kinematic_result"]
#                 → AsyncSqliteSaver persists it in the checkpoint under thread_id
#   Invocation 2: ainvoke({"request_type": "prop_analysis", ...},
#                          config={"configurable": {"thread_id": tid}})
#                 → prop_quant_agent reads state.get("kinematic_result") from checkpoint
#                 → _apply_kinematic_adjustment() boosts probability if RECEIVING_PROPS match
# Both invocations MUST use the same thread_id. Single-invocation path not supported.
```

### Pattern: SUMMARY frontmatter field addition
```yaml
# Correct frontmatter key (check existing files for hyphen vs underscore):
requirements_completed: [QUANT-02, CTXT-01, CTXT-04]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `fetch_player_props("nfl")` hardcoded | `fetch_player_props(sport)` dynamic | Phase 16 (this phase) | NBA prop snapshots now correctly ingested when sport="nba" |
| No documentation of two-invocation pattern | Comment in graph.py | Phase 16 (this phase) | PROP-04 kinematic integration is now documented for API consumers |

---

## Open Questions

1. **YAML key convention: hyphen vs underscore in SUMMARY frontmatter**
   - What we know: 03-02 and 03-03 use `requirements-completed` (hyphen); 14-01 uses `requirements_closed` (underscore + different name); 15-01 uses nothing
   - What's unclear: Which key does the GSD toolchain look for when checking SUMMARY compliance?
   - Recommendation: Inspect one SUMMARY file that the verifier/planner has confirmed as correct (e.g., 01-02 or 02-02) and use that exact key spelling for all additions

2. **05-02-SUMMARY.md requirements_completed value**
   - What we know: 05-02 delivers CorrelationGuard and Aggregator classes; ARBT-03 and ARBT-04 are wired in 05-03
   - What's unclear: Should 05-02 list ARBT-03/ARBT-04 as "completed" even though graph wiring happens in 05-03?
   - Recommendation: Use `requirements_completed: []` with a comment that wiring is in 05-03, or check what 05-03-SUMMARY.md currently has

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (pyproject.toml) |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_context_and_vig_completion.py tests/test_prop_integration_gap_closure.py -x -q` |
| Full suite command | `python -m pytest -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROP-01 | `fetch_player_props(sport)` called with "nba" when state sport="nba" | unit | `python -m pytest tests/test_context_and_vig_completion.py -k "nba" -x` | Partial — existing tests mock the call; new assertion needed |
| CTXT-04 | Context agent sport routing unchanged for NFL path | unit | `python -m pytest tests/test_context.py -x` | Yes |
| PROP-04 | graph.py contains two-invocation comment | inspection/documentation | N/A — documentation check only | N/A |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_context_and_vig_completion.py tests/test_prop_integration_gap_closure.py tests/test_context.py -x -q`
- **Per wave merge:** `python -m pytest -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] Add test assertion in existing test file that `fetch_player_props` is called with `sport="nba"` when GraphState has `sport="nba"` — covers REQ-PROP-01 NBA path

---

## Sources

### Primary (HIGH confidence)
- Direct file inspection: `src/sportsbet/graph/agents.py` lines 187, 246 — confirmed exact bug location and variable in scope
- Direct file inspection: `src/sportsbet/graph/graph.py` lines 1-295 — confirmed no existing two-invocation comment
- `.planning/v1.0-MILESTONE-AUDIT.md` — authoritative source for all debt items, file paths, and line numbers
- `.planning/REQUIREMENTS.md` lines 99-143 — confirmed exact stale checkbox and traceability entries
- `.planning/ROADMAP.md` lines 63-65 — confirmed Phase 2 plan sub-items are `[ ]`
- Direct inspection of all 7 flagged SUMMARY files — confirmed actual field presence/absence

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` Decisions section — confirms sport routing pattern and closure variable conventions used across all prior phases

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Code fix (GAP-INT-1): HIGH — exact line, exact fix, variable already in scope
- Documentation comment (GAP-INT-2): HIGH — exact location and content pattern documented in audit
- REQUIREMENTS.md fixes: HIGH — audit table lists every stale entry with current and correct values
- ROADMAP.md fixes: HIGH — specific checkboxes confirmed unchecked by audit
- SUMMARY frontmatter fixes: MEDIUM — exact field values for 5 of 7 files are clear; key name convention (hyphen vs underscore) needs verification for 2 files

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable codebase, no external dependencies)

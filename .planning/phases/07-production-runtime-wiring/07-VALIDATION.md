---
phase: 7
slug: production-runtime-wiring
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/test_graph.py tests/test_arbitrage.py tests/test_vig.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_graph.py tests/test_arbitrage.py tests/test_vig.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 7-01-01 | 01 | 0 | KINE-02 | unit | `pytest tests/test_graph.py -k "test_graphstate_has_receiver_gsis_id" -x` | ❌ W0 | ⬜ pending |
| 7-01-02 | 01 | 0 | QUANT-02 | unit | `pytest tests/test_graph.py -k "test_extract_odds_devigged" -x` | ❌ W0 | ⬜ pending |
| 7-01-03 | 01 | 0 | ARBT-01,03,04,KINE-01 | smoke | `pytest tests/test_graph.py -k "test_create_graph_with_sqlite_nodes" -x` | ❌ W0 | ⬜ pending |
| 7-01-04 | 01 | 1 | KINE-02 | unit | `pytest tests/test_graph.py -k "test_graphstate_has_receiver_gsis_id" -x` | ✅ | ⬜ pending |
| 7-01-05 | 01 | 1 | ARBT-01,03,04,KINE-01 | smoke | `pytest tests/test_graph.py -k "test_create_graph_with_sqlite_nodes" -x` | ✅ | ⬜ pending |
| 7-01-06 | 01 | 1 | QUANT-02 | unit | `pytest tests/test_graph.py -k "test_extract_odds_devigged" -x` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_graph.py` — add `test_graphstate_has_receiver_gsis_id` (asserts `"receiver_gsis_id"` in `get_type_hints(GraphState)`)
- [ ] `tests/test_graph.py` — add `test_extract_odds_devigged` (asserts devigged prob != raw division result for -110 American odds)
- [ ] `tests/test_graph.py` — add `test_create_graph_with_sqlite_nodes` (smoke: `create_graph()` with all 7 node params confirms arbitrage, guard, aggregator, kinematic nodes reachable via `request_type` dispatch; uses `MemorySaver()` not disk)
- [ ] Update `make_minimal_state()`, `_base_state()`, and `make_checkpoint_state()` in existing test files to include `"receiver_gsis_id": ""`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Kinematic agent returns non-empty NGS data for a real receiver GSIS ID against live DB | KINE-01, KINE-02 | Requires live PostgreSQL with NGS data loaded | Run a `kinematic_analysis` ainvoke with a known WR GSIS ID; confirm `kinematic_result.separation_at_catch` is non-None |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

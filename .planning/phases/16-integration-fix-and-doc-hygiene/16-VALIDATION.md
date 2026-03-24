---
phase: 16
slug: integration-fix-and-doc-hygiene
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 16-01-01 | 01 | 1 | PROP-01 | unit | `pytest tests/ -k "test_fetch_player_props" -x -q` | ✅ | ⬜ pending |
| 16-01-02 | 01 | 1 | PROP-04 | manual | inspect graph.py comment | ✅ | ⬜ pending |
| 16-01-03 | 01 | 1 | CTXT-04 | manual | inspect REQUIREMENTS.md | ✅ | ⬜ pending |
| 16-01-04 | 01 | 1 | CTXT-04 | manual | inspect SUMMARY files | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `fetch_player_props(sport)` called with dynamic sport from GraphState | PROP-01 | Code inspection — verifying string literal replaced with variable | Grep `agents.py` for `fetch_player_props("nfl")` — should return 0 matches |
| `graph.py` has two-invocation checkpoint comment | PROP-04 | Comment-only change | Read graph.py near kinematic_agent edge and verify comment documents two-invocation pattern |
| REQUIREMENTS.md checkboxes all `[x]` | CTXT-04 | Documentation audit | Grep REQUIREMENTS.md for `[ ]` — should return 0 matches |
| 7 SUMMARY files have non-empty `requirements_completed` | CTXT-04 | Documentation audit | Read each SUMMARY file frontmatter |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

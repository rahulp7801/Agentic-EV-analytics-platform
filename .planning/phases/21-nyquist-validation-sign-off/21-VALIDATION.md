---
phase: 21
slug: nyquist-validation-sign-off
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 21 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pytest.ini |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 21-01-01 | 01 | 1 | Phase 16 sign-off | doc edit | `grep "nyquist_compliant: true" .planning/phases/16-*/16-VALIDATION.md` | ✅ | ⬜ pending |
| 21-02-01 | 02 | 2 | Phase 18 sign-off | doc edit | `grep "nyquist_compliant: true" .planning/phases/18-*/18-VALIDATION.md` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. This phase edits VALIDATION.md frontmatter only — no new test files needed.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Phase 16 VALIDATION.md frontmatter flip | Phase 21 SC-1 | File edit confirmed by grep | `grep "nyquist_compliant: true" .planning/phases/16-*/16-VALIDATION.md` |
| Phase 18 VALIDATION.md frontmatter flip | Phase 21 SC-2 | File edit confirmed by grep | `grep "nyquist_compliant: true" .planning/phases/18-*/18-VALIDATION.md` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

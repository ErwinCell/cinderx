# Task Plan: Enable LIGHTWEIGHT_FRAMES with LTO/PGO/ADAPTIVE_STATIC on ARM 3.14

## Goal
Make `ENABLE_LIGHTWEIGHT_FRAMES` build and run correctly on Python 3.14 ARM, and verify it can be enabled together with `CINDERX_ENABLE_LTO=1`, `CINDERX_ENABLE_PGO=1`, and `ENABLE_ADAPTIVE_STATIC_PYTHON=1` through remote-only validation.

## Current Phase
Phase 6

## Phases

### Phase 1: Brainstorming & Requirements
- [x] Load required skills (`using-superpowers`, `planning-with-files`, `brainstorming`, `writing-plans`, `test-driven-development`, `verification-before-completion`)
- [x] Capture constraints from user prompt
- [x] Clarify remote test entrypoint details and acceptance criteria
- [x] Produce design options and get approval
- **Status:** complete

### Phase 2: Writing Plan
- [x] Write implementation plan in `docs/plans/YYYY-MM-DD-enable-lightweight-frames-314-arm.md`
- [x] Ensure plan follows TDD steps and remote-only verification steps
- **Status:** complete

### Phase 3: TDD (RED -> GREEN)
- [x] Add/adjust tests for `ENABLE_LIGHTWEIGHT_FRAMES` behavior and option wiring
- [x] Run tests on remote entrypoint and observe RED failure first
- [x] Implement minimal code to reach GREEN
- **Status:** complete

### Phase 4: Integration (LTO/PGO/Adaptive Static)
- [x] Ensure flags coexist in setup/CMake/runtime behavior
- [x] Address compile/runtime issues discovered on ARM remote host
- [x] Keep changes minimal and targeted
- **Status:** complete

### Phase 5: Verification Before Completion
- [x] Run full remote verification matrix (no-LTO, LTO, PGO+LTO as applicable)
- [x] Verify `ENABLE_LIGHTWEIGHT_FRAMES` effective and no regression to adaptive static
- [x] Collect command outputs/evidence and append to `findings.md`
- **Status:** complete

### Phase 6: Delivery
- [x] Summarize code changes and validation evidence
- [ ] Confirm repo clean state and provide next-step commands
- **Status:** in_progress

## Key Questions
1. What exact command/script should be treated as `<远端测试入口>` for this task? -> `ssh root@124.70.162.35`
2. What runtime/API signal is considered authoritative for "LIGHTWEIGHT_FRAMES enabled"? -> `cinderx.is_lightweight_frames_enabled()`
3. Should final verification include full `test_oss_quick.py` plus targeted new tests? -> Yes.

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use remote-only tests/verification | Explicit user constraint |
| Use full closed loop (brainstorming -> plan -> TDD -> verification) | Explicit user workflow requirement |
| Stage A scope: 3.14 ARM first, 3.15 default off | User requested 3.14 priority and deferred 3.15 |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| planning-with-files default catchup script path missing (`~/.codex/skills/...`) | 1 | Used actual installed path `~/.codex/planning-with-files/.codex/skills/...` |
| `CINDERX_ENABLE_PGO=1 CINDERX_ENABLE_LTO=1` workload failed intermittently in `test_generators` | 1 | Added bounded workload retry in `setup.py` (`run_pgo_workload`, 2 attempts) and re-verified remotely |


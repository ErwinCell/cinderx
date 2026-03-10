# Task Plan: Issue 17 Redundant Global Load/Guard Elimination

## Goal
Eliminate redundant `LoadGlobalCached + GuardIs` sequences for the same global in the same basic block when it is safe to do so.

## Workflow
- Brainstorm equivalent: inspect issue text, current HIR semantics, and remote repro before editing.
- Write plan: keep decisions and evidence in this directory.
- TDD equivalent: add targeted HIR pass tests before or alongside implementation.
- Verification before completion: use the remote ARM environment for HIR reproduction and validation.

## Constraints
- Do not break global invalidation semantics.
- Prefer the smallest safe optimization scope over a broad but under-specified CSE.
- All meaningful verification should use the remote host `124.70.162.35`.

## Status
- [x] Start planning
- [x] Review issue 17 source and local semantics
- [x] Reproduce on remote
- [ ] Implement
- [x] Verify remotely

## Result
- The optimization proposed in issue 17 is not safe for the reproduced cases.
- Both the issue's `generators:tree` description and the provided minimal repro shape involve repeated `LoadGlobalCached + GuardIs` separated by `VectorCall`, which can execute arbitrary Python and mutate globals.
- No code change was made for issue 17 in this pass. The safe next step, if needed, is a narrower optimization limited to regions with no arbitrary-execution barrier and no `AGlobal` invalidation risk.

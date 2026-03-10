# Task Plan: Remote Review for Issue 14

## Goal
Review the issue 14 optimization proposal and current local implementation against the real Linux/ARM target environment at `124.70.162.35`.

## Scope
- Review-only unless the evidence shows an obvious correctness gap that must be called out.
- Validate whether the proposal's HIR and assembly assumptions match reality.
- Focus on correctness, NaN semantics, deopt/refcount behavior, and whether the rewrite pattern is too narrow or too broad.

## Steps
- [x] Load required skills
- [ ] Collect local review context and relevant checklists
- [ ] Connect to remote host and locate target repo / branch
- [ ] Reproduce or inspect current HIR / assembly for the float-compare case
- [ ] Compare proposal assumptions with actual backend semantics
- [ ] Write findings and recommendations

## Status
Current phase: local preflight

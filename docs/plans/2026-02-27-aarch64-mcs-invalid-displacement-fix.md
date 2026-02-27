# AArch64 MCS InvalidDisplacement Formal Fix Plan

Date: 2026-02-27
Branch: `bench-cur-7c361dce`
Owner: Codex + User

## Goal

Fix AArch64 `InvalidDisplacement` failures under:

- `PYTHONJITMULTIPLECODESECTIONS=1`
- large section distances (e.g. hot/cold = 2 MiB)

and keep verification fully on the remote ARM entrypoint.

## 1) Brainstorming

Observed symptom:

- `code->resolveUnresolvedLinks()` fails with AsmJit `InvalidDisplacement`.

Likely root causes:

- Short-range AArch64 branch forms (`b.cond`, `cbz/cbnz`) crossing far hot/cold.
- `adr` users in stage-2 deopt trampoline pointing at hot labels from cold.

Fix candidates:

1. Replace short conditional branches with local-veneer pattern:
   - short inverse-branch to local `skip`
   - long-range unconditional `b target`
2. Keep stage-1 deopt trampolines cold, move stage-2 deopt trampoline to hot.
3. Add a large-distance ARM runtime smoke test to prevent regression.

## 2) Writing Plans

Implementation steps:

1. Apply branch-veneer translators for guard and generic branch op rules.
2. Split deopt exit generation by stage (cold stage-1, hot stage-2).
3. Add runtime smoke for MCS large-distance force-compile.
4. Run remote entrypoint with `SKIP_PYPERF=1` for quick RED/GREEN.
5. If GREEN, run one full remote entrypoint pass (with pyperformance gate).
6. Record key outcomes in `findings.md`.

## 3) Test-Driven Development

RED target:

- `test_multiple_code_sections_large_distance_force_compile_smoke`
  fails before fix under 2 MiB/2 MiB section sizing.

GREEN target:

- same test passes on ARM after fix.

Guardrails:

- existing `test_multiple_code_sections_force_compile_smoke` keeps passing.
- existing `test_aarch64_call_sites_are_compact` keeps passing.

## 4) Verification Before Completion

Unified remote entry only:

- `scripts/arm/remote_update_build_test.sh`

Required pass criteria:

1. Wheel build/install succeeds.
2. `cinderx/PythonLib/test_cinderx/test_arm_runtime.py` passes.
3. JIT effectiveness smoke passes.
4. (final pass) pyperformance gate jobs complete.

Deliverables:

- code changes in JIT/codegen + tests
- findings updates in `findings.md`

## Execution Result

Status summary:

1. Brainstorming: completed.
2. Writing plans: completed.
3. TDD: completed (`RED -> GREEN` on new 2MiB/2MiB smoke).
4. Verification-before-completion: partially completed due pre-existing smoke crash outside this fix scope.

What changed during execution:

- Root cause was refined from generic branch distance to cold->hot `ldr literal` reachability (`imm19`) for helper-call targets.
- Implemented cold-section call lowering fallback (`mov + blr`) while retaining hot-section deduplicated literal-pool calls.
- Kept deopt stage split (stage-1 cold, stage-2 hot).
- Reverted broad branch-veneer rewrite because it caused size-regression guard failures.

Remote-entry verification outcome:

- `scripts/arm/remote_update_build_test.sh`:
  - wheel build/install: pass
  - `test_arm_runtime.py`: pass (`Ran 9 tests ... OK`)
  - includes new large-distance test and size guard tests passing
- Remaining failure:
  - line-210 smoke segfault in pyperf venv (`PYTHONJITAUTO=0` + `re.compile`)
  - reproduced on baseline commit `436bee31`, so treated as pre-existing blocker, not introduced by this fix.

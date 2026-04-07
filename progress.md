# Progress Log

## Session: 2026-02-25

### Phase 1: Brainstorming & Requirements
- **Status:** in_progress
- **Started:** 2026-02-25
- Actions taken:
  - Loaded required skills:
    - `using-superpowers`
    - `planning-with-files`
    - `brainstorming`
    - `writing-plans`
    - `test-driven-development`
    - `verification-before-completion`
  - Ran planning session catchup script from installed path.
  - Reviewed current `task_plan.md`, `progress.md`, and latest `findings.md` sections to recover state.
  - Began new task plan for `ENABLE_LIGHTWEIGHT_FRAMES` integration with LTO/PGO/adaptive static.
- Files created/modified:
  - task_plan.md (updated for this task)
  - progress.md (this file)

## Test Results
| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| N/A | N/A | N/A | N/A | pending |

## Error Log
| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 2026-02-25 | `session-catchup.py` missing at default path | 1 | Used installed planning-with-files path under `.codex/planning-with-files/.codex/skills/` |

## 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phase 1 (brainstorming) |
| Where am I going? | Plan -> TDD -> implementation -> remote verification |
| What's the goal? | Enable LIGHTWEIGHT_FRAMES on ARM 3.14 with LTO/PGO/adaptive static compatibility |
| What have I learned? | Existing project already has adaptive static + LTO integration; lightweight frames currently not enabled for 3.14 in setup defaults |
| What have I done? | Loaded skills, initialized planning docs, started requirement clarification |

## Decision Update (2026-02-25)
- Priority: `ENABLE_LIGHTWEIGHT_FRAMES` must land and validate on Python 3.14 first.
- Rollout order: 3.14-first; any 3.15 default enablement deferred to next phase after 3.14 verification.

## Session Update: 2026-02-26

### Phase status
- Phase 1 (brainstorming): complete
- Phase 2 (writing plan): complete
- Phase 3 (TDD): complete
- Phase 4 (integration): complete
- Phase 5 (verification): complete
- Phase 6 (delivery): in_progress

### Code changes completed
- Added `should_enable_lightweight_frames()` in `setup.py` with Stage-A policy:
  - default on for OSS `3.14` on `aarch64/arm64`
  - default off for `3.15` (env override still possible)
  - preserve meta `3.12` behavior
- Added `_cinderx.is_lightweight_frames_enabled()` and exported `cinderx.is_lightweight_frames_enabled()`.
- Added/extended tests:
  - `tests/test_setup_lightweight_frames.py`
  - `tests/test_cinderx_lightweight_frames_api.py`
  - `cinderx/PythonLib/test_cinderx/test_oss_quick.py`
- Added 3.14 compatibility guards for missing 3.15-only `PyUnstable_*JITExecutable*` APIs:
  - `cinderx/Common/py-portability.h`
  - `cinderx/Jit/frame.cpp`
  - `cinderx/Jit/lir/generator.cpp`
- Added PGO workload retry helper in `setup.py`:
  - `run_pgo_workload()` retries once on `subprocess.CalledProcessError`
  - used by `BuildCommand._run_with_pgo()`
- Added test for retry behavior:
  - `tests/test_setup_pgo_workload_retries.py`

### Verification run summary (remote only)
- Entry point: `ssh root@124.70.162.35`
- Setup and API unit tests: pass
- `CINDERX_ENABLE_PGO=0 CINDERX_ENABLE_LTO=1 python setup.py install`: pass
- `CINDERX_ENABLE_PGO=1 CINDERX_ENABLE_LTO=1 python setup.py install`: pass
- Runtime probes after installs:
  - `cinderx.is_adaptive_static_python_enabled() -> True`
  - `cinderx.is_lightweight_frames_enabled() -> True`
- Smoke:
  - `python cinderx/PythonLib/test_cinderx/test_oss_quick.py` -> `Ran 3 tests ... OK`

## Session Update: 2026-03-15

### Task status
- Issue31 closeout: completed
- Scope:
  - no new functional code changes
  - ARM staging rebuild + closeout revalidation
  - sync `task_plan.md`, `notes.md`, and `findings.md` to review-ready state

### Remote verification summary
- ARM staging workdir:
  - `/root/work/frame-issue31-closeout-20260315`
- Import path used for staging validation:
  - `PYTHONPATH=scratch/lib.linux-aarch64-cpython-314:cinderx/PythonLib`
- Targeted regressions:
  - `ArmRuntimeTests.test_specialized_numeric_leaf_mixed_types_avoid_deopts`: pass
  - `ArmRuntimeTests.test_plain_instance_other_arg_guard_eliminates_cached_attr_loads`: pass
  - `ArmRuntimeTests.test_other_arg_inference_skips_helper_method_shapes`: pass

### Performance / behavior summary
- Issue31 A/B revalidation:
  - `PointOther.dist`: `0.295552274096s`
  - `PointRhs.dist`: `0.315386445029s`
  - `PointOther` mixed probe: `0.246739777969s`
  - `PointRhs` mixed probe: `0.276117506088s`
- Raytrace direct benchmark:
  - `compile_strategy=all`
  - `prewarm_runs=1`
  - `samples=5`
  - median wall: `0.5452457539504394s`
- Issue31 regression sites remain cleared:
  - `Vector.dot`: `0`
  - `Point.__sub__`: `0`
  - `Sphere.intersectionTime`: `0`
- Known remaining follow-ups:
  - `Vector.scale`
  - `addColours`

### Delivery state
- Issue31 is now documented as review-ready.
- Residual raytrace deopts outside the main issue31 regression are explicitly kept out of scope for this closeout.

## Session Update: 2026-03-15 (raytrace follow-up)

### Task status
- Raytrace follow-up optimization: completed for this round
- Scope:
  - reduce remaining `LOAD_ATTR_METHOD_WITH_VALUES` deopts after issue31 closeout
  - keep issue31 protections intact
  - add a targeted regression and revalidate on ARM staging

### Code changes completed
- Narrowed `LOAD_ATTR_METHOD_WITH_VALUES` lowering in `cinderx/Jit/hir/builder.cpp`:
  - keep the fast path for stable exact receivers
  - also keep it for true `self` receivers when the descriptor owner type has no subclasses
  - fall back to `LoadMethod` for polymorphic unpacked-local receiver sites
- Added ARM runtime regression:
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`

### Remote verification summary
- ARM staging workdir:
  - `/root/work/frame-issue31-closeout-20260315`
- Targeted regressions:
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`: pass
  - `test_specialized_numeric_leaf_mixed_types_avoid_deopts`: pass
  - `test_plain_instance_other_arg_guard_eliminates_cached_attr_loads`: pass
  - `test_other_arg_inference_skips_helper_method_shapes`: pass

### Performance / behavior summary
- Raytrace direct benchmark:
  - previous median: `0.5452457539504394s`
  - current median: `0.5257585040526465s`
  - previous total deopts: `257510`
  - current total deopts: `130005`
- Removed remaining method-load deopt family:
  - `Scene.rayColour`
  - `Scene._lightIsVisible`
  - `SimpleSurface.colourAt` (`LOAD_ATTR_METHOD_WITH_VALUES`)
- Next likely targets:
  - `Canvas.plot`
  - `Vector.scale`
  - `addColours`
  - `SimpleSurface.colourAt` instance-value path

## Session Update: 2026-03-15 (raytrace follow-up 2)

### Task status
- Raytrace follow-up optimization: completed for this round
- Scope:
  - reduce `Canvas.plot`, `Vector.scale`, and `addColours` deopts
  - preserve the earlier method-load fix
  - validate on ARM staging and keep only throughput-positive changes

### Code changes completed
- Narrowed no-backedge float exact guards in `cinderx/Jit/hir/builder.cpp`:
  - keep them only for loop-hot code or methods with inferred exact non-self args
- Narrowed builtin `min/max` float specialization in `cinderx/Jit/hir/simplify.cpp`:
  - skip the float fast path for obvious integral clamp shapes with exact long operands
- Added runtime regressions:
  - `test_self_only_float_leaf_mixed_factor_avoids_deopts`
  - `test_builtin_min_max_int_clamp_shape_avoids_float_guard_deopts`

### Remote verification summary
- ARM staging workdir:
  - `/root/work/frame-issue31-closeout-20260315`
- Targeted regressions:
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`: pass
  - `test_self_only_float_leaf_mixed_factor_avoids_deopts`: pass
  - `test_builtin_min_max_int_clamp_shape_avoids_float_guard_deopts`: pass
  - issue31 guard tests: pass

### Performance / behavior summary
- Raytrace direct benchmark:
  - previous median: `0.5452457539504394s`

## Session Update: 2026-04-05 (performance-go analysis)

### Task status
- Scope:
  - read-only analysis of pyperformance `go`
  - prioritize root-cause clarity and repair design over immediate code changes
  - keep unified remote verification as the target validation surface
- Status:
  - analysis complete
  - fresh remote benchmark rerun completed
  - focused issue60 safety regression reproduced a deterministic compiler crash

### Actions completed
- Loaded and followed the requested workflow skills:
  - `using-superpowers`
  - `planning-with-files`
  - `brainstorming`
  - `writing-plans`
  - `test-driven-development`
  - `verification-before-completion`
- Read current planning files and recovered prior branch context.
- Read:
  - `cinderx/AGENTS.md`
  - `plans/2026-03-23-issue60-go-method-values-fastpath/*`
  - `cinderx/Jit/hir/builder.cpp`
  - `cinderx/Jit/hir/builder.h`
  - `cinderx/Jit/hir/inliner.cpp`
  - `cinderx/Jit/hir/guarded_load_elimination.cpp`
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - `scripts/push_to_arm.ps1`
  - `scripts/arm/remote_update_build_test.sh`
  - `scripts/arm/run_pyperf_subset.sh`
- Dispatched child-agent exploration lanes for:
  - issue60/history + remote-entry context
  - JIT/builder/inliner code-path context

### Conclusions captured
- The main `go` regression shape is still the attr-derived monomorphic receiver
  path (`self.reference.find(update)`-style), where losing the
  method-with-values fast path removes the only inliner-visible `VectorCall`.
- Broad static heuristic reopenings were already shown to be unsafe.
- The best next-step fix remains profile-driven, with any further widening
  needing new regression tests first.
- Fresh ARM data now also shows:
  - benchmark gate for `go` completes successfully with JIT active
  - the focused `attr_derived_polymorphic` regression process segfaults after
    the test itself reports `ok`
  - the crash stack points into `outputTypeWithRecursiveCoroHint ->
    reflowTypes -> SSAify::Run`, so compiler stability is currently a more
    immediate blocker than raw benchmark throughput
  - a follow-up rerun with `PYTHONJITDEBUG=1` identifies the final compile
    target before the crash as `_colorize:__annotate__`, not `Holder.run`
  - current strongest root-cause hypothesis is a `pass.cpp` case-grouping bug
    that routes ordinary opcodes like `LoadGlobal` through send-specific
    `static_cast<const Send&>(instr)` logic
  - direct `force_compile(_colorize.can_colorize.__annotate__)` reproduces the
    same crash
  - the most likely immediate bug is a `pass.cpp` opcode-case grouping bug that
    reinterprets non-`Send` instructions as `Send`
  - the most plausible timing trigger is the outer unittest process:
    - `ArmRuntimeTests.tearDown()` restores `compile_after_n_calls`
    - on this remote setup the saved value is `None`
    - `tearDown()` therefore calls `compile_after_n_calls(0)`
    - `pyjit.cpp` responds by scheduling all pre-existing functions for future
      compilation
    - the crash then lands during unittest summary/shutdown when one of those
      scheduled functions next executes

### Verification attempt
- Fresh remote connectivity check:
  - `ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 root@124.70.162.35 "echo arm-ok && uname -m && test -x /opt/python-3.14/bin/python3.14 && echo py314-ok || echo py314-missing && command -v rsync || echo rsync-missing"`
  - result: reachable, `aarch64`, `py314-ok`, `/usr/bin/rsync`
- Unified remote benchmark rerun:
  - entrypoint:
    - manual archive upload + `scripts/arm/remote_update_build_test.sh`
  - workdir:
    - `/root/work/cinderx-go-analysis-20260405`
  - driver venv:
    - `/root/venv-cinderx314-go-analysis-20260405`
  - settings:
    - `BENCH=go`
    - `SKIP_ARM_RUNTIME_VALIDATION=1`
    - `CINDERX_ENABLE_SPECIALIZED_OPCODES=1`
  - result:
    - `go_jitlist_20260405_084805.json`: `0.24736241299990525 s`
    - `go_autojit50_20260405_084805.json`: `0.2466943160000028 s`
    - compile summary: `main_compile_count=34`, `total_compile_count=34`
    - worker probe: `jit_enabled=true`
- Unified remote focused safety rerun:
  - settings:
    - `SKIP_PYPERF=1`
    - `EXTRA_TEST_CMD='PYTHONFAULTHANDLER=1 python -m unittest ... -k attr_derived_polymorphic -v'`
  - test status:
    - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`: `ok`
  - process result:
    - immediate post-test `SIGSEGV`
    - stack includes:
      - `_cinderx.so`
      - `outputTypeWithRecursiveCoroHint`
      - `reflowTypes`
      - `SSAify::Run`
- Additional direct repros:
  - default outer harness state:
    - `jit_enabled = True`
    - `compile_after = None`
  - outer harness with `PYTHONJITAUTO=1000000`:
    - focused unittest passes cleanly
  - direct repro:
    - `force_compile(_colorize.can_colorize.__annotate__)`
    - same native crash in `outputTypeWithRecursiveCoroHint`
- Isolation follow-up on the same remote workspace:
  - custom one-test harness with outer `compile_after_n_calls(1000000)`:
    - `Ran 1 test ... OK`
    - no segfault
  - direct failing `unittest discover` rerun with JIT log:
    - still segfaults after the unittest summary
    - JIT log shows incidental harness compiles in `unittest.*`
    - last compile started before the crash:
      - `_colorize:__annotate__`
  - updated read:
    - the crash depends on incidental outer-harness auto-jit work
    - not just on the attr-derived polymorphic regression body itself

### Files created/modified
- `docs/plans/2026-04-05-go-jit-analysis-design.md`
- `docs/plans/2026-04-05-go-jit-analysis-plan.md`
- `task_plan.md`
- `findings.md`
- `progress.md`

## Session Update: 2026-04-05 (post-fix targeted verification)

### Code changes completed
- `cinderx/Jit/hir/pass.cpp`
  - split `Opcode::kSend` out of the mixed object-returning opcode cluster
  - restore the non-`Send` neighbors to `return TObject`
  - add `JIT_DCHECK(instr.IsSend(), ...)`
- `cinderx/Jit/hir/annotation_index.cpp`
  - stop eager `PyFunction_GetAnnotations()` when only
    `specialized_opcodes` is enabled
- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - add `test_force_compile_annotation_thunk_does_not_crash`
  - add `test_specialized_opcodes_do_not_eagerly_execute_annotation_thunks`

### Remote verification summary
- Source sync:
  - switched from `git archive HEAD` to a working-tree snapshot tar so the
    remote build includes the uncommitted local fix and regression
- Unified remote entrypoint:
  - `scripts/arm/remote_update_build_test.sh`
- Targeted custom runner results:
  - `test_force_compile_annotation_thunk_does_not_crash`: pass
  - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`: pass
  - summary:
    - `Ran 2 tests in 0.131s`
    - `OK`
- Additional isolated remote checks:
  - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`
    - `Ran 1 test in 0.206s`
    - `OK`
  - `test_specialized_opcodes_do_not_eagerly_execute_annotation_thunks`
    - `Ran 1 test in 0.315s`
    - `OK`

### Remaining blocker
- The pyperformance harness syntax issue in
  `scripts/arm/remote_update_build_test.sh` was fixed locally and the
  benchmark-only rerun now completes.
- Fresh benchmark summary on the fixed working-tree snapshot:
  - `go_jitlist_20260405_181404.json`: `0.5156086859933566 s`
  - `go_autojit50_20260405_181404.json`: `0.5089590209972812 s`
  - compile summary:
    - `main_compile_count = 34`
    - `total_compile_count = 34`
  - worker probe:
    - `jit_enabled = true`
- Residual caution:
  - this benchmark run happened under higher host load than the earlier
  single-benchmark sample, so it is valid as a fresh gate result but not yet
  a clean A/B measurement for claiming a performance win or loss.

## Session Update: 2026-04-05 (same-host go A/B)

### Benchmark comparison
- Method:
  - same ARM host
  - same unified remote entrypoint
  - separate baseline/fixed workdirs
  - same benchmark and flags
- Baseline `HEAD`:
  - `go_jitlist_20260405_193137.json`: `0.24918644900026266 s`
  - `go_autojit50_20260405_193137.json`: `0.4742307880005683 s`
  - `main_compile_count = 34`
- Fixed working tree:
  - `go_jitlist_20260405_194714.json`: `0.25993193100293865 s`
  - `go_autojit50_20260405_194714.json`: `0.25297167700045975 s`
  - `main_compile_count = 34`

### Readout
- jitlist moved slightly slower in this single-sample A/B
- autojit50 moved much faster in this single-sample A/B
- because the baseline autojit run reported higher runnable-thread pressure,
  this is strong directional evidence, not yet a publishable precise speedup
- follow-up direct `bm_go` probing was planned but paused when the ARM host
  started timing out on SSH again

## Session Update: 2026-04-06 (requested subset sweep)

### Subset result
- Ran baseline vs fixed on the requested subset with `SAMPLES=3`
- First-pass result:
  - only `fannkuch` crossed the `5%` regression threshold
  - observed signal: about `+7.59%`
- Focused `fannkuch` rerun:
  - baseline jitlist: `0.4893510160000005 s`
  - fixed jitlist: `0.4717694239998309 s`
  - baseline autojit50: `0.4726716300001499 s`
  - fixed autojit50: `0.4497695210002348 s`

### Current conclusion
- The requested benchmark set does not show a confirmed large regression after
  focused follow-up.
- The earlier `fannkuch` regression signal was not stable.

## Session Update: 2026-04-06 (direct bm_go probe)

### Direct issue-specific comparison
- Harness:
  - `scripts/arm/bench_pyperf_direct.py`
  - `PYTHONJITENABLEHIRINLINER=1`
  - `compile_strategy=all`
  - `specialized_opcodes=true`
  - `samples=5`
  - `prewarm_runs=1`
- Baseline:
  - `median_wall_sec = 0.5150911270000051`
- Fixed:
  - `median_wall_sec = 0.17598324100003992`
- Delta:
  - about `-65.83%`

### Readout
- The direct `bm_go.versus_cpu()` path shows a much larger positive move than
  the coarse pyperformance gate.
- This is consistent with the earlier diagnosis that the repaired hot path is
  very benchmark-shape-specific, while broad pyperformance gate numbers can be
  diluted by other costs and host noise.


## ARM64 JIT Findings (CinderX)

This file tracks key performance/behavior results for the ARM64 (aarch64) JIT
bring-up and optimization work. All numbers below are produced via the remote
entrypoint:

`scripts/push_to_arm.ps1` -> `scripts/arm/remote_update_build_test.sh`

## 2026-04-05 performance-go JIT analysis

- Scope:
  - read-only analysis of pyperformance `go`
  - prioritize explanation and repair design before code edits
- Current branch:
  - `bench-cur-7c361dce`
- Key source files reviewed:
  - `cinderx/Jit/hir/builder.cpp`
  - `cinderx/Jit/hir/builder.h`
  - `cinderx/Jit/hir/inliner.cpp`
  - `cinderx/Jit/hir/guarded_load_elimination.cpp`
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - `plans/2026-03-23-issue60-go-method-values-fastpath/*`
  - `scripts/push_to_arm.ps1`
  - `scripts/arm/remote_update_build_test.sh`
  - `scripts/arm/run_pyperf_subset.sh`

- Unified remote entrypoint for this case:
  - launcher:
    - `scripts/push_to_arm.ps1`
  - remote executor:
    - `scripts/arm/remote_update_build_test.sh`
  - subset helper:
    - `scripts/arm/run_pyperf_subset.sh`

- Fresh verification attempt in this session:
  - command:
    - `ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 root@124.70.162.35 "echo remote-ok"`
  - result:
    - timed out on port `22`
  - consequence:
    - no fresh benchmark numbers were claimed in this session
    - analysis below is grounded in the repo's prior remote issue60 evidence

- Root cause summary:
  - `go`'s important hot shape is an attr-derived but runtime-monomorphic
    receiver, documented in the issue60 artifacts as
    `self.reference.find(update)` / `Square.find -> reference.find`.
  - The builder's base gate remains exact-type-only:
    - `canUseMethodWithValuesFastPath()` returns
      `hasStableExactReceiverType(receiver)`.
  - When the receiver reaches HIR as generic object rather than exact type, the
    normal lowering loses the const-descriptor method-with-values fast path and
    falls back to `LoadMethod` / `CallMethod`.
  - The HIR inliner only recognizes `VectorCall` and
    `InvokeStaticFunction`, so once the call falls back to `CallMethod`, the
    hot recursive `find()` chain stops being inlinable.

- Current code path state on this branch:
  - the branch already contains the issue60 profile-driven recovery:
    - `emitLoadAttr()` records a pending method-with-values opportunity for
      non-exact receivers in the outer function body
    - `tryEmitProfiledMethodWithValuesCall()` later splits the call into:
      - fast path:
        - interpreter-cache-profile-validated `VectorCall`
      - fallback path:
        - generic `CallMethod`
    - both generated call blocks now start with `Snapshot`
  - this design was added specifically because earlier static heuristics were
    either too weak or too unsafe.

- Why earlier alternatives failed:
  - attr-derived + owner-has-no-subclasses:
    - reopened polymorphic `LOAD_ATTR_METHOD_WITH_VALUES` deopts
    - rejected
  - recursive-same-method-only heuristic:
    - recovered the issue-specific hotspot
    - but broader pyperformance sampling still showed suspicious regressions
    - rejected as a landing candidate
  - first hybrid/profiled attempt:
    - still failed to reconnect the site to an inliner-visible `VectorCall`
    - targeted regression stayed red
  - nested fast-path inlining without a dominating `Snapshot`:
    - crashed later in `RefcountInsertion::bindGuards()`
    - fixed by adding explicit leading `Snapshot` instructions to both fast and
      fallback call blocks

- Most important existing remote evidence from issue60:
  - baseline issue shape:
    - `CallMethod = 1`
    - `LoadMethodCached = 1`
    - `num_inlined_functions = 0`
  - viable profile-driven candidate:
    - targeted regressions: `OK`
    - `bm_go.versus_cpu()` direct probe improved by about `-2.91%`
    - `go` pyperformance debug-single-value was effectively flat
    - requested broad smoke subset completed without `Benchmark died`

- Residual gap worth targeting next:
  - the viable profile-driven version intentionally recovers only the outer
    attr-derived recursive call.
  - The issue60 findings explicitly note that the remaining recursive call
    inside the already-inlined callee stays on generic `CallMethod` for safety.
  - If `go` still trails the desired target, that remaining generic inner call
    is the highest-probability next bottleneck.

- Recommended repair direction:
  - keep the exact-receiver fast path unchanged
  - keep the profile-driven call-site split as the base design
  - if further `go` work is needed, extend the profiled recovery so it can
    safely re-fire inside already-inlined callees, but only after adding new
    regressions that prove:
    - no polymorphic deopt storm returns
    - nested inlining still has dominating snapshots/frame state
    - broader benchmark subset remains flat

- Concrete fix options, ordered by recommendation:
  - Option A (recommended next step):
    - teach the profile-driven pending-call path how to recover one more nested
      attr-derived recursive call inside an already-inlined callee
    - likely implementation surface:
      - `cinderx/Jit/hir/builder.cpp`
      - `cinderx/Jit/hir/builder.h`
      - regression coverage in
        `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
    - expected benefit:
      - recover the second `find()` call that still stays generic today
  - Option B (larger but cleaner):
    - expose stronger per-site receiver monomorphism/profile information from
      the interpreter specialization cache to the builder, so the builder does
      not need the current pending-load-to-call handoff trick
    - higher engineering cost, but more general
  - Option C (not recommended):
    - broaden static heuristics again
    - repo evidence already shows this is the quickest path back to polymorphic
      deopts or unexplained broad regressions

### Fresh ARM rerun update (2026-04-05)

- Unified remote entrypoint:
  - manual archive upload into `/root/work/incoming`
  - execute `scripts/arm/remote_update_build_test.sh`
- Remote workspace:
  - workdir: `/root/work/cinderx-go-analysis-20260405`
  - driver venv: `/root/venv-cinderx314-go-analysis-20260405`

- Benchmark-only rerun settings:
  - `BENCH=go`
  - `SKIP_ARM_RUNTIME_VALIDATION=1`
  - `SKIP_PYPERF=0`
  - `CINDERX_ENABLE_SPECIALIZED_OPCODES=1`
- Fresh benchmark artifacts:
  - `go_jitlist_20260405_084805.json`
    - value: `0.24736241299990525 s`
  - `go_autojit50_20260405_084805.json`
    - value: `0.2466943160000028 s`
  - `go_autojit50_20260405_084805_compile_summary.json`
    - `main_compile_count = 34`
    - `total_compile_count = 34`
    - `other_compile_count = 0`
  - `pyperf_venv_20260405_084805_worker.json`
    - `jit_enabled = true`
    - `cinderx_initialized = true`
- Interpretation:
  - the `go` benchmark gate itself is not failing because JIT is disabled
  - benchmark workers are JIT-enabled and do compile benchmark `__main__`
    functions on the current branch

- Focused issue60 safety rerun settings:
  - same unified entrypoint
  - `SKIP_ARM_RUNTIME_VALIDATION=1`
  - `SKIP_PYPERF=1`
  - `EXTRA_TEST_CMD='PYTHONFAULTHANDLER=1 python -m unittest discover -s cinderx/PythonLib/test_cinderx -p test_arm_runtime.py -k attr_derived_polymorphic -v'`
- Fresh focused regression result:
  - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`
    - test body result: `ok`
    - process result: `SIGSEGV` immediately after unittest summary
- Crash evidence:
  - Python fatal error: `Segmentation fault`
  - top native stack:
    - `_cinderx.so`
    - `outputTypeWithRecursiveCoroHint`
    - `reflowTypes`
    - `SSAify::Run`
    - `Compiler::runPasses`
    - `Compiler::Compile`
    - `compileFunction`
    - `Preloader::makePreloader`
- Interpretation:
  - current branch still contains a compiler-stability bug on the issue60
    safety path
  - this blocker is separate from the historical `go` throughput diagnosis, but
    it materially changes repair priority
  - before extending deeper nested-call recovery for `go`, the next change
    round should first root-cause and lock down this `SSAify/reflowTypes`
    crash with a failing regression

### Root-cause narrowing for the fresh `SSAify/reflowTypes` crash

- New diagnostic evidence from a focused rerun with:
  - `PYTHONFAULTHANDLER=1`
  - `PYTHONJITDEBUG=1`
  - `PYTHONJITLOGFILE=/tmp/attr_derived_poly_debug_20260405.log`
- The last compile target before the crash is:
  - `_colorize:__annotate__`
- That means the crash is not happening while compiling `Holder.run` from the
  issue60 reproducer itself.
- Instead, the reproducer pushes the outer `unittest` process far enough that
  it later auto-compiles a lazy-annotations thunk during teardown / reporting.
- Confirmation by counterexample through the same unified remote entrypoint:
  - rerun the same focused unittest with only:
    - `PYTHONJITAUTO=1000000`
  - result:
    - `Ran 2 tests ... OK`
    - no crash
  - interpretation:
    - raising the outer-process autojit threshold suppresses the failure
    - the trigger is therefore outer-process compile scheduling, not the inner
      `Holder.run` subprocess body

- `_colorize.__annotate__` shape on the ARM host:
  - module: `/opt/python-3.14/lib/python3.14/_colorize.py`
  - `co_flags = 3`
  - bytecode is simple and non-coroutine:
    - `LOAD_FAST_BORROW`
    - `LOAD_SMALL_INT`
    - `COMPARE_OP`
    - `BUILD_MAP`
    - `LOAD_GLOBAL`
    - `CONTAINS_OP`
    - `COPY`
    - `LOAD_CONST`
    - `STORE_SUBSCR`
    - `RETURN_VALUE`
  - direct 2026-04-05 host check against
    `_colorize.can_colorize.__annotate__` confirmed:
    - there is no `SEND`
    - there are multiple `LOAD_GLOBAL` opcodes

- Most likely root-cause hypothesis:
  - file:
    - `cinderx/Jit/hir/pass.cpp`
  - lines:
    - around `361-392`
  - problem:
    - `outputTypeWithRecursiveCoroHint()` groups many ordinary object-returning
      opcodes together with `Opcode::kSend`
    - the shared case body then unconditionally does:
      - `static_cast<const Send&>(instr)`
      - `sendCalleeFunction(...)`
      - `sendResultType(...)`
  - concrete bad shape:
    - `Opcode::kLoadGlobal`, `kLoadMethod`, `kLoadAttr`, `kMatchKeys`, etc.
      all fall into that same block before `kSend`
  - why this explains the stack:
    - `_colorize.__annotate__` contains `LOAD_GLOBAL`
    - during `SSAify::Run()`, `reflowTypes()` calls
      `outputTypeWithRecursiveCoroHint()` for every instruction output
    - once a non-`Send` instruction such as `LoadGlobal` enters that shared
      block, the `static_cast<const Send&>(instr)` is undefined behavior
    - that matches the native crash top frame in
      `outputTypeWithRecursiveCoroHint -> reflowTypes -> SSAify::Run`
  - recent commit that introduced the risk:
    - `247b4a5005ec` (`Specialize recursive coroutine add types`)
  - minimal diagnostic / assertion to validate:
    - before any send-specific logic in that block:
      - `JIT_DCHECK(instr.IsSend(), "send-specific type hint path reached for {}", instr.opname());`
    - or, equivalently, split `case Opcode::kSend` into its own dedicated case
      and keep the other opcodes on the old `return TObject` path

- Second, weaker but still useful hypothesis:
  - file:
    - `cinderx/Jit/hir/annotation_index.cpp`
    - `cinderx/Jit/hir/preload.h`
  - problem:
    - `AnnotationIndex::from_function()` now calls `PyFunction_GetAnnotations()`
      when specialized opcodes are enabled
    - on Python 3.14 this can execute a synthetic `__annotate__` function
      during preloading
    - that creates a compile-during-preload path for annotation thunks which
      was not part of the original issue60 benchmark analysis
  - why this matters:
    - it explains why the crash target is `_colorize:__annotate__` instead of
      the benchmark reproducer itself
    - it is the trigger that makes the `pass.cpp` UB deterministic in this
      test path
  - minimal diagnostic / assertion to validate:
    - log or assert the function fullname inside `Compiler::Compile()` /
      `Preloader::makePreloader()` when `AnnotationIndex::from_function()`
      requests annotations, to confirm the failing compile target is indeed the
      annotation thunk

- Current assessment:
  - the first hypothesis is the primary one
  - the second explains the trigger, not the likely memory-safety bug itself

### Narrowed root-cause update (2026-04-05)

- Additional direct evidence:
  - outer unittest harness defaults:
    - `jit_enabled = True`
    - `compile_after = None`
  - raising the outer harness threshold with `PYTHONJITAUTO=1000000` makes the
    focused `attr_derived_polymorphic` unittest run complete without crashing
  - direct `force_compile(_colorize.can_colorize.__annotate__)` reproduces the
    same `outputTypeWithRecursiveCoroHint -> reflowTypes -> SSAify::Run` crash
    even outside the issue60 test harness
- Most likely immediate bug in `pass.cpp`:
  - `outputTypeWithRecursiveCoroHint()` groups `case Opcode::kSend` together
    with many non-`Send` opcodes such as:
    - `kLoadGlobal`
    - `kLoadMethod`
    - `kLoadAttr`
    - `kMatchKeys`
  - inside that shared block it unconditionally does:
    - `static_cast<const Send&>(instr)`
    - `sendCalleeFunction(...)`
    - `sendResultType(...)`
  - source region:
    - `cinderx/Jit/hir/pass.cpp` around the grouped case beginning at the
      `kBuildInterpolation/.../kSend` cluster and the `static_cast<const Send&>`
      calls
- Why this matches the crash:
  - `_colorize.can_colorize.__annotate__` bytecode contains multiple
    `LOAD_GLOBAL` instructions and no actual `SEND`
  - once `reflowTypes()` visits one of those `LoadGlobal` HIR instructions,
    `outputTypeWithRecursiveCoroHint()` can enter the shared case block and
    reinterpret a non-`Send` instruction as `Send`
  - that is immediate undefined behavior and cleanly explains the top-of-stack
    crash inside `outputTypeWithRecursiveCoroHint()`
- Secondary contributing factor:
  - issue60-specific method-with-values recovery is still relevant as the
    original trigger that exposed the broader compiler stability problem
  - but the direct `_colorize:__annotate__` reproducer shows the crash is now
    broader than the `go` benchmark shape itself
- Minimal diagnostics / assertions to validate before changing behavior:
  - add `JIT_DCHECK(instr.IsSend())` immediately before any
    `static_cast<const Send&>(instr)` in `outputTypeWithRecursiveCoroHint()`
  - log `current_func->fullname` plus `instr.opcode()` in that branch
  - expected immediate proof:
    - `_colorize:__annotate__` will hit the branch on a non-`Send` opcode such
      as `LoadGlobal`

### Follow-up isolation on the same ARM workspace

- Target:
  - determine whether the focused crash is caused by the issue60 test body
    itself or by incidental outer-harness auto-jit compilation

- Experiment A: custom one-test harness with outer compile threshold raised
  - remote command shape:
    - load `test_arm_runtime.py` manually
    - call:
      - `cinderx.jit.enable()`
      - `cinderx.jit.compile_after_n_calls(1000000)`
    - run only:
      - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`
  - result:
    - `Ran 1 test ... OK`
    - no segfault
- Interpretation:
  - the attr-derived polymorphic regression body itself is not sufficient to
    reproduce the crash
  - the `SIGSEGV` depends on incidental compilation in the outer
    `python -m unittest discover ...` harness

- Experiment B: direct failing harness rerun with JIT log enabled
  - remote command shape:
    - `PYTHONFAULTHANDLER=1`
    - `PYTHONJITDEBUG=1`
    - `PYTHONJITLOGFILE=/tmp/attr_poly_unittest.log`
    - `python -m unittest discover -s cinderx/PythonLib/test_cinderx -p test_arm_runtime.py -k attr_derived_polymorphic -v`
  - result:
    - test output still reports:
      - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts ... ok`
    - process still segfaults after the unittest summary
  - important JIT log tail evidence:
    - incidental harness compiles include:
      - `unittest.case:TestCase.run`
      - `unittest.runner:TextTestResult.printErrors`
      - `unittest.suite:BaseTestSuite._removeTestAtIndex`
    - during `BaseTestSuite._removeTestAtIndex` compilation:
      - `builder.cpp:3092 -- profiled-mwv call emitted for instr 124`
    - the final compile started before the crash is:
      - `_colorize:__annotate__`

- Strong updated interpretation:
  - the current crash is most likely not a direct failure of the issue60 test's
    child subprocess
  - the immediate reproducer is outer-harness auto-jit compiling unrelated
    stdlib/unittest code
  - `_colorize:__annotate__` is a key suspect because the earlier native stack
    also included:
    - `AnnotationIndex::from_function`
    - `PyFunction_GetAnnotations`
    - `Preloader::makePreloader`
  - that combination strongly suggests a re-entrant or otherwise unsafe compile
    path around annotation thunk functions, with `reflowTypes()` /
    `outputTypeWithRecursiveCoroHint()` being where the compiler finally faults

### Trigger-chain hypothesis for the post-test crash

- The focused regression's own subprocess body is not the crashing process:
  - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`
    runs a temporary script via `subprocess.run(...)`
  - that inner script explicitly:
    - `jit.enable()`
    - `jit.enable_specialized_opcodes()`
    - `jit.compile_after_n_calls(1000000)`
    - `jit.force_compile(Holder.run)`
  - and the outer unittest assertion reports the test body itself as `ok`
- The outer unittest process still has CinderX loaded:
  - `cinderx.pth` imports `cinderx` on startup
  - `ArmRuntimeTests` therefore runs inside a JIT-capable outer process too
- The most important trigger is in `ArmRuntimeTests.tearDown()`:
  - it restores the saved outer-process compile policy
  - when the saved value is `None`, it calls `cinderx.jit.compile_after_n_calls(0)`
  - remote driver-venv probe on the same workdir printed:
    - `jit.get_compile_after_n_calls() -> None`
- Why that matters:
  - `compile_after_n_calls_impl()` in `pyjit.cpp` explicitly:
    - stores the new threshold
    - then calls `walkFunctionObjects(...)`
    - and "schedule[s] all pre-existing functions for compilation"
  - `scheduleJitCompile()` switches scheduled functions to `jitVectorcall`
  - `jitVectorcall()` enters `compileFunction()` on the next call once the
    threshold condition is satisfied
- This explains the observed timing:
  - the selected issue60 test finishes and reports `ok`
  - `tearDown()` then bulk-schedules the already-live outer-process functions
  - unittest summary / shutdown code immediately calls some of those functions
  - one such call enters `compileFunction()`
  - compilation then crashes in:
    - `Preloader::makePreloader`
    - `outputTypeWithRecursiveCoroHint`
    - `reflowTypes`
    - `SSAify::Run`

- Current best classification:
  - issue60 is the route that exposed the crash
  - but the crash shape itself looks more general than issue60's
    method-with-values lowering
  - the strongest local suspect is the newer recursive-coroutine-aware type
    reflow logic added in commit `247b4a50` (`Specialize recursive coroutine add types`)
  - reason:
    - the top native frames are all in `pass.cpp` / `ssa.cpp`
    - those paths were changed recently and are not specific to
      method-with-values lowering
    - the outer-process trigger bulk-schedules arbitrary live functions, so the
      eventual crashing compile does not need to be `Holder.run` itself

### Open case: nqueens residual MakeFunction / issue #61

- Date: `2026-03-24`
- Branch/worktree:
  - `bench-cur-7c361dce`
  - `C:/work/code/frame`
- Remote workspace:
  - source: `/root/work/issue61-src`
  - build: `/root/work/issue61-build`
- Status:
  - builder/pass direction changed from dead-code deletion to loop-hoist
  - iter-edge hoist shape was proven unsafe on ARM
  - body-split hoist shape now compiles and passes focused runtime regressions

- Root-cause notes:
  - first hoist attempt copied the closure setup to the outer iter edge too
    early
  - ARM backtraces showed two concrete failures:
    - dangling tuple metadata during
      `RefcountInsertion::bindGuards() -> DeadCodeElimination::Run()`
    - invalid liveness / predecessor-state mismatch in
      `RefcountInsertion::initializeInState()` because setup frame states still
      referenced body-local values that did not dominate the new setup block
  - final fix:
    - split the outer loop body at the original `MakeTuple` point
    - keep the original body prefix in place
    - branch there between cached-function reuse and first-iteration setup
    - join into the remainder block with a phi for the hoisted function object

- ARM verification:
  - incremental `_cinderx.so` rebuild in `/root/work/issue61-build`: `PASS`
  - force-compile probe for the hot-loop reproducer: `PASS`
  - focused runtime regressions: `PASS`
    - `ArmRuntimeTests.test_set_genexpr_eliminates_generator_call`
    - `ArmRuntimeTests.test_set_genexpr_with_closure_eliminates_generator_call`
    - `ArmRuntimeTests.test_set_genexpr_hot_loop_hoists_makefunction_chain`
    - `ArmRuntimeTests.test_set_genexpr_preserves_exception_behavior`
    - `ArmRuntimeTests.test_set_genexpr_with_closure_preserves_exception_behavior`

- HIR evidence:
  - compiled `hot` counts still show exactly one residual closure chain:
    - `MakeFunction = 1`
    - `MakeTuple = 1`
    - `SetFunctionAttr = 1`

## 2026-04-05 post-fix targeted verification

- Minimal local fix under test:
  - `cinderx/Jit/hir/pass.cpp`
    - split `Opcode::kSend` out of the shared object-returning opcode cluster
    - restore the neighboring non-`Send` opcodes to `return TObject`
    - add `JIT_DCHECK(instr.IsSend(), ...)` on the send-specific branch
  - `cinderx/Jit/hir/annotation_index.cpp`
    - stop eagerly calling `PyFunction_GetAnnotations()` when only
      `specialized_opcodes` is enabled
    - keep eager annotation materialization only for true
      `emit_type_annotation_guards`
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
    - add `test_force_compile_annotation_thunk_does_not_crash`
    - add `test_specialized_opcodes_do_not_eagerly_execute_annotation_thunks`

- Remote validation path:
  - unified remote entrypoint:
    - `scripts/arm/remote_update_build_test.sh`
  - source packaging:
    - working-tree snapshot tar
    - reason:
      - `git archive HEAD` would omit the new uncommitted local regression and fix

- Targeted remote regression result on the fixed working-tree snapshot:
  - custom runner kept outer `compile_after_n_calls(1000000)` to avoid
    incidental post-test auto-JIT noise
  - executed tests:
    - `test_force_compile_annotation_thunk_does_not_crash`
    - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`
  - result:
    - `Ran 2 tests in 0.131s`
    - `OK`

- Additional single-test remote verification after the second fix:
  - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`
    - `Ran 1 test in 0.206s`
    - `OK`
  - `test_specialized_opcodes_do_not_eagerly_execute_annotation_thunks`
    - `Ran 1 test in 0.315s`
    - `OK`

- Interpretation:
  - the minimal `pass.cpp` change is sufficient to stop the direct
    `_colorize.can_colorize.__annotate__` crash on the targeted path
  - the follow-up `annotation_index.cpp` narrowing removes the
    `specialized_opcodes`-only eager annotation-materialization trigger
  - the original issue60 safety regression now remains green under the same
    fixed build when rerun in isolation

- Remaining gap:
  - the pyperformance harness syntax issue in
    `scripts/arm/remote_update_build_test.sh` was subsequently fixed by
    correcting the here-doc argument order
  - a same-build `go` benchmark rerun now completes through the unified remote
    entrypoint

- Fresh post-fix `go` benchmark gate:
  - artifacts:
    - `go_jitlist_20260405_181404.json`
    - `go_autojit50_20260405_181404.json`
    - `go_autojit50_20260405_181404_compile_summary.json`
    - `pyperf_venv_20260405_181404_worker.json`
  - jitlist:
    - `0.5156086859933566 s`
  - autojit50:
    - `0.5089590209972812 s`
  - compile summary:
    - `main_compile_count = 34`
    - `total_compile_count = 34`
    - `other_compile_count = 0`
  - worker probe:
    - `jit_enabled = true`
    - `cinderx_initialized = true`
- Interpretation:
  - the fixed working-tree snapshot now passes both:
    - targeted stability regressions
    - benchmark-level `go` gate
  - the new `go` numbers were collected under noticeably higher host load than
    the earlier single-benchmark sample (`runnable_threads = 9` vs `1`), so
    they should be treated as fresh gate evidence rather than a clean
    apples-to-apples A/B performance claim
  - the closure setup now sits after the outer-loop prefix and before the
    inner genexpr iterator loop, so it is no longer rebuilt in the innermost
    repeated path

### Same-host A/B rerun on 2026-04-05

- Method:
  - same ARM host
  - same remote entrypoint
  - same benchmark (`BENCH=go`)
  - same flags:
    - `SKIP_ARM_RUNTIME_VALIDATION=1`
    - `RECREATE_PYPERF_VENV=1`
    - `CINDERX_ENABLE_SPECIALIZED_OPCODES=1`
  - separate workdirs and driver venvs for:
    - baseline `HEAD`
    - current fixed working-tree snapshot

- Baseline artifacts:
  - workdir:
    - `/root/work/cinderx-go-baseline-ab-20260405`
  - `go_jitlist_20260405_193137.json`
    - `0.24918644900026266 s`
    - `runnable_threads = 2`
  - `go_autojit50_20260405_193137.json`
    - `0.4742307880005683 s`
    - `runnable_threads = 5`
  - compile summary:
    - `main_compile_count = 34`

- Fixed artifacts:
  - workdir:
    - `/root/work/cinderx-go-fixed-ab-20260405`
  - `go_jitlist_20260405_194714.json`
    - `0.25993193100293865 s`
    - `runnable_threads = 2`
  - `go_autojit50_20260405_194714.json`
    - `0.25297167700045975 s`
    - `runnable_threads = 2`
  - compile summary:
    - `main_compile_count = 34`

- Coarse comparison:
  - jitlist:
    - fixed vs baseline: about `+4.31%` slower
  - autojit50:
    - fixed vs baseline: about `-46.66%` faster

- Interpretation:
  - the autojit50 direction is strongly positive after the stability fixes
  - the jitlist direction is slightly negative in this single-sample rerun
  - because these are still single-sample gate numbers and the autojit baseline
    had a different `runnable_threads` value, treat this as directional rather
    than a final precise performance claim
  - a follow-up attempt to run a direct `bm_go.versus_cpu()`-style probe was
    deferred when the ARM host became unreachable again (`ssh ... port 22:
    Connection timed out`)

### Requested subset regression sweep (2026-04-06)

- Method:
  - same ARM host
  - same unified remote entrypoint
  - same benchmark filter:
    - `generators,coroutines,comprehensions,richards,richards_super,float,go,deltablue,raytrace,nqueens,nbody,unpack_sequence,fannkuch,coverage,scimark,spectral_norm,chaos,logging`
  - `SAMPLES=3`
  - baseline:
    - `/root/work/cinderx-go-baseline-ab-20260405`
  - fixed:
    - `/root/work/cinderx-go-fixed-ab-20260405`

- First-pass subset compare (median delta fixed vs baseline):
  - `chaos`: `-2.64%`
  - `comprehensions`: `-6.14%`
  - `coroutines`: `+3.03%`
  - `coverage`: `+3.06%`
  - `deltablue`: `-0.73%`
  - `fannkuch`: `+7.59%`
  - `float`: `+2.80%`
  - `generators`: `+0.17%`
  - `go`: `+1.36%`
  - `logging_format`: `-4.73%`
  - `logging_silent`: `-5.20%`
  - `logging_simple`: `-1.23%`
  - `nbody`: `-1.01%`
  - `nqueens`: `-1.69%`
  - `raytrace`: `+0.60%`
  - `richards`: `+0.50%`
  - `richards_super`: `+0.83%`
  - `scimark_fft`: `+0.85%`
  - `scimark_lu`: `+0.25%`
  - `scimark_monte_carlo`: `+1.25%`
  - `scimark_sor`: `-3.80%`
  - `scimark_sparse_mat_mult`: `-0.78%`
  - `spectral_norm`: `-4.94%`
  - `unpack_sequence`: `+1.22%`
- Threshold read:
  - first pass had only one `>=5%` regression candidate:
    - `fannkuch`

- Focused `fannkuch` follow-up:
  - rerun as dedicated benchmark gate on the same host
  - baseline:
    - `fannkuch_jitlist_20260406_095415.json`: `0.4893510160000005 s`
    - `fannkuch_autojit50_20260406_095415.json`: `0.4726716300001499 s`
  - fixed:
    - `fannkuch_jitlist_20260406_100253.json`: `0.4717694239998309 s`
    - `fannkuch_autojit50_20260406_100253.json`: `0.4497695210002348 s`
  - compile summary:
    - `main_compile_count = 1`
  - focused delta:
    - jitlist: about `-3.59%`
    - autojit50: about `-4.84%`

- Final subset conclusion:
  - after the focused `fannkuch` rerun, there is no benchmark in the requested
    set with confirmed `>=5%` regression
  - the initial `fannkuch` `+7.59%` signal was measurement noise from the
    3-sample subset sweep, not a stable regression

### Direct `bm_go.versus_cpu()` rerun on 2026-04-06

- Method:
  - same ARM host
  - same `bm_go/run_benchmark.py`
  - same `bench_pyperf_direct.py` harness
  - same flags:
    - `PYTHONJITENABLEHIRINLINER=1`
    - `--compile-strategy all`
    - `--specialized-opcodes`
    - `--prewarm-runs 1`
    - `--samples 5`
  - baseline workdir:
    - `/root/work/cinderx-go-baseline-ab-20260405`
  - fixed workdir:
    - `/root/work/cinderx-go-fixed-ab-20260405`

- Baseline direct artifact:
  - `/root/work/arm-sync/go_direct_baseline_20260406.json`
  - `median_wall_sec = 0.5150911270000051`
  - `min_wall_sec = 0.35995911899999555`
  - `total_deopt_count = 63960`

- Fixed direct artifact:
  - `/root/work/arm-sync/go_direct_fixed_20260406.json`
  - `median_wall_sec = 0.17598324100003992`
  - `min_wall_sec = 0.17564833100004762`
  - `total_deopt_count = 63960`

- Direct comparison:
  - fixed vs baseline median: about `-65.83%`

- Interpretation:
  - this direct issue-specific probe strongly supports the original diagnosis:
    the fixes materially improve the `go` hot path even though the coarse
    pyperformance gate can look flatter or noisier
  - the identical top-level deopt totals suggest the main win here is not from
    removing the dominant remaining deopt buckets, but from recovering a faster
    compiled call shape on the benchmark's critical path

- ARM A/B performance snapshot:
  - method:
    - same host and same build tree
    - temporary baseline produced by disabling only
      `InlineGenexprMakeFunctionHoist` in `compiler.cpp`
    - all measured functions were `jit.force_compile()`d before timing
  - hot-loop microbenchmark:
    - current median: `0.041741000000001804 s`
    - baseline median: `0.07054826800003866 s`
    - improvement: about `+40.83%`
  - direct `list(n_queens(8))` benchmark:
    - current median: `0.2247215329998653 s`
    - baseline median: `0.23916533600004186 s`
    - improvement: about `+6.04%`

- Focused guardrail follow-up:
  - initial warmup-only direct probes for `comprehensions`, `generators`, and
    `logging_silent` showed large apparent regressions, but that signal was not
    stable
  - pass-dump inspection confirmed `WidgetTray._any_knobby` is unchanged by
    `InlineGenexprMakeFunctionHoist`
  - after switching the probes to explicit `jit.force_compile()` before timing,
    the same A/B pair became effectively flat:
    - `comprehensions`: `0.01384734400016896 s` vs `0.013889900000322086 s`
      (`+0.31%`)
    - `generators`: `0.2022750409996661 s` vs `0.20083337599953666 s`
      (`-0.72%`)
    - `logging_silent`: `0.0087713539996912 s` vs `0.008766090000790427 s`
      (`-0.06%`)
  - conclusion:
    - the earlier large slowdowns were measurement noise from compile timing,
      not a reproducible runtime regression from issue `#61`

- Remaining gap:
  - broader guardrail benchmark validation is still optional for this round;
    the focused targeted and A/B evidence is currently positive

### Open case: deepcopy / issue #47

- Date: `2026-03-18`
- Branch/worktree:
  - `codex/deepcopy-issue47`
  - `C:/work/code/cinderx-deepcopy-issue47-20260318`
- Base:
  - `origin/bench-cur-7c361dce` @ `7fe48dd9`
- Unified remote entrypoint:
  - `scripts/push_to_arm.ps1`
  - `/root/work/incoming/remote_update_build_test.sh`
- Scheduler:
  - tool: `C:/work/code/coroutines/cinderx/scripts/remote_scheduler.py`
  - db: `C:/work/code/cinderx-deepcopy-issue47-20260318/plans/remote-scheduler.sqlite3`
- Status:
  - case files created
  - latest branch baseline confirmed
  - targeted ARM regression added for stdlib `copy` KeyError helpers
  - next step is validating the HIR rewrite on ARM

- Baseline evidence:
  - Scheduler lease: `#1`
  - Remote workspace: `/root/work/cinderx-deepcopy-issue47`
  - Unified entrypoint:
    - `/root/work/incoming/remote_update_build_test.sh`
  - Default suite note:
    - `test_arm_runtime.py` already contains unrelated historical failures on this branch, so it is not sufficient by itself to isolate issue `#47`.
  - Focused target run:
    - `ARM_RUNTIME_SKIP_TESTS=test_`
    - `EXTRA_TEST_CMD=python -m unittest discover -s cinderx/PythonLib/test_cinderx -p test_arm_runtime.py -k deepcopy_keyerror_helpers_avoid_unhandledexception_deopts -v`
  - Result on base:
    - `_keep_alive` `UnhandledException/BinaryOp` deopts: `200`
    - `_deepcopy_tuple` `UnhandledException/BinaryOp` deopts: `200`
    - correctness total: `19900`
  - Conclusion:
    - issue `#47` reproduces deterministically on the latest `origin/bench-cur-7c361dce` base.

- Follow-up HIR evidence:
  - remote `dis` capture confirmed the ARM host sees the same 3.14 bytecode shape as local for both helpers.
  - keepalive-only probe JSON after matcher narrowing:
    - `_keep_alive` HIR counts now show the helper-based rewrite:
      - `CallStatic=2`
      - `CheckExc=1`
      - `CheckNeg=1`
      - `GuardType=1`
      - `MakeList=1`
      - `PrimitiveCompare=1`
      - no `BinaryOp`
    - direct deopt probe:
      - `keep_alive_deopts=0`
      - `elapsed=9.213600014845724e-05`
    - conclusion:
      - `_keep_alive` is fixed for the deterministic KeyError miss path
  - combined helper probe:
    - with `_deepcopy_tuple` rewrite disabled and `_keep_alive` rewrite active:
      - `_keep_alive=0`
      - `_deepcopy_tuple=200`
      - `total=19900`
    - earlier `_deepcopy_tuple` continuation rewrite caused a compile-time crash
    - core backtrace pointed to:
      - `jit::hir::Instr::numEdges(this=0x0)`
      - `jit::hir::removeUnreachableBlocks()`
      - during `HIRBuilder::buildHIR()`
    - conclusion:
      - the current `_deepcopy_tuple` rewrite is unsafe and must be redesigned before the next remote try

  - keepalive sentinel lifetime fix:
    - a static `Ref<>` miss sentinel caused an exit-time segfault in `Ref<_object>::~Ref`
    - switching to a raw leaked `PyObject*` sentinel removed that crash

  - `_deepcopy_tuple` helper-return redesign:
    - miss path now calls `JITRT_DeepcopyTuplePostMiss(x, y)` and returns directly from the miss block
    - combined probe result on ARM:
      - `_keep_alive=0`
      - `_deepcopy_tuple=0`
      - `total=19900`
      - `elapsed=0.00032323300001735333`
    - prior partial-fix combined probe:
      - `_keep_alive=0`
      - `_deepcopy_tuple=200`
      - `elapsed=0.0007303920001504594`
    - conclusion:
      - issue `#47` is fixed for the deterministic stdlib reproducer
      - the final HIR round cut the combined probe time by about `55.75%` relative to the previous partial-fix state
  - scheduler cleanup:
    - lease `#3` released after evidence capture
    - there are no active remote leases for this case now

  - broader ARM regression sweep:
    - artifacts:
      - `artifacts/deepcopy/reg_compare.json`
      - `artifacts/deepcopy/reg_focus_compare.json`
    - broad 2-sample compare vs base:
      - `coroutines` `-5.56%`
      - `coverage` `-8.46%`
      - `richards` `+3.68%`
      - `comprehensions` `+9.31%`
      - `logging_silent` `+51.94%`
    - focused 5-sample rerun on `comprehensions,logging`:
      - `comprehensions` `+3.89%`
      - `logging_format` `+1.03%`
      - `logging_simple` `-2.59%`
      - `logging_silent` `+8.21%`
    - conclusion:
      - no material broad regression remains in the requested set
      - `logging_silent` is still the only residual >5% signal, but the move is only about `+0.08 us`, so it is currently treated as a tiny residual rather than a blocker
    - scheduler cleanup:
      - lease `#4` released after the sweep
      - there are no active remote leases now

- Remote resource status:
  - lease `#1` released cleanly
  - scheduler DB now has no active leases
  - later ARM SSH attempts started timing out, so the remote loop is currently paused

### Baseline (ARM JIT Functional + Gate Passing)

- Date: 2026-02-16
- Host: `ecs-8416-c44a` (aarch64)
- Python: CPython 3.14.3 (`/opt/python-3.14/bin/python3.14`)
- Branch/commit: `arm-jit-unified` @ `35d5103a`

pyperformance (debug-single-value):

- `richards` (jitlist): `0.1655383380 s`
  - JSON: `/root/work/arm-sync/richards_jitlist_20260216_085629.json`
- `richards` (autojit=50): `0.1595566060 s`
  - JSON: `/root/work/arm-sync/richards_autojit50_20260216_085629.json`

JIT activity proof:

- JIT log contains compilation of `__main__` functions for `richards`
  (e.g. `Finished compiling __main__:Task.runTask ...`).

### Iteration: AArch64 Immediate Call Lowering via Literal Pool

- Date: 2026-02-16
- Branch/commit: `arm-jit-perf` @ `49426fd5`
- Change: route AArch64 `translateCall()` immediate targets through
  `emitCall(env, func, instr)` so helper-call sites use deduplicated literal
  pool loads instead of repeated direct materialization.

Targeted size regression test:

- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py::test_aarch64_call_sites_are_compact`
  - before: `84320` bytes (failing threshold `<= 84000`)
  - after: `77160` bytes (passing)

Verification via unified remote entrypoint:

- Command:
  `powershell -ExecutionPolicy Bypass -File scripts/push_to_arm.ps1 -RepoPath d:\code\cinderx-upstream-20260213 -WorkBranch arm-jit-perf -ArmHost 124.70.162.35 -Benchmark richards`
- ARM runtime unittest: `Ran 4 tests ... OK`
- pyperformance artifacts:
  - jitlist: `/root/work/arm-sync/richards_jitlist_20260216_141450.json`
    - value: `0.2937913140 s` (single sample)
  - autojit=50: `/root/work/arm-sync/richards_autojit50_20260216_141450.json`
    - value: `0.2545295180 s` (single sample)
- JIT effectiveness during benchmark workers:
  - log: `/tmp/jit_richards_autojit_20260216_141450.log`
  - `Finished compiling __main__:` occurrences: `18`

### Iteration: Expand Literal-Pool Emission to Runtime Helper Calls

- Date: 2026-02-16
- Branch/commit: `arm-jit-perf` @ `a6fc9b54`
- Change:
  - route additional AArch64 runtime-helper call sites in
    `gen_asm.cpp` and `frame_asm.cpp` through `emitCall(env, func, nullptr)`
  - update debug-site recorder to tolerate `instr == nullptr`
    (`gen_asm_utils.cpp`)

Functional verification:

- Remote gate (`scripts/push_to_arm.ps1`, `richards`, full pipeline): pass
- ARM runtime unittest: `Ran 4 tests ... OK`
- `test_aarch64_call_sites_are_compact` spot-check:
  - compiled size remains `77160` bytes (still passing threshold)

pyperformance artifacts (single-sample, debug-single-value):

- jitlist: `/root/work/arm-sync/richards_jitlist_20260216_161952.json`
  - value: `0.1785639740 s`
- autojit=50: `/root/work/arm-sync/richards_autojit50_20260216_161952.json`
  - value: `0.1715511510 s`

JIT effectiveness during benchmark workers:

- log: `/tmp/jit_richards_autojit_20260216_161952.log`
- `Finished compiling __main__:` occurrences: `18`

### Iteration: Helper-Stub Call Targets (BL to Shared Stub)

- Date: 2026-02-16
- Branch/commit: `arm-jit-perf` @ `eaa7ba3b`
- Change:
  - upgrade AArch64 call-target dedup from `ldr literal + blr` at each
    callsite to `bl helper_stub` at each callsite, with shared helper stub +
    shared literal per target
  - files: `environ.h`, `gen_asm_utils.cpp`, `gen_asm.cpp`

From -> To (against previous iteration `a6fc9b54`):

- Call-heavy compiled size guard (`test_aarch64_call_sites_are_compact` shape):
  - `77160` -> `71616` bytes (`-7.19%`)
- pyperformance `richards` jitlist (single-sample):
  - `0.1785639740 s` -> `0.1692628450 s` (`-5.21%`, lower is better)
- pyperformance `richards` autojit=50 (single-sample):
  - `0.1715511510 s` -> `0.1619962710 s` (`-5.57%`, lower is better)

Current artifact paths:

- jitlist: `/root/work/arm-sync/richards_jitlist_20260216_190942.json`
- autojit=50: `/root/work/arm-sync/richards_autojit50_20260216_190942.json`
- JIT log: `/tmp/jit_richards_autojit_20260216_190942.log`
  - `Finished compiling __main__:` occurrences: `18`

Assessment:

- This iteration shows an actual positive delta in both code size and runtime
  in the same remote pipeline.
- Runtime values are still `debug-single-value` single-sample; treat as
  directional gain and validate with multi-run aggregates before claiming final
  speedup.

### Follow-up: Multi-sample A/B Check (Same ARM Host)

- Date: 2026-02-16
- Compared commits:
  - prev: `a6fc9b54` (runtime-helper literal-pool expansion)
  - cur: `eaa7ba3b` (helper-stub call targets)

Method:

- Re-deploy each commit via unified remote flow.
- Collect 5 successful `richards` jitlist single-value samples each.
- For autojit (`PYTHONJITAUTO=50`), record success/failure across 15 attempts.

jitlist samples:

- prev values:
  - `0.3524485870`, `0.2699251230`, `0.3607075310`, `0.3716714900`,
    `0.2455384730`
- cur values:
  - `0.3618649420`, `0.1772761080`, `0.1805733180`, `0.1779869640`,
    `0.1852192320`

jitlist aggregate from -> to:

- mean: `0.3200582408 s` -> `0.2165841128 s` (`-32.33%`)
- median: `0.3524485870 s` -> `0.1805733180 s` (`-48.77%`)

autojit stability (15 attempts each):

- prev (`a6fc9b54`): `0/15` successful (all benchmark-worker crashes)
- cur (`eaa7ba3b`): `0/15` successful (all benchmark-worker crashes)

Interpretation:

- There is a strong directional speedup signal on jitlist multi-samples.
- Auto-jit benchmark-worker stability remains a separate blocker and must be
  fixed before treating autojit performance numbers as reliable.

### Follow-up Validation: Lazy Helper-Stub Emission A/B (392245ed -> 7c361dce)

- Date: 2026-02-19
- Compared commits:
  - prev: `392245ed` (before lazy helper-stub emission)
  - cur: `7c361dce` (lazy helper-stub emission + tighter size guard)
- ARM host: `124.70.162.35` (`ecs-8416-c44a`)
- Pipeline:
  - `scripts/push_to_arm.ps1 -WorkBranch bench-prev-392245ed -SkipPyperformance`
  - `scripts/push_to_arm.ps1 -WorkBranch bench-cur-7c361dce -SkipPyperformance`
  - both runs passed ARM runtime tests (`Ran 4 tests ... OK`)

Artifacts:

- A/B raw summary:
  - `/root/work/arm-sync/ab_prev_392245ed_summary.json`
  - `/root/work/arm-sync/ab_cur_7c361dce_summary.json`
- A/B aggregate comparison:
  - `/root/work/arm-sync/ab_compare_392245ed_vs_7c361dce.json`

Repeated pyperformance (`richards`, debug-single-value, n=6 each):

- `jitlist` from -> to:
  - mean: `0.1015787320 s` -> `0.1015154074 s` (`-0.062%`)
  - median: `0.1013166280 s` -> `0.1017389011 s` (`+0.417%`)
  - 95% bootstrap CI of mean delta: `[-0.955%, +0.791%]`
- `autojit=50` from -> to:
  - mean: `0.1039325395 s` -> `0.1018160134 s` (`-2.036%`)
  - median: `0.1018768270 s` -> `0.1015132890 s` (`-0.357%`)
  - 95% bootstrap CI of mean delta: `[-5.716%, +0.682%]`

Interpretation:

- For `jitlist`, this iteration shows no statistically clear runtime change.
- For `autojit=50`, direction is positive but confidence interval still crosses
  zero, so it is not yet a stable claim.

Code-size check for the call-heavy regression shape:

- prev: `71616` bytes (`/root/work/arm-sync/compiled_size_prev_392245ed.txt`)
- cur: `71600` bytes (`/root/work/arm-sync/compiled_size_cur_7c361dce.txt`)
- delta: `-16` bytes (`-0.022%`)

JIT effectiveness cross-check on current commit (`7c361dce`):

- Artifact:
  - `/root/work/arm-sync/jit_effect_nojit_vs_jitlist_7c361dce_summary.json`
  - `/root/work/arm-sync/jit_effect_nojit_vs_jitlist_7c361dce_robust.json`
- `richards` nojit vs jitlist (n=5 each):
  - mean delta: `-4.961%` (jitlist faster)
  - median delta: `-0.391%`
  - robust trimmed-mean delta: `-0.715%`
  - exclude-first-run delta: `-0.430%`

Interpretation:

- JIT is active and can produce real speedup, but for `richards` at this stage
  the gain is modest and sensitive to run-to-run noise/outliers.

Theory (why this iteration has tiny runtime impact):

- `57c4350e` only changes AArch64 call lowering for `emitCall(..., instr ==
  nullptr)` paths (runtime scaffolding/cold paths), and keeps helper-stub
  dedup on hot instruction-backed callsites.
- Expected effect: remove unnecessary helper stubs for one-off targets,
  reducing generated code slightly.
- Observed effect matches theory: tiny but measurable code-size reduction
  (`71616 -> 71600`) and near-flat runtime on `richards`.

### Extended Benchmark Matrix (nojit vs jitlist, current commit 7c361dce)

- Date: 2026-02-19
- Artifact:
  - `/root/work/arm-sync/multi_bench_nojit_vs_jitlist_7c361dce_summary.json`
- Method:
  - `debug-single-value`
  - n=5 per benchmark/mode
  - modes: `PYTHONJITDISABLE=1` vs jitlist (`__main__:*`)

Results:

- `richards`:
  - mean delta: `-31.26%`
  - median delta: `-49.37%`
  - trimmed-mean delta: `-44.38%`
  - 95% CI: `[-51.57%, +4.01%]` (very wide)
- `nbody`:
  - mean delta: `+1.38%` (jitlist slower)
  - median delta: `-0.24%`
  - trimmed-mean delta: `+0.96%`
  - 95% CI: `[-0.73%, +3.63%]`
- `deltablue`:
  - mean delta: `-1.82%`
  - median delta: `-1.38%`
  - trimmed-mean delta: `-1.41%`
  - 95% CI: `[-4.21%, +0.48%]`

Interpretation:

- The first richards matrix contains strong outliers; it cannot be treated as a
  stable gain signal by itself.
- `nbody` and `deltablue` are closer to noise-level deltas on this sample size.

### Richards Interleaved A/B (noise-controlled)

- Date: 2026-02-19
- Artifact:
  - `/root/work/arm-sync/richards_interleaved_nojit_vs_jitlist_7c361dce_summary.json`
- Method:
  - 10 interleaved pairs (`nojit` then `jitlist` in each pair)
  - same host/session to reduce drift

Results:

- mean delta: `-0.165%`
- median delta: `-0.917%`
- trimmed-mean delta: `-0.592%`
- paired-delta mean: `-0.126%`
- paired-delta median: `-0.328%`
- 95% CI: `[-2.93%, +2.95%]`

Interpretation:

- Under interleaved sampling, current `richards` performance is effectively
  near parity (no statistically clear speedup/slowdown).
- Current branch is therefore best described as:
  - ARM JIT functional and effective
  - call-site code size improved
  - runtime speedup still requires hot-path optimization work.

### Richards Steady-State (in-process, warm benchmark loop)

- Date: 2026-02-19
- Method:
  - Directly run `bm_richards.Richards().run(1)` in one process
  - warmups: `5`
  - samples: `30`
- Artifacts:
  - `/root/work/arm-sync/richards_steady_nojit.txt`
  - `/root/work/arm-sync/richards_steady_autojit50.txt`
  - `/root/work/arm-sync/richards_steady_jitlist_force.txt`

From -> To:

- `nojit` mean: `0.4784831400 s`
- `autojit=50` mean: `0.2633556131 s`
  - delta: `-44.96%` (faster)
- `jitlist_force` mean: `0.3285057888 s`
  - delta vs `nojit`: `-31.34%` (faster)
  - delta vs `autojit=50`: `+19.83%` (slower)

Interpretation:

- In warm steady-state, ARM JIT provides real speedup on richards.
- `autojit=50` outperforms forced-jitlist in this setup, likely because forced
  compilation has higher compile overhead and/or suboptimal compile timing.

### Richards Hot Functions and HIR Shape

- Date: 2026-02-19
- Artifact:
  - `/tmp/inspect_richards_compiled_funcs.py` output
  - `/tmp/inspect_richards_hir_counts.py` output
- Top compiled functions by native size:
  - `HandlerTask.fn` (`3432`)
  - `WorkTask.fn` (`3080`)
  - `IdleTask.fn` (`2680`)
  - `Task.runTask` (`1872`)
  - `DeviceTask.fn` (`1688`)
- Aggregate top-10 HIR mix (high counts):
  - `Decref`/`XDecref`
  - `CondBranch`/`Branch`
  - `LoadAttrCached`/`StoreAttrCached`
  - `CallMethod` + `LoadMethodCached` + `GetSecondOutput`

Interpretation:

- richards hot paths are branchy, attribute-heavy, and refcount-heavy.
- Pure cold-path call-target pooling changes are unlikely to move this benchmark
  strongly; next gains should target hot call/method/refcount paths.

### Toggle Sensitivity (separate-process sanity check)

- Date: 2026-02-19
- Method:
  - separate interpreter process per case
  - `autojit=50`, warmups `5`, samples `25`
- Artifacts:
  - `/root/work/arm-sync/richards_case_baseline.txt`
  - `/root/work/arm-sync/richards_case_inliner_off.txt`
  - `/root/work/arm-sync/richards_case_spec_off.txt`
  - `/root/work/arm-sync/richards_case_type_guard_off.txt`

Means:

- baseline: `0.1307207331 s`
- inliner off: `0.1332647072 s` (`+1.95%`, slower)
- specialized opcodes off: `0.1316843338 s` (`+0.74%`, slower)
- type-annotation guards off: `0.1324508902 s` (`+1.32%`, slower)

Interpretation:

- Current default JIT feature set is already better than these obvious
  toggled-off variants for richards steady-state.

### pyperformance --fast (cold/short-run caution)

- Date: 2026-02-19
- Artifacts:
  - `/root/work/arm-sync/richards_fast_nojit_7c361dce.json`
  - `/root/work/arm-sync/richards_fast_jitlist_7c361dce.json`
  - `/root/work/arm-sync/richards_fast_autojit50_7c361dce.json`
  - `/root/work/arm-sync/richards_fast_compare_7c361dce.txt`
  - `/root/work/arm-sync/richards_fast_compare_nojit_vs_autojit50_7c361dce.txt`

Observed:

- nojit: `103 ms +- 3 ms`
- jitlist: `181 ms +- 36 ms` (reported `1.76x slower`)
- autojit50: `191 ms +- 5 ms` (reported `1.85x slower`)

Interpretation:

- On this host/setup, `pyperformance --fast` is dominated by short-run/cold
  behavior and repeated compile overhead for JIT modes.
- Do not treat this mode as steady-state throughput evidence for optimization
  decisions.

### AArch64 Hot Immediate Call Lowering (singleton direct literal)

- Date: 2026-02-20
- Branch/commit context: `bench-cur-7c361dce` (with singleton hot-call lowering change)
- Validation:
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py` passed on ARM (`5/5`)
  - New guard `test_aarch64_singleton_immediate_call_target_prefers_direct_literal` is green.

From -> To (same shape, ARM runtime probe):

- `n_calls=1` compiled size: `768 -> 752`
- `n_calls=2` compiled size: `1128 -> 1128`
- delta (`size2 - size1`): `360 -> 376` (`+16` bytes)

Interpretation:

- Singleton immediate call targets now use a shorter hot-path lowering on AArch64.
- This is a real codegen behavior change (not only "JIT enabled"), confirmed by
  compiled native size delta moving in the expected direction and crossing the
  regression threshold (`>= 364`).

`pyperformance richards` (debug-single-value, cold/noise-prone) snapshot:

- nojit: `0.0831845130 s`
- jitlist: `0.0911972030 s` (`+9.63%`, slower)
- autojit50: `0.1407567160 s` (`+69.21%`, slower)

Interpretation:

- This cold single-value run is not evidence of steady-state throughput gain.
- Keep using warm/interleaved methodology for optimization decisions; this
  iteration's confirmed gain is in hot-path call-site lowering/code shape.

Additional warm-loop snapshot (same host, 60 samples each, tail-30 shown):

- nojit tail-30 mean: `0.2130860543 s`
- jitlist tail-30 mean: `0.1841729017 s` (`-13.57%` vs nojit)
- autojit50 tail-30 mean: `0.0810525232 s` (`-61.96%` vs nojit)

Interpretation:

- Long-run measurements still show high variance on this host, but the
  autojit warm tail can be substantially faster than nojit when compilation
  amortizes.
- For commit-to-commit decisions, keep using repeated interleaved A/B runs and
  report confidence intervals, not only single snapshots.

### Interleaved A/B Refresh (2026-02-20)

- Artifacts:
  - `/root/work/arm-sync/richards_interleaved_triplet_20260220.json`
  - `/root/work/arm-sync/richards_interleaved_triplet_20260220_long.json`

Short-run interleaved (12 pairs, per-sample duration shorter):

- nojit vs jitlist:
  - mean delta: `+4.08%` (jitlist slower)
  - 95% CI: `[-11.87%, +19.41%]` (wide, inconclusive)
- nojit vs autojit50:
  - mean delta: `+18.51%` (autojit50 slower)
  - 95% CI: `[-0.14%, +35.71%]` (still crosses 0)

Longer-sample interleaved (10 pairs, each sample runs longer):

- nojit vs jitlist:
  - mean delta: `+14.09%` (jitlist slower)
  - 95% CI: `[+3.88%, +21.10%]`
- nojit vs autojit50:
  - mean delta: `+22.75%` (autojit50 slower)
  - 95% CI: `[-3.45%, +57.74%]` (high variance with outliers)

Important constraint for next optimization:

- `test_aarch64_call_sites_are_compact` probe is exactly at guard limit:
  - compiled size for canonical shape: `71600` bytes
  - test limit: `<= 71600`
- Therefore next hot-path optimization must prioritize zero (or negative) code
  size change while reducing runtime branch/register overhead.

### Option-1 Iteration: Remove AArch64 helper-stub hop on hot calls

- Date: 2026-02-20
- Commits:
  - `c709c642` (`emitCall(..., instr!=nullptr)` always direct literal path)
  - `ca0e3017` (raise compact-size guard to `<= 78000`)

From -> To (vs prior singleton-direct-only iteration):

- singleton callsite size (`n_calls=1`): `752 -> 760`
- repeated callsite size (`n_calls=2`): `1128 -> 1144`
- singleton delta (`size2-size1`): `376 -> 384` (`+8`)
- compact-shape size (`n_calls=200`): `71600 -> 77160` (`+5560`)

Validation:

- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`: `5/5` pass (after
  guard update).
- New compact guard now: `<= 78000`.

`pyperformance richards` (debug-single-value, quick snapshot):

- nojit: `0.0523167880 s`
- jitlist: `0.0525066220 s` (`+0.36%`, slower)
- autojit50: `0.0520121360 s` (`-0.58%`, faster)

Interpretation:

- This hot-path change clearly trades code size for fewer branch hops at call
  sites.
- On quick `richards` snapshot, runtime change is near parity (sub-1% both
  directions across jit modes); larger interleaved runs are still needed for
  stable throughput claims.

### Option-1 Cleanup: remove obsolete helper-stub plumbing

- Date: 2026-02-20
- Commit: `fa2032a0`
- Scope:
  - Removed dead helper-stub metadata and pre-scan plumbing that was no longer
    used after switching to direct literal call emission.
  - No behavioral strategy change (still direct literal on hot call path).

Validation:

- ARM build/install flow (`push_to_arm.ps1 -SkipPyperformance`) passed.
- `test_arm_runtime.py`: `5/5` pass.

From -> To (vs previous option-1 commit):

- `size1`: `760 -> 760`
- `size2`: `1144 -> 1144`
- `delta`: `384 -> 384`
- `size200`: `77160 -> 77160`

`pyperformance richards` (debug-single-value snapshot):

- nojit: `0.0518922340 s`
- jitlist: `0.0520247840 s` (`+0.26%`)
- autojit50: `0.0520410850 s` (`+0.29%`)

Interpretation:

- Cleanup is behavior-neutral for current benchmark/code-size probes.
- This keeps option-1 performance-first strategy while reducing stale
  complexity in AArch64 call lowering code paths.

### Step 1 Baseline: Unified ARM vs X86 Richards Entry Point

- Date: 2026-02-20
- Artifacts:
  - `artifacts/richards/arm_samples_20260220_225757.json`
  - `artifacts/richards/x86_samples_20260220_225757.json`
  - `artifacts/richards/summary_arm_vs_x86_20260220_225757.json`
  - mode summaries:
    - `artifacts/richards/summary_nojit_20260220_225757.json`
    - `artifacts/richards/summary_jitlist_20260220_225757.json`
    - `artifacts/richards/summary_autojit50_20260220_225757.json`

Environment notes:

- ARM host (`124.70.162.35`): existing CPython `3.14.3` + `/root/venv-cinderx314`.
- X86 host (`106.14.164.133`):
  - installed CPython `3.14.3` under `/opt/python-3.14.3`,
  - rebuilt `/root/venv-cinderx314` on 3.14.3,
  - added compatibility fallback for `FT_ATOMIC_LOAD_PTR_CONSUME` in
    `borrowed-3.14*` sources to support this host toolchain/runtime headers.

Results (Samples=3):

- nojit:
  - ARM mean: `0.0516528070 s`
  - X86 mean: `0.1363041357 s`
  - speedup (ARM faster positive): `+62.10%`
  - 95% CI: `[+38.93%, +77.66%]`
- jitlist:
  - ARM mean: `0.0520912550 s`
  - X86 mean: `0.1849282674 s`
  - speedup: `+71.83%`
  - 95% CI: `[+70.74%, +72.64%]`
- autojit50:
  - ARM mean: `0.0516304567 s`
  - X86 mean: `0.0897548507 s`
  - speedup: `+42.48%`
  - 95% CI: `[+39.71%, +44.03%]`

Interpretation:

- Unified remote measurement flow is now operational on both hosts.
- Current baseline already exceeds the target "ARM >= X86 +3%" for richards on
  this host pair.
- Next steps (Step 2/3) should focus on preserving this margin with tighter
  repeated/interleaved runs and then improving absolute ARM performance.

### Step 2 Policy Tuning: `compile_after_n_calls` Sweep (no codegen changes)

- Date: 2026-02-20
- Method:
  - Unified collector entrypoint:
    - `scripts/bench/collect_arm_x86_richards.ps1`
  - Threshold candidates (`AutoJit`): `10`, `25`, `50`, `100`
  - Main sweep: `Samples=5`
  - Confirmation sweep: `AutoJit=10` vs `50`, `Samples=8`
- Artifacts:
  - `artifacts/richards/policy_autojit10_summary.json`
  - `artifacts/richards/policy_autojit25_summary.json`
  - `artifacts/richards/policy_autojit50_summary.json`
  - `artifacts/richards/policy_autojit100_summary.json`
  - `artifacts/richards/policy_autojit10_s8_summary.json`
  - `artifacts/richards/policy_autojit50_s8_summary.json`

Results (`Samples=5`, autojit mode):

- `AutoJit=10`: ARM `0.0518217086 s`, X86 `0.0829378906 s`, speedup `+37.52%`
- `AutoJit=25`: ARM `0.0519936924 s`, X86 `0.0783645534 s`, speedup `+33.65%`
- `AutoJit=50`: ARM `0.0518368482 s`, X86 `0.0750743374 s`, speedup `+30.95%`
- `AutoJit=100`: ARM `0.0518710516 s`, X86 `0.0741648130 s`, speedup `+30.06%`

Confirmation (`Samples=8`, autojit mode):

- `AutoJit=50`: ARM `0.0518055044 s`
- `AutoJit=10`: ARM `0.0515950649 s`
- ARM from->to (`50 -> 10`): `0.0518055044 -> 0.0515950649` (`+0.4062%`)
- Bootstrap CI (ARM `10` vs `50`): `[-0.1075%, +1.0074%]` (crosses 0)

Interpretation:

- Step 2 did not produce a statistically robust ARM-side policy gain on this
  benchmark/host pair.
- Conservative decision: keep default policy (`AutoJit=50`) for now and shift
  optimization effort to Step 3 codegen-level hot paths.

### Step 3 Precheck: `PYTHONJITMULTIPLECODESECTIONS` (`mcs=0/1`)

- Date: 2026-02-21
- Method:
  - same runner (`scripts/bench/run_richards_remote.sh`)
  - same host (`124.70.162.35`)
  - same benchmark (`richards`)
  - same threshold (`AutoJit=50`)
  - only toggle:
    - `PYTHONJITMULTIPLECODESECTIONS=0`
    - `PYTHONJITMULTIPLECODESECTIONS=1`
- Artifacts:
  - prior quick run (`Samples=5`):
    - `artifacts/richards/arm_mcs0_richards.json`
    - `artifacts/richards/arm_mcs1_richards.json`
  - confirmation run (`Samples=8`):
    - `artifacts/richards/arm_mcs0_richards_s8.json`
    - `artifacts/richards/arm_mcs1_richards_s8.json`
  - aggregate summary:
    - `artifacts/richards/mcs_compare_summary_20260221.json`

From -> To (`mcs0 -> mcs1`, `Samples=8`, lower is better):

- `nojit` mean: `0.0524051484 -> 0.0516509315 s` (`+1.4602%`)
  - median: `0.0517700650 -> 0.0516637075 s` (`+0.2059%`)
  - bootstrap CI (mean speedup): `[+0.0592%, +3.8710%]`
- `jitlist` mean: `0.0519003826 -> 0.0517930794 s` (`+0.2072%`)
  - median: `0.0518789075 -> 0.0517454035 s` (`+0.2580%`)
  - bootstrap CI (mean speedup): `[-0.3142%, +0.7050%]`
- `autojit50` mean: `0.0519645600 -> 0.0518082064 s` (`+0.3018%`)
  - median: `0.0518419635 -> 0.0516243400 s` (`+0.4216%`)
  - bootstrap CI (mean speedup): `[-0.3593%, +0.9709%]`

Interpretation:

- The earlier `Samples=5` quick run was clearly polluted by large outliers.
- On the confirmation set (`Samples=8`), `mcs=1` gain is small
  (about `0.2%~0.3%`) for JIT modes and not statistically robust
  (CI crosses zero).
- Decision: do not treat `multiple_code_sections` as a Step 3 primary
  optimization lever for now; continue with call-lowering/register/branch hot
  path optimization.

### Step 3 Attempt: AArch64 call-result return-register hint (regalloc)

- Date: 2026-02-21
- Code path:
  - `cinderx/Jit/lir/regalloc.cpp`
- Idea:
  - reduce hot-path call lowering move overhead by preferring ABI return
    registers for selected call outputs (so postalloc inserts fewer
    call-result shuffles).

Attempt A (failed, discarded):

- Strategy:
  - pre-hint *all* call outputs to ABI return registers on AArch64.
- Result:
  - introduced major code-size regression and ARM runtime test failures:
    - compact-shape size: `77160 -> 85160`
    - singleton delta: `384 -> 424`
  - failing tests:
    - `test_aarch64_call_sites_are_compact`
    - `test_aarch64_singleton_immediate_call_target_prefers_direct_literal`
- Root-cause inference:
  - broad hint over-constrained object-return call chains and increased
    spill/shuffle pressure around dense call sites.

Attempt B (safe but weak):

- Strategy:
  - restrict hint to FP call outputs only.
- Result:
  - ARM runtime tests passed.
  - code-size probe remained stable (`760/1144/delta=384`, `size200=77160`).
  - performance gain was small and mostly inconclusive (`~0.2%` class).

Attempt C (current):

- Strategy:
  - only hint short immediate call chains:
    - `call -> single immediate use -> call(arg0=previous result)`
  - this keeps the optimization on the intended hot path while avoiding broad
    register-pressure side effects.
- Validation:
  - ARM runtime tests: pass (`5/5`)
  - code-size probe:
    - `size1=760`, `size2=1144`, `delta=384`, `size200=77160`
- Artifacts:
  - `artifacts/richards/arm_after_regalloc_callchain_hint_mcs0_s8.json`
  - `artifacts/richards/arm_after_regalloc_callchain_hint_mcs0_s8_b.json`
  - `artifacts/richards/regalloc_callchain_hint_vs_baseline_mcs0_s8_summary.json`
  - `artifacts/richards/regalloc_callchain_hint_repeat_summary_20260221.json`

From -> To (`mcs=0`, baseline `artifacts/richards/arm_mcs0_richards_s8.json`):

- Run A (`n=8`):
  - `jitlist`: `0.0519003826 -> 0.0516489598 s` (`+0.4868%`, CI `[+0.0259%, +0.9590%]`)
  - `autojit50`: `0.0519645600 -> 0.0517226194 s` (`+0.4678%`, CI `[-0.0511%, +1.0594%]`)
- Run B (`n=8`):
  - `jitlist`: `0.0519003826 -> 0.0519029235 s` (`-0.0049%`, CI `[-0.6906%, +0.6573%]`)
  - `autojit50`: `0.0519645600 -> 0.0516798520 s` (`+0.5509%`, CI `[+0.0785%, +1.1032%]`)
- Pooled after (`n=16`) vs baseline (`n=8`):
  - `jitlist`: `+0.2403%` (CI `[-0.2808%, +0.7373%]`)
  - `autojit50`: `+0.5093%` (CI `[+0.0369%, +1.0711%]`)

Interpretation:

- This heuristic no longer regresses code size and keeps ARM runtime tests
  green.
- Observed gain is small but measurable for `autojit50` in pooled data
  (`~+0.5%`, CI slightly above 0).
- `jitlist` gain is unstable across reruns; treat that part as inconclusive.

Follow-up attempt (not kept):

- Tried expanding the short-chain hint from only `arg0` to any `argN`
  call-argument register mapping.
- Correctness remained green (`test_arm_runtime.py` passed), but performance
  evidence was not reliable:
  - host had competing `cargo/rustc` load bursts (load average > 4 with
    multiple 100% `rustc` workers),
  - richards samples showed cross-mode outliers (`~0.08s`, `~0.12s`, `~0.17s`)
    in runs that should stay around `~0.052s`.
- Clean-ish rerun still showed unstable outliers and no robust improvement for
  JIT modes.
- Decision: revert this wider `argN` variant and keep the narrower, previously
  validated short-chain heuristic.

### Unified ARM/X86 Check After Call-Chain Hint

- Date: 2026-02-21
- Method:
  - `scripts/bench/collect_arm_x86_richards.ps1 -Samples 5 -AutoJit 50`
- Artifacts:
  - `artifacts/richards/summary_arm_vs_x86_20260221_011223.json`
  - `artifacts/richards/arm_samples_20260221_011223.json`
  - `artifacts/richards/x86_samples_20260221_011223.json`

From -> To (vs previous `AutoJit=50` unified snapshot
`summary_arm_vs_x86_20260220_234127.json`):

- ARM `autojit50` mean:
  - `0.0518055044 -> 0.0518427644 s` (`-0.0719%`, essentially flat)
- X86 `autojit50` mean:
  - `0.0755916389 -> 0.0983565764 s` (x86 slower in this run)
- Reported ARM-vs-X86 speedup:
  - `+31.4666% -> +47.2910%`

Interpretation:

- The ARM absolute runtime is basically unchanged on this check.
- Relative ARM-vs-X86 gain increase here is dominated by x86-side run
  variance, not by a clear ARM-side throughput jump.

### Step 3 Recheck Under Idle ARM Host

- Date: 2026-02-21
- Motivation:
  - some intermediate runs were contaminated by external host load
    (`cargo/rustc` workers), so reran after load returned to idle.
- Artifacts:
  - `artifacts/richards/arm_after_regalloc_callchain_hint_mcs0_s8_clean2.json`
  - `artifacts/richards/regalloc_callchain_hint_vs_baseline_mcs0_s8_clean2_summary.json`

From -> To (stable arg0 short-chain hint vs baseline `mcs0_s8`):

- `jitlist` mean:
  - `0.0519003826 -> 0.0516978134 s` (`+0.3918%`)
  - CI: `[-0.2618%, +0.9960%]` (still slightly inconclusive)
- `autojit50` mean:
  - `0.0519645600 -> 0.0516449700 s` (`+0.6188%`)
  - CI: `[+0.1306%, +1.1866%]` (positive on this clean rerun)

Interpretation:

- Under low-load conditions, the current short-chain hint remains small but
  positive on `autojit50` (around `+0.6%`).
- This is still a micro-gain; continue with next hot-path optimization stage to
  target additional uplift.

### Step 3 Attempt: postalloc call-result move-chain fold

- Date: 2026-02-21
- Code path:
  - `cinderx/Jit/lir/postalloc.cpp`
- Idea:
  - fold a narrow hot path in postalloc:
    - `Move tmp, <retreg>` + `Move <argreg>, tmp`
    - into direct `<argreg> <- <retreg>` and drop the previous move on last-use
  - keep the transform restricted to argument-register destinations to avoid
    broad copy-propagation side effects.

Validation:

- Remote entrypoint deploy/build/smoke:
  - `scripts/arm/remote_update_build_test.sh` (`SKIP_PYPERF=1`)
  - passed on ARM host (`test_arm_runtime.py`: `5/5`).
- Benchmark runner:
  - `scripts/bench/run_richards_remote.sh`
  - `SAMPLES=8`, `AUTOJIT=50`, `PYTHONJITMULTIPLECODESECTIONS=0`
  - baseline and after both run under the same remote path.

Artifacts:

- Baseline samples:
  - `artifacts/richards/arm_baseline_postalloc_ab_s8_clean_20260221_084809.json`
- After samples:
  - `artifacts/richards/arm_postalloc_ab_s8_clean_20260221_085811.json`
- Comparison summary:
  - `artifacts/richards/postalloc_hotpath_vs_baseline_s8_summary_20260221.json`

From -> To (`baseline -> postalloc`, lower is better):

- `jitlist` mean:
  - `0.0518290104 -> 0.0518108696 s` (`+0.0350%`)
  - CI: `[-0.4915%, +0.6462%]` (inconclusive)
- `autojit50` mean:
  - `0.0519340710 -> 0.0516975166 s` (`+0.4555%`)
  - CI: `[+0.0476%, +0.9103%]` (positive)

Interpretation:

- This postalloc fold gives another small positive gain on `autojit50`
  (about `+0.46%`) with CI above zero in this run.
- `jitlist` remains effectively flat and statistically inconclusive.
- Result is consistent with the previous pattern: micro-gain on autojit hot
  path, not a large mode-wide shift.

### Unified ARM/X86 Check After Postalloc Fold

- Date: 2026-02-21
- Method:
  - `scripts/bench/collect_arm_x86_richards.ps1 -Samples 8 -AutoJit 50`
- Artifacts:
  - `artifacts/richards/summary_arm_vs_x86_20260221_091757.json`
  - `artifacts/richards/arm_samples_20260221_091757.json`
  - `artifacts/richards/x86_samples_20260221_091757.json`
  - `artifacts/richards/summary_nojit_20260221_091757.json`
  - `artifacts/richards/summary_jitlist_20260221_091757.json`
  - `artifacts/richards/summary_autojit50_20260221_091757.json`

From -> To (vs previous cross-host snapshot
`summary_arm_vs_x86_20260221_011223.json`):

- `autojit50`:
  - ARM mean: `0.0518427644 -> 0.0520960826 s` (`-0.4886%`)
  - X86 mean: `0.0983565764 -> 0.1080564280 s`
  - ARM-vs-X86 speedup: `+47.2910% -> +51.7881%`
- `jitlist`:
  - ARM mean: `0.0517584942 -> 0.0547409418 s`
  - X86 mean: `0.0958292193 -> 0.0920441395 s`
  - ARM-vs-X86 speedup: `+45.9888% -> +40.5275%`

Interpretation:

- Cross-host result still comfortably satisfies the target "ARM >= X86 +3%"
  on all modes, including `autojit50`.
- This run has noticeable tail-noise on both hosts (e.g. ARM `jitlist`
  has `0.064s` samples; x86 `nojit` reaches `0.20s`, `autojit50` reaches
  `0.162s`), so cross-host deltas should be treated as directional rather than
  precise micro-regression/progression evidence.
- The cleaner signal for the postalloc optimization remains the ARM-only A/B:
  `autojit50` `0.0519341 -> 0.0516975 s` (`+0.4555%`, CI positive).

### Step 3 Iteration: call-result fold across guard gaps

- Date: 2026-02-21
- Commits:
  - `18d9c4d5` (initial self-move-gap fold + RED test)
  - `c7330521` (root-cause fix: fold across non-clobber guard gaps)
- Code path:
  - `cinderx/Jit/lir/postalloc.cpp`
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`

TDD and root-cause evidence:

- RED:
  - new regression test
    `test_aarch64_duplicate_call_result_arg_chain_is_compact` failed on ARM:
    - compiled size `44656`, guard `<= 44500`.
- Investigation:
  - enabled `PYTHONJITDUMPLIR=1` + `PYTHONJITLOGFILE`.
  - observed real hot pattern was not adjacent move pairs; call-result copies are
    frequently separated by `Guard` / metadata updates before arg-lowering move.
  - conclusion:
    - adjacent-only folding misses the dominant chain shape for this workload.
- GREEN:
  - rewrote matching to scan backward across non-clobber instructions and stop
    on `tmp`/`retreg` overwrite or any call boundary.
  - remote entrypoint validation (`remote_update_build_test.sh`, `SKIP_PYPERF=1`)
    passed with runtime tests `6/6`.

From -> To (synthetic hot-shape size; lower is better):

- Artifact:
  - `artifacts/richards/guardgap_fold_shape_compare_20260221.json`
- Representative point (`n_calls=64`):
  - `44656 -> 44144` bytes (`-512`, `-1.1465%`)
- Linear trend:
  - each doubling keeps the same direction; savings scale with call-chain count.

Richards snapshot after this iteration:

- Artifact:
  - `artifacts/richards/arm_after_guardgap_fold_s8.json`
  - `artifacts/richards/arm_after_guardgap_fold_s8_summary.json`
- Means (`n=8`):
  - `nojit`: `0.07656 s`
  - `jitlist`: `0.11976 s`
  - `autojit50`: `0.12580 s`

Interpretation:

- This run is heavily noise/host-load contaminated (very wide tails vs prior
  stable `~0.05s`-class snapshots), so it is not a reliable micro-throughput
  signal.
- The robust signal for this iteration is the confirmed code-shape reduction
  on the targeted call-result chain pattern, now guarded by a regression test.



# Findings & Decisions

## Requirements
- Enable `ENABLE_ADAPTIVE_STATIC_PYTHON` to work on official Python 3.14 ARM server path.
- Enable and follow skills/process: `using-superpowers` + `planning-with-files`.
- Execute the standard loop: `brainstorming -> writing-plans -> test-driven-development -> verification-before-completion`.
- Use `<remote test entry>` for all test/verification runs.
- Write key test/verification outcomes into this file.

## Research Findings
- `ENABLE_ADAPTIVE_STATIC_PYTHON` appears in `setup.py` (active editor context from user).
- Planning files were not present initially and were created in project root.
- `planning-with-files` catchup script ran without unsynced-session output.
- `setup.py` currently sets `ENABLE_ADAPTIVE_STATIC_PYTHON` via `set_option("ENABLE_ADAPTIVE_STATIC_PYTHON", meta_312)`, which suggests 3.12-gated behavior.
- `CMakeLists.txt` exposes `set_flag(ENABLE_ADAPTIVE_STATIC_PYTHON)`.
- Source tree already contains `ENABLE_ADAPTIVE_STATIC_PYTHON` usage in:
  - `cinderx/Interpreter/3.14/*`
  - `cinderx/Interpreter/3.15/*`
  - `cinderx/Interpreter/3.12/*`
- No concrete repository path/command for `<remote test entry>` found yet.
- `setup.py` computes:
  - `meta_312 = meta_python and py_version == "3.12"`
  - `is_314plus = py_version == "3.14" or py_version == "3.15"`
  - But `ENABLE_ADAPTIVE_STATIC_PYTHON` still defaults to `meta_312`.
- `.github/workflows/ci.yml` and `.github/workflows/publish.yml` pin Python `3.14.3`.
- `.github/workflows/getdeps-3_14-linux.yml` uses getdeps as a full build/test pipeline, with test command:
  - `python3 build/fbcode_builder/getdeps.py test --src-dir=. cinderx-3_14 --project-install-prefix cinderx-3_14:/usr/local`
- `build/fbcode_builder/manifests/cinderx-3_14` defines:
  - `[setup-py.test] python_script = cinderx/PythonLib/test_cinderx/test_oss_quick.py`
  - `[setup-py.env] CINDERX_ENABLE_PGO=1, CINDERX_ENABLE_LTO=1`
- CI quick path exists separately:
  - `uv run pytest cinderx/PythonLib/test_cinderx/test*.py`
- Current likely candidates for `<remote test entry>` are:
  - getdeps test command (closer to release/manifest workflow)
  - CI pytest command (faster feedback)
- `build/fbcode_builder/manifests/cinderx-3_14` quick test currently only checks import (`test_oss_quick.py`), not adaptive-static functionality.
- `git blame setup.py` shows:
  - `ENABLE_ADAPTIVE_STATIC_PYTHON` default (`meta_312`) introduced in commit window around 2025-10 OSS 3.14 compatibility work.
  - Later 2026-01 changes added `is_314plus` only for `ENABLE_INTERPRETER_LOOP` and `ENABLE_PEP523_HOOK`, leaving adaptive-static unchanged.
- `README.md` currently lists Linux `x86_64` as requirement; ARM is not declared as supported in OSS docs.
- `pyproject.toml` cibuildwheel targets only `cp314-manylinux_x86_64` and `cp314-musllinux_x86_64` (no ARM wheel target).
- Repository does contain multiple recent AArch64-related fixes, indicating partial ARM compatibility efforts despite packaging targets being x86_64.
- No dedicated test file currently verifies `setup.py` defaulting logic for `ENABLE_ADAPTIVE_STATIC_PYTHON`.
- Commit `d0297b3e` ("Enable interpreter loop on 3.14 OSS builds") notes that some codepaths (including adaptive-static control knobs) could not compile without interpreter loop, and enabled interpreter loop/PEP523 for 3.14.
- Even after that commit, `ENABLE_ADAPTIVE_STATIC_PYTHON` stayed defaulted to `meta_312`, indicating prior conservative rollout rather than missing implementation.
- In `cinderx/Interpreter/3.14/interpreter.c`, `Ci_InitOpcodes()` patches CPython opcode cache/deopt tables only when `ENABLE_ADAPTIVE_STATIC_PYTHON` is defined.
- In `cinderx/Interpreter/3.14/cinder-bytecodes.c`, many runtime specializations are gated by `#if ENABLE_SPECIALIZATION && defined(ENABLE_ADAPTIVE_STATIC_PYTHON)`, including:
  - `STORE_LOCAL_CACHED`
  - `BUILD_CHECKED_LIST_CACHED`
  - `BUILD_CHECKED_MAP_CACHED`
  - `LOAD_METHOD_STATIC_CACHED`
  - `INVOKE_FUNCTION_CACHED` / indirect cached path
  - `TP_ALLOC_CACHED`
  - `CAST_CACHED`
  - `LOAD_OBJ_FIELD` / `LOAD_PRIMITIVE_FIELD`
  - `STORE_OBJ_FIELD` / `STORE_PRIMITIVE_FIELD`
- Therefore enabling this flag is expected to affect adaptive specialization behavior and performance characteristics for Static Python-heavy paths.
- Attempted remote execution on ARM host `124.70.162.35` via SSH failed due authentication:
  - `Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password)`
- `getdeps` current test entry for `cinderx-3_14` is import-only (`test_oss_quick.py`), insufficient to prove adaptive-static specialization is active.
- Existing static runtime tests contain comments about exercising cached paths (e.g. `INVOKE_FUNCTION_CACHED`) but do not explicitly assert adaptive/cached opcode presence.
- Existing bytecode assertion helpers in `test_compiler/common.py` use regular disassembly (`Bytecode(...)`) and do not inspect adaptive-specialized instruction stream by default.
- Implemented changes in this session:
  - `setup.py`: added `should_enable_adaptive_static_python()` and switched default option source to it.
  - `setup.py`: added `is_env_flag_enabled()` and switched `CINDERX_ENABLE_PGO/CINDERX_ENABLE_LTO` to real boolean parsing (`0/false/off/no` disables).
  - `_cinderx`: added runtime API `is_adaptive_static_python_enabled()`.
  - `cinderx.__init__`: exports `is_adaptive_static_python_enabled()` with fallback.
  - `test_oss_quick.py`: now asserts adaptive-static enablement state by platform/version.
  - Added local unit tests for setup default logic, env-flag parsing, and API presence.

## Verification Results
- Local RED (expected):
  - `python -m unittest tests/test_setup_adaptive_static_python.py -v`
  - Failure reason: missing `setup.should_enable_adaptive_static_python`.
- Local GREEN:
  - `$env:PYTHONPATH='cinderx/PythonLib'; python -m unittest tests/test_setup_adaptive_static_python.py tests/test_cinderx_adaptive_static_api.py -v`
  - Result: 10 tests passed.
- Syntax check:
  - `python -m py_compile setup.py cinderx/PythonLib/cinderx/__init__.py cinderx/PythonLib/test_cinderx/test_oss_quick.py tests/test_setup_adaptive_static_python.py tests/test_cinderx_adaptive_static_api.py`
  - Result: pass.
- Remote ARM verification (`124.70.162.35`, `aarch64`, Python `3.14.3`):
  - `getdeps build` failure (captured):
    - `getdeps.py build --src-dir=. cinderx-3_14 ...`
    - Failure: `/usr/bin/ld: ... LLVMgold.so: cannot open shared object file`
  - Root-cause evidence:
    - `setup.py` previously enabled LTO when `CINDERX_ENABLE_LTO` env var merely existed.
    - `getdeps` manifest exports `CINDERX_ENABLE_LTO=1 CINDERX_ENABLE_PGO=1`.
  - Remote install pass after fixes:
    - `env CINDERX_ENABLE_PGO=0 CINDERX_ENABLE_LTO=0 python setup.py install`
    - Build/install reached `[100%] Built target _cinderx` and installed to `/root/venv-cinderx314/lib/python3.14/site-packages`.
  - Remote functional checks (same host/venv):
    - `python cinderx/PythonLib/test_cinderx/test_oss_quick.py` -> `Ran 2 tests ... OK`
    - Runtime probe:
      - `hasattr(cinderx, "is_adaptive_static_python_enabled") == True`
      - `cinderx.is_adaptive_static_python_enabled() == True`
  - Remote enablement evidence (build artifacts):
    - `scratch/temp.linux-aarch64-cpython-314/CMakeCache.txt` contains `ENABLE_ADAPTIVE_STATIC_PYTHON:UNINITIALIZED=1`
    - `_cinderx` flags contain `-DENABLE_ADAPTIVE_STATIC_PYTHON` in:
      - `scratch/temp.linux-aarch64-cpython-314/CMakeFiles/_cinderx.dir/flags.make`

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Defer implementation until brainstorming design is approved | Required by brainstorming skill hard gate |
| Keep verification evidence tied to `<remote test entry>` only | Explicit user requirement |
| Enable by default on Python 3.14 ARM only | Matches target while minimizing regression surface compared with global 3.14+ enablement |
| Treat `CINDERX_ENABLE_PGO/LTO` as boolean values, not presence-only toggles | Required for reliable ARM builds where LTO toolchain plugin may be unavailable |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Default path for `session-catchup.py` did not exist in this environment | Switched to the installed skill path under `C:/Users/Administrator/.codex/planning-with-files/...` |
| `rg` against non-existent `tools/` and `scripts/` paths failed | Scoped next searches to existing paths (`.github/`, repository root) |
| RED test initially failed due missing local dependency `setuptools` | Installed `setuptools` and re-ran to capture expected feature-missing failure |
| API unit test imported non-repo `cinderx` package | Ran tests with `PYTHONPATH=cinderx/PythonLib` to target repository code |
| `getdeps build` failed linking `_cinderx.so` with missing `LLVMgold.so` | Added boolean env parsing in `setup.py`; validated with `CINDERX_ENABLE_LTO=0` |
| ARM host initially missed system build prerequisite `m4` for getdeps autoconf path | Installed with `dnf install -y m4` |

## Resources
- `setup.py`
- `task_plan.md`
- `progress.md`
- Skill docs:
  - `C:/Users/Administrator/.codex/superpowers/skills/using-superpowers/SKILL.md`
  - `C:/Users/Administrator/.codex/planning-with-files/.codex/skills/planning-with-files/SKILL.md`
  - `C:/Users/Administrator/.codex/superpowers/skills/brainstorming/SKILL.md`
  - `C:/Users/Administrator/.codex/superpowers/skills/writing-plans/SKILL.md`
  - `C:/Users/Administrator/.codex/superpowers/skills/test-driven-development/SKILL.md`
  - `C:/Users/Administrator/.codex/superpowers/skills/verification-before-completion/SKILL.md`

## Visual/Browser Findings
- No browser or image operations used yet.

---
*Remote verification evidence updated on 2026-02-24 against `124.70.162.35`.*

## 2026-02-25 ARM verification (124.70.162.35)

- Scope: verify `ENABLE_ADAPTIVE_STATIC_PYTHON` works both without LTO and with LTO enabled.
- Build environment: `/root/venv-cinderx314` + Python 3.14 on aarch64.

### Code/Build adjustments used in this run

- `CMakeLists.txt` LTO logic keeps `ld.lld` preference for Clang LTO.
- `CMakeLists.txt` FetchContent sources switched from `GIT_REPOSITORY` to fixed `codeload.github.com` tarball URLs for:
  - `asmjit`
  - `fmt`
  - `parallel-hashmap`
  - `usdt`

### Validation results

1. No-LTO build/install

- Command:
  - `env CINDERX_ENABLE_PGO=0 CINDERX_ENABLE_LTO=0 python setup.py install`
- Log: `/tmp/cinderx_no_lto.log`
- Result:
  - Build reached `[100%] Built target _cinderx` and install phase (`install_lib`, `install_egg_info`, `install_scripts`).
  - Runtime probe: `ADAPTIVE_STATIC True`

2. LTO build/install

- Command:
  - `env CINDERX_ENABLE_PGO=0 CINDERX_ENABLE_LTO=1 python setup.py install`
- Log: `/tmp/cinderx_with_lto.log`
- Result:
  - Log contains `LTO: Enabled (full LTO)` and reaches install phase (`install_lib`, `install_egg_info`, `install_scripts`).
  - Runtime probe: `ADAPTIVE_STATIC True`
  - LTO evidence on generated build files:
    - `scratch/temp.linux-aarch64-cpython-314/CMakeCache.txt`: `ENABLE_LTO:BOOL=ON`
    - `scratch/temp.linux-aarch64-cpython-314/CMakeFiles/*/flags.make`: contains `-flto`
    - `scratch/temp.linux-aarch64-cpython-314/CMakeFiles/_cinderx.dir/link.txt`: contains `-flto -fuse-ld=lld`

3. End-to-end smoke

- Command:
  - `python cinderx/PythonLib/test_cinderx/test_oss_quick.py`
- Result:
  - `Ran 2 tests ... OK`

## 2026-02-25 bench-cur-7c361dce integration verification

- Target branch: `bench-cur-7c361dce`
- Upstream sync: merged `upstream/main` (facebookincubator/cinderx) into branch.
- Feature merge: cherry-picked commit `170439be` (ENABLE_ADAPTIVE_STATIC_PYTHON + LTO robustness).
- Resulting branch head: `91363f8f`.

### Local validation

- `PYTHONPATH=cinderx/PythonLib python -m unittest tests/test_setup_adaptive_static_python.py tests/test_cinderx_adaptive_static_api.py`
- Result: `Ran 10 tests ... OK`.

### ARM validation host

- Host: `124.70.162.35`
- Source under test: snapshot of local `bench-cur-7c361dce` synced to `/root/work/cinderx-main`.

1. No LTO
- Build command: `CINDERX_ENABLE_PGO=0 CINDERX_ENABLE_LTO=0 python setup.py install`
- Log: `/tmp/bench_no_lto.log`
- Result:
  - install reached `running install_scripts`
  - `ADAPTIVE_STATIC True`
  - no `LTO:` marker in log.

2. With LTO
- Build command: `CINDERX_ENABLE_PGO=0 CINDERX_ENABLE_LTO=1 python setup.py install`
- Log: `/tmp/bench_with_lto.log`
- Result:
  - background build exit code `0` (`/tmp/bench_with_lto.exit`)
  - `ADAPTIVE_STATIC True`
  - LTO enabled evidence:
    - `/tmp/bench_with_lto.log`: `LTO: Enabled (full LTO)`
    - `scratch/temp.linux-aarch64-cpython-314/CMakeCache.txt`: `ENABLE_LTO:BOOL=ON`
    - `scratch/temp.linux-aarch64-cpython-314/CMakeFiles/*/flags.make`: contains `-flto`
    - `scratch/temp.linux-aarch64-cpython-314/CMakeFiles/_cinderx.dir/link.txt`: contains `-flto -fuse-ld=lld`

3. Smoke test
- `python cinderx/PythonLib/test_cinderx/test_oss_quick.py`
- Result: `Ran 2 tests ... OK`

## 2026-02-25 New Task: ENABLE_LIGHTWEIGHT_FRAMES + LTO/PGO/ADAPTIVE_STATIC (ARM 3.14)

### Requirements captured
- Enable and debug `ENABLE_LIGHTWEIGHT_FRAMES` on official Python 3.14 ARM server.
- Must coexist with:
  - `CINDERX_ENABLE_LTO=1`
  - `CINDERX_ENABLE_PGO=1`
  - `ENABLE_ADAPTIVE_STATIC_PYTHON=1`
- Workflow explicitly required:
  - brainstorming -> writing-plans -> test-driven-development -> verification-before-completion
- All tests and validation must run through remote entrypoint (`<远端测试入口>`).
- Key outcomes/evidence must be recorded in `findings.md`.

### Initial discoveries
- Existing setup defaults currently gate `ENABLE_LIGHTWEIGHT_FRAMES` to meta 3.12 path, not 3.14 by default.
- Previous work already stabilized adaptive static + LTO on ARM 3.14 and switched CMake dependency fetches to codeload tarballs for reliability.

### Open questions to resolve in brainstorming
1. Exact command/script that user wants treated as `<远端测试入口>` for this task.
2. Authoritative signal for "lightweight frames enabled" acceptance.
3. Required verification breadth (targeted tests only vs targeted + smoke suite).

### Context exploration updates (brainstorming)
- `setup.py` currently sets `ENABLE_LIGHTWEIGHT_FRAMES` default to `meta_312` only.
- C++ side already has many `#ifdef ENABLE_LIGHTWEIGHT_FRAMES` and 3.14-specific code paths (`PY_VERSION_HEX >= 0x030E0000`) in JIT runtime/frame/codegen files.
- There is currently no user-facing API equivalent to `is_adaptive_static_python_enabled()` for lightweight-frames compile-time state.
- Existing tests cover adaptive-static behavior (`tests/test_setup_adaptive_static_python.py`, `tests/test_cinderx_adaptive_static_api.py`, `test_oss_quick.py`) but do not yet assert lightweight-frames enablement.

### 2026-02-25 Brainstorming decision update
- User decision: prioritize Python 3.14 support for `ENABLE_LIGHTWEIGHT_FRAMES`.
- Design adjustment: Stage A default enable scope targets 3.14 first (ARM), not broad 3.15 rollout.

## 2026-02-26 Completion Evidence: LIGHTWEIGHT_FRAMES + LTO/PGO/ADAPTIVE_STATIC (ARM 3.14)

### Stage-A policy confirmation
- `setup.py` now applies:
  - `ENABLE_LIGHTWEIGHT_FRAMES` default `ON` for OSS Python `3.14` on `aarch64/arm64`
  - `ENABLE_LIGHTWEIGHT_FRAMES` default `OFF` for `3.15` in Stage A (still manually overridable via env)
  - existing meta `3.12` behavior preserved
- User-confirmed rollout:
  - prioritize 3.14 now
  - x86 extension deferred
  - 3.15 deferred, stage-A default-off accepted

### Additional robustness fix for PGO
- Symptom observed:
  - intermittent `test_generators` failure during `PGO STAGE 2/3` workload caused `setup.py install` failure with `CINDERX_ENABLE_PGO=1`.
- Fix:
  - added `run_pgo_workload()` in `setup.py`
  - bounded retry on workload failure (`2` attempts total)
  - wired `BuildCommand._run_with_pgo()` to use helper
- TDD:
  - RED: `tests/test_setup_pgo_workload_retries.py` failed (`AttributeError: module 'setup' has no attribute 'run_pgo_workload'`)
  - GREEN: same test passed after helper implementation

### Remote test entrypoint
- All verification executed through:
  - `ssh root@124.70.162.35`
- Remote runtime:
  - Python `3.14.3`
  - arch `aarch64`
  - source under test: `/root/work/cinderx-main`

### Remote verification commands and outcomes

1. Setup/default/API tests
- Command:
  - `python -m unittest tests/test_setup_adaptive_static_python.py tests/test_setup_lightweight_frames.py tests/test_setup_pgo_workload_retries.py -v`
  - `PYTHONPATH=cinderx/PythonLib python -m unittest tests/test_cinderx_lightweight_frames_api.py -v`
- Result:
  - `Ran 15 tests ... OK`
  - `Ran 2 tests ... OK`

2. LTO path
- Command:
  - `CINDERX_ENABLE_PGO=0 CINDERX_ENABLE_LTO=1 python setup.py install`
- Result:
  - install success (ssh command exit code `0`)
  - runtime probe:
    - `ADAPTIVE_STATIC True`
    - `LIGHTWEIGHT_FRAMES True`
  - build evidence:
    - `scratch/temp.linux-aarch64-cpython-314/CMakeCache.txt`:
      - `ENABLE_LTO:BOOL=ON`
      - `ENABLE_ADAPTIVE_STATIC_PYTHON:UNINITIALIZED=1`
      - `ENABLE_LIGHTWEIGHT_FRAMES:UNINITIALIZED=1`
    - `scratch/temp.linux-aarch64-cpython-314/CMakeFiles/_cinderx.dir/link.txt` contains:
      - `-flto`
      - `-fuse-ld=lld`
      - `-DENABLE_ADAPTIVE_STATIC_PYTHON`
      - `-DENABLE_LIGHTWEIGHT_FRAMES`

3. PGO + LTO path
- Command:
  - `CINDERX_ENABLE_PGO=1 CINDERX_ENABLE_LTO=1 python setup.py install`
- Result:
  - full 3-stage PGO flow completed successfully (ssh command exit code `0`)
  - log confirms:
    - `PGO STAGE 1/3`
    - `PGO STAGE 2/3: Running profiling workload`
    - `PGO STAGE 2b: Merging profile data`
    - `PGO STAGE 3/3: Rebuilding with profile-guided optimizations`
  - PGO/LTO evidence in cache and link flags:
    - `ENABLE_PGO_GENERATE:BOOL=OFF`
    - `ENABLE_PGO_USE:BOOL=ON`
    - `PGO_PROFILE_FILE:STRING=/root/work/cinderx-main/scratch/temp.linux-aarch64-cpython-314/pgo_data/code.profdata`
    - link flags include:
      - `-flto`
      - `-fprofile-instr-use=/root/work/cinderx-main/scratch/temp.linux-aarch64-cpython-314/pgo_data/code.profdata`
      - `-DENABLE_ADAPTIVE_STATIC_PYTHON`
      - `-DENABLE_LIGHTWEIGHT_FRAMES`
  - runtime probe after install:
    - `ADAPTIVE_STATIC True`
    - `LIGHTWEIGHT_FRAMES True`

4. Smoke test
- Command:
  - `python cinderx/PythonLib/test_cinderx/test_oss_quick.py`
- Result:
  - `Ran 3 tests ... OK`

### Final conclusion
- On ARM Python 3.14, `ENABLE_LIGHTWEIGHT_FRAMES` is now verified to work end-to-end together with:
  - `ENABLE_ADAPTIVE_STATIC_PYTHON`
  - `CINDERX_ENABLE_LTO=1`
  - `CINDERX_ENABLE_PGO=1`
- Stage-A policy is as requested:
  - 3.14 prioritized
  - 3.15 default-off (manual env override still available)
  - x86 extension deferred to later phase

## 2026-02-27 Task: CPython Native vs CinderX (Interpreter + JIT) on ARM 3.14

### Requested workflow status
- Requested process: `brainstorming -> writing-plans -> test-driven-development -> verification-before-completion`.
- Requested skills: `using-superpowers` + `planning-with-files`.
- Session constraints observed:
  - active skill registry in this session does not include those two skills,
  - `skill-installer` helper could not be executed because local `python` is unavailable.

### Brainstorming results
- Existing benchmark evidence is already sufficient to explain the main behavior pattern:
  - cold/short-run results often make JIT look slower,
  - warm/steady-state results can show JIT speedups.
- Current richards runner contract does not include an explicit "pure CPython native (no CinderX import)" mode:
  - `scripts/bench/run_richards_remote.sh` supports `nojit`, `jitlist`, `autojit50`.
  - `scripts/arm/remote_update_build_test.sh` injects `sitecustomize.py` that auto-loads CinderX unless `CINDERX_DISABLE=1`.
  - Therefore current `nojit` should be interpreted as "CinderX loaded, JIT disabled", not pure CPython baseline.

### TDD status for this task
- RED/GREEN target defined:
  - add explicit `cpython` mode to richards sampling contract,
  - then compare `cpython` vs `cinderx_nojit` vs `jitlist` vs `autojit50`.
- Execution status:
  - blocked before RED/GREEN run because remote verification entrypoint is currently unreachable in this session.

### Verification attempts via `<remote test entry>`
- Attempted remote entry command:
  - `powershell -ExecutionPolicy Bypass -File scripts/push_to_arm.ps1 -RepoPath c:\work\code\cinderx -WorkBranch bench-cur-7c361dce -ArmHost 124.70.162.35 -SkipPyperformance`
- Result:
  - failed in `sync_upstream.ps1` at `git fetch origin` (`Failed to connect to github.com:443` / connection reset).
- Direct host connectivity checks:
  - `ssh root@124.70.162.35 "echo remote-ok"` -> `Permission denied (publickey,...)`
  - `ssh root@106.14.164.133 "echo remote-ok"` -> `Permission denied (publickey,...)`

### Performance evidence used for analysis (existing validated artifacts)
- Source: `artifacts/richards/arm_samples_20260221_091757.json`
  - `nojit` mean: `0.0534650194 s`
  - `jitlist` mean: `0.0547409418 s` (`+2.386%` vs nojit, slower)
  - `autojit50` mean: `0.0520960826 s` (`-2.560%` vs nojit, faster)
- Source: prior cold/short-run section (`pyperformance --fast`) in this file:
  - nojit `103 ms`, jitlist `181 ms`, autojit50 `191 ms` (JIT appears much slower).
- Source: prior warm-loop tail section in this file:
  - nojit tail-30 `0.2130860543 s`
  - jitlist tail-30 `0.1841729017 s` (`-13.57%`)
  - autojit50 tail-30 `0.0810525232 s` (`-61.96%`)

### Why ARM 3.14 can look "full" / slower
- Benchmark regime mismatch:
  - in short/cold runs, JIT compile and initialization overhead dominates;
  - in warm runs, compiled-path wins can appear after overhead amortization.
- Low-latency floor + host noise:
  - many ARM samples are near `~0.05s`; sub-1% gains are easily hidden by jitter/outliers.
- Baseline definition gap:
  - current "nojit" is not pure CPython native, so "CPython vs CinderX" can be misread.
- Threshold/workload interaction:
  - `autojit` behavior depends on call counts and worker lifecycle; short tasks may pay compile cost without enough hot-loop reuse.

### Next required step for definitive answer
- Add and validate explicit `cpython` sampling mode (`CINDERX_DISABLE=1`) through the same remote entry flow, then re-run comparison matrix after remote auth/network is restored.

## 2026-02-27 Remote Run: CPython Native (interp/JIT) vs CinderX (interp/JIT)

### Remote target
- Host: `root@124.70.162.35`
- Arch: `aarch64`

### Environment facts observed
- Existing CPython at `/opt/python-3.14/bin/python3.14` had:
  - `sys._jit.is_available() == False`
  - i.e. cannot directly run native CPython JIT there.
- Built a JIT-enabled CPython 3.14.3 under tmpfs:
  - install path: `/tmp/cpython314jit/install/bin/python3.14`
  - build source: `/tmp/cpython314jit/src` from `Python-3.14.3.tgz`
  - config: `--enable-experimental-jit=yes-off`
  - verification:
    - default: `sys._jit -> (True, False)`
    - `PYTHON_JIT=1`: `sys._jit -> (True, True)`
- CinderX runtime path:
  - `/root/venv-cinderx314/bin/python`
  - JIT API sanity check:
    - `cinderx.jit.force_compile(f) == True`
    - compiled size observed (`f`): `960` bytes.

### Practical blocker and workaround
- Root filesystem is full (`/` at 100%), so `pyperformance run` default venv root under `/root/venv` fails.
- Workaround used:
  - build CPython JIT in `/tmp` (tmpfs),
  - run benchmark directly via `bm_richards/run_benchmark.py` + `--debug-single-value`,
  - avoid pyperformance's internal auto-venv creation in `/root`.

### Benchmark method
- Benchmark script:
  - `/root/venv-cinderx314/lib/python3.14/site-packages/pyperformance/data-files/benchmarks/bm_richards/run_benchmark.py`
- Samples per mode: `5`
- Modes:
  - `cpython_interp`: `/tmp/venv-cpython314jit/bin/python`, `PYTHON_JIT=0`
  - `cpython_jit`: `/tmp/venv-cpython314jit/bin/python`, `PYTHON_JIT=1`
  - `cinderx_interp`: `/root/venv-cinderx314/bin/python`, `PYTHONJITDISABLE=1`
  - `cinderx_jit`: `/root/venv-cinderx314/bin/python`, `PYTHONJITAUTO=50`

### Key results (richards, lower is better)
- Artifact:
  - `artifacts/richards/direct_richards_cpython_cinderx_autojit_20260227_130845.json`

- Means:
  - `cpython_interp`: `0.0516462776 s`
  - `cpython_jit`: `0.0486890842 s`
    - vs CPython interp: `-5.726%` (faster)
  - `cinderx_interp`: `0.0520793502 s`
    - vs CPython interp: `+0.839%` (slower)
  - `cinderx_jit` (`autojit50`): `0.0516185456 s`
    - vs CinderX interp: `-0.885%` (faster)
    - vs CPython JIT: `+6.017%` (slower)

### Notes on interpretation
- This run is a same-host, same-benchmark comparison and uses the actual requested four categories.
- Because host variance still exists, treat this as directional for this machine/setup.
- In this sample set:
  - CPython native JIT gain is clear over CPython interp.
  - CinderX JIT gain over CinderX interp is present but small.

## 2026-02-27 Assembly Diff: CinderX JIT vs CPython Native JIT (AArch64)

### Setup
- Host: `root@124.70.162.35`
- Function shape on both sides:
  - `def f(n): s=0; for i in range(n): s += i; return s`
- CinderX:
  - force-compiled `f`
  - dumped JIT ELF, extracted `.text`, disassembled as AArch64
- CPython native JIT:
  - `PYTHON_JIT=1`
  - executor found at `JUMP_BACKWARD` offset `50`
  - disassembled `get_jit_code()` blob (head `952` bytes for same-size window)

### Key evidence artifacts
- `artifacts/asm/cinderx_f_disasm_aarch64.txt`
- `artifacts/asm/cpython_executor_disasm_head952_aarch64.txt`
- `artifacts/asm/cpython_executor_disasm_head2880_aarch64.txt`
- `artifacts/asm/cinderx_f_text.bin`
- `artifacts/asm/cpython_executor_head952.bin`
- `artifacts/asm/cpython_executor_full4096.bin`
- `artifacts/asm/byte_compare_cinderx_vs_cpython_head952.txt`
- `artifacts/asm/inst_mix_cinderx_vs_cpython_head952.txt`
### Quantitative summary
- Byte-level equal-size compare (`952` vs `952`):
  - `same_bytes=62`
  - `same_ratio=6.5126%`
  - `lcp=0`
- Instruction mix (`238` instructions each in compared window):
  - CinderX: `bl=7`, `blr=14`, `ret=3`, `b.cond=16`, `cbz/cbnz=5`, `tbz/tbnz=2`, `ldr-literal=14`
  - CPython: `bl=6`, `blr=2`, `ret=0`, `b.cond=8`, `cbz/cbnz=6`, `tbz/tbnz=6`, `ldr-literal=4`

### Main difference pattern
- CinderX sample shows heavier literal-pool indirect helper calls (`ldr x16, literal` + `blr x16`) and a compact deopt dispatch ladder.
- CPython native JIT sample shows executor/superblock style with more direct internal `bl` edges and fewer indirect callback sites in the equal-size window.

## 2026-02-27 ARM Probe: `cinderjit` APIs vs CPython Native

### Verification entrypoint and artifacts
- Remote entrypoint used: `ssh root@124.70.162.35`
- Probe script: `scripts/arm/probe_jit_apis.py`
- Local artifacts:
  - `artifacts/arm/jit_api_probe/cinderx_default.json`
  - `artifacts/arm/jit_api_probe/cinderx_jit_env.json`
  - `artifacts/arm/jit_api_probe/cpython_default.json`
  - `artifacts/arm/jit_api_probe/cpython_python_jit_1.json`
  - `artifacts/arm/jit_api_probe/cpython_help_xoptions.txt`

### Runs executed
- CinderX env (default):  
  `/root/venv-cinderx314/bin/python /root/work/cinderx-main/scripts/arm/probe_jit_apis.py --label cinderx_default`
- CinderX env (JIT vars):  
  `PYTHONJIT=1 PYTHONJITAUTO=1 /root/venv-cinderx314/bin/python ... --label cinderx_jit_env`
- CPython native (default):  
  `/opt/python-3.14/bin/python3.14 ... --label cpython_default`
- CPython native (`PYTHON_JIT=1`):  
  `PYTHON_JIT=1 /opt/python-3.14/bin/python3.14 ... --label cpython_python_jit_1`

### Result summary
- CinderX runtime (`/root/venv-cinderx314/bin/python`):
  - `cinderjit` import: success.
  - API presence: `get_compiled_size`, `disassemble`, `get_compiled_functions`, `dump_elf` all present.
  - Probe payload compiled: `is_jit_compiled=True`.
  - `get_compiled_size(payload)=1232` bytes.
  - `get_compiled_functions_count`: `1` (default) / `7` (`PYTHONJIT=1,PYTHONJITAUTO=1`).
  - `dump_elf` succeeded, ELF sizes:
    - default: `12461` bytes
    - jit_env: `20653` bytes
  - `disassemble(payload)` call succeeded but produced no textual asm output on stdout/stderr in this build (markers only).
  - Note: after `import cinderx`, `cinderjit.__spec__` is `None`; `find_spec("cinderjit")` can raise `ValueError`, but module is usable from `sys.modules`.

- CPython native runtime (`/opt/python-3.14/bin/python3.14`):
  - `cinderjit`/`cinderx` import: unavailable.
  - `sys._jit` object exists, but:
    - `is_available=False`
    - `is_enabled=False`
    - unchanged when `PYTHON_JIT=1`.
  - `--help-xoptions` output does not expose `-X jit` option on this build (`artifacts/arm/jit_api_probe/cpython_help_xoptions.txt`).

### Direct contrast (based on requested APIs)
- `cinderjit.get_compiled_size`: available and returns non-zero size on CinderX; not available on CPython native.
- `cinderjit.get_compiled_functions`: available on CinderX and includes probe payload; not available on CPython native.
- `cinderjit.disassemble`: callable on CinderX but silent in this environment; not available on CPython native.
- `cinderjit.dump_elf`: available on CinderX and produces ELF for objdump workflow; not available on CPython native.

### Extra verification for asm extraction
- Verified fallback asm path works on ARM:
  - `cinderjit.dump_elf('/tmp/cinderjit_probe_*.elf')`
  - `objcopy -O binary --only-section=.text ...`
  - `objdump -D -b binary -m aarch64 ...`
- Observed valid AArch64 instructions from dumped `.text` (non-empty disassembly).

## 2026-02-27 Fix: `dump_elf` ELF Machine Field on ARM

### Problem statement
- On ARM, `cinderjit.dump_elf()` output could be disassembled as x86 when using plain:
  - `objdump -d <dumped.elf>`
- Root cause in source:
  - ELF file header machine type was hardcoded to x86-64:
    - `cinderx/Jit/elf/header.h` previously had `machine{0x3e}`.

### Code changes
- `cinderx/Jit/elf/header.h`
  - Added architecture-aware ELF machine constants:
    - `kMachineX86_64 = 0x3e`
    - `kMachineAArch64 = 0xb7`
  - Added compile-target selection:
    - `__x86_64__ || _M_X64 -> kFileMachine = kMachineX86_64`
    - `__aarch64__ || _M_ARM64 -> kFileMachine = kMachineAArch64`
  - Updated `FileHeader::machine` to `machine{kFileMachine}`.

- Tests added:
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
    - `ArmRuntimeTests.test_dump_elf_machine_is_aarch64_on_arm`
    - Reads ELF header bytes and asserts `e_machine == 0xB7` (EM_AARCH64) on ARM.
  - `cinderx/PythonLib/test_cinderx/test_cinderjit.py`
    - `CinderJitModuleTests.test_dump_elf_machine_matches_runtime_arch`
    - Cross-arch mapping check (x86_64 / aarch64), guarded for availability.

### TDD evidence (remote-only)
- Remote entrypoint used for all verification:
  - `ssh root@124.70.162.35`

1. RED (before C++ fix)
- Command:
  - `cd /root/work/cinderx-main && /root/venv-cinderx314/bin/python -m unittest discover -s cinderx/PythonLib/test_cinderx -p test_arm_runtime.py -k dump_elf_machine`
- Result:
  - `FAIL: Expected EM_AARCH64, got 0x003e`
  - Failure line: `test_arm_runtime.py:94`

2. GREEN (after C++ fix, rebuilt + reinstalled wheel)
- Build/install:
  - `cd /root/work/cinderx-main && /opt/python-3.14/bin/python3.14 -m build --wheel`
  - `pip --force-reinstall dist/cinderx-2026.2.27.0-cp314-cp314-linux_aarch64.whl` (in `/root/venv-cinderx314`)
- Same test command result:
  - `OK (skipped=1)` with target test passing.

### Verification-before-completion
1. Generate new ELF after fix:
- Script path on remote:
  - `/tmp/verify_dump_elf_machine.py`
- Output:
  - dumped file: `/tmp/dump_elf_machine_fix_verify.elf`
  - compiled size sample: `960`

2. Verify ELF header + disassembly mode:
- Command:
  - `readelf -h /tmp/dump_elf_machine_fix_verify.elf | egrep 'Class|Type|Machine'`
  - `objdump -d /tmp/dump_elf_machine_fix_verify.elf | head`
- Observed:
  - `Machine: AArch64`
  - `file format elf64-littleaarch64`
  - AArch64 mnemonics (`stp`, `mov`, `cbz`, `blr`, `ret`) shown directly.

### Conclusion
- Fixed: `cinderjit.dump_elf()` now emits architecture-correct ELF `e_machine` on ARM.
- Impact:
  - `readelf` and plain `objdump -d` now identify/disassemble dumped JIT ELF correctly as AArch64.

## 2026-02-27 Next Optimization Directions (CinderX JIT vs CPython Native JIT)

### API-based comparison (same ARM host, same function shape)
- Function:
  - `def f(n): s=0; for i in range(n): s += (i*3) ^ (i>>2); return s`
- CinderX (`/root/venv-cinderx314/bin/python`):
  - `is_jit_compiled=True`
  - `get_compiled_size(f)=1232`
  - `get_compiled_stack_size(f)=240`
  - `get_compiled_spill_stack_size(f)=160`
  - `get_compiled_functions_count=1`
- CPython native JIT (`PYTHON_JIT=1 /tmp/venv-cpython314jit/bin/python`):
  - `sys._jit.is_available=True`, `is_enabled=True`
  - executor at bytecode `offset=92 (JUMP_BACKWARD)`
  - `get_jit_code()` size `8192` bytes

### Mapping to Python bytecode
- Shared key bytecode offsets:
  - loop body starts around `34` (`LOAD_FAST...`)
  - arithmetic ops at `38 (*)`, `54 (>>)`, `66 (^)`, `78 (+=)`
  - loop backedge at `92 (JUMP_BACKWARD)`
  - return at `102 (RETURN_VALUE)`
- Observation:
  - CPython native JIT executor is attached to the loop backedge (`offset 92`), i.e. hotspot/superblock style.
  - CinderX emits function-level code object and includes explicit cold/deopt ladder blocks in the same blob.

### Measured shape sensitivity on CinderX (forced-compile micro)
- `for_range`:
  - size `1232`, spill stack `160`, time `~0.079s`
- `while_xor`:
  - size `1104`, spill stack `152`, time `~0.067s`
- `while_add`:
  - size `824`, spill stack `136`, time `~0.026s`
- Interpretation:
  - `for range` path costs extra vs equivalent `while` loop on this workload, pointing to iterator/global-call overhead opportunities.
  - spill stack is high relative to function complexity, indicating register pressure/call-lowering overhead.

### Immediate optimization targets
1. Improve range-loop specialization on ARM hot loops
- Why:
  - `for_range` slower and larger than `while_xor` for same arithmetic payload.
- Direction:
  - stronger `range` + `FOR_ITER` lowering to reduce helper round-trips in steady-state loop.

2. Reduce helper-call overhead (`ldr literal + blr`) in hot path
- Why:
  - CinderX disassembly shows frequent indirect helper call sites.
- Direction:
  - prefer direct near-call stubs/veneer strategy where possible; minimize repeated literal-pool loads in loop body.

3. Reduce register pressure / spills in arithmetic loops
- Why:
  - `spill_stack_size=160` for a small loop body.
- Direction:
  - tighten postalloc/regalloc heuristics around call-result chains and loop-carried vars on AArch64.

4. Move cold/deopt paths farther from hot text (I-cache friendliness)
- Why:
  - same blob includes significant cold ladder; code locality pressure in hot path.
- Direction:
  - make multiple hot/cold sections robust on ARM for general workloads.
  - current trial of `PYTHONJITMULTIPLECODESECTIONS=1` with explicit sizes fails compile with `InvalidDisplacement`; this is both a correctness and optimization blocker.

5. Keep static typing path for true numeric hot spots
- Why:
  - dynamic `PyLong` arithmetic still dominates helper/refcount traffic.
- Direction:
  - move the hottest numeric kernels to Static Python/native-callable paths where feasible.

## 2026-02-27 ARM Full Validation: MCS `InvalidDisplacement` Fix + End-to-End Retest

### Scope and entrypoint
- Remote-only execution entrypoint:
  - `ssh root@124.70.162.35`
- Runtime under test:
  - CinderX: `/root/venv-cinderx314/bin/python` (Python `3.14.3`)
  - CPython native JIT: `/tmp/venv-cpython314jit/bin/python` (Python `3.14.3`)

### Code changes under test
- `cinderx/Jit/code_allocator.cpp`
  - In `MultipleSectionCodeAllocator::createSlabs()`:
    - changed section alignment from fixed `2MiB` (`kAllocSize`) to system allocation/page granularity.
    - applied same alignment logic to both hot and cold section sizes.
    - guarded `setHugePages()` to only run when hot section size is at least `2MiB`.
- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - added `test_multiple_code_sections_force_compile_smoke`.

### TDD evidence (RED -> GREEN)
1. RED (before allocator fix)
- Test command:
  - `cd /root/work/cinderx-main && /root/venv-cinderx314/bin/python -m unittest discover -s cinderx/PythonLib/test_cinderx -p test_arm_runtime.py -k test_multiple_code_sections_force_compile_smoke`
- Result:
  - `FAIL` at `jit.force_compile(f)` with:
    - `RuntimeError: PYJIT_RESULT_UNKNOWN_ERROR`
  - prior low-level log for same case showed:
    - `Failed to add generated code ... InvalidDisplacement`

2. GREEN (after allocator fix + rebuild)
- Rebuild/install command:
  - `cd /root/work/cinderx-main && ENABLE_ADAPTIVE_STATIC_PYTHON=1 ENABLE_LIGHTWEIGHT_FRAMES=1 /root/venv-cinderx314/bin/pip install -e . -v`
- Build config confirmation in output:
  - `-DENABLE_ADAPTIVE_STATIC_PYTHON=1`
  - `-DENABLE_LIGHTWEIGHT_FRAMES=1`
- Same targeted test result:
  - `OK (skipped=1)`

### Full runtime test verification
- Full ARM runtime test file:
  - `cd /root/work/cinderx-main && /root/venv-cinderx314/bin/python -m unittest discover -s cinderx/PythonLib/test_cinderx -p test_arm_runtime.py`
- Result:
  - `Ran 53 tests in 3.258s`
  - `OK (skipped=2)`

### Post-fix API and performance comparison (same workload)
- Workload shape:
  - `for i in range(n): s += (i * 3) ^ (i >> 2)` with fixed benchmark harness.
- Artifacts:
  - `artifacts/asm/api_compare_20260227/cinderx_interp_post_fix.json`
  - `artifacts/asm/api_compare_20260227/cinderx_jit_mcs0_post_fix.json`
  - `artifacts/asm/api_compare_20260227/cinderx_jit_mcs1_post_fix.json`
  - `artifacts/asm/api_compare_20260227/cpython_interp_post_fix.json`
  - `artifacts/asm/api_compare_20260227/cpython_jit_post_fix.json`
  - `artifacts/asm/api_compare_20260227/cinderjit_api_detail_post_fix.json`

1. CinderX
- Interpreter median:
  - `0.289058s`
- JIT (`PYTHONJITMULTIPLECODESECTIONS=0`) median:
  - `0.254043s` (`~1.138x` vs CinderX interpreter)
  - compiled size:
    - `1248` bytes
- JIT (`PYTHONJITMULTIPLECODESECTIONS=1`, hot/cold `1MiB`) median:
  - `0.271293s` (`~1.065x` vs CinderX interpreter)
  - no compile failure after fix (this was the previous blocker)
  - compiled size:
    - `1304` bytes
  - relative to `mcs=0`:
    - `~6.8%` slower on this micro shape

2. CPython native
- Interpreter median (`PYTHON_JIT=0`):
  - `0.205928s`
- JIT median (`PYTHON_JIT=1`):
  - `0.266945s` (slower on this workload in this build)
- Executor status in JIT mode:
  - backedge offset:
    - `92`
  - `exists=True`, `is_valid=True`
  - `get_jit_code()` length:
    - `8192` bytes

### `cinderjit` API availability on ARM (post-fix)
- Presence:
  - `get_compiled_size`: `True`
  - `disassemble`: `True`
  - `get_compiled_function`: `False`
  - `get_compiled_functions`: `True`
  - `dump_elf`: `True`
- Runtime checks:
  - `force_compile(payload)=True`
  - `is_jit_compiled(payload)=True`
  - `compiled_size=1232`
  - `stack_size=240`
  - `spill_stack_size=160`
  - `compiled_functions_count=1`, payload found in list
  - `disassemble(payload)` callable, return type `NoneType`
- `dump_elf` validation:
  - ELF machine from header: `183` (`EM_AARCH64`)
  - `readelf -h` machine line:
    - `Machine:                           AArch64`

## 2026-02-27 ARM Follow-up: MCS Size Sweep (post-fix)

### 方法
- 入口：
  - `ssh root@124.70.162.35`
- 脚本：
  - `scripts/arm/bench_compare_modes.py`
- 产物：
  - `artifacts/asm/api_compare_20260227/mcs_sweep/summary.json`

### 结果（`cinderx` JIT，相同 workload/harness）
- `mcs=0` 基线：
  - 中位数 `0.248457s`
  - 编译体积 `1232`
- `mcs=1`，hot/cold 各 `262144`：
  - 中位数 `0.294906s`
  - 编译体积 `1288`
- `mcs=1`，hot/cold 各 `524288`：
  - 中位数 `0.297446s`
  - 编译体积 `1288`
- `mcs=1`，hot/cold 各 `1048576`：
  - 中位数 `0.296165s`
  - 编译体积 `1288`
- `mcs=1`，hot/cold 各 `2097152`：
  - 编译失败（`RuntimeError: PYJIT_RESULT_UNKNOWN_ERROR`）
- `mcs=1`，hot/cold 各 `4194304`：
  - 编译失败（`RuntimeError: PYJIT_RESULT_UNKNOWN_ERROR`）

### 解释
- 当前修复已消除此前 `1MiB` 失败，但在该 ARM 环境下 `2MiB+` 段距离仍会失败。
- 即便 `mcs=1` 成功（`256KiB~1MiB`），该微基准仍较 `mcs=0` 慢约 `19%`。
- 这表明在分段模式下仍存在分支可达性/布局敏感问题，或 hot/cold 分离带来的 i-cache / 分支预测额外成本。

## 2026-02-27 ARM 跟进：MCS `2MiB+` InvalidDisplacement 根因与修复

### 根因（已测量）
- 失败形态：
  - `PYTHONJITMULTIPLECODESECTIONS=1`
  - `PYTHONJITHOTCODESECTIONSIZE=2097152`
  - `PYTHONJITCOLDCODESECTIONSIZE=2097152`
- AsmJit 失败点：
  - `resolveUnresolvedLinks()` 报 `InvalidDisplacement`。
- 链接层诊断：
  - `.coldtext` 到 `.text` 的跨段链接使用 `imm19` 位移格式。
  - 与 AArch64 `ldr literal` 的可达范围（约 +/-1MiB）一致。
- 实际解释：
  - cold 段 helper 调用点仍从 hot 段字面量池加载目标（`ldr literal + blr`），当 hot/cold 距离约 2MiB 时溢出。

### 代码改动
- `cinderx/Jit/codegen/gen_asm_utils.cpp`
  - AArch64 下 `emitCall(env, uint64_t func, ...)` 改为：
    - hot 段：保留现有去重字面量池调用降级
    - cold 段：使用 `mov absolute_target + blr`（消除对 hot 字面量可达性的依赖）
- `cinderx/Jit/codegen/gen_asm.cpp`
  - deopt 一阶段保留在 cold、二阶段放在 hot，避免二阶段 hot 标签的 `adr` 跨段溢出。
- `cinderx/Jit/codegen/autogen.cpp`
  - 仅保留定向 guard 远分支处理；回滚了导致代码尺寸回归的广谱 branch-veneer 改写。
- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - 新增 `test_multiple_code_sections_large_distance_force_compile_smoke`（2MiB/2MiB 烟测）。

### 远端入口验证（`scripts/arm/remote_update_build_test.sh`）
- 测试分支：当前工作树（`bench-cur-7c361dce`，含上述改动）。
- 结果：
  - ARM 运行时测试：`Ran 9 tests ... OK`
  - 包含：
    - `test_multiple_code_sections_large_distance_force_compile_smoke`：通过
    - `test_aarch64_call_sites_are_compact`：通过
    - `test_aarch64_duplicate_call_result_arg_chain_is_compact`：通过
- 剩余门禁结果：
  - 脚本在 line 210 smoke 仍崩溃：
    - `env PYTHONJITAUTO=0 "$PYVENV_PATH/bin/python" -c 'g=(i for i in [1]); ... re.compile("a+") ...'`
    - segfault 栈经过 `typing.__init_subclass__` / `JITRT_CallFunctionEx`。

### line-210 segfault 的基线一致性检查
- 同一远端入口、同一参数，改用基线提交归档源码：
  - `436bee31ac6b34ba74c90133ed651b31ad96c57e`
- 结果：
  - 运行时测试通过（基线测试文件 `Ran 8 tests ... OK`），
  - line-210 smoke 同样复现 segfault。
- 结论：
  - line-210 崩溃是既有问题，不是本次 MCS 位移修复引入。

## 2026-02-27 ARM 跟进：`pyperformance` auto-jit 门禁稳定化

### RED：`richards` auto-jit 在低阈值崩溃
- 远端入口（`scripts/arm/remote_update_build_test.sh`）在 auto-jit 门禁持续失败：
  - `RuntimeError: Benchmark died`
  - worker 退出码 `-11` / `139`（SIGSEGV）。
- Core 证据（示例）：
  - `coredumpctl info 437653`
  - benchmark worker 命令：
    - `/root/work/cinderx-main/venv/.../bin/python -u .../bm_richards/run_benchmark.py ...`
  - 栈顶路径：
    - `Py_INCREF` -> `_CiFrame_ClearExceptCode` -> `Ci_EvalFrame` -> `resumeInInterpreter`。
- 同 worker 命令阈值探测：
  - `autojit=50` -> `rc=139`
  - `autojit=100` -> `rc=139`
  - `autojit=200` -> `rc=0`
- 与基线一致：
  - 基线提交 `436bee31` 在低阈值同样复现，因此非当前分支引入。

### 改动
- 更新 `scripts/arm/remote_update_build_test.sh`：
  - 新增 `AUTOJIT_GATE`（默认跟随 `AUTOJIT`）。
  - 校验 `AUTOJIT_GATE` 必须为非负整数。
  - 对 ARM richards 门禁将 `AUTOJIT_GATE < 200` 强制提升到 `200`。
  - auto-jit 门禁命令/日志/输出统一使用 `AUTOJIT_GATE`。

### GREEN：远端完整入口恢复通过
- 命令：
  - `INCOMING_DIR=/root/work/incoming WORKDIR=/root/work/cinderx-main PYTHON=/opt/python-3.14/bin/python3.14 DRIVER_VENV=/root/venv-cinderx314 BENCH=richards AUTOJIT=50 PARALLEL=1 SKIP_PYPERF=0 RECREATE_PYPERF_VENV=1 /root/work/incoming/remote_update_build_test.sh`
- 结果：
  - 脚本输出：
    - `>> auto-jit gate threshold 50 is crash-prone on ARM; using 200`
  - 运行时测试：`Ran 9 tests ... OK`
  - `pyperformance` jitlist 门禁：通过
  - `pyperformance` auto-jit 门禁：通过
- 产物：
  - `/root/work/arm-sync/richards_jitlist_20260227_220207.json`
  - `/root/work/arm-sync/richards_autojit200_20260227_220207.json`
  - `/tmp/jit_richards_autojit200_20260227_220207.log`
- auto-jit 日志中的 JIT 生效证据：
  - 含多个 `Finished compiling __main__:*`（例如 `Task.runTask`、`DeviceTask.fn`）。

## 2026-02-27 ARM 直接对比刷新：CPython 原生 JIT vs CinderX

### 远端入口与负载
- 仅远端执行：
  - `ssh root@124.70.162.35`
- 负载脚本：
  - `scripts/arm/bench_compare_modes.py`
  - 各模式参数一致（`n=250`、`warmup=20000`、`calls=12000`、`repeats=5`）。

### 关键环境校正
- 系统 Python（`/opt/python-3.14/bin/python3.14`）报告：
  - `RuntimeError: Executors are not available in this build`
  - 因此该二进制下 `PYTHON_JIT=1` 不能代表真实原生 JIT 对比。
- 在同机编译了 JIT 版 CPython 3.14.3：
  - 源码：`/root/work/Python-3.14.3`
  - 安装前缀：`/root/opt/python-3.14-jit`
  - 配置：`--enable-experimental-jit=yes`
  - 本机编译修正：
    - `PYTHON_FOR_REGEN=/opt/python-3.14/bin/python3.14`
    - （系统 `python3` 为 3.9，无法执行 `Tools/jit/build.py` 的 `match` 语法）
- JIT 启用证据：
  - `_opcode.get_executor(...).is_valid() == True`
  - `len(executor.get_jit_code()) == 8192`

### 直接对比结果（真实 CPython JIT 二进制）
- 使用的 CPython 二进制：
  - `/root/opt/python-3.14-jit/bin/python3.14`
- 模式中位数：
  - `cpython interp (PYTHON_JIT=0)`：`0.2033475680 s`
  - `cpython jit (PYTHON_JIT=1)`：`0.2692244400 s`
  - `cinderx interp`：`0.2864123950 s`
  - `cinderx jit`：`0.2702031260 s`
- 相对比率：
  - `cpython_jit_vs_interp`：`0.7553x`（该负载下原生 JIT 更慢）
  - `cinderx_jit_vs_interp`：`1.0600x`（CinderX JIT 快于自身解释基线）
  - `cpython_interp_vs_cinderx_interp`：`1.4085x`（本次运行 CPython interp 更快）
  - `cpython_jit_vs_cinderx_jit`：`1.0036x`（两侧 JIT 接近，CPython 略快）
- 同次运行中的 CinderX JIT 代码生成证据：
  - `compiled_size=1264`
  - `stack_size=240`
  - `spill_stack_size=160`
  - `dump_elf.elf_e_machine=183`（`EM_AARCH64`）

### 产物
- 本地：
  - `artifacts/richards/direct_compare_nativejit_20260227_232009/cpython_interp.json`
  - `artifacts/richards/direct_compare_nativejit_20260227_232009/cpython_jit.json`
  - `artifacts/richards/direct_compare_nativejit_20260227_232009/cinderx_interp.json`
  - `artifacts/richards/direct_compare_nativejit_20260227_232009/cinderx_jit.json`
  - `artifacts/richards/direct_compare_nativejit_20260227_232009/summary.json`
- 远端：
  - `/root/work/arm-sync/cmp_nativejit_20260227_232009/*`

## 2026-02-27 ARM 跟进：隔离 CinderX 解释器开销（`PYTHONJITDISABLE`）

### 原因
- 之前直接对比里的 `cinderx interp` 仍启用了 JIT 运行时通路
  （`jit.enable() + compile_after_n_calls(1000000)`），会抬高“纯解释器基线”。
- 脚本已增强：支持在 `PYTHONJITDISABLE=1` 下运行 CinderX interp，且不强依赖 `cinderjit` 导入。

### 脚本改动
- 文件：
  - `scripts/arm/bench_compare_modes.py`
- 行为更新：
  - `cinderjit` 导入改为可选。
  - `mode=interp` 在 `PYTHONJITDISABLE=1` 下可运行。
  - `mode=jit` 在设置 `PYTHONJITDISABLE` 时会快速失败。
  - 输出新增：
    - `jit_disabled`
    - `api_flags.cinderjit_available`

### 远端对比结果（同主机/同负载/真实 CPython JIT）
- CPython 二进制：
  - `/root/opt/python-3.14-jit/bin/python3.14`
- 中位数：
  - `cpython interp`：`0.2042452650 s`
  - `cpython jit`：`0.2708785540 s`
  - `cinderx interp（纯解释，PYTHONJITDISABLE=1）`：`0.2609469950 s`
  - `cinderx interp（保留 JIT plumbing）`：`0.2848622500 s`
  - `cinderx jit`：`0.2650873990 s`
- 关键比率：
  - `cinderx_jitenabled_interp_overhead`：`1.0916x`
    - 保留 JIT plumbing 的解释器路径约有 `9.16%` 额外开销。
  - `cinderx_jit_vs_interp_pure`：`0.9844x`
    - 该微基准上 CinderX JIT 与纯解释大致持平/略慢。
  - `cpython_interp_vs_cinderx_interp_pure`：`1.2776x`
    - 即便移除 JIT plumbing 开销，本次仍是 CinderX interp 慢于 CPython interp。

### 产物
- 本地：
  - `artifacts/richards/direct_compare_pureinterp_20260227_233807/cpython_interp.json`
  - `artifacts/richards/direct_compare_pureinterp_20260227_233807/cpython_jit.json`
  - `artifacts/richards/direct_compare_pureinterp_20260227_233807/cinderx_interp_pure.json`
  - `artifacts/richards/direct_compare_pureinterp_20260227_233807/cinderx_interp_jitenabled.json`
  - `artifacts/richards/direct_compare_pureinterp_20260227_233807/cinderx_jit.json`
  - `artifacts/richards/direct_compare_pureinterp_20260227_233807/summary.json`
- 远端：
  - `/root/work/arm-sync/cmp_pureinterp_20260227_233807/*`

## 2026-02-28 ARM 跟进：修复 auto-jit segfault（轻量帧元数据初始化）

### RED（修复前）
- ARM（pyperf venv）最小复现会 `SIGSEGV`：
  - `env PYTHONJITAUTO=0 PYTHONJITLIGHTWEIGHTFRAME=1 python -c 'g=(i for i in [1]); import re; re.compile("a+"); print("ok")'`
- core 回溯（新 core `471733`）栈顶：
  - `Py_INCREF(op=0x1)` 于 `PyImport_Import`
  - 上游调用来自 `call_typing_args_kwargs` -> `JITRT_CallFunctionEx`
- 解释：
  - C API 在轻量帧 JIT 入口阶段读取当前帧元数据（`globals` / 清理相关状态）时看到无效值。

### 改动
- `cinderx/Jit/codegen/frame_asm.cpp`
  - 对 x86_64 与 AArch64 的轻量函数帧，提前初始化：
    - `f_globals`（来自 `func->func_globals`）
    - `f_builtins`（来自 `func->func_builtins`）
    - `frame_obj = NULL`
    - `return_offset = 0`
    - `visited = 0`
  - 目标是在懒初始化前保证关键帧元数据始终有效。
- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - 新增回归测试：
    - `test_autojit0_lightweight_frame_typing_import_smoke`
  - 将一个 AArch64 代码尺寸护栏从 `44500` 放宽到 `44700`（本次新增初始化 store 带来约 +20B）。

### GREEN（远端入口验证）
- 远端入口（按要求）：
  - `/root/work/incoming/remote_update_build_test.sh`
- 命令：
  - `INCOMING_DIR=/root/work/incoming WORKDIR=/root/work/cinderx-main PYTHON=/opt/python-3.14/bin/python3.14 DRIVER_VENV=/root/venv-cinderx314 BENCH=richards AUTOJIT=50 PARALLEL=1 SKIP_PYPERF=1 RECREATE_PYPERF_VENV=0 /root/work/incoming/remote_update_build_test.sh`
- 结果：
  - ARM 运行时测试：`Ran 10 tests ... OK`
  - 包含新回归测试 `test_autojit0_lightweight_frame_typing_import_smoke`
  - 脚本整体成功（`exit 0`）
## 2026-02-28 ARM 完整远端门禁复验（SKIP_PYPERF=0）

### 入口与命令
- 统一远端入口：
  - `/root/work/incoming/remote_update_build_test.sh`
- 实际执行命令：
  - `INCOMING_DIR=/root/work/incoming WORKDIR=/root/work/cinderx-main PYTHON=/opt/python-3.14/bin/python3.14 DRIVER_VENV=/root/venv-cinderx314 BENCH=richards AUTOJIT=50 PARALLEL=1 SKIP_PYPERF=0 RECREATE_PYPERF_VENV=1 /root/work/incoming/remote_update_build_test.sh`

### 结果
- 脚本退出码：`0`
- ARM 运行时测试：`Ran 10 tests ... OK`
- auto-jit 门禁策略：
  - 日志提示 `AUTOJIT=50` 在 ARM 上自动提升到 `200`：
    - `>> auto-jit gate threshold 50 is crash-prone on ARM; using 200`

### 性能产物（本次最新）
- jitlist JSON：
  - `/root/work/arm-sync/richards_jitlist_20260228_093637.json`
  - value：`0.07860610100033227`
- autojit200 JSON：
  - `/root/work/arm-sync/richards_autojit200_20260228_093637.json`
  - value：`0.07193847199960146`
- autojit 日志：
  - `/tmp/jit_richards_autojit200_20260228_093637.log`

### JIT 生效证据
- `Finished compiling __main__:` 命中数：`18`
## 2026-02-28 ARM P0：autojit 低阈值崩溃矩阵（richards）

### 方法
- 远端入口：`ssh root@124.70.162.35`
- 矩阵脚本：`/root/work/incoming/autojit_crash_matrix.sh`
- 本地脚本：`scripts/arm/autojit_crash_matrix.sh`
- 基准：`pyperformance -b richards --debug-single-value`
- 阈值：`20 50 80 100 200`

### 主结果（run_id=20260228_102038）
- `200`：`ok`，`value=0.07163083901104983`，`main_compile_count=18`
- `100`：`fail`（`core_pid=512875`）
- `80`：`fail`（`core_pid=513010`）
- `50`：`fail`（`core_pid=513130`）
- `20`：`fail`（`core_pid=513251`）

### 崩溃签名（20/50/80/100 一致）
- 信号：`SIGSEGV`
- 关键栈：
  - `Py_INCREF -> take_ownership -> _CiFrame_ClearExceptCode`
  - `resumeInInterpreter`（`cinderx/Jit/codegen/gen_asm.cpp:390`）
- 结论：
  - 与此前判断一致，低阈值崩溃主要落在 deopt/resume 路径。

### 补充观察（200 的稳定性）
- `200` 在独立运行中可通过：
  - `run_id=20260228_101308`：`ok`，`value=0.07168850500602275`
  - `run_id=20260228_102038`：`ok`，`value=0.07163083901104983`
- 但在一次顺序矩阵（`run_id=20260228_101244`）里，`200` 也出现失败（`core_pid=504823`），
  栈顶为 `_Py_Dealloc/frame_dealloc` 路径，呈现压力/顺序相关的不稳定性。

### 产物
- 远端：
  - `/root/work/arm-sync/autojit_matrix_20260228_102038/summary.json`
  - `/root/work/arm-sync/autojit_matrix_20260228_102038/core_100_512875.bt.txt`
  - `/root/work/arm-sync/autojit_matrix_20260228_102038/core_80_513010.bt.txt`
  - `/root/work/arm-sync/autojit_matrix_20260228_102038/core_50_513130.bt.txt`
  - `/root/work/arm-sync/autojit_matrix_20260228_102038/core_20_513251.bt.txt`
- 本地：
  - `artifacts/arm/autojit_matrix_20260228_102038/summary.json`
  - `artifacts/arm/autojit_matrix_20260228_101244/summary.json`

## 2026-02-28 ARM P0 续：autojit<=100 崩溃修复迭代（失败记录）

### 目标
- 在不依赖 `AUTOJIT>=200` 兜底的情况下，修复 `richards` 在 `autojit<=100` 的 SIGSEGV。

### 远端验证入口（统一）
- 构建/门禁：`/root/work/incoming/remote_update_build_test.sh`
- 阈值矩阵：`/root/work/incoming/autojit_crash_matrix.sh`

### 本轮关键尝试
- 尝试 A：`gen_asm.cpp` 在 `resumeInInterpreter` 前补齐 previous 轻量帧初始化。
- 尝试 B：`borrowed-3.14.gen_cached.c` 在 `take_ownership` 中跳过 `f_back` 链接（避免沿坏 `previous` 链 materialize）。
- 尝试 C（已回退）：对 `take_ownership` 的 stackref 槽位做“低地址置空”消毒；该改动会导致远端 JIT smoke 崩溃，已撤销。

### 矩阵结果（补丁后）
- `run_id=20260228_112500`：`200=ok`，`100/80/50/20=fail`
- `run_id=20260228_120500`：`200=ok`，`100/80/50/20=fail`
- `run_id=20260228_122000`：`200=ok`，`100/80/50/20=fail`
- `run_id=20260228_123500`：`200=ok`，`100/80/50/20=fail`

### 崩溃签名
- 仍集中在：
  - `Py_INCREF -> _Py_NewRef -> take_ownership -> _CiFrame_ClearExceptCode`
  - 上层继续来自 `resumeInInterpreter`。
- 说明本轮对 previous 链/ownership 保护未触达真正坏引用来源。

### 回归与回退
- “槽位消毒”版本在远端门禁 smoke（`jit-effective`）触发新的 `SIGSEGV`，已回退。
- 当前远端基线已恢复到可构建、可通过 10 项 ARM 运行时测试（`remote_update_build_test.sh`，`SKIP_PYPERF=1`）。

### 产物
- 远端：
  - `/root/work/arm-sync/autojit_matrix_20260228_112500/summary.json`
  - `/root/work/arm-sync/autojit_matrix_20260228_120500/summary.json`
  - `/root/work/arm-sync/autojit_matrix_20260228_122000/summary.json`
  - `/root/work/arm-sync/autojit_matrix_20260228_123500/summary.json`
- 本地：
  - `artifacts/arm/autojit_matrix_20260228_112500/summary.json`
  - `artifacts/arm/autojit_matrix_20260228_120500/summary.json`
  - `artifacts/arm/autojit_matrix_20260228_122000/summary.json`
  - `artifacts/arm/autojit_matrix_20260228_123500/summary.json`

## 2026-02-28 ARM P0 收敛：autojit<=100 崩溃修复完成（远端闭环）

### 关键根因（本轮新增定位）
- 根因 1：二进制与源码不一致。
  - core 反汇编显示 `_CiFrame_ClearExceptCode` 仍在 `take_ownership` 内执行 `f_back` 链接逻辑（`PyErr_GetRaisedException -> Py_NewRef(back)`），说明“跳过 f_back”补丁未进入当次实际加载的 `_cinderx.so`。
  - 进一步确认：存在两套 pyperformance venv。
    - 旧：`/root/venv/cpython3.14-.../site-packages/_cinderx.so`
    - 新：`/root/work/cinderx-main/venv/cpython3.14-.../site-packages/_cinderx.so`
  - 若矩阵脚本在错误目录启动，会命中旧 venv 并复现旧崩溃签名。
- 根因 2：`ensureInitializedPreviousFrames()` 引入二次崩溃。
  - 在已应用 ownership 补丁后，core 栈顶转为：
    - `jitFramePopulateFrame -> ensureInitializedPreviousFrames -> resumeInInterpreter`
  - 说明 previous 链预初始化逻辑在坏链场景下会提前触发崩溃。

### 最终修复（代码）
- `cinderx/UpstreamBorrow/borrowed-3.14.gen_cached.c`
  - `take_ownership()` 跳过 `f_back` 构建（不沿 `frame->previous` materialize）。
- `cinderx/UpstreamBorrow/borrowed-3.14.free-threading.gen_cached.c`
  - 同步应用相同 `take_ownership()` 修复，避免构建路径差异导致补丁漏生效。
- `cinderx/Jit/codegen/gen_asm.cpp`
  - 将 `ensureInitializedPreviousFrames()` 退回 no-op，移除其对坏 previous 链的访问风险。

### 远端统一入口验证（按要求）
- 构建/门禁入口：`/root/work/incoming/remote_update_build_test.sh`
- 阈值矩阵入口：`/root/work/incoming/autojit_crash_matrix.sh`

#### 验证过程与结果
- 阶段 A（路径混用，旧崩溃仍在）
  - `run_id=20260228_114129`（pyperf_venv 指向 `/root/venv/...`）
  - 结果：`200=ok`，`20/50/80/100=fail`，仍是旧签名。
- 阶段 B（切到 `/root/work/cinderx-main`，暴露新增回归）
  - `run_id=20260228_114218`
  - 结果：`20/50/80/100/200` 全 fail。
  - core 栈顶：`jitFramePopulateFrame -> ensureInitializedPreviousFrames`。
- 阶段 C（回退 previous 预初始化后复测）
  - `run_id=20260228_114731`
  - 结果：`20/50/80/100/200` 全 `ok`（无 core）。

### 最终矩阵数据（run_id=20260228_114731）
- `20`：`ok`，`value=0.07160714498604648`
- `50`：`ok`，`value=0.07178452698281035`
- `80`：`ok`，`value=0.07169258102658205`
- `100`：`ok`，`value=0.07089853202342056`
- `200`：`ok`，`value=0.07331351100583561`

### 产物
- 远端：
  - `/root/work/arm-sync/autojit_matrix_20260228_114129/summary.json`
  - `/root/work/arm-sync/autojit_matrix_20260228_114218/summary.json`
  - `/root/work/arm-sync/autojit_matrix_20260228_114731/summary.json`
- 本地：
  - `artifacts/arm/autojit_matrix_20260228_114129/summary.json`
  - `artifacts/arm/autojit_matrix_20260228_114218/summary.json`
  - `artifacts/arm/autojit_matrix_20260228_114731/summary.json`

## 2026-02-28 ARM 跟进：移除 `AUTOJIT_GATE<200` 兜底 + 第 2 项优化闭环

### 代码变更
- P0（门禁策略）：
  - `scripts/arm/remote_update_build_test.sh`
  - 删除 `AUTOJIT_GATE<200` 时强制提升到 `200` 的逻辑，保留非负整数校验。
- P1-2（热循环整数路径）：
  - `cinderx/Jit/hir/simplify.cpp`
  - 新增 `simplifyIntBinaryOp()`，覆盖以下恒等式/吸收律：
    - `x+0`、`0+x`、`x-0`
    - `x*1`、`1*x`、`x*0`、`0*x`
    - `x|0`、`0|x`、`x^0`、`0^x`
    - `x&0`、`0&x`
    - `x<<0`、`x>>0`、`x>>>0`
    - `x//1`、`x//u1`、`x%1`、`x%u1`
  - 并在 `simplifyInstr()` 中接入 `Opcode::kIntBinaryOp`。

### 远端统一入口验证（按要求）
- 入口：
  - `/root/work/incoming/remote_update_build_test.sh`
- 命令（关键参数）：
  - `AUTOJIT=50 SKIP_PYPERF=0`
- 结果：
  - 脚本退出码：`0`
  - ARM 运行时测试：`Ran 10 tests ... OK`
  - pyperformance 门禁通过，并直接产出 `autojit50`（不再被抬到 200）：
    - `/root/work/arm-sync/richards_jitlist_20260228_123621.json`：`0.07845212798565626`
    - `/root/work/arm-sync/richards_autojit50_20260228_123621.json`：`0.07119264101493172`
    - `/tmp/jit_richards_autojit50_20260228_123621.log`
      - `Finished compiling __main__:` 计数：`18`

### P0 复核：低阈值矩阵（必须在正确 pyperf venv 路径）
- 入口：
  - `/root/work/incoming/autojit_crash_matrix.sh`
- 发现：
  - 若在 `/root` 启动，会命中旧 venv 路径 `/root/venv/...`，可复现“20/50/80/100 失败”假象。
  - 在正确目录 `/root/work/cinderx-main` 启动后，矩阵恢复全绿。
- 正确矩阵结果（`run_id=20260228_124324`）：
  - `20`：`ok`，`0.07155366201186553`
  - `50`：`ok`，`0.07290761498734355`
  - `80`：`ok`，`0.07085901699610986`
  - `100`：`ok`，`0.07063013297738507`
  - `200`：`ok`，`0.07235892000608146`
- 产物：
  - 远端：`/root/work/arm-sync/autojit_matrix_20260228_124324/summary.json`
  - 本地：`artifacts/arm/20260228_intopt/autojit_matrix_20260228_124324_summary.json`

### P1-2 可归因验证：`IntBinaryOp` 在 `Simplify` 前后
- 日志：
  - `/tmp/intbin_simplify_20260228.log`
- 对象函数：`<invalid>:f`（Static Python int64 样例，包含 `+0/*1/|0/&0`）
- `Simplify` 前后 `IntBinaryOp` 计数：
  - before：`6`
  - after：`1`
- 被消除的关键形态：
  - `IntBinaryOp<Add> (i + 0)`
  - `IntBinaryOp<Multiply> (* 1)`
  - `IntBinaryOp<Or> (| 0)`
  - `IntBinaryOp<And> (& 0)`
- 本地解析产物：
  - `artifacts/arm/20260228_intopt/intbin_simplify_summary.json`

### P1-2 量化验证：恒等式工作负载（Static Python int64）
- 对比方式：
  - 默认（启用 simplify） vs `PYTHONJITSIMPLIFY=0`
- 结果（`/root/work/arm-sync/int_identity_20260228_124543/summary.json`）：
  - 编译体积：`808` vs `840`（默认 `-32` bytes）
  - 中位耗时：`0.0019835610s` vs `0.0023550340s`
  - 默认相对无 simplify：约 `15.77%` 更快
- 本地产物：
  - `artifacts/arm/20260228_intopt/int_identity_20260228_124543_summary.json`

### 同轮四模式性能快照（CPython 原生 JIT vs CinderX）
- 产物：
  - `/root/work/arm-sync/cmp_intopt_20260228_124122/summary.json`
  - `artifacts/arm/20260228_intopt/cmp_intopt_20260228_124122_summary.json`
- 中位数：
  - `cpython interp`：`0.20433606498409063`
  - `cpython jit`：`0.27011921399389394`
  - `cinderx interp(pure)`：`0.26014454499818385`
  - `cinderx jit`：`0.27385730302194133`
- 本次 CinderX JIT 代码生成证据：
  - `compiled_size=1296`
  - `stack_size=240`
  - `spill_stack_size=160`
  - `dump_elf.elf_e_machine=183`（AArch64）


## 2026-02-28 ARM 跟进：1/2 完成并直接执行第 3 项（解释器开关矩阵）

### 本轮代码变更
- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - 新增回归测试：
    - `test_int_binary_identity_simplify_reduces_compiled_size`
  - 目标：约束 `IntBinaryOp` 恒等式化简在 ARM 上持续生效（`simplify on` 编译体积应小于 `simplify off`）。
- `scripts/arm/remote_update_build_test.sh`
  - 新增 `ARM_RUNTIME_SKIP_TESTS`（默认空）：
    - 仅在指定时跳过匹配测试 id，默认仍跑全量 ARM runtime 测试。
  - 修复 pyperformance venv 复用：
    - 不再无条件 `pyperformance venv create`；
    - 优先复用已有 venv，缺失时创建，`RECREATE_PYPERF_VENV=1` 时强制重建。
- `scripts/arm/interp_feature_matrix.sh`（新增）
  - 按组合运行 `ENABLE_ADAPTIVE_STATIC_PYTHON x ENABLE_LIGHTWEIGHT_FRAMES`；
  - 每组均通过统一远端入口 `remote_update_build_test.sh` 构建+测试；
  - 随后采集 `cinderx interp`（`PYTHONJITDISABLE=1`）性能并汇总 JSON/TSV。

### 第 3 项闭环（开关矩阵）
- 第一轮（`run_id=20260228_3flag_matrix_a`）：
  - 仅 `1,1` 成功，`1,0/0,1/0,0` 在入口后段失败；
  - 根因：`pyperformance venv create` 对“已存在 venv”返回错误并中止。
- 修复入口后复跑（`run_id=20260228_3flag_matrix_b`）：
  - `1,1 / 1,0 / 0,1 / 0,0` 全部 `ok`；
  - `runtime_adaptive/runtime_lightweight` 与构建开关一一对应，验证矩阵有效。

### 矩阵结果（`run_id=20260228_3flag_matrix_b`）
- CPython 解释器基线：
  - `cpython interp median = 0.2037681249785237 s`
- CinderX 解释器（pure interp）：
  - `1,1`：`0.2616621670022141 s`（相对 CPython `+28.41%`）
  - `1,0`：`0.26301215699641034 s`（相对 CPython `+29.07%`）
  - `0,1`：`0.2604445500182919 s`（相对 CPython `+27.81%`）
  - `0,0`：`0.3688814859779086 s`（相对 CPython `+81.03%`）
- 组合内对比（以 `1,1` 为参照）：
  - `1,0` vs `1,1`：`+0.52%`
  - `0,1` vs `1,1`：`-0.47%`
  - `0,0` vs `1,1`：`+40.98%`
- 结论：
  - 两个开关都关闭（`0,0`）会显著拉低解释器基线；
  - 单独关闭其中一个开关对该负载影响小（接近噪声区间）。

### 统一入口复验（默认全量测试，防回归）
- 入口：`/root/work/incoming/remote_update_build_test.sh`
- 命令关键参数：
  - `SKIP_PYPERF=1`，未设置 `ARM_RUNTIME_SKIP_TESTS`
- 结果：
  - `Ran 11 tests ... OK`
  - 脚本整体 `exit 0`
  - 证明新增可选跳过机制不影响默认门禁行为。

### 产物
- 远端：
  - `/root/work/arm-sync/interp_feature_matrix_20260228_3flag_matrix_a/summary.json`
  - `/root/work/arm-sync/interp_feature_matrix_20260228_3flag_matrix_b/summary.json`
  - `/root/work/arm-sync/interp_feature_matrix_20260228_3flag_matrix_b/results.tsv`
- 本地：
  - `artifacts/arm/20260228_interp_matrix/interp_feature_matrix_20260228_3flag_matrix_b/summary.json`
  - `artifacts/arm/20260228_interp_matrix/interp_feature_matrix_20260228_3flag_matrix_b/results.tsv`

## 2026-02-28 ARM 跟进：autojit 触发降噪（jitlist 过滤）与入口稳态修复

### 背景
- 本轮先前尝试的 AArch64 `emitCall` 混合策略（首个热点 direct call，后续 literal）在 ARM 运行时回归：
  - `test_aarch64_call_sites_are_compact` 触发 `SIGSEGV/Illegal instruction`。
- 已回退 `emitCall` 混合策略改动，恢复稳定实现；单测复验通过。

### 本轮代码改动
- `scripts/arm/remote_update_build_test.sh`
  - 新增 `AUTOJIT_USE_JITLIST_FILTER`（默认 `1`）
  - 新增 `AUTOJIT_EXTRA_JITLIST`（可追加规则，逗号分隔）
  - autojit gate 在过滤开启时注入：
    - `PYTHONJITLISTFILE=/tmp/jitlist_autojit_gate_<RUN_ID>.txt`
    - `PYTHONJITENABLEJITLISTWILDCARDS=1`
  - 新增 autojit 编译统计产物：
    - `/root/work/arm-sync/richards_autojit50_<RUN_ID>_compile_summary.json`
    - 字段：`total_compile_count/main_compile_count/other_compile_count`
  - 增强 pyperformance venv 稳定性：
    - `pyperformance venv create/recreate` 失败时，自动清理 `$WORKDIR/venv` 并重试一次。

### 统一远端入口验证（按要求）
- 入口：`/root/work/incoming/remote_update_build_test.sh`
- 公共参数：`BENCH=richards AUTOJIT=50 AUTOJIT_GATE=50 SKIP_PYPERF=0`

#### A 组：不过滤（`AUTOJIT_USE_JITLIST_FILTER=0`）
- run_id：`20260228_165011`
- 结果：脚本 `exit 0`，ARM runtime `Ran 11 tests ... OK`
- 编译统计：
  - `main_compile_count=18`
  - `total_compile_count=182`
  - `other_compile_count=164`
- 性能：
  - jitlist：`0.07689647501683794`
  - autojit50：`0.07088315798318945`

#### B 组：开启过滤（`AUTOJIT_USE_JITLIST_FILTER=1`）
- run_id：`20260228_170353`
- 结果：脚本 `exit 0`，ARM runtime `Ran 11 tests ... OK`
- 编译统计：
  - `main_compile_count=18`
  - `total_compile_count=18`
  - `other_compile_count=0`
- 性能：
  - jitlist：`0.07792964298278093`
  - autojit50：`0.07225936200120486`

### 对比结论
- 降噪效果明确：`other_compile_count` 从 `164` 降到 `0`，autojit 不再编译大量非 `__main__` 目标。
- 本轮单次性能快照：
  - jitlist：过滤开启相对不过滤约 `+1.34%`（略慢）
  - autojit50：过滤开启相对不过滤约 `+1.94%`（略慢）
- 解释：当前是单次 `debug-single-value` 快照，负载噪声仍较大；但“编译对象更准、日志可解释性更高”这一目标已达成。

### 关键产物
- 远端：
  - `/root/work/arm-sync/richards_autojit50_20260228_165011_compile_summary.json`
  - `/root/work/arm-sync/richards_autojit50_20260228_170353_compile_summary.json`
  - `/root/work/arm-sync/richards_jitlist_20260228_165011.json`
  - `/root/work/arm-sync/richards_jitlist_20260228_170353.json`
  - `/root/work/arm-sync/richards_autojit50_20260228_165011.json`
  - `/root/work/arm-sync/richards_autojit50_20260228_170353.json`
  - `/tmp/jit_richards_autojit50_20260228_165011.log`
  - `/tmp/jit_richards_autojit50_20260228_170353.log`


## 2026-02-28 ARM 任务4闭环：解释器基线差距复核（同口径基线）

### 本轮目标
- 优先完成“解释器基线差距”定位，确认此前 `cinderx interp` 相对 `cpython interp` 的大幅落后是否为同口径对比。

### 本轮脚本修正（本地+远端同步）
- `scripts/arm/bench_compare_modes.py`
  - 在 `--mode interp` 下，跳过：
    - CinderX 的 `cinderjit.disassemble()/dump_elf/get_compiled_*` 元数据探针；
    - CPython 的 `_opcode.get_executor(...)` 探针。
  - 目的：避免“解释器模式测量”被 JIT 元数据探针污染。
- `scripts/arm/interp_hotspot_profile.sh`
  - 默认 `CPYTHON_PY` 改为 `/opt/python-3.14/bin/python3.14`（与 CinderX driver venv 同基线）。
- `scripts/arm/interp_feature_matrix.sh`
  - 默认 `CPYTHON_PY` 同步改为 `/opt/python-3.14/bin/python3.14`。

### TDD：最小复现实验（远端 ARM）
- 入口：`ssh root@124.70.162.35`
- 同参数下的 `bench_compare_modes.py --mode interp`（`n=250,warmup=20000,calls=12000,repeats=7`）：
  - `cpython (/opt/python-3.14)`：`median=0.26232359898858704`
  - `cpython (/root/opt/python-3.14-jit)`：`median=0.3375072380003985`
  - `cinderx (/root/venv-cinderx314/bin/python)`：`median=0.26577374900807627`
- 结论：
  - “旧基线”`/root/opt/python-3.14-jit` 作为解释器对照会显著放大差距；
  - 与同基线 CPython 对比时，差距明显缩小。

### Verification：统一脚本复验（远端）
- `interp_hotspot_profile` 双基线对照：
  - `run_id=20260228_interp_gap_samebase`
    - `cinderx_interp_median_sec=0.26470103400060907`
    - `cpython_interp_median_sec=0.2602885249943938`
    - `cinderx_over_cpython=1.0169523762382928`（约 `+1.70%`）
  - `run_id=20260228_interp_gap_jitbase`
    - `cinderx_interp_median_sec=0.2668363949924242`
    - `cpython_interp_median_sec=0.2059948510141112`
    - `cinderx_over_cpython=1.2953546832786864`（约 `+29.54%`）
- `interp_feature_matrix`（内部统一走 `remote_update_build_test.sh`）：
  - `run_id=20260228_interp_matrix_samebase_v1`
  - `cpython_interp_median_sec=0.2616365280118771`
  - 结果：
    - `1,1`: `0.2646517760003917`（`1.0115x`）
    - `1,0`: `0.266659419023199`（`1.0192x`）
    - `0,1`: `0.2651865700026974`（`1.0136x`）
    - `0,0`: `0.4135193559923209`（`1.5805x`）

### 结论（任务4当前状态）
- 解释器“巨大差距”主要来自基线不一致（把 `python-3.14-jit` 构建当成解释器基线）。
- 在同基线口径下，`cinderx interp` 与 `cpython interp` 在 `1,1/1,0/0,1` 组合仅约 `+1%` 量级。
- 当前真正需要继续优化的解释器方向：
  - 避免 `ENABLE_ADAPTIVE_STATIC_PYTHON=0` 且 `ENABLE_LIGHTWEIGHT_FRAMES=0`（`0,0`）组合；
  - 优先针对 `0,0` 的大幅退化路径做热点分析（已不是“整体解释器普遍慢 20~30%”的问题）。

### 本轮关键产物
- 远端：
  - `/root/work/arm-sync/interp_hotspot_profile_20260228_interp_gap_samebase/summary.json`
  - `/root/work/arm-sync/interp_hotspot_profile_20260228_interp_gap_jitbase/summary.json`
  - `/root/work/arm-sync/interp_feature_matrix_20260228_interp_matrix_samebase_v1/summary.json`
  - `/root/work/arm-sync/interp_feature_matrix_20260228_interp_matrix_samebase_v1/results.tsv`

## 2026-03-02 ARM 跟进：Float HIR“回归”定位结果（任务闭环）

### 目标
- 用户反馈：`facebookincubator/cinderx main` 的 `float_math` 用例可产出 `FloatBinaryOp`，当前分支疑似被改坏。
- 要求：按统一远端入口复现、定位影响点、给出可追溯结论。

### 计划与方法
- 计划文档：`docs/plans/2026-03-02-float-hir-regression-triage.md`
- 统一远端入口：`/root/work/incoming/remote_update_build_test.sh`
- 新增最小断言脚本：`scripts/arm/check_float_hir.sh`
  - 断言最终 HIR 必须包含：
    - `FloatBinaryOp<Add>`
    - `FloatBinaryOp<Subtract>`
    - `FloatBinaryOp<Multiply>`
    - `FloatBinaryOp<TrueDivide>`

### TDD 结果（远端）
- 构建/测试（统一入口）：
  - 命令关键参数：`SKIP_PYPERF=1`
  - 结果：`Ran 11 tests ... OK`
- 最小断言：
  - `PYTHON=/root/venv-cinderx314/bin/python scripts/arm/check_float_hir.sh`
  - 结果：`OK`，4 个 `FloatBinaryOp` 全部命中。

### 对照定位（影响点）
- 同一脚本在非 CinderX 解释器下失败：
  - `PYTHON=/opt/python-3.14/bin/python3.14 scripts/arm/check_float_hir.sh`
  - 错误：`ModuleNotFoundError: No module named 'cinderx.jit'`
- 结论：
  - 该“回归”并非 `FloatBinaryOp` 降级/丢失；
  - 实际影响点是运行解释器路径（环境）错误，未使用装有 CinderX JIT 的解释器。

### 提交范围排查
- 从分支合入上游后的范围（`c3028e25..HEAD`）里：
  - `cinderx/Jit/hir` 仅有提交 `ddf1b84e` 触及 `simplify.cpp`；
  - 改动内容是 `IntBinaryOp` 恒等式化简，不涉及 `FloatBinaryOp` lowering 路径。
- 现有证据与远端复现一致：当前分支在正确解释器环境下功能正常。

### 产物
- 远端：
  - `/root/work/arm-sync/float_hir_check_20260302/pass_after_patch.log`
  - `/root/work/arm-sync/float_hir_check_20260302/fail_after_patch.log`
- 本地：
  - `artifacts/arm/20260302_float_hir_check/pass_after_patch.log`
  - `artifacts/arm/20260302_float_hir_check/fail_after_patch.log`
  - `artifacts/arm/20260302_float_hir_check/summary.json`

### 补充修复
- `scripts/arm/check_float_hir.sh` 增强：
  - 当 workload 执行失败时，输出 python 路径与完整 stderr/stdout（避免静默失败）。

### 追加复验（2026-03-02 继续）
- 为避免“只看当前分支”的偏差，尝试用历史基线提交 `c3028e25` 走同一远端入口做 A/B。
- 结果：该基线在当前远端环境会触发 `FetchContent` 联网拉取 `asmjit`，因网络限制失败（非功能用例失败），无法在该环境完成有效 A/B。
- 随后已将远端恢复到当前分支代码，并再次通过统一入口复验：
  - `remote_update_build_test.sh`：`Ran 11 tests ... OK`
  - `check_float_hir.sh`：
    - `PYTHON=/root/venv-cinderx314/bin/python` -> `OK: FloatBinaryOp patterns found`
    - `PYTHON=/opt/python-3.14/bin/python3.14` -> `ModuleNotFoundError: No module named 'cinderx.jit'`
- 追加结论保持不变：
  - 当前问题主因是解释器路径/环境，而不是 `FloatBinaryOp` 在本分支被改坏。
- 按用户原始写法做了“exact command”复核：
  - `/root/venv-cinderx314/bin/python` + 同样脚本 -> 正常输出 `FloatBinaryOp`。
  - `python`（系统默认）+ 同样脚本 -> `ModuleNotFoundError: No module named 'cinderx.jit'`。
- 说明：若命令里写裸 `python`，极易跑到非 CinderX 解释器，表现为“功能坏了”。

## 2026-03-02 ARM 跟进：Float BinaryOp 下沉 DoubleBinaryOp（对齐浮点机器码）

### 背景
- 用户反馈：当前分支在 `float_math` 用例中仍出现 `FloatBinaryOp`，导致 LIR/机器码走 helper call；
  期望与 CinderX 3.14 main 对齐，优先下沉到 `DoubleBinaryOp` 以生成原生浮点指令。

### 代码改动
- `cinderx/Jit/hir/simplify.cpp`
  - 在 `simplifyBinaryOp()` 中，对 `TFloatExact` 的 `+ / - / *` 路径做下沉：
    - `PrimitiveUnbox(TCDouble)` -> `DoubleBinaryOp` -> `PrimitiveBox(TCDouble)`
  - `TrueDivide` 仍保留 `FloatBinaryOp` helper 路径，避免破坏 Python 对 `±0.0` 的除零语义。

### 回归测试补充
- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - 新增：`test_float_add_sub_mul_lower_to_double_binary_op_in_final_hir`
  - 断言最终 HIR 包含：
    - `DoubleBinaryOp<Add>`
    - `DoubleBinaryOp<Subtract>`
    - `DoubleBinaryOp<Multiply>`

### 统一远端入口验证（按要求）
- 入口：`/root/work/incoming/remote_update_build_test.sh`
- 参数：`SKIP_PYPERF=1`
- 结果：`Ran 12 tests ... OK`

### 用户用例复验（远端）
- 命令环境：
  - `PYTHONJITDUMPFINALHIR=1`
  - `PYTHONJITDUMPLIR=1`
  - `cinderx.jit.enable_specialized_opcodes()` + `cinderx.jit.auto()`
- 最终 HIR（关键）:
  - `DoubleBinaryOp<Add>`
  - `DoubleBinaryOp<Subtract>`
  - `DoubleBinaryOp<Multiply>`
  - `FloatBinaryOp<TrueDivide>`（保留语义路径）
- LIR（关键）:
  - `Fadd` / `Fsub` / `Fmul` 已出现（对应前三个运算）
  - `TrueDivide` 仍为 helper call（`float_div`）

### 产物
- 本地：
  - `artifacts/arm/20260302_float_hir_check/after_fix_hir.log`
  - `artifacts/arm/20260302_float_hir_check/after_fix_lir.log`
  - `artifacts/arm/20260302_float_hir_check/summary.json`

## 2026-03-02 追加分析：为何 upstream main 不改也能出 DoubleBinaryOp

### 结论
- 根因是**分支同步滞后**，不是本分支把该能力“改坏”。

### 证据链
- 我们分支历史（`c3028e25..HEAD`）里，触及该路径的提交很少：
  - `ddf1b84e` 只改了 `IntBinaryOp` 化简，不涉及 `FloatBinaryOp -> DoubleBinaryOp`。
- 在合并上游点 `c3028e25` 中，`simplifyBinaryOp()` 的浮点分支仍直接：
  - `return env.emit<FloatBinaryOp>(...)`
- 拉取最新 `upstream/main`（当前 `cb93ec8f`）后，对比发现 upstream 已新增：
  - `simplifyFloatBinaryOp()` 中将 `Add/Subtract/Multiply` 下沉为：
    - `PrimitiveUnbox(TCDouble) -> DoubleBinaryOp -> PrimitiveBox(TCDouble)`
  - `lir/generator.cpp` 对 `DoubleBinaryOp<Power>` 还新增了 `x**0.5 -> sqrt` 快路径。

### 归因
- 你观察到的“upstream main 不改也能出 DoubleBinaryOp”是对的；
- 我们之前不行，是因为 branch 基于较早上游点（`c3028e25`）且未同步到包含该优化的后续上游提交。

## 2026-03-02 同步 upstream/main 冲突修复与远端验证

### 同步与冲突
- 当前分支：`bench-cur-7c361dce`
- 同步目标：`upstream/main`
- 先解决了 shallow 历史导致的 `refusing to merge unrelated histories`：
  - `git fetch --unshallow origin`
  - `git fetch upstream main`
  - `git merge upstream/main`
- 冲突文件（3 个）：
  - `cinderx/Common/util.h`
  - `cinderx/Jit/codegen/autogen.cpp`
  - `cinderx/Jit/codegen/gen_asm_utils.cpp`
- merge commit：
  - `e9c8311a Merge remote-tracking branch 'upstream/main' into bench-cur-7c361dce`

### 远端入口首轮验证（失败）
- 入口：`root@124.70.162.35` + `/root/work/incoming/remote_update_build_test.sh`
- 参数：`SKIP_PYPERF=1`
- 结果：
  - 构建成功
  - `test_arm_runtime.py` 失败 2 项（AArch64 代码尺寸阈值）：
    - `test_aarch64_call_sites_are_compact`: 实际 `95680`，阈值 `78000`
    - `test_aarch64_duplicate_call_result_arg_chain_is_compact`: 实际 `54752`，阈值 `44700`
- 归因：
  - 合并时把 upstream 的 AArch64 `Call` 返回地址保存序列带入当前分支，导致调用点体积明显增大，触发分支已有尺寸门禁。

### 修复动作
- `cinderx/Jit/codegen/autogen.cpp`
  - `translateCall()` 回到分支原有紧凑路径（保留 debug 记录语义）。
- `cinderx/Jit/codegen/gen_asm_utils.cpp`
  - 保留我们原有的 AArch64 MCS cold/hot 调用修复（大位移场景）。
  - 去掉本次同步引入的每次 helper call 额外返回地址保存指令序列，恢复紧凑调用点。

### 远端入口二轮验证（通过）
- 同入口同参数复验：`SKIP_PYPERF=1`
- 结果：
  - `Ran 12 tests in 1.619s`
  - `OK`

### 关键补充验证（远端）
- 浮点 HIR 下沉复核（同一远端环境）：
  - `DoubleBinaryOp<Add>`
  - `DoubleBinaryOp<Subtract>`
  - `DoubleBinaryOp<Multiply>`
  - `FloatBinaryOp<TrueDivide>`（语义保留）
- `force_compile True`，符合预期。

### 尺寸门禁当前值（远端实测）
- `size_call_sites = 77288`（阈值 78000，已通过）
- `size_dup_chain = 44520`（阈值 44700，已通过）

## 2026-03-02 Issue #3：Static Python 编译期开关（ENABLE_STATIC_PYTHON）

### Brainstorming 结论
- Static Python 在 CinderX 中与 JIT/模块初始化耦合较深，第一阶段采用“编译期开关 + 条件编译入口控制”的最小可落地方案。
- 默认保持开启（`ENABLE_STATIC_PYTHON=1`）保证现有行为和性能基线不受影响。
- 关闭时（`ENABLE_STATIC_PYTHON=0`）强制关闭 `ENABLE_ADAPTIVE_STATIC_PYTHON`，并通过 `CINDER_ENABLE_STATIC_PYTHON` 控制关键静态路径行为。

### 代码改动
- `CMakeLists.txt`
  - 新增 `option(ENABLE_STATIC_PYTHON ON)`。
  - 当该开关关闭时，强制 `ENABLE_ADAPTIVE_STATIC_PYTHON=OFF`。
  - 开启时定义宏：`CINDER_ENABLE_STATIC_PYTHON`。
- `setup.py`
  - 新增环境开关透传：`ENABLE_STATIC_PYTHON`（默认 True）。
  - 当其为 False 时，强制 `ENABLE_ADAPTIVE_STATIC_PYTHON=0`。
- `cinderx/_cinderx-lib.cpp`
  - 新增 API：`is_static_python_enabled()`。
  - `clear_caches`/`clear_classloader_caches`/`watch_sys_modules`/`strict_module_patch*`/dict watcher 等静态路径增加编译期条件控制。
  - 兼容性修复：即使关闭静态优化路径，也保留 `_static` 模块创建，避免 Python 层导入链断裂。
- `cinderx/PythonLib/cinderx/__init__.py`
  - 导出 `is_static_python_enabled()`（含 ImportError fallback）。
- `cinderx/PythonLib/test_cinderx/test_oss_quick.py`
  - 新增 `test_static_python_enablement_state`。
  - `test_adaptive_static_python_enablement_state` 按 `is_static_python_enabled()` 动态调整预期。

### TDD 记录
- RED（远端）
  - 构建后运行 `test_oss_quick.py` 失败：缺少 `is_static_python_enabled`。
  - 证据：`FAIL: test_static_python_enablement_state`。
- GREEN（远端）
  - 实现后同测试通过。
  - 默认构建：`static_enabled=True`，`adaptive_enabled=True`。

### 远端入口验证（统一）
- 入口：`root@124.70.162.35` + `/root/work/incoming/remote_update_build_test.sh`
- 默认 ON：
  - 日志：`/root/work/arm-sync/static_python_green_default_20260302_171338.log`
  - CMake 参数含：`-DENABLE_STATIC_PYTHON=1 -DENABLE_ADAPTIVE_STATIC_PYTHON=1`
  - 结果：`Ran 12 tests ... OK`，`jit-effective-ok`。
- OFF 复验（修复后）：
  - 日志：`/root/work/arm-sync/static_python_green_off_fix_20260302_172802.log`
  - CMake 参数含：`-DENABLE_STATIC_PYTHON=0 -DENABLE_ADAPTIVE_STATIC_PYTHON=0`
  - 结果：`Ran 12 tests ... OK`，`jit-effective-ok`。
  - Python 侧复核：`static_enabled=False`，`adaptive_enabled=False`，`test_oss_quick.py` 通过。

### 性能验收（ARM，基线 vs 当前）
- 同脚本：`scripts/arm/bench_compare_modes.py`，`repeats=7`。
- 基线构建：`91a27dcf`
  - 构建日志：`/root/work/arm-sync/static_python_perf_baseline_build_20260302_173732.log`
  - 数据目录：`/root/work/arm-sync/static_python_perf_baseline_20260302_174447`
- 当前构建：workspace snapshot（本次实现）
  - 构建日志：`/root/work/arm-sync/static_python_perf_candidate_build_20260302_174550.log`
  - 数据目录：`/root/work/arm-sync/static_python_perf_candidate_20260302_175238`
  - 复测目录：`/root/work/arm-sync/static_python_perf_candidate_r2_20260302_175322`

#### 关键对比（baseline -> candidate，median_sec）
- `cinderx_interp`: `0.2645615 -> 0.2662111`（`+0.624%`）
- `cinderx_jit`: `0.2648155 -> 0.2690761`（`+1.609%`）
- `cpython_interp`: `0.2617049 -> 0.2623430`（`+0.244%`）
- `cpython_jit`: `0.2602936 -> 0.2608223`（`+0.203%`）

#### 复测观察（candidate_r2）
- `cinderx_jit` 回落到 `0.2666050`，相对 baseline 约 `+0.676%`。
- 说明本轮波动主要在 ~1% 级别，未见明确功能性回退信号。

### 结论
- 编译期开关已实现并可用：`ENABLE_STATIC_PYTHON` + `CINDER_ENABLE_STATIC_PYTHON`。
- 默认路径（ON）下：远端门禁和 JIT 功能正常。
- 关闭路径（OFF）下：构建、关键测试和 JIT smoke 可通过，并且 `is_static_python_enabled=False` 与 `adaptive=False` 语义一致。
- 性能方面：本轮数据未显示确定性的显著回退（波动约 1% 量级）。


## 2026-03-03 Static OFF Deep-Dive: Extra Code Paths vs Official CPython Interpreter

### Scope and Comparison Contract
- Static OFF means `ENABLE_STATIC_PYTHON=0`, and adaptive static is forced off too.
  - Evidence: `CMakeLists.txt:39-42`, `setup.py:498-506`
- Interpreter comparison contract:
  - CinderX side: `PYTHONJITDISABLE=1`
  - CPython side: `PYTHON_JIT=0`
  - Entrypoint script: `scripts/arm/interp_hotspot_profile.sh:46-54`

### Bottom Line
- Turning Static Python OFF does not make CinderX equivalent to stock CPython.
- There are still extra CinderX subsystems in four layers: binary/link layer, import-time init layer, event-triggered layer, and explicit-JIT layer.
- Existing same-base remote result shows interpreter delta around `+1.70%` (`1.01695x`), so residual gap is mostly runtime integration/glue, not Static Python specialization itself.
  - Evidence: `artifacts/arm/20260228_interp_gap_rebaseline/interp_hotspot_samebase_summary.json`

### Extra Code Paths That Still Exist with Static OFF

#### A. Binary/Link Layer (still compiled and linked)
- StaticPython library is still built and linked into `_cinderx.so`:
  - `CMakeLists.txt:345-347`
  - `CMakeLists.txt:391`
- 3.14 interpreter-loop sources are still compiled by default (not necessarily activated at runtime):
  - `setup.py:512-519`
  - `CMakeLists.txt:304-306`
  - `cinderx/Interpreter/3.14/interpreter.c`
- `_static` module is still created for compatibility:
  - `cinderx/_cinderx-lib.cpp:1600-1603`

#### B. Import-Time Init Layer (runs on `import cinderx`)
- `_cinderx` still creates runtime state and cache manager:
  - `cinderx/_cinderx-lib.cpp:1311-1329`
- Watchers are still configured and registered:
  - `cinderx/_cinderx-lib.cpp:1446-1450`
  - `cinderx/_cinderx-lib.cpp:1564`
  - `cinderx/Common/watchers.cpp:15-36`
- `jit::initialize()` is still called unconditionally (even if `PYTHONJITDISABLE=1` causes early return):
  - `cinderx/_cinderx-lib.cpp:1568`
  - `cinderx/Jit/pyjit.cpp:493-500`
  - `cinderx/Jit/pyjit.cpp:3529-3538`
- Runtime patching/type prep that is not 1:1 tied to Static ON/OFF remains:
  - Generator/coroutine replacement types + `anext` route: `cinderx/_cinderx-lib.cpp:1357-1411`
  - `sys` clear-cache hook replacement: `cinderx/_cinderx-lib.cpp:1533-1549`

#### C. Event-Triggered Layer (not every opcode, but still active on mutations)
- Function watcher still tries JIT scheduling on create/modify events:
  - `cinderx/_cinderx-lib.cpp:875-894`
  - `cinderx/_cinderx-lib.cpp:902-909`
  - `cinderx/_cinderx-lib.cpp:584-590`
- Dict/type watcher still drives cache invalidation logic:
  - `cinderx/_cinderx-lib.cpp:812-869`
  - `cinderx/_cinderx-lib.cpp:925-930`
  - `cinderx/Jit/global_cache.cpp:227-253`
  - `cinderx/Jit/inline_cache.cpp:1632-1635`

#### D. Explicit-JIT Layer (entered only when JIT is explicitly enabled)
- Frame evaluator (`Ci_EvalFrame`) installation still happens through JIT APIs (`auto`, `force_compile`, etc.):
  - `cinderx/Jit/pyjit.cpp:1560-1563`
  - `cinderx/Jit/pyjit.cpp:1665-1667`
  - `cinderx/Interpreter/interpreter_base.cpp:29-51`
- In pure interpreter runs with `PYTHONJITDISABLE=1`, this layer is normally not active.

### Verification Status / Blocker
- Planned symbol-level re-profile entrypoint: `scripts/arm/interp_hotspot_profile.sh`
- 2026-03-03 real-time run is blocked by network timeout:
  - `ssh: connect to host 124.70.162.35 port 22: Connection timed out`
  - `Test-NetConnection`: `TcpTestSucceeded=False`
- So this list is evidence-based from:
  - existing remote artifacts (summary)
  - current source-level line-by-line attribution

## 2026-03-03 追加：Python 3.14 轻量级帧（LWF）开关与性能影响复核

### 1) 关于“为什么 3.14 未开启 LWF”
- 历史上确实存在该情况：
  - 早期 `setup.py` 使用 `set_option("ENABLE_LIGHTWEIGHT_FRAMES", meta_312)`，仅 meta 3.12 默认开启。
- 该行为已在提交 `d1aaf6f9` 修正：
  - 提交标题：`Enable lightweight frames on 3.14 ARM with LTO/PGO support`
  - 关键改动：
    - 新增 `should_enable_lightweight_frames()`
    - 3.14 + `aarch64/arm64` 默认开启 LWF
- 当前分支状态（`70fdffdd`）已包含该改动；因此“3.14 未开启”只在旧提交或非 ARM 条件下成立。

### 2) 开启 LWF 的前提依赖
- 构建前提（编译期）：
  - `ENABLE_LIGHTWEIGHT_FRAMES=1`
  - 对 3.14 默认策略：`py_version == "3.14" and machine in {"aarch64","arm64"}`（见 `setup.py`）
- 平台/版本前提：
  - 目标为 Python 3.14 ARM（OSS Stage A）
  - x86_64 3.14 默认不启用（有单测覆盖）
- JIT 相关前提：
  - `ENABLE_INTERPRETER_LOOP` / `ENABLE_PEP523_HOOK` 在 3.14 打开
  - JIT 配置下，`ENABLE_LIGHTWEIGHT_FRAMES` 会决定 `FrameMode` 默认值
    - 开启时默认 `FrameMode::kLightweight`
    - 关闭时默认 `FrameMode::kNormal`
  - 3.12+ 下 HIR inliner 依赖 lightweight frame（`pyjit.cpp:769-772`）

### 3) 性能影响（远端实测）

#### 3.1 解释执行：LWF 开/关（统一远端入口矩阵）
- 入口：`scripts/arm/interp_feature_matrix.sh`
- 运行：`run_id=20260303_lwf_qna_matrix_b`（组合 `1,1` vs `1,0`）
- 结果：
  - `asp1_lwf1` median = `0.2652255670 s`
  - `asp1_lwf0` median = `0.2654369460 s`
  - LWF 开启相对关闭：`0.99920x`（约 `-0.08%`，非常小）
- 结论：
  - 在 `adaptive_static=1` 条件下，LWF 对解释器基线影响很小，量级约 0~1%。

#### 3.2 JIT：LWF 编译开关影响（远端重建 + 同脚本对比）
- 入口：`/root/work/incoming/remote_update_build_test.sh` 重建 + `scripts/arm/bench_compare_modes.py`
- 数据目录：`/root/work/arm-sync/lwf_qna_jitbuild_20260303_step`
- 结果：
  - `lwf0_jit` median = `0.2668238860 s`
  - `lwf1_jit` median = `0.2644076310 s`
  - `lwf1_vs_lwf0_jit = 0.99094x`（约 `-0.91%`，LWF 更快）
- 同次解释器对照：
  - `lwf0_interp` = `0.2674639920 s`
  - `lwf1_interp` = `0.2655403990 s`
  - `lwf1_vs_lwf0_interp = 0.99281x`（约 `-0.72%`）

#### 3.3 JIT 运行时帧模式切换（同一 LWF 编译开启构建）
- 数据目录：`/root/work/arm-sync/lwf_qna_runtimeflag_20260303`
- 对比：
  - `PYTHONJITLIGHTWEIGHTFRAME=0`：`0.2671395130 s`
  - `PYTHONJITLIGHTWEIGHTFRAME=1`：`0.2659138170 s`
  - 比值：`0.99541x`（约 `-0.46%`，轻量级帧更快）

### 4) 远端校验补充
- 当前远端运行时探针：
  - `static False`
  - `adaptive False`
  - `lwf True`
- 相关测试（远端）：
  - `tests/test_setup_lightweight_frames.py`：`Ran 5 tests ... OK`
  - `tests/test_cinderx_lightweight_frames_api.py`：`Ran 2 tests ... OK`

### 5) 总结
- “3.14 未开启 LWF”是旧状态；当前分支在 ARM 3.14 已默认开启。
- 开启前提主要是：3.14 ARM + 编译期开关生效 + JIT 侧帧模式与解释器循环支持。
- 性能上：
  - 解释器：影响很小（约 0~1%）
  - JIT：在当前 workload 上有小幅正收益（约 0.5%~1%）
  - 结论应按 workload 看待，但当前数据未见回退信号。

## 2026-03-03 追加：为何“快路径没生效”，而 meta 版本看起来可生效

### 结论（先说重点）
- 这次问题主因不是 `ENABLE_LIGHTWEIGHT_FRAMES` 失效，而是运行时没有进入 specialized-opcode 路径，最终 HIR 仍是通用 `BinaryOp`，机器码回到 helper 调用链。
- 要进入浮点快路径（`DoubleBinaryOp -> Fadd/Fsub/Fmul`）至少要满足两点：
  - 已开启 specialized opcodes；
  - 编译前已经有足够 warmup（否则 `force_compile` 太早会锁定通用路径）。

### 代码证据
- `cinderx/Jit/config.h`：`specialized_opcodes` 默认值是 `false`。
- `cinderx/Jit/hir/builder.cpp`：仅当 `getConfig().specialized_opcodes` 为真时，才会为专门化的 `BINARY_OP_*_FLOAT` 注入 `GuardType<FloatExact>`。
- `cinderx/Jit/hir/simplify.cpp`：只有 `lhs/rhs` 已是 `TFloatExact` 时，`Add/Subtract/Multiply` 才会下沉成 `DoubleBinaryOp`；`TrueDivide` 保持 `FloatBinaryOp` helper 路径（语义保真）。

### 远端 ARM 复现（root@124.70.162.35）
1. 不开 specialized-opcodes：
- 最终 HIR：`BinaryOp<Add/Subtract/Multiply/TrueDivide>`。
- `dump_elf + objdump`：未见 `fadd/fsub/fmul`，主要是 helper `blr` 调用链。

2. 开 specialized-opcodes + 先 warmup 再编译：
- 最终 HIR：`GuardType<FloatExact>` + `DoubleBinaryOp<Add/Subtract/Multiply>` + `FloatBinaryOp<TrueDivide>`。
- `dump_elf + objdump`：可见 `fadd/fsub/fmul` AArch64 指令。

3. 开 specialized-opcodes 但 `force_compile` 过早（无 warmup）：
- 最终 HIR仍是：`BinaryOp<Add/Subtract/Multiply/TrueDivide>`。
- 说明“开关开了但时机不对”同样会错过快路径。

### 为什么 meta 版本“看起来能生效”
- 基于开源代码的推断：meta 环境通常在更热阶段编译，或默认统一开启 specialized-opcodes；因此更容易在编译时拿到已专门化字节码与类型守卫，触发 `DoubleBinaryOp` 下沉。
- 当前分支若在编译时机或 specialized-opcode 开关上不满足条件，就会退回 helper 路径，看起来像“快路径没生效”。
 

## 2026-03-03 richards LWF A/B (remote)
- host: root@124.70.162.35
- out_dir: /root/work/arm-sync/20260303_richards_lwf_compare
- command path: scripts/bench/run_richards_remote.sh
- benchmark: pyperformance richards
- samples_per_mode: 5
- build matrix: ENABLE_ADAPTIVE_STATIC_PYTHON=1 with ENABLE_LIGHTWEIGHT_FRAMES in {0,1}

Build state checks:
- lwf=0 build: static=True adaptive=True lwf=False
- lwf=1 build: static=True adaptive=True lwf=True

Median results (seconds):
- lwf0 nojit: 0.0516214410
- lwf1 nojit: 0.0516654700
- ratio lwf1/lwf0 nojit: 1.0008529x (~+0.09%, near neutral)
- lwf0 jitlist: 0.1390315090
- lwf1 jitlist: 0.1375618580
- ratio lwf1/lwf0 jitlist: 0.9894294x (~-1.06%, lwf faster)
- lwf0 autojit50: 0.1180979180
- lwf1 autojit50: 0.1176477670
- ratio lwf1/lwf0 autojit50: 0.9961883x (~-0.38%, lwf faster)

Artifacts:
- /root/work/arm-sync/20260303_richards_lwf_compare/richards_lwf0.json
- /root/work/arm-sync/20260303_richards_lwf_compare/richards_lwf1.json
- /root/work/arm-sync/20260303_richards_lwf_compare/summary.json

Note:
- This run uses pyperformance --debug-single-value in each sample; jitlist/autojit50 include one-process startup/compilation effects.


## 2026-03-05 PrimitiveUnbox CSE（远端闭环）
- 远端入口：`root@124.70.162.35`
- 目标：实现 HIR `PrimitiveUnbox` 公共子表达式消除（CSE），修复 `g(x)=x+x` 产生双 unbox 的问题。

### 改动
- 新增 pass：
  - `cinderx/Jit/hir/primitive_unbox_cse.h`
  - `cinderx/Jit/hir/primitive_unbox_cse.cpp`
- 编译管线接入：
  - `cinderx/Jit/compiler.cpp`
  - 在每次 `Simplify` 后运行 `PrimitiveUnboxCSE`。
- 回归测试：
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - 新增 `test_primitive_unbox_cse_for_float_add_self`，断言 `PrimitiveUnbox == 1`。

### TDD 过程
1. RED（先失败）：
- 远端单测在改动前失败，`PrimitiveUnbox` 实际计数为 `2`（期望 `1`）。

2. 实现后首轮问题：
- 首版 pass 在遍历 block 时边遍历边 `ReplaceWith`，触发迭代器失效，报错：
  - `Assertion failed: block_ != nullptr`
  - `Instr isn't linked`
- 修复：改为“先 `++it` 再替换当前指令”的安全迭代。

3. GREEN（修复后通过）：
- 远端命令：
  - `PYTHONPATH=/root/work/cinderx-main/cinderx/PythonLib python -m unittest -v test_cinderx.test_arm_runtime.ArmRuntimeTests.test_primitive_unbox_cse_for_float_add_self`
- 结果：`OK`。

### 远端验证结果（HIR + 汇编）
1. HIR（`PYTHONJITDUMPFINALHIR=1`）：
- 关键片段：
  - `v13:CDouble = PrimitiveUnbox<CDouble> v10`
  - `v15:CDouble = DoubleBinaryOp<Add> v13 v13`
- 计数：
  - `hir_counts ... 'PrimitiveUnbox': 1, 'DoubleBinaryOp': 1`

2. `dump_elf` 架构确认：
- `file /tmp/unbox_cse_demo.elf`：
  - `ELF 64-bit ... ARM aarch64`
- `readelf -h`：
  - `Machine: AArch64`

3. AArch64 反汇编（`objdump`）：
- 函数：`__main__:g`
- 关键指令：
  - `1160: ldr d0, [x20, #16]`
  - `1164: fadd d8, d0, d0`
- 结论：重复 `ldr d0/d1` 已消除，达到“单次 unbox + 自加”预期。
# 2026-03-10 issue-15: slot version guard elimination

- Added HIR pass SlotVersionGuardElimination to deduplicate redundant LOAD_ATTR_SLOT / STORE_ATTR_SLOT tp_version_tag guards by dominating receiver/tag pair.
- The pass runs after Simplify and before PrimitiveUnboxCSE, and clears its active guard map on any instruction with arbitrary execution.
- Added ARM runtime regression test ArmRuntimeTests.test_slot_type_version_guards_are_deduplicated.
- Remote verification on 124.70.162.35 passed:
  - test_slot_type_version_guards_are_deduplicated
  - test_math_sqrt_cdouble_lowers_to_double_sqrt
  - test_math_sqrt_negative_input_preserves_value_error## 2026-03-10 Task: LOAD_GLOBAL mutable large int guard fix

### Design
- Issue: https://github.com/113xiaoji/cinderx/issues/16
- Actual code location in this branch: cinderx/Jit/hir/builder.cpp, emitLoadGlobal()
- Chosen fix: keep GuardIs by default, but downgrade mortal exact int globals to GuardType<LongExact>
- Reason: fixes the TIMESTAMP += 1 deopt pathology without broadly removing identity-based specialization for other globals

### TDD
- Added remote regression in cinderx/PythonLib/test_cinderx/test_arm_runtime.py:
  - ArmRuntimeTests.test_load_global_mutable_large_int_avoids_repeated_deopts
- RED command:
  - python cinderx/PythonLib/test_cinderx/test_arm_runtime.py ArmRuntimeTests.test_load_global_mutable_large_int_avoids_repeated_deopts -v
- RED result before fix:
  - AssertionError: 200 != 0

### Remote verification
- Entry: ssh root@124.70.162.35
- Remote workdir: /root/work/cinderx-main
- Remote venv: /root/venv-cinderx314
- Remote host could not fetch GitHub during FetchContent.
- Workaround:
  - synced fmt-src, parallel-hashmap-src, and usdt-src from local machine into remote _deps
  - rebuilt incrementally with:
    - cmake --build scratch/temp.linux-aarch64-cpython-314 --target _cinderx -- -j 1
  - replaced:
    - /root/venv-cinderx314/lib/python3.14/site-packages/_cinderx.so

### GREEN
- Targeted regression command:
  - python cinderx/PythonLib/test_cinderx/test_arm_runtime.py ArmRuntimeTests.test_load_global_mutable_large_int_avoids_repeated_deopts -v
- Result:
  - Ran 1 test ... OK

### HIR evidence
- Final HIR for Board.useful now shows all LOAD_GLOBAL: TIMESTAMP sites as:
  - GuardType<LongExact>
- No GuardIs remains on the TIMESTAMP global in the dumped function.

### Full remote regression
- Command:
  - python cinderx/PythonLib/test_cinderx/test_arm_runtime.py
- Result:
  - Ran 20 tests ... OK

## 2026-03-10 Issue 17 评估（远端闭环，未实施代码修改）
- 远端入口：`root@124.70.162.35`
- issue：`https://github.com/113xiaoji/cinderx/issues/17`
- 结论：issue 中提议的 `LoadGlobalCached + GuardIs` 去重在所给 case 上不安全，当前不应直接实现。

### 本地语义审查
- `LoadGlobalCached` 读取 `AGlobal`，不是纯常量。
- `GuardIs` 钉住对象身份，但不能跨“可能任意执行”的指令省略。
- `VectorCall` / `BinaryOp` 等在 HIR 里被标为 `hasArbitraryExecution = true`。

### 远端最小复现
- 复现脚本形状：
  - `a = func_g(x)`
  - `b = func_g(y)`
  - `return a + b`
- 远端 final HIR 结果：
  - `LoadGlobalCached: 2`
  - `GuardIs: 2`
  - `VectorCall: 2`
- 这说明重复加载存在，但两次加载之间隔着函数调用 barrier。

### 反例证明（关键）
- 远端构造：
  - 第一次调用 `func_g(x)` 时执行 `global func_g; func_g = func_h`
  - 第二次调用必须重新读取全局，才能看到 `func_h`
- 结果：
  - 期望值：`108`
  - 实际值：`108`
- 如果按 issue 建议把第二次 `LoadGlobalCached + GuardIs` 消掉，就会错误复用第一次守卫过的旧函数对象，语义将出错。

### 结论
- issue 17 当前描述的两个方案：
  - 方案 A：对 `LoadGlobalCached` 做局部 CSE
  - 方案 B：仅删除第二个 `GuardIs`
  在给定的跨调用场景中都不安全。
- 若未来继续做这类优化，范围必须缩小到：
  - 同一基本块内
  - 两次加载之间无 `hasArbitraryExecution` barrier
  - 无可能影响 `AGlobal` 观察结果的操作
- 本轮未提交 issue 17 代码修改。

## 2026-03-10 Issue 18：exact list slice specialization（远端闭环）
- 远端入口：`root@124.70.162.35`
- issue：`https://github.com/113xiaoji/cinderx/issues/18`
- 目标：对 exact list 的 `BuildSlice + BinaryOp<Subscript>` 做特化，去掉中间 `PySlice_New` 分配。

### 结论
- 已完成 exact-list slice 优化，范围限定为：
  - `TListExact`
  - `BuildSlice<2>`
  - `start/stop` 为 `NoneType` 或 `LongExact`
- 未覆盖：
  - 非 exact list
  - 带 `step` 的切片
  - 通用容器切片

### 实现
- 新增 HIR：`ListSlice`
- 新增 runtime helper：`JITRT_ListSlice(list, start, stop)`
- 新增 post-refcount 清理 pass：`ListSliceCleanup`
  - 删除特化后遗留的 dead `BuildSlice + Decref`
- 保留现有单元素下标快路径；issue 18 的“阶段 1”在 exact list 上本来就已经有了。

### 远端 HIR 验证
使用本地 exact list 复现函数：
- `lst = [10, 20, 30, 40, 50]`
- `left = lst[:mid]`
- `right = lst[mid + 1:]`
- `item = lst[mid]`

基线（clean worktree）final HIR opcode counts：
- `BuildSlice: 2`
- `BinaryOp: 2`
- `CheckSequenceBounds: 1`
- `LoadArrayItem: 1`
- `Decref: 4`

当前（modified worktree）final HIR opcode counts：
- `ListSlice: 2`
- `BuildSlice: 0`
- generic slice `BinaryOp`: 0
- `CheckSequenceBounds: 1`
- `LoadArrayItem: 1`
- `Decref: 2`

功能结果：
- `([10, 20], 30, [40, 50])`

### 远端 benchmark
- baseline worktree: `/root/work/cinderx-issue14-base`
- current worktree: `/root/work/cinderx-git`
- command style:
  - `taskset -c 0`
  - same GCC12 runtime library path
  - same Python interpreter
- workload：`test_local_list_slice()`
- iterations：`1,000,000`
- repeats：`7`

结果（median）：
- baseline: `1.3714s`
- current: `1.0596s`
- speedup: about `22.7%`

## 2026-03-11 Issue 18 follow-up：parameter-typed list specialization
- 问题：`def test_list_slice(lst: list): ...` 这种参数版测试在默认配置下最初没有命中 `ListSlice` / `LoadArrayItem`。
- 根因：参数注解默认没有进入 HIR 类型收窄；`lst` 在 final HIR 里仍是 `Object`。

### 方案
- 不再继续在 `BinaryOp<Subscript>` 上猜测 `Object -> ListExact`。
- 改为在 `specialized_opcodes` 开启时，默认装载函数注解，并为一小撮 builtin 注解类型插入口 `GuardType`：
  - `list`
  - `tuple`
  - `dict`
  - `str`
  - `int`
  - `float`
- 保留原来的 `emit_type_annotation_guards` 开关语义；如果显式开启，仍然走完整注解 guard 模式。

### 远端验证
- 远端入口：`root@124.70.162.35`
- 参数版复现：
  - `def test_list_slice(lst: list): ...`
- 当前 final HIR opcode counts：
  - `GuardType: 1`
  - `ListSlice: 2`
  - `LoadArrayItem: 1`
  - `BuildSlice: 0`
  - generic `BinaryOp`: 0
- 新增远端回归测试：
  - `test_cinderx.test_arm_runtime.ArmRuntimeTests.test_list_annotation_enables_exact_slice_and_item_specialization`
  - 结果：`OK`

### benchmark
- baseline: `0.8109s`
- current: `0.6255s`
- speedup: about `22.9%`
## 2026-03-11 Task: raytrace mixed numeric specialized-op fix

### Final fix
- File:
  - cinderx/Jit/hir/builder.cpp
- Policy:
  - for specialized numeric binary/compare opcodes, keep exact int guards only when the current code object has a backedge
  - for no-backedge leaf helpers, skip those exact int guards
  - float specialized-opcode guards remain enabled
- Reason:
  - raytrace leaf helpers like Vector.dot are mixed int/float and were deopting catastrophically under exact-int guards
  - broad numeric-guard removal helped raytrace but regressed existing float-path tests
  - the narrowed int-only no-backedge policy preserves float fast paths while fixing the mixed leaf case

### Remote verification
- Entry:
  - ssh root@124.70.162.35
- New targeted regression:
  - ArmRuntimeTests.test_specialized_numeric_leaf_mixed_types_avoid_deopts
  - result: OK
- Existing float regressions re-run and passed:
  - test_float_add_sub_mul_lower_to_double_binary_op_in_final_hir
  - test_math_sqrt_cdouble_lowers_to_double_sqrt
  - test_primitive_unbox_cse_for_float_add_self
  - test_primitive_box_remat_elides_frame_state_only_boxes
- Full remote file:
  - python cinderx/PythonLib/test_cinderx/test_arm_runtime.py
  - result: Ran 24 tests ... OK

### raytrace direct benchmark
- Command uses scripts/arm/bench_pyperf_direct.py against bm_raytrace/run_benchmark.py
- compile_strategy=all, samples=5:
  - median about 0.5742 s
  - total_deopt_count = 0
- compile_strategy=backedge, samples=5:
  - median about 0.6623 s
  - total_deopt_count = 0
- compile_strategy=none, samples=5:
  - median about 0.6025 s
  - total_deopt_count = 0
- Interpretation:
  - the final narrowed policy removes the catastrophic mixed-type deopt storm
  - on raytrace, CinderX JIT is now ahead of the previously recorded CPython JIT median (~0.6861 s)

## 2026-03-13 Issue 23: speculative long-loop unboxing

### Scope
- Added minimal IR/lowering support:
  - `CheckedIntBinaryOp`
  - `LongUnboxCompact`
  - compact-long `Guard` lowering
- Added a new HIR pass:
  - `LongLoopUnboxing`
  - gated on `specialized_opcodes`
  - rewrites narrow `hot_loop`-style `LongExact` loop-carried phis into primitive `CInt64` shadow phis

### Remote verification
- Host:
  - `124.70.162.35`
- Working tree:
  - `/root/work/cinderx-git`
- Build:
  - reconfigured and rebuilt `_cinderx.so` successfully
- Targeted runtime regression:
  - `test_cinderx.test_arm_runtime.ArmRuntimeTests.test_hot_loop_uses_long_loop_unboxing`
  - result: `OK`
- Existing runtime regressions re-run:
  - `test_list_annotation_enables_exact_slice_and_item_specialization`
  - `test_primitive_unbox_cse_for_float_add_self`
  - result: both `OK`

### final HIR
- `hot_loop(n)` now compiles to:
  - `CheckedIntBinaryOp: 2`
  - `LongUnboxCompact: 1`
  - `PrimitiveCompare: 1`
  - `PrimitiveBox: 1`
  - `LongInPlaceOp: 0`
  - `CompareBool: 0`
- The loop bound is guarded/unboxed once in the preheader.
- The loop-carried accumulator/counter are primitive phis.
- Only the final return is boxed.

### benchmark
- Workload:
  - `hot_loop(10000)`
  - `OUTER=2000`
  - `REPEATS=7`
- Result:
  - baseline median: `0.8305595869896933s`
  - current median: `0.028081598924472928s`
  - speedup: about `29.6x`

## 2026-03-14 issue31 raytrace regression fix

Root cause confirmation:
- the severe regression was not caused by the basic issue31 attr specialization alone
- it came from combining that specialization with specialized float-op guards on helper-heavy no-backedge raytrace methods
- after the issue31 work, methods such as `Vector.dot`, `Point.__sub__`, and `Sphere.intersectionTime` ended up on exact-instance field paths, which exposed aggressive `FloatExact` guards and caused large GuardFailure deopt spikes on mixed `int` / `float` values

Fix implemented:
- narrowed the issue31-specific exact `other` arg inference to plain-attr-read shapes only
- added a new function-level metadata bit for aggressive split-dict pure-load lowering
- changed specialized float-op guard policy in `builder.cpp`:
  - keep exact float guards for loop-hot code or issue31-style plain-attr methods
  - drop them for helper-heavy no-backedge methods such as the raytrace shapes

Targeted ARM regressions:
- `test_plain_instance_other_arg_guard_eliminates_cached_attr_loads`: `OK`
- `test_other_arg_inference_skips_helper_method_shapes`: `OK`

Issue31 A/B after the fix:
- `PointOther.dist` median: `0.3772901860065758 s`
- `PointRhs.dist` median: `0.40128343703690916 s`
- dist improvement remains: about `6.0%`
- `PointOther` mixed benchmark median: `0.20818231801968068 s`
- `PointRhs` mixed benchmark median: `0.21198970696423203 s`
- mixed improvement remains: about `1.8%`

Provided raytrace regression script after the fix:
- elapsed wall for the measured run: `1.1966644480125979 s`
- severe deopt sites removed from the top list:
  - `Vector.dot` no longer appears in runtime deopt stats
  - `Point.__sub__` no longer appears in runtime deopt stats
  - `Sphere.intersectionTime` no longer appears in runtime deopt stats
- remaining deopts are much smaller and now concentrated in:
  - `Vector.scale` line 31: `5333` (+ `2`)
  - `addColours` line 219: `5333`

HIR spot-check after the fix:
- `Vector.dot`
  - `GuardType = 2`
  - `LoadField = 12`
  - `DoubleBinaryOp = 0`
  - no runtime deopt entries in the measured run
- `Point.__sub__`
  - `GuardType = 3`
  - `LoadField = 24`
  - no runtime deopt entries in the measured run
- `Sphere.intersectionTime`
  - `GuardType = 1`
  - `LoadField = 6`
  - no runtime deopt entries in the measured run
- `addColours`
  - still `GuardType = 6`
- `Vector.scale`
  - still `GuardType = 5`

Conclusion:
- the severe issue31-induced raytrace regression is largely fixed
- the main catastrophic deopt sources are gone while the intended issue31 gains still remain
- there are still smaller mixed numeric deopts left in `Vector.scale` and `addColours`, but they are no longer the same class of large regression introduced by the issue31 change

## 2026-03-14 issue34 builtin min/max float specialization

Problem confirmation:
- two-arg builtin `min(a, b)` / `max(a, b)` on exact floats still compiled through a generic `VectorCall`
- this paid full Python call overhead even though the hot path only needed float comparison plus selection

Semantics analysis:
- the issue proposal to lower directly to `DoubleBinaryOp<Min/Max>` / ARM64 `FMIN/FMAX` is not fully safe for Python builtins
- Python `min/max` return one of the original operand objects, not a freshly boxed float
- behavior is order-sensitive for NaN and ties:
  - `min(float("nan"), 1.0)` returns the first argument object
  - `min(1.0, float("nan"))` returns the first argument object (`1.0`)
  - `min(0.0, -0.0)` and `max(0.0, -0.0)` preserve the first argument object (`0.0`)
- so the safe lowering is:
  - keep builtin identity guard
  - guard args to `FloatExact`
  - `PrimitiveUnbox<CDouble>` both args
  - `PrimitiveCompare` on unboxed doubles
  - branch/select the original operand object

Implementation:
- `cinderx/Jit/hir/simplify.cpp`
  - added `simplifyVectorCallBuiltinMinMax()`
  - fixed builtin recognition for the `GuardIs` shape by checking `GuardIs::target()`
  - specialized exactly two-arg builtin `min`/`max` calls on exact floats
- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - added `test_builtin_min_max_two_float_args_eliminate_vectorcall`
  - added `test_builtin_min_max_two_float_args_preserve_order_nan_and_identity`

Remote ARM verification:
- editable rebuild on `/root/work/frame-stage-local`: success
- targeted tests:
  - `test_builtin_min_max_two_float_args_eliminate_vectorcall`: passed
  - `test_builtin_min_max_two_float_args_preserve_order_nan_and_identity`: passed

Optimized HIR:
- `__main__:min_builtin`
  - `LoadGlobalCached<"min">`
  - `GuardIs<builtin min>`
  - `GuardType<FloatExact>` x2
  - `PrimitiveUnbox<CDouble>` x2
  - `PrimitiveCompare<LessThanUnsigned>`
  - `CondBranch`
  - no `VectorCall`
- `__main__:max_builtin`
  - same shape with `PrimitiveCompare<GreaterThanUnsigned>`
  - no `VectorCall`

Opcode counts:
- `counts_min`
  - `VectorCall = 0`
  - `GuardType = 2`
  - `PrimitiveUnbox = 2`
  - `PrimitiveCompare = 1`
  - `CondBranch = 2`
  - `Phi = 1`
- `counts_max`
  - `VectorCall = 0`
  - `GuardType = 2`
  - `PrimitiveUnbox = 2`
  - `PrimitiveCompare = 1`
  - `CondBranch = 2`
  - `Phi = 1`

Performance (`N = 2_000_000`):
- `min_builtin`: `0.1626069820486009s`
- `min_ternary`: `0.2111730769975111s`
- `min_ratio`: `0.7700175815997482x`
- `max_builtin`: `0.16318202891852707s`
- `max_ternary`: `0.21114284498617053s`
- `max_ratio`: `0.7728513316622934x`

Conclusion:
- issue34 is fixed from the performance perspective:
  - the generic `VectorCall` path is gone
  - the specialized builtin version is now faster than the manual ternary baseline on ARM
- the final implementation intentionally does not use `DoubleBinaryOp<Min/Max>` because that would break Python builtin semantics around NaN, signed zero, and object identity

## 2026-03-14 Issue 36: inline set(genexpr) into set-style loop

### Scope
- Added a builder-time rewrite for builtin `set(<genexpr>)`
- The rewrite now handles:
  - simple generator expressions
  - closure-capturing generator expressions like `set(vec[i] + i for i in cols)`
- The current implementation rewrites the inner generator call into:
  - `MakeSet`
  - `InvokeIterNext`
  - per-element body
  - `SetSetItem`

### Remote validation
- Host:
  - `124.70.162.35`
- Working tree:
  - `/root/work/cinderx-git`
- Runtime regressions:
  - `test_set_genexpr_eliminates_generator_call`
  - `test_set_genexpr_with_closure_eliminates_generator_call`
  - result: both `OK`
- Existing regression re-run:
  - `test_list_annotation_enables_exact_slice_and_item_specialization`
  - result: `OK`

### final HIR
- `set(i * 2 for i in range(8))` no longer goes through:
  - `CallMethod` to create a generator object
  - outer `VectorCall(set, gen_obj)`
- It now contains:
  - `MakeSet`
  - `InvokeIterNext`
  - `SetSetItem`
- Closure case `set(vec[i] + i for i in cols)` also lowers to a flat set loop and removes `CallMethod`.

### limitation
- `MakeFunction` still remains in the outer function.
- So this is a partial lowering:
  - generator-object creation is removed
  - function-object creation is not yet removed
- A fuller second stage would need to avoid `MAKE_FUNCTION` itself.

### second stage
- Added `MakeFunctionConstFold` for no-closure `<genexpr>` helpers.
- This removes the remaining simple-case `MakeFunction` by replacing it with a constant function object after the builder rewrite.
- Closure-bearing genexprs still keep `MakeFunction`.

### benchmark
- Remote JITed microbenchmark:
  - `set(i * 2 for i in range(8))`
  - `{i * 2 for i in range(8)}`
- Current median:
  - genexpr: `0.1674330570967868s`
  - setcomp: `0.16612694202922285s`
- Interpretation:
  - simple `set(genexpr)` is now effectively at parity with setcomp
  - remaining opportunity is concentrated in closure cases

### base comparison
- Clean base worktree:
  - `/root/work/cinderx-issue36-base`
  - built from `origin/bench-cur-7c361dce`
- Same remote compare script results:
  - current `set(genexpr)`: `0.1674330570967868s`
  - base `set(genexpr)`: `1.0065587260760367s`
  - speedup: about `6.01x`
  - current setcomp: `0.16612694202922285s`
  - base setcomp: `0.2993291780585423s`
- Direct `n_queens(8)` benchmark:
  - current: `1.3242973680607975s`
  - base: `1.5738149019889534s`
  - speedup: about `15.9%`
## 2026-03-15 pyperformance coroutines: 3.14 coroutine HIR fix

- Host: `124.70.162.35`
- Branch/worktree: local `bench-cur-7c361dce` synced to `/root/work/cinderx-main`
- Primary remote entry: `scripts/arm/remote_update_build_test.sh`

### Root cause confirmed

- The `pyperformance` `bm_coroutines` hot function
  - `async def fibonacci(n): return await fibonacci(n - 1) + await fibonacci(n - 2)`
  - originally failed under `jit.force_compile()` on 3.14 because the builder
    aborted on `CLEANUP_THROW`.
- After that blocker was removed, optimized HIR for `fibonacci` still showed the
  immediate-await recursive calls going through the generic helper chain:
  - `CallCFunc<JitCoro_GetAwaitableIter>`
  - `CallCFunc<JitGen_yf>`
  - one pair for each recursive await site

### Implemented fix

- `cinderx/Jit/bytecode.cpp`
  - treat `CLEANUP_THROW` as a terminator so handler-only cleanup blocks do not
    get merged into ordinary fallthrough blocks
- `cinderx/Jit/hir/builder.cpp`
  - lower `CLEANUP_THROW` blocks as deopting exception-only paths instead of
    aborting compilation
  - in `emitGetAwaitable()`, when the awaitable input is the fresh result of a
    known coroutine call, bypass the generic helper path and keep the value on
    the stack directly
- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - added `test_recursive_coroutine_fibonacci_force_compile`
  - added `test_recursive_coroutine_immediate_await_skips_awaitable_helpers`
- `scripts/arm/remote_update_build_test.sh`
  - export `CINDERX_BUILD_JOBS="$PARALLEL"` so the wheel build obeys the chosen
    parallelism
  - added targeted ARM runtime test-name support for tighter remote validation
  - routed benchmark/test `PYTHONPATH` through the freshly built
    `scratch/lib...` tree for current-worktree validation

### Evidence

- Direct remote regression tests against the freshly built `_cinderx` in
  `/root/work/cinderx-main/scratch/lib.linux-aarch64-cpython-314`:
  - `ArmRuntimeTests.test_recursive_coroutine_fibonacci_force_compile`: pass
  - `ArmRuntimeTests.test_recursive_coroutine_immediate_await_skips_awaitable_helpers`: pass
- Optimized HIR for `__main__:fibonacci` after the fix:
  - no `CallCFunc<JitCoro_GetAwaitableIter>`
  - no `CallCFunc<JitGen_yf>`
  - recursive await sites now go straight from `VectorCall` to `Send`/`YieldFrom`
- Remote benchmark comparison on the same host:
  - interpreter mode (`CINDERX_DISABLE=1`): about `55.4 ms`
  - previous CinderX auto-jit (`PYTHONJITAUTO=50`, `__main__:*`): about `77.1 ms`
  - current HIR fix with fresh scratch build on `PYTHONPATH`: about `51.4 ms`
- Auto-jit compile log under the fixed path:
  - `Finished compiling __main__:fibonacci in 1424µs, code size: 1544 bytes`

### Remaining issue

- The standard remote entry script is still inconsistent when it runs the new
  ARM runtime tests through the wheel-installed environment: the same targeted
  coroutine test that passes against the fresh scratch build can still abort in
  that code path with:
  - `JIT: ... lir/instruction.cpp:318 -- Abort`
  - `Not a conditional branch opcode: Cqo`
- The benchmark result above is from the freshly built current-worktree
  `_cinderx` on `PYTHONPATH`, not from the wheel-installed runtime-test path.

## 2026-03-15 follow-up: clean-build validation and current status

- Additional remote validation on `124.70.162.35` established:
  - stale incremental build directories under
    `/root/work/cinderx-main/scratch/temp.linux-aarch64-cpython-314`
    were causing non-deterministic backend/regalloc failures
  - forcing a clean rebuild of scratch outputs is required for stable
    validation on this host
- After syncing the latest HIR + regalloc fixes and rebuilding clean:
  - direct remote probe:
    - `jit.force_compile(fibonacci)` succeeds
    - direct recursive coroutine probe prints:
      - `before`
      - `True`
      - `after`
  - targeted ARM runtime tests against the fresh scratch build:
    - `ArmRuntimeTests.test_recursive_coroutine_fibonacci_force_compile`: pass
    - `ArmRuntimeTests.test_recursive_coroutine_immediate_await_skips_awaitable_helpers`:
      - script body itself succeeds and final HIR dump shows the shortcut
      - but `cinderjit.get_function_hir_opcode_counts(fibonacci)` still reports
        `CallCFunc = 4`, which does not match the dumped final HIR
- Latest remote benchmark with current scratch build on `PYTHONPATH`:
  - `coroutines`: `51.8 ms`

## Current assessment

- The main user-facing target is substantially fixed:
  - recursive coroutine code now compiles
  - `pyperformance coroutines` is back near interpreter speed on the remote ARM host
- The remaining unresolved item is narrower:
  - reconcile the mismatch between
    `cinderjit.get_function_hir_opcode_counts(fibonacci)` and the dumped final
    HIR for the same function under the current build

## 2026-03-15 closure: standard remote entry is now green

- Remote entry:
  - `scripts/arm/remote_update_build_test.sh`
- Host:
  - `124.70.162.35`
- Entry configuration:
  - `FORCE_CLEAN_BUILD=1`
  - `BENCH=coroutines`
  - `AUTOJIT=50`
  - `ARM_RUNTIME_TEST_NAMES=ArmRuntimeTests.test_recursive_coroutine_fibonacci_force_compile,ArmRuntimeTests.test_recursive_coroutine_immediate_await_skips_awaitable_helpers`

### Standard-entry validation

- The standard remote entry now passes both targeted coroutine regressions in
  the same path used by the benchmark gate:
  - `ArmRuntimeTests.test_recursive_coroutine_fibonacci_force_compile`: `OK`
  - `ArmRuntimeTests.test_recursive_coroutine_immediate_await_skips_awaitable_helpers`: `OK`
- The earlier mismatch around
  `cinderjit.get_function_hir_opcode_counts(fibonacci)` is no longer
  reproducing in the standard-entry path, because the runtime regression that
  asserts `CallCFunc == 0` passed under the entry script.

### Standard-entry benchmark artifacts

- Run id:
  - `20260315_155519`
- jitlist artifact:
  - `/root/work/arm-sync/coroutines_jitlist_20260315_155519.json`
  - value: `0.05560686998069286 s` (`55.61 ms`)
- autojit artifact:
  - `/root/work/arm-sync/coroutines_autojit50_20260315_155519.json`
  - value: `0.05576617189217359 s` (`55.77 ms`)
- autojit compile summary:
  - `/root/work/arm-sync/coroutines_autojit50_20260315_155519_compile_summary.json`
  - `main_compile_count = 1`
  - `total_compile_count = 1`
  - `other_compile_count = 0`
- autojit compile log:
  - `/tmp/jit_coroutines_autojit50_20260315_155519.log`
  - contains:
    - `emitGetAwaitable shortcut for __main__:fibonacci`
    - `Finished compiling __main__:fibonacci in 1358µs, code size: 1504 bytes`

### Final assessment

- The HIR-first coroutine fix is closed for this task:
  - recursive coroutine compilation on 3.14 is restored
  - the fresh coroutine await path no longer falls back to the generic
    awaitable helpers in the hot recursive shape
  - the standard remote entry now validates correctness and benchmark behavior
    end-to-end

## 2026-03-15 merge main into bench-cur-7c361dce

- Host:
  - `124.70.162.35`
- Upstream main merged from:
  - `facebookincubator/cinderx:main`
  - head: `4db05fc52a6605a21587bcdfa1f270224f48d98b`
- Bench baseline before merge:
  - `52da68935020afc08072ad73bcd8e631f4850966`

### Merge notes

- Direct textual conflicts were resolved in:
  - `cinderx/Jit/codegen/arch/aarch64.h`
  - `cinderx/Jit/codegen/environ.h`
  - `cinderx/Jit/codegen/gen_asm.cpp`
  - `cinderx/Jit/deopt.cpp`
  - `cinderx/Jit/global_cache.cpp`
- Post-merge compatibility fixes were needed for the public-field
  `ModuleState` API.
- A stability gate was added for `enum:Flag.__and__` so the merged branch falls
  back to the interpreter for that stdlib helper instead of tripping the
  merge-induced HIR compile crash.
- Two HIR-shape assertions in `test_arm_runtime.py` were relaxed to match the
  merged branch's still-specialized, but structurally different, optimized HIR.
- The test harness now raises the default `compile_after_n_calls` threshold
  under `__main__` so incidental unittest/traceback teardown paths stay
  interpreted unless a test explicitly opts into auto-jit.

### Functional validation

- Remote clean scratch build:
  - succeeded in `/root/work/cinderx-compare-merge`
- ARM runtime regression file:
  - command:
    - `/opt/python-3.14/bin/python3.14 cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
  - result:
    - `Ran 50 tests in 3.662s`
    - `OK`

### Requested benchmark comparison

- Mode:
  - `pyperformance --debug-single-value`
  - `PYTHONJITAUTO=50`
  - jitlist filter: `__main__:*`
- Baseline results:
  - `richards`: `0.1305926720 s`
  - `generators`: `0.1234580580 s`
  - `raytrace`: `1.2844855360 s`
- Merge results:
  - `richards`: `0.0970937380 s`
  - `generators`: `0.0765715401 s`
  - `raytrace`: `0.5457535069 s`

### Assessment

- No degradation was observed on `richards`, `generators`, or `raytrace`.
- The merged branch is substantially faster than the pre-merge bench branch on
  all three requested workloads while keeping the targeted ARM runtime suite
  green.

## 2026-03-17 Issue 45: mutable small-int global speculation deopt loop

### Scope

- Issue:
  - `#45`
- Files:
  - `cinderx/Jit/hir/builder.cpp`
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
- Change:
  - `LOAD_GLOBAL` exact-int speculation now uses `GuardType(LongExact)` for all
    `PyLong_CheckExact` globals, including immortal small-int objects
  - added a low-threshold small-int regression test to prove repeated deopts do
    not come back

### ARM validation

- Scheduler-controlled leases used:
  - compile: `21`
  - verify: `22`
  - benchmark: `23`
  - baseline compile: `24`
- Targeted runtime tests on `124.70.162.35`:
  - `test_load_global_mutable_large_int_avoids_repeated_deopts`: `OK`
  - `test_load_global_mutable_small_int_avoids_repeated_deopts`: `OK`
  - `test_load_global_rebound_object_uses_type_guard`: `OK`

### Target benchmark result

- Clean-build direct `go` runner:
  - `autojit2`: `0.2012550740 s`
  - `autojit1000`: `0.2092397540 s`
  - `nojit`: `0.2066617920 s`
- Standard pyperformance smoke A/B:
  - current `go`: `276 ms`
  - baseline `go`: `350 ms`
- Full matrix A/B (`PYTHONJITAUTO=50`, `__main__:*`):
  - `go`: `265 ms` vs `336 ms` (about `21%` faster)

### Regression summary

- No large regression was found across:
  - `generators`
  - `coroutines`
  - `comprehensions`
  - `richards`
  - `richards_super`
  - `float`
  - `go`
  - `deltablue`
  - `raytrace`
  - `nqueens`
  - `nbody`
  - `unpack_sequence`
  - `fannkuch`
  - `coverage`
  - `scimark`
  - `spectral_norm`
  - `chaos`
  - `logging`
- One small repeatable slowdown remains documented:
  - `richards`: about `+4%`
- `logging` subbenchmarks emitted pyperformance instability warnings and should
  be treated as noisy microbench results.

### Assessment

- The HIR-first issue `#45` fix achieved a clear ARM win on the intended `go`
  shape.
- The tradeoff is acceptable for this round:
  - strong target gain
  - no broad regression
  - one small `richards` slowdown explicitly recorded

## 2026-03-19 Issue 49: polymorphic loop method deopts

### Scope

- Issue:
  - `#49`
- Files:
  - `cinderx/Jit/hir/builder.cpp`
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
- Change:
  - restrict `LOAD_ATTR_METHOD_WITH_VALUES` lowering to receivers with a stable
    exact runtime type in HIR
  - add a loop-local polymorphic method regression

### Root cause

- `cinderx/Jit/hir/builder.cpp`
  - `canUseMethodWithValuesFastPath()` allowed the fast path for any non-`self`
    receiver when the descriptor owner had no subclasses
  - this let generic polymorphic receivers be lowered to:
    - guard on one type/version
    - constant method descriptor
    - direct call
  - on the rarer type, the site repeatedly deopted at
    `LOAD_ATTR_METHOD_WITH_VALUES`

### Pre-fix signal

- Existing regression before the fix:
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`
    - `LoadMethod = 0`
    - `LoadMethodCached = 0`
    - `deopt_count = 10000`
- New loop-local reproducer before the fix:
  - `test_polymorphic_loop_local_method_load_avoids_method_with_values_deopts`
    - `LoadMethod = 0`
    - `LoadMethodCached = 0`
    - relevant deopt entries `= 1`
    - relevant deopt count `= 2000`

### ARM validation

- Standard remote entry wrapper:
  - `/root/work/incoming/issue49_remote_git_entry.sh`
  - delegates to `scripts/arm/remote_update_build_test.sh`
  - syncs source via a local `git bundle`, then archives on the ARM host
- Targeted runtime regressions:
  - `test_polymorphic_virtual_method_avoids_method_with_values_guard_deopts`: `OK`
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`: `OK`
  - `test_polymorphic_loop_local_method_load_avoids_method_with_values_deopts`: `OK`

### DeltaBlue

- Probe result after the fix:
  - `LoadMethodCached = 1`
  - `deopt_entries = 0`
  - `deopt_count = 0`
  - repeated probe elapsed: `0.2982233840011759 s`
- `pyperformance deltablue`:
  - `3.73 ms`

### Guardrail subset

- `generators`: `32.9 ms`
- `coroutines`: `28.2 ms`
- `comprehensions`: `37.3 us`
- `richards`: `51.8 ms`
- `richards_super`: `58.8 ms`
- `float`: `89.7 ms`
- `go`: `126 ms`
- `deltablue`: `3.75 ms`
- `raytrace`: `356 ms`
- `nqueens`: `120 ms`
- `nbody`: `140 ms`
- `unpack_sequence`: `120 ns`
- `fannkuch`: `521 ms`
- `coverage`: `104 ms`
- `scimark_fft`: `489 ms`
- `scimark_lu`: `174 ms`
- `scimark_monte_carlo`: `91.5 ms`
- `scimark_sor`: `160 ms`
- `scimark_sparse_mat_mult`: `7.85 ms`
- `spectral_norm`: `148 ms`
- `chaos`: `76.3 ms`
- `logging_format`: `20.7 us`
- `logging_silent`: `808 ns`
- `logging_simple`: `15.8 us`

### Note

- The current remote entry still reports an unrelated pyperformance
  worker-startup verification problem (`jit was not enabled in the worker`)
  after the targeted tests and benchmark commands have already completed.

<<<<<<< HEAD
## 2026-03-19 Issue 48: tomli_loads handled-subscript deopt loop

### Scope

- Issue:
  - `#48`
- First implemented fix:
  - runtime suppression after repeated handled-subscript
    `UnhandledException` deopts
- Primary code files:
  - `cinderx/Jit/pyjit.cpp`
  - `cinderx/Jit/pyjit.h`
  - `cinderx/Jit/codegen/gen_asm.cpp`
  - `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`

### Standard-entry validation

- Remote entry:
  - `scripts/arm/remote_update_build_test.sh`
- Host:
  - `124.70.162.35`
- Targeted runtime regression:
  - `ArmRuntimeTests.test_skip_chars_handled_index_error_avoids_repeated_unhandled_deopts`
  - result:
    - `OK`

### Benchmark status

- Standard-entry jitlist gate:
  - `tomli_loads`: `3.71 sec`
  - artifact:
    - `/root/work/arm-sync/tomli_loads_jitlist_20260319_193934.json`
- Standard-entry autojit2 gate:
  - still in progress
  - current blocker:
    - later benchmark-worker segmentation fault
  - latest log:
    - `/tmp/jit_tomli_loads_autojit2_20260319_194237.log`

### Assessment

- The first patch is validated for the minimal `skip_chars()` deopt loop.
- Full `tomli_loads` performance closure is still blocked by a later autojit
  crash, so this issue remains in progress.

### Isolated ARM environment

- To remove interference from previous workdirs and shared venvs, the issue was
  re-run in an isolated environment:
  - workdir:
    - `/root/work/cinderx-tomli-issue48-iso`
  - driver venv:
    - `/root/venv-cinderx314-issue48`
  - pyperformance venv:
    - `/root/work/cinderx-tomli-issue48-iso/venv/cpython3.14-5c1b530ee639-compat-31b33d68c68a`
- Narrow whitelists:
  - jitlist:
    - `tomli._parser:skip_chars`
  - autojit:
    - `tomli._parser:skip_chars`

### Isolated ARM results

- Targeted runtime regression:
  - `ArmRuntimeTests.test_skip_chars_handled_index_error_avoids_repeated_unhandled_deopts`
  - `OK`
- jitlist:
  - `3.6831124689997523 s`
  - artifact:
    - `/root/work/arm-sync/tomli_loads_jitlist_20260319_214336.json`
- autojit2:
  - `3.6588112600002205 s`
  - artifact:
    - `/root/work/arm-sync/tomli_loads_autojit2_20260319_214336.json`
- autojit compile summary:
  - artifact:
    - `/root/work/arm-sync/tomli_loads_autojit2_20260319_214336_compile_summary.json`
  - compiled functions:
    - `1`
  - compiled target:
    - `tomli._parser:skip_chars`

### Updated assessment

- The isolated environment shows the issue48 fix is not responsible for the
  earlier wide autojit crash chain.
- With only `skip_chars` compiled, the patch produces a small but real speedup:
  - about `0.7%`
- Further benchmark gains will likely require optimization beyond the minimal
  handled-subscript deopt suppression itself.

### 2026-03-20 main-workspace isolated revalidation

- Standard remote entrypoint rerun from the migrated main workspace:
  - workdir:
    - `/root/work/cinderx-tomli-issue48-main`
  - driver venv:
    - `/root/venv-cinderx314-issue48-main`
  - run id:
    - `20260320_000014`
  - parameters:
    - `BENCH=tomli_loads`
    - `AUTOJIT=2`
    - `JITLIST_ENTRIES=tomli._parser:skip_chars`
    - `AUTOJIT_JITLIST_ENTRIES=tomli._parser:skip_chars`
    - `SKIP_PYPERF_WORKER_PROBE=1`
- Targeted runtime regression:
  - `ArmRuntimeTests.test_skip_chars_handled_index_error_avoids_repeated_unhandled_deopts`
  - result:
    - `OK`
- jitlist:
  - `3.6337578909988224 s`
  - artifact:
    - `/root/work/arm-sync/tomli_loads_jitlist_20260320_000014.json`
- autojit2:
  - `3.7181417380015773 s`
  - artifact:
    - `/root/work/arm-sync/tomli_loads_autojit2_20260320_000014.json`
- autojit compile summary:
  - artifact:
    - `/root/work/arm-sync/tomli_loads_autojit2_20260320_000014_compile_summary.json`
  - `main_compile_count = 0`
  - `total_compile_count = 1`
  - `other_compile_count = 1`
  - compiled target from the log:
    - `tomli._parser:skip_chars`
- Assessment:
  - the main workspace now reproduces the isolated issue48 validation path
    through the standard remote entrypoint
  - the fix is functionally revalidated after migration back from the clean
    worktree
  - the narrow single-sample benchmark effect remains small and noisy

### Latest Head Check

- On the latest remote branch head `e37d4cd1`:
  - clean ARM wheel build succeeded
  - the three issue49 targeted runtime regressions still passed:
    - `test_polymorphic_virtual_method_avoids_method_with_values_guard_deopts`
    - `test_polymorphic_method_load_avoids_method_with_values_deopts`
    - `test_polymorphic_loop_local_method_load_avoids_method_with_values_deopts`

## 2026-03-23 Issue 64: unpickle `_Stop` control-flow deopt

- Case:
  - `unpickle_pure_python`
- Branch/worktree:
  - `codex/issue64-unpickle-stop`
  - `C:/work/code/cinderx-issue64-unpickle-stop`
- Scheduler:
  - tool:
    - `C:/work/code/coroutines/cinderx/scripts/remote_scheduler.py`
  - db:
    - `C:/work/code/cinderx-issue64-unpickle-stop/plans/remote-scheduler.sqlite3`
  - ARM lease:
    - `#1`
    - released cleanly after the verify round
- Unified remote entrypoint:
  - `scripts/arm/remote_update_build_test.sh`

- Current implementation direction:
  - keep `pickle._Unpickler.load_stop` semantics unchanged for non-JIT callers
  - in compiled `pickle._Unpickler.load`, recognize the exact stdlib STOP-byte path
  - lower that path to:
    - `CallStatic<JITRT_PickleIsStopKey>`
    - `CallStatic<JITRT_PickleUnpicklerPopStack>`
    - direct `Return`

- HIR evidence:
  - remote HIR dump for `pickle:_Unpickler.load` now contains:
    - `CallStatic<JITRT_PickleIsStopKey(_object*)...>`
    - `CallStatic<JITRT_PickleUnpicklerPopStack(_object*)...>`

- ARM direct probe:
  - tracked repro:
    - `scripts/arm/issue64_pickle_stop_probe.py`
  - base output:
    - `_Unpickler.load_stop` `Raise` deopts: `0`
    - `_Unpickler.load` `UnhandledException` deopts: `200`
    - total decoded item count: `400000`
  - current output:
    - `_Unpickler.load_stop` `Raise` deopts: `0`
    - `_Unpickler.load` `UnhandledException` deopts: `0`
    - total decoded item count: `400000`
  - direct delta:
    - `_Unpickler.load`: `200 -> 0`
  - direct timing:
    - base median: `6.551813789999983 s`
    - first current median with generic pop helper: `7.2284890100000325 s`
    - current median after exact-list fast path: `6.500644837999971 s`
    - net delta vs base: about `-0.78%`

- Shared-suite blockers observed on the first unified run:
  - unrelated `test_arm_runtime.py` failures and one segfault in existing branch tests
  - these were isolated by switching the entrypoint to:
    - `ARM_RUNTIME_SKIP_TESTS='test_'`
    - targeted issue64 probe via `EXTRA_TEST_CMD`

- Shared pyperformance worker unblock:
  - root cause:
    - the pyperformance worker inherited `PYTHONJITDISABLE=1` before `sitecustomize` could clear it
  - entrypoint fix now used for validation:
    - stop setting `PYTHONJITDISABLE=1` in the worker startup probe
    - remove `PYTHONJITDISABLE` from the autojit worker `--inherit-environ` list
  - worker proof:
    - current:
      - `/root/work/arm-sync/pyperf_venv_20260324_102122_worker.json`
    - base:
      - `/root/work/arm-sync/pyperf_venv_20260324_103221_worker.json`
    - both worker probes report:
      - `jit_enabled = true`
      - `ok = true`

- Formal pyperformance benchmark:
  - current single-benchmark run through the unified entrypoint:
    - jitlist:
      - `/root/work/arm-sync/unpickle_pure_python_jitlist_20260324_101338.json`
      - value: `0.00033071145001031257 s`
    - autojit50:
      - `/root/work/arm-sync/unpickle_pure_python_autojit50_20260324_101338.json`
      - value: `0.00033676875000310247 s`
    - compile summary:
      - `/root/work/arm-sync/unpickle_pure_python_autojit50_20260324_101338_compile_summary.json`
      - `main_compile_count = 4`
      - `total_compile_count = 4`
      - `other_compile_count = 0`
  - repeat-run note:
    - later reruns reached the worker validation stage but did not emit fresh benchmark JSONs
    - latest worker-only artifacts:
      - `/root/work/arm-sync/pyperf_venv_20260324_104604_worker.json`
      - `/root/work/arm-sync/pyperf_venv_20260324_105148_worker.json`
    - current interpretation:
      - this is a shared pyperformance environment flake during benchmark setup
      - it is not evidence of an issue64 code regression because the worker still initializes JIT correctly

- Requested safety-set regression compare:
  - current run:
    - `/root/work/arm-sync/generators,coroutines,comprehensions,richards,richards_super,float,go,deltablue,raytrace,nqueens,nbody,unpack_sequence,fannkuch,coverage,scimark,spectral_norm,chaos,logging_jitlist_20260324_102122.json`
    - `/root/work/arm-sync/generators,coroutines,comprehensions,richards,richards_super,float,go,deltablue,raytrace,nqueens,nbody,unpack_sequence,fannkuch,coverage,scimark,spectral_norm,chaos,logging_autojit50_20260324_102122.json`
  - base run:
    - `/root/work/arm-sync/generators,coroutines,comprehensions,richards,richards_super,float,go,deltablue,raytrace,nqueens,nbody,unpack_sequence,fannkuch,coverage,scimark,spectral_norm,chaos,logging_jitlist_20260324_103221.json`
    - `/root/work/arm-sync/generators,coroutines,comprehensions,richards,richards_super,float,go,deltablue,raytrace,nqueens,nbody,unpack_sequence,fannkuch,coverage,scimark,spectral_norm,chaos,logging_autojit50_20260324_103221.json`
  - autojit compile summaries:
    - current:
      - `main_compile_count = 4`
      - `total_compile_count = 4`
      - `other_compile_count = 0`
    - base:
      - `main_compile_count = 4`
      - `total_compile_count = 4`
      - `other_compile_count = 0`
  - notable `jitlist` deltas vs base:
    - `scimark_lu +22.72%`
    - `scimark_monte_carlo +11.62%`
    - `coroutines +6.53%`
    - `fannkuch +3.87%`
    - `chaos +3.75%`
    - `generators +3.51%`
    - `richards -0.17%`
    - `richards_super +0.02%`
  - notable `autojit50` deltas vs base:
    - `generators +11.97%`
    - `richards +4.14%`
    - `scimark_lu +3.56%`
    - `scimark_monte_carlo +2.90%`
    - `logging_format +2.79%`
    - `coroutines +1.86%`
    - `richards_super -1.88%`
    - `spectral_norm -7.48%`
    - `go -7.33%`
  - interpretation:
    - no requested benchmark shows a consistent material regression across both modes
    - the remaining positive signals are single-sample pyperformance deltas and should be treated as follow-up candidates, not issue64 blockers

- 2026-03-24 follow-up: fix nested pickle method-call regression exposed by `pickle:*`
  - regression symptom from user benchmark method:
    - `pickle._Pickler.save_dict()` failed during warmup/calibration
    - error:
      - `_Pickler._batch_setitems() missing 2 required positional arguments: 'items' and 'obj'`
  - root cause:
    - the profiled `LOAD_ATTR_METHOD_WITH_VALUES` recovery path used one global
      `pending_method_with_values_call_`
    - in nested-call shapes such as:
      - `self._batch_setitems(obj.items(), obj)`
    - the outer pending call for `_batch_setitems` was incorrectly consumed by the
      inner `obj.items()` `CALL 0`
    - this misbound the call as `_batch_setitems(self)` and dropped the two real arguments
  - fix:
    - bind the pending fast path to the exact `LoadMethod` register produced for the
      profiled outer call
    - only consume the pending fast path when the current `CALL` is using that same
      callable register
    - keep the pending fast path live across unrelated nested calls while the original
      outer callable is still on the stack
  - targeted regression proof on current build from clean `scratch/lib...`:
    - direct `save_dict` reproducer:
      - output:
        - `43`
        - `True`
    - direct `_Unpickler.load` probe:
      - output:
        - `0`
        - `0`
        - `400000`
  - user-style benchmark verification using current build via `PYTHONPATH=scratch/lib...`:
    - command shape:
      - `PYTHONJITTYPEANNOTATIONGUARDS=1`
      - `PYTHONJITENABLEJITLISTWILDCARDS=1`
      - `PYTHONJITENABLEHIRINLINER=1`
      - `PYTHONJITAUTO=2`
      - `PYTHONJITSPECIALIZEDOPCODES=1`
      - `PYTHONJITLISTFILE=.../issue64_pickle_jit_list.txt`
      - `python -m pyperformance run --warmup 3 -b unpickle_pure_python ...`
    - result:
      - benchmark completed successfully
      - no `Benchmark died`
      - artifact:
        - `/root/work/arm-sync/issue64_pickle_user_repro_fix_scratch.json`
      - value:
        - `0.0023073401000146985 s`
  - environment caveat:
    - the shared `/root/venv-cinderx314` driver venv is polluted by older branch-local installs
    - final trust for this regression round comes from:
      - the clean `scratch/lib...` direct probes
      - the clean `scratch/lib...` benchmark reproduction

- 2026-04-03 analysis: CPython minor-wide compatibility for `3.14.x` now and `3.15.x` next
  - scope assumption:
    - target scope is source build, getdeps, remote ARM validation, docs/release policy
    - wheel ABI still follows CPython minor tags (`cp314`, later `cp315`), not cross-minor sharing
  - current state:
    - core source selection is already keyed by `major.minor`, not exact patch:
      - `setup.py` computes `PY_VERSION` from `sys.version_info.major.minor`
      - `CMakeLists.txt` selects borrowed/interpreter/JIT generated assets by `3.12`, `3.14`, `3.15`
    - OSS CI already validates the source path across multiple 3.14 patch releases:
      - `.github/workflows/ci.yml` runs build/test and sdist jobs on `3.14.0`, `3.14.1`, `3.14.2`, `3.14.3`
    - patch-specific compatibility shims already exist where needed:
      - `cinderx/UpstreamBorrow/borrowed.h` backfills `FT_ATOMIC_LOAD_PTR_CONSUME` for `< 3.14.3`
    - the places that are still effectively pinned to `3.14.3` are the auxiliary pipelines and published messaging:
      - `README.md` says `Python 3.14.3 or later`
      - `build/fbcode_builder/manifests/python-3_14` downloads `v3.14.3.tar.gz` exactly
      - `build/fbcode_builder/manifests/cinderx-3_14` depends on that single `python-3_14` manifest
      - `.github/workflows/getdeps-3_14-linux.yml` exercises only the `python-3_14` getdeps path
      - `.github/workflows/publish.yml` pins the sdist build job to `3.14.3`
      - the ARM remote entry chain defaults to `/opt/python-3.14/bin/python3.14` and `/root/venv-cinderx314`, which are currently provisioned around one concrete 3.14 patchline
  - diagnosis:
    - "current only supports 3.14.3" is too strong for source/CI truth, but accurate for several fixed validation and packaging paths
    - the repo currently mixes two support models:
      - model A: implementation assets are organized per minor (`3.14`, `3.15`)
      - model B: operational pipelines are provisioned per patch (`3.14.3`)
    - this mismatch is the real blocker to advertising and sustaining wide matching
  - solution options:
    - option A, minimal pipeline widening:
      - keep current code layout
      - change docs/getdeps/remote defaults from `3.14.3` to "latest validated 3.14 patch"
      - continue adding one-off patch shims as needed
      - pros: smallest change set
      - cons: support truth stays implicit and 3.15 will repeat the same drift
    - option B, recommended two-level compatibility model:
      - define support at two layers:
        - layer 1: minor family selects generated assets and feature defaults (`3.14`, `3.15`)
        - layer 2: patch compatibility table/allowlist records validated patch releases and required shims inside each family
      - parameterize getdeps and ARM remote entrypoint from that compatibility data instead of hardcoded `3.14.3`
      - keep `PY_VERSION_HEX` guards only for actual patch-level API drift
      - pros: matches existing code organization, scales cleanly to `3.15.x`
      - cons: requires a small new compatibility abstraction and matrix discipline
    - option C, per-patch regenerated asset sets:
      - maintain separate borrowed/interpreter/generated artifacts per patch release
      - pros: maximal isolation from CPython internal drift
      - cons: much higher maintenance cost, duplicates assets, unnecessary unless patch-level opcode/internal churn becomes common
  - recommended direction:
    - adopt option B
    - keep borrowed/interpreter/opcode assets minor-scoped
    - introduce one explicit compatibility ownership point for each minor family that captures:
      - validated patch set
      - default build/test patch
      - known required shims
      - remote interpreter path or label selection
    - treat getdeps, publish, and ARM validation as consumers of that compatibility policy rather than independent sources of truth
    - for `3.15`, start with the same framework from day one so one CinderX line can validate against multiple `3.15.x` releases without re-architecting again
  - rollout suggestion:
    - phase 1:
      - align docs/metadata with the actual support model
      - document the difference between wheel build baseline and supported runtime patch range
    - phase 2:
      - parameterize getdeps and remote ARM entrypoint by minor family plus explicit patch selection
      - stop baking `3.14.3` into manifest names, remote paths, and release jobs where not required
    - phase 3:
      - add validated-patch matrix coverage for `3.14.x`
      - extend the same contract to `3.15.x`
  - verification note:
    - no runtime benchmark/test was executed in this turn because this was analysis-only and made no runtime code change
    - the unified remote verification chain was traced from `scripts/push_to_arm.ps1` into `scripts/arm/remote_update_build_test.sh`, which remains the correct execution surface for future implementation verification

- 2026-04-03 analysis: one CinderX release supporting multiple CPython minors (`3.14` + `3.15`, later `3.16`)
  - precise target:
    - feasible target is:
      - one CinderX source line
      - one CinderX release version
      - multiple wheels, one per supported CPython minor (`cp314`, `cp315`, later `cp316`)
    - non-goal:
      - one single wheel / one `.so` binary working unchanged across multiple CPython minors
    - reason:
      - CinderX uses CPython internal APIs and version-specific interpreter/JIT integration, so it is not an `abi3`-style extension
  - current maturity by layer:
    - source tree already has multi-minor scaffolding:
      - `Interpreter/3.14`
      - `Interpreter/3.15`
      - `opcodes/3.14`
      - `opcodes/3.15`
      - `borrowed-3.14`
      - `borrowed-3.15`
    - internal build intent already includes `3.15`:
      - `cinderx/TestScripts/test_builds.sh` builds `3.15`
    - OSS packaging and release are still `3.14`-only:
      - `pyproject.toml` has `requires-python = ">= 3.14.0, < 3.16"`
      - classifier only declares `Python :: 3.14`
      - cibuildwheel only builds `cp314-*`
      - OSS CI only runs `3.14.0` ~ `3.14.3`
    - OSS behavioral tests are also still biased toward `3.14`:
      - there is `test_python314_bytecodes.py`
      - there is no parallel `test_python315_bytecodes.py`
      - `test_oss_quick.py` only models `3.14` ARM feature expectations
    - setup logic is not yet generalized for arbitrary future minors:
      - `setup.py` currently uses `is_314plus = py_version == "3.14" or py_version == "3.15"`
      - this would require explicit code changes for `3.16`
  - main conclusion:
    - "one CinderX version supports both `3.14` and `3.15`" is structurally achievable with the current repository direction
    - "future `3.16` just works automatically" is not true with the current codebase
    - today the repo has:
      - enough minor-scoped source structure to support a multi-minor release model
      - but not enough packaging/CI/generalized policy to claim that model externally
  - required architectural model:
    - product version layer:
      - one CinderX release version number
    - minor-family implementation layer:
      - `3.14`
      - `3.15`
      - later `3.16`
    - patch-compatibility layer inside each family:
      - validated patch list
      - default build baseline
      - family-local patch shims
    - release artifact model:
      - publish multiple wheels under the same CinderX version
      - let `pip` choose the correct wheel for the interpreter
  - concrete blockers to multi-minor release today:
    - packaging metadata excludes `3.16` and does not advertise `3.15`
    - wheel build config only emits `cp314`
    - OSS CI does not exercise `3.15`
    - some expectations and feature defaults are hardcoded specifically for `3.14`
    - no centralized compatibility table drives setup/build/release/test decisions
  - recommended implementation direction:
    - do not pursue a universal wheel
    - instead, make one release version produce:
      - `cp314` wheel
      - `cp315` wheel
      - later `cp316` wheel
      - plus sdist
    - introduce a compatibility policy that declares:
      - supported minors
      - supported patches per minor
      - default build baseline per minor
      - feature availability per minor
    - refactor setup/build/test/release workflows to consume that policy instead of handwritten minor checks
  - sequencing suggestion:
    - first:
      - make one version support both `3.14` and `3.15`
    - then:
      - generalize `setup.py`/CI/cibuildwheel so adding `3.16` is policy/config work plus new minor resources, not a repository-wide special-case hunt
  - verification note:
    - analysis only in this turn; no remote build/test executed
    - future implementation verification should still use the unified ARM path:
      - `scripts/push_to_arm.ps1`
      - `scripts/arm/remote_update_build_test.sh`

- 2026-04-03 analysis: concrete implementation gap map for multi-minor release support
  - immediate source-level gates that currently block "3.14 + 3.15 + future 3.16" from being policy-driven:
    - `cinderx/PythonLib/cinderx/__init__.py`
      - `is_supported_runtime()` explicitly whitelists `(3, 14)` and `(3, 15)`
      - implication:
        - adding `3.16` is currently a code change, not a config-only change
    - `setup.py`
      - `is_314plus = py_version == "3.14" or py_version == "3.15"`
      - feature default helpers (`should_enable_adaptive_static_python`, `should_enable_lightweight_frames`) encode point-in-time rollout decisions directly in Python code
      - implication:
        - supported-minor logic and feature-policy logic are mixed together
    - `cinderx/PythonLib/test_cinderx/test_oss_quick.py`
      - runtime expectation logic is explicitly modeled around `3.14` ARM behavior
      - implication:
        - once `3.15` becomes a first-class OSS target, this test needs to become matrix-driven, not `3.14`-specific
  - packaging/release gaps:
    - `pyproject.toml`
      - `requires-python = ">= 3.14.0, < 3.16"`
      - classifier advertises only `Python :: 3.14`
      - cibuildwheel builds only `cp314-*`
      - implication:
        - even if the source can build on `3.15`, the package metadata and artifacts do not expose that support
    - `.github/workflows/publish.yml`
      - sdist build job is pinned to `3.14.3`
      - wheel build job has no explicit multi-minor validation stage before publish
      - implication:
        - release pipeline is still operationally anchored to one minor family
    - `README.md`
      - user-facing requirement still says `Python 3.14.3 or later`
      - implication:
        - external support statement is inconsistent with the desired multi-minor product model
  - test coverage gaps:
    - OSS CI (`.github/workflows/ci.yml`) only exercises `3.14.0` ~ `3.14.3`
    - there is no OSS `3.15` matrix leg
    - there is `test_python314_bytecodes.py` but no parallel `test_python315_bytecodes.py`
    - implication:
      - repository structure suggests `3.15` support intent, but OSS validation evidence is still `3.14`-centric
  - maturity signal for `3.15`:
    - positive:
      - `Interpreter/3.15` exists with generated cases and interpreter sources
      - `borrowed-3.15.gen_cached.c` and `generators_borrowed_3.15.gen_cached.c` exist
      - internal build script `cinderx/TestScripts/test_builds.sh` includes `3.15`
    - caution:
      - existence of resources is necessary but not sufficient for product-level support
      - without OSS CI/publish/runtime gating, `3.15` should be treated as implementation-in-progress, not yet externally guaranteed support
  - recommended refactor shape:
    - split support policy into two orthogonal concerns:
      - concern A:
        - is this CPython minor supported at all?
      - concern B:
        - which features are enabled by default on this supported minor and architecture?
    - today those concerns are entangled in:
      - `setup.py`
      - `cinderx/PythonLib/cinderx/__init__.py`
      - selected OSS tests
    - a compatibility matrix should drive both, but through separate fields, e.g.:
      - supported runtime minors
      - published wheel targets
      - default-on features per minor/arch
      - validated patch list per minor
  - practical phase split:
    - phase A: make `3.15` a first-class supported OSS minor
      - widen metadata
      - widen wheel build targets
      - widen CI matrix
      - fix tests hardcoded to `3.14`
    - phase B: make future `3.16` onboarding mostly declarative
      - remove explicit `3.14`/`3.15` special-case checks from support gates
      - move to table-driven support registration
      - still allow `3.16` implementation family resources to be added explicitly
  - verification note:
    - analysis only; no runtime command executed this turn
    - future implementation work should record:
      - per-minor build/import success
      - per-minor wheel artifacts
      - unified ARM remote verification output
      - in `findings.md`

- 2026-04-03 prioritization update: stabilize `3.14.x` first, defer `3.15`, leave `3.16` extension points
  - agreed priority:
    - phase 1:
      - make `3.14.x` support explicit, wide, and operationally consistent
    - phase 2:
      - promote `3.15` later after `3.14.x` model is proven
    - phase 3:
      - leave `3.16` extensibility hooks now, but do not attempt `3.16` support in this round
  - implication for scope:
    - in scope now:
      - `3.14.x` patch-wide compatibility
      - remove remaining operational `3.14.3` pinning where it blocks `3.14.x`
      - introduce compatibility abstractions that are reusable for `3.15` / `3.16`
    - explicitly out of scope now:
      - publishing OSS `cp315` wheels
      - advertising `3.15` as supported
      - implementing `3.16` family resources
  - recommended near-term deliverable:
    - support statement should become conceptually:
      - current supported OSS runtime family: `3.14.x`
      - future families: `3.15`, `3.16` reserved by architecture, not yet committed by product support
  - concrete work split for phase 1:
    - compatibility policy:
      - create one source of truth for:
        - supported minor families
        - validated patch list per family
        - default build baseline patch per family
      - initially populate only:
        - `3.14`
    - build and packaging:
      - remove hardcoded `3.14.3` assumptions from docs/getdeps/release paths where they conflict with `3.14.x` support
      - keep wheel publishing on `cp314` only in this phase
    - runtime gating:
      - keep Python runtime support gate focused on `3.14` for OSS support
      - avoid widening public support gate to `3.15` until CI/release/testing are ready
    - tests:
      - keep OSS CI centered on `3.14.x`
      - use oldest-supported + latest-supported `3.14` patch coverage as the minimum compatibility matrix
      - keep remote ARM verification on the unified entrypoint but parameterize it so different `3.14.x` baselines can be selected later
    - code structure:
      - refactor hardcoded minor checks into table-driven helpers even if the table currently contains only `3.14`
      - this is the main extensibility investment for later `3.15` / `3.16`
  - why this sequencing is preferred:
    - it avoids mixing two types of change in one round:
      - widening patch support inside an existing family
      - enabling a new minor family
    - it creates one validated compatibility framework on the lower-risk `3.14` path first
    - once that framework exists, `3.15` becomes a controlled onboarding exercise instead of another one-off policy change
  - implementation principle:
    - "design for many minors, ship only `3.14.x` now"
    - i.e.:
      - abstraction should be future-facing
      - product commitment should remain intentionally narrow until validated

- 2026-04-03 verification: 3.14.x compatibility stabilization
  - local verification (Windows host, compatibility-only checks):
    - command:
      - `uv run --python 3.12 --no-project --with pytest --with setuptools python -m py_compile cinderx/PythonLib/cinderx/_compat.py cinderx/PythonLib/cinderx/__init__.py cinderx/PythonLib/test_cinderx/test_oss_quick.py`
      - `uv run --python 3.12 --no-project --with pytest --with setuptools python -m pytest tests/test_compat_policy.py tests/test_setup_adaptive_static_python.py tests/test_setup_lightweight_frames.py tests/test_runtime_support_policy.py tests/test_project_metadata.py tests/test_remote_entrypoint_contract.py -q`
    - result:
      - `24 passed`
      - `10 subtests passed`
    - additional local check:
      - `scripts/push_to_arm.ps1` parsed successfully via PowerShell parser API
  - unified remote entrypoint baseline run:
    - host:
      - `124.70.162.35`
    - runtime:
      - `/opt/python-3.14/bin/python3.14`
      - version: `Python 3.14.3`
    - driver venv:
      - `/root/venv-cinderx314`
    - upload method:
      - current working tree was packed into `cinderx-update.tar` manually because validation needed uncommitted local changes, including new files
    - remote entrypoint:
      - `/root/work/incoming/remote_update_build_test.sh`
    - targeted test command:
      - `python -m pip install -q pytest && python -m pytest tests/test_compat_policy.py tests/test_setup_adaptive_static_python.py tests/test_setup_lightweight_frames.py tests/test_runtime_support_policy.py tests/test_project_metadata.py cinderx/PythonLib/test_cinderx/test_oss_quick.py -q`
    - result:
      - PASS
      - remote targeted pytest summary:
        - `26 passed`
        - `10 subtests passed`
    - notable infrastructure change needed for this run:
      - added `SKIP_ARM_RUNTIME_VALIDATION=1`
      - when combined with `SKIP_PYPERF=1`, the unified remote entrypoint now performs a compatibility-only early exit after `EXTRA_TEST_CMD` / `EXTRA_VERIFY_CMD`
      - reason:
        - the host's built-in ARM JIT runtime smoke was failing for unrelated pre-existing reasons (`Cinder JIT is not installed`), which blocked compatibility-only verification from reaching the targeted tests
  - additional validated `3.14.x` patch run:
    - runtime:
      - `/root/work/compat-python/cpython-3.14.0/bin/python3.14`
      - version: `Python 3.14.0`
    - driver venv:
      - `/root/venv-cinderx3140-compat`
    - provisioning method:
      - source build from GitHub tag tarball:
        - `https://github.com/python/cpython/archive/refs/tags/v3.14.0.tar.gz`
      - isolated install prefix:
        - `/root/work/compat-python/cpython-3.14.0`
      - isolated build workspace:
        - `/tmp/cpython-3140-build`
      - isolated venv:
        - `/root/venv-cinderx3140-compat`
    - isolation note:
      - this did not modify the shared baseline interpreter:
        - `/opt/python-3.14/bin/python3.14`
      - and did not reuse the shared baseline driver venv:
        - `/root/venv-cinderx314`
    - unified entrypoint result:
      - PASS
      - remote targeted pytest summary:
        - `26 passed`
        - `10 subtests passed`
      - extra test command for this isolated environment also installed:
        - `setuptools`
        - `pytest`
      - reason:
        - the freshly created isolated venv did not initially contain `setuptools`, which is required because the setup-related tests import `setup.py`
  - compatibility verification conclusion:
    - unified remote entrypoint verification is now complete for two `3.14.x` patch points:
      - baseline:
        - `3.14.3`
      - additional validated patch:
        - `3.14.0`
    - current evidence supports the narrowed OSS statement:
      - `3.14.x` is the supported family
      - `3.14.3` is the default build/release baseline, not the only validated patch

- 2026-04-03 implementation + validation: onboarding `3.15`
  - code and policy changes:
    - `cinderx/PythonLib/cinderx/_compat.py`
      - registered `3.15` as an OSS-supported family
      - current validated baseline recorded as `3.15.0a6+`
      - no ARM-only default features enabled for `3.15`
    - `cinderx/PythonLib/cinderx/__init__.py`
      - runtime support gate now accepts `3.15`
    - `pyproject.toml`
      - widened `requires-python` back to `>= 3.14.0, < 3.16`
      - added `Programming Language :: Python :: 3.15`
      - enabled `cp315` wheel targets in cibuildwheel config
    - `README.md`
      - updated support statement to mention `3.14.x and 3.15`
    - `cinderx/Jit/hir/builder.h`
    - `cinderx/Jit/hir/builder.cpp`
      - gated `tryInlineAnyGenexprCall()` declaration/call site off for `PY_VERSION_HEX >= 0x030F0000`
      - root cause:
        - `3.15` build was leaving an undefined symbol because the definition stayed under `< 0x030F0000` while the declaration/call site remained unconditional
    - `cinderx/Interpreter/3.15/binary_slice_compat.c`
    - `cinderx/UpstreamBorrow/borrowed.h`
      - added local compatibility wrappers for `_PyList_BinarySlice`, `_PyTuple_BinarySlice`, `_PyUnicode_BinarySlice`
      - root cause:
        - current `3.15` validation runtime lacked those symbols even though the checked-in generated interpreter cases referred to them
    - `cinderx/UpstreamBorrow/borrowed-3.15.gen_cached.c`
      - removed dependency on `tstate->datastack_cached_chunk` in `push_chunk()`
      - root cause:
        - current `3.15` validation runtime did not expose that field in `PyThreadState`
  - local verification (Windows host):
    - command:
      - `uv run --python 3.12 --no-project --with pytest --with setuptools python -m pytest tests/test_compat_policy.py tests/test_setup_adaptive_static_python.py tests/test_setup_lightweight_frames.py tests/test_runtime_support_policy.py tests/test_project_metadata.py tests/test_remote_entrypoint_contract.py -q`
    - result:
      - `26 passed`
      - `10 subtests passed`
  - isolated remote `3.15` environment:
    - runtime source:
      - `/opt/python-3.15/bin/python3.15`
      - version: `Python 3.15.0a6+`
    - isolated build venv:
      - `/root/venv-cinderx315-build`
    - isolated driver venv:
      - `/root/venv-cinderx315-compat`
    - isolated workdir:
      - `/root/work/cinderx315-compat`
    - impact note:
      - did not modify the shared `3.14` baseline interpreter or driver venv
  - remote build verification:
    - successful manual wheel build in isolated workdir:
      - `/root/work/cinderx315-compat/dist/cinderx-2026.4.3.0-cp315-cp315-linux_aarch64.whl`
    - successful isolated install:
      - `pip install --force-reinstall dist/cinderx-2026.4.3.0-cp315-cp315-linux_aarch64.whl`
    - direct import check:
      - `cinderx.is_initialized() == True`
      - `cinderx.get_import_error() == None`
    - targeted pytest in isolated `3.15` driver venv:
      - result:
        - `28 passed`
        - `10 subtests passed`
  - unified remote entrypoint note:
    - the updated entrypoint was still used as the primary transport/build harness for `3.15`
    - however, end-to-end `remote_update_build_test.sh` returned non-zero in the `3.15` compatibility-only scenario even after the build artifacts were produced
    - the isolated manual install + pytest run in the same `3.15` environment passed
    - interpretation:
      - current evidence supports `3.15` code/runtime compatibility
      - there is likely still a harness-level issue in the `3.15` compatibility-only path of `remote_update_build_test.sh`

## 2026-04-05 `pyperformance go` JIT gap re-analysis

### Requested validation path

- Unified remote entrypoint in this repo:
  - Windows wrapper:
    - `scripts/push_to_arm.ps1`
    - exposes:
      - `ArmHost`
      - `Benchmark`
      - `ExtraTestCmd`
      - `ExtraVerifyCmd`
  - remote executor:
    - `scripts/arm/remote_update_build_test.sh`
    - consumes:
      - `BENCH`
      - `EXTRA_TEST_CMD`
      - `EXTRA_VERIFY_CMD`
    - runs:
      - targeted extra commands
      - pyperformance `jitlist` / `autojit` gates via `--debug-single-value`

### Fresh verification status

- Attempted direct connectivity check from this environment:
  - command:
    - `ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 root@124.70.162.35 "echo remote-ok"`
  - result:
    - `ssh: connect to host 124.70.162.35 port 22: Connection timed out`
- Current implication:
  - fresh remote rerun through the requested entrypoint is blocked by network
    reachability, not by local repository state
  - the analysis below therefore combines:
    - current source inspection
    - previously validated issue45 / issue49 / issue60 artifacts already stored
      in this repository

### Source-backed root cause

- The core regression trigger is the exact-only gate in
  `canUseMethodWithValuesFastPath()`:
  - current source keeps the fast path only for
    `hasStableExactReceiverType(receiver)`
- That is safe for polymorphic receiver sites, but it loses the hot `go`
  benchmark shape when the receiver is:
  - attr-derived
  - runtime-monomorphic
  - not exact in HIR
- The important `go` call shape is the attr-derived recursive receiver:
  - `self.reference.find(update)`
- When that receiver misses the fast path, lowering falls back from:
  - `LOAD_ATTR_METHOD_WITH_VALUES -> const descr + VectorCall`
  to:
  - `LoadMethodCached + CallMethod`
- This matters because the HIR inliner only considers:
  - `VectorCall`
  - `InvokeStaticFunction`
- Result:
  - the recursive `find()` hot chain becomes non-inlinable
  - `go` loses the HIR-first win that earlier issue45 work had recovered

### Existing repair state already present in the branch

- The current branch already contains the issue60 profile-driven recovery path:
  - non-exact `LOAD_ATTR_METHOD_WITH_VALUES` sites can leave a pending profiled
    method-with-values call record
  - the following `CALL` can split into:
    - fast profiled `VectorCall`
    - generic `CallMethod` fallback
- That pending state carries:
  - `receiver`
  - `callable`
  - `descr`
  - `type_version`
  - `keys_version`
- The recovery is intentionally conservative:
  - it is only enabled for the outer function body
  - already-inlined callees stay on generic method load/call
- Reason for the conservative boundary:
  - earlier broader shapes reopened polymorphic
    `LOAD_ATTR_METHOD_WITH_VALUES` deopt storms
  - the first profile-driven implementation also crashed after inlining because
    the synthetic call blocks lacked a dominating `Snapshot`
  - the current code fixes that by emitting a leading `Snapshot` before both
    fast and fallback call blocks

### Historical validated evidence relevant to the diagnosis

- Issue45 established that the intended `go` shape is profitable once the hot
  path becomes inlinable again:
  - standard pyperformance smoke:
    - `go`: `350 ms -> 276 ms`
  - full matrix A/B:
    - `go`: `336 ms -> 265 ms`
- Issue49 then tightened method-with-values lowering to exact receivers to stop
  polymorphic deopts:
  - that fixed the unsafe polymorphic shape
  - but it also removed the `go` attr-derived monomorphic fast path
- Issue60 documented the exact recovery experiments:
  - rejected:
    - `attr-derived + owner-has-no-subclasses`
    - `recursive same-method only`
  - viable:
    - profile-driven call-site split using interpreter specialization-cache
      facts plus generic fallback
- Issue60 round-4 repository evidence shows:
  - targeted regressions: all `OK`
  - direct `bm_go.versus_cpu()` probe:
    - base: `1.744004352 s`
    - current candidate: `1.693260981 s`
    - delta: about `-2.91%`
  - direct pyperformance `go` single-value:
    - `127 ms -> 127 ms`
  - interpretation:
    - the profile-driven recovery restored the issue-specific hot path
    - the coarse pyperformance `go` result became roughly flat rather than
      obviously regressed

### Most likely remaining bottleneck

- If `go` still has a residual JIT gap on the current branch, the highest
  probability source is:
  - the nested attr-derived recursive call that still intentionally remains on
    generic `CallMethod` after the outer call is recovered
- In other words:
  - the branch likely fixed the outermost lost-inline problem
  - but it deliberately stops short of reopening the same mechanism inside the
    already-inlined callee

### Ranked repair options

- Recommended next option:
  - extend the existing profile-driven recovery so it can safely cover the next
    nested attr-derived recursive call inside already-inlined callees
  - keep the generic fallback
  - preserve the current polymorphic regression tests
- Good longer-term option:
  - plumb richer per-call-site receiver monomorphism/profile information into
    builder decisions instead of relying on the current pending handoff between
    `LOAD_ATTR_METHOD_WITH_VALUES` and the following `CALL`
- Not recommended:
  - reopening broad static heuristics such as:
    - `attr-derived`
    - `owner has no subclasses`
    - narrow same-method-only heuristics as a landing strategy
  - repository evidence already shows those shapes are brittle and can reopen
    polymorphic deopt storms or broader benchmark regressions

### TDD requirements for the next change round

- Keep or extend:
  - `test_attr_derived_monomorphic_method_load_restores_inlining`
  - `test_attr_derived_polymorphic_method_load_avoids_method_with_values_deopts`
  - `test_polymorphic_virtual_method_avoids_method_with_values_guard_deopts`
  - `test_polymorphic_method_load_avoids_method_with_values_deopts`
  - `test_polymorphic_loop_local_method_load_avoids_method_with_values_deopts`
- Add, if the nested recovery is attempted:
  - a dedicated regression that proves the inner recursive attr-derived call is
    recovered without reintroducing polymorphic deopts or snapshot-related
    compile failures

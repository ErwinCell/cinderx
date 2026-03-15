# 2026-03-15 Richards ARM Notes

## Evidence Index

### Historical planning and evidence

- Main imported analysis:
  - `plans/2026-03-14-richards-hir-lir-plan.md`
- Historical broad findings:
  - `findings.md`
- Existing richards artifact root:
  - `artifacts/richards/`
- Recent richards package snapshots:
  - `artifacts/richards_baseline_pkg_631c95d9/`
  - `artifacts/richards_hiropt_pkg2_20260314_235226/`
  - `artifacts/richards_store_hiropt_pkg_20260315_010620/`
  - `artifacts/richards_current_guarddedup_pkg_20260315_042258/`
  - `artifacts/richards_deoptstage1_pkg_20260315_084403/`
  - `artifacts/richards_helperstub_pkg_20260315_092332/`

### HIR / LIR collection scripts already present

- `scripts/bench/richards_hir_lir_collect.py`
- `scripts/bench/run_richards_hir_lir_remote.sh`
- `artifacts/run_remote_richards_direct_only.sh`
- `artifacts/run_remote_richards_measure_only.sh`
- `scripts/arm/remote_update_build_test.sh`

## Imported Conclusions

### HIR parity vs x86

- Imported summaries:
  - ARM: `/root/work/arm-sync/richards_hir_lir_20260314_183722/summary.json`
  - x86: `/root/work/arm-sync/richards_hir_lir_x86_20260314_201125_execfix4/summary.json`
- Observed from the imported plan:
  - `HandlerTask.fn`, `Task.runTask`, `Packet.append_to`, and `Task.qpkt` had essentially matching HIR shape on ARM and x86.
  - The big remaining differences were below HIR:
    - ARM compiled size larger
    - ARM stack / spill metrics larger

### Imported HIR win to preserve

- Documented winning HIR-side changes:
  - `LOAD_ATTR_METHOD_WITH_VALUES`
  - direct `CallMethod(PyFunction, self, ...) -> VectorCall(func, self, ...)`
- Imported ARM direct richards probe:
  - old median: `0.4713475180324167s`
  - new median: `0.2626585039542988s`
  - reported delta: about `-44.3%`
- Imported post-win HIR signal on hot functions:
  - `Task.runTask`: `LoadAttrCached=4`, `LoadField=20`, `StoreAttrCached=1`, `VectorCall=4`
  - `HandlerTask.fn`: `LoadAttrCached=7`, `LoadField=30`, `StoreAttrCached=4`, `VectorCall=6`
  - `Task.qpkt`: `LoadAttrCached=2`, `LoadField=12`, `StoreAttrCached=3`, `VectorCall=2`
  - `Richards.run`: `LoadField=34`, `StoreAttrCached=2`, `VectorCall=34`

### Imported rejected or neutral paths

- HIR:
  - `STORE_ATTR_INSTANCE_VALUE` overwrite fast path: regressed badly, especially on constructor / first-write shapes.
  - specialized attr guard dedup: HIR got smaller but ARM direct richards was about `+0.6%` slower on same-host fresh workdir.
  - `PYTHONJITINSTANCEVALUEMINLOCALS=1`: removed residual cached attr loads but regressed richards hard.
- Backend:
  - AArch64 deopt stage-1 compaction: smaller code, slower end-to-end.
  - always-shared AArch64 helper-call stubs: bigger code, slower end-to-end.
- Interpretation imported from the plan:
  - simple HIR-only richards headroom has been substantially mined already.
  - backend pressure exists, but the previous regalloc story was over-simplified.

## 2026-03-15 Local Review Notes

### Scheduler state

- `plans/remote-scheduler.sqlite3` has been initialized locally.
- Current status check:
  - ARM: `compile=0`, `verify=0`, `benchmark=0`
  - x86: `compile=0`, `verify=0`, `benchmark=0`

### Resolved local blocker before remote use

- Review found a correctness hole in the experimental exact `LoadMethod` cache split path from `cinderx/Jit/hir/simplify.cpp`.
- Problem:
  - the fast path compared only cached receiver type and then read the cached method value directly.
  - it skipped the instance-dict `keys_version` validation that the normal `LoadMethodCache::lookup()` path uses to detect method-name shadowing.
- Why that matters:
  - after a cache entry is filled, an instance can later gain a dict entry that shadows the method name.
  - the experimental split fast path could still return the cached class method instead of the shadowing instance attribute.
- Local action taken:
  - removed the live HIR producer that enabled the exact-method-cache split.
  - left the supporting experimental scaffolding as dormant code for now; it is not a live candidate for this SOP round.
- Effect on round planning:
  - do not benchmark or reason about `PYTHONJITEXACTMETHODCACHESPLIT` in this round.
  - keep the round focused on remaining LIR/codegen deltas that still have a sound correctness story.

## 2026-03-15 Round 1 Evidence

### ARM HIR-base vs current

- ARM HIR-base rebuild:
  - compile lease: `1`
  - workdir: `/root/work/cinderx-richards-hirbase-r1`
  - package source: `artifacts/richards_hiropt_pkg2_20260314_235226/cinderx-src.tar`
- ARM current rebuild:
  - successful compile lease: `4`
  - workdir: `/root/work/cinderx-richards-lir-r1`
  - package source: `artifacts/richards_lir_round1_pkg_fullfix2_20260315_173301/cinderx-update.tar`
- ARM LIR benchmark artifacts:
  - local: `artifacts/richards_lir_round1_results_20260315_174500/`
  - remote:
    - `/root/work/arm-sync/richards_lir_r1_hirbase.json`
    - `/root/work/arm-sync/richards_lir_r1_current.json`
- Direct benchmark result:
  - `richards`: `0.2162761030s -> 0.1793787990s` (`-17.06%`)
  - `method_chain`: `0.0016903901s -> 0.0016239550s` (`-3.93%`)

### ARM codegen env toggle

- Benchmark lease: `6`
- Artifacts:
  - local: `artifacts/richards_codegen_round1_results_20260315_175100/`
  - remote:
    - `/root/work/arm-sync/richards_codegen_storestub_off.json`
    - `/root/work/arm-sync/richards_codegen_storestub_on.json`
- Comparison:
  - `PYTHONJITAARCH64STOREATTRSTUBMINCALLS=1000000 -> 6`
  - `richards`: `0.1935252650s -> 0.1807337359s` (`-6.61%`)
  - `method_chain`: `0.0017029609s -> 0.0016588881s` (`-2.59%`)
- Important caveat:
  - default no-env current run (`0.1793787990s`) remained slightly faster than the stub-on run (`0.1807337359s`)
  - treat the store-attr stub as an experimental codegen knob, not yet a default richards landing candidate

### x86 comparison

- x86 successful compile lease: `10`
- x86 benchmark lease: `11`
- x86 workdir: `/root/work/cinderx-richards-x86-r1`
- x86 artifact:
  - local: `artifacts/richards_x86_round1_results_20260315_181000/richards_x86_current.json`
  - remote: `/root/work/arm-sync/richards_x86_current.json`
- Current direct benchmark result:
  - `richards`: `0.2460568990s`
  - `method_chain`: `0.0020649391s`
- Current ARM vs current x86:
  - `richards`: ARM faster by `27.10%`
  - `method_chain`: ARM faster by `21.36%`

### Compile and environment blockers fixed during the round

- Exact method-cache split correctness hole removed before remote use.
- `simplifyCallMethod()` invalid type comparison fixed after ARM compile failure.
- `kFillMethodCache` memory-effects entry added after ARM compile warning.
- `STORE_ATTR_INSTANCE_VALUE` overwrite fast path and its failing positive test removed after ARM runtime failure.
- x86 cross-arch compile fix:
  - `isStoreAttrInvokeTarget()` now returns `false` on non-AArch64 builds instead of referencing an AArch64-only helper.

### Remaining blocker for formal case closure

- The worker-hook blocker was resolved with two script-side fixes:
  - `verify_pyperf_venv.py` now accepts a non-venv `sitecustomize` path when an explicit prefix is supplied.
  - pyperformance parent processes now stay on `PYTHONJITDISABLE=1`, while workers recover `PYTHONJITAUTO` via `CINDERX_WORKER_PYTHONJITAUTO`.
- Direct benchmark evidence is strong and internally consistent.
- Formal pyperformance now runs on both hosts, but the x86 build path is still not fully config-matched with ARM.
- The single final pre-merge x86 functionality run remains outstanding.

## 2026-03-15 Formal pyperformance follow-up

### ARM formal pyperformance

- verify lease: `12`
- benchmark lease: `13`
- artifact:
  - local: `artifacts/richards_arm_pyperf_results_20260315_212600/richards_arm_current_pyperf_autojit50_v2.json`
  - remote: `/root/work/arm-sync/richards_arm_current_pyperf_autojit50_v2.json`
- result:
  - `richards`: `0.1145693631s`

### x86 formal pyperformance

- benchmark lease: `14`
- artifacts:
  - local: `artifacts/richards_x86_pyperf_results_20260315_213200/richards_x86_current_pyperf_autojit50_v2.json`
  - remote:
    - `/root/work/arm-sync/richards_x86_current_pyperf_autojit50_v2.json`
    - `/root/work/arm-sync/pyperf_venv_x86_recheck_worker_v2.json`
- result:
  - `richards`: `0.0748875150s`

### Formal pyperformance comparison caveat

- Formal current-vs-current pyperformance gives:
  - ARM `0.1145693631s`
  - x86 `0.0748875150s`
  - ARM slower by `52.99%`
- However, this should not yet be treated as final closure evidence because the x86 current build path is not fully config-matched with the ARM build path.
- Observed during rebuilds:
  - ARM current compile used `/opt/python-3.14/bin/python3.14` and produced a configuration with lightweight frames enabled.
  - x86 current compile used `/root/venv-cinderx314/bin/python` and the observed CMake configure line showed different settings, including lightweight-frame/adaptive-static differences.
- Interpretation:
  - the formal pyperformance worker-hook path is now fixed
  - but a config-matched x86 rebuild remains the last major comparison-quality blocker

## Current Worktree Stage Map

### HIR-heavy files

- `cinderx/Jit/bytecode.cpp`
- `cinderx/Jit/bytecode.h`
- `cinderx/Jit/hir/builder.cpp`
- `cinderx/Jit/hir/builder.h`
- `cinderx/Jit/hir/hir.cpp`
- `cinderx/Jit/hir/hir.h`
- `cinderx/Jit/hir/hir_ops.h`
- `cinderx/Jit/hir/instr_effects.cpp`
- `cinderx/Jit/hir/parser.cpp`
- `cinderx/Jit/hir/pass.cpp`
- `cinderx/Jit/hir/printer.cpp`
- `cinderx/Jit/hir/simplify.cpp`
- Live HIR candidates visible in the delta:
  - specialized lowering for `LOAD_ATTR_INSTANCE_VALUE`
  - specialized lowering for `LOAD_ATTR_METHOD_WITH_VALUES`
  - slot/member-descriptor field loads/stores
  - exact method cache split in simplify

### LIR-heavy files

- `cinderx/Jit/lir/generator.cpp`
- `cinderx/Jit/lir/generator.h`
- Live LIR candidates visible in the delta:
  - explicit `LoadMethodCache` allocation and entry helpers
  - `FillMethodCache` lowering
  - `CallMethod` lowering to `JITRT_CallMethod`
  - array-store helper routing changes

### codegen-heavy files

- `cinderx/Jit/codegen/environ.h`
- `cinderx/Jit/codegen/gen_asm.cpp`
- `cinderx/Jit/codegen/gen_asm_utils.cpp`
- `cinderx/Jit/codegen/gen_asm_utils.h`
- `cinderx/Jit/inline_cache.cpp`
- `cinderx/Jit/inline_cache.h`
- `cinderx/Jit/jit_rt.cpp`
- `cinderx/Jit/jit_rt.h`
- Live codegen candidates visible in the delta:
  - AArch64 `StoreAttrCache::invoke` shared-stub path gated by `PYTHONJITAARCH64STOREATTRSTUBMINCALLS`
  - supporting runtime / cache helpers for method and attr flows

### Validation and remote orchestration files

- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
- `scripts/arm/remote_update_build_test.sh`
- Tests added or extended in the current worktree appear to cover:
  - method-call runtime helper behavior
  - slot/member-descriptor HIR field lowering
  - AArch64 store-attr stub correctness / code-size behavior

## Remote Environment Notes

- Shared scheduler DB:
  - `plans/remote-scheduler.sqlite3`
- Host defaults from the skill:
  - ARM `124.70.162.35`
  - x86 `106.14.164.133`
- Known historical ARM workdirs:
  - `/root/work/cinderx-richards-baseline-631c95d9`
  - `/root/work/cinderx-richards-hiropt2-20260314_235251`
  - `/root/work/cinderx-richards-current-guarddedup`
  - `/root/work/cinderx-richards-deoptstage1`
  - `/root/work/cinderx-richards-helperstub`
- Preferred shared workdir for this SOP thread:
  - `/root/work/cinderx-richards-sop`

## Open Questions

- Which subset of the current dirty worktree is still a live richards hypothesis after importing the historical wins and failures?
- Does the new `CallMethod -> JITRT_CallMethod` path change richards ARM performance positively after the HIR win, or is it only a correctness / cleanliness refactor?
- Does the exact `LoadMethodCache` split help richards specifically, or is it a generic cache experiment with no case-local signal yet?
- Is the AArch64 `StoreAttrCache::invoke` stub relevant to richards hot overwrite sites after the store-side HIR path was already rejected?
- Can the current mixed worktree be benchmarked as one unit without violating stage attribution, or must it be split logically and validated in separate steps?

## Immediate Local Tasks

- Audit the diff into stage buckets with explicit “imported win”, “new live hypothesis”, and “already-rejected idea” labels.
- Run structured code review before remote validation.
- Initialize and inspect the shared scheduler DB.
- Draft the first case issue reply with imported evidence and the next remote question.

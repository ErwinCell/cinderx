# Task Plan: Issue 14 FloatCompare Optimization

## Goal
Optimize the `FloatCompare -> compare with Py_True` branch pattern described in issue 14 by removing the boxed bool result on the hot path and replacing it with primitive double comparison.

## Constraints
- Keep behavior correct for all float comparison operators used by `FloatCompare`.
- Preserve correct `NaN` semantics.
- Prefer minimal IR surface area; reuse existing `PrimitiveUnbox(TCDouble)` where possible.
- Add regression tests at both HIR and backend/codegen levels.

## Chosen Approach
1. Recognize the pattern only after `RefcountInsertion`, when the real problem shape exists:
   - `FloatCompare`
   - `PrimitiveCompare<Equal>(..., Py_True)`
   - `Decref` of the boxed bool result
2. Insert:
   - `PrimitiveUnbox(TCDouble)` of both float operands
   - primitive compare over doubles
   before the original `FloatCompare`, so the float operands are still alive.
3. Remove the obsolete `FloatCompare`, boxed-bool compare, and `Decref` of the boxed result.
4. Fix double compare lowering so generated machine code has correct ordered floating-point semantics, including `NaN`.
5. Validate with a dedicated post-refcount HIR pass test, backend floating-point compare tests, and remote ARM repro.

## Status
- [x] Read issue 14 and inspect existing HIR/codegen paths
- [x] Confirm `PrimitiveUnbox(TCDouble)` already provides the `LoadFloatValue` behavior
- [x] Replace the incorrect simplify rewrite with a post-refcount pass
- [x] Implement vecD compare codegen fix
- [x] Add regression tests
- [x] Run targeted verification

## Verification Notes
- `python setup.py build_ext --inplace` fails on this Windows host before compilation because CMake selects `NMake Makefiles` but `nmake` is unavailable.
- Manual `cmake -G Ninja` configure progresses further but then fails on repository/environment prerequisites unrelated to this patch:
  - `PY_VERSION`-dependent generated interpreter header inputs are not resolved correctly in this local configuration
  - `ZLIB` is missing for this machine's CMake environment
- `git diff --check` passed aside from line-ending warnings.
- Remote ARM validation on `124.70.162.35` succeeded after setting:
  - `LD_LIBRARY_PATH=/opt/toolchains/gcc-12.3.1-2025.03-aarch64-linux/lib64`
  - `PYTHONPATH=/root/work/cinderx-git/scratch/lib.linux-aarch64-cpython-314`
- Remote repro for `Scalar.maximize()` no longer shows `FloatCompare` in final HIR. Opcode counts now include:
  - `PrimitiveUnbox: 2`
  - `PrimitiveCompare: 1`
  - `Decref: 3`
  - no `FloatCompare`
- Remote AArch64 assembly now shows:
  - `ldr d0`, `ldr d1`, `fcmp d0, d1`, `cset w24, gt`
  - no hot `blr` for `FloatCompare`
  - no boxed-bool `Decref`
- Remote runtime validation for `== != < <= > >=` with `NaN` returned `ok`.
- Remote benchmark on `124.70.162.35` using an apples-to-apples baseline worktree built from the same `HEAD` commit (`562c620a989420f571de3962e709218e94c73a81`) showed:
  - `Scalar.maximize()` median: `2.3513s -> 2.1898s` for 2,000,000 iterations
  - `Point.maximize()` median: `2.8074s -> 2.7439s` for 1,000,000 iterations
  - Relative speedup:
    - scalar: about `6.9%`
    - point: about `2.3%`
  - This matches the review expectation that the current implementation removes the hot helper call and boxed-bool cleanup, but does not yet implement compare-branch fusion.

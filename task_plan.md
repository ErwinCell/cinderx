# Task Plan: Issue 31 Raytrace Regression Fix

## Goal
Keep the issue31 instance-attr specialization gains while removing the severe raytrace regression introduced by commit `4c14dd10`.

## Current Phase
Phase 1: reproduce and localize the regression.

## Phases

### Phase 1: Reproduction and root cause
- [ ] Reproduce the regression on the provided raytrace script on remote ARM
- [ ] Confirm whether the regression is caused by exact `other` arg guards, downstream float specialization, or both
- [ ] Capture current HIR/deopt evidence for the hottest failing methods
- Status: in progress

### Phase 2: Minimal safe fix
- [ ] Narrow or remove the unsafe exact-arg inference that causes the regression
- [ ] Preserve the stable issue31 gains on the safe Point.dist / linear_combination-style shape
- [ ] Add a regression test for the raytrace shape
- Status: pending

### Phase 3: Verification
- [ ] Remote rebuild on ARM staging
- [ ] Verify the new raytrace regression test
- [ ] Re-run the issue31 targeted test to ensure no regression on the intended optimization
- [ ] Check raytrace deopt counts and timing after the fix
- Status: pending

### Phase 4: Evidence
- [ ] Append the root cause and fix results to findings.md
- [ ] Update task status for commit/push readiness
- Status: pending
## Issue 31 Regression Fix Checkpoint
- Severe raytrace regression from issue31 is mostly fixed.
- Current strategy:
  - exact `other` arg inference only on plain attr-read methods
  - specialized float-op guards disabled on helper-heavy no-backedge methods
- Current balance:
  - issue31 plain attr gains still remain (`dist` and mixed benchmark still faster with `other` than `rhs`)
  - raytrace's worst deopt offenders (`Vector.dot`, `Point.__sub__`, `Sphere.intersectionTime`) are no longer present in runtime deopt stats for the provided repro
- Remaining follow-up if needed:
  - smaller residual deopts in `Vector.scale` and `addColours`

## Issue 34: builtin `min/max` on two floats

### Goal
- Remove the generic `VectorCall` path for `min(a, b)` / `max(a, b)` when both arguments are exact floats.
- Preserve Python semantics for NaN handling, signed-zero ties, and result object identity.

### Analysis
- Direct lowering to `DoubleBinaryOp<Min/Max>` is not semantically safe for Python builtins:
  - `min/max` return one of the original operand objects, not a freshly boxed float.
  - NaN behavior is order-sensitive (`min(nan, 1.0)` differs from `min(1.0, nan)`).
  - Ties such as `0.0` vs `-0.0` preserve the first argument object.
- Safe specialization strategy:
  - keep the builtin `GuardIs`
  - guard both args to `FloatExact`
  - unbox to `CDouble`
  - compare `rhs < lhs` for `min` and `rhs > lhs` for `max`
  - branch/select between the original operand objects

### Verification
- Remote ARM editable rebuild on `/root/work/frame-stage-local`: completed
- Targeted tests:
  - `test_builtin_min_max_two_float_args_eliminate_vectorcall`: passed
  - `test_builtin_min_max_two_float_args_preserve_order_nan_and_identity`: passed
- Probe results (`N=2_000_000`):
  - `min_builtin`: `0.1626069820486009s`
  - `min_ternary`: `0.2111730769975111s`
  - `min_ratio`: `0.7700175815997482x`
  - `max_builtin`: `0.16318202891852707s`
  - `max_ternary`: `0.21114284498617053s`
  - `max_ratio`: `0.7728513316622934x`
- Optimized HIR evidence:
  - `VectorCall = 0`
  - `GuardType = 2`
  - `PrimitiveUnbox = 2`
  - `PrimitiveCompare = 1`
  - `CondBranch = 2`
  - `Phi = 1`

### Status
- Current local code for issue34 is ready for review/commit.

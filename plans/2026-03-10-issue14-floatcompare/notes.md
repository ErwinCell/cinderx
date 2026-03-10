# Notes: Issue 14 FloatCompare

## Issue Summary
- Current `FloatCompare` lowering calls `PyFloat_Type.tp_richcompare`, returning a boxed `PyBool*`.
- In Python 3.14+ branch lowering, the result is then compared against `Py_True` using `PrimitiveCompare<Equal>`.
- That retains an avoidable object result and can lead to redundant refcount traffic on the hot path.

## Existing Building Blocks
- `PrimitiveUnbox(TCDouble)` already lowers to a direct load from `PyFloatObject.ob_fval`.
- `FloatCompare` is already emitted by `simplifyCompare()` when both operands are `FloatExact`.
- `PrimitiveCompare` already lowers to LIR compare instructions, and backend tests already exist for floating-point compare instructions.

## Key Design Decision
- Do not add a separate `LoadFloatValue` HIR instruction.
- Reuse `PrimitiveUnbox(TCDouble)` and teach the existing compare lowering to handle double semantics correctly.
- Do not do this in `Simplify`: that rewrite happens before `RefcountInsertion` and cannot remove the later `Decref` of the boxed bool result.
- Use a dedicated post-refcount pass instead, inserting the unbox/compare sequence before `FloatCompare`.

## Risk
- x86 floating-point `==` / `!=` with `comisd` need explicit unordered handling for `NaN`.
- Ordered `<` / `<=` on doubles cannot reuse integer-style condition mapping blindly.
- If the unbox/compare sequence is inserted after the float operands have already been `Decref`'d, it becomes a use-after-release bug. Insertion point must be before the original `FloatCompare`.

## Benchmark Notes
- Benchmark host: `124.70.162.35` (AArch64)
- Toolchain/runtime used for both runs:
  - `LD_LIBRARY_PATH=/opt/toolchains/gcc-12.3.1-2025.03-aarch64-linux/lib64`
  - Python: `/root/work/cinderx-git/.venv-benchfinal/bin/python`
- Clean baseline:
  - worktree: `/root/work/cinderx-issue14-base`
  - built from the same `HEAD` as the modified tree
  - `PYTHONPATH=/root/work/cinderx-issue14-base/cinderx/PythonLib:/root/work/cinderx-issue14-base/scratch/temp.linux-aarch64-cpython-314`
- Current tree:
  - worktree: `/root/work/cinderx-git`
  - `PYTHONPATH=/root/work/cinderx-git/cinderx/PythonLib:/root/work/cinderx-git/scratch/lib.linux-aarch64-cpython-314`
- Workloads:
  - `Scalar.maximize`: one float compare per call, 2,000,000 iterations, 7 repeats
  - `Point.maximize`: three float compares per call, 1,000,000 iterations, 7 repeats
- Median results:
  - Scalar: `2.3513s` baseline vs `2.1898s` current
  - Point: `2.8074s` baseline vs `2.7439s` current

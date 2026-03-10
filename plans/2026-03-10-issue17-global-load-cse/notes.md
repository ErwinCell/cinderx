# Notes: Issue 17

## Questions
- Is `LoadGlobalCached` safe to CSE directly, or should we only eliminate the second `GuardIs`?
- What instructions between the two loads must be considered barriers?
- Is this only needed intra-block, or does the issue require cross-block value numbering?
- Does the pattern already disappear after other passes for simpler examples?

## Initial Hypothesis
- A full general-purpose CSE for `LoadGlobalCached` is probably larger and riskier than needed.
- A narrow intra-block pass that rewrites:
  - `LoadGlobalCached<slot>`
  - `GuardIs<target>`
  - ... replayable instructions with no global writes ...
  - `LoadGlobalCached<same slot>`
  - `GuardIs<same target>`
  into reuse of the first guarded value is more likely to be safe and sufficient.

## Local Semantics Review
- `LoadGlobalCached` is replayable, but it reads `AGlobal` memory and is not a pure constant load.
- `GuardIs` is passthrough for value flow, but it enforces runtime object identity and cannot be dropped if the loaded global may have changed.
- `VectorCall`, `BinaryOp`, and many call-like instructions are marked as having arbitrary execution.

## Remote Findings
- Remote minimal repro for:
  - `a = func_g(x); b = func_g(y); return a + b`
  produced final HIR with:
  - `LoadGlobalCached: 2`
  - `GuardIs: 2`
  - `VectorCall: 2`
- This is expected, not obviously redundant, because the first call is a barrier.

## Unsoundness Counterexample
- Remote counterexample:
  - first call to `func_g` rebinds the global `func_g = func_h`
  - second call must therefore observe the new global binding
- Observed result:
  - expected `108`
  - actual `108`
- This proves the second `LoadGlobalCached + GuardIs` pair is semantically necessary across the intervening call.

## Conclusion
- Issue 17's proposed transformation is unsafe for the reported shape.
- A safe optimization would need a stricter barrier model and will not fix the issue's call-separated examples as written.

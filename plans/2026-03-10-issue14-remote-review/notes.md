# Notes: Remote Review for Issue 14

## Initial Questions
- Does the remote environment still show the exact `FloatCompare -> boxed Bool -> compare with Py_True` chain described in the issue?
- Is the local rewrite valid for all compare operators, especially with `NaN`?
- Does the proposal require a new HIR instruction, or is `PrimitiveUnbox(TCDouble)` sufficient?
- Is branch lowering in 3.14+ always through `PrimitiveCompare(..., Py_True)` for this case?

## Review Focus
- Correctness first
- Match between proposal text and actual implementation surface
- Whether the selected compare op mapping is semantically correct on x86 and AArch64
- Missed cases: `!= True`, direct `Return`, non-branch consumers, snapshot/liveness interactions

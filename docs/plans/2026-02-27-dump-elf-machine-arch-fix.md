# 2026-02-27 CinderX `dump_elf` Machine Field Fix (ARM)

## Context
- Symptom: on ARM host, `cinderjit.dump_elf()` output is disassembled as `elf64-x86-64` when using `objdump -d`.
- Root cause hypothesis: ELF header `e_machine` is hardcoded to x86-64 in CinderX ELF writer header defaults.
- Constraint: all test/verification must run through remote entrypoint `<远端测试入口>` (`ssh root@124.70.162.35`).

## Brainstorming
1. Minimal fix:
   - Set ELF header `machine` by compile target (`__aarch64__`, `__x86_64__`) instead of hardcoded value.
   - Keep existing layout/sections unchanged.
2. Safety:
   - Preserve x86 behavior on x86 builds.
   - Explicitly fail compile on unknown arch so it does not silently emit wrong metadata.
3. Regression prevention:
   - Add a Python test that reads ELF header `e_machine` from `dump_elf` output and compares to runtime architecture mapping.

## TDD Plan
1. RED:
   - Add regression test under `test_cinderjit.py` for `dump_elf` header machine.
   - Run targeted test on remote ARM; expect failure before code fix.
2. GREEN:
   - Implement architecture-aware `e_machine` selection in ELF header code.
   - Re-run targeted test on remote ARM; expect pass.
3. Extra verification:
   - Confirm `readelf -h` shows `Machine: AArch64` for dumped ELF.
   - Confirm `objdump -d` on ELF no longer mislabels as x86.

## Remote Verification Commands
1. Targeted RED/GREEN test:
   - `ssh root@124.70.162.35 'cd /root/work/cinderx-main && /root/venv-cinderx314/bin/python -m unittest test_cinderx.test_cinderjit.CinderJitModuleTests.test_dump_elf_machine_matches_runtime_arch'`
2. Manual ELF header check:
   - `ssh root@124.70.162.35 'readelf -h /tmp/<dumped>.elf | grep Machine'`
3. Manual disassembly check:
   - `ssh root@124.70.162.35 'objdump -d /tmp/<dumped>.elf | head'`

## Files Expected to Change
- `cinderx/Jit/elf/header.h`
- `cinderx/PythonLib/test_cinderx/test_cinderjit.py`
- `findings.md`

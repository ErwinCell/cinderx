# PGO/LTO pyperformance 改动自验证报告

## 验证范围

本报告覆盖本次修改自身的正确性验证：

- `setup.py` 不再硬编码 pyperformance workload。
- `custom-command` PGO workload 能正确解析和包装外部命令。
- 默认 `cpython-pgo` workload 保持可用。
- pyperformance worker hook 能识别 `PYTHONJITSPECIALIZEDOPCODES=1`。
- 几何平均 speedup 汇总脚本能正确通过和失败。
- ARM A/B 验收脚本语法正确。

## 已执行命令

```bash
python3 -m py_compile setup.py scripts/arm/pyperf_speedup_summary.py \
  tests/test_setup_pgo_validation.py tests/test_arm_pyperf_speedup_summary.py
```

结果：通过。

```bash
python3 -m unittest discover -s tests -p 'test_setup_*.py' -v
```

结果：28/28 通过。

```bash
python3 -m unittest tests.test_arm_pyperf_speedup_summary -v
```

结果：2/2 通过。

```bash
bash -n scripts/arm/pgo_lto_pyperformance_compare.sh
```

结果：通过。

```bash
git diff --check -- setup.py scripts/arm/pyperf_env_hook/sitecustomize.py \
  tests/test_setup_pgo_validation.py tests/test_setup_pgo_workload_retries.py \
  scripts/arm/pgo_lto_pyperformance_compare.sh \
  scripts/arm/pyperf_speedup_summary.py tests/test_arm_pyperf_speedup_summary.py \
  docs/pgo-lto-pyperformance-change-notes.md \
  docs/pgo-lto-pyperformance-design.md \
  docs/pgo-lto-pyperformance-self-validation.md
```

结果：通过。

```bash
rg -n "pyperformance-full|CINDERX_PGO_PYPERF|build_pgo_pyperformance|PGO_WORKLOAD_PYPERFORMANCE|pyperformance" \
  setup.py tests/test_setup_pgo_validation.py
```

结果：无匹配，确认 `setup.py` 和对应单测中没有 pyperformance 专用 workload 或
旧 pyperformance build hook 名称。

## 未执行项

本地没有执行全量 ARM A/B pyperformance 验收：

- 全量 pyperformance 会构建并安装 baseline 与 PGO/LTO candidate，耗时较长。
- 该验证应在目标 ARM 环境使用 `scripts/arm/pgo_lto_pyperformance_compare.sh`
  执行。
- 是否达到 `1.02x` 以该脚本生成的 `speedup_summary.json` 为准。

## 当前结论

本次修改的代码级自验证通过。构建系统层面已经解除对 pyperformance 的硬编码依赖；
pyperformance 只作为 ARM 验收脚本可选使用的外部命令存在。最终性能结论仍需在 ARM
环境跑完整 A/B 验收脚本确认。

# PGO/LTO pyperformance 验证设计文档

## 目标

- 保持默认 CinderX PGO 构建行为不变，避免把 pyperformance 变成构建依赖。
- 提供显式 opt-in 的代表性 PGO 训练入口，供 ARM 性能验收脚本使用。
- 用同一份源码、同一个 Python、同一套 JIT 环境、同一份 jitlist，对比
  non-PGO/LTO baseline 和 PGO/LTO candidate。
- 用 common benchmarks 的几何平均 speedup 作为 suite-level 指标，默认通过线是
  `1.02x`。

## 非目标

- 不给 `setup.py` 增加 pyperformance 依赖。
- 不让 `CINDERX_ENABLE_PGO=1` 或 `CINDERX_ENABLE_LTO=1` 自动触发
  pyperformance。
- 不加入 benchmark 名称判断、定向 jitlist 生成或定向编译分支。
- 不处理 x86 分支。

## 构建接口

PGO workload 有两个模式：

- `CINDERX_PGO_WORKLOAD=cpython-pgo`

  默认模式，继续使用现有 CPython `--pgo` workload。

- `CINDERX_PGO_WORKLOAD=custom-command`

  显式模式，必须同时提供 `CINDERX_PGO_WORKLOAD_CMD`。该命令使用 shell-like
  quoting 解析，并在 `_cinderx` 导入和初始化校验通过后运行。运行环境会包含
  指向 instrumented build output 和 checkout root 的 `PYTHONPATH`。

`setup.py` 不关心 `custom-command` 的具体内容。外部验收脚本可以选择传入
pyperformance 命令，但这个依赖属于验收脚本和运行环境，不属于 CinderX 构建系统
契约。

## 验证流程

`scripts/arm/pgo_lto_pyperformance_compare.sh` 执行端到端 ARM 验证：

1. 把当前源码复制到两个临时目录。
2. baseline 使用 `CINDERX_ENABLE_PGO=0` 和 `CINDERX_ENABLE_LTO=0` 构建安装。
3. 使用用户给定的 JIT 环境运行全量 pyperformance，输出 `baseline.json`。
4. candidate 使用 `CINDERX_ENABLE_PGO=1`、`CINDERX_ENABLE_LTO=1` 和
   `CINDERX_PGO_WORKLOAD=custom-command` 构建安装。
5. 验收脚本把外部训练命令写入 `CINDERX_PGO_WORKLOAD_CMD`，让 candidate 的
   Stage 2 可以用同形态 workload 训练，同时不把 pyperformance 写进构建系统。
6. 再次运行全量 pyperformance，输出 `pgo_lto.json`。
7. 运行官方 `pyperformance compare -O table`，输出 `compare.txt`。
8. 读取两份 JSON，计算每个 common benchmark 的 `baseline_mean / changed_mean`，
   再计算几何平均 speedup；低于 `THRESHOLD` 时脚本失败。

## Worker 环境

验收脚本只在 candidate 的自定义 PGO 训练命令中注入
`scripts/arm/pyperf_env_hook/sitecustomize.py`。这个 hook 的作用是让
pyperformance worker 稳定初始化 instrumented CinderX build。

hook 会识别两种 specialized opcodes 信号：

- `CINDERX_ENABLE_SPECIALIZED_OPCODES=1`
- `PYTHONJITSPECIALIZEDOPCODES=1`

最终 A/B benchmark 命令保持用户提供的 inherit-environment 形态，不要求这个
hook。

## 失败模式

- 如果 `CINDERX_PGO_WORKLOAD=custom-command` 但没有
  `CINDERX_PGO_WORKLOAD_CMD`，Stage 2 直接失败。
- 如果 `_cinderx` 在 custom workload 前导入失败或未初始化，Stage 2 直接失败。
- 如果 GCC 核心 target profile 缺失，现有 Stage 2b 审计仍会在 Stage 3 前失败。
- 如果最终几何平均 speedup 低于阈值，验收脚本会在写出
  `speedup_summary.json` 后以非零状态退出。

## 验收标准

- 默认 PGO 构建不需要 pyperformance，并继续使用 CPython `--pgo` workload。
- ARM 验收脚本可以运行用户给定的 pyperformance 命令生成 baseline 和 candidate
  数据。
- candidate PGO/LTO 构建只在验收脚本显式设置 `custom-command` 时使用外部训练
  命令。
- 通过时 `speedup_summary.json` 中的 `geomean_speedup >= 1.02`。

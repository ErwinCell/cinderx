# PGO/LTO pyperformance 验证改动说明

## 背景

前一轮 PGO/LTO 修复已经解决了 GCC 下构建正确性问题：第三方 target 不再吃
PGO/LTO，核心第一方 target 的 profile 数据会在 Stage 2b 被审计，缺核心画像时
不会继续进入 Stage 3。

这次改动的目标是补上“可验证性能收益”的工程路径，同时满足一个新的约束：
CinderX 构建系统本身不能依赖 pyperformance。

## 修改内容

- `setup.py` 默认仍使用 `CINDERX_PGO_WORKLOAD=cpython-pgo`，也就是原来的
  CPython `--pgo` workload。
- `setup.py` 新增 `CINDERX_PGO_WORKLOAD=custom-command` 和
  `CINDERX_PGO_WORKLOAD_CMD`，用于显式传入外部 PGO 训练命令。
- `custom-command` 会先复用现有 `_cinderx` 导入和初始化校验，再运行用户提供
  的命令；如果 `_cinderx` 没有真实初始化，仍然会在 Stage 2 失败。
- `setup.py` 不 import、不命名、不直接调用 pyperformance；pyperformance 只出现
  在 ARM 验收脚本和结果汇总脚本里。
- `scripts/arm/pyperf_env_hook/sitecustomize.py` 现在会把
  `PYTHONJITSPECIALIZEDOPCODES=1` 视作启用 specialized opcodes 的信号，避免
  pyperformance worker 和用户测试环境不一致。
- 新增 `scripts/arm/pgo_lto_pyperformance_compare.sh`，用于在临时 source copy
  上构建 baseline 和 PGO/LTO candidate，运行全量 pyperformance，输出官方
  compare 结果和几何平均 speedup。
- 新增 `scripts/arm/pyperf_speedup_summary.py`，直接读取 pyperformance JSON，
  计算 common benchmarks 的几何平均 speedup，并以默认 `1.02x` 作为 gate。

## 使用方式

```bash
PYTHONJITTYPEANNOTATIONGUARDS=1 \
PYTHONJITENABLEJITLISTWILDCARDS=1 \
PYTHONJITENABLEHIRINLINER=1 \
PYTHONJITAUTO=2 \
PYTHONJITSPECIALIZEDOPCODES=1 \
PYTHONJITLISTFILE=/home/jit_list.txt \
scripts/arm/pgo_lto_pyperformance_compare.sh
```

默认输出目录：

```text
artifacts/pgo_lto_pyperf_<RUN_ID>/
```

关键产物：

- `baseline.json`
- `pgo_lto.json`
- `compare.txt`
- `speedup_summary.json`
- `baseline_build.log`
- `pgo_lto_build.log`

## 可选参数

- `THRESHOLD=1.02`：修改几何平均 speedup gate。
- `PYTHON=/home/pybin/bin/python3.14`：指定 driver Python。
- `PGO_TRAINING_ARGS="--debug-single-value -b richards --warmup 1"`：让验收脚本
  使用短 PGO 训练 workload 做 smoke。
- `CINDERX_PGO_WORKLOAD_CMD="<command>"`：完全替换验收脚本默认生成的 PGO 训练
  命令。
- `ARTIFACT_DIR=<path>` 和 `WORK_ROOT=<path>`：指定输出目录和临时 source copy
  目录。

## 构建依赖边界

CinderX 构建系统只提供通用 `custom-command` hook，不依赖 pyperformance。ARM
验收脚本可以把 pyperformance 作为外部命令传给这个 hook，但这是验收脚本层的
选择，不是 `setup.py` 的固定依赖。

# CinderX UT 统一入口

`tests/run_test_suites.py` 是当前两类 UT 的统一入口：

- `pythonlib`：`cinderx/PythonLib/test_cinderx`
- `runtime`：`cinderx/RuntimeTests`，即 `RuntimeTests` 二进制

脚本默认面向远端 ARM/Linux 调试环境，按 Python 3.14 + GCC14 工具链设计。

## 依赖

- Python 3.14
- `cmake`
- `gcc/g++/gcov` 14
- 可选：`lcov`、`genhtml`

默认远端路径：

- Python：`/opt/python-3.14.3/bin/python3.14`
- GCC root：`/opt/openEuler/gcc-toolset-14/root`

如果环境里的 GCC 布局是 `/opt/gcc-14/bin/gcc`，则传：

```bash
--gcc-root /opt/gcc-14
```

## 命令格式

```bash
python tests/run_test_suites.py \
  -t [all|pythonlib|runtime] \
  -o <输出目录> \
  [-f <过滤条件>] \
  [-l] \
  [-c]
```

补充参数：

- `--python-exe <path>`
- `--runtime-build-dir <path>`
- `--runtime-binary <path>`
- `--runtime-cwd <path>`
- `--keep-going`
- `--no-build`
- `--gcc-root <path>`

## `-f` 过滤语义

- `pythonlib`
  - 按模块名过滤
  - 例如：`-f test_cinderx.test_jit_exception`
- `runtime`
  - 按 gtest filter 语义过滤
  - 例如：`-f 'AliasClassTest.*'`
  - 多个模式可直接写成：`-f 'AliasClassTest.*:BitVectorTest.*'`
- `all`
  - 同一组 `-f` 会同时传给两类测试
  - `pythonlib` 仍按模块名解释
  - `runtime` 仍按 gtest filter 解释

## `-c` 覆盖率语义

`-c` 现在统一表示 **GCC C++ 覆盖率**：

- `pythonlib -c`
  - 会先构建带 `--coverage` 的 `_cinderx.so`
  - 再用 `test_cinderx` 去驱动 native 代码执行
  - 最终产出 `.gcda/.gcov/lcov`
- `runtime -c`
  - 会构建带 `--coverage` 的 `RuntimeTests`
  - 再逐 case 执行并收集 C++ 覆盖率

注意：

- `-c` 不再把 Python `coverage.py` 当作主语义
- 两类测试的覆盖率都以 C++ native 覆盖率为准
- 如果远端没装 `lcov/genhtml`，脚本会退化为 `gcov-summary.txt + raw-gcov/ + index.md`
- 任务结束时会额外打印一段 **产品口径** 的覆盖率总览
  - 分母固定为构成 `_cinderx.so` 的产品 native 可执行代码行
  - 同时会在输出根目录生成：
    - `coverage-overview.json`
    - `coverage-overview.md`

## 常用命令

列举 `pythonlib` 模块：

```bash
/opt/python-3.14.3/bin/python3.14 tests/run_test_suites.py -t pythonlib -l
```

列举 `runtime` 用例：

```bash
/opt/python-3.14.3/bin/python3.14 tests/run_test_suites.py -t runtime -l
```

执行一个 `pythonlib` 模块：

```bash
/opt/python-3.14.3/bin/python3.14 tests/run_test_suites.py \
  -t pythonlib \
  -f test_cinderx.test_asynclazyvalue
```

执行一个 `runtime` suite：

```bash
/opt/python-3.14.3/bin/python3.14 tests/run_test_suites.py \
  -t runtime \
  -f 'AliasClassTest.*'
```

同时执行两类测试：

```bash
/opt/python-3.14.3/bin/python3.14 tests/run_test_suites.py -t all
```

采 `pythonlib` 的 C++ 覆盖率：

```bash
/opt/python-3.14.3/bin/python3.14 tests/run_test_suites.py \
  -t pythonlib \
  -c \
  -f test_cinderx.test_jit_exception
```

采 `runtime` 的 C++ 覆盖率：

```bash
/opt/python-3.14.3/bin/python3.14 tests/run_test_suites.py \
  -t runtime \
  -c \
  -f 'AliasClassTest.*'
```

## 输出目录

默认输出根目录：

```text
<workspace>/cov/ut/<timestamp>/
```

典型结构：

```text
cov/ut/<timestamp>/
  README.md
  pythonlib/
    summary.tsv
    summary.md
    tests.json
    logs/
    configure.log
    build.log
    gcda-files.txt
    gcov-summary.txt
    raw-gcov/
    runtime-tests.lcov.info
    html/
    index.md
  runtime/
    summary.tsv
    summary.md
    tests.json
    logs/
    configure.log
    build.log
    gcda-files.txt
    gcov-summary.txt
    raw-gcov/
    runtime-tests.lcov.info
    html/
    index.md
  coverage-overview.json
  coverage-overview.md
```

说明：

- `pythonlib/` 和 `runtime/` 的覆盖率产物结构一致
- `runtime-tests.lcov.info`、`html/` 只在远端存在 `lcov/genhtml` 时生成

## 状态说明

汇总表里可能出现：

- `PASSED`
- `FAILED`
- `SKIPPED`
- `NO_TESTS`
- `CRASHED`

其中：

- `CRASHED` 表示测试进程出现 segfault 或信号退出
- 脚本会把崩溃记录到汇总和对应日志中
- 单个 segfault 不会中断整个批次执行

## 额外说明

- `pythonlib` 固定走 `cinderx/TestScripts/cinder_test_runner312.py`
- `runtime` 固定按“单 case 逐个执行”模式运行，避免 seg 影响整批
- 未指定 `--no-build` 时，脚本会自动配置并构建所需 native 目标

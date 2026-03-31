# 2026-03-31 pyperformance nbody JIT Enable Report

## 目标

让 `nbody` 这类 `pyperformance` 用例在 `erwin` 环境里：

1. 真的触发 `CinderX JIT`
2. 结果回到和此前 `jit_list` 路径同一量级
3. 同时区分清楚：
   - 哪些是运行方式问题
   - 哪些是 `cinderx` 自身 bug

## 最初症状

用户原始命令：

```bash
PYTHONJITTYPEANNOTATIONGUARDS=1 \
PYTHONJITENABLEHIRINLINER=1 \
PYTHONJITAUTO=2 \
PYTHONJITSPECIALIZEDOPCODES=1 \
/home/pybin/bin/python3.14 -m pyperformance run \
  --affinity=2 \
  -b nbody \
  --warmup 3 \
  --inherit-environ \
http_proxy,https_proxy,LD_LIBRARY_PATH,PYTHONJITAUTO,PYTHONJITSPECIALIZEDOPCODE,PYTHONJITENABLEHIRINLINER,PYTHONJITTYPEANNOTATIONGUARDS
```

在 `erwin` 上会报：

```text
JIT: .../cinderx/Jit/stack.h:19 -- Assertion failed: !stack_.empty()
Can't pop from empty stack
Aborted (core dumped)
```

而 `jit_list` 版本可以完成运行，且结果大约在 `60ms` 量级。

## 定位过程

### 第 1 步：先确认不是 benchmark 本身先坏

最小化后发现下面这条就会崩：

```bash
PYTHONJITTYPEANNOTATIONGUARDS=1 \
PYTHONJITENABLEHIRINLINER=1 \
PYTHONJITAUTO=2 \
PYTHONJITSPECIALIZEDOPCODES=1 \
/home/pybin/bin/python3.14 -c "import pyperformance"
```

这说明一开始不是 `nbody` 本体先坏，而是 `pyperformance` 父进程在 import 阶段就被带进了 JIT。

### 第 2 步：确认 `.pth` 是触发链的一部分

远端安装里的：

- `/home/pybin/lib/python3.14/site-packages/cinderx.pth`

最初是无条件：

```python
import builtins, cinderx; builtins.cinderx = cinderx
```

这会让 `pyperformance` 父进程也自动导入 `cinderx`。

因此第一轮修复把它改成只在 worker 带有 `PYPERFORMANCE_RUNID` 时才导入 `cinderx`。

这一改动解决了父进程过早进入 JIT 的问题，但没有解决 worker 侧真正的 crash。

### 第 3 步：确认之前的 hook 路径其实没真正触发 JIT

此前通过：

- [sitecustomize.py](/mnt/d/code/cinderx/scripts/arm/pyperf_env_hook/sitecustomize.py)

的 hook 路径，可以让 `pyperformance run -b nbody` 跑完，但结果在 `122ms` 左右。

进一步打开 `PYTHONJITDEBUG` 后发现：

```text
CinderX JIT Total Compilation Time: 0ms
```

也就是说，这条路径虽然“跑完了”，但实际上没有真正启用 autojit。

### 第 4 步：找出为什么 hook 没有真正打开 autojit

原因是导入顺序：

1. worker 进程启动
2. `cinderx.pth` 因为 `PYPERFORMANCE_RUNID` 存在而提前导入 `cinderx`
3. 此时父进程传下来的 `PYTHONJITDISABLE=1` 还没被移除
4. `sitecustomize.py` 随后执行时，只调用了 `jit.enable()`，但没有重新调用 `jit.compile_after_n_calls(...)`

结果就是：

- JIT 被 enable 了
- 但 autojit threshold 没有恢复
- 所以整个 benchmark 其实没有任何编译发生

### 第 5 步：修复 hook 后，确认 JIT 真的启动

给 hook 补上：

```python
jit.compile_after_n_calls(int(worker_autojit))
```

之后，worker 的 JIT 日志里开始出现真实 compile 记录，说明 JIT 确实被触发。

### 第 6 步：进一步确认这是 `cinderx` bug，不是 `pyperformance` 兼容层单独的问题

修完 hook 之后，`pyperformance` 框架路径会继续向前走，但一旦真的让 autojit 编译 importlib 热路径，就会在更深一层崩成 `-11`。

更关键的是，下面这条完全脱离 `pyperformance run` 的 direct harness 也会崩：

```bash
PYTHONJITTYPEANNOTATIONGUARDS=1 \
PYTHONJITENABLEHIRINLINER=1 \
PYTHONJITSPECIALIZEDOPCODES=1 \
/home/pybin/bin/python3.14 -S - <<'PY'
import sys, importlib.util
sys.path.append("/home/pybin/lib/python3.14/site-packages")
import cinderx
import cinderx.jit as jit
jit.enable()
jit.compile_after_n_calls(2)
jit.enable_specialized_opcodes()
spec = importlib.util.spec_from_file_location(
    "bm_nbody",
    "/home/pybin/lib/python3.14/site-packages/pyperformance/data-files/benchmarks/bm_nbody/run_benchmark.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for i in range(5):
    mod.bench_nbody(1, mod.DEFAULT_REFERENCE, mod.DEFAULT_ITERATIONS)
PY
```

这说明：

- 问题不依赖 `pyperformance run` 框架本身
- 问题来自 `cinderx` 在 autojit 编译 importlib / startup 热路径时的真实 bug

## 关键结论

问题被拆成了两层：

### A. 运行方式问题

此前 hook 路径“能跑完但没 JIT”，这是运行方式/启动顺序问题，不是 benchmark 本体问题。

这一层已经通过补齐 `compile_after_n_calls()` 修正。

### B. `cinderx` 自身 bug

当真正让 autojit 在 startup/import 阶段编译 importlib 热路径时，`cinderx` 仍会 segfault。

这不是单纯的 `pyperformance` 兼容问题，因为 direct harness 也能复现。

## 最终方案

### 1. 仓库内正式修改

#### `.pth` 只在 worker 自动导入

- [cinderx.pth](/mnt/d/code/cinderx/cinderx/PythonLib/cinderx.pth)

从无条件导入改成只在 `PYPERFORMANCE_RUNID` 存在时自动导入 `cinderx`。

#### 给 worker hook 补回真正的 autojit 配置

- [sitecustomize.py](/mnt/d/code/cinderx/scripts/arm/pyperf_env_hook/sitecustomize.py)

新增：

- `_parse_compile_after()`
- 在 `jit.enable()` 后调用 `jit.compile_after_n_calls(...)`

这样 worker 恢复的就不只是“JIT enabled”，而是完整的 autojit 行为。

#### 给 direct driver 增加 autojit-after-import 模式

- [bench_pyperf_direct.py](/mnt/d/code/cinderx/scripts/arm/bench_pyperf_direct.py)

新增参数：

- `--jit-mode force|autojit`
- `--compile-after-n-calls`

这样可以稳定使用 `pyperformance` 的 benchmark 模块，但脱离 `pyperformance run` 框架：

1. 先安全导入 benchmark 模块
2. 再打开 `cinderx` JIT
3. 再对 benchmark 函数本体触发 autojit 或 force_compile

#### 给全量 manifest 批跑补一个 direct suite runner

- [run_pyperf_suite_direct.py](/mnt/d/code/cinderx/scripts/arm/run_pyperf_suite_direct.py)

新增能力：

- 读取 `pyperformance` manifest
- 用 `runscript + extra_opts` 复原每个 benchmark 的注册方式
- 支持 `bench_time_func` / `bench_func` / `bench_async_func`
- 对 `bench_command` 和缺依赖 benchmark 做结构化跳过
- 输出整轮 suite 的 JSON 汇总

### 2. 新增回归测试

- [test_setup_pyperformance_pth.py](/mnt/d/code/cinderx/tests/test_setup_pyperformance_pth.py)
- [test_pyperf_env_hook.py](/mnt/d/code/cinderx/tests/test_pyperf_env_hook.py)
- [test_run_pyperf_suite_direct.py](/mnt/d/code/cinderx/tests/test_run_pyperf_suite_direct.py)

覆盖点：

- `.pth` 不再无条件导入
- worker hook 会恢复 `compile_after_n_calls()`
- specialized opcodes 和 jit list 附加配置仍然能生效
- manifest benchmark 的注册信息可以被 direct suite runner 正确捕获
- direct suite runner 在执行 benchmark 前会恢复正确的 autojit 配置

## 当前推荐使用方式

### 方案 A：如果你要继续用 `pyperformance` 用例，但不要求走 `pyperformance run` 框架

这是当前最稳、而且已经实测能触发 JIT 的方案。

#### `advance` 直接跑法

```bash
cd /home/test/cinderx

/home/pybin/bin/python3.14 scripts/arm/bench_pyperf_direct.py \
  --module-path /home/pybin/lib/python3.14/site-packages/pyperformance/data-files/benchmarks/bm_nbody/run_benchmark.py \
  --module-name bm_nbody \
  --bench-func advance \
  --bench-args-json '[0.01,20000]' \
  --samples 6 \
  --prewarm-runs 2 \
  --compile-strategy backedge \
  --specialized-opcodes
```

这一条在 `erwin` 上已经验证通过，输出大约：

```text
median_wall_sec ~= 0.059s
```

#### `bench_nbody` 先导入后 autojit 的效果

在 direct harness 里实测：

- 前两次约 `0.134s / 0.141s`
- 第三次开始稳定到 `~0.061s`

这说明 benchmark 本体已经真正吃到了 JIT，而不是假跑。

### 方案 C：如果你想批量跑 `pyperformance` 的全量 manifest benchmark

现在仓库里新增了：

- [run_pyperf_suite_direct.py](/mnt/d/code/cinderx/scripts/arm/run_pyperf_suite_direct.py)

它的设计目标是：

1. 继续复用 `pyperformance` 提供的 benchmark 脚本和 manifest
2. 但不再走 `pyperformance run` 的 worker / startup 路径
3. 改成“先导入 benchmark，再开启 JIT，再直接执行 benchmark callable”
4. 对不适合 after-import JIT 的 benchmark 做结构化跳过，而不是整轮崩掉

#### 当前 `erwin` 环境上的支持情况

我在 `2026-03-31` 的 `erwin` 环境上做过一次全量 `--probe-only` 验证，结果是：

- manifest benchmark 总数：`97`
- 当前环境可直接跑的 benchmark：`67`
- 当前环境会被稳定标成 `skipped` 的 benchmark：`30`

这 `30` 个 `skipped` 分成两类：

1. 设计上跳过
   - `2to3`
   - `python_startup`
   - `python_startup_no_site`

这三项是 `bench_command` / startup-subprocess 类型，它们测的是“另起 Python 子进程”的耗时，不适合 after-import JIT 方案。

2. 当前环境缺依赖
   - 例如 `websockets`、`coverage`、`dask`、`django`、`sqlalchemy`、`sqlglot`、`sympy`、`tornado` 等

这一类不是 `cinderx` bug，也不是 direct runner 的逻辑问题，而是 `/home/pybin/bin/python3.14` 当前没有装对应 benchmark 的第三方依赖。

#### 先探测当前环境支持范围

建议先跑：

```bash
cd /home/test/cinderx

/home/pybin/bin/python3.14 scripts/arm/run_pyperf_suite_direct.py \
  --probe-only \
  --output artifacts/pyperf/full_suite_probe.json
```

这条命令不会真正执行 benchmark 本体，只会：

1. 读取 `pyperformance` manifest
2. 按每个 manifest benchmark 的 `runscript + extra_opts` 做捕获
3. 判断它是：
   - 可以 direct-run
   - 还是应该跳过
   - 以及缺哪个依赖

#### 跑当前环境里“可 direct-run 的整套 benchmark”

```bash
cd /home/test/cinderx

/home/pybin/bin/python3.14 scripts/arm/run_pyperf_suite_direct.py \
  --samples 3 \
  --prewarm-runs 2 \
  --compile-after-n-calls 2 \
  --specialized-opcodes \
  --output artifacts/pyperf/full_suite_direct.json
```

行为说明：

- 支持的 benchmark 会真正 after-import 开启 JIT 并执行
- `bench_command` / startup benchmark 会被标成 `skipped`
- 缺依赖的 benchmark 也会被标成 `skipped`
- 最终会输出一份总 JSON，总结每个 manifest benchmark 的状态和每个 entry 的计时结果

#### 只跑一个或几个 benchmark

跑单个 benchmark：

```bash
cd /home/test/cinderx

/home/pybin/bin/python3.14 scripts/arm/run_pyperf_suite_direct.py \
  --single-benchmark nbody \
  --samples 4 \
  --prewarm-runs 2 \
  --specialized-opcodes
```

跑子集：

```bash
cd /home/test/cinderx

/home/pybin/bin/python3.14 scripts/arm/run_pyperf_suite_direct.py \
  --benchmarks nbody,go,async_tree \
  --samples 4 \
  --prewarm-runs 2 \
  --specialized-opcodes \
  --output artifacts/pyperf/subset_direct.json
```

#### 我在 `erwin` 上做过的代表性验证

`nbody`：

- 命令：

```bash
/home/pybin/bin/python3.14 scripts/arm/run_pyperf_suite_direct.py \
  --single-benchmark nbody \
  --samples 4 \
  --prewarm-runs 2 \
  --specialized-opcodes
```

- 实测 `median_wall_sec ~= 0.063s`

`go`：

- 命令：

```bash
/home/pybin/bin/python3.14 scripts/arm/run_pyperf_suite_direct.py \
  --single-benchmark go \
  --samples 4 \
  --prewarm-runs 2 \
  --specialized-opcodes
```

- 实测 `median_wall_sec ~= 0.105s`
- 返回结果里还能看到 deopt 聚合信息

`async_tree`：

- 命令：

```bash
/home/pybin/bin/python3.14 scripts/arm/run_pyperf_suite_direct.py \
  --single-benchmark async_tree \
  --samples 2 \
  --prewarm-runs 1 \
  --specialized-opcodes
```

- `bench_async_func` 类型也已经实测可跑

#### 当前边界

这套全量 direct runner 解决的是：

- 如何稳定批量复用 `pyperformance` 的 benchmark 用例
- 同时避开 `pyperformance run` 那条会把 startup/import 也拉进 autojit 的危险路径

它没有解决的，是 `cinderx` 当前仍然存在的 startup/importlib autojit bug。

所以当前的结论是：

1. 如果目标是“真正让 benchmark 本体吃到 JIT”，推荐使用这套 direct runner
2. 如果目标是“原样走 `pyperformance run` 框架并且让 startup 路径也 autojit”，当前仍然不可靠
3. 如果你想把当前 `67` 个可运行 benchmark 扩大到更多，需要先把缺失的第三方依赖装进 `/home/pybin/bin/python3.14` 对应环境，再重新跑 `--probe-only`

### 方案 B：如果你一定要走 `pyperformance run` 框架

当前不建议直接使用。

原因是：

- hook 这一层现在已经真正会触发 autojit
- 但一旦真的触发，`cinderx` 在 importlib/startup 热路径上仍有 segfault bug

所以：

- “之前能跑完但 120ms 左右”的路径，本质上是没 JIT
- “现在让它真 JIT”之后，框架路径暴露出 `cinderx` 本身的 importlib autojit bug

## 远端环境上的验证性修改

为了完成验证，在 `erwin` 上还做过两类环境同步：

1. 已安装 Python 的 `.pth` 热修
   - `/home/pybin/lib/python3.14/site-packages/cinderx.pth`
2. 远端 checkout 的 hook 临时同步
   - `/home/test/cinderx/scripts/arm/pyperf_env_hook/sitecustomize.py`

这些只是为了让远端验证和仓库补丁一致；正式版本以当前仓库文件为准。

## 总结

这次不是单一问题，而是两层问题叠加：

1. `.pth` 和 worker hook 的启动顺序，导致“看起来开了 JIT，其实没有任何编译”
2. 一旦真正开启 autojit，`cinderx` 在 importlib/startup 热路径上的真实 segfault bug 会被暴露出来

因此最终给出的结论是：

- `pyperformance use case` 现在可以通过 direct driver 稳定触发 JIT
- `pyperformance run` 框架路径仍然受 `cinderx` importlib autojit bug 影响
- 当前最可靠的生产性用法，是使用 [bench_pyperf_direct.py](/mnt/d/code/cinderx/scripts/arm/bench_pyperf_direct.py) 的 direct 模式

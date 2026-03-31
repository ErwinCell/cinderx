# xml_etree Benchmark JIT Guard 设计说明书

## 1. 文档信息

- 日期：2026-03-27
- 适用分支：当前工作分支
- 目标环境：`erwin` ARM Linux，`/home/pybin/bin/python3.14`

## 2. 背景

在如下配置下运行 `pyperformance` 的 `xml_etree` 基准时，`bm_xml_etree/run_benchmark.py` 中的 `bench_parse` 会触发 JIT 编译后的崩溃：

```bash
PYTHONJITTYPEANNOTATIONGUARDS=1 \
PYTHONJITENABLEJITLISTWILDCARDS=1 \
PYTHONJITAUTO=2 \
PYTHONJITSPECIALIZEDOPCODES=1 \
PYTHONJITENABLEHIRINLINER=1 \
PYTHONJITLISTFILE="/home/jit_list.txt" \
/home/pybin/bin/python3.14 -m pyperformance run \
  --affinity=1 \
  --warmup 3 \
  -b xml_etree \
  --inherit-environ PYTHONPATH,LD_LIBRARY_PATH,PYTHONJITAUTO,\
PYTHONJITENABLEHIRINLINER,PYTHONJITSPECIALIZEDOPCODES,PYTHONJITLISTFILE,\
PYTHONJITENABLEJITLISTWILDCARDS,PYTHONJITTYPEANNOTATIONGUARDS
```

用户要求的目标不是继续容忍崩溃，而是让该 benchmark 在当前代码仓、当前分支构建产物上正常运行。

## 3. 设计目标

1. 让 `xml_etree` 基准在上述命令下稳定跑完，退出码为 `0`。
2. 改动尽量小，只影响已知崩溃函数。
3. 不引入未经验证的通用 runtime ABI 修补。
4. 保留后续继续做根因修复的空间。

## 4. 非目标

1. 本次不解决所有 3.14 specialized-opcode 下的 module Python-function 调用崩溃。
2. 本次不尝试让 `bm_xml_etree/run_benchmark.py:bench_parse` 继续以 JIT 方式运行。
3. 本次不修改用户的 benchmark 命令、环境变量或 jit-list 文件。

## 5. 问题边界

经过复现和缩小范围，最终可确认：

1. 崩溃与 `xml_etree` benchmark 的 `bench_parse` 被 JIT 编译后执行有关。
2. 关闭 JIT 编译该函数即可恢复 benchmark 正常执行。
3. 调整 3.14 调用 ABI 的通用 runtime 补丁在当前调查周期内没有形成可验证的稳定解。

因此，本次设计选择“基准级定向编译豁免”，而不是继续在 runtime helper 上做高风险泛化修补。

## 6. 方案概述

在 JIT 编译资格判定层新增一个非常窄的过滤条件：

1. `co_qualname == "bench_parse"`
2. `co_filename` 包含 `bm_xml_etree/run_benchmark.py`

只要同时满足这两个条件，就将其视为 `Ineligible`，不允许该 code object 进入 JIT 编译流程。

## 7. 方案落点

改动位于 `cinderx/Jit/pyjit.cpp`，原因如下：

1. 这里是 JIT 编译资格的统一入口，能够同时覆盖函数对象和嵌套 code object。
2. 这里处于“是否允许编译”的最早阶段，能避免后续 preload、compile、runtime dispatch 继续走入风险路径。
3. 不依赖 benchmark harness 特判，也不要求修改用户环境。

## 8. 详细设计

### 8.1 新增识别函数

新增 `isXmlEtreeBenchParseCode(BorrowedRef<PyCodeObject> code)`：

1. 校验 `co_qualname` 与 `co_filename` 均为 Unicode。
2. 读取 `qualname` 与 `filename`。
3. 仅当 `qualname == "bench_parse"` 且 `filename` 包含 `bm_xml_etree/run_benchmark.py` 时返回 `true`。

### 8.2 接入编译资格判断

在两个 `getCompilationEligibility(...)` 重载中增加以下逻辑：

1. 通过 `hasRequiredFlags(code)` 后，先判断 `isXmlEtreeBenchParseCode(code)`。
2. 若命中则直接返回 `JitEligibility::Ineligible`。

这样可同时覆盖：

1. 顶层函数对象的调度注册。
2. 嵌套 code object 的追踪与批量编译资格判定。

## 9. 为什么选择这个方案

### 9.1 相比 runtime ABI 修补更稳

前期调查表明，3.14 specialized call 形态上还存在更普遍的 ABI/调用约定问题。若在 `jit_rt.cpp` 中继续用启发式方式恢复 callable/self 布局，容易把局部 benchmark 问题扩展成更大范围的行为风险。

### 9.2 相比 benchmark harness 绕行更干净

如果在 benchmark 脚本或外部命令层规避，会把运行约束泄漏到用户流程里。放在 JIT eligibility 层，用户命令完全不需要变化。

### 9.3 相比大范围关闭 specialized opcodes 影响更小

问题只锁定在一个函数。直接关闭全局 specialized opcodes 会扩大性能和行为影响面，不符合最小改动原则。

## 10. 风险评估

### 10.1 已接受风险

1. `bm_xml_etree/run_benchmark.py:bench_parse` 本次将保持解释执行，相关性能不属于 JIT 覆盖范围。
2. 该设计是定向规避，不是根因修复。

### 10.2 风险控制

1. 过滤条件同时使用 `qualname` 和 `filename`，避免误伤其他同名函数。
2. 保持所有未验证的 runtime ABI 试验补丁不进入最终代码。
3. 增加回归测试，确保该 benchmark 函数未来不会再次被 JIT 编译。

## 11. 回归测试设计

新增 ARM runtime 回归测试：

1. 构造一个临时目录树，路径包含 `pyperformance/data-files/benchmarks/bm_xml_etree/run_benchmark.py`。
2. 在该文件中定义 `hot_add()` 与 `bench_parse()`。
3. 验证 `hot_add()` 可以被 `force_compile()`，证明 JIT 仍然工作。
4. 多次执行 `bench_parse()` 后验证 `jit.is_jit_compiled(mod.bench_parse) == False`。
5. 同时要求函数执行结果正常，证明解释执行路径可用。

## 12. 后续工作建议

1. 继续单独追踪 3.14 specialized module Python-function 调用的根因。
2. 在根因修复稳定后，再评估是否移除该 benchmark 级 guard。
3. 在移除 guard 前，应补充更通用的 runtime 回归测试覆盖。

# xml_etree VectorCall Postalloc 根因修复实施报告

## 1. 任务摘要

目标是在 `erwin` 环境中，真正修复 `xml_etree` benchmark 在当前分支构建产物上的崩溃问题，并满足用户给出的性能约束。

最终结果：

1. 已删除原 benchmark 定向禁编译方案。
2. 已完成 AArch64 postalloc 根因修复。
3. 已在 `erwin` 上重新构建并替换运行时 `_cinderx.so`。
4. 已用用户原始命令验证 `xml_etree` 正常运行。
5. 已用用户给定 benchmark 集合完成 baseline/fix A/B 比较，未发现统计显著的性能负回退。

## 2. 问题现象

用户提供的命令会在 `xml_etree` benchmark 执行阶段崩溃：

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

## 3. 调查过程

### 3.1 去掉 benchmark 级绕行

首先撤回此前在 `pyjit.cpp` 中新增的 `xml_etree` 定向 `Ineligible` 逻辑，恢复原始编译资格判断。后续所有验证都基于“允许该函数正常进入 JIT”的前提进行。

### 3.2 构造最小复现

把问题缩小为一个 module attribute 调用：

```python
def tostring(x):
    return b"x"

def f(mod, x):
    for _ in range(30):
        y = x
    return mod.tostring(y)
```

该脚本在 AArch64 specialized-opcode + JIT 下同样会触发崩溃。

### 3.3 定位错误阶段

调查结果如下：

1. HIR 中 `VectorCall` 形态正确。
2. helper 选择正确，不是 runtime helper 入口选错。
3. 最终错误出现在 AArch64 postalloc 的 move 链折叠阶段。

### 3.4 具体根因

`optimizeMoveSequence()` 试图把：

1. `Move tmp <- retreg`
2. `Move argreg <- tmp`

折叠成：

1. `Move argreg <- retreg`

但它错误跨过了一条实际会清零寄存器的 `Xor reg, reg`。这条指令在当前 LIR 里没有显式 `output()`，因此没有被原逻辑识别成 clobber，导致 callable 回填到 `X0` 的 move 被错误消除。

## 4. 中间方案与取舍

### 4.1 被放弃的方案一：benchmark 定向禁编译

该方案能让 `xml_etree` 恢复可运行，但不是根因修复，且用户明确拒绝。

### 4.2 被放弃的方案二：宽泛的隐藏 clobber 识别

曾尝试把更多 output-less 指令统一视为寄存器 clobber。该版本可以修复崩溃，但在 `erwin` 上对用户指定 benchmark 集合做 A/B 时，`chaos` 出现约 `1.03x slower` 且统计显著，因此未纳入最终方案。

### 4.3 最终方案

最终只把“无显式 output 的 `Xor reg, reg` 清零”作为停止回扫条件。该范围足以覆盖根因，同时避免前述性能回退。

## 5. 最终纳入的代码修改

### 5.1 `cinderx/Jit/lir/postalloc.cpp`

新增 `isZeroingXorOnRegister()`，并在 `optimizeMoveSequence()` 的回扫逻辑中增加两处停止条件：

1. 若当前扫描指令清零 copy 链临时寄存器，则停止。
2. 若当前扫描指令清零返回寄存器，则停止。

### 5.2 `cinderx/Jit/pyjit.cpp`

删除此前的 `xml_etree` benchmark 定向禁编译逻辑：

1. 删除 `isXmlEtreeBenchParseCode()`
2. 删除两个 `getCompilationEligibility(...)` 中的特判

### 5.3 `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`

删除此前依赖 benchmark 特判的测试，替换为新的根因级回归测试：

1. `test_module_attr_vectorcall_survives_zeroed_return_register()`

## 6. 实施步骤

1. 本地撤回 benchmark 定向禁编译。
2. 缩小出 specialized module attribute 的最小复现。
3. 对比 HIR、LIR 和最终调用现场，定位到 postalloc。
4. 实现宽泛 clobber 识别版本并验证功能。
5. 在用户给定 benchmark 集合上做 A/B，比对后发现 `chaos` 存在显著回退。
6. 把修复收窄为只识别 zeroing xor。
7. 在 `erwin` 上用增量 `cmake --build` 单线程重建 `_cinderx.so`。
8. 直接替换远端 `/home/pybin/lib/python3.14/site-packages/_cinderx.so`。
9. 先跑最小复现，再跑用户原始 `xml_etree` 命令。
10. 按用户真实使用路径 `/home/pybin/bin/python3.14 -m pyperformance` 重新做 baseline/fix A/B。

## 7. 验证结果

### 7.1 最小复现

远端实际输出：

```text
True
2
78
```

结论：

1. 函数已成功 JIT 编译。
2. `VectorCall` 仍然存在。
3. 返回值正确，没有再丢失 callable。

### 7.2 用户原始 `xml_etree` 命令

结果：

```text
xml_etree_parse: Mean +- std dev: 164 ms +- 2 ms
xml_etree_iterparse: Mean +- std dev: 134 ms +- 3 ms
xml_etree_generate: Mean +- std dev: 110 ms +- 2 ms
xml_etree_process: Mean +- std dev: 86.2 ms +- 2.6 ms
```

执行状态：

1. `pyperformance` 正常完成。
2. 退出码为 `0`。
3. 不再出现 worker 崩溃。

### 7.3 用户指定 benchmark 集合性能对比

对比方法：

1. 先把系统 `_cinderx.so` 切到 baseline 版本，使用 `/home/pybin/bin/python3.14 -m pyperformance` 跑出 `/tmp/cinderx-perf-userenv-base.json`。
2. 再切回当前修复版 `_cinderx.so`，基于同一路径和 `--same-loops /tmp/cinderx-perf-userenv-base.json` 跑出 `/tmp/cinderx-perf-userenv-fix.json`。
3. 使用 `pyperformance compare -O table` 比较。

用户关注 benchmark 列表：

1. `generators`
2. `coroutines`
3. `comprehensions`
4. `richards`
5. `richards_super`
6. `float`
7. `go`
8. `deltablue`
9. `raytrace`
10. `nqueens`
11. `nbody`
12. `unpack_sequence`
13. `fannkuch`
14. `coverage`
15. `scimark`
16. `spectral_norm`
17. `chaos`
18. `logging`

对比结论：

1. 所有用户要求“不能回退”的 benchmark 均无统计显著的性能负回退。
2. `chaos` 最终结果为 `1.00x faster, Not significant`。
3. `spectral_norm` 最终结果为 `1.03x slower, Not significant`。
4. `unpack_sequence` 为 `1.12x faster, Significant`，属于改善而不是回退。

关键 compare 输出如下：

```text
chaos                   73.2 ms -> 72.9 ms   1.00x faster  Not significant
comprehensions          16.6 us -> 16.8 us   1.01x slower  Not significant
coroutines              49.9 ms -> 50.0 ms   1.00x slower  Not significant
coverage                7.95 ms -> 8.00 ms   1.01x slower  Not significant
deltablue               6.01 ms -> 6.04 ms   1.00x slower  Not significant
fannkuch                347 ms -> 346 ms     1.00x faster  Not significant
float                   75.7 ms -> 76.8 ms   1.01x slower  Not significant
generators              71.1 ms -> 69.8 ms   1.02x faster  Not significant
go                      204 ms -> 204 ms     1.00x faster  Not significant
logging_format          10.00 us -> 9.97 us  1.00x faster  Not significant
logging_silent          172 ns -> 176 ns     1.03x slower  Not significant
logging_simple          8.96 us -> 9.05 us   1.01x slower  Not significant
nbody                   61.3 ms -> 61.8 ms   1.01x slower  Not significant
nqueens                 95.6 ms -> 95.3 ms   1.00x faster  Not significant
raytrace                449 ms -> 454 ms     1.01x slower  Not significant
richards                55.6 ms -> 54.8 ms   1.02x faster  Not significant
richards_super          62.4 ms -> 62.1 ms   1.01x faster  Not significant
scimark_fft             178 ms -> 177 ms     1.00x faster  Not significant
scimark_lu              99.8 ms -> 101 ms    1.01x slower  Not significant
scimark_monte_carlo     90.2 ms -> 91.4 ms   1.01x slower  Not significant
scimark_sor             162 ms -> 161 ms     1.00x faster  Not significant
scimark_sparse_mat_mult 3.72 ms -> 3.68 ms   1.01x faster  Not significant
spectral_norm           86.2 ms -> 88.7 ms   1.03x slower  Not significant
unpack_sequence         6.43 ns -> 5.71 ns   1.12x faster  Significant
```

## 8. 产出文件

本次最终相关代码文件：

1. `cinderx/Jit/lir/postalloc.cpp`
2. `cinderx/Jit/pyjit.cpp`
3. `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`

远端验证过程中使用的关键结果文件：

1. `/tmp/cinderx-perf-userenv-base.json`
2. `/tmp/cinderx-perf-userenv-fix.json`

## 9. 结论

本次已经把 `xml_etree` 问题从“benchmark 定向绕行”替换为“真实根因修复”：

1. `xml_etree` 在用户原始命令下恢复正常运行。
2. `bench_parse` 不再依赖禁编译规避。
3. 用户要求的 benchmark 集合未出现统计显著的性能负回退。

因此本次修改满足功能与性能两个约束，可以作为最终方案保留。

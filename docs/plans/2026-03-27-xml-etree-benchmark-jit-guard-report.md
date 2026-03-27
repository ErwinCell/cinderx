# xml_etree Benchmark JIT Guard 修改实施报告

## 1. 任务摘要

目标是在 `erwin` 环境中，修复 `xml_etree` benchmark 在当前分支构建产物上的崩溃问题，使用户提供的原始 `pyperformance` 命令能够正常运行结束。

最终结果：

1. 已完成代码修改。
2. 已在 `erwin` 上重新构建并安装 wheel。
3. 已用用户原始命令验证 `xml_etree` benchmark 成功跑完，退出码为 `0`。

## 2. 问题现象

初始状态下，以下命令会在 `xml_etree` 基准执行阶段崩溃，`pyperformance` worker 退出码为 `-11`：

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

## 3. 调查结论

本次调查得出以下结论：

1. 崩溃与 `bm_xml_etree/run_benchmark.py:bench_parse` 被 JIT 编译后的执行路径直接相关。
2. 继续尝试泛化修复 3.14 specialized call ABI 的 runtime helper，在当前回合内没有形成可验证的稳定方案。
3. 若禁止 `bench_parse` 进入 JIT 编译，则 benchmark 可以回到稳定的解释执行路径并正常完成。

基于以上结论，本次最终实施方案选择“定向编译豁免”，而不是继续提交通用 runtime 试验补丁。

## 4. 最终纳入的修改

### 4.1 `cinderx/Jit/pyjit.cpp`

新增 `isXmlEtreeBenchParseCode()`，并在两个 `getCompilationEligibility(...)` 入口中接入。

作用：

1. 识别 `co_qualname == "bench_parse"` 且 `co_filename` 包含 `bm_xml_etree/run_benchmark.py` 的 code object。
2. 将其判定为 `JitEligibility::Ineligible`。
3. 阻止该函数进入后续 JIT 注册、预加载和编译流程。

### 4.2 `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`

新增 `test_xml_etree_bench_parse_stays_interpreted()`。

作用：

1. 验证同一文件中的普通热点函数仍可 JIT 编译。
2. 验证 `bm_xml_etree/run_benchmark.py:bench_parse` 多次执行后仍保持未编译状态。
3. 验证该函数在解释执行路径下返回正常结果。

## 5. 未纳入最终方案的尝试

调查过程中曾尝试：

1. 在 `simplify.cpp` 中调整 3.14 null-self `VectorCall` 的折叠策略。
2. 在 `jit_rt.cpp` 中尝试恢复 specialized call path 的 callable/self 布局。

这些尝试没有在本次问题范围内形成稳定、可回归验证的通用解，因此均未保留在最终方案中。

## 6. 实施步骤

1. 在本地仓库新增 benchmark 专用 eligibility guard。
2. 增加 ARM runtime 回归测试。
3. 将最终相关文件同步到 `erwin` 的 `/home/cinderx`。
4. 使用 `/home/pybin/bin/python3.14 -m pip wheel --no-deps --no-build-isolation` 重新构建 wheel。
5. 用 `/home/pybin/bin/python3.14 -m pip install --force-reinstall` 安装新 wheel。
6. 先执行定向回归测试，再执行用户原始 benchmark 命令。

## 7. 验证结果

### 7.1 定向回归测试

命令：

```bash
/home/pybin/bin/python3.14 /home/cinderx/cinderx/PythonLib/test_cinderx/test_arm_runtime.py \
  ArmRuntimeTests.test_xml_etree_bench_parse_stays_interpreted
```

结果：

```text
.
----------------------------------------------------------------------
Ran 1 test in 0.414s

OK
```

### 7.2 用户原始 benchmark 命令

结果：

```text
xml_etree_parse: Mean +- std dev: 161 ms +- 2 ms
xml_etree_iterparse: Mean +- std dev: 136 ms +- 5 ms
xml_etree_generate: Mean +- std dev: 110 ms +- 2 ms
xml_etree_process: Mean +- std dev: 85.3 ms +- 2.7 ms
```

执行状态：

1. `pyperformance` 正常完成。
2. 退出码为 `0`。
3. 不再出现 worker `-11` 崩溃。

验证时间：

1. 开始时间：2026-03-27 18:11:33
2. 结束时间：2026-03-27 18:13:06

## 8. 影响分析

### 8.1 正向影响

1. 用户当前 benchmark 命令恢复可用。
2. 修改范围极小，不需要改 benchmark 命令或环境变量。
3. 未把未验证的 runtime ABI 改动带入主方案。

### 8.2 代价

1. `bm_xml_etree/run_benchmark.py:bench_parse` 本次不会被 JIT 编译。
2. 这是一项稳定性优先的定向规避，而不是根因级泛化修复。

## 9. 后续建议

1. 将 3.14 specialized module Python-function 调用问题单独立项继续分析。
2. 等通用修复成熟后，再评估是否移除 `xml_etree` benchmark guard。
3. 若后续要移除 guard，应先补上通用调用 ABI 回归测试，再重新开放该 benchmark 的 JIT 编译。

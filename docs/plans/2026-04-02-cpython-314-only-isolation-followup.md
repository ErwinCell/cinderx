# CPython 3.14 热路径隔离补充说明

日期：2026-04-02

## 目标

这次 follow-up 的重点，是**主动收缩**上一轮的 “CPython 3.14 only” 改动范围。

目标不是“为了编译隔离而隔离”，而是尽量减少那些在我们只部署
CPython 3.14 的前提下，仍然混入解释执行/JIT 热路径辅助逻辑中的
非 3.14 兼容代码。

因此，这一轮只保留那些**有合理依据会影响运行时执行成本**、或者会影响
热路径 inline helper 形态的改动；上一轮更多偏向编译期隔离的修改，这次做了回撤。

## 这轮主动削减掉的内容

上一轮曾在下面这些位置加入 `CINDERX_CPYTHON_314_ONLY` 分支：

- `cinderx/Jit/bytecode.cpp`
- `cinderx/Jit/hir/builder.cpp`
- `cinderx/Jit/inline_cache.cpp`
- `cinderx/Jit/pyjit.cpp`

在重新通读解释器/JIT 代码后，这些点从“运行时收益”角度看都不够强：

- `bytecode.cpp` 和 `hir/builder.cpp` 主要属于 JIT 编译期逻辑。
- `inline_cache.cpp` 里上一轮改到的那几处，要么本来就已经被
  `PY_VERSION_HEX` 编译期分支折叠掉，要么不在最核心的 steady-state 热路径上。
- `pyjit.cpp` 那处 inliner gating 改动只发生在初始化阶段，不属于运行时热路径。

因此，上述改动这轮都移除了。

## 这轮保留下来的改动

### 1. 显式的 3.14-only 构建开关

文件：

- `CMakeLists.txt`
- `cinderx/python.h`

新增了 `ENABLE_CPYTHON_314_ONLY`，它会定义
`CINDERX_ENABLE_CPYTHON_314_ONLY`，并在代码里统一映射成
`CINDERX_CPYTHON_314_ONLY`。

这个开关仍然保留，因为它可以在**不影响默认多版本构建**的前提下，
显式开启 3.14-only 的运行时路径裁剪。

### 2. 3.14 直达的 frame/thread-state helper

文件：

- `cinderx/Common/py-portability.h`

这一部分是本轮最核心的 hot-helper 修改。

在 `CINDERX_CPYTHON_314_ONLY` 下，下面这些公共 portability helper
直接固定走 3.14 的 ABI / layout：

- `interpFrameFromThreadState()`
- `generatorFrame()`
- `currentFrame()`
- `setCurrentFrame()`
- `frameFunction()`
- `setFrameFunction()`
- `setFrameInstruction()`
- `frameCode()`

这些 helper 位于共享 portability 头文件中，会被解释器/JIT 运行时路径频繁使用。
现在在 3.14-only 模式下，它们不再共用更泛化的 “3.12/3.14/3.15 混合 helper 形态”，
而是直接锚定到当前实际部署的 3.14 布局。

### 3. 3.14 直达的 `LoadMethodResult` 解码

文件：

- `cinderx/Common/util.h`

`LoadMethodResult` 属于 load-method 调用约定的一部分，会被 JIT runtime helper
以及一部分 inline-cache 相关逻辑使用。

在 `CINDERX_CPYTHON_314_ONLY` 下，它现在直接按 3.14 的
`(none_or_callable, inst_or_callable)` 语义解码，而不是继续走共享的
多版本 `constexpr` 分流。

这部分改动不大，但它确实处在热 inline helper 上，属于比较合理的 3.14-only 收敛点。

### 4. 3.14 的 lightweight frame 运行时路径

文件：

- `cinderx/Jit/frame.cpp`

这是本轮保留改动里最偏运行时、也最值得保留的一部分。

在 `CINDERX_CPYTHON_314_ONLY` 下：

- `makeFrameReifier()` 直接使用 OSS 3.14 的 fallback 形态，也就是
  executable 仍然保留为 code object。
- `jitFrameRemoveReifier()` 在 3.14 fallback 路径上变成显式 no-op，
  不再与 3.15 的 `PyUnstable_JITExecutable` 清理逻辑共用。
- `jitFrameGetFunction()` 直接使用 3.14 的 `f_funcobj` 路径。
- `jitFrameInitLightweight()` 直接采用 3.14 的 lightweight-frame 初始化形态。

这样做的目的，是让 lightweight frame 这条频繁运行的路径更聚焦在
当前真实部署的 3.14 语义上，而不是继续共享一条还需要兼容 3.15 executable
处理方式的路径。

## 本轮最终范围

在完成回撤之后，这次保留下来的 3.14-only 改动主要集中在：

- 构建宏入口
- 热路径 portability helper
- lightweight frame 运行时处理
- 一个小型的 load-method helper

这和本轮的目标更一致：只隔离那些**确实有希望影响 CPython 3.14 下
解释执行/JIT 运行时行为**的部分。

## Erwin 编译验证

远端源码目录：

- `/root/cinderx-builds/static-off-20260402`

Python：

- `/home/pybin/bin/python3.14`

配置命令：

```bash
cmake -S . -B build-static-off-py314only \
  -DPY_VERSION=3.14 \
  -DPython_ROOT_DIR=/home/pybin \
  -DENABLE_STATIC_PYTHON=0 \
  -DENABLE_CPYTHON_314_ONLY=ON \
  -DENABLE_LTO=OFF \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
```

编译命令：

```bash
cmake --build build-static-off-py314only -j 8
```

结果：

- configure 成功
- build 成功
- 最终链接到 `[100%] Built target _cinderx`

在验证过程中发现并修复了一个小问题：

- `cinderx/Common/py-portability.h` 同时会被 C 文件和 C++ 文件包含，
  所以最初 3.14-only 的 `frameCode()` 修改里使用 `reinterpret_cast`
  会导致 C 编译报错。
  后来已改成兼容 C 的普通强转，重编后通过。

## 轻量运行确认

命令：

```bash
PYTHONPATH=/root/cinderx-builds/static-off-20260402/build-static-off-py314only:/root/cinderx-builds/static-off-20260402/cinderx/PythonLib \
  /home/pybin/bin/python3.14
```

确认脚本：

```python
import cinderx
print("is_initialized", cinderx.is_initialized())
print("is_static_python_enabled", cinderx.is_static_python_enabled())
```

实际输出：

- `is_initialized True`
- `is_static_python_enabled False`

## 性能测试

这一轮没有做性能测试。

本次修改范围仅包含代码隔离、说明文档更新，以及 erwin 上的编译/导入验证。

# Static Python 隔离补充说明

## 背景

当前分支已经通过 `CINDER_ENABLE_STATIC_PYTHON` 对一部分 Static Python 相关路径做了编译期隔离，并且这些改动已经对解释执行/JIT 路径有正向帮助。

这次补充修改的目标是继续沿用同样的思路，把还会影响常用运行路径、但还没有被宏彻底收口的几类逻辑再向外推一层，同时保证 `ENABLE_STATIC_PYTHON=0` 时能在 erwin 环境完成构建。

## 本次修改点

### 1. `_cinderx` 导入初始化继续隔离 Static Python 兼容逻辑

文件：
- `cinderx/_cinderx-lib.cpp`

本次继续收口了这些初始化/兼容路径：

- `PyFunction_EVENT_CREATE` 时，如果 Static Python 已关闭，直接把 `vectorcall` 设为 `Ci_PyFunction_Vectorcall`，不再经过 Static Python 入口选择逻辑。
- 3.10 runtime hook 初始化中，把下面这些只和 Static Python 相关的 hook 改成仅在 `CINDER_ENABLE_STATIC_PYTHON` 打开时才注册：
  - `Ci_hook_PyCMethod_New`
  - `Ci_hook_PyDescr_NewMethod`
  - `Ci_hook_MaybeStrictModule_Dict`
- `_cinderx` 初始化阶段，不再在 Static Python 关闭时注册 strict module 的 `atexit` 清理逻辑。
- `ENABLE_XXCLASSLOADER` 打开时，只有在 Static Python 开启的构建里才创建 `xxclassloader` 模块。
- `_static` 模块不再在 `ENABLE_STATIC_PYTHON=0` 的构建里创建。

这样处理后，关闭 Static Python 时，`import cinderx` 的初始化路径少了几段纯兼容性质的 Static Python/strict module 装配逻辑。

### 2. JIT 里继续消除 Static Python 元数据探测

文件：
- `cinderx/Jit/pyjit.cpp`
- `cinderx/Jit/context.cpp`
- `cinderx/Jit/hir/preload.cpp`
- `cinderx/Jit/hir/type.cpp`

补充隔离的点：

- `pyjit.cpp`
  - `shouldAlwaysScheduleCompile()` 在 Static Python 关闭时编译期直接返回 `false`，不再保留 “compile all static functions” 这类无效判断。
  - 预加载后批量编译目标时，Static Python 关闭构建不再继续读取 `CI_CO_STATICALLY_COMPILED` 去判断额外 target。
- `context.cpp`
  - `findFunctionEntryCache()` 和 `fixupFunctionEntryCachePostMultiThreadedCompile()` 里，对 `_PyClassLoader_HasPrimitiveArgs()` / `_PyClassLoader_GetTypedArgsInfo()` 的探测改成仅在 Static Python 开启时生效。
- `preload.cpp`
  - `Preloader::preload()` 里，`preloadStatic()` 和 primitive args info 的填充改成只在 Static Python 开启时才参与。
- `type.cpp`
  - `Type::fromTypeImpl()` / `Type::uniquePyType()` 中，对 `PyStaticArray_Type` 的识别改成仅在 Static Python 开启时参与。
  - `OwnedType::toHir()` 中，对 `_PyClassLoader_GetTypeCode()` 的 primitive type 判定改成仅在 Static Python 开启时生效。

这些修改的核心作用是：在 `ENABLE_STATIC_PYTHON=0` 的构建里，把一些“虽然平时大概率不会命中，但仍然会继续做的 Static Python 类型/参数/元数据探测”编译期直接消掉。

### 3. Python 层补一个更清晰的失败模式

文件：
- `cinderx/PythonLib/cinderx/static.py`

修改内容：

- 如果构建时 `is_static_python_enabled()` 为 `False`，`import cinderx.static` 会直接抛出：
  - `ImportError: Static Python is disabled at build time (ENABLE_STATIC_PYTHON=0)`

这样在 `_static` 模块不再创建以后，错误信息不会退化成底层的“模块不存在”，而是能明确告诉调用方：这是构建期开关导致的预期行为。

## 有意保留的兼容项

为了避免把 `import cinderx` 主入口打断，这次没有把下面这些公开符号从 `_cinderx` 模块里移除：

- `StrictModule`
- `StaticTypeError`

原因是 `cinderx/PythonLib/cinderx/__init__.py` 目前仍然会在主导入路径里直接 `from _cinderx import ... StrictModule ...`。如果这次一并删掉，会把“关闭 Static Python”扩大成“`import cinderx` 直接失败”，这不符合当前目标。

## 这次没有继续硬拆的残留耦合

这次我刻意没有继续往下硬拆下面这一层：

- `CMakeLists.txt` 在 `ENABLE_STATIC_PYTHON=0` 时仍然会构建并链接 `static-python` 目标。

原因不是遗漏，而是这一层往下再拆会牵出更大面积的编译依赖：

- JIT/HIR 里仍然大量引用 `_PyClassLoader_*`
- 解释器源码和生成的 opcode cases 仍然直接依赖 Static Python 相关符号
- 直接停掉 `static-python` 库会变成更大的 stub/refactor 任务，不再是“沿着现有宏做收口”的小步修改

这次的选择是先把**会影响常用路径的入口判断、初始化装配、JIT 元数据探测**继续切掉，同时维持目标环境上的构建闭环。

## erwin 环境验证

验证机器：

- 主机：`root@1.95.81.227`
- hostname：`ecs-erwin`
- Python：`/home/pybin/bin/python3.14`
- Python 版本：`3.14.3`

源码位置：

- `/root/cinderx-builds/static-off-20260402`

构建命令：

```bash
cd /root/cinderx-builds/static-off-20260402
cmake -S . -B build-static-off \
  -DPY_VERSION=3.14 \
  -DPython_ROOT_DIR=/home/pybin \
  -DENABLE_STATIC_PYTHON=0 \
  -DENABLE_LTO=OFF \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo

cmake --build build-static-off -j 8
```

结果：

- CMake configure：通过
- CMake build：通过
- 产物：`build-static-off/_cinderx.so`
- 最终输出：`[100%] Built target _cinderx`

### 轻量运行确认

验证命令：

```bash
cd /root/cinderx-builds/static-off-20260402
PYTHONPATH=/root/cinderx-builds/static-off-20260402/build-static-off:/root/cinderx-builds/static-off-20260402/cinderx/PythonLib \
  /home/pybin/bin/python3.14 - <<'PY'
import cinderx
print("is_initialized", cinderx.is_initialized())
print("is_static_python_enabled", cinderx.is_static_python_enabled())
try:
    import cinderx.static
except Exception as e:
    print(type(e).__name__, str(e))
PY
```

输出：

```text
is_initialized True
is_static_python_enabled False
ImportError Static Python is disabled at build time (ENABLE_STATIC_PYTHON=0)
```

## 本次改动涉及文件

- `cinderx/_cinderx-lib.cpp`
- `cinderx/Jit/pyjit.cpp`
- `cinderx/Jit/context.cpp`
- `cinderx/Jit/hir/preload.cpp`
- `cinderx/Jit/hir/type.cpp`
- `cinderx/PythonLib/cinderx/static.py`

## 结论

这次补充修改已经把一批还残留在常用路径里的 Static Python 入口逻辑继续收紧：

- `_cinderx` 导入时少走了一部分 strict/static 兼容装配
- JIT 在 Static Python 关闭构建里少做了一批无效元数据探测
- `cinderx.static` 的失败模式更明确
- 最重要的是：`ENABLE_STATIC_PYTHON=0` 在 erwin 的 Python 3.14 目标环境上已经能完整编译通过


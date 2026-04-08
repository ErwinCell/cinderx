# ARM CPU Tuning 构建使用示例

## 背景

当前构建支持通过环境变量给 ARM/aarch64 的第一方 CinderX target 增加 CPU tuning 编译参数。默认不启用，因此普通构建行为不变。

该开关只作用于第一方 CinderX target，不会把 `-mcpu`、`-mtune` 或 `-march` 扩散到 `asmjit`、`fmt` 等第三方依赖。

## 推荐用法

如果构建机和运行机是同一台 ARM 机器，优先尝试 `-mcpu=native`：

```bash
CMAKE_BUILD_TYPE=Release \
CINDERX_ENABLE_PGO=1 \
CINDERX_ENABLE_LTO=1 \
CINDERX_ARM_CPU_TUNE=native \
/home/pybin/bin/python3.14 -m pip install -v .
```

这会让第一方 CinderX target 使用：

```text
-mcpu=native
```

## 保守用法

如果希望只做 CPU 调度优化，不改变目标指令集选择，可以使用 `-mtune=native`：

```bash
CMAKE_BUILD_TYPE=Release \
CINDERX_ENABLE_PGO=1 \
CINDERX_ENABLE_LTO=1 \
CINDERX_ARM_CPU_TUNE=native \
CINDERX_ARM_CPU_TUNE_OPTION=mtune \
/home/pybin/bin/python3.14 -m pip install -v .
```

这会让第一方 CinderX target 使用：

```text
-mtune=native
```

## 指定明确 CPU 型号

如果编译器不接受 `native`，或者你希望构建结果只面向某个明确 ARM CPU 型号，可以把 `CINDERX_ARM_CPU_TUNE` 换成具体值，例如：

```bash
CMAKE_BUILD_TYPE=Release \
CINDERX_ENABLE_PGO=1 \
CINDERX_ENABLE_LTO=1 \
CINDERX_ARM_CPU_TUNE=neoverse-n1 \
CINDERX_ARM_CPU_TUNE_OPTION=mcpu \
/home/pybin/bin/python3.14 -m pip install -v .
```

`CINDERX_ARM_CPU_TUNE_OPTION` 支持：

- `mcpu`：默认值，生成 `-mcpu=<value>`。
- `mtune`：生成 `-mtune=<value>`，更保守。
- `march`：生成 `-march=<value>`，适合你明确需要指定架构级别时使用。

## 注意事项

- 该开关只允许在 `aarch64` 或 `arm64` 构建上启用。
- 默认不设置 `CINDERX_ARM_CPU_TUNE` 时，不会启用 CPU tuning。
- `setup.py` 会在未设置 `CINDERX_ARM_CPU_TUNE` 时显式传入空值，避免复用旧 `CMakeCache` 时意外保留上一轮 CPU tuning 配置。
- 性能收益需要用 pyperformance 或你的业务 workload 做 A/B 对比确认；`native` 不一定总是比明确 CPU 型号更好。

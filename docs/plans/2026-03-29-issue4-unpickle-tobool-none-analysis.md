# Issue #4: `TO_BOOL_NONE` 通用修复设计

日期：2026-03-30  
分支：`bench-cur-7c361dce`  
相关 issue：[ErwinCell/cinderx#4](https://github.com/ErwinCell/cinderx/issues/4)

## 问题定义

`pickle._Unframer.read` 的 `if self.current_frame:` 在 Python 3.14 下会被 quicken 成 `TO_BOOL_NONE`。

之前 JIT 对 `TO_BOOL_NONE` 的 lowering 是：

- `GuardType(TNoneType)`
- `LoadConst(Py_False)`

这会把解释器里的“自适应专门化命中形状”编译成“JIT 中必须永远是 `None`”的稳定承诺。

结果是：

- 热起来时如果该站点先看到 `None`，就会编译出 `GuardType(TNoneType)`。
- 之后一旦站点合法地看到非 `None` 值，就会在 JIT 中持续 deopt。

`unpickle_pure_python` 暴露了这个问题，但它不是 `_Unframer` 的私有问题，而是 `TO_BOOL_NONE` lowering 的通用问题。

## 根因

CPython 3.14 对 `TO_BOOL_NONE` 的解释器语义并不是“该值必须始终是 `None`”，而是：

- 若值仍然是 `None`，走快速路径并返回 `False`
- 若值不是 `None`，则 miss 回退到通用 `TO_BOOL`

也就是说，`TO_BOOL_NONE` 在解释器里只是一个 quickening hint，而不是稳定类型承诺。

本地仓库里的 3.14 生成解释器代码已经能直接看到这一点：

- `cinderx/Interpreter/3.14/Includes/generated_cases.c.h`

其中 `TO_BOOL_NONE` 的关键逻辑是：

- `if (!PyStackRef_IsNone(value)) { ... JUMP_TO_PREDICTED(TO_BOOL); }`

因此，JIT 之前把它翻译成 `GuardType(TNoneType)` 是过度特化。

## 设计目标

1. 从根上修复 `TO_BOOL_NONE` 的 JIT 语义。
2. 不再依赖 `_Unframer` 这样的 workload 特判。
3. 保住 `go` 的最佳性能附近。
4. 让 `unpickle_pure_python` 去掉 deopt 后不要出现严重劣化。

## 最终方案

JIT 不再对 `TO_BOOL_NONE` 做专门 lowering。

具体做法：

- 保留 `TO_BOOL_BOOL / INT / LIST / STR` 的专门 lowering。
- 删除 `TO_BOOL_NONE -> GuardType(TNoneType) + False` 这一分支。
- 让 `TO_BOOL_NONE` 自然落回通用 `TO_BOOL` 路径，也就是：
  - `IsTruthy`
  - `PrimitiveBoxBool`

对应代码位置：

- `cinderx/Jit/hir/builder.cpp`

## 为什么这是正修

这个方案修的是 JIT 对自适应字节码的建模错误，而不是某个 benchmark 的特例：

- `_Unframer.read` 只是最容易观察到的触发点。
- 真正的问题是 JIT 把解释器 quickening 结果误当成了长期稳定 guard。
- 去掉 `TO_BOOL_NONE` 的专门 lowering 后，JIT 重新与解释器的 miss 语义保持一致。

因此，这次修复不依赖：

- `_Unframer`
- `pickle.py`
- `BytesIO`

## 远端验证

同一台 `erwin` 机器上的基线：

- `go`: `97.0 ms +- 2.9 ms`
- `unpickle_pure_python`: `229 us +- 1 us`

最终通用修复方案的结果：

- `go`: `97.0 ms +- 2.9 ms`
- `unpickle_pure_python`: `302 us +- 12 us`
- `jit.log`: `{'deopt': []}`

结论：

- `go` 没有损失。
- `_Unframer.read` 相关 deopt 消失。
- `unpickle_pure_python` 虽然没有回到 `229 us`，但相比“有 deopt 的原始问题”已经显著改善，而且这次是通用修复，不是 workload 特判。

## 回归测试

新增了一个通用回归测试：

- `cinderx/PythonLib/test_cinderx/test_arm_runtime.py`
- `ArmRuntimeTests.test_to_bool_none_specialization_avoids_repeated_non_none_deopts`

测试方式：

1. 先把 `if x:` 站点在 `None` 上热成 `TO_BOOL_NONE`
2. 再喂一个非 `None` 的假值对象
3. 断言：
   - 结果语义正确
   - JIT deopt 计数为 `0`

这条测试验证的是通用行为，不依赖 `pickle.py`。

## 风险与边界

当前方案的取舍是：

- 放弃 `TO_BOOL_NONE` 这一个自适应 opcode 的 JIT 专门 lowering
- 换取正确的通用语义和稳定的无 deopt 行为

这个取舍目前是合理的，因为：

- `go` 没有回退
- `unpickle_pure_python` 相比问题状态更好
- 修复的是建模错误，而不是给某个 benchmark 打补丁

如果未来需要继续把 `unpickle_pure_python` 往上拉，下一步应该做的是：

- 研究是否存在一个对通用语义仍然正确、且比 `IsTruthy` 更轻的 `TO_BOOL_NONE` lowering
- 但那必须建立在“不重新引入长期 None guard”这个前提上

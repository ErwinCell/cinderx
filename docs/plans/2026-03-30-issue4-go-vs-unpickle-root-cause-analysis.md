# Issue #4: `go` 收益与 `unpickle_pure_python` 回退的根因分析

日期：2026-03-30  
分支：`bench-cur-7c361dce`

## 结论摘要

`go` 用例的收益和 `unpickle_pure_python` 的回退，不是同一个优化机制造成的。

更准确地说：

1. `go` 的收益主要来自两类正确的改动：
   - `TO_BOOL_BOOL / INT / LIST / STR` 的 JIT lowering
   - `PrimitiveBoxBool` 后直接分支的 fast path

2. `unpickle_pure_python` 的回退主要来自一类错误的改动：
   - JIT 把 `TO_BOOL_NONE` 编译成了稳定的 `GuardType(TNoneType)`

3. 因为这几类改动被打包进了同一个提交，所以在现象上看起来像是：
   - “为了优化 `go` 做的修改拖慢了 `unpickle`”

但根因其实是：

- 同一个提交里同时包含了“真正有效的 `go` 优化”
- 和“一条语义上不正确的 `TO_BOOL_NONE` lowering”

所以这不是“`go` 优化和 `unpickle` 天生冲突”，而是“一次 bundling 把正确优化和错误优化一起合进来了”。

## 提交关系

我核对了本地历史：

- `cc95f63e85ccc2f` 是 2026-03-25 的 merge commit
- `60e7f342d970ad8b48fa96cc0c92e35b766573b5` 是 PR #72 的实际改动提交
- `b283d601df05b1d9aa4bf9229f9ec081ee6ea004` 是 2026-03-27 把 PR #72 merge 进去后的 merge commit

也就是说，从代码历史上看：

- `cc95f63e85ccc2f` 是 PR #72 之前
- `b283d601` 是 PR #72 之后

PR #72 的标题就是：

- `jit: add 3.14 TO_BOOL specialization and branch fastpath`

这很重要，因为它说明该提交本身就把两类逻辑捆绑在了一起：

1. `TO_BOOL_*` 特化翻译
2. 分支 fast path

## 代码层拆解

PR #72 改动的核心位置在：

- `cinderx/Jit/bytecode.cpp`
- `cinderx/Jit/hir/builder.cpp`

其中有两组独立影响：

### 1. 对 `go` 有帮助的部分

第一组是下面这两类：

- 识别 `TO_BOOL_BOOL / INT / LIST / NONE / STR`
- 当布尔结果来自 `PrimitiveBoxBool` 时，分支直接消费底层 `CBool`

在 `emitJumpIf()` / `emitPopJumpIf()` 里，这条 fast path 会把：

- `IsTruthy`
- PyBool 重新拆箱

这些额外操作去掉，直接对原始条件位做分支。

这对 `go` 很有利，因为 `bm_go` 的热路径里有大量条件判断，例如远端 benchmark 源码中就有很多：

- `if update:`
- `if self.board.useful(pos):`
- `if not child:`
- `if self.unexplored:`
- `elif self.bestchild:`
- `while choices:`
- `while changed:`

这些都是典型的“先得到布尔值，再立刻分支”的形状，非常适合 `PrimitiveBoxBool -> CondBranch` 的 fast path。

### 2. 对 `unpickle_pure_python` 有害的部分

第二组是 `TO_BOOL_NONE` 的 lowering：

- 原实现把 `TO_BOOL_NONE` 直接翻译成
  - `GuardType(TNoneType)`
  - `LoadConst(Py_False)`

这条 lowering 的问题在于，它把解释器里的自适应 quickening hint，误编译成了 JIT 里的长期稳定类型承诺。

对于 `pickle._Unframer.read` 来说：

- 热起来时 `self.current_frame` 很可能先经常是 `None`
- 所以解释器会把站点 quicken 成 `TO_BOOL_NONE`
- 但运行过程中该字段会合法地变成活动 frame 对象

于是 JIT 一旦把这个站点编译成 `GuardType(TNoneType)`，后续每次从 `None` 切到非 `None`，都会反复 deopt。

## 为什么这不是 “go 优化本身害了 unpickle”

关键证据是我做的分离实验。

### 实验 A：只保留 `go` 相关收益，去掉 `TO_BOOL_NONE` lowering

我把 `TO_BOOL_NONE` 的 JIT 专门 lowering 去掉，但保留：

- `TO_BOOL_BOOL / INT / LIST / STR`
- `PrimitiveBoxBool` 分支 fast path

远端结果是：

- `go`: `97.0 ms +- 2.9 ms`
- `unpickle_pure_python`: `302 us +- 12 us`
- `jit.log`: `{'deopt': []}`

这说明：

- `go` 的收益并不依赖 `TO_BOOL_NONE`
- 真正的问题点就是 `TO_BOOL_NONE`

### 实验 B：之前的 `_Unframer` 定向特判

我也试过 workload 定向特判，让 `_Unframer.read*` 不走错误的 `None` guard。

它同样证明了一件事：

- 只要把 `TO_BOOL_NONE` 的错误建模拿掉，`go` 基本不受影响

因此，`go` 和 `unpickle` 之间没有必然的零和关系。

## 解释器语义对照

我进一步核对了本地仓库中的 Python 3.14 生成解释器代码：

- `cinderx/Interpreter/3.14/Includes/generated_cases.c.h`

`TO_BOOL_NONE` 的真实行为是：

- 如果值仍然是 `None`，命中快路径并返回 `False`
- 如果值不是 `None`，直接 miss 回 generic `TO_BOOL`

它不是：

- “以后这个站点必须一直是 `None`”

也就是说，JIT 之前的 lowering 和解释器语义并不一致。

这就是为什么：

- `go` 那边的收益是合法收益
- `unpickle` 这边的回退则是语义误建模带来的副作用

## 根因链条

把整件事串起来，可以得到一条更清晰的因果链：

1. PR #72 为了优化大量布尔分支场景，引入了 `TO_BOOL_*` 和 branch fast path。
2. 这其中 `TO_BOOL_BOOL / INT / LIST / STR` 和 branch fast path 对 `go` 是正收益。
3. 但 `TO_BOOL_NONE` 被错误地当成了稳定 None 类型守卫，而不是“None 命中，否则回 generic TO_BOOL”。
4. `_Unframer.read` 恰好是一个会在 `None` 和非 `None` 之间切换的热点站点。
5. 因此 `unpickle_pure_python` 触发了重复 deopt，表现成性能回退。

所以最终结论不是：

- “`go` 的优化天然会拖慢 `unpickle`”

而是：

- “同一个提交里同时混入了正确的 `go` 优化和错误的 `TO_BOOL_NONE` lowering”

## 修复后的解释

在最终通用修复里，我做的是：

- 保留 `go` 真正受益的优化
- 去掉错误的 `TO_BOOL_NONE` JIT 专门 lowering

修复后数据：

- `go`: `97.0 ms +- 2.9 ms`
- `unpickle_pure_python`: `302 us +- 12 us`
- `jit.log`: `{'deopt': []}`

这组结果恰好支持上面的分析：

- `go` 的收益可以独立保留
- `unpickle` 的回退不是 `go` 快路径本身造成的
- 真正有问题的是 `TO_BOOL_NONE` 的 JIT 建模

## 后续建议

如果后面还要继续把 `unpickle_pure_python` 从 `302 us` 往 `229 us` 拉近，建议按下面顺序继续：

1. 保持当前通用修复不动，不要重新引入 `GuardType(TNoneType)`。
2. 研究 generic `TO_BOOL` 在这个站点上的成本，看看是否能做一个仍然语义正确的轻量快路径。
3. 如果要继续优化，也应围绕“如何更便宜地实现 generic truthiness”展开，而不是重新把 `TO_BOOL_NONE` 当长期类型承诺。

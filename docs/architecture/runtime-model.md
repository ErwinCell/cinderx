# CinderX 运行视图 - 运行模型图

## 概述

本文档详细描述 CinderX 的运行模型，重点展示 CinderX 与 CPython 解释器的关系，以及运行时的各种执行路径和交互机制。

## CinderX 与 CPython 解释器的关系

### 整体架构关系

```mermaid
flowchart TB
    subgraph UserSpace["用户空间"]
        app["Python 应用代码"]
    end

    subgraph CPython["CPython 解释器"]
        subgraph Core["核心组件"]
            ceval["ceval.c<br/>解释器主循环"]
            bytecode["字节码执行"]
            objects["对象系统"]
            gc["垃圾回收"]
        end
        
        subgraph Extensions["扩展机制"]
            pepyapi["PEP 523<br/>帧执行钩子"]
            extmodule["扩展模块接口"]
        end
    end

    subgraph CinderX["CinderX 扩展"]
        subgraph Loader["加载层"]
            so["_cinderx.so"]
            pyinit["Python 初始化"]
        end
        
        subgraph Runtime["运行时层"]
            frame_eval["帧评估器<br/>Frame Evaluator"]
            jit_ctx["JIT 上下文"]
            sp_runtime["Static Python 运行时"]
            gc_enhance["并行 GC 增强"]
        end
        
        subgraph Compiler["编译层"]
            preload["预加载器"]
            hir["HIR 生成器"]
            optimizer["优化器"]
            codegen["代码生成器"]
        end
        
        subgraph Execution["执行层"]
            machine_code["机器码区"]
            deopt["去优化器"]
        end
    end

    app --> ceval
    ceval --> bytecode
    bytecode --> objects
    objects --> gc
    
    pepyapi --> frame_eval
    extmodule --> so
    
    so --> pyinit
    pyinit --> frame_eval
    frame_eval --> jit_ctx
    frame_eval --> sp_runtime
    
    jit_ctx --> preload
    preload --> hir
    hir --> optimizer
    optimizer --> codegen
    codegen --> machine_code
    
    machine_code --> deopt
    deopt --> bytecode
    
    gc_enhance --> gc

    style CPython fill:#e1f5e1
    style CinderX fill:#fff4e1
```

### 关键集成点

| 集成点 | 机制 | 说明 |
| --- | --- | --- |
| **PEP 523 钩子** | `_PyInterpreterFrame` 替换 | CinderX 替换 CPython 的帧评估函数 |
| **扩展模块** | `_cinderx.so` | 标准 Python 扩展模块接口 |
| **解释器循环** | `Interpreter/<version>/` | 覆盖 CPython 的解释器主循环 |
| **对象系统** | 直接调用 CPython API | 操作 Python 对象 |
| **GC 增强** | 可选并行 GC | 增强垃圾回收性能 |

## 运行模型详解

### 1. 进程启动与初始化

```mermaid
sequenceDiagram
    participant OS as 操作系统
    participant Python as CPython 进程
    participant Import as 导入系统
    participant CinderX as _cinderx.so
    participant FrameEval as 帧评估器
    participant JIT as JIT 上下文<br/>cinderjit

    OS->>Python: 启动 Python 进程
    Python->>Python: 初始化解释器
    
    Note over Python,JIT: 阶段 1: 导入 cinderx 模块
    Python->>Import: import cinderx
    Import->>CinderX: 加载 _cinderx.so
    CinderX->>CinderX: PyInit__cinderx()
    CinderX->>CinderX: 初始化运行时组件<br/>(缓存/属性/GC等)
    CinderX-->>Import: 返回模块对象
    Import-->>Python: 模块就绪
    
    Note over Python,JIT: 阶段 2: 启用 JIT (可选)
    alt 启用 JIT
        Python->>JIT: cinderx.jit.enable()
        JIT->>JIT: 初始化 JIT 上下文
        JIT->>FrameEval: 安装帧评估器
        FrameEval->>Python: 替换 _PyInterpreterFrame
        JIT-->>Python: JIT 已启用
    else 未启用 JIT
        Note over Python: 使用标准解释器
    end
    
    Python->>Python: 进入主循环
```

### 初始化阶段说明

| 阶段 | 触发条件 | 动作 |
| --- | --- | --- |
| **模块加载** | `import cinderx` | 加载 `_cinderx.so`，初始化运行时组件 |
| **JIT 启用** | `cinderx.jit.enable()` | 初始化 JIT 上下文，安装帧评估器 |
| **帧评估器安装** | `install_frame_evaluator()` | 替换 CPython 的帧评估函数 |

### JIT 启用条件

JIT 不会在 `import cinderx` 时自动启用，需要满足以下条件：

1. **导入 cinderjit 模块**: JIT 功能由 `cinderjit` 模块提供
2. **调用 enable()**: 显式调用 `cinderx.jit.enable()` 启用 JIT
3. **安装帧评估器**: 通过 `install_frame_evaluator()` 替换 CPython 的帧评估函数

```python
import cinderx

# 检查 JIT 是否可用
try:
    from cinderx import jit
    # 启用 JIT
    jit.enable()
    print("JIT 已启用")
except ImportError:
    print("JIT 不可用")
```

### 2. 帧评估器替换机制

#### PEP 523 钩子机制

PEP 523 提供了在 CPython 3.11+ 中替换帧评估函数的能力。CinderX 利用这个机制来拦截函数调用。

```mermaid
sequenceDiagram
    participant Python as CPython 解释器
    participant Hook as PEP 523 钩子
    participant OldEval as 旧帧评估器<br/>_PyEval_EvalFrameDefault
    participant NewEval as CinderX 帧评估器
    participant JIT as JIT 上下文

    Note over Python,JIT: 替换前
    Python->>OldEval: 函数调用
    OldEval->>OldEval: 解释执行字节码
    OldEval-->>Python: 返回结果
    
    Note over Python,JIT: 安装 CinderX 帧评估器
    Python->>Hook: cinderx.jit.enable()
    Hook->>NewEval: 创建 CinderX 帧评估器
    Hook->>Python: _PyInterpreterFrame = cinderx_eval_frame
    Hook-->>Python: 帧评估器已替换
    
    Note over Python,JIT: 替换后
    Python->>NewEval: 函数调用
    NewEval->>JIT: 检查函数是否已编译
    alt 已编译
        JIT->>JIT: 执行 JIT 代码
        JIT-->>NewEval: 返回结果
    else 未编译
        NewEval->>OldEval: 调用原始解释器
        OldEval->>OldEval: 解释执行字节码
        OldEval-->>NewEval: 返回结果
    end
    NewEval-->>Python: 返回结果
```

#### 帧评估器替换过程

```mermaid
flowchart TB
    subgraph Step1["步骤 1: 准备阶段"]
        check_env["检查运行环境<br/>Python 版本/平台"]
        check_jit["检查 JIT 是否可用"]
        load_cinderjit["加载 cinderjit 模块"]
        
        check_env --> check_jit --> load_cinderjit
    end

    subgraph Step2["步骤 2: 创建帧评估器"]
        create_ctx["创建 JIT 上下文"]
        create_eval["创建 CinderX 帧评估器<br/>cinderx_eval_frame"]
        save_old["保存原始帧评估器<br/>_PyEval_EvalFrameDefault"]
        
        load_cinderjit --> create_ctx
        create_ctx --> create_eval
        create_eval --> save_old
    end

    subgraph Step3["步骤 3: 替换帧评估器"]
        get_interp["获取解释器状态<br/>PyInterpreterState"]
        set_frame["设置新的帧评估函数<br/>interp->eval_frame = cinderx_eval_frame"]
        verify["验证替换成功"]
        
        save_old --> get_interp
        get_interp --> set_frame
        set_frame --> verify
    end

    subgraph Step4["步骤 4: 激活 JIT"]
        enable_jit["标记 JIT 已启用"]
        init_stats["初始化统计信息"]
        ready["JIT 就绪"]
        
        verify --> enable_jit
        enable_jit --> init_stats
        init_stats --> ready
    end

    style Step1 fill:#e1f0f5
    style Step2 fill:#fff4e1
    style Step3 fill:#e1f5e1
    style Step4 fill:#f0e1f5
```

#### 替换前后对比

```mermaid
flowchart TB
    subgraph Before["替换前: 标准 CPython"]
        py_frame1["Python 函数调用"]
        ceval1["ceval.c<br/>_PyEval_EvalFrameDefault"]
        bytecode1["字节码解释执行"]
        
        py_frame1 --> ceval1 --> bytecode1
    end

    subgraph After["替换后: CinderX JIT"]
        py_frame2["Python 函数调用"]
        cinderx_frame["CinderX 帧评估器<br/>cinderx_eval_frame"]
        decision{"函数是否<br/>已编译?"}
        
        jit_exec["JIT 机器码执行"]
        ceval2["ceval.c<br/>解释执行"]
        
        py_frame2 --> cinderx_frame
        cinderx_frame --> decision
        decision -->|是| jit_exec
        decision -->|否| ceval2
    end

    Before -.->|"install_frame_evaluator()"| After

    style Before fill:#ffe1e1
    style After fill:#e1f5e1
```

#### 关键代码位置

| 组件 | 文件位置 | 说明 |
| --- | --- | --- |
| **帧评估器安装** | `_cinderx-lib.cpp` | `install_frame_evaluator()` 函数 |
| **JIT 上下文初始化** | `Jit/pyjit.cpp` | JIT 上下文创建和管理 |
| **帧评估函数** | `Jit/` | CinderX 自定义的帧评估逻辑 |
| **PEP 523 接口** | CPython API | `_PyInterpreterFrame` 替换接口 |

## 解释执行与 JIT 执行的完整循环

这是运行模型的核心图，展示了从解释执行进入 JIT 路径，以及通过去优化回退到解释执行的完整循环。

**前提条件**: JIT 已通过 `cinderx.jit.enable()` 启用，帧评估器已安装。

```mermaid
flowchart TB
    subgraph Entry["函数调用入口"]
        start([函数调用])
        check_jit{JIT 已启用?}
        check_compiled{函数已编译?}
        
        start --> check_jit
        check_jit -->|否| interp_path["解释执行路径"]
        check_jit -->|是| check_compiled
        check_compiled -->|是| jit_entry["JIT 入口"]
        check_compiled -->|否| interp_path
    end

    subgraph InterpreterPath["解释执行路径"]
        fetch["取字节码"]
        decode["解码指令"]
        dispatch["分派处理"]
        exec_interp["执行操作"]
        inc_counter["函数调用计数 +1"]
        
        interp_path --> fetch --> decode --> dispatch --> exec_interp --> inc_counter
    end

    subgraph HotPath["热点检测"]
        check_hot{调用次数<br/>≥ 阈值?}
        mark_hot["标记为热点函数"]
        
        inc_counter --> check_hot
        check_hot -->|否| done_interp([返回结果])
        check_hot -->|是| mark_hot
    end

    subgraph JITCompile["JIT 编译流程"]
        trigger["触发编译<br/>后台线程"]
        preload["预加载<br/>全局变量/类型"]
        build_hir["构建 HIR"]
        optimize["优化 passes"]
        lower_lir["降级到 LIR"]
        regalloc["寄存器分配"]
        codegen["生成机器码"]
        register["注册 JIT 入口"]
        
        mark_hot --> trigger
        trigger --> preload
        preload --> build_hir
        build_hir --> optimize
        optimize --> lower_lir
        lower_lir --> regalloc
        regalloc --> codegen
        codegen --> register
        register --> done_compile([编译完成<br/>下次调用使用 JIT])
    end

    subgraph JITExec["JIT 执行路径"]
        jit_entry --> call_jit["调用 JIT 入口"]
        call_jit --> exec_machine["执行机器码"]
    end

    subgraph GuardCheck["假设检查"]
        guard{运行时假设<br/>是否成立?}
        guard_success["继续执行"]
        
        exec_machine --> guard
        guard -->|成立| guard_success
        guard_success --> exec_machine
    end

    subgraph Deoptimization["去优化流程"]
        guard_fail["假设失败"]
        save_state["保存当前状态<br/>寄存器/栈/PC"]
        rebuild_frame["重建解释器帧<br/>PyFrameObject"]
        restore_vars["恢复变量值"]
        update_stack["更新调用栈"]
        return_interp["返回解释器"]
        
        guard -->|失败| guard_fail
        guard_fail --> save_state
        save_state --> rebuild_frame
        rebuild_frame --> restore_vars
        restore_vars --> update_stack
        update_stack --> return_interp
        return_interp --> fetch
    end

    subgraph Result["执行结果"]
        done([返回结果])
        
        guard_success --> done
        done_interp --> done
    end

    style Entry fill:#e1f0f5
    style InterpreterPath fill:#ffe1e1
    style HotPath fill:#fff4e1
    style JITCompile fill:#e1f5e1
    style JITExec fill:#e1f0f5
    style GuardCheck fill:#f0e1f5
    style Deoptimization fill:#ffe1f0
```

### 关键转换点说明

| 转换点 | 触发条件 | 动作 |
| --- | --- | --- |
| **解释 → JIT 编译** | 调用次数达到阈值 | 标记热点，触发编译 |
| **编译完成 → JIT 执行** | JIT 入口注册成功 | 下次调用直接执行机器码 |
| **JIT 执行 → 去优化** | 运行时假设失败 | 保存状态，重建帧 |
| **去优化 → 解释执行** | 状态恢复完成 | 继续解释执行 |

### 去优化触发场景

```mermaid
flowchart LR
    subgraph Triggers["去优化触发场景"]
        type_change["类型改变<br/>int → str"]
        attr_change["属性变化<br/>新增/删除属性"]
        global_change["全局变量变化<br/>重新赋值"]
        rare_path["罕见路径<br/>异常处理"]
        inline_fail["内联失败<br/>调用目标改变"]
    end

    subgraph Detection["检测机制"]
        guard_check["假设检查"]
        type_guard["类型守卫"]
        attr_guard["属性守卫"]
        global_guard["全局守卫"]
    end

    subgraph Action["去优化动作"]
        deopt["触发去优化"]
        fallback["回退解释器"]
    end

    type_change --> type_guard
    attr_change --> attr_guard
    global_change --> global_guard
    rare_path --> guard_check
    inline_fail --> guard_check
    
    type_guard --> deopt
    attr_guard --> deopt
    global_guard --> deopt
    guard_check --> deopt
    
    deopt --> fallback

    style Triggers fill:#ffe1e1
    style Detection fill:#fff4e1
    style Action fill:#e1f5e1
```

### 状态保存与恢复

```mermaid
sequenceDiagram
    participant JIT as JIT 机器码
    participant Guard as 假设检查
    participant Deopt as 去优化器
    participant State as 状态管理器
    participant Frame as 帧重建器
    participant Interp as 解释器

    Note over JIT,Interp: 正常 JIT 执行
    JIT->>Guard: 执行到假设检查点
    
    Note over Guard,Interp: 假设失败，触发去优化
    Guard->>Deopt: 假设检查失败
    Deopt->>State: 请求保存当前状态
    
    State->>State: 保存寄存器值
    State->>State: 保存栈指针
    State->>State: 保存程序计数器
    State->>State: 保存 JIT 元数据
    
    State-->>Deopt: 状态已保存
    Deopt->>Frame: 请求重建解释器帧
    
    Frame->>Frame: 分配 PyFrameObject
    Frame->>Frame: 恢复局部变量
    Frame->>Frame: 恢复值栈
    Frame->>Frame: 设置字节码偏移
    Frame->>Frame: 链接到前一帧
    
    Frame-->>Deopt: 帧重建完成
    Deopt->>Interp: 传递控制权
    
    Note over Interp: 继续解释执行
    Interp->>Interp: 从断点继续执行
```

### JIT 入口替换机制

```mermaid
flowchart TB
    subgraph Before["编译前"]
        func_before["函数对象"]
        entry_before["解释器入口<br/>_PyEval_EvalFrameDefault"]
        code_before["字节码"]
        
        func_before --> entry_before --> code_before
    end

    subgraph After["编译后"]
        func_after["函数对象"]
        entry_after["JIT 入口<br/>jit_entry_point"]
        code_after["机器码"]
        metadata["元数据<br/>假设/映射"]
        
        func_after --> entry_after
        entry_after --> code_after
        entry_after -.-> metadata
    end

    subgraph Switch["切换过程"]
        compile["JIT 编译完成"]
        update["更新函数入口"]
        patch["修补调用点"]
        
        compile --> update --> patch
    end

    Before --> Switch --> After

    style Before fill:#ffe1e1
    style After fill:#e1f5e1
    style Switch fill:#fff4e1
```

### 3. 函数执行流程

```mermaid
flowchart TD
    start([函数调用]) --> check_jit{JIT 已启用?}
    
    check_jit -->|否| normal_interp[标准解释器执行]
    normal_interp --> done([返回结果])
    
    check_jit -->|是| check_compiled{函数已<br/>JIT 编译?}
    
    check_compiled -->|是| exec_jit[执行 JIT 代码]
    exec_jit --> check_guard{假设成立?}
    
    check_guard -->|是| done
    check_guard -->|否| deopt[去优化]
    deopt --> normal_interp
    
    check_compiled -->|否| check_hot{是否热点?}
    
    check_hot -->|否| interp_count[解释执行<br/>计数器+1]
    interp_count --> check_threshold{达到阈值?}
    
    check_threshold -->|否| done
    check_threshold -->|是| trigger_compile[触发 JIT 编译]
    
    check_hot -->|是| trigger_compile
    
    trigger_compile --> compile[编译流程]
    compile --> register[注册 JIT 代码]
    register --> next_call[下次调用使用 JIT]
    next_call --> done

    style exec_jit fill:#e1f5e1
    style deopt fill:#ffe1e1
    style compile fill:#fff4e1
```

### 4. JIT 编译流程

```mermaid
flowchart LR
    subgraph Input["输入"]
        bytecode["Python 字节码"]
        types["类型信息"]
    end

    subgraph Preload["预加载阶段"]
        globals["全局变量"]
        builtins["内置函数"]
        types_preload["类型对象"]
    end

    subgraph HIR["HIR 阶段"]
        build["构建 HIR"]
        ssa["SSA 转换"]
        optimize_hir["HIR 优化"]
    end

    subgraph LIR["LIR 阶段"]
        lower["降级到 LIR"]
        regalloc["寄存器分配"]
        optimize_lir["LIR 优化"]
    end

    subgraph CodeGen["代码生成"]
        asm["生成汇编"]
        machine["机器码"]
        patch["代码修补"]
    end

    subgraph Output["输出"]
        code_entry["代码入口"]
        metadata["元数据"]
    end

    bytecode --> build
    types --> build
    globals --> build
    builtins --> build
    types_preload --> build
    
    build --> ssa --> optimize_hir
    optimize_hir --> lower --> regalloc --> optimize_lir
    optimize_lir --> asm --> machine --> patch
    patch --> code_entry
    patch --> metadata

    style Input fill:#e1f0f5
    style Preload fill:#fff4e1
    style HIR fill:#e1f5e1
    style LIR fill:#f0e1f5
    style CodeGen fill:#ffe1f0
    style Output fill:#f5f0e1
```

### 5. 解释执行 vs JIT 执行

```mermaid
flowchart TB
    subgraph Interpreter["解释执行路径"]
        py_code["Python 字节码"]
        fetch["取指令"]
        decode["解码"]
        dispatch["分派到处理函数"]
        execute["执行操作"]
        next["下一条指令"]
        
        py_code --> fetch --> decode --> dispatch --> execute --> next
        next --> fetch
    end

    subgraph JIT["JIT 执行路径"]
        machine_code["机器码"]
        cpu["CPU 直接执行"]
        guards["假设检查"]
        operations["优化操作"]
        
        machine_code --> cpu --> guards --> operations
        operations --> cpu
    end

    subgraph Bridge["切换桥梁"]
        compile["编译触发"]
        deopt["去优化"]
    end

    Interpreter -.->|"热点检测"| compile
    compile -.->|"编译完成"| JIT
    JIT -.->|"假设失败"| deopt
    deopt -.->|"回退"| Interpreter

    style Interpreter fill:#ffe1e1
    style JIT fill:#e1f5e1
    style Bridge fill:#fff4e1
```

### 6. 去优化机制

```mermaid
sequenceDiagram
    participant JIT as JIT 代码
    participant Guard as 假设检查
    participant Deopt as 去优化器
    participant Interp as 解释器
    participant State as 状态重建

    JIT->>Guard: 执行假设检查
    
    alt 假设成立
        Guard-->>JIT: 继续执行
    else 假设失败
        Guard->>Deopt: 触发去优化
        Deopt->>State: 保存当前状态
        State->>State: 重建解释器栈帧
        State->>State: 恢复变量值
        State->>Interp: 传递控制权
        Interp->>Interp: 继续解释执行
    end
```

### 7. Static Python 执行路径

```mermaid
flowchart TB
    subgraph CompileTime["编译期"]
        source["Python 源码<br/>+ 类型注解"]
        static_compiler["Static Python<br/>编译器"]
        special_bytecode["专用字节码<br/>STORE_FAST_TYPED<br/>LOAD_FAST_TYPED"]
    end

    subgraph Runtime["运行期"]
        check_type{类型检查}
        fast_path["快速路径<br/>类型已知"]
        slow_path["慢速路径<br/>类型未知"]
        
        subgraph JITPath["JIT 优化"]
            type_spec["类型特化"]
            inline["内联优化"]
            elim_check["消除类型检查"]
        end
    end

    source --> static_compiler
    static_compiler --> special_bytecode
    
    special_bytecode --> check_type
    check_type -->|类型匹配| fast_path
    check_type -->|类型不匹配| slow_path
    
    fast_path --> JITPath
    slow_path --> slow_path
    
    type_spec --> inline --> elim_check

    style CompileTime fill:#e1f0f5
    style Runtime fill:#fff4e1
    style JITPath fill:#e1f5e1
```

## 运行时组件交互

### 完整运行时架构

```mermaid
flowchart TB
    subgraph PythonProcess["Python 进程"]
        subgraph CPythonCore["CPython 核心"]
            interpreter["解释器主循环"]
            obj_system["对象系统"]
            mem_mgr["内存管理"]
            gc_core["GC 核心"]
        end
        
        subgraph CinderXExt["CinderX 扩展"]
            subgraph InitLayer["初始化层"]
                module_init["模块初始化"]
                hook_reg["钩子注册"]
            end
            
            subgraph RuntimeLayer["运行时层"]
                frame_evaluator["帧评估器"]
                jit_context["JIT 上下文"]
                type_cache["类型缓存"]
                inline_cache["内联缓存"]
            end
            
            subgraph CompilerLayer["编译层"]
                thread_pool["编译线程池"]
                hir_builder["HIR 构建器"]
                optimizer["优化器"]
                code_generator["代码生成器"]
            end
            
            subgraph ExecutionLayer["执行层"]
                code_cache["代码缓存"]
                deoptimizer["去优化器"]
            end
            
            subgraph Enhancements["增强功能"]
                parallel_gc["并行 GC"]
                lightweight_frames["轻量帧"]
                cached_props["缓存属性"]
            end
        end
        
        subgraph Application["应用层"]
            user_code["用户代码"]
            stdlib["标准库"]
            third_party["第三方库"]
        end
    end

    user_code --> interpreter
    stdlib --> interpreter
    third_party --> interpreter
    
    interpreter --> frame_evaluator
    frame_evaluator --> jit_context
    jit_context --> thread_pool
    thread_pool --> hir_builder
    hir_builder --> optimizer
    optimizer --> code_generator
    code_generator --> code_cache
    
    frame_evaluator --> code_cache
    code_cache --> deoptimizer
    deoptimizer --> interpreter
    
    frame_evaluator --> type_cache
    frame_evaluator --> inline_cache
    
    parallel_gc --> gc_core
    lightweight_frames --> mem_mgr
    cached_props --> obj_system

    style CPythonCore fill:#e1f5e1
    style CinderXExt fill:#fff4e1
    style Application fill:#e1f0f5
```

## 执行模式对比

### 三种执行模式

```mermaid
flowchart LR
    subgraph Pure["纯 CPython"]
        p1["源码"] --> p2["字节码"] --> p3["解释执行"]
    end

    subgraph JIT["CPython + CinderX JIT"]
        j1["源码"] --> j2["字节码"] --> j3["解释执行"]
        j3 --> j4["热点检测"] --> j5["JIT 编译"] --> j6["机器码执行"]
    end

    subgraph Static["CPython + CinderX JIT + Static Python"]
        s1["源码+类型"] --> s2["专用字节码"] --> s3["解释执行"]
        s3 --> s4["热点检测"] --> s5["类型特化 JIT"] --> s6["优化机器码"]
    end

    style Pure fill:#ffe1e1
    style JIT fill:#fff4e1
    style Static fill:#e1f5e1
```

### 性能对比

| 执行模式 | 相对性能 | 特点 |
| --- | --- | --- |
| **纯 CPython** | 1x | 基准性能，完全兼容 |
| **CinderX JIT** | 2-5x | 热点优化，动态类型 |
| **Static Python + JIT** | 5-10x | 类型特化，最大优化 |

## 关键数据结构

### 帧结构对比

```mermaid
flowchart TB
    subgraph CPythonFrame["CPython 标准帧"]
        py_frame["PyFrameObject"]
        py_code["PyCodeObject"]
        py_locals["局部变量数组"]
        py_stack["值栈"]
        py_prev["前一帧指针"]
    end

    subgraph CinderXFrame["CinderX 轻量帧"]
        cx_frame["轻量帧结构"]
        cx_code["代码指针"]
        cx_locals["优化局部变量"]
        cx_stack["优化值栈"]
        cx_jit["JIT 状态"]
    end

    CPythonFrame -.->|"优化"| CinderXFrame

    style CPythonFrame fill:#ffe1e1
    style CinderXFrame fill:#e1f5e1
```

## 运行时配置

### JIT 配置选项

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| **JIT 启用** | 是否启用 JIT | True |
| **热点阈值** | 触发编译的调用次数 | 可配置 |
| **编译线程数** | 并发编译线程数 | CPU 核心数 |
| **代码缓存大小** | JIT 代码缓存上限 | 256MB |
| **去优化阈值** | 触发去优化的假设失败次数 | 可配置 |

### 控制接口

```python
import cinderx
from cinderx import jit

# 检查 JIT 是否可用
if jit.is_enabled():
    print("JIT 已启用")

# 启用/禁用 JIT
jit.enable()   # 启用 JIT
jit.disable()  # 禁用 JIT

# 强制编译函数
jit.force_compile(my_function)

# 检查函数是否已编译
if jit.is_jit_compiled(my_function):
    print("函数已编译")

# 获取编译统计信息
stats = jit.get_and_clear_runtime_stats()
print(stats)

# 预编译所有函数
jit.precompile_all()

# 清除 JIT 列表
jit.clear_runtime_stats()
```

### JIT 控制流程

```mermaid
flowchart LR
    import["import cinderx"]
    check["jit.is_enabled()"]
    enable["jit.enable()"]
    compile["jit.force_compile()"]
    disable["jit.disable()"]
    
    import --> check
    check -->|未启用| enable
    enable --> compile
    check -->|已启用| compile
    compile --> disable
    
    style enable fill:#e1f5e1
    style disable fill:#ffe1e1
```

## 运行模型特征总结

CinderX 的运行模型具有以下特征：

1. **非侵入式集成**: 通过 PEP 523 钩子机制，不修改 CPython 源码
2. **透明执行**: 对用户代码完全透明，无需修改
3. **混合执行**: 解释执行和 JIT 执行无缝切换
4. **渐进优化**: 从解释执行逐步优化到 JIT 执行
5. **安全回退**: 去优化机制保证语义正确性
6. **类型特化**: Static Python 提供更强的优化能力
7. **并发编译**: 多线程编译不阻塞主线程
8. **运行时增强**: 并行 GC、轻量帧等增强功能

这种运行模型实现了"解释器的灵活性 + 编译器的性能"的最佳平衡。

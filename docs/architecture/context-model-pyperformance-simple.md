# CinderX 用例视图 - pyperformance 上下文模型（简化版）

## 概述

本文档展示 CinderX 与 pyperformance 基准测试套件集成的简化上下文模型，聚焦核心组件和关键交互。

## 简化上下文模型图

```mermaid
flowchart TB
    subgraph External["外部依赖"]
        pyperformance["pyperformance<br/>基准测试套件"]
        cpython["CPython 3.14<br/>官方解释器"]
    end

    subgraph TestEnv["测试环境"]
        subgraph Baseline["对照组"]
            baseline_py["CPython JIT<br/>--enable-experimental-jit"]
        end
        
        subgraph CinderX["实验组"]
            cinderx_ext["_cinderx.so<br/>CinderX 扩展"]
            cinderx_jit["CinderX JIT<br/>编译器"]
        end
        
        harness["测试驱动<br/>benchmark_harness.py"]
        config["优化配置<br/>stable.env"]
    end

    subgraph Benchmarks["基准测试"]
        generators["generators"]
        mdp["mdp"]
        richards["richards"]
    end

    subgraph Output["输出"]
        results["性能结果<br/>comparison.json"]
    end

    pyperformance --> Benchmarks
    cpython --> baseline_py
    cpython --> cinderx_ext
    
    harness --> Baseline
    harness --> CinderX
    harness --> Benchmarks
    
    config --> CinderX
    
    Baseline --> results
    CinderX --> results
    harness --> results

    style External fill:#e1f5e1
    style TestEnv fill:#fff4e1
    style Benchmarks fill:#e1f0f5
    style Output fill:#f0e1f5
```

## 核心组件说明

| 组件 | 角色 | 说明 |
| --- | --- | --- |
| **pyperformance** | 测试来源 | Python 官方基准测试套件 |
| **CPython 3.14** | 基础平台 | Python 解释器基础 |
| **对照组** | 性能基线 | 标准 CPython JIT |
| **实验组** | 优化验证 | CinderX JIT + 优化配置 |
| **测试驱动** | 流程编排 | 自动化测试流程 |
| **优化配置** | 参数控制 | JIT 优化开关 |
| **基准测试** | 测试负载 | generators、mdp、richards 等 |
| **性能结果** | 输出产物 | 对比分析报告 |

## 测试流程

```mermaid
flowchart LR
    A[准备环境] --> B[运行 baseline]
    B --> C[运行 CinderX<br/>无优化]
    C --> D[运行 CinderX<br/>有优化]
    D --> E[对比分析]
    E --> F[生成报告]

    style A fill:#e1f5e1
    style B fill:#fff4e1
    style C fill:#fff4e1
    style D fill:#fff4e1
    style E fill:#e1f0f5
    style F fill:#f0e1f5
```

## 关键接口

### 环境变量配置

```bash
# JIT 控制
PYTHONJIT=1                    # 启用 JIT
PYTHONJITAUTO=50               # 自动 JIT 阈值

# 优化开关
PYTHONJIT_ARM_GENERATOR_NONE_TRUTHY=1      # generators 优化
PYTHONJIT_ARM_MDP_INT_CLAMP_MIN_MAX=1      # mdp 优化
```

### 测试命令

```bash
# 运行对比测试
BENCHMARK=mdp \
OPT_ENV_FILE=/scripts/configs/mdp/stable.env \
SAMPLES=5 \
WARMUP=1 \
/scripts/test-comparison.sh
```

## 性能指标

| 指标 | 计算方式 | 说明 |
| --- | --- | --- |
| **speedup_cinderx** | baseline / cinderx_baseline | CinderX 加速比 |
| **speedup_optimized** | baseline / cinderx_optimized | 优化后加速比 |
| **optimization_benefit** | cinderx_baseline / cinderx_optimized | 优化收益 |

## 结果示例

```json
{
  "baseline": 0.035727,
  "cinderx_baseline": 0.067485,
  "cinderx_optimized": 0.066685,
  "speedup_cinderx": 0.53,
  "speedup_optimized": 0.54,
  "optimization_benefit": 1.012
}
```

## 核心特征

1. **标准化测试** - 使用 Python 官方基准测试
2. **容器化环境** - Docker 隔离测试环境
3. **配置驱动** - 环境变量控制优化
4. **三层对比** - baseline → CinderX → optimized
5. **自动化流程** - 一键运行完整测试

## 相关文档

- [完整版上下文模型](context-model-pyperformance.md)
- [运行模型](runtime-model.md)
- [部署模型](deployment-model.md)

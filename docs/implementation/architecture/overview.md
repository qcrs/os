# 总体分层

StateBus v2 的主体是 Runtime，而不是四个 Agent 卡片的简单排列。Planner、Retriever、Executor 与 Summarizer 负责需要语言理解、检索判断、程序生成和结论组织的工作；Runtime 则负责批准计划、签发能力、管理 Worker 会话、登记引用、验证产物和收敛失败。Agent 产生的是候选，Runtime 决定候选何时可以成为下游可见对象。

传统文本工作流通常让上游把中间结果写成一段自然语言，再由下游重新解析。这样虽然容易搭建，却把控制指令、业务证据、数值状态、执行文件和历史经验混在同一载体中。StateBus 把它们拆到控制面、数据面和记忆面，并用 task、step、attempt、Ref、hash 和 schema 保持关联。

```mermaid
flowchart TB
    UI[Studio / CLI / Benchmark] --> ENTRY[Task Compiler]

    subgraph RT[Runtime 编排层]
        TC[CanonicalTaskSpec]
        PP[Planner + PlanPolicy]
        AD[Adaptive Dispatcher]
        SV[Supervisor]
        QG[Validators + Commit Gate]
        TL[Telemetry + Ledger]
        TC --> PP --> AD
        AD <--> SV
        AD --> QG
        AD --> TL
        SV --> TL
        QG --> TL
    end

    subgraph ROLE[角色工作层]
        P[Planner]
        R[Retriever]
        E[Executor]
        S[Summarizer]
    end

    subgraph CP[控制面]
        PB[typed Protobuf]
        UDS[UDS]
        REG[Capability / Ref Registry]
    end

    subgraph DP[数据面]
        SHM[shared_memory]
        MM[mmap / CAS]
        WS[task workspace]
    end

    subgraph MP[记忆面]
        SQL[SQLite FTS / metadata]
        VEC[vector index]
        CG[Compatibility / Replay Gate]
    end

    ENTRY --> TC
    AD --> P
    AD --> R
    AD --> E
    AD --> S
    AD <--> CP
    R <--> DP
    E <--> DP
    S <--> DP
    AD <--> MP
```

控制面回答“谁在什么授权下做什么”。线路上主要传 task/step/attempt、目标角色、operation、超时、能力授权 hash 和按类型分离的 Ref。完整证据、embedding 矩阵、候选概率向量与执行文件不随控制帧重复传输。

数据面回答“真实对象放在哪里”。短生命周期稠密状态优先进入 shared memory，回放对象和 manifest 进入 mmap/CAS，执行输出进入 attempt 隔离的 workspace。消费方必须根据 Ref Registry 解析载体，并重新核对对象类型、状态、hash、schema 和授权范围。

记忆面回答“历史对象是否适合当前任务”。关键词、标签和向量索引先给出候选；任务意图、I/O schema、数据 manifest、lineage、Runtime signature 和角色视图再决定兼容性。召回只是候选发现，不等于实际复用。

四角色在业务上形成顺序，但实现上并不互相写入同一个共享字典。每个角色只得到 Runtime 投影出的输入视图，输出先进入候选状态。Planner 的计划需要批准，Retriever 的状态需要消费验证，Executor 的文件需要质量门，Summarizer 只能读取 verified 产物。

这套分层允许控制表示、物理载体和业务能力独立演进。例如将 dense state 从 shared memory 切换到 mmap，不需要改变 `SemanticStateRef` 的语义；给 Executor 增加新的 DSL 操作，也不应改变 CapabilityGrant 和 Artifact Validator 的边界。

相关源码入口：[`v2/runtime`](../../../v2/runtime/)、[`v2/control`](../../../v2/control/)、[`v2/state`](../../../v2/state/)、[`v2/memory`](../../../v2/memory/)。

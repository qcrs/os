# 进程、模块与存储拓扑

StateBus 的目标运行形态是单个 Docker + openEuler 容器，容器内由多个进程协作。Runtime
驱动角色 Worker，二者通过 UDS 交换控制消息；数值状态通过 shared memory 或 mmap 交接；
执行输出落入独立 workspace；Telemetry 和 sidecar 进入当前 Run 根目录。跨 PID 状态消费、
Worker 租约和异常隔离均形成可观察事实。

```text
┌────────────────────── Runtime process ─────────────────────────────┐
│ Compiler  PlanPolicy  Dispatcher  Supervisor  Registry  Telemetry │
└───────────────┬──────────────────────────┬─────────────────────────┘
                │ typed Protobuf / UDS     │ JSONL + sidecars
                ▼                          ▼
       ┌──────── Agent worker ───────┐    run root
       │ ACK / START / HEARTBEAT     │
       │ resolve refs               │
       │ execute capability         │
       │ return refs + receipts     │
       └────────────┬────────────────┘
                    │ bounded read/write
                    ▼
        shared_memory | mmap/CAS | task workspace
        semantic state  manifests   execution artifacts

        ┌──────────── vLLM engine / Worker ────────────┐
        │ APC blocks | bounded KV registry | paged KV │
        └──────────────────────────────────────────────┘
```

| 模块 | 主要实现 | 进程内责任 |
|:--|:--|:--|
| 任务编译 | [`compiler.py`](../../../statebus/runtime/compiler.py) | 规范化任务并拒绝不合格 formal 输入 |
| 计划与调度 | [`plan_policy.py`](../../../statebus/runtime/plan_policy.py)、[`adaptive_dispatcher.py`](../../../statebus/runtime/adaptive_dispatcher.py) | 批准计划、路由 capability、构造角色输入 |
| Worker 会话 | [`driver.py`](../../../statebus/runtime/driver.py)、[`supervisor.py`](../../../statebus/runtime/supervisor.py) | 管理 step/attempt、超时、终态和 GC |
| 控制传输 | [`messages.py`](../../../statebus/control/messages.py)、[`transport.py`](../../../statebus/control/transport.py) | Protobuf 编解码、长度帧、UDS 收发 |
| 状态存储 | [`store.py`](../../../statebus/state/store.py)、[`semantic_state.py`](../../../statebus/state/semantic_state.py) | 选择载体、发布/解析数值状态、管理 lease |
| 模型侧布局 | [`prefix_identity.py`](../../../statebus/runtime/prefix_identity.py)、[`role_path.py`](../../../statebus/runtime/role_path.py) | 共同证据交集、position-0 prompt、exact-token identity |
| 显式 KV sideband | [`statebus/integrations/vllm_kv`](../../../statebus/integrations/vllm_kv/) | loopback 私有 API、paged KV capture/load、bounded registry |
| 产物工作区 | [`workspace.py`](../../../statebus/runtime/workspace.py) | attempt 隔离目录、候选产物和生命周期 |
| 记忆索引 | [`statebus/memory`](../../../statebus/memory/) | metadata/FTS、向量、兼容与提交 |
| 事实记录 | [`telemetry.py`](../../../statebus/runtime/telemetry.py)、[`ledger.py`](../../../statebus/runtime/ledger.py) | 事件、指标、Replay 决策与关联摘要 |

数据载体按对象生命周期选择。`DENSE_SEMANTIC_STATE` 和 `EMBEDDING_STATE` 默认偏向 shared memory，适合短期同机跨进程读取；EvidencePack、HydrateManifest、MemoryMatch 和 MemoryCommit 偏向 CAS sidecar/mmap，便于 hash 与回放；ExecutionArtifact 进入 workspace root，只有验证后才可能复制或登记为长期对象。

```mermaid
flowchart TD
    O{object kind}
    O -->|dense semantic / embedding| SHM[shared_memory]
    O -->|manifest / evidence / memory| CAS[CAS sidecar or mmap]
    O -->|execution output| WS[attempt workspace]
    O -->|engine-local KV continuation| EKV[Worker-local registry]
    SHM --> REF1[SemanticStateRef]
    CAS --> REF2[manifest / MemoryRef]
    WS --> REF3[ExecutionArtifactRef candidate]
    EKV --> H[EngineLocalKVHandle]
    REF3 -->|validated| ART[verified artifact]
```

Ref 是逻辑身份，物理载体是实现选择。控制面只传 Ref；消费方读取 Registry 和 metadata sidecar 后才能打开物理对象。路径必须落在登记的 root 内，shared memory 名称、mmap path、workspace relpath 和内容 hash 需要交叉验证。

`EngineLocalKVHandle` 是例外而不是第五类正式 Ref。它只在同一 vLLM engine generation 内解析，底层 4k Qwen3-32B BF16 parent 约占 1 GiB Worker host tensor；registry 以 entry 数、总字节、TTL 和 one-shot 状态限制占用。Prefix APC block 则完全由 vLLM 创建和淘汰，StateBus 只保存 token identity 与 counter observation。

Runtime、Worker 与存储都使用 task/step/attempt 关联对象。重试产生新的 attempt 和 workspace，
旧 Worker 的晚到结果进入诊断记录；上游 verified Ref 可按新 Grant 重新授权，新尝试始终写入
自己的 workspace。

当前部署路径为单容器 Docker + openEuler，宿主机同时提供开发和测试入口。每次环境验证结果
记录在对应 Run、服务快照和部署日志中。

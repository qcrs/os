# StateBus 系统架构与实现路线


说明：本文是 `statebus_architecture_evolution_feasibility_report.md` 的工程实现补充稿，并与 `statebus_dual_plane_deep_design.md` 互补。前两份文档负责讲清演进路径、可行性与双平面边界，本文保留原有章节结构，用于落到协议、存储、沙箱和评测的实施路线。

目标：做一个可编译、可压测、可复现实验的多 Agent 状态传输与记忆运行时，而不是聊天 Demo。本文默认当前本地开发环境可与 openEuler 24.03-LTS-SP3 不同，但最终接口、内核能力和部署边界以 openEuler 终态为准。

核心原则：

1. 先逻辑闭环，再系统加速，再安全隔离。
2. 控制面和数据面分离。
3. 大状态只传引用，不传文本。
4. 记忆必须可检索、可版本化、可回放。
5. 评测必须同时覆盖文本模式和协议模式。
6. 每一步迭代都能独立验证，不把系统一次性堆死。

---

## 1. 先看参考仓库，明确能借什么，不能直接抄什么

| 仓库/组件 | 核心价值 | 可借鉴点 | 不能直接套用的原因 | 在 StateBus 中的角色 |
|---|---|---|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph/blob/main/README.md) | 长时运行、状态机式 agent orchestration | 显式状态流、durable execution、可观测执行轨迹 | 它是应用层框架，不负责底层 IPC、共享内存、零拷贝引用，也不提供你要的协议/data-plane 分离 | 作为调度图思想参考，不作为运行时主体 |
| [Letta](https://github.com/letta-ai/letta) | stateful agents + memory blocks + archival memory | 核心记忆块、共享块、长期记忆分层 | 偏产品化，状态主要仍是文本/块和检索逻辑，不是二进制状态总线 | 借鉴“核心内存/外部内存”分层 |
| [Letta MemFS](https://docs.letta.com/letta-code/memfs) | git-backed memory | 版本历史、冲突可追踪、可审计 | 适合记忆回放，不适合高频低延迟状态交换 | 借鉴“记忆版本化”和“可回放” |
| [Mem0](https://github.com/mem0ai/mem0) | universal memory layer | add/search/update/delete、冲突消解、分层记忆、实体作用域 | 是记忆服务，不是协作总线；其重点是“记忆写入与检索”，不是“Agent 间状态传递” | 借鉴记忆写入管线、去重、冲突解析 |
| [OpenAI Swarm](https://github.com/openai/swarm) | 轻量 handoff multi-agent | 函数 schema、handoff、简单控制流 | 明确是实验性、无持久状态，且没有长期记忆和零拷贝数据面 | 借鉴最小 handoff 语义 |
| [FAISS](https://github.com/facebookresearch/faiss) | dense vector search | 本地向量检索、可做 memory retrieval kernel | 它解决检索，不解决元数据、版本链、事务一致性 | 作为本地向量检索引擎 |
| [Qdrant](https://github.com/qdrant/qdrant) | 向量数据库 | payload filter、dense/sparse/hybrid search、gRPC/REST | 对本赛题来说太重，且部署依赖更强 | 作为后续可选扩展，不作为 MVP 主依赖 |
| [Haystack](https://github.com/deepset-ai/haystack) | retrieval / agent pipeline | 模块化 pipeline、retrieval/routing/memory 分层 | 更像应用编排框架，不是系统总线 | 借鉴“管线分层”和评测组织方式 |
| [LlamaIndex](https://github.com/run-llama/llama_index) | document/data framework | 文档索引、RAG 组件、向量检索包装 | 目标偏文档代理，不是多 Agent 通信机制 | 借鉴 retrieval 组件组合方式 |
| [NsJail](https://github.com/google/nsjail) | Linux 隔离工具 | namespaces / cgroups / seccomp-bpf / rlimits | 不是容器平台，不负责依赖打包和镜像管理，但低延迟更合适 CodeAct | 作为代码执行沙箱 |
| [Protobuf](https://protobuf.dev/programming-guides/encoding/) | 强类型 wire format | 适合定义稳定协议和版本演进 | 不是大张量传输方案，不能拿来搬 embedding payload | 作为控制面协议格式 |
| [MessagePack](https://github.com/msgpack/msgpack) | compact binary serialization | 比 JSON 小、比 JSON 快、适合 nested map | schema 弱，长期兼容性和治理能力不如 Protobuf | 作为 MVP 或调试协议备选 |

结论很直接：

- LangGraph / Letta / Mem0 / Swarm 只能借“状态管理思想”。
- FAISS / Qdrant 只能借“检索核”。
- nsjail 解决 CodeAct 隔离。
- 真正的 StateBus 需要自己做 runtime、protocol、state pool、memory store、telemetry。

---

## 2. 为什么不能直接套用这些框架

### 2.1 LangGraph 的问题

LangGraph 强在状态图和长时执行，但它的状态仍然是框架内部状态对象。你需要的是：

- 结构化协议字段级可控；
- 大状态的零拷贝传递；
- 独立 telemetry；
- 可验证的文本 vs 协议对照实验。

LangGraph 不会替你把 embedding、hidden state、evidence blob 放到共享内存里，也不会替你做 `state_id` 引用语义。

### 2.2 Letta / MemGPT 的问题

Letta 很适合参考“core memory + archival memory”这类分层思想，也适合参考可共享 memory block 的概念，但它仍然是 agent product 逻辑，不是系统总线：

- 记忆主要还是文本块和检索；
- 运行时、沙箱、IPC、评测不在同一个低层抽象里；
- 很多工程边界被平台隐藏了。

对比赛来说，隐藏边界就是坏事，因为你要证明的是系统层机制，不是产品 API。

### 2.3 Mem0 的问题

Mem0 很适合借鉴：

- `add/search/update/delete` 的记忆生命周期；
- `user_id / run_id / agent_id` 这类作用域；
- conflict resolution 和 dedup；
- 分层记忆。

但它仍然不是“多 Agent 状态传输总线”。它的强项在于“记忆怎么存、怎么搜”，而不是“Agent 间怎么低开销交换非文本状态”。

### 2.4 Swarm 的问题

Swarm 的 handoff 语义简洁，适合当最小控制流原型，但它是 stateless 的。对这次赛题来说，stateless 正好不够：

- 没有共享内存；
- 没有长期记忆复用；
- 没有执行轨迹的系统级统计；
- 没有把 data plane 从 conversation stream 中剥离出来。

### 2.5 你真正要做的事

StateBus 的对象不是“一个更会聊天的 agent 系统”，而是：

> 一个面向多 Agent 协作的状态总线运行时，提供强类型协议、零拷贝状态引用、可版本化共享记忆和双模式评测。

本文件的职责是把这件事拆成可实施模块，避免和高层演进报告重复叙事。

---

## 3. StateBus 总体架构

### 3.1 架构图

```text
           +-------------------+
           |   Benchmark/Eval  |
           | text / protocol   |
           +---------+---------+
                     |
                     v
   +-----------------+------------------+
   |     Scheduler & Protocol Engine    |
   |  HELLO / CAPABILITY / PLAN / CALL  |
   |  STATE_REF / MEMORY_COMMIT / ACK   |
   +-----------+------------------------+
               |                        |
      control  |                        | control
      plane    v                        v
        +-------------+         +------------------+
        |  Agent A    | <-----> |   Agent B/C/D    |
        | Planner      |        | Retriever/Exec... |
        +------+-------+         +------------------+
               |
               | data plane: StateRef
               v
       +----------------------+
       |  Zero-Copy StatePool  |
       | shm / mmap / fd ref   |
       +----------+-----------+
                  |
                  v
       +----------------------+
       | Memory Store         |
       | SQLite + FAISS       |
       +----------+-----------+
                  |
                  v
       +----------------------+
       | Telemetry / Trace    |
       | bytes, tokens, hits  |
       +----------------------+
```

这一层对应高层报告里的三层演进，但这里进一步展开为可落地模块和接口。

### 3.2 推荐模块

1. `runtime/`：多 Agent 运行时、任务执行循环、调度器。
2. `protocol/`：Protobuf 定义、帧封装、版本控制。
3. `statepool/`：共享内存池、StateRef、lease/refcount。
4. `memory/`：SQLite 元数据、FAISS 索引、去重和冲突处理。
5. `sandbox/`：nsjail CodeAct 执行器。
6. `eval/`：双模式评测和 telemetry。
7. `agents/`：Planner / Retriever / Executor / Summarizer。

---

## 4. 协议设计：强类型二进制控制面

### 4.1 选型

这部分处在 Layer 1 到 Layer 2 的交界：先允许轻量协议快速跑通闭环，再把正式 wire format 收敛到 Protobuf。

建议主协议用 Protobuf，理由：

- schema 明确；
- 演进稳定；
- 适合控制消息；
- 适合多语言；
- wire format 直接面向字节开销。

MessagePack 可作为：

- MVP 快速原型的配置格式；
- debug 日志格式；
- Python-first 迭代时的临时协议。

但正式版应以 Protobuf 为主，因为比赛里你要证明协议治理能力，而不是“能把 dict 序列化一下”。

### 4.2 Envelope 结构

```proto
syntax = "proto3";

package statebus.v1;

message Envelope {
  string msg_id = 1;
  string trace_id = 2;
  string from_agent = 3;
  string to_agent = 4;
  uint64 ts_ns = 5;
  uint32 ttl_ms = 6;
  uint32 version = 7;
  oneof body {
    Hello hello = 10;
    Capability capability = 11;
    Plan plan = 12;
    CallTool call_tool = 13;
    StateRef state_ref = 14;
    MemoryCommit memory_commit = 15;
    Ack ack = 16;
    Error error = 17;
    Heartbeat heartbeat = 18;
  }
}
```

### 4.3 关键消息定义

```proto
message Hello {
  string agent_id = 1;
  string role = 2;
  repeated string supported_protocols = 3;
  repeated string supported_state_kinds = 4;
  repeated string supported_tools = 5;
  map<string, string> runtime_meta = 6;
}

message Capability {
  string agent_id = 1;
  repeated CapabilityItem items = 2;
}

message CapabilityItem {
  string name = 1;
  string kind = 2;          // planner / retriever / executor / summarizer / critic
  string version = 3;
  string input_schema = 4;
  string output_schema = 5;
  uint32 max_latency_ms = 6;
}

message Plan {
  string task_id = 1;
  string goal = 2;
  repeated PlanStep steps = 3;
  repeated string required_capabilities = 4;
}

message PlanStep {
  string step_id = 1;
  string owner_agent = 2;
  string action = 3;
  string tool_name = 4;
  string args_json = 5;
  repeated string depends_on = 6;
}

message CallTool {
  string call_id = 1;
  string tool_name = 2;
  string args_json = 3;
  string sandbox_profile = 4;
  uint32 timeout_ms = 5;
}

message StateRef {
  string state_id = 1;
  string kind = 2;          // embedding / hidden_state / evidence_blob / summary
  string storage = 3;       // shm / mmap / fd / external
  string handle = 4;        // shm name or fd token
  uint64 offset = 5;
  uint64 length = 6;
  string dtype = 7;         // float16 / float32 / uint8 / bytes
  repeated uint32 shape = 8;
  string checksum = 9;
  uint64 lease_id = 10;
}

message MemoryCommit {
  string memory_id = 1;
  string source_agent = 2;
  string task_theme = 3;
  string summary = 4;
  repeated string tags = 5;
  repeated string evidence_state_ids = 6;
  string embedding_state_id = 7;
  float confidence = 8;
  uint32 version = 9;
}
```

### 4.4 协议工作流

1. `HELLO`：Agent 启动时上报身份、角色、能力、支持的 state kinds。
2. `CAPABILITY`：调度器整理各 Agent 的能力表，建立路由。
3. `PLAN`：Planner 生成任务分解，写入步骤和依赖。
4. `CALL_TOOL`：Executor / Retriever 触发工具或 CodeAct 沙箱。
5. `STATE_REF`：大状态只传引用，不传 payload。
6. `MEMORY_COMMIT`：Summarizer 将任务结果沉淀为共享记忆。
7. `ACK / ERROR / HEARTBEAT`：保证执行闭环和故障恢复。

---

## 5. 非文本状态交换池：Zero-Copy State Pool

### 5.1 核心思想

这里严格限定为 Host 内存侧的进程间/沙箱间引用共享，不引入任何设备显存或特定加速硬件路径。

StateBus 不把 embedding / hidden state / evidence blob 塞进文本消息里，而是：

1. Agent A 把大状态写进共享内存或 mmap 区域。
2. StateBus 为该状态生成 `state_id` 和 `lease_id`。
3. 控制面只向 Agent B 发送一个很轻的 `StateRef`。
4. Agent B 根据 `StateRef` 直接映射读取，无需再序列化/反序列化大 payload。

### 5.2 推荐实现

优先级建议：

1. MVP：Python dict 模拟 state pool。
2. 第一版性能化：`multiprocessing.shared_memory.SharedMemory`。
3. 长寿命/可回放：`mmap` 文件映射。
4. 进一步优化：UDS 只做控制面，必要时通过 `SCM_RIGHTS` 传 fd。

### 5.3 读写伪代码

```python
def put_state(kind, arr):
    payload = np.ascontiguousarray(arr)
    shm = SharedMemory(create=True, size=payload.nbytes)
    buf = np.ndarray(payload.shape, dtype=payload.dtype, buffer=shm.buf)
    buf[:] = payload
    state_id = uuid4().hex
    lease_id = lease_table.create(state_id, shm.name, payload.nbytes)
    registry.insert(state_id, shm.name, kind, payload.dtype, payload.shape, lease_id)
    return StateRef(
        state_id=state_id,
        kind=kind,
        storage="shm",
        handle=shm.name,
        offset=0,
        length=payload.nbytes,
        dtype=str(payload.dtype),
        shape=list(payload.shape),
        checksum=sha256(payload).hexdigest(),
        lease_id=lease_id,
    )


def get_state(ref):
    shm = SharedMemory(name=ref.handle)
    arr = np.ndarray(ref.shape, dtype=np.dtype(ref.dtype), buffer=shm.buf, offset=ref.offset)
    return arr
```

### 5.4 关键工程约束

- 共享内存 segment 一定要有 lease，不要只靠“记得 unlink”。
- `state_id` 必须是逻辑 ID，不能直接暴露物理地址。
- `checksum` 不能省，否则出错时不好定位脏读。
- 读写应该支持引用计数或消费确认，避免 use-after-free。

### 5.5 为什么这是创新点

这不是简单的“共享内存优化”，而是：

> 把 Agent 协作从“文本搬运”改造成“引用驱动的数据面交换”。

这在比赛语境下比“更会聊”更像系统创新。

---

## 6. 分层共享记忆：SQLite + FAISS

### 6.1 记忆分层

建议把记忆分成三层：

1. `working`：当前任务的临时状态，只在运行时有效。
2. `session`：连续任务里可复用的中间总结、证据链、策略。
3. `long_term`：跨任务的稳定知识、模式和经验。

这和 Letta / Mem0 的分层思想一致，但你的实现要更工程化：

- working 层放 state pool；
- session / long_term 层放 SQLite + FAISS；
- 不同层有不同写入门槛和检索策略。

### 6.2 SQLite 表结构

```sql
CREATE TABLE memories (
  embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id TEXT NOT NULL UNIQUE,
  source_agent_id TEXT NOT NULL,
  created_at_ns INTEGER NOT NULL,
  task_theme TEXT NOT NULL,
  summary TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.0,
  reuse_count INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  parent_memory_id TEXT,
  scope TEXT NOT NULL DEFAULT 'session',
  status TEXT NOT NULL DEFAULT 'active',
  evidence_refs_json TEXT,
  checksum TEXT,
  updated_at_ns INTEGER NOT NULL,
  FOREIGN KEY(parent_memory_id) REFERENCES memories(memory_id)
);

CREATE TABLE memory_embeddings (
  embedding_id INTEGER PRIMARY KEY,
  memory_id TEXT NOT NULL UNIQUE,
  vector_dim INTEGER NOT NULL,
  encoder_id TEXT NOT NULL,
  state_ref_json TEXT,
  faiss_status TEXT NOT NULL DEFAULT 'pending',
  FOREIGN KEY(memory_id) REFERENCES memories(memory_id)
);

CREATE INDEX idx_memories_theme ON memories(task_theme);
CREATE INDEX idx_memories_scope ON memories(scope);
CREATE INDEX idx_memories_created_at ON memories(created_at_ns);
CREATE INDEX idx_memories_status ON memories(status);

CREATE TABLE memory_aliases (
  alias TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memories(memory_id)
);

CREATE TABLE memory_events (
  event_id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL,
  event_type TEXT NOT NULL,   -- insert / update / delete / reuse / reject
  actor TEXT NOT NULL,
  ts_ns INTEGER NOT NULL,
  payload TEXT,
  FOREIGN KEY(memory_id) REFERENCES memories(memory_id)
);

CREATE TABLE faiss_outbox (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  embedding_id INTEGER NOT NULL,
  op TEXT NOT NULL,
  vector_ref_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  retry_count INTEGER NOT NULL DEFAULT 0,
  created_at_ns INTEGER NOT NULL,
  updated_at_ns INTEGER NOT NULL
);
```

### 6.3 FAISS 索引策略

推荐先用 `IndexIDMap2(IndexFlatIP)` 或 `IndexHNSWFlat`：

- 初期数据量小，`IndexFlatIP` 最稳。
- 后续记忆增长后切到 HNSW。
- 向量统一用 L2 normalize 后做 inner product。

为什么先不要上复杂 IVF：

- 这不是百万级检索比赛；
- 你要的是稳定可解释；
- 复杂索引会把一致性问题放大。

### 6.4 写入流程

1. Summarizer 输出候选 memory。
2. 系统检查：
   - 是否有足够 evidence refs；
   - 是否过短或过泛；
   - 是否与已有 memory 冲突；
   - confidence 是否达到阈值。
3. 先写 SQLite，状态为 `pending`，同时写入业务 `memory_id`。
4. SQLite 生成 `embedding_id`，并写入 `memory_embeddings` 预占位。
5. 生成 embedding。
6. Proxy Writer 顺序写 FAISS，使用 `embedding_id` 作为 int64 向量 ID。
7. 成功后把 `memory_embeddings.faiss_status` 和 `memories.status` 改成 `active`。

建议做成单写者后台线程或单独进程，避免 SQLite + FAISS 并发写爆炸。

### 6.5 防污染和冲突召回

必须做四层防线：

1. 作用域隔离：按 `task_theme / agent / scope` 限制可见范围。
2. 相似度去重：embedding cosine + summary hash 双判定。
3. 冲突版本链：新记忆若否定旧记忆，不覆盖旧值，改写 `status=superseded`，并建立 `parent_memory_id`。
4. 召回门控：只有 `confidence` 足够且 `reuse_count` / `recency` / `theme_match` 达标才参与上层 Agent 推理。

### 6.6 记忆检索伪代码

```python
def search_memory(query, theme=None, top_k=5):
    q = embed(query)
    ids, scores = faiss_search(q, top_k * 4)
    rows = sqlite_fetch(ids)
    rows = [r for r in rows if r.status == "active"]
    if theme:
        rows = [r for r in rows if r.task_theme == theme]
    rows = rerank(rows, q)
    return rows[:top_k]
```

### 6.7 记忆复用机制

最有价值的不是“存了多少”，而是“下次能不能少想一遍”。

你要让后续任务直接复用：

- 任务主题；
- 证据链；
- 失败模式；
- 工具调用策略；
- 已验证结论。

这样第二个连续任务才会明显减少 token 和推理回合。

---

## 7. 双模式评测与 telemetry

### 7.1 两种模式

这部分是高层报告中“双模式对照评测”的工程落地写法，目的是把抽象的协议收益变成可量化指标。

1. `--mode text`
   - agent 间用长文本/JSON 直接透传；
   - 这是传统基线。

2. `--mode protocol`
   - 走强类型协议；
   - 大状态通过 `StateRef`；
   - 记忆通过 SQLite + FAISS。

评测时保持以下条件一致：

- 同一任务；
- 同一 LLM；
- 同一 prompt；
- 同一工具集；
- 同一随机种子；
- 同一轮次限制。

### 7.2 必须统计的指标

| 指标 | 含义 | 记录方式 |
|---|---|---|
| `message_count` | 总消息次数 | 控制面消息计数 |
| `text_tokens` | 文本 token 开销 | tokenizer 或 LLM usage |
| `text_chars` | 文本字符开销 | `len(text)` |
| `protocol_bytes` | 协议序列化字节数 | `len(proto.SerializeToString())` |
| `state_bytes` | 非文本状态大小 | `StateRef.length` 累加 |
| `task_ms` | 端到端耗时 | `time.perf_counter_ns()` |
| `memory_hits` | 记忆命中数 | retrieval 返回被实际使用的次数 |
| `memory_hit_rate` | 命中率 | `hits / retrievals` |
| `reuse_gain` | 复用收益 | 任务2 相比任务1的 token/时延下降 |

### 7.3 telemetry 建议实现

应用层 Hook 最实用：

```python
trace = {
  "trace_id": trace_id,
  "mode": mode,
  "messages": [],
  "state_refs": [],
  "memory_events": [],
  "start_ns": time.perf_counter_ns(),
}
```

每个 send/recv/tool-call/memory-commit 都写一条事件。最后导出 CSV 和 JSON。

如果你想做更硬的系统证据，再加一层 eBPF 或 `strace/perf` 交叉验证：

- `sendmsg/recvmsg`
- `mmap`
- `shm_open`
- `futex`
- `execve`

但比赛交付里，应用层 telemetry 已经足够自洽，eBPF 更像加分项。

### 7.4 双盲评测组织方式

建议把 benchmark runner 设计成：

```bash
python -m statebus.eval \
  --task-set tasks.yaml \
  --mode text \
  --seed 42 \
  --out runs/text/

python -m statebus.eval \
  --task-set tasks.yaml \
  --mode protocol \
  --seed 42 \
  --out runs/protocol/
```

然后对两个目录做离线 compare，避免评测过程里人工干预。

---

## 8. CodeAct 沙箱：nsjail 最实用

### 8.1 为什么选 nsjail

这部分对应高层报告中的 Layer 3：安全隔离不是附属项，而是把 CodeAct 从宿主机权限域里切出去的必要手段。

nsjail 直接对准比赛需求：

- namespaces；
- cgroups；
- seccomp-bpf；
- rlimits；
- 支持 protobuf config；
- 低延迟；
- 适合短命 Python 代码片段执行。

Docker 不是不能用，但它更重，启动链更长，做 CodeAct 的单次执行不够利落。

WASM 很安全，但 Python 生态兼容成本高，尤其是你要跑真实库、FAISS 绑定、文件读写和调试。

### 8.2 建议命令

```bash
nsjail -Mo \
  --chroot /opt/statebus_jail \
  --user 99999 --group 99999 \
  --rlimit_as 2048 \
  --rlimit_cpu 10 \
  --rlimit_nofile 64 \
  --seccomp_policy /opt/statebus_jail/seccomp.policy \
  --bindmount_ro /opt/statebus_jail/lib:/lib \
  --bindmount_ro /opt/statebus_jail/usr:/usr \
  --tmpfsmount /tmp \
  -- /usr/bin/python3 -I /workspace/run_code.py
```

### 8.3 沙箱约束

- 只允许白名单 syscalls；
- 禁止任意网络；
- 工作目录只读或 tmpfs；
- 输出 artifacts 只允许落到指定目录；
- 每次运行都回收环境；
- 代码执行结果必须带 `exit_code/stdout/stderr/artifacts`。

---

## 9. 3 到 4 个硬核创新点

### 创新点 1：控制面 / 数据面分离的二进制状态总线

表述建议：

> StateBus 将多 Agent 协作从“文本消息传递”重构为“强类型控制面 + 零拷贝数据面”的状态总线架构。

为什么有价值：

- 控制消息固定小；
- 大 payload 不再重复编码；
- 状态交换从 O(payload text) 变成 O(1) reference + O(1) control frame。

### 创新点 2：基于 StateRef 的零拷贝非文本状态传递

表述建议：

> 通过共享内存 / mmap + `StateRef` 引用语义，实现 embedding、hidden state、evidence blob 的跨 Agent 零拷贝共享。

为什么有价值：

- 降低序列化开销；
- 降低重复拷贝；
- 让大状态传输从“消息内容”变成“可回收对象引用”。

### 创新点 3：版本化共享记忆与冲突消解

表述建议：

> 构建 SQLite + FAISS 的层次记忆存储，支持 memory write / search / update / delete、版本链、冲突消解和跨任务复用。

为什么有价值：

- 解决“任务做完就忘”；
- 防止记忆污染；
- 支撑第二个连续任务直接复用第一轮经验。

### 创新点 4：文本模式 vs 协议模式的双模式双盲评测

表述建议：

> 提供同任务、同模型、同工具链下的 text/protocol 对照评测，精确统计 token、byte、latency 和 memory hit rate。

为什么有价值：

- 不靠主观讲故事；
- 直接对标比赛评分维度；
- 能把“低开销”变成可复现实验结论。

---

## 10. 3 个最容易炸的点，以及怎么躲

### 死穴 1：共享内存生命周期失控

典型问题：

- segment 泄漏；
- consumer 读到 stale ref；
- 多进程并发释放；
- 长时间跑 10 轮后莫名 crash。

解决方案：

1. 统一由 StateBus daemon 管理 `lease_id`。
2. 每个 `StateRef` 带 `ttl_ms` 和 `checksum`。
3. 只允许单写者，读者只拿引用。
4. `unlink` 放到 lease 归零之后。

### 死穴 2：FAISS 和 SQLite 不一致

典型问题：

- SQLite 写成功，FAISS 没写进去；
- FAISS 写进去，SQLite 事务回滚；
- 重启后索引和元数据对不上。

解决方案：

1. 用 `pending -> active -> superseded` 状态机。
2. 先落 SQLite 事务，再异步写 FAISS。
3. 建一个 outbox / replay 队列，启动时补写。
4. 单写者维护 FAISS，避免并发写。

### 死穴 3：CodeAct 沙箱依赖崩

典型问题：

- 代码能跑，但包没装；
- 能装包，但 syscalls 被 seccomp 卡死；
- 过于严格导致执行器没法启动；
- 环境不稳定，无法复现。

解决方案：

1. 先做固定 rootfs + 预装 venv。
2. 只放行必要 syscall。
3. 先在无网络环境跑最小 Python 任务，再逐步开工具。
4. 所有执行都在 nsjail 里完成，宿主机只接收结果。

---

## 11. 技术栈清单

### 11.1 必备技能树

#### Python

- `multiprocessing.shared_memory`
- `mmap`
- `socket` / `AF_UNIX`
- `sqlite3`
- `protobuf`
- `msgpack`
- `numpy`
- `faiss`
- `pydantic`
- `pytest`
- `time.perf_counter_ns`
- `subprocess`

#### Linux

- `strace`
- `perf`
- `bpftrace`
- `ipcs`
- `lsns`
- `unshare`
- `nsenter`
- `ss`
- `lsof`
- `mount`
- `cgroups v2`
- `seccomp-bpf`

#### 构建和部署

- `gcc/g++`
- `cmake`
- `make`
- `git`
- `dnf`
- `python3 -m venv`

### 11.2 openEuler 上建议先装的包

```bash
dnf install -y \
  git gcc gcc-c++ make cmake \
  python3 python3-devel python3-pip \
  sqlite sqlite-devel \
  protobuf protobuf-devel protobuf-compiler \
  zlib zlib-devel openssl-devel
```

如果你要上 telemetry，再补：

```bash
dnf install -y strace perf bpftrace
```

如果 FAISS wheel 不好拿，就优先走源码编译或 conda 环境。

---

## 12. 两阶段实施路线

### 阶段 1：4 天跑通最小闭环

对应高层报告的 Layer 1：逻辑闭环层。

目标：先证明系统可跑，不追求极致性能。

#### Day 1

- 定义 4 个 Agent：`Planner / Retriever / Executor / Summarizer`
- 定义 2 个任务对照组
- 定义 text/protocol 两种模式
- 先用 JSON 协议 + Python dict state pool

#### Day 2

- 跑通文本模式
- 跑通协议模式
- 打通消息日志、任务日志、结果日志
- 做最小 telemetry

#### Day 3

- 加入 `STATE_REF` 语义，但先用 dict 模拟引用
- 加入 `MEMORY_COMMIT`
- 建立 SQLite 元数据表

#### Day 4

- 跑 10 轮连续任务
- 输出对比表：
  - 消息数
  - token/char
  - 时延
  - memory hit rate
- 形成第一版演示脚本

阶段 1 成功标准：

- 两种模式都能稳定跑完；
- 10 轮不崩；
- protocol 模式的文本开销明显低于 text 模式。

### 阶段 2：7 天替换为高性能组件

对应高层报告的 Layer 2，并补齐 Layer 3 的沙箱接入与隔离壳。

#### Day 5

- dict state pool -> `SharedMemory`
- `STATE_REF` 真正指向 shm 句柄

#### Day 6

- JSON/手写字典 -> Protobuf
- 控制面切到 UDS

#### Day 7

- SQLite metadata + FAISS retrieval 正式接入
- 实现 dedup / conflict resolution / version chain

#### Day 8

- nsjail CodeAct 沙箱接入
- Executor 只通过受控工具调用执行代码

#### Day 9

- telemetry 完整化
- 增加 `message_count / bytes / hits / reuse_gain`

#### Day 10

- crash recovery
- lease 回收
- outbox replay

#### Day 11

- 固定两组连续任务
- 跑多 seed 实验
- 出最终对比图表

阶段 2 成功标准：

- 协议模式在重复任务上显著降低 token/字符开销；
- 状态传递走真正的零拷贝路径；
- 记忆复用在第二组连续任务上有可见收益；
- 10 轮连续任务稳定。

Layer 3 的 seccomp、bind mount、FD 注入和动态库穿透可以作为阶段 2 的后半段收尾，也可以在答辩前单独做安全加固封板。

---

## 13. 如何迭代，才不会把系统做散

迭代顺序必须固定：

1. 先做 text baseline。
2. 再做 protocol control plane。
3. 再把大状态迁到 StateRef。
4. 再加共享记忆。
5. 最后加沙箱和更硬的 telemetry。

每一轮只改一个变量，不要同时改协议、存储、沙箱和评测。否则你永远不知道收益来自哪里。

建议每次迭代都产出三样东西：

- 一张对比表；
- 一份日志；
- 一个最小复现实验命令。

---

## 14. 推荐交付物清单

1. `statebus/` 源码
2. `proto/statebus.proto`
3. `docs/architecture.md`
4. `docs/deployment_openEuler.md`
5. `docs/evaluation.md`
6. `reports/statebus_architecture_evolution_feasibility_report_20260529.md`
7. `reports/statebus_dual_plane_deep_design_20260529.md`
8. `reports/ablation_text_vs_protocol.md`
9. `reports/memory_reuse_report.md`
10. `demo/`
11. `video/`

---

## 15. 参考链接

- [LangGraph](https://github.com/langchain-ai/langgraph/blob/main/README.md)
- [Letta](https://github.com/letta-ai/letta)
- [Letta MemFS](https://docs.letta.com/letta-code/memfs)
- [Letta Memory Blocks](https://docs.letta.com/guides/core-concepts/memory/memory-blocks)
- [Letta Archival Memory](https://docs.letta.com/guides/core-concepts/memory/archival-memory/)
- [Mem0](https://github.com/mem0ai/mem0)
- [Mem0 Memory Types](https://docs.mem0.ai/core-concepts/memory-types)
- [Mem0 Add Memory](https://docs.mem0.ai/core-concepts/memory-operations/add)
- [Mem0 Memory Evaluation](https://docs.mem0.ai/core-concepts/memory-evaluation)
- [OpenAI Swarm](https://github.com/openai/swarm)
- [FAISS](https://github.com/facebookresearch/faiss)
- [Haystack](https://github.com/deepset-ai/haystack)
- [LlamaIndex](https://github.com/run-llama/llama_index)
- [Qdrant](https://github.com/qdrant/qdrant)
- [Qdrant Python client](https://github.com/qdrant/qdrant-client)
- [MessagePack](https://github.com/msgpack/msgpack)
- [Protobuf encoding](https://protobuf.dev/programming-guides/encoding/)
- [Python shared_memory](https://docs.python.org/3/library/multiprocessing.shared_memory.html)
- [Python mmap](https://docs.python.org/3/library/mmap.html)
- [Python socket](https://docs.python.org/3/library/socket.html)
- [NsJail](https://github.com/google/nsjail)
- [openEuler 24.03 LTS SP3 quick start](https://docs.openeuler.org/en/docs/24.03_LTS_SP3/server/quickstart/quickstart/quick_start.html)

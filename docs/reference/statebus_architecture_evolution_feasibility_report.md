# StateBus 系统架构设计、技术演进与可行性分析报告


项目名称：StateBus，面向多智能体协作的解耦控制面与零拷贝数据面总线运行时

适配赛题：一种面向多智能体协作的低开销通信、状态传递与共享记忆机制

基础材料：

- `zuoye/jingsai/statebus_architecture_and_implementation.md`
- `zuoye/jingsai/statebus_dual_plane_deep_design.md`

定位说明：

StateBus 的目标不是再做一个 Agent Workflow 框架，而是在通用 Linux/openEuler 运行环境中，为多 Agent 协作提供“结构化控制面 + Host 内存侧状态数据面 + 可复用共享记忆”的系统级运行时机制。当前本地设计环境不等同于 openEuler，但最终设计目标、内核原语、部署形态和评测指标均对齐 openEuler 24.03-LTS-SP3。本文不讨论 CANN/NPU 或任何特定 AI 加速硬件，零拷贝范围严格限定在 Host 内存侧的多进程/多沙箱状态共享。

---

## 1. 核心痛点与系统级质疑

### 1.1 控制面 Token 隐性膨胀

传统多 Agent 框架常把“路由、交接、状态说明、工具结果解释”都塞回自然语言上下文。即使外层消息格式从文本换成 JSON，只要 Router 或每个节点仍然调用 LLM 读取完整历史，控制面本身就会成为 token 消耗主因。

系统级质疑：

- 路由节点如果依赖 LLM 判断下一跳，复杂 DAG 的每个边切换都会重复消耗上下文。
- 工具描述、历史轨迹、失败原因反复进入 prompt，通信优化只停留在序列化格式层面。
- `protocol_bytes` 降低不代表真实成本降低，必须同时统计 `text_tokens` 和 LLM usage。

StateBus 破局：

- Planner 只在入口把自然语言目标编译成符号化 DAG。
- 后续路由由运行时根据 `ActionType`、`CapabilityItem`、依赖拓扑和 FSM 状态确定，不重复调用 LLM。
- 控制面只流转 `PlanStep`、`StepResult`、`StateRef`、`MemoryQuery` 等强契约帧。

### 1.2 能力发现与自适应协议映射难点

多 Agent 系统的真实困难不是“能不能发消息”，而是异构 Agent 的输入输出契约不一致。不同模型、不同 Prompt、不同工具调用协议会造成字段名、类型、状态含义和错误语义不一致。

系统级质疑：

- 一个 Agent 输出 `topK`，另一个要求 `top_k`；一个返回 markdown JSON，另一个返回 OpenAI-style tool call。
- 如果 Schema 校验发生在业务逻辑深处，错误会滞后暴露并污染共享记忆。
- 能力表只写“retriever/executor”没有意义，必须声明输入输出 Schema、可消费状态类型、并发限制和事务能力。

StateBus 破局：

- Agent 接入必须先执行 `Hello -> CapabilityItem -> SchemaSpec` 契约握手。
- `ProtocolMapper` 负责把 Agent 私有格式转换成 StateBus 标准控制帧。
- `SchemaInterceptor` 在调度前拦截错误帧，避免错误进入 DAG 和 Memory Store。

### 1.3 异步并行编排与状态死锁隐患

复杂任务不是线性链，而是带依赖的 DAG。Retriever、Executor、Summarizer 可能并行运行，也可能共享上游状态。如果只用 `asyncio.gather()` 或线程池粗暴并发，容易引发状态读写冲突和等待环。

系统级质疑：

- 并行分支同时读写同一中间状态时，谁拥有写权，谁负责发布？
- 两个 Agent 互相等待对方释放 `StateRef` 时，如何发现死锁？
- 沙箱中工具执行超时后，依赖它的节点如何取消或重规划？

StateBus 破局：

- 编译期对 DAG 做依赖完整性检查和 cycle 检测。
- 运行期用 Kahn 拓扑排序驱动 ready queue，只调度依赖已提交的 step。
- 数据面采用单写多读：写者在 `PREPARE` 阶段写 provisional state，`COMMIT` 后发布只读 `StateRef`。
- 应用层 refcount 不跨 step 持锁，lease 只用于生命周期管理，不参与控制流等待。

### 1.4 动态重规划与事务级回滚代价

Agent 执行失败不是异常日志问题，而是状态污染问题。工具或沙箱失败时，可能已经写入共享内存、SQLite 记忆候选或 FAISS 写队列。

系统级质疑：

- Executor 写了一半 SHM 后超时，下游是否可能读到脏 `StateRef`？
- SQLite 写成功但 FAISS add 失败，重启后两边如何对齐？
- 重规划时是否把失败状态带入下一轮，导致错误被固化成“经验”？

StateBus 破局：

- 引入 `PREPARE -> COMMIT -> ROLLBACK` 的事务状态机。
- 共享状态在提交前只存在于 provisional slot，未提交不向下游发布。
- SQLite 使用 WAL 和 outbox，Memory Proxy Writer 负责 FAISS 单写者提交。
- 回滚释放 provisional `StateRef`、撤销 SQLite pending/outbox、触发结构化 `REPLAN`。

---

## 2. 行业顶尖开源仓库的系统级参考点

### 2.1 LangGraph：CompiledStateGraph 与 Checkpoint

参考点：

- `StateGraph` 是 builder，`compile()` 后生成可执行图。
- 编译阶段完成节点、边、分支、channel、checkpoint 配置的组合。
- Checkpoint 提供长时执行中的状态保存、恢复和回放思路。

StateBus 借鉴：

- 采用 `PlanBuilder -> DAG Compile -> Runtime Execute` 三阶段，而不是边跑边口头协调。
- `CompiledStateGraph` 思想转化为可序列化 `Plan{steps, depends_on}`，便于跨进程、跨语言和持久化。
- Checkpoint 不只保存 Agent 文本状态，还要保存 `StateRef` lease、SQLite txn id、outbox offset 和 step FSM。

### 2.2 OpenAI Swarm：符号化 Handoff 最小交接语义

参考点：

- Swarm 的 `Agent` 是带函数和指令的执行单元。
- `Result` 可以返回 `agent` 和 `context_variables`，实现轻量 handoff。
- Handoff 的本质不是长文本解释，而是“下一执行者 + 上下文增量”。

StateBus 借鉴：

- 把 Agent 交接设计成符号动作：`next_agent/capability_id/context_delta/state_refs`。
- Handoff 进入 DAG/FSM，而不是进入自然语言对话流。
- 对外保留最小语义，对内加入事务、租约、telemetry 和失败恢复。

### 2.3 MetaGPT：发布-订阅 SOP 总线架构

参考点：

- Environment 负责消息发布，Role 订阅自己关心的消息。
- RoleContext 维护私有消息缓冲、memory、working memory 和 state。
- SOP 把复杂协作拆成角色、动作、产物和顺序。

StateBus 借鉴：

- 借鉴“环境承载角色，消息进入私有队列，角色只观察订阅事件”的结构。
- SOP 不放在 prompt 里，而是落成 `CapabilityItem + PlanStep.action + depends_on`。
- 发布订阅用于控制帧分发，数据 payload 仍由数据面 `StateRef` 引用。

### 2.4 Apache Arrow Plasma / Ray Core：不可变对象共享和 Seal

参考点：

- Plasma/Ray object store 把对象放入共享内存，用 ObjectRef 跨进程引用。
- 对象创建和发布分离，写完后 seal，之后只读共享。
- 同节点 NumPy 类对象可通过共享内存减少重复拷贝。

StateBus 借鉴：

- `StateRef` 是 Agent 运行时版本的 ObjectRef，包含 `kind/dtype/shape/checksum/lease/fd_slot`。
- `PREPARE -> COMMIT` 对应 create/seal/publish，提交后只读。
- 消费方需要修改状态时必须 copy-on-write，生成新的 `StateRef`。

### 2.5 Google NsJail：受控目录穿透与进程空间隔离

参考点：

- NsJail 组合 namespaces、cgroups、rlimit、seccomp-bpf、bind mount。
- 通过只读 bind mount 暴露宿主机必要目录，通过 tmpfs 隔离临时写入。
- `pass_fd` 或父进程 UDS 可以把受控 FD 注入沙箱进程。

StateBus 借鉴：

- CodeAct 执行进入无网络、低权限、受限资源的沙箱。
- 共享状态通过只读 bind mount 或 `SCM_RIGHTS` FD 注入穿透隔离边界。
- 沙箱不能直接写共享记忆，只能返回 `StepResult` 和受控 artifact。

---

## 3. 渐进式三层演进架构设计

StateBus 不应该第一天就把 Protobuf、SHM、FAISS、NsJail、FD passing 全部堆上去。正确路线是先证明协作逻辑，再替换性能底座，最后接入内核隔离。

### 3.1 Layer 1：逻辑闭环层，MVP 基础版

目标：

优先验证多角色 Agent 编排控制流、双模式评测和共享记忆复用逻辑。此层不追求零拷贝真实性，只证明系统语义成立。

组件选型：

- Python 进程内运行时。
- 纯 Python dict/list 模拟 StatePool。
- JSON-Schema 或 MessagePack 作为轻量强契约协议。
- SQLite 可先作为可选持久化，也可先用内存表模拟。
- Agent 角色至少包含 Planner、Retriever、Executor、Summarizer。

解决的问题：

- 证明 `text` 与 `protocol` 两种模式可在同一任务集切换。
- 证明 Planner 输出 DAG，Scheduler 根据拓扑依赖调度，而不是靠多轮 LLM 路由。
- 证明 `StateRef` 指针语义在逻辑上替代大文本 payload。
- 证明共享记忆能被后续任务命中并触发 DAG 剪枝。

架构图：

```text
Task
  -> Planner
  -> Python DAG Scheduler
  -> Agent Handlers
  -> InMemory StatePool
  -> InMemory/SQLite MemoryStore
  -> Telemetry JSON
```

验证标准：

- 至少 3 个 Agent 协同运行。
- 10 轮连续任务自动执行不崩。
- `--mode text` 和 `--mode protocol` 能在同一任务集上对照。
- 输出 `text_tokens/text_chars/message_count/task_ms/memory_hit_rate`。
- 关联任务中能看到 `reuse_gain`，即第二组任务少走部分规划或检索。

### 3.2 Layer 2：系统加速层，性能终态版

目标：

将控制面和数据面彻底剥离，实现 Host 内存侧零拷贝状态流转，并把记忆模块改成稳定的 SQLite WAL + FAISS 单写者架构。

组件选型：

- Protobuf 作为强类型 wire format。
- Unix Domain Socket 作为本机控制面通信。
- `multiprocessing.shared_memory`、POSIX SHM、`mmap` 或 memfd 作为 Host 数据面载体。
- SQLite WAL 保存记忆元数据、事务状态和 outbox。
- FAISS 常驻单写者进程维护向量索引。

解决的问题：

- 大状态不进入控制帧，控制面只传 `StateRef`。
- 非文本状态能跨进程直接读取，减少序列化/反序列化。
- SQLite 与 FAISS 写入路径有 outbox 和单写者，避免并发崩溃。
- 状态池通过 lease/refcount/checksum 管理生命周期。

架构图：

```text
Control Plane UDS
  ControlFrame(Protobuf)
  StateRef(logical pointer)
        |
        v
Data Plane StatePool
  SHM/mmap/memfd slot
  lease/refcount/checksum
        |
        v
Memory Plane
  SQLite WAL metadata
  FAISS Proxy Writer
```

验证标准：

- `protocol_bytes` 低于 text mode 长文本传输。
- `state_bytes` 能独立统计，证明 payload 从控制面剥离。
- `task_ms` 在状态密集任务中下降，或至少 I/O/序列化开销下降。
- 非文本状态传递次数、规模、消费方使用路径可观测。
- SQLite/FAISS 在连续 10 轮任务中无 pending 悬挂、无 ID 不一致。

### 3.3 Layer 3：内核隔离层，安全完美版

目标：

面向 openEuler 终态，打通全隔离 CodeAct 的安全数据通路。沙箱内代码无网络、低权限、资源受限，但仍可通过受控 FD 读取宿主机共享状态。

组件选型：

- Linux namespaces：user、mount、pid、net、uts、cgroup。
- cgroups v2：限制 CPU、内存、进程数、I/O。
- NsJail：封装 namespace、rlimit、seccomp-bpf、bind mount。
- UDS `SCM_RIGHTS`：跨沙箱边界传递共享内存 FD。
- Read-only bind mount：穿透 Python/Conda 运行所需路径和只读状态目录。

解决的问题：

- CodeAct 代码不直接运行在宿主机权限域。
- 沙箱无网络，不能越权访问宿主机文件。
- 共享状态以只读 FD 或只读挂载进入沙箱，不复制 payload。
- 动态库和 Python 运行时依赖通过最小只读挂载解决。

架构图：

```text
StateBus Runtime(host)
  -> create/seal StateRef
  -> UDS sendmsg(SCM_RIGHTS fd)
  -> NsJail Executor
       namespaces + cgroups + seccomp
       mmap(PROT_READ) fd
       run CodeAct
       return StepResult
```

验证标准：

- 沙箱内无网络访问能力。
- 沙箱内 Python CodeAct 能运行并读取受控共享状态。
- FD 注入后不出现 FD 泄漏，`RLIMIT_NOFILE` 下能稳定运行。
- 失败时能回滚 provisional state，不污染 SQLite 和 FAISS。

---

## 4. 控制面与数据面双平面交互边界

### 4.1 硬性隔离边界

控制面只做四件事：

- Agent 注册、能力发现、Schema 校验。
- Planner DAG 编译、拓扑调度、FSM 状态转移。
- 事务协调：`PREPARE/COMMIT/ROLLBACK`。
- Telemetry、错误传播、重规划和背压。

控制面禁止做的事：

- 禁止携带 embedding、hidden state、大段 evidence blob。
- 禁止把完整历史文本作为路由依据。
- 禁止直接读写 SHM payload。
- 禁止让普通 Agent 直接写 FAISS。

数据面只做四件事：

- 分配、复用、回收 Host 内存块。
- 管理 `StateRef`、lease、refcount、checksum。
- 提供只读映射或 FD 传递。
- 在 lease 过期或回滚时隔离和回收对象。

数据面禁止做的事：

- 不理解 `PLAN/RETRIEVE/EXECUTE` 业务语义。
- 不调用 LLM，不做路由决策。
- 不解析 Agent prompt，不修改记忆内容。

### 4.2 自适应能力握手协议流程

```text
Agent Process Start
  -> HELLO(agent_id, role, protocol_version, transports)
  -> CAPABILITY(items: action, input_schema, output_schema, accepted_state_kinds)
  -> Runtime validates schema and compatibility
  -> Runtime registers capability table
  -> Runtime sends ACK or ERROR
  -> Agent becomes schedulable
```

细化流程：

1. Agent 启动后通过 UDS/stdin/gRPC over UDS 发送 `Hello`。
2. `Hello` 中声明角色，例如 Planner、Retriever、Executor、Summarizer。
3. 每个 `CapabilityItem` 声明支持的动作、输入 Schema、输出 Schema、可消费的 `StateKind`、最大并发、是否支持 2PC、是否支持 FD passing。
4. Runtime 为该 Agent 加载 `ProtocolMapper`，把私有字段映射到标准字段。
5. Runtime 生成 capability table，调度时只依据 table 确定 owner Agent。
6. 若 Agent 输出不满足 Schema，Frame 在进入 DAG 前被拦截并返回结构化错误。

---

## 5. 核心场景端到端数据流向图

### 5.1 场景 A：复杂任务异步并行编排与跨沙箱 FD 投递

三层叠加流程：

```text
Layer 1 Logic
UserTask
  -> Planner compiles DAG
  -> Scheduler finds ready steps
  -> Retriever and Executor run concurrently
  -> StateRef is simulated by in-memory object id

Layer 2 System Data Plane
Retriever
  -> allocate StatePool slot
  -> write embedding/evidence into SHM/mmap
  -> seal and publish StateRef
  -> Scheduler forwards only StateRef

Layer 3 Sandbox
Executor(CodeAct)
  -> NsJail starts isolated Python
  -> Runtime sends fd through UDS SCM_RIGHTS
  -> sandbox mmap(PROT_READ) shared state
  -> returns StepResult
```

完整拓扑：

```text
Task Input
  -> Planner.PLAN
       output: PlanStep DAG
  -> Runtime.DAG_COMPILE
       validate no cycle, bind capabilities
  -> Runtime.DISPATCH
       ready: Retriever.RETRIEVE, Executor.PREPARE_ENV
  -> Retriever.RETRIEVE
       write DenseEvidence to preallocated StatePool
       publish StateRef(ref_evidence)
  -> Executor.EXECUTE
       receive StateRef(ref_evidence)
       receive fd via SCM_RIGHTS or readonly bind path
       run in NsJail
       publish StateRef(ref_artifact)
  -> Summarizer.SUMMARIZE
       consume ref_evidence + ref_artifact
       produce summary + memory candidate
  -> MemoryProxy.MEMORY_COMMIT
       SQLite pending
       FAISS outbox
       active memory
```

失败回滚流：

```text
Executor timeout/exception
  -> StepState FAILED
  -> Runtime ROLLBACK(txn_id)
  -> StatePool release provisional refs
  -> SQLite rollback pending memory/outbox
  -> Scheduler triggers REPLAN with structured error
```

### 5.2 场景 B：跨任务记忆复用与 Graph Pruning

三层叠加流程：

```text
NewTask
  -> Runtime intercepts MEMORY_QUERY before full planning
  -> MemoryProxy searches FAISS by embedding_id
  -> SQLite filters active rows and metadata
  -> high confidence hit
  -> GraphPruner removes repeated PLAN/RETRIEVE steps
  -> Scheduler executes pruned DAG
```

完整拓扑：

```text
Task#2 Input
  -> Runtime.MEMORY_QUERY(task_theme, tags, query_text)
  -> FAISS_SEARCH(query_embedding)
       returns embedding_ids: [101, 88, 72]
  -> SQLite_SELECT
       WHERE embedding_id IN (101, 88, 72)
       AND status='active'
       AND confidence >= threshold
  -> MemoryHit
       memory_id, reusable_steps, evidence_refs, strategy_summary
  -> GraphPruning
       remove repeated retrieval branch
       inject reused StateRef or strategy node
  -> Execute Pruned DAG
  -> Telemetry
       pruned_step_count
       reuse_gain.token
       reuse_gain.latency
```

剪枝原则：

- 只能剪掉被历史成功路径覆盖且输入条件相似的步骤。
- 剪枝结果必须保留验证节点，避免错误记忆直接支配输出。
- 若复用后的验证失败，记忆不增加 `reuse_count`，并写入 `reuse_rejected` 事件。

---

## 6. 双模式自动化评测与 Telemetry 矩阵

### 6.1 公平对照组织方式

同一任务集必须在两种模式下运行：

- `--mode text`：Agent 间用自然语言或长 JSON 搬运中间结果，作为传统基线。
- `--mode protocol`：Agent 间用结构化控制帧和 `StateRef` 传递状态引用。

公平性约束：

- 同一 LLM 和同一模型参数。
- 同一系统 prompt、工具列表和任务输入。
- 同一随机种子和相同最大轮次。
- 同一 Agent 角色拆分。
- 同一任务成功判定标准。
- 不允许 protocol 模式额外拿到 text 模式没有的外部信息。

建议实验组：

```text
TaskSet-A: 首次复杂任务，无历史记忆
TaskSet-B: 关联连续任务，允许复用 TaskSet-A 记忆
TaskSet-C: 故障注入任务，验证 rollback/replan
```

### 6.2 Telemetry 矩阵

应用层指标：

| 指标 | 含义 | 价值 |
|---|---|---|
| `message_count` | Agent 间消息数量 | 判断协议是否减少来回协调 |
| `text_tokens` | LLM 输入输出 token | 直接对应通信效率评分 |
| `text_chars` | 文本字符量 | 无 tokenizer 时的稳定替代指标 |
| `protocol_bytes` | Protobuf/MessagePack 控制帧字节 | 衡量控制面开销 |
| `state_ref_count` | StateRef 次数 | 衡量非文本状态传递频率 |
| `state_bytes` | 被引用状态总字节 | 证明 payload 已剥离出控制面 |
| `task_ms` | 端到端任务耗时 | 衡量实际性能收益 |
| `memory_hit_rate` | 记忆检索命中率 | 衡量共享记忆可用性 |
| `reuse_gain.token` | 复用带来的 token 下降比例 | 量化跨任务收益 |
| `reuse_gain.latency` | 复用带来的耗时下降比例 | 量化跨任务收益 |
| `rollback_count` | 回滚次数 | 评估容错路径是否被覆盖 |
| `pruned_step_count` | 被剪枝步骤数 | 证明 Graph Pruning 有效 |

系统层指标：

| 指标 | 采集方式 | 价值 |
|---|---|---|
| `sendmsg/recvmsg_count` | strace/eBPF/perf trace | 验证 UDS 通信开销 |
| `mmap/munmap_count` | strace/eBPF | 验证状态池复用程度 |
| `shm_open/memfd_count` | strace/eBPF | 观察对象创建频率 |
| `fd_inflight` | runtime 计数 + `/proc/<pid>/fd` | 防止 FD 泄漏 |
| `rss_peak` | `/proc/<pid>/status` | 衡量内存开销 |
| `page_faults` | perf 或 `/proc` | 观察 mmap/SHM 抖动 |
| `sqlite_pending_count` | SQL 查询 | 检查事务悬挂 |
| `faiss_outbox_lag` | outbox 队列长度 | 检查索引写入滞后 |

---

## 7. 缺陷堵漏、实现流程与必备技能树

### 7.1 SQLite 与 FAISS 的 ID 映射细节隐患解决

问题本质：

FAISS 的 `IndexFlatIP`、`IndexHNSWFlat` 搭配 `IndexIDMap/IndexIDMap2` 时，向量 ID 是 `idx_t`，通常以 64 位有符号整数表达。SQLite 的 `memory_id` 如果使用 TEXT UUID，不能直接作为 FAISS ID。若强行 hash UUID，存在碰撞和可追踪性差的问题。

推荐表结构：

```sql
CREATE TABLE memories (
  embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id TEXT NOT NULL UNIQUE,
  source_agent_id TEXT NOT NULL,
  task_theme TEXT NOT NULL,
  summary TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  confidence REAL NOT NULL,
  status TEXT NOT NULL,
  created_at_ns INTEGER NOT NULL,
  updated_at_ns INTEGER NOT NULL
);

CREATE TABLE memory_embeddings (
  embedding_id INTEGER PRIMARY KEY,
  memory_id TEXT NOT NULL UNIQUE,
  vector_dim INTEGER NOT NULL,
  encoder_id TEXT NOT NULL,
  state_ref_json TEXT,
  faiss_status TEXT NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memories(memory_id)
);

CREATE TABLE faiss_outbox (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  embedding_id INTEGER NOT NULL,
  op TEXT NOT NULL,
  vector_ref_json TEXT NOT NULL,
  status TEXT NOT NULL,
  retry_count INTEGER NOT NULL DEFAULT 0,
  created_at_ns INTEGER NOT NULL,
  updated_at_ns INTEGER NOT NULL
);
```

写入流程：

```text
1. MemoryProxy BEGIN IMMEDIATE
2. INSERT INTO memories(memory_id TEXT UUID, status='pending')
3. SQLite 生成 embedding_id INTEGER
4. INSERT INTO memory_embeddings(embedding_id, memory_id, faiss_status='pending')
5. INSERT INTO faiss_outbox(embedding_id, op='ADD', vector_ref_json, status='pending')
6. COMMIT SQLite
7. Proxy Writer 顺序读取 faiss_outbox pending
8. 从 vector_ref_json 读取向量
9. FAISS index.add_with_ids(vector, np.array([embedding_id], dtype=int64))
10. SQLite UPDATE memory_embeddings SET faiss_status='active'
11. SQLite UPDATE memories SET status='active'
12. SQLite UPDATE faiss_outbox SET status='done'
```

检索流程：

```text
1. Query embedding -> FAISS search
2. FAISS returns int64 embedding_ids and scores
3. SQLite SELECT * FROM memories
   JOIN memory_embeddings USING(embedding_id)
   WHERE embedding_id IN (...)
   AND status='active'
   AND encoder_id=?
4. Runtime 按 FAISS score 顺序重排 SQLite rows
5. 返回 memory_id、summary、evidence_refs、score
```

一致性策略：

- SQLite 是真源，FAISS 是可重建索引。
- `memory_id` 面向业务和审计，`embedding_id` 面向 FAISS。
- Proxy Writer 是唯一 FAISS 写者。
- 重启时扫描 `faiss_status!='active'` 或 outbox pending，重放写入。
- FAISS 索引快照用临时文件写入，完成后 `rename(2)` 原子替换。

### 7.2 NsJail 内 Python 动态链接库路径穿透隐患解决

问题本质：

Conda/venv Python 常依赖跨目录动态库，例如 `libpython3.x.so`、`libstdc++.so`、`libopenblas.so`、NumPy/FAISS 扩展模块等。进入 NsJail 后，mount namespace 和 rootfs 隔离会导致动态链接器找不到库，引发 `ImportError` 或 `error while loading shared libraries`。

设计原则：

- 不把整个宿主机根目录暴露给沙箱。
- 只读绑定挂载 Python 解释器、Conda 环境、动态库目录、必要系统库。
- 工作目录和 `/tmp` 可写，但依赖目录只读。
- `LD_LIBRARY_PATH` 指向只读挂载后的路径。
- StateBus 共享状态目录只读挂载，或用 FD 注入替代路径穿透。

通用路径占位：

```text
/xxx/path/conda/envs/statebus
/xxx/path/statebus_jail_root
/xxx/path/statebus_workspace
/xxx/path/statebus_shm
/xxx/path/system/lib64
```

NsJail 挂载流：

```text
Host
  /xxx/path/conda/envs/statebus
  /xxx/path/statebus_workspace
  /xxx/path/statebus_shm
  /xxx/path/system/lib64
      |
      v read-only bind mount
NsJail
  /opt/conda/envs/statebus
  /workspace
  /statebus_shm
  /lib64
```

配置规范片段：

```protobuf
mount {
  src: "/xxx/path/statebus_jail_root"
  dst: "/"
  is_bind: true
  rw: false
}

mount {
  src: "/xxx/path/conda/envs/statebus"
  dst: "/opt/conda/envs/statebus"
  is_bind: true
  rw: false
}

mount {
  src: "/xxx/path/system/lib64"
  dst: "/lib64"
  is_bind: true
  rw: false
  mandatory: false
}

mount {
  src: "/xxx/path/statebus_workspace"
  dst: "/workspace"
  is_bind: true
  rw: true
}

mount {
  src: "/xxx/path/statebus_shm"
  dst: "/statebus_shm"
  is_bind: true
  rw: false
  mandatory: false
}

mount {
  dst: "/tmp"
  fstype: "tmpfs"
  rw: true
  options: "size=64m,mode=1777"
}

envar: "PATH=/opt/conda/envs/statebus/bin:/usr/bin:/bin"
envar: "LD_LIBRARY_PATH=/opt/conda/envs/statebus/lib:/lib64:/usr/lib64"
cwd: "/workspace"

exec_bin {
  path: "/opt/conda/envs/statebus/bin/python3"
  arg: "-I"
  arg: "/workspace/run_code.py"
}
```

调试流程：

```text
1. 在宿主机用 ldd /xxx/path/conda/envs/statebus/bin/python3 找库依赖
2. 对 NumPy/FAISS .so 继续 ldd，列出 libopenblas/libstdc++ 等依赖
3. 把必要目录只读 bind mount 到 jail 内稳定路径
4. 设置 LD_LIBRARY_PATH
5. 如果 seccomp kill，先临时放宽 seccomp，strace 记录缺失 syscall
6. 收敛 seccomp 白名单
```

安全边界：

- Python 环境目录只读，避免沙箱内篡改依赖。
- 工作目录只暴露任务临时文件。
- 共享状态目录只读，写结果必须走 Runtime 注册为新 `StateRef`。
- 网络 namespace 独立且不配置网络。

### 7.3 技能补齐

Python 高级并发与协议：

- `asyncio` 任务调度、取消、超时、背压。
- `asyncio.Queue`、Semaphore、拓扑调度。
- `socket.AF_UNIX`、`SOCK_SEQPACKET`、`sendmsg/recvmsg`。
- Protobuf、MessagePack、JSON-Schema/Pydantic。
- `multiprocessing.shared_memory`、`mmap`、NumPy buffer protocol。
- SQLite WAL、事务、outbox pattern。

Linux 内核原语：

- `mmap(2)`、`munmap(2)`、`madvise(2)`、`ftruncate(2)`。
- `shm_open(3)`、`memfd_create(2)`、`fcntl(2)` seals。
- Unix Domain Socket、`SCM_RIGHTS`、`SO_PEERCRED`。
- `epoll(7)`、`eventfd(2)`、`timerfd(2)`、`futex(2)` 基本语义。
- `/proc/<pid>/fd`、`/proc/<pid>/maps`、`smaps` 调试。
- `strace`、`perf`、`bpftrace`、`lsof`、`ss`。

安全沙箱与隔离：

- Linux namespaces：user、mount、pid、ipc、net、uts。
- cgroups v2：CPU、memory、pids、I/O 限制。
- seccomp-bpf/Kafel syscall 白名单。
- NsJail config.proto、bind mount、tmpfs、rlimit。
- 动态链接调试：`ldd`、`LD_LIBRARY_PATH`、`readelf -d`。
- 沙箱故障定位：`strace -f`、exit status、seccomp audit。

工程与评测：

- 双模式 benchmark 设计。
- Telemetry schema 和离线对比报告生成。
- FAISS `IndexIDMap2`、`IndexFlatIP`、`IndexHNSWFlat` 基础。
- 向量归一化、encoder_id 管理、检索 rerank。
- 故障注入：超时、沙箱异常、SQLite pending、FD 泄漏、StateRef lease 过期。

---

## 结论

StateBus 的合理演进路线是先做逻辑闭环，再替换系统数据面，最后接入沙箱隔离。Layer 1 证明多 Agent 编排、双模式评测和记忆复用成立；Layer 2 证明 Host 内存侧零拷贝和 SQLite/FAISS 一致性成立；Layer 3 证明 openEuler 终态下隔离 CodeAct 仍能通过受控 FD 读取共享状态。这样报告可以用于开题、中期和答辩，而深度设计稿继续承担工程规格和落地细节补充。

---

## 参考资料

- openEuler 24.03-LTS-SP3 下载与版本信息：https://www.openeuler.org/en/download/archive/detail/?version=openEuler+24.03+LTS+SP3
- LangGraph StateGraph：https://raw.githubusercontent.com/langchain-ai/langgraph/main/libs/langgraph/langgraph/graph/state.py
- OpenAI Swarm types：https://raw.githubusercontent.com/openai/swarm/main/swarm/types.py
- OpenAI Swarm core：https://raw.githubusercontent.com/openai/swarm/main/swarm/core.py
- MetaGPT Environment：https://raw.githubusercontent.com/FoundationAgents/MetaGPT/main/metagpt/environment/base_env.py
- MetaGPT Role：https://raw.githubusercontent.com/FoundationAgents/MetaGPT/main/metagpt/roles/role.py
- Apache Arrow Plasma：https://arrow.apache.org/blog/2017/08/08/plasma-in-memory-object-store/
- Ray Object Serialization：https://docs.ray.io/en/latest/ray-core/objects/serialization.html
- NsJail README：https://raw.githubusercontent.com/google/nsjail/master/README.md
- NsJail config.proto：https://raw.githubusercontent.com/google/nsjail/master/config.proto
- SQLite WAL：https://www.sqlite.org/wal.html
- FAISS FAQ：https://github.com/facebookresearch/faiss/wiki/FAQ

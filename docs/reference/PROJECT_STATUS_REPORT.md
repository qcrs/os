# LangGraph 项目完成情况评估报告

> 评估日期：2026-06-06
> 评估对象：`/data/mingwei/langgraph` 本地源码
> 评估标准：6 项核心需求（多 Agent 协同、结构化通信、非文本状态传递、共享记忆、关联任务验证、性能数据）

---

## 一、项目概述

LangGraph 是 LangChain 团队开发的**底层编排框架**，用于构建、管理和部署有状态的、长运行的 AI Agent。其核心灵感来自 Google Pregel 图计算模型，采用 Bulk Synchronous Parallel（BSP）执行引擎。

**定位**：Low-level orchestration framework for building stateful agents.

**仓库结构**：

```
libs/
├── langgraph          # 核心框架（图定义、Channel、Pregel 执行引擎）
├── checkpoint         # 检查点与 Store 基础接口
├── checkpoint-postgres # Postgres 后端（含 pgvector 向量检索）
├── checkpoint-sqlite  # SQLite 后端（含 sqlite_vec 向量检索）
├── prebuilt           # 预构建 Agent（create_react_agent、ToolNode 等）
├── cli                # 命令行工具 + 示例图
├── sdk-py             # Python SDK（LangGraph Server API）
├── sdk-js             # JS/TS SDK
└── checkpoint-conformance # 后端一致性测试
```

---

## 二、逐项评估

### 需求 1：系统支持不少于 3 个 Agent 协同运行，覆盖规划、检索、执行、总结等角色

**完成度：✅ 完全满足**

#### 已有能力

- **无硬性并发上限**：Pregel 引擎对所有就绪任务并行执行，通过 `max_concurrency` 可选限流
  - 源码：`libs/langgraph/langgraph/_internal/_config.py:162`
  - 源码：`libs/langgraph/langgraph/pregel/_executor.py:135`（asyncio.Semaphore 实现）

- **三种并行机制**：
  1. **静态 fan-out**：`add_edge(["a", "b"], "c")` 创建 waiting-edge，等待所有前驱完成
  2. **动态 fan-out**：`Send(node, arg)` 在条件边中返回任意数量的并行任务
  3. **Command 路由**：`Command(goto=[Send(...), Send(...)])` 组合控制流

- **子图组合**：编译后的图可直接作为节点嵌入父图，支持层级式 Agent 架构
  - 源码：`libs/langgraph/langgraph/graph/state.py:1187`
  - `Command.PARENT` 允许子图节点跳转到父图（`types.py:808`）

- **分布式 Agent**：`RemoteGraph` 支持将远程 LangGraph Server 部署作为节点调用
  - 源码：`libs/langgraph/langgraph/pregel/remote.py:118`

#### 角色模式覆盖

| 角色 | 实现方式 | 代码位置 |
|------|---------|---------|
| 规划 | `Command(goto=...)` 动态路由，planner 节点分派步骤 | `tests/test_pregel.py:5185` |
| 检索 | 多 retriever 并行 fan-out | `tests/test_pregel.py:1941` |
| 执行 | STORM 示例中的 Interviewer/Expert 子图 | `libs/cli/examples/graphs/storm.py` |
| 总结 | `generate_sections` 汇总节点 | `tests/test_pregel.py:4090` |

---

### 需求 2：设计结构化通信协议替代自然语言交互

**完成度：✅ 完全满足**

这是 LangGraph 的**核心设计理念**——节点间通信完全通过结构化的 Channel 和状态更新完成，不涉及自然语言。

#### 通信协议层次

```
┌─────────────────────────────────────────────────┐
│  应用层：State = TypedDict / dataclass / BaseModel │
├─────────────────────────────────────────────────┤
│  Channel 层：9 种强类型 Channel                      │
│  LastValue / BinaryOperatorAggregate / Topic /  │
│  DeltaChannel / NamedBarrierValue / ...         │
├─────────────────────────────────────────────────┤
│  控制流层：Send / Command / Overwrite / Interrupt    │
├─────────────────────────────────────────────────┤
│  写入层：ChannelWriteEntry(channel, value, mapper)   │
├─────────────────────────────────────────────────┤
│  执行层：apply_writes() → Channel.update() → 触发    │
└─────────────────────────────────────────────────┘
```

#### 核心类型

| 类型 | 作用 | 源码位置 |
|------|------|---------|
| `Send(node, arg)` | 动态派发任务到指定节点，携带任意结构化数据 | `types.py:664` |
| `Command(goto, update, resume)` | 组合状态更新 + 导航 + 中断恢复 | `types.py:759` |
| `Overwrite(value)` | 绕过 reducer 直接覆写 Channel | `types.py:937` |
| `Interrupt(value, id)` | 人类介入中断，携带任意值 | `types.py:533` |
| `ChannelWriteEntry` | 底层写入描述符，映射输出到 Channel | `pregel/_write.py` |

#### Channel 系统（9 种）

| Channel | 用途 |
|---------|------|
| `LastValue` | 保留最新值，每步仅允许一个写入者（默认） |
| `LastValueAfterFinish` | 延迟可用，消费后清除 |
| `AnyValue` | 保留最新值，假设并发写入者产生相同值 |
| `EphemeralValue` | 仅存活一步，用于 START 和分支触发 |
| `UntrackedValue` | 类似 LastValue 但不持久化 |
| `BinaryOperatorAggregate` | 二元操作符聚合（如 `operator.add` 追加消息） |
| `DeltaChannel` | 增量快照，减少高吞吐场景的序列化开销 |
| `Topic` | PubSub 模式，收集多值为序列 |
| `NamedBarrierValue` | 同步屏障，等待所有命名值到达后才可用 |

所有 Channel 源码位于：`libs/langgraph/langgraph/channels/`

---

### 需求 3：实现非文本中间状态传递机制（embedding/语义向量/隐藏状态）

**完成度：⚠️ 框架层面支持，但非内置专项特性**

#### 已有能力

- **Channel 类型无关**：`BaseChannel.typ` 为 `Any`，`Send.arg` 为 `Any`，可传递任意 Python 对象
  - 源码：`channels/base.py:24`

- **序列化支持任意类型**：`ormsgpack` + pickle fallback
  - 源码：`libs/checkpoint/langgraph/checkpoint/serde/jsonplus.py`

- **Store 语义向量检索**：
  - `BaseStore.search(query=...)` 支持自然语言语义搜索
  - `IndexConfig` 配置 embedding 维度、provider、提取路径
  - `ensure_embeddings()` 支持 LangChain Embeddings、自定义 callable、provider 字符串
  - 后端：pgvector（cosine/l2/inner_product，HNSW/IVFFlat/flat 索引）、sqlite_vec
  - 源码：`libs/checkpoint/langgraph/store/base/embed.py`

#### 未实现 / 需应用层构建

| 缺失项 | 说明 |
|--------|------|
| 内置 Embedding Channel | 没有专门的 Channel 类型用于自动 embedding 化传递 |
| 隐藏状态传播机制 | Channel 传递显式 Python 对象，不自动传播神经网络 hidden state |
| 向量相似度路由 | 没有基于向量相似度的自动路由/分发机制 |
| 端到端 embedding 流水线 | 需要用户自行定义状态 schema 中的向量字段并串联 |

#### 结论

框架在技术上**不阻碍**非文本数据传递，但需要用户在应用层自行构建 embedding 流水线。如果需要演示"非文本中间状态传递"，需要补充一个示例实现。

---

### 需求 4：实现共享记忆模块，支持记忆的存储、检索和复用

**完成度：✅ 完全满足，且是核心特性**

#### 双层记忆架构

```
┌──────────────────────────────────────────────────────┐
│  长期记忆：BaseStore                                    │
│  · 跨线程、跨会话共享                                     │
│  · 层级化 namespace: tuple[str, ...]                    │
│  · 支持 put / get / search / delete / list_namespaces   │
│  · 语义向量检索（cosine / l2 / inner_product）            │
│  · TTL 过期机制                                         │
│  · 后端：InMemoryStore / PostgresStore / SqliteStore    │
├──────────────────────────────────────────────────────┤
│  短期记忆：BaseCheckpointSaver                          │
│  · 线程级作用域（thread_id）                              │
│  · 版本化快照：Checkpoint(v, id, ts, channel_values...)  │
│  · 支持故障恢复、状态回溯、human-in-the-loop               │
│  · 后端：InMemorySaver / PostgresSaver / SqliteSaver    │
└──────────────────────────────────────────────────────┘
```

#### 共享机制

1. **同一 Store 对象共享**：`graph.compile(store=store)` 传入的 store 被所有节点共享
   - 源码：`pregel/_loop.py:293`，传递给每个 task

2. **Runtime 注入**：Store 通过 `Runtime` 对象注入到每个节点
   - 源码：`pregel/_algo.py:688-693`

3. **函数式 API**：`@task` 和 `@entrypoint(store=store)` 也支持 Store 传播
   - 源码：`libs/langgraph/langgraph/func/__init__.py:468, 604`

4. **子图继承**：子图自动继承父图的 Store
   - 源码：`pregel/_loop.py:565, 616, 797, 825`

#### 记忆检索能力

| 能力 | 实现 |
|------|------|
| 键值精确查询 | `store.get(namespace, key)` |
| 命名空间前缀搜索 | `store.search(namespace_prefix=...)` |
| 结构化过滤 | `$gt` / `$gte` / `$lt` / `$lte` / `$ne` 操作符 |
| 语义向量搜索 | `store.search(query="自然语言查询")` → cosine 相似度排序 |
| 命名空间浏览 | `store.list_namespaces(prefix, suffix, max_depth)` |
| 批量操作 | `store.batch([GetOp, PutOp, SearchOp, ...])` |

#### 测试验证

- `test_store_injected`（`test_pregel.py:4264`）：验证多线程共享同一 Store，一个线程可覆盖另一线程写入的数据

---

### 需求 5：至少设计 2 组关联性连续任务进行验证

**完成度：✅ 完全满足（4 组以上）**

#### 任务组 1：RAG 检索-问答流水线

```
rewrite_query（规划/查询改写）
    ├── retriever_one（检索分支 A）
    └── retriever_two（检索分支 B）
        └── qa（总结/问答）
```

- 代码位置：`tests/test_pregel.py:1941`（`test_in_one_fan_out_state_graph_waiting_edge`）
- 特征：静态 fan-out + waiting-edge fan-in

#### 任务组 2：研究访谈流水线

```
generate_analysts（规划：生成分析师人设）
    ├── conduct_interview_1（访谈子图 A）
    ├── conduct_interview_2（访谈子图 B）
    └── conduct_interview_N（访谈子图 N，via Send）
        └── generate_sections（总结：综合报告）
```

- 代码位置：`tests/test_pregel.py:4090`
- 特征：动态 Send fan-out + 子图并行

#### 任务组 3：客户服务流水线

```
one（触发事件处理）
    → two（自动回复 + 问题分类）
    → three（规则获取） ∥ four（分类 + 响应起草）
    → five（用户/CRM 丰富）
    → six（响应组装）
    → 循环或 END
```

- 代码位置：`bench/wide_state.py`
- 特征：6 节点图，含并行分支和条件循环

#### 任务组 4：STORM 研究流水线

```
outline（规划：生成大纲）
    → [interview × N（并行访谈：Interviewer ↔ Expert）]
    → write_sections（撰写各章节）
    → refine（精炼终稿）
```

- 代码位置：`libs/cli/examples/graphs/storm.py`
- 特征：完整多角色 Agent 流水线（Researcher、Editor、Interviewer、Expert、Writer）

#### 任务组 5：Planner 动态规划

```
planner（动态规划节点）
    → step1 → [step2 ∥ step3] → step4 → END
```

- 代码位置：`tests/test_pregel.py:5185`（`test_command_dynamic_routing`）
- 特征：`Command(goto=...)` 动态路由，plan 数组驱动

---

### 需求 6：提供通信开销、任务时延、记忆复用等方面的性能对比数据

**完成度：⚠️ 基础设施完备，但部分维度数据缺失**

#### 已有的 Benchmark 基础设施

**Benchmark 套件**：`libs/langgraph/bench/`

基于 `pyperf` 的 30+ 场景，涵盖：

| 类别 | 场景 | 有/无 checkpoint |
|------|------|-----------------|
| Fan-out 子图 | 10x, 100x | ✅ 有 / ✅ 有 |
| React Agent | 10x, 100x | ✅ 有 / ✅ 有 |
| Wide State | 25x300, 15x600, 9x1200 | ✅ 有 / ✅ 有 |
| Wide Dict | 25x300, 15x600, 9x1200 | ✅ 有 / ✅ 有 |
| Sequential | 10, 1000 | ✅ 有 |
| Pydantic State | 25x300, 15x600, 9x1200 | ✅ 有 / ✅ 有 |
| 序列化 | allowlist small/large | ✅ 有 |

**已测量的性能指标**：

| 指标 | 测量方式 | 代码位置 |
|------|---------|---------|
| 首事件延迟 | `perf_counter()` 测量到首个流式事件的时间 | `bench/__main__.py:36-54, 478-497` |
| 全程运行延迟 | `pyperf` 精确计时 | `bench/__main__.py` 全局 |
| 图编译时间 | 独立 benchmark | `bench/__main__.py:500-516` |
| 流式分块延迟 | `perf_counter()` 时间戳 + 断言窗口 | `test_pregel_async.py:5175` |
| 并行节点执行时延 | fast(0.1s) + slow(2s) 并行 < 3.0s | `test_pregel_async.py:6538` |
| DeltaChannel 写入延迟 | `write_per_invoke_ms` | `test_delta_channel_benchmark.py` |
| DeltaChannel 读取延迟 | `read_avg_ms`（5 次 get_state 平均） | `test_delta_channel_benchmark.py` |
| Checkpoint 存储大小 | `storage_bytes` | `test_delta_channel_benchmark.py` |
| 峰值内存 | `tracemalloc` | `test_delta_channel_benchmark.py` |

**CI 自动化对比**：

- `.github/workflows/baseline.yml`：push 到 main 时生成 baseline JSON
- `.github/workflows/bench.yml`：PR 时运行 benchmark，`pyperf compare_to` 生成对比表，结果发布为 PR annotation

**Makefile 目标**：

```bash
make benchmark       # 完整 benchmark（--rigorous）
make benchmark-fast  # 快速 benchmark（--fast）
make profile         # py-spy 火焰图
```

#### 缺失的性能数据

| 缺失维度 | 说明 | 建议补充方式 |
|----------|------|-------------|
| **Channel 通信开销** | Channel 是进程内内存读写，开销极低但未量化 | 测量单次 `channel.update()` / `channel.get()` 的 ns 级延迟 |
| **Agent 间通信延迟** | 未测量节点通过 Channel 传递状态的端到端延迟 | 在 fan-out 场景中测量 `apply_writes()` 的耗时 |
| **记忆复用率** | 未测量 Store 的缓存命中率 / 语义检索召回率 | 设计重复查询场景，计算 hit@k |
| **记忆检索延迟** | 未对比 InMemory vs Postgres vs SQLite 的检索速度 | 对同一数据集在三种后端上运行 search benchmark |
| **跨 Agent 共享开销** | 未测量多 Agent 并发读写同一 Store 的竞争开销 | 设计 N 个 Agent 并发 put/get 场景 |
| **Checkpoint 序列化开销** | DeltaChannel 有测量，但普通 Channel 的序列化开销未量化 | 对比有/无 checkpoint 的运行时间差 |

---

## 三、总结

### 完成度总览

| # | 需求 | 完成度 | 核心程度 |
|---|------|--------|---------|
| 1 | ≥3 Agent 协同（规划/检索/执行/总结） | ✅ 完全满足 | 核心 |
| 2 | 结构化通信协议 | ✅ 完全满足 | **最核心** |
| 3 | 非文本中间状态传递 | ⚠️ 框架支持，需应用层实现 | 非核心 |
| 4 | 共享记忆模块 | ✅ 完全满足 | 核心 |
| 5 | ≥2 组关联连续任务验证 | ✅ 完全满足 | 验证支撑 |
| 6 | 性能对比数据 | ⚠️ 基础设施完备，部分维度缺失 | 补充项 |

### 已有优势

1. **架构成熟**：Pregel 执行引擎 + Channel 状态传递 + 双层记忆，形成了完整的有状态 Agent 编排体系
2. **通信协议完备**：9 种 Channel + Send/Command 控制流，结构化程度高
3. **共享记忆深度实现**：Store 支持跨会话共享、语义向量检索、TTL 过期，后端覆盖 InMemory/Postgres/SQLite
4. **多 Agent 验证充分**：4+ 组完整流水线，覆盖 RAG、研究访谈、客户服务、STORM 等场景
5. **性能基础设施完善**：pyperf benchmark + CI 自动对比 + 火焰图 profiling

### 待补充项

1. **非文本状态传递示例**：需补充一个显式传递 embedding/向量的 Channel 实现或示例
2. **通信开销专项 benchmark**：Channel 读写 ns 级延迟、apply_writes() 端到端延迟
3. **记忆复用率度量**：Store 缓存命中率、语义检索 recall@k
4. **跨后端性能对比**：InMemory vs Postgres vs SQLite 的检索延迟对比

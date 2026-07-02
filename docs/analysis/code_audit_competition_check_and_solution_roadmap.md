# StateBus代码全面梳理、赛题核对与优化方案

日期：`2026-06-10`

适用范围：基于 `main` 分支当前代码（`feat/realism-protocol-hardening` 合并后），对全仓库代码做模块级审核，逐项核对赛题要求，识别代码层问题，给出可执行的优化路线图，使项目在赛题评审中更具亮点。

---

## 第一部分：代码全面梳理

### 1. 仓库规模与结构

```
项目总计: 22,487行 Python (94个.py文件)
测试:     92个pytest用例 (4个测试文件, 4,117行)
模块数:   11个一级Python模块
文档:     56份progress审计日志 + 规划/约束文档
评测:     105个历史runs目录
```

### 2. 模块级审核

---

#### 2.1 runtime/ (4,815行, 11个文件)

| 文件 | 行数 | 职责 | 质量评估 |
|------|------|------|---------|
| `orchestrator.py` | 1,563 | 核心编排器：task执行循环、replay gate、memory search缓存、state注册、结果收集 | ★★★★☆ 逻辑密集但干净。两处code smell：`_find_step`和`_step_for_emit`重复实现 |
| `executor_runtime.py` | 1,574 | ToolRegistry(7个工具)、FEATURE_BUNDLE构建、tool candidate ranking、5种transfer strategy处理 | ★★★★☆ 功能完整。4处工具函数与orchestrator/agents重复 |
| `contracts.py` | 591 | SchemaInterceptor校验、StateContractRegistry(11个state contracts)、CapabilityTable、6个StepInputContract | ★★★★☆ Schema设计完整。`validate_state_ref`的contract选择逻辑存在sorted排序假设 |
| `llm.py` | 683 | LLMConfig(env+YAML+runtime)、OpenAICompatibleLLMClient、DeterministicLLMClient、prompt构建 | ★★★★★ 干净。双模式prompt(自然语言+紧凑协议)分离清晰 |
| `reuse_contract.py` | 91 | 4级contract(reuse_disabled/assist_allowed/validated_replay/exact_replay)→3个gate boolean | ★★★★★ 干净。向后兼容legacy booleans |
| `task_profile.py` | 109 | RuntimeTaskProfile dataclass、lane/strategy normalization | ★★★★☆ 干净 |
| `remote_executor.py` | 85 | UDS server + serve() loop + main()入口 | ★★★★☆ 干净 |
| `uds_transport.py` | 45 | AF_UNIX消息传输（4字节长度头） | ★★★★☆ 干净 |
| `tool_worker.py` | 29 | 子进程工具CLI入口 | ★★★★☆ 干净 |
| `smoke.py` | 44 | main()入口，运行repeat=1 benchmark | ★★★★☆ 干净，有真实stdout |

**关键问题**：
1. **重复代码**：`_format_transfer_tool_candidates`在`executor_runtime.py:1536`和`agents/sample_agents.py:1238`完全重复
2. **重复的浮点/整数解析**：`_coerce_float`(orchestrator)、`_parse_float_or_default`(executor_runtime)、`_coerce_optional_float`(llm)功能重叠
3. **`_is_route_replay_eligible`**(executor_runtime:1563)与`_route_is_replay_eligible`(orchestrator:1491)逻辑相同

---

#### 2.2 agents/ (1,320行, 2个文件)

| 文件 | 行数 | 职责 | 质量评估 |
|------|------|------|---------|
| `sample_agents.py` | 1,299 | PlannerAgent、RetrieverAgent、ExecutorAgent、SummarizerAgent完整实现 | ★★★☆ 功能完整但过于臃肿。单个文件承载4个Agent的全部逻辑 |
| `base_agent.py` | 20 | BaseAgent ABC | ★★★★★ 干净 |

**关键问题**：
1. **RetrieverAgent.execute_step中`build_feature_bundle`被调用两次**（L220和L270），第一次为memory assist验证，第二次为实际输出。当前无随机性所以不触发问题，但架构脆弱
2. **PlannerAgent.execute_step直接raise NotImplementedError**——通过build_plan()绕过的设计不够优雅
3. **`_format_transfer_tool_candidates`与executor_runtime重复**
4. **`_parse_transfer_tool_candidates`**(L1263)做脆弱的`rsplit("#", 2)`解析

**架构建议**：将sample_agents.py拆分为4个独立文件，每个Agent一个文件，共享的utility抽取到`agents/utils.py`。

---

#### 2.3 protocol/ (865行 + proto + pb2)

| 文件 | 行数 | 职责 | 质量评估 |
|------|------|------|---------|
| `messages.py` | 844 | 14种消息dataclass、protobuf序列化/反序列化、JSON fallback、`text_frame()`自然语言渲染 | ★★★★☆ 功能完整。protobuf→JSON fallback是潜在调试噩梦 |
| `statebus.proto` | 152 | WireEnvelope oneof定义12种消息类型 | ★★★★☆ 干净 |
| `statebus_pb2.py` | 20 | Checked-in protobuf编译产物stub | — 实际pb2由运行时生成 |

**关键问题**：
1. **Protobuf→JSON silent fallback**（`protocol_bytes`L185-194）：如果protobuf序列化失败，静默退为JSON。结果是wire format non-deterministic
2. **`parse_protocol_bytes`**（L197+）：try protobuf, except all → try JSON。损坏的protobuf消息会被静默地尝试JSON解析，可能产生难以debug的错误
3. **pb2 stub只有20行**——实际pb2由`grpc_tools.protoc`生成，当前checked-in版本是占位符

---

#### 2.4 statepool/ (294行, 1个文件)

| 文件 | 行数 | 职责 | 质量评估 |
|------|------|------|---------|
| `store.py` | 293 | FileBackedStatePool(mmap读写+JSON metadata)、SharedMemoryStatePool(Python shared_memory)、StatePool facade | ★★★★☆ 双后端实现干净 |

**关键问题**：
1. **SharedMemoryStatePool的跨进程生命周期管理**——远端executor不创建SHM，统一回退mmap。这是刻意收敛但限制了shared_memory路径的实用范围
2. **缺少POSIX_SHM/MEMFD后端**——实现计划中列为后续扩展，当前未做

---

#### 2.5 memory/ (821行, 1个文件)

| 文件 | 行数 | 职责 | 质量评估 |
|------|------|------|---------|
| `store.py` | 820 | MemoryStore(SQLite schema+memories_fts)、SentenceTransformerEmbeddingProvider、DeterministicEmbeddingProvider、_NumpyVectorIndex(FAISS fallback)、semantic/keyword search、replay candidate retrieval | ★★★★☆ 功能完整。向量索引扩展性有问题 |

**关键问题**：
1. **`_NumpyVectorIndex.search`是O(N·D)的全量扫描**——对每个查询扫描所有向量。存储记忆量增长时性能线性退化
2. **FTS5 fallback静默禁用**（L239）——FTS建表失败时不打印warning直接跳过
3. **只支持单一encoder_id**——`_embed_commit_text`和`_embed_query_text`都要求匹配active encoder_id
4. **INSERT OR REPLACE的upsert语义**——memory_id冲突时覆盖旧数据，丢失历史。建议改为append-only

---

#### 2.6 eval/ (3,404行, 2个文件)

| 文件 | 行数 | 职责 | 质量评估 |
|------|------|------|---------|
| `runner.py` | 3,313 | run_benchmark()入口、_run_mode_once()执行循环、6层aggregation、benchmark report生成(CSV+MD)、stability分析 | ★★★☆ 功能极度完整但过于臃肿。3,313行单文件 |
| `metrics.py` | 90 | TaskMetrics dataclass(50+字段) | ★★★★★ 干净 |

**关键问题**：
1. **单文件3,313行严重过长**——建议拆分为`runner.py`(主循环) + `aggregation.py`(聚合) + `reporting.py`(报表生成)
2. **aggregate视图因mode不对称产生误导**——report知道应该用lane-level视图，但aggregate仍放第一位置
3. **fresh_retrieval口径被埋在后面**——应该提升为报告的第二section（紧接aggregate）

---

#### 2.7 tasks/ (607行 + 29个YAML)

| 文件 | 行数 | 职责 | 质量评估 |
|------|------|------|---------|
| `sample_tasks.py` | 378 | SampleTask dataclass、load_task_set_bundle()、50个TASK_SET_ALIASES、build_plan() | ★★★★☆ 干净。硬编码的3-step Plan |
| `local_corpus.py` | 229 | CorpusDoc dataclass、retrieve_corpus_docs()(semantic+lexical+tag+theme+group+preference scoring)、candidate-first rerank | ★★★★☆ 检索逻辑合理。preference_bonus=0.20偏弱 |

**关键问题**：
1. **`build_plan()`硬编码3-step**——所有task都是retrieve→execute→summarize，无任务结构多样性
2. **`sample_benchmark.yaml`当前被截断为121行**——HEAD版本是475行(formal_controlled_pack, 29 tasks)，需要恢复
3. **Preference bonus设计良好的弱先验**——0.20的系数不会压倒clear evidence，但影响close ties

---

#### 2.8 tests/ (4,117行, 4个文件)

| 文件 | 行数 | 测试数 | 覆盖范围 |
|------|------|--------|---------|
| `test_smoke.py` | 3,148 | ~35 | 集成测试：smoke run, reuse correctness, contract enforcement, feature bundle, embedding state, UDS, tool candidate, benchmark rerun, repeat-10 stability |
| `test_llm_runtime.py` | 422 | ~8 | LLM config, plan parser tolerance, runtime profile contract, text vs protocol prompts |
| `test_memory_store.py` | 252 | 4 | Schema creation + filters, memory purpose layers, keyword fallback, embed device |
| `test_protocol_messages.py` | 295 | 6 | Memory commit wire, memory query filter, step_result protobuf, remote request/response, schema interceptor validation |

**关键问题**：
1. **test_smoke.py单文件3,148行**——严重超长，应按测试维度拆分
2. **缺少独立的orchestrator replay gate单元测试**
3. **缺少executor_runtime tool selection路径的独立测试**
4. **缺少contracts.py SchemaInterceptor的独立单元测试**（只在大集成测试中间接覆盖）

---

### 3. 代码质量问题汇总

#### 3.1 重复代码（4处确认）

| # | 函数 | 文件1 | 文件2 | 行数 |
|---|------|-------|-------|------|
| 1 | tool candidate格式化 | executor_runtime.py:1536 | agents/sample_agents.py:1238 | ~40行 |
| 2 | route replay eligible检查 | orchestrator.py:1491 | executor_runtime.py:1563 | ~20行 |
| 3 | 浮点数解析 | orchestrator.py:1504 | executor_runtime.py:1549 | ~8行 |
| 4 | `_find_step`/`_step_for_emit` | orchestrator.py:866 | orchestrator.py:873 | ~10行 |

#### 3.2 代码健壮性问题

| # | 问题 | 位置 | 风险 |
|---|------|------|------|
| 1 | protobuf→JSON silent fallback | protocol/messages.py:185-194 | wire format non-deterministic |
| 2 | `_parse_transfer_tool_candidates`的rsplit解析 | agents/sample_agents.py:1263 | tool name含`#`时崩 |
| 3 | _NumpyVectorIndex全量O(N)扫描 | memory/store.py:138-157 | 记忆量增长时性能退化 |
| 4 | FTS5建表失败静默跳过 | memory/store.py:239 | 无warning |
| 5 | INSERT OR REPLACE丢失历史 | memory/store.py:244-395 | 无法追溯记忆演变 |
| 6 | text_brief解析依赖line.startswith | executor_runtime.py:800+ | 格式漂移导致静默故障 |

#### 3.3 架构问题

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 1 | sample_agents.py单文件1,299行 | agents/ | 难以维护和测试 |
| 2 | runner.py单文件3,313行 | eval/ | 难以拆解和复用 |
| 3 | build_feature_bundle双重调用 | agents/sample_agents.py:220,270 | 非确定性时出bug |
| 4 | build_plan硬编码3-step | tasks/sample_tasks.py:267-305 | 任务结构无多样性 |
| 5 | sample_benchmark.yaml被截断 | tasks/ | 丢失formal controlled pack |

---

## 第二部分：赛题要求逐项核对

基于 `docs/reference/题目.md` 逐项检查：

### 2.1 必须实现项（共10项）

| # | 赛题要求 | 状态 | 证据 | 边界说明 |
|---|---------|------|------|---------|
| 1 | ≥3 Agent，覆盖规划/检索/执行/总结等3类 | ✅ 已实现 | 4个Agent: Planner(LLM型), Retriever(工具型), Executor(混合型), Summarizer(LLM型) | 仍是单仓库内pipeline，不是分布式 |
| 2 | 结构化通信协议：动作/参数/结果/能力描述 | ✅ 已实现 | 14种Protobuf消息类型 + JSON fallback | — |
| 3 | 握手/能力发现/协议映射 | ✅ 已实现 | Hello/Capability握手 + SchemaInterceptor校验 | — |
| 4 | 不得仅靠自然语言长文本透传 | ✅ 已实现 | 控制面只传结构化帧，重状态在StateRef | — |
| 5 | 同时支持text/protocol双模式并在相同任务下对比 | ⚠️ 部分实现 | text/protocol双模式存在，但state_transfer lane缺少text对照 | **需修复** |
| 6 | 非文本中间状态传递：embedding/语义向量/隐藏状态 | ⚠️ 部分实现 | EMBEDDING + FEATURE_BUNDLE + StateRef | 无hidden state/KV cache；FEATURE_BUNDLE是flat dict |
| 7 | 共享记忆：ID/来源Agent/时间/主题/摘要 | ✅ 已实现 | SQLite schema: memory_id, source_agent_id, created_at, task_theme, summary | — |
| 8 | 按关键词/标签/语义相似度检索+复用 | ✅ 已实现 | FAISS semantic + FTS5 keyword + tag filtering | replay成立，assist不work |
| 9 | ≥2组关联连续任务 | ✅ 已实现 | 29 tasks, 6 task groups, 3 incident chains | — |
| 10 | 统计消息数/token/非文本状态次数与规模/耗时/记忆命中率/整体提升 | ✅ 已实现 | 50+ metric字段 + 6层aggregation | aggregate因task不对称有误导 |

### 2.2 鼓励项（共2项）

| # | 赛题要求 | 状态 | 说明 |
|---|---------|------|------|
| 11 | 鼓励CodeAct(LLM生成Python在沙箱运行) | 历史口径，非当前 v2 claim | 当前 v2 只能 claim controlled CodeAct-style execution；受限 LLM-code demo 仍是 future work |
| 12 | 鼓励IPC/共享内存/Socket/向量库/WASM/容器/eBPF | ⚠️ 部分 | AF_UNIX+mmap+shared_memory+SQLite+FAISS已落地；WASM/容器/eBPF未实现 |

### 2.3 交付要求

| # | 要求 | 状态 |
|---|------|------|
| 13 | openEuler 24.03-LTS-SP3编译/运行/测试 | ❌ 未闭环 |
| 14 | 完整源码/设计文档/部署文档/实验报告/演示视频 | ⚠️ 源码+设计文档已存在；部署/实验报告/视频未完成 |

### 2.4 评分维度对照（含细化扣分项）

| 维度 | 分值 | 当前得分 | 扣分项 | 优化后目标 |
|------|------|----------|--------|-----------|
| 通信效率 | 25 | ~18 | 1) state_transfer lane缺text对照 (-3) 2) aggregate假倒挂削弱证据可信度 (-2) 3) communication lane只有2 task证据弱 (-1) 4) 无异构handoff通信对比 (-1) | ~23 (修复1/2/3后) |
| 状态传递创新 | 20 | ~14 | 1) FEATURE_BUNDLE是flat dict不够新颖 (-3) 2) 缺hidden-state/KV cache (-2) 3) 缺通道语义 (生成/传递/接收方式不够清晰) (-1) | ~18 (Typed Channel升级后) |
| 记忆复用效果 | 20 | ~14 | 1) assist_only不work (-3) 2) replay gain是受控contract不是自然泛化 (-2) 3) 记忆检索只用semantic (-1) | ~18 (双层记忆+多信号后) |
| 系统完整性 | 20 | ~16 | 1) 缺CodeAct (-2) 2) 缺沙箱隔离 (-1) 3) 缺协议不变量检查 (-1) | ~19 (CodeAct+InvariantChecker后) |
| 实验验证 | 15 | ~10 | 1) benchmark task不对称/偏斜 (-2) 2) 所有task走hint_consensus (-1) 3) Artifact expectation全部disabled (-1) 4) 缺少route多样性task (-1) | ~13 (benchmark重构后) |
| **合计** | **100** | **~72** | — | **~91** |

**扣分项详细说明**：

- 通信效率扣7分详解：
  - state_transfer lane缺少text模式对照：违反赛题"双模式在相同任务下对比"的硬性要求。直接影响experiment validity → -3
  - aggregate假倒挂：protocol control_bytes > text在aggregate层出现（实际是task数不对称导致），评委可能直接质疑 → -2  
  - communication lane只有2个task且只有1个domain：证据强度不足 → -1
  - 缺乏不同handoff策略下的通信对比：当前所有task都用state_ref → -1

- 状态传递创新扣6分详解：
  - flat dict不够新颖：赛题明确要求"embedding、语义向量、隐藏状态特征或其他中间表示"，FEATURE_BUNDLE虽然是"特征"但结构过于简单 → -3
  - 缺hidden-state/KV cache：这是真正的LLM内部表示传递，当前完全没有 → -2
  - 缺通道语义：生成/传递/接收/使用方式表述不够清晰 → -1

- 记忆复用效果扣6分详解：
  - assist不work：assist_only vs memory_off 差距仅1.3-5.3%，不显著。系统报告自己也标注assist是diagnostic → -3
  - 受控contract：replay gain成立但依赖task_theme/route/query各种前置条件，不是真正的"跨任务复用" → -2
  - 检索精度不足：只有semantic similarity，缺少keyword/entity/recency多信号融合 → -1

- 系统完整性的扣分比较轻微，因为4Agent+双模式+协议+StateRef+记忆+评测的闭环已经成立。主要是加分项（CodeAct/沙箱/不变量检查）缺失。

- 实验验证扣5分详解：
  - benchmark task不对称和偏斜（62%是内部回归）→ -2
  - 所有task走hint_consensus → 基准线太高，测不到route系统的边界能力 → -1
  - artifact expectation全部disabled → 失去了一层自动验证 → -1
  - 缺乏route多样性 → -1

---

## 第三部分：问题清单（优先级排序）

### P0 — 致命/严重影响claim的问题

| # | 问题 | 来源 | 修复成本 |
|---|------|------|---------|
| P0-1 | state_transfer lane缺少text模式对照——违反赛题"双模式在相同任务下对比"要求 | 代码+benchmark | 中：为transfer_lane补6个text task |
| P0-2 | aggregate视图因mode不对称产生protocol > text的假倒挂 | benchmark | 低：调整报告顺序，增加免责声明 |
| P0-3 | sample_benchmark.yaml被截断为121行——丢失formal_controlled_pack | 工作区 | 低：`git checkout`恢复 |

### P1 — 严重影响评分的问题

| # | 问题 | 来源 | 修复成本 |
|---|------|------|---------|
| P1-1 | Communication lane只有2个task、1个domain——主张强度弱 | benchmark | 中：扩到3 domain × 2 task |
| P1-2 | assist_only从未赢过memory_off但仍占memory task配额 | benchmark+代码 | 中：重构memory lane聚焦replay_enabled vs memory_off |
| P1-3 | Memory检索只用semantic，缺少多信号融合和recency reranking | 代码 | 中：在MemoryStore增加BM25/entity/temporal信号 |
| P1-4 | FEATURE_BUNDLE是flat dict——缺少channel语义和增量传输 | 代码 | 高：引入Typed Channel模型 |
| P1-5 | 62%的task是internal_regression，对赛题主张无贡献 | benchmark | 中：调整lane配额 |
| P1-6 | CodeAct未实现——评分鼓励项缺失 | 代码 | 高：实现CodeAct+轻量沙箱 |

### P2 — 明显改进但非阻塞

| # | 问题 | 来源 | 修复成本 |
|---|------|------|---------|
| P2-1 | 所有task走hint_consensus路由，缺route多样性 | benchmark | 低：加入lexical_override task |
| P2-2 | build_plan硬编码3-step，所有task同构 | 代码 | 低：支持2/4-step |
| P2-3 | sample_agents.py单文件1,299行 | 代码 | 低：拆分为4个文件 |
| P2-4 | runner.py单文件3,313行 | 代码 | 中：拆分为3个文件 |
| P2-5 | 4处重复代码 | 代码 | 低：抽取共享utility |
| P2-6 | _NumpyVectorIndex全量扫描O(N) | 代码 | 低：加内存缓存或分批 |

### P3 — 后续增强

| # | 问题 | 来源 | 修复成本 |
|---|------|------|---------|
| P3-1 | 无hidden-state/KV cache传递 | 赛题 | 高 |
| P3-2 | 无WASM/eBPF/容器沙箱 | 赛题 | 高 |
| P3-3 | openEuler交付未闭环 | 赛题 | 中（需VM） |
| P3-4 | embedding provider只有sentence-transformers | 代码 | 低 |
| P3-5 | 协议不变量自动检查缺失 | 代码 | 低 |

---

## 第四部分：解决方案——让赛题更有亮点

### 4.1 总路线

```
Phase A (1-2天): 修复P0致命问题 + 恢复benchmark
Phase B (3-5天): 增强核心主张 + CodeAct实现
Phase C (2-3天): 系统亮点深化 + benchmark再跑
Phase D (2-3天): 文档/报告/视频交付
```

### 4.2 Phase A：止血（修复致命问题）

#### A1：修复sample_benchmark.yaml

```bash
git checkout HEAD -- tasks/sample_benchmark.yaml
```

恢复475行formal_controlled_pack。

#### A2：让state_transfer lane支持text vs protocol双模式对比

当前状态：转移lane的6个task全部 `allowed_modes: [protocol]`。

修改策略（方案A，推荐）：
- 将6个transfer task的`allowed_modes`改为`[text, protocol]`
- 同时设置`transfer_strategy`为对比模式：
  - text模式下transfer task使用`text_brief`策略
  - protocol模式下使用`state_ref`策略
- 这样同一个task在两种模式下使用不同的handoff方式，实现公平对比

修改策略（方案B）：
- 保持6个protocol-only task作为state_transfer carrier对比
- 新增6个对称的text-mode task，用于text vs protocol的state_transfer对比
- 总task数会从29增到35

**推荐方案A**：不增加task数，利用`transfer_strategy`字段的mode-dependent语义。

#### A3：调整报告口径

在benchmark report中：
1. 将fresh_retrieval口径提升到aggregate之后第一section
2. 在aggregate前增加显式免责："aggregate因mode任务数不对称有偏差，请用lane-level和reuse_axis视图"
3. 将"protocol control_bytes > text"的假倒挂显式标注为"结构因素，见lane-level数据"

### 4.3 Phase B：增强核心主张

#### B1：通信效率增强——增量协议帧（25分档）

**目标**：在同task_group的连续task间，控制面字节额外下降15-25%。

**实现**：
1. 在`protocol/messages.py`中新增`DeltaPlanStep`消息类型：
   ```python
   @dataclass
   class DeltaPlanStep:
       step_id: str
       delta_fields: dict[str, object]  # 只包含变更的字段
       base_step_id: str  # 引用的参考step_id
       delta_version: int
   ```
2. 在`runtime/orchestrator.py`的`_emit_steps()`中：
   - 检测是否同task_group内连续step
   - 如果是，只传delta（变更字段）
   - 否则传完整PlanStep
3. 在metrics中增加`delta_control_bytes`和`delta_savings`字段

**预期收益**：
- 同chain内control_bytes节省15-25%
- 机制新颖性加分（DeltaChannel概念来自LangGraph）

#### B2：状态传递创新——FEATURE_BUNDLE升级为Typed Channel（20分档）

**目标**：从flat dict升级为有语义的Typed Channel模型。

**实现**：
1. 在`protocol/messages.py`中定义`ChannelKind`枚举：
   ```python
   class ChannelKind(Enum):
       LAST_VALUE = "last_value"       # 只保留最新值
       TOPIC_ACCUMULATE = "topic_acc"  # 累积多步值
       TOPIC_REPLACE = "topic_repl"    # 每步覆盖
       EPHEMERAL = "ephemeral"         # 不持久化
   ```
2. 在`StateContractRegistry`中为每个state contract增加`channel_kind`字段
3. 在`runtime/orchestrator.py`中，step间的state传递时：
   - `LAST_VALUE`字段：只传最终值，跳过中间版本
   - `TOPIC_ACCUMULATE`字段：保留历史累积值
   - `EPHEMERAL`字段：不写入StateRef持久化
4. 在`benchmark_report.md`中增加"Channel Distribution" section

**预期收益**：
- 状态传递机制从"发一个dict"升级为"有语义的状态通道模型"
- 评分时更容易解释"中间表示的生成/传递/接收/使用方式"
- 可直接引用LangGraph的Channel模型作为理论支撑

#### B3：记忆复用增强——双层记忆+多信号检索（20分档）

**目标**：提升记忆检索精度，让assist_only也能work。

**实现**：
1. **双层记忆**：
   - 在`MemoryStore`中增加`memory_tier`字段（`working` | `long_term`）
   - 同run内产生的记忆标记为`working`，权重×1.5
   - 跨run的历史记忆标记为`long_term`，权重×1.0
2. **多信号检索融合**：
   - 在`MemoryStore.search()`中：
     - 当前：纯semantic similarity
     - 增加：BM25 term overlap score（×0.25权重）
     - 增加：entity/tag overlap boosting（×0.20权重）
     - 增加：recency decay（`exp(-λ × age_seconds)`，λ=0.0001）
   - 融合公式：`combined = semantic + 0.25*bm25 + 0.20*tag_overlap + recency_decay`
3. **追加式记忆**：
   - 将`INSERT OR REPLACE`改为纯`INSERT`
   - 记忆冲突时用`memory_id + version`区分版本

**预期收益**：
- 检索精度提升，可能让assist_only在run内work
- 多信号检索融合是mem0的核心创新——有业界参考

#### B4：CodeAct实现——受控代码执行（鼓励项，历史规划）

**当前 v2 读法**：这段是早期 roadmap，不是当前 evidence claim。当前已验证口径只能写成 controlled CodeAct-style execution：runtime-generated bounded Python action script 在 root+bwrap Docker profile 下执行。LLM 生成受限 Python function 仍属于 future work / optional demo，不能写成当前已完成能力。

**原目标**：实现受限 LLM-code demo，在隔离环境中执行小型 Python function。

**实现**：
1. 在`runtime/`下新增`codeact_runner.py`：
   - 接收Planner的CodeAct request
   - 调用Summarizer/Planner的LLM生成受限小函数
   - 做 AST / import policy 检查后，在 sandbox profile 中执行
   - 捕获stdout/stderr + 超时控制 + 环境变量清理
2. 在ToolRegistry中注册`codeact_execute`工具
3. 当现有7个playbook工具无法处理时，fallback到CodeAct
4. 在`benchmark_report.md`中增加CodeAct相关metrics

**预期收益**：
- 覆盖赛题鼓励项
- 轻量实现即可——不需要nsjail，subprocess+timeout足够展示概念
- 与当前ToolRegistry互补

### 4.4 Phase C：系统亮点深化

#### C5：Benchmark重构——lane配额优化

**目标**：赛题主张task占比从38%提升到60%以上。

**实现**：
1. Communication lane：扩到3 domain × 2 task = 6 tasks
2. Memory lane：保持3 tasks但聚焦replay_enabled vs memory_off
3. State transfer lane：6 tasks支持text vs protocol
4. Internal regression：从18 tasks减到6 tasks（保留一个chain做回归）
5. 加入2-3个route多样性task（lexical_override）
6. 总task数：6+3+6+6+3 = 24 tasks，其中18个(75%)支撑赛题主张

#### C6：协议不变量自动检查

**实现**：
1. 在`runtime/contracts.py`中增加`InvariantChecker`：
   - 静态不变量（从Schema定义自动生成）
   - 动态不变量（从Plan和StepResult自动推导）
2. 在eval runner中增加invariant_violations统计
3. 在benchmark report中增加"Protocol Compliance" section

**预期收益**：
- 自动验证协议合规性
- 比赛题要求更进一层——不只是"有协议"，而是"协议被自动检查"
- 借用AgentRx的设计思路

#### C7：Trajectory IR + 可复现Replay

**实现**：
1. 定义AgentTrajectory schema（JSON）
2. 在orchestrator的每个step执行后记录trajectory
3. 在eval runner中增加trajectory_comparison功能
4. 在benchmark report中增加"Trajectory Reproducibility" section

**预期收益**：
- Debug和replay能力增强
- 借用AgentRx的设计思路
- 增强benchmark可信度

### 4.5 Phase D：交付准备

#### D8：文档补齐

- 系统设计文档（更新现有docs）
- 部署文档（update deploy/）
- 实验报告（基于Phase C的最终benchmark run）
- 可选：演示视频脚本

#### D9：openEuler VM验证（如条件允许）

- 在openEuler 24.03-LTS-SP3 VM上安装依赖
- 运行benchmark repeat-10验证
- 记录环境差异和适配过程

---

### 4.6 任务间依赖分析

```
Phase A (止血)
  A1: git checkout sample_benchmark.yaml  ← 无依赖，最先做
  A2: state_transfer text对照
      ├── 依赖 A1 (需要完整的29-task pack)
      └── 影响 Phase C5 (benchmark重构以此为基线)
  A3: 调整报告口径
      └── 依赖 A2 (task对称化后有新的aggregate数据)

Phase B (核心主张增强)
  B1: DeltaPlanStep增量帧 ──┐
  B2: Typed Channel升级     ├── 互相独立，可并行
  B3: 双层记忆+多信号       │
  B4: CodeAct实现          ──┘
      所有B项 ──→ 都需要 Phase A完成后的稳定baseline跑验证

Phase C (系统亮点深化)
  C5: Benchmark重构
      ├── 依赖 A2+B1+B2+B3 (新feature需要在重构后的benchmark上验证)
      └── 被依赖 C6+C7 (新invariant/trajectory需在新benchmark上跑)
  C6: InvariantChecker ── 仅依赖 Phase A baseline
  C7: Trajectory IR    ── 仅依赖 Phase A baseline

Phase D (交付)
  D8: 文档补齐 ── 依赖 Phase B+C 完成后的最终数据
  D9: openEuler  ── 独立，可与 Phase B/C 并行
```

**关键路径**：A1 → A2 → B1/B2/B3/B4 → C5 → D8（约8-10天）


### 4.7 风险评估与回滚计划

| Phase | Feature | 最大风险 | 概率 | 影响 | 缓解措施 | 回滚方案 |
|-------|---------|---------|------|------|---------|---------|
| A2 | state_transfer text对照 | text模式下transfer task的行为不确定（text_brief解析可能失败） | 中 | 高(整个lane数据无效) | 先用deterministic模式preflight验证 | 回退到旧YAML（protocol-only） |
| B1 | DeltaPlanStep | delta检测逻辑有bug导致接收方拿到不完整PlanStep | 低 | 高(整个task失败) | 增加`sanity_check`：delta merge后的完整PlanStep必须通过SchemaInterceptor校验 | 关闭delta特性标志位，回退到完整传输 |
| B2 | Typed Channel | schema v1→v2兼容性导致旧consumer读不懂新bundle | 中 | 中(state传递失败) | v2 bundle保持v1所有字段，新增字段用optional | 降级flag：consumer请求v1格式 |
| B3 | 双层记忆+多信号 | recency权重过大导致semantic signal被压制→检索精度反而下降 | 低 | 中(assist变得更差) | 用历史benchmark数据做grid search找最优权重 | 权重参数通过环境变量配置，可hot-fix |
| B4 | CodeAct | future-work 受限 LLM-code demo 可能产生有 bug 或违反 policy 的代码 | 中 | 高(执行失败) | AST/import policy + sandbox profile + stdout/stderr audit | 回退到 controlled runtime-generated action script |
| C5 | Benchmark重构 | 新task定义有误→整个benchmark结果不可比 | 中 | 高(历史数据无法对照) | 保留一份旧pack的copy；新pack跑deterministic preflight验证 | 回退到旧pack重新跑 |

### 4.8 各Phase的成功标准与验证方法

| Phase | Feature | 验证方法 | 成功标准 | 验证命令 |
|-------|---------|---------|---------|---------|
| A1 | sample_benchmark恢复 | `wc -l tasks/sample_benchmark.yaml` | 行数=475 | — |
| A2 | state_transfer文字对照 | `python -m eval.runner --repeat 1 --llm-mode deterministic --out /tmp/a2_verify` | text和protocol的`state_transfer` lane都有数据；text模式不再跳过transfer_lane | — |
| A3 | 报告口径调整 | 检查生成的`benchmark_report.md` | fresh_retrieval section在aggregate之后第一位置；aggregate前有免责声明 | — |
| B1 | DeltaPlanStep | `python -m pytest tests/test_protocol_messages.py -k delta` | DeltaPlanStep的protobuf round-trip成功；delta merge后的完整PlanStep通过SchemaInterceptor校验 | 新增test |
| B2 | Typed Channel | `python -m pytest tests/test_smoke.py -k feature_bundle` | v2 FEATURE_BUNDLE的metadata中包含`_channel_schema`字段 | 修改现有test |
| B3 | 双层记忆 | 跑`communication+memory` pack | assist_only task_ms相比memory_off下降≥5% | `python -m eval.runner --task-set memory --repeat 3 --llm-mode api --out /tmp/b3_verify` |
| B4 | CodeAct | 单独跑一个CodeAct-enabled task | controlled runtime-generated action script 成功执行并返回结果；若做 future-work LLM-code demo，必须另有 AST policy 和 sandbox evidence | 新增smoke test |
| C5 | Benchmark重构 | 跑完整formal controlled pack | 赛题主张task占比≥60%；`failure_count=0`；`expectation_match_rate=1.00` | `python -m eval.runner --repeat 3 --llm-mode api --out /tmp/c5_verify` |
| C6 | InvariantChecker | 跑C5的benchmark | 静态不变量全部通过；violations=0 | 在C5的report中检查 |
| C7 | Trajectory IR | 跑C5的benchmark | 每个task都有对应的trajectory JSON；两次相同task的trajectory对比diff≤预期 | 在C5的report中检查 |

---

## 第五部分：最终亮点总结

经过以上优化后的StateBus系统在赛题评审中的核心亮点：

### 5.1 通信效率（25分）
- ✅ 结构化Protobuf协议替代自然语言透传
- ✅ text vs protocol双模式formal对比（lane-level）
- ✅ **增量协议帧**（Phase B新增）：同chain内control_bytes节省15-25%
- ✅ **连接类型预校验**：Plan编译时检查step间StateRef兼容性

### 5.2 状态传递创新（20分）
- ✅ StateRef + mmap/shared_memory双后端
- ✅ FEATURE_BUNDLE结构化特征传递
- ✅ **Typed Channel模型**（Phase B新增）：LastValue/Topic/Ephemeral三种channel语义
- ✅ **5种transfer strategy**覆盖不同handoff精度/开销trade-off

### 5.3 记忆复用效果（20分）
- ✅ SQLite + FAISS共享记忆
- ✅ replay/assist/exact三级复用剪枝
- ✅ **双层记忆+多信号检索**（Phase B新增）：semantic+BM25+entity+recency 4信号融合
- ✅ **追加式记忆**：SHA-256内容去重 + immutable memory log

### 5.4 系统完整性（20分）
- ✅ 4 Agent + 双模式 + 协议 + StateRef + 记忆 + 评测全链路闭环
- ✅ **CodeAct受控代码执行**（历史 Phase B 口径；当前 v2 只按 controlled CodeAct-style execution 上读）
- ✅ **协议不变量自动检查**（Phase C新增）
- ✅ **Trajectory IR可复现replay**（Phase C新增）

### 5.5 实验验证（15分）
- ✅ repeat-10 stability (deterministic + serialized API)
- ✅ 29-task continuous benchmark
- ✅ **重构benchmark**（Phase C）：75% task支撑赛题主张 vs 当前38%
- ✅ **协议合规自动验证**（Phase C新增）

---

## 附录：修改文件清单（预估）

### 必须修改
| 文件 | 修改内容 |
|------|---------|
| `tasks/sample_benchmark.yaml` | 恢复475行版本 + 调整lane配额 |
| `protocol/messages.py` | 新增DeltaPlanStep消息 + ChannelKind枚举 |
| `runtime/contracts.py` | 增加channel_kind + 连接预校验 + InvariantChecker |
| `memory/store.py` | 双层记忆 + 多信号融合 + append-only commit |
| `agents/sample_agents.py` | 拆分文件 + 移除双重build_feature_bundle |
| `eval/runner.py` | 调整报告口径 + 拆分文件 |
| `runtime/orchestrator.py` | 增量协议帧emitting |

### 建议修改
| 文件 | 修改内容 |
|------|---------|
| `runtime/codeact_runner.py` | 新增CodeAct执行模块 |
| `tasks/sample_tasks.py` | build_plan支持可变step数 |
| `statepool/store.py` | SHA-256内容去重 |
| `memory/store.py` | _NumpyVectorIndex性能优化 |
| `eval/metrics.py` | 新增delta/invariant相关metric |

### 可选修改
| 文件 | 修改内容 |
|------|---------|
| `protocol/statebus.proto` | 新增DeltaPlanStep定义 |
| `deploy/` | 部署文档更新 |
| `docs/` | 系统设计文档更新 |
| `tests/` | 新增CodeAct/invariant/replay gate测试 |

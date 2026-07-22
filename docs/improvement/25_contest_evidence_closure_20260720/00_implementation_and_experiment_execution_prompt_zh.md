# StateBus v2 赛题证据闭环实施与实验执行 Prompt

> 状态：待实施，完成后由新鲜容器证据替换本文中的历史基线
>
> 日期：2026-07-20
>
> 实现基线：`f0e5583 v2: close adaptive semantic state validation`
>
> 目标环境：`statebus-dev-qcrs`，openEuler 24.03 LTS-SP3 单容器
>
> 适用范围：`v2/`、`tests/v2/`、`scripts/v2_diagnostics/`、连续任务 manifest、实验报告

## 0. 如何使用本文

本文是一份可以直接交给后续实现 Agent 的执行 Prompt，不是结果报告。实施者必须按本文顺序完成代码修复、定向测试、正式实验和证据收口，不得先跑大实验再根据结果反向修改任务或门槛。

本轮只回答赛题要求的五个问题：

1. 纯文本协作换成结构化控制面后，通信开销发生了什么变化？
2. embedding 语义状态是否真的跨进程传递、被数值消费，并改变了后续 evidence hydration？
3. 跨任务记忆是否经历写入、检索、兼容性判断和实际消费，并减少了重复工作？
4. LLM Agent 是否能在注册能力范围内自主规划、检索并选择 DSL 或 CodeAct，而不是只有固定工作流？
5. 上述机制能否在 openEuler 单容器中稳定、可复现地完成两组连续任务？

不要为了让系统看起来更复杂而增加 Agent、能力、后端、模型或实验组合。一个功能只有在它对应明确赛题问题、存在可审计消费链、并有单变量实验时才进入本轮。

## 1. 结论和执行边界

### 1.1 当前不是“功能没做”，而是正式证据还没有完全闭合

基线 `f0e5583` 已经真实具备：

- Planner、Retriever、Executor、Summarizer 四角色 Runtime；
- typed Protobuf + UDS 控制面；
- `StateRef`、shared-memory dense semantic state、跨进程 consumer 和 hydration accounting；
- `ExecutionArtifactRef`、workspace、CAS/长期对象持久化；
- SQLite/向量式 memory index、hybrid query、兼容性和 replay gate；
- 六个 generic adaptive capability；
- LLM 选择 DSL/CodeAct、AST policy、bwrap、非 root 执行和 Runtime quality validator；
- openEuler embed 容器内 `516 passed` 的历史回归证据。

当前 Gate 4 的历史读数是两组正式 family、`5 + 5 = 10` 轮，semantic transfer 9、artifact reuse 13、validated replay 2。Gate 6 的历史读数是 25 个任务中 CodeAct 17、DSL 8。它们是已有证据，不是新实验必须调参复现的目标比例。

还缺六项必须显式关闭的问题；后续实现和验收不得只处理其中一部分：

1. `v2/benchmark/adaptive_formal.py::_financial_source_rows` 会先按 ticker/quarter/metric 筛出唯一目标行，存在 controller 预解题风险；必须改为传递授权范围内的完整原始文档或完整表行。
2. Adaptive formal 当前只有 memory query 记录，没有跨任务 commit、重新加载、实际输入消费和行为改变；query 不能继续被当作 memory reuse。
3. 当前 25-case 的 Retriever 全部选择 `retrieve_table_evidence_v1`，`retrieve_semantic_evidence_v1` 缺少正式自然覆盖；必须由独立 semantic holdout 补证据，不能在 Prompt 中写 expected route。
4. 尚无同任务、同模型、同角色图、同 Executor 算法、同 subprocess 拓扑下的 L0-L3 严格单变量主矩阵。
5. `business_formula_is_not_pre_registered=True` 与当前公开 task contract/operation semantics 的事实不一致；必须改成“公式来自公开 task contract，capability registry 不含 expected answer”。
6. 当前缺口是证据闭环，不是功能数量；本轮不继续增加后端、Agent/进程数量、CodeAct 比例或无新权限边界的 capability。

### 1.2 赛题要求到实验的唯一映射

| 赛题要求 | 本轮机制 | 唯一主证据 | 不用它证明什么 |
| --- | --- | --- | --- |
| 低开销通信 | typed UDS + Protobuf | L0 -> L1 | 不归因给 embedding 或 memory |
| 非文本状态 | Qwen embedding `StateRef` + shared memory | L1 -> L2 | 不声称 hidden state/KV handoff |
| 共享记忆复用 | MemoryRef + compatibility/replay gate | L2 -> L3 | query 数不等于命中或复用 |
| 至少 3 Agent | 四角色相同图和相同 LLM 配置 | 所有 L0-L3 quality pass | 不用 Agent 数量制造复杂度 |
| 两组连续任务、至少 10 轮 | 两个 family 的前 5 轮 | `5 + 5` L0-L3 主矩阵 | 不用重复题凑轮数 |
| 稳定长期运行 | 两个 family 各扩展到 10 轮 | `10 + 10` 仅跑 L3 | 不重复完整四层矩阵 |
| CodeAct 鼓励项 | LLM 在 DSL/Python 中选择 | 独立 Adaptive 25-case | 不混入通信/记忆因果实验 |
| openEuler 交付 | 单容器构建、运行、回归 | 最终 container gate | 不扩大为 VM/跨机兼容性 |

### 1.3 必须保留的 claim 边界

- 当前非文本状态是 little-endian float32 embedding/semantic matrix，不是 LLM hidden state 或 KV cache。
- 当前可证明的是“注册合同和离线分析域内的 bounded generalization”，不是开放域 Agent。
- 外层 Runtime 以容器 root 创建 bwrap namespace；生成代码在 bwrap 内以 `65534:65534` 执行。这不是 production-grade sandbox。
- `ExecutionArtifactRef` 与 `StateRef` 必须继续分离。
- history reuse、artifact reuse、assist、validated replay、exact replay 必须分别统计。
- 端到端时延如果没有串行重复证据，只能作为描述性结果，不能写 superiority。

### 1.4 已实现能力必须有证据落点，但不强制每题触发

| 已实现路径 | 本轮使用位置 | 为什么需要 |
| --- | --- | --- |
| UDS handshake、typed Protobuf、capability discovery | E1-E5 | 对应结构化通信和 Runtime 权限面 |
| shared-memory embedding `StateRef` | E1 L2/L3、E2、E4 | 对应非文本中间状态和跨进程 hydration |
| workspace + `ExecutionArtifactRef` + CAS/长期对象 | 所有执行 lane | 保证结果、lineage、复验和长期引用 |
| hybrid memory + compatibility/replay gate | E1 L3、E2、E3 | 对应跨任务写入、检索、消费和拒绝 |
| semantic/table Retriever | E4、E5 | 证明 route 不是固定单一路径 |
| Transform DSL / bounded Python | E5 | 证明 LLM Executor 的受控执行选择 |
| AST/policy + bwrap non-root | E5 | 证明 CodeAct 执行边界 |
| terminal quality validator | 所有 lane | 防止格式正确但业务错误的产物进入 memory/报告 |

“使用全部实现”不等于让每个 capability 在每个 case 都出现。比如没有风险冲突的任务不应为了覆盖率强制选择 `compose_risk_memo_v1`；正式报告应同时给出 capability advertised count、selected count 和 verified count，未选择就是未选择。

### 1.5 KV/hidden 研究明确不属于本轮闭环

KV cache、hidden-state 和 latent-state handoff 的问题定义、开源实现审计、合同草案及独立实验方案见 [`kv_hidden_state_transfer_design_20260720.md`](../../planning/kv_hidden_state_transfer_design_20260720.md)。该文档是 Runtime 冻结后的研究支线，不是 E1-E6 的待办清单。其推荐方案是接入同一个 Adaptive Runtime 的 Retriever -> Summarizer 可选 latent handoff mode，而不是另建一套旁路系统；Planner 只提出逐边 handoff 意图，Runtime 在 retrieval 后做最终激活和确定性回退。prefix 与 latent 使用独立开关，但这一接入仍必须等本轮冻结后开始。

在本轮完成定义全部满足并冻结 Git SHA、镜像 digest 和正式 artifact 之前：

- 不新增 `KVCacheRef` 或 `LatentStateRef` 到当前 Runtime；
- 不安装 LMCache、修改 vLLM connector、重启或替换 `127.0.0.1:53334` 服务；
- 不把 APC registry/metric、prefix hash 或 embedding `StateRef` 写成真实 KV/hidden transfer；
- 不把 KV/hidden 混入 L0-L3、10+10、adaptive memory、semantic holdout 或 CodeAct 的结论。

本轮正式非文本状态仍只有 Qwen embedding `StateRef`。后续若启动研究支线，必须使用独立容器、模型、端口、runtime root 和 artifact，并且只在 consumer engine/worker 真实消费 tensor 后声称实现。

## 2. 为什么采用当前架构

### 2.1 Runtime 的作用

LLM Agent 负责语义决策：理解任务、提出计划、表达检索意图、选择合法执行方式、生成 DSL/Python、组织引用结论。

Runtime 负责系统事实：

- 向 Agent 公布当前允许的 capability surface；
- 审批 DAG、角色数量、依赖深度、时间预算和权限；
- 通过 UDS/Protobuf 调度角色和执行器；
- 创建、解析、校验和回收 StateRef/ArtifactRef；
- 执行 handler、沙箱和 validator；
- 管理 memory commit、检索、兼容性和 replay；
- 记录 telemetry、lineage、失败原因和清理结果。

因此 Runtime 不是替代 Agent，也不是把答案写死。它相当于一个受控操作系统/控制平面：模型提出“做什么和怎样做”，Runtime 决定“是否有权、怎样安全执行、结果是否可信”。

### 2.2 “只能使用注册 capability”为什么合理

capability 是 Runtime 允许 Agent 调用的受控 API，不是某一道题的答案模板。当前 generic pack 的六项能力是：

| 角色 | capability | 允许的通用行为 |
| --- | --- | --- |
| Retriever | `retrieve_semantic_evidence_v1` | 从授权离线 corpus 检索叙事语义证据 |
| Retriever | `retrieve_table_evidence_v1` | 从授权离线 corpus 检索结构化表格证据 |
| Executor | `execute_analysis_dsl_v2` | 执行受限、可验证的分析 DSL |
| Executor | `execute_bounded_python_v2` | 生成并执行受 AST/bwrap/validator 约束的 Python |
| Summarizer | `compose_claim_set_v2` | 从已验证 evidence/artifact 生成引用结论 |
| Summarizer | `compose_risk_memo_v1` | 从异常/冲突证据生成风险 memo |

注册表限定的是权限、输入输出合同、副作用和验证方式。它不应包含 task ID、expected answer、某个 ticker 的数值或针对单 case 的公式分支。

本轮不新增 web、任意 shell、任意文件读取或动态工具注册。只有满足以下任一条件才允许新增 capability：

1. 新任务需要一种现有六项能力不能表达的新副作用边界；
2. 新输入/输出 Ref 种类有独立生命周期和校验语义；
3. 必须采用不同 sandbox/权限策略；
4. 已有通用 DSL/Python 无法表达，且原因不是 adapter 写得不够通用。

如果只是增加一个公式、列名、数据集或任务描述，应扩展公开 task contract/schema/manifest，不能增加 `solve_case_foo_v1`。

### 2.3 LLM 为什么重要，但不能污染 L0-L3 因果实验

LLM 对 Agent 职能很重要，因为开放文本任务的计划、查询表达、route 选择、DSL/Python 生成和总结都不是固定计算器能替代的。Adaptive 25-case 专门验证这件事。

L0-L3 的目标不同：它要归因通信、语义状态和 memory 三项系统机制。因此四个 lane 必须使用同一 Executor 算法。推荐正式 profile：

```text
Planner     = qwen3-32b local_vllm
Retriever   = qwen3-32b local_vllm
Executor    = deterministic_codeact
Summarizer  = qwen3-32b local_vllm
```

这里的 `deterministic_codeact` 表示固定执行算法/公开 operation contract，不表示固定答案：

- 从当前输入实时读取和计算；
- 不读取 `expected_facts`；
- 相同输入和合同得到相同结果；
- 仍经过 workspace、artifact、Runtime validator 和 lineage；
- 四个 lane 使用同一实现和版本。

当前 CLI 的 `role_path_mode` 同时控制多个角色。实施时必须把“语义角色模型模式”和“Executor recipe 模式”拆开，至少为 continuous formal 增加独立的 `executor_mode=deterministic_codeact`。不要通过四个 lane 选不同 `role_path_mode` 来模拟该控制。

### 2.4 本轮不调整 embedding 模型

正式 embedding 固定使用 `Qwen3-Embedding-0.6B`。本轮不做维度、模型、量化、阈值或 pooling 的参数搜索，也不把 deterministic embedding 混入 live 结果。

需要补的是 embedding 的消费闭环，而不是换模型：

- 同一个 model revision 和 normalization 配置；
- Retriever producer 生成 query/candidate matrix；
- 通过 shared-memory StateRef 交给独立 consumer PID；
- consumer 做真实数值 top-k；
- selected IDs 决定后续局部 hydration；
- memory commit/query 复用同一 embedding 空间；
- 记录 shape、dtype、bytes、PID、selected IDs、hydration bytes 和 cleanup。

deterministic embedding 仅用于快速单元测试，不能进入正式报告聚合。

## 3. 正式实验对象

### 3.1 L0-L3 主矩阵

| Lane | 相对上一层唯一新增机制 | 数据/历史传递方式 | Memory | Executor |
| --- | --- | --- | --- | --- |
| L0 | 无 | 纯文本 handoff，完整 current evidence 和等价历史事实 | 关闭 | `deterministic_codeact` |
| L1 | typed UDS + Protobuf | typed inline payload，内容与 L0 等价 | 关闭 | 同上 |
| L2 | Qwen semantic `StateRef` | shared-memory top-k 后局部 hydration | 关闭 | 同上 |
| L3 | 跨轮 MemoryRef/replay | L2 + family-scoped memory query/consume | 开启 | 同上 |

主矩阵使用现有两个 family 的前 5 轮：

- `formal_financial_reports_v1`：保留两个 validated replay 目标轮次 R2、R4；
- `formal_operating_metrics_v1`：只声称 history/artifact reuse，不强行改成 replay；
- 运行量：`2 family x 5 round x 4 lane = 40` 次任务执行。

### 3.2 L0 的“纯文本”准确含义

L0 可以复用同一个外层 benchmark harness、模型客户端、workspace 和 validator，以便公平采集指标；但 Agent handoff 本身必须满足：

- 不发送 typed StateRef、MemoryRef 或 capability result ref；
- 不使用 semantic selection；
- 不查询共享 memory；
- 当前 evidence 和前序已验证结果都渲染成自然语言/文本表格；
- 与其他 lane 保持相同四角色顺序和消息边界。

如果 L0 仍在 StateBus Runtime 内部运行，报告必须写“matched pure-text lane in the same harness”，不能称为独立外部系统。若使用 existing external text baseline，也必须先证明角色图、信息、模型、Executor 和 validator 等价。

### 3.3 信息等价和历史公平性

每个 round 都生成一个 lane-neutral `PriorRoundContext` 审计对象，只包含已经由该 lane 自己完成并验证的前序事实/产物摘要。四个 lane 的 `prior_fact_digest` 必须相同：

- L0：把它渲染成文本；
- L1：以 typed inline fields 传递；
- L2：允许直接引用本 lane 的上游 artifact/state，但不做 memory search/replay；
- L3：通过 MemoryRef 检索和消费等价对象。

禁止让 L3 看到其他 lane 看不到的业务事实。L3 的优势只能来自索引、传递、复用和跳步方式，而不是额外信息。

所有 lane 还必须固定：

- 相同 request text、source files 和 source content hash；
- 相同 qwen3-32b endpoint、temperature、seed、max tokens 和 timeout；
- 相同角色数、DAG 上限、任务顺序、工具 handler 和 validator；
- 相同 UDS worker/subprocess 拓扑；L0 传 UTF-8 文本 frame，L1-L3 传 typed Protobuf frame；
- 相同 deterministic Executor 版本；
- 相同错误重试政策；
- 独立、干净的 lane runtime root；
- 全部串行执行，不并发启动 formal API calls。

只有 L3 在同一 family 的连续轮次内共享 memory root。family 之间、lane 之间、正式 run 之间不得共享 memory。

### 3.4 结构化通信的公平计量

不得只比较 L0 的全部文本字节和 L1 的 Protobuf header 字节。每个 lane 至少分别记录：

- `message_count`；
- handshake/capability-discovery message count 和 registry digest；
- `control_bytes`；
- `inline_payload_bytes`；
- `state_ref_descriptor_bytes`；
- `hydrated_evidence_bytes`；
- `total_wire_bytes`；
- Driver/worker/producer/consumer PID 和实际 transport backend；
- 各角色 `prompt_chars`、`prompt_tokens`、completion tokens；
- tokenizer/model revision。

主报告同时展示 control-plane 与 end-to-end Agent-visible 开销。只有定义相同、范围相同的字段可以直接求 delta。

正式 E1 不得让 L0 走本地函数调用、L1 走 subprocess 后再比较二者。若当前 continuous runner 只支持 loopback，Phase 3 必须复用已有 control subprocess worker，将 matched text frame 和 typed Protobuf frame 放到相同 UDS/process topology 中；无法做到时，只能把 carrier 结果标为 diagnostic，不能作为低开销通信 headline。

### 3.5 两组 10 轮的正确实现

不要复制两套前 5 轮，也不要用 `--max-cases 5` 把主矩阵标成 `diagnostic_partial`。将两个正式 family 扩展为 10 轮，并在 manifest 中增加通用命名视图：

```json
{
  "round_count": 10,
  "experiment_views": {
    "causal_core": [1, 2, 3, 4, 5],
    "long_horizon": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
  }
}
```

loader 必须验证：

- view 中 round 严格递增、无重复、都存在；
- 所有 dependency 都在当前 round 之前；
- `causal_core` 的 R1-R5 内容 hash 与基线一致，除中性措辞修正外不得改题；
- 选择一个命名 view 是完整实验对象，不是 partial run；
- 未声明 view 的历史 family 行为保持兼容。

`causal_core` 跑完整 L0-L3；`long_horizon` 只跑 L3。总计新增长期稳定性证据为 `2 x 10 x 1 = 20` 次执行，不再把完整四层扩成 80 次。

## 4. 连续任务调整

### 4.1 先修正文案，不暗示实现

将以下类型措辞：

```text
Both values are already in memory.
All values are already in memory.
```

改成中性合同，例如：

```text
Prefer previously verified results when they are available and compatible; otherwise recompute from the source.
```

任务可以要求复用目标，但不能告诉 Agent “memory 一定命中”“应该走 semantic route”或“本轮应 replay”。这些是 Runtime 决策和实验观测，不是用户给出的答案。

### 4.2 财务 family 的 R1-R10

R1-R5 保留当前业务结构：

| Round | 任务 | 主要依赖 | 最低复用语义 |
| --- | --- | --- | --- |
| R1 | 提取 ACME 2026Q1 revenue | 无 | bootstrap/commit |
| R2 | 提取 ACME 2025Q4 revenue | R1 extraction strategy | validated replay target |
| R3 | 计算 ACME Q4 -> Q1 delta | R1、R2 facts | assist |
| R4 | 提取 BETA 2026Q1 revenue | R1 strategy | validated replay target |
| R5 | 比较 ACME/BETA 2026Q1 | R1、R4 facts | assist |

R6-R10 只增加新的现实场景，不通过换数字重复前五轮：

| Round | 新场景 | 设计目的 | 预期策略边界 |
| --- | --- | --- | --- |
| R6 | 提取 BETA 2025Q4 revenue | 跨越 5 轮复用早期 extraction strategy | 至少 assist；不新增强制 replay headline |
| R7 | 计算 BETA Q4 -> Q1 delta | 组合 R4、R6 的两个历史事实 | 实际消费多个 MemoryRef/artifact |
| R8 | 从列顺序/表头轻微变化的财报输入提取 BETA 2025Q3 | schema drift 下的迁移 | 兼容结果只能 assist，不能无条件 replay |
| R9 | 提取 ACME 2025Q3，同时存在高相似但 runtime/output signature 不兼容的旧 memory | 负例和 fail-closed | 候选可被检索，但必须拒绝 replay 并重新执行 |
| R10 | 生成 ACME/BETA 三期趋势与完整 lineage 摘要 | 长程多源组合和审计 | 消费前序事实/产物，列出真实 reuse/reject 记录 |

R8 的 schema drift 必须通过通用 markdown/table schema 适配实现。若为 R8 增加 `if task_id == ...` 或 ticker/quarter 专用分支，则该轮不能作为泛化证据。

R9 的不兼容候选由 benchmark fixture 在运行前写入一个明确旧版本签名的 memory entry。该 fixture 不包含当前正确答案，只改变 compatibility/output contract/validator digest。任务 Prompt 不得提及候选 ID 或预期拒绝原因。

### 4.3 运营指标 family 的 R1-R10

R1-R5 保持当前 history/artifact reuse 定位：

| Round | 任务 | 主要依赖 | 最低复用语义 |
| --- | --- | --- | --- |
| R1 | disease CSV schema/missingness profile | 无 | bootstrap/commit |
| R2 | mean cases + max deaths | R1 schema | assist/artifact reuse |
| R3 | IQR outlier analysis | R1、R2 | assist/artifact reuse |
| R4 | weather CSV profile + mean windspeed | R1/R2 strategy | cross-dataset assist |
| R5 | 汇总前四轮 lineage | R1-R4 artifacts | history-backed reuse |

R6-R10 设计为：

| Round | 新场景 | 设计目的 | 预期策略边界 |
| --- | --- | --- | --- |
| R6 | 按月份聚合 weather `WINDSPEED` | 复用 R4 schema/stats，执行新聚合 | assist，不称 replay |
| R7 | 对 weather `BARO` 执行 IQR 异常分析 | 跨数据集复用 R3 的统计策略并结合 R4 schema | 多 artifact/strategy 消费 |
| R8 | 对列重排、增加无关列或公开 alias 的 weather 变体做 profile/mean | 验证轻微 schema drift | assist；记录 alias/schema 解析 lineage |
| R9 | materialize cleaned weather table，存在 validator/output contract 不兼容旧候选 | 验证不兼容拒绝 | candidate > 0、compatible replay = 0、正常重算通过 |
| R10 | 汇总十轮 schema、stats、outlier、clean artifact 和拒绝记录 | 长期 lineage 完整性 | history/artifact reuse，不升级为 validated replay |

运营 family 仍然是 history-backed-only。不能为了让 suite 的 replay 数字更大而修改它的 minimum reuse class。

### 4.4 expected facts 的边界

`expected_facts`、`quality_checks`、`expected_metric_effects` 和 expected route 只能由 benchmark 完成后读取。它们不得进入：

- Planner/Router/Retriever/Executor/Summarizer Prompt；
- capability public view；
- Runtime operation selection；
- memory query；
- memory commit gate；
- replay decision。

memory commit 由产品 Runtime 的 terminal validator、artifact hash、input lineage 和 contract validation 决定，不能由 benchmark gold 决定。外部 expected facts 如果失败，应将整次 formal run 标为无效，但不能反向改变该次 Runtime 的行为。

新增自动 leakage audit：序列化每个角色实际发送给模型的 request，断言不存在上述 benchmark-only keys/values。对数值相同但属于公开输入的情况要通过 provenance 判断，不能只做脆弱的全局字符串禁用。

## 5. 实施阶段和代码顺序

### Phase 0：冻结基线和证据口径

1. 记录实现起点 `f0e5583`、当前分支、容器镜像 ID、模型 ID 和 capability registry digest。
2. 不修改或删除历史 run artifact；新实验使用全新 run ID/root。
3. 将本文的“工程完整性门”和“正向结果门”分开。实验结果为负不等于实验未完成。
4. 在任何代码改动前，运行容器内 deterministic focused baseline；不先运行 live 25-case。

### Phase 1：先修真实性、公平性和 adapter 预解题风险

#### 1.1 修 financial source adapter

当前 `v2/benchmark/adaptive_formal.py::_financial_source_rows` 会按 ticker/quarter/metric 解析后只返回唯一目标行。改为向 Retriever/Executor 提供授权 corpus scope 内的完整原始文档或完整表行，并保留每行 locator。

允许 Runtime 根据公开 corpus scope 定位文档；不允许 benchmark adapter 在 Agent 之前按目标 metric 把答案行筛出来。改完后验证：

- execution input 包含多行候选；
- selected row/locator 由检索或执行步骤产生；
- expected value 从未进入 input artifact；
- 原 25-case quality 不下降。

#### 1.2 修公式与泛化文案

`_operation_for_spec`、`_output_schema`、`_operation_semantics` 中的 operation/schema/formula 是公开 task contract 和 deterministic validator 的一部分，本身不等于作弊；但不能继续声明业务公式“未预注册”。

将 `business_formula_is_not_pre_registered=True` 改为准确、可审计的字段，例如：

```text
formula_source=public_task_contract
capability_registry_contains_expected_answers=false
benchmark_gold_visible_to_runtime=false
```

报告必须说明：generic capability 没有按题注册，但正式 adapter 仍支持一个声明过的离线分析 operation/schema 集合。这支持 bounded domain generalization，不支持开放域泛化。

#### 1.3 拆分角色模型模式和 Executor 模式

为 continuous formal 增加显式 execution profile，至少可独立配置：

- Planner mode；
- Retriever mode；
- Executor mode；
- Summarizer mode；
- embedding mode。

默认历史 CLI 保持兼容；新 `contest_causal` profile 使用三角色 local-vLLM + `deterministic_codeact` Executor。结果 artifact 必须逐角色记录实际 model/backend，不能只记录一个模糊的 `role_path_mode`。

#### 1.4 建立 matched lane contract

新增机器可读 fairness manifest，逐 lane 记录并比对：

- task/source/prior-fact digest；
- role graph 和 message boundary digest；
- model config digest；
- executor/validator digest；
- capability surface digest；
- runtime root 和 memory scope；
- gold visibility audit；
- lane 唯一开启的 feature flags。

若存在两个以上非预期差异，主矩阵必须 fail closed，不能输出 headline delta。

#### 1.5 Phase 1 测试

优先扩展已有测试文件，只有合同独立时才新建测试。至少覆盖：

- full-table financial source，不能只剩目标行；
- benchmark-only fields 不进入 role requests；
- per-role execution profile 的 Executor 在四层完全相同；
- L0/L1/L2/L3 source 和 prior-fact digest 相同；
- fairness manifest 对额外 feature 差异 fail closed；
- 旧 CLI/default suite 不回归。

### Phase 2：补 Adaptive memory 的真实闭环

#### 2.1 共享 store 生命周期

当前 `v2/runtime/adaptive_mainline.py` 每个 task 在 `runtime_root/memory_index` 创建独立 store。增加显式、可注入的 family memory scope：

```text
task runtime root     = 每个 task 独立
family memory root    = 同一 family 连续轮次共享
lane/run memory root  = 隔离
```

建议在 `AdaptiveMainlineRequest` 增加 `memory_store_root` 或等价依赖注入；未提供时保持当前 task-local 行为，避免破坏历史调用者。不要把一个可变 Python store 对象塞进 Protobuf 合同。

#### 2.2 commit gate

只有满足以下产品 Runtime 条件才能写 memory：

- terminal `ExecutionArtifactRef` 已 verified；
- terminal quality report 对应最终 artifact hash；
- input refs、source hashes、operation/output contract 和 validator digest 完整；
- commit status、source Agent、创建时间、topic、summary、tags、embedding ref 完整；
- 无 fallback/未验证 artifact 不能进入 replay-ready memory。

benchmark gold 不参与 commit gate。commit 后必须持久化并可由下一个 task 的新 Runner 实例重新加载。

#### 2.3 query、match、consume 分层

当前 `adaptive_dispatcher.py` 在 retrieval 后调用 `lookup_hybrid`，但结果主要被记录。补成以下漏斗：

```text
memory_query
  -> raw candidate pool
  -> compatibility-filtered match
  -> policy-approved match
  -> input Ref consumption
  -> behavioral effect
  -> optional skipped work/replay
```

各层必须有独立计数和 ID，不允许用 `hybrid_memory_query_count > 0` 代替命中。

#### 2.4 消费语义

- `assist`：把兼容 MemoryRef 的摘要/evidence/artifact lineage 作为 Executor 或 Summarizer 的真实输入；不能跳过当前结果验证。
- `validated_replay`：复用已验证策略/program/artifact recipe，在当前输入上重新执行或复算并通过 validator；允许跳过重复的 recipe/code generation，但不能直接恢复旧答案。
- `exact_replay`：只有 task/spec/input/plan/runtime/output contract 全部精确匹配时才可恢复 verified artifact。此次实验不要求出现，未观测就保持 0。
- `disallowed`：候选保留在 audit pool，记录具体不兼容维度，不进入任何角色输入。

每次消费生成 `MemoryConsumptionRecord` 或等价合同，至少包含 memory ID、consumer role/step、输入 Ref、replay class、compatibility decision、before/after decision surface、实际跳过的 step/LLM call。

#### 2.5 behavioral effect

新增可复算指标：

- `memory_candidate_count`；
- `memory_compatible_match_count`；
- `memory_consumed_count`；
- `memory_behavioral_effect_count`；
- `memory_rejected_incompatible_count`；
- `skipped_step_count`；
- `skipped_llm_call_count`；
- `reused_artifact_count`；
- `validated_replay_count`；
- `exact_replay_count`。

behavioral effect 必须由输入 Ref、selected IDs、plan/recipe、hydration 或实际执行步骤发生变化证明。仅把 match 写进 summary 不算消费。

#### 2.6 Phase 2 测试

至少覆盖：

- task A commit，task B 使用新 Runner 从 family root 加载并检索；
- assist match 进入 Executor/Summarizer 的实际 input refs；
- validated replay 复用 recipe，但当前数值仍重新验证；
- runtime signature 不兼容候选被检索但不消费；
- output contract 不兼容 fail closed；
- gold 不影响 commit/replay；
- memory family/lane/run 隔离；
- query、match、consume、effect、skip 计数互不混用。

### Phase 3：连续任务 view、R6-R10 和实验 runner

1. 扩展 continuous family schema/loader，加入 `experiment_views`。
2. 按第 4 节增加 R6-R10，R1-R5 仅做中性措辞修复。
3. 新增 view-level design audit 和 dependency/reuse audit。
4. `live_runner` 增加 `--round-view causal_core|long_horizon`。
5. `--layer L3 --round-view long_horizon` 必须被标记为正式稳定性证据，但不得冒充完整 L0-L3 对照。
6. 将 existing subprocess transport 扩展到 continuous formal；四层使用相同 worker 拓扑，只有 carrier/state/memory flags 按层变化。
7. 默认 formal continuous collection 必须显式选择 view，避免未来 round_count 改变后悄悄改变 headline 对象。
8. 将 L0-L3 的 output schema、timing、role calls、memory funnel 和 semantic consumption 指标统一到同一 report contract。

不得为 R6-R10 添加 task ID 分支。若现有 generic operation contract 无法表达，应先判断是否为公开 schema/validator 扩展；只有新的权限或副作用边界才增加 capability。

### Phase 4：semantic holdout 和配置级泛化审计

新增一个独立 4-case holdout，不并入连续 10 轮 headline：

| Case | 输入形态 | 任务目的 | 外部审计期望 |
| --- | --- | --- | --- |
| S1 | 纯叙事长文档，无答案表格 | 抽取跨段事实及 locator | 自然选择 semantic capability |
| S2 | 纯叙事长文档，无答案表格 | 汇总两个章节的因果/风险关系 | 自然选择 semantic capability |
| S3 | 表格为唯一答案来源 | 数值/实体 lookup 控制 | 自然选择 table capability |
| S4 | 叙事 + 表格混合 | 数值和限定条件联合回答 | route 不预写，记录模型实际选择和 evidence 类型 |

约束：

- source 必须是 repo-local、offline、可复现的数据；
- S1/S2 不能暗藏可直接回答的表格；
- Prompt/capability description 不写 expected route；
- expected facts 只在结束后评分；
- 4/4 quality pass；
- suite 至少观测 semantic capability 2 次、table capability 1 次；
- semantic case 必须留下跨进程 embedding StateRef 数值消费和 hydration 记录；
- 不要求 S4 走某条固定 route，以免把评测写进 Prompt。

做一次“配置级扩展”审计：在 generic Runtime 和 adapter 接口完成后记录 `RUNTIME_FREEZE_SHA`，holdout 只能新增/修改 corpus、manifest、公开 schema 和外部 gold。运行后检查 `RUNTIME_FREEZE_SHA..HEAD` 在 `v2/runtime/`、`v2/control/`、`v2/state/`、`v2/memory/` 中没有 holdout-specific 分支。

这不是严格双盲学术 holdout，只能证明 manifest/schema 级扩展不需要改 Runtime。若新增任务后仍需修改 Runtime `if` 分支，必须将结论降级为“adapter-supported bounded domain”，不能写配置级泛化。

### Phase 5：Adaptive Agent 和 CodeAct 保持独立

保留现有 25-case Adaptive formal 作为 Agent 自主性实验：

- Planner/Retriever/Executor/Summarizer 使用同一 qwen3-32b 配置；
- Planner 在六个注册 capability 中提出合法 DAG；
- Retriever 自主选择 semantic/table；
- Executor 自主选择 DSL 或 bounded Python；
- Python 必须经过 AST/policy、bwrap、非 root 和 terminal quality validator；
- DSL/Python 均不得读取 expected facts；
- 不允许 sandbox/model/runtime fallback 被算作 formal success。

历史 `CodeAct 17 / DSL 8` 的含义只是：25 个 case 中有 17 个 verified Executor 选择 bounded Python，8 个选择 DSL。它不是 17 个 Agent、17 个 capability，也不是“CodeAct 比 DSL 提升 17 次”。新 run 不以复现 17/8 为门槛，只要求两种 execution kind 都有自然覆盖、25/25 quality 和完整审计。

Adaptive memory 另做一个最小补充序列：现有 financial 5 轮 + 1 个 runtime-signature 不兼容负例。它回答“Adaptive match 是否被实际消费”，不把 memory 变量混入 25-case CodeAct 选择分布。

正式 Adaptive run 的 replan budget 继续为 0，以保证当前 25-case 可控。若时间允许，可额外做 1 个 `max_replans=1` 的诊断 case，展示 DSL 不适用时转 bounded Python；该 case 不进入主性能和质量 headline，也不是本轮阻塞项。

## 6. 最小实验矩阵和顺序

| ID | 实验 | 执行数 | 唯一问题 | Headline 级别 |
| --- | --- | ---: | --- | --- |
| E0 | deterministic focused/container preflight | 测试集合 | 实现和环境是否可运行 | 工程门 |
| E1 | `causal_core` L0-L3 | 40 | 通信、状态、memory 分别贡献什么 | 主因果证据 |
| E2 | `long_horizon` L3 only | 20 | 两组各 10 轮能否稳定并长期复用 | 稳定性证据 |
| E3 | Adaptive memory financial 5 + negative 1 | 6 | Adaptive memory 是否真实 commit/consume/reject | memory 补充证据 |
| E4 | semantic holdout | 4 | semantic route 和长文本是否真实覆盖 | 泛化补充证据 |
| E5 | Adaptive formal | 25 | LLM 是否自主选择 DSL/CodeAct | Agent 能力证据 |
| E6 | full `tests/v2` + deterministic preflight | 1 套 | openEuler 容器交付是否回归 | 最终交付门 |

不增加 embedding 参数 sweep、capability 数量 sweep、Agent 数量 sweep、后端性能矩阵或 20 轮四层矩阵。mmap/CAS/shared-memory 的实现测试继续保留，但本轮 headline 只使用 semantic shared memory 和长期 artifact/CAS 的既定分工。

### 6.1 工程完整性门和正向结果门必须分开

工程完整性门失败表示实验无效：

- source/model/executor/validator 不等价；
- gold 泄漏；
- quality 未通过；
- semantic state 没有真实跨进程消费；
- memory 只有 query 没有 consume；
- CodeAct 使用非 bwrap/root fallback；
- artifact/telemetry 不完整。

正向结果门决定能否升级 claim，不决定是否隐藏结果：

- L1 相比 L0 的 matched communication token/byte delta 是否为负；
- L2 相比 L1 的 hydration/prompt bytes 是否下降；
- L3 相比 L2 是否有实际 skip/LLM call reduction；
- p50/p95 是否改善。

如果正向结果为 0 或负，仍应报告，并分析结构化 envelope、embedding 构造、持久化或 validator 的成本。禁止改任务使数字变好。

### 6.2 时延口径

第一次 E1 串行 run 足以生成每 lane 10 个 task 的描述性 p50/p95，但不足以宣称稳定时延 superiority。

只有需要正式写时延优势时，才增加一次完全相同的反向 lane 顺序 run：

```text
Run A: L0 -> L1 -> L2 -> L3
Run B: L3 -> L2 -> L1 -> L0
```

两次都必须串行，模型服务配置不变。否则报告写“observed latency in this run”，不写 statistically stable improvement。

## 7. 指标和验收门槛

### 7.1 所有实验公共指标

- task/family/lane/run ID；
- git SHA、dirty flag、image ID/digest、OS、Python；
- role model、embedding model、revision、temperature、seed、max tokens；
- capability registry digest、runtime compatibility signature、validator digest；
- `message_count`、control/inline/ref/hydration/total bytes；
- 各角色 prompt/completion token 与 LLM call count；
- task total 和各 stage latency；
- quality floor、expected-facts external score、fallback/repair；
- artifact hash、source hash、lineage path、cleanup status。

### 7.2 Semantic State 指标

- publish/resolve/transfer/consume count；
- backend、dtype、shape、size bytes；
- producer PID、consumer PID；
- query row reuse/encode count；
- candidate IDs、counterfactual IDs、selected IDs；
- selected evidence bytes、hydrated bytes；
- `behavioral_effect`；
- owner release、consumer close、orphan cleanup。

L2 必须满足：

- 10/10 quality pass；
- 至少一个真实 local Qwen state；
- producer PID != consumer PID；
- consumer 对矩阵执行数值 top-k；
- selected IDs 实际决定 hydration；
- 相对无 semantic selection 的 counterfactual 至少一次 `behavioral_effect=changed`；
- 不出现 deterministic embedding fallback。

### 7.3 Memory 指标漏斗

报告按以下顺序展示，不合并：

```text
query_count
candidate_count
compatible_match_count
policy_approved_match_count
consumed_memory_count
behavioral_effect_count
assist_count
validated_replay_count
exact_replay_count
rejected_incompatible_count
skipped_step_count
skipped_llm_call_count
```

L3 必须满足：

- 两个 family 均 10/10 quality pass；
- 至少一次 compatible match 被 Executor/Summarizer 实际消费；
- 至少一次可复算 behavioral effect；
- financial `causal_core` 的 R2/R4 两个 validated replay target 成功；
- operating family 保持 history/artifact reuse，不伪装成 replay；
- R9 负例候选可见、replay 被拒绝、当前任务重算通过；
- `hybrid_memory_query_count > 0` 单独不构成通过。

### 7.4 Adaptive/CodeAct 指标

- approved/rejected/repaired plan count；
- selected capability/role/step DAG；
- semantic/table retrieval selection；
- DSL/Python selection；
- AST/policy reject、repair、bwrap execution；
- sandbox UID/GID/backend/network policy；
- terminal quality report 与 artifact hash 对齐；
- model/runtime/sandbox fallback；
- actual MemoryRef input/consumption（仅 E3）。

E5 门槛：25/25 quality pass、DSL 和 Python 都有自然覆盖、所有 Python 为 bwrap/non-root、无 sandbox fallback。不要把 17/8 写成硬编码通过条件。

### 7.5 总体质量门

- E1：四个 lane 各 `10/10`；
- E2：两个 family 各 `10/10`；
- E3：`6/6`，含不兼容负例；
- E4：`4/4`，semantic >= 2、table >= 1；
- E5：`25/25`；
- E6：完整 `tests/v2` 通过，preflight `ok=true`；
- 无 oracle prompt、无未声明 fallback、无孤儿 shared memory、无 artifact hash mismatch。

## 8. 容器和 vLLM 执行规范

### 8.1 容器是正式执行边界

宿主机只做：

- `docker compose`/`docker exec`；
- GPU 映射；
- vLLM endpoint 健康检查；
- 读取挂载到 `$HOME/statebus/runs` 的结果；
- Git 操作。

Runtime、Executor、validator、StatePool consumer、memory、bwrap 和 pytest 都在容器内运行。不得在宿主 conda 环境跑一次后把结果写成 container evidence。

这是硬约束，不只约束最终 formal run。以下命令和脚本全部必须通过 `docker exec` 或 repo wrapper 进入 `statebus-dev-qcrs` 后执行：

- focused/full `pytest`；
- deterministic/live preflight；
- benchmark、report generator 和 evidence audit；
- embedding/CUDA/StateRef/MemoryRef diagnostics；
- bwrap/CodeAct readiness 和 smoke；
- 任何会 import `v2` Runtime 代码的 Python 检查。

宿主机允许执行的只是不运行项目 Runtime 的操作，例如 `git status`、`git diff --check`、`docker ps`、`docker exec`、vLLM health check 和读取挂载结果。宿主机上的 `python`/`pytest` 结果一律不得计入测试通过数或实验结论。

当前目标容器：

```text
container: statebus-dev-qcrs
image:     statebus-dev-openeuler:24.03-lts-sp3-embed
project:   /workspace/statebus/project
python:    /usr/bin/python3
runs:      /statebus/runs -> $HOME/statebus/runs
```

### 8.2 构建或启动容器

容器已存在时不要无理由重建。需要重建时使用 embed target：

```bash
export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
export STATEBUS_DOCKER_TARGET=embed
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d
docker ps --filter name=statebus-dev-qcrs
```

### 8.3 每条容器命令都先激活环境

统一模板：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q tests/v2/...
'
```

不要在容器里执行 `source deploy/activate_statebus_host.sh`，也不要依赖宿主 conda。外层 Runtime 以 root 运行是为了创建 bwrap namespace；LLM 生成代码必须在 bwrap 内以非 root 身份运行。

### 8.4 vLLM 使用方式

当前本地服务配置：

```text
STATEBUS_LOCAL_VLLM_BASE_URL=http://127.0.0.1:53334/v1
STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b
STATEBUS_EMBEDDING_MODE=local
STATEBUS_EMBED_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B
STATEBUS_EMBED_DEVICE=cuda:0
```

容器使用 `network_mode: host`，因此容器内 `127.0.0.1:53334` 可以访问宿主 vLLM。先在宿主和容器各检查一次：

```bash
curl -fsS http://127.0.0.1:53334/health
curl -fsS http://127.0.0.1:53334/v1/models

docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  curl -fsS http://127.0.0.1:53334/health
  python3 -c "import json,urllib.request; p=json.load(urllib.request.urlopen(\"http://127.0.0.1:53334/v1/models\")); print([x.get(\"id\") for x in p.get(\"data\",[])])"
'
```

容器内没有 `jq`，不要把它加入 gate。不得由实验脚本自动启动、kill 或重启用户的 vLLM 服务。若 health check 失败：

1. 继续完成 deterministic/container tests；
2. 将 live E1-E5 标记为 `blocked_by_vllm_health`；
3. 保留 health 输出；
4. 不切换远端 API 或 deterministic model 冒充正式 live 结果。

### 8.5 GPU 映射

正式脚本沿用当前约定：

```text
STATEBUS_CUDA_VISIBLE_DEVICES=1  # 宿主物理 GPU
CUDA_VISIBLE_DEVICES=1           # 传入 docker exec 进程
STATEBUS_EMBED_DEVICE=cuda:0     # 容器进程内重编号后的设备
```

运行前用一个小 tensor probe 验证 CUDA，不仅调用 `nvidia-smi`。

### 8.6 已有 Adaptive wrapper

`scripts/v2_diagnostics/run_adaptive_formal_compare_gpu1.sh` 已包含：

- 容器激活；
- vLLM health；
- CUDA probe；
- bwrap/non-root readiness；
- focused tests；
- serialized formal run；
- mounted result root。

E5 优先复用并扩展该 wrapper，不复制第二套 Adaptive 启动逻辑。

### 8.7 本轮应新增的薄 wrapper

新增一个薄的 `scripts/v2_diagnostics/run_contest_evidence_closure_gpu1.sh`，只负责环境检查、容器参数、run root 和调用 Python 正式入口。业务逻辑必须留在 `v2/benchmark/`，不能写进 shell。

建议 stage：

```text
focused
causal
stress
adaptive-memory
semantic-holdout
full
```

默认只运行一个显式 stage；`all` 必须由调用者主动指定。建议调用方式：

```bash
STATEBUS_CONTEST_STAGE=focused bash scripts/v2_diagnostics/run_contest_evidence_closure_gpu1.sh
STATEBUS_CONTEST_STAGE=causal bash scripts/v2_diagnostics/run_contest_evidence_closure_gpu1.sh
STATEBUS_CONTEST_STAGE=stress bash scripts/v2_diagnostics/run_contest_evidence_closure_gpu1.sh
STATEBUS_CONTEST_STAGE=adaptive-memory bash scripts/v2_diagnostics/run_contest_evidence_closure_gpu1.sh
STATEBUS_CONTEST_STAGE=semantic-holdout bash scripts/v2_diagnostics/run_contest_evidence_closure_gpu1.sh
STATEBUS_CONTEST_STAGE=full bash scripts/v2_diagnostics/run_contest_evidence_closure_gpu1.sh
```

Python 正式入口应沿用 `v2.benchmark.live_runner` 的模式，增加必要参数，而不是另造平行 Runtime。目标命令形状：

```bash
python3 -m v2.benchmark.live_runner \
  --suite continuous \
  --benchmark-tier formal \
  --round-view causal_core \
  --role-path-mode local_vllm \
  --executor-mode deterministic_codeact \
  --embedding-mode local \
  --state-pool-mode shared_memory \
  --transport subprocess

python3 -m v2.benchmark.live_runner \
  --suite continuous \
  --benchmark-tier formal \
  --round-view long_horizon \
  --layer L3 \
  --role-path-mode local_vllm \
  --executor-mode deterministic_codeact \
  --embedding-mode local \
  --state-pool-mode shared_memory \
  --transport subprocess
```

`--round-view` 和 `--executor-mode` 是本轮应实现的新参数；continuous suite 的 `--transport subprocess` 也是本轮需要接通的现有 transport 扩展。在实现前不要把以上命令写成“当前已可执行”。

## 9. 容器内测试顺序

本节代码块展示的是进入容器并激活环境后的内部命令，不得直接复制到宿主 shell 执行。所有 stage wrapper 必须采用 `docker exec -u 0 ... bash -lc`，先 source `docker/activate_statebus_container.sh`，再执行这些命令。

测试默认静默运行：使用 `pytest -q`，将完整 stdout/stderr 重定向到本次 mounted run root 的 `pytest.log`/`console.log`，终端只输出 stage、PASS/FAIL、耗时和 artifact 路径。静默不等于吞掉错误；失败 traceback、退出码和失败 artifact 必须完整保留。

### 9.1 每个 Phase 后的 focused tests

Phase 1 后：

```bash
python3 -m pytest -q \
  tests/v2/test_adaptive_formal_compare.py \
  tests/v2/test_adaptive_role_prompts.py \
  tests/v2/test_continuous_runner.py \
  tests/v2/test_continuous_suite_schedule.py
```

Phase 2 后：

```bash
python3 -m pytest -q \
  tests/v2/test_hybrid_memory_query.py \
  tests/v2/test_replay.py \
  tests/v2/test_adaptive_dispatcher.py \
  tests/v2/test_adaptive_mainline_integration.py
```

Phase 3/4 后：

```bash
python3 -m pytest -q \
  tests/v2/test_continuous_task_family_loader.py \
  tests/v2/test_continuous_task_family_design.py \
  tests/v2/test_continuous_suite_schedule.py \
  tests/v2/test_retrieval_capability_routing.py \
  tests/v2/test_adaptive_structured_markdown_retrieval.py \
  tests/v2/test_embedding_state_consumer.py
```

按实际合同扩展上述文件；不要为了文件名与本文一致而建立空壳测试。

### 9.2 deterministic preflight

```bash
python3 -m v2.benchmark.live_runner \
  --suite preflight \
  --role-path-mode deterministic \
  --embedding-mode deterministic
```

### 9.3 live 运行顺序

严格按以下顺序串行：

1. E1 causal L0-L3；
2. E2 L3 long horizon；
3. E3 Adaptive memory；
4. E4 semantic holdout；
5. E5 fresh Adaptive 25-case；
6. E6 full regression + preflight。

任一阶段失败时先保留 artifact 和错误分类，修复后使用新 run ID 重跑该阶段及所有受影响下游阶段。不得覆盖失败 artifact。

### 9.4 最终 full gate

```bash
python3 -m pytest -q tests/v2
python3 -m v2.benchmark.live_runner \
  --suite preflight \
  --role-path-mode deterministic \
  --embedding-mode deterministic
```

最后再次记录：

```bash
cat /etc/os-release
python3 --version
bwrap --version
```

## 10. Artifact 和报告合同

每个正式 run root 至少包含：

```text
run_manifest.json
environment.json
fairness_manifest.json
capability_registry.json
case_reports/*.json
role_requests/*.json
state_consumption/*.json
memory_queries/*.json
memory_consumption/*.json
replay_decisions/*.json
artifact_lineage/*.json
summary.json
summary.md
pytest.log
console.log
checksums.sha256
```

`run_manifest.json` 必须记录：

- suite/stage/view/lane/order；
- git SHA 和 dirty flag；
- image ID/digest；
- model/embedding revision；
- registry/runtime/validator digest；
- source/task manifest hash；
- runtime/workspace/memory root；
- serial execution flag；
- start/end time 和 exit status。

报告按以下逻辑组织，不再混合 Gate 4 和 Gate 6：

1. 赛题问题与系统机制；
2. E1 L0-L3 单变量结果；
3. E2 10+10 稳定性；
4. E3 memory commit/match/consume/reject 漏斗；
5. E4 semantic/table route holdout；
6. E5 Adaptive DSL/CodeAct；
7. openEuler/container/sandbox 边界；
8. 负结果、限制和 Future Work。

## 11. 允许和禁止的最终表述

### 11.1 只有数据满足时可以写

- “在相同任务、角色、模型和 Executor 条件下，typed control 相比 matched text lane 减少了 X% 的 matched communication tokens/bytes。”
- “Qwen embedding matrix 经 shared-memory StateRef 在不同 PID 间传递，并通过数值 top-k 改变 selected evidence IDs 和 hydration。”
- “在两个连续 family 中，MemoryRef 经兼容性判断后被后续 Agent 实际消费，并产生 N 次行为改变/跳步。”
- “LLM 在冻结的六项 capability surface 内自然选择了 DSL 和 bounded Python，Python 全部经 bwrap 非 root 验证。”
- “冻结 Runtime 后，holdout 通过 manifest/schema 扩展完成，支持离线分析域内 bounded/configuration-level generalization。”
- “在 openEuler 24.03 LTS-SP3 单容器路径完成了本次 fresh regression 和实验。”

### 11.2 禁止写

- 把 25 次 memory query 写成 25 次 memory hit；
- 把 13 次 artifact reuse 写成 13 次 replay；
- 把 history step reduction 自动写成 LLM call reduction；
- 把 deterministic CodeAct 写成 LLM-generated CodeAct；
- 把 CodeAct 17/DSL 8 写成性能提升比例；
- 把 expected facts 参与的外部评分写成 Runtime 自主验证；
- 把 shared-memory embedding 写成 hidden-state/KV transfer；
- 把 root+bwrap 写成 production-grade sandbox；
- 把单容器结果写成 openEuler VM、跨机器或任意 Linux 全兼容；
- 把注册 capability 的权限边界写成开放工具生态；
- 把有限 operation/schema 支持写成开放域强泛化；
- 为了正向时延结果删除失败 run、并发 formal API 或挑选有利 case。

## 12. 完成定义

只有同时满足以下条件，本轮才算完成：

- Phase 1 的预解题、错误文案、role/executor 控制和 fairness audit 已修复；
- Adaptive memory 完成跨 task commit、load、match、consume、effect 和 reject；
- 两个 family 都有 `causal_core` 5 轮和 `long_horizon` 10 轮视图；
- E1-E5 全部生成新鲜、不可覆盖的容器 artifact；
- E1 四 lane 各 10/10，E2 两组各 10/10；
- semantic holdout 4/4，并自然覆盖 semantic/table；
- Adaptive 25/25，DSL/CodeAct 都有覆盖，CodeAct 全部 bwrap/non-root；
- memory 指标按 query -> candidate -> compatible -> consumed -> effect 分层；
- final `tests/v2` 和 preflight 通过；
- 报告明确给出所有负结果和 claim 边界；
- `docs/reports/README.md`、`docs/improvement/README.md` 和最终 evidence index 更新；
- 代码、测试、报告分阶段提交，工作树中不混入 run cache、模型、密钥或无关改动。

建议提交顺序：

1. `v2: harden contest lane fairness and truth boundaries`
2. `v2: close adaptive memory consumption loop`
3. `v2: add continuous task views and semantic holdout`
4. `test: add contest evidence closure gates`
5. `docs: report fresh contest evidence closure results`

最终答辩逻辑必须保持简单：

```text
L0 -> L1 证明结构化通信
L1 -> L2 证明非文本语义状态
L2 -> L3 证明共享记忆复用
10 + 10 L3 证明长期稳定
semantic holdout 证明 route 覆盖
Adaptive 25-case 证明 LLM Agent 的受控自主性和 CodeAct
```

这六条足以覆盖赛题，不需要继续堆叠能力或实验。

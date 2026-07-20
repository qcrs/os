# Adaptive 主链路与 Semantic State 收口计划

日期：2026-07-19；容器收口：2026-07-20
状态：已实施并完成 Gate 1-7（openEuler 容器路径）
适用分支：`feat/yzm-v2-migration`
基线提交：`e6f62de`（`v2: add adaptive agent and CodeAct runtime`）

## 0. 文档用途

这份文档是下一阶段的实施合同和执行 Prompt，目标不是继续增加概念、接口或实验矩阵，而是把已经存在的能力接入同一条真实主链路：

1. `Adaptive Agent / CodeAct`
2. typed Protobuf over UDS 控制面
3. `StateRef + shared_memory/mmap` Semantic State 数据面
4. Retriever、证据裁剪和局部 hydration
5. SQLite + FAISS 共享记忆
6. workspace + `ExecutionArtifactRef`
7. 两组连续任务和 10 轮稳定验证

本文同时固定：

1. 什么必须做；
2. 什么明确不做；
3. Agent 的真实职责和 CodeAct 选择边界；
4. embedding 如何成为被真实消费者使用的非文本中间状态；
5. Docker、root、GPU、目录和环境约束；
6. 精简后的测试集和静默执行规则；
7. 可直接交给实现 Agent 的完整 Prompt。

## 1. 起点事实

开始实施前必须保留以下事实，不得用旧报告覆盖：

1. 起点分支是 `feat/yzm-v2-migration`。
2. 起点提交是 `e6f62de`。
3. 在本计划编写前，工作树是干净的。
4. 提交前已有 `540 passed`，但本计划编写阶段没有重复运行全量测试。
5. fresh adaptive formal 已有串行 `25/25` 质量结果。
6. 该 `25/25` 证明 Adaptive Planner、DSL/CodeAct Executor 和 Summarizer 的模型执行质量已修复。
7. 该结果来自 adaptive formal 诊断装配入口，不能证明 adaptive 路径已经真实消费主 Runtime 的 StatePool、UDS 和 Memory。

### 1.1 本轮收口事实

本轮所有执行器、Runtime validator、StatePool/semantic consumer、bwrap 和 benchmark 测试均在 `statebus-dev-qcrs` openEuler 24.03 LTS-SP3 容器内完成。宿主机只负责启动容器、分配 GPU、重定向日志和读取摘要；formal role model 通过既有 vLLM HTTP endpoint 提供推理，不承担执行器或验证职责。

当前 fresh 证据覆盖：

1. Gate 6：25/25 attempted、completed、verified，quality 25/25，system-safety/high-accuracy/formal-enhancement 全部通过；
2. Gate 7：容器内 `516 passed, 100 warnings`，deterministic preflight `ok=true`；
3. Gate 4：两组正式离线 family 共 10 轮，semantic state transfer 9，artifact reuse 13，validated replay 2；
4. Gate 4 local embedding：Qwen3-Embedding-0.6B 的 `[4,1024]` binary matrix 由不同 PID 的 producer/consumer 通过 `shared_memory` 传递并数值消费。

任何后续报告都必须区分：

1. 旧的可信基线证据；
2. 当前工作树 fresh rerun；
3. deterministic 测试；
4. live model 串行测试。

## 2. 当前真正的问题

### 2.1 Adaptive 与主 Runtime 仍是两条装配路径

`RuntimeDriver.run_adaptive()` 已能执行 bounded adaptive DAG，但正式 handler、factory、retrieval adapter、CodeAct dispatcher 和输入对象主要仍由诊断脚本组装。`RuntimeDriver.run()` 则拥有 StatePool、Memory、workspace、UDS、persistence 和 replay 的既有严格路径。

问题不是 Adaptive Agent 没工作，而是：

1. Adaptive 质量链和系统基础设施链没有统一；
2. 诊断脚本承担了本应属于产品 Runtime 的装配职责；
3. Adaptive 结果不能自动证明 StateRef、Memory、UDS 和 artifact lifecycle 被真实使用；
4. strict/adaptive 两条路径继续演进会产生合同漂移和重复 bug。

### 2.2 当前 embedding 是“使用后发布”

现有流程大致是：

```text
Retriever 内部生成 query embedding
  -> Retriever 内部完成 cosine 排序
  -> Retriever 内部完成 evidence pruning
  -> embedding 转成 JSON UTF-8
  -> JSON bytes 写入 StatePool
  -> 发布 StateRef 并记录传递次数
```

因此目前同时存在四个真事实：

1. embedding 检索是真的；
2. evidence pruning 是真的；
3. StatePool materialization 是真的；
4. 但发布后的 embedding ref 没有成为下游数值决策的输入。

单纯 `STATE_PUBLISHED` 或把同一个 ref 附在消息上，不等于 `STATE_CONSUMED`。

### 2.3 当前 UDS worker 没有承载主要业务

现有 subprocess worker 能：

1. 接收 typed Protobuf frame；
2. 读取部分 memfd ref；
3. 发送 ACK、RUN_START、HEARTBEAT、SUCCESS 生命周期事件。

但它主要回传原 ref，没有执行核心 retrieval、semantic selection 或 CodeAct 业务。因此下一步不是增加更多空 worker，而是让至少一个真实业务消费者位于 worker 进程中。

### 2.4 当前 Memory 主链路没有融合三种检索

当前代码已经分别具备：

1. vector/FAISS lookup；
2. keyword/FTS lookup；
3. tag lookup。

但主 Runtime 的 MemoryQuery 主要只消费 vector lookup。关键词和标签路径存在，但没有形成一次统一的主链路查询。

### 2.5 当前连续任务约束过度收紧

赛题要求：

1. 至少两组关联性连续任务；
2. 系统稳定执行不少于 10 轮连续任务。

赛题没有要求每个 family 都有 10 轮。当前 loader 却要求每个 family `round_count >= 10`，runner 还维护 family ID 白名单，导致两组任务被放大成 20 轮和大量固定期待值。

## 3. 冻结决策

以下决策在本阶段不再重新讨论。

### 3.1 主线范围

只做三个 P0：

1. Adaptive/CodeAct 接入唯一主 Runtime；
2. embedding matrix 通过真实 StateRef 被跨进程消费者数值使用；
3. keyword + tags + vector 记忆检索进入一次 hybrid query。

P1 只做：

1. `EvidenceRequest.evidence_types` 真正控制 retriever fan-out；
2. 连续任务和测试矩阵精简；
3. 最终 formal/openEuler 验收。

### 3.2 非目标

本阶段明确不做：

1. KV cache、hidden state、activation 或跨模型 latent handoff；
2. 新增 Fusion Agent、Memory Agent、Evaluator Agent 等角色；
3. LLM reranker；
4. 任意未知自然语言任务的强泛化工程；
5. sealed holdout、多 seed 大矩阵、全后端乘全模型实验；
6. eBPF、WASM、nsjail 或新的容器编排扩展；
7. 把所有任务强制送入 CodeAct；
8. 把 embedding 直接放进 LLM prompt；
9. 用 case ID、公司名、expected facts 或答案关键词写 Runtime 分支；
10. 为了展示接口而增加没有 producer、consumer 和行为效果的对象。

KV 只保留以下定性：

```text
Engine-Local Prefix Reuse / Future Work
```

不得声称已经完成 KV tensor export 或跨 Agent 神经状态接力。

### 3.3 最低泛化边界

不追求无限任务泛化，但必须满足：

1. Planner 面对 capability registry、输入 schema、输出合同和 policy 做选择；
2. Runtime 不识别 benchmark case ID；
3. 新任务通过 `CanonicalTaskSpec + capability + input/output schema` 接入；
4. DSL/CodeAct 的选择由能力覆盖和 policy 决定；
5. task family 只提供数据、合同、依赖边和质量检查；
6. 不修改 Runtime 才能新增同类任务。

### 3.4 CodeAct 选择边界

不是所有任务都经过 CodeAct。

建议顺序固定为：

```text
已注册 deterministic DSL/tool 能满足合同
  -> 使用 DSL/tool

不存在匹配能力，但任务允许生成短 Python 且 sandbox policy 通过
  -> 使用 bounded CodeAct

两者均不满足
  -> 明确拒绝、请求一次受限 replan，或按既有 policy 失败
```

Planner 提出执行方式，plan policy 校验，Runtime 发放 capability grant。模型不能绕过 policy 直接获得工具、网络或文件权限。

## 4. 目标主链路

```text
CanonicalTaskSpec
  -> Task Compiler / Adaptive Envelope
  -> Planner
       输入：用户目标、capability surface、输出合同、允许的 memory assist refs
       输出：ApprovedPlan
  -> RuntimeDriver（唯一产品装配点）
       -> Retriever
            生成 query + candidate embedding matrix
            发布 DenseSemanticStateRef + HydrateManifest
       -> UDS typed control frame
            只传 action、grant、ref、timeout、contract version
       -> Executor-side Semantic Consumer worker
            解析 StateRef
            映射 float32 matrix
            cosine/top-k + budget pruning
            根据 locator 局部 hydrate EvidencePack
       -> MemoryProxy
            消费同一 query vector
            keyword + tags + vector 候选融合
            compatibility/replay gate
       -> Executor
            DSL 或 bounded CodeAct
            输入仅为 verified evidence/artifact，不接收裸向量
            输出 ExecutionArtifactRef
       -> Summarizer
            生成 ClaimSet / 目标输出合同
       -> quality floor
       -> memory candidate commit / replay ledger
       -> lifecycle cleanup
```

关键规则：

1. 诊断脚本只能做 CLI 参数解析和报告落盘，不能继续拥有正式 Runtime handler 装配逻辑。
2. strict 和 adaptive 可以保留不同 workflow policy，但必须复用相同的 StatePool、MemoryProxy、UDS transport、workspace、artifact、telemetry 和 cleanup 基础设施。
3. `ExecutionArtifactRef` 与 `SemanticStateRef` 始终是不同 ref family。
4. Planner 不读取 corpus facts，也不把答案复制进 plan。
5. CodeAct 只消费经过验证和局部 hydrate 的输入。

## 5. Agent 与基础设施职责

| 组件 | 必须真正承担的职责 | 不应承担的职责 |
|---|---|---|
| Planner | 根据目标、能力和合同生成 bounded plan；选择已注册 DSL/tool 或申请 CodeAct；必要时一次受限 replan | 读取 gold answer、按 case ID 路由、直接访问 corpus、授予自身权限 |
| Retriever | 按 EvidenceRequest 执行所需检索；生成 query/candidate embedding matrix、locator manifest 和候选 refs | 固定对所有任务执行全部 retriever；把完整文档塞给 LLM |
| Executor | 消费 verified evidence/artifact；执行 DSL 或受限 CodeAct；生成独立 artifact | 直接消费浮点向量文本；自行扩大文件、网络或工具权限 |
| Summarizer | 基于 claims、evidence 和 artifact 满足输出合同；生成可验证 memory candidate | 重新执行检索/计算；从 expected facts 补答案 |
| Runtime Supervisor | dispatch、lease、ACK、heartbeat、cancel、retry、GC、policy、telemetry | 替 Agent 写任务答案；按数据集名称硬编码路线 |
| MemoryProxy | hybrid retrieval、兼容性过滤、assist/strategy/replay 分级、单写提交 | 作为额外 LLM Agent；只返回历史问题而不返回可复用对象 |
| StatePool | 短命 dense state materialization、ref resolution、hash 和生命周期 | 决定业务语义；把 JSON 文本伪装成 dense state |

`MemoryProxy`、StatePool、fan-in 和 context adapter 是系统组件，不新增成赛题 Agent。多 Agent 仍保持 `Planner / Retriever / Executor / Summarizer`。

## 6. P0-A：Adaptive 接入唯一主 Runtime

### 6.1 实施步骤

1. 审计 `scripts/v2_diagnostics/run_adaptive_formal_compare.py` 中的正式 factory 和 handler 装配。
2. 将可复用装配移动到 `v2/runtime/` 所有的产品入口；只有确实减少重复时才新增小型 builder/context 对象。
3. 让 adaptive request 获得与 strict request 同一套：
   - StatePool；
   - Memory store/proxy；
   - UDS transport；
   - workspace manager；
   - artifact registry；
   - persistence；
   - telemetry；
   - cleanup。
4. 保持 `RuntimeDriver.run()` 现有 strict 行为兼容；不要用大范围重写破坏历史测试。
5. 收敛正式产品入口，使 normal Runtime 能显式选择：
   - `strict_fixed`；
   - `adaptive_bounded`；
   - 必要时保留 `adaptive_shadow` 作为审计模式。
6. 将 diagnostics runner 改成调用产品入口，不再在脚本里构造另一套 Runtime。
7. 确认每个完成步骤都有真实 dispatch、input refs、output refs 和 validator 记录。

### 6.2 验收标准

1. Adaptive formal case 从产品 Runtime 入口执行，而不是诊断脚本私有链。
2. 同一个 run bundle 中能看到 Planner、Retriever、Executor、Summarizer 的真实 step 记录。
3. DSL 和 CodeAct 都能由 capability/policy 选择；不要求固定为历史 `19/6` 分布。
4. full 25-case 时至少存在一条 verified CodeAct 证据，但不能为满足计数强制改 plan。
5. 没有 model fallback、sandbox fallback、未授权工具或 infrastructure failure。
6. strict path 既有行为和测试保持通过。
7. diagnostics script 删除装配职责后仍能生成原有 summary/report。

### 6.3 Planner rejection 口径

Planner rejection 本身不必然是 bug，必须按原因拆分：

1. `unsafe_or_out_of_scope`：请求越权、不安全或超出允许能力，拒绝是正确行为；
2. `capability_missing`：能力表确实不存在所需能力，拒绝或请求受限 replan 是正确行为；
3. `invalid_contract`：任务输入/输出合同本身不合法，fail closed 是正确行为；
4. `schema_parse_or_normalization_failure`：合法任务因模型格式漂移被拒绝，属于模型/adapter 质量问题；
5. `policy_false_reject`：合法、可执行且能力存在的 formal case 被 policy 拒绝，属于系统 bug。

fresh formal 报告必须同时给出 hard rejection、schema repair、policy repair 和最终 approved 数量。对于 registry 中 25 个合法 formal cases，目标是：

1. hard rejection 为 0；
2. schema/policy repair 可以非零，但必须有界、可审计且最终批准；
3. 不通过在 prompt 中加入 case-specific 示例来消除拒绝。

### 6.4 Agent Prompt 合同

Planner、CodeAct 和 Summarizer prompt 必须从当前请求、上文合同和已授权 refs 构造：

1. Planner 输入只包含用户目标、`CanonicalTaskSpec` 的允许语义字段、capability registry、policy 和输出合同；
2. Planner 不看到 expected facts、gold answer 或 corpus 中的答案正文；
3. CodeAct 输入只包含当前 step goal、operation semantics、verified input schema/artifact、completion criteria 和 sandbox policy；
4. CodeAct prompt 不包含 case ID 到算法的映射，也不包含目标数据集专用答案模板；
5. Summarizer 只消费 verified claims/evidence/artifact 和输出合同，不从 expected facts 补字段；
6. role prompt、输出合同模板和固定工具规则必须进入 prompt bundle digest；
7. prompt 中可以有通用 schema 示例，但不能使用 formal case 的公司名、数值或答案作为 few-shot。

任何为了修复单个 case 而新增的提示词，都必须先说明它对应的通用失败类别，并至少用另一任务 family 验证同一修复。

## 7. P0-B：真实非文本 Embedding State

### 7.1 选择 embedding，而不是 KV

赛题明确允许 embedding/语义向量作为非文本中间状态。当前主线选择 embedding matrix，因为它：

1. 与检索、裁剪、hydration 和记忆召回直接相关；
2. 不绑定具体 LLM 推理引擎；
3. 可以由 NumPy/FAISS 直接消费；
4. 可以明确验证 producer、transport、consumer 和行为效果；
5. 比 KV 更适合当前单容器多进程原型。

### 7.2 正式 producer 和 consumer

Producer：`Retriever`。

Retriever 生成：

1. query embedding；
2. 候选 evidence embeddings；
3. query + candidate 的连续 embedding matrix；
4. row index 到 candidate ID/source locator 的 `HydrateManifest`。

Consumer：

1. Executor-side context adapter/semantic consumer worker：执行 cosine/top-k、预算裁剪和局部 hydration；
2. `MemoryProxy`：读取 query row，执行 FAISS/vector memory lookup。

CodeAct LLM 不是 embedding consumer。它只接收 consumer 产出的 verified EvidencePack 和 artifact。

### 7.3 Binary payload 合同

数据面 payload 使用连续、C-order、小端 `float32` matrix。首版不做 float16/int8 量化。

建议布局：

```text
row 0      query embedding
row 1..N   candidate embeddings
```

向量 payload 中不放字符串、JSON、candidate ID 或 locator。它们进入 ref/manifest 元数据。

`SemanticStateRef` 或其 manifest 至少包含：

```text
schema_version
state_id
state_kind = DENSE_SEMANTIC_STATE
storage_kind
dtype = float32
byte_order = little
shape = [N + 1, dims]
row_layout = query_then_candidates
normalized = true
encoder_id
encoder_revision / encoder_signature
source_text_hashes or source_doc_hashes
hydrate_manifest_id
blob_hash
size_bytes
owner_session_id
lease/expiry metadata
```

约束：

1. `size_bytes == rows * dims * 4`；
2. query、candidate 和 memory index 必须使用相同 encoder signature、维度和归一化约定；
3. 非 finite 数值、长度、hash、schema 或 encoder 不匹配时 fail closed；
4. JSON canonical payload 可以保留作审计 sidecar，但不能作为正式 dense payload；
5. 不把 naked bytes 当完整合同；dtype/shape/model metadata 是必要组成。

### 7.4 传输与解析

1. 控制面继续使用 length-prefixed typed Protobuf over UDS。
2. 控制帧只携带 operation、grant、`RefHandle`、manifest ID、timeout 和 contract version。
3. dense payload 默认放 `shared_memory`；预算超限或平台不可用时按既有 policy 回退到 `mmap`。
4. consumer 通过 registry/metadata resolver 打开 state，不能依赖 producer 进程内 `materializations` dict。
5. consumer 使用 `numpy.ndarray(..., buffer=...)` 或 `numpy.frombuffer()` 建立只读数值视图。
6. producer 创建并负责 unlink；consumer 只 close；Runtime 在 ACK、terminal、timeout 和 cancel 路径统一清理。
7. 如果扩展 Protobuf 消息，必须与真实 consumer handler、集成测试在同一改动中落地，禁止先留空接口。

### 7.5 与现有裁剪的关系

保留现有两层逻辑，不新增算法：

1. embedding cosine/top-k：选择语义相关 evidence；
2. dynamic budget pruning：根据重要度和可用预算进一步过滤，同时保护 hard facts/structured evidence。

需要改变的是执行边界：

```text
之前：Retriever 进程内排序和裁剪 -> 事后发布 ref
之后：Retriever 发布 matrix ref -> consumer 读取 matrix -> 排序/裁剪/hydrate
```

对于精确 CSV/table 任务，如果 EvidenceRequest 不需要 semantic evidence，就不生成或传递 embedding matrix。不得为了计数强制所有任务经过 semantic path。

### 7.6 Telemetry 语义

必须拆分：

1. `STATE_PUBLISHED`：producer materialize 成功；
2. `STATE_RESOLVED`：consumer 成功解析并校验 ref；
3. `STATE_CONSUMED`：consumer 完成数值操作；
4. `STATE_RELEASED`：owner 完成回收。

`semantic_state_transfer_count` 只能在真实跨角色/进程传递成功后增加。建议另记：

1. `semantic_state_publish_count`；
2. `semantic_state_consume_count`；
3. `semantic_state_bytes`；
4. `semantic_state_consumer_pid`；
5. `selected_candidate_count`；
6. `raw_evidence_bytes_seen_by_llm`。

不再为 Retriever、Executor、Summarizer 批量生成没有真实 read 的 `STATE_HYDRATED` 事件。

### 7.7 验收标准

1. dense payload 长度等于 matrix 元素数乘 4，不是 UTF-8 JSON vector。
2. integration test 中 producer PID 与至少一个 consumer PID 不同。
3. consumer 从 ref/registry 打开 shared memory 或 mmap，而不是接收 Python tuple。
4. state path 与同一 encoder 的 in-process reference path 得到一致 top-k/score tolerance。
5. consumer 产生 selected IDs，并实际决定 hydrate 的 EvidencePack。
6. MemoryProxy 使用同一 query row 完成 vector lookup，不重复编码同一 query。
7. missing、expired、corrupt、wrong shape、wrong encoder ref 全部明确报错并清理。
8. CodeAct request 中不存在 embedding vector 或向量 JSON。
9. deterministic 单测使用 16 维 encoder；formal 使用本地 Qwen embedding，不允许 silent fallback 到 deterministic。

## 8. P0-C：Hybrid MemoryQuery

### 8.1 查询合同

一次 MemoryQuery 至少包含：

```text
query_task_id
query_spec_hash
query_text / normalized task intent
tags
query_embedding_ref
limit
allowed_memory_types
allow_assist
allow_validated_replay
allow_exact_replay
compatibility signature / scope
```

embedding 用于召回，不进入 exact replay key。

### 8.2 索引什么，返回什么

主向量检索文本应由以下稳定字段组成：

1. task theme；
2. normalized intent；
3. tags；
4. 简短 summary。

不要把完整最终答案或 expected facts 作为主要 query key。命中后可以返回：

1. assist summary；
2. strategy；
3. evidence ref；
4. verified artifact ref；
5. replay metadata。

因此设计语义是：

```text
按当前问题/任务意图检索
  -> 找到适用的历史记忆
  -> 再读取记忆中的答案、证据、策略或 artifact
```

### 8.3 融合算法

首版不增加 LLM reranker。使用确定性 rank-only RRF：

1. keyword/FTS 产生有序候选；
2. tag lookup 产生有序候选；
3. vector/FAISS 产生有序候选；
4. 按 memory ID 去重；
5. 使用固定 RRF 常数融合；
6. 相同分数按 memory ID 稳定排序；
7. 融合后再经过 compatibility/replay gate。

不要直接混加 BM25、tag overlap 和 cosine 原始分数，因为三个分数空间不可直接比较。

### 8.4 复用等级

1. `assist`：历史摘要或证据作为上下文，仍重新执行；
2. `strategy`：复用方法、代码模板或工具方案；
3. `validated_replay`：兼容性通过后复用旧产物，但仍执行必要校验；
4. `exact_replay`：只在 canonical spec、输入 hash、runtime signature 和输出合同严格等价时跳步。

### 8.5 验收标准

1. 主 Runtime 对一次任务只发起一个 hybrid MemoryQuery。
2. 三个候选源至少能在集成测试中各自贡献候选。
3. 去重和 RRF 结果稳定、可复现。
4. compatibility gate 在融合之后执行，并能排除高相似但不兼容的记忆。
5. assist 命中不能被误报为 skipped step/reuse gain。
6. exact replay 不能由 embedding 相似度单独触发。
7. 返回对象包含真正可复用的 summary/strategy/evidence/artifact，而不是只有旧问题文本。

## 9. P1：Retriever 选择真正影响执行

当前 lexical、semantic、table 三路不应对每个任务固定全部执行。

实施要求：

1. `EvidenceRequest.evidence_types` 和 capability grant 决定启用哪些 retriever；
2. table/明确字段任务优先 table + metadata；
3. 长文档 narrative 任务使用 semantic + lexical，必要时增加 table；
4. memory 使用 hybrid MemoryQuery，不混进文档 fan-out；
5. fan-in 保持 deterministic；
6. rerank/selection 必须真正决定 selected set，而不是只给已经全选的候选重新计分；
7. hard facts 和 structured evidence 保持保护规则；
8. 不增加 LLM reranker。

验收时必须能观察：

1. 不同 EvidenceRequest 导致不同 retriever dispatch 集合；
2. 未请求的 retriever 没有调用和模型开销；
3. selected IDs 由 consumer/rerank 决定；
4. 最终质量 floor 不下降。

## 10. P1：连续任务与实验精简

### 10.1 任务设计

保留两组 offline 财报/经营指标任务。每组只保留 2 至 3 种核心任务关系，通过不同输入实例组织成总计 10 次连续执行。

建议：

```text
组 A：CSV / operating metrics
  A1 schema/profile
  A2 derived metric / comparison，依赖 A1
  A3 anomaly/quality artifact，依赖 A1/A2

组 B：financial report / long document
  B1 metric/evidence index
  B2 narrative/trend retrieval，依赖 B1
  B3 risk memo，依赖 B1/B2
```

10 次执行建议使用输入变体，而不是精确重复：

```text
A1 -> A2 -> A3 -> B1 -> B2 -> B3 -> A1' -> A2' -> B1' -> B2'
```

`'` 表示不同公司、期间或 repo-local 数据文件，并使用唯一 task/execution ID。

### 10.2 Runner 调整

1. family 最少 2 个相关 round，不再要求每个 family 至少 10 round；
2. collection 至少包含 2 个 family；
3. collection/suite 总执行数至少 10；
4. 移除 family ID 硬编码白名单，改为 schema、capability 和 input contract 校验；
5. 更新固定期待 10/20 轮的测试和 replay audit 计数；
6. 不引入复杂 task template engine；现有 manifest 能表达时，使用显式参数化 round；
7. reuse 只统计 manifest 声明的依赖边；
8. 稳定执行率和 memory/replay 收益分开报告。

### 10.3 防止伪收益

1. 不用完全相同输入的 exact repeat 冒充关联任务复用；
2. fresh quality run 使用全新 runtime/memory root；
3. family 内可以共享声明的历史，family 间默认隔离，除非合同明确允许；
4. assist hit 不等于计算减少；
5. 只有 artifact reuse、history step reduction 或 replay skipped steps 才计真实复用收益；
6. 不把 10 轮成功执行直接写成 memory gain。

### 10.4 删除或停止扩展的实验

1. sealed genericity holdout；
2. 多 seed 大模型质量矩阵；
3. state on/off/corrupt 的大规模反事实矩阵；
4. 所有 StatePool 后端乘所有 LLM 后端；
5. 两条各 10 轮的冗长重复 family；
6. KV/prefix 大矩阵。

保留的正式证据只有：

1. 同任务 text vs typed protocol/ref；
2. 一个真实跨进程 embedding producer/consumer；
3. 一个 hybrid memory 连续任务 collection；
4. 一次 fresh 25-case Adaptive/CodeAct 质量测试；
5. 一次 openEuler 容器交付 smoke。

## 11. Docker、root 与目录约束

### 11.1 固定目录

| 用途 | 路径 |
|---|---|
| 宿主机项目根 | `/home/qcrs/statebus/project` |
| 容器项目根 | `/workspace/statebus/project` |
| 容器 StateBus 根 | `/statebus` |
| 模型 | `/statebus/models` |
| 缓存 | `/statebus/caches` |
| 测试/benchmark 输出 | `/statebus/runs/<run_id>` |
| runtime 临时工作 | `/statebus/work/<run_id>` |
| task workspace | `/statebus/work/workspaces/<run_id>` |
| StatePool | `/statebus/work/statepool/<run_id>` |
| 短 UDS 路径 | `/tmp/statebus-<run_id>.sock` 或 transport 的 bounded fallback |

正式运行产物不要写回源码目录。不要把新 evidence bundle 默认写进仓库的历史 `runs/` 目录。

### 11.2 镜像和用户

1. 使用 `docker/compose.yaml` 的单服务 `statebus-dev-qcrs`。
2. 基础镜像必须是 openEuler 24.03-LTS-SP3。
3. semantic/formal 测试统一使用 `STATEBUS_DOCKER_TARGET=embed`。
4. 容器 Runtime/test harness 按现有合同使用 root：`docker exec -u 0`。
5. root 只用于容器装配、挂载、GPU 和 bwrap 外壳。
6. CodeAct 生成代码必须在 bwrap 内以非 root UID/GID 执行；readiness 检查必须验证 sandbox UID/GID 非 0。
7. 不允许用 root 身份绕过 bwrap 直接执行 LLM 代码。
8. 尽量在宿主机用户环境编辑源码，避免容器 root 在 bind mount 中制造 root-owned 源文件。
9. 容器测试设置 `PYTHONDONTWRITEBYTECODE=1`，日志和临时目录写入 `/statebus`。

### 11.3 启动命令

宿主机：

```bash
cd /home/qcrs/statebus/project

export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
export STATEBUS_DOCKER_TARGET=embed
export STATEBUS_DOCKER_RUNTIME=nvidia
export STATEBUS_NVIDIA_VISIBLE_DEVICES=all

docker compose -f docker/compose.yaml build statebus-dev
docker compose -f docker/compose.yaml up -d statebus-dev
docker inspect --format '{{.State.Running}}' statebus-dev-qcrs
```

进入容器：

```bash
docker exec -it -u 0 statebus-dev-qcrs bash
source /workspace/statebus/project/docker/activate_statebus_container.sh
cd /workspace/statebus/project
```

容器内检查：

```bash
test "$(id -u)" = "0"
test "$PWD" = "/workspace/statebus/project"
test "$STATEBUS_HOME" = "/statebus"
test -d /statebus/models/Qwen3-Embedding-0.6B
python3 --version
python3 -c 'import numpy, faiss, torch, sentence_transformers; print("embed stack ok")'
python3 scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py
```

### 11.4 GPU 约束

1. 不自行占用未分配 GPU；先用 `nvidia-smi` 核对。
2. 物理 GPU 通过 `CUDA_VISIBLE_DEVICES` 显式指定。
3. 容器内映射后的 embedding device 通常使用 `cuda:0`。
4. vLLM 与 embedding worker 的 GPU 不能靠猜测共享；按现有部署显式分配。
5. deterministic tests 不要求 GPU。
6. local embedding/formal tests 缺少模型或 CUDA 时必须报错，不得 silent fallback。

### 11.5 配置和秘密

1. LLM 配置来自 `deploy/statebus_llm.yaml.local`；
2. API secret 来自 `deploy/statebus_llm.env.local`；
3. 不输出、不提交、不复制 secret；
4. 不在测试日志记录完整请求 header 或 API key；
5. formal API timing 只能串行运行，不能并发启动多个 case runner 当正式延迟证据。

## 12. 静默测试协议

### 12.1 用户交互规则

测试开始前只报告一次：正在运行哪个 gate、日志目录在哪里。

测试运行期间：

1. 不持续输出 pytest case；
2. 不 `tail -f`；
3. 不用 `tee` 把完整日志流到终端；
4. 不发送周期性“仍在运行”消息；
5. 工具返回 session/cell ID 时，继续 wait，直到进程完成或报错；
6. 不把长测试放到后台后结束当前工作；
7. 不并行启动 live API/formal timing 测试。

测试结束后只返回：

1. PASS/FAIL；
2. exit code；
3. 关键计数；
4. 日志和 summary 路径。

失败时额外返回最后不超过 80 行相关错误，不倾倒完整日志。

### 12.2 推荐静默包装

在宿主机执行：

```bash
RUN_ID="adaptive_mainline_$(date +%Y%m%d_%H%M%S)"
HOST_LOG_ROOT="$HOME/statebus/runs/$RUN_ID"
mkdir -p "$HOST_LOG_ROOT"

run_quiet() {
  stage="$1"
  shift
  log="$HOST_LOG_ROOT/$stage.log"
  if "$@" >"$log" 2>&1; then
    printf '[PASS] %s log=%s\n' "$stage" "$log"
  else
    status=$?
    printf '[FAIL] %s exit=%s log=%s\n' "$stage" "$status" "$log" >&2
    tail -n 80 "$log" >&2 || true
    return "$status"
  fi
}
```

示例：

```bash
run_quiet focused-v2 \
  docker exec -i -u 0 \
    -e PYTHONDONTWRITEBYTECODE=1 \
    statebus-dev-qcrs bash -lc '
      source /workspace/statebus/project/docker/activate_statebus_container.sh
      cd /workspace/statebus/project
      python3 -m pytest -q \
        tests/v2/test_state_materialization.py \
        tests/v2/test_control_plane.py \
        tests/v2/test_uds_loopback.py \
        tests/v2/test_retrieval_pipeline.py \
        tests/v2/test_dynamic_pruning.py \
        tests/v2/test_memory_store.py \
        tests/v2/test_memory_runtime.py \
        tests/v2/test_adaptive_driver.py \
        tests/v2/test_adaptive_dispatcher.py \
        tests/v2/test_adaptive_codeact_integration.py
    '
```

实现阶段新增的测试文件也必须加入 focused gate。

## 13. 测试层级

必须按顺序执行。上一层失败时停止，不继续烧 live model 成本。

### Gate 1：Focused deterministic

覆盖：

1. embedding binary codec round-trip；
2. state metadata/hash/shape 校验；
3. cross-process state resolve；
4. UDS typed request/result；
5. semantic top-k 与 pruning；
6. hybrid memory RRF；
7. Adaptive mainline wiring；
8. DSL/CodeAct policy；
9. lifecycle cleanup。

建议新增或扩展：

```text
tests/v2/test_embedding_state_codec.py
tests/v2/test_embedding_state_consumer.py
tests/v2/test_adaptive_mainline_integration.py
tests/v2/test_hybrid_memory_query.py
tests/v2/test_retrieval_capability_routing.py
tests/v2/test_continuous_suite_schedule.py
```

测试名是建议，若现有测试文件更合适，应扩展现有文件，避免无意义拆分。

### Gate 2：全部 v2 regression

```bash
python3 -m pytest -q tests/v2
```

目标：不低于基线覆盖，全部通过。报告 fresh 数量，不机械写死为 540，因为新增测试后计数会变化。

### Gate 3：deterministic preflight/formal

```bash
python3 -m v2.benchmark.live_runner \
  --suite preflight \
  --role-path-mode deterministic \
  --embedding-mode deterministic

python3 -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier formal \
  --role-path-mode deterministic \
  --embedding-mode deterministic
```

### Gate 4：真实 StateRef 和连续任务

```bash
python3 -m v2.benchmark.live_runner \
  --suite continuous \
  --role-path-mode deterministic \
  --embedding-mode deterministic \
  --state-pool-mode shared_memory
```

必须额外保留一条真实跨进程 local embedding integration，不得只靠 deterministic Python tuple 测试。

### Gate 5：bwrap readiness

```bash
python3 scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py
```

必须验证：

1. actual backend 为 bwrap；
2. sandbox UID/GID 非 0；
3. no-network、workspace allowlist、timeout 和输出扫描仍有效。

### Gate 6：fresh 25-case 串行质量

从宿主机使用现有 wrapper；wrapper 在本阶段结束时必须已经变成主 Runtime 的薄入口：

```bash
export STATEBUS_CUDA_VISIBLE_DEVICES=<明确分配的物理 GPU>
export STATEBUS_EMBED_DEVICE=cuda:0
export STATEBUS_ADAPTIVE_FORMAL_MAX_CASES=25
export STATEBUS_ADAPTIVE_FORMAL_LANE=adaptive
export STATEBUS_ADAPTIVE_FORMAL_EXIT_GATE=high-accuracy
export STATEBUS_ADAPTIVE_FORMAL_QUALITY_THRESHOLD=0.80

bash scripts/v2_diagnostics/run_adaptive_formal_compare_gpu1.sh
```

验收：

1. attempted/verified execution 为 25/25；
2. system safety gate 通过；
3. infrastructure failure 为 0；
4. model/sandbox fallback 为 0；
5. high-accuracy gate 至少 80%；
6. 目标仍是恢复或保持 25/25，但不得通过任务特化达到；
7. 汇报 DSL/CodeAct 实际分布，不把历史 `19/6` 写成硬编码门。

### Gate 7：openEuler 交付 smoke

确认当前容器 OS 和最终入口：

```bash
cat /etc/os-release
python3 -m pytest -q tests/v2
python3 -m v2.benchmark.live_runner --suite preflight \
  --role-path-mode deterministic --embedding-mode deterministic
```

只有在该容器路径 fresh 通过后，才能声称 openEuler 容器验证通过；不能由宿主机测试推断。

## 14. 精简后的正式指标

### 14.1 系统正确性

1. task attempted/completed/failed；
2. role step count；
3. planner rejection/repair；
4. DSL/CodeAct verified count；
5. sandbox/system fallback；
6. quality pass count/rate。

### 14.2 控制面

1. message count；
2. protocol bytes；
3. text chars/tokens；
4. timeout/retry/error count。

### 14.3 Semantic State

1. publish/resolve/consume/release count；
2. state bytes；
3. storage backend；
4. producer/consumer role 和 PID；
5. selected candidate count；
6. raw evidence bytes seen by LLM；
7. embedding encode count。

### 14.4 Memory

1. keyword/tag/vector candidate count；
2. fused/selected count；
3. assist/strategy/replay 分类；
4. artifact reuse count；
5. skipped step count；
6. reuse gain。

性能结论约束：

1. quality floor 未通过时不比较性能 headline；
2. shared memory 对单个小向量可能没有延迟优势，不预设结论；
3. 真实价值优先看重复编码减少、无文本向量序列化、批量 matrix 多消费者和 evidence ingress 减少；
4. API latency 只使用串行 rerun。

## 15. 文件影响地图

优先检查而不是机械全部修改：

| 工作包 | 主要文件 |
|---|---|
| 主 Runtime 接入 | `v2/runtime/driver.py`、`adaptive_runtime.py`、`adaptive_dispatcher.py`、`smoke.py`、diagnostics runner |
| binary embedding | `v2/memory/models.py`、`embedding.py`、`v2/state/store.py`、`v2/refs/models.py`，必要时新增小型 codec |
| 跨进程 consumer | `v2/control/statebus_v2.proto`、`messages.py`、`transport.py`、worker harness、state resolver |
| pruning/hydration | `v2/retrieval/pipeline.py`、`pruning.py`、`v2/provenance/hydration.py` |
| hybrid memory | `v2/memory/store.py`、`models.py`、Runtime memory query wiring |
| retriever routing | retrieval adapter、EvidenceRequest、capability registry/dispatcher |
| continuous suite | `continuous_task_family.py`、`continuous_runner.py`、`live_runner.py`、sample manifests |
| tests | 现有相关 `tests/v2/`，必要时增加第 13 节测试 |

不要修改顶层 v1 `runtime/ protocol/ statepool/ memory/ eval`，除非发现 v2 明确复用且无法隔离的真实阻塞；遇到这种情况先说明影响。

## 16. 分阶段提交顺序

建议按可独立验证的顺序实施，不做一个巨型改动：

1. Runtime-owned adaptive assembly + wiring tests；
2. embedding binary codec/ref metadata + unit tests；
3. cross-process semantic consumer + lifecycle tests；
4. Retriever/MemoryProxy 真消费 + pruning/hydration integration；
5. hybrid MemoryQuery + replay gate tests；
6. EvidenceRequest retriever routing；
7. continuous runner/schema 精简；
8. docs、telemetry 和最终 gates。

每一步都必须保持 strict path 可运行。不要在中间阶段通过大范围 skip 或降低 quality floor 保绿。

## 17. 完成定义

只有同时满足以下条件，任务才算完成：

1. Adaptive formal 使用产品 Runtime 装配；
2. StatePool、UDS、Memory、workspace 和 artifact 位于同一 adaptive 主链；
3. embedding 数据面是 binary matrix，不是 JSON vector；
4. 至少一个真实不同 PID 的 consumer 数值使用 state；
5. consumer 的 selected IDs 实际影响 EvidencePack/hydration；
6. CodeAct 不直接消费 embedding；
7. Memory 主链使用 hybrid query；
8. retriever fan-out 受 EvidenceRequest 控制；
9. 两组关联任务总计稳定执行至少 10 次；
10. focused、full v2、deterministic、continuous、bwrap、fresh 25-case、openEuler smoke 按层通过；
11. 所有测试均静默等待到完成或报错；
12. 文档诚实区分已实现、已验证和 Future Work；
13. 没有 case/task-set 特化；
14. 工作树中没有无关格式化、生成物或用户修改被回退。

### 17.1 2026-07-20 直接证据矩阵

下表是本轮完成判断的直接证据，不把历史 `core` 容器结果当作当前 `embed` 容器结果。路径均为宿主机挂载目录；对应执行发生在容器内。

| # | 完成条件 | 直接证据 | 状态 |
|---:|---|---|---|
| 1 | Adaptive formal 使用产品 Runtime 装配 | Gate 6 fresh summary 的 25 个 case 均为 `workflow_mode=adaptive_bounded`，含 Runtime session/dispatch、四个 role 和最终 artifact；实现入口为 `v2/runtime/adaptive_mainline.py`。 | PASS |
| 2 | StatePool、UDS、Memory、workspace、artifact 在同一 adaptive 主链 | Gate 6 每例 summary 的 `runtime_dispatches`、`state_consumption_records`、`claim_sets`、`execution_records` 和 workspace/runtime manifest；Gate 4 report 另观测到 10 次 hybrid MemoryQuery。 | PASS |
| 3 | embedding 数据面是 binary matrix | [`gate4_continuous_local_embedding.log`](/home/qcrs/statebus/runs/adaptive_mainline_20260719/embed_target_validation_20260720/gate4_continuous_local_embedding.log) 记录 Qwen matrix `shape=[4,1024]`、`size_bytes=16384`、`storage_kind=shared_memory`；codec/metadata 测试在 Gate 7 全量通过。 | PASS |
| 4 | 至少一个真实不同 PID 的 consumer 数值使用 state | 同一 local embedding log 记录 `producer_pid=43533`、`consumer_pid=45180`、`query_row_reused_without_encode=true` 和 `owner_release_verified=true`。 | PASS |
| 5 | selected IDs 实际影响 EvidencePack/hydration | local embedding log 记录 `selected_row_indices=[1,2]`、`selected_candidate_ids` 和 `selected_evidence_bytes=110`；Gate 4 family reports 同时记录 semantic selection 与 hydration accounting。 | PASS |
| 6 | CodeAct 不直接消费 embedding | `tests/v2/test_adaptive_mainline_integration.py`、`tests/v2/test_embedding_state_consumer.py` 的输入边界断言，加上 Gate 6 CodeAct execution records 与 prompt/request audit；向量只在 consumer/MemoryProxy 侧使用。 | PASS |
| 7 | Memory 主链使用 hybrid query | `tests/v2/test_hybrid_memory_query.py` 验证 keyword/tag/vector 三路和稳定 RRF；Gate 4 两个 L3 report 各执行 5 次 `hybrid_memory_query`，并通过 compatibility/replay gate。 | PASS |
| 8 | retriever fan-out 受 EvidenceRequest 控制 | `tests/v2/test_retrieval_capability_routing.py` 与 Gate 7 全量回归覆盖 requested/unrequested dispatch 和 deterministic fan-in。 | PASS |
| 9 | 两组关联任务稳定执行至少 10 次 | Gate 4 report：2 families、`continuous_round_count=10`、两组均成功；quality headline eligible，financial family 的 validated replay 目标 2/2 通过。 | PASS |
| 10 | focused/full/deterministic/continuous/bwrap/fresh-25/openEuler 分层通过 | Gate 1 composite、Gate 2 `513 passed`、Gate 3 formal `25/25`、Gate 4、Gate 5、Gate 6 `25/25`、Gate 7 `516 passed` 的日志索引见验证报告。 | PASS |
| 11 | 测试静默等待到完成或报错 | 每个 gate 均使用重定向日志和持有 session/cell 的等待；Gate 6 wrapper 与 Gate 7 log 均以完成摘要结束，没有并发 live case。 | PASS |
| 12 | 文档诚实区分实现/验证/Future Work | 本计划本节矩阵与验证报告的“声明边界/Future Work”明确保留 `Engine-Local Prefix Reuse`、outer-container root 和 VM posterior validation 限制。 | PASS |
| 13 | 无 case/task-set 特化 | Gate 6 覆盖 5 个 formal families，`planner_hard_rejection_count=0`、25/25 approved，未出现 failure classification；相关 source-contract tests 与 Gate 7 全量通过。 | PASS |
| 14 | 未回退用户修改、无本轮无关生成物 | 最终 `git status`/`git diff --check` 已检查；本轮只修改终态判定、对应回归测试和两份收口文档，既有 dirty worktree 修改全部保留，未执行 reset/checkout/commit。 | PASS |

Gate 1 的初始 expanded 运行曾暴露 1 个历史 continuous-incident 断言失败（`212 passed, 1 failed`）；该日志保留作审计。随后 replay 修复回归 `11 passed`、Gate 2 全量 `513 passed`、终态质量修复 expanded `62 passed`，因此 Gate 1 按 composite evidence 关闭，而不是隐藏失败。

## 18. 可直接使用的实施 Prompt

下面内容可直接交给新的实现 Agent。

```text
你正在 /home/qcrs/statebus/project 中继续 StateBus v2 实现。

当前分支应为 feat/yzm-v2-migration，起点提交为 e6f62de。开始前先执行只读检查：
1. git status --short --branch
2. git log -1 --oneline --decorate
3. 阅读 AGENTS.md
4. 完整阅读：
   - README.md
   - docs/reference/题目.md
   - docs/constraints/current_host_and_migration.md
   - docs/constraints/current_feature_scope.md
   - docs/planning/implementation_plan.md
   - docs/planning/adaptive_mainline_semantic_state_integration_plan_20260719.md
   - docs/planning/semantic_provenance_and_hydration_contract.md
   - docs/planning/replay_admissibility_contract.md
   - docs/planning/execution_artifact_and_workspace_contract.md
   - docs/planning/benchmark_quality_floor_contract.md
   - docs/planning/ephemeral_neural_state_boundary_note.md

不要 reset、checkout 或覆盖用户已有修改。若工作树已脏，先判断修改是否相关；无关修改保留并绕开。

目标不是继续讨论或增加接口，而是完成以下主线，并持续实现到测试结束：

P0-1：把 Adaptive Agent/CodeAct 接入唯一产品 Runtime。
- 把 diagnostics 脚本里的正式 factory/handler 装配移动到 v2/runtime 所有的产品入口。
- strict/adaptive 可以有不同 workflow policy，但必须共享 StatePool、MemoryProxy、UDS、workspace、artifact、telemetry、persistence 和 cleanup。
- diagnostics runner 最终只负责 CLI 和报告。
- Planner 提出 DSL/CodeAct，policy 校验，Runtime 发 grant；不得让所有任务强制 CodeAct。
- 对 Planner rejection 分因：unsafe/out-of-scope、capability missing、invalid contract 是允许的安全拒绝；合法 formal case 的 schema failure 或 policy false reject 是必须修复的问题。
- fresh 25-case 报告分别统计 hard rejection、schema repair、policy repair 和最终 approved；合法 formal cases 的 hard rejection 目标为 0。
- Planner prompt 不得看到 expected facts、gold answer 或 corpus 答案正文。
- CodeAct prompt 只使用当前 step goal、operation semantics、verified inputs/schema、completion criteria 和 sandbox policy。
- Summarizer 只消费 verified claims/evidence/artifact，不从 expected facts 补答案。
- 不得用 formal case 的公司名、数值或答案编写 few-shot；提示词修复必须对应通用失败类别，并跨至少两个 task family 验证。

P0-2：实现真实非文本 embedding state。
- Retriever 生成 query + candidate embedding matrix 和 HydrateManifest。
- dense payload 使用 little-endian contiguous float32；字符串和 locator 不进入 payload。
- ref/manifest 必须包含 dtype、shape、normalized、encoder signature、manifest ID、hash、size 和 lifecycle 元数据。
- shared_memory 是短命 dense state 默认后端，预算/平台失败按现有 policy 回退 mmap。
- UDS + typed Protobuf 只传 ref 和控制字段。
- 至少一个不同 PID 的 Executor-side semantic consumer 从 ref/registry 打开 matrix，执行 cosine/top-k、dynamic pruning 和局部 hydration。
- MemoryProxy 读取同一 query row 做 FAISS lookup，不能重新 encode 同一 query。
- CodeAct 只消费 verified EvidencePack/artifact，绝不接收向量或向量 JSON。
- JSON embedding 可保留作审计 sidecar，但不能作为数据面 payload。
- 只有真实 resolve 并数值使用后才能记录 STATE_CONSUMED/semantic_state_transfer_count。

P0-3：把 keyword + tags + vector 接成一次 Hybrid MemoryQuery。
- 三路各自产生有序候选。
- memory ID 去重后用确定性 rank-only RRF 融合，不直接混加 BM25/cosine/tag 原始分数。
- 融合后执行 compatibility/replay gate。
- embedding 只用于召回，不能进入 exact replay key。
- 按任务意图检索，命中后返回 summary、strategy、evidence 或 verified artifact，不是只返回历史问题。

P1-1：让 EvidenceRequest.evidence_types 真正控制 lexical/semantic/table dispatch。
- table 任务不强制 semantic。
- 长文档 narrative 才使用 semantic + lexical。
- 未请求的 retriever 不应执行。
- fan-in deterministic，rerank 必须真正影响 selected set。
- 不增加 LLM reranker。

P1-2：精简连续任务。
- 两个 offline 财报/经营指标 family。
- 每组 2 至 3 种核心任务关系，通过不同输入实例形成总计 10 次连续执行。
- family 不再各自要求 10 rounds；collection 至少 2 families，总执行数至少 10。
- 移除 family ID 白名单，改为 schema/capability/input contract 校验。
- 不用完全相同任务 replay 冒充关联任务收益。
- 稳定性和 memory/replay gain 分开统计。

禁止：
1. KV/hidden-state/logit handoff 主线；
2. 新 Agent；
3. case ID、公司名、expected facts、答案关键词分支；
4. 任务专用 Runtime 工具；
5. embedding 直接给 LLM；
6. JSON vector 放 shared memory；
7. sealed holdout、多 seed、全后端乘全模型、反事实大矩阵；
8. 未经测试就声称 shared memory 更快；
9. 为通过测试降低 quality floor、放宽 sandbox 或开启 silent fallback。

Docker 环境固定为：
- host repo: /home/qcrs/statebus/project
- container: statebus-dev-qcrs
- container repo: /workspace/statebus/project
- STATEBUS_HOME: /statebus
- image target: embed
- container test harness: root（docker exec -u 0）
- CodeAct sandbox: bwrap 内非 root UID/GID
- run artifacts: /statebus/runs/<run_id>
- temp/workspace/statepool: /statebus/work/<run_id>

宿主机启动：
cd /home/qcrs/statebus/project
export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
export STATEBUS_DOCKER_TARGET=embed
export STATEBUS_DOCKER_RUNTIME=nvidia
export STATEBUS_NVIDIA_VISIBLE_DEVICES=all
docker compose -f docker/compose.yaml build statebus-dev
docker compose -f docker/compose.yaml up -d statebus-dev

容器激活：
docker exec -it -u 0 statebus-dev-qcrs bash
source /workspace/statebus/project/docker/activate_statebus_container.sh
cd /workspace/statebus/project

实施顺序：
1. 先写/更新 focused tests，证明当前缺口。
2. Runtime-owned adaptive assembly。
3. embedding binary codec 和 typed metadata。
4. cross-process resolver/consumer 和 lifecycle。
5. Retriever/MemoryProxy 消费与 pruning/hydration。
6. hybrid memory。
7. retriever routing。
8. continuous suite 精简。
9. 分层测试和文档更新。

测试必须静默：
1. 测试前只向用户说明 gate 和日志目录。
2. stdout/stderr 全部重定向到 /statebus/runs 或宿主机 $HOME/statebus/runs。
3. 不使用 tee、tail -f、pytest -s，不流式报告 case。
4. 如果执行工具返回 session/cell ID，持续 wait 到完成或错误；不要结束当前任务。
5. live API/formal timing 串行执行，不能并发。
6. 成功只报告 PASS、计数、耗时、日志/summary 路径。
7. 失败报告 exit code 和最后最多 80 行相关错误，然后修复并重新跑受影响 gate。

测试顺序：
Gate 1 focused deterministic：codec、state resolver、UDS、retrieval/pruning、memory、adaptive wiring、CodeAct policy、cleanup。
Gate 2 python3 -m pytest -q tests/v2。
Gate 3 deterministic preflight + formal。
Gate 4 shared_memory continuous + 一个真实 local embedding 跨进程 consumer。
Gate 5 bwrap readiness，确认 sandbox UID/GID 非 0。
Gate 6 fresh serialized adaptive 25-case，系统门必须通过，质量门至少 80%，目标保持 25/25，禁止特化。
Gate 7 openEuler 容器 smoke。

不要重复运行已经通过且未受影响的昂贵 gate；根据改动风险选择 focused rerun，但最终交付前必须完成全部 Gate 1-7。API 测试只做最终一次正式串行 run。

完成后给出：
1. outcome-first 变更摘要；
2. Agent/Runtime/State/Memory 的真实调用链；
3. 所有测试命令、fresh 结果和 artifact 路径；
4. fresh 25-case 的 Planner rejection、DSL/CodeAct 分布、Executor model failures、system failures 和质量率；
5. continuous 10 次执行的稳定性与真实复用指标；
6. 已知剩余风险和明确 Future Work；
7. git diff/status，且不要自动 commit，除非用户明确要求。

不要停在计划或半成品；在当前轮可行范围内完成实现、验证和清晰交付。遇到真实阻塞时，先穷尽仓库内可验证路径，再报告具体阻塞条件。
```

## 19. 最终判断

这一阶段的核心不是“把更多技术名词接进系统”，而是让每条正式机制都能回答四个问题：

1. 谁生产；
2. 怎么传；
3. 谁消费；
4. 消费后改变了什么。

Adaptive Agent、embedding、StatePool、UDS 和 Memory 只有进入同一条 Runtime 主链，并在质量门通过的前提下产生可观察效果，才构成完整的赛题实现。

# StateBus v2 赛题就绪度详细审计：latent/KV handoff 关闭，Prefix + LogitState 待闭环

日期：2026-07-22

审计类型：实现、历史证据、赛题要求、实验缺口和包装边界的联合审计。

审计范围：`v2/` 当前工作树、2026-07-20 canonical E0-E6 artifact、2026-07-22 代码级核查。本文不修改 Runtime，不重跑正式模型实验，也不把历史结果重写为当前工作树结果。

## 1. 执行摘要

StateBus v2 已经有一个可解释的赛题核心：四个受控角色、typed Protobuf/UDS 控制面、embedding `SemanticStateRef`、共享 memory/replay、受控执行和 benchmark。最强且已具备直接消费证据的非文本状态不是 latent，而是 embedding matrix。

当前不能直接进入“最终包装”的原因不是功能数量不足，而是以下五件事情尚未同时成立：

1. `LogitState` 还只是提取和 telemetry，没有真实 `publish -> numeric consumer -> decision effect -> release` 闭环。
2. Prefix 已有 prompt layout、调度、估算和 `/metrics` 接口，但没有一个满足质量等价、任务局部 counter、冷/热分离、重复与统计纪律的正式实测结论。
3. 2026-07-20 E3 的 memory consumption 统计被后续综合审计认定存在 Summarizer 假消费和过宽 Executor 归因；历史 artifact 必须保留，但 memory 效果 headline 需经当前代码和新鲜反事实实验重建。
4. 正式 headline 的“企业经营/财报垂类”与现有部分 repo-local 合成材料、disease/weather CSV 的来源叙事不一致；缺少可追溯公开数据、独立 holdout 和预处理 provenance ledger。
5. canonical E0-E6 来自一个历史 dirty-worktree snapshot；当前工作树又包含用户拥有的 latent/alignment 改动。因此未来正式结果必须有新的 runtime/config/data freeze，不能把旧 artifact 直接当作当前版本的完全证明。

结论：项目可把 embedding StateRef、结构化通信和受控多角色链作为当前已验证底座；prefix 和 LogitState 应作为本轮必须补实的两个新增机制，但必须先完成 P0/P1 真实性修复和数据治理。任何“时间减少、token 减少、memory 命中提升、质量提升”的包装都应被写为条件性主张，直到对应新鲜实验过门。

## 2. 审计方法和证据优先级

### 2.1 阅读和代码核查对象

- 赛题：`docs/reference/题目.md`。
- canonical 证据：`docs/reports/final_v2_contest_evidence_index_20260720.md`、`docs/reports/contest_evidence_closure_final_report_20260720.md`，以及 `/home/qcrs/statebus/runs/contest_evidence_closure_20260720/` 下的 E1-E6 `summary.json`。
- 纠错审计：`docs/reports/statebus_v2_comprehensive_review_20260720.md`、`docs/reports/statebus_v2_system_task_experiment_report_20260720.md`。
- 当前实现：`v2/runtime/smoke.py`、`v2/state/semantic_state.py`、`v2/retrieval/pipeline.py`、`v2/runtime/neural_state.py`、`v2/runtime/logit_state.py`、`v2/runtime/role_path.py`、`v2/runtime/vllm_metrics.py`、`v2/runtime/prefix_feedback.py`、`v2/benchmark/continuous_runner.py`、`v2/runtime/adaptive_dispatcher.py`。
- 当前任务数据：`v2/benchmark/samples/continuous_task_families/` 下的正式与 prefix 样本 manifest。

### 2.2 当前源码的定向回归

本审计运行了非服务、非破坏性的合同测试：

```text
python -m pytest -q \
  tests/v2/test_logit_state.py \
  tests/v2/test_kv_prefix_control_plane.py \
  tests/v2/test_prefix_feedback.py \
  tests/v2/test_contracts_and_refs.py

33 passed in 0.86s
```

这证明当前 LogitState 序列化、Ref 类型、prefix control-plane 和 feedback 合同有单元测试；它不证明真实 vLLM cache hit、LogitState 下游消费、质量收益或端到端性能。

### 2.3 优先级规则

当报告、代码和历史实验矛盾时，按以下顺序使用：

1. 当前源码和新鲜、带 checksum 的 artifact；
2. canonical E0-E6 的原始 manifest/summary/audit slices；
3. 2026-07-20 综合审计对历史计数的纠错；
4. 其他报告作为背景；
5. 设计/历史 Prompt 不能替代事实。

特别说明：E3 `consumed=23` 是历史 recorded value，但不是可直接用于“真实 Agent 消费”主张的 value。后续报告必须同时保留历史数值和纠错解释，不能静默改写旧 artifact。

## 3. 赛题要求逐项审计

| 赛题要求 | 当前实现/历史证据 | 当前判断 | 严重缺口或必要动作 |
| --- | --- | --- | --- |
| 至少 3 个 Agent、覆盖规划/检索/执行/总结 | `Planner`、`Retriever`、`Executor`、`Summarizer`；E4/E5 有角色请求记录 | 基本满足 | 必须写成“受控固定角色链”，不写成开放式自治协商。正式数据需自然覆盖 semantic/table retrieval。 |
| 结构化通信：动作、参数、结果、能力描述，支持发现/映射 | typed Protobuf/UDS、capability registry、typed Ref；E1 | 满足机制要求 | 当前能力发现主要是进程内 registry，不是 wire-level Hello。可保持“capability discovery + protocol mapping”，不要夸成 UDS 握手。 |
| 纯文本与结构化模式同任务比较 | L0-L3 matched lane，E1 40/40 且 fairness valid | 机制和历史对照满足 | L0 是同一 harness 内的 matched text lane，不是外部系统。后续修复后必须重跑，不可把旧 lane 结果嫁接到新 Runtime。 |
| 非文本中间状态，说明生成、传递、接收、使用 | `SemanticStateRef`：`[query; candidates]` `<f4` matrix，shared memory/mmap，独立 PID cosine top-k，selected IDs 决定 hydration；E4 4/4 | 强满足 | 需要当前版本 fresh rerun，并分开 logical owner、physical consumer、downstream role 记账。不要误称为 hidden/KV。 |
| 共享 memory 存储、检索、跨任务复用 | SQLite/向量/compatibility/policy/replay；E1/E2/E3 | 部分满足，证据有风险 | candidate/approved 不能等于消费；E3 的 23 条消费不能当主张。需做真实 Prompt/recipe receipt 和 with/without-memory counterfactual。 |
| 两组关联连续任务、至少 10 轮 | E2 两 family 各 10/10，合计 20/20 | 历史稳定性满足 | 用于正式 headline 的两条链必须与最终垂类、公开数据和新 Runtime 一致，不能只保留合成/通用 CSV。 |
| 消息、token/字符、状态次数/字节、时延、memory reuse 指标 | telemetry 和 summary 已有 | 覆盖面足够，定义尚需收紧 | latency、prefix hit、memory hit、LogitState transfer 不能用估算/候选/单次结果包装为优势。 |
| Runtime、协议、状态交换、memory、评测模块 | `v2/` 结构完整 | 满足 | 需要以模块间真实数据流而不是目录名证明。 |
| 稳定执行不少于 10 轮 | E2 20/20；E6 `558 passed` | 历史满足 | 未来最终版本需 fresh regression 和新的 2x10 artifact。 |
| CodeAct 鼓励项 | E5 25/25，DSL 7、bounded Python 18、bwrap/non-root 记录 | 可作为增强项 | 只能称受控 DSL/bounded Python，不能称任意自由代码或生产级沙箱。 |
| openEuler 交付 | canonical 证据为 openEuler 24.03 单容器 | 历史容器验证满足 | 当前版本、正式新数据和新机制完成后需重新 freeze/回归；不能扩展为 VM、跨机或任意 Linux。 |

## 4. 当前实现状态：机制、真实消费者与缺口

### 4.1 控制面和角色能力

当前主路径是 Runtime 控制的固定顺序调用，而不是四个模型经 UDS 自主互相协商：

```text
TaskCompiler -> Planner objective -> Retriever fan-out
  -> Retriever/Executor closed-set selection -> bounded execution
  -> verified artifact -> Summarizer -> memory/telemetry
```

- Planner 主要产生 bounded retrieval objective，不能产生执行 DAG、动态子任务或任意 tool call。
- Retriever/Executor 在 Runtime 构造的 candidate surface 中选择，属于闭集受控决策。
- Executor 的 DSL/bounded Python 仍由 workspace、静态策略、bwrap/资源回退和 validator 约束。
- Summarizer 组织已验证的 artifact/evidence，不是数值真相来源。
- Controller、semantic selector、prefix scheduler、ConfidenceGate 都是系统组件，不能计入 LLM Agent 数量。

这是赛题可接受、甚至更可审计的设计；严重风险在于包装时把它称为“通用自主多 Agent 平台”。

### 4.2 Embedding SemanticStateRef

实现位置：`v2/state/semantic_state.py`、`v2/runtime/smoke.py:2205` 附近、`v2/retrieval/pipeline.py:1645`。

真实链路：

```text
Retriever query + candidate embeddings
  -> encode_dense_semantic_matrix(): normalized <f4 matrix
  -> publish_dense_semantic_state(): StateRef + manifest + hash + lease
  -> SubprocessExecutorTransport semantic_select_v1
  -> independent PID resolve + cosine + top-k + byte budget
  -> apply_semantic_state_selection()
  -> selected IDs hydrate CanonicalEvidencePack and role slices
  -> release
```

这条链有真实二进制状态、跨 PID 数值 consumer、对 EvidencePack 的确定性影响和状态生命周期，是当前最适合赛题的非文本状态主证据。

仍需补强：

- 一次 current-code 的 producer/consumer/selected-ID/hydration/release fresh audit；
- `state off`、`state on`、已批准扰动/错误 Ref 的机制对照；
- 将 Runtime selector 的物理消费与 Executor role 的逻辑目标分开，避免 `target_role=executor` 被误读为 Executor LLM 直接读向量；
- 报告 matrix shape、dtype、byte order、bytes、source hashes、PIDs、lease 和实际 selected IDs。

### 4.3 MemoryRef 与 replay

当前 MemoryRef 模型、兼容性门和 replay 类型是正确方向：query、candidate、compatible/degraded、policy approved、projected、actual consumed、effect、assist、validated replay、exact replay、skipped step、skipped LLM call 应逐层统计。

当前源码已经出现较严格的 receipt-oriented 逻辑：`adaptive_dispatcher._record_memory_consumption()` 要求 approved input、consumed IDs、rendered request hash 或 executed recipe hash；`smoke._continuous_memory_consumption_records()` 的注释也说明 candidate 不等于 receipt。它说明实现正在朝正确方向收口。

但是，这不是 E3 历史 artifact 已自动被修复的证据。必须以新鲜 run 证明以下事项：

- 每条 `consumed` 对应实际 rendered prompt 或已执行 recipe；
- Summarizer 未看到 memory 时不记录为 consumed；
- 多候选场景只给实际使用的 memory ID 记账；
- with/without-memory paired counterfactual 分别报告质量、token、LLM call、工具步骤和 latency；
- incompatible candidate 可见、被拒绝且当前任务重新计算通过。

### 4.4 Engine-Local Prefix Reuse

实现位置：`v2/runtime/neural_state.py`、`v2/runtime/role_path.py`、`v2/runtime/vllm_metrics.py`、`v2/runtime/prefix_feedback.py`、`v2/benchmark/kv_prefix_schedule.py`、`v2/benchmark/continuous_runner.py`。

当前已存在：

- corpus/evidence prefix identity、schedule hint 和 `EngineLocalPrefixRegistry`；
- `shared_evidence_prefix` prompt layout；
- `cache_friendly`/`cache_hostile` 十轮任务族和依赖安全的 schedule plan；
- vLLM `/metrics` parser，以及 before/after query/hit counter delta 的有效性检查；
- TTFT probe 和 predicted-vs-observed feedback data structure；
- focused contract tests，证明 plan/layout/metric aggregation 的代码合同。

当前没有得到正式证明的事项：

- `EngineLocalPrefixRegistry.cache_hit` 只是控制面复见，不是 GPU cache hit；
- `evidence_prefix_hash` 是否严格绑定 tokenizer 产生的 exact shared token sequence，需要审计；
- current prompt 中不同 role 的公共前缀是否在相同 token 位置，需要 P-A 渲染完整性实验；
- 某个 task-local `/metrics` delta 是否在当前 vLLM 版本实际可用，需要探针；
- cache-friendly 与 hostile 是否在质量等价、冷/热分离、重复和 AB/BA 下产生可重复 TTFT 或 prefill 差异，尚无 canonical 结论；
- 当前 estimated prefill saved tokens 只能当调度估算，不能当性能结果。

因此 Prefix 是“实现骨架已存在、性能证据不足”的高优先级机制，而不是已证明的加速 headline。

### 4.5 LogitState

实现位置：`v2/runtime/logit_state.py`、`v2/refs/models.py`、`v2/runtime/role_path.py:2035` 附近、`v2/runtime/smoke.py:3552` 附近。

当前已存在：

- `LogitStateRef`、`RefKind.LOGIT_STATE` 和 storage preference；
- `serialize_logit_state_v2()`：从 response top-logprobs 取 peak entropy position 的 `<f4` probabilities，并提供 entropy、aggregated entropy、varentropy、top gap、candidate decision entropy；
- Executor decision 把上述摘要写入 telemetry；
- `logit_state_transfer_count` 目前仅从 `logit_state_bytes > 0` 推导，`confidence_proxy < 0.3` 目前只是粗粒度计数门；
- 本审计的 33 个 focused tests 覆盖空输入、peak、varentropy、top gap、payload、candidate entropy、Ref 和 prefix control-plane 合同。

当前缺失且属于严重功能缺口：

- 没有在主路径发布 payload 到 `LayeredStateStore`；
- 没有注册 active `LogitStateRef`、metadata sidecar、lease、resolve/release；
- 没有独立 numeric consumer，也没有 producer/consumer PID；
- 没有 calibration，`0.3` 不可当质量阈值；
- 没有由 LogitState 造成的 evidence expansion、verifier、selection retry、reject 或 accept action；
- 没有 gate-off/telemetry-only/gate-on 的质量成本对照。

当前状态必须写为“输出不确定性遥测和待接入的非文本状态合同”，不能写为“LogitState 已在 Agent 间传递并改善决策”。

### 4.6 数据、预处理和任务

当前任务框架有 25-case formal registry、两条核心十轮链、semantic holdout、prefix probe 和多种诊断族。优势是离线、可重复、可做确定性 validator；弱点是数据来源和垂类叙事不统一。

- `formal_financial_reports_v1`、`cross_period_financial_v1` 依赖 repo-local ACME/BETA markdown；manifest 的 `source_basis` 是 design note，不是外部 provenance。
- `formal_operating_metrics_v1`、`csv_table_profile_v1` 依赖本地 disease/weather CSV 和 `task/group2_*`，适合表处理，但与“企业经营分析”主叙事不天然一致。
- `kv_prefix_reuse_v1` 的 Orion/Nova 文件被明示为 mechanism-only、not default formal chain；可用于 prefix 控制实验，不能自动升级为正式业务泛化。
- semantic holdout 虽将 gold 与 role 可见面分离，但仍是 repo-local limited holdout，不是第三方或盲测。

必要动作不是立即重做所有数据，而是先决定正式垂类，随后建立可复现的 raw source -> normalize -> canonical corpus/table -> locator -> manifest -> separate gold 链。预处理不能预筛目标答案或把 expected facts 变成 Runtime 路由线索。

## 5. 历史结果审计：能用什么，不能用什么

| 证据 | 已观察结果 | 可信用途 | 不能扩大成 |
| --- | --- | --- | --- |
| E0 | focused tests `135 passed` + preflight | 历史工程门 | 当前 dirty worktree 的完整回归 |
| E1 | 40/40，四 lane 各 10/10；L0->L1 control `-83.05%`、wire `-68.95%`；L1->L2 prompt tokens `-55.76%`、visible bytes `-81.10%`；L3 validated replay 2、skipped steps 2、skipped LLM calls 0 | 匹配 carrier、semantic hydration、历史 memory 漏斗 | Protobuf 省 token、稳定总时延更快、自然 memory 节省 LLM call、prefix gain |
| E2 | 两条连续 family 各 10/10，共 20/20；memory candidate 48、compatible/approved/recorded consumed 9、validated replay 2、skipped LLM calls 0 | 历史 2x10 稳定性和 rejection/recompute 行为 | 44 artifact reuse 就是 44 replay，或整体性能 superiority |
| E3 | 6/6；historical recorded `candidate=16`、`compatible=15`、`consumed/effect=23`、skipped LLM call 1 | commit/load/compatibility/rejection 的设计证据 | 23 次真实角色消费；自然任务稳定跳过 LLM；该次 skip 是一般收益 |
| E4 | 4/4，semantic 3、table 1；gold 未暴露给 roles；跨 PID semantic consumed | embedding StateRef 的最强历史机制证据 | 外部/开放域 generalization 或 hidden/KV transfer |
| E5 | 25/25；DSL 7、bounded Python 18；retriever table 25；latency superiority disabled | capability surface 下的受控选择和执行 | semantic route 在 25-case 内自然覆盖，或通用自治 Agent |
| E6 | `558 passed` + preflight | 历史 openEuler container regression | 当前 branch/数据/prefix/logit 改造后的最终 gate |

历史描述性 latency：E1 的固定顺序单次 p50/p95 为 L0 `31.953/33.440 s`、L1 `32.355/35.589 s`、L2 `32.391/36.336 s`、L3 `29.135/35.212 s`。这些数据没有反向顺序、多重复或置信区间，不能用于“StateBus 更快”的正式包装。

## 6. 严重问题排序

| 优先级 | 问题 | 严重性 | 为什么严重 | 修复完成定义 |
| --- | --- | --- | --- |
| P0-1 | `LogitState` 没有真实 consumer chain | 阻断新增机制 | 当前只有 bytes/metric；无法证明非文本传递或质量控制 | published ref、独立 resolve、calibrated gate、可观察 action、release、counterfactual |
| P0-2 | Prefix 没有正式实测因果证据 | 阻断“时间/TTFT 减少”包装 | estimate/registry hit 不等于 engine hit；服务残留会污染结果 | P-A/P-B/P-C 完成，quality 等价，合法 counters，重复统计 |
| P0-3 | Memory 历史消费口径失真 | 阻断 memory reuse 效果主张 | 赛题 20 分涉及 memory；假消费会伤害可信度 | rendered/recipe receipt、角色级真实消费、with/without-memory paired run |
| P0-4 | 数据 provenance 与垂类叙事不闭合 | 阻断“面向垂类”和外部说服力 | 合成/通用数据不能直接证明企业经营域价值 | source/license/hash/transform/gold ledger、外部 holdout、正式数据决定 |
| P0-5 | 当前代码与 canonical evidence identity 不同 | 阻断最终交付可信性 | 旧 E0-E6 是另一个 dirty snapshot；当前有 latent/alignment 用户改动 | final config/runtime/data freeze，新鲜 tests 和 artifacts |
| P1-1 | 结构化通信和 latency 的因果边界易被夸大 | 高 | E1 token 不降，latency 无统计设计 | 保留 bytes headline；对 latency 用随机/ABBA repeated design |
| P1-2 | Agent 能力叙事过宽 | 高 | 当前固定 pipeline/闭集 tools，不是开放式自治 | 角色权限表、自然 capability 覆盖、收窄措辞 |
| P1-3 | semantic state 记账角色混淆 | 中高 | 物理 selector 被写作 Executor 容易误导 | owner/consumer/target 分字段，PID 不聚合 |
| P1-4 | `kv_prefix_reuse` 为 mechanism-only 数据 | 中高 | 若直接当业务基准会被质疑专门造 case | 用于机制 AB/BA；另建业务正式数据验证 |
| P2-1 | wire-level Hello/negotiation 缺失 | 中 | registry discovery 已满足三选一，不是硬 blocker | 仅在答辩确有需求时补真协商和测试 |
| P2-2 | sandbox 边界可能被过度宣传 | 中 | bwrap/non-root 不等于生产多租户沙箱 | 保持 contest validation profile 描述 |

## 7. 必要实验清单与判定标准

以下不是“可做可不做”的性能调参清单；P0/P1 属于本轮必要实验或必要证据。所有实验先在 dev 数据做机制与阈值确定，再冻结 manifest、配置和 runtime hash 后运行 holdout/formal。

| 编号 | 是否必要 | 研究问题 | 最小对照 | 通过/降级规则 |
| --- | --- | --- | --- | --- |
| R0 冻结与回归 | 必要 | 当前版本是否可被识别和复现 | source/config/data/runtime/image hash + focused/full tests | 未 freeze 不进入正式实验；测试失败不包装 |
| R1 embedding 状态机制 | 必要 | matrix 是否被跨 PID 数值消费并改变 hydration | state off、state on、合法扰动/拒绝 control | 记录 ref/shape/bytes/PID/IDs/release；质量不降才谈 evidence pruning |
| R2 L0-L3 因果矩阵 | 必要 | control、semantic、memory 分层效果 | 同任务/模型/拓扑/quality，仅切换 lane feature | 每 lane quality pass；bytes、tokens、state、memory 分开；不强求 latency 优势 |
| R3 两组 10 轮 | 必要 | 连续链是否稳定、memory 是否兼容复用 | 两个 frozen family，各 10 轮，独立 family/lane roots | 10/10，rejection/recompute 可审计；candidate 不等于 reuse |
| R4 memory 真实消费与反事实 | 必要 | memory 是否实际进入角色/recipe，并产生受控效果 | memory off、disclosed-only、actual consumed；负例 incompatible | receipt 对齐，质量/token/call/step 分开；无收益则降为 storage/retrieval evidence |
| R5 prefix 渲染完整性 | 必要（启用 prefix） | 公共前缀是否确为 exact same token prefix | stable canonical render vs reordered/unstable render | exact token-ID hash/length 和质量结果；不同则不谈 cache reuse |
| R6 prefix 引擎机制 | 必要（启用 prefix） | 调度是否创造真实 engine-local hit/TTFT 变化 | cache-friendly vs hostile，AB/BA，冷/热分开 | valid counter delta + repeated TTFT/request latency；无 counters 时只能报告 unavailable |
| R7 prefix 端到端 | 必要（包装时间减少） | prefix policy 对总任务成本是否有净价值 | prefix off vs on，其他机制固定 | 质量等价、重复、CI；只观察 TTFT 不足以写总时延减少 |
| R8 LogitState calibration | 必要（启用 LogitState） | uncertainty 特征是否预测实际错误 | dev calibration set，entropy/gap/feature policy | frozen threshold；报告 calibration/risk-coverage；无预测力则不进入 gate |
| R9 LogitState 生命周期 | 必要（启用 LogitState） | raw float state 是否真实被数值 consumer 使用 | valid ref、perturbed/refused/expired ref | publish/resolve/PID/effect/release 全闭环；telemetry-only 不算通过 |
| R10 LogitState 效果 | 必要（包装质量或风险） | gate 是否在可接受成本下改善 verified result | gate off、telemetry-only、calibrated gate | quality/recovery/false trigger/extra tokens/calls/latency；无净收益则降为 telemetry |
| R11 垂类与数据 holdout | 必要（包装垂类/泛化） | 任务是否不是 repo-local 造例 | external source family、preprocessing ledger、frozen holdout | source/gold/runtime visibility 有证据；不通过只能称 repo-local benchmark |
| R12 Agent capability coverage | 强烈建议 | semantic/table 与 DSL/Python 是否自然受任务驱动 | frozen formal set，观察选择而非强行 route | 只报告自然 selected count；未覆盖则缩窄能力主张 |

## 8. Prefix 和 LogitState 应放在核心链路的什么位置

这不是已实现事实，而是经过审计后需要由后续设计文档选择并论证的目标结构。它给出明确的接入边界，防止二者沦为旁路指标：

```text
raw vertical data -> deterministic preprocessing -> canonical corpus/table + locator
  -> Planner retrieval objective
  -> Retriever candidate fan-out
  -> embedding SemanticStateRef -> selector -> selected EvidencePack
       |                                      |
       |                                      +-> role-specific evidence slices
       |
       +-> canonical shared evidence prefix -> PrefixReuseIntent
              -> exact token identity -> dependency-safe schedule
              -> same vLLM APC observation (not KV transfer)

role closed-set decision with top_logprobs
  -> LogitStateRef(float32 + binding contract)
  -> independent ConfidenceGate / Verifier
  -> accept OR expand_once / verify_once / retry_once / fail_closed
  -> verified artifact -> Summarizer -> MemoryRef
```

### 8.1 Prefix 的推荐边界

- StateBus 处理公开且可审计的 prompt layout、token identity 和 scheduling intent；vLLM 处理 KV block 创建、命中、淘汰和显存布局。
- prefix 的共享对象必须是 canonical selected evidence 和稳定模板，不是“语义相近的文本”。
- role-specific task、instruction、response schema 放在公共 token prefix 之后，且必须用质量实验检查这种布局没有伤害角色行为。
- 只在同 engine/cache namespace、相同 model/tokenizer/template/token IDs/cache epoch 下当 `eligible`；真实 hit 必须来自引擎观测。
- Prefix 主要期望改善 prefill/TTFT；若端到端延迟、token 或调用数不降，必须如实分开报告。

### 8.2 LogitState 的推荐边界

- producer 应选择有业务含义、有限候选面且可判错的模型决策；不能仅用 JSON 尾部语法 token。
- payload 是短命 `<f4` probabilities/uncertainty feature，默认 shared memory；metadata 绑定 task/session/prompt/candidate surface/model/template/calibration policy。
- consumer 应为独立 `ConfidenceGate` 或 verifier worker，数值读取 ref 后只能输出一个预注册、最多执行一次的 bounded action。
- action 应服务于质量：扩大证据、调用 verifier、重选候选或拒绝 risky replay；它不必减少时间，且可能增加 token/latency。
- threshold 必须在 dev calibration 固定，holdout 仅验证。top-logprob 并不自动代表正确率。

## 9. 包装规则：现在能说什么，未来可争取什么

### 9.1 现在可以诚实包装的内容

- StateBus 用 typed Protobuf/UDS 表达动作、合同和 Ref，历史 matched run 观察到控制面与总 wire bytes 明显降低。
- embedding semantic matrix 经 shared memory 在不同 PID 间被数值消费，selected IDs 改变后续 hydration；LLM 不直接读取向量。
- Memory 具备存储、检索、兼容性拒绝、artifact/strategy reuse 与 replay 设计，但真实消费和自然效率收益需按更严格口径重建。
- 四角色在受控 capability surface 内协作，Executor 有 DSL/bounded Python 和 validator；不是开放式通用自治系统。
- 历史 openEuler 单容器内完成过 E0-E6 和完整回归；当前版本仍需 fresh validation。

### 9.2 只有满足新实验门后才能包装的内容

| 想要的包装句 | 必要新证据 |
| --- | --- |
| “端到端时间减少 X%” | R7，质量等价、串行重复、ABBA/随机化、CI、无服务残留混杂 |
| “prefix 命中提升/TTFT 降低” | R5+R6，exact token identity、valid engine counter delta、冷/热分开 |
| “LogitState 提升质量/减少错误” | R8+R9+R10，calibration、真实 consumer、gate-off 对照、成本报告 |
| “memory 减少重复计算/LLM 调用” | R4，actual receipt、paired counterfactual、非零 verified skipped call 或等价证据 |
| “面向企业经营垂类有效” | R11，公开来源/provenance、frozen holdout、与叙事一致的两条十轮链 |
| “semantic selector 节省上下文” | R1+R2，真实 selected IDs/hydration、质量不降、prompt-visible/token 口径明确 |

### 9.3 永久禁止的包装

- 将 prefix/handle/estimate 写成 KV tensor 或 Agent-to-Agent hidden-state transfer；
- 将 top-logprob entropy 写成正确率、可信度或已改善质量；
- 将 memory candidate/approved/history artifact reuse 写成 replay/hit；
- 将 L0-L1 control bytes 降低写成 Protobuf 必然节省 token；
- 将单次或固定顺序 latency 写成稳定性能 superiority；
- 将 repo-local 或合成样本写成第三方/开放域/生产泛化；
- 将受控固定角色链写成自由自治 multi-Agent 群体。

## 10. 建议的文档化交付顺序

在开始实现前，应先产出并冻结下列文档，而不是先修改代码：

1. `00_executive_decision_and_packaging.md`：赛题问题、垂类、难点、系统方案、当前/未来/禁止主张。
2. `01_current_state_and_remediation.md`：本审计所有 P0/P1 问题、代码位置、修复完成定义。
3. `02_prefix_engine_local_reuse_design.md`：理论、exact identity、事件、文件级接入、P-A/P-B/P-C preregistration。
4. `03_logitstate_core_chain_design.md`：理论、producer/consumer 选择、contract、calibration、L-A/L-B/L-C/L-D preregistration。
5. `04_vertical_data_preprocess_and_task_design.md`：数据来源、许可、转换、gold 隔离、两组十轮链、holdout。
6. `05_experiment_matrix_metrics_and_statistics.md`：R0-R12、L0-L3、指标字典、随机化、统计和 claim gate。
7. `06_implementation_plan_and_acceptance.md`：按 P0/P1/P2 排序的文件级变更、测试和退出条件。

这些文档完成且相互一致后，才应开始代码实施。最终包装文档必须从实际通过的 claim gate 生成，而不是预先承诺时间、token 或质量收益。

## 11. 审计结论

StateBus v2 的正确竞争力不是“更多不透明神经状态”，而是把协作中可被核查的对象做成不同层：typed control contract、embedding StateRef、verified execution artifact、MemoryRef、engine-local prefix intent 和 uncertainty-driven LogitState gate。

当前最优策略是：以 embedding 作为非文本状态主证据，先修 memory/data/fairness 可信性，再把 prefix 做成真实引擎观测的性能层，把 LogitState 做成经校准的质量控制层。只有这样，后续答辩中的“通信更低、上下文更少、时间更短、记忆更有效、质量更稳”才会有各自独立且可审计的证据，而不是一张混合指标表。

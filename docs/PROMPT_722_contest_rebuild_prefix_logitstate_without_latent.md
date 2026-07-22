# StateBus v2 赛题重建执行 Prompt：Prefix + LogitState，latent/KV handoff 关闭

日期：2026-07-22

状态：待执行设计审计、辅助核对与文档化。本文是交给后续 AI 的决策/设计 Prompt；本轮只允许写指定设计文档，并可做受限的辅助核对；不实现代码、不改数据或 manifest、不跑正式实验，也不生成最终结果报告。

术语说明：用户口述中的 `logstic` 按仓库已有术语 `LogitState` 理解，即从模型输出 `top_logprobs` 提取的 float32 概率分布与不确定性特征；它不是 logistic regression、hidden state 或 KV cache。

## 0. 总目标与执行顺序

你负责把 StateBus v2 收敛为一个可提交、可复现、可解释的赛题原型的详细设计方案。最终定位默认是：

> 面向企业经营分析、财报与运营指标连续任务的多 Agent 协作基础设施：以结构化控制面降低协作传递开销，以 embedding 语义状态选择证据，以共享记忆复用已验证知识，以 engine-local prefix reuse 降低重复 prefill 机会成本，并以 LogitState 驱动受控核验。

这不是只改叙事的任务。你需要把未来执行严格约束为下列顺序，但本 Prompt 在“完成文档设计”处停止：

```text
先审计真实实现和证据缺口
  -> 先修复会导致错误主张的机制/记账/数据问题
  -> 实现并测试 prefix 与 LogitState 的真实消费闭环
  -> 冻结数据、配置、质量门与实验计划
  -> 运行新鲜、可校验的正式实验
  -> 最后才写答辩、README、报告和视频叙事
```

不得建议先跑大实验、再根据结果改任务、改阈值、改 gold 或包装成功故事。失败结果必须保留，不能删除、覆盖或混入 canonical 聚合。

本 Prompt 内所有“实现”“实验”“验收”措辞都表示后续工程阶段的计划，不是你现在获准执行的动作。你现在的唯一交付是写入 `docs/planning/contest_rebuild_20260722/` 的设计文档集，具体文件清单见第 11 节。

## 1. 不可变决策与安全边界

### 1.1 本轮关闭的路线

本轮赛题主线明确关闭以下能力：

- `LatentStateRef`、`prompt_embeds`、aligned latent、hidden-state handoff；
- Agent/进程/机器之间的 KV tensor 导出、传输、恢复或共享；
- LatentMAS 复现、lossless latent、latent token/时延/质量收益；
- 将任何 prefix hash、registry handle 或 vLLM 自动 prefix cache 写成 KV tensor transfer。

已有 latent 代码和用户未提交改动不得擅自回滚、reset、checkout 或删除；但正式 contest 配置、benchmark lane、架构图、指标表、README 和答辩主线必须显式 `latent_mode=off`，且不能依赖它通过质量门。

### 1.2 本轮必须加入的两条机制

`Engine-Local Prefix Reuse` 与 `LogitState` 都是本轮必须完成的轨道，但实现 Agent 必须先决定正确的理论定义、生产者、消费者、契约、实验和边界，不能把现有遥测字段直接包装成已完成能力。

- Prefix 的目标是：让同一兼容 vLLM 引擎在真正相同的 token 前缀上更可能命中它自己的自动 prefix cache，并用引擎观测证明这一点。
- LogitState 的目标是：让一个后续的、受控的程序或角色真实消费非文本概率状态，决定是否扩大证据、执行核验、重试选择或保持结果；不能只记录 entropy 后宣称“状态已传递”。

它们不是 embedding StateRef 的替代品。embedding 仍是赛题非文本中间状态的正式主证据；prefix 是性能优化层；LogitState 是不确定性驱动的质量控制层。

### 1.3 操作约束

- 保留用户已有脏工作树，不使用破坏性 Git 命令。
- 未得到用户明确许可，不重启、终止、替换当前 `127.0.0.1:53334` vLLM 服务，也不占用无关 GPU 进程。
- 不修改源码、测试、脚本、benchmark manifest、既有实验 artifact JSON、模型或数据；不得下载外部数据并假装已完成数据治理。
- 本轮只可创建/修改第 11 节规定的设计文档。允许按第 1.4 节做辅助核对；不得启动正式模型实验，且不得把辅助核对写成性能、质量或泛化结论。
- 不把 secret、token、完整 raw completion、GPU 地址或 KV 内容写入设计文档。
- 必须把后续代码改动、测试、数据冻结和昂贵实验写成有依赖顺序与退出条件的计划。

### 1.4 允许的辅助核对，及其证据边界

本 Prompt 不要求后续 AI 在纸面假设下写设计。为消除实现认知错误，可以做必要、低风险且可复核的辅助核对，并把命令、输入、观察、局限和是否改变任何运行状态写入 `07_auxiliary_verification_record.md`。允许的范围是：

- 只读源码、Proto/contract、manifest、历史 artifact、服务日志和只读 `/metrics` 快照的交叉核对；
- 现有非破坏性 unit/contract tests，固定 fixture 的序列化、Ref lifecycle、prompt 渲染、tokenizer token-ID identity、配置/manifest 一致性和静态依赖检查；
- 不写入 repo 数据、不改变正式 run root 的短小本地诊断，例如确认某字段是否存在、某个 layout 是否把公共前缀放在相同 token 位置、或一个已存 artifact 是否可被当前解析器读取；
- 若用户明确授权，可对当前服务进行一次最小、固定输入的能力探针，例如确认 `top_logprobs` 或 `/metrics` 中某计数器是否可用。该探针必须单独标记为 capability probe，记录服务/cache 可能受影响的风险，且绝不汇总为 prefix hit、TTFT、质量或端到端性能结果。

以下仍然不允许：启动或重启服务、下载/改造数据、修改实现、跑成组请求、切换 policy 做对照、产生可用于性能或质量比较的样本，或为取得预期结论而反复试探。若辅助核对需要写入服务状态、显著占用 GPU、改变 cache epoch 或执行模型请求而尚未得到用户许可，停止在设计层，写明建议的探针和所需授权。

辅助核对的目的只是确认“现有接口、字段、token identity 或机制观察是否存在”，不是提前替代 P-A/P-B/P-C、L-A/L-B/L-C/L-D 或正式赛题实验。任何未核对项必须在设计中显式标记为假设及其后续验证门。

## 2. 必读资料与证据优先级

先完整阅读并核对当前代码；文档间有历史矛盾时，以后列优先级和实际代码/新鲜 artifact 为准。

1. `AGENTS.md`、`README.md`、`docs/reference/题目.md`：仓库约束和赛题原始要求。
2. `docs/reports/final_v2_contest_evidence_index_20260720.md`、`docs/reports/contest_evidence_closure_final_report_20260720.md`：canonical E0-E6 证据身份和允许的主张。
3. `docs/reports/statebus_v2_comprehensive_review_20260720.md`：对 memory 记账、Agent 能力、语义状态和实验边界的纠错审计。
4. `docs/reports/statebus_v2_contest_readiness_audit_20260722.md`：本 Prompt 的强制决策输入，包含实现/结果/严重问题/必要实验/包装边界审计。
5. `docs/reports/statebus_v2_system_task_experiment_report_20260720.md`：实际系统、任务和实验对象。
6. `docs/reports/statebus_v2_implementation_guide_zh.md`：重点读第 6、9、10、11、12 节。
7. `docs/reports/statebus_v2_agent_controlplane_codeact_architecture_zh.md`：以代码事实界定四个角色，而不是把固定 runtime 写成自治群体。
8. `docs/reports/statebus_native_latent_long_document_plan_remediation_20260722.md`：只用于确认 latent 质量失败和关闭理由。
9. `v2/state/semantic_state.py`、`v2/retrieval/pipeline.py`、`v2/runtime/smoke.py`、`v2/runtime/role_path.py`、`v2/runtime/neural_state.py`、`v2/runtime/logit_state.py`、`v2/runtime/vllm_metrics.py`、`v2/runtime/prefix_feedback.py`、`v2/benchmark/continuous_runner.py`。
10. `v2/benchmark/samples/continuous_task_families/` 下的 `formal_financial_reports`、`formal_operating_metrics`、`cross_period_financial`、`csv_table_profile`、`kv_prefix_reuse` manifest 和原始样本。

`docs/PROMPT_714_intermediate_state_architecture_research.md` 与其他 KV/latent 研究 Prompt 均为历史研究资料；它们不能覆盖本文件的 `latent/KV handoff off` 决策。

### 2.1 审计结论必须成为设计输入

阅读 `statebus_v2_contest_readiness_audit_20260722.md` 后，必须将以下事实写进你的决策文档，而不是用“后续再看”回避：

- embedding SemanticStateRef 已有真实跨 PID 数值 consumer，是当前非文本状态主证据；
- Prefix 是“控制面/布局/调度骨架已在、正式性能证据不足”，必须设计 exact token identity、真实引擎观察和 P-A/P-B/P-C；
- LogitState 是“Ref/序列化/telemetry 已在、真正消费者缺失”，必须设计 calibration 和 L-A/L-B/L-C/L-D；
- memory 的历史 E3 `consumed=23` 不能作为真实消费 headline，必须规划 receipt 和反事实实验；
- “企业经营垂类”需要公开来源、预处理 provenance 和 holdout，现有 repo-local/通用 CSV 不能被静默升级为外部泛化；
- “时间减少”现在不是既成结果。包装文档必须区分当前已证实 bytes 结果、未来 Prefix 的 TTFT/prefill 可能收益、未来 memory 的跳步/调用可能收益，以及没有通过质量等价重复实验时禁止的总时延主张。

## 3. 已知事实、必须先承认的缺口

### 3.1 已有且可保留的主链

```text
CanonicalTaskSpec
  -> Planner 给出 bounded retrieval objective
  -> Retriever 生成 query + candidates
  -> Qwen3-Embedding-0.6B 编码并 L2 normalize
  -> [query; candidates] little-endian float32 matrix
  -> SemanticStateRef(shared_memory 或 mmap)
  -> 独立 selector PID 做 cosine top-k + evidence byte budget
  -> selected candidate IDs 决定 hydration
  -> CanonicalEvidencePack / role-specific prompt slice
  -> Executor 的 verified artifact -> Summarizer -> MemoryRef
```

这条 embedding 链已经满足赛题“非文本中间状态”的核心定义：向量不直接喂给 LLM，而是被数值组件读取，改变下游 EvidencePack。正式补强应证明 producer、physical consumer、logical owner、下游 hydration、release 和 counterfactual 全部闭环。

### 3.2 当前证据的正确读法

- L0 -> L1 已观测到 control bytes `-83.05%`、total wire bytes `-68.95%`，但 prompt tokens `+2.88%`。不得称 Protobuf 自身稳定节省 token。
- L1 -> L2 已观测到 prompt tokens `-55.76%`、prompt-visible bytes `-81.10%`。其解释是 semantic selection 后的局部 hydration，不是 KV cache 命中。
- E4 已证明跨 PID float32 matrix 的数值读取与 selected ID/hydration 变化；它是 repo-local frozen holdout，不是第三方开放域评测。
- Memory 的 `candidate -> compatible -> approved -> projected -> consumed -> effect -> replay` 必须分开。E3 的 `consumed=23` 含 Summarizer 假阳性和过宽 Executor 记账，不能当作真实消费总数。
- E5 的 25-case Adaptive run 虽全通过，但自然 route 全是 table Retriever；semantic Retriever 的自然覆盖主要来自独立 E4，不能夸大为通用自适应能力。
- 现有 prefix registry 的 `cache_hit=True` 仅表示控制面见过兼容 handle，不是 vLLM GPU hit；现有 estimate 也不是观测值。
- 现有 LogitState 路径已能从 Executor completion 提取 top-logprobs、entropy、varentropy、top gap、decision entropy 和 float32 bytes；但当前主要是 telemetry，`LogitStateRef` 尚未形成 publish -> resolve -> consumer decision -> effect -> release 的正式闭环。

### 3.3 不能被 prefix/LogitState 掩盖的前置问题

先把下面问题纳入 P0/P1，否则后续性能或质量结论没有可信底座：

1. 修正 memory 实际消费记账：只有实际渲染到 Prompt 或实际送入执行配方、并收到 explicit consumed-ID receipt 的对象才算 consumed。
2. 将 semantic state 的 logical owner、physical consumer component、downstream target role 分开记账；PID 是事件属性，不能做加法指标。
3. 选择并冻结垂类定位。若主张“企业经营/财报分析”，disease/weather CSV 只能保留为开发或通用诊断数据，除非能给出同一垂类的合理解释和来源证据。
4. 修复或明确收窄 Agent 主张：当前是受控固定角色链，Planner 不生成 DAG，Retriever/Executor 只能在闭集选择，CodeAct 是 bounded DSL/Python，不是无限制自由代码 Agent。
5. 为正式数据建立原始来源、许可、版本、哈希、转换脚本、gold 隔离和冻结 manifest；repo-local 合成样本不能伪装成外部泛化。

## 4. 先做理论与设计判定，再写代码

### 4.1 Prefix 的理论问题

必须先写一份有来源的短理论说明，并用官方 vLLM 文档/源码与可核查文献验证，不凭印象套用术语。至少回答：

- Transformer KV cache 复用要求的是什么：语义相似、文本相同，还是精确 token prefix 相同？
- 为什么 embedding 相似、同一 document hash 或相同 evidence ID 仍不足以保证 KV 可复用？
- 模型、tokenizer、chat template、system prompt、token IDs、position/RoPE、dtype/quantization、engine instance、parallel layout、cache epoch 和服务生命周期分别如何影响兼容性？
- Planner/Retriever/Executor/Summarizer 的 role instruction 不同时，哪些 token 还能构成真实公共前缀？角色说明放在前缀前还是后缀会怎样影响质量与复用？
- prefix cache 可能降低的是预填充计算和 TTFT，为什么不必然降低网络字节、请求 token 数、LLM call 数或端到端总时延？
- 如何区分 `eligible`、`control-plane handle seen`、`request sent`、`engine query`、`observed hit`、`evicted/miss` 和 `estimated saving`？

必须产出一个明确选择，而不是泛泛说“使用 prefix cache”。最低可行且推荐的定义是：

> StateBus 只维护 `PrefixReuseIntent`、精确渲染/分词 identity 和依赖约束下的队列调度；自动 prefix cache 的 KV blocks 始终留在同一个 vLLM engine 内。StateBus 不创建 `KVCacheRef`，不导出 tensor，不转运 GPU 内存。

若研究后提出更强路线，必须证明其必要性、当前版本可用性、真实 consumer 和与本定义相比的净收益；否则不得增加 LMCache、vLLM fork 或跨引擎状态复杂度。

### 4.2 LogitState 的理论问题

先建立如下边界：top-logprobs 的截断分布是模型输出不确定性的代理，不是校准后的“答案正确概率”。JSON grammar、格式 token、温度、候选字符串长度和 top-k 截断都可能让 entropy 或 margin 失真。

必须查阅并引用可核查的 selective prediction、confidence calibration、risk-coverage、entropy/margin uncertainty 或 LLM uncertainty 资料，并回答：

- 哪个决策点的 top-logprobs 对当前系统有可验证含义：Retriever route、Executor route/tool、数值/引用 claim，还是 Summarizer 文本？为什么？
- 当前 `peak entropy`、`aggregated entropy`、`varentropy`、`top gap`、`candidate decision entropy` 各自能和不能说明什么？
- 如何避免将 JSON 括号、引号、结束符的语言模型不确定性误当作业务不确定性？
- 使用的是固定启发式门还是经开发集校准的 gate？阈值怎样选、怎样冻结、怎样防止在 test 上调参？
- 何种决策使 LogitState 产生可量化价值：扩展证据、调用 verifier、要求重新选闭集候选、拒绝不确定 replay，还是只做告警？
- 质量提升、风险下降与额外 token/时延之间如何衡量？何时应 fail closed，何时应不额外消耗资源？

LogitState 不允许降级为“模型输出一句 confidence 文本”。必须至少有一个数值 consumer 读取二进制 `LogitStateRef`，并记录它如何改变后续决策。

### 4.3 三层机制的统一理论模型

后续设计和答辩必须按以下因果关系解释，不能混用：

```text
embedding semantic state：当前任务应看什么证据？
  -> selector 决定 selected IDs 与 hydration

engine-local prefix reuse：相同已选证据的 token 前缀能否少做一次预填充？
  -> same-engine cache 可能降低 TTFT/prefill 工作

LogitState：当前闭集决策是否不确定，值得不值得付出额外核验成本？
  -> confidence gate 决定 expand / verify / retry / accept

MemoryRef：历史上已验证的什么知识或执行策略可以在兼容合同下复用？
  -> compatibility + policy gate 决定 assist/replay/recompute
```

每层都要有独立开关、独立 consumer、独立实验和独立主张。任何两层同时发生时，都不得把收益相互归因。

## 5. Prefix 必须形成的设计、实施计划与验收

### 5.1 先审计现有接入是否真实

审计 `NeuralPrefixIdentity`、`EngineLocalPrefixRegistry`、`compile_prefix_layout()`、`vllm_metrics.py`、`PrefixCacheFeedbackLoop`、`kv_prefix_reuse_v1` 和 continuous runner。逐项给出：已接入、仅测试、仅估算、未接入、错误命名或缺少真实观测。

尤其检查：

- `evidence_prefix_hash` 是否真绑定已渲染的公共前缀，而不只是 EvidencePack/hash 元数据；
- 是否记录 tokenizer 对公共前缀得到的 exact token-id hash 与 token count；
- 同一 EvidencePack 在不同 role 的 prompt 中是否真处于同一开头位置，role suffix 是否只出现在公共前缀之后；
- scheduling 是否尊重任务依赖图，cache-friendly 排序不能改变业务因果；
- `/metrics` 是否有单调 query/hit counters。只有 before/after counter delta 合法时才产生 task-local observed hit；服务生命周期 gauge 不得替代它。

### 5.2 选择最小正式接入

文档必须给出未来实施者可执行的文件级设计、最小变更范围和验收测试；本 Prompt 不实现它。默认方向如下，若偏离必须论证：

1. 从 canonical selected EvidencePack 以确定顺序渲染 `shared_evidence_prefix`；将角色 instruction、任务专属问题和输出 schema 放在 role suffix。
2. 用 `PrefixReuseIntent` 或等价 typed event 记录 engine ID、model/tokenizer/template identity、exact token hash、prompt layout version、source/evidence hashes、cache epoch、eligible reason、dependency-safe priority 和 lease。
3. 将 `EngineLocalPrefixRegistry` 的内部复见改名或加字段，明确它仅表示 `candidate_handle_seen`；真实引擎结果只写入 `observed_query_delta`、`observed_hit_delta`、`observed_hit_rate` 或 unavailable reason。
4. 为每个请求写入 `eligible -> requested -> observed/invalidated` 事件，保留前后 metrics snapshot、TTFT、请求 latency、prompt token count 和 quality result。
5. 只在同一 engine/cache namespace 内调度；engine/model/tokenizer/template/token-ID/epoch 不兼容即 fail closed，不尝试跨 engine 复用。
6. 将 prefix 运行开关与 semantic state、memory、latent 分开；prefix 默认可关闭，latent 始终关闭。

### 5.2.1 Prefix 设计文档必须达到实施就绪度

`02_prefix_engine_local_reuse_design.md` 不能停留在“把公共文本挪到前面”或“调用 vLLM cache”的层面。它必须给出一个未来工程师无需重新做架构猜测即可执行的计划，至少包含下表所列内容；每一项都要注明现有代码事实、拟改动、未证实假设和验收证据。

| 计划部件 | 必须写清的内容 |
| --- | --- |
| 当前基线 | `NeuralPrefixIdentity`、registry、layout、scheduler、metrics parser、feedback、runner 各自的调用点、真实输入/输出、当前是否已被主路径消费；指出错误命名和重复责任。 |
| 精确兼容合同 | `PrefixReuseIntent`、identity、request/observation/invalidated event 的字段、类型、版本、hash 输入、tokenizer/chat-template/model/engine/cache epoch/position/layout invariants；明确哪些字段变化必须 fail closed。 |
| 状态机与时序 | 从 selected EvidencePack 的稳定排序、canonical render、tokenize、eligible、queue、request、before/after metrics、observed hit/miss/unavailable、feedback、expiry 的逐步时序；每一步的 owner、写入位置、是否跨进程和失败路径。 |
| Prompt/layout 改造 | 每个角色的公共前缀和 role suffix 的精确边界、schema 位置、token-ID equality 的比较窗口、如何保证不改变业务语义/质量，以及不能共享的 role-specific 内容如何处理。 |
| 文件级改动表 | 精确到现有模块、类/函数、配置入口和测试文件：新增/修改/删除责任、接口签名变化、上游/下游调用者、兼容策略。不得用“修改 prefix 模块”这种笼统描述。 |
| 观测与记账 | 哪些字段代表 `eligible`、`requested`、`candidate_handle_seen`、`observed query`、`observed hit`、`miss/eviction/unavailable`；metrics snapshot 的原子性/污染条件、TTFT 采集点和不可比较条件。 |
| 配置与迁移 | feature flags、默认值、cache namespace、epoch 清理、旧 telemetry 的兼容和弃用策略；关闭开关时必须回到何种无 prefix 行为。 |
| 测试与实验映射 | 单元、contract、render/tokenize、调度依赖、metrics parser、integration、服务能力 probe、P-A/P-B/P-C 分别测什么；哪些测试不需要模型，哪些需要用户授权。 |
| 降级、回滚与资源 | 计数器不存在、tokenizer 不可用、模板漂移、服务重启、cache 淘汰、质量下降、并发污染时的处理；资源上限、不可做的跨引擎行为，以及如何无损关闭。 |
| 实施顺序与验收 | 最小垂直 slice、每一步前置条件/产物/退出条件、代码评审检查项、最终 claim gate；明确“观测不到 hit”时仍可交付什么，不可交付什么。 |

应优先利用第 1.4 节允许的固定-fixture 渲染与分词辅助核对，来确认现有 layout 和 hash 是否真的对应同一个 token 前缀；核对失败也必须写入计划，不能默默假设未来实现会正确。

### 5.3 Prefix 的实验必须独立完成

至少运行三个层次，不能用一个服务窗口截图代替：

| 实验 | 固定项 | 唯一改变项 | 必须报告 |
| --- | --- | --- | --- |
| P-A 渲染完整性 | evidence、模型、角色、任务 | stable prefix vs unstable/reordered prefix | token-id prefix equality、prompt hash、质量不降 |
| P-B 引擎机制 | 同一请求集、模型、token、质量 | cache-friendly vs cache-hostile schedule | 合法 counter delta、TTFT、request latency、AB/BA 顺序 |
| P-C 端到端 | 任务、质量门、角色和资源 | prefix policy on/off | total latency、stage latency、tokens、质量、实际 cache observation |

P-B 必须有冷服务/独立 cache epoch 与连续服务两种口径，串行重复、ABBA 或随机化顺序、置信区间和失败样本。若服务重启是冷服务实验的唯一办法，先请求用户明确许可；未获许可时只能报告连续服务结果和限制。

通过条件不预设“必然更快”。只有质量等价、引擎计数有效、方向在重复中一致且实验设计无残留污染时，才可宣称 engine-local prefix reuse 带来了对应层面的观察结果。没有总时延优势时，仍可如实保留“实际 hit/TTFT 机制证据”。

## 6. LogitState 必须形成的设计、实施计划与验收

### 6.1 当前实现不是完成态

当前有 `LogitStateRef` 类型、`LOGIT_STATE` storage preference、`serialize_logit_state_v2()` 和 `logit_state_transfer_count` telemetry；这不等于已经完成非文本交接。必须明确补上：

```text
producer completion
  -> extract / validate top-logprobs
  -> publish float32 payload to short-lived shared memory state
  -> register LogitStateRef with contract and lease
  -> independent numeric consumer resolves bytes
  -> calibrated confidence gate issues a bounded decision
  -> downstream expand/verify/retry/accept action leaves observable effect
  -> explicit receipt, state release and failure telemetry
```

### 6.2 必须比较并选择实际 consumer 方案

在设计文档中比较至少下列方案，选择一个主方案并说明为什么另外方案不作为本轮主线：

| 方案 | 数值消费者 | 后续动作 | 主要风险 |
| --- | --- | --- | --- |
| A | Runtime `ConfidenceGate` / 独立 selector | bounded evidence expansion 或 verifier | 可能只是额外成本，需 calibration |
| B | Verifier worker | 对闭集 route/tool/claim 发起复核或 reject | 需定义可验证的 verifier contract |
| C | 下游 LLM 直接看文本化置信度 | 模型自行决定 | 不构成数值状态消费，默认不接受 |

推荐优先实现 A 或 B：Retriever/Executor 在闭集业务选择处生产 LogitState；独立 `ConfidenceGate` 读取 ref 的 float32 概率、entropy/gap 和绑定 metadata，只能提出预注册的 `accept`、`expand_once`、`verify_once`、`selection_retry_once` 或 `fail_closed`。Runtime 执行该动作；最多一次扩展/核验，不能形成无限重试循环。

### 6.3 LogitState contract 与生命周期

主方案必须定义和测试以下字段；禁止只存一个 entropy 标量：

- producer role/step/PID、logical target、physical consumer component/PID；
- task/session/request/prompt hash、candidate surface digest、model/tokenizer/template identity；
- source evidence/hydration digest、decision type、top-k、peak position、sequence length；
- `<f4` payload shape、byte order、blob hash、storage kind、lease、release reason；
- calibration version、threshold policy version、gate result、fallback reason；
- no raw token strings by default；若需要 candidate mapping，只保存闭集 candidate digest 和安全的 position mapping，不保存原始 completion。

top-logprobs 缺失、response schema 不支持、payload 不完整、consumer/model/contract 不兼容或 lease 过期时必须 fail closed：记录 unavailable/rejected，走普通非 LogitState 路径，不得虚报 transfer 或 gate success。

### 6.4 LogitState 的实验与质量门

先在独立开发集完成 calibration；冻结阈值和 policy 后，才能触碰正式 holdout。不要将当前硬编码的 `confidence_proxy < 0.3` 直接包装成理论阈值。

至少运行以下矩阵：

| 实验 | 唯一改变项 | 回答的问题 | 必须记录 |
| --- | --- | --- | --- |
| L-A 离线 calibration | entropy/gap/policy feature | 不确定性是否预测 route/tool/claim 错误 | reliability curve、ECE/Brier 或等价指标、risk-coverage、阈值来源 |
| L-B 生命周期机制 | true ref vs perturb/refusal control | 二进制状态是否被独立 consumer 读取并改变 gate | producer/consumer PID、bytes、selected action、release、counterfactual |
| L-C 受控质量收益 | gate off vs telemetry-only vs calibrated gate | 核验动作是否减少错误或提升 verified quality | 质量、错误恢复、额外 LLM/tool calls、token、latency、无效扩展率 |
| L-D 端到端鲁棒性 | compatible vs incompatible/expired ref | fail-closed 是否有效 | reject reason、fallback 正确性、无污染 |

报告必须同时说明：LogitState 可能提高质量但增加成本；它不必以减少 token/时延为目标。若无预测力或无净质量价值，应保留机制/负结果，将其降级为 telemetry 或不放入 headline，而不是选择性展示成功案例。

### 6.5 LogitState 设计文档必须达到实施就绪度

`03_logitstate_core_chain_design.md` 必须选择一个最小、可验证的闭集决策点作为主路径，例如 Retriever 的检索路由、Executor 的 tool/recipe 选择或一个可验证 claim 的 accept/retry；不能同时模糊覆盖所有生成阶段。选定后，文档必须形成如下完整计划，而不是只列出一个 `entropy < threshold` 规则：

| 计划部件 | 必须写清的内容 |
| --- | --- |
| 主路径决定 | 为什么该决策有可定义的正确/错误标签、候选集如何冻结、top-logprobs 来自哪个 response 字段/位置、JSON/格式 token 如何排除或映射，以及为何没有选择其他 producer。 |
| 数值契约 | `LogitStateRef` payload 的 dtype、shape、byte order、probability normalization、top-k/truncation 语义、candidate-position mapping、metadata/version/hash、兼容性约束和敏感内容最小化；必须列出 producer 与 consumer 的 validate rules。 |
| 生命周期与进程边界 | `completion -> extract -> validate -> StatePool publish -> registry/grant -> independent consumer resolve -> gate -> runtime action -> effect receipt -> release/expiry` 的时序图；每一步的 owner/PID、lease、重试幂等性、异常清理和审计事件。 |
| Gate 与动作合同 | calibration 后的 feature/policy 输入、阈值版本、`accept`、`expand_once`、`verify_once`、`selection_retry_once`、`fail_closed` 的精确定义、最多一次动作的循环防护、普通路径 fallback 和 effect/consumed receipt。 |
| Calibration 方案 | dev/test 隔离、标签定义、样本均衡/失败样本、特征选择、阈值选择与冻结、ECE/Brier/risk-coverage 的计算、无预测力时的退出决定；不得用 holdout 调阈值。 |
| 文件级改动表 | 精确到 refs/contracts、state store、producer role path、independent consumer/ConfidenceGate、runtime orchestration、telemetry、config、tests 和 benchmark runner 的模块与符号；说明输入输出、迁移和调用顺序。 |
| 可观测性与成本 | publish/resolve/reject/release/action/effect 的事件和字段、bytes、latency、额外 LLM/tool calls、token、false trigger、recovery；明确哪些是 mechanism receipt，哪些只能在 L-C 后成为质量主张。 |
| 测试、扰动与失败 | 无 top-logprobs、截断 payload、错误 dtype/hash、过期/跨 task ref、consumer crash、threshold unavailable、incompatible model/template、重复 gate 和 action failure 的测试；L-B/L-D 的扰动控制和 fail-closed 行为。 |
| 配置、回滚与验收 | feature flags、默认 telemetry-only/off、policy/calibration version、资源/时延预算、关闭后的基线行为；按最小 slice 排序的实施步骤、每一步的验收和最终 L-A 至 L-D claim gate。 |

允许用第 1.4 节的辅助核对确认当前 `top_logprobs` 契约、`LogitStateRef` 编解码和 fixed-fixture 生命周期是否真实存在；若要发真实模型请求确认 endpoint 能力，先取得用户许可，并只将结果写为“能力可用/不可用”，不可提前宣称 gate 有效。

## 7. 任务、数据预处理与垂类可信度

### 7.1 先做数据决策

在实现前输出一个明确决定：哪些数据留在正式 headline，哪些只作为 dev/diagnostic，哪些必须替换或补充。默认推荐：

- formal headline：公开、可追溯的企业财报、经营报告、运营指标表格与长文本；
- dev/diagnostic：现有 ACME/BETA、Orion/Nova 等 repo-local synthetic documents，除非能提供真实来源标注；
- 通用 CSV：disease/weather 作为 parser/CodeAct 回归样本，不用来支撑“企业经营垂类”主张。

若选择不同方案，必须说明其赛题收益、数据许可、复现成本和为何比上述更可信。

### 7.2 预处理可以做，但不能预解题

设计并实现可复现、版本化的 ingestion pipeline：

```text
raw public source
  -> source URL/license/retrieval date/version/hash ledger
  -> deterministic parser/normalizer
  -> canonical document/table representation with locator
  -> chunk/evidence catalog and schema profile
  -> task manifest and independent gold
  -> train/dev/test split and frozen checksums
```

预处理允许抽取表结构、日期/单位规范化、文档分段、locator、来源元数据、重复内容去除和安全清洗；不得根据某个任务的 expected answer 预筛唯一目标行、把 gold 写入 corpus metadata、把 route/tool 作为硬编码暗示、或让 Runtime 读取 gold。

每条正式数据至少记录 source、license、raw hash、transformation version、output hash、task author、gold author、split policy 与运行时可见性。Runtime freeze 后的 external holdout 必须与开发集作者/调参过程隔离。

### 7.3 赛题任务设计

至少保留两组真正关联的 10 轮连续任务：

1. 财报/跨期指标链：抽取 -> 同合同策略复用 -> 趋势/比较 -> 已验证 replay/recompute -> 最终可追溯结论。
2. 运营文档/表格链：schema/证据索引 -> 指标与异常 -> 策略复用 -> 跨文档/跨期间综合 -> 受控风险核验。

每轮必须显式声明输入、依赖轮次、可消费对象、不可跳过校验、新产物、质量门和允许的复用等级。连续任务不能只是同一道题重复十次；具体事实复用、策略复用、artifact reuse、validated replay 和 exact replay 必须分开。

## 8. 统一实验架构：不要把所有优化混成一张表

### 8.1 赛题主矩阵

保留并重新做公平的 L0-L3：

| Lane | 机制 | 不允许混入 |
| --- | --- | --- |
| L0 | matched pure-text collaboration | typed ref、semantic selection、memory query |
| L1 | L0 + typed Protobuf/UDS control | semantic StateRef、memory |
| L2 | L1 + embedding SemanticStateRef/hydration | memory/replay；prefix/logit 单独开关固定 |
| L3 | L2 + compatible MemoryRef/replay | 额外业务信息、跨 lane memory |

四 lane 固定任务、数据、角色图、模型、温度、工具、validator、subprocess topology 和 quality floor；只改变规定变量。L0 是同一 harness 内的 matched text comparator 时必须如实标注，不能冒充独立外部系统。

Prefix 和 LogitState 的实验必须另立矩阵。主矩阵中可统一将二者关闭，或固定在完全相同的已验证设置；不得让它们成为 L1/L2/L3 的未控制混杂变量。

### 8.2 指标字典

为每项指标给出定义、分母、采集点、数据源和不可比较条件。至少包括：

- 消息数、control bytes、inline bytes、state-ref descriptor bytes、total wire bytes；
- 每角色 prompt/completion/total tokens、prompt-visible evidence bytes、hydrated evidence bytes；
- semantic/logit state publish/resolve/consume/release count、bytes、shape、dtype、PID 与 effect；
- memory query/candidate/compatible/approved/projected/actual consumed/effect/assist/replay/skipped step/skipped LLM call；
- prefix eligible/requested/observed query/hit/miss/invalidated、exact token prefix length、TTFT、prefill/request/total task latency；
- LogitState calibration quality、gate trigger、verified recovery、false trigger、extra calls/tokens/latency；
- task quality、citation/provenance、validator pass、failure/retry/fallback；
- 冷/热服务状态、run order、seed、model/embedding/tokenizer/vLLM identity、manifest and runtime hashes。

不能把 `candidate` 写为 hit、把 estimate 写为 observation、把 state bytes 写为 token saving、把成功 fallback 写为 feature success。

### 8.3 统计与复现实验纪律

- 正式 API 延迟只使用串行实验；进行足够的独立重复、ABBA/随机化顺序和置信区间或 bootstrap interval。
- 质量不等价时，不能做“更快”的 superiority claim。
- 先冻结 source manifest、gold、threshold、policy、model/config/runtime hash，再跑 test；test 失败后若修改设计，必须创建新版本和新 manifest，旧结果保留。
- 每次正式 run 写入环境、git dirty 状态、container/image、model、endpoint、cache policy、checksum ledger 和完整失败列表。
- 新 run root 不得覆盖 E0-E6 或任何既有 artifact。

## 9. Agent 能力与协议必须如实补强

保持四角色：Planner、Retriever、Executor、Summarizer；Runtime Controller、selector、ConfidenceGate 是系统组件，不计为 LLM Agent。

实现/审计时必须给出每个角色的输入、输出、可见状态、权限、拒绝条件与实际行为证据：

- Planner：bounded semantic retrieval objective，不得假称动态任务图调度；
- Retriever：在闭集 capability 中选择 semantic/table retrieval，正式数据需自然覆盖二者；
- Executor：受控 DSL/bounded Python 和验证，不得假称任意 shell/自由 CodeAct；
- Summarizer：只根据 verified artifact/受控证据写结论，不得生成未经验证数值；
- Controller：负责 Ref grant、lifecycle、quality gate、memory commit、prefix/logit policy 和 telemetry。

赛题要求“握手、能力发现或协议映射”三选一时，当前 registry discovery 可作为最低满足；若增加 wire-level `HELLO/HELLO_ACK`，必须给出版本协商、capability digest、失败测试和真实通信证据，不能只加 proto enum。

## 10. 本 Prompt 的文档化工作阶段与退出条件

### D0：复核审计并建立决定登记册

先将当前审计中的每一项按 `implemented and consumed`、`implemented but unconsumed`、`telemetry only`、`planned`、`historical only` 或 `invalidated historical count` 分类。对每项写明证据路径、当前可说的话、不能说的话、后续验收门和依赖。

退出条件：没有任何“当前存在字段/测试”被误写成“当前有质量/性能收益”；P0/P1 问题和最终垂类选择均有明确 owner/decision gate。

### D0.5：按需进行受限辅助核对并留下可审计记录

只在它能消除一个具体设计不确定性时，使用第 1.4 节允许的核对。每一项必须先写明待确认问题、最小输入、预期可区分的观察和不会证明什么；完成后记录实际命令/文件、结果、环境、是否接触服务和局限。优先级为：静态/fixture 核对 -> 现有测试 -> 仅在已获用户许可时做最小服务 capability probe。

退出条件：Prefix 的现有 layout/token identity/metrics 可用性、LogitState 的现有 payload/Ref lifecycle/top-logprobs 可用性均被标为“已核对”“未核对”或“需授权”，没有将未知实现细节写成事实；未获授权的服务探针只保留为未来执行项。

### D1：形成机制和数据设计文档

写出 Prefix、LogitState、embedding/memory、Agent 边界、数据预处理、两组十轮任务和实验矩阵的详细设计。必须明确 producer、consumer、生命周期、失败路径、文件级实施位置、接口/事件/配置、迁移与回滚、测试、实验和 claim gate；Prefix 与 LogitState 必须分别满足第 5.2.1 和第 6.5 节的实施就绪度表。

退出条件：每个进入赛题主线的机制都有一个真实 consumer 和可证伪实验；不存在“先实现再决定怎么测”的空白。

### D2：形成 future implementation/preregistration 计划

把未来工作拆成 P0/P1/P2：先处理 memory truth、semantic accounting、data provenance 和 fairness，再实现 Prefix/LogitState，再冻结并运行正式实验。每项给出前置条件、变更文件、测试、run root、失败处理和停止条件。

退出条件：未来实施者可以不重新猜测研究问题，直接按文档执行；但本 Prompt 在此停止，不写源码、不跑实验。

### D3：形成包装和交付叙事计划

只写“包装设计”，不写假的结果。将竞赛问题、垂类、难点、方案、亮点、实验图和演示顺序拆为：当前可证实、未来通过某 gate 后可证实、永久禁止。时间减少、TTFT、token、memory/quality 增益必须引用对应的未来 claim gate，不能预填数值。

退出条件：包装稿能够在任何一项实验失败时自动降级措辞，而不是要求结果迎合故事。

## 11. 你必须写入的文档集

不要只在聊天中给建议。创建目录 `docs/planning/contest_rebuild_20260722/`，并在其中写入以下 Markdown 文档；允许添加辅助文档，但不得省略任何一个：

1. `README.md`：文档索引、决策树、依赖关系和阅读顺序。
2. `00_executive_decision_and_packaging.md`：赛题问题、目标用户、垂类决定、难点、方案、亮点、演示故事；用三栏表区分当前可说、通过 future gate 后可说、永久禁止。必须单独说明“时间减少”现在不能写成结果。
3. `01_current_state_and_remediation.md`：基于 `statebus_v2_contest_readiness_audit_20260722.md` 的问题清单、严重性、代码位置、根因、修复方向、完成定义和 P0/P1/P2 顺序。
4. `02_prefix_engine_local_reuse_design.md`：Prefix 理论、候选方案比较、exact token identity、prompt layout、typed intent/event、schedule、真实观测、P-A/P-B/P-C、失败/降级和文件级实施计划；不允许 KV handoff。
5. `03_logitstate_core_chain_design.md`：LogitState 理论、producer/consumer 选择、calibration、Ref contract、shared-memory lifecycle、ConfidenceGate/verifier、L-A/L-B/L-C/L-D、成本/质量权衡和文件级实施计划。
6. `04_vertical_data_preprocess_and_task_design.md`：正式垂类和数据集决定、source/license/hash/transform ledger、预处理边界、gold 隔离、external holdout、两组十轮连续任务，以及现有 repo-local 数据的保留/降级。
7. `05_experiment_matrix_metrics_and_statistics.md`：R0-R12、L0-L3、公平性、指标字典、ABBA/随机化、冷/热服务、样本数/统计、quality gate、artifact/checksum、失败保留和 claim matrix。
8. `06_implementation_plan_and_acceptance.md`：未来工程实施顺序、精确文件/模块、测试、配置开关、迁移、回滚、验收标准、风险和资源依赖；这里写计划，不执行计划。必须逐项引用 `02`、`03` 的文件级计划，禁止用泛化任务列表替代。
9. `07_auxiliary_verification_record.md`：本轮每项辅助核对的目的、授权状态、命令/输入范围、观察、局限、对设计决策的影响；未执行的服务探针写为待授权项。此文件不得报告正式性能、质量或比较性结论。

每个文档必须相互链接，并在开头标记 `事实来源`、`设计假设`、`待验证实验`。最终聊天回复只总结创建了哪些文档、关键决定和仍需用户授权的事项。

## 12. 永久禁止的表述

- “embedding 直接喂给下一个 LLM”或“embedding 就是 KV”。
- “StateBus 在 Agent 间传递 KV/hidden tensor”。
- “控制面 estimate 或 registry hit 就是实际 GPU cache hit”。
- “entropy 低就证明答案正确”或“LogitState 已改善质量”，除非有冻结 holdout 的 calibration 与受控收益实验。
- “memory candidate/approved/artifact reuse 就是 memory hit/replay”。
- “Protobuf 必然省 token”或“单次固定顺序 latency 就证明更快”。
- “四个不同 Prompt 就是自治多 Agent 系统”或“bounded CodeAct 是任意代码执行”。
- “repo-local 样本证明开放域/第三方/生产泛化”。

真正的目标不是让系统看上去拥有更多名词，而是让每一个进入赛题主线的机制都同时具备：明确问题、真实生产者、可验证消费者、受控生命周期、公平对照、质量门、新鲜证据和诚实边界。

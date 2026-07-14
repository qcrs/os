# Prompt: 为 StateBus 设计真正适用的 KV 中间状态机制

## 任务目标

你是一名熟悉 LLM Serving、KV Cache、多 Agent Runtime、共享内存和系统性能优化的研究工程师。

本任务的中心不是复核 StateBus 过去实验，也不是专门分析 LMCache，而是：

> 从 StateBus 当前架构和赛题目标出发，系统调研可用的 KV/神经中间状态方案，筛选真正适合当前系统的技术路线，并形成可以直接实施的详细设计和重构计划。

你需要先广泛检索和建立候选技术图谱，再根据 StateBus 的实际约束筛选，最后只深入研究最匹配的少数方案。LMCache 是参考候选之一，不预设一定采用，也不要让整份调研变成 LMCache 代码分析。

本阶段只做调研、设计和实施规划。不要修改 StateBus 或第三方源码，不要启动完整实验。

## 一、当前项目环境

仓库：

```text
/home/qcrs/statebus/project
```

先阅读以下材料以理解项目和赛题，不需要重新审计或证明这些背景事实：

```text
/home/qcrs/statebus/project/AGENTS.md
/home/qcrs/statebus/project/README.md
/home/qcrs/statebus/project/docs/reference/题目.md
/home/qcrs/statebus/project/docs/constraints/current_feature_scope.md
/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/43_full_qwen3_extended_audit_20260714.md
/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/44_planner_role_and_stability_plan_20260714.md
/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/45_planner_kv_replay_fix_results_20260714.md
```

阅读代码的目的只是理解现有接口和确定改造位置，不是重新做实验真实性审计。重点入口：

```text
v2/runtime/neural_state.py
v2/runtime/logit_state.py
v2/runtime/prefix_feedback.py
v2/runtime/vllm_metrics.py
v2/runtime/role_path.py
v2/runtime/smoke.py
v2/runtime/semantic_plan.py
v2/runtime/replay.py
v2/runtime/driver.py
v2/refs/
v2/retrieval/
v2/statepool/
v2/memory/
v2/control/
v2/benchmark/
scripts/probe_local_vllm_prefix_alignment.py
scripts/vllm_v0_prefix_counter_exporter.py
```

工作树存在用户未提交修改。不得 reset、checkout、clean、回滚或覆盖它们。研究阶段只写本任务的调研和设计文档。

当前运行环境需要纳入方案约束：

- Docker 单容器 + openEuler 交付目标；
- 本地 Qwen3-32B 由现有 vLLM 服务提供，OpenAI-compatible endpoint 为 `http://127.0.0.1:53334/v1`；
- Qwen3-32B 主要占用 GPU 0，local embedding 使用 GPU 1；
- StateBus 当前正式控制面为 UDS + typed Protobuf；
- 短期 dense/embedding state 使用 shared memory，长期对象、artifact 和 replay 使用 mmap/CAS/workspace；
- Runtime 固定流程为 `Planner -> Retriever Fan-out -> Executor -> Summarizer`；
- 可以接受较大重构，但方案必须可部署、可回退、可实验验证。

当前主模型是 Qwen3-32B。可以把 Qwen3-8B、Qwen3-32B 或其他不同规格模型之间的状态协同作为低优先级研究支线，但不要求主方案必须支持跨模型 KV 复用。

## 二、当前 StateBus 中间状态实现

下面是设计工作的已知背景。理解这些能力如何协同，并重点寻找 KV 层的下一步，而不是重新统计旧 artifact。

### 2.1 Semantic、Artifact 和 Memory 状态

当前已有：

- `SemanticStateRef`：embedding、语义检索和 dense state 的引用；
- `CanonicalEvidencePack` / `HydrateManifest`：结构化证据和可恢复 locator；
- `ExecutionArtifactRef`：执行结果、文件和可验证 artifact；
- shared memory、mmap、CAS 和 workspace 数据面；
- memory match、artifact/strategy reuse、validated replay 和 exact replay；
- typed Protobuf/UDS 控制面和 Ref registry。

这些对象解决“传什么语义、如何定位证据、如何跨任务复用”，但它们没有直接保存或传输模型推理产生的 KV tensor。

### 2.2 Planner 和上下文形成

Planner 当前生成 bounded `SemanticTaskPlan`，为以下 retrieval path 提供不同 objective：

- lexical metadata；
- semantic chunk；
- table structure；
- memory。

Retriever 根据 objective 形成 evidence/context，Executor 和 Summarizer再消费这些上下文。Runtime 仍掌握固定拓扑、工具和 route 闭集、fallback、replay、lease 和 GC。

因此 Planner/检索层解决的是“选择什么上下文”，KV 机制应解决“这些上下文计算出的模型状态怎样复用”，二者需要协同但不能混成一个概念。

### 2.3 当前 Prefix/KV 能力

StateBus 当前已经有：

- `NeuralPrefixIdentity`、`NeuralStateHandle` 和 `EngineLocalPrefixRegistry`；
- corpus/evidence prefix hash、cache affinity 和生命周期控制信息；
- `shared_evidence_prefix` prompt layout，把可共享 evidence 放到 prompt 前部；
- cache-friendly scheduling 和 prefix feedback；
- vLLM task-local block query/hit counter delta；
- shared-prefix 与 independent layout 的 TTFT probe。

当前能力本质上是：

```text
StateBus 选择和排列上下文
        -> 构造稳定 token prefix
        -> 同一个 vLLM engine 内部复用已经存在的 KV blocks
```

StateBus 传递的是 prefix identity、上下文引用和调度信息。KV block 仍由 vLLM engine 内部拥有。当前没有：

- StateBus 可寻址的真实 KV tensor object；
- KV 从 vLLM 导出到 StateBus storage；
- Agent/进程/engine 之间的 KV store、transfer、restore；
- 跨服务重启的 KV 持久化；
- 非 prefix evidence segment 的可靠 KV 组合；
- hidden-state tensor 的 producer-consumer 链路。

这一实现已经可以优化同 engine 的重复 prefill，但还不是完整的“KV 中间状态交换层”。本次研究要判断是否值得、以及怎样把它推进到更有价值且适合 StateBus 的程度。

### 2.4 LogitState 的位置

`LogitStateRef` 来自 Executor completion 的 top-logprobs，包含 entropy、varentropy、top gap、peak position 等摘要。它不是 KV，也不是 hidden state。目前主要用于 telemetry，尚未稳定改变 route、tool、retry 或 evidence expansion。

本任务可以讨论它如何与 KV/上下文调度协同，例如用于低置信度时扩展 evidence 或禁止 cache/replay，但不要把 LogitState 当作 KV 主线，也不要让它抢占主要调研篇幅。

## 三、赛题导向

赛题重点包括：

- 多 Agent 低开销结构化通信；
- 非文本中间状态的生成、传递、接收和下游使用；
- 共享记忆和跨任务复用；
- 同任务纯文本/结构化对比；
- token、状态字节、时延、命中率和复用收益；
- openEuler 上可运行、可复现。

研究方案必须帮助 StateBus回答：

1. KV 是否可以成为一种真实的非文本中间状态，而不仅是 vLLM 自动 prefix cache；
2. 哪个 Agent/阶段产生 KV，哪个后续 Agent/请求真正消费；
3. 传递的是 tensor、外部 cache handle、engine-local handle，还是稳定 token segment identity；
4. 它相对当前 shared-prefix 方案增加了什么真实收益；
5. 如何与 semantic state、artifact、memory/replay 分工；
6. 怎样通过实验证明收益，而不是只增加一个“transfer count”。

不得为了赛题措辞强行伪造没有 consumer 的 hidden state或 KV tensor channel。

## 四、调研方法：先广泛检索，再筛选深入

### 4.1 第一轮：建立候选技术图谱

先检索相关论文、开源项目、官方设计文档和公开 benchmark，对可能的路线做宽覆盖。至少包含：

- vLLM native prefix caching、KV connector、KV events、V0/V1 engine；
- LMCache；
- SGLang RadixAttention / HiCache；
- CacheBlend、CacheGen、non-prefix/segment KV reuse；
- Mooncake Store、NIXL、NVIDIA Dynamo；
- MemServe、DistServe、prefill/decode disaggregation；
- prefix-aware routing/scheduling；
- persistent/tiered KV cache；
- 多轮 Agent/RAG workload 的 KV reuse；
- hidden state/activation exchange，仅作为对照路线。

也可以补充其他真正相关的方案。不要一开始就深入单个仓库。

每个候选先只记录：

- 解决的问题；
- 状态对象是什么；
- producer 和 consumer；
- cache identity；
- storage/transport；
- prefix-only 还是支持 arbitrary segment；
- same-engine、cross-engine 还是 cross-node；
- 实验收益和测试条件；
- 接入 vLLM 的侵入程度；
- 对 StateBus 的潜在价值；
- 明显不适合的原因。

### 4.2 第二轮：按 StateBus 约束筛选

用统一标准对候选方案评分：

- 是否形成真实的 Agent 下游消费；
- 是否适合固定四角色流程；
- 是否适合 Retriever evidence/RAG 上下文；
- 是否兼容当前 Qwen3-32B + vLLM；
- 单机双 GPU、Docker/openEuler 条件是否可行；
- 是否需要修改或 fork vLLM；
- GPU、CPU pinned memory和磁盘成本；
- 是否能优于当前 engine-local shared prefix；
- 是否能公平实验和清晰解释；
- 实施与交付风险；
- 通用性及是否容易被认为针对赛题 case 特化。

跨模型状态复用不是第一版筛选的硬条件。若某项技术支持不同模型之间的 prompt、semantic state、draft/verify state、hidden feature 或 KV 转换，可以作为附加价值记录；不能仅因两个模型属于 Qwen3 系列或共用 tokenizer，就认定 KV tensor兼容。

筛选出 2-4 个最适合的方向后，再深入阅读其源码/API/论文。不要对明显不合适的项目做大篇幅代码解读。

### 4.3 LMCache 的定位

本地有 LMCache 源码：

```text
/home/qcrs/statebus/project/third_party/LMCache
```

它只是候选参考之一。先阅读 README、architecture、vLLM integration、KV SDK、observability、CacheBlend和必要的 storage/transport接口，判断它是否进入 shortlist。只有进入 shortlist 后，才深入分析与 StateBus 的适配方式。

重点判断：

- 是否可作为 StateBus 可选 KV data plane；
- 当前 vLLM 版本和 engine 模式是否兼容；
- 是否必须改变 vLLM 启动方式；
- StateBus 能拿到的是 KV handle、token lookup、真实 tensor，还是仅 metrics；
- cross-request/cross-engine reuse 对当前单 engine 流程是否有实际价值；
- CacheBlend 是否适合 evidence segment 重排；
- 引入依赖、native extension和部署复杂度是否值得。

不要默认“LMCache 功能很多，所以 StateBus 应集成 LMCache”。也不要把 LMCache 已实现的能力写成 StateBus 已实现。

## 五、外部访问

可以通过宿主机 `54321` 端口访问网页、论文和代码仓库。先检查代理协议，再按实际情况设置，例如：

```bash
export HTTP_PROXY=http://127.0.0.1:54321
export HTTPS_PROXY=http://127.0.0.1:54321
export ALL_PROXY=http://127.0.0.1:54321
```

如需 clone，只放在：

```text
/home/qcrs/statebus/work/intermediate_state_research/
```

不得自动加入项目 `third_party/`。记录来源 URL、论文信息、仓库 commit、license 和访问日期。网络不可用时明确记录，不凭印象编造细节。

## 六、需要重点分析的问题

### 6.1 什么才是适合 StateBus 的 KV 中间状态

请比较并判断以下定义：

1. **Engine-local handle**：StateBus只维护 prefix/segment identity和调度，KV由同一 engine拥有；
2. **External KV reference**：StateBus持有可寻址 `KVCacheRef`，KV由 LMCache/其他 cache service存储；
3. **Transferable KV object**：StateBus可以通过 shared memory、CPU pinned memory、IPC/NIXL等真实传递 tensor；
4. **Evidence-segment KV**：Retriever输出稳定 evidence segments，服务层按 segment identity复用或组合 KV；
5. **Prefill artifact**：将预填充结果作为有兼容合同、生命周期和复用策略的系统 artifact。

分析它们对 StateBus 的收益、成本和语义是否成立，并给出推荐定义。必要时可将 engine-local 和 external KV 分成不同 Ref 类型，避免一个 `NeuralStateHandle` 同时表示两种完全不同的能力。

### 6.2 跨 Agent KV 复用是否真的可行

Planner、Retriever、Executor、Summarizer 的 system prompt、response schema和任务不同。请分析：

- 哪些 token prefix 可以真正相同；
- shared evidence 应放在 system、user 还是独立稳定 segment；
- role instruction 在前会不会破坏共享 prefix；
- 不同 role 能否复用同一 evidence segment KV；
- position、RoPE、attention mask、chat template变化如何影响兼容性；
- 应共享完整 prompt KV，还是只共享稳定 corpus/evidence chunks；
- KV reuse 是同一个请求链内有价值，还是跨任务/跨轮次更有价值。

需要给出具体 prompt/token layout 示例，而不是只写“复用公共上下文”。

### 6.3 KV identity 和安全边界

设计候选 identity，至少考虑：

- model id/revision；
- tokenizer和chat template；
- attention/KV layout、dtype、block size和parallel rank；
- RoPE/position和token ids；
- evidence/source hash；
- tenant/task/cache salt；
- role/prompt contract version；
- generation config中真正影响兼容性的字段；
- 生命周期、lease、pin、eviction和GC。

错误复用必须 fail closed。分析 stale cache、模型重启、partial hit、corpus更新、跨 case污染和多租户泄露。

### 6.4 与现有状态系统如何协同

明确以下对象的分工和优先级：

```text
SemanticStateRef     -> 选择/表达证据
ExecutionArtifactRef -> 保存工具执行结果
Memory/Replay        -> 跨任务复用语义、策略或验证产物
KV/ServingStateRef   -> 避免重复模型 prefill
LogitStateRef        -> 表达输出不确定性
```

说明一次请求中它们怎样连接：Planner objective如何形成 evidence；evidence identity如何生成 cache key/prefetch hint；cache hit如何减少 prefill；cache miss如何回退；exact replay何时直接绕过模型；LogitState是否会影响下一轮 evidence或cache策略。

### 6.5 真实收益在哪里

重点分析适用 workload：

- 多 Agent共享长 corpus/evidence；
- 同任务不同角色读取相同证据；
- 10轮连续任务；
- 同一财报/CSV上的不同问题；
- RAG evidence顺序变化；
- exact replay、validated replay和cache hit的组合；
- 单 engine已开启 prefix caching时，外部 KV layer还有多少增量价值。

不要只讨论理论 token savings。要区分 prompt token计费、实际 prefill计算、TTFT、端到端时延、吞吐和内存/传输成本。

### 6.6 低优先级：不同模型之间的状态协同

可选研究 Qwen3-8B 与 Qwen3-32B 等不同模型之间能否共享或转换某些中间状态，但不得为了覆盖该方向拖累主方案。至少区分：

- 相同 tokenizer下复用 token ids或稳定 evidence segment；
- 共享 semantic/evidence/artifact state；
- 小模型规划、路由、检索，大模型执行或总结；
- speculative decoding中的 draft/verify协同；
- hidden state projection或 learned adapter；
- KV tensor直接复用或转换。

重点判断模型层数、hidden size、KV head数、head dimension、attention layout、权重、RoPE/position、dtype和并行布局是否兼容。默认假设不同参数规模的模型不能直接消费彼此的 KV tensor；共用 tokenizer只能说明 token identity可能一致，不能说明每层 K/V 数值和形状兼容。

如果存在可靠的跨模型 KV转换、蒸馏、投影或复用研究，说明：

- 它转换的具体对象；
- 是否需要训练额外 adapter；
- 转换成本是否低于重新 prefill；
- 质量损失和适用上下文长度；
- 是否支持当前 Qwen3-8B/32B 与 vLLM环境；
- 对 StateBus 多 Agent流程的明确 consumer和收益。

如果没有足够证据或工程上不划算，直接给出不纳入第一版的技术原因即可。推荐架构不应因此复杂化。更现实的跨模型方案可以是共享 `SemanticStateRef`、evidence/artifact/memory和任务分工，而不是共享原始 KV tensor。

## 七、候选架构与最终选择

至少比较以下路线，也可以组合或增加方案：

### A. 强化当前 vLLM engine-local prefix路线

继续优化 shared evidence layout、cache affinity、调度、prefetch hint、task-local counters和生命周期，不引入外部 KV tensor store。

### B. StateBus + 外部 KV cache data plane

StateBus 保留 Protobuf/Ref/semantic/memory控制面，通过 adapter接入 LMCache或其他 KV service，实现可寻址、可加载、可观测的 KV reuse。

### C. Evidence segment / non-prefix KV reuse

把 `CanonicalEvidencePack` 的稳定 evidence segment映射成 token/KV chunk，使用 CacheBlend、Radix/segment cache或选择性重算处理位置和拼接问题。

### D. 更深的 tensor/hidden-state路径

直接导出、传输或保存 KV/hidden activation。只有存在清晰 consumer、兼容合同和收益时才推荐，否则明确放弃。

最终必须：

1. 选出一个适合当前 StateBus 的主方案；
2. 给出一个低风险 fallback方案；
3. 说明为何没有选择其他方案；
4. 明确最终第一版究竟传递什么对象；
5. 说明它相对当前 shared-prefix实现增加的能力。

不要只给多个路线让用户自行选择，也不要简单写成几个抽象 Phase。

## 八、详细设计要求

推荐方案必须细化到可以开始编码，至少包含：

1. 当前架构到目标架构的组件图；
2. 一次 cold miss、warm hit、partial hit、exact replay的时序；
3. StateBus control plane与KV data plane边界；
4. `ServingStateRef`、`KVCacheRef`或其他 contract草案；
5. canonical identity和compatibility signature；
6. producer、consumer、store、lookup、prefetch、restore、evict和GC；
7. Planner、Retriever、Executor、Summarizer各自读写什么；
8. prompt/evidence segment layout；
9. adapter接口和vLLM/外部cache集成点；
10. feature flag、fallback和故障隔离；
11. telemetry字段和避免伪指标的方法；
12. Docker/openEuler进程拓扑、端口、SHM、CPU/GPU内存预算；
13. 对现有 semantic state、replay、UDS、Planner和benchmark的影响；
14. 旧 `NeuralStateHandle` 如何迁移、重命名或保留；
15. 建议修改/新增的具体文件和核心符号。

跨模型能力作为可选附录说明：第一版是否明确禁止跨模型 KV lookup；compatibility signature如何拒绝 model/revision/layout不一致；未来如果增加转换 adapter，接口应放在哪里。不要把它设成主链路的交付前置条件。

关键 contract请给 JSON/Protobuf/Python protocol草案。重要数据流给出伪代码或时序图。

## 九、实施计划

给出按依赖顺序排列的具体工作包，不要停留在“Phase 1/2/3”标题。每个工作包写清：

- 要实现的能力；
- 涉及的文件和接口；
- 不做什么；
- 测试；
- 验收 gate；
- 风险和回滚点；
- 是否需要修改或重启 vLLM；
- 是否需要编译 LMCache/native extension；
- 对当前已通过功能的回归范围。

计划至少覆盖：

1. 最小可运行 KV中间状态闭环；
2. 与当前 engine-local prefix路径共存；
3. 真实 consumer和行为证据；
4. observability；
5. targeted smoke；
6. formal/continuous/compare验证；
7. openEuler交付；
8. 若首选依赖不兼容时的替代实现。

可以给大致人日和依赖关系，但不要用时间估算代替技术细节。

## 十、验证设计

设计能证明因果关系的最小实验矩阵，本阶段只写方案、不执行：

- external text baseline；
- StateBus no KV reuse；
- 当前 vLLM-native shared prefix；
- 推荐的新 KV方案；
- cold/warm、hit/miss、partial hit；
- same corpus/different corpus；
- same role/cross role；
- stable evidence/reordered evidence；
- 10轮 continuous；
- cache disabled/identity perturbed/model mismatch；
- quality和oracle/污染检查。

若调研认为跨模型状态协同值得继续，再增加 Qwen3-8B producer / Qwen3-32B consumer及反向组合的独立实验设计；否则只验证 model mismatch 必须 fail closed，不要求实际运行跨模型实验。

至少记录：

- request/block/token cache hit；
- store/load/transfer bytes；
- prefill token计算量；
- TTFT、ITL、端到端时延和吞吐；
- GPU/CPU/pinned memory；
- Agent/LLM/tool调用数；
- prompt token和completion token；
- quality gate；
- fallback、reject和stale count。

正式时延使用串行 repeats，报告 median、p90/p95和离散度。不能用服务生命周期累计 gauge冒充 task-local hit，不能用估算 token冒充实际 KV load，也不能因单次 TTFT下降就宣称系统端到端加速。

## 十一、输出文档

只输出两份主文档，并分章节持续写入，不需要拆成十几个小文件：

```text
docs/improvement/21_intermediate_state_architecture_research_20260714/
├── 01_kv_intermediate_state_research.md
└── 02_statebus_kv_design_and_implementation_plan.md
```

第一份包含：

- 当前 StateBus KV/Prefix背景摘要；
- 候选技术图谱；
- 来源和引用；
- 初筛标准；
- shortlist深入分析；
- 对比矩阵；
- 最终技术选择依据。

第二份包含：

- 推荐架构；
- contract和数据流；
- 与当前系统的协同；
- 文件级改造方案；
- 实施工作包；
- 风险、fallback和迁移；
- 最小及完整验证矩阵；
- 当前可宣称与完成后可宣称的边界。

如果内容较长，先创建文档骨架，再完成一个章节就写入一次。不要额外生成大量重复摘要、日报或中间文档。

## 十二、结论纪律

必须严格区分：

- vLLM engine-local prefix reuse；
- StateBus prefix identity和调度控制；
- 可寻址 external KV cache；
- 实际 KV tensor store/load/transfer；
- hidden-state activation；
- top-logprobs派生的 LogitState；
- semantic memory和artifact replay。

禁止：

- 把 LogitState写成 hidden state；
- 把 prefix hash写成 KV tensor；
- 把 LMCache能力直接写成 StateBus能力；
- 没有 downstream consumer却宣称状态传递有效；
- 不检查模型/tokenizer/position兼容性就设计跨请求 KV复用；
- 用 expected facts、route、tool、candidate key或case id制造效果；
- 只因为方案“创新”就忽略部署和实验可行性。

## 十三、完成条件

完成调研和设计后暂停，不修改实现、不启动实验。最终会话回复重点汇报：

1. 最推荐的 StateBus KV中间状态定义和架构；
2. 它相对当前 shared-prefix路径的增量价值；
3. LMCache是否适合、适合到什么边界；
4. 第一批应修改的文件和接口；
5. 最大技术风险；
6. 最小验证矩阵；
7. 开始实施前需要用户确认的重大依赖或服务改动。

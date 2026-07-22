# StateBus KV Cache / Hidden-State / Latent-State 传递设计与实验执行方案

更新时间：2026-07-20  
状态：设计已完成，代码与正式实验尚未开始  
适用范围：`v2` 后续研究支线，不替代当前竞赛证据闭环  

## 0. 结论先说

当前 Qwen embedding `StateRef` 已经满足赛题对“真实非文本中间状态”的基本要求，但它主要是检索选择信号，状态传递创新性有限。若需要再做一项与 StateBus 主线契合的创新，推荐实现 **可验证双通道 latent evidence handoff**：Retriever 选出长叙事证据后，由模型 backend 把证据生成成一小段 aligned latent embeddings，经现有 StatePool/UDS/Ref 体系交给下游 Summarizer；同时保留极小的 evidence ID/locator anchor 供授权、引用和验证。

这项能力不要求放弃 vLLM，也不允许被当前 vLLM OpenAI API 的能力边界限制。StateBus 定义 backend-neutral 的 `LatentStateRef` 和消费合同；第一版用 HuggingFace Transformers 获得真实 `output_hidden_states` / `inputs_embeds`，当前 vLLM 继续服务普通文本角色，未来有可靠的 vLLM native connector 时接入同一合同。实验是独立 lane，产品架构不是另一套系统。

建议只保留三层清晰边界：

| 层级 | 当前决策 | 解决的问题 | 竞赛定位 |
|---|---|---|---|
| S0：Semantic State | 保留当前 Qwen embedding + shared memory `StateRef` | 语义选择、证据裁剪、跨进程非文本状态消费 | 正式基础证据 |
| L1：Validated Latent Handoff | 推荐，接入现有 retrieval -> summarizer 链路 | 避免长叙事 evidence 被上游压成文本摘要、下游再次编码，同时保留可验证 anchor | 优先创新补充实验 |
| K1：External KV | 暂不实现；出现真实重复 prefill/跨 engine 需求后再评估 LMCache | 避免完全相同 token prefix 被重复 prefill | 后续性能支线，不是当前 Agent 状态创新 |

第一原则不是“都实现”，而是每种机制必须对应不同的真实问题：

- embedding 回答“应该找回和传递哪些证据”；
- KV 回答“同一段 token 前缀是否需要再次做 Transformer prefill”；
- latent hidden 回答“上游思考是否必须先解码为文本才能交给下游”；
- MemoryRef 回答“跨任务的事实、策略和已验证产物能否长期复用”。

它们不是同一个对象，也不能用同一组命中率混合汇报。

本方案的实施优先级是：

1. 先完成当前竞赛证据闭环并冻结 Runtime；
2. 用现有 StateBus Runtime 实现 L1 的最小 HF backend 样机；
3. L1 达到质量、真实消费和通信门槛后，才进入正式补充实验；
4. 不做 KVCOMM、C2C、Mooncake 的第一版集成；
5. 不修改或重启当前 `127.0.0.1:53334` 的 Qwen3-32B 服务。

### 0.1 每项实现必须对应一个真实问题

| 实现 | 触发它的真实需求 | 当前采用方式 | 不应为了什么继续扩张 |
|---|---|---|---|
| typed UDS + Protobuf | 多 Agent 文本约定容易歧义，Ref、权限、错误和版本无法机器校验 | 控制面只传合同、handle、状态和错误；payload 走对应数据面 | 不为了减少几字节 header 自创协议 |
| tiered backend | 短命 dense tensor、长期 replay 对象和执行产物的生命周期、大小及访问方式不同 | embedding 用 shared memory；长期对象用 mmap/CAS；执行结果用 workspace + artifact + CAS | 不为了“多后端”数量让同一对象随机换 backend |
| 多进程 Runtime | 必须证明状态跨隔离边界消费，并隔离角色失败、权限和资源 | 固定 Driver/worker 拓扑，记录 producer/consumer PID 与清理 | 不为了 Agent 数量或进程数量本身加分 |
| bounded CodeAct | 固定 DSL 无法覆盖所有离线分析算法，但任意 shell/Python 风险过高 | LLM 在注册执行能力中选择 DSL 或受控 Python，经过 AST、bwrap 和 validator | 不把所有任务切成 Python，也不把它混入通信因果实验 |
| durable memory/replay | 连续任务反复抽取、计算和验证同一事实或产物 | 质量通过后 commit，后续 query -> compatible -> consume -> effect/replay | 不把一次 query 或候选召回称为复用 |
| semantic `StateRef` | 下游只需少量相关证据，传全量文本会重复 hydration，纯 ID 又没有数值选择证据 | embedding matrix 经 shared memory 跨进程 top-k，并改变 selected IDs | 不把 embedding 声称为 LLM hidden/KV |
| external KV | 同模型、相同 token prefix 在本地 APC 不可用时仍被重复 prefill | 仅在 K1 独立实验中用 engine connector 做真实 tensor store/load | 不用于语义检索、长期记忆或不同 prefix 的自动复用 |
| latent hidden | 中间 Agent 被迫先解码文本、下游再编码，可能丢失连续表示 | 仅在 L1 独立实验中传 compact aligned hidden，并由 `inputs_embeds` 真实消费 | 不声称任意异构模型免训练兼容 |

因此，结构化协议、多后端、多进程、CodeAct、memory 和 semantic state 都有不同的必要性；合理性取决于是否存在对应消费链和单变量证据，而不是代码中是否出现了更多组件。L1 只在当前证据闭环冻结后作为状态创新补充，K1 继续保持有条件 Future Work；二者都不混入当前竞赛因果主矩阵。

### 0.2 独立实验 lane，不是独立产品路线

必须把两种“单独”区分开：

| 范围 | 决策 | 原因 |
|---|---|---|
| 产品/代码架构 | 不另起路线 | 继续使用当前 Adaptive Runtime、四角色、CapabilityGrant、Ref registry、LayeredStateStore、UDS worker、telemetry 和 validator |
| 模型执行 backend | 可插拔 | 普通角色可继续走当前 vLLM；需要 hidden access 的 producer/consumer 第一版走 HF，后续 vLLM connector 实现同一接口 |
| 实验 | 单独 latent lane | 不把 hidden、memory、CodeAct 和 L0-L3 同时打开，才能判断 hidden 本身是否有价值 |
| 任务数据 | 新增小型 long-narrative holdout | 复用当前 offline analysis domain、manifest 和 evidence contract，但不把不需要 hidden 的表格任务强行改造 |

第一版只接一条现有角色边：

```text
Retriever capability
  -> CanonicalEvidencePack
  -> semantic StateRef top-k（当前已有）
  -> selected long narrative evidence
  -> Retriever evidence-assimilation phase（同一逻辑 Retriever 的职责增强）
       text lane: compact evidence analysis
       latent lane: aligned latent thoughts，不先解码文本
  -> LatentStateRef(shared_memory/memfd) + evidence ID/locator anchors
  -> Summarizer model worker consumes inputs_embeds
  -> ClaimSet
  -> 当前 ClaimSetValidator 使用原始 EvidencePack 做外部验证
```

这里不增加第五个 Agent，也不把 `use_hidden_v1` 注册成一个业务 capability；latent 是 Retriever 输出状态到 Summarizer 输入状态的一种 handoff policy，而不是 Planner 可以直接执行的工具。表格抽取、精确数值和 CodeAct 继续使用可解释 artifact。

### 0.2.1 Planner 提出意图，Runtime 最终激活

可以让 Planner 判断当前任务是否值得使用 latent，但不能让 Planner 单方面打开 tensor path。Planner 在 retrieval 之前运行，只能看到任务目标、输入合同、允许的角色边和 capability surface；它看不到最终 selected evidence 的真实长度、类型、冲突情况，也不知道执行时的模型兼容性、GPU/共享内存预算和 backend 健康状态。

因此采用两阶段决策：

```text
Planner
  -> 对 Retriever -> Summarizer 边提出 handoff_intent
     requested_policy = text | latent_assist | auto
     rationale = long_context | cross_span_relation |
                 conflict_or_qualifier | exact_artifact_preferred

Runtime after retrieval
  -> 检查部署开关和 TaskEnvelope 是否允许
  -> 检查 Planner 请求与 ApprovedPlan
  -> 检查实际 selected evidence 类型、token 数和结构
  -> 检查 producer/consumer backend capability
  -> 检查模型、alignment、position、预算、TTL 和 validator
  -> ACCEPT latent_assist，或 REJECT/FALLBACK 到当前 text path
```

建议使用每条角色边的通用合同，而不是按任务 ID 或业务公式写分支：

```text
AdaptiveTaskEnvelope.allowed_handoff_policies
PlanStep.handoff_intent.edge
PlanStep.handoff_intent.requested_policy
PlanStep.handoff_intent.rationale_codes
ApprovedPlan.handoff_decision
```

Planner 只能选择 `text`、请求 `latent_assist` 或用 `auto` 把选择留给 Runtime；不能输出 tensor handle、storage backend、model device 或绕过 compatibility gate。Runtime 的最终审计记录至少包含：

```text
requested_policy
effective_policy
planner_rationale_codes
runtime_gate_checks
activation_reason | rejection_reason | fallback_reason
selected_evidence_tokens / evidence_kind
producer_backend / consumer_backend
```

默认使用独立开关，且它只是部署侧上限，不能扩大 TaskEnvelope 权限：

```text
STATEBUS_LATENT_HANDOFF_MODE=off|shadow|planner_assist|force
```

| Mode | 行为 | 用途 |
|---|---|---|
| `off` | 完全沿用当前 text/structured path，不生产 latent | 当前竞赛主线和默认值 |
| `shadow` | 运行 latent 生成、传递、消费和 validator，但外部结果仍取当前 text path | 上线前可观测性与等价性检查 |
| `planner_assist` | Planner 请求，Runtime gate 通过后才启用；否则确定性回退 text | L1 证明成立后的产品模式 |
| `force` | 仅跳过 Planner 请求条件，不跳过权限、兼容、预算或 validator | 容器内诊断；禁止用于正式 headline |

正式实验不能用 `force` 的通过结果证明 Planner 会选择，也不能把 Runtime 拒绝后成功的 text fallback 计作 latent success。当前 contest evidence closure 期间该开关必须保持 `off`。

### 0.3 当前还没有天然 hidden producer，必须先补角色语义

当前 `RolePathRunner` 中的 Retriever LLM 主要选择 route、tool 和 retrieval objective；真正的 evidence fan-in、embedding top-k 和 hydration 在 Runtime/adapter 中完成。`RolePathRunner.build_claim_set()` 随后把 `evidence_text` 放进 Summarizer Prompt。因而当前链路已有真实 semantic tensor，但还没有一份“Retriever 已经形成、却被迫解码成文本”的生成模型 hidden state。

这给出一个明确决策门：

- 如果不准备让 Retriever 在检索后真正阅读并分析 selected evidence，就不要实现 hidden handoff；额外启动一个模型只为制造 tensor 是伪需求。
- 如果需要提升 Retriever 职能，使它不仅选工具，还负责吸收长叙事证据并向 Summarizer 交接分析状态，那么 text/latent 两种 handoff 都有自然定义，L1 才成立。

推荐第二种，但只在 long-narrative holdout 中启用。它提升的是现有 Retriever 的语义职责，不是增加新角色，也不是按 task ID 写死行为。激活条件来自通用合同：`evidence_kind=narrative`、selected evidence 超过预注册 token 门槛、producer/consumer backend 都声明 latent capability；不符合时继续走当前 full-text 路径。

最小接入面必须沿用当前模块边界：

| 当前实现位置 | 直接复用 | 最小新增 |
|---|---|---|
| `v2/runtime/adaptive_dispatcher.py::_consume_retrieval_semantic_state` | semantic top-k、跨进程 selection、EvidencePack fan-in | selection 完成后可选调用同一 Retriever 的 evidence-assimilation phase，并发布 latent ref |
| `v2/contracts/models.py::RefKind` / `RefRegistryEntry` | ref identity、storage/status 小索引 | 增加 `LATENT_STATE`，不修改 `EXECUTION_ARTIFACT` 语义 |
| `v2/state/LayeredStateStore` | shared memory/memfd/mmap 的 state bytes、sidecar 和清理 | latent tensor contract metadata 与短 TTL |
| `v2/control` UDS + `RefHandle` | typed request、PID、lifecycle event | 新的 latent role worker/operation；Protobuf 仍只传 handle，不 inline tensor |
| `v2/runtime/adaptive_dispatcher.py::_dispatch_summarizer` | CapabilityGrant、verified evidence/artifact scope | 把 optional latent ref 交给支持该能力的 model backend |
| `v2/runtime/role_path.py::build_claim_set` | 当前 task、artifact、evidence ID/locator prompt contract | latent lane 去掉 prompt 中的 `evidence_text`，通过 `complete_with_latent()` 生成相同 ClaimSet |
| `ClaimSetValidator` | 原始 EvidencePack/ArtifactRef 的引用、数值和状态验证 | 不改 validator 语义，只记录 latent/fallback provenance |

禁止建立绕过 `AdaptiveCapabilityDispatcher` 的独立 demo orchestrator，再把结果写回报告。可以先做 upstream HF readiness probe，但正式 StateBus evidence 必须经过上表主链路。

## 1. 为什么需要先把四类状态分开

### 1.1 Semantic embedding

生产者通常是 embedding encoder，消费者是 Retriever、MemoryProxy 或 Runtime selector。它是一个语义索引/选择信号，不是大模型的内部思考，也不能直接当作普通 LLM 的 `past_key_values`。

当前 StateBus 已有的真实链路是：

```text
Retriever 生成 embedding/semantic matrix
  -> StatePool(shared_memory)
  -> 只在 Protobuf 中发送 RefHandle
  -> 另一个 worker 解析并读取 tensor
  -> 改变 selected evidence IDs / hydration
```

这条链路对赛题“非文本中间状态传递”是成立的，前提是正式证据继续展示 producer PID、consumer PID、真实字节、selected IDs 和行为变化。

### 1.2 Transformer KV cache

KV cache 是每一层 attention 的 Key/Value 张量。它是对特定模型权重、特定 token 序列和特定位置编码已经完成 prefill 的计算结果。

KV 的消费者不是 Planner 或 Retriever，而是推理引擎的 attention backend。Agent 不应该在 Prompt 中选择 `use_kv_cache_v1`；Runtime/engine connector 应根据精确兼容性自动决定是否加载。

KV 解决的是计算复用，不是语义记忆：

```text
相同模型 + 相同 token prefix + 兼容位置/布局
  -> 已有 KV 可加载
  -> 少做一部分 prefill
  -> TTFT 可能下降
```

### 1.3 Hidden/latent state

hidden state 是某一层或末层的连续向量。LatentMAS 将末层 hidden 映射回输入 embedding 空间，再通过 `inputs_embeds` 自回归产生若干 latent thoughts；同时保留所有层 `past_key_values` 作为 working memory。

它解决的是中间 Agent 必须输出自然语言的问题，但代价是：

- 消费者必须支持 `inputs_embeds` 或直接的 `past_key_values`；
- 模型、层形状、位置语义和对齐方法高度耦合；
- tensor 不可读，错误定位和安全审计更难；
- 跨进程通常发生 GPU -> CPU/shared memory -> GPU 搬运；
- 异构模型需要训练 adapter，不能声称自动兼容。

### 1.4 Shared memory / durable memory

StateBus 的 `MemoryRef` 保存的是可解释、可检索、可验证的事实、摘要、策略和 artifact lineage。KV/hidden 的生命周期短、模型耦合强，不应直接进入长期语义记忆索引。

正确关系是：

```text
MemoryRef: 跨任务长期复用，按主题/标签/语义检索
StateRef: 当前任务内的结构化或稠密中间状态
KVCacheRef: 推理引擎计算缓存，严格精确兼容，短 TTL
LatentStateRef: 模型内部连续表示，严格模型/adapter 兼容，短 TTL
ExecutionArtifactRef: 工具执行产物，可验证、可 replay
```

## 2. 当前 StateBus 到底实现了什么

当前代码已经有：

- `NeuralPrefixIdentity`：记录 corpus/evidence prefix 的稳定身份；
- `NeuralStateHandle`：记录 engine、session、model、tokenizer 和 prefix hash；
- `EngineLocalPrefixRegistry`：登记同一引擎中的候选 prefix 复用机会；
- cache-friendly prompt layout 和任务排序；
- vLLM APC 指标观测与估算字段；
- 明确的 `no_kv_tensor_export` claim boundary。

主要实现位于：

- `v2/runtime/neural_state.py`
- `v2/runtime/role_path.py`
- `v2/runtime/prefix_feedback.py`
- `v2/benchmark/kv_prefix_schedule.py`

当前没有：

- 从 vLLM 导出 KV tensor；
- 将 KV tensor 存入 StatePool、LMCache 或外部 store；
- 另一个进程/engine 加载并消费 KV tensor；
- hidden state export/import；
- 通过 `inputs_embeds` 继续生成；
- 跨模型 latent/KV adapter；
- KV/hidden 的真实 tensor 字节、store/load latency 和消费事件。

因此当前只能称为 **Engine-Local Prefix Reuse control plane / APC observation**，不能称为“Agent 间 KV cache 传递”。

还需注意：`EngineLocalPrefixRegistry.ensure_handle()` 返回的 `cache_hit=True` 只是“相同登记键已存在”，不是 vLLM GPU cache hit。未来如果继续保留该字段，应在证据层拆成：

```text
candidate_registered
reuse_requested
engine_hit_observed
engine_miss_observed
invalidated
```

在当前竞赛闭环完成前不建议重命名或重构这些对象，以免污染冻结实验；只需继续保持 claim boundary。

### 2.1 本地 prefix 仍然有意义，且与 latent 正交

当前本地 prefix 路线解决的是“多个请求在同一 vLLM engine 内是否具有完全相同的 token prefix，从而有机会复用 APC”；latent 路线解决的是“Retriever 的中间分析是否必须先解码成文本再交给 Summarizer”。二者作用阶段和消费者都不同：

```text
prefix/APC: request text -> engine prefill optimization
latent:     Retriever state -> Summarizer semantic conditioning
```

因此 latent 启用后，本地 prefix 仍用于 Planner、普通 Retriever、CodeAct、text fallback，以及 Summarizer 中保持不变的 system/task/anchor prefix。现有开关继续独立保留：

```text
STATEBUS_PREFIX_ALIGNMENT_MODE=independent|shared_evidence_prefix
STATEBUS_LATENT_HANDOFF_MODE=off|shadow|planner_assist|force
```

不能用一个开关隐式打开另一个，也不能在第一次 latent 因果实验中同时改变 prefix policy。`EngineLocalPrefixRegistry.cache_hit` 仍只代表控制面候选再次出现；只有 vLLM 原始 metrics/engine event 才能支持真实 GPU APC 命中声明。若后续做组合实验，必须先分别证明 prefix-only 和 latent-only，再固定其中一个测试组合效应。

## 3. 当前环境的真实量级

2026-07-20 只读检查得到：

| 项目 | 当前值 |
|---|---|
| vLLM API | `0.7.3` |
| PyTorch | `2.5.1+cu121` |
| Transformers | `4.51.3` |
| 服务模型 | `/data/models/Qwen3-32B`，served name `qwen3-32b` |
| 服务端口 | `127.0.0.1:53334` |
| max model len | `8192` |
| hidden size | `5120` |
| layers | `64` |
| KV heads | `8` |
| head dim | `128` |
| dtype | BF16 |

完整 KV 的理论 payload：

```text
bytes_per_token
  = layers * (K + V) * kv_heads * head_dim * dtype_bytes
  = 64 * 2 * 8 * 128 * 2
  = 262,144 bytes
  = 256 KiB/token
```

所以：

| 对象 | 理论 payload，不含 allocator/block 元数据 |
|---|---:|
| 1 token 完整 KV | 256 KiB |
| 40 token 完整 KV | 10 MiB |
| 4096 token 完整 KV | 1 GiB |
| 8192 token 完整 KV | 2 GiB |
| 1 token 末层 hidden | 10 KiB |
| 40 个末层 hidden vectors | 400 KiB |

这说明“KV 是非文本，所以通信更小”是错误推理。与几十或几百个文本 token 相比，完整 KV 可能大几个数量级。KV 是否有净收益只能由：

```text
saved_prefill_compute
  - store_cost
  - transfer_cost
  - load_cost
  - compatibility/lookup cost
```

决定。

## 4. 本地论文与开源实现审计

所有参考仓库位于项目本地 `third_party/`，由 `.git/info/exclude` 排除，不进入 StateBus 提交。除预先存在的 LMCache 外，本轮新增仓库均为 shallow clone。

### 4.1 固定研究快照

| 项目 | 本地路径 | 固定 commit | 许可证事实 | 第一版决策 |
|---|---|---|---|---|
| LatentMAS | `third_party/LatentMAS` | `9a9e4d331eb11430bd9e64754c6b252b06d73031` | `LICENSE` 为 Apache-2.0 | 只参考 HF latent 算法和实验设计 |
| C2C | `third_party/C2C` | `113c3a9b2538cbf096a0477e1ec99ae2a2e0d12a` | `LICENSE` 是 Apache-2.0，但 `pyproject.toml` 声称 MIT，元数据冲突 | 不复制；仅作为异构模型研究参考 |
| KVCOMM | `third_party/KVCOMM` | `48ca0b376c7f4fbf1c24042c1709a6fe4148c959` | 当前 snapshot 未找到 LICENSE/NOTICE | 不复制或 vendor |
| LMCache | `third_party/LMCache` | `2756b828e86e94c18662037bb4a0c24b9de1bf13` | Apache-2.0 | K1 首选 connector 研究对象 |
| Mooncake | `third_party/Mooncake` | `ff800ade1fe2a2df0e3e24ea9ab8d825a7979536` | `LICENSE-APACHE` | 后续大规模/跨节点对象，不进第一版 |

本地论文：

- `docs/2511.20639v3.pdf`
- SHA256：`10a9d1d141cfac51720abcd476d200f275db54d5ff3c74ec86a6f65341418ca2`

### 4.2 LatentMAS 的真实实现边界

论文和代码的核心链路是：

1. HF Transformer 输出末层 hidden；
2. 用输出 embedding 与输入 embedding 构造 ridge/pseudo-inverse 风格的 `d_h x d_h` realignment matrix；
3. 将对齐后的向量作为下一步 `inputs_embeds`；
4. 每个 latent step 更新所有层 `past_key_values`；
5. 后续 Agent 继承这份 working memory；
6. 最终 Agent 才解码文本。

代码证据位于：

- `third_party/LatentMAS/models.py` 的 `_build_latent_realign_matrix()`；
- `generate_latent_batch()` 对 `inputs_embeds` 和 `past_key_values` 的实际调用；
- `methods/latent_mas.py` 的逐 Agent `past_kv` 继承。

其 vLLM 路径不是 OpenAI HTTP KV API：

- 辅助 HuggingFace 模型负责 latent rollout 与 hidden alignment；
- vLLM 只负责最终 `prompt_embeds` 解码；
- 代码直接创建进程内 `vllm.LLM`；
- README 明确提示修改了 vLLM 内部包，并建议用 HF 路径复现正式结果；
- Qwen prompt embedding 插入位置存在模型特定断言。

因此它不能直接接到当前 `53334/v1` 服务。论文还明确假设各 Agent Transformer layer shape 相同；异构模型需要训练 adapter。

#### 论文对 StateBus 的参考价值与边界

`docs/2511.20639v3.pdf` 有直接参考价值，但它是方法与实验设计参考，不是 StateBus 已经实现或必然提速的证据。

可以采用的部分：

- 明确定义“上游 latent thought 被迫解码成文本、下游重新编码”的问题；
- 末层 hidden 的自回归 latent steps，以及 output-to-input embedding realignment；
- 将完整 layer-wise KV 视为短期 working memory，而不是长期业务 memory；
- 使用相同 MAS 拓扑比较 TextMAS 与 LatentMAS，并同时报告质量、输出 token 和端到端速度；
- 对 alignment、latent step depth 和中间状态可调试性做消融；
- 其开源实现展示了 HF latent rollout + 进程内 vLLM `prompt_embeds` 最终解码的混合路线。

不能直接继承的声明：

- 论文的“lossless working-memory transfer”依赖同构模型之间传递完整 layer-wise KV；只传固定数量 aligned latent vectors 的 `LatentStateRef` 不等价，也不能称为 lossless；
- 论文的 `4x-4.3x` 速度和 `70.8%-83.7%` 输出 token 降幅来自其 9 个 benchmark、超参数设置和 `8 x A100-80G` 环境，不能外推到 StateBus；
- 论文没有证明 StateBus 的跨进程 shared-memory transport、CapabilityGrant、typed ref、兼容门、citation validator 或 fallback；这些必须由本项目自己的实验闭环证明；
- 论文没有解决 Planner 动态选择 handoff policy。Planner request + Runtime post-retrieval gate 是 StateBus 自己的系统设计；
- 其 vLLM 路线直接使用进程内 `vllm.LLM`、`enable_prompt_embeds=True` 并修改内部包，不等于当前 OpenAI-compatible HTTP 服务支持 hidden/KV API。

因此本项目应引用它来解释“为什么 latent handoff 可能有价值”和“最小算法怎么做”，但最终只声称自己的实测结果。若 A0/L0 反事实不能证明当前任务确实需要 latent，这篇论文也不能替代需求证据。

### 4.3 LMCache 的真实实现边界

LMCache 的 vLLM connector 会：

- 通过 `register_kv_caches()` 获取 vLLM paged KV tensor；
- 在 forward 前调用 `start_load_kv()`；
- 按 layer `save_kv_layer()`；
- 向 scheduler 报告 `get_num_new_matched_tokens()`；
- 在 cache engine 中将 GPU KV 转换为 CPU/storage `MemoryObj`；
- 再由 GPU connector 将真实对象加载回 paged KV buffer。

这满足“真实 tensor store/load”的必要条件，适合 K1。

但版本必须冻结：

- 当前 LMCache `dev` 快照构建依赖已经前进到 PyTorch 2.11 / CUDA 12.9 或 13 路线，不能直接安装到现有 vLLM 0.7.3 环境；
- 历史 `v0.2.0` 对应 commit `6e17f2ab488cecfc946514ad0b2c8e1f8f47f241`；其 compatibility matrix 明确列出 LMCache V1 + vLLM 0.7.3，且 PyTorch pin 为 2.5.1；
- 同一历史文档又把部分二进制构建环境写为 CUDA 12.4，而当前服务环境是 cu121，所以仍必须在独立容器做 ABI/readiness probe；
- 不能在当前在线服务环境中直接 `pip install` 尝试。

K1 的候选基线应先锁为：

```text
vLLM 0.7.3
PyTorch 2.5.1+cu121
LMCache v0.2.0 @ 6e17f2ab488cecfc946514ad0b2c8e1f8f47f241
同一 Qwen 小模型、同一 tokenizer、同一 TP/PP
```

若 source build 或 connector API 不通过，停止该组合；不要给现有环境打补丁硬凑。

### 4.4 Mooncake 的真实实现边界

Mooncake 同时提供：

- `MooncakeConnector`：prefill/decode 节点之间直接传 KV；
- `MooncakeStoreConnector`：把 KV 放入共享分布式 store；
- `put_tensor/get_tensor/batch_*` 等真实 PyTorch tensor API；
- RDMA/TCP、CPU/SSD 和跨节点能力。

它适合多 engine、PD disaggregation 和高吞吐集群。当前 StateBus 只有一个主要 vLLM engine，第一版引入 master、metadata server、transfer engine 和 connector 会增加大量变量，无法回答 StateBus 自身机制是否有效。因此第一版不选 Mooncake。

此外最新文档主推现代 vLLM V1，legacy V0 路线主要写到 `<=0.6.4.post1`；对当前 `0.7.3` 不能仅凭 README 推断兼容。

### 4.5 KVCOMM 的真实实现边界

KVCOMM 是同模型、training-free 的 cross-context KV 近似复用：

- 官方实现直接操作 HuggingFace `DynamicCache`；
- 用 anchor 记录不同 prefix 下共享片段的 KV deviation；
- 按相似度加权近似 offset；
- 决定候选是否进入 anchor pool；
- README 将 LMCache 集成列为 Next Step，而不是现成 vLLM connector。

它不是 exact KV reuse，会引入新的质量变量；当前 snapshot 又没有许可证，第一版只能研究，不能复制实现。

### 4.6 C2C 的真实实现边界

C2C 用训练过的 projector 将 source model 的 KV 投影到 target model，再通过 layer gate 融合：

- 需要模型对专用 projector；
- 官方已有权重只覆盖列出的模型组合；
- 自定义模型组合需要训练 projector；
- 代码对 Qwen3 attention 有具体 monkey patch；
- PyTorch/Transformers pin 与当前服务不同；
- 仓库许可证元数据互相冲突。

所以它不能支持“任意模型间自动 KV 兼容”的声明，也不适合作为 Runtime 第一版通用协议。

## 5. 场景到机制的选择规则

| 真实需求 | 应选机制 | 不应选 |
|---|---|---|
| 同一 engine、完全相同 token prefix | vLLM APC / 当前 K0 | 外部 KV store |
| GPU KV 被淘汰后仍需重复 exact prefix | LMCache external KV | Semantic memory |
| 同模型跨 engine 复用 exact prefix | LMCache，规模更大时 Mooncake | 普通 shared-memory embedding |
| prefill/decode 分离、跨节点高速传 KV | MooncakeConnector | StateBus Protobuf 搬 tensor |
| 同一文本片段出现在不同位置，需要融合 | CacheBlend 类机制，另立实验 | 宣称 exact replay |
| 不同 prefix 下近似复用共享语义片段 | KVCOMM 研究 lane | 直接进入正式质量结论 |
| 避免中间 Agent 输出文本 | LatentStateRef / LatentMAS 类研究 | APC |
| 异构模型共享 latent/KV | 训练过的 C2C/adapter | 只比较 hidden size 后强行加载 |
| 跨任务复用事实、策略和验证产物 | MemoryRef / ExecutionArtifactRef | KV cache |

## 6. 推荐架构

### 6.1 总体关系

```text
Planner / Retriever / Executor / Summarizer
                  |
                  | typed RefHandle only
                  v
        StateBus Runtime + Ref Registry
          |
          +--> LayeredStateStore / UDS data plane
          |      semantic StateRef（当前）
          |      latent StateRef（新增）
          |
          +--> RoleModelBackend
                 openai_vllm: complete_text（当前）
                 transformers_hf: complete_text / produce_latent / complete_with_latent
                 vllm_native: 同一接口的未来可选 adapter
          |
          +--> KVConnector SPI（Future Work）
                 LMCache owns tensor layout/store/load

Protobuf: identity, lifecycle, compatibility, lineage, metrics
Data plane: connector-owned tensor; never inline in Protobuf
```

StateBus 的职责是：

- 定义 typed ref；
- 做权限、生命周期和兼容门；
- 选择是否发布/消费 state，并把 backend 能力与 task 权限分开；
- 记录 producer/consumer 与真实行为；
- 失败后回退到正常 prefill/text path。

StateBus 不应：

- 自己解释 vLLM paged KV 内存布局；
- 把几 GiB tensor 填进 Protobuf；
- 让 LLM Planner 输出任意存储 handle；
- 把 KV 命中混入长期 Memory hit；
- 用 registry hit 代替 engine consumption。

### 6.2 模型 backend 不能写进协议语义

建议定义最小 `RoleModelBackend` SPI：

```text
capabilities() -> {text_completion, hidden_output, latent_input, kv_import, kv_export}
complete_text(request) -> RoleCompletion
produce_latent(request, latent_steps) -> ProducedLatentTensor
complete_with_latent(request, latent_input) -> RoleCompletion
```

Runtime 先检查 backend capability，再做 `NeuralCompatibilitySignature`，最后才发 lease。协议中的 `LatentStateRef` 不包含“必须由 HF”或“必须由 vLLM”这样的条件；backend ID、版本和模型 signature 只是兼容性事实。

第一版选择 HF 不是因为 StateBus 不需要 vLLM，而是因为 HF 当前提供可验证的标准 tensor API。当前 `openai_vllm` backend 继续承担 Planner、普通 Retriever、Executor CodeAct 和非 latent Summarizer。以后若 vLLM worker/plugin 能稳定提供 hidden output 与 latent input，只新增 `vllm_native` adapter，不改变 Ref、任务 manifest、validator 或实验定义。

vLLM 可以按三层逐步使用：

| 层级 | 是否现在可用 | 作用 |
|---|---|---|
| `openai_vllm` HTTP | 是 | Planner 和普通 text roles；继续承载当前主线 |
| `vllm_native` prompt-embeds adapter | 仅研究容器候选 | HF 产生 latent，vLLM 进程内 engine 做最终解码；必须验证版本和数值一致性 |
| vLLM KV import/export connector | Future Work | exact prefix 的真实 external KV store/load，不属于 L1 |

当前 `0.7.3` OpenAI-compatible endpoint 没有官方接口返回任意层 hidden，也不能通过普通 `/v1/chat/completions` 请求注入任意 `inputs_embeds`。LatentMAS 的可运行思路可以参考，但其 README 明确说明 latent embedding/KV 修改不是 vLLM 官方支持路径。因此第一版不改 `53334`，而是在隔离容器中用 HF 完成真实性基线；若 `vllm_native` 需要长期维护侵入式 fork，就保留为可选优化，不让它定义 StateBus 协议。

### 6.3 两个独立合同

不要继续用一个模糊的 `NeuralStateHandle` 同时代表 prefix identity、KV 和 latent hidden。L1 先新增 `LatentStateRef`；`KVCacheRef` 只保留合同草案，等真实 workload 出现后再实现。wire 层仍只发送当前 `RefHandle(ref_id, ref_kind)`。

#### `KVCacheRef`

建议最小字段：

```text
ref_id
ref_kind = kv_cache
status = PREPARED | COMMITTED | LEASED | CONSUMED | REJECTED | EXPIRED
connector_id / connector_version
backend_handle
producer_engine_id / producer_pid
created_at_ns / expires_at_ns
prefix_token_count / prefix_token_ids_hash
tensor_bytes
tensor_manifest_digest
neural_compatibility_signature
source_task_id / source_step_id / source_role
```

#### `LatentStateRef`

建议最小字段：

```text
ref_id
ref_kind = latent_state
status
storage_kind = shared_memory | mmap_file | connector
root_id / handle / offset / length
producer_pid / producer_device
producer_backend_id / producer_backend_version
consumer_contract_version
model_revision
source_layer_index
hidden_size
latent_step_count
dtype / shape
alignment_method / alignment_matrix_digest
position_contract_digest
tensor_bytes / tensor_digest
anchor_evidence_pack_hash
anchor_item_ids / anchor_locator_digest
source_task_id / source_step_id / source_role
created_at_ns / expires_at_ns
```

### 6.4 `NeuralCompatibilitySignature`

现有 `RuntimeCompatibilitySignature` 面向工具、Prompt、extractor 和 replay，粒度不足以判断 KV/hidden 是否可加载。应新增独立 signature，至少包含：

```text
model_id
model_revision / weights_digest
architecture
tokenizer_id / tokenizer_revision
chat_template_digest
active_adapter_or_lora_digest
quantization_digest
num_layers
hidden_size
num_attention_heads
num_kv_heads
head_dim
kv_dtype
kv_layout
attention_backend
rope_config_digest
sliding_window_config
block_size
tensor_parallel_size / rank_mapping_digest
pipeline_parallel_size / layer_mapping_digest
connector_id / connector_version
```

判定原则：

- exact KV：任一影响数值或布局的字段不同即 `INCOMPATIBLE`；
- latent hidden：同模型可 exact compatible；模型不同必须存在显式、已验证的 `adapter_id + adapter_digest`；
- 不允许 `DEGRADED` 状态自动加载 KV；degraded 只能回退到正常 prefill；
- tokenizer/chat template 不直接改变已有 tensor shape，但会改变 token sequence identity，所以必须进入前缀身份门。

### 6.5 生命周期

```text
PREPARE
  -> connector 分配/声明 pending object
  -> producer 写入真实 tensor
  -> 记录 shape/dtype/bytes/digest

COMMIT
  -> 原子变为可见
  -> 只有完整写入才允许查询

LEASE
  -> consumer 请求短租约
  -> Runtime 做兼容、权限、TTL、完整性检查

CONSUME
  -> connector/worker 实际加载 tensor
  -> engine 报告 loaded token count 或 forward consumed ref_id

RELEASE / EXPIRE
  -> 引用计数下降
  -> connector 回收对象

任一步失败
  -> REJECT / INVALIDATE
  -> 回退到正常 prefill 或 text path
```

只有发生 `CONSUME` 且有 engine/worker 证据时，报告才能写“KV/latent state 被消费”。仅发送 handle、lookup 成功或 lease 成功都不算。

## 7. L1：可验证双通道 latent evidence handoff

### 7.1 它解决的真实场景

第一版只覆盖 **长叙事证据交接**：财报脚注、运营复盘、服务风险说明等离线文档中，答案依赖跨段落的时间限定、例外条件、冲突和不确定性。Retriever 已经选出了相关 evidence，但如果它再生成一段自然语言摘要交给 Summarizer，会发生两件事：

1. producer 需要先把内部状态解码成文本，产生额外 completion tokens；
2. consumer 需要重新 tokenize/prefill 这段文本，且摘要可能丢掉限定词和冲突关系。

当前表格抽取、确定性公式和 CodeAct 不存在这个问题：它们需要精确、可验证的 rows/artifact，latent 反而会降低可审计性。因此 L1 不进入这些步骤，也不以 KV reuse、多 consumer fan-out 或跨任务 memory reuse 为前提；一次真实的 Retriever -> Summarizer handoff 就是完整场景。

### 7.2 为什么采用双通道

只传 hidden/latent 会让下游无法可靠引用来源，也容易被质疑把答案藏进不可读 tensor。第一版同时传两部分：

| 通道 | 内容 | 下游用途 |
|---|---|---|
| typed anchor | 现有 `CanonicalEvidencePack` 的 item ID、locator、类型、lineage 和 pack hash，不含答案式摘要或完整 evidence text | CapabilityGrant 授权、引用候选、validator 对齐和 fallback |
| latent data | 从选中 evidence 和 Retriever 目标生成的固定 `m` 个 aligned latent embeddings | Summarizer 的语义条件，通过 `inputs_embeds` 实际消费 |

Runtime 保留原始 EvidencePack 供 `ClaimSetValidator` 做外部验证，但在 latent lane 中不把完整 evidence text 放进 Summarizer Prompt。Summarizer 仍接收当前 verified artifact rows，因此数值事实继续来自可解释 artifact；latent 只携带叙事限定、关系和风险语义。

这也是相较 LatentMAS 的 StateBus 增量：LatentMAS 提供 training-free latent rollout/realignment 思路；StateBus 增加跨进程 typed ref、权限与兼容门、anchor/latent 双通道、生命周期、真实消费 telemetry、引用验证和确定性 fallback。应称为系统机制创新，不声称发明新的 latent learning 算法。

### 7.3 生成与消费

Retriever-owned latent producer：

1. 接收当前 `task_goal`、选中 evidence text 和固定 producer role prompt；
2. 使用同一冻结 causal model 做 forward，开启 `output_hidden_states=True`；
3. 取末层最后位置 hidden，通过 LatentMAS 类 training-free realignment 映射到 input embedding space；
4. 自回归产生固定 `m` 个 aligned latent embeddings；
5. 转为 BF16 contiguous tensor，计算 shape/bytes/SHA256；
6. 通过当前 `LayeredStateStore` 写入 shared memory 或 memfd；
7. COMMIT `LatentStateRef`，绑定 evidence pack hash 和 anchor digest。

Summarizer consumer：

1. 通过当前 CapabilityGrant 获得 evidence/artifact/latent refs；
2. Runtime 校验模型、alignment、position contract、anchor pack、TTL 和 tensor digest；
3. LEASE 并由独立 worker attach/read state；
4. 将 latent tensor 插入固定 `<statebus-latent>` marker 对应的 `inputs_embeds` 位置；
5. 与任务指令、anchor IDs/locators、verified artifact rows 一起完成 ClaimSet generation；
6. 记录 `consumed_ref_id`、producer/consumer PID、D2H/H2D、prompt tokens 和 forward event；
7. 现有 `ClaimSetValidator` 用原始 EvidencePack/ArtifactRef 验证；
8. RELEASE；任何失败回退到现有 full-text Summarizer。

原始末层 hidden 不能直接假定是合法 input embedding，所以 wire object 的准确名称是 **aligned latent embedding sequence**，其 lineage 来自 hidden state。报告可以说“hidden-derived latent handoff”，不能把它写成任意 raw hidden tensor 直通。

### 7.4 第一版限制

- 只支持相同 model revision、tokenizer、chat template 和 alignment digest；
- 只支持 batch size 1、固定末层和固定 latent step count；
- 只接 Retriever -> Summarizer，不接数值 Executor、CodeAct 或 memory；
- HF 是首个真实 backend，但合同不绑定 HF；vLLM adapter 以后实现同一 SPI；
- 不支持异构模型，不声称与完整 `past_key_values` 等价或 lossless；
- 不声称 latent tensor 比文本字节更小；必须同时报告 tensor bytes、文本 tokens 和端到端时延；
- 最终 ClaimSet 必须通过现有 validator，否则 fallback 结果不能计作 latent success。

## 8. K1：LMCache 同模型真实 KV Future Work

### 8.1 目标

K1 只回答一个问题：

> 当 consumer engine 的本地 APC 不可用时，同模型 external KV store/load 是否比重新 prefill 更快，同时保持输出质量？

它不回答记忆复用、semantic routing 或 Agent 职能问题。

### 8.2 集成方式

第一版让 LMCache connector 持有所有 tensor。StateBus 只保存：

- token prefix identity；
- connector handle；
- compatibility signature；
- lifecycle/lease；
- bytes 和 latency；
- engine 返回的 matched/loaded token count。

请求流程：

```text
producer request prefill
  -> vLLM connector save real KV
  -> LMCache commit
  -> StateBus commit KVCacheRef

consumer request
  -> StateBus exact compatibility gate
  -> connector lookup/load
  -> vLLM reports external matched tokens
  -> request consumes loaded blocks
  -> StateBus records CONSUME
```

### 8.3 不使用当前在线服务

当前 `53334` 服务正在承载正式实验，禁止安装 connector、重启或替换依赖。K1 必须在独立容器、独立端口和独立小模型中运行。

## 9. 最小实验，不堆叠变量

### 9.1 竞赛主实验保持不变

L0-L3、10+10 长期稳定性、adaptive CodeAct 和 semantic holdout 不加入 KV/latent。原因是这些实验分别测通信、semantic state、memory 和 Agent 自主选择；加入推理引擎 tensor 后无法归因。

### 9.2 L1 feasibility matrix

固定同一个小型 Qwen causal model revision、同一 tokenizer/chat template、同一 Retriever/Summarizer Prompt、temperature=0、同一 max tokens。所有相关模型调用在 C0/T0/A0/L0/L1 中使用同一个 backend/version；不能用大模型跑文本 lane、小模型跑 latent lane。第一版固定 `latent_steps=40`，取论文消融中 `40-80` 合理区间的下界作为预注册起点，但不声称它对 StateBus 最优，也不在正式 case 上搜索预算。Retriever text handoff 固定最多 128 completion tokens。

该 matrix 固定 `STATEBUS_PREFIX_ALIGNMENT_MODE=independent`，不同时测试 APC/prefix 效应。C0/T0/A0/L0/L1 由实验 harness 显式选择，Planner 动态选择只在后续 policy audit 使用 `STATEBUS_LATENT_HANDOFF_MODE=planner_assist`。

新增一个 `latent_narrative_holdout_v1`，不复用 4-case semantic route holdout 的 headline。只做 6 个离线长叙事 case：

- 2 个跨段落时间限定；
- 2 个冲突证据/风险判断；
- 2 个条件与例外组合；
- 每个 case 的选中 evidence 控制在约 `4k-8k` tokenizer tokens，并预注册 4 个 required facts，共 24 个 fact checks；
- anchor 只含现有 ID、locator、类型和 lineage，不含答案式摘要；
- expected facts 只用于执行后评分。

| Mode | Summarizer 获得的信息 | 回答的问题 |
|---|---|---|
| C0 current full evidence | task + verified artifact + anchors + 完整 selected evidence text | 当前 StateBus Summarizer 路径的质量基线和 prompt 成本 |
| T0 Retriever text handoff | Retriever 阅读 selected evidence 后输出不超过 128 tokens 的 analysis；Summarizer 看 anchors + analysis | 真实 Agent 文本交接基线及文本化损失 |
| A0 anchor only | task + verified artifact + anchors，不含 evidence text/analysis/latent | anchors 自己是否已经足够；hidden 是否有真实需求 |
| L0 latent in-process | A0 + Retriever 产生的 canonical latent tensor 进程内只读消费 | latent thoughts 是否携带了 anchors 之外的有效语义 |
| L1 latent StateRef | A0 + 同一 canonical tensor 经 shared memory/memfd 跨 worker 消费 | StateBus transport 是否保持 L0 行为 |
| N1 incompatible | L1 候选存在，但 model/alignment/position digest 被修改 | Runtime 是否先拒绝，再走现有 C0 fallback |

每个 case 的 Retriever latent phase 只生成一次 canonical tensor，转为 BF16 contiguous 后冻结 shape、bytes 和 SHA256。L0 与 L1 消费完全相同的 tensor；禁止分别 rollout 两份状态。producer latency 同时计入 L0/L1 的端到端成本，transport 子指标再单独比较 L0/L1。

第一阶段运行量是 `6 case x 5 positive mode + 2 negative = 32` 次，全部串行。只有同时满足以下预注册门槛，才能扩展连续任务：

- C0 至少 `22/24` required facts，证明任务和所选模型本身有效；
- T0 至少 `20/24`，否则先承认 128-token text handoff 不是有效基线，不进入 latent 优势结论；
- L0/L1 各至少 `22/24`，L1 不比 C0 少超过 1 个 fact，且不得低于 T0；
- L0 与 L1 的逐 case fact verdict、citation verdict 和规范化最终结论全部一致；
- L0/L1 比 A0 至少多通过 3 个 required facts；若没有增益，说明 anchors/verified artifact 已经足够，当前 workload 不需要 latent；
- L1 是 `6/6` 不同 producer/consumer PID、`6/6` tensor digest/shape 一致、`6/6` 有实际 `inputs_embeds` forward consumption event；
- L1 相比 C0 的 Summarizer prompt-visible evidence tokens 至少减少 50%，并相对 T0 消除 Retriever handoff completion tokens；tensor bytes 必须单列，不允许把非文本字节隐去；
- 2 个 N1 都在 tensor map/forward 前拒绝，随后 C0 fallback 通过对应质量门；
- 全部 case 报告 producer inference、D2H、state write/read、H2D、consumer inference、文本 tokens、tensor bytes 和端到端 latency。

这里不要求 latent 一定降低端到端时延。若质量恢复但 tensor/搬运成本较高，可以诚实结论为“状态传递创新成立，性能收益未成立”；若 L0 对 A0 没有质量增益，或 L1 无法保持 L0 行为，则不再扩展。

### 9.3 Planner/Runtime 激活策略审计

前述 C0/T0/A0/L0/L1 matrix 使用固定 lane，是为了先隔离 latent 表示和 transport 本身，不能用它证明 Planner 能正确选择。matrix 通过后只补一个很小的 policy audit，不新增业务任务：

- 复用 6 个 long-narrative case，要求 Planner 在不知道 expected facts 的情况下提出 `latent_assist`，Runtime 对兼容 positive run 接受；
- 复用 2 个现有短表格/精确数值 case，要求 Planner 选择 `text` 或给出 `exact_artifact_preferred`，不得为了覆盖率开启 latent；
- 复用 N1 的不兼容 signature，验证即使 Planner 请求 latent，Runtime 仍在 tensor map/forward 前拒绝并回退；
- 报告 requested/effective policy、Planner rationale、Runtime gate checks 和 fallback reason，不把选择准确率混入任务质量指标。

这组审计回答“自动启用是否合理”；它不重新比较 latent 算法质量，所以不需要再扩成另一套大矩阵。任何按 case ID、expected answer 或固定 family name 选择 latent 的实现均判定失败。

### 9.4 K1 minimal matrix，仅在未来出现 workload 后执行

使用 2 个固定长前缀，每个条件做 `1` 次 warmup + `10` 次串行测量：

| Mode | 本地 APC | External KV | 条件 |
|---|---:|---:|---|
| K-cold | 关 | 关 | 每次正常 prefill |
| K-apc | 开 | 关 | 同 engine 完全相同 token prefix |
| K-external | consumer 本地冷 | 开 | 独立 producer engine A 保存，独立 consumer engine B 加载 |
| K-negative | consumer 本地冷 | 候选存在但拒绝 | chat template/model/layout signature 不兼容 |

固定变量：

- 同一 model revision、tokenizer、chat template；
- 同一 TP/PP、KV dtype、block size 和 attention backend；
- temperature=0、相同 max tokens；
- 相同输入 token IDs；
- 串行请求；
- K-cold/K-apc/K-external 使用等价 engine 配置；
- engine A 与 engine B 使用独立 PID、worker、block pool 和本地 APC；K-external 每个测量 trial 前必须通过受支持的 reset API 或重建 B 证明 consumer 本地冷；
- expected answer 只在生成后评分。

必须记录：

- TTFT p50/p95；
- end-to-end latency p50/p95；
- prompt token count；
- engine computed prefill tokens；
- external matched/loaded token count；
- KV tensor bytes；
- lookup/store/load/D2H/H2D latency；
- connector hit/miss/reject；
- producer/consumer engine ID 和 PID；
- output quality/equality；
- fallback count。

`n=10` 的 p95 仅作描述性诊断，必须同时输出 10 个原始样本、min/max 和 bootstrap/分位数算法；不得凭这一小样本单独声称稳定的尾延迟优势。需要 headline p95 时再预注册更大的重复次数。

成功门槛：

- K-external 有真实 loaded token count > 0；
- consumer engine 在加载后少计算对应 prefix；
- 输出质量通过；
- `store + load + transfer` 后仍有正的 TTFT 净收益；
- K-negative 在 connector load 前被 Runtime 拒绝；
- 没有把 APC 命中计入 external KV hit。

若 external KV 对当前长度没有净收益，应如实报告负结果并停止扩张；这不是失败，而是说明当前单机 workload 不需要该机制。

## 10. 实现顺序

### Phase 0：冻结与隔离

1. 等当前 contest evidence closure 完成；
2. 提交并记录主线 Git SHA、镜像 digest 和正式 artifact；
3. 从冻结 SHA 建独立研究分支；
4. 新建独立 `statebus-neural-lab` 容器；
5. 使用独立 GPU、端口、runtime root 和模型目录；
6. 不修改 `statebus-dev-qcrs` 和 `53334`。

退出门槛：主线 formal artifact 不因 neural lab 改变。

### Phase 1：接入现有 Runtime 的合同和 fake backend

建议新增：

```text
v2/contracts/neural.py
v2/runtime/role_model_backend.py
v2/runtime/latent_handoff.py
v2/runtime/neural_ref_registry.py
tests/v2/neural/
```

实现：

- `RefKind.LATENT_STATE`、`LatentStateRef` 和 anchor binding；
- `NeuralCompatibilitySignature`；
- lifecycle state machine；
- lease/TTL/invalidation；
- `RoleModelBackend` SPI；
- `allowed_handoff_policies`、逐边 `handoff_intent` 和 `HandoffDecision`；
- `STATEBUS_LATENT_HANDOFF_MODE` 四态开关，默认 `off`；
- Planner request + post-retrieval Runtime activation gate；
- fake backend 的 prepare/commit/consume/reject；
- telemetry schema；
- negative tests。

此阶段只可声称“合同、backend SPI 和状态机已实现”，不可声称 hidden 已传递。

退出门槛：全部测试在容器内通过，且 fake handle 不会被报告为 tensor consumption。

### Phase 2A：L1 样机，推荐优先

1. 固定一个小型 Qwen causal model revision，C0/T0/A0/L0/L1 使用同一模型；
2. 实现 `transformers_hf` producer/consumer backend；
3. 将 producer 接在现有 retrieval semantic selection 之后；
4. 实现 realignment matrix 的一次构建与 digest；
5. 复用 `LayeredStateStore`、shared memory/memfd 和 UDS worker 发布/读取 BF16 latent；
6. 将 consumer 接入现有 Summarizer claim-set factory，不改 ClaimSetValidator；
7. 记录真实 `inputs_embeds` forward、D2H/H2D、tensor bytes、PID 和行为；
8. 跑 32 次 feasibility matrix；
9. matrix 通过后运行最小 Planner/Runtime policy audit；
10. 只在“L0 对 A0 有增益且 L1 等价 L0”后扩到连续任务。

### Phase 2B：vLLM adapter，可选且不阻塞 L1

1. 只在 vLLM 具有可维护的 hidden output/latent input worker API 时开始；
2. 实现同一 `RoleModelBackend`，不得修改 `LatentStateRef` 或实验 manifest；
3. 用同一 canonical tensor 做 HF/vLLM consumer 一致性诊断；
4. 若必须长期维护侵入式 fork，只保留 HF reference backend，不让 vLLM 阻塞功能成立。

### Phase 2C：K1/LMCache，只有出现重复 prefill 需求才启动

1. 先用 telemetry 证明本地 APC 不可用时存在重复 exact prefix prefill；
2. 再在独立镜像验证 LMCache `v0.2.0` + vLLM `0.7.3` ABI；
3. 运行本节 K1 matrix；
4. 净收益不成立则停止，不升级 Mooncake。

### Phase 3：报告和 claim review

1. 生成 artifact manifest；
2. 记录代码 SHA、镜像 digest、模型 revision、connector revision；
3. 审核所有 `hit`、`reuse`、`transfer` 用词；
4. 将 L1 放入状态创新补充实验，K1 仍为有条件 Future Work；
5. 未通过门槛的对象保持 `Future Work`。

## 11. 容器执行约束与命令模板

以下是计划中的执行约定，不代表对应 `neural-lab` 文件现在已经实现。

### 11.1 网络与本地参考仓库

宿主机只负责 Git 和 Docker 编排。网络不稳定时使用：

```bash
export HTTPS_PROXY=http://127.0.0.1:54321
export HTTP_PROXY=http://127.0.0.1:54321
```

当前参考仓库已经位于：

```text
/home/qcrs/statebus/project/third_party/LatentMAS
/home/qcrs/statebus/project/third_party/C2C
/home/qcrs/statebus/project/third_party/KVCOMM
/home/qcrs/statebus/project/third_party/LMCache
/home/qcrs/statebus/project/third_party/Mooncake
```

### 11.2 启动独立实验容器

未来新增 compose 文件后，统一从宿主机执行：

```bash
export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
docker compose -f docker/compose.neural-lab.yaml build neural-lab
docker compose -f docker/compose.neural-lab.yaml up -d neural-lab
```

约束：

- 不复用 `53334`；建议 lab API 使用 `53434/53435`；
- `54321` 保留给网络代理，不作为 vLLM 服务端口；
- GPU 必须在启动前通过 `nvidia-smi` 和当前实验 owner 确认；
- 模型目录只读挂载；
- run artifacts 写入 `/statebus/runs/neural_state_lab_<timestamp>/`；
- 依赖安装只发生在 lab image/env，不污染现有容器。

### 11.3 进入容器并激活环境

```bash
docker exec -it statebus-neural-lab bash
source /opt/conda/etc/profile.d/conda.sh
conda activate statebus-neural-lab
python --version
python -c "import torch, transformers; print(torch.__version__, transformers.__version__)"
```

若使用 vLLM/LMCache，再显式验证：

```bash
python -c "import vllm, lmcache; print(vllm.__version__, lmcache.__version__)"
```

版本不匹配时停止，不允许临时升级当前正式服务环境。

### 11.4 测试只能在容器内执行

```bash
docker exec statebus-neural-lab bash -lc '
  source /opt/conda/etc/profile.d/conda.sh &&
  conda activate statebus-neural-lab &&
  pytest -q tests/v2/neural
'
```

实验同样从容器内运行，并把 stdout/stderr 写入 run root。宿主机不运行 pytest、Runtime、benchmark 或 Python 实验；宿主机只读取 artifact、执行 `docker ps`、health check 和 Git 操作。

## 12. 防止“声称实现、实际作弊”的检查表

以下任一情况都不能写“实现了 KV/hidden transfer”：

- 只传了 prefix hash；
- 只登记了 `NeuralStateHandle`；
- 只看到 vLLM APC metric 增长；
- 只把 embedding 放进 shared memory；
- 只传 connector handle，没有 consumer load；
- 只做 lookup，没有减少 computed prefill tokens；
- 只统计 token 节省，不报告 tensor bytes；
- producer 和 consumer 实际是同一个 Python 对象，却声称跨进程；
- consumer Prompt 中偷偷包含了同一份文本答案；
- expected facts 进入 Agent Prompt；
- 不兼容模型仍通过字符串 model name 强行加载；
- 用预先注册答案或 task ID 选择 expected route；
- 将近似 KV 融合称为 exact replay；
- 将一次 query 称为 memory/KV hit。

正式 evidence row 至少需要：

```text
ref_id
producer_pid / producer_engine_id
consumer_pid / consumer_engine_id
producer_backend_id / consumer_backend_id
model_revision
compatibility_digest
anchor_evidence_pack_hash / anchor_locator_digest
tensor_shape / dtype / bytes
store_started/completed timestamp
load_started/completed timestamp
consumed_at timestamp
loaded_token_count or inputs_embeds_consumed_ref_id
fallback/reject reason
quality verdict
```

## 13. 风险和停止条件

### 13.1 L1 停止条件

- 小模型质量明显低于 TextMAS；
- L0/L1 相比 A0 没有预注册的 required-fact 增益；
- shared-memory transport 后结果与 in-process latent 不一致；
- D2H/H2D 占据大部分端到端耗时；
- 需要对每个任务写 prompt/adapter 分支才能工作；
- 只有同进程成功，跨进程无法产生真实消费证据。

出现这些情况时，保留 embedding StateRef 主线，将 L1 记录为负结果/Future Work。

### 13.2 K1 停止条件

- LMCache/vLLM ABI 在隔离容器中无法稳定复现；
- 需要修改当前正式 Qwen3-32B 服务；
- external load 没有减少 computed prefill；
- store/load/transfer 成本高于重新 prefill；
- 只有 registry/lookup 命中，没有 engine load；
- 为通过任务而改 expected answer 或输入 prefix。

### 13.3 何时才考虑 Mooncake/KVCOMM/C2C

- Mooncake：已经有至少两个 engine 或明确 PD disaggregation 需求；
- KVCOMM：exact prefix 命中不足且愿意单独承担近似质量实验；
- C2C：有固定异构模型对、训练数据和 projector 训练预算。

在这些需求出现前，增加它们只是堆叠依赖。

## 14. 最终建议

从赛题和当前实现出发，最合理的选择是：

1. 不把 KV/hidden 加入当前竞赛主实验；
2. 保持 embedding `StateRef` 为正式非文本状态基础证据；
3. 完成 adaptive memory 的真实 commit/match/consume/replay 闭环；
4. 当前 evidence closure 完成后，在同一个 StateBus Runtime 中实现 L1 可验证双通道 latent handoff；
5. 首个真实 backend 使用 HF，当前 vLLM 继续服务普通角色，协议和 Ref 不绑定任一 backend；
6. L1 只接长叙事 Retriever -> Summarizer，并用 C0/T0/A0/L0/L1 回答“是否真的需要 hidden”和“跨进程传输是否保持行为”；
7. K1/LMCache 只有在 telemetry 证明存在本地 APC 无法解决的重复 exact prefill 后才启动；
8. 若 L0/L1 对 A0 没有质量增益，或只有 handle 没有真实 `inputs_embeds` 消费，则诚实停止并保留 embedding 主线。

这条路线的创新点不是“又增加一个 tensor 类型”，而是把 hidden-derived latent 变成 StateBus 中可授权、可兼容判断、可跨进程消费、可引用验证、可失败回退的 Agent 状态。它直接解决长叙事 evidence 必须先文本摘要再重新编码的问题，同时保留当前系统的审计边界；如果反事实实验不能证明这个问题存在，就不继续实现。

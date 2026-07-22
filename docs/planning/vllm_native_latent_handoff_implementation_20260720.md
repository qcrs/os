# StateBus vLLM Native Latent Handoff 详细实现与验证文档

更新时间：2026-07-20

状态：实现前冻结稿，代码尚未开始

适用版本：StateBus v2、vLLM 0.9.2、V0 engine、Qwen3-32B

执行原则：同一 vLLM 服务、显式开关、默认关闭、失败回退文本、所有 StateBus 测试在 openEuler embed 容器内执行

## 0. 文档用途

这是一份可以直接交给后续实现者执行的 implementation prompt。它回答五个问题：

1. 为什么 StateBus 需要 latent handoff，而不是为了创新堆一个 tensor 类型；
2. 第一版准确实现什么，不实现什么；
3. 如何在当前同一个 vLLM 服务中实现 hidden producer、latent registry 和 consumer；
4. 如何只重启一次现有 `53334` 服务并完成容器内验证；
5. 通过哪些证据后，才允许对外声称“hidden-derived latent handoff 已实现”。

本轮只编写文档。不得因为本文件存在就把 latent 写成当前已实现能力。

### 0.1 治理边界

本文基于已经验证的 vLLM `0.9.2` 能力，替代旧设计中“vLLM `0.7.3` 缺少可用 consumer、第一版只能采用 HF producer/consumer”的技术假设，但替代范围仅限本文提出的 native experimental path。

本文不会自动修改以下事实：

- 当前正式 StateBus 主线仍以 embedding `StateRef`、文本路径和 `Engine-Local Prefix Reuse` 为已验证能力；
- repo `AGENTS.md` 中将 hidden/KV handoff 标为 `Future Work` 的约束仍然生效；
- 现有正式实验、报告和答辩口径不得因为本设计文档存在而新增 latent 实现声明；
- 只有第 22 节完成定义全部满足，并另行更新约束、实现状态和验证报告后，才能把该路径标为 `experimental implemented`。

因此，本文是实现冻结稿，不是功能完成证明，也不改变当前 contest evidence baseline。

## 1. 结论先说

第一版采用以下架构：

```text
同一个 StateBus Runtime
  |
  +-- 普通任务 ----------------------------------------------+
  |                                                          |
  |    /v1/chat/completions                                  |
  |                                                          v
  +-- 长叙事任务 -> Planner 提出 latent_assist        同一个 vLLM 0.9.2 服务
                     -> Runtime post-retrieval gate           |
                     -> /statebus/latent/produce              |
                     -> opaque LatentStateRef                 |
                     -> /statebus/latent/complete             |
                     -> ClaimSet validator                    |
                     -> 失败时走原文本 Summarizer ------------+
```

vLLM 内部只增加两个可启动时加载的扩展：

```text
LatentHandoffMiddleware
  - 在同一端口提供 /statebus/latent/*
  - 串行化 latent capture
  - 调用现有 AsyncLLMEngine 和 collective_rpc

LatentWorkerExtension
  - 捕获真实末层 hidden
  - 将 hidden 对齐到 input embedding space
  - 在后续 decode step 注入 aligned latent embedding
  - 将短生命周期 tensor 存入有界 engine-local registry
```

启动时使用：

```text
--middleware v2.integrations.vllm_latent.middleware.LatentHandoffMiddleware
--worker-extension-cls v2.integrations.vllm_latent.worker_extension.LatentWorkerExtension
```

不要替换 `--worker-cls`。vLLM 已提供 worker extension 注入点，第一版不应接管整个标准 Worker。

升级至 vLLM 0.9.2 只解决了 latent consumer 的基础能力：在线服务能够接收 `prompt_embeds`。它没有自动实现 hidden 导出、latent recurrence、Ref registry 或 StateBus gate，因此仍需上述插件。

## 2. 当前已经验证的环境事实

以下事实已在 2026-07-20 验证：

| 项目 | 当前事实 |
|---|---|
| vLLM 环境 | `/home/qcrs/statebus/conda-envs/vllm-qwen-cu121` |
| vLLM | `0.9.2` |
| Transformers | `4.52.4`，必须保持 4.x，不能回到导致 `aimv2` 冲突的 5.x |
| PyTorch | `2.7.0+cu126` |
| 模型 | `/data/models/Qwen3-32B` |
| served model | `qwen3-32b` |
| 模型 hidden size | `5120` |
| 服务地址 | `http://127.0.0.1:53334` |
| engine | `VLLM_USE_V1=0` |
| max model len | `8192` |
| max sequences | `1` |
| prefix caching | 已启用 |
| prompt embeds | 已启用 |
| eager mode | 已启用 |
| 模型权重显存 | 约 `61.03 GiB` |
| KV cache 余量 | 约 `2.37 GiB` |

已经从 `statebus-dev-qcrs` embed 容器内完成的 readiness smoke：

- `/health` 返回 HTTP 200；
- `/v1/models` 返回 `qwen3-32b` 和 `max_model_len=8192`；
- StateBus `OpenAICompatibleLLMClient` 返回合法结构化 JSON；
- BF16、shape `[4, 5120]` 的真实 `prompt_embeds` 请求返回 HTTP 200；
- 相同 1540-token prefix 的两次请求观测到约 `0.530s -> 0.067s` 的 smoke 变化；
- `/metrics` 明确显示 `enable_prefix_caching=True`。

这些结果只证明：

```text
普通文本路径可用
prompt_embeds consumer 可用
本地 prefix cache 配置可用
```

它们不证明：

```text
hidden producer 已实现
latent recurrence 已实现
LatentStateRef 被消费
latent 提高质量或降低时延
```

特别是随机 `prompt_embeds` 返回 200，只是 consumer readiness，不是 Agent latent handoff 证据。

### 2.1 当前安装源码审计

对当前 vLLM `0.9.2` site-packages 的只读审计确认：

- `entrypoints/openai/api_server.py` 会通过 `args.middleware` 加载 ASGI class，并在初始化后暴露 `app.state.engine_client`；
- `worker/worker_base.py` 会把 `worker_extension_cls` 动态加入标准 Worker 的基类，并将新增方法暴露给 extended `collective_rpc`；
- `engine/async_llm_engine.py` 提供异步 `collective_rpc()`；
- `worker/model_runner.py` 的 V0 input 包含 `inputs_embeds` 和 `request_ids_to_seq_ids`，且 `return_hidden_states=True` 时将最新 hidden 放入 `SamplerOutput`；
- `model_executor/models/qwen3.py` 的 forward 接受 `inputs_embeds`。

这说明本文架构有真实扩展入口，不需要仅为入口能力 fork vLLM；它仍不证明 recurrence wrapper、registry 或 consumer forward hook 已经正确实现。对应方法签名必须在 Phase 0 固化为 compatibility snapshot，升级 vLLM 后重新审计。

## 3. 为什么做 latent handoff

### 3.1 真实问题

第一版只服务一个真实场景：Retriever 已选出较长的叙事证据，并需要把跨段落关系、条件、例外、冲突和风险语义交给 Summarizer。

当前文本交接通常是：

```text
Retriever 读取长证据
  -> 生成一段自然语言分析或摘要
  -> HTTP/JSON 传给 Summarizer
  -> Summarizer 再 tokenize 和 prefill
  -> 生成 ClaimSet
```

这里存在两个可验证的问题：

1. 上游内部连续表示必须先被压成有限文本，下游再重新编码；
2. 简短摘要可能遗漏时间限定、否定、例外或证据冲突。

latent lane 尝试改成：

```text
Retriever 读取长证据
  -> 生成固定步数的 hidden-derived aligned latent embeddings
  -> Runtime 只传 opaque LatentStateRef 和可验证 anchor
  -> Summarizer 通过 inputs_embeds 消费
  -> 生成相同 ClaimSet 合同
```

### 3.2 为什么不是所有任务都启用

下列任务通常不需要 latent：

- 精确表格行提取；
- 确定性公式计算；
- 已验证 artifact 的读取或 replay；
- CodeAct 输出验证；
- 短文本事实；
- 需要逐字引用原文的任务。

这些场景需要的是可解释 row、locator、artifact 或文本引用。latent 既不能替代验证对象，也可能增加 tensor 搬运和调试成本。

### 3.3 创新点在哪里

创新点不是“增加 hidden tensor”，而是把 hidden-derived latent 变成 StateBus 中具有以下属性的受控状态：

- Planner 只能提出 intent，Runtime 决定是否启用；
- 通过 typed `LatentStateRef` 授权，不把 tensor 放进 Prompt 或 Protobuf；
- 有模型、tokenizer、位置、alignment 和版本兼容门；
- 有 PREPARE、COMMIT、LEASE、CONSUME、RELEASE、EXPIRE 生命周期；
- 有 evidence anchor 和 ClaimSetValidator，不把答案藏在不可审计 tensor 中；
- 有普通文本 fallback；
- 有真实 worker forward 消费事件；
- 有 tensor bytes、D2H/H2D 和质量指标，不只统计 token。

LatentMAS 提供 latent recurrence 和 training-free alignment 的方法参考；StateBus 增加的是协议、权限、生命周期、兼容、审计、验证与回退这一整套系统机制。

## 4. 必须区分的五类状态

| 对象 | 生产者/消费者 | 解决的问题 | 生命周期 | 当前决策 |
|---|---|---|---|---|
| Semantic embedding | embedding encoder -> Retriever/MemoryProxy | 找哪些证据、如何 top-k | 当前任务或长期索引 | 已实现，正式主线 |
| Prefix/APC | 同一 vLLM engine | 相同 token prefix 避免重复 prefill | engine cache | 已启用，和 latent 正交 |
| Hidden-derived latent | Retriever model -> Summarizer model | 避免中间分析必须文本化 | 秒级、单次或少量消费 | 本文要实现 |
| KV cache | attention backend -> attention backend | exact prefix prefill 计算复用 | 短期、强模型耦合 | 不在本文实现 |
| MemoryRef/ArtifactRef | Runtime/Agent -> 后续任务 | 跨任务事实、策略、产物复用 | 长期 | 现有主线 |

禁止混用以下口径：

- prefix registry 命中不等于 GPU APC hit；
- prompt embeds 可输入不等于 hidden 已导出；
- latent ref lookup 不等于 forward 已消费；
- latent 不等于完整 KV working memory；
- latent 不进入长期 MemoryIndex；
- tensor bytes 不能从通信成本报告中隐藏。

## 5. 第一版范围

### 5.1 必须实现

- 同一 `53334` vLLM 服务；
- `RefKind.LATENT_STATE`；
- `StorageKind.ENGINE_LOCAL`；
- `LatentStateRef`；
- `NeuralCompatibilitySignature`；
- Retriever -> Summarizer 单条 role edge；
- vLLM worker 内真实末层 hidden 捕获；
- 至少 2 个 latent recurrence step，正式默认建议 8，实验再预注册 8 或 16；
- aligned latent sequence 的 engine-local CPU registry；
- `prompt_embeds` consumer；
- evidence ID/locator anchor 双通道；
- Runtime post-retrieval gate；
- 文本 fallback；
- TTL、容量、one-shot lease 和释放；
- 容器内 contract、negative 和真实 vLLM integration tests；
- 完整 telemetry。

### 5.2 第一版明确不实现

- external KV store/load；
- LMCache、Mooncake、KVCOMM 或 C2C 集成；
- 跨模型或异构 hidden adapter；
- tensor 通过 HTTP/base64 暴露给 StateBus；
- tensor 写入长期 MemoryIndex；
- 多并发 latent capture；
- tensor parallel 大于 1；
- pipeline parallel 大于 1；
- batch size 大于 1；
- 任意 Agent edge；
- 按 task ID、family 名或 expected answer 启用 latent；
- 将 latent 加入当前 L0-L3 正式主矩阵；
- 声称 lossless、通用跨模型或必然提速。

### 5.3 初始支持矩阵

```text
vLLM version       == 0.9.2
engine             == V0
model architecture == Qwen3ForCausalLM
hidden size        == 5120
TP                 == 1
PP                 == 1
max_num_seqs       == 1
execution          == eager
dtype              == BF16
consumer           == same model revision
```

任何字段不满足时，Runtime 应拒绝 latent 并回退文本，而不是尝试“兼容运行”。

## 6. 目标代码布局

建议新增：

```text
v2/contracts/neural.py
v2/runtime/latent_handoff.py
v2/runtime/role_model_backend.py
v2/integrations/vllm_latent/
  __init__.py
  api_models.py
  middleware.py
  registry.py
  worker_extension.py
  client.py
  telemetry.py
tests/v2/neural/
  test_neural_contracts.py
  test_latent_gate.py
  test_latent_registry.py
  test_vllm_latent_middleware.py
  test_vllm_latent_worker_extension.py
  test_vllm_latent_client.py
  test_vllm_latent_integration.py
scripts/
  check_vllm_latent_readiness.sh
  smoke_vllm_latent_from_container.sh
docs/reports/
  vllm_native_latent_handoff_container_validation_20260720.md
```

现有文件的最小修改面：

```text
v2/contracts/models.py
  - RefKind.LATENT_STATE
  - StorageKind.ENGINE_LOCAL

v2/contracts/adaptive.py
  - PlanStepProposal.handoff_intent
  - PlanProposal/ApprovedPlan canonical payload

v2/contracts/__init__.py
v2/refs/models.py
v2/refs/__init__.py
  - 导出新合同

v2/runtime/adaptive_dispatcher.py
  - retrieval 后调用 latent gate/producer
  - summarizer 前选择 latent/text backend
  - 记录 fallback 和 consumption

v2/runtime/adaptive_mainline.py
  - 注入 LatentHandoffController/Backend

v2/runtime/role_path.py
  - Planner handoff intent schema
  - latent Summarizer 不内联完整 evidence_text
  - 保持 ClaimSet 输出合同不变
```

不要新建绕开 `AdaptiveCapabilityDispatcher` 的 demo orchestrator。独立 probe 可以存在，但正式 StateBus 证据必须经过现有 Runtime、Grant、Ref、validator 和 telemetry。

## 7. 合同设计

### 7.1 `HandoffIntent`

建议枚举：

```text
auto
text
latent_assist
exact_artifact_preferred
```

Planner 只能在 Envelope 暴露的集合中选择。它不能指定：

- endpoint；
- worker class；
- tensor shape；
- storage handle；
- latent step 数；
- compatibility digest；
- fallback 是否绕过。

这些全部由 Runtime/controller 管理。

### 7.2 `LatentStateRef`

建议最小字段：

```text
ref_id
ref_kind = latent_state
status
storage_kind = engine_local
backend_handle
producer_role
consumer_role
source_task_id
source_step_id
source_evidence_pack_hash
anchor_item_ids
anchor_locator_digest
model_id
model_revision
tokenizer_revision
chat_template_digest
hidden_size
source_layer_index
latent_step_count
alignment_method
alignment_config_digest
position_contract_digest
dtype
shape
tensor_bytes
tensor_digest
producer_pid
engine_id
created_at_ns
expires_at_ns
compatibility_digest
schema_version
```

Ref 中不放：

- tensor bytes；
- base64 tensor；
- 完整 evidence text；
- expected facts；
- 答案或最终 ClaimSet。

### 7.3 `NeuralCompatibilitySignature`

至少包含：

```text
vllm_version
engine_generation = V0
model_id
model_revision_or_manifest_digest
architecture
tokenizer_id
tokenizer_revision
chat_template_digest
active_lora_or_adapter_digest
quantization_digest
dtype
hidden_size
num_layers
num_attention_heads
num_kv_heads
head_dim
rope_config_digest
attention_backend
tensor_parallel_size
pipeline_parallel_size
worker_extension_version
alignment_method
alignment_config_digest
position_contract_digest
```

同模型名不足以判定 compatible。`model_revision_or_manifest_digest` 建议使用：

1. Hugging Face commit/revision，若本地模型保留；
2. 否则使用 `config.json`、tokenizer 文件和 `model.safetensors.index.json` 的组合 digest；
3. 不要求每次读取 61 GiB 权重计算全量 hash。

### 7.4 生命周期

```text
PREPARED
  -> worker 建立 capture context，但 ref 不可查询

COMMITTED
  -> exact latent_step_count/shape/dtype/digest 已冻结

LEASED
  -> Runtime 通过权限、TTL 和 compatibility gate

CONSUMING
  -> begin_consume 将 ref、consumer request 和 materialized prompt embeds 绑定；尚未计为消费

CONSUMED
  -> model-runner hook 已观察同一 request 的 inputs_embeds 真正进入 consumer model forward，finish_consume 原子记录 forward proof

RELEASED
  -> one-shot 请求完成后释放

EXPIRED
  -> TTL 到期，下一次访问返回稳定错误

REJECTED / INVALIDATED
  -> capture 不完整、digest 不匹配或兼容失败
```

只有 `CONSUMED` 可以计入 latent consumption。`PREPARED`、`COMMITTED`、lookup、lease、prompt materialization、`begin_consume` 或仅调用 engine `generate()` 都不能算消费。Middleware 不得自行伪造 `finish_consume`；该转换只能由 model-runner forward hook 提交的、与 `ref_id + request_id` 精确匹配的证据触发。

## 8. 同一 vLLM 服务的插件结构

### 8.1 为什么选择 middleware + worker extension

vLLM 0.9.2 已存在以下扩展点：

- `--middleware`：启动时将自定义 ASGI middleware 加入 OpenAI server；
- `--worker-extension-cls`：将不冲突的方法注入标准 Worker，用于 `collective_rpc`；
- `AsyncLLMEngine.collective_rpc()`：API server 与 worker 间调用扩展方法；
- V0 `ModelRunner.return_hidden_states`：可在 `SamplerOutput` 中返回最新 hidden；
- Qwen3 model forward 支持 `inputs_embeds`；
- `--enable-prompt-embeds`：engine 可接受完整 prompt embedding sequence。

因此第一版不需要：

- fork vLLM；
- 修改 site-packages；
- 新增 sidecar；
- 替换标准 Worker；
- 第二个模型服务端口。

但这些是 vLLM 0.9.2 的版本耦合扩展点，必须有启动时 readiness check 和 fail-closed 行为。

### 8.2 Middleware 职责

建议接口：

```text
GET  /statebus/latent/health
POST /statebus/latent/produce
POST /statebus/latent/complete
POST /statebus/latent/release
```

Middleware 负责：

- 解析和校验请求；
- 校验本地 bearer token；
- 限制只接受 loopback 请求；
- 在每次请求处理时从 `scope["app"].state.engine_client` 获取已初始化 engine，不在 middleware 构造阶段缓存尚未初始化的对象；
- 对所有 latent capture 加全局异步锁；
- 第一版 capture 期间串行化普通 inference；
- 调用 `engine_client.collective_rpc()`；
- 直接调用同一个 `engine_client.generate()`；
- 组装响应和 telemetry；
- 不接触模型权重细节。

为了保证 streaming 请求也不会提前释放锁，应实现原生 ASGI middleware，直到收到最终 `http.response.body` 且 `more_body=False` 才释放。不要只依赖可能提前返回 StreamingResponse 的简单 `BaseHTTPMiddleware` 上下文。

### 8.3 Worker extension 职责

建议公开给 collective RPC 的方法：

```text
statebus_latent_capabilities()
statebus_latent_begin(capture_spec)
statebus_latent_finish(capture_id)
statebus_latent_abort(capture_id, reason)
statebus_latent_describe(ref_id)
statebus_latent_materialize_consumer_prompt(ref_id, left_token_ids, right_token_ids)
statebus_latent_begin_consume(ref_id, request_id, prompt_embed_digest)
statebus_latent_finish_consume(ref_id, request_id, forward_proof)
statebus_latent_release(ref_id)
statebus_latent_sweep_expired()
```

worker extension 不替换调度器，也不允许任意 Python 方法名从外部透传。Middleware 只能调用固定 allowlist。

`begin_consume` 只建立一次性消费事务并将状态变为 `CONSUMING`。`finish_consume` 不能由 HTTP handler 在拿到 completion 后补写，而必须由 model-runner hook 在实际 consumer forward 内部触发。`forward_proof` 至少包含 `ref_id`、`request_id`、worker PID、engine ID、实际 `inputs_embeds` shape/dtype/digest 和 monotonic timestamp。若 forward 抛错、request ID 不匹配或 hook 未观察到目标 tensor，事务回滚或失效，绝不能进入 `CONSUMED`。

### 8.4 Engine-local registry

默认配置建议：

```text
STATEBUS_LATENT_REGISTRY_MAX_BYTES=67108864
STATEBUS_LATENT_REGISTRY_MAX_ENTRIES=64
STATEBUS_LATENT_TTL_S=60
STATEBUS_LATENT_MAX_STEPS=32
STATEBUS_LATENT_MAX_HIDDEN_SIZE=8192
STATEBUS_LATENT_ONE_SHOT=true
STATEBUS_LATENT_ALIGNMENT=soft_token_topk_v1
STATEBUS_LATENT_ALIGNMENT_TOP_K=32
STATEBUS_LATENT_ALIGNMENT_TEMPERATURE=1.0
```

registry 规则：

- committed tensor 立即转为 CPU BF16 contiguous；
- 不长期占用当前仅约 2.37 GiB 的 GPU KV 余量；
- 每次 put 前先 sweep expired；
- 超容量时只淘汰未 leased、最旧的 committed entry；
- leased entry 不允许被容量淘汰；
- 默认 one-shot，成功消费后释放；
- 保存 tensor SHA256、shape、dtype 和 byte count；
- 不记录原始证据文本；
- ref ID 使用随机不可猜 UUID，不使用 task ID 作为访问凭证。

40 个 BF16、hidden size 5120 的向量约为：

```text
40 * 5120 * 2 = 409,600 bytes
```

因此 64 MiB registry 足够做串行实验，同时不会引入无限内存增长。

## 9. Hidden producer 与 latent recurrence

### 9.1 必须捕获真实 hidden

不能把以下对象当作 producer 输出：

- 随机 embedding；
- Qwen3-Embedding-0.6B 的 semantic embedding；
- sampled token ID；
- token 的普通 input embedding；
- prefix hash；
- OpenAI completion 文本再做 embedding。

producer 必须来自 Qwen3-32B causal model 当前 forward 的末层 hidden。

### 9.2 推荐 hook 位置

第一次 `statebus_latent_begin()` 时：

1. 第一次安装 wrapper 时保存 `model_runner.execute_model` 原方法和原始 `return_hidden_states` 值；
2. `begin` 在全局锁内建立唯一 active capture，并临时设置 `model_runner.return_hidden_states=True`；
3. wrapper 只安装一次，后续 capture 不重复叠加 monkey patch；
4. wrapper 只在 active capture context 存在且 request ID 精确匹配时改变行为；
5. `finish`、`abort` 和异常清理都在 `finally` 中恢复原始 `return_hidden_states` 值并清除 active context；
6. 普通请求在无 active capture 时必须逐参数调用原方法，行为不变。

当前服务固定 `max_num_seqs=1`，第一版可使用“全局唯一 active capture + middleware 全请求串行锁”准确关联 request。不得在此基础上声称支持并发或 batch。

若 capture 结束后 `return_hidden_states` 未恢复、active context 未清空或 wrapper 层数不为 1，readiness 应转为 `not_ready`。不能让普通 `/v1/chat/completions` 长期承担 hidden capture 开销。

### 9.3 真正的 latent recurrence

仅捕获普通文本生成的 hidden trace，不足以称为 latent rollout。第一版应实现：

```text
prefill(prompt tokens)
  -> last hidden h0
  -> align(h0) = e1

decode step 1
  - scheduler 仍生成 bookkeeping token
  - model 实际输入由 wrapper 替换为 inputs_embeds=e1
  -> hidden h1
  -> align(h1) = e2

decode step 2
  - model 实际输入 inputs_embeds=e2
  -> hidden h2
  -> align(h2) = e3

...
  -> freeze [e1, e2, ... em]
```

实现要点：

- producer generation 使用 `max_tokens=latent_steps`；
- 使用 `ignore_eos=True`，避免 bookkeeping token 提前结束；
- 第一次 forward 是正常 text prefill；
- 后续 forward 使用 `dataclasses.replace(model_input, inputs_embeds=pending_latent)`；
- `input_tokens` 仅保留给 scheduler 维护序列，不再作为模型的下一步输入；
- 每步必须记录 hidden capture 和 latent injection；
- 只有 `captured_step_count == latent_steps` 且 `injection_count == latent_steps - 1` 才允许 COMMIT；
- 内部 sampled token 文本不返回、不存储，也不进入下游 Prompt。

当前必须保留 `--enforce-eager`。第一版不支持 CUDA graph，因为动态切换 decode input 为 `inputs_embeds` 会引入 graph key、buffer 和可观测性风险。

### 9.4 Alignment 方法

末层 hidden 不能直接假设属于 input embedding 分布。第一版建议实现两个显式方法。

#### `soft_token_topk_v1`，推荐默认

1. 从当前 hidden 计算原始 vocabulary logits；
2. 取固定 top-k；
3. 对 top-k logits 做 temperature softmax；
4. 读取对应 token input embeddings；
5. 做加权和，得到连续 soft-token embedding；
6. 按输入 embedding 平均范数做稳定归一化；
7. 作为下一 latent step 的 `inputs_embeds`。

这不是 hard argmax token。它保留 top-k 分布的连续混合，同时避免为 Qwen3-32B 构建昂贵的 5120 x 5120 ridge matrix。

实现上可在 active capture 时临时包装 `model.compute_logits`，保存当前 step 的 logits 引用；`execute_model` 返回后立即做 top-k 和 input embedding lookup，然后删除完整 logits 引用。

兼容 digest 必须包含：

```text
method=soft_token_topk_v1
top_k
temperature
normalization rule
model revision
input/output embedding identity
```

#### `identity_norm_v1`，只作诊断 fallback

将 hidden 按平均 input embedding norm 缩放后直接作为 `inputs_embeds`。它便于验证 hook 和 recurrence，但不能代替正式 alignment 质量证据。

#### Ridge realignment，后续研究项

LatentMAS 使用 output/input embedding 的 ridge/pseudo-inverse 风格 realignment。Qwen3-32B 的 vocab 和 hidden 规模使矩阵构建、临时 FP32 权重和求解成本较高。第一版不要为了复刻论文而挤占仅约 2.37 GiB 的服务余量。

如果后续实现 `ridge_realign_v1`，必须：

- 离线构建并固定 digest；
- 报告构建时间、峰值 CPU/GPU 内存和数值误差；
- 与 `soft_token_topk_v1` 做独立消融；
- 不在正式 case 上搜索 alignment 参数。

## 10. Latent consumer

### 10.1 双通道输入

Summarizer 同时接收：

```text
typed anchor channel
  - evidence item IDs
  - source locators
  - evidence pack hash
  - verified artifact rows

latent channel
  - opaque LatentStateRef
  - worker 内 BF16 aligned latent sequence
```

Runtime 保留原 EvidencePack 供最终 ClaimSetValidator 使用，但 latent lane 不把完整 evidence text 放进 Summarizer Prompt。

### 10.2 插入位置合同

消费者 Prompt 使用唯一 marker：

```text
<|statebus_latent_v1|>
```

构造规则：

1. Runtime 构造不含完整 evidence text 的 Summarizer prompt；
2. prompt 中 marker 必须且只能出现一次；
3. Middleware 将 rendered prompt 在 marker 处分成 left/right；
4. tokenizer 对 left/right 分别 `add_special_tokens=False`；
5. worker 生成 left/right token embeddings；
6. 拼接 `left_embeddings + latent_embeddings + right_embeddings`；
7. 调用 `statebus_latent_begin_consume()`，绑定 `ref_id`、consumer `request_id` 和完整 prompt-embed digest；
8. 用同一 engine 的 `generate({"prompt_embeds": tensor}, ..., request_id=request_id)` 解码，不得生成另一个内部 request ID；
9. model-runner hook 必须确认 `model_input.request_ids_to_seq_ids` 只包含该 `request_id`，并观察对应实际 `inputs_embeds` 进入 Qwen3 consumer forward，然后从 hook 内调用 `statebus_latent_finish_consume()`；
10. 只有 finish 证据与 begin 事务、shape/dtype/digest 全部一致，才记录 `consumed_ref_id` 并转为 `CONSUMED`。

`position_contract_digest` 必须覆盖 marker、chat template、左右 tokenization 规则和拼接顺序。

仅看到 `/statebus/latent/complete` 返回、engine 接受 `prompt_embeds` 或生成了文本都不构成消费证明。若 completion 已返回但没有匹配的 worker forward proof，Middleware 必须返回 `latent_consumer_forward_not_observed`，Runtime 释放或失效该 ref，并走文本 fallback。

### 10.3 结构化输出

`/statebus/latent/complete` 应接受可选 `response_schema`。当存在 schema 时，使用 vLLM 0.9.2 的 `GuidedDecodingParams(json=...)` 构造 `SamplingParams.guided_decoding`，保持 ClaimSet JSON 合同。

即使 guided decoding 成功，最终结果仍必须经过现有 `ClaimSetValidator`。模型生成成功不等于业务质量通过。

## 11. 同端口 API 合同

### 11.1 Health

```http
GET /statebus/latent/health
```

响应至少包含：

```json
{
  "status": "ready",
  "plugin_version": "statebus.vllm_latent.v1",
  "vllm_version": "0.9.2",
  "engine_generation": "V0",
  "model": "qwen3-32b",
  "hidden_size": 5120,
  "prompt_embeds_enabled": true,
  "worker_extension_ready": true,
  "max_num_seqs": 1,
  "tensor_parallel_size": 1,
  "registry_entries": 0,
  "registry_bytes": 0
}
```

只要 worker extension、版本或配置不满足，返回 `status=not_ready`，不能静默降级后仍报 ready。

### 11.2 Produce

```http
POST /statebus/latent/produce
```

请求示意：

```json
{
  "model": "qwen3-32b",
  "request_id": "latent-producer-uuid",
  "producer_role": "retriever",
  "consumer_role": "summarizer",
  "messages": [
    {"role": "system", "content": "...fixed retriever assimilation contract..."},
    {"role": "user", "content": "...selected narrative evidence..."}
  ],
  "latent_steps": 8,
  "alignment_method": "soft_token_topk_v1",
  "anchor": {
    "evidence_pack_hash": "sha256:...",
    "item_ids": ["ev-1", "ev-2"],
    "locator_digest": "sha256:..."
  },
  "ttl_s": 60,
  "expected_compatibility_digest": "sha256:..."
}
```

成功响应只返回 ref 和 telemetry，不返回内部 sampled text 或 tensor：

```json
{
  "ref_id": "latent-uuid",
  "status": "committed",
  "dtype": "bfloat16",
  "shape": [8, 5120],
  "tensor_bytes": 81920,
  "tensor_digest": "sha256:...",
  "captured_step_count": 8,
  "recurrence_injection_count": 7,
  "producer_pid": 123,
  "expires_at_ns": 0,
  "compatibility_digest": "sha256:..."
}
```

### 11.3 Complete

```http
POST /statebus/latent/complete
```

请求示意：

```json
{
  "model": "qwen3-32b",
  "request_id": "latent-consumer-uuid",
  "latent_ref_id": "latent-uuid",
  "rendered_prompt": "...anchors...<|statebus_latent_v1|>...ClaimSet instruction...",
  "response_schema": {},
  "sampling": {
    "temperature": 0.0,
    "max_tokens": 512,
    "seed": 7
  },
  "expected_compatibility_digest": "sha256:..."
}
```

响应至少包含：

```json
{
  "id": "statebus-latent-completion-uuid",
  "model": "qwen3-32b",
  "text": "{...ClaimSet JSON...}",
  "consumed_ref_id": "latent-uuid",
  "consumer_forward_observed": true,
  "consumer_forward_event_id": "forward-uuid",
  "prompt_embed_shape": [123, 5120],
  "usage": {
    "prompt_tokens_equivalent": 123,
    "completion_tokens": 100
  },
  "telemetry": {}
}
```

`consumer_forward_observed=true` 必须来自 `statebus_latent_finish_consume()` 保存的 worker event，不能由 Middleware 根据“请求没有抛异常”推断。

### 11.4 Release

```http
POST /statebus/latent/release
```

重复 release 应幂等。已过期 ref 与未知 ref 使用不同稳定错误码。

### 11.5 稳定错误码

至少定义：

```text
latent_plugin_not_ready
latent_auth_failed
latent_loopback_required
latent_capture_busy
latent_request_invalid
latent_model_incompatible
latent_alignment_incompatible
latent_position_contract_incompatible
latent_anchor_mismatch
latent_capture_incomplete
latent_ref_not_found
latent_ref_expired
latent_ref_already_consumed
latent_registry_capacity_exceeded
latent_consumer_forward_not_observed
latent_output_validation_failed
```

Runtime 必须基于 error code 回退，不能解析自由文本异常。

## 12. Planner 与 Runtime gate

### 12.1 四态总开关

```text
STATEBUS_LATENT_HANDOFF_MODE=off|shadow|planner_assist|force
```

语义：

| 模式 | 行为 |
|---|---|
| `off` | 默认；不调用插件，当前主线完全不变 |
| `shadow` | 可运行 producer/readiness，但最终仍使用文本；只做诊断，不计性能 |
| `planner_assist` | Planner 提出 intent，Runtime gate 决定 effective policy |
| `force` | 仅实验 lane；跳过 Planner 选择，但不能跳过兼容、权限、TTL 和质量 gate |

### 12.2 Runtime 激活条件

全部满足才启用：

```text
mode in {planner_assist, force}
Planner requested latent_assist，或 force lane
edge == Retriever -> Summarizer
evidence_kind contains narrative/semantic_context
selected evidence token estimate >= configured threshold
task is not exact-artifact-only
task is not numeric-table-only
producer and consumer model signature exact-compatible
plugin health ready
latent registry has budget
ClaimSetValidator available
fallback text path available
```

推荐初始阈值：

```text
STATEBUS_LATENT_MIN_EVIDENCE_TOKENS=1024
STATEBUS_LATENT_MAX_EVIDENCE_TOKENS=6144
```

不要按 case ID、family name、ticker、metric 或 expected facts 判断。

### 12.3 Gate 输出

每次都记录：

```text
requested_policy
effective_policy
checks[]
rejection_reason
plugin_health_digest
compatibility_digest
fallback_policy
```

Planner 的 rationale 只是建议，不构成权限。

## 13. 文本 fallback

任何失败都必须回到当前文本路径：

```text
produce 失败
  -> 不创建可见 LatentStateRef
  -> 当前 full-evidence Summarizer

compatibility/TTL/anchor gate 失败
  -> 不 materialize tensor
  -> 当前 full-evidence Summarizer

consumer forward 失败
  -> invalidate/release ref
  -> 当前 full-evidence Summarizer

ClaimSet validation 失败
  -> latent attempt 记为 quality rejection
  -> 当前 full-evidence Summarizer 只重试一次
```

最终报告必须区分：

```text
latent_attempted
latent_committed
latent_consumed
latent_quality_passed
text_fallback_used
final_task_passed
```

不能因为 fallback 最终通过，就把该 run 计为 latent success。

## 14. 实现顺序

### Phase 0：冻结现状

1. 保持当前 vLLM 服务运行；
2. 记录当前 Git SHA、dirty status、镜像 ID 和 vLLM 依赖版本；
3. 保存当前启动参数；
4. 保存容器内普通 text、structured JSON、prompt_embeds readiness 结果；
5. 当前正式实验继续保持 latent mode `off`。

退出门槛：插件代码尚未加载时，现有结果不变。

### Phase 1：纯合同与 fake backend

1. 新增 neural contracts；
2. 新增 lifecycle state machine；
3. 新增 compatibility compare；
4. 新增 `RoleModelBackend` SPI；
5. 新增 `LatentHandoffDecision`；
6. 使用 fake backend 覆盖 commit、lease、consume、expire、reject；
7. 确保 fake consumption 不会写成真实 worker forward。

这一阶段不需要重启 vLLM。

### Phase 2：registry 与 worker extension 单元测试

1. 实现有界 registry；
2. 使用 fake torch model/model runner 测 hook；
3. 验证普通请求无 active capture 时完全透传；
4. 验证 recurrence injection 计数；
5. 验证 capture 不完整不 commit；
6. 验证 TTL、capacity、one-shot 和幂等 release；
7. 验证 tensor 不出现在 API model dump/log。

仍不需要重启 vLLM。

### Phase 3：middleware 与 client 合同测试

1. 用 fake ASGI app/engine client 测四个 endpoint；
2. 测 auth、loopback、稳定错误码；
3. 测 streaming lock 生命周期；
4. 测 collective RPC allowlist；
5. 测 marker 恰好一次；
6. 测 schema-guided request；
7. 测 begin/finish consume 的 request、shape 和 digest 绑定；
8. 测 completion 成功但无 consumer forward proof 时 Runtime fallback。

仍不需要重启 vLLM。

### Phase 4：一次计划内重启和真实 vLLM probe

1. 停止当前前台服务；
2. 原命令只追加 middleware/worker extension 和 registry 环境变量；
3. 等待 Qwen3-32B 重新加载；
4. 从 embed 容器依次验证 health、text、prompt_embeds、produce、complete、release；
5. 先跑 2/4/8 latent steps；
6. 只有 worker telemetry 证明 recurrence injection 后才进入 Runtime 集成。

### Phase 5：Adaptive Runtime 集成

1. Planner schema 增加 handoff intent；
2. post-retrieval gate；
3. Retriever assimilation producer；
4. Summarizer latent consumer；
5. ClaimSetValidator；
6. fallback；
7. telemetry 和 artifact manifest；
8. negative signature 测试。

### Phase 6：小型实验

先完成本文第 18 节的 feasibility matrix。未通过门槛时停止，不把 latent 混入主实验。

## 15. 如何只重启一次

结论：首次加载 `--middleware` 和 `--worker-extension-cls` 必须重启 vLLM，因为这两个扩展在 engine/API server 启动时注入；修改已经被该进程 import 的插件代码或宿主 registry 配置后也需要重启。只修改 StateBus Runtime gate、client、Prompt、validator、容器内测试或实验 manifest，不需要重启 vLLM，只需重启相应的 StateBus 进程。

为避免 Qwen3-32B 重复加载约 7 分钟，先在 fake backend 和容器单元测试中完成 Phase 1-3，确认全部通过后再做一次 Phase 4 计划内重启。当前文档编写阶段不重启服务。

### 15.1 重启前检查

插件代码、fake tests 和 middleware tests 全部通过后，再执行：

```bash
docker exec statebus-dev-qcrs python3 -m pytest -q tests/v2/neural
```

随后只做宿主启动兼容预检。它用于避免模型加载后才发现 import 失败，不作为 StateBus 测试证据：

```bash
source /home/qcrs/statebus/conda-envs/vllm-qwen-cu121/bin/activate
export PYTHONPATH=/home/qcrs/statebus/project

python - <<'PY'
from v2.integrations.vllm_latent.middleware import LatentHandoffMiddleware
from v2.integrations.vllm_latent.worker_extension import LatentWorkerExtension

print(LatentHandoffMiddleware.__module__)
print(LatentWorkerExtension.__module__)
PY

vllm serve --help | rg -n \
  "enable-prompt-embeds|enable-prefix-caching|worker-extension-cls|middleware"
```

任何 import、方法签名或 flag 检查失败都先修复，不停止当前服务。记录当前完整启动命令和 PID，确保回滚时能原样恢复普通路径。

确认 GPU 2 没有其他任务占用：

```bash
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader
```

不要终止其他用户进程。

### 15.2 停止当前前台服务

如果当前 vLLM 在你的终端前台运行，使用：

```text
Ctrl-C
```

确认端口释放：

```bash
curl -sS --max-time 2 http://127.0.0.1:53334/health
```

预期连接失败。不要同时启动第二个 `53334` 实例。

### 15.3 带插件启动

先在宿主的 StateBus work root 创建本地 API token。token 只保存在共享 work volume，不写入 repo、命令参数或日志：

```bash
umask 077
TOKEN_FILE=/home/qcrs/statebus/work/latent_api.token
if [ ! -s "$TOKEN_FILE" ]; then
  openssl rand -hex 32 > "$TOKEN_FILE"
fi
chmod 600 "$TOKEN_FILE"
```

宿主插件读取：

```text
/home/qcrs/statebus/work/latent_api.token
```

容器内 StateBus client 读取同一挂载文件：

```text
/statebus/work/latent_api.token
```

重启前先确认容器能看到非空文件，但不要输出内容：

```bash
docker exec statebus-dev-qcrs test -s /statebus/work/latent_api.token
```

激活原 vLLM 环境：

```bash
source /home/qcrs/statebus/conda-envs/vllm-qwen-cu121/bin/activate
```

前台启动，第一次不要使用 nohup：

```bash
export PYTHONPATH=/home/qcrs/statebus/project
export STATEBUS_LATENT_API_TOKEN_FILE=/home/qcrs/statebus/work/latent_api.token
export STATEBUS_LATENT_REGISTRY_MAX_BYTES=67108864
export STATEBUS_LATENT_REGISTRY_MAX_ENTRIES=64
export STATEBUS_LATENT_TTL_S=60
export STATEBUS_LATENT_MAX_STEPS=32
export STATEBUS_LATENT_ONE_SHOT=true
export STATEBUS_LATENT_ALIGNMENT=soft_token_topk_v1
export STATEBUS_LATENT_ALIGNMENT_TOP_K=32
export STATEBUS_LATENT_ALIGNMENT_TEMPERATURE=1.0

CUDA_VISIBLE_DEVICES=2 \
VLLM_USE_V1=0 \
vllm serve /data/models/Qwen3-32B \
  --host 127.0.0.1 \
  --port 53334 \
  --served-model-name qwen3-32b \
  --dtype bfloat16 \
  --tensor-parallel-size 1 \
  --max-model-len 8192 \
  --max-num-seqs 1 \
  --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.82 \
  --enable-prefix-caching \
  --enable-prompt-embeds \
  --enforce-eager \
  --worker-extension-cls v2.integrations.vllm_latent.worker_extension.LatentWorkerExtension \
  --middleware v2.integrations.vllm_latent.middleware.LatentHandoffMiddleware
```

第一轮重启只增加两个 plugin 参数，不同时改变 model、port、context、GPU utilization、prefix、sampling defaults 或 TP。这样启动前后差异可归因。

`STATEBUS_LATENT_HANDOFF_MODE` 是 StateBus Runtime 的策略配置，不是宿主 vLLM 进程配置。应在 `statebus-dev-qcrs` 内启动 Runtime/测试进程时设置：

```bash
export STATEBUS_LATENT_HANDOFF_MODE=off
export STATEBUS_LATENT_API_TOKEN_FILE=/statebus/work/latent_api.token
```

若 Runtime 由 Compose 或其他常驻进程启动，应把这两个变量配置到该容器进程环境；只在宿主 shell 中 export 不会传入容器，只在某次临时 `docker exec` 中 export 也不会改变其他进程。默认保持 `off`，此时插件 health/readiness 仍可探测，但 Runtime 不会自动选择 latent。真实机制 probe 可以显式调用实验 endpoint；完成 Runtime 集成和门控验证后，才允许在独立实验运行中切到 `planner_assist`。

### 15.4 必须看到的启动证据

日志至少应出现：

```text
Injected ... LatentWorkerExtension ... extended collective_rpc calls
StateBus latent middleware initialized
StateBus latent worker extension ready
Starting vLLM API server ... 127.0.0.1:53334
Application startup complete
```

缺少 worker injection 时，即使 `/v1/chat/completions` 可用，也不能继续 latent 测试。

### 15.5 回滚启动

若插件导致启动失败，删除两个参数并使用原命令启动。不要卸载 vLLM，不要回退 Torch，也不要修改 StateBus 容器：

```text
删除：--worker-extension-cls ...
删除：--middleware ...
保留：--enable-prompt-embeds
保留：--enable-prefix-caching
保留：VLLM_USE_V1=0
```

## 16. 容器内测试要求

### 16.1 唯一正式测试环境

所有 pytest、StateBus Runtime、client smoke 和正式实验都在：

```text
statebus-dev-qcrs
statebus-dev-openeuler:24.03-lts-sp3-embed
```

宿主机只负责：

- 启动 vLLM；
- Docker 编排；
- GPU/进程检查；
- Git 操作；
- 读取 artifact。

宿主机随机 Python 脚本不能成为正式 StateBus 测试证据。

### 16.2 基础回归

```bash
docker exec statebus-dev-qcrs curl -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:53334/health

docker exec statebus-dev-qcrs curl -sS \
  http://127.0.0.1:53334/v1/models
```

然后运行现有 StateBus client structured JSON smoke，确认插件没有改变普通路径。

### 16.3 Plugin health

使用后续实现的 readiness 脚本。脚本从 token file 读取 secret 并放入 HTTP Authorization header，不把 token 作为命令参数或日志输出：

```bash
docker exec \
  -e STATEBUS_LATENT_API_TOKEN_FILE=/statebus/work/latent_api.token \
  statebus-dev-qcrs \
  bash scripts/check_vllm_latent_readiness.sh
```

必须检查 JSON 字段，而不是只看 HTTP 200。脚本和 client 的 debug/error 日志都只能记录 token file path、auth success/failure 和稳定错误码，不能记录 bearer value。

### 16.4 真实 producer smoke

脚本必须从容器发起，断言：

```text
HTTP 200
shape == [latent_steps, 5120]
dtype == bfloat16
captured_step_count == latent_steps
recurrence_injection_count == latent_steps - 1
tensor_bytes == latent_steps * 5120 * 2
tensor_digest 非空
响应中没有 tensor/base64/internal sampled text
```

### 16.5 真实 consumer smoke

断言：

```text
consumed_ref_id == produced ref_id
consumer_forward_observed == true
prompt_embed_shape[-1] == 5120
输出可解析
one-shot 模式下再次消费返回 latent_ref_already_consumed
```

### 16.6 Negative tests

至少覆盖：

- model revision 不同；
- alignment digest 不同；
- position contract 不同；
- anchor pack hash 不同；
- TTL 已过期；
- unknown ref；
- duplicate marker；
- capture step 不完整；
- registry 超容量；
- 同时发起第二个 capture；
- 非 loopback 请求；
- 无效 token；
- `begin_consume` 成功但 worker 未观察到 forward，状态不得变为 `CONSUMED`；
- worker forward 的 request ID、shape 或 digest 与 begin 事务不一致；
- plugin mode off 时 Runtime 不自动调用；
- consumer 失败后文本 fallback 通过。

所有不兼容测试必须在 materialize/forward 前拒绝。

### 16.7 定向回归

```bash
docker exec statebus-dev-qcrs python3 -m pytest -q \
  tests/v2/neural \
  tests/v2/test_adaptive_contracts.py \
  tests/v2/test_adaptive_dispatcher.py \
  tests/v2/test_adaptive_planner_policy.py \
  tests/v2/test_adaptive_role_prompts.py \
  tests/v2/test_local_vllm_wrappers.py \
  tests/v2/test_kv_prefix_control_plane.py
```

### 16.8 完整回归

定向回归通过后：

```bash
docker exec statebus-dev-qcrs python3 -m pytest -q tests/v2
```

不得用宿主机 pytest 结果替代。

## 17. Telemetry

每次 producer 至少记录：

```text
request_id
ref_id
producer_role
worker_pid
engine_id
model_revision
compatibility_digest
source_evidence_pack_hash
anchor_digest
latent_steps_requested
hidden_steps_captured
latent_steps_committed
recurrence_injection_count
alignment_method/config_digest
raw_hidden_shape
aligned_tensor_shape/dtype/bytes/digest
producer_prefill_ms
latent_rollout_ms
d2h_ms
registry_commit_ms
created_at_ns/expires_at_ns
```

每次 consumer 至少记录：

```text
request_id
ref_id
lease_ms
compatibility_gate_ms
registry_load_ms
h2d_ms
left/right token counts
latent vector count
combined prompt embed shape/bytes
consumer_forward_observed
consumer_forward_event_id/timestamp
consumer_forward_inputs_embeds_shape/dtype/digest
consumer_model_ms
completion_tokens
ClaimSet validation verdict
release_ms
fallback reason
```

聚合指标至少包括：

- latent requested/accepted/rejected；
- committed/consumed/quality-passed；
- text fallback count；
- producer completion token count，理论上为 0 个可见 handoff token；
- hidden-derived tensor bytes；
- text handoff bytes/tokens；
- Summarizer prompt-visible evidence tokens；
- end-to-end latency；
- task quality；
- registry peak entries/bytes；
- expired/evicted refs。

不要把内部 bookkeeping sampled tokens 报成 Agent 文本通信，但应单独记录 `internal_scheduler_sample_count`，避免隐去计算。

## 18. 最小实验设计

### 18.1 先验证需求，不先追求胜率

使用 6 个离线长叙事 case：

- 2 个跨段落时间限定；
- 2 个冲突证据或风险判断；
- 2 个条件与例外组合。

expected facts 只用于生成后评分，不进入 Planner、Retriever、producer、Summarizer 或 gate。

### 18.2 对照 lane

| Lane | Summarizer 可见信息 | 回答的问题 |
|---|---|---|
| C0 | anchors + verified artifact + 完整 selected evidence text | 当前 full-evidence 上限 |
| T0 | anchors + verified artifact + Retriever 最多 128-token 文本分析 | 真实文本 Agent handoff |
| A0 | anchors + verified artifact，无 evidence/analysis/latent | anchor 是否已经足够 |
| L1 | anchors + verified artifact + engine-local LatentStateRef | latent 是否带来 anchor 外信息 |
| N1 | 存在 ref 但 signature 被修改，随后 C0 fallback | gate 和回退是否真实 |

第一版不需要同时加入 memory、CodeAct、prefix policy 变化或多后端。固定：

```text
同一 Qwen3-32B
同一 vLLM 0.9.2/V0
同一 Retriever/Summarizer prompt bundle
temperature=0
相同 seed 和 max tokens
串行请求
STATEBUS_PREFIX_ALIGNMENT_MODE=independent
memory 对这组实验关闭
CodeAct 不参与
```

### 18.3 预注册门槛

建议门槛：

- C0 先证明任务本身可解；
- L1 质量不得明显低于 C0，且不得低于 T0；
- L1 必须显著优于 A0，否则当前 workload 没有 latent 需求；
- 6/6 有真实 hidden capture；
- 6/6 recurrence injection 大于 0；
- 6/6 有 committed ref 和 consumer forward event；
- 6/6 anchor/digest/shape 一致；
- N1 全部在 forward 前拒绝并成功文本 fallback；
- tensor bytes、producer compute 和 D2H/H2D 全部单列；
- 不强制要求端到端更快。

如果质量恢复但时延更差，允许结论为：

> engine-local latent 状态传递机制成立，但当前 Qwen3-32B 单请求实现尚未形成性能收益。

如果 L1 与 A0 无差异，应停止扩展，并结论为当前任务不需要 latent。不能换 task 或调 expected answer 强行制造优势。

## 19. 资源与安全边界

### 19.1 GPU 内存

当前权重已占约 61 GiB，KV 余量只有约 2.37 GiB。规则：

- registry 只存 CPU BF16；
- 每步 aligned vector 完成后尽快 D2H；
- GPU 只保留下一步 pending latent；
- 删除 full logits 临时引用；
- 不缓存 raw hidden sequence；
- `torch.cuda.empty_cache()` 不应每步调用，只在异常清理或显式诊断使用；
- 超预算 fail closed，不降低 KV cache 到不可运行值。

### 19.2 API 安全

- 服务继续只绑定 `127.0.0.1`；
- latent endpoint 使用独立 bearer token；宿主插件从 `/home/qcrs/statebus/work/latent_api.token` 读取，容器 client 从 `/statebus/work/latent_api.token` 读取；
- token 文件权限设为 `0600`，不得提交到 Git、写入镜像、放进 Prompt、出现在进程命令行或打印到日志；
- token 缺失、空文件、权限过宽或请求鉴权失败时，latent plugin fail closed，但普通 OpenAI 路径保持可用；
- ref ID 不可枚举；
- 请求限制 body size；
- 日志不打印 evidence、tensor、base64 或完整 Prompt；
- `torch.load` 不用于不可信 latent payload，因为 tensor 不从客户端上传；
- collective RPC 方法固定 allowlist；
- 不允许客户端指定 Python qualname、文件路径、device 或任意 worker method。

### 19.3 版本耦合

插件依赖 vLLM 0.9.2 V0 内部对象。每次升级 vLLM 都必须先运行：

```text
method existence check
signature check
fake hook tests
real 2-step probe
ordinary text regression
```

版本不匹配时 plugin health 返回 not_ready，普通 OpenAI 路径仍应可用。

## 20. 参考资料

### 20.1 LatentMAS 论文

- Jiaru Zou et al., *Latent Collaboration in Multi-Agent Systems*, ICML 2026, PMLR 306；
- 论文：`docs/2511.20639v3.pdf`
- arXiv：https://arxiv.org/abs/2511.20639
- 本地 SHA256：`10a9d1d141cfac51720abcd476d200f275db54d5ff3c74ec86a6f65341418ca2`

主要参考：

- 中间 Agent 从 token communication 转向 latent communication 的动机；
- 末层 hidden 的多步 latent recurrence；
- output hidden 到 input embedding space 的 alignment；
- 最终 consumer 通过 prompt embeddings 解码；
- TextMAS/LatentMAS 相同拓扑的对照实验思路。

必须明确差异：论文的跨 Agent latent working memory 包含 layer-wise KV cache；本文第一版只保存和传递有界的 aligned latent embedding sequence，不实现 KV handoff。因此本文是受其启发的 StateBus experimental mechanism，不是 LatentMAS 复现，也不能沿用论文的 `pure latent collaboration`、`lossless` 或复杂度结论。

不能直接继承：

- 论文速度和 token 降幅；
- lossless working-memory transfer 声明；
- 同构模型假设以外的泛化；
- StateBus 的跨进程 Ref、权限、validator 和 fallback 证据。

### 20.2 LatentMAS 开源实现

- 本地：`third_party/LatentMAS`
- commit：`9a9e4d331eb11430bd9e64754c6b252b06d73031`
- license：Apache-2.0
- upstream：https://github.com/Gen-Verse/LatentMAS

关键参考文件：

- `models.py::_build_latent_realign_matrix()`；
- `models.py::generate_latent_batch()`；
- `models.py::generate_latent_batch_hidden_state()`；
- `methods/latent_mas.py` 的 prompt embedding consumer。

StateBus 不直接复制其 vLLM 修改。第一版采用 vLLM 0.9.2 原生扩展点，并在文档中明确 alignment 方法差异。

### 20.3 vLLM 0.9.2

- upstream tag：https://github.com/vllm-project/vllm/tree/v0.9.2
- `vllm/worker/worker_base.py`：`worker_extension_cls` 动态注入；
- `vllm/engine/async_llm_engine.py`：`collective_rpc()` 与 `generate()`；
- `vllm/worker/model_runner.py`：`return_hidden_states`、`inputs_embeds` 和 `SamplerOutput.hidden_states`；
- `vllm/model_executor/models/qwen3.py`：Qwen3 forward 的 `inputs_embeds`；
- `vllm/entrypoints/openai/api_server.py`：`--middleware` 加载；
- `vllm/entrypoints/openai/serving_engine.py`：在线 `prompt_embeds` 解码。

采用这些接口前必须以当前安装源码和 readiness test 为准，不能只看 README。

### 20.4 KV 系统，仅用于划清边界

- LMCache：https://github.com/LMCache/LMCache
- Mooncake：https://github.com/kvcache-ai/Mooncake

它们处理 external KV/prefill reuse，不是本文的 Retriever -> Summarizer latent handoff。第一版不集成。

## 21. 防止“声称实现、实际作弊”

以下任一情况都不能写“实现了 latent handoff”：

- 只验证随机 `prompt_embeds` 返回 200；
- 只增加 `LatentStateRef` dataclass；
- 只登记 registry handle；
- hidden 来自 embedding model；
- 将生成文本重新 embedding 后冒充 hidden；
- 只捕获普通 token generation trace，却没有 latent recurrence injection；
- consumer Prompt 仍包含完整 evidence text；
- expected facts 或 expected route 进入 Prompt/gate；
- 按 case ID 启用 latent；
- fallback 通过后把 run 计为 latent success；
- 不报告 tensor bytes、producer compute 或 D2H/H2D；
- ref lookup 成功但没有 consumer forward event；
- 使用不同模型比较 text 和 latent；
- 将 engine-local latent 称为 external KV 或跨模型 transfer；
- 用 prefix/APC hit 代替 latent consumption。

一条合格 evidence row 至少需要：

```text
task_id
requested/effective handoff policy
ref_id
producer/consumer role
worker PID/engine ID
model revision
compatibility digest
anchor hashes
hidden captured steps
recurrence injection count
alignment method/digest
tensor shape/dtype/bytes/digest
commit/lease/consume/release timestamps
consumer forward event
text fallback reason
ClaimSet quality verdict
```

## 22. 完成定义

只有以下全部完成，才把状态从“planned”改为“experimental implemented”：

- [ ] contracts 和 canonical hash tests；
- [ ] lifecycle/TTL/capacity tests；
- [ ] worker extension fake tests；
- [ ] middleware fake engine tests；
- [ ] Runtime gate/fallback tests；
- [ ] 普通 OpenAI 路径无回归；
- [ ] 真实 Qwen3 hidden capture；
- [ ] 真实 recurrence injection；
- [ ] engine-local tensor commit；
- [ ] opaque ref consumer；
- [ ] real prompt embeds forward，并由 begin/finish consume 事务绑定 worker forward proof；
- [ ] ClaimSetValidator 通过；
- [ ] incompatible signature 在 forward 前拒绝；
- [ ] one-shot release 和 TTL 清理；
- [ ] 定向测试在 embed 容器通过；
- [ ] `tests/v2` 在 embed 容器通过；
- [ ] 运行 artifact 记录 Git SHA、镜像 ID、vLLM/torch/transformers、模型 revision 和启动参数；
- [ ] validation report 明确区分 readiness、mechanism、quality 和 performance。

只有 feasibility matrix 也通过后，才允许写“latent 对当前 long-narrative workload 有作用”。只有串行正式测量显示正收益后，才允许写“降低时延”。

## 23. 最终执行提示

后续实现者必须按以下顺序工作：

1. 不重启当前服务，先完成合同、registry、worker fake、middleware fake 和 Runtime fallback；
2. 所有 pytest 在 `statebus-dev-qcrs` embed 容器内运行；
3. 在 fake/contract tests 全绿后，只做一次带插件参数的 vLLM 重启；
4. 先证明 ordinary text 不回归；
5. 再证明真实 hidden capture 和 recurrence injection；
6. 再证明 opaque ref consumer forward；
7. 再接 Adaptive Runtime 和 ClaimSetValidator；
8. 最后运行小型 C0/T0/A0/L1/N1 matrix；
9. 任一真实性门槛不满足时，保留 embedding StateRef 主线，latent 维持 experimental 或记录负结果；
10. 不因实现难度而降低兼容、安全、回退或证据标准。

最终目标不是展示一个能接收任意 embedding 的接口，而是证明：

> 在不改变普通 StateBus 路径的前提下，Retriever 的真实模型 hidden 能在同一 vLLM engine 中形成受控 latent recurrence，经 opaque、可授权、可过期的 LatentStateRef 被 Summarizer 实际消费，并且最终输出仍由原始 evidence/artifact validator 验证；当该机制不适用或失败时，系统可以确定性回退到现有文本路径。

# 模型侧状态路径

模型侧路径插在 Runtime 主链的不同位置：

~~~mermaid
flowchart LR
    T[CanonicalTaskSpec] --> R[Retriever]
    R --> E[Embedding / SemanticStateRef]
    E --> X[EvidencePack]
    X --> G[Executor]
    G --> L[LogitStateRef / GateReceipt]
    L --> C[CodeAct / Artifact]
    C --> S[Summarizer]
    X -. common token prefix .-> P[APC / vLLM engine-local cache]
    G -. producer handle .-> K[Explicit KV / same Worker]
    K -. suffix continuation .-> S
~~~

| 路径 | 当前对象 | 接入点 | 默认状态 |
| --- | --- | --- | --- |
| Embedding | SemanticStateRef | Retriever candidate/evidence 选择 | 由 task/runtime 配置决定 |
| Logit | LogitStateRef、LogitGateReceipt | Executor 闭集选择后、dispatch 前 | off |
| APC | canonical prefix、exact-token identity、counter delta | 完整请求发送到同一 vLLM engine 前 | alignment independent、policy off |
| 显式 KV | EngineLocalKVHandle、forward proof | Producer Executor 到 Consumer Summarizer | off |

Embedding 和 Logit 使用 StateBus 的 Ref、sidecar 和 typed control path。APC 只观察同一 vLLM engine 的 token block reuse；显式 KV 只在兼容的 engine generation 和 Worker registry 内传递短生命周期 handle。它们不改变 Task、EvidencePack、Artifact 或 quality gate。

## 当前可达行为

- Embedding 发布 query/candidate matrix；consumer 解析 SemanticStateRef，选择 row，再由 Runtime hydrate 回 evidence ID。
- Logit 只接受闭集候选概率。Gate 校验 state、candidate surface、PID 和 receipt；retry_once 在首次 retry 后最多再请求一次，第二次仍不满足时 fail closed。
- APC 先构造参与角色共同可见且 digest 一致的 evidence prefix，再用真实 tokenizer 计算 exact-token identity；counter delta 无效时只把观测记为 unavailable。
- 显式 KV 由 producer capture、consumer load、forward proof 和 finally release 组成。handle unavailable 的处理由实验或产品 profile 明确选择，不能隐式改变主链。

## 机制边界

APC 是 engine-local cache hit，不是跨进程 KV tensor 传输。显式 KV 是同一 vLLM Worker 的 connector/registry 路径，不是任意 Agent 间的 hidden state 交换。provider tokens、logical tokens、computed prefill 和 KV bytes 分别记录，不能互换。

## 代码与结果

| 主题 | 代码 | 证据/说明 |
| --- | --- | --- |
| Semantic State | src/statebus/state/semantic_state.py、src/statebus/runtime/state_consumption.py | [稠密语义状态](../state/dense-semantic-state.md) |
| Logit Gate | src/statebus/runtime/logit_gate.py、logit_state.py | [Logit Retry Gate](logit-retry-gate.md) |
| APC | src/statebus/runtime/prefix_identity.py、prefix_feedback.py | [Engine-Local Prefix Reuse](engine-local-prefix-reuse.md) |
| 显式 KV | src/statebus/integrations/vllm_kv/、contracts/engine_local_kv.py | [Engine-Local KV Continuation](engine-local-kv-continuation.md) |
| utility runner | src/statebus/benchmark/model_assist_utility/ | [实验与证据](../../experiments/README.md) |

APC、KV、Logit 的当前计分分母分别为 8、8、12，共 28 个位置；它们是独立 utility 链，不是 48 个主链任务的新结果。

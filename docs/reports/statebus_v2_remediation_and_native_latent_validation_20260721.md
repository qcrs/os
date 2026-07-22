# StateBus v2 Remediation and Native Latent Validation

日期：2026-07-21

分支：`feat/yzm-v2-migration`

基线 HEAD：`bda17745ecb8a160221efe3b58ca678644dac81a`

最终 run root：`/home/qcrs/statebus/runs/statebus_v2_remediation_latent_20260721_204150`

## 1. 最终结论

Track R 的 F-01 到 F-12 已完成实现、负向回归和 openEuler 容器完整回归。Track L 已达到 `experiment-complete`，更准确的状态是：

```text
contracts/fake complete
  + real Qwen3-32B mechanism complete
  + 30/30 preregistered samples complete
  + quality/performance benefit not established
```

真实 Qwen3-32B 机制证据成立：Retriever worker hidden capture、有界 aligned recurrence、engine-local BF16 tensor commit、opaque `LatentStateRef`、Summarizer `prompt_embeds` worker-forward proof、one-shot、release 和 incompatible-signature pre-forward rejection 均有真实 artifact。2/4/8-step probe 全部通过；正式实验的 6 个 L1 case 也全部完成 8-step capture、7 次 recurrence、`[8,5120]` BF16 tensor、worker-forward proof 和 release。

收益结论不成立。预注册质量门要求 C0 至少命中 22/24 facts，但实际 C0 只有 17/24，因此实验解释为 `task_design_failed_c0_not_solvable`。L1 为 0/24、A0 为 0/24、T0 为 9/24；不能声明 latent 质量收益。L1 总耗时中位数为 48.824 秒，高于本次 A0 和 C0 的描述性中位数；同时各 lane 质量不等、T0 还有一条无有效耗时的失败样本，因此也不能声明 latency benefit。

最终容器测试均通过：定向集合 `112 passed`，完整 `tests/v2` 为 `671 passed`，仓库全量为 `973 passed, 1 warning`。唯一 warning 是 LangGraph 上游 `allowed_objects` 默认值将变化的 pending-deprecation 提醒。

## 2. 证据分层

| 层级 | 已证明 | 未据此声明 |
| --- | --- | --- |
| Track R correctness/security | allowlist、field support、receipt accounting、authenticated grant、typed negotiation、worker-owned operation、typed telemetry | production-grade sandbox、跨租户安全 |
| Contract/fake proof | latent contracts、registry、worker extension、middleware/client、Runtime gate、fallback、cleanup | 真实模型执行 |
| Real mechanism proof | Qwen3 hidden、recurrence、opaque ref、consumer worker-forward、one-shot/release | 质量或速度收益 |
| Quality | 30 个样本的 post-generation fact score | C0 未过可解门，因此不评价 latent 优越性 |
| Performance | 串行样本耗时和组件 telemetry | equal-quality gate 未过，不做 superiority claim |

主合同 SHA256：

- Review remediation：`c2c0561f752969b7fa8092078293c8f4a7c9e11072700ac3887cc45648128712`
- Native latent freeze：`da60d1756bf84cd4aaa5dae4ab095a405b469eb63e4bd0d36ff2ece730488ef6`

## 3. Track R：F-01 到 F-12

| ID | 状态 | 实现与验证结果 | 声明边界 |
| --- | --- | --- | --- |
| F-01 | complete | `PlanPolicyValidator` 对 descriptor outputs 与 task envelope 做交集校验，repair/fallback 后再次校验；负例覆盖 excluded output 和 authority expansion | Controller normalization 只能补 typed wiring，不能扩大 envelope |
| F-02 | complete | Claim v2 增加 field-level support、normalized value hash、source locator 和 artifact field path；双来源 qualifier、borrowed locator、hash mismatch 均 fail closed | latent/embedding 不能替代最终事实字段的 source citation |
| F-03 | complete | candidate、disclosed、rendered、recipe-executed、actual-consumed 分开；只有 role receipt 或实际 recipe hash 产生 consumption | assist candidate 没有 receipt 时 `memory_consumed_count=0` |
| F-04 | complete | 聚合从 raw rows 重算 recorded 与 receipt-backed 数量；历史 E3 的 `23` 只称 recorded consumption | 历史 artifact 不回写 |
| F-05 | complete | HMAC token 绑定 task/session/step/attempt/ref/output、expiry 和 nonce；校验 tamper、single-use 与 peer UID | 单机 Controller-worker 鉴权，不是跨租户生产认证 |
| F-06 | scoped complete | semantic selector 只得到单对象只读 view；mmap 复制到 scoped root，metadata/manifest/payload 只读 | worker 仍共享宿主 Unix identity，不声明生产级 OS 隔离 |
| F-07 | complete | owner、logical step、physical component/PID/UID、downstream role 分字段；counter 从原子事件聚合，PID 仅为 identity set | 不再生成 PID sum |
| F-08 | mechanism complete, gain unproven | recipe template 与 task bindings 分离；changed arguments 必须 schema-compatible；repair 后不计 validated replay/LLM skip | natural memory 尚无非零 `skipped_llm_call_count` 证据，仍称 assist-style reuse |
| F-09 | complete | typed wire 使用 `HELLO -> HELLO_ACK -> ExecRequest`，执行前校验 protocol/schema/registry digest/capability；pre-Hello 请求拒绝 | UTF-8 carrier 无 negotiation，并明确记录 0 negotiation frames |
| F-10 | typed mechanism complete | `typed_numeric_summary_v1` 从授权 inherited memfd 读取 vector 并在 worker 计算；返回 output hash、schema digest、validator receipt、PID 和 compute time，Controller 独立复算 | 机制证据，不作为业务端到端性能对比 |
| F-11 | complete | Planner 每例只属于 directly executable、controller normalized、model repaired、hard rejected/fallback 之一；aggregate 强制 one-hot partition | success 不再暗示 raw plan 可直接执行 |
| F-12 | complete with negative timing result | serialized ABBA/BAAB、3 blocks、median/P90/P95、deterministic bootstrap CI、paired block delta 和 component summary 已实现 | typed carrier 与 end-to-end latency superiority 均未获授权 |

关键代码边界位于 `v2/runtime/plan_policy.py`、`v2/runtime/claims.py`、`v2/runtime/adaptive_dispatcher.py`、`v2/runtime/capability_grants.py`、`v2/control/transport.py`、`v2/control/subprocess_worker.py`、`v2/control/worker_operations.py`、`v2/parameterized_recipe.py` 和 `v2/runtime/telemetry.py`。对应回归由 `tests/v2/test_adaptive_planner_policy.py`、`test_adaptive_claims.py`、`test_memory_runtime.py`、`test_capability_grant_auth.py`、`test_control_plane.py`、`test_subprocess_executor.py`、`test_experiment_design.py` 等覆盖。

### 3.1 F-12 fresh carrier experiment

Artifact：`evidence/track_r/control_transport_summary.json`

| 指标 | typed Protobuf | UTF-8 text |
| --- | ---: | ---: |
| observations | 6 | 6 |
| median ms | 1058.224 | 1006.214 |
| P90 ms | 1180.665 | 1297.591 |
| P95 ms | 1228.074 | 1370.675 |

三组 paired block 的 `typed - text` median 为 `61.684 ms`，95% bootstrap interval 为 `[-205.501, 91.460] ms`。区间跨 0，所以：

- `carrier_latency_claim_allowed=false`；
- `end_to_end_latency_superiority_claim_allowed=false`；
- 不声明 typed Protobuf 比 UTF-8 更快或 bytes 更小。

## 4. Track L：合同与 fake proof

新增的合同和实现边界包括：

- `v2/contracts/neural.py`：`NeuralCompatibilitySignature`、`LatentAnchor`、gate decision、forward proof 和 lifecycle event；
- `v2/refs/models.py`：独立 opaque `LatentStateRef`，没有把它折回普通 `StateRef`；
- `v2/integrations/vllm_latent/registry.py`：bounded CPU BF16 registry、TTL、capacity、lease、one-shot、proof-bound consume、release；
- `v2/integrations/vllm_latent/worker_extension.py`：hidden capture、soft-token alignment、recurrence、consumer forward hook；
- `v2/integrations/vllm_latent/middleware.py`：同端口 ASGI route、loopback、0600 token auth、body limit、RPC allowlist、稳定错误码；
- `v2/integrations/vllm_latent/client.py`：同步/异步 client，token 值不进入日志或 artifact；
- `v2/runtime/latent_handoff.py`：mode、post-retrieval gate、produce/consume proof 校验、单次 fallback；
- `v2/runtime/adaptive_dispatcher.py` 和 `adaptive_mainline.py`：Retriever commit、Summarizer consume、telemetry、manifest 和 cleanup；
- `scripts/start_vllm_qwen3_32b_latent.sh`、readiness/mechanism/negative probe 脚本：可审计启动和验证入口。

Fake/contract tests 覆盖 normal passthrough、hidden recurrence、incomplete capture、concurrent capture、registry capacity、TTL、anchor/signature mismatch、forward-binding mismatch、middleware auth、loopback、mode off、fallback exactly once 和 release exactly once。Fake backend 明确不能产生 real latent consumed counter。

Adaptive Runtime 集成已经进入主代码并通过 fake/contract 回归；真实 vLLM 证明由专用 Phase 4 probe 和 Phase 6 实验 harness 完成。本报告不把 fake mainline test 写成真实模型 mainline execution。

## 5. Real vLLM mechanism proof

### 5.1 支持矩阵与 readiness

当前经过真实验证的矩阵固定为：

```text
vLLM 0.9.2 / V0
Qwen3ForCausalLM / Qwen3-32B
BF16 / hidden_size 5120
TP=1 / PP=1 / max_num_seqs=1
prompt_embeds enabled / eager mode
soft_token_topk_v1 alignment
loopback-only authenticated middleware
```

Fresh readiness：`evidence/runtime/vllm_readiness.json`。结果为 `status=ready`、`worker_extension_ready=true`、`prompt_embeds_enabled=true`，compatibility digest 为 `572d13d5be7a1e3e05fd15c10f0d8090f49a98af9b36fcba230aef65eba32316`。

### 5.2 2/4/8-step probe

Artifacts：

- `evidence/phase4/mechanism_steps2.json`
- `evidence/phase4/mechanism_steps4_8.json`

| steps | capture | recurrence | tensor | bytes | consumer proof | one-shot | release |
| ---: | ---: | ---: | --- | ---: | --- | --- | --- |
| 2 | 2 | 1 | `[2,5120]` BF16 | 20,480 | worker-forward true | second consume 409 | released |
| 4 | 4 | 3 | `[4,5120]` BF16 | 40,960 | worker-forward true | second consume 409 | released |
| 8 | 8 | 7 | `[8,5120]` BF16 | 81,920 | worker-forward true | second consume 409 | released |

每个 producer response 只含 opaque ref、shape/dtype/digest 和安全 telemetry，不含 tensor、base64、prompt embeddings 或 producer internal text。Consumer proof 的 ref ID、request ID、shape、dtype 和 input-embedding digest 均与 worker-forward receipt 绑定；只有 successful forward 返回后才提交 consumed event。

### 5.3 真实负向矩阵

Artifact：`evidence/phase4/negative_probe.json`。

真实 HTTP negative probe 的 9/9 cases 全部得到预期稳定错误：wrong model、wrong compatibility digest、wrong alignment、missing marker、duplicate marker、unknown ref、invalid bearer token、wrong anchor 和 TTL expired。拒绝发生在 capture、registry lookup/lease 或 materialize 之前；结束时 registry entries/bytes 均为 0。

不适合通过线上破坏服务验证的 incomplete capture、capacity、concurrent capture、forward binding、mode off、loopback 和 fallback 由 injected/fake tests 覆盖。Phase 6 的 N1 另外给出 6/6 真实 signature mismatch pre-forward rejection。

### 5.4 vLLM 0.9.2 兼容偏差

实现过程中保留并修复了三个真实兼容偏差：

1. 默认 frontend multiprocessing 使用的 `MQLLMEngineClient` 没有所需 collective RPC，因此启动合同增加 `--disable-frontend-multiprocessing`，固定 direct V0 engine。
2. vLLM 0.9.2 public async collective RPC 的 nested path 抛 `NotImplementedError`；middleware 只对该明确异常使用同一 V0 wrapper 内的同步 RPC，其余异常 fail closed。
3. `inputs_embeds` 可在 model forward 后被原地改写；worker 改为 forward 入口快照 binding digest，forward 成功返回后才提交 proof。Mismatch 会 invalidate ref，不再穿透并杀死 engine。

这些修复均有回归；冻结技术文档本身未被改写来掩盖 site-packages 偏差。

## 6. Adaptive Runtime integration

`LatentHandoffController` 和 adaptive dispatcher 现执行以下边界：

1. Planner 只能提出 bounded `handoff_intent`；
2. Runtime 在 retrieval 后独立检查 mode、长叙事语义、coverage、signature、anchor 和 backend health；
3. mode 默认 `off`，普通路径不调用 latent backend；
4. 只有真实 producer commit 才保存 active opaque ref；
5. Summarizer completion 必须带同 ref 的 worker-forward proof；
6. 输出仍进入 `ClaimSetValidator`，validator failure 不能计 latent success；
7. 任一 gate/produce/forward/validator failure 只执行一次 C0/text fallback；
8. active ref 在 success、fallback 或 Runtime failure 后只 release 一次；
9. tensor、token、raw prompt、raw completion 不进入 Protobuf、MemoryIndex、manifest 或 telemetry。

需要特别区分：Track R 的 strict field-level support 是 Claim v2 路径；Phase 6 为兼容 guided decoding 使用 `statebus.claim_set.v1`，其 validator 证明 task/session、evidence ID、locator 和 artifact reference 结构有效，不能证明 claim text 与 evidence 语义一致。后者由冻结的 post-generation required-fact scorer单独判定，这正是 L1 结构校验通过但事实得分为 0 的原因。不得把 `validator_ok=true` 当成质量通过。

## 7. Phase 6 preregistered experiment

### 7.1 设计

Manifest：`v2/benchmark/samples/latent_narrative_holdout_v1/manifest.json`

Manifest SHA256：`d53c26351732620f3aee6198efc1f6b03147d633a733db8edcf47ce526515c4e`

固定设计：6 个离线长叙事 case、24 个 required facts、5 lanes、30 个串行 samples、temperature 0、seed 7、同一 Qwen3-32B、memory off、CodeAct off、8 latent steps。Expected facts 只在生成后进入评分器，未暴露给生成请求。每个 case 使用冻结随机顺序及其 paired reverse 设计。

| Lane | 输入边界 |
| --- | --- |
| C0 | full selected evidence |
| T0 | 128-token Retriever text handoff |
| A0 | anchors + verified artifact，无 analysis/latent |
| L1 | anchors + artifact + engine-local latent |
| N1 | compatibility signature 破坏，forward 前拒绝，随后一次 C0 fallback |

主结果：`phase6/native_latent_experiment.json`，SHA256 `7c8af68ab6fbd16236a281d8319485c4f1ff1f32901de8c80a49690bf050f7ad`。`phase6/checksums.sha256` 对 summary、plan、progress 和 30 个 raw sample 全部校验通过。

### 7.2 Mechanism result

L1 mechanism 为 6/6：每例 capture `8/8`、recurrence `7`、`[8,5120]` BF16、81,920 bytes、真实 worker-forward、release；总 latent tensor bytes 为 491,520。所有 L1 worker PID 均为 `541934`。

N1 为 6/6 pre-forward rejection：producer 可完成并 commit，但破坏后的 signature 在 consumer forward 前得到 `latent_model_incompatible`；`latent_consumed=false`、无 forward event、release true，随后只运行一次 C0 fallback。N1 最终输出成功不计 latent success。

### 7.3 Quality result

| Lane | valid samples | facts passed | latent success | fallback | 预注册判定 |
| --- | ---: | ---: | ---: | ---: | --- |
| C0 | 6/6 | 17/24 | 0 | 0 | 未达到 22/24 solvability gate |
| T0 | 5/6 | 9/24 | 0 | 0 | 一例 `retriever_text_handoff_invalid` |
| A0 | 6/6 | 0/24 | 0 | 0 | 无有效质量 |
| L1 | 6/6 | 0/24 | 6 | 0 | mechanism 成立，quality floor 失败 |
| N1 | 6/6 | 16/24 | 0 | 6 | rejection/fallback 成立，不计 latent success |

Summary 中：

```text
c0_task_solvable=false
l1_mechanism_all_cases=true
n1_pre_forward_rejection_all_cases=true
l1_quality_floor=false
quality_matrix_passed=false
interpretation=task_design_failed_c0_not_solvable
```

因此不能比较或宣称 L1 quality gain。L1 与 A0 都为 0/24 也表明当前 prompt/workload 没有展示可用的 latent 信息收益。

### 7.4 Performance result

以下仅是本次串行样本的描述性数字，不是 superiority claim：

| Lane | median ms | P90 ms | P95 ms |
| --- | ---: | ---: | ---: |
| C0 | 32,789.190 | 62,880.335 | 64,169.295 |
| T0 | 36,302.457 | 71,523.889 | 72,040.234 |
| A0 | 31,439.027 | 54,066.385 | 54,357.740 |
| L1 | 48,823.649 | 75,542.346 | 76,705.579 |
| N1 | 34,989.809 | 64,211.129 | 64,550.251 |

T0 的失败样本记录 `elapsed_ms=0`，所以该 lane 的 latency distribution 不能用于正式比较。各 lane 的质量也不相等，性能 gate 已先失败。

L1 组件中位数：producer prefill `1.365 ms`、7-step latent rollout `1,215.009 ms`、registry commit `11.860 ms`、registry load `49.698 ms`、consumer model `47,712.748 ms`。每例 latent tensor 为 81,920 bytes；6 例 consumer combined prompt-embed bytes 合计 58,839,040。Artifact 中 `d2h_ms`/`h2d_ms` 均记录为 0，但当前实现没有独立验证 transfer timing，因此这些 0 不作为“无传输成本”声明，性能分解仍不完整。

## 8. Container regressions

全部命令在 `statebus-dev-qcrs` openEuler 容器中串行执行，latent mode 在普通回归中显式为 `off`：

| 范围 | 结果 | 日志 |
| --- | --- | --- |
| latent targeted | `112 passed in 4.38s` | `tests/latent_targeted.log` |
| complete `tests/v2` | `671 passed in 1148.33s` | `tests/v2_full.log` |
| repository full | `973 passed, 1 warning in 2049.62s` | `tests/repo_full.log` |

三个 exit-code 文件均为 0。仓库全量唯一 warning：

```text
LangChainPendingDeprecationWarning:
the default value of allowed_objects will change in a future version
```

这是 installed LangGraph 的 upstream pending-deprecation，不是 StateBus contract warning。`protocol/statebus_pb2.py` 的 legacy protobuf exemption 仍为 exact import-scoped filter，没有全局 ignore-all。

容器镜像：`statebus-dev-openeuler:24.03-lts-sp3-embed`

Image ID：`sha256:715ded05373ca023f3acf33d180b8db2e0c4f2b1361b6c2a31c58c33c1fb6647`

CodeAct/bwrap 仍是 contest validation profile，不声明 production-grade sandbox。

## 9. Current service and restart record

初始 ordinary vLLM PID `997073` 没有 plugin。用户明确批准重启该 PID；第一次 plugin launch 暴露 frontend collective-RPC 偏差。用户随后明确批准重启 PID `2201759`；后续用户给出继续执行授权，并最终明确要求使用卡 1 启动。每次只处理 StateBus service process group，没有终止其他用户进程，也没有使用旧 PID 授权静默扩张到不相关进程。

当前服务：

| 字段 | 值 |
| --- | --- |
| tmux | `statebus-vllm-latent` |
| PID / PGID | `541934` / `541932` |
| GPU | physical index `1` |
| GPU UUID | `GPU-a53fa601-8471-d782-2971-46e5a8e5d328` |
| port | `127.0.0.1:53334` |
| log | `/home/qcrs/statebus/logs/vllm_latent_20260721_203226.log` |
| ordinary health/models | HTTP 200 / HTTP 200 |
| latent readiness | ready |
| token file | `/home/qcrs/statebus/work/latent_api.token`, mode 0600；值未记录 |

非敏感命令：

```text
/home/qcrs/statebus/conda-envs/vllm-qwen-cu121/bin/python /home/qcrs/statebus/conda-envs/vllm-qwen-cu121/bin/vllm serve /data/models/Qwen3-32B --host 127.0.0.1 --port 53334 --served-model-name qwen3-32b --dtype bfloat16 --tensor-parallel-size 1 --max-model-len 8192 --max-num-seqs 1 --max-num-batched-tokens 8192 --gpu-memory-utilization 0.82 --enable-prefix-caching --enable-prompt-embeds --enforce-eager --disable-frontend-multiprocessing --worker-extension-cls v2.integrations.vllm_latent.worker_extension.LatentWorkerExtension --middleware v2.integrations.vllm_latent.middleware.LatentHandoffMiddleware
```

Host vLLM environment：Python `3.11.15`、vLLM `0.9.2`、torch `2.7.0+cu126`、transformers `4.52.4`。容器 test/experiment runner 是 Python `3.11.6`、torch `2.5.1+cu121`、transformers `4.51.3`；真正执行模型的版本以前者为准。

Model revision 参数和 vLLM reported revision 均为 `None`。本地模型使用以下 identity hashes：config `97e295b6...83bb`、tokenizer config `d5d09f07...8101`、tokenizer `aeb13307...ae4`、weight index `bed42c6c...ecd0`。完整值保存在 `evidence/runtime/runtime_snapshot.json`。

## 10. Freeze, manifest, and worktree

最终 runtime freeze：

- snapshot：`docs/improvement/27_statebus_v2_remediation_and_native_latent_execution_20260721/final_runtime_freeze_snapshot.json`
- per-file ledger：`final_runtime_freeze_files.sha256`
- 63 files；
- runtime freeze SHA：`0a1297789630e4b2a965008930597f1f0ce5f88b3fd906e42f212ab75bc584a9`；
- ledger SHA：`3086c04ca912aa8b11148bd495a9c4e76fbd068afd30c71f3fff07d4ea1fc2df`；
- active audit changed/added/removed 均为空。

工作树从执行前就是 dirty。HEAD 保持 `bda17745...`，没有 reset、checkout、删除未知文件、覆盖 E0-E6、创建 commit 或 push。由于修改跨越大量执行前已 dirty 的文件，本次不创建混合所有权提交；`local commits: none`，`remote pushes: none`。

最终 machine-readable 文件：

- `manifests/final_manifest.json`
- `manifests/completion_audit.json`
- `manifests/checksums.sha256`

## 11. StateBus aligned latent 与 LatentMAS

| 维度 | StateBus 当前实现 | LatentMAS 论文工作内存 |
| --- | --- | --- |
| 传递对象 | 最末 hidden 经 `soft_token_topk_v1` 对齐后的短 embedding sequence | layer-wise KV working memory |
| shape | `[latent_steps, hidden_size]`，当前最多验证 8 x 5120 | 多层 attention KV，语义和体量均不同 |
| 生命周期 | engine-local opaque Ref、TTL/capacity/one-shot/release | 论文机制，不等于 StateBus Ref 治理 |
| 安全与审计 | signature、anchor、auth、worker-forward proof、fallback、telemetry | 不直接提供 StateBus 这些治理合同 |
| 声明 | bounded experimental mechanism | 论文结果不能继承到本实现 |

本实现不是 LatentMAS 复现，不包含 layer-wise KV handoff，不继承 lossless、速度、token 降幅或准确率数字，也没有复制论文的 vLLM fork。

## 12. 可声明、不可声明与 Future Work

可以声明：

- Track R F-01 到 F-12 的 correctness/security/accounting/protocol hardening 已通过当前 openEuler container suite；
- Qwen3-32B/vLLM 0.9.2/V0 的 bounded aligned latent producer-consumer mechanism 真实成立；
- 2/4/8-step 和正式 6-case L1 均有 worker-forward proof；
- N1 signature mismatch 6/6 在 forward 前拒绝，fallback 不计 latent success；
- 正式 30-sample experiment 已完成并保存全部 raw artifacts/checksums。

不可声明：

- latent quality gain、latency gain、token saving 或 lossless transfer；
- typed carrier 或 StateBus end-to-end latency superiority；
- C0 未过可解门时的 L1/A0/T0 优劣；
- natural memory 已真实跳过 LLM；
- production-grade sandbox、semantic-worker isolation 或 multi-tenant auth；
- LatentMAS 复现或 layer-wise KV transfer。

Future Work 按当前负结果排序：

1. 先修订 holdout/prompt，使冻结后的 C0 稳定达到 solvability threshold，再讨论 latent 对比；
2. 正式实验改用 Claim v2 strict field support，并保留独立 semantic fact scorer；
3. 补真实 D2H/H2D 计时、producer/consumer token throughput 和多重复 paired latency；
4. 用真实 backend 再跑一次完整 AdaptiveMainlineRunner，而不仅是 dedicated experiment harness；
5. 扩展到其他 vLLM 版本、V1、TP/PP 大于 1 前，重新做 compatibility matrix；
6. 生产部署前增加独立 Unix identity/sandbox、secret rotation 和容量运维策略。

当前没有代码或环境 blocker；阻止收益声明的是预注册质量门失败，而不是测试或机制失败。

# Deep Contest Audit 16

审计日期：2026-07-06
审计范围：StateBus v2 clean-room branch `feat/statebus-v2-container-runtime`
起点提交：`be74494 Harden external fairness gate raw payload checks`

## Executive Summary

当前 StateBus v2 已经能支撑一个保守但真实的比赛叙事：`UDS + typed Protobuf` 控制面、结构化角色 handoff、`SemanticStateRef` 非文本状态承载、workspace artifact 与 CAS/mmap/shared-memory 分层、continuous replay/downgraded reuse、以及带 external pure-text fairness gate 的 dev compare。

不能支撑的叙事也必须明确降级：formal financial primary 不是 broad reasoning superiority；compare 不是端到端速度胜利；memfd 不是正式 benchmark 主路径；`validated_replay` 不能说成 generic safe answer restoration，应称为 validated downgraded reuse / strategy-backed reuse。

本轮修复了两个 P1 风险：

- full audit 脚本的 socket path 纳入 run id，并新增 `key_metrics` JSON 解析。
- replay 指标增加保守机器可读别名：`validated_downgraded_reuse_count` 和 `answer_restoration_replay_count`。

Artifacts:

- `docs/improvement/artifacts/16_deep_contest_audit/worklog.md`
- `docs/improvement/artifacts/16_deep_contest_audit/command_log.md`
- `docs/improvement/artifacts/16_deep_contest_audit/evidence_log.md`
- `docs/improvement/artifacts/16_deep_contest_audit/issue_ledger.md`
- `docs/improvement/artifacts/16_deep_contest_audit/final_summary.md`

## Claim Grading

| Claim | Grade | Evidence | Boundary |
| --- | --- | --- | --- |
| typed control plane and structured role handoff exist | Strong | `v2/control/transport.py:260`, `v2/control/transport.py:306`, `tests/v2/test_control_plane.py:95` | memfd transport is not benchmark-mainline evidence. |
| `SemanticStateRef` and `ExecutionArtifactRef` are separated | Strong | `v2/refs/models.py:50`, `v2/refs/models.py:77`, `v2/refs/models.py:93` | StateRef should not be collapsed with execution artifacts. |
| non-text semantic state transfer reduces prompt exposure in stress families | Medium/Strong | flagship stress JSON: 6 families, 4 pass, 8409 visible bytes saved | Two stress families did not pass; do not overgeneralize. |
| formal financial structured mode passes quality floor | Strong | `07_formal_primary/stdout.json`: 8/8 quality floor pass | `L3_reuse_gain=0`; not replay superiority. |
| continuous replay/reuse is observed over multiple families | Strong | `10_continuous_replay_collection_primary/stdout.json`: 3 family, 30 round, 20/20 replay targets observed | Validated replay is downgraded reuse, not exact answer replay. |
| external pure-text fairness gate passes latest raw-payload audit | Strong for dev fixed-answer | `codex-raw-fairness-20260706-cold-start-compare-api.json`: hard gate true, 0 failures | Scope is dev fixed-answer only. |
| StateBus is faster end-to-end than external text baseline | Unsupported | latest compare has `api_task_ms_delta=9906.00388` | May discuss prompt/token/control reductions only. |
| openEuler compatibility is validated | Unsupported | no VM-stage validation in this audit | Must remain planned/final delivery validation. |

## 1. 赛题对齐

赛题核心不是“把文本变短”本身，而是多智能体之间如何传递、复用和校验中间状态：至少 3 Agent、结构化通信、记忆检索复用、上下文压缩、双模式对比、连续任务稳定性和 openEuler 交付。

当前 v2 与赛题对齐的强点：

- 四角色路径使用 `Planner / Retriever / Executor / Summarizer`，role metrics 在 external compare hard gate 中要求全部存在。
- v2 formal 控制面是 `UDS + typed Protobuf`，不是 MessagePack 主合同。
- `SemanticStateRef`、`ExecutionArtifactRef`、memory commit、hydrate manifest、workspace artifact 的类型边界清晰。
- continuous replay collection 已覆盖 3 个 family、30 round、20 个 replay target。

主要降级点：

- formal primary 是金融表格 precision anchor，不能扩展成所有复杂推理场景胜利。
- 旧文档中涉及 formal superiority、速度胜利、memfd 主路径、openEuler 已验证的语句必须视为过时或 unsupported。
- prompt 裁剪和文本摘要不能单独包装成 StateBus 创新；必须绑定 typed refs、hydration、provenance、replay gate 和 benchmark JSON。

## 2. 结构化与非文本状态

`SemanticStateRef` 是一等 ref 类型，字段包含 `state_kind`、`storage_kind`、`blob_hash`、`source_doc_hashes` 等；`ExecutionArtifactRef` 独立表示 execution output，并在 registry entry 中使用 `StorageKind.WORKSPACE_ROOT`。这两者没有被合并为 vague ref。

数据面实际路径：

- `LayeredStoragePolicy` 对 `EMBEDDING_STATE` / `DENSE_SEMANTIC_STATE` 首选 `SHARED_MEMORY`，fallback 到 `MMAP_FILE`。
- `LayeredStateStore.publish()` 会 materialize bytes，并分别走 shared memory、mmap file 或 inline。
- workspace artifact 是 execution output 主路径。
- CAS sidecar 用于 memory match/result、memory commit、hydrate manifest 和 evidence pack 类对象。
- memfd + subprocess transport 存在编码、传 fd 和 e2e test，但 formal/compare benchmark 主路径没有把它作为 headline 证据。

Benchmark 证据上，`15_flagship_ablation_primary` 的 non-text stress summary 显示 6 个 family 中 4 个 stress pass，总 LLM prompt saving 22208 bytes，总 prompt-visible saving 8409 bytes。这个 claim 是中强证据，但必须保留 family 差异。

## 3. Memory / Replay / Reuse

当前 memory/replay 不是简单 cache hit。代码里 exact replay 与 validated replay 分离；validated path 的 contract compatibility 允许同 task family / intent / tools / outputs / argument shape 下的复用，测试明确允许不同 ticker 的同 shape validated replay。

因此：

- `exact_replay_count` 可以说 answer restoration / exact replay。
- `validated_replay_count` 应对外解释为 validated downgraded reuse / strategy-backed reuse。
- 本轮新增 `validated_downgraded_reuse_count` 和 `answer_restoration_replay_count`，让 summary JSON 可机器审计 claim scope。

Replay evidence:

- `family_count=3`
- `continuous_round_count=30`
- `replay_target_round_count=20`
- `replay_observed_round_count=20`
- `replay_missing_target_round_count=0`
- `validated_replay_count=17`
- `exact_replay_count=3`
- `L3_artifact_reuse_count=39`
- `L3_reuse_gain=20`

污染风险审计：

- external baseline 最新修复后不再用 gold revenue fallback。
- replay negative audit 仍是必要 gate；不能只看 positive replay count。
- persisted history 有 runtime signature、artifact hash、output contract 等 gate，但 schema drift / task family 扩展时仍需要负控继续覆盖。

## 4. 四角色真实性与 Fairness Gate

四角色并不是完全独立的多进程智能体，但它们不是纯展示字段：role path 有独立 prompt/call metrics，external hard gate 要求 planner/retriever/executor/summarizer role metrics 全部出现。

公平性最新状态：

- raw role JSON 与 raw choices 已纳入 `_fairness_gate()`，不能靠 normalization 把不可见 route/tool 选择救回来。
- `observed_revenue_value = llm_revenue_value`，外部 pure-text baseline 不再 fallback corpus/gold value。
- comparator hard gate 要求 external fairness coverage、0 failed case、0 failed check。

最新 raw fairness artifact 通过 hard gate，但 claim scope 是 `dev_fixed_answer_only`，不能迁移成 formal financial superiority。

## 5. Benchmark 与任务集

Formal financial:

- 证明结构化协议、语义状态和 quality floor 稳定性。
- 不能证明 replay gain；当前 `L3_reuse_gain=0`。

Fixed-answer external compare:

- 证明 external pure-text baseline 在公平 gate 下可比，StateBus 降低 token/prompt/control exposure。
- 不能证明 formal superiority 或 latency victory。

Continuous families:

- `cross_period_financial_v1`：跨期经营指标/财务表复用。
- `csv_correlation_replay_v1`：CSV 相关性/表格分析中的 replay/downgraded reuse。
- `long_doc_metric_replay_v1`：长文档 metric replay，含 exact replay。
- `incident_diagnosis_v2`：连续诊断/状态迁移，但不是金融正式默认族。
- `gridops_world`：更像系统/运营 demo，不应替代 formal financial 证据。

下一步应新增更难的 offline financial-report / operating-metric formal family，并加入负控任务，验证 baseline 没被人为削弱。

## 6. 实验数据可信度

最新完整 evidence bundle：

- `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/summary.latest.json`
- `stage_count=16`
- `failed_stage_count=0`

最新 fairness rerun：

- `/home/qcrs/statebus/runs/codex-raw-fairness-20260706/runtime/benchmark_reports/codex-raw-fairness-20260706-cold-start-compare-api.json`
- hard gate pass，0 fairness failure。

可信度边界：

- API + local 是最强线上证据。
- deterministic + local / deterministic + deterministic 适合作 regression 和 fallback，不适合作 API 效果 headline。
- latency claim 必须用串行 API rerun；不能把并发 launch 或 full audit stage wall clock 当正式速度证据。
- 本轮更新 full audit script，使后续 `summary.json` 自动记录 `key_metrics`，降低只看 stage success 的风险。

## 7. 严重问题与修复

P0：未发现。

P1 已修：

- AUDIT-001：full audit socket collision 风险。
- AUDIT-002：full audit summary 缺关键 JSON 指标。
- REPLAY-001：validated replay 机器可读口径不够保守。

P2 保留：

- formal family narrow。
- memfd 未进入正式 benchmark 主路径。
- full audit fallback matrix 仍有限。
- 旧 docs/reports 中有过时 claim。
- latency 不能 headline。

详情见 `docs/improvement/artifacts/16_deep_contest_audit/issue_ledger.md`。

## Updated Full Audit Script

复用脚本仍是：

`scripts/run_v2_full_container_audit_suite.sh`

本轮没有新增平行脚本，原因是已有 full suite 已包含 env probe、pytest、runtime smoke、preflight、formal、compare、replay negative、continuous replay collection 和 optional flagship。直接增强它比新增一个口径不同的 deep audit script 更稳。

新增能力：

- 每个 stage 的 socket path hash 加入 `STATEBUS_RUN_ID`。
- `summary.json` 新增 `key_metrics`。
- `summary.md` 新增 `## Key Metrics`。
- 解析 formal、compare、external fairness、replay collection、单族 replay、negative replay、flagship stress 指标。

## Old Document Status

| 文档 | 状态 | 说明 |
| --- | --- | --- |
| `docs/improvement/14_full_validation_rollup_20260706.md` | 当前事实源 | full audit rollup 仍有效。 |
| `docs/improvement/15_fairness_gate_propagation_audit_20260706.md` | 当前事实源 | raw fairness 修复链路有效。 |
| `docs/improvement/11_competition_readiness_audit.md` | 部分过时 | P0-A revenue fallback、P0-C table concern 已过时；validated replay wording 风险仍成立。 |
| `docs/improvement/05_memory_and_replay_complete_design.md` | 部分过时 | `lookup_by_tags` 和 FAISS 未实装结论已过时。 |
| `docs/reports/final_v2_evidence_index_20260703.md` | historical | formal superiority、speed、memfd 主路径相关 claim 需降级。 |
| `docs/reports/v2_experiment_summary_20260703.md` | historical | 旧指标不能覆盖最新 fairness hard gate。 |

## Final Claim Language

建议答辩表述：

StateBus v2 demonstrates a typed state bus for multi-agent workflows: structured Protobuf control messages over UDS, first-class semantic state references and execution artifacts, deterministic hydration/provenance, and replay-aware memory reuse. In the current evidence, formal financial tasks validate quality and structured/non-text state transfer, while continuous task families demonstrate exact replay and validated downgraded reuse. External pure-text comparison is fairness-gated and shows prompt/token/control exposure reductions on dev fixed-answer tasks, but not end-to-end latency superiority.

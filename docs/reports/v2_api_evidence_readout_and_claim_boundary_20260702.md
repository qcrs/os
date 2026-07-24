# StateBus v2 API Evidence Readout And Claim Boundary

日期：`2026-07-02`

范围：`/home/qcrs/statebus/project`

本文档只服务于一件事：

- 冻结 `2026-07-02` 这轮 `v2` API evidence 的正式读法；
- 明确当前哪些 claim 已经有 artifact 支撑；
- 明确哪些结论仍然不能上读；
- 给后续汇报、答辩、实验说明一个统一入口。

如果旧的 compare 讨论、局部优化叙事或未冻结口头判断与本文冲突，以本文为准。

---

## 1. Source Of Truth

本轮 API 证据的主 artifacts：

- API 日志根目录：
  - host 路径：`/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352`
  - container 路径：`/statebus/runs/v2-api-evidence-20260702_145352`
- formal suite：
  - `v2-live/runtime/benchmark_reports/statebus-v2-benchmark-formal-suite.json`
- internal carrier compare：
  - `v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-carrier-compare.json`
- external compare debug：
  - `v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-compare.json`
- non-text flagship ablation：
  - `v2-live/runtime/flagship-ablation/benchmark_reports/statebus-v2-benchmark-non-text-flagship-ablation.json`
- replay negative audit：
  - `v2-live/runtime/replay-negative-audit/benchmark_reports/statebus-v2-benchmark-replay-negative-audit.json`

本轮基础门：

- `pytest-v2`: `152 passed in 358.04s`
- `preflight-api`: `ok=true`
- `role_path_mode`: `api`
- `embedding_mode`: `local`
- `embedding_device`: `cuda:0`
- `torch_cuda_available`: `true`
- `torch_version`: `2.5.1+cu121`
- `sentence_transformers`: present
- `CodeAct`: controlled CodeAct-style execution；formal / carrier artifacts 中 `codeact_sandbox_bwrap_count > 0` 且 `codeact_sandbox_fallback_count = 0`

本轮主读法所对应的日志文件：

- `formal-api.log`
- `carrier-compare-api.log`
- `external-compare-api-debug.log`
- `replay-negative-audit.log`
- `flagship-ablation-api.log`

---

## 2. Bottom Line

当前最强的正式证据链已经不是 external compare，而是：

1. `formal suite`
2. `non-text flagship ablation`
3. `continuous / continuous-replay` families

这轮结果支持以下判断：

- `v2` 四角色主链已经在 `api` 模式下完成 formal-first-pass 复验；
- `GPU local embedding` 已用真实 `sentence_transformers + torch cu121 + cuda:0` 路径复验，不再只是 deterministic embedding 模拟；
- controlled CodeAct-style execution 已在 root+bwrap openEuler Docker profile 下进入真实 bwrap 后端，无 fallback；当前执行脚本是 runtime-generated bounded Python action script，不是开放式 LLM 任意生成 Python；
- `L1` 的收益主要是结构化 carrier 减少 prompt scaffolding；
- `L2` 的收益主要是 semantic selection / non-text state 让 LLM 看到的原始证据和 prompt-visible bytes 显著下降；
- `L3` 的收益只在 replay / history 真命中时成立，不能把所有 L3 都上读成自动加速；
- external pure-text comparator 仍未过 fairness gate，因此仍然只能作为 debug evidence。

因此，当前不是“方法骨架失败”，而是“收益边界已经被拆清楚”。

---

## 3. 现在可以诚实 Claim 什么

| 轴 | 当前状态 | 当前最诚实读法 |
| --- | --- | --- |
| 多 Agent 角色 | `established` | `Planner -> Retriever -> Executor -> Summarizer` 四角色主链已在 `api` 模式跑通 |
| 双模式协作 | `established` | 同一 StateBus runtime 下同时支持 `pure text` 与 `structured` 协作模式 |
| 结构化通信 | `established` | `L1` 在相同主链下减少 control / scaffolding，且不降低 fixed-answer 质量底线 |
| 非文本状态传递 | `established` | `L2` 在长任务 family 中显著降低 `raw_evidence_bytes_seen_by_llm` 与 `prompt_visible_total_bytes` |
| 共享记忆 / replay | `partially established` | 仅在 replay/headline-eligible family 中可以正式讲 `exact/validated replay` 与 `skipped_step_count` |
| 连续任务 | `established` | 至少 2 组以上 10 轮连续任务已有 artifact 证明 |
| CodeAct 支撑 | `established_as_controlled_runtime_capability_with_profile_boundary` | formal 与 continuous artifacts 中存在真实 `codeact_plan_*`、`codeact_execution_stage_ms`；执行对象是 runtime-generated bounded Python action script；root+bwrap profile 下有 bwrap sandbox evidence |

可以正式说：

- `formal suite` 在 `role_path_mode=api` 下通过，且 `quality_floor_pass_count=3` 在 `L0-L3` 均保持不变。
- 同一 StateBus runtime 内部，structured carrier 相比 internal pure-text carrier 确实减少了 prompt scaffolding。
- 在长文档 / 表格 / 连续任务 family 中，`L2` semantic pruning / semantic state 带来真实的 evidence-byte 降低。
- 两组 replay family 都已经在 GPU/local/API 路径下达到 `replay_admissible`；CSV 负责 validated replay 全覆盖，long-doc 负责 exact + validated 混合 replay。
- CodeAct 只能写成 controlled CodeAct-style execution，不能写成 LLM generated arbitrary Python code、general-purpose CodeAct benchmark superiority 或 production-grade sandbox。

---

## 4. 现在仍不能 Claim 什么

| 不能 claim 的内容 | 原因 |
| --- | --- |
| formal external pure-text superiority | external compare 仍然 `fairness_gate_failed` |
| fair external comparator 已完成 | 外部四角色 lane 还没有通过 fairness hard gate |
| KV cache / hidden-state handoff 已实现 | 当前实现的是 typed state / semantic state / artifact replay，不是模型内部隐藏态传递 |
| 低开销优化已经收口 | persistence overhead 仍然是明确成本桶，不能说优化完成 |
| persist_and_reload 已不再是主要瓶颈 | 当前仍不能这样说 |
| openEuler VM 最终交付验证已完成 | openEuler Docker 容器已跑通；若交付按 VM 口径验收，仍需目标 VM 上最终编译、运行、测试验证 |

外部 compare 当前只能读成：

- debug 侧 StateBus 这轮看起来更强；
- 但 fairness gate 没过；
- 所以不能升级成正式 superiority narrative。

---

## 4.1 Replay 分类边界

当前 `L3` / memory 结果必须按 replay class 分开读：

| Class | 可 claim 内容 | 不可 claim 内容 |
| --- | --- | --- |
| `assist` | 历史记忆作为候选或摘要参与当前任务 | 跳过步骤、`reuse_gain`、exact replay |
| `validated_replay` | 跳过部分步骤，但仍需要输出合同、任务形状和验证状态通过 | exact key 完全匹配、成熟审计级 replay |
| `exact_replay` | runtime signature、input hashes、output contract、task shape 与 exact key 全匹配时跳过步骤 | 泛化到未匹配 family 或未审计历史 |

`csv_correlation_replay_v1` 当前只能作为 validated-only replay 证据：

- `exact_replay_count = 0`
- `validated_replay_count = 8`
- `skipped_step_count = 8`

`long_doc_metric_replay_v1` 当前只能写成 mixed exact + validated replay：

- `exact_replay_count = 3`
- `validated_replay_count = 5`
- `skipped_step_count = 11`

2026-07-03 后续 P0-006 remediation 增加了一个 persisted-history unit regression：

- `tests/v2/test_replay.py::test_persisted_history_replay_ignores_corrupted_output_artifact`
- 该测试构造 tmp-path persisted memory commit、artifact manifest/ref、replay ledger、runtime session 和 output file。
- 它证明 corrupted output artifact hash 不会被加载成 history replay candidate。
- 这仍不是 12-case persisted-live-history audit，不能升级成 mature audit-grade replay claim。

---

## 5. Formal Suite 读法

formal suite 元数据已经把 claim 边界写得很清楚：

- `comparison_contract = same_mainline_internal_attribution_ladder`
- `ladder_claim_scope = internal_attribution_only_not_external_superiority`
- `role_path_mode = api`
- `task_family_tier = formal_financial`

formal suite 当前可直接引用的关键信号：

- `family_case_count = 3`
- `quality_floor_pass_count = 3` at `L0-L3`
- `control_bytes_delta_l0_to_l1 = 373`
- `pruning_bytes_saved_vs_l0 = 3543`
- `L0_raw_evidence_bytes_seen_by_llm = 5740`
- `L2_semantic_state_transfer_count = 3`
- `L2_shared_memory_publish_count = 3`
- `L3_quality_floor_pass_count = 3`
- controlled CodeAct-style `bwrap` count = `3` at each layer, fallback count `0`

formal suite 当前支持的不是 external superiority，而是内部 attribution ladder：

- `L1` 说明 structured carrier 带来的 control/scaffolding 变化；
- `L2` 说明 semantic pruning / semantic state 带来的 evidence reduction；
- `L3` 在本 formal family 里没有 seeded replay memory，因此 `artifact_reuse` 和 `reuse_gain` 不是 headline。

---

## 6. Internal Carrier Compare 读法

internal carrier compare 当前是有效的，`comparison_valid = true`。

关键指标：

- `control_bytes_delta = -220`
- `llm_prompt_bytes_delta = -1922`
- `llm_total_tokens_delta = -250`
- `prompt_scaffolding_bytes_total_delta = -1922`
- `prompt_visible_total_bytes_delta = 0`
- `raw_evidence_bytes_seen_by_llm_delta = 0`

这说明：

1. structured carrier 的直接收益是减少 prompt scaffolding / control packaging；
2. 它本身并不减少模型实际看到的 evidence 内容；
3. 因此 `L1` 不能被误读为“已经证明非文本状态传递本体收益”。

这一点对后续口径很重要：

- `L1` 回答“结构化 carrier 是否比 internal text handoff 更紧”；
- `L2` 才回答“非文本状态 / semantic pruning 是否减少重复证据处理”。

---

## 7. External Compare 当前如何读

external compare 当前结论很简单：

- `comparison_valid = false`
- `invalid_reason = fairness_gate_failed`
- `formal_superiority_claim_allowed = false`

这轮 debug 指标虽然看起来偏向 StateBus：

- `api_debug_statebus_exact_match_count = 3`
- `api_debug_external_exact_match_count = 2`
- `api_debug_statebus_quality_floor_pass_count = 3`
- `api_debug_external_quality_floor_pass_count = 2`
- `api_debug_llm_total_tokens_delta = -1495`
- `api_debug_prompt_bytes_delta = -8348`

但这些都不能升级成正式叙事。

当前最诚实的说法只能是：

- external pure-text lane 还没拿到 formal comparator 资格；
- 这轮结果可作为 debug diagnosis；
- 不能作为 superiority headline。

---

## 8. Flagship Ablation 读法

本轮最重要的新完成项，是 `flagship ablation` 已经在 `api` 模式下跑通，而且 baseline contracts 已经拆干净：

1. `L0_internal_pure_text_carrier`
2. `T2_text_same_semantic_selection`
3. `external_pure_text_four_role`

这意味着当前不再把“纯文本 baseline”混成一个模糊对象，而是明确拆成三种不同对照。

### 8.1 Fixed-Answer 读法

fixed-answer family 的核心数字：

| 层 | `llm_prompt_bytes` | `prompt_visible_total_bytes` | `raw_evidence_bytes_seen_by_llm` |
| --- | ---: | ---: | ---: |
| `L0` | `16119` | `6297` | `5740` |
| `L1` | `14197` | `6297` | `5740` |
| `L2` | `10649` | `2800` | `2243` |
| `L3` | `10649` | `2800` | `2243` |
| `T2` | `12619` | `2800` | `2243` |

固定判断：

- `L1` 相比 `L0` 的收益主要来自 carrier / packaging。
- `L2` 相比 `L1` 的主要收益来自 semantic selection / pruning。
- `T2` 与 `L2` 的对照说明：在 fixed-answer 小任务上，non-text transfer 相对 text-with-same-selection 的额外收益有限。

`T2` 对 `L2` 的直接对照：

- `llm_prompt_bytes = -1970`
- `prompt_visible_total_bytes = 0`
- `raw_evidence_bytes_seen_by_llm = 0`

解释：

- fixed-answer family 上，`L2` 的额外收益更多是 carrier / slice 组织差异；
- 还不足以把“非文本状态传递”本体收益放大成旗舰 headline；
- 所以 fixed-answer 更适合当 `L1/L2/T2` 机制拆分示意，不适合当长任务主 headline。

### 8.2 Continuous Families 读法

#### `csv_table_profile_v1`

关键数字：

- `L0 raw_evidence_bytes_seen_by_llm = 136328`
- `L2 raw_evidence_bytes_seen_by_llm = 37990`
- `raw_evidence_reduction_pct_vs_l1 = 72.13%`
- `L2 semantic_state_transfer_count = 10`
- `L3 artifact_reuse_count = 21`
- `L3 history_step_reduction_count = 2`

`T2` 对照说明：

- `L2 vs T2 llm_prompt_bytes = -1537`
- `L2 vs T2 raw_evidence_bytes_seen_by_llm = 0`

解释：

- 主要节省先来自 semantic selection；
- non-text transfer 额外还能压 prompt bytes，但这里不是最大头。

#### `long_doc_table_v1`

关键数字：

- `L0 raw_evidence_bytes_seen_by_llm = 94120`
- `L2 raw_evidence_bytes_seen_by_llm = 26132`
- `raw_evidence_reduction_pct_vs_l1 = 72.24%`
- `L2 semantic_state_transfer_count = 10`
- `L3 artifact_reuse_count = 20`
- `L3 history_step_reduction_count = 2`

`T2` 对照说明：

- `L2 vs T2 llm_prompt_bytes = -2153`
- `L2 vs T2 prompt_visible_total_bytes = -1029`
- `L2 vs T2 raw_evidence_bytes_seen_by_llm = 0`

这比 fixed-answer 更重要，因为它证明：

- 在长文档 / 长表格任务里，non-text state 不再只是“包一层结构化壳”；
- 它已经开始在真实 prompt-visible 面上产生额外压缩。

### 8.3 Continuous Replay Families 读法

#### `csv_correlation_replay_v1`

`20260702_145352` GPU/local artifact 已经收口，是当前第二组 replay headline family：

- `quality_floor_pass_count = 10/10`
- `headline_scope = replay_admissible`
- `replay_headline_eligible = true`

- `exact_replay_count = 0`
- `validated_replay_count = 8`
- `skipped_step_count = 8`

CSV replay 的当前合同是 validated-only：

- exact target rounds: `[]`
- validated target rounds: `[3, 4, 5, 6, 7, 8, 9, 10]`

这条 family 可以作为“第二组连续任务 validated replay 全覆盖”的正式证据；不要把它上读成 exact replay 证据。

#### `long_doc_metric_replay_v1`

`20260702_145352` GPU/local artifact 已经收口，是当前最干净的 replay headline family：

- `quality_floor_pass_count = 10/10`
- `headline_scope = replay_admissible`
- `replay_headline_eligible = true`

关键数字：

| 指标 | `L0` | `L3` |
| --- | ---: | ---: |
| `llm_total_tokens` | `42802` | `21932` |
| `raw_evidence_bytes_seen_by_llm` | `94120` | `24698` |

同时它还有：

- `exact_replay_count = 3`
- `validated_replay_count = 5`
- `skipped_step_count = 11`

long-doc replay 的当前合同为：

- exact target rounds: `[5, 7, 10]`
- validated target rounds: `[3, 4, 6, 8, 9]`

这条 family 可以作为正式 `L3 exact + validated replay` headline；CSV 则作为 validated-only 的第二 replay family。

### 8.4 Non-Text State Stress

`20260702_145352` 的 non-text stress 已经是 `4/4`：

- `stress_pass_family_count = 4`
- `total_llm_prompt_saved_by_state_ref_bytes = 13834`
- `total_prompt_visible_saved_by_state_ref_bytes = 2100`
- `top_prompt_visible_saving_family = csv_correlation_replay_v1`

这组结果的正确读法是：

- `T2` 使用相同 semantic selection，但不传 `SemanticStateRef`；
- `L2` 使用 structured semantic state / StateRef；
- 四个 continuous/replay family 都显示 L2 相比 T2 有 prompt 或 prompt-visible 侧收益；
- 这仍然不是 KV cache / hidden-state handoff，只能 claim typed semantic state / artifact ref / replay 机制。

---

## 9. 这轮结果到底说明了什么

### 9.1 为什么长任务能体现优势，fixed-answer 不够明显

因为这两类任务回答的问题不同：

- fixed-answer 任务太短，更多用于拆机制，不足以放大 state transfer 本体价值；
- long-doc / table / replay 任务才真正放大了“重复证据处理”与“历史复用”的成本结构。

所以现在最正确的叙事顺序不是：

- 先拿 fixed-answer 证明一切；

而是：

1. fixed-answer 证明 `L0/L1/L2/T2` 机制分离是干净的；
2. long tasks 证明 `L2` 在真实长任务里确实减少了 evidence 与 prompt-visible 开销；
3. replay family 证明 `L3` 在合格 family 中确实减少重复步骤。

### 9.2 纯文本 baseline 之前为什么会显得怪

因为之前容易把三种不同对象混在一起：

1. internal pure-text carrier
2. text + same semantic selection
3. external pure-text four-role

这轮 flagship ablation 最大的价值之一，就是把这三种 baseline 显式拆开了。

今后应该固定读法：

- 用 `L0` 证明 structured carrier 相对 internal text lane 的包装收益；
- 用 `T2` 证明“选择收益”和“非文本传递收益”不是同一件事；
- 用 external compare 仅在 fairness gate 通过后才讨论 superiority。

### 9.3 当前方法是不是不可行

当前证据不支持“题目本质不可行”这个判断。

更准确的判断是：

- `L1` 可行，但它不是最终 headline；
- `L2` 已经在长任务上形成比较硬的证据；
- `L3` 可行，但必须选对 family，不能泛化到所有连续任务；
- external comparator 还不够成熟，不能反向否定主链方法。

---

## 10. 当前最适合用于比赛/合同叙事的证据链

主叙事建议固定为：

1. `formal suite`
   - 证明 `api` 模式下四角色主链、L0-L3 梯度、质量底线都成立。
2. `flagship ablation`
   - 证明 `L1/L2/L3/T2` 的收益来源已被拆开，而不是“统称 StateBus 更好”。
3. `continuous + continuous-replay`
   - 证明长任务上的非文本状态传递与 replay reuse 不是骨架，而是有真实 artifact 的行为。

external compare 的当前角色应固定为：

- debug appendix
- fairness diagnosis surface
- 不是 formal headline

---

## 11. Deliverable 视角下还缺什么

如果按赛题和交付要求继续推进，当前更像“formal-first-pass 已成形”，但还没到“最终交付完全闭环”。

离最终交付仍有几类缺口：

1. external comparator 仍未 formalized
   - 不影响内部机制叙事
   - 但影响 external superiority 叙事
2. runtime overhead 还没有收口
   - persistence 仍是主要成本桶
3. openEuler 最终验证未完成
   - 这属于交付闭环，不属于机制本体
4. evidence pack 仍需做成更易读的提交材料
   - 当前 artifact 已经够强
   - 但还需要 submission-ready 摘要和索引

---

## 12. Final Claim Freeze For This Run

基于 `2026-07-02` 这轮 API evidence，当前冻结结论如下。

可以说：

- StateBus `v2` 在 `api` 模式下已完成四角色 formal-first-pass 运行。
- StateBus 支持 internal pure-text、structured carrier、semantic state、history/replay 四层可分离对照。
- `L1` 减少 control / scaffolding。
- `L2` 在长任务上显著减少 `raw_evidence_bytes_seen_by_llm` 和 `prompt_visible_total_bytes`。
- `L3` 在 replay-headline-eligible family 中带来真实 `exact/validated replay` 与 `skipped_step_count`。
- 系统已具备不少于 2 组、每组不少于 10 轮的连续任务 evidence。

不能说：

- StateBus 已 formal 优于 external pure-text multi-agent baseline。
- 当前 external comparator 已公平成熟。
- 当前系统已经实现 KV / hidden-state 跨 agent 传递。
- 当前系统的 runtime overhead 优化已经完成。
- 当前系统已经完成 openEuler 最终交付验证。

这轮最正确的总结不是“对比胜利”，而是：

> internal mechanism evidence 已经成形，L0/L1/L2/L3/T2 的边界已清晰；external superiority 仍待后续 comparator fairness 过关。

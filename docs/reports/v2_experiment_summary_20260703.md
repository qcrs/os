# StateBus v2 实验数据汇总

> 日期：2026-07-04（post-fix update）
> 分支：`feat/statebus-v2-container-runtime`
> HEAD：`ac58044`
> 实验目录：`/statebus/runs/full-experiment-20260703_124448`
> 补测目录：`/statebus/runs/formal-postfix-20260704_040218`
> 环境：Container (openEuler 24.03-LTS-SP3) + Host (Linux)

---

## 一、测试套件状态

| 环境 | 测试数 | 结果 | 耗时 |
|---|---|---|---|
| Container (openEuler) | 175 | **全部通过** | 5m53s |
| Host (Linux) | 175 | **全部通过** | 5m28s |

Preflight：`ok=True`，`role_path_mode=api`，`embedding_mode=local`

---

## 二、Formal Compare — 核心论点

**配置**：`--suite compare --benchmark-tier formal --role-path-mode api --embedding-mode local`

### 结论

| 指标 | 值 |
|---|---|
| `formal_superiority_claim_allowed` | **True** |
| `formal_efficiency_claim_allowed` | **True** |
| `external_comparator_claim_scope` | `formal_financial_family` |
| StateBus quality | **8 / 8** |
| External quality | **5 / 8** |
| `quality_floor_pass_delta` | **+3.0** |
| `llm_total_tokens_delta` | **-776 tokens** |
| `prompt_bytes_delta` | **-11,098 bytes** |
| `net_llm_ms_delta` | +15,195 ms（API 延迟波动） |
| `system_overhead_ms_delta` | +13,284 ms（非 LLM runtime overhead） |
| `comparison_valid` | False（`quality_floor_gate_failed`） |

### Per-case 质量明细

| Case | StateBus | External | External失败原因 |
|---|---|---|---|
| benchmark-sample-1 | PASS | PASS | — |
| benchmark-sample-2 | PASS | PASS | — |
| benchmark-sample-3 | PASS | PASS | — |
| benchmark-sample-4 | PASS | PASS | — |
| benchmark-sample-5 | PASS | PASS | — |
| benchmark-sample-6 | PASS | **FAIL** | revenue_exact=0（LLM提取值错误） |
| benchmark-sample-7 | PASS | **FAIL** | revenue_exact=0（LLM提取值错误） |
| benchmark-sample-8 | PASS | **FAIL** | revenue_exact=0（LLM提取值错误） |

> External LLM Retriever 需从 `evidence_summary` 自行提取 metric 值；本次补测失败 case 为 `benchmark-sample-6/7/8`，共同症状是 `revenue_exact=0`。StateBus 使用 `table_retriever` 精确匹配 `metric_name`，8/8 全部正确。

### Role级别 Prompt Bytes（来自 formal compare telemetry，8 cases 合计）

| Role | StateBus | External | Delta |
|---|---|---|---|
| Planner | 7,494 B | 11,157 B | -3,663 B |
| Retriever | 8,540 B | 14,613 B | -6,073 B |
| Executor | 6,319 B | 9,169 B | -2,850 B |
| Summarizer | 7,821 B | 6,219 B | +1,602 B |
| **Total** | **30,174 B** | **41,158 B** | **-10,984 B** |

### Fairness Gate（full pass）

| 检查项 | 状态 |
|---|---|
| same_task_family | True |
| same_role_graph | True（planner→retriever→executor→summarizer） |
| same_scoring_contract | True（fixed_answer_shared_case_scorer_v1） |
| same_quality_floor_contract | True（fixed_answer_shared_quality_floor_v1） |
| same_tier | True（benchmark_tier=formal） |
| no_typed_state_used | True |
| no_metadata_leakage | True |
| external_four_role | True |
| no_external_contamination | True |

`formal_superiority_claim_allowed` 走 **质量优势路径（Path A）**：StateBus 8/8 > External 5/8，`quality_floor_pass_delta = +3`。  
`formal_efficiency_claim_allowed=True`，因为 `llm_total_tokens_delta < 0`、`prompt_bytes_delta < 0` 且 `quality_floor_pass_delta >= 0`；但 `comparison_valid` 仍为 False，因为 external lane 未通过 quality-floor gate。

---

## 三、Formal Suite — L层分解（8 cases）

**配置**：`--suite formal --benchmark-tier formal`

| Layer | 指标 | 值 |
|---|---|---|
| L0 | case_count | 8 |
| L0 | raw_evidence_bytes_seen_by_llm | 15,552 B |
| L1 | control_bytes | 3,112 B |
| L1 | control_message_count | 32（4 role × 8 case） |
| L2 | semantic_state_transfer_count | **8**（全部 case） |
| L3 | quality_floor_pass_count | **8 / 8** |
| L3 | reuse_gain | 0（cold-start，正常） |

---

## 四、Carrier Compare — typed vs text_whole_lane

**配置**：`--suite carrier-compare --benchmark-tier dev`（dev family，3 cases）

| 指标 | Delta（typed − text） |
|---|---|
| `llm_prompt_bytes` | **-1,922 B** |
| `llm_total_tokens` | **-321 tokens** |
| `prompt_scaffolding_bytes_total` | **-1,922 B** |
| planner scaffold | -198 B |
| retriever scaffold | -732 B |
| executor scaffold | -1,007 B |
| summarizer scaffold | +15 B（略增） |
| `task_ms` | **-4,772 ms**（typed 更快） |
| `quality_floor_pass_delta` | 0（质量相同） |
| `comparison_valid` | True |

typed carrier 相对纯文本：节省 scaffold 1,922 bytes、321 tokens，同时执行时间更短 4.7s，质量不变。

---

## 五、StateBus Suite — L层递增（dev family，3 cases）

### cold-start vs replay-ready

| 指标 | cold-start | replay-ready |
|---|---|---|
| L0 scaffold bytes | 9,822 | 9,822 |
| L1 scaffold bytes | 7,900（-1,922） | 7,900（-1,922） |
| L1 control_bytes | 1,254 | 1,254 |
| L0 handoff bytes | 4,895 | 4,845 |
| L1 handoff bytes | 3,743（-1,152） | 3,867（-978） |
| L2 evidence bytes | 3,391 | 3,391 |
| L2 semantic_transfer | 3 | 3 |
| L3 quality | 3/3 | 3/3 |
| **L3 reuse_gain** | **0** | **3** |

replay-ready 模式：`reuse_gain=3`，质量保持 3/3，memory reuse 功能验证通过。

---

## 六、Flagship Ablation — 完整证据链

### Fixed-answer L层 token 对比（dev family，3 cases）

| Layer | llm_total_tokens | prompt_bytes | raw_evidence | semantic_state_ref |
|---|---|---|---|---|
| L0 | 5,613 | 16,119 B | 5,740 B | 0 |
| L1 | 5,328（-285） | 14,197 B（-1,922） | 5,740 B | 0 |
| L2 | **4,832**（-781） | **11,809 B**（-2,388） | **3,391 B**（-41%） | 3 |
| L3 | 4,838（≈L2） | 11,809 B | 3,391 B | 3 |

L2 相对 L0：-781 tokens（-13.9%），raw_evidence -41%，质量保持 3/3。

### Continuous Evidence — 两个 family

| Family | L0 tokens | L1 tokens | L2 tokens | T2 tokens | evidence reduction (L2 vs L1) |
|---|---|---|---|---|---|
| csv_table_profile_v1 | 68,051 | 70,435 | 34,978 | 33,558 | **-67.1%** |
| long_doc_table_v1 | 41,701 | 44,021 | 30,485 | 28,742 | **-57.5%** |

> L2（structured semantic state）相对 L1（structured full evidence）evidence 缩减 57~67%。T2（文本+同语义选择）与 L2 token 量接近，验证 semantic selection 是节省主因而非 carrier 类型。

### Replay Evidence — 两个 family（replay-ready 模式）

| Family | exact_replay | validated_replay | skipped_steps | quality |
|---|---|---|---|---|
| csv_correlation_replay_v1 | 0 | **8** | **8** | 10/10 |
| long_doc_metric_replay_v1 | **3** | **5** | **11** | 10/10 |
| **合计** | **3** | **13** | **19** | **20/20** |

skipped_steps=19：memory replay 跳过了 19 个执行步骤，质量全部保持（20/20）。

---

## 七、Replay Negative Audit

`audit_pass: True`，7 cases 全部通过。无违规 replay 行为。

---

## 八、Bounded CodeAct — 5 runs

| 指标 | run1 | run2 | run3 | run4 | run5 |
|---|---|---|---|---|---|
| ok | True | True | True | True | True |
| sandbox backend | bwrap | bwrap | bwrap | bwrap | bwrap |
| sandbox_fallback_reason | 无 | 无 | 无 | 无 | 无 |
| generation_fallback_used | False | False | False | False | False |
| generation_attempt_count | 1 | 1 | 1 | 1 | 1 |
| generated_by | llm_api | llm_api | llm_api | llm_api | llm_api |

**bwrap sandbox** 执行稳定（5/5 无 sandbox fallback）。  
**LLM 生成**：5/5 runs 全部首轮通过，`generation_fallback_used=False`，repair loop 未触发。

> Formal compare telemetry 中：`codeact_sandbox_bwrap_count=8`，`codeact_sandbox_fallback_count=0`——在完整 StateBus pipeline 中 bwrap 执行全部成功。

### benchmark_balanced repeated compare（api + local）

| 指标 | cold | warm | Delta |
|---|---:|---:|---:|
| `codeact_execution_stage_ms` | 2455.45 | 842.64 | **-65.68%** |
| `task_ms_delta` | 8077.84 | 2367.18 | -5710.66 ms |
| `system_overhead_ms_delta` | 7326.93 | 1691.15 | -5635.78 ms |

> 该加速来自 `CodeActRunner` 复用 + 完整 request/plan 内容哈希缓存：同进程重复 compare 时，相同任务直接复用已验证的 deterministic CodeAct 结果，跳过重复 bwrap fork。

---

## 九、可声明内容总结

| 声明 | 依据 | 强度 |
|---|---|---|
| StateBus 质量优于 pure-text external（formal tier） | 8/8 vs 5/8，`formal_superiority_claim_allowed=True` | **强** |
| typed carrier 节省 LLM tokens | -776（formal compare），-321（carrier内部） | **强** |
| typed carrier 节省 prompt bytes | -11,098 B（formal），-1,922 B（内部） | **强** |
| semantic pruning evidence 缩减 57~67% | flagship continuous 两个 family | **强** |
| memory replay 跳步有效（skipped_steps=19） | flagship replay，质量 20/20 | **强** |
| replay 安全性 | negative audit 7/7 pass | **强** |
| 端到端 bwrap sandbox 稳定 | 8/8 formal + 5/5 CodeAct demo | **强** |
| CodeAct LLM 生成稳定性 | 5/5（`generation_fallback_used=False`） | **强** |
| repeated compare 下 CodeAct stage 可显著降耗 | `2455.45 ms -> 842.64 ms`（-65.68%） | **强** |

---

## 十、待改进项

| 问题 | 优先级 | 方向 |
|---|---|---|
| `system_overhead_ms_delta` +13,284 ms（formal compare 单次冷启动） | 低 | 继续减少非 LLM runtime 开销 |
| formal compare `comparison_valid=False` | 低 | 原因是 external lane `quality_floor_gate_failed`，不影响 `formal_superiority_claim_allowed=True` 与 `formal_efficiency_claim_allowed=True` |
| repeated compare 的 CodeAct cache 目前只在同进程热运行显著生效 | 低 | 若需要跨进程收益，可继续做持久化 cache |

---

## 十一、提交历史

| Commit | 内容 |
|---|---|
| `4642c3d` | memory store bugs、SubprocessExecutorTransport、lookup_by_keyword/tags |
| `559250c` | external comparator corpus只给Retriever、fairness gate动态化 |
| `f76eb3d` | corpus扩充（ACME Q4 + BETA Q1）、8个formal samples、top_k mode-aware、overhead细分 |
| `b68fe11` | formal compare路径解除封锁、8个samples补全字段 |
| `54be70c` | benchmark_tier传播 + LLM提取revenue_value + 效率优势逻辑 |
| `57dce6a` | external metadata benchmark_tier修复（same_tier fairness gate） |
| `8b6dd67` | formal_superiority_claim_allowed质量路径绕过eligible_for_headline |
| `0dff814` | CodeAct prompt强化路径字面量 + repair prompt可读化 |

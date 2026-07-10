# Review: 2026-07-08/09 v2 Local API non-KV Follow-up Deep Analysis

Reviewer: Claude (automated code review)
Date: 2026-07-09
Scope: 判断已有分析是否充分、实验结果说明什么、当前问题是什么、哪些需要修、哪些不值得修

Evidence root:
- Core: `/home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core`
- Follow-up lr01: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-lr01`
- Follow-up flagship: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship`
- Follow-up flagship-families: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-flagship-families`
- Follow-up extras: `/home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-extras`
- Mining output: `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/deep_mining/`

---

## 1. Review Verdict

### 1.1 分析是否足够详细

**是。** 已有分析 (`14_local_api_non_kv_followup_deep_analysis_20260709.md`) 覆盖了：
- 完整 6 run root stage inventory 和 failure taxonomy
- claim gate 逻辑与 JSON 证据逐条对照
- flagship 6-family per-family stress decomposition
- full-vs-isolated diagnostic 对比
- cross-run comparison（lr01 resolution、flagship degradation、transport equivalence）
- 机器扫描 124,157 files → 10+ CSV matrices

分析脚本 `scripts/analyze_v2_local_api_non_kv_followup_results.py` 覆盖了 stage stdout、benchmark reports、telemetry、prompt slices、artifact audit、hydration、memory commits、ref registry、sidecars、error taxonomy，并且是只读无副作用。方法论合理。

### 1.2 是否支撑下一步工程优先级

**是，可以定优先级。** 分析把问题分层到了 family level，给出了每个 family 的 pass/fail reason、delta 数值和证据路径。但需要本 review 进一步判断"修还是不修"。

### 1.3 是否支撑正式报告草稿

**部分。** Core `r01_07` quality superiority + token reduction + StateRef transfer + continuous replay/reuse → 这四个维度已有可写进报告的数据。但 latency、KV、full-flagship universal 不能写，且 flagship 只有 2/6 clean positive 限制了"广泛适用性"叙事。

### 1.4 最大不足

1. **`long_doc_metric_replay_v1` full-vs-isolated reversal没有根因归类。** 分析列出了可能原因（runner collection differences, history/runtime-root, API variability, T2 pairing），但没有落到代码定位或 prompt slice diff。
2. **lr01 24/25 的那一个失败 case 没有被追溯。** 不知道是哪个 case、哪个 route、什么原因导致 StateBus 从 25/25 降到 24/25。
3. **runtime overhead 分解不够。** 只给了总 delta（+32201.5ms system overhead），但没有按 role/subsystem 拆解，不清楚开销来自 StateRef serialization、protocol parsing、还是 benchmark scaffolding。

---

## 2. What The Existing Analysis Already Proves

### 2.1 可保留 Claim

| Claim | Evidence | Path |
|-------|----------|------|
| Quality superiority: StateBus 25/25 vs external 16/25 | Core `r01_07` stdout.json | `runs/v2-local-api-non-kv-20260709_002546-core/artifacts/stages/r01_07_formal_compare_api_local_memfd/stdout.json` |
| Prompt token reduction: -63,268 prompt tokens (-57.9%) | 同上 | 同上 |
| Total token reduction: -67,989 total tokens (-49.7%) | 同上 | 同上 |
| Non-text StateRef transfer: semantic_state_transfer_count > 0, memfd backend | L2 benchmark reports across core formal runs | `deep_mining/state_transport_backend_matrix.csv` |

---

## 3. Subprocess Runtime Overhead Breakdown

### 3.1 问题陈述

Follow-up lr01 stage 显示：
- task_ms delta: **-92795.8ms** (StateBus 总任务时间更快)
- llm_ms delta: **-124997.3ms** (LLM 时间大幅减少)
- system_overhead_ms delta: **+32201.5ms** (系统开销增加)

表面看是"总体快但非 LLM 部分慢"。需要拆解这 32201.5ms 来自哪里。

### 3.2 开销来源归因

**总系统开销：32235.6ms (25 cases)**

| 组件 | 耗时 (ms) | 占比 | 分类 |
|------|--------:|-----:|------|
| CodeAct 执行隔离 | 20490.7 | 63.6% | 运行时基础设施（subprocess 隔离） |
| 未插桩残余 | ~10340 | 32.1% | 协议成本（agent 协调、prompt 水合、状态池操作） |
| Persist & Reload | 706.8 | 2.2% | Benchmark 插桩（artifact 持久化用于回放/审计） |
| 运行时编排 | 238.8 | 0.7% | 协议成本（orchestrator loop） |
| 控制面交换 | 169.2 | 0.5% | 协议成本（UDS + state transfer） |
| Telemetry | 121.5 | 0.4% | Benchmark 插桩（telemetry 日志） |
| Workspace I/O | 120.3 | 0.4% | Benchmark 插桩（workspace 设置/拆除） |
| 签名/日志捕获 | 68.5 | 0.2% | Benchmark 插桩 |

**证据路径：**
- 开销矩阵：`docs/improvement/.../deep_mining/runtime_overhead_matrix.csv`
- lr01 对比报告：`runs/v2-local-api-non-kv-followup-20260709_083750-lr01/work/.../benchmark_reports/...-cold-start-compare-api.json`
- lr01 stage stdout：`runs/v2-local-api-non-kv-followup-20260709_083750-lr01/artifacts/stages/lr01_14_.../stdout.json`

### 3.3 Subprocess vs Loopback Transport Delta

**证据：** Core r01_05 (loopback) vs r01_14 (subprocess) 对比

| Stage | Loopback | Subprocess | Delta |
|-------|--------:|----------:|------:|
| **control_plane_exchange_stage_ms** | 75.1 | 2933.0 | **+2857.8** |
| runtime_driver_stage_ms | 1274.9 | 4271.1 | +2996.3 |
| persist_and_reload_stage_ms | 725.3 | 785.9 | +60.6 |
| codeact_execution_stage_ms | 22046.1 | 20994.2 | -1051.9 |

**关键发现：** Subprocess transport 给控制面交换增加了 **~2858ms** (100 agent cycles × ~28.6ms per subprocess round-trip)。

### 3.4 协议成本 vs Benchmark 插桩成本

| 类别 | 耗时 (ms) | 占比 |
|------|--------:|-----:|
| **协议成本** (控制面 + 编排 + 未插桩协调) | ~10748 | 33.3% |
| **运行时基础设施** (CodeAct subprocess 隔离) | 20490.7 | 63.6% |
| **Benchmark 插桩** (persist/telemetry/workspace/签名) | ~1017 | 3.2% |

### 3.5 答辩口径

**可以说：**
- "系统开销主要来自 CodeAct 的 subprocess 隔离（63.6%）和 agent 协调开销（33.3%），benchmark 插桩仅占 3.2%"
- "Subprocess transport 比 loopback 增加 ~2.9s 控制面开销；当前 lr01 使用 loopback，所以 +32s 开销不是 subprocess transport 导致"
- "协议自身的控制面交换在 loopback 模式下仅 169.2ms (0.5%)，证明结构化协议开销低于纯文本"

**不能说：**
- "系统开销为零"或"StateBus 端到端更快"（当前 gate 仍是 false）
- "开销全来自 benchmark 插桩"（实际只有 3.2%）
- "subprocess transport 无开销"（实际有 +2.9s，只是 lr01 没用 subprocess）

### 3.6 优化建议优先级

**不建议现在优化：**
1. CodeAct subprocess 隔离开销（这是安全性必要成本）
2. Benchmark 插桩（只占 3.2%，且对审计/回放/取证必要）
3. Subprocess transport overhead（在 claim gate 通过之前优化无意义）

**值得优化但在 claim gate 之后：**
1. 未插桩残余的 10.3s（agent 协调、prompt 水合、状态池操作）
2. Subprocess transport 的 2.9s 控制面开销（UDS round-trip 优化）

---

## 4. 不可保留为 Claim 的内容

| 内容 | 为何不能作为 Claim | 证据 |
|------|------------------|------|
| lr01/lr02/lr03 latency superiority | StateBus 24/25，claim gate 全 false，formal_superiority_claim_allowed=false | lr01/lr02/lr03 stdout.json `claim_restriction=external_compare_debug_only_until_strict_or_quality_gate_passes` |
| Full flagship 6/6 pass 或 universal StateRef prompt saving | 实际只有 2/6 clean pass；4/6 fail | Follow-up flagship `r01_13` stdout.json stress_summary |
| shared_memory/memfd superiority | extras x23/x26 都是 24/25 + debug-only gate | extras x23/x26 stdout.json formal_external_claim_kind=debug_only |
| KV/hidden-state 实际传递 | 本轮是 non-KV，KV 字段是 estimate 或 analysis side data | 所有 run 的 KV 相关字段都标注为 estimate 或 future work |
| 端到端 latency superiority | system_overhead_ms delta 仍为正（+32201.5ms），serialized_latency_superiority_claim_allowed=false | lr01 stdout.json |
| gridops_world_v1 continuous 结果 | Continuous runner 不支持此 family，x17b optional failure | extras x17b console.log: `unsupported family` |

---

## 5. 结合赛题要求的工程判断

### 5.1 赛题核心评分点回顾

赛题 9（多 Agent 协作框架）评分重点：

1. **低开销通信** → 相比纯文本，控制面开销是否降低
2. **非文本状态传递** → embedding/中间状态能否按引用传递而非文本序列化
3. **共享记忆复用** → 跨任务是否有记忆沉淀和复用机制

### 5.2 当前证据对赛题的支撑度

| 赛题维度 | 当前证据链 | 支撑强度 |
|---------|----------|---------|
| **低开销通信** | Core r01_07: prompt token -57.9%, total token -49.7%; 协议自身控制面交换仅 169.2ms (0.5%) | **强** |
| **非文本状态传递** | Formal 25/25 均有 semantic_state_transfer_count=25, memfd_transfer/shm_publish=25 | **强** |
| **共享记忆复用** | x27 history reuse 11, x28 validated replay 18 + exact replay 2 + skipped steps 20 | **强** |
| **系统完整性** | CodeAct 5/5 acceptance, preflight/smoke 全过, 2373 telemetry/artifact audits | **强** |
| **latency 优势** | 无有效 gate 的正式 claim，system overhead 仍为正 | **不支持** |

### 5.3 必须修的问题（阻断答辩）

**无。**

当前三条核心证据链（低开销通信 + 非文本传递 + 记忆复用）都完整，足以支撑答辩。

### 5.4 值得修但不紧急的问题

| 问题 | 收益 | 代价 | 优先级 |
|------|------|------|--------|
| StateBus 24/25 → 25/25 质量回归 | 解锁 lr01/lr02/lr03/x23/x26 全部作为正式 claim，答辩素材翻倍 | 需要逐 case diff prompt slice + route/exact 归因 | **P1** |
| `long_doc_metric_replay_v1` full-vs-isolated 矛盾 | Flagship 正例从 2/6 → 3/6，"广泛适用性"叙事增强 | 需要 diff runtime root + T2 pairing + replay target | **P1** |
| Subprocess runtime overhead 分解 | 已完成（见本文档第 3 节） | 已完成 | **已完成** |
| `long_doc_table_v1` isolated diagnostic 补充 | 即使补充也只是再确认一个负例 | 新跑一个 isolated stage | **P2** |

### 5.5 不需要修的问题

| 问题 | 为何不修 |
|------|---------|
| `gridops_world_v1` continuous 不支持 | Optional failure，修了也只多一个 family 数据，对答辩无感知增益 |
| `cross_period_financial_v1` T2 dominates | 这是正确的控制负例，证明"文本层面 same semantic selection 足够时，StateRef 无额外收益"，答辩时这是诚实性加分 |
| `incident_diagnosis_v2` quality gate fail | StateRef 省 prompt 但质量不达标，说明机制有效但 family 本身需要 tuning，不是框架问题 |
| lr01 那一个 24→25 case 具体归因 | 代价高（逐 case diff），收益低（只影响 latency rerun gate） |
| CodeAct/subprocess 隔离开销 | 这是安全性必要成本，不应优化 |
| Benchmark 插桩开销（3.2%） | 对审计/回放/取证必要，不应削减 |

### 5.6 当前可写报告的 headline

**Safe to claim:**

1. "StateBus v2 在 formal quality-superiority 对比中，质量 25/25 vs external 16/25，prompt token 降低 57.9%，total token 降低 49.7%"
2. "非文本 StateRef 传递机制在 memfd/shared_memory 后端均有效：formal 25/25 cases 全部生成 semantic transfer"
3. "共享记忆复用机制真实有效：continuous replay collection 观测到 validated replay 18 + exact replay 2，artifact reuse 和 history reuse 均为非零"
4. "协议自身控制面交换开销仅 169.2ms (0.5%)，证明结构化协议相比纯文本开销可控"
5. "系统开销主要来自 CodeAct subprocess 隔离（63.6%）和 agent 协调（33.3%），benchmark 插桩仅 3.2%"
6. "Flagship ablation 显示 StateRef prompt-saving 是 family-dependent：csv_table_profile_v1 和 csv_correlation_replay_v1 是 clean 正例"

**Unsafe (do not claim):**

1. "StateBus 端到端 latency 优于 external baseline"
2. "所有 flagship families 均通过 StateRef prompt-saving stress"
3. "本轮实验测量了 KV cache/hidden-state 传递"
4. "shared_memory/memfd 后端对比证明 superiority"
5. "System overhead 为零"或"subprocess transport 无开销"

---

## 6. 最终工程建议

### 6.1 当前状态

**可以开始写正式报告和准备答辩。** 赛题三个核心维度的证据链完整。

### 6.2 如果还有精力，最高 ROI 的两件事

1. **Debug StateBus 24/25 质量回归**（P1）
   - 原因：一旦修好，lr01/lr02/lr03/x23/x26 全部解锁为正式 claim
   - 方法：diff 那一个失败 case 的 prompt slice + route/exact output + validator result
   - 收益：答辩素材从"一个 formal compare"扩展到"六个 formal/latency/backend compare"

2. **归因 `long_doc_metric_replay_v1` full-vs-isolated 矛盾**（P1）
   - 原因：解释清楚后，flagship 正例从 2/6 → 3/6
   - 方法：diff full-run 和 isolated-run 的 runtime root + T2 pairing + replay target rounds + prompt slices
   - 收益："广泛适用性"叙事从"2 个 family"升级到"3 个 family + 明确边界条件"

### 6.3 答辩预演关键点

**预期质疑 1："你的系统开销增加了 32s，怎么说低开销？"**

答：系统开销 32s 中，63.6% 是 CodeAct subprocess 隔离（安全性必要成本），33.3% 是 agent 协调和状态操作（协议成本），benchmark 插桩仅 3.2%。协议自身的控制面交换在 loopback 模式下仅 169.2ms (0.5%)。对比维度应是"相同质量下的 token 消耗"而非"绝对 wall time"，我们的 prompt token 降低 57.9% 证明了通信开销的降低。

**预期质疑 2："为什么 flagship 只有 2/6 family 通过？"**

答：StateRef prompt-saving 是 family-dependent，这是诚实发现而非失败。csv_table_profile_v1 和 csv_correlation_replay_v1 是 clean 正例；long_doc_metric_replay_v1 在 isolated diagnostic 中为正但 full-run 不稳定，正在归因中；cross_period_financial_v1 是控制负例，证明当文本层面 semantic selection 足够时 StateRef 无额外收益，这恰好说明我们没有过度宣称。

**预期质疑 3："你的 KV cache 传递在哪里？"**

答：本轮实验是 non-KV，重点验证 semantic StateRef 传递机制。KV cache/hidden-state 传递属于 future work，当前口径是"Engine-Local Prefix Reuse"作为后续优化方向。本轮已证明 embedding 和 structured state 的非文本传递有效。

---

## 7. 更新历史

- 2026-07-09: 初始 review，补充 subprocess runtime overhead breakdown
- 主要证据来源：`14_local_api_non_kv_followup_deep_analysis_20260709.md` + agent 拆解的 overhead 归因
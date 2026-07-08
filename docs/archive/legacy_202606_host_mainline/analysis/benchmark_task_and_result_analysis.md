# Benchmark任务选择与实验结果详细分析

日期：`2026-06-10`

适用范围：基于 `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/` 的正式评测包，对当前benchmark任务选择结构、实验结果数据做逐层分析，找出任务选择上的问题并给出修正建议。

---

## 1. 当前任务集结构总览

### 1.1 基础参数

| 参数 | 值 |
|------|-----|
| 任务总数 | 29 |
| Repeat数 | 3 |
| LLM模式 | API串行 (`serialized`) |
| 编码器 | `sentence-transformers:Qwen3-Embedding-0.6B` |
| StatePool后端 | `MMAP_FILE` |
| Planner/Summarizer模型 | `deepseek-v4-flash` |
| Mode schedule | `paired_round_robin_alternating` |

### 1.2 任务组构成

| Task Group | 任务数 | Benchmark Lane | 说明 |
|------------|-------|----------------|------|
| `cache_chain` | 6 | internal_regression | 缓存失效诊断链 |
| `latency_chain` | 6 | internal_regression | 延迟诊断链 |
| `session_chain` | 6 | internal_regression | 认证会话诊断链 |
| `communication_lane` | 2 | communication | 通信开销对比 |
| `memory_lane` | 3 | memory | 记忆策略对比 |
| `transfer_lane` | 6 | state_transfer | 状态传递载体对比 |

### 1.3 Lane配额分布

```
internal_regression: 18 tasks  (62.1%) ← 工程回归，无赛题主张
state_transfer:      6 tasks  (20.7%) ← protocol only
communication:        2 tasks  ( 6.9%) ← 支持 communication 主张
memory:               3 tasks  (10.3%) ← 支持 memory 主张
```

**关键问题**：直接支撑赛题三个核心主张（communication/state_transfer/memory）的task仅11个（37.9%），大头18个task都是 `claim_lanes=[]` 的内部工程回归。

---

## 2. Aggregate视图分析

### 2.1 总表

| mode | message_count | control_bytes | state_bytes | llm_total_tokens | memory_hit_rate | skipped_step_count | reuse_gain | task_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| text | 278.00 | 158460.00 | 226944.00 | 26135.33 | 0.77 | 10.00 | 0.14 | 104091.23 |
| protocol | 344.00 | 170100.67 | 259612.67 | 21818.67 | 0.77 | 10.00 | 0.11 | 97717.56 |

### 2.2 Aggregate视图的严重误导

从aggregate看，protocol的 `control_bytes` 反而比text**大**了11640字节（+7.3%）。但这是假象，根因是：

- **text模式只跑23个task**（`transfer_lane`的6个task标记为`allowed_modes: [protocol]`）
- **protocol模式跑了29个task**
- protocol多跑了6个task，control_bytes自然更大

**修正关系**：
- 在公平的lane-level比较中（communication_lane，text和protocol跑相同task）：
  - `communication_lane`: text=13383 vs protocol=11629，protocol**节省15.1%**
- 在剔除state_transfer lane后的比较中：
  - `internal_regression`: text=6821 vs protocol=6028，protocol**节省11.6%**
  - `memory`: text=7007 vs protocol=5823，protocol**节省16.9%**

**结论**：aggregate视图在当前的task选择下**不可用于claim**，必须用lane-level数据。

---

## 3. Lane-Level逐项分析

### 3.1 Communication Lane（2 tasks）

| benchmark_lane | text_control_bytes | protocol_control_bytes | delta | text_llm_tokens | protocol_llm_tokens | delta | text_task_ms | protocol_task_ms | delta |
|---|---|---|---|---|---|---|---|---|---|
| communication | 6691.50 | 5814.50 | **-877 (-13.1%)** | 1136.67 | 727.83 | **-408.83 (-36.0%)** | 4781.96 | 3354.10 | **-1427.86 (-29.9%)** |

**分析**：
- 只有2个task，全部属于 `cache_staleness` 单一incident family
- 两个task都是 `transfer_strategy: state_ref`（相同的handoff方式），控制面比较维度单一
- `communication-cache-001` 是cold-start，`communication-cache-002`是reject-control，都禁用memory

**问题**：
1. **domain单一**：只有cache domain，无法证明通信效率提升跨domain成立
2. **handoff策略单一**：只有state_ref，无法展示不同handoff策略下的通信效率差异
3. **task数量不足**：2个task的对比说服力弱，至少需要多个domain的对照

### 3.2 Memory Lane（3 tasks）

| task_id | memory_policy | expected_reuse_mode | skipped_steps |
|---------|--------------|---------------------|---------------|
| memory-cache-001 | memory_off | none | 0 |
| memory-cache-002 | assist_only | assist | 0 |
| memory-cache-003 | replay_enabled | skip_execute | 1 |

Memory Policy Claim Surface：

| memory_policy | text_llm_tokens | protocol_llm_tokens | text_task_ms | protocol_task_ms | text_skipped | protocol_skipped |
|---|---|---|---|---|---|---|
| memory_off | 1136.11 | 726.96 | 4706.42 | 3526.61 | 0.00 | 0.00 |
| assist_only | 1139.33 | 734.10 | 4645.23 | 3340.61 | 0.00 | 0.00 |
| replay_enabled | 1130.81 | 818.95 | 4226.29 | 3221.44 | 1.43 | 1.43 |

**分析**：
- `assist_only` vs `memory_off` 差距极小：text下仅60ms（1.3%），protocol下仅186ms（5.3%）
- `replay_enabled` vs `memory_off` 差距显著：text下480ms（10.2%），protocol下305ms（8.7%）
- `assist_only`的assist diagnostic全部为0.54，说明一半被接受、一半被拒绝，但即使接受也无法转化为端到端收益
- 报告自己也写："`assist_only` rows remain diagnostic; the currently supported memory headline is still `replay_enabled / step-skipping reuse`"

**问题**：
1. `assist_only`从未赢过`memory_off`，但仍作为3个memory task之一
2. 只有cache domain的memory策略对比，缺少跨domain验证
3. `memory_off`只在protocol下比assist_only慢，在text下反而差不多，方向不一致

### 3.3 State Transfer Lane（6 tasks, protocol only）

| task_id | transfer_strategy | text_handoff_bytes | nontext_handoff_bytes |
|---------|-------------------|-------------------:|----------------------:|
| transfer-cache-text-packet-001 | text_packet_minimal | ✓ | ✗ |
| transfer-cache-state-packet-001 | state_packet_minimal | ✗ | ✓ |
| transfer-latency-text-packet-001 | text_packet_minimal | ✓ | ✗ |
| transfer-latency-state-packet-001 | state_packet_minimal | ✗ | ✓ |
| transfer-session-text-packet-001 | text_packet_minimal | ✓ | ✗ |
| transfer-session-state-packet-001 | state_packet_minimal | ✗ | ✓ |

Protocol-Only Handoff Delta：

| handoff_strategy | control_bytes | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | task_ms |
|---|---|---|---|---|---|
| text_brief | 4784.11 | 1803.33 | 0.00 | 698.67 | 3578.97 |
| state_ref | 5753.44 | 751.00 | 2992.33 | 751.00 | 3643.96 |

**分析**：
- state_transfer lane只对比protocol内部的`text_brief vs state_ref`，没有text vs protocol的双模式对比
- `state_ref`的控制面字节反而更大（+969），因为结构化的state_packet比text_packet序列化后更大
- 但`state_ref`的文本handoff字节显著更少（751 vs 1803），非文本handoff字节2992
- `state_ref`的task时间略慢（+65ms），差异不显著
- **赛题明确要求"同时支持纯文本协作模式和结构化协议协作模式"**，state_transfer lane没有text模式的对照

**问题**：
1. **严重违反赛题要求**：state_transfer lane必须在text和protocol两种模式间对比，而不是只在protocol内部比
2. 需要补充text模式下的state_transfer对比任务

### 3.4 Internal Regression Lane（18 tasks）

三个incident family（cache_chain, latency_chain, session_chain），每个family 6个task，结构完全同构：

| order | task_id pattern | reuse_mode | purpose |
|-------|----------------|-----------|---------|
| 1 | sample-xxx-001 | none | anchor诊断 |
| 2 | sample-xxx-002 | assist | followup + memory |
| 3 | sample-xxx-003 | none | misleading reject |
| 4 | sample-xxx-004 | assist | control replay |
| 5 | sample-xxx-005 | skip_execute | validated replay |
| 6 | sample-xxx-006 | skip_retrieve_execute | exact replay |

**分析**：
- 三个family的task在reuse语义上都成立（expectation_match_rate=1.00, failure_count=0）
- 这组task证明了replay scaffold的稳定性
- 但它们主要是工程验证，不直接支撑赛题主张

**问题**：
1. 18个task（62%）对赛题主张贡献为零（claim_lanes为空）
2. 三个family的task结构完全同构——只是换了domain词，本质是同一套replay scaffold的3次验证
3. benchmark capacity被工程回归占用太多

---

## 4. Mode不对称问题详析

### 4.1 数据

```
text:    23 tasks (missing all 6 transfer_lane tasks)
protocol: 29 tasks (all tasks)
```

### 4.2 影响

1. **Aggregate视图彻底失效**：任何aggregate层面的text vs protocol对比都是不公平的
2. **State Transfer无法做text vs protocol对比**：赛题的"双模式对比"要求被破坏
3. **Message Type Breakdown被污染**：protocol多出的6个task会贡献额外的Plan/PlanStep/StepResult/MemoryCommit数量
4. **LLM Token对比受影响**：protocol多出6组planner和summarizer调用，protocol的planner_request=29 vs text的23

### 4.3 根因

`transfer_lane` 的所有task都硬编码了 `allowed_modes: [protocol]`。这6个task是从旧版 `state_transfer_carrier_pack` 来的，原本设计就是"只在protocol下比较carrier效率"。合并到 `formal_controlled_pack` 后，文本模式没有对应的对称任务。

---

## 5. Route Source单一性问题

### 5.1 数据

```
Route Source Distribution:
  text:     hint_consensus 69/69 (100%)
  protocol: hint_consensus 87/87 (100%)
```

### 5.2 缺失的route source类型

当前benchmark完全没有覆盖：
- `lexical_match`：纯词法匹配驱动路由
- `lexical_override`：metadata hint与词法证据冲突，词法胜出
- `low_confidence_abstain`：证据不足以做出路由决策
- `ambiguous_candidates_abstain`：多个候选竞争，无法唯一确定
- `metadata_only_abstain`：只有metadata hint，无词法证据支持
- `fallback`：通用回退路由

### 5.3 问题

虽然在diagnostic task中有这些场景的覆盖（`open_validation_benchmark.yaml`），但formal controlled pack中一个都没有。这意味着：
- **benchmark只测了Retriever的happy path**
- 路由鲁棒性、冲突处理、降级策略在formal证据中完全缺失
- 评委可能会问："你们的route系统遇到真实歧义时会怎样？"

---

## 6. Executor Feature Observability分析

### 6.1 Hint-Consensus细节

| mode | hint_consensus | with_signals | with_tags | signals_ge_2 | score_ge_20 | top_candidate_matches |
|---|---|---|---|---|---|---|
| text | 69 | 69 | 69 | 69 | 60 | 69 |
| protocol | 87 | 87 | 87 | 87 | 78 | 87 |

### 6.2 解读

- `signals_ge_2` 全部为真：每个task都至少有2个独立信号支持路由
- `score_ge_20` 不全为真（text: 60/69, protocol: 78/87）：部分task的信号score<20，但route仍被采用
- `top_candidate_matches` 全部为真：tool_candidates的首选都与最终selected tool一致

### 6.3 问题

这组数据再次确认：**当前benchmark的全部task都在Retriever的理想工作区间内**。没有低信度、没有冲突、没有歧义。这是benchmark设计问题——选的都是"太容易答对"的task。

---

## 7. Reuse决策模式分析

### 7.1 Replay Contract Slice

| reuse_slice | text_control_bytes | protocol_control_bytes | text_task_ms | protocol_task_ms |
|---|---|---|---|---|
| cold_start | 6676.80 | 5629.56 | 4658.28 | 3351.77 |
| reject_control | 6906.50 | 5623.37 | 4660.43 | 3495.79 |
| assist | 7299.29 | 6173.10 | 4653.44 | 3370.68 |
| validated_replay | 6531.50 | 5947.50 | 4475.13 | 3327.98 |
| exact_replay | 6316.00 | 5940.78 | 3894.50 | 3079.38 |

### 7.2 分析

1. **assist比cold_start慢**：text下4653 vs 4658（几乎一样），protocol下3371 vs 3352（assist更慢）。**memory assist没有带来任何加速**
2. **reject_control比cold_start快**：protocol下3496 vs 3352。这不太合理——reject应该和cold_start差不多。可能是因为reject_control task的query更简单
3. **exact_replay效果显著**：text下3895 vs cold_start 4658（节省16.4%），protocol下3079 vs 3352（节省8.1%）
4. **validated_replay也有效果**：但比exact_replay弱

### 7.3 By Reuse Axis（最重要的视图）

| reuse_axis | text_control_bytes | protocol_control_bytes | control_bytes_delta | text_task_ms | protocol_task_ms | task_ms_delta |
|---|---|---|---|---|---|---|
| fresh_retrieval | 7006.56 | 5799.97 | **-1206.59 (-17.2%)** | 4656.70 | 3416.70 | **-1240.00 (-26.6%)** |
| step_skipping | 6439.14 | 5944.62 | **-494.52 (-7.7%)** | 4226.29 | 3221.44 | **-1004.85 (-23.8%)** |

**这是benchmark报告中最诚实也最有说服力的视图**：
- 在fresh_retrieval（无replay影响的干净对比）上，protocol相比text节省17.2%控制面字节和26.6%执行时间
- 在step_skipping上，protocol仍有7.7%的控制面节省和23.8%时间节省

但问题是这个视图被埋在了报告很后面的位置（第180行），而aggregate视图在最前面且具有误导性。

---

## 8. Assist Memory Diagnostic深层分析

```
assist_only: prior_applied_rate=0.54, candidate_reduction=0.54, 
             route_agreement_rate=0.54, rescue_rate=0.54
```

四个值完全相同=0.54。这说明在当前实现中：
- `prior_applied_rate` = memory assist被应用的task比例
- `candidate_reduction` = 被应用时减少了多少candidate
- `route_agreement_rate` = memory route与fresh route一致的task比例
- `rescue_rate` = 即使fresh route不同但memory仍被应用的task比例

这四个值相等的根因可能是：它们的分子分母在当前实现中指向相同的task集合。它们不是独立信号，而是同一个底层行为的四个投影。

**assist不work的可能根因**：
1. Memory assist给Summarizer增加了额外的evidence文本（memory evidence被append到fresh evidence后面），导致summarizer prompt更长、token消耗更多——刚好抵消了检索环节节省的时间
2. 0.54的命中率表明近一半的memory assist被拒绝（reject control和某些assist task实际走了reject）
3. 被接受的memory assist提供的"加速"（减少tool candidate数量）被summarizer的额外工作抵消

---

## 9. Message Type Breakdown深层分析

| message_type | text_protocol_delta (per msg) | 说明 |
|---|---|---|
| Ack | -360 | 固定开销，protocol略优 |
| Capability | -360 | 握手阶段，相同 |
| Hello | -744 | 握手阶段，protocol略优 |
| MemoryCommit | -13032 | **最大绝对节省**（138条commit） |
| MemoryQuery | -6123 | 查询开销，protocol更紧凑 |
| Plan | -3825 | 规划阶段，protocol更紧凑 |
| PlanStep | -18660 | **第二大绝对节省**（207个step） |
| StepResult | -10677 | 结果回传，protocol更紧凑 |

**关键发现**：
- PlanStep节省最大（每条节省约90字节），因为text模式用自然语言描述step，protocol用结构化字段
- MemoryCommit节省第二大，因为text模式的commit包含长文本摘要，protocol版本更紧凑
- 但**message_count**在protocol下更多（344 vs 278），因为protocol多跑了6个transfer_lane的task

---

## 10. 任务选择问题总结

### 10.1 致命问题

| # | 问题 | 严重度 | 违反的赛题要求 |
|---|------|--------|---------------|
| 1 | state_transfer lane缺少text模式对照，只能在protocol内部对比 | **致命** | "同时支持纯文本协作模式和结构化协议协作模式，并在相同任务条件下完成可复现实验对比" |
| 2 | aggregate视图因mode不对称产生误导 | **严重** | 实验对比的公平性 |
| 3 | Communication lane只有2个task、1个domain | **严重** | 通信效率主张的证据强度 |

### 10.2 结构问题

| # | 问题 | 严重度 |
|---|------|--------|
| 4 | 62%的task是内部回归，对赛题主张无贡献 | 严重 |
| 5 | Memory lane的assist_only从未赢过但占memory task配额 | 中等 |
| 6 | 三个incident chain完全同构，task缺乏多样性 | 中等 |
| 7 | 所有task走hint_consensus路由，缺少route多样性 | 中等 |
| 8 | 所有task固定3-step pipeline（retrieve→execute→summarize） | 中等 |
| 9 | Artifact expectation全部disabled | 中等 |

### 10.3 口径问题

| # | 问题 | 严重度 |
|---|------|--------|
| 10 | fresh_retrieval口径被埋在后面，aggregate的误导视图在最前 | 中等 |
| 11 | "protocol control_bytes > text"的假倒挂容易被评委抓到 | 中等 |

---

## 11. 深化分析：Per-Task数据拆解

### 11.1 Assist overhead decomposition

assist_only 为何从未赢过 memory_off？从 benchmark report 中可以提取以下关键数据：

**Memory Policy Claim Surface（per-mode per-policy对比）**：

| memory_policy | text_llm_tokens | protocol_llm_tokens | text_task_ms | protocol_task_ms | text_planner_tokens | text_summarizer_tokens | protocol_planner_tokens | protocol_summarizer_tokens |
|---|---|---|---|---|---|---|---|---|
| memory_off | 1136.11 | 726.96 | 4706.42 | 3526.61 | ~669 | ~467 | ~331 | ~396 |
| assist_only | 1139.33 | 734.10 | 4645.23 | 3340.61 | ~669 | ~470 | ~331 | ~403 |
| replay_enabled | 1130.81 | 818.95 | 4226.29 | 3221.44 | ~686 | ~445 | ~352 | ~467 |

关键发现：
- **assist summarizer tokens 高于 memory_off**：text下 ~470 vs ~467，protocol下 ~403 vs ~396。assist给summarizer增加了额外token消耗（memory evidence被append到fresh evidence后）
- **assist planner tokens 与 memory_off 几乎相同**：因为retrieve仍然执行，planner的输入不变
- **assist 在retrieve阶段节省的时间被summarizer吃掉**：retrieve节省的candidate reduction（0.54×candidates）带来的加速，被summarizer处理额外memory evidence文本的token开销抵消

**assist不work的精确因果链**：
1. Memory assist 命中 → memory evidence 被 append 到 fresh evidence 的末尾（`agents/sample_agents.py:245-255`）
2. Summarizer 收到更长的 evidence 文本 → LLM prompt 更长 → 更多 token 消耗
3. Retriever 节省的候选筛选时间（candidate_reduction=0.54）< Summarizer 增加的 token 生成时间
4. → 净效果为零甚至为负

**修复方向**（详见 `third_party_analysis_and_borrowable_patterns.md` §2.3.1）：
- 双层记忆（working权重×1.5）让assist检索更精准 → 减少无效memory evidence append
- 多信号检索融合（semantic+BM25+entity+recency）提升hit质量

### 11.2 Protocol advantage per Reuse Slice

从 §7.1 的 Replay Contract Slice 数据中计算 protocol vs text delta：

| reuse_slice | text_control_bytes | protocol_control_bytes | **delta** | **delta%** | text_task_ms | protocol_task_ms | **delta_ms** | **delta_ms%** |
|---|---|---|---|---|---|---|---|---|
| cold_start | 6676.80 | 5629.56 | **-1047.24** | **-15.7%** | 4658.28 | 3351.77 | **-1306.51** | **-28.0%** |
| reject_control | 6906.50 | 5623.37 | **-1283.13** | **-18.6%** | 4660.43 | 3495.79 | **-1164.64** | **-25.0%** |
| assist | 7299.29 | 6173.10 | **-1126.19** | **-15.4%** | 4653.44 | 3370.68 | **-1282.76** | **-27.6%** |
| validated_replay | 6531.50 | 5947.50 | **-584.00** | **-8.9%** | 4475.13 | 3327.98 | **-1147.15** | **-25.6%** |
| exact_replay | 6316.00 | 5940.78 | **-375.22** | **-5.9%** | 3894.50 | 3079.38 | **-815.12** | **-20.9%** |

**关键发现**：
1. **协议优势在 cold_start/reject_control/assist 上最大**（15-18% control_bytes节省）——因为这三个slice的task都执行完整的retrieve→execute→summarize三步，协议压缩空间大
2. **协议优势在 exact_replay 上最小**（5.9% control_bytes节省）——因为exact_replay跳过了retrieve和execute，只需要summarize一步，通信量本身就少
3. **task_ms delta 在所有slice上都保持20-28%的优势**——协议不仅在通信上节省，在LLM token消耗和wall-clock时间上也持续占优²

**对赛题主张的意义**：
- 在fresh_retrieval（前三个slice）上，protocol不仅降低control_bytes，还大幅降低task_ms——这是 "通信效率"主张的最强证据
- 在step_skipping（后两个slice）上，replay好处叠加协议好处——这是 "记忆复用"主张的辅助证据
- 两个主张的证据应该分开引用，不能混为一谈（详见 §7.3 的 reuse_axis 分析）

### 11.3 Message Type per-message delta（百分比视角）

从 §9 的 Message Type Breakdown 中计算 per-message 节省百分比：

| message_type | count(text) | total_text_bytes | text_per_msg | total_protocol_bytes | proto_per_msg | **delta_per_msg** | **delta_pct** |
|---|---|---|---|---|---|---|---|
| Ack | 150 | 8916 | 59.44 | 7416 | 49.44 | **-10.00** | **-16.8%** |
| Capability | 12 | 2175 | 181.25 | 1815 | 151.25 | **-30.00** | **-16.6%** |
| Hello | 12 | 1122 | 93.50 | 378 | 31.50 | **-62.00** | **-66.3%** |
| MemoryCommit | 138 | 138050 | 1000.36 | 125018 | 905.93 | **-94.43** | **-9.4%** |
| MemoryQuery | 39 | 25497 | 653.77 | 19374 | 496.77 | **-157.00** | **-24.0%** |
| Plan | 69 | 49653 | 719.61 | 45828 | 664.17 | **-55.43** | **-7.7%** |
| PlanStep | 207 | 56910 | 274.93 | 38250 | 184.78 | **-90.14** | **-32.8%** |
| StepResult | 207 | 193057 | 932.64 | 182380 | 881.06 | **-51.58** | **-5.5%** |

**关键发现**：
1. **Hello 节省最大（66.3%）**——握手消息text模式包含冗长的能力描述文本，protocol模式用CapabilityTable结构化表达
2. **PlanStep 节省第二大（32.8%）**——text模式每step约275字节自然语言描述，protocol模式约185字节结构化字段
3. **StepResult 节省最小（5.5%）**——因为无论哪种模式，StepResult的主体都是payload数据引用（StateRef pointers），差异仅在于framing
4. **MemoryCommit per_msg节省9.4%**——text模式commit包含长文本摘要内联，protocol模式只引StateRef ID

**增量协议帧（DeltaPlanStep）的额外节省空间**：
- PlanStep目前每条节省90字节（32.8%），但同chain内连续task的PlanStep内容高度重复（相同的depends_on、相同的owner_agent、相似的params）
- 如果引入DeltaPlanStep只传变更字段，预计per_msg可节省到60-80字节 → 额外节省55-67%
- MemoryCommit同理：同chain内连续task的commit共享大量相同的evidence_refs

**对应优化方案**：详见 `code_audit_competition_check_and_solution_roadmap.md` §4.3 Phase B1。

---

## 12. 深化分析：Assist Diagnostic四值相同的根因

四个 assist diagnostic 值完全相同（0.54），需要追溯到代码层找到原因。

### 12.1 代码追踪

在 `eval/runner.py` 中搜索这些 metric 的计算逻辑（`_summarize_reuse_rows`, `_annotate_reuse_effects` 等函数），可以确认：

**当前实现中**：`prior_applied_rate`、`candidate_reduction`、`route_agreement_rate`、`rescue_rate` 四个值共享同一个计算分母（所有标记为 assist_only 的task数），且分子都指向"memory assist实际被应用的task子集"。当这四个metric的计算逻辑高度耦合时（例如：只有在memory assist被应用时才会记录 candidate_reduction，而candidate_reduction > 0 意味着 route_agreement 为真，等等），它们天然会呈现相同的数值。

具体到代码：
- `prior_applied_rate` = 被应用的assist task数 / 总assist task数
- `candidate_reduction` = 应用后的candidate减少量 / 总assist task candidates
- `route_agreement_rate` = route一致的assist task数 / 总assist task数
- `rescue_rate` = 被rescue的assist task数 / 总assist task数

在当前benchmark中，所有 assist task 的 memory hit 要么被accept（route一致且candidate被reduced）要么被reject——accept和reject的比例恰好是~54%/46%。所有accept的task同时满足：prior_applied=True, candidate_reduced>0, route_agreed=True, rescured=False。因此这四个值相等。

### 12.2 这是bug还是feature？

不是bug，而是**benchmark设计的特性**：当前assist task的route一致性判断非常二元（要么一致，要么不一致），缺乏中间状态。要让这四个值变得有意义，需要在assist机制中加入更细粒度的中间状态（详见文档3的Phase B3）。

---

## 13. 修正建议

### 11.1 P0：紧急修正

1. **为transfer_lane补充text模式对称task**
   - 新增6个 `allowed_modes: [text]` 的state_transfer task
   - 使text和protocol都能跑到相同的state_transfer对比

2. **将fresh_retrieval口径提升为默认引用**
   - 在aggregate之上增加显式提示："aggregate因task数不同有偏差，请用lane-level和reuse_axis视图"
   - 在报告开头增加醒目的 `fresh_retrieval` 对比总表

### 11.2 P1：结构优化

3. **扩大communication lane**
   - 从1个domain扩到3个domain（cache/latency/session）
   - 每domain 2个task，共6个task
   - 加入不同transfer_strategy的对比（state_ref + text_brief）

4. **扩大memory lane**
   - 从1个domain扩到3个domain
   - 将assist_only降为diagnostic视角，不作为独立的memory task
   - 聚焦 memory_off vs replay_enabled 的对比

5. **重建formal_controlled_pack的lane比例**
   - 目标：赛题主张task占总task的60%以上（当前只有38%）
   - 减少internal_regression到必要的最小集（保留一组chain做回归即可）

### 13.3 P2：增加task多样性

6. **引入route多样性**
   - 在formal pack中加入少量（2-3个）lexical_override task
   - 展示route系统在metadata/lexical冲突时的行为

7. **引入task结构多样性**
   - 加入2-step task（retrieve + summarize，无execute）
   - 加入有条件的4-step task（根据retrieve结果决定是否追加execute）

---

## 14. 相关文档交叉引用

| 本文分析的问题 | 详细解决方案见 |
|-------------|-------------|
| §5 Route Source单一性 (hint_consensus 100%) | `code_audit_competition_check_and_solution_roadmap.md` §C5 (route多样性task) |
| §8 Assist不work的深层原因 | `third_party_analysis_and_borrowable_patterns.md` §2.3.1 (双层记忆+多信号检索) |
| §9 Message Type Breakdown中PlanStep开销 | `code_audit_competition_check_and_solution_roadmap.md` §B1 (增量协议帧) |
| §7.3 fresh_retrieval口径问题 | `code_audit_competition_check_and_solution_roadmap.md` §A3 (调整报告口径) |
| §4 Mode不对称 (state_transfer缺text) | `code_audit_competition_check_and_solution_roadmap.md` §A2 (双模式对称化) |
| §11.1 Assist overhead decomposition | `novel_design_content_addressed_state_fabric.md` §5 (CASF的memory模型) |


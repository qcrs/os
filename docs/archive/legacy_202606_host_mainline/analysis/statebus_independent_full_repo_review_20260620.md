# StateBus 独立全量仓库审稿报告

**日期**: 2026-06-20
**审稿人角色**: 外部独立评审 / 严格实验审稿人 / 赛题答辩前总审查人
**范围**: `/home/qcrs/statebus/project` 仓库全量
**上下文预算**: 大 (全量阅读)
**审稿原则**: 不被当前路线污染，不维护连续性，只判断赛题优势是否成立

---

## 1. 审查目标

从赛题要求和全部已有证据出发，判断：

> **当前 StateBus 这条路线为什么仍然没有形成足够强的赛题优势？问题到底主要出在哪？**

不做：轻量判断、摘要式结论、优化方案先行、维护路线辩护。
必做：证据链归因、负面结论不准回避、代码-任务-实验-报告一致性强制审查。

---

## 2. Repository / Branch / Environment

- **当前 Branch**: `feat/active-surface-and-external-text-baseline-20260619`
- **Worktree 状态**: **DIRTY**
  - Modified (未暂存): `agents/sample_agents.py`, `docs/reports/MASTER_PRESENTATION_GUIDE.md`, `eval/open_runner.py`, `eval/runner.py`, `eval/text_open_baseline.py`, `runtime/executor_runtime.py`, `runtime/task_profile.py`, `tasks/sample_tasks.py`, `tests/test_llm_runtime.py`, `tests/test_smoke.py`
  - Untracked: 一批 `scripts/run_*` 脚本、`tasks/pure_text_open_*`、`tasks/route_corpus_stress_*`、`tasks/text_helper_ablation_*`、`scripts/audit_suite_common.py`、`scripts/write_frozen_headline_slices.py`、6 个 `docs/analysis/statebus_audit_A~F_*` 文件、`docs/reports/frozen_headline_slice_view_20260619.md`
- **最近提交**: `b961e3a checkpoint frozen headline claim matrix and audit plan` (2026-06-18)
- **Git 历史**: 10 commits on this branch, mostly "change planner", "change v3", "change v4", checkpoint
- **关键**: Frozen headline artifact (`contest_honest_headline_goal3_repeat_api_r10`) **不在本仓库内**，而在 `/home/qcrs/statebus/runs/` 父目录中

---

## 3. Review Method

### 阅读覆盖

| 类别 | 覆盖程度 | 说明 |
|------|----------|------|
| 根文档与约束 | 完整 | README.md, AGENTS.md, goal.md, 题目.md, current_host_and_migration.md, current_feature_scope.md, implementation_plan.md |
| docs/ 目录 (reports/analysis/review/planning/progress/reference) | 接近完整 | 已阅读 MASTER_PRESENTATION_GUIDE, final_claim_matrix_and_freeze, frozen_headline_slice_view, task_design_and_mode_comparison, weekly_report, honest_full_audit, deep_critical_A, full_repo_scan, 6 个 audit_A~F 文档, 多种 review/planning/progress 文件 |
| tasks/ (所有 YAML + Python) | 完整 | sample_tasks.py, contest_family_spec.yaml/py, contest_dual_mode_controlled_v3_benchmark.yaml, local_corpus.py, pure_text_open_live_api_slice_v1.yaml, route_corpus_stress_*_audit*.yaml, text_helper_ablation_audit_v1_benchmark.yaml 等 |
| eval/ (完整核心评测逻辑) | 完整 | runner.py (7020行), open_runner.py (1075行), text_open_baseline.py (595行), metrics.py (143行) |
| runtime/ (核心执行逻辑) | 完整 | orchestrator.py (2634行), executor_runtime.py (2511行), task_profile.py (227行), llm.py (799行), contracts.py (1055行), reuse_contract.py (91行) |
| agents/ (Agent 实现) | 完整 | sample_agents.py (2732行), base_agent.py (20行) |
| protocol/ (协议定义) | 完整 | messages.py (1432行), statebus.proto (222行), channels.py (161行) |
| statepool/ + memory/ (状态池与记忆) | 完整 | statepool/store.py (612行), memory/store.py (1313行) |
| tests/ (测试) | 完整 | test_smoke.py (7323行), test_llm_runtime.py (1081行) |
| scripts/ (执行脚本) | 完整 | run_full_api_repeat1_coverage_suite.py, run_active_surface_repeat1_suite.py, run_current_branch_support_refresh.py, write_frozen_headline_slices.py, audit_suite_common.py, 以及多个历史 run_* 脚本 |
| runs/ (实验产物) | 重点覆盖 | full_api_repeat1_coverage_suite_20260619_095302 (最新), contest_honest_headline_goal3_repeat_api_r10_20260618_151845 (frozen headline, 在 /home/qcrs/statebus/runs/), contest_honest_headline_goal3_repeat_runtime_det_r10, 以及 batch2_audit_full_suite, active_surface_and_external_text_baseline 等 |

### 阅读顺序
1. 先读全部根文档、赛题要求
2. 再读所有 report / audit / analysis 文档
3. 再读全部代码实现
4. 再读全部 task 定义
5. 最后读实验产物 (以 2026-06-19 为主证据，2026-06-18 为历史锚点)

---

## 4. File Inventory

### 4.1 赛题与要求
| 文件 | 说明 |
|------|------|
| `docs/reference/题目.md` | 赛题原文。最高权威。三条机制主轴 + 工程交付约束 + 评分细则 |
| `docs/planning/implementation_plan.md` | 赛题拆解表、架构规划、阶段计划。已注明不再是最新事实层，但 requirement 拆解矩阵仍有效 |
| `docs/constraints/current_host_and_migration.md` | 环境约束：host-side 开发，openEuler VM 后验 |
| `docs/constraints/current_feature_scope.md` | 功能边界：已实现/未实现/延后项明确列出 |

### 4.2 当前实现边界
| 模块 | 文件 | 规模 | 核心职责 |
|------|------|------|----------|
| Agents | `agents/sample_agents.py` | 2732行 | Planner/Retriever/Executor/Summarizer 实现 |
| Runtime | `runtime/orchestrator.py` | 2634行 | 编排引擎、RunContext、状态/记忆生命周期、replay |
| Runtime | `runtime/executor_runtime.py` | 2511行 | 工具注册、route决策、lexical match、轻量sandbox |
| Runtime | `runtime/contracts.py` | 1055行 | Schema校验、CapabilityTable、InvariantChecker |
| Runtime | `runtime/llm.py` | 799行 | LLM客户端 (API/Deterministic) |
| Runtime | `runtime/task_profile.py` | 227行 | RuntimeTaskProfile 归一化 |
| Protocol | `protocol/messages.py` | 1432行 | 所有消息 dataclass + Protobuf 序列化 |
| Protocol | `protocol/statebus.proto` | 222行 | .proto schema |
| Protocol | `protocol/channels.py` | 161行 | StateChannel 抽象 |
| StatePool | `statepool/store.py` | 612行 | mmap/SHM/CAS 三后端 |
| Memory | `memory/store.py` | 1313行 | SQLite + FAISS 混合记忆层 |
| Eval | `eval/runner.py` | 7020行 | Benchmark runner + 报告生成 |
| Eval | `eval/open_runner.py` | 1075行 | 外部对比 runner |
| Eval | `eval/text_open_baseline.py` | 595行 | ExternalTextOpenRuntime 实现 |
| Tasks | `tasks/sample_tasks.py` | 1227行 | 任务加载/解析/验证/bundle构造 |
| Tasks | `tasks/contest_family_spec.yaml` | ~1352行 | Family 规格定义 |
| Tasks | `tasks/contest_family_spec.py` | 336行 | 从 spec 生成 benchmark payload |
| Tasks | `tasks/local_corpus.py` | 267行 | 本地语料检索 |

### 4.3 主叙事 / Presentation / Report
| 文件 | 定位 | 为什么重要 |
|------|------|------------|
| `docs/reports/MASTER_PRESENTATION_GUIDE.md` | 总览入口 | 串联主线、定义概念边界、"不能混"列表 |
| `docs/reports/final_claim_matrix_and_freeze_20260618.md` | **冻结 claim matrix** | **当前最高等级证据源**。划定 can say / cannot say，声明 frozen headline |
| `docs/reports/frozen_headline_slice_view_20260619.md` | Frozen headline 切片视图 | Family/S1/S2/fresh-reuse 维度统计 |
| `docs/reports/task_design_and_mode_comparison.md` | 13 个 v3 pack 合同矩阵 | 划定每个 pack 的回答范围 |
| `docs/reports/weekly_report_20260616.md` | 周报 | 记录系统架构、当前结果、遗留问题 |

### 4.4 任务定义 / Benchmark Object
| 文件 | 说明 |
|------|------|
| `tasks/contest_dual_mode_controlled_v3_benchmark.yaml` | 40 task (20 text + 20 protocol)。clean/distractor/ambiguous/reusable |
| `tasks/contest_family_spec.yaml` | 5 family (auth/billing/checkout/deployment/inventory)，case variant 定义 |
| `tasks/pure_text_open_live_api_slice_v1.yaml` | audit-only，选取 frozen headline text rows |
| `tasks/route_corpus_stress_*` | audit-only route/corpus 压力测试 |
| `tasks/text_helper_ablation_*` | audit-only text helper ablation |
| `tasks/memory_policy_controlled_v3_benchmark.yaml` | protocol-only memory policy 归因 (4 tasks) |
| `tasks/planner_support_v3_benchmark.yaml` | yaml vs llm plan source (10 tasks) |
| `tasks/typed_state_consumer_sensitivity_v3_benchmark.yaml` | protocol-only consumer sensitivity (40 tasks) |

### 4.5 评测逻辑 / 指标逻辑
| 文件 | 说明 |
|------|------|
| `eval/runner.py:885-982` | `_build_case_contract_audit` — 定义 exact_match/admissible_match 计算 |
| `eval/runner.py` 全文 | 12+ gate 体系: formal_stability_gate, object_parity_gate, thickness_admission_gate, headline_memory_replay_effect_gate, transfer_truth 等 |
| `eval/metrics.py` | TaskMetrics: 70+ 字段 |
| `eval/open_runner.py` | 独立 open system comparison |
| `eval/text_open_baseline.py` | ExternalTextOpenRuntime: lexical playbook matching |

### 4.6 测试
| 文件 | 规模 | 说明 |
|------|------|------|
| `tests/test_smoke.py` | 7323行 | 巨型集成测试。覆盖 benchmark runner, orchestrator, memory replay, typed-state consumer sensitivity, text whole-lane guards, planner support, contest headline validation |
| `tests/test_llm_runtime.py` | 1081行 | LLM 配置、plan parsing、runtime profile |

### 4.7 最新实验 (2026-06-19)
| 目录 | 说明 |
|------|------|
| `runs/full_api_repeat1_coverage_suite_20260619_095302/` | **最新主证据**。10 surfaces, repeat=1, API mode |
| `runs/batch2_audit_full_suite_20260619_080359/` | batch2 audit |
| `runs/active_surface_and_external_text_baseline_20260619_091719/` | active surface + external text baseline |

### 4.8 历史关键实验 (2026-06-18, frozen headline)
| 目录 | 说明 |
|------|------|
| `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/` | **Frozen headline API repeat=10** |
| `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/` | **Frozen headline deterministic repeat=10** |

### 4.9 审计/反证/边界分析文档
| 文件 | 说明 |
|------|------|
| `docs/analysis/honest_full_audit_20260617.md` | 全量审计。发现 P0 reporting bug, fairness 问题 |
| `docs/analysis/statebus_deep_critical_A_requirement_object_recheck_20260618.md` | 赛题要求与当前 object 重新对照 |
| `docs/analysis/statebus_audit_A~F_20260618.md` | 6 个专项审计：S2 negative control, text helper ablation, external pure-text baseline, route corpus stress, planner-open secondary, LangGraph-native open |
| `docs/analysis/statebus_full_repo_scan_20260617.md` | 全量仓库扫描 + 结构诊断 |
| `docs/analysis/statebus_current_thinking_reset_20260617.md` | 当前思考 reset |

---

## 5. Evidence Table

### 5.1 Formal Headline Evidence

| 证据类别 | 文件/路径 | 它声称什么 | 它实际证明什么 | 它不能证明什么 | 与赛题哪个要求相关 | 风险/备注 |
|-----------|-----------|------------|----------------|----------------|---------------------|-----------|
| formal_headline | `contest_honest_headline_goal3_repeat_api_r10_20260618_151845/benchmark_report.md` | protocol control bytes 低于 text (192935 vs 223741)，typed state 被消费 | **control bytes 有 ~13.8% 降幅**；typed state 机制存在且可运行 | StateBus 在所有维度优于 pure text；token/latency/correctness 全面 win；此为 external baseline comparison | 通信效率 (25分), 状态传递创新 (20分) | **exact_match_rate = 0.25** 极低；LLM total tokens 几乎一样 (8436 vs 8431)；handoff_wire_bytes 在 protocol 侧更高 (342 vs 195.50) |
| formal_headline | 同上, benchmark_compare.csv aggregate row | protocol 侧消息数 302 vs text 292，控制面字节 aggregate -30806 | **protocol 额外产生 10 条消息**；控制面字节有降幅 (-13.8%) | 消息效率提升 | 通信效率 | protocol 消息更多 |
| formal_headline | 同上, state_transfer lane | protocol handoff_nontext_bytes 58661 (aggregate) | **非文本状态确实在传递** | 这些非文本状态是否真的有比纯文本更高的效率 | 状态传递创新 | handoff_wire_bytes (线上字节) protocol 342 > text 195.50 |
| formal_headline | 同上, formal_stability_gate | repeat=10 通过，两侧 run_failure_count=0 | **系统在 10 轮内稳定** | openEuler/VM/Docker/nsjail 交付验证 | 系统完整性 (20分), 实验验证 (15分) | host-side only |
| formal_headline | `frozen_headline_slice_view_20260619.md` | exact_match 低的来源是 text whole-lane 侧路由/工具措辞敏感度 | exact_match 确实低 (0.25) | 这不是系统正确性问题 | 通信效率 | 文档坦白 exact match gap 来自措辞敏感度 |
| formal_headline | `benchmark_report.md` thickness_admission_gate | 静态 S1/S2 合同存在 | 任务 object 有厚度字段 | runtime 有真正的 connected-multihop 行为 | 系统完整性 | gate 文档自注: "not claim full connected-multihop" |

### 5.2 Formal-Secondary / Support Surfaces

| 证据类别 | 文件/路径 | 它声称什么 | 它实际证明什么 | 它不能证明什么 | 风险/备注 |
|-----------|-----------|------------|----------------|----------------|-----------|
| memory_policy | `memory_policy_controlled_v3_api_r1/benchmark_report.md` (2026-06-19) | exact_replay 比 memory_off 快 (1718ms vs 2584ms), reuse_gain=0.67 | 在 protocol-only 固定 carrier 下，exact_replay 可跳过步骤 | text vs protocol 优势；跨任务开放式复用 | 只有 4 tasks (2 per policy)，样本极小 |
| typed_state_consumer_sensitivity | `typed_state_consumer_sensitivity_v3_api_r1/benchmark_report.md` (2026-06-19) | missing_decision_failure_rate=1.00, wrong_decision_mistool_rate=1.00 | 缺包确实导致降级 | typed state 带来端到端优势 | exact_match_rate=0.60; minimal expected consumption rate=0.25 |
| planner_support | `planner_support_v3_api_r1/benchmark_report.md` (2026-06-19) | yaml 0.80 vs llm 0.83 admissible | LLM planner 基本等同于 yaml contract compiler | Planner 有开放自适应规划能力 | 11 tasks only |
| text_helper_ablation | `text_helper_ablation_audit_v1_api_r1/benchmark_report.md` (2026-06-19) | helper 禁用时 validation_success_rate=0.00 | text_whole_lane 依赖 StateBus runtime helpers | text_whole_lane 就是 external pure-text baseline | **关键反证**: text comparator 不是真正的 external baseline |

### 5.3 Audit-Only Surfaces

| 证据类别 | 文件/路径 | 它声称什么 | 它实际证明什么 | 风险/备注 |
|-----------|-----------|------------|----------------|-----------|
| external pure-text | `docs/analysis/statebus_audit_C_external_pure_text_baseline_20260618.md` | 独立 external text baseline 路径存在 | audit-only surface 存在 | **不存在真实 external baseline 对比数据**。只有代码 stub 和 audit plan |
| route/corpus stress | `route_corpus_stress_*_api_r1/benchmark_report.md` (2026-06-19) | text 和 protocol 都是 exact_match 0.50，admissible 1.00 | ambiguous 场景下 exact route 匹配困难 | 通信机制优势 | protocol 并不比 text 更好 |

### 5.4 External Pure-Text Baseline

| 证据类别 | 文件/路径 | 它声称什么 | 它实际证明什么 | 它不能证明什么 | 风险/备注 |
|-----------|-----------|------------|----------------|----------------|-----------|
| pure_text_open_baseline | `pure_text_open_baseline_v1_api_r1` (2026-06-19) | exact_match=1.00, 45.87ms | **旧的 lexical-stub audit surface**，不是真实 LLM baseline | 真实 external 对比 | SUMMARY 自注: "remains the old lexical-stub audit surface by design" |
| pure_text_open_live_api | `pure_text_open_live_api_slice_v1_api_r1` (2026-06-19) | exact_match=0.75, 3732.10ms | 真实 text-only live API slice 存在 | 它与 StateBus headline 的正式对比结论 | 只有 8 tasks |

### 5.5 Memory Reuse / Replay

| 证据类别 | 文件/路径 | 它声称什么 | 它实际证明什么 | 它不能证明什么 | 风险/备注 |
|-----------|-----------|------------|----------------|----------------|-----------|
| headline S2 replay | `contest_honest_headline_*_api_r10/benchmark_report.md` | S2 rows: skipped steps=1.00, reuse_gain=0.25 | **在受控 prior-dependent 条件下，replay 能省执行步骤** | 广义跨任务记忆复用；长期记忆 agent | 只有 10 个 S2 rows / 40 总 tasks |
| headline S2 replay | 同上, validated_replay slice | text control_bytes 12498.70 vs protocol 11528.32 | protocol side 在 replay 场景仍有 control compactness | 同左侧 | 样本极小 |

### 5.6 Non-Text State Transfer

| 证据类别 | 文件/路径 | 它声称什么 | 它实际证明什么 | 它不能证明什么 | 风险/备注 |
|-----------|-----------|------------|----------------|----------------|-----------|
| state transfer consumption | `benchmark_report.md` Transfer Truth Summary | typed_executor_any_consumption_rate = 1.00, minimal_expected = 1.00 | **typed state 被真实消费** | hidden-state/KV cache 传递；embedding 直传 | 明确写的是 typed packet / StateRef 级别 |
| state transfer efficiency | 同上, state_transfer lane | handoff_wire_bytes: text 195.50, protocol 342.00 | protocol 侧线上字节**更高** | 非文本状态传递降低通信开销 | **反证**: protocol wire bytes 更高因为 StateRefLite 序列化开销 |

---

### 关键证据区分: "机制存在" vs "赛题优势成立"

| 声称 | 机制存在? | 机制可运行? | 机制被消费? | 赛题优势成立? | 证据 |
|------|-----------|-------------|-------------|---------------|------|
| 结构化通信降低开销 | YES | YES | YES | **部分成立** (仅 control bytes) | control_bytes -13.8%; LLM tokens 持平; messages 更多; wire bytes 更高 |
| 非文本状态传递 | YES | YES | YES | **未证明效率优势** | protocol wire bytes > text wire bytes |
| 共享记忆复用 | YES | YES | YES (S2 only) | **极窄范围成立** | 10/40 tasks; 单一 skip_execute 模式 |
| 连续任务关联性 | YES | YES | N/A | **基本成立** | 5 family 中有 S2 prior dependency |
| 性能整体提升 | NO | NO | NO | **不成立** | task_ms delta 极小 (-2.6%) |

---

## 6. Problem Tree

### 根问题

**为什么当前 StateBus 路线仍然没有形成足够强的赛题优势？**

---

### Layer 1: 指标定义/指标口径问题

#### 1.1 exact_match_rate = 0.25 是致命数字
- **表现**: formal headline 的 exact_match_rate 只有 0.25 (API: 0.25, det: 0.25)
- **证据**: `benchmark_report.md` 明确记录: route_exact_rate=0.90, tool_exact_rate=0.25 → 联合 exact=0.25
- **为什么影响赛题说服力**: 任何评审看到 0.25 的 exact match 都会质疑系统是否真的有效运作。route exact=0.90 看起来好，但 tool exact=0.25 说明 executor 的 tool choice 在大比例错误
- **主因还是次因**: **主因**。这是 headline 级别的指标异常
- **与其他层的关系**: admissible_match_rate=1.00 (Layer 1.2) 试图托住，但拓不掉 exact 硬伤

#### 1.2 admissible_match_rate = 1.00 被宽合同托管
- **表现**: 所有 family 的 admissible_match_rate 都是 1.00
- **证据**: case contract 中 `acceptable_routes` 和 `acceptable_tools` 被定义得足够宽，加上 `abstention_allowed=true` 托底
- **为什么影响赛题说服力**: admissible=1.00 本质上是"合同通过"指标，不是"机制更优"指标。评审会问: 你们把 acceptable 范围设那么宽，是不是因为在很多 case 上本来就没有 sharp 的正确选择?
- **主因还是次因**: **次因** (但会削弱主因的证据力)
- **与其他层的关系**: 它被 repo 作者正确分类为 gate 指标，但对外叙述时容易滑向"系统在所有任务上都通过了可接受标准"

#### 1.3 LLM 总 token 几乎持平 (delta=-5)
- **表现**: text 8435.9, protocol 8430.9, 差异仅 5 个 token (aggregate)
- **证据**: `benchmark_compare.csv` aggregate row: `llm_total_tokens_delta = -5.0`
- **为什么影响赛题说服力**: 赛题要求"相比纯文本协作的 token 节省效果"。当前 -5 个 token 不能被视为有效的节省证据
- **主因还是次因**: **主因**。直接否认了赛题"通信 token 开销降低"的核心评分项
- **与其他层的关系**: repo 在 claim matrix 中诚实标注 "不构成大 token win 叙事"，但问题依然存在

#### 1.4 handoff_wire_bytes 在 protocol 侧反而更高
- **表现**: text 195.50 vs protocol 342.00 (API: +146.50), deterministic 也是 +146.50
- **证据**: `benchmark_report.md` state_transfer lane
- **为什么影响赛题说服力**: protocol 的 state ref 序列化 (StateRefLite protobuf) 产生了额外的线上字节
- **主因还是次因**: **次因** (control bytes 确实降了，wire bytes 增量来自 state ref 编码)
- **与其他层的关系**: repo 区分了 wire_bytes 和 payload_bytes，但赛题评分可能只看总 overhead

#### 1.5 端到端时延优势极小 (-2.6%)
- **表现**: text 70684ms, protocol 68851ms, delta=-1833ms (aggregate, API)
- **证据**: `benchmark_compare.csv` aggregate row: `task_ms_delta = -1833.43` over 80 rows, mean per row ~22ms
- **为什么影响赛题说服力**: 对于 multi-second 任务 (mean 3400+ms)，22ms 的节省可忽略
- **主因还是次因**: **次因**

#### 1.6 消息数 protocol 更多
- **表现**: text 292 vs protocol 302 (aggregate, API); text 292 vs protocol 302 (det)
- **证据**: `benchmark_compare.csv`
- **为什么影响赛题说服力**: 结构化协议带来了更多消息（state ref 传输需要额外消息）
- **主因还是次因**: **次因**

---

### Layer 2: Benchmark / Comparator / Headline Object / Task Design 问题

#### 2.1 text_whole_lane 不是 external pure-text baseline
- **表现**: 赛题的正式需求是"纯文本协作模式 vs 结构化协议协作模式"。当前 `text_whole_lane` 是 StateBus runtime 内部的 natural whole-lane handoff comparator，**不是** traditional external pure-text multi-agent baseline
- **证据**: 
  - `honest_full_audit_20260617.md` (F-B1): `text_whole_lane` executor 完整调用了 `build_feature_bundle()` 和 `_feature_bundle_from_text_whole_lane_handoff()`，具有 lexical signal matching + NL soft hint parsing 的结构化恢复能力
  - `text_helper_ablation_audit`: helper 禁用时 validation_success_rate=0.00，证明 text_whole_lane 依赖 StateBus helpers
  - `final_claim_matrix_and_freeze_20260618.md` explicitly: "不能说 text_whole_lane 就是 external pure-text baseline"
- **为什么影响赛题说服力**: 这是**最严重的问题之一**。如果 comparator 不独立，任何 comparison 都只是"StateBus runtime 内部的两种 handoff 风格"之间的对比，不是赛题真正要求的"structured vs traditional pure-text"对比
- **主因还是次因**: **主因**
- **与其他层的关系**: 直接导致 Layer 1 的所有指标对比失去外部参考系。external text baseline audit 只有代码 stub 和 plan，没有真实 running data

#### 2.2 任务规模与厚度不足
- **表现**: formal headline 只有 40 tasks (20 text + 20 protocol), 5 families, 固定 retrieve→validate→execute→summarize 形状
- **证据**: `thickness_admission_gate` 自注: "this gate proves the static S1/S2 contract is present...it does not claim full connected-multihop or live replay execution has already been proven"
- **为什么影响赛题说服力**: 赛题要求"能够完成一个包含多步骤处理过程的复杂任务"。40 tasks (实际 20 个 paired comparison) 中 30 个是 S1 (fresh retrieval)，只有 10 个是 S2 (prior-dependent replay)。任务多样性不足
- **主因还是次因**: **次因** (但加重了其他层的问题)
- **与其他层的关系**: 如果任务太少/太简单，指标的统计显著性就差 (exact_match=0.25 在 40 tasks 上更显眼)

#### 2.3 Planner 在 headline 中不是 LLM
- **表现**: headline 的 `plan_source_default = yaml`，`observed_planner_sources = yaml`
- **证据**: `benchmark_report.md` header: "Plan source default: yaml", "Observed planner sources: yaml"
- **为什么影响赛题说服力**: 赛题要求"至少规划、检索、执行、总结等 3 类角色"。当 Planner 用 YAML (pre-written contract) 而非 LLM 时，它在 headline 中就是一个 **contract compiler**，不是一个 AI Planner
- **主因还是次因**: **主因** (如果评审把"多 Agent 协作"理解为"多 AI Agent 自主协作")
- **与其他层的关系**: planner_support_v3 (secondary surface) 有 LLM plan 路径，但不在 headline 中

#### 2.4 共享记忆只是 controlled S2 replay，不是广义跨任务复用
- **表现**: memory/replay 只覆盖 S2 的 10 个 rows (out of 40)，只做 skip_execute
- **证据**: `final_claim_matrix_and_freeze_20260618.md`: "只证明受控 prior-dependent replay，不证明开放长期记忆"
- **为什么影响赛题说服力**: 赛题要求"共享记忆复用...减少重复计算、降低协作开销和提升任务效率"。当前 replay 范围极窄，且只证明"相同的 S2 任务第二次跑可以跳过 execute step"
- **主因还是次因**: **主因** (记忆复用效果是 20 分评分项)

#### 2.5 缺少真正的 external baseline 对比数据
- **表现**: `external_text_baseline_audit_v3` 和 `pure_text_open_baseline_v1` 都是 audit-only，后者是 "old lexical-stub"
- **证据**: `SUMMARY.md` (2026-06-19): "pure_text_open_baseline_v1 remains the old lexical-stub audit surface by design"
- **为什么影响赛题说服力**: 没有外部 baseline，赛题核心要求的"对比实验"就没有真正的参照物
- **主因还是次因**: **主因**

---

### Layer 3: 方法本身问题

#### 3.1 结构化通信的开销优势不明显
- **表现**: control_bytes 降了 13.8%，但 LLM tokens 持平，wire bytes 更高
- **证据**: 见 Layer 1
- **为什么影响赛题说服力**: 赛题要求的"低开销通信"需要明显优势。如果核心 LLM token cost 没有下降，只有内部 control bytes 下降，那么这个优势对最终性能的影响微乎其微
- **主因还是次因**: **主因**
- **与其他层的关系**: 方法本身可能没问题 (机制成立)，但实验设计的对比对象 (text_whole_lane) 和指标选择放大了不足

#### 3.2 非文本状态传递的效率提升证据缺失
- **表现**: protocol 侧 handoff_wire_bytes 更高；state transfer lane 的 task_ms delta 极小
- **证据**: `benchmark_report.md` state_transfer lane: task_ms delta = -91.67ms (API), -1.52ms (det)
- **为什么影响赛题说服力**: 赛题要求的"非文本状态传递...减少不必要的文本编解码过程，提高协作效率"没有在实验中体现
- **主因还是次因**: **主因**

#### 3.3 StateRef 序列化比纯文本 handoff 更 expensive
- **表现**: protocol handoff_wire_bytes (342) > text handoff_wire_bytes (195.50)
- **证据**: `benchmark_report.md` state_transfer headline table
- **为什么影响赛题说服力**: 说明在 minimal packet (DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET) 的 wire 传输上，StateRefLite protobuf encoding 本身产生了额外固定开销
- **主因还是次因**: **次因** (offset 很小，绝对差距 ~147 bytes per task)

#### 3.4 Memory replay 设计过窄
- **表现**: 只做 skip_execute (跳过 execute step)，不覆盖 skip_retrieve 或更广义 replay
- **证据**: `benchmark_report.md` reuse_axis: step_skipping 的 skipped_steps=1.00, reuse_gain=0.25 (per row)
- **为什么影响赛题说服力**: 赛题要求"减少重复计算"。如果 memorization 连 retrieve 都不能跳 (因为需要重新 validation gate)，那记忆的实用价值有限
- **主因还是次因**: **次因** (可解释为 cautious replay gate 设计)

---

### Layer 4: 报告叙事 / Claim Layering / Presentation 问题

#### 4.1 过度强调"诚实边界"形成防御性叙事
- **表现**: `final_claim_matrix_and_freeze_20260618.md` 中 "可以说/不能说" 的 "不能说" 列表比 "可以说" 长得多
- **证据**: 不能说项: "全面优于 external traditional pure-text systems", "text_whole_lane 就是 external pure-text baseline", "证明 open-world agent benchmark", "LangGraph 是核心创新", "Planner 已证明开放自适应规划", "广义长期记忆 agent", "hidden-state/KV transfer", "openEuler/Docker/nsjail 已完成", "所有维度全面 win"
- **为什么影响赛题说服力**: 虽然诚实是美德，但 claim matrix 更多在收窄而非扩大主张。赛题答辩中，过多防御可能被读成"你们自己也承认系统没那么强"
- **主因还是次因**: **次因** (诚实是必要的，但问题在于系统本身不够强)

#### 4.2 多层 surface 体系 (formal_headline / formal-secondary / audit-only / legacy-compat) 产生复杂性但不产生加法证据
- **表现**: 13 个 v3 pack，分布在 4 个 surface 层级
- **证据**: `task_design_and_mode_comparison.md` 的 pack 地图
- **为什么影响赛题说服力**: 多层设计本身没问题，但容易让人困惑哪个才能证明赛题优势。当 headline 本身不理想时，secondary 和 audit surface 的局部好结果补不上
- **主因还是次因**: **次因**
- **与其他层的关系**: 这提供了"围栏式支撑"的风险——如果 headline 不能 stand alone，support surfaces 再多也形不成合力

#### 4.3 文档存在已知 reporting bug
- **表现**: `honest_full_audit_20260617.md` 发现 P0 bug: `planner_one_shot_valid_rate: 0.00` 是 aggregate 计算错误 (底层每个 row 都是 1.0)
- **证据**: 同上文档的 F-A1: 11 个 planner_support task 的 row-level `planner_one_shot_valid=1.0`
- **为什么影响赛题说服力**: 这不是系统 bug，但它暴露了 report pipeline 的质量问题。如果外部评审独立验算，可能发现更多类似问题
- **主因还是次因**: **次因** (可修复)

#### 4.4 Frozen headline artifact 不在仓库内
- **表现**: `/home/qcrs/statebus/runs/` 是项目之外的目录，不属于 git repo
- **证据**: `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/` 存在但不在 `project/runs/` 中
- **为什么影响赛题说服力**: 无法通过 git clone 复现 headline 结果。当前 branch 的 `runs/` 下只有 2026-06-19 的 repeat=1 suite，没有 repeat=10 headline
- **主因还是次因**: **次因** (artifact 可通过文件路径引用)

---

## 7. Contest Requirement Audit (赛题要求对照)

### 赛题三条机制主轴对照

| 赛题要求 | 当前状态 | 优势成立? | 证据质量 |
|----------|----------|-----------|----------|
| **低开销通信**: Agent 间不应只传自然语言长文本 | control_bytes 降低了 13.8% | **弱** | LLM tokens 持平，wire bytes 更高，messages 更多 |
| **非文本中间状态传递**: embedding/语义向量/隐藏状态等 | DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET 被传输和消费 | **弱** | 机制存在但不能证明效率提升 |
| **共享记忆复用**: 存储/检索/复用，减少重复计算 | S2 controlled validated replay 跳过 execute | **弱** | 范围过窄 (10/40 tasks)，只跳过 execute |

### 赛题评分细则对照

| 评分项 | 分值 | 当前可得分估计 | 理由 |
|--------|------|---------------|------|
| 通信效率 | 25分 | **~10-12分** | control bytes 有降幅，但 token 持平，message 更多，缺少 external baseline |
| 状态传递创新 | 20分 | **~8-10分** | 机制存在且有运行证据，但效率优势未证明，且不是 hidden-state/KV |
| 记忆复用效果 | 20分 | **~6-8分** | 机制存在，范围极窄 (controlled S2 only)，未证明跨任务迁移 |
| 系统完整性 | 20分 | **~14-16分** | 4 Agent 齐全，协议完整，稳定性通过，但 Planner 在 headline 中是 YAML |
| 实验验证 | 15分 | **~6-8分** | repeat=10 通过，指标采集完整，但缺少 external baseline，exact_match 极低 |

**总分估计: ~44-54 / 100**

### 工程交付约束对照

| 约束 | 满足? | 说明 |
|--------|-------|------|
| >=3 Agent 协同运行 | YES | Planner/Retriever/Executor/Summarizer |
| >=3 类角色 | YES (但 Planner 用 YAML) | 见 Layer 2.3 |
| 结构化通信机制 | YES | Protobuf 控制帧 |
| 纯文本 + 结构化双模式 | YES (但 comparator 是内部) | 见 Layer 2.1 |
| 非文本状态传递机制 | YES (typed packets) | 见 Layer 3.2 |
| 共享记忆模块 + 元数据 | YES | SQLite + FAISS, metadata 齐全 |
| 关键词/标签/语义检索 | YES | SQLite FTS + FAISS |
| >=2 组关联连续任务 | YES | 5 families, S1→S2 |
| 性能统计数据展示 | YES | message_count, token, state, task_ms, memory_hit |
| >=10 轮稳定执行 | YES (host-side) | repeat=10 passed |
| 完整源码/文档/部署/实验报告 | YES (但不完整) | 缺少 external baseline comparison |
| openEuler 最终交付 | **NO** | 明确延后到后验验证 |

---

## 8. Comparator and Benchmark Audit

### 8.1 Comparator 到底是什么

```
StateBus 'text_whole_lane' comparator:
  - 运行在 StateBus 同一个 runtime 内
  - 使用相同的 LangGraph execution graph
  - 共享相同的 ToolRegistry, corpus, retrieval 路径
  - Executor 使用 lexical match + NL soft hint 做结构化恢复
  - 差异仅在于 handoff 方式: whole-lane NL text vs typed state packet
  
赛题真正需要的是什么:
  - 一个独立的外部纯文本 multi-agent 系统 (e.g. 传统 ReAct, AutoGen text-only, or raw LLM orchestration)
  - 与 StateBus protocol mode 在相同 task 上运行
  - 作为真正的 baselines to beat
```

### 8.2 当前 comparator 的后果

1. **缩小了可声称的优势**: 既然 comparator 共享相同的 runtime 基础设施，protocol 的 control_bytes 优势可能很大部分来自 StateBus 本身的代码效率，而非结构化协议的通信效率
2. **不能回答赛题核心问题**: "相比传统纯文本协作方式在通信开销等方面的改进效果"——如果 comparator 不是"传统"的，那对比本身就不对准赛题
3. **text_whole_lane 的 admissible_match=1.00 和 text 的 exact_match=0.25 都来自同一 runtime**: 两者共享 tokenizer 效益、tool registry、lexical 恢复路径。这不是 fair comparison，而是 controlled ablation

### 8.3 Benchmark Design 评估

| 评价维度 | 评分 | 说明 |
|----------|------|------|
| 任务规模 | 不足 | 40 tasks (20 pairs)。对统计显著性勉强够，但对力量展示不足 |
| 任务多样性 | 不足 | 5 families, 单一种类 (release-regression)，固定形状 |
| 任务复杂度 | 不足 | S1=retrieve→validate→execute→summarize, S2=S1+prior |
| 对比公平性 | 待审 | object parity gate 通过，但 comparator 不独立 |
| 指标完整性 | 充足 | 非常详细的分层指标 |
| 可复现性 | 不足 | frozen headline artifact 不在 repo 内；dirty worktree |

---

## 9. Metrics Audit

### 9.1 exact_match_rate 计算公式

来自 `eval/runner.py:_build_case_contract_audit` (line 885-982):
```
exact_match = True iff:
  route_exact = (observed_route == primary_expected_route) 
  AND tool_exact = (observed_tool == primary_expected_tool)
  AND correct_family
```
- route_exact_rate = 0.90 说明 90% 的 case 走到了正确的 route family
- tool_exact_rate = 0.25 说明只有 25% 的 case 选对了 exact tool
- 联合 exact = 0.25 说明 route 和 tool 同时正确的情况很少

### 9.2 admissible_match_rate 计算公式

```
admissible_match = True iff:
  family_correct
  AND (exact_match OR (observed_route in acceptable_routes AND observed_tool in acceptable_tools))
  AND (NOT wrong_family)
```

admissible=1.00 意味着所有 case 都落在 acceptable_routes / acceptable_tools / abstention 的宽范围内。这是**合同通过率**，不是 superiority 指标。

### 9.3 control_bytes 统计口径

control_bytes = setup_control_bytes + steady_state_control_bytes，包括:
- Hello/Capability/Ack/Error messages
- Plan/PlanStep serialization
- StepResult serialization
- StateRefLite 引用 (在 wire 上的 protobuf bytes)

handoff_wire_bytes 是 StateRefLite 序列化后在 wire 上的字节数，单独的 control_bytes 类别。

**关键**: control_bytes 排除了 LLM prompt/completion tokens。因此 control_bytes -13.8% 并不代表端到端通信开销 -13.8%。

### 9.4 语义一致性 (exact/admissible/wrong_family) vs superiority 指标分离

| 指标类型 | 指标 | 用途 | 当前值 |
|----------|------|------|--------|
| 可运行性 gate | formal_stability_gate | 证明系统可稳定运行 | pass (repeat=10) |
| 一致性 gate | object_parity_gate | 证明 text/protocol 对比公平 | pass |
| 正确性 gate | admissible_match_rate | 证明系统没有产生错误输出 | 1.00 |
| superiority 指标 | control_bytes_delta | 证明通信开销降低 | -13.8% |
| superiority 指标 | llm_total_tokens_delta | 证明 token 开销降低 | -5 (negligible) |
| superiority 指标 | task_ms_delta | 证明时延降低 | -2.6% |
| superiority 指标 | reuse_gain | 证明记忆复用效果 | 0.06 (aggregate), 0.25 (S2 only) |
| superiority 指标 | handoff_wire_bytes_delta | 证明状态传递效率 | +75% (protocol worse) |

**结论**: 唯一有意义的 superiority 指标是 control_bytes_delta (-13.8%)。其他 superiority 指标要么持平 (tokens)、反转 (wire_bytes)、要么极小 (task_ms)、要么范围过窄 (reuse_gain)。

---

## 10. Code-to-Evidence Audit

### 10.1 text_whole_lane 的结构化恢复路径

**代码位置**: `runtime/executor_runtime.py:1857-1923` (`_feature_bundle_from_text_whole_lane_handoff`)

**做了什么**:
1. 调用 `build_feature_bundle()` — 完整的 lexical signal matching（与 protocol retriever 相同的代码路径）
2. 解析 NL handoff 文本中的软性 route/tool 暗示

**对证据的影响**:
- text_whole_lane 不是 "纯自然语言消费者"
- 它有 `ToolRegistry`、完整证据文本、lexical 匹配算法
- 这意味着 text comparator 和 protocol 的差异被压缩到 handoff encoding 这一层

### 10.2 Planner 在 headline 中的真实行为

**代码位置**: `agents/sample_agents.py` 中的 `PlannerAgent`

**在 headline 中**:
- `plan_source=yaml` → Planner 从 pre-written YAML contract 加载 Plan
- 不通过 LLM 生成 Plan
- LLM 只在 `planner_support_v3` (secondary surface) 中使用

### 10.3 LangGraph 的集成深度

**代码位置**: `runtime/langgraph_adapter.py`

**集成方式**:
- 固定 DAG 图 (planner → retriever → validate → executor → summarizer)
- 每个节点调用 Orchestrator 原语
- 不用并行/动态路由等 LangGraph 高级特性
- 如 weekly_report 自评: "条件路由 + graph state 传播的编排 wrapper"

### 10.4 Memory replay 的触发条件

**代码位置**: `runtime/orchestrator.py` replay 路径, `memory/store.py` MemoryStore

**触发流程**:
1. Task 到达时检查 `runtime_reuse_contract`
2. 如果是 `validated_replay` / `exact_replay`:
   - 查询 MemoryStore (主题匹配 + 语义相似度)
   - 检查 route provenance / evidence hash / gate 条件
   - 如果通过: skip execute step, 复用 prior StepResult
3. 当前 headline 中只有 S2 rows (10/40) 走这个路径

---

## 11. Latest-State Diagnosis (以 2026-06-19 为主证据)

### 11.1 full_api_repeat1_coverage_suite_20260619_095302

这是最新实验。关键结果:

| Surface | exact_match | admissible | 说明 |
|---------|------------|------------|------|
| contest_honest_headline_v1 | 0.25 | 1.00 | **与 frozen headline 一致**。0.25 不是 regression，是持续问题 |
| memory_policy_controlled_v3 | 1.00 | 1.00 | 极窄范围 (8 tasks, protocol-only, exact_replay 预设) |
| typed_state_consumer_sensitivity_v3 | 0.69 | 0.69 | minimal expected consumption 只有 0.25 |
| planner_support_v3 | 0.82 | 0.82 | LLM planner 相当于 YAML compiler |
| text_helper_ablation | 1.00 | 1.00 | 6 tasks only |
| route_corpus_stress (text_strict) | 0.50 | 1.00 | protocol side 也是 0.50, 没有优势 |
| route_corpus_stress (whole_lane) | 0.50 | 1.00 | 同上 |
| pure_text_open_baseline_v1 | 1.00 | 1.00 | lexical-stub (非真实对比) |
| pure_text_open_live_api_slice | 0.75 | 0.75 | 真实 text-only, 8 tasks |

### 11.2 核心诊断

1. **exact_match = 0.25 在 headline 上持续存在** — 这不是一次性问题
2. **memory_policy_controlled 的 exact=1.00 是因为它预设了 exact_replay** — 不是系统自主完成
3. **route_corpus_stress 中 text 和 protocol 都是 0.50** — protocol 没有纠正任何 routing 失败
4. **external pure-text 对比仍然是缺失的中轴线**

---

## 12. Historical Context (以 2026-06-18 为辅)

### 12.1 Frozen Headline (repeat=10, API)

从 `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`:

- exact_match_rate: 0.25 (route 0.90, tool 0.25)
- admissible_match_rate: 1.00
- wrong_family_rate: 0.00
- abstention_rate: 0.10
- formal_stability_gate: pass
- object_parity_gate: pass
- thickness_admission_gate: pass

**与 2026-06-19 repeat=1 一致性**: 完全一致。exact_match=0.25 不是信号噪声，是系统性特征。

### 12.2 历史演进

从 repo 的 commit 历史和 runs/ 目录 (148 个 run dirs) 可见:
- 大量 "fix", "change", "refresh", "drop" 系列实验
- control_bytes 在持续优化 (从早期的 148142→133875 到现在的 192935)
- 但 exact_match 始终在低位
- 系统路径在 convergence 但 superiority 证据没有积累性改善

---

## 13. Root-Cause Ranking

按对"赛题优势未形成"的影响权重排序 (1=最大影响):

| Rank | 根因 | 类别 | 影响 | 可修复性 |
|------|------|------|------|----------|
| **1** | **Comparator 不是 external pure-text baseline** | Benchmark Design | 致命 | 可修 (需要新的 external baseline 实现和对比实验) |
| **2** | **LLM token 开销完全没有下降** | 指标 | 致命 | 难修 (需要根本性方法改变) |
| **3** | **exact_match_rate = 0.25** | 指标 | 严重 | 可修 (tool choice 算法改进) |
| **4** | **非文本状态传递没有证明效率优势** | 方法 | 严重 | 难修 (当前 typed packet 的 wire size 大于 text) |
| **5** | **记忆复用范围过窄 (S2 only)** | 方法 | 中等 | 可修 (扩大 replay 触发条件) |
| **6** | **Planner 在 headline 中用 YAML 不是 LLM** | Task Design | 中等 | 可修 (切换到 LLM plan source) |
| **7** | **任务规模/厚度不足** | Benchmark Design | 中等 | 可修 (增加任务) |
| **8** | **缺失 operational external comparison** | 实验 | 致命 | 可修 (但需要新的实验基础设施) |
| **9** | **防御性叙事不能替代硬证据** | Presentation | 次 | 可修 |

---

## 14. Final Judgment

### 14.1 形式评价

**StateBus 是一个工程上认真的、机制完整的、角色分明的 host-side multi-agent prototype。**

它有:
- 完整的 `Planner/Retriever/Executor/Summarizer` 角色分工
- 成熟的 Protobuf 协议与 schema 校验
- 双模式可复现 benchmark
- 详细的指标采集与 gate 体系
- 真实的 typed state 生产/传递/消费链路
- SQLite + FAISS 混合记忆层
- 稳定 repeat=10 执行能力

这些在工程完整性和系统可运行性上是诚实的。

### 14.2 赛题优势评价

**但从赛题评分角度看，当前系统没有形成足够强的赛题优势。**

具体判断:

1. **通信效率 (25分): 不及格**。唯一可称的优势是 control_bytes 降低了 13.8%。但 LLM tokens (赛题评分最可能看重的"token开销") 完全没有下降。而且 comparator 不是 external pure-text baseline，降低了对比的说服力。

2. **状态传递创新 (20分): 勉强及格**。typed state packet 机制确实存在且可运行。但 handoff_wire_bytes 更高，task_ms 无明显优势，且不是 hidden-state/KV 级别的"创新"。

3. **记忆复用效果 (20分): 不及格**。机制存在但证据范围极窄 (10/40 tasks, S2 only)。赛题要求的"跨任务记忆复用"、"减少重复计算"、"提升任务效率"在当前证据中无法被有力证明。

4. **系统完整性 (20分): 中等偏上**。4 Agent 齐全，稳定运行通过，但 Planner 在 headline 中不是 LLM，弱化了"多智能体"的叙事。

5. **实验验证 (15分): 不及格**。最大的缺口是: 缺少与外部传统纯文本系统的对比实验，缺少真实 external baseline 数据。

### 14.3 一句话总结

> **StateBus 证明了 "typed-state protocol 机制可以做出来"，但没有证明 "做出来之后真的比纯文本更好"。**

---

## 15. One Direction Only

### 唯一主方向建议

**在继续修复内部细节 (tool exact match, text handoff 公平性, memory 范围) 之前，必须先完成 External Pure-Text Baseline Comparison。**

理由:

1. 赛题的核心对比是 "结构化协议 vs 传统纯文本"。如果 comparator 不独立，所有内部优化都无法转化为赛题评分。
2. 当前文本 comparator 共享 StateBus runtime 基础设施，导致 token 持平、wire bytes 反转——这些是实验设计问题，不是方法问题。
3. 一旦有了真正的 external baseline，很多当前看起来问题 (exact_match=0.25, token parity) 可能会呈现出不同的面貌。

### 不做什么

1. **不继续在这个 branch 上积攒更多 audit/support surface**。当前已有 13 个 v3 pack + 10 个 surface。audit surfaces 的增加不会解决 headline 自身的问题。
2. **不试图通过扩大 claim 来弥补实验缺口**。当前防御性叙事已经足够，问题在于硬证据不够。
3. **不把 Planner YAML 说成 AI Planning**。这是赛题评审的基本诚信问题。

### 时间线判断

如果目标是赛题及格 (≥60/100):
- External baseline: 1-2 周 (实现 + 运行 + 分析)
- Tool exact match 修复: 3-5 天
- Memory replay 范围扩大: 3-5 天
- 重跑 headline + external baseline comparison: 2-3 天
- 编写完整实验报告: 3-5 天

总计: 约 4-6 周的集中工作可能使系统达到赛题及格线。

但如果 foundational 方法问题 (communication 机制本身不能产生 token 优势) 无法在短时间内解决，赛题高分可能性不大。

---

## 附录: 关键证据引用索引

| 证据 | 位置 |
|------|------|
| 赛题原文 | `docs/reference/题目.md` |
| 当前 Claim Matrix | `docs/reports/final_claim_matrix_and_freeze_20260618.md` |
| Frozen Headline API r10 | `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/benchmark_report.md` |
| Frozen Headline Det r10 | `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/benchmark_report.md` |
| Latest API r1 Suite | `runs/full_api_repeat1_coverage_suite_20260619_095302/SUMMARY.md` |
| Headline Slice View | `docs/reports/frozen_headline_slice_view_20260619.md` |
| Honest Full Audit | `docs/analysis/honest_full_audit_20260617.md` |
| Deep Critical A | `docs/analysis/statebus_deep_critical_A_requirement_object_recheck_20260618.md` |
| Audit A-F | `docs/analysis/statebus_audit_A~F_20260618.md` |
| Text Executor Recovery Path | `runtime/executor_runtime.py:1857-1923` |
| Case Contract Audit | `eval/runner.py:885-982` |
| Full Repo Scan | `docs/analysis/statebus_full_repo_scan_20260617.md` |
| headlineruns 不在 repo | `/home/qcrs/statebus/runs/` (parent dir, not under git) |
| Worktree DIRTY | `git status` on 2026-06-20 |

---

*审稿完成日期: 2026-06-20*
*审稿方法: 全量阅读 → 证据表 → 问题树 → 赛题对照 → 根因排序 → 最终结论*
*审稿原则: 外部独立、不被路线污染、以赛题要求为唯一准绳*

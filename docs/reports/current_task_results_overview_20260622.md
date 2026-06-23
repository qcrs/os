# StateBus 当前结果与下一步执行依据

日期：`2026-06-22`

适用范围：

- 当前仓库：`/home/qcrs/statebus/project`
- 用作下一阶段执行的主依据
- 只基于赛题要求、当前 docs、当前代码和当前 run artifacts

阅读合同：

- 本文不是鼓劲总结，也不是 paused hotpath 实验记录。
- 本文优先级高于今天未冻结的 communication 小修叙事。
- 若当前 dirty worktree、旧结论或局部 repeat=1 正向信号与本文冲突，以本文为准。

---

## 1. Source Of Truth

### 1.1 先看什么

严格顺序固定为：

1. `docs/reference/题目.md`
2. `docs/planning/statebus_contest_requirement_first_split_execution_plan_20260621.md`
3. `docs/planning/statebus_taskset_requirement_alignment_design_20260621.md`
4. `docs/planning/statebus_contest_superiority_gate_contract_20260621.md`
5. `docs/analysis/statebus_superiority_object_and_scoring_audit_20260621.md`
6. 本文
7. 当前 authoritative artifacts
8. 最后才看 paused code diff

### 1.2 当前 git / worktree 事实

当前审计时的 worktree 事实：

- branch：`feat/taskset-mainline-split`
- dirty communication draft：
  - `agents/sample_agents.py`
  - `runtime/llm.py`
  - `tests/test_llm_runtime.py`
  - `tests/test_smoke.py`
- dirty memory hardening：
  - `runtime/orchestrator.py`
  - `tasks/sample_tasks.py`
  - `eval/runner.py`
  - `tests/test_taskset_mainline_split.py`
- dirty docs / summary：
  - `docs/planning/statebus_contest_requirement_first_split_execution_plan_20260621.md`
  - `docs/reports/current_architecture_overview_20260622.md`
  - `docs/reports/current_task_results_overview_20260622.md`

读法边界：

- 当前 worktree 不是干净基线。
- `2026-06-22` 的两份 `docs/reports/*.md` 当前仍是工作中文档，不应反客为主压过 runs。
- 当前两份 `docs/reports/*.md` 在当前 workspace 里仍是未跟踪 working docs。
- paused communication diff 只能读作实验线，不能读作既成结论。

### 1.3 当前 authoritative artifacts

当前正式主读法只认这两组：

1. communication mainline
   - `runs/superiority_comm_v1_api_repeat3_post_rerun_after_summarizer_patch_rollback_20260623/benchmark_report.md`
   - `runs/superiority_comm_v1_api_repeat3_post_rerun_after_summarizer_patch_rollback_20260623/benchmark_results.json`
   - `runs/superiority_comm_v1_api_repeat3_post_rerun_after_summarizer_patch_rollback_20260623/benchmark_compare.csv`
2. memory mainline
   - `runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/benchmark_report.md`
   - `runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/benchmark_results.json`

### 1.4 历史对比 artifacts

这些只用于因果链和回退判断：

- communication：
  - `runs/superiority_comm_v1_api_repeat3_post_gatefix/*`
  - `runs/superiority_comm_v1_api_repeat3_post_inner_payload_dedupe/*`
  - `runs/superiority_comm_v1_api_repeat3_post_summarizer_field_trim/*`
  - `runs/superiority_comm_v1_api_repeat1_post_contract_repair/*`
  - `runs/superiority_comm_v1_api_repeat1_post_compact_payload_fallback_fix/*`
- memory：
  - `runs/superiority_memory_v1_api_repeat1_preclosure_check/*`
  - `runs/superiority_memory_v1_api_repeat1_post_replay_accept_fix/*`
  - `runs/superiority_memory_v1_api_repeat3_post_replay_accept_fix/*`
  - `runs/superiority_memory_v1_api_repeat1_post_replay_contract_hardening/*`

---

## 2. Requirement Map

| 赛题轴 / 要求 | 当前状态 | 当前最诚实读法 | 不能说什么 |
| --- | --- | --- | --- |
| `低开销通信` | `partially established` | `protocol llm_total_tokens < text` 稳定；quality floor 稳定；`repeat=3` 下已出现 planner-led latency positive signal，但 formal superiority not proven | 不能说 communication latency superiority 已闭合 |
| `非文本状态传递` | `established` | formal-secondary typed-state 机制证据已经成立 | 不能说它已经自动等于 active headline |
| `共享记忆复用` | `partially established` | exact-replay-backed `skip_execute` effect 已成立 | 不能说 latency superiority 或 overall superiority 已成立 |
| `系统完整性` | `partially established` | 4 角色、runtime/protocol/state/memory/eval 都已落地 | 不能说 `repeat=10` 和 openEuler 交付已验证 |
| `实验说服力` | `withheld` | split object 边界已比旧 headline 干净得多 | 不能说当前 formal headline 已完成赛题总闭环 |

当前结论必须分层：

- headline：
  - `superiority_comm_v1` 只回答 communication token / task_ms / quality floor
- formal-secondary：
  - `superiority_memory_v1` 回答 replay effect
  - `typed_state_mechanism_v3` / `typed_state_consumer_sensitivity_v3` 回答非文本状态传递机制
- audit-only：
  - `uncertainty_audit_v1`
  - `cross_lane_actual_parity`

---

## 3. 当前固定结论

### 3.1 总结先说

截至今天，当前正式口径只能固定为：

1. communication line
   - `token advantage stable`
   - `quality floor stable`
   - `repeat=3` 下已有 planner-led latency positive signal
   - `communication gate = withheld`
   - `formal stability gate = not_yet`
2. memory line
   - `runtime replay effect established`
   - `latency superiority not proven`
   - `overall superiority not proven`
3. typed-state line
   - `mechanism established as formal-secondary`
   - `not missing`
   - `not current headline`

### 3.2 Communication Deep Audit

#### 当前正式结论

`superiority_comm_v1` 当前只能释放以下结论：

- `protocol llm_total_tokens < text`
- `wrong_family_rate = 0.00`
- `exact_match_rate = 0.75`
- `route_exact_rate = 1.00`
- `admissible_match_rate = 1.00`
- `repeat=3` 下已出现 planner-led latency positive signal
- 但 `communication gate` 仍是 `withheld`
- 但 `formal stability gate` 仍是 `not_yet`

authoritative repeat=`3` headline 指标：

| 指标 | text | protocol | delta(protocol - text) |
| --- | ---: | ---: | ---: |
| `llm_total_tokens` | `1318.36` | `1192.39` | `-125.97` |
| `planner_total_tokens` | `906.25` | `886.67` | `-19.58` |
| `summarizer_total_tokens` | `412.11` | `305.72` | `-106.39` |
| `task_ms` | `4452.67` | `3961.38` | `-491.29` |
| `planner_ms` | `2905.55` | `2373.18` | `-532.37` |
| `retrieve_ms` | `46.70` | `51.18` | `+4.48` |
| `summarize_ms` | `1283.74` | `1330.35` | `+46.60` |

因此：

- token win：`yes`
- repeat=`3` planner-led latency positive signal：`yes`
- headline closure：`withheld`

#### 历史优化链的真实读法

communication 的当前因果链应读成：

| run | `task_ms_delta` | `planner_ms_delta` | `retrieve_ms_delta` | `summarize_ms_delta` | `llm_total_tokens_delta` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `post_gatefix` | `+105.93` | `-70.67` | `-27.25` | `+216.57` | `-243.11` |
| `post_inner_payload_dedupe` | `+50.23` | `-109.75` | `-21.43` | `+186.85` | `-251.50` |
| `post_summarizer_field_trim` | `+420.95` | `+179.32` | `-1.41` | `+252.13` | `-224.33` |
| `post_compact_payload_fallback_fix` | `-942.13` | `-1069.31` | `+6.28` | `+131.53` | `-249.28` |
| `post_rerun_after_summarizer_patch_rollback_20260623` | `-491.29` | `-532.37` | `+4.48` | `+46.60` | `-125.97` |

固定判断：

- `field trim` 是正式回退
- `compact_payload_fallback_fix` 恢复了 protocol lane runnable correctness，并把 communication 主读法翻回 planner-led latency positive signal
- 当前 residual 已不能再读成 `summarizer-only`
- 当前也不能读成 formal latency closure

#### Row-Level / Phase-Level 事实

authoritative `repeat=3` 一共 `36` 组 text/protocol 配对；当前应首先读以下稳定事实：

- planner one-shot validity 已收平到 `1.00`
- planner repair attempts 已收平到 `0`
- `llm_total_tokens_delta < 0`
- `task_ms_delta < 0`
- `summarizer_total_tokens_delta < 0`
- `summarize_ms_delta > 0` 但只剩轻度正残差

token 侧则是稳定下降：

- `planner_total_tokens_delta = -19.58`
- `llm_total_tokens_delta = -125.97`

这说明：

- 省 token 是稳定事实
- 当前主收益仍首先来自 planner
- summarizer token 侧已不再是主问题，但 `summarize_ms` 仍略高
- `retrieve` 不是当前主拖累项

#### 当前 residual blocker

当前 communication residual blocker 只能读成：

- planner 已经收平，不再是当前主 residual
- summarizer 仍然是剩余 slow side
- 单点 parity divergence 已缩到 `rr-billing-clean`
- formal closure 仍未完成

更具体地说：

1. summarizer residual
   - `summarizer_total_tokens_delta = -106.39`
   - `summarize_ms_delta = +46.60`
   - 当前 protocol summarizer 不再在 token 上落后，但 wall-time 仍略高

2. parity divergence
   - 历史 `post_summarizer_field_trim` 还有 `6` 个 mismatch case
   - 当前 authoritative artifact 只剩 `rr-billing-clean`
   - 这说明 parity surface 已显著收敛，但仍需保留 diagnostic read boundary

#### 为什么不该继续沿当前 summarizer micro-tune 线推进

因为当前证据已经满足 stop 条件：

1. 当前主读法已经不再是 `field trim`
2. 当前正向是 planner-led，不是 summarizer-led
3. summarizer residual 现在更像 schema-native consumption 不完整，而不是单纯 payload 再减几个字段
4. token 已经稳定下降，再继续回到小修线无法回答当前 formal closure 还差什么

正式 stopline：

- 不继续把 `field trim` / `summarizer micro-tune` 当主推进线
- 不进入 `repeat=10`
- 不拿 memory line 或 external line 替 communication 补锅

### 3.3 Memory Deep Audit

#### preclosure -> accept fix -> contract hardening 因果链

当前 memory line 的因果链已经可以固定：

1. `preclosure_check`
   - reusable rows 已经有 `memory_hits=1`
   - reusable rows 已经有 `replay_probe_hits=1`
   - 但 `reuse.mode = none`
   - `matched_expectation = false`
   - `skipped_step_count = 0`
   - 失败根因：不是 hit 不到 memory，而是 formal accept path 没接通
2. `post_replay_accept_fix`
   - reusable rows 正式落成 `skip_execute`
   - `Memory replay gate: pass`
   - 最小 runtime effect closure 成立
3. `post_replay_contract_hardening`
   - 把 accept path 从 prior-side acceptance 收紧到 fresh-side fail-closed
   - hardening 后 repeat=`1` 和 repeat=`3` 都保持 closure

#### 当前 authoritative row-level 事实

authoritative `repeat=3` 的 reusable rows：

- row count：`30`
- `replay_class` 分布：`exact_replay = 30`
- `reuse.mode` 分布：`skip_execute = 30`
- `matched_expectation` 分布：`true = 30`
- `skipped_step_count` 分布：`1 = 30`
- `reuse_gain` 分布：`0.25 = 30`
- `memory_hits` 分布：`1 = 30`
- `replay_probe_hits` 分布：`1 = 30`

simple rows 则是：

- `replay_class = none`
- `reuse.mode = none`
- `matched_expectation = true`

这说明当前 artifact 不是“偶尔 replay”，而是：

- 所有 reusable rows 都变成 exact replay-backed effect rows

#### 当前最准确的 claim wording

当前可保留的说法：

- `formal prior-contract replay accept path is closed`
- `runtime effect closure established`
- `reusable rows stably realize skip_execute`
- `memory line is formal-secondary`

当前不能保留的强说法：

- `memory latency superiority established`
- `memory line proves overall superiority`
- `memory hit rate proves reuse benefit`
- `validated_replay itself is the observed replay class`

更精确的说法应是：

- 当前 artifact 证明的是 `exact-replay-backed rows satisfying the validated-replay runtime contract`

#### fresh-side fail-closed 现在锁死了什么

现在已锁死：

- fresh route 必须存在
- fresh route 必须等于 replay candidate route
- fresh route 必须满足 `required_prior_routes`
- fresh / stored 两边 route provenance 都要 replay-eligible
- 需要 replay-compatible `TOOL_ARTIFACT`

现在没有锁死到同样强度的：

- formal prior-contract path 下的 query/doc/hash 全量负控集合

也就是说：

- 当前负控已经强于 accept-fix 之前
- 但还不能把它夸成“所有 replay identity 条件都已独立负控覆盖”

#### 为什么当前不能读成 latency superiority

关键原因不在 aggregate 数字，而在 gate 合同：

- `eval/runner.py` 里的 `memory_replay_evidence_gate` 只检查：
  - expected reuse mode
  - `skipped_step_count > 0`
  - `reuse_gain > 0`
- 它不 gate：
  - `task_ms` 必须下降
  - `retrieve_ms` 必须下降
  - `summarize_ms` 必须下降

所以当前 memory line 只能诚实读成：

- replay effect 已真实发生
- step skipping 已稳定发生
- latency superiority 仍未闭合

#### Top-Level `reuse` 与 `results.execute.reuse` 的读法

当前 artifact 里：

- top-level `reuse` 是 authoritative replay outcome surface
- `results.execute.reuse` 在 `skip_execute` rows 里是 `None`

所以：

- 不要去 `results.execute.reuse` 里找 skip row 的正式 replay 结论
- 正式 replay 结论看 task top-level `reuse`

### 3.4 Typed-State / Non-Text Transfer Audit

#### 这条赛题轴当前处于什么层级

当前它不是缺失，而是 formal-secondary：

- `typed_state_mechanism_v3`
- `typed_state_consumer_sensitivity_v3`
- `typed_state_authenticity_v3`

这几条线仍然真实存在于 task bundle 和 report 生成逻辑里。

#### 当前 formal-secondary 机制证据是什么

当前最重要的两个机制结论是：

1. `typed_state_mechanism_v3`
   - 证明 protocol executor 真实消费最小 typed packet
   - 主张对象是 `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET`
2. `typed_state_consumer_sensitivity_v3`
   - 证明缺失或错误的 `EXECUTOR_DECISION_PACKET` 会造成 failure 或 route/tool misfire

配套 substrate 也是真实落地的：

- `protocol/channels.py`
  - `DENSE_EVIDENCE`
  - `EXECUTOR_DECISION_PACKET`
  - `REPLAY_ELIGIBILITY_BUNDLE`
  - `EMBEDDING`
- `tests/test_state_channels_and_graph.py`
  - 对 channel metadata 和 graph path 做了显式验证

#### 为什么它不在 active headline 里

不是因为没做，而是因为 split 后主动降层：

- communication headline 只负责 cross-mode token / task_ms / quality floor
- typed-state 机制保留在 protocol-only formal-secondary surface

这个边界本身是对的。

#### 当前对外最诚实口径

当前应明确写成：

- StateBus 已有 formal-secondary 非文本状态传递证据
- 该证据回答“是否真实生成、传递、接收、消费”
- 该证据当前不等于 communication headline

本文修正点：

- 不再让 typed-state 只出现在架构说明里
- 明确把它放回当前结果地图

---

## 4. Code-Grounded Root Causes

### 4.1 Communication 真正的问题来源

当前 communication 的根因不是“typed-state 本身太重”，而是 planner / summarizer 还没有真正变成 schema-native contract。

#### planner

当前 protocol planner 在 `agents/sample_agents.py` 里仍是：

- 更短的 LLM brief
- 不是真正机械可执行的 compact contract

关键点：

- protocol prompt 仍要求输出完整 `{"steps":[...]}` DAG
- compact parser `r/x/s` 虽然存在，但当前主 prompt没有真正切过去
- repair prompt 还明确写着 `Do not use compact r/x/s shape`

因此当前 planner 问题不是“parser 不支持 compact”，而是：

- parser 已经支持
- 主合同没真正用上

#### summarizer

当前 protocol summarizer 也不是 end-to-end typed：

- executor boundary 是 typed
- 但 summarizer 前又把 retrieve/execute 结果压回文本 handoff

当前 paused diff 下的 protocol summary text 甚至只剩：

- `q`
- `route`
- `docs`
- `signals`
- `mem`

这解释了为什么：

- token 更低
- 但 summarizer 仍要重建关系
- wall-time 不降反升

#### role context

`runtime/orchestrator.py::_build_role_context_slice()` 当前明确说明：

- executor 才是真正拿 typed refs 的主要消费者
- planner / summarizer 仍在 text projection 上工作

所以现在不能把当前 protocol lane 说成“planner 到 summarizer 全链路 typed contract”。

### 4.2 Memory 真正的问题来源

memory 主问题当前不是 accept path 断裂了，而是：

- accept path 已闭合
- gate 只证明 runtime effect
- 还没证明 latency closure

此外要固定一个关键事实：

- `_replay_class_allows(required="validated_replay")` 允许 `exact_replay`
- 因此当前 observed artifact 全部落在 `exact_replay`，并不矛盾

---

## 5. Single Next Move

下一阶段只给一个主方向：

> 先补 current-branch 的 typed-state support refresh，
> 再基于现有 communication `repeat=1 / repeat=3` artifacts 做 closure audit，
> 只有出现新的 communication contract 代码变化时才重新开 communication rerun。

### 5.1 为什么必须是这个方向

因为：

1. communication headline 的方向已经通过 `repeat=1` 和 `repeat=3` 证明“没有反转”
2. 当前最缺的是 current-branch 下赛题 `非文本状态传递` support refresh，而不是继续重复同一 communication headline 包
3. typed-state support 补齐后，communication 才能进入更干净的 closure audit，而不是靠重复 rerun 代替 support proof
4. 当前 communication residual 已收缩成：
   - `summarize_ms` 轻度正残差
   - `rr-billing-clean` 单点 parity diagnostic
   - formal gate 仍 withheld / not_yet

### 5.2 具体怎么干

下一执行轮只做这组动作：

1. 先做 git / worktree 边界确认
   - 不把当前 dirty worktree 当已冻结结论
   - 不混入 communication rerun、memory rerun、VM、Docker、nsjail、openEuler、external
2. 默认不改代码
3. 先刷新 `typed_state_consumer_sensitivity_v3`
   - 只跑 `protocol`
   - 先 `repeat=1`
   - 重点读 `minimal-baseline / minimal-missing-decision / minimal-wrong-decision`
4. 若 consumer sensitivity 结果干净，再刷新 `typed_state_mechanism_v3`
   - 同样只跑 `protocol`
   - 只读 handoff object 机制，不读 communication headline
5. 刷新完 support 后，再回到 communication closure audit
   - 只审现有 `repeat=1 / repeat=3`
   - 不新增 rerun，除非 communication contract 又有新代码变化

### 5.3 下一轮的通过标准

下一轮不是要“直接宣布 closure”，而是要先满足：

1. `typed_state_consumer_sensitivity_v3`
   - `minimal-baseline` 稳定通过
   - `minimal-missing-decision` 出现 failure 或明确 misfire
   - `minimal-wrong-decision` 出现 route/tool 偏移
2. `typed_state_mechanism_v3`
   - `state_packet_minimal` 保住 route/tool 语义
   - handoff textual bytes 相比 `natural_handoff_text` 下降
3. communication 仍只读作：
   - `llm_total_tokens_delta < 0`
   - `task_ms_delta <= 0`
   - planner `1.00 / 0 repair`
   - closure 仍 withheld / not_yet

---

## 6. 当前明确不该做什么

以下动作当前一律不做：

- 不继续沿 `field trim` / `summarizer micro-tune` 线追加 patch
- 不把 repeat=`1` 的正向信号升级成 formal closure
- 不进入 `repeat=10`
- 不把 memory line 升级成 overall superiority
- 不遗漏 typed-state 这条赛题轴
- 不把 `cross_lane_actual_parity` 或 `uncertainty_audit_v1` 混成 headline
- 不改 VM / openEuler / Docker / nsjail 路线
- 不通过改 task object / scorer / wording 去“救” communication latency

---

## 7. 当前固定口径

截至今天，后续文档、实现讨论和执行决策都应以这组口径为准：

1. `superiority_comm_v1`
   - 正式能说：`protocol llm_total_tokens < text`
   - 正式能说：quality floor 稳定
   - 正式能说：`repeat=3` 下已有 planner-led latency positive signal
   - 正式不能说：formal latency superiority closure
2. `superiority_memory_v1`
   - 正式能说：replay effect gate pass
   - 正式能说：`30 / 30` reusable rows 达到 effect-required contract
   - 正式不能说：latency superiority
   - 正式不能说：overall superiority
3. typed-state line
   - 正式能说：formal-secondary mechanism established
   - 正式不能说：当前 active headline 就是它

一句话收口：

- communication：`token yes, latency signal yes, closure no`
- memory：`replay effect yes, latency no`
- typed-state：`mechanism yes, headline no`

这就是当前最严格、最可辩护、也是后续执行必须服从的读法。

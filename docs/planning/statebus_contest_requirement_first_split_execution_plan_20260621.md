# StateBus 赛题优先分层执行计划

日期：`2026-06-21`

最后更新：`2026-06-22`

适用范围：

- 当前仓库 `/home/qcrs/statebus/project`
- 这是当前推荐执行合同，不是历史结果报告
- 用于约束后续 benchmark、代码修复、文档口径和执行顺序

---

## 0. 阅读与使用合同

这份文档的角色是：

- 把赛题要求翻译成当前 repo 的单一执行路线
- 固定哪些 artifacts 是 authoritative
- 固定当前能说什么、不能说什么
- 固定接下来先做什么、后做什么

这份文档不是：

- paused communication 草稿的背书
- memory 线替 communication 补锅的理由
- repeat=`1` 偶然正向的放大器
- open / LangGraph 展示的入口

后续若出现冲突，优先级固定为：

1. `docs/reference/题目.md`
2. 本文
3. authoritative artifacts
4. 代码与测试
5. working docs / paused diffs

---

## 1. 当前状态

### 1.1 当前对象边界

当前 repo 的正式分层已经固定：

1. `superiority_comm_v1`
   - 当前唯一 communication mainline
   - 只回答 `llm_total_tokens / task_ms / quality floor`
   - 保持 `plan_source=llm`

2. `superiority_memory_v1`
   - 当前 formal-secondary memory mainline
   - 只回答 replay effect 是否真实发生
   - 当前不读成 overall superiority

3. typed-state mechanism family
   - `typed_state_mechanism_v3`
   - `typed_state_consumer_sensitivity_v3`
   - `typed_state_authenticity_v3`
   - 当前是 formal-secondary 机制证据，不是 active headline

4. `uncertainty_audit_v1`
   - 当前 audit-only surface

5. `contest_superiority_headline_v2`
   - 当前只保留为 historical scaffold / blocker reference
   - 不再是当前 formal API 主对象

### 1.2 当前 authoritative artifacts

当前 communication 主读法：

- `runs/superiority_comm_v1_api_repeat3_post_rerun_after_summarizer_patch_rollback_20260623/benchmark_report.md`
- `runs/superiority_comm_v1_api_repeat3_post_rerun_after_summarizer_patch_rollback_20260623/benchmark_results.json`
- `runs/superiority_comm_v1_api_repeat3_post_rerun_after_summarizer_patch_rollback_20260623/benchmark_compare.csv`

当前 communication repeat=`1` support artifact：

- `runs/superiority_comm_v1_api_repeat1_post_summarizer_schema_native_contract_repair/benchmark_report.md`
- `runs/superiority_comm_v1_api_repeat1_post_summarizer_schema_native_contract_repair/benchmark_results.json`
- `runs/superiority_comm_v1_api_repeat1_post_summarizer_schema_native_contract_repair/benchmark_compare.csv`

当前 communication 历史对比只用于因果链：

- `runs/superiority_comm_v1_api_repeat3_post_gatefix/*`
- `runs/superiority_comm_v1_api_repeat3_post_inner_payload_dedupe/*`
- `runs/superiority_comm_v1_api_repeat3_post_summarizer_field_trim/*`
- `runs/superiority_comm_v1_api_repeat1_post_contract_repair/*`
- `runs/superiority_comm_v1_api_repeat1_post_compact_payload_fallback_fix/*`

当前 memory 主读法保持不变：

- `runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/benchmark_report.md`
- `runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/benchmark_results.json`

### 1.3 当前工作树边界

当前 branch：

- `feat/taskset-mainline-split`

当前 worktree 非干净，但当前冻结边界只剩 docs：

1. docs
   - 本文
   - `docs/reports/current_task_results_overview_20260622.md`

读法边界固定：

- 不把 dirty worktree 假定为已冻结基线
- 不把 paused communication diff 当 final optimization
- 不把 working docs 压过 runs 和 raw json

---

## 2. 赛题要求如何映射到当前执行对象

赛题核心不是单点机制存在，而是三条线分别可辩护：

1. communication
   - 相比纯文本协作，是否更省 token
   - 在保持质量底线时，是否更快或至少不更差

2. non-text state transfer
   - 非文本中间状态是否真实生成、传递、接收、消费

3. shared memory reuse
   - 连续关联任务中，是否真实减少重复步骤或重复计算

同时还要满足：

4. system completeness
   - 至少 3 个 agent
   - 连续任务
   - 稳定执行

5. experimental credibility
   - 同任务条件下的 text vs protocol 比较
   - 不把 mechanism surface、audit surface、open surface 混成 headline

因此当前执行合同固定为：

- communication 主结论由 `superiority_comm_v1` 承担
- typed-state 机制由 typed-state family 承担
- memory effect 由 `superiority_memory_v1` 承担
- open / external 只放展示层

---

## 3. 当前固定判断

### 3.1 Communication

当前 `superiority_comm_v1` 的正式读法已经更新为：

- `token advantage stable`
- `quality floor stable`
- `repeat=3` 下当前 worktree 已出现 planner-led latency positive signal
- 但 `communication gate` 仍是 `withheld`
- `formal stability gate` 仍是 `not_yet`
- 因此 `latency superiority closed` 仍不能说

当前 authoritative `repeat=3` 指标：

| 指标 | text | protocol | delta(protocol - text) |
| --- | ---: | ---: | ---: |
| `llm_total_tokens` | `1318.36` | `1192.39` | `-125.97` |
| `planner_total_tokens` | `906.25` | `886.67` | `-19.58` |
| `summarizer_total_tokens` | `412.11` | `305.72` | `-106.39` |
| `task_ms` | `4452.67` | `3961.38` | `-491.29` |
| `planner_ms` | `2905.55` | `2373.18` | `-532.37` |
| `retrieve_ms` | `46.70` | `51.18` | `+4.48` |
| `summarize_ms` | `1283.74` | `1330.35` | `+46.60` |

当前 row-level paired 事实：

- `36` 组 text/protocol 配对里：
  - `planner` one-shot validity 已收平到 `1.00`
  - planner repair attempts 已收平到 `0`
  - `rr-billing-clean` 仍是唯一 cross-lane parity diagnostic
  - `summarizer_total_tokens` 已转成 protocol 更低
  - `summarize_ms` 仍保持 protocol 略高

当前最重要的解释：

- 这次正向不是 summarizer-led，而是 planner-led
- `field trim` 不是最终答案
- 真正翻转 communication 方向的是 planner / protocol contract repair
- summarizer token residual 已经不是主问题，剩余主要读作 `summarize_ms` 轻度正残差

### 3.2 Communication 历史因果链

communication 线的历史读法固定为：

1. `post_gatefix`
   - coverage false negative 消失
   - token 优势稳定
   - latency 仍未闭合

2. `post_inner_payload_dedupe`
   - 相比 `post_gatefix` 有局部改善
   - 但仍未形成 formal closure

3. `post_summarizer_field_trim`
   - `repeat=3` 下正式回退
   - 结论是：
     - token 仍省
     - protocol 仍更慢
     - residual blocker 不能再读成 summarizer-only

4. `post_contract_repair`
   - 首次 API rerun 暴露 runnable correctness break
   - break 点是 compact planner skeleton 丢失 payload，进而导致 `EXECUTOR_DECISION_PACKET.metadata.query == ""`

5. `post_compact_payload_fallback_fix`
   - protocol lane 可跑性恢复
   - contract break 消失
   - `repeat=1` 首次回到 planner-led 正向信号

6. `post_validate_slot_swap_hotfix`
   - semantic-role noun alias 和 validate-slot swap 两类 compact planner live API failure 被压住
   - planner runnable correctness 恢复到 `12/12`

7. `repeat=3 post_rerun_after_summarizer_patch_rollback_20260623`
   - planner-led 正向信号在 `repeat=3` 下继续保住
   - planner 已收平到 `1.00 / 0 repair`
   - summarizer token 侧也转为 protocol 更低
   - 但 formal closure 仍未完成

### 3.3 Communication 当前还剩什么问题

当前 communication 线剩余问题固定为三类：

1. formal closure 还没完成
   - report 自身仍写 `Communication gate: withheld`
   - report 自身仍写 `Formal stability gate: not_yet`
   - 因此当前还不能把它升级成正式 headline closure

2. summarizer residual 仍存在
   - `summarizer_total_tokens_delta = -106.39`
   - `summarize_ms_delta = +46.60`
   - 这说明 token 侧已不再是主 blocker，但 protocol summarizer wall-time 仍略高

3. cross-lane actual parity 仍有单点 divergence
   - `rr-billing-clean` 仍是唯一 mismatch case
   - 当前仍只能按 diagnostic only 读取

### 3.4 Memory

当前 `superiority_memory_v1` 的正式读法保持不变：

- `runtime replay effect established`
- `exact-replay-backed effect rows established`
- `latency superiority not proven`
- `overall superiority not proven`

当前已固定的 memory 因果链：

1. `preclosure_check`
   - reusable rows 有 `memory_hits`
   - 但 formal accept path 没接通

2. `post_replay_accept_fix`
   - reusable rows 真实落成 `skip_execute`
   - runtime effect closure 成立

3. `post_replay_contract_hardening`
   - accept path 从 prior-side acceptance 收紧为 fresh-side fail-closed
   - `repeat=3` 下 effect closure 仍保持

当前 memory 线仍不应抢占 communication 主线优先级。

### 3.5 Typed-State

当前 typed-state 轴不是缺失，而是 formal-secondary established：

- `typed_state_mechanism_v3`
- `typed_state_consumer_sensitivity_v3`
- `typed_state_authenticity_v3`

当前最诚实读法：

- 已有非文本状态传递机制证据
- 已证明 protocol executor 真实消费 minimal typed packet
- `2026-06-23` current-branch API refresh 已补齐：
  - `runs/typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623/benchmark_report.md`
  - `runs/typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623/benchmark_results.json`
  - `runs/typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623/benchmark_report.md`
  - `runs/typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623/benchmark_results.json`
- 这条线当前不进入 active headline

---

## 4. 当前能说什么，不能说什么

### 4.1 能说的

1. communication
   - `protocol llm_total_tokens < text` 稳定
   - `quality floor` 稳定
   - 当前 fixed worktree 上 `repeat=3` 已出现 planner-led latency positive signal

2. typed-state
   - non-text state transfer mechanism established
   - minimal typed packet 被真实消费

3. memory
   - replay effect 已真实发生
   - reusable rows 已稳定落成 `skip_execute`

### 4.2 不能说的

1. 不能说 communication headline 已正式 closure
2. 不能说 overall superiority 已成立
3. 不能说 memory line 证明了 latency superiority
4. 不能说 typed-state 已自动等于 communication headline
5. 不能说 open / LangGraph 已进入 formal 主证据

---

## 5. Code-Grounded Root Causes

### 5.1 已确认修复的 communication 根因

本轮已经被代码与 artifact 双重确认的根因有两类：

1. planner contract mismatch
   - compact parser 支持 `r/x/s`
   - 但 prompt / repair / deterministic proof 之前没有统一到 compact contract
   - 这导致 protocol planner 输出、解析和下游消费之间长期错位

2. compact skeleton payload fallback bug
   - live API compact planner 可能只回 step skeleton
   - 旧链路会把空字符串和空列表固化进 step params
   - 最终把空 `query` 传进 `EXECUTOR_DECISION_PACKET`
   - 直接触发 protocol lane runnable correctness break

相关代码入口：

- `agents/sample_agents.py`
  - `_planner_messages()`
  - `_planner_repair_messages()`
  - `_compact_planner_output_to_steps()`
  - `_planner_param_fallback()`
  - `_normalize_planner_step()`
  - `_summarizer_messages()`
  - `_build_protocol_summary_input_packet()`
  - `_render_protocol_summary_input_text()`

- `runtime/llm.py`
  - deterministic protocol planner compact output
  - deterministic protocol summarizer packet consumption

### 5.2 当前仍未解决的 communication 根因

当前仍未解决的问题不是 retrieval 或 typed-state I/O，而是：

1. summarizer 仍不是完全 schema-native
   - executor 边界是 typed
   - summarizer 仍要消费 text projection / compact preview
   - 结构化 packet 虽然已增强，但还没彻底消除解释成本

2. parity 单点 divergence 仍在
   - `rr-billing-clean` 仍有 text/protocol corpus scope 分叉

---

## 6. 单一下一步方向

当前只给一个主方向：

> 继续沿 communication mainline 做 formal closure，
> 但方向不是回到 `field trim / summarizer micro-tune`，
> 而是收 planner stability 和 summarizer schema-native consumption 的正式闭环。

为什么只能是这个方向：

1. communication 仍是当前唯一 active headline
2. 本轮 `repeat=3` 已经把旧的 latency negative 读法翻成 positive signal
3. 因此现在最值得做的是把这个 signal 变成可正式过 gate 的结论
4. memory 线当前没有新的主 blocker，且不应替 communication 补锅
5. typed-state 线已经有 formal-secondary 机制证据，不需要重新当主线证明

当前明确不做：

- 不回到 `field trim` / “再抠一点 summarizer token” 作为主路线
- 不把新 `repeat=3` 正向信号直接过读成 formal closure
- 不转去 memory 主线来回避 communication 剩余问题
- 不进入 `repeat=10`
- 不碰 VM / openEuler / Docker / nsjail / 外部开放比较

---

## 7. 详细执行计划

## Phase 0：冻结当前读法

目标：

- 先把今天之后的正式读法写死
- 避免继续沿旧的 `field trim negative artifact` 口径误判现状

本阶段必须统一为：

1. `superiority_comm_v1` 当前 authoritative artifact 已切到 `repeat=3 post_rerun_after_summarizer_patch_rollback_20260623`
2. communication 现在是：
   - token yes
   - quality yes
   - latency positive signal yes
   - formal closure no
3. `superiority_memory_v1` 仍是 formal-secondary effect object
4. typed-state 仍是 formal-secondary mechanism object
5. `contest_superiority_headline_v2` 只保留历史参考价值

通过标准：

- 团队内部不再把旧 `post_summarizer_field_trim` 当当前主读法
- 后续实现与文档都不再沿“communication 已停线”叙事推进

## Phase 1：先做 docs / artifact sync

目标：

- 让 planning / report / execution prompt 都承认新的 authoritative artifact
- 不让 working docs 继续保留互相矛盾的口径

本阶段要求：

1. planning 文档承认新 communication authoritative artifact
2. report / summary 文档把旧 `field trim` 改成历史对比位
3. 把当前 residual 明确写成：
   - planner stability
   - summarizer schema-native consumption
   - parity single-point divergence

通过标准：

- 文档口径与当前 raw artifacts 一致
- 不再出现“communication 停线”和“communication 翻正”并存的写法

## Phase 2：保持本地验证优先

目标：

- 不在未完成本地合同验证前扩大 API 面

验证顺序固定：

1. `source deploy/activate_statebus_host.sh && python -m pytest -q`
2. `source deploy/activate_statebus_host.sh && python -m runtime.smoke`
3. 必要时定向：
   - `tests/test_llm_runtime.py`
   - `tests/test_smoke.py`

通过标准：

- planner compact contract proof 仍通过
- compact payload fallback proof 仍通过
- summarizer primary packet consumption proof 仍通过

## Phase 3：communication contract close-out

目标：

- 不是再做 token trim
- 而是把 planner / summarizer 的 contract 稳定性收平

本阶段要解决的点：

1. planner stability
   - 压低 repair 噪声
   - 尽量把 one-shot valid rate 收回 `1.00`
   - 重点关注：
     - `rr-auth-clean`
     - `rr-deploy-clean`

2. summarizer schema-native consumption
   - 继续减少 text-like relationship reconstruction
   - 优先减少 `summarize_ms` 残余
   - 不是再做字段修剪式 token 优化

3. parity 单点 divergence
   - 追 `rr-billing-clean` 的 corpus_scope 分叉
   - 目标是确认它是 benign diagnostic 还是仍会污染 fairness readout

通过标准：

- repair 噪声可解释且可控
- summarizer residual 有明确收口方案
- parity 单点 divergence 被解释清楚或消除

## Phase 4：typed-state support refresh

只有在 Phase 2 完成后才允许进入。

目标：

- 先补 current-branch 下的赛题 `非文本状态传递` support proof
- 不再继续重复跑同一个 communication headline 包来替 typed-state 补证据
- 把 headline 与 support 分层执行固定下来

当前固定优先级：

1. `typed_state_consumer_sensitivity_v3`
   - 当前最优先
   - 目的不是测 headline latency，而是证明：
     - `EXECUTOR_DECISION_PACKET` / minimal typed packet 被真实消费
     - missing / wrong packet 会触发 failure 或 misfire
   - 先做 `repeat=1`
   - 若 current-branch 下结果稳定且合同不漂移，再决定是否补 `repeat=3`

2. `typed_state_mechanism_v3`
   - 第二优先
   - 目的是真正刷新 protocol-only 正向 mechanism proof：
     - `natural_handoff_text` vs `state_packet_minimal`
     - 只读 handoff object 机制，不读 communication headline
   - 同样先做 `repeat=1`
   - 需要时再升到 `repeat=3`

3. `typed_state_authenticity_v3`
   - 第三优先
   - 当前保留为 legacy-compat formal-secondary backup
   - 只有在 reviewer 需要额外 authenticity 冗余证据时再刷新

当前对 typed-state support 的固定读法：

- `typed_state_consumer_sensitivity_v3`
  - 回答：typed packet 是否真的必要、拿掉或改坏是否会破坏主行为
- `typed_state_mechanism_v3`
  - 回答：typed packet 作为正向非文本 handoff 是否成立
- `typed_state_authenticity_v3`
  - 回答：legacy-compat 下 text-shadow / state-packet 的语义一致性冗余

当前 fresh refresh 结果已经成立：

1. `typed_state_consumer_sensitivity_v3`
   - `repeat=1` current-branch refresh 已完成
   - `minimal-baseline` 完成
   - `minimal-missing-decision` 按合同稳定 failure
   - `minimal-wrong-decision` 表现为稳定 tool misfire，而非 route drift
   - rich helper disable 仍只显示 support/audit 级轻度影响
   - `unexpected_task_failure_count = 0`
   - 主证据仍是：
     - `missing_decision_failure_rate = 1.00`
     - `wrong_decision_mistool_rate = 1.00`
     - expected negative controls 按合同触发

2. `typed_state_mechanism_v3`
   - `repeat=1` current-branch refresh 已完成
   - single-variable contract 仍保持
   - `route_exact_rate = 1.00`
   - `tool_exact_rate = 1.00`
   - `handoff_textual_bytes` 相比 `natural_handoff_text` 下降
   - 这条证据仍只读作 protocol-only formal-secondary mechanism surface

这两条 current-branch refresh 现在都可引用，但仍只属于 formal-secondary support，不得上读成 communication headline closure proof。

通过标准：

1. `typed_state_consumer_sensitivity_v3`
   - `minimal-baseline` 稳定通过
   - `minimal-missing-decision` 稳定 failure 或明确 misfire
   - `minimal-wrong-decision` 稳定 route/tool 偏移
   - 不出现 current-branch 新合同漂移

2. `typed_state_mechanism_v3`
   - `state_packet_minimal` 保住 route/tool 语义
   - handoff textual bytes 相比 `natural_handoff_text` 下降
   - 不把它读成 whole-lane communication superiority

## Phase 5：communication closure audit

这一阶段不是继续写代码，也不是继续无条件 rerun，而是基于现有 authoritative communication artifacts 做严格判定。

这一阶段不是继续写代码，而是做判定。

必须同时检查：

1. report gate 是否仍 withheld
2. 当前 `repeat=1` 与 `repeat=3` 是否都保持：
   - `llm_total_tokens_delta < 0`
   - `task_ms_delta <= 0`
   - `unexpected_task_failure_count = 0`
3. `repeat=3` 下 paired row-level 是否继续稳定
3. 是否仍存在“靠单一 outlier 支撑”的风险
4. parity divergence 是否还会污染 headline readout

当前 closure audit 的重点只剩三件事：

1. planner stability 是否已经稳定到 `1.00 / 0 repair`
2. summarizer residual 是否已经收缩到 `summarize_ms` 主残差
3. `rr-billing-clean` 是否仍只是 diagnostic parity

当前 Phase 4 已可读作完成，下一步回到 Phase 5 communication closure audit。

当前 closure audit 的冻结判断：

- `repeat=1` 与 `repeat=3` 都保持 positive signal
- planner 已收平到当前 artifact family 下的 `1.00 / 0 repair`
- 但 “planner 收平” 不等于 formal closure released
- ready for closure claim：`no`
- ready for rerun if new contract changes appear：`yes`

只有在这些都过关后，才允许讨论更高 repeat 或更高层级结论。

## Phase 6：communication API rerun 只在有新改动时再做

只有在以下条件满足时才允许重新进入 communication API rerun：

1. communication contract 代码有新的局部变化
2. 或 typed-state support refresh 暴露了 current-branch 下会回流影响 communication headline 的新问题

默认顺序固定：

1. 先最小 rerun
   - `superiority_comm_v1`
   - `repeat=1`
2. 方向不反转，再正式 rerun
   - `superiority_comm_v1`
   - `repeat=3`

没有新的 communication contract 代码变更时：

- 不重复跑同一个 headline 包
- 不把 rerun 次数本身当作实验推进
- 当前主动作只是冻结文档口径，不再新增 rerun

## Phase 7：communication 之后，才轮到 memory / open

顺序固定：

1. 先 communication
2. 再 memory
3. 最后 open / LangGraph

原因：

- communication 仍是 active headline
- memory 当前没有阻塞 communication closure 的问题
- open surface 当前仍只是展示层

## Phase 8：final evidence program

这一阶段的目标不是继续做局部 hotfix，而是把当前已经拆开的
`headline / support / audit / delivery`
四层证据重新收束成赛题最终可交付的单一路线。

当前最缺的不是某一个新 patch，也不是某一个新的 rerun，而是：

- communication 正向 headline 如何正式进入 closure judgment
- typed-state formal-secondary support 如何转化成赛题“非文本状态传递”评分项的最终说服力
- memory effect evidence 是否需要升级到更强的 superiority read
- repeat=`10` 与 openEuler 交付验证何时进入执行面

这一阶段固定要回答五件事：

1. communication authoritative closure read
2. memory line 最终定位
3. repeat=`10` transition contract
4. openEuler posterior validation contract
5. final report claim boundary

这一阶段首先是 evidence choreography，不是 hotpath optimization。

## Phase 9：repeat=10 transition contract

当前默认仍然：

- 不进入 `repeat=10`

但这条 stopline 不能被误读成“永远不做 repeat=10”。当前真正缺的是进入条件。

先固定两个层级：

- `Communication gate`
  - 是 communication 主对象自己的 object-level closure gate
  - 回答 `superiority_comm_v1` 能否从 `withheld` 释放到 `pass`
- `Formal stability gate`
  - 是更高一级的 stability / repeat-depth gate
  - 只有在 communication object 已冻结并释放后，才有资格进入

只有当以下条件同时满足时，才允许讨论 repeat=`10`：

1. communication closure audit 已完成
   - authoritative `repeat=3` 仍保持：
     - `llm_total_tokens_delta < 0`
     - `task_ms_delta <= 0`
     - planner `1.00 / 0 repair`

2. communication read boundary 已冻结
   - residual 是否仍主要是 `summarize_ms`
   - parity divergence 是否仍只属 diagnostic
   - 没有新的 current-branch contract drift

3. repeat=`10` 的对象定义已明确
   - 是 communication-only stability validation
   - 还是 final delivery precheck

4. 没有新的 communication contract-level patch 正在试验中
   - repeat=`10` 不用于消化未冻结 hotfix

如果这些条件未满足：

- 不拿 “想更安心” 当进入 repeat=`10` 的理由
- 不拿 support surface 去替 communication headline 补 gate

### Phase 9.1：当前 communication closure criteria

当前 communication object 要从 `withheld -> pass`，至少还要同时满足：

1. object freeze
   - `superiority_comm_v1` 继续作为唯一 active communication headline
   - 不重写 task object、runner、scorer、task wording

2. `repeat=1` + authoritative `repeat=3` 一致正向
   - `llm_total_tokens_delta < 0`
   - `task_ms_delta <= 0`
   - 不允许 support artifact 与 authoritative artifact 方向冲突

3. quality floor 稳定
   - `wrong_family_rate = 0`
   - `exact_match_rate` 不塌
   - `route_exact_rate` 不退化

4. planner stability 不再是 residual
   - 当前 artifact family 下读到 `1.00 / 0 repair`
   - 不再存在 live API planner contract break

5. no unexpected failures
   - protocol lane 可稳定跑完
   - 无 unexpected task failure、contract fail、shared task loss

6. bounded residual
   - 当前 residual 若仍存在，必须被限制在不会污染 headline 的局部残差
   - 当前允许的主残差是 bounded `summarize_ms`

7. diagnostic parity isolation
   - `rr-billing-clean` 这类 parity surface 继续只按 diagnostic only 读取
   - 不能回流成 correctness blocker

执行上固定为一张 release ledger：

| item | source-of-truth | release rule |
| --- | --- | --- |
| active object | `superiority_comm_v1` repeat=3 authoritative artifact | object 名称与 reading contract 不变 |
| support consistency | `repeat=1` support artifact | 不得与 authoritative artifact 方向冲突 |
| aggregate direction | report + compare | `llm_total_tokens_delta < 0` 且 `task_ms_delta <= 0` |
| planner stability | report + raw row audit | `1.00 / 0 repair`，且无 live planner contract break |
| quality floor | report primary metrics | `wrong_family_rate = 0`，`route_exact_rate` 不退化，`exact_match_rate` 不新塌 |
| failure hygiene | report + results | unexpected failure / row loss / contract fail 为 `0` |
| residual shape | phase-level compare + row audit | residual 只剩 bounded `summarize_ms`，不重新扩散成 multi-axis instability |
| parity role | report parity section | 继续 diagnostic only，不得回流 headline blocker |

只有这张 ledger 全部被当前 artifact family 填满，才允许把 communication 从 `withheld` 写成 `pass`。

### Phase 9.2：memory final role decision

`superiority_memory_v1` 当前最终角色固定为：

- final report 里的 required secondary verdict

不是：

- communication headline
- appendix-only optional note
- overall superiority closure surrogate

当前正式允许写入 final report 的内容只有：

1. `runtime replay effect established`
2. `exact-replay-backed effect established`

当前正式不允许写入的内容：

1. `memory superiority established`
2. `overall superiority established`
3. `memory line can backfill communication headline`

如果未来要把 memory 从 required secondary verdict 再升格，缺的证据要分三类单独补：

1. net savings evidence
2. stability evidence
3. safety evidence

### Phase 9.3：typed-state final role decision

typed-state 这条赛题轴当前最终角色固定为：

- final report 里的 required secondary state-transfer verdict

不是：

- current active communication headline
- appendix-like architecture note
- memory line 的附属说明

当前正式允许写入 final report 的内容只有：

1. `non-text state-transfer mechanism established`
2. `minimal typed packet is genuinely produced, transferred, received, and consumed`
3. `missing/wrong decision packet causes expected failure or misfire`

当前正式不允许写入的内容：

1. `typed-state line already proves communication superiority`
2. `typed-state line can replace communication closure`
3. `typed-state mechanism alone proves overall contest closure`

当前 primary evidence 固定读取：

- `runs/typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623/*`
- `runs/typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623/*`

如果未来要把 typed-state 从 required secondary state-transfer verdict 再升格，缺的不是更多 mechanism narration，而是：

1. score-facing convergence wording
2. delivery-phase carry-through evidence
3. 与 communication / memory 的 final-report stitching contract

## Phase 10：openEuler posterior validation

openEuler 轴当前不是 benchmark 主线，但它是赛题交付的硬约束：

- 最终代码需在 `openEuler 24.03-LTS-SP3` 上编译、运行、测试

因此它必须被明确放进最终程序，而不是继续停留在“以后再说”。

固定顺序：

1. 先完成 current Linux host 下的 evidence closure
2. 再进入 openEuler posterior validation
3. openEuler 验证通过后，才允许把 final delivery wording 写成“交付 ready”

openEuler 这一阶段至少要覆盖：

1. 环境建立
2. 基础可运行性
   - `pytest`
   - `runtime.smoke`
   - 至少一条 current benchmark runnable path
3. benchmark 复现边界
4. 文档与部署面

这一阶段仍不重开 Docker / nsjail / VM 路线争论；openEuler 只按 posterior delivery validation 读取。

---

## 8. 当前最推荐的提交顺序

1. `docs-sync`
   - 内容：
     - authoritative artifact 更新
     - 当前固定判断更新
     - headline / support 分层实验程序更新
     - 旧停线口径删除

2. `typed-state-support-refresh`
   - 内容：
     - 先 `typed_state_consumer_sensitivity_v3`
     - 再 `typed_state_mechanism_v3`
     - 视需要补 `typed_state_authenticity_v3`

3. `comm-closure-audit`
   - 内容：
     - 基于现有 communication `repeat=1 / repeat=3`
     - 做 row-level / phase-level 审计
     - 不新增 rerun，除非 communication contract 有新改动

4. `comm-rerun-if-needed`
   - 内容：
     - 仅在 communication contract 有新变化时
     - 先 `repeat=1`
     - 再决定是否升 `repeat=3`

5. `final-evidence-program`
   - 内容：
     - 定义 final claim boundary
     - 定义 repeat=`10` 进入条件
     - 定义 openEuler posterior validation 程序
     - 明确 memory 与 typed-state 的 final-report role 是否保持 secondary 或需要升级 read

6. `memory-followup`
   - 内容：
     - 只在 final evidence program 允许其升格时再继续

7. `repeat10-if-authorized`
   - 内容：
     - 仅在 transition contract 满足后
     - 跑 serialized repeat=`10`
     - 不承担未冻结 hotfix 的消化责任

8. `openeuler-posterior-validation`
   - 内容：
     - benchmark closure 后进入
     - 只读 final delivery compatibility

---

## 9. 当前明确不做的事

1. 不把新 `repeat=3` 正向信号直接写成 formal closure
2. 不回退到 `field trim` / summarizer micro-tune 当主线
3. 不把 memory line 升级成 overall superiority
4. 不遗漏 typed-state 这条赛题轴
5. 不把 `cross_lane_actual_parity` 混成 headline 主证据
6. 不碰 VM / openEuler / Docker / nsjail
7. 不进入 `repeat=10`
8. 不在没有新 communication contract 代码变更时重复跑同一个 headline 包
9. 不先做 external pure-text baseline / text helper ablation / route-corpus stress / LangGraph-open comparison
10. 不把 `admissible_match_rate` 当 superiority 结论
11. 不把 current split evidence 直接拼接成 final delivery claim，而不经过 final evidence program
12. 不把 openEuler 交付要求继续无限后置

---

## 10. 一句话执行路线

先把实验程序拆成 `headline`、`support`、`audit`、`delivery` 四层：
communication headline 先做 closure audit；
typed-state 与 memory 继续保持 formal-secondary / support 分层；
然后补 final evidence program，定义 repeat=`10` 与 openEuler 的进入条件；
在这些条件冻结前，不做更高 repeat，不做交付级 claim。

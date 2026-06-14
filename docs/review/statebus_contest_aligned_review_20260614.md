# StateBus Contest-Aligned Review Report

日期：`2026-06-14`

定位：这份报告按赛题原文重新审计当前 StateBus 主线，不只看代码是否能跑，而是看当前 benchmark、方法设计、公开口径是否能支撑答辩中的三类主张：低开销通信、非文本状态传递、共享记忆复用。

## 0. Executive Summary

当前项目方向是对的：`StateBus = 结构化控制面 + StateRef 数据面 + 共享记忆/replay 面`，这个对象正好对齐赛题要求的系统层机制。多 Agent、结构化协议、状态池、SQLite/FAISS 记忆、LangGraph 编排入口都已经存在，不是空设计。

但当前不能把结果读成“StateBus 全面优于 text”。主要问题不是实现没有东西，而是 benchmark 和报告还没有把这些对象拆干净：

- `text_whole_lane` 已经比旧 text baseline 干净很多，executor/summarizer typed input 被 guard 限制；但它仍复用同一套 retriever feature construction、memory assist 判断、tool registry 和 playbook execution，所以它不是一个完全外部的“传统纯文本多 Agent 系统”。
- `memory_dual_mode_fairness_v3` 目前更像 restore/object-fairness surface，不足以证明共享记忆复用效率；expected replay 未命中时必须 hard withheld。
- `state_packet_minimal` 和 `text_whole_lane` 同时改变了 mode、memory policy、restore object class，不能干净归因到 memory policy。
- LangGraph 现在是固定四节点编排底座，不是当前创新核心；它可以提高工程完整性，但不应被包装成赛题主要贡献或 formal baseline。
- 公开文档仍有旧对象名、旧 pack 数量和旧 state-transfer wording，会直接影响评审理解。

结论：当前最稳的答辩口径是“系统机制主链路已经成立，formal benchmark 需要继续按 claim 分层收口”。现在可以 claim 通信/状态/记忆三面机制存在；不能 claim memory fairness 已证明 StateBus 更优，也不能 claim text baseline 已是完全独立的传统纯文本系统。

## 1. Contest Requirement Mapping

赛题的核心不是做一个普通工作流，而是验证三类系统机制：

| 赛题要求 | 当前对象 | 当前判断 |
| --- | --- | --- |
| 至少 3 个 Agent，覆盖规划/检索/执行/总结 | `Planner / Retriever / Executor / Summarizer` | 基本满足 |
| 结构化通信替代自然语言长文本 | protocol message、capability/schema、StateRefLite wire metrics | 机制成立，formal 对比仍要按 pack 解读 |
| 两种协作模式，同任务可复现实验 | `text` / `protocol` modes, v3 packs | 有入口，但 text baseline 定义还需更清晰 |
| 非文本中间状态传递 | `StateRef`, `DENSE_EVIDENCE`, `FEATURE_BUNDLE`, `EXECUTOR_DECISION_PACKET`, mmap/shared_memory | 机制成立，真实消费需继续用 authenticity/sensitivity test 证明 |
| 共享记忆存储、检索、复用 | SQLite + FAISS + assist/replay gates | 存储检索成立；复用减少重复工作只应由非零 replay/skip 证明 |
| 至少 2 组关联连续任务 | v3 packs 多 family/memory chain | 任务数足够，但不同 pack 的 claim 不能混读 |
| 展示 token/字符、状态次数/规模、耗时、记忆命中率、整体提升 | eval metrics/report | 指标体系存在；headline gate 还不够严格 |
| 稳定执行不少于 10 轮 | runner 支持 repeat，历史有证据 | 当前 active v3 surface 仍需专门 repeat gate |

关键审计结论：赛题允许 API LLM、允许本地 embedding、鼓励 IPC/shared memory/socket/vector DB；所以 StateBus 的系统对象是合题的。风险在证据层，不在选题方向。

## 2. What Is Correct Innovation

当前真正有价值的创新不是“用了 LangGraph”，也不是“把文本换成 JSON”。可辩护的创新线是：

- `控制面`：Agent 间动作、参数、结果、能力描述用结构化协议和 schema 管控，而不是长自然语言自由传递。
- `数据面`：重状态通过 `StateRef` 指向 mmap/shared_memory/CAS-like blob，不把大证据或中间状态内联到消息里。
- `状态对象`：`FEATURE_BUNDLE`、`RANKED_EVIDENCE_BUNDLE`、`TOOL_CANDIDATE_SET`、`EXECUTOR_DECISION_PACKET`、`REPLAY_ELIGIBILITY_BUNDLE` 这些对象让“中间表示”有结构和生命周期。
- `记忆面`：Memory commit 按 task theme、summary、tags、evidence refs、replay class 写入 SQLite/FAISS，并在后续任务中通过 assist 或 replay gate 使用。
- `运行证据`：runner 收集 control bytes、state bytes、handoff wire/payload、message count、LLM tokens、memory hit、skipped steps、reuse gain。

这些都服务于赛题要求，方向正确。当前要避免的错误表述是：

- 不要说“我们传了 LLM hidden state/KV cache”。当前没有同构 self-hosted LLM hidden-state backend。
- 不要说“StateBus 就是 LangGraph 的增强”。LangGraph 是编排 substrate，StateBus 的贡献在协议、StateRef、memory/replay contract。
- 不要说“text baseline 是完全传统纯文本多 Agent 系统”。当前 text lane 仍在同一 runtime/tool/retrieval 框架内运行。

## 3. Text Baseline Audit

### 3.1 当前已经修好的部分

`text_whole_lane` 现在比早期 text baseline 更接近纯文本协作：

- runtime profile 明确把 `text_whole_lane` 限定在 `mode=text`，protocol 模式不能使用。
- executor input contract 对 `text_whole_lane` 是空 sources，避免 executor 直接消费 typed state refs。
- summarizer 在 `text_whole_lane` 下只接收 executor 的 `TOOL_ARTIFACT` 文本。
- runner 的 whole-lane text guard 会检查 executor/summarizer input kinds、hidden field leak、missing handoff text。
- replay restore allowlist 对 text 只允许 execute 侧恢复 `TOOL_ARTIFACT`，不允许恢复 `FEATURE_BUNDLE / CHANNEL_SNAPSHOT / REPLAY_ELIGIBILITY_BUNDLE / EXECUTOR_DECISION_PACKET / EMBEDDING` 等 typed objects。

这些说明“text 在 agent 边界上不直接吃 StateRef typed object”这个目标已经有代码保护。

### 3.2 仍然不清晰的部分

当前 text baseline 仍不等价于“完全独立的传统纯文本多 Agent 系统”：

- Retriever 在所有策略下都会先构造 `feature_bundle`、`ranked_evidence_bundle`、`tool_candidate_set`、`replay_eligibility_bundle` 这些内部对象，再按策略决定哪些对象变成 StateRef，哪些只转成文本。
- `text_whole_lane` 的 executor 虽然不拿 StateRef，但仍通过 `_feature_bundle_from_natural_handoff(...)` 从 text handoff 中重建 route/tool feature，然后走同一个 tool registry 和 playbook runner。
- memory assist 在 retriever 阶段仍可参与 route agreement 判断，text lane 不是没有 memory/run-time machinery 的外部 baseline。
- text 的 route/tool 结果来自同一套 corpus hints、feature extraction、default tool registry，不是自然语言 agent 自己开放推理出来的。

这不是实现 bug。它是 benchmark 定义问题：当前 text 可以被定义成“StateBus runtime 内的 whole-lane natural-language carrier baseline”，但不能被定义成“传统纯文本多 Agent 框架 baseline”。如果报告把它写成后者，评审会认为 text 借用了 StateBus 的检索、工具、记忆和 runtime 语义。

更具体地说，当前 text side 借用的不是“同一个消息格式”，而是“同一套方法路径”：

- `agents/sample_agents.py` 在 text 路径下仍先做 feature extraction、tool candidate ranking、replay eligibility 计算和 memory assist 判断。
- `runtime/executor_runtime.py` 的 `text_whole_lane` 会把 text handoff 重新解析成 feature bundle，再喂给同一个 tool registry 和 playbook execution。
- `eval/runner.py` 的 whole-lane guard 主要检查外显 input kind 和 hidden-field leak，挡不住内部 helper path 继续使用结构化语义。

所以 text 可能优于 StateBus 的第一层原因，不是 text 天然更强，而是当前 text baseline 仍然沿用了 StateBus 的部分方法栈，属于“被增强过的 text carrier”，不是一个干净的纯文本对照物。

### 3.3 为什么 text 可能优于 StateBus

如果结果里 text 看起来更好，不能直接说明纯文本协作更强。当前更可能有几类原因：

- benchmark 定义污染：text side 不是外部纯文本系统，而是 StateBus runtime 内被增强过的 text carrier，所以它天然会比一个真正的 plain-text baseline 更强。
- benchmark 对比轴混杂：`text` / `protocol`、memory policy、restore object class、replay contract 同时变化，无法把差异归因到单一机制。
- protocol 侧固定成本更高：`StateRef` 创建、StatePool 写读、schema 校验、decision packet 构造、channel snapshot、CAS/replay 兼容检查都是真成本，短期内会抬高 statebus 侧开销。
- replay 证据没打中：memory fairness pack 里如果 `skip_execute` / `skip_retrieve_execute` 没有实际命中，statebus 侧就只付出了 restore/check 成本，没有拿到 skip 收益。
- protocol 侧对象可能过胖：`FEATURE_BUNDLE`、`RANKED_EVIDENCE_BUNDLE`、`REPLAY_ELIGIBILITY_BUNDLE`、`CHANNEL_SNAPSHOT` 这些对象是为了真实性和审计性服务的，但如果不被消费者换成更低 token / 更少步骤，就只会变成额外负担。

因此当前应把 text 优势读成“当前实现和 benchmark 合同下，text carrier 被增强、protocol/state 路径付出额外机制成本，而 replay 收益又没有充分释放”，而不是“纯文本系统本质上优于 StateBus”。

### 3.4 根因矩阵

| 根因 | 更像 benchmark 侧还是实现侧 | 为什么会把 text 推高 | 怎么改 |
| --- | --- | --- | --- |
| text 定义不清，text carrier 复用了 StateBus 的 feature/tool/memory 路径 | benchmark 侧为主，带少量实现支撑 | text 不是纯文本，而是被增强的 carrier，天然更强 | 新增 strict pure-text formal lane，把 feature/bundle/tool/memory helper 从 formal text baseline 中剥离 |
| mode、memory policy、restore object class 同时变化 | benchmark 侧 | 无法归因，text 可能只是占了“更少状态成本”的便宜 | 拆分 benchmark：communication / state authenticity / replay proof 三层各自单变量 |
| protocol 侧状态对象和 replay gate 太重 | 实现侧为主 | statebus 付出状态创建、校验、restore 的固定成本 | 减少不必要的 restore 对象，按 pack 精简到最小可辩护对象 |
| memory replay 没真正命中 | benchmark + runtime 两侧 | statebus 只付出成本，没有拿到 skip 收益 | 加 anchor row、replay certificate、hard replay evidence gate |
| whole-lane text guard 只挡外显输入，不挡 helper path | 实现侧 | text 仍能借用方法层路径，只是形式上不消费 typed state | 把纯文本 baseline 的 helper path 也纳入 contract/测试，必要时单独拉出 external strict text pack |

这张表的结论是：当前“text 可能优于 StateBus”主要不是单点 bug，而是 benchmark 定义和方法边界没有对齐赛题要求。实现侧有成本，但最大的问题仍然是比较对象没定义干净。

## 4. Memory Fairness and Replay Audit

`memory_dual_mode_fairness_v3` 是当前最高风险 surface。

### 4.1 现象

YAML 中有 `expected_reuse_mode: skip_execute` 和 `skip_retrieve_execute`，但实际 deterministic 结果可能只有 `none/assist`。这意味着该 pack 当前不能证明共享记忆带来了减少重复工作的复用收益。

### 4.2 机制原因

runtime replay gate 是严格的：

- `skip_execute` 要求 route、query overlap、doc ids、fresh evidence sha、route confidence/provenance、replay blob hash 等匹配。
- `skip_retrieve_execute` 要求 task theme、exact normalized query、replay class、evidence sha、channel snapshot hash、replay blob hash 等成立。

严格 gate 本身是合理的，因为 replay 不能靠 benchmark label 伪造。但当前 memory commit 和 restore contract 没闭合：

- text lane 的 memory commit 为了公平性收窄 refs，只保留 summary/artifact，导致 replay gate 需要的 replay proof bundle/hash 不可用。
- protocol minimal exact replay 要恢复 `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET + TOOL_ARTIFACT`，但 replay memory 是否稳定保存 `EXECUTOR_DECISION_PACKET` 仍需补齐。
- runner 把 `expected_reuse_mode` 写成 benchmark validation，但没有把 expected replay mismatch 作为 formal memory headline 的硬失败。

### 4.3 Benchmark 原因

`memory_dual_mode_fairness_v3` 同时变化：

- mode：`text` vs `protocol`
- memory policy：`reuse_disabled / assist_allowed / validated_replay / exact_replay`
- restore object class：text compatible vs minimal typed packet

这不是单变量实验。它可以作为“dual-mode memory fairness surface”，但不能单独证明“memory policy 造成效率提升”。

### 4.4 修复方向

不要放宽 replay gate。应补齐证据链：

- 增加 mode-compatible replay certificate：text lane 可保存 route/doc/query/evidence/provenance/hash 作为不可恢复 typed state 的 replay proof；runtime gate 可以读取 certificate，但 text restore 仍只允许 `TOOL_ARTIFACT`。
- protocol minimal replay memory commit 必须包含 `EXECUTOR_DECISION_PACKET`，否则 exact replay 缺少最小 typed packet。
- 为每个 family/mode 设计明确 anchor rows：cold row 生成 replay memory，validated row 必须命中 `skip_execute`，exact row 必须命中 `skip_retrieve_execute`。
- runner 增加 `memory_replay_evidence_gate`：expected replay row 未命中时，headline 必须 withheld，理由应是 `memory_replay_expectation_failed`。
- 报告中区分 `memory_dual_mode_fairness_v3` 和 `memory_reuse_v3`：前者证明双模式公平边界，后者证明 protocol-only replay 机制。

## 5. State Transfer Authenticity Audit

状态传递创新是当前最值得保留的主线，但要用正确对象证明。

当前 `state_ref` / `state_packet_minimal` 已经真实生产非文本对象并进入 StatePool。问题在于“存在”和“被有效消费”不是一回事：

- `protocol_feature_only_typed_state` 主要看 `DENSE_EVIDENCE + FEATURE_BUNDLE` 是否被 executor 消费。
- `state_packet_minimal` 主要看 `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` 是否构成最小可执行 typed packet。
- `protocol_full_rich_audit` 可以检查 channel snapshot、tool candidate、ranked evidence、replay eligibility 等 rich objects，但不能读成 production formal headline。

当前应保留三层读法：

- formal communication：`contest_dual_mode_controlled_v3`，只回答 text whole lane vs state packet minimal 的控制面/模式差异。
- formal secondary authenticity：`typed_state_authenticity_v3`，只回答 protocol natural handoff text vs state_ref 是否真实生产、传递、消费。
- audit only：`typed_state_full_rich_audit_v3`、`carrier_microbench_v3`，只做机制和工程成本解释。

必须补的不是更多对象，而是 consumer sensitivity：

- 关闭 `FEATURE_BUNDLE` 后 route/tool/correctness 是否变差。
- 关闭 `EXECUTOR_DECISION_PACKET` 后 state_packet_minimal 是否失败。
- 关闭 `TOOL_CANDIDATE_SET / CHANNEL_SNAPSHOT / RANKED_EVIDENCE_BUNDLE` 后是否只影响 audit，而不是 formal headline。
- summarizer 在 `actions_plus_evidence` contract 下不能使用 protocol rich handoff shortcut。

## 6. LangGraph Audit

当前 LangGraph 接入是工程上有价值的，但深度仍是“固定编排底座”，不是完整替代 StateBus 语义层：

- `StateBusGraphRunner` 构建固定四节点图：planner -> retriever -> executor -> summarizer。
- 每个 node 内仍调用 `Orchestrator` 的 plan compile、replay gate、step invocation、schema validation、result registration、StatePool/MemoryStore side effects。
- LangGraph graph state 主要保存 `ctx/results/state_refs/memory_hits/metrics` 快照。
- benchmark runner 已经 langgraph-only，这是工程统一入口，但不意味着 LangGraph 成为创新对象。

这条路线可以保留，但报告要降调：

- 可以说：我们用 LangGraph 固定图承载多 Agent orchestration，保证执行轨迹可观测。
- 不应说：LangGraph 本身提供了 StateBus 的低开销通信、非文本状态传递或共享记忆复用。
- 不应把 LangGraph vs non-LangGraph 做 formal headline，因为赛题评分轴不是编排框架优劣。

LangGraph 下一步如果要“深入”，应服务于 StateBus 机制，而不是另起 baseline：

- 把 graph state 的 channel/reducer 映射成 StateBus channel store 的可审计语义。
- 把 replay gate decision 写入 graph state，形成可解释的 execution trace。
- 把 TaskCommit / ExecutionDAG / channel snapshot 作为 durable graph checkpoint，而不是只在 ctx 里封装。

## 7. Public Wording and Report Risk

当前公开口径仍有明显 drift：

- `README.md` 写 “6 个 v3 pack”，但实际列了 8 个。
- `README.md` 写 `contest_dual_mode_controlled_v3` 是“唯一正式双模式 headline”，但现在还有 `memory_dual_mode_fairness_v3`。
- `MASTER_PRESENTATION_GUIDE.md` 仍把 state_transfer 写成 `text_brief -> state_ref`，而 active authenticity pack 已经是 `natural_handoff_text vs state_ref`。
- `task_design_and_mode_comparison.md` 写 7 个 v3 对象，但表格有 8 个。
- `tasks/README.md` 仍有 `feature-only mainline typed state` wording，与当前 `natural_handoff_text vs state_ref` 和 `state_packet_minimal` 公开读法混在一起。

这些不是小 typo。它们会让评审无法判断你到底测的是：

- whole-lane text vs protocol minimal packet
- protocol natural handoff text vs state_ref
- text packet vs state packet carrier microbench
- memory fairness vs protocol-only replay proof

公开材料必须按 pack 分层，不要用一张总表把所有结论合并成“StateBus 优于 text”。

## 8. Prioritized Findings

### High

1. `memory_dual_mode_fairness_v3` 目前不能证明 memory reuse efficiency。
   - 根因：YAML expectation、memory commit refs、runtime replay gate、report gate 没闭合。
   - 处理：补 replay certificate、protocol minimal decision packet commit、anchor rows、hard replay evidence gate。

2. text baseline 定义仍不够干净。
   - 根因：text lane 在 agent 边界上是文本，但内部仍复用 StateBus retriever feature construction、memory assist、tool registry、playbook execution。
   - 处理：公开定义为 “StateBus runtime 内 whole-lane text carrier baseline”；另建 `external_pure_text_baseline` 或 `strict_natural_text_baseline` 才能代表传统纯文本系统。

3. benchmark 变量缠绕导致归因不成立。
   - 根因：mode、memory policy、restore object class 同时变化。
   - 处理：拆成三类 pack：communication headline、state authenticity secondary、memory replay proof；memory fairness 只读 fairness，不读 policy 因果。

4. active docs/report 口径不一致。
   - 根因：v2/v3、text_brief/natural_handoff_text、feature-only/state_packet_minimal 多轮切换后没有统一入口。
   - 处理：修 README、tasks README、MASTER_PRESENTATION_GUIDE、task design overview。

### Medium

5. LangGraph 深度容易被过度宣称。
   - 当前是固定图 + Orchestrator semantic core。
   - 处理：把 LangGraph 放在 system completeness/orchestration substrate，不放在 formal headline。

6. typed-state authenticity 还需要 consumer sensitivity。
   - 当前对象存在不等于消费者依赖。
   - 处理：逐类关闭 state kinds，看 executor/summarizer 和 route/tool/correctness 是否变化。

7. report gate 没有把 expected replay mismatch 变成 stopline。
   - 处理：新增 `memory_replay_evidence_gate` 和 report reason。

### Low

8. historical docs 较多，容易被误读。
   - 处理：active docs 直接链接的历史文档加 historical snapshot 标记；不必全仓库重写。

## 9. Concrete Remediation Plan

### Phase 1: Stopline and wording first

- 修 active docs：README pack 数量、formal headline 口径、MASTER_PRESENTATION_GUIDE 的 state_transfer wording、task_design pack 数量。
- report 中明确：`memory_dual_mode_fairness_v3` 不等于 memory reuse proof；`memory_reuse_v3` 才是 protocol replay proof。
- runner 对 memory fairness 增加 `memory_replay_evidence_gate`，expected replay 未命中时 headline withheld。

### Phase 2: Text baseline contract

- 在 task/report contract 中把 `text_whole_lane` 定义成 “whole-lane natural-language carrier inside StateBus runtime”。
- 新增 strict baseline pack：
  - 不生成 feature bundle 给 text route 决策。
  - 不使用 memory prior route agreement。
  - 不暴露 route/tool structured fields。
  - 只允许 corpus evidence natural text + natural-language executor parse。
- 保留当前 `text_whole_lane` 作为 fair carrier baseline，不再把它说成 external pure text baseline。

### Phase 3: Memory replay closure

- text replay memory 写入不可恢复的 replay certificate metadata。
- protocol minimal replay memory 写入 `EXECUTOR_DECISION_PACKET`。
- replay gate 从 certificate/metadata 读取 proof，但 restore allowlist 继续按 mode 限制。
- 每个 family 至少保证一条 text validated replay、一条 text exact replay、一条 protocol validated replay、一条 protocol exact replay。

### Phase 4: State authenticity and LangGraph support

- typed authenticity pack 加 row-level object alignment test。
- consumer sensitivity audit 固化到 tests。
- LangGraph 只做 support evidence：graph state 必须包含 replay decision、state refs、channel snapshot、TaskCommit hash。

## 10. Test Plan

必须新增或收紧：

- `memory_dual_mode_fairness_v3` deterministic run：text/protocol 各至少一个 `skip_execute` 和 `skip_retrieve_execute`。
- replay visibility test：text restored kinds 只能是 `TOOL_ARTIFACT`；protocol minimal exact restored kinds 必须是 `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET + TOOL_ARTIFACT`。
- memory replay evidence gate synthetic fail：expected skip 未命中时 withheld reason 必须含 `memory_replay_expectation_failed`。
- text baseline contamination audit：`text_whole_lane` executor/summarizer input refs 为空或只含允许文本 artifact，同时报告标明它仍复用 StateBus runtime。
- strict external pure text pack test：不生成/不消费 feature bundle route shortcut。
- typed_state_authenticity row-level test：`natural_handoff_text` vs `state_ref` pair 对齐，state_ref executor input kinds 精确符合合同。
- LangGraph support test：graph state 与 ctx state refs、metrics、replay decision 一致，但不把 LangGraph 作为 formal benchmark axis。
- docs smoke：active docs 不出现旧 `text_brief -> state_ref` formal headline，不出现 pack count drift。

## 11. What Can Be Claimed Now

可以说：

- StateBus 的系统设计方向符合赛题：多 Agent、结构化协议、StateRef 非文本状态、共享记忆、评测模块都已有实现。
- protocol/control-plane 降低通信开销这条可以作为当前最稳 headline，但必须绑定具体 pack 和 gate。
- typed-state/statepool 机制存在，且有真实性审计 pack；是否成为正式效率结论取决于 consumer sensitivity。
- LangGraph 已作为固定编排入口接入，提升工程完整性和可观测性。

必须 withheld：

- `memory_dual_mode_fairness_v3` 已证明记忆复用效率更好。
- StateBus 总体优于 text。
- text baseline 是完全传统纯文本系统。
- LangGraph 是主要创新点。
- rich typed-state 一定比 natural text 更优。

## 12. Recommended Final Framing

推荐答辩主线：

> StateBus 针对赛题的三个痛点拆成三层：结构化控制面降低消息开销，StateRef 数据面承载非文本中间状态，共享记忆面通过 assist/replay 支持跨任务复用。当前实现已经把三层机制跑通，并用 v3 packs 分别验证。我们不把所有 pack 聚合成“全面胜利”，而是按通信、状态真实性、记忆复用三个 claim 分别给证据和 stopline。

这比宣称“StateBus 全面优于 text”更稳。评审追问 fairness 时，应主动说明：

- 当前 `text_whole_lane` 是 StateBus runtime 内的 natural-language carrier baseline，不是外部纯文本系统。
- memory fairness headline 只有在 replay evidence gate 通过后才释放。
- protocol side 的额外开销来自状态对象、schema、restore 和 replay gate；只有 replay/consumer proof 命中时才应 claim 收益。

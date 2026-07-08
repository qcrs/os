# StateBus Final Claim Matrix and Headline Freeze

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

本文档是 2026-06-18 之后报告、答辩、后续窗口读取 current formal headline 时的主入口。它的作用不是新增 benchmark 结论，而是冻结已经闭合的主线证据，明确能说什么、不能说什么，以及哪些旧 Goal2 结论已经被 Goal3 证据 superseded。

## 1. Current Formal Headline Freeze

当前冻结的正式主对象：

- task set: `contest_honest_headline_v1`
- public surface: `formal_headline`
- variable axis: `mode`
- text object: `text_whole_lane`
- protocol object: `state_packet_minimal`
- primary artifact: `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`
- deterministic support artifact: `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/`

Freeze rule:

- `contest_honest_headline_v1` 不再随便改。
- 后续如果修改 task contract、runtime gate、text/protocol object、memory policy、S1/S2 语义，必须视为新对象或新 audit surface，不能继续沿用当前 frozen headline 结论。
- 如果确实需要 thaw 当前 headline，必须先写 thaw/requalification doc，并重新跑完整 gate；旧 artifact 只能保留为历史证据。
- 当前允许继续改的是报告、索引、claim wording、audit plan；不允许用这些报告改动反向扩大 benchmark 结论。

## 2. Frozen Evidence Snapshot

最新 API repeat=10 artifact 的当前读法：

| 项 | 当前值 | 解释 |
| --- | ---: | --- |
| repeat | 10 | 满足 current host-side formal repeat gate |
| `withheld_headline_reason` | empty | current headline 不再因 repeat 不足 withheld |
| `formal_stability_gate.passed` | true | text/protocol 两侧 repeat=10 都通过 |
| `object_parity_gate.passed` | true | 当前 paired object parity 通过 |
| `contest_formal_coverage_gate.passed` | true | 20 matched pairs、5 families、4 complexity buckets |
| text control bytes mean | `223741.2` | API repeat=10 mode check |
| protocol control bytes mean | `192935.2` | protocol control compactness evidence |
| text task ms mean | `70684.29` | 不能单独读成 protocol latency win |
| protocol task ms mean | `68850.85` | 当前 API run protocol 略低，但主 claim 仍限于 control compactness |
| text LLM total tokens | `8435.9` | 不构成大 token win 叙事 |
| protocol LLM total tokens | `8430.9` | 只可谨慎说明基本持平 |
| protocol state transfer count mean | `50` | 非文本 state transfer 在 protocol side 真实发生 |
| text state transfer count mean | `0` | text side 不消费 typed state refs |
| S1 changed action count | `120` | S1 不再只是静态字段 |
| S2 prior action changes | `100` | S2 prior-dependent admissible action 已进入 runtime |
| memory replay rows | `100` | current-headline S2 replay effect 已存在 |
| skipped steps | `100` | current-headline memory/replay effect 有 runtime 省步骤证据 |

这些数字支撑的是受控 contest object 下的机制结论，不支撑开放世界泛化结论。

## 3. Superseded Goal2 Statements

以下 Goal2 文档仍保留为历史审计材料，但其中关于 current headline 的若干状态已经被 Goal3 artifacts superseded：

- `docs/analysis/statebus_review_requirement_map_20260618.md`
- `docs/analysis/statebus_review_benchmark_and_task_audit_20260618.md`
- `docs/analysis/statebus_review_runtime_and_authenticity_20260618.md`
- `docs/analysis/statebus_review_external_alignment_and_rebuild_20260618.md`
- `docs/analysis/statebus_review_reading_and_search_log_20260618.md`

不要再把以下旧判断当 current blocker：

- current headline 仍然只有 repeat=1 或 repeat=3；
- current headline 仍因 `contest_repeat_insufficient` withheld；
- current headline 仍是 fresh-retrieval-only；
- current headline 没有 memory/replay effect；
- S2 仍只是静态 prior 字段；
- repeat=10 formal stability 未闭合。

仍然有效的 Goal2 贡献：

- 赛题要求要从 structured communication、non-text state transfer、memory reuse 三条线拆读；
- support surface 不能冒充 headline；
- text baseline、LangGraph、Planner、memory claim 不能混读；
- benchmark 必须 single-variable、object-pure、artifact-visible；
- openEuler/Docker/nsjail/hidden-state/KV 不属于当前 host-mainline 已完成项。

## 4. Claim Matrix

| 赛题/系统要求 | 当前证据 | 可以说 | 不能说 | 边界 |
| --- | --- | --- | --- | --- |
| 多 Agent 角色 | Planner/Retriever/Executor/Summarizer 均在 runtime 中运行 | StateBus 是四角色 host-side multi-agent runtime | Planner 已证明开放自主规划能力 | Planner 在 frozen headline 中主要是 task contract compiler |
| 低开销结构化通信 | API repeat=10 protocol control bytes mean `192935.2` vs text `223741.2` | protocol side 在受控 paired object 中稳定降低控制面字节 | StateBus 在所有 token/latency/correctness 维度全面优于 text | 主 claim 是 control compactness，不是 end-to-end 全面胜利 |
| 非文本中间状态传递 | protocol state transfer count mean `50`；executor input includes `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET + VALIDATION_GATE_PACKET` | StateBus 传递并消费 feature/packet/StateRef 级非文本中间态 | hidden-state/KV/activation transfer 已实现 | 当前是 typed packet / StateRef，不是模型内部隐状态 |
| 共享记忆复用 | current headline S2 replay rows `100`，skipped steps `100`，memory gate ready | current-headline controlled S2 validated replay 能减少重复执行步骤 | 广义长期记忆 agent 已成立 | 只证明受控 prior-dependent replay，不证明开放长期记忆 |
| 连续关联任务 | 5 families、4 complexity buckets、20 matched pairs | release-regression family 下有关联连续任务 object | open-world connected multihop benchmark 已成立 | 任务仍是 route/corpus/playbook shaped |
| 实验指标 | message count、control bytes、state transfer、task ms、tokens、reuse/skipped-step gates 均在 artifact 中 | 可以分层报告通信、状态、replay、稳定性指标 | 可以汇总成单一“overall better”结论 | 每个指标只在对应 claim lane 中解释 |
| 不少于 10 轮稳定执行 | API repeat=10 与 deterministic repeat=10 均闭合 | current host-side formal headline repeat=10 已通过 | openEuler final validation 已完成 | 当前不是 VM/Docker/nsjail 交付验证 |
| 工程部署 | host env 可运行，StateRef/mmap/SQLite/FAISS 等路径存在 | host-side prototype 可运行并可复现 benchmark | openEuler/Docker/nsjail/strong sandbox 已交付 | 这些是后验验证或明确不做范围 |

## 5. Claim Layers

### Mainline

主线只讲：

> StateBus 在受控 paired contest task object 中，用 structured control + typed-state handoff 替代 whole-lane text handoff，稳定降低控制面通信开销，并证明 S1/S2/replay runtime behavior。

对应对象：

- `contest_honest_headline_v1`
- API repeat=10 primary artifact
- deterministic repeat=10 support artifact

### Secondary

次级机制可讲，但不能抢主线：

- controlled S2 replay / memory effect；
- typed-state consumer sensitivity；
- planner support；
- memory policy controlled attribution；
- statepool backend and StateRef implementation.

### Support

支撑层只说明系统完整性：

- Planner role 存在；
- LangGraph 是真实 execution substrate；
- UDS/subprocess/tool registry 是工程实现；
- SQLite + FAISS memory store 存在；
- mmap/shared_memory 是 StatePool backend 选项。

### Audit

审计层只能影响 future claim strength，不能反向污染 frozen headline：

- external pure-text baseline；
- text helper ablation；
- route/corpus stress；
- S2 negative control；
- planner-open secondary；
- LangGraph-native/open comparison.

## 6. Can Say / Cannot Say

可以说：

- current headline 是 `text_whole_lane` vs `state_packet_minimal` 的内部 paired contest comparison；
- protocol side 在 repeat=10 API 中有稳定 control-byte compactness；
- protocol side 真实生产、传递、消费 typed state packet；
- S1/S2 runtime gates 已从静态 contract 推进到真实行为；
- current headline 已包含 controlled S2 validated replay effect；
- LangGraph 被真实用作 host-side graph execution substrate；
- Planner role 满足系统完整性和 plan contract 组织。

不能说：

- StateBus 已经全面优于 external traditional pure-text multi-agent systems；
- `text_whole_lane` 就是 external pure-text baseline；
- current headline 证明 open-world agent benchmark；
- LangGraph 是 StateBus 的核心创新；
- Planner 已证明开放 adaptive planning；
- memory/replay 证明广义长期记忆 agent；
- StateBus 实现了 hidden-state/KV transfer；
- openEuler/Docker/nsjail/strong sandbox 已完成；
- protocol control bytes win 等于所有 token/latency/任务成功维度全面 win。

## 7. Report Usage

后续报告与答辩优先引用本文档作为 current claim source。

旧文档使用规则：

- 引用 Goal2 文档时，必须说明它反映的是 Goal3 前的审计状态；
- 引用 deep critical review 文档时，优先读取它的 claim narrowing 与边界，而不是把它读成 current headline 失败；
- 引用 older v3 reports 时，必须确认是否已被 API repeat=10 frozen headline 更新。


# StateBus 外部 Benchmark 调研与映射

日期：`2026-06-18`

定位：

- 保存这轮重新做的外部 benchmark 调研，避免后续继续靠回忆讨论。
- 只回答一件事：`StateBus` 当前 headline benchmark 厚化，应该借哪些外部 benchmark 的设计原则，哪些不能直接照搬。

结论先说：

- 目前**没有一个外部 benchmark 可以直接拿来当 StateBus contest headline 数据集**。
- 但已经有一组外部 benchmark 很适合给当前 `contest_honest_headline_v1` 的下一轮厚化提供设计约束。
- 当前最有价值的不是“直接换数据集”，而是把这些 benchmark 的**构题方式、验证方式、对照方式、日志方式**借进来。

---

## 1. 当前仓库是否已经落实外部参考

截至本文件落盘前：

- 仓库文档里已经零散提到 `HotpotQA`、`MuSiQue`、`BRIGHT`、`LongMemEval`、`SWE-bench`、`WebArena`、`BenchAgent`
- 但这些参考**没有被收成一份稳定的调研与映射文档**
- 也**没有形成一份“当前 headline 厚化到底借什么、不借什么”的执行合同**

这份文档就是补这个空缺。

---

## 2. 外部参考总表

| 来源 | 主要回答什么 | 当前最该借什么 | 当前不该直接照搬什么 |
| --- | --- | --- | --- |
| [HotpotQA](https://arxiv.org/abs/1809.09600) | 多文档多跳问答、supporting facts、distractor setting | supporting facts、distractor 注入、comparison case | 直接拿 QA 数据当 StateBus task |
| [MuSiQue](https://arxiv.org/abs/2108.00573) | connected multihop、反 shortcut | connected hop 构题、2-4 hop、unanswerable contrast | 只保留问答输出而不做 route/tool/action contract |
| [BRIGHT](https://arxiv.org/abs/2407.12883) | reasoning-intensive retrieval | 让检索前必须先理解问题，不靠词面命中 | 直接把 BRIGHT query 当 triage/action task |
| [LongMemEval](https://arxiv.org/abs/2410.10813) | 长时记忆能力分层：indexing/retrieval/reading | memory 能力拆层、abstention、time-aware retrieval | 直接把 chat memory benchmark 当 replay benchmark |
| [LongMemEval-V2](https://arxiv.org/abs/2605.12493) | agent environment experience memory | workflow knowledge、history-to-evidence context gathering | 直接把 web-agent history 迁成 StateBus headline |
| [BenchAgent](https://arxiv.org/abs/2606.05670) | 统一 loader / tool access / answer contract / usage accounting / trajectory logging | 统一执行协议、matched anchor、logging contract | 直接拿它的多 benchmark 平均分叙事当我们的 headline |
| [τ-bench](https://arxiv.org/abs/2406.12045) | tool-agent-user interaction 的 end-state verifier 与稳定性 | end-state verifier、`pass^k` 式可靠性视角 | 直接把对话 retail/airline 任务搬进当前 contest mainline |
| [WebArena](https://arxiv.org/abs/2307.13854) | 真实可复现长程 web agent 任务 | long-horizon、固定环境、真实任务成功率 | 当前就把 open-world web 环境引入主线 |
| [SWE-bench](https://arxiv.org/abs/2310.06770) | 真实 issue 到 patch 的执行式评测 | artifact bundle + environment-based verification | 当前就切到代码修复型主对象 |
| [AgentEscapeBench](https://arxiv.org/abs/2605.07926) | 长依赖工具推理、显式 DAG、自动验证 | dependency depth 分级、显式 DAG、难度梯度 | 直接照搬 escape-room 主题 |

---

## 3. 每个参考到底怎么借

### 3.1 HotpotQA

原文重点：

- 要求问题必须跨多个文档推理
- 提供 supporting facts
- 还有 distractor setting 与 full-wiki setting 两种难度

对 StateBus 的直接启发：

1. headline family 不该只给“能答出来”的文档集合，还要给**支持事实宇宙**
2. `distractor` 不能只是换个假文档名字，而要真能对 route/tool 形成干扰
3. 可以借它的“两档 retrieval 难度”思想，把 `current honest floor` 和 `thickened retrieval` 分开

不该直接照搬：

- HotpotQA 是 QA 数据集，不自带 `route/tool/action/replay` 合同
- 它适合借构题原则，不适合直接拿数据

### 3.2 MuSiQue

原文重点：

- 通过可组合 single-hop 构造真正 connected multihop
- 目标是避免 benchmark 被 shortcut 解掉
- 数据集显式做成 `2-4 hop`

对 StateBus 的直接启发：

1. 当前 `contest_honest_headline_v1` 需要从“受控单跳分流”升级到**connected multihop**
2. 每个 thickened case 都应满足：
   - 第二个决策必须依赖第一个决策产出的中间结果
   - 不能删掉其中一跳还保持正确
3. `ambiguous` 不能只是两条 route 都勉强合理，而应让“进一步收集/组合证据”成为真正必要步骤

这是当前最重要的厚化参考之一。

### 3.3 BRIGHT

原文重点：

- retrieval benchmark 不该只靠 lexical/semantic matching
- query 本身需要 reasoning，才能找到相关文档

对 StateBus 的直接启发：

1. 当前 retrieval 不能再让 query 一眼指向唯一 route/tool
2. thickened headline 应显式包含：
   - 要先判断 incident structure
   - 再决定该找哪类证据
   - 最后才允许 execute/summarize
3. 当前 family spec 里的 query 文本要继续去掉“答案暗示词”

### 3.4 LongMemEval 与 LongMemEval-V2

原文重点：

- `LongMemEval` 把记忆设计拆成 indexing / retrieval / reading
- `LongMemEval-V2` 把 memory 看成从长 history 中 gathering evidence，重点在 workflow knowledge 和环境经验

对 StateBus 的直接启发：

1. 记忆问题必须继续拆层，不要再把 fairness / replay / headline 混读
2. `replay_reusable` case 应该不只是“上一题答过”，而应体现：
   - prior rejection 是否保留下来
   - prior scoped action 是否保留下来
   - downstream 需要的不是全文复制，而是 compact evidence
3. 厚化后的 reusable case 应更接近 `context gathering`，而不是只是“从上题抄结论”

### 3.5 BenchAgent

原文重点：

- 在同一 normalized execution and logging protocol 下比较 single-agent 与 multi-agent
- 固定 loader、tool access、answer contract、usage accounting、trajectory logging

对 StateBus 的直接启发：

1. 任何 text/protocol 比较都必须继续共享：
   - loader
   - tool access
   - answer contract
   - usage accounting
   - trajectory logging
2. 当前 headline 厚化之后，**不能换一套 report 语义再比**
3. 若后面要比较不同厚化 setting，必须沿用同一 logging 口径

这条不是数据集参考，而是**评测 harness 纪律**参考。

### 3.6 τ-bench

原文重点：

- 用最终数据库状态做 end-state verifier
- 引入 `pass^k` 视角看稳定性和一致性

对 StateBus 的直接启发：

1. 后续厚化 case 的评分不应只看 summary 文本，还要尽量落到**可验证的最终状态/动作合同**
2. 当前 `repeat=10` 不应只被读成 timing evidence，也可以读成 reliability probe
3. 如果后面 thickened case 引入多步交互，应该保留一个“最终动作是否把系统带到正确状态”的 verifier 思路

### 3.7 WebArena

原文重点：

- 真实、可复现、长程、带外部知识的 web 环境

对 StateBus 的直接启发：

1. StateBus headline 以后如果要继续加厚，方向应是**固定环境中的长程任务**
2. 但当前阶段不应直接引入 open-world web 环境；成本和变量太大

当前结论：

- WebArena 更适合做后续环境级扩展参考
- 不适合当前这轮 contest headline 厚化主线

### 3.8 SWE-bench

原文重点：

- 真 issue、真仓库、真环境验证
- 需要跨文件理解和执行环境

对 StateBus 的直接启发：

1. 真实 artifact bundle 与环境验证值得借
2. 但当前 contest 主问题不是“修代码”，而是“structured protocol vs pure-text handoff”

当前结论：

- SWE-bench 适合借“真实 artifact + environment verification”
- 不适合作为当前 headline task 数据本体

### 3.9 AgentEscapeBench

原文重点：

- 每个任务有显式 dependency DAG
- 支持 difficulty tier
- 难度随着 dependency depth 增加而显著上升

对 StateBus 的直接启发：

1. 这是当前 headline 厚化最值得直接借的另一个对象
2. 它提醒我们：不能只说“多跳”，还要**写出 dependency depth**
3. 后续 thickened family 最好显式分 tier：
   - `depth=1` 当前 floor
   - `depth=2` connected multihop
   - `depth=3` cross-task dependency

---

## 4. 哪些参考最适合当前主线

当前最适合 `contest_honest_headline_v1` 厚化阶段的优先顺序：

1. `MuSiQue`
   - 解决“connected multihop，不要 shortcut”
2. `HotpotQA`
   - 解决“supporting facts + distractor universe”
3. `BRIGHT`
   - 解决“retrieval 必须先 reasoning”
4. `AgentEscapeBench`
   - 解决“dependency depth 与长依赖”
5. `LongMemEval-V2`
   - 解决“history to compact evidence 的 memory 合同”
6. `BenchAgent`
   - 解决“统一 loader / logging / answer contract”
7. `τ-bench`
   - 解决“稳定性 / end-state verifier”

`WebArena` 和 `SWE-bench` 当前保留为后续环境级参考，不进入本轮 headline task 设计主合同。

---

## 5. 对当前 StateBus 的具体映射

### 5.1 当前 headline 不该直接换数据集

原因：

- 赛题对象是 StateBus 协作/协议/记忆主线，不是开放世界 agent benchmark
- 当前需要的是**控制变量的 task thickening**
- 直接换外部数据集会把对象、公平性、工具合同一起打散

### 5.2 应该怎么落到本仓库

当前最合理的路线不是“导入新 benchmark”，而是：

1. 保留 `contest_honest_headline_v1` 作为唯一 headline
2. 在 `tasks/contest_family_spec.yaml` 上厚化现有 family
3. 借外部 benchmark 的构题原则，补充：
   - connected hops
   - stronger distractor universe
   - dependency depth
   - cross-task carry-over
   - explicit abstention boundary
4. 保持：
   - 同一 corpus
   - 同一 scoring
   - 同一 plan source
   - 同一 logging contract

---

## 6. 当前可执行结论

可以立刻执行的结论只有三条：

1. **外部 benchmark 参考已经落实为文档，但还没有完全落实为当前 headline 的厚化合同。**
2. **当前不该继续扩 pack 数量，而应在现有 `contest_honest_headline_v1` 上吸收这些设计原则。**
3. **下一步最该做的是把这些参考压成 StateBus 自己的厚化执行合同和方法评测准入门。**


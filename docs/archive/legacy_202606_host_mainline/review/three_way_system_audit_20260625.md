# StateBus / Internal Snapshot / Third-Party YZM 三方深度审查报告

日期：2026-06-25  
审查对象：
- 主仓库：`/home/qcrs/statebus/project`
- 内部快照：`/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz`
- 外部参考：`third_party/yzm_unzipped/`

---

## 1. 总判断

### 1.1 一页总判断

#### 事实

1. 主仓库已经不是“赛题构想”或“演示性脚手架”，而是一套真实存在的 host-side 多 Agent 系统实现，覆盖了：
   - 结构化通信协议
   - 非文本状态引用 `StateRef`
   - `mmap` / `shared_memory` 双状态池后端
   - SQLite + FAISS 共享记忆
   - assist / validated replay / exact replay 复用路径
   - fairness gate、text leak guard、role visibility control
   - benchmark、report、evidence program

   证据：
   - [README.md](/home/qcrs/statebus/project/README.md:136)
   - [docs/constraints/current_feature_scope.md](/home/qcrs/statebus/project/docs/constraints/current_feature_scope.md:17)
   - [runtime/orchestrator.py](/home/qcrs/statebus/project/runtime/orchestrator.py:922)
   - [statepool/store.py](/home/qcrs/statebus/project/statepool/store.py:85)
   - [memory/store.py](/home/qcrs/statebus/project/memory/store.py:184)

2. 当前正式主张不是“系统三条线全部闭环成立”，而是被明确拆成不同证据层级：
   - active headline：`superiority_comm_v1`
   - formal-secondary：`typed_state_mechanism_v3`、`typed_state_consumer_sensitivity_v3`、`superiority_memory_v1`
   - audit / historical：若干辅助对象

   证据：
   - [README.md](/home/qcrs/statebus/project/README.md:136)
   - [tasks/README.md](/home/qcrs/statebus/project/tasks/README.md:9)
   - [docs/reports/statebus_system_method_task_and_results_explainer.md](/home/qcrs/statebus/project/docs/reports/statebus_system_method_task_and_results_explainer.md:41)

3. 当前系统最核心的问题不是“有没有实现结构化通信、状态传递、共享记忆”，而是“哪些结论已经被正式证明、哪些还不能释放”。
   - communication headline 已经 `Communication gate = pass`
   - 但 `Formal stability gate = not_yet`
   - memory 线只足以证明 replay effect，不足以证明 overall superiority
   - typed-state 线只足以证明机制和消费者依赖，不足以证明总 headline

   证据：
   - [docs/planning/statebus_contest_superiority_gate_contract_20260621.md](/home/qcrs/statebus/project/docs/planning/statebus_contest_superiority_gate_contract_20260621.md:274)
   - [docs/reports/current_task_results_overview_20260622.md](/home/qcrs/statebus/project/docs/reports/current_task_results_overview_20260622.md:134)
   - [docs/reports/statebus_system_method_task_and_results_explainer.md](/home/qcrs/statebus/project/docs/reports/statebus_system_method_task_and_results_explainer.md:162)

4. 所谓“内部另一套实现”并不存在为一条独立技术路线。内部仓库是主仓库的同步阅读快照，不是第二个不同架构。

   证据：
   - [/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md](/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md:1)
   - [/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md](/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md:3)
   - [/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md](/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md:8)
   - [/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md](/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md:9)

5. 外部第三方参考真正的价值不是给出“可直接复用的更好实现”，而是分别提供了三类不同启发：
   - `master_4` / `master_7`：系统机制展示方式
   - `master_6`：实验合同、claim ledger、judge-facing evidence pack
   - `master_8`：教学化、可读化、可测化 skeleton

#### 推断

1. 主仓库当前路线之所以走到 `headline / support / audit / historical`，本质上是团队在主动降低 claim 过冲风险，而不是在绕弯路。
2. 你们当前最大的短板不是系统机制贫乏，而是“证据交付物尚未压缩成评委最容易审阅的形式”。
3. 如果继续优先扩机制而不是补 formal closure，最终风险会从“没做出来”转成“做出来但说不清、证不稳、边界不诚实”。

#### 建议

1. 后续工作重心应从“新机制扩展”转向“正式证据闭环和评审包装”。
2. 内部快照应明确作为“阅读快照”而非“独立实现”使用。
3. 外部最值得借鉴的是抽象原则：
   - claim 与 evidence 对齐
   - judge 与 producer 分离
   - requirement 映射为 artifact contract
   - negative control / blind control 显式化

---

## 2. 三方对比总览

### 2.1 总表

| 维度 | 主仓库 `statebus/project` | 内部快照 `/home/qcrs/yzm...` | 第三方 `third_party/yzm*` |
|---|---|---|---|
| 技术定位 | 真正主实现 | 主实现快照 | 多个不同阶段/风格的外部参考 |
| 证据定位 | 有正式 gate、support、audit | 只复述主仓库正式读法 | 强弱不一，`master_6` 最强 |
| 通信线 | text vs protocol，强调 fairness | 同主仓库 | 从 JSON 到二进制 IPC/Protobuf/MessagePack |
| 状态线 | `StateRef` + `mmap/shared_memory` + consumer packet | 同主仓库 | `master_4/7` 偏 SHM/IPC；`master_8` 较轻 |
| 记忆线 | SQLite + vector + replay episodes | 同主仓库 | 有 shared memory / SQLite / Chroma / quorum 等变体 |
| 复用判定 | 合同化 replay eligibility | 同主仓库 | 一部分偏 heuristic，一部分偏 demo |
| 测试强项 | fairness、contract、wire、memory、evidence release | 同主仓库 | `master_8` 可读性高，`master_4` 系统 feature 覆盖广 |
| 报告强项 | object boundary 诚实 | 无新增 | `master_6` 最强 |
| 最大优点 | 诚实边界、可审计性、host realism | 阅读收敛 | 不同分支分别展示机制、包装、脚手架 |
| 最大问题 | formal closure 未完全封口 | 不是独立实现 | README claim 常大于严谨证据 |

### 2.2 三方总体结论

#### 事实

1. 主仓库最强的不是“功能最多”，而是“把公平比较、角色可见性和 claim release 程序化”。
2. 内部快照的主要价值只是便于对外阅读，不提供额外技术信息。
3. 外部第三方中，`master_6` 对比赛答辩最有参考价值，但主要是证据组织能力，不应误读成底层系统必然更强。

#### 推断

1. 如果你们只想形成第一版可交付证据包，主仓库已经足够；关键在收口，不在换架构。
2. 如果你们想进一步创新，优先空间也在实验设计与证据工程，而非再造一个 transport 或 memory 名词。

---

## 3. 我们自己的实现：前因后果

### 3.1 为什么会走到现在这条路线

#### 事实

1. 主仓库明确要求优先实现 host-side 可运行路径，而不是一开始追容器、虚拟机、特权 sandbox。
   - [AGENTS.md 环境策略摘录](/home/qcrs/statebus/project/AGENTS.md:1)
   - [docs/constraints/current_host_and_migration.md](/home/qcrs/statebus/project/docs/constraints/current_host_and_migration.md:174)
   - [docs/constraints/current_host_and_migration.md](/home/qcrs/statebus/project/docs/constraints/current_host_and_migration.md:207)

2. 设计优先级明确是：
   1. host 环境前提
   2. text path
   3. protocol path
   4. `StateRef` / statepool
   5. memory
   6. benchmark / telemetry

   证据：
   - [AGENTS.md](/home/qcrs/statebus/project/AGENTS.md:1)
   - [docs/planning/implementation_plan.md](/home/qcrs/statebus/project/docs/planning/implementation_plan.md:1)

3. 当前路线与赛题要求直接同构：
   - 至少三类 Agent
   - 同时支持 text / structured protocol
   - 实现非文本状态传递
   - 实现共享记忆
   - 连续任务验证
   - 指标统计

   证据：
   - [docs/reference/题目.md](/home/qcrs/statebus/project/docs/reference/题目.md:1)
   - [README.md](/home/qcrs/statebus/project/README.md:1)

#### 推断

这条路线不是偶然演化，而是从一开始就把“先把 contest 真正要求的基础设施做出来”放在“秀复杂系统技术”前面。后面之所以又引入 `headline/support/audit` 分层，是因为在 contest-facing 阶段，团队发现“已实现能力”和“能正式声称的优势”不再等价。

### 3.2 headline / support / audit 分层怎么来的

#### 事实

1. `tasks/README.md` 已经把 object 明确分层：
   - `headline`
   - `formal-secondary`
   - `audit`
   - `historical`

   证据：
   - [tasks/README.md](/home/qcrs/statebus/project/tasks/README.md:19)
   - [tasks/README.md](/home/qcrs/statebus/project/tasks/README.md:21)
   - [tasks/README.md](/home/qcrs/statebus/project/tasks/README.md:42)

2. 当前 active communication headline 只有 `superiority_comm_v1`。
   - [README.md](/home/qcrs/statebus/project/README.md:136)
   - [docs/reports/statebus_system_method_task_and_results_explainer.md](/home/qcrs/statebus/project/docs/reports/statebus_system_method_task_and_results_explainer.md:41)

3. `typed_state_mechanism_v3` 与 `superiority_memory_v1` 被定义为 formal-secondary，不再承担总 headline 闭环。
   - [README.md](/home/qcrs/statebus/project/README.md:137)
   - [docs/reports/current_task_results_overview_20260622.md](/home/qcrs/statebus/project/docs/reports/current_task_results_overview_20260622.md:97)
   - [docs/reports/statebus_system_method_task_and_results_explainer.md](/home/qcrs/statebus/project/docs/reports/statebus_system_method_task_and_results_explainer.md:162)

4. `scripts/write_final_evidence_program.py` 和对应测试把 release ledger 程序化，说明这个分层不只是文档写法，而是正式 release mechanism。
   - [scripts/write_final_evidence_program.py](/home/qcrs/statebus/project/scripts/write_final_evidence_program.py:242)
   - [tests/test_final_evidence_program.py](/home/qcrs/statebus/project/tests/test_final_evidence_program.py:214)
   - [tests/test_final_evidence_program.py](/home/qcrs/statebus/project/tests/test_final_evidence_program.py:297)

#### 推断

这个分层的根本原因是：系统能力已经丰富到足以产生多种“看起来都不错”的结论，但为了防止 claim 冲突、对象漂移和不公平读取，必须建立一个对象冻结体系。

### 3.3 当前最核心的矛盾是什么

#### 事实

1. communication 线已经通过 gate，但 formal stability 没过。
   - [docs/planning/statebus_contest_superiority_gate_contract_20260621.md](/home/qcrs/statebus/project/docs/planning/statebus_contest_superiority_gate_contract_20260621.md:274)
   - [docs/reports/current_task_results_overview_20260622.md](/home/qcrs/statebus/project/docs/reports/current_task_results_overview_20260622.md:269)

2. memory 线当前被限定为 replay effect scaffold。
   - [docs/reports/current_task_results_overview_20260622.md](/home/qcrs/statebus/project/docs/reports/current_task_results_overview_20260622.md:391)
   - [eval/runner.py](/home/qcrs/statebus/project/eval/runner.py:6169)

3. typed-state 线当前被限定为 mechanism claim，而不是 contest dual-mode headline。
   - [docs/reports/statebus_system_method_task_and_results_explainer.md](/home/qcrs/statebus/project/docs/reports/statebus_system_method_task_and_results_explainer.md:91)
   - [eval/runner.py](/home/qcrs/statebus/project/eval/runner.py:6407)

#### 推断

当前最核心的矛盾不是“有没有 improvement signal”，而是“主信号有了，但 contest-facing 最终闭环还没有全部达到可以无歧义释放的程度”。

### 3.4 现在证据已经证明了什么，没证明什么

#### 已证明

1. `protocol` 路径相较内部 `text_whole_lane` headline 对照路径，在当前对象上更省 communication 开销，并保持质量底线。
2. minimal typed packet 确实被产生、传递、消费。
3. memory/replay 路径确实存在并能产生 skip/reuse effect。
4. 系统存在公平性防护：
   - text lane 不得偷看 typed state
   - protocol lane 不得无界泄露 rich helper
   - role/model/tool/corpus visibility 有专门约束

   证据：
   - [docs/reports/statebus_system_method_task_and_results_explainer.md](/home/qcrs/statebus/project/docs/reports/statebus_system_method_task_and_results_explainer.md:399)
   - [runtime/role_contracts.py](/home/qcrs/statebus/project/runtime/role_contracts.py:93)
   - [tests/test_role_contracts.py](/home/qcrs/statebus/project/tests/test_role_contracts.py:8)
   - [tests/test_context_slices.py](/home/qcrs/statebus/project/tests/test_context_slices.py:3)
   - [tests/test_fairness_gates.py](/home/qcrs/statebus/project/tests/test_fairness_gates.py:1)

#### 未证明或不足以证明

1. `superiority_comm_v1` 的更高重复深度稳定性结论。
2. memory 模块带来的 overall superiority。
3. typed-state 机制本身自动推出 overall system superiority。
4. 全系统更细粒度的 per-role overhead 已被完整量化。

### 3.5 当前文档和代码是否一致

#### 事实

总体上是一致的，且比普通仓库更一致，因为存在“文档 + 报告生成逻辑 + release 测试”三重绑定：
- 文档给出口径
- `eval/runner.py` 负责把 pack 类型渲染成相应 stopline
- `write_final_evidence_program.py` 负责 formal release ledger
- 测试验证禁止错误表述

证据：
- [eval/runner.py](/home/qcrs/statebus/project/eval/runner.py:6112)
- [eval/runner.py](/home/qcrs/statebus/project/eval/runner.py:6169)
- [scripts/write_final_evidence_program.py](/home/qcrs/statebus/project/scripts/write_final_evidence_program.py:96)
- [tests/test_final_evidence_program.py](/home/qcrs/statebus/project/tests/test_final_evidence_program.py:297)

#### 发现的局部张力

1. 运行时能力已经很强，但 README 层面的高层描述比正式 claim 更宽，读者若只看 README，容易误以为三条线都已经 headline closure。
2. 报告已经能区分 planner/summarizer token，但 retriever/executor 的报告粒度没有同等细化。

### 3.6 当前最缺什么

#### 事实

缺的主要不是代码模块，而是证据交付层：
- requirement-to-evidence matrix
- judge-facing one pager
- 完整 claim table
- 更明确的 “what we do not claim”
- retriever/executor 粒度 overhead 表

#### 建议

优先补文档、实验合同与 evidence pack，而不是再扩一层 transport 或 memory feature。

---

## 4. 我们内部参考实现：架构与策略

### 4.1 仓库实际性质

#### 事实

该仓库自述就是一个同步快照：
- “从 `statebus/project` 同步出来的精简快照”
- source branch：`feat/taskset-mainline-split`
- source revision：`99685b6`

证据：
- [/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md](/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md:3)
- [/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md](/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md:8)
- [/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md](/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md:9)

### 4.2 是否存在用户点名的第二套文件体系

#### 事实

下列用户指定文件在该仓库中不存在：
- `DESIGN.md`
- `TECHNICAL_REPORT.md`
- `docs/contest_summary.md`
- `docs/evaluation_protocol.md`
- `docs/赛题符合性矩阵.md`
- `docs/experiment_notes.md`
- `docs/evidence_pack.md`
- `docs/defense_one_pager.md`
- `src/hqm/agents.py`
- `src/hqm/orchestrator.py`
- `src/hqm/state_exchange.py`
- `src/hqm/memory.py`
- `src/hqm/quorum.py`
- `src/hqm/benchmark.py`
- `src/hqm/report.py`

#### 结论

`事实`：该仓库不能被审读为一套 `hqm` 风格独立实现，因为证据对象根本不存在。  
`建议`：在任何后续汇报中，应明确写成“该文件在仓库中不存在”，而不是进行推断性补完。

### 4.3 该快照真正的价值

#### 事实

1. 它把主仓库当前正式读法压缩到更小的阅读面。
2. 它保留了核心实现、主阅读文档、最小实验结果集。
3. 它故意移除了大量历史草稿、分析目录和全量结果。

证据：
- [/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md](/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md:38)
- [/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md](/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md:58)
- [/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md](/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md:70)

#### 推断

它更像一个“外发阅读包”或“审查窗口”，而不是并行研发分支。

---

## 5. 外部参考逐项目报告

### 5.1 `master_1`：基线型参考

#### 事实

`master_1` 的主要价值在于把 contest 核心元件压成一套简单 baseline：
- text-like runtime
- StateRef / shared memory state store
- 基础 metrics / benchmark / report

证据：
- `third_party/.../master_1/README.md:9`
- `third_party/.../master_1/README.md:23`

#### 评价

- 创新点：有限，主要是把最小可比较系统搭出来。
- 启发：一个对照组应尽量简单、可解释、低自由度。
- 不能照搬：其 baseline 结构、命名和实现细节都过于特化于其仓库。

### 5.2 `master_3`：过渡型参考

#### 事实

`master_3` 已开始把 protocol、memory、evaluation 分开，但整体仍较轻，证据规模有限。

#### 推断

它的价值主要是“从 demo 走向体系化”的组织过程，而不是最终可采纳方案。

### 5.3 `master_4`：系统秀肌肉型参考

#### 事实

1. `README.md` 和 `TECHNICAL_REPORT.md` 强调：
   - 结构化通信
   - embedding 状态向量
   - shared memory 引用
   - CodeAct 沙箱
   - openEuler 可运行

   证据：
   - `third_party/.../master_4/README.md:3`
   - `third_party/.../master_4/README.md:9`
   - `third_party/.../master_4/README.md:11`
   - `third_party/.../master_4/TECHNICAL_REPORT.md:10`
   - `third_party/.../master_4/TECHNICAL_REPORT.md:12`

2. `DESIGN.md` 明确把状态交换、shared memory、memory、CodeAct 执行和修复闭环连到一起。
   - `third_party/.../master_4/DESIGN.md:25`
   - `third_party/.../master_4/DESIGN.md:96`
   - `third_party/.../master_4/DESIGN.md:139`

3. 测试覆盖 IPC pipeline、memory center、repair loop、sandbox、message limit、evaluation。
   - `third_party/.../master_4/tests/test_ipc_pipeline.py:12`
   - `third_party/.../master_4/tests/test_memory_center.py:11`
   - `third_party/.../master_4/tests/test_repair_loop.py:34`
   - `third_party/.../master_4/tests/test_sandbox.py:9`
   - `third_party/.../master_4/tests/test_message_limits.py:11`
   - `third_party/.../master_4/tests/test_evaluation.py:11`

#### 创新点

- 机制创新：把 IPC、SHM、sandbox、repair loop 放在一条系统 story 里。
- 展示创新：很善于把“系统层能力”讲得强而完整。

#### 局限

1. README/报告中的强性能结论主要是 feature-forward，公平性控制读起来不如主仓库严格。
2. 证据包装没有 `master_6` 那样强的 claim/caveat/judge ledger。

#### 可借鉴抽象原则

- 可以借鉴“如何把系统 feature 讲成系统 story”。
- 不应照搬其 message、vector、repair 或 sandbox 组织方式。

### 5.4 `master_6`：证据工程最强参考

#### 事实

1. `docs/evaluation_protocol.md` 直接回答：
   - 谁评判 correctness
   - 怎么做 controlled comparison
   - 有哪些 ablation
   - 不应该 claim 什么

   证据：
   - `third_party/.../master_6/docs/evaluation_protocol.md:3`
   - `third_party/.../master_6/docs/evaluation_protocol.md:17`
   - `third_party/.../master_6/docs/evaluation_protocol.md:26`
   - `third_party/.../master_6/docs/evaluation_protocol.md:121`
   - `third_party/.../master_6/docs/evaluation_protocol.md:124`

2. `evidence/evidence_pack.md` 把 evidence source、judge、how、result、caveat 都写出来，并且区分 controlled comparison、external trace replay、pytest、deterministic harness 等不同 judge 来源。
   - `third_party/.../master_6/evidence/evidence_pack.md:112`
   - `third_party/.../master_6/evidence/evidence_pack.md:131`
   - `third_party/.../master_6/evidence/evidence_pack.md:134`
   - `third_party/.../master_6/evidence/evidence_pack.md:148`
   - `third_party/.../master_6/evidence/evidence_pack.md:160`

3. `docs/defense_one_pager.md` 明确区分：
   - what we claim
   - who judges correctness
   - what we do not claim

   证据：
   - `third_party/.../master_6/docs/defense_one_pager.md:38`
   - `third_party/.../master_6/docs/defense_one_pager.md:47`
   - `third_party/.../master_6/docs/defense_one_pager.md:66`

4. `docs/赛题符合性矩阵.md` 提供 requirement-to-file 映射。
   - `third_party/.../master_6/docs/赛题符合性矩阵.md:6`
   - `third_party/.../master_6/docs/赛题符合性矩阵.md:7`
   - `third_party/.../master_6/docs/赛题符合性矩阵.md:9`

5. 核心模块入口：
   - `src/hqm/agents.py:79,109,149,265,273`
   - `src/hqm/state_exchange.py:24,44,66,86,112`
   - `src/hqm/memory.py:31`
   - `src/hqm/quorum.py:31,50`
   - `src/hqm/benchmark.py:81,133,157,434,502`
   - `src/hqm/report.py:13`

#### 创新点

- 实验创新：`Memory Only`、`Quorum Only`、`Full` 等五路控制。
- 评审创新：hidden oracle、blind strict、integration evidence、judge view。
- 包装创新：one pager、evidence pack、claim table、requirement matrix。

#### 局限

1. 需要警惕“包装强”被误读成“底层机制一定更强”。
2. 很多叙事已经明显面向答辩与 defense 优化，不能直接拿来当实现设计模板。

#### 对我们的启发

这是对你们最有价值的外部参考，但价值主要在证据组织和实验合同，不在代码复用。

### 5.5 `master_7`：基础设施优先参考

#### 事实

1. `src/README.md` 强调多进程 UDS + Protobuf + shared memory + Chroma memory + bubblewrap/cgroup sandbox。
   - `third_party/.../master_7/src/README.md:3`
   - `third_party/.../master_7/src/README.md:11`
   - `third_party/.../master_7/src/README.md:76`

2. 关键模块：
   - orchestrator：`src/orchestrator.py:47`
   - message schema：`src/protocol/messages.py:31`
   - binary serializer：`src/protocol/binary_serializer.py:27`
   - UDS server：`src/ipc/uds_server.py:46`
   - SHM manager：`src/ipc/shm_manager.py:56`
   - vector pool：`src/state_transfer/vector_pool.py:29`
   - reuse controller：`src/memory/reuse_controller.py:90`
   - shared memory store：`src/memory/shared_memory.py:12`
   - agent process：`src/agents/agent_process.py:47`
   - sandbox：`src/sandbox/bwrap_sandbox.py:29`
   - evaluation reporter：`src/evaluation/reporter.py:6`

#### 创新点

- 机制创新：把“系统 runtime”认真做成多进程 IPC 基础设施。
- 展示创新：把 transport reality、sandbox reality 说得很清楚。

#### 局限

1. README 中 90%+ reduction 很吸引人，但当前可读到的证据更多是 narrative 与模块存在性，严谨对照面不如主仓库和 `master_6`。
2. 容易把 transport improvement 过度外推到 overall contest superiority。

### 5.6 `master_8`：教学化 skeleton 参考

#### 事实

1. 仓库 `README.md` 基本只是赛题原文，没有额外设计报告。
2. 代码层有完整 skeleton：
   - `src/maos/runtime/bus.py:32,89,98`
   - `src/maos/runtime/uds_bus.py:15`
   - `src/maos/state/state_store.py:12`
   - `src/maos/state/shm_store.py:13`
   - `src/maos/memory/sqlite_store.py:13`
   - `src/maos/runtime/scheduler.py:46`
   - `src/maos/runtime/execution.py:31`
   - `src/maos/agents/planner.py:11`
   - `src/maos/agents/retriever.py:13`
   - `src/maos/agents/executor.py:11`
   - `src/maos/agents/summarizer.py:12`

3. 测试强调“可跑通”而非“强证明”：
   - `tests/test_agents_flow.py:46`
   - `tests/test_eval_runner.py:13`
   - `tests/test_uds_bus.py:1`
   - `tests/test_shm_store.py:1`

#### 判断

- `事实`：它更像教学化、低风险 contest skeleton。
- `事实`：`UDSBus` 是 placeholder，真实 UDS transport 没有主线实现；`run_task` 也主要走 `InMemoryStateStore`。
- `推断`：它不是“更强的系统路线”，而是“更干净、更容易看懂的最小骨架”。

### 5.7 `master_5`：创意密集但证据不足的参考

#### 事实

`master_5/README.md` 提出了：
- MessagePack
- 隐藏状态特征
- P2P 消息总线
- Delta 增量编码
- 遗忘曲线
- BM25+FAISS+RRF

证据：
- `third_party/.../master_5/README.md:1`

#### 结论

`不足以证明`这些设计都已经被公平、稳定、可复现实验证实。当前更像高密度 proposal/marketing-style summary。

### 5.8 `master_2` 与 `master_9`

#### 事实

1. `master_2` 更像 ScienceWorld/adapter/real score 方向分支，不是核心 contest 线。
2. `master_9` 当前只看到赛题原文，缺少可审的实现/报告对象。

#### 结论

二者都不应成为此次三方主比较的中心对象。

---

## 6. 外部参考的创新点清单

### 6.1 机制创新

#### 事实

1. `master_4` / `master_7` 在 IPC、shared memory、sandbox 的系统级叙事上最突出。
2. `master_5` 在 README 层提出 hidden-state、delta、P2P、forgetting 等更激进设想。
3. `master_6` 的 quorum-gated memory 机制，把 memory 是否进入主流程变成可拆分开关。

### 6.2 实验创新

#### 事实

1. `master_6` 的 controlled comparison / ablation 最系统。
2. `master_6` 的 blind strict、integration demo、real embedding validation 明确区分证据强弱。

### 6.3 包装创新

#### 事实

1. `master_6` 的 one pager、evidence pack、claim table、judge view 是最成熟的比赛证据包装。
2. `master_4` / `master_7` 更偏“系统 showcase 包装”。

### 6.4 哪些只是包装，不是本质

#### 事实

- 华丽术语
- 漂亮 dashboard
- 高压缩 headline 数字
- SDK 名称
- defense 话术

这些都不是系统能力本身。

---

## 7. 外部参考的不足与风险

### 7.1 共同风险

#### 事实

1. 多个分支 README claim 很强，但 fairness control 与 claim boundary 文档不一定同样强。
2. 一些分支更像 feature demo，而不是 formal contest proof。

### 7.2 对我们而言最需要避免的点

#### 建议

1. 不要把 feature-rich 误写成 claim-rich。
2. 不要把 packaging-rich 误写成 capability-rich。
3. 不要从第三方直接搬类名、变量名、SDK surface、目录结构或模块分工。

---

## 8. 对我们最有价值的启发

### 8.1 来自主仓库自身

#### 事实

主仓库已经证明了一条重要原则：公平比较、角色可见性、claim gate 必须从实现层、报告层、测试层同时约束。

### 8.2 来自 `master_6`

#### 建议

最值得借鉴的不是代码，而是以下抽象原则：
- 把赛题要求映射成 requirement matrix
- 把 claim 映射成 artifact 和 evaluator
- 把 “不能 claim 什么” 写出来
- 把 blind control 明文化
- 把 integration evidence 与 benchmark evidence 分层

### 8.3 来自 `master_4/7`

#### 建议

可以借鉴它们更直观的“系统 story”表达方式，但必须放在你们当前 fairness/claim 边界之下，不能反过来用 systems story 覆盖证据边界。

### 8.4 来自 `master_8`

#### 建议

对外阅读材料应尽量像 `master_8` 一样整洁、分层明确、测试好扫读，但不能为了干净而牺牲真实复杂度与正式证据。

---

## 9. 我们当前最缺什么

### 9.1 证据组织缺口

#### 事实

最缺的是：
- `requirement -> claim -> evaluator -> artifact -> caveat` 总表
- judge-facing 一页纸
- claim table
- what-we-do-not-claim 显式文档

### 9.2 实验设计缺口

#### 事实

1. communication formal stability 仍未封口。
2. memory 线仍缺更强主张所需的严格对照。
3. retriever/executor 开销量化粒度不如 planner/summarizer 完整。

### 9.3 组织认知缺口

#### 事实

内部快照被误当“第二实现”的风险需要彻底去除。

---

## 10. 下一步优先级建议

### 10.1 P0：正式证据收口

#### 建议

1. 固定 `superiority_comm_v1` 的最终 judge-facing 读法。
2. 补 communication formal stability 所需重复深度和 release 论证。
3. 输出 claim table / one pager / requirement matrix。

### 10.2 P1：memory 线收缩或补强

#### 建议

1. 如果短期无法补齐严格证据，就正式坚持“memory = replay effect support”。
2. 如果要升级主张，必须补：
   - 对照
   - 消融
   - 负控
   - claim boundary

### 10.3 P2：报告粒度完善

#### 建议

补 retriever/executor 粒度 token / char / latency / state-byte accounting。

### 10.4 P3：可读性与外发材料

#### 建议

做一个更干净的 judge snapshot 或 reader pack，但要明确不是第二实现。

---

## 11. 风险清单

### 11.1 主张风险

#### 事实

1. typed-state 被误说成 active headline 的风险已经被测试专门防御。
   - [tests/test_final_evidence_program.py](/home/qcrs/statebus/project/tests/test_final_evidence_program.py:297)

2. memory support 被误说成 superiority 的风险依然很高。

### 11.2 证据风险

#### 事实

1. formal stability 尚未通过。
2. per-role overhead 统计尚不完全均衡。

### 11.3 组织风险

#### 事实

内部快照若被当成第二实现，会导致重复计证与错误叙事。

---

## 12. 逐文件 / 逐模块详细报告

### 12.1 主仓库：文档与证据合同层

#### `README.md`

- 做什么：给出项目概览、当前正式读法、运行方式。
- 系统位置：外层入口。
- 关键设计点：明确 active headline 与 formal-secondary。
- 创新点：README 不只是宣传，而是和正式口径基本一致。
- 局限：对 casual reader 仍可能显得“功能全都已经证明”。
- 启发：总入口必须主动声明 claim boundary。
- 不能照搬的地方：术语与 headline 对象命名。

#### `docs/constraints/current_host_and_migration.md`

- 做什么：冻结 host 假设与迁移边界。
- 位置：环境合同。
- 关键点：`shared_memory`、FAISS、UDS、host-side path、openEuler 后验验证分工。
- 启发：先冻结环境事实再谈机制优劣。

#### `docs/constraints/current_feature_scope.md`

- 做什么：定义“现在到底有哪些 feature 是正式存在的”。
- 位置：功能边界合同。
- 关键点：`StateRef + mmap/shared_memory + SQLite + FAISS` 皆为正式存在对象。
- 局限：feature scope 强，不等于 headline 也强。

#### `docs/planning/implementation_plan.md`

- 做什么：描述从 host runnable path 到 statepool/memory/benchmark 的实现顺序。
- 位置：前因后果来源。
- 启发：当前实现路线是连续演化，不是赛前临时拼接。

#### `docs/reference/题目.md`

- 做什么：冻结赛题文本。
- 位置：所有 claim 的外部标准。
- 关键点：它定义了系统题，而非 workflow 拼接题。

#### `docs/reports/statebus_system_method_task_and_results_explainer.md`

- 做什么：当前最重要的正式解释文档。
- 位置：主仓库“怎么读系统、任务、结果”的中心文档。
- 关键点：active headline、support boundary、state plane、memory plane、evidence boundary 全在这里。
- 创新点：把实现、实验和主张边界统一到一份文档。
- 局限：篇幅大，非评审友好版。

#### `docs/reports/current_task_results_overview_20260622.md`

- 做什么：总结 authoritative artifact 与当前 object 读法。
- 位置：结果总览。
- 关键点：区分 authoritative artifacts 与历史 runs。
- 启发：结果汇总必须先定义对象边界。

#### `docs/planning/statebus_contest_requirement_first_split_execution_plan_20260621.md`

- 做什么：把赛题要求拆成执行任务。
- 位置：从 requirement 到 implementation 的桥。
- 启发：赛题拆分不是抽象路线图，而是后续 evidence contract 的源头之一。

#### `docs/planning/statebus_contest_superiority_gate_contract_20260621.md`

- 做什么：定义 superiority gate 的对象、条件、释放规则。
- 位置：形式化 claim release 合同。
- 关键点：`communication gate` 与 `formal stability gate` 分离。
- 创新点：把“何时能说什么”写成合同。

### 12.2 主仓库：任务、测试、运行时与证据程序

#### `tasks/README.md`

- 做什么：定义 task object 的层级与读取方式。
- 位置：任务对象注册表说明。
- 关键点：headline / support / audit / historical 分层。
- 启发：任务集本身也是证据对象，不只是输入数据。

#### `tests/test_llm_runtime.py`

- 做什么：验证 role-specific model、planner parsing、transfer strategy、支持字段解析等运行时行为。
- 位置：LLM/runtime 质量门。
- 关键点：防止 prompt、plan parser、runtime drift。
- 局限：测试量大，读者成本高。

#### `tests/test_final_evidence_program.py`

- 做什么：验证 evidence release 逻辑。
- 位置：正式 claim 守门测试。
- 关键点：禁止错误 claim，验证 ledger 条件。
- 创新点：很少有项目把“能不能这么说”写成测试。

#### `eval/runner.py`

- 做什么：benchmark、summary、report、object-specific stopline 输出核心。
- 位置：实验与报告主入口。
- 关键点：不同 `pack_type` 有不同 report contract。
- 创新点：runner 同时懂任务对象与 claim boundary。
- 局限：复杂度高，外部读者难全盘吸收。

#### `agents/sample_agents.py`

- 做什么：contest agent 行为与 handoff/decision 逻辑。
- 位置：系统行为层。
- 关键点：text/protocol、audit/helper、planner/refinement、多包对象约束都在此显式体现。
- 局限：task pack 语义耦合较重。

#### `runtime/llm.py`

- 做什么：provider path、deterministic path、role-specific config、解析与 fallback。
- 位置：模型执行层。
- 关键点：使实验既能 deterministic，又能走 provider。

#### `scripts/write_final_evidence_program.py`

- 做什么：读取 benchmark artifacts，产出 final evidence verdict。
- 位置：正式发布程序。
- 关键点：release ledger、forbidden claims、gate reads。
- 重要提醒：这不是 runtime 能力本身，而是证据程序。

### 12.3 主仓库：协议、状态、记忆、编排

#### `protocol/messages.py`

- 做什么：定义 `StateRef`、step result、wire 序列化与 proto 转换。
- 位置：控制面/状态面协议层。
- 关键点：`StateRef` 既是引用对象，也是统计、replay、wire accounting 的基础。
- 创新点：协议对象里显式带 replay / skip 元信息。

#### `runtime/role_contracts.py`

- 做什么：定义每个角色能看到什么。
- 位置：公平性边界层。
- 关键点：bounded visibility，而不是“所有对象都随便传”。

#### `runtime/context_slice.py`

- 做什么：把上下文切片成角色可见片段。
- 位置：角色隔离实现层。
- 启发：公平比较必须有具体切片逻辑。

#### `runtime/orchestrator.py`

- 做什么：主编排器，管理 plan、state、memory、replay、step execution。
- 位置：系统中枢。
- 关键点：
  - `prepare_plan`
  - `resolve_skip_retrieve_execute`
  - `resolve_skip_execute`
  - state registration / restore / replay compatibility
- 创新点：复用不是简单命中，而是受合同与状态兼容性约束。
- 局限：复杂，后续审计需要更多摘要材料。

#### `runtime/executor_runtime.py`

- 做什么：构建 typed feature bundle、decision packet，并执行工具路径。
- 位置：typed-state 消费中心。
- 关键点：状态包围绕 executor 决策而设计，不是为了“证明有状态传递”而传递。

#### `statepool/store.py`

- 做什么：实现 file-backed `mmap`、`shared_memory`、统一 `StatePool`、blob store。
- 位置：状态数据面。
- 关键点：控制面只传引用，数据面走真实状态对象。
- 创新点：支持 replay-restorable artifact。

#### `memory/store.py`

- 做什么：共享记忆与 replay episodes 存储检索。
- 位置：记忆与复用层。
- 关键点：assist 与 replay 不是混在一起的简单 memory hit。
- 局限：当前正式结论仍然只到 replay effect。

#### `eval/fairness_gates.py`

- 做什么：实现计划公平性、执行公平性判定。
- 位置：实验方法学约束层。
- 启发：fairness 不能只在文档里说，要成为代码 gate。

### 12.4 内部快照：关键文件小报告

#### `/home/qcrs/yzmxdzntxzddkxtxztcdygxjyjz/README.md`

- 做什么：定义快照性质、同步来源、保留内容、移除内容。
- 位置：阅读快照入口。
- 关键设计点：压缩主仓库阅读面，保留最小正式结果集。
- 启发：对外阅读包需要更强筛选。
- 不能照搬的地方：不能把快照规则当成独立架构。

#### 该仓库中不存在的文件组

- 做什么：不是模块，而是“缺失事实”。
- 位置：方法学边界。
- 关键点：不存在就是不存在，不能补想象。
- 启发：审查报告必须区分“仓库无此对象”和“对象存在但未读完”。

### 12.5 第三方：逐模块小报告

#### `master_6/src/hqm/agents.py`

- 做什么：Planner、Retriever、Executor、Verifier、Summarizer 五类 agent。
- 位置：HQM 主行为层。
- 关键点：把 defect diagnosis / verification / memory recording 串成闭环。
- 创新点：加入 verifier 和 diagnosis parsing，使 correctness judge 可以外置。
- 局限：面向特定 defect task，非常比赛/答辩导向。
- 启发：可以借鉴“验证者独立于生产者”原则。
- 不能照搬：五角色组织、诊断字段、memory id 组织。

#### `master_6/src/hqm/state_exchange.py`

- 做什么：把 packet/text 转成 state frame，提供 semantic vector/similarity。
- 位置：状态交换层。
- 关键点：状态帧同时服务 memory query 与 packet state 描述。
- 启发：状态交换不仅是传输问题，也是后续检索/比较问题。

#### `master_6/src/hqm/memory.py`

- 做什么：SQLite memory + semantic/tag 检索 + reuse 事件记录。
- 位置：共享记忆层。
- 关键点：不仅存 memory，还存 reuse success/failure 事件。
- 启发：reuse 事件应被单独记录。

#### `master_6/src/hqm/quorum.py`

- 做什么：根据 homeostasis state 和 packet 集合做 quorum decision。
- 位置：memory 与主流程之间的 gate。
- 关键点：memory promotion、conflict quorum 不是默认通过。
- 启发：复用进入主流程前应有决策门。

#### `master_6/src/hqm/benchmark.py`

- 做什么：baseline、full、memory-only、quorum-only、champion ablation 运行入口。
- 位置：实验组织中心。
- 创新点：把 ablation 直接固化进 benchmark harness。
- 启发：对照和消融应成为入口级对象，而不是事后分析脚本。

#### `master_6/src/hqm/report.py`

- 做什么：输出 runs/messages/memory events/markdown 报告。
- 位置：evidence 物料生成层。
- 启发：报告应按事件类型分文件，而不是只出一个 summary。

#### `master_7/src/orchestrator.py`

- 做什么：多进程 orchestrator，分别调用 planner/retriever/executor/summarizer agent process。
- 位置：infra-first 编排层。
- 关键点：text mode 与 IPC mode 双路径。
- 启发：若要强调 transport reality，应在 orchestrator 层保留两条真实路径。

#### `master_7/src/protocol/messages.py`

- 做什么：结构化消息、握手、任务命令、状态传输、memory record schema。
- 位置：协议 schema 层。
- 启发：协议对象应显式覆盖 handshake/capability/task/state/memory。

#### `master_7/src/protocol/binary_serializer.py`

- 做什么：把多类消息转成 Protobuf envelope，并比较 JSON vs binary size。
- 位置：二进制协议层。
- 启发：carrier 优势最好有同消息双编码比较。

#### `master_7/src/ipc/uds_server.py`

- 做什么：agent 端 UDS server。
- 位置：真实 IPC transport。
- 启发：如果要宣称 UDS，就要有真正 socket server，而不是 metadata placeholder。

#### `master_7/src/ipc/shm_manager.py`

- 做什么：共享内存 embedding 写入、读取、释放和统计。
- 位置：SHM 数据面。
- 启发：SHM 生命周期管理必须显式。

#### `master_7/src/state_transfer/vector_pool.py`

- 做什么：共享向量池与 similarity search。
- 位置：状态/记忆中间层。
- 局限：vector pool 的存在本身不等于 consumer 真正依赖它。

#### `master_7/src/memory/reuse_controller.py`

- 做什么：reuse decision 与 reuse stats。
- 位置：记忆复用门控层。
- 启发：reuse 不该只是 memory hit count。

#### `master_7/src/memory/shared_memory.py`

- 做什么：共享记忆存储与多种检索。
- 位置：memory 层。
- 局限：命名容易与 OS shared memory 概念混淆。

#### `master_7/src/agents/agent_process.py`

- 做什么：agent 进程封装，接收 envelope 并 dispatch。
- 位置：多进程 agent runtime。
- 启发：真实 agent process 能提升系统展示真实感。

#### `master_7/src/sandbox/bwrap_sandbox.py`

- 做什么：bubblewrap sandbox 与 fallback。
- 位置：CodeAct 安全执行层。
- 局限：你们当前 host 事实不支持把这一路当主线。

#### `master_7/src/evaluation/reporter.py`

- 做什么：汇总 metrics 并生成报告。
- 位置：评测输出层。
- 启发：系统特性强时，也要让报告能解释 outlier 与统计口径。

#### `master_8/src/maos/runtime/bus.py`

- 做什么：text/struct bus 与通信统计。
- 位置：最小通信层。
- 关键点：同一 `AgentMessage` 支持 text prompt 渲染和结构化编码。
- 启发：最小对照模型可做得很清晰。

#### `master_8/src/maos/runtime/uds_bus.py`

- 做什么：UDS metadata wrapper。
- 位置：transport placeholder。
- 局限：不是完整 UDS runtime。

#### `master_8/src/maos/state/state_store.py` 与 `shm_store.py`

- 做什么：in-memory / shared-memory state store。
- 位置：最小状态层。
- 局限：主运行路径并没有把 SHM 作为强证明对象。

#### `master_8/src/maos/memory/sqlite_store.py`

- 做什么：SQLite memory with FTS fallback。
- 位置：最小共享记忆层。
- 启发：最小 memory store 也应支持 metadata、keyword、tag。

#### `master_8/src/maos/runtime/scheduler.py`

- 做什么：固定四阶段流水线。
- 位置：简化编排层。
- 启发：教学性材料可以用固定 pipeline 降低认知负担。

#### `master_8/src/maos/runtime/execution.py`

- 做什么：按 mode 组装 bus、embedder、memory store、agents 并运行任务。
- 位置：主执行入口。
- 关键点：`text`、`struct`、`struct_state`、`struct_state_memory` 四模式。
- 局限：相对简化，更多是 skeleton。

#### `master_8/src/maos/agents/*.py`

- 做什么：四角色 deterministic mock agent。
- 位置：最小 agent 行为层。
- 局限：更适合教学和 smoke，而不是 contest headline proof。

#### `master_8/tests/*`

- 做什么：证明 skeleton 可跑通、可产出 artifact、可做基础状态/总线回环。
- 启发：对外代码示例应尽量有清晰、短小、覆盖核心模块的测试。

---

## 13. 可执行建议清单

### P0

1. 产出主仓库 judge-facing `one_pager + claim_table + requirement_matrix + evidence_pack`。
2. 把 `superiority_comm_v1` 的 `formal stability gate` 作为第一优先级收口对象。
3. 在正式对外文档中明确写出：
   - 已证明什么
   - 未证明什么
   - 不宣称什么

### P1

4. 将 memory 线正式锁定为“replay effect support”，除非补齐更强 controlled evidence。
5. 补 retriever/executor 粒度的 token/latency/state-byte accounting。

### P2

6. 做一个更干净的 reader/judge snapshot，但明确标注其为快照，不是第二实现。
7. 压缩主仓库历史 object 噪音，为非作者读者提供更短阅读路径。

### P3

8. 如果还有创新空间，优先做实验组织创新：
   - 更强负控
   - blind prompt slice
   - evaluator split
   - integration evidence

### 不建议优先做的事

1. 不建议优先再加一个 transport 名词。
2. 不建议优先再堆一个 memory 技术名词。
3. 不建议把第三方 SDK surface、类名、目录结构、变量名直接搬进主仓库。
4. 不建议把内部快照继续当“第二条独立技术路线”叙述。


# StateBus V2 严格代码审查深化文档

日期：2026-06-28  
范围：`/home/qcrs/statebus/project` 当前 `v2/` clean-room 实现。  
目的：把 2026-06-28 的严格 code review 结论深化成可直接指导后续整改的工作文档。  
约束：本文档是审查与整改说明，不是实现说明；不把“能跑通”视为“严格实现”。

---

## 1. 如何使用这份文档

这份文档的用途不是重复之前的 finding，而是把每个 finding 进一步拆开，回答下面几类实际修改时必须面对的问题：

1. 当前到底违反了哪份上位文档。
2. 当前代码的真实行为是什么，偏差发生在什么位置。
3. 这个偏差为什么会影响 formal benchmark、fairness、replay claim 或 innovation claim。
4. 如果要改，有哪些可能的终局路径。
5. 哪条路径是推荐终局，为什么。
6. 改到什么程度才算“合同对齐”，不是“又加了一层解释”。

建议的使用方式：

1. 先读第 2 节的总判断，统一口径。
2. 然后按第 3 节的 findings 顺序修，优先修会污染 formal 口径的问题。
3. 修改时同步参考每条 finding 下的“验收标准”。
4. 在没有满足“验收标准”前，不要恢复更强的 README / benchmark / innovation claim。

---

## 2. 权威依据与总判断

### 2.1 权威依据顺序

一级依据：

1. `docs/reference/题目.md`
2. `docs/planning/statebus_v2_clean_room_rebuild_plan_20260625.md`
3. `docs/planning/statebus_v2_container_refactor_bootstrap_20260627.md`

核心合同：

1. `docs/planning/statebus_4_role_comparator_contract_20260620.md`
2. `docs/planning/benchmark_quality_floor_contract.md`
3. `docs/planning/task_compiler_contract.md`
4. `docs/planning/runtime_state_machine_contract.md`
5. `docs/planning/execution_artifact_and_workspace_contract.md`
6. `docs/planning/replay_admissibility_contract.md`
7. `docs/planning/canonical_evidence_pack_and_fan_in_contract.md`
8. `docs/planning/semantic_provenance_and_hydration_contract.md`
9. `docs/planning/ref_registry_and_manifest_storage_contract.md`
10. `docs/planning/runtime_compatibility_signature_contract.md`
11. `docs/planning/telemetry_event_contract.md`

辅助但非上位依据：

1. `docs/review/v2_implementation_gap_audit_20260627.md`
2. `README.md`
3. `docs/constraints/current_host_and_migration.md`
4. `docs/constraints/current_feature_scope.md`
5. `docs/planning/implementation_plan.md`

### 2.2 总判断

当前 `v2` 不是“完全没做”，但也远没有达到可以稳妥宣称“formal comparator / fair external baseline / strict L0-L3 / strict replay-ready / mature CodeAct runtime”的程度。

更准确的总判断是：

1. `ExecutionArtifactRef`、workspace、artifact commit、基础 replay gate、typed provenance 对象都已经是真实实现，不是空壳。
2. `TaskCompiler`、`CanonicalTaskSpec`、telemetry、state machine、semantic pruning、CodeAct 都是首版或 first-pass，不能拔高成 fully contract-aligned。
3. 当前最严重的问题不在“跑不起来”，而在“formal 口径和 demo/dev 口径混在一起”，导致 benchmark、headline delta、replay gain、innovation claim 都可能被高估。
4. 当前 comparator 不公平，这不是措辞问题，而是结构问题：两条 lane 没有共享同一角色图、同一 scoring contract、同一 helper 约束。

### 2.3 当前可以诚实 claim 的内容

可以诚实 claim：

1. 已有 `v2` clean-room typed contracts、semantic provenance 对象、artifact/workspace 主链路。
2. 已有 first-pass `TaskCompiler`、retrieval fanout、replay ledger、quality floor、workspace executor。
3. 已有 dev comparator / live harness，可用于开发期对照和容器内冒烟。

当前不应诚实 claim：

1. formal benchmark 默认入口已经冻结并对齐合同。
2. external lane 是干净的 pure-text 4-role baseline。
3. L0-L3 已经是合同意义上的纯文本到 full replay 梯度。
4. replay-ready gain 已经证明了连续任务历史复用。
5. CodeAct 已经是成熟的 agentic execution。
6. prompt-slice accounting / telemetry / state machine 已经达到严格审计级。

---

## 3. Findings

### Finding 1

严重度：High  
结论：当前仓内默认 `v2` live/comparator 入口不是冻结的 formal benchmark，而是 incident-style fixed-answer dev comparator。

合同/计划依据：

1. `docs/planning/statebus_v2_container_refactor_bootstrap_20260627.md:214-219,263-279` 把 formal tier 冻结为 offline local corpus 的财报/经营数据分析，并把 incident/code-audit 放到 demo/live。
2. `docs/planning/statebus_v2_clean_room_rebuild_plan_20260625.md:1425-1462` 明确 formal benchmark family 与 live demo family 需要分离。

代码/测试位置：

1. `v2/benchmark/live_runner.py:16-18,36-49,109-149`
2. `v2/benchmark/samples/fixed_answer_family/auth_session_drift.json:2-23`
3. `v2/benchmark/samples/fixed_answer_family/cache_replica_stale_read.json:2-23`
4. `v2/benchmark/samples/fixed_answer_family/worker_queue_starvation.json:2-23`
5. `README.md:119-125`
6. `tests/v2/test_preflight_and_live_runner.py:80-171`

详细问题说明：

1. 当前默认入口先把 fixed-answer family 暴露出来，而 fixed-answer family 的样本本质是 incident route/tool 题，不是 formal financial family。
2. 这会直接污染“默认用户路径”和“CI 习惯路径”。任何顺手执行 `live_runner` 的人，都更容易跑到 dev comparator，而不是合同冻结的 formal family。
3. 文档与默认入口错位的后果不是表述误差，而是 benchmark 结果很容易被错误解释成“正式 headline”，尤其当 README 和测试都把这条路径当成主入口时。
4. formal family 虽然存在，但在主入口层面被 dev family 抢占了心智位和命令位。

为什么这违反合同/计划：

1. 合同要的是 formal default family 与 demo/live family 清晰分叉，而不是“formal 文件存在即可”。
2. 一旦默认入口不是 formal family，formal 口径就失去了冻结对象和稳定复现实验面的意义。

影响：

1. 当前 live/comparator 跑出的 headline 结果不能安全写成 formal benchmark。
2. 当前 README 和测试对用户形成了错误引导。
3. 后续所有 compare、delta、L0-L3、replay-ready 读数都会先被 family 错位污染。

可能的终局思路：

1. 最小诚实修复：保留当前实现，但把 `live_runner.py` 明确重命名或文档降级为 `dev/demo runner`，并把 formal runner 单独暴露出来。
2. 合同对齐修复：正式分裂出 `formal_runner` / `formal_compare_runner` 与 `demo_live_runner`；formal 默认 family 只能指向 `formal_financial_family`；fixed-answer family 只能通过显式 flag 进入。
3. 容错式修复：允许一个总入口存在，但必须要求显式 `--tier formal|dev`，且无默认值；未指定时直接拒绝运行。

推荐终局：

1. 推荐第 2 条，直接把 formal 与 demo 入口分叉。
2. 如果短期不想拆 runner，至少先做第 3 条，避免继续靠默认值把 dev path 冒充 formal path。

验收标准：

1. formal benchmark 默认命令只会落到 `formal_financial_family`。
2. fixed-answer family 需要显式声明 `--tier dev` 或等价开关。
3. README、tests、sample docs 对 formal 和 demo 的命令示例完全分开。
4. compare 输出里有稳定字段表明 `benchmark_tier`、`task_family`、`claim_level`。

修改前的 claim discipline：

1. 在修完前，不应再宣称“当前默认 live/comparator 入口就是 formal benchmark”。

---

### Finding 2

严重度：High  
结论：StateBus lane 和 external lane 没有共享同一 scoring / quality-floor contract，当前 comparator 的 quality/headline delta 不可比。

合同/计划依据：

1. `docs/planning/statebus_4_role_comparator_contract_20260620.md:497-504` 要求 paired comparator 使用相同 scoring contract。
2. `docs/planning/benchmark_quality_floor_contract.md:21-28,75-90` 要求只有在 `quality_floor_pass == true` 后，成本 headline 才成立。

代码/测试位置：

1. `v2/benchmark/external_text_baseline.py:252-263`
2. `v2/runtime/smoke.py:356-399`
3. `v2/benchmark/fixed_answer_runner.py:203-223`
4. `v2/benchmark/comparator_runner.py:48-78`

详细问题说明：

1. external lane 的 quality floor 绑定在 exact route/tool match、no contamination、non-empty summary 上。
2. StateBus lane 的 quality floor 主要绑定在 summary_text、revenue_value、expected_facts 上，route/tool exactness 只是附加 metrics。
3. 这意味着两条 lane 的 `quality_floor_pass` 根本不是一回事。一个 lane 先看 routing fidelity，另一个 lane 先看 answer/fact coverage。
4. 在这种前提下继续计算 `quality_floor_pass_delta`、token delta、latency delta，本质上是在对不同判定口径做差值。
5. 这不是“指标还没完全收敛”，而是“分母不相同”，所以 formal delta 逻辑本身不成立。

为什么这违反合同/计划：

1. 合同要求 paired comparator 的 scoring contract 共用，不允许 lane-specific floor 再直接做 headline delta。
2. quality floor 的作用是“先对齐 correctness floor，再比成本”，不是“各自过各自的线，然后继续比成本”。

影响：

1. 当前 compare 报告中的 `quality_floor_pass_count`、`quality_floor_pass_delta` 不可信。
2. 任何 formal 成本优势都可能只是因为 external lane 被更严 floor 卡住，或者 StateBus lane 被更松 floor 放过。
3. benchmark 结论会天然偏向拥有更宽松 floor 的 lane。

可能的终局思路：

1. 统一 deterministic scorer：两条 lane 只共享一套样本级 scorer，分别输出 `route_tool_fidelity`、`answer_quality`、`contamination`，再由同一 quality floor 组合。
2. 保留 lane-specific diagnostics：可以保留 lane-specific debug metrics，但这些 debug metrics 不能驱动 headline。
3. 暂时停用 formal delta：如果短期来不及统一 scorer，就直接禁止 comparator 输出 headline delta，只输出并排诊断。

推荐终局：

1. 推荐第 1 条加第 2 条。
2. 在统一 scorer 完成前，应先执行第 3 条，停止对外输出 quality/cost delta。

验收标准：

1. 两条 lane 使用完全相同的样本 scorer 和 `quality_floor_pass` 逻辑。
2. compare 输出明确区分 `headline_metrics` 和 `debug_metrics`。
3. 只有在两条 lane 都 `quality_floor_pass == true` 时，才允许输出 token/latency/cost delta。
4. 测试覆盖 “一条 lane 未过 floor 时 headline delta 被禁止”。

修改前的 claim discipline：

1. 在修完前，不应把当前 compare 报告里的 cost delta 当 formal 证据。

---

### Finding 3

严重度：High  
结论：external pure-text baseline 不是干净的 external baseline，也不满足 4-role comparator contract。

合同/计划依据：

1. `docs/planning/statebus_4_role_comparator_contract_20260620.md:206-236,366-393,497-519` 要求两条 lane 共用四角色图，且 text lane 不得 import StateBus hidden helper。

代码/测试位置：

1. `v2/benchmark/external_text_baseline.py:21-24`
2. `v2/benchmark/external_text_baseline.py:123-143`
3. `v2/benchmark/external_text_baseline.py:217-233`
4. `v2/benchmark/external_text_baseline.py:239-244`

详细问题说明：

1. 当前 external baseline 直接 import `TaskCompiler`、`RetrieverFanoutPipeline`、`build_route_tool_surface`。
2. 这意味着所谓 external lane 并没有只消费“公共问题输入 + 公共语料/工具说明”，而是复用了内部编译器、内部 retrieval、内部 route/tool 候选构造。
3. 真实 LLM 调用只有 planner 和 summarizer 两次；Retriever 和 Executor 并没有作为独立 LLM role 存在。
4. 四角色 message log 只是事后伪造的文本记录，不是四角色真实执行路径。
5. 因此当前 external baseline 既不 external，也不 pure-text，更不是 4-role。

为什么这违反合同/计划：

1. 4-role comparator 的重点不是“最终都能回答”，而是“保持相同角色图，只改变 carrier”。
2. 一旦 text lane 直接复用 StateBus 内部 helper，比较对象就从“carrier 差异”变成了“helper 包装差异”。

影响：

1. 当前 external lane 无法作为 formal 对照组。
2. 当前 comparator 输出无法支持“StateBus 相对于 external pure-text baseline 的公平对比”。
3. 若继续保留这个命名，会持续误导后续读者和评审。

可能的终局思路：

1. 诚实降级：把当前实现重命名为 `assisted_text_wrapper_baseline`，只作为开发诊断工具，不再叫 external pure-text baseline。
2. 合同对齐重写：重写 external lane，只允许消费样本文本、公开语料、公开工具说明、公开评分器；四个 role 都通过文本 prompt 显式运行。
3. 折中方案：先保留两角色 wrapper，但 comparator 禁用这条 lane，直到真正的 external 4-role lane 补齐。

推荐终局：

1. 短期先做第 1 条或第 3 条，立刻停止错误 claim。
2. 中期做第 2 条，真正补齐公平 comparator。

验收标准：

1. external lane 不再 import `TaskCompiler`、`RetrieverFanoutPipeline`、`build_route_tool_surface` 等内部 helper。
2. external lane 的四个 role 都有独立 prompt、独立输入、独立输出和独立 telemetry。
3. external lane 与 StateBus lane 共用同一 scorer、同一 corpus、同一 tool description surface。
4. contamination 检查不是靠事后说明，而是可审计的输入来源控制。

修改前的 claim discipline：

1. 在修完前，当前 external lane 只能被称作“内部辅助文本基线”。

---

### Finding 4

严重度：High  
结论：fairness gate 不是 fail-closed，只是装饰性检测。

合同/计划依据：

1. `docs/planning/statebus_4_role_comparator_contract_20260620.md:698-730` 要求 fairness gate 在关键条件不满足时直接判比较无效。

代码/测试位置：

1. `v2/benchmark/external_text_baseline.py:92-107`
2. `v2/benchmark/external_text_baseline.py:203-247`
3. `v2/benchmark/comparator_runner.py:48-78`

详细问题说明：

1. 当前 `_fairness_gate()` 主要只扫 `sys.modules`，检查 external lane 有没有 import 某些模块。
2. 更关键的对象级条件，如共享角色图、共享 scorer、共享工具面、共享 oracle、共享 task family、共享 claim level，并没有真正校验。
3. 即使 fairness gate 失败，代码也只是把 `contamination_detected` 写进结果，不会中止比较，更不会阻断 headline delta。
4. 这让 gate 从“准入门槛”退化成了“事后注释”。

为什么这违反合同/计划：

1. 合同里的 fairness gate 是 fail-closed 机制，不是报告装饰字段。
2. 如果关键公平条件不满足，正确行为不是“继续算，然后附带说一下可能不公平”，而是“直接不允许形成 formal 结论”。

影响：

1. 当前 comparator 允许在已知不公平的情况下继续产出 delta。
2. 使用者很可能只看 headline，不会仔细看 contamination 字段。
3. 这会让不公平 benchmark 带着正式表格外观流出。

可能的终局思路：

1. 最小修复：当 fairness gate 失败时，compare 仍可执行，但必须只输出 `invalid_comparison`，禁止任何 delta/headline 字段。
2. 合同对齐修复：在 run 前生成 fairness manifest，逐项校验 family、roles、carrier、tool surface、scorer、oracle、history mode、claim level；任一不匹配则 fail-closed。
3. 分层修复：区分 `hard gate` 与 `soft diagnostics`，只有 soft diagnostics 允许继续输出非正式调试信息。

推荐终局：

1. 推荐第 2 条加第 3 条。
2. 在改完前，至少要先做第 1 条。

验收标准：

1. fairness gate 失败时 compare 结果没有 formal delta/headline。
2. fairness manifest 是落盘对象，可复查。
3. 测试覆盖 “carrier mismatch / scorer mismatch / family mismatch / gate failure”。

修改前的 claim discipline：

1. 在修完前，不应把 comparator 结果视为 formal fairness evidence。

---

### Finding 5

严重度：High  
结论：route/tool 选择被 runtime helper 预解了，Retriever/Executor 的语义决策被候选面和自动纠偏严重污染。

合同/计划依据：

1. `docs/planning/statebus_4_role_comparator_contract_20260620.md:266-273,295-325,408-411,444-482` 要求 route/tool 决策归属于角色路径，而不是被 hidden helper 预先解题。

代码/测试位置：

1. `v2/route_tool_catalog.py:39-54,129-198`
2. `v2/runtime/role_path.py:97-119,167-211,213-261`
3. `tests/v2/test_fixed_answer_and_external_baseline.py:233-275`

详细问题说明：

1. 当前 route/tool catalog 在进入 prompt 之前就已经计算了 `helper_rank`、`score`、`support_terms`、`matched_issue_ids`、`rationale`。
2. 这些字段不是中性 catalog，而是已经带有题目匹配结果和选择倾向的“答案接近物”。
3. `role_path` 里还会对 LLM 输出的错误 route/tool 做自动归一纠偏，回收到“最佳可见候选”。
4. 测试也把这种自动纠偏当作正确行为来验证。
5. 这等于 runtime 在 agent 做决定前先替它做了一轮窄化和修正。

为什么这违反合同/计划：

1. 合同要求的是角色在可见候选面内做决策，而不是 runtime 先替角色压缩候选并自动修错。
2. 一旦 helper 自带高强度匹配与纠偏，比较对象就变成“谁拿到了更强的 runtime assist”，而不是“谁在同等角色条件下更有效”。

影响：

1. Planner / Retriever / Executor 的 attribution 被污染。
2. role-level token / latency / prompt-bytes accounting 也被弱化，因为一部分真正的决策成本被移到了 helper。
3. external lane 更容易因为看不到这些 helper 而天然吃亏。

可能的终局思路：

1. 诚实降级：保留 helper，但显式标注这是 `assisted route/tool surface`，formal comparator 禁用。
2. 合同对齐：formal path 只允许暴露原始 route/tool catalog，不允许 `helper_rank`、`matched_issue_ids`、自动纠偏。
3. 工程折中：允许用轻量 top-k 缩减 prompt，但 top-k 只能基于样本公开 metadata 或 corpus namespace，不能基于答案导向特征；自动纠偏必须关闭。

推荐终局：

1. 推荐第 3 条作为迁移路径，第 2 条作为 formal end state。
2. fixed-answer dev family 可以继续保留更强 helper，但必须退出 formal comparator。

验收标准：

1. formal role path 中不再出现带答案倾向的 helper fields。
2. formal role path 对错误 route/tool 的处理是显式失败或显式低分，不是 silent correction。
3. role-level telemetry 能准确区分“模型做的决策”和“runtime 预先做的裁剪”。

修改前的 claim discipline：

1. 在修完前，当前 prompt/comparator 不应被描述为“只比较 carrier 差异”。

---

### Finding 6

严重度：High  
结论：formal L0 不是合同意义上的 pure-text baseline，`raw_evidence_bytes_seen_by_llm` 也不是按真实 prompt slice 计量。

合同/计划依据：

1. `docs/planning/statebus_v2_container_refactor_bootstrap_20260627.md:275-279` 定义了 L0 pure text cold baseline 到 L3 full replay 的正式分层。
2. `docs/planning/semantic_provenance_and_hydration_contract.md:262-347` 要求 `raw_evidence_bytes_seen_by_llm` 与 prompt slice 绑定，不能用近似总量替代。

代码/测试位置：

1. `v2/benchmark/minimal_runner.py:22-58,329-414`
2. `v2/runtime/driver.py:1038-1060`
3. `v2/runtime/smoke.py:345-353`
4. `v2/runtime/smoke.py:543-547`
5. `v2/runtime/smoke.py:746-780`

详细问题说明：

1. 当前 L0-L3 全部复用同一个 `run_smoke` 主链路。
2. 即使所谓 L0，仍然走 typed `ExecRequest` + UDS loopback，不是脱离 StateBus control plane 的 pure-text baseline。
3. `raw_evidence_bytes_seen_by_llm` 在 pruning-off 时直接被记成 full corpus bytes，但真正 prompt 还是只吃 `_evidence_text_from_retrieval()` 选出的 pack。
4. 这意味着指标名叫“raw evidence seen by llm”，实际却是“我们估算它理论上应该接触的 corpus 总量”。
5. 当前 L0-L3 更像内部 ablation flags，而不是合同意义上的层级基线。

为什么这违反合同/计划：

1. 合同里的 L0-L3 是为了解释不同系统能力层的净收益，不是简单关几个 flag。
2. 如果 L0 仍然保留 control plane、typed request 和内部 retrieval/smoke path，它就不是 pure-text baseline。
3. 如果 prompt bytes 不是按真实进入 prompt 的 slice 计量，那么 pruning gain 也不再是可审计指标。

影响：

1. 当前 waterfall 不能诚实支撑 “从 pure text 到 replay-ready” 的收益分层。
2. raw_evidence_bytes、pruning gain、carrier gain 之间的归因全部会混。
3. 对外解释时会给人一种“我们已经做了完整 formal ablation ladder”的误导。

可能的终局思路：

1. 立刻诚实修复：把当前 L0-L3 先改名为 internal ablation tiers，不再叫 formal L0-L3。
2. 合同对齐修复：实现真正的 L0 pure-text runner，完全不走 StateBus typed control plane；L1 只引入 control plane；L2 再引入 pruning；L3 再引入 replay。
3. 计量修复：无论哪条路径，都要改成从 prompt builder 真正截取每个 role 的 hydrated slice，再统计 bytes。

推荐终局：

1. 短期先做第 1 条，立刻止损。
2. 中期做第 2 条和第 3 条，才有资格恢复 L0-L3 命名。

验收标准：

1. L0 与 StateBus runtime 解耦，不走 typed `ExecRequest` + UDS loopback。
2. L1/L2/L3 每一层只新增合同定义的一种能力，不夹带别的变化。
3. `raw_evidence_bytes_seen_by_llm` 来源于真实 prompt slice，而不是 corpus 总量估算。
4. 测试覆盖“pruning off 但实际 prompt 仍然截断”的反例，防止回归。

修改前的 claim discipline：

1. 在修完前，当前 L0-L3 只能叫“内部消融层级”，不能叫 formal baseline ladder。

---

### Finding 7

严重度：High  
结论：replay-ready 与 cold-start 的 benchmark 目前是人工播种的 synthetic replay，不是连续任务自然复用。

合同/计划依据：

1. `docs/reference/题目.md:18-22` 要求通过连续任务证明共享记忆复用。
2. `docs/planning/replay_admissibility_contract.md:319-366` 要求 replay commit 建立在可追溯、可恢复、质量通过的历史产物上。

代码/测试位置：

1. `v2/benchmark/live_runner.py:86-89`
2. `v2/benchmark/fixed_answer_runner.py:66-89,173-190`
3. `v2/runtime/smoke.py:164-172`
4. `v2/runtime/smoke.py:633-689`
5. `v2/memory/store.py:97-169`

详细问题说明：

1. 当前 live runner 默认就是 replay-ready。
2. fixed-answer runner 会在 replay-ready 模式下自动 `seed_replay_memory`。
3. smoke path 里直接塞入 `mem-history-*` exact replay 候选。
4. runtime signature 还是硬编码占位，且 exact replay 候选召回仍有 embedding 相似度先导。
5. 这证明的不是“历史任务真实留下的可复用工件被后续任务合法命中”，而是“benchmark 在运行前人工埋了一个能命中的候选”。

为什么这违反合同/计划：

1. replay-ready 不是“人为预热一下就算”，而是要来自真实历史任务链条。
2. admissibility contract 不只关心命中，还关心命中的来源、签名相容性、artifact 可恢复性、历史质量门槛。

影响：

1. 当前 replay gain 不能作为正式历史复用证据。
2. cold-start 与 replay-ready 的分界被人为播种混淆。
3. 如果继续把这类结果写成 replay speedup，很容易被质疑为 benchmark engineering。

可能的终局思路：

1. 立即止损：benchmark 默认关闭 synthetic seed；保留 `--seed-replay-memory`，但标注为 dev-only。
2. 合同对齐修复：把 benchmark 改成两阶段。先跑一批历史任务并 commit 合格产物，再在后续连续任务上验证 replay-ready。
3. 进一步修复：真实采集 `RuntimeCompatibilitySignature`，exact replay key 只看合同字段，不混 embedding，embedding 只用于 candidate recall。

推荐终局：

1. 短期先做第 1 条。
2. 中期做第 2 条和第 3 条，形成真正的历史任务 replay benchmark。

验收标准：

1. 默认 benchmark 模式是 cold-start。
2. replay-ready 模式必须引用真实历史 run 输出的 artifact/state/ledger，而不是合成 seed。
3. runtime signature 由真实环境采集，不再硬编码占位。
4. exact replay key 与 embedding 召回严格分家，且有测试覆盖。

修改前的 claim discipline：

1. 在修完前，当前 replay-ready 只能叫 synthetic replay probe，不能叫 formal replay evidence。

---

### Finding 8

严重度：Medium  
结论：Planner 显式存在，但执行顺序和职责边界与合同不符，Retrieval 先于 Planner，replan/fallback 又归 runtime supervisor。

合同/计划依据：

1. `docs/planning/task_compiler_contract.md:54-67` 要求 `TaskCompiler` 在 Planner 前，但 Planner 负责形成 retrieval objective。
2. `docs/planning/statebus_4_role_comparator_contract_20260620.md:254-284` 规定四角色边界。
3. `docs/planning/statebus_v2_container_refactor_bootstrap_20260627.md:167-169` 也强调 planner 与 runtime/supervisor 的职责不能混写。

代码/测试位置：

1. `v2/runtime/smoke.py:539-624`
2. `v2/runtime/smoke.py:746-755`
3. `v2/runtime/driver.py:163-195`
4. `v2/runtime/driver.py:223-229`
5. `v2/runtime/driver.py:371-447`

详细问题说明：

1. 当前 smoke path 是先跑 `RetrieverFanoutPipeline`，之后才跑 planner。
2. 这样 planner 获得的是 retrieval 后的证据包，而不是先对任务做规划再给 retrieval objective。
3. runtime driver 还承担了 trap/replan/fallback 的流程编排，并累计 `planner_replan_count`。
4. `planner.compile` 被混写成 workflow 里的 planner step，而真正的 LLM planner 没有处于严格的正式 step 链位置。
5. 这让 planner、compiler、runtime supervisor 三层的边界都不清晰。

为什么这违反合同/计划：

1. 合同允许 compiler 在 planner 前做 schema 规范化，但不允许 retrieval 抢在 planner 前定义检索目标。
2. replan/fallback 的语义归属 planner，不应由 runtime driver 代持，再把指标记回 planner 头上。

影响：

1. planner token / latency / replan attribution 不可信。
2. 四角色图被 runtime helper 与 workflow step 混写，后续 comparator 更难公平。
3. 如果未来补 telemetry，很容易继续沿着错误边界累积错误指标。

可能的终局思路：

1. 诚实降级：承认当前是 retrieval-first assist pipeline，不再强说 planner 在主导。
2. 合同对齐修复：`TaskCompiler -> Planner -> Retriever -> Executor -> Summarizer` 严格主链；replan objective 和 fallback ownership 回到 planner。
3. 渐进迁移：保留极轻量 pre-retrieval 只做 corpus scoping，不做 answer-bearing evidence selection；真正 retrieval objective 仍由 planner 决定。

推荐终局：

1. 推荐第 3 条作为迁移步骤，第 2 条作为最终目标。

验收标准：

1. Planner 在主链上早于 Retriever，至少先生成 retrieval objective 或 route intent。
2. runtime 只负责 transport/state/attempt lifecycle，不替 planner 做 replan 语义决策。
3. planner token/latency/replan_count 的来源和归属可审计。

修改前的 claim discipline：

1. 在修完前，当前 Planner 只能算“显式存在但职责混杂”，不能叫严格四角色 Planner。

---

### Finding 9

严重度：Medium  
结论：TaskCompiler / CanonicalTaskSpec strict path 只有首版骨架，formal benchmark 仍主要依赖 runtime JSON blob 编译。

合同/计划依据：

1. `docs/planning/task_compiler_contract.md:23-46,165-184,243-255` 要求 strict benchmark 优先消费预编译 `CanonicalTaskSpec`，失败即拒绝执行。

代码/测试位置：

1. `v2/runtime/compiler.py:21-45`
2. `v2/runtime/compiler.py:61-99`
3. `v2/runtime/smoke.py:525-537`
4. `v2/benchmark/minimal_runner.py:107-120,273-282`
5. `v2/benchmark/fixed_answer_runner.py:103-117,181-189`

详细问题说明：

1. 当前 compiler 确实区分 strict reject 和 interactive fallback，这是实装。
2. 但 `_canonical_from_mapping()` 对 `task_family`、`intent_op`、`required_outputs`、`required_tools` 没有强 enum 约束。
3. formal benchmark runner 大多还是把样本里的 JSON request 在运行时现场编译成 spec，而不是直接读取预编译 `canonical_task_spec.json`。
4. 这让 strict path 虽然存在，但缺少“冻结 spec”带来的稳定性。
5. 一旦 schema 解释仍然依赖 runtime 编译过程，replay key、task family 统计、prompt routing 都更容易漂移。

为什么这违反合同/计划：

1. 合同把 strict path 的目标定成“预编译 spec + runtime 只校验”，不是“运行时再编译一遍，但失败就报错”。
2. 没有硬枚举约束时，formal family 的关键语义仍可能被输入自由发明。

影响：

1. formal benchmark 的可复验性不足。
2. CanonicalTaskSpec 的 hash/stability 价值被削弱。
3. 后续 exact replay key、family analytics、quality floor 统计都会吃到 schema 漂移风险。

可能的终局思路：

1. 先补样本资产：每个 formal sample 附带预编译 `canonical_task_spec.json`。
2. strict compiler 退到 validator：strict path 只做 schema 验证、enum 校验、hash 复算，不再做自由编译。
3. interactive/dev path 保留当前 heuristic fallback，和 formal path 显式分叉。

推荐终局：

1. 推荐三条一起做，尤其是第 1 条和第 2 条。

验收标准：

1. formal runner 从磁盘加载预编译 `CanonicalTaskSpec`。
2. strict path 的非法 enum、未知 family、未知 tool/output 直接拒绝。
3. interactive fallback 只能在非 formal path 触发。

修改前的 claim discipline：

1. 在修完前，TaskCompiler 只能叫“strict/interactive 双路径首版”，不能叫“formal strict fully enforced”。

---

### Finding 10

严重度：Medium  
结论：telemetry 和 runtime state machine 目前是 harness 版，不是合同要求的 runtime-fact / benchmark-ready / dashboard-ready 分层实现。

合同/计划依据：

1. `docs/planning/telemetry_event_contract.md:72-107,174-197,277-323`
2. `docs/planning/runtime_state_machine_contract.md:97-159,194-245,246-306`

代码/测试位置：

1. `v2/runtime/telemetry.py:60-112`
2. `v2/runtime/smoke.py:919-985`
3. `v2/runtime/driver.py:586-862`
4. `v2/runtime/supervisor.py:46-125`
5. `v2/control/transport.py:78-225`
6. `v2/control/messages.py:63-120`

详细问题说明：

1. 当前 telemetry 主要是内存聚合对象。
2. smoke path 只落一个 JSON array 文件，不是合同里的 jsonl + sqlite 双层。
3. driver 的事件名和合同不完全一致，缺 `STEP_DISPATCHED`、`GC_ISSUED`、`ARTIFACT_PUBLISHED`、`ARTIFACT_RESTORED` 等关键事件。
4. transport/supervisor 没有真正的 ACK / heartbeat timeout enforcement。
5. control message 也缺少一些冻结字段，如 `worker_id`、`worker_pid`、`stderr_preview`、`traceback_ref` 或 `traceback_preview`。
6. 这说明现在更像 benchmark harness telemetry，而不是审计级 runtime telemetry。

为什么这违反合同/计划：

1. 合同要求的是三层口径：runtime-fact、benchmark-ready、dashboard-ready。
2. 当前实现直接把执行事实、benchmark 汇总、展示字段揉在一起，既不利于审计，也不利于稳定二次聚合。

影响：

1. 无法严格支撑 latency、replay、artifact lifecycle 的正式审计。
2. 未来一旦出现异常事件，很难从 telemetry 重建准确生命周期。
3. comparator 和 runtime 的数据口径容易互相污染。

可能的终局思路：

1. 诚实降级：先在文档中明确这是 harness telemetry，不作正式 claim。
2. 分层修复：先实现 runtime-fact jsonl，再实现 benchmark aggregation，再实现 dashboard projection。
3. 事件对齐修复：补齐合同事件名、冻结字段、ACK/heartbeat timeout enforcement。

推荐终局：

1. 推荐第 2 条和第 3 条。
2. 在未完成前应同步做第 1 条。

验收标准：

1. 原始事件按 runtime-fact jsonl 落盘，可追加、可回放。
2. benchmark 汇总不是运行时原始事件的直接替身，而是第二层聚合。
3. 事件名、字段、超时语义与合同一致。
4. 关键异常场景能从 telemetry 单独复盘。

修改前的 claim discipline：

1. 在修完前，当前 telemetry 只能叫 harness/demo telemetry。

---

### Finding 11

严重度：Medium  
结论：非文本状态、provenance、semantic pruning 已有正式对象，但仍是 first-pass，不是严格主链路。

合同/计划依据：

1. `docs/planning/semantic_provenance_and_hydration_contract.md:55-79,255-347`
2. `docs/planning/statebus_4_role_comparator_contract_20260620.md:444-482`

代码/测试位置：

1. `v2/refs/models.py:50-205`
2. `v2/provenance/hydration.py:79-242`
3. `v2/retrieval/pipeline.py:288-298`
4. `v2/retrieval/pipeline.py:326-375`
5. `v2/runtime/smoke.py:553-565`
6. `v2/runtime/role_path.py:133-145,174-181,221-231,274-284`

详细问题说明：

1. `SemanticStateRef`、`HydrateManifest`、`CanonicalEvidencePack` 这些对象已经实装，且有清楚的类型边界。
2. 但 runtime 主链里真正传递的 semantic state 主要只是 query embedding。
3. role prompt 里仍大量直接灌入 evidence_text，而不是围绕 hydrate manifest 和 prompt slice 做按需回填。
4. retrieval pipeline 里的 raw bytes 更接近 bundle 级估计值，不是 per-role hydrated slice 统计。
5. 所以当前非文本状态更像“旁路辅助元数据 + first-pass typed provenance”，而不是严格进入主链路的 carrier reduction 机制。

为什么这违反合同/计划：

1. 合同要的是“可追溯的非文本状态 + 按需 hydrate + prompt-slice accounting”。
2. 现在 typed object 有了，但 prompt 真正消耗的仍是大段文本证据，所以 semantic pruning 的主链地位还没有成立。

影响：

1. 可以证明“我们有 typed provenance/object model”，但不能证明“我们已经靠非文本状态显著替代文本 prompt”。
2. 如果继续把这部分写成强创新点，会被质疑为对象层实装和效果层实装混淆。

可能的终局思路：

1. 先降 claim：把当前表述固定为 first-pass semantic provenance / pruning path。
2. 主链修复：对每个 role 记录实际 hydrated prompt slice，按 role 落盘 slice ref 与 byte count。
3. 能力扩展：在第 2 条稳定后，再扩展更丰富的非文本状态，而不是先扩对象种类。

推荐终局：

1. 推荐先做第 2 条，再考虑第 3 条。

验收标准：

1. 每个 role 的 prompt slice 都有 provenance / hydration 记录。
2. `raw_evidence_bytes_seen_by_llm` 来自真实 slice，而非 bundle 估算。
3. `SemanticStateRef` 与 `ExecutionArtifactRef` 的边界继续保持独立，不回退到 vague ref。

修改前的 claim discipline：

1. 在修完前，这部分只能叫 typed provenance + first-pass pruning，不应叫成熟的 non-text mainline。

---

### Finding 12

严重度：Medium  
结论：CodeAct 目前是受控 workspace 内的固定脚本执行器，不是多轮 agentic CodeAct。

合同/计划依据：

1. `docs/reference/题目.md:25-26` 只是鼓励 CodeAct。
2. `docs/planning/execution_artifact_and_workspace_contract.md:49-77,302-350,356-389` 要求的是受控 workspace、artifact contract、validator path 与保守 claim。

代码/测试位置：

1. `v2/runtime/codeact.py:234-309`
2. `v2/runtime/codeact.py:311-387`
3. `v2/runtime/codeact.py:412-566`
4. `v2/runtime/smoke.py:782-806`

详细问题说明：

1. 当前 CodeAct plan 是静态 stage/action 模板。
2. runtime 会写 request、plan、script 后本地 subprocess 执行，这是真实 executor，不是 mock。
3. 但执行脚本是固定模板生成，不含多轮 LLM 生成代码、失败分析、修复循环、工具搜索或反思。
4. 所以它解决的是“如何在 workspace 内执行受控动作并产出 artifact”，不是“如何进行 agentic 编程型执行”。

为什么这违反合同/计划：

1. 严格说并没有违反合同底线，因为合同本身对 CodeAct 只是鼓励、不是强制。
2. 真正的问题在 claim 强度：如果把当前实现说成成熟 CodeAct，就超出了代码事实。

影响：

1. 对内会误导后续设计优先级，以为 CodeAct 已经成熟，只差调参。
2. 对外会让评审把当前实现和真正多轮 agentic executor 对标，风险很高。

可能的终局思路：

1. 保守终局：继续把它定义为 `workspace executor` 或 `CodeAct first-pass executor`。
2. 中间终局：在当前基础上补 validator 驱动的失败修复循环，但仍不宣称 fully agentic。
3. 强终局：补多轮 LLM 生成代码、执行反馈、修复迭代、最小工具搜索边界，形成真正 agentic CodeAct。

推荐终局：

1. 短期推荐第 1 条。
2. 如果 benchmark 真需要更强执行能力，再做第 2 条。
3. 第 3 条不是当前 formal 合同闭环的前置条件，不应优先于 comparator/fairness/replay 修复。

验收标准：

1. 在 README、benchmark、review 文档里统一把当前实现称作 first-pass executor。
2. 若补修复循环，需单独增加 artifact/validator/attempt telemetry。
3. 在出现多轮 LLM 代码生成与修复前，不再使用“agentic CodeAct”作为默认表述。

修改前的 claim discipline：

1. 当前只能 claim “first-pass workspace executor + artifact pipeline”。

---

## 4. Coverage Matrix

| 对象 | 分类 | 当前判断 | 关键依据 | 下一步重点 |
| --- | --- | --- | --- | --- |
| Planner role | 有明显偏差/问题 | 类与 prompt 存在，但顺序错、职责混，replan 归 runtime | `v2/runtime/smoke.py:539-624,746-755`; `v2/runtime/driver.py:371-447` | 把 planner 放回 retrieval 前，并收回 replan ownership |
| 4-role comparator | 有明显偏差/问题 | 两条 lane 不是同图、同打分、同 helper 约束 | `v2/benchmark/comparator_runner.py:48-78`; `v2/benchmark/external_text_baseline.py:21-24,252-263` | 重建 comparator contract，先禁 formal delta |
| external pure-text baseline | 有明显偏差/问题 | 复用内部 helper，只有 2 个真实 LLM role | `v2/benchmark/external_text_baseline.py:123-143,217-244` | 先降级命名，再重写真实 external 4-role lane |
| TaskCompiler | 部分实现 | strict reject / interactive fallback 已做，但 formal strict 仍依赖 runtime JSON 编译 | `v2/runtime/compiler.py:21-45,61-99` | formal sample 附 precompiled spec；strict path 只做校验 |
| CanonicalTaskSpec | 部分实现 | 对象与稳定 hash 有了，但不是预编译样本驱动，也缺硬枚举约束 | `v2/runtime/compiler.py:61-99`; `v2/benchmark/minimal_runner.py:107-120` | 冻结样本 spec 并加强 enum 约束 |
| Runtime state machine | 部分实现 | lifecycle/attempt 结构存在，但 ACK/heartbeat/GC 语义不全 | `v2/runtime/driver.py:586-862`; `v2/runtime/supervisor.py:46-125` | 对齐合同事件与超时 enforcement |
| Telemetry events | 部分实现 | 事件对象存在，但还是 harness 聚合，不是正式三层口径 | `v2/runtime/telemetry.py:60-112`; `v2/runtime/smoke.py:919-985` | 补 jsonl + sqlite，分 runtime-fact / benchmark / dashboard |
| Semantic pruning | 骨架偏多 | typed object 已有，prompt-slice accounting 仍不严格 | `v2/provenance/hydration.py:79-242`; `v2/runtime/role_path.py:133-145,174-181,221-231,274-284` | 补 per-role hydrated slice 审计 |
| ExecutionArtifactRef | 严格实现 | 已独立成正式 ref family，具备 manifest/root_id/relpath/commit lifecycle | `v2/refs/models.py:132-205`; `v2/runtime/execution.py` | 保持边界，避免回退成 vague ref |
| Replay admissibility | 部分实现 | exact key 不混 embedding 是正确方向，但 history 来源、signature、benchmark 用法仍偏 first-pass | `v2/runtime/smoke.py:164-172,633-689`; `v2/memory/store.py:97-169` | 去 synthetic seed，改真实历史任务 replay |
| Quality floor | 部分实现 | deterministic/fact coverage/commit gate 已串，但双 lane comparator 口径不一致 | `v2/benchmark/fixed_answer_runner.py:203-223`; `v2/benchmark/external_text_baseline.py:252-263` | 统一 scorer，再恢复 headline |
| CodeAct | 骨架偏多 | 真实 workspace/artifact 路径已连通，但仍是固定模板执行器 | `v2/runtime/codeact.py:234-566` | 降 claim；若需要再补 validator loop |
| Formal benchmark family | 有明显偏差/问题 | formal family 存在，但不是默认 live/compare 入口 | `v2/benchmark/live_runner.py:16-18,36-49,109-149` | formal/demo 入口彻底分叉 |

---

## 5. Open Questions

下面这些问题无法仅凭当前仓内代码完全确认，但会影响修复方案的力度和顺序：

1. 是否存在仓外 CI wrapper、容器 entrypoint 或发布脚本，实际上已经把 `formal_financial_family` 作为正式默认入口，而不是 `v2/benchmark/live_runner.py`？
2. 是否存在尚未提交到当前 worktree 的独立 external pure-text baseline 实现？如果有，应先核对它是否比仓内版本更接近 comparator contract。
3. 是否存在独立的 runtime signature 采集器、jsonl/sqlite telemetry sink、或 openEuler 环境验证脚本，只是目前未并入 `v2/`？
4. formal financial family 是否计划扩充成连续任务链条？如果没有，replay-ready 的正式验证样本集需要重新设计。

---

## 6. Recommended Corrections

这一节只给高优先级修正建议，按建议顺序排列。每条都标注是“合同对齐修复”还是“性能/工程优化”。

### 6.1 先止损：formal 与 dev 彻底分叉

类型：合同对齐修复

1. 把 formal benchmark 入口与 demo/live comparator 入口分叉。
2. formal 默认 family 只能指向 `formal_financial_family`。
3. fixed-answer family 明确降级为 dev/demo。
4. 在这一步完成前，停止把默认 live/comparator 结果写成 formal headline。

这是第一优先级，因为它会影响所有后续结果的解释口径。

### 6.2 comparator 先停错，再重建

类型：合同对齐修复

1. 先让 fairness gate 和 quality gate fail-closed。
2. gate 失败或任一 lane `quality_floor_pass == false` 时，直接禁止输出 formal delta/headline。
3. 然后重建 comparator，使两条 lane 真正共享同一 4-role 图、同一 scorer、同一 tool/corpus surface。

如果不先做这一步，后面的调优都会建立在不公平 compare 之上。

### 6.3 停止把当前 external lane 叫 external pure-text baseline

类型：合同对齐修复

1. 在真正重写前，把当前实现明确降级为 assisted text wrapper baseline。
2. 不要再让它承载 formal comparator。
3. 之后再补真正的 external 4-role lane。

### 6.4 停止把当前 L0-L3 叫 formal baseline ladder

类型：合同对齐修复

1. 如果暂时做不了真实 pure-text L0，就不要继续沿用 L0-L3 的 formal 命名。
2. 当前实现更适合叫内部 ablation tiers。
3. 待真实 pure-text L0、prompt-slice bytes accounting 补齐后，再恢复正式命名。

### 6.5 去掉 synthetic replay benchmark 默认路径

类型：合同对齐修复

1. 从 benchmark 默认路径移除 synthetic replay seeding。
2. replay-ready 必须来自真实历史任务、真实 artifact/state、真实 runtime signature。
3. 在真实历史链条没有补齐前，只能保留 dev-only seed 模式。

### 6.6 把 Planner 放回它该在的位置

类型：合同对齐修复

1. Planner 应回到 Retriever 之前。
2. fallback/replan ownership 应从 runtime supervisor 回归 planner。
3. `planner.compile` 不应继续混写成正式 planner role step。

### 6.7 把 strict benchmark 真正绑定到预编译 CanonicalTaskSpec

类型：合同对齐修复

1. formal strict 样本应随文件附带预编译 `canonical_task_spec.json`。
2. strict path 只做校验，不做现场 JSON request 自由编译。
3. 同时补齐硬枚举约束。

### 6.8 把 telemetry / provenance 升到合同口径

类型：合同对齐修复

1. 补 `LLM_CONTEXT_SLICE` 审计。
2. 补 jsonl + sqlite 双落盘。
3. 对齐合同事件名和冻结字段。
4. 把 runtime-fact / benchmark-ready / dashboard-ready 三层彻底拆开。

### 6.9 降低创新点表述强度，直到代码事实跟上

类型：性能/工程优化前的口径修复

1. 在多轮生成代码、失败修复循环、真实非文本主链、真实 replay-ready benchmark 没补齐前，把 CodeAct、semantic pruning、replay innovation 的对外 claim 全部降到 `first-pass` / `prototype` 级别。
2. 这不是保守过度，而是防止表述先于实现。

---

## 7. 依赖关系与建议改造顺序

下面给出一个更适合实际落地的整改顺序。重点不是“哪里最有趣”，而是“哪里最影响合同口径”。

### Phase 1: 口径止血

目标：先停止错误 headline。

1. 分叉 formal 与 demo 入口。
2. comparator 改成 fail-closed。
3. external lane 改名或退出 formal compare。
4. L0-L3 改名为 internal ablation tiers。
5. synthetic replay 改成 dev-only。

这一阶段完成后，可以诚实说：

1. 仓内存在 dev harness 与 prototype benchmark。
2. formal 入口正在重新冻结。

这一阶段完成前，不应再发任何 formal delta。

### Phase 2: formal benchmark 地基

目标：把 formal benchmark 的输入、评分、对照组三件事做实。

1. formal sample 附预编译 `CanonicalTaskSpec`。
2. 两条 lane 共享同一 deterministic scorer。
3. 重写真实 external pure-text 4-role lane。
4. formal family 只使用冻结 financial family。

这一阶段完成后，才有资格重新谈 formal comparator。

### Phase 3: 角色边界与 prompt 公平性

目标：把真正属于角色路径的决策从 runtime helper 手里拿回来。

1. Planner 前置，Retriever 后置。
2. route/tool helper 去答案导向字段。
3. 关闭 silent correction。
4. 把 role-level token/latency/prompt-bytes accounting 绑定回真实 role。

这一阶段完成后，四角色比较才开始有解释力。

### Phase 4: replay 与 telemetry 严格化

目标：让 replay 和运行时事实都可审计。

1. replay-ready 改成真实历史任务链。
2. 真实采集 runtime signature。
3. telemetry 改成 runtime-fact jsonl + benchmark aggregate + dashboard projection。
4. 补 ACK/heartbeat timeout enforcement。

这一阶段完成后，replay gain 和 runtime lifecycle 才能作为正式证据。

### Phase 5: 创新点做强，而不是先说强

目标：让 non-text pruning 和 CodeAct 从 first-pass 走向可验证能力。

1. 实做 per-role prompt slice / hydrate accounting。
2. 再扩 richer semantic state。
3. 若确实需要，再补 validator-driven CodeAct repair loop。

这一阶段不是当前最前置的工作，因为在 formal comparator 和 replay 路线没修正前，强化创新点不会先解决口径问题。

---

## 8. 最后结论

这次审查最关键的结论不是“`v2` 做得少”，而是“`v2` 有一批真实实现，但 formal 口径、fairness 口径、innovation 口径都比代码事实更强”。

因此整改优先级不应是先继续加功能，而应是：

1. 先把 formal 与 dev 的边界切开。
2. 再把 comparator、公平性、strict benchmark、replay provenance 这些基础合同做实。
3. 最后再增强 CodeAct、semantic pruning 等可选亮点。

如果按这个顺序推进，`v2` 后续可以逐步恢复更强 claim；如果不先处理这些口径性问题，即使继续加代码，也很难得到可信的 formal benchmark 叙事。

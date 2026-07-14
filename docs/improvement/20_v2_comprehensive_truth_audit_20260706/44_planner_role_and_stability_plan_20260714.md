# StateBus v2 Planner 真实职责与稳定改进方案

日期：2026-07-14  
事实数据：`43_full_qwen3_extended_audit_20260714.json`  
配套审计：`43_full_qwen3_extended_audit_20260714.md`  
状态：已实施并完成定向验证；未启动新的 16-stage full matrix

## 0. 实施状态更新

本文第 2-18 节保留 2026-07-13 extended run 的修复前审计和原始设计依据。其描述的“当前 Planner”均指修复前实现，不应覆盖解释为修复后的运行事实。修复后的结构化结果见 `45_planner_kv_replay_fix_results_20260714.json`，人工可读报告见 `45_planner_kv_replay_fix_results_20260714.md`。

本轮没有停留在 Phase 方案。Phase 1 可观测性、bounded `SemanticTaskPlan`、受限 Retriever 消费、disabled/perturbed ablation、genericity gate 修正、vLLM V0 prefix counter exporter 和 replay identity 修复均已落地。Runtime 仍固定掌握四步拓扑、route/tool 闭集、replay gate、fallback、lease 和 GC。

定向验证结论：

- Planner local vLLM gate：primary、original/paraphrase、disabled、perturbed 共 16 次执行，4 个 primary case、4 个 paraphrase comparison、4 个 disabled case、4 个 perturbed case 均通过对应 gate。disabled 全部为 `runtime_fallback` 且 behavioral effect 为 false；perturbed 全部改变 effective/consumed hash 且 behavioral effect 为 true；route/tool 保持稳定。
- KV prefix probe：4/4 serialized alternating-order pair gate 通过，40/40 请求和 JSON contract 通过，40/40 task-local counter delta 有效。shared 为 5,458 hits / 6,996 queries，independent 为 0 / 7,200；shared warm TTFT median 267.06 ms，independent 2,282.89 ms。
- Replay：incident L3 10/10 quality pass；round 3/4/6/7/8/9/10 为 exact replay，round 2/5 为 validated replay，无 missing/unexpected round。
- Docker 定向回归：`128 passed in 469.01s`。日志 SHA256 为 `9d905e6f1930d091433a2b80f49f785b279a2c69f49d405834adbacc090b3553`。

声明边界没有放宽：Planner holdout 仍基于预编译 `CanonicalTaskSpec`，不证明自由文本 spec 编译泛化；KV 只证明同一 vLLM engine 内 block prefix reuse 和 TTFT 差异，不是 hidden-state/KV tensor transfer，也不是 StateBus 端到端加速；本轮没有运行完整 16-stage matrix。

## 1. 结论先行

StateBus 不需要让 Planner 动态生成任意 DAG。稳定架构可以继续固定为：

```text
Planner -> Retriever Fan-out -> Executor -> Summarizer
```

Runtime 继续掌握拓扑、能力注册、工具白名单、replay gate、fallback、lease、持久化和 GC。Planner 的真实职责应收敛为“bounded semantic planning”：解析任务语义，为 table/semantic/memory retrieval 生成不同的受限 objective，声明 required evidence 和 required outputs，并把可校验、可追踪的语义计划交给固定 pipeline。

修复前 Planner 尚未承担这一职责。该 extended run 证明它被调用并产生/保存 payload，但没有一个 case 产生模型 `retrieval_objective`，也没有 disabled/perturbed ablation 证明 Planner 模型输出改变下游行为。修复前 `planner_generated_retrieval_objective_count=1` 是硬编码误归因，Stage 08 的 `planner_workflow_step_count>=3` 也是错误验收标准。

## 2. 当前 Planner 的五层事实

| 层次 | 本 run 结论 | 证据 |
| --- | --- | --- |
| Planner 被调用 | 是，359/359 workspace | `task_metrics.planner_call_count=1` |
| Planner 产生数据 | 是，compact echo或steps payload | `planner_handoff.planner_plan_payload` |
| 数据被保存/透传 | 是，359 handoff，359 result roundtrip | `inputs/planner_handoff.json`、`outputs/result.json` |
| 数据被下游读取 | final fallback objective被Retriever读；plan payload被CodeAct/driver携带 | `smoke.py:1880, 2425, 2670` |
| 模型数据改变行为 | 当前无证据 | model objective 0；无A/B；固定workflow |

“被下游读取”不能自动升级为“改变行为”。本轮实际被 Retriever消费的是 merge 后的 final objective，而不是可确认来自模型的 objective。

## 3. 当前 Planner 实际输出

### 3.1 Artifact 观察

359 个 `planner_plan_payload` 主要有两种规范化形态：

1. compact echo：键为 `g/h/q/rr/sp/t/tf`。它回显 Runtime 已给出的 goal、query、required roles、shared-prefix描述、required tools和task family。
2. `steps`：通常 3-5 个简化 step；但这些 step不控制 Runtime DAG。

所有 359 个 `planner_plan_payload` 都没有 `retrieval_objective`。模型生成 objective case数=0、字段数=0。raw Planner completion没有单独持久化，因此只能复核规范化后的 payload，不能重建原始文本和 fallback前状态。

代表 artifact：

- `stages/06_formal_full/workspaces/L3/benchmark-sample-1/inputs/planner_handoff.json`
- `stages/06_formal_full/workspaces/L3/formal-agg-003/inputs/planner_handoff.json`
- `stages/08_genericity_holdout/workspaces/genericity-formal-agg-004/inputs/planner_handoff.json`

### 3.2 代码生成链

Planner prompt本身由 Runtime构造 `g/q/h/t/rr/tf/e`，见 [role_path.py](/home/qcrs/statebus/project/v2/runtime/role_path.py:1216)。`plan_workflow()` 对 completion规范化后，即使模型没有 objective，也补：

- `query_text`：Runtime输入；
- `required_tools`：Runtime tags；
- `candidate_keys`：Runtime visible candidates。

证据为 [role_path.py](/home/qcrs/statebus/project/v2/runtime/role_path.py:1265)。随后 `run_smoke()` 继续合并：

1. `_planner_scope_payload()`：evidence text/table、source hashes、history artifact summaries；
2. `build_retrieval_objective()`：goal、query、task family、intent、required tools、required outputs；
3. `planner_result.retrieval_objective`：本 run仅包含上述 fallback，模型字段为0。

合并点见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:1868)，默认 objective构造见 [role_path.py](/home/qcrs/statebus/project/v2/runtime/role_path.py:1069)。

## 4. `workflow_payload` 与 `planner_plan_payload` 的真实作用

`workflow_payload` 是 `PlannerRoleResult` 中的内存名称；落盘后对应 `planner_plan_payload`。它目前被：

- 写入 `planner_handoff.json`；
- 计算 handoff/hash；
- 写入 CodeAct request；
- 写入 CodeAct/result payload；
- 写入 Runtime driver Planner step payload；
- 写入 replay key material。

代码搜索显示 `planner_plan_payload` 在 CodeAct/data-task 中只被读取后重新写入 output，没有逻辑根据其 `steps/g/q/...` 改变 plan action、route、tool或required outputs。CodeAct request中的 `required_outputs/task_family/intent_op/spec_arguments/quality_checks/route/tool_name` 都由 CanonicalTaskSpec、Retriever/Executor和 Runtime单独提供，见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2391)。

所以当前最精确的说法是：`planner_plan_payload` 被持久化、hash和透传；尚未证明它驱动 Runtime或CodeAct。

## 5. Retrieval objective 字段来源

| 字段类别 | 例子 | 当前来源 | 模型来源证据 |
| --- | --- | --- | --- |
| evidence scope | text/table context、doc hashes、history summaries | `_planner_scope_payload()` | 无 |
| semantic task | goal、task_family、intent_op | `build_retrieval_objective(spec)` | 无 |
| output contract | required_outputs、required_tools | CanonicalTaskSpec | 无 |
| query | query_text | spec生成 + `plan_workflow()` fallback | 无 |
| candidate constraint | candidate_keys | visible candidate fallback | 无 |

因此 `objective_source` 在本 run应是 `runtime_fallback`，不是 `model_generated`，也不是 `hybrid`。

## 6. Retriever 到底消费什么

Retriever pipeline真实消费 final objective 的：

- `query_text`：写入临时 spec `arguments.request_text`，并作为 query embedding/retrieval query；
- normalized scope/evidence context：进入 candidate filter、pool和evidence pack；
- `candidate_keys` 和 `required_tools`：在 fan-out后约束 Retriever/Executor可见闭集。

入口见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:1880)，candidate约束见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2026)，pipeline normalization/filter见 [pipeline.py](/home/qcrs/statebus/project/v2/retrieval/pipeline.py:925)。

但是 artifact没有 `retriever_consumed_objective_hash`，只能用代码路径和 query相等性证明读取，不能逐 case证明消费的是哪一版本 objective。这正是 Phase 1要补的观测字段。

三个 Retriever 没有各自 Planner objective。pipeline固定调用 lexical/semantic/table，见 [pipeline.py](/home/qcrs/statebus/project/v2/retrieval/pipeline.py:978)；三路共享同一 normalized scope/query。memory lookup在后续 Runtime memory/replay路径，不是 Planner拆出的第四路 Retriever。

## 7. 为什么 zero-step Planner 仍能完成任务

Runtime 在 [driver.py](/home/qcrs/statebus/project/v2/runtime/driver.py:206) 无条件安装四步 workflow：

1. `planner.plan`
2. `retriever.fanout`
3. `executor step`
4. `summarizer.commit`

模型 `steps` 不参与 attach workflow。因此 Stage 06 有 76/100 zero-step payload、Stage 08 有 4/4 zero-step payload，任务仍然完成是设计的直接结果，不是异常。把 `planner_workflow_step_count>=3` 作为 genericity gate，相当于用一个不控制 Runtime的展示字段阻断正式实验。

## 8. 与历史 tag 的关系

对 `v2-non-kv-baseline-20260710` 做 AST function hash比较：

| 函数 | 当前 working tree | tag | 是否相同 |
| --- | --- | --- | --- |
| `build_default_workflow` | `61ba11...520c2` | 同值 | 是 |
| `build_retrieval_objective` | `841a49...6ab2` | 同值 | 是 |
| `plan_workflow` | `2e2013...c849` | 同值 | 是 |

tag中也已有硬编码 `planner_generated_retrieval_objective_count=1`。所以当前 Planner不是相对 tag的新行为回归；它是历史固定 workflow + fallback objective设计的延续。当前新增指标暴露了问题，但 `planner_objective_present` 仍把 fallback后的存在性误写成 Planner贡献。

旧实验若只验证四角色调用数、handoff存在和quality pass，只能证明 Planner参与流程，不能证明 Planner计划影响结果。

## 9. 目标职责：Bounded SemanticTaskPlan

Planner 应只负责语义层，不负责系统控制层。

### Planner 负责

- 从安全的 task request/context解析任务意图；
- 生成 bounded `SemanticTaskPlan`；
- 分别生成 table/semantic/memory retrieval objectives；
- 声明 required evidence；
- 从 Runtime允许集合中声明 required outputs；
- 标记歧义和置信度，供 fallback/人工审计使用。

### Runtime 保留

- 固定四步拓扑；
- registered retriever和tool whitelist；
- route/tool最终闭集；
- replay admissibility和compatibility signature；
- CodeAct plan、lease、retry、fallback；
- workspace/CAS、GC和telemetry；
- scorer-only expected facts和quality gate。

## 10. 建议的 SemanticTaskPlan 边界

概念 schema如下，Phase 2先 shadow，不立即作为运行合同：

```json
{
  "schema_version": "statebus.semantic_task_plan.v1",
  "task_semantics": {
    "operation_class": "comparison|trend|join|aggregation|anomaly|profile",
    "entities": ["bounded normalized entity"],
    "time_scope": "bounded normalized scope"
  },
  "retrieval_objectives": {
    "table": {
      "enabled": true,
      "query_terms": ["bounded term"],
      "required_evidence_types": ["table_cell", "schema", "derived_metric"]
    },
    "semantic": {
      "enabled": true,
      "query_terms": ["bounded term"],
      "required_evidence_types": ["text_span", "citation"]
    },
    "memory": {
      "enabled": false,
      "reuse_intent": "none|artifact|strategy",
      "required_evidence_types": []
    }
  },
  "required_evidence": ["registered evidence enum"],
  "required_outputs": ["runtime-allowed output id"],
  "ambiguities": ["bounded non-answer note"]
}
```

禁止字段：

- tool name；
- route label；
- candidate key；
- expected facts/expected values；
-答案或结论；
- case id、sample id；
- Python/code；
-任意 DAG/dependency；
- Runtime lease/replay/GC策略。

`operation_class` 也不能直接映射成 scorer route oracle；它只能用于语义等价审计或作为受限 retrieval hint。若风险过高，Phase 3可先不消费它，只消费 query/evidence字段。

## 11. Phase 1：只增加可观测性

Phase 1不改变 prompt、不改变执行、不改变 scorer、不改变 Runtime workflow。

### 11.1 必需字段及精确定义

| 字段 | 类型 | 定义 |
| --- | --- | --- |
| `objective_source` | enum | `model_generated/runtime_fallback/hybrid`，按最终有效字段 provenance计算 |
| `planner_model_generated_field_count` | int | schema校验后、进入effective objective的模型叶子字段数 |
| `planner_fallback_field_count` | int | effective objective中由Runtime补入的叶子字段数 |
| `planner_downstream_consumed_field_count` | int | Retriever明确读取且hash校验一致的字段数 |
| `planner_behavioral_effect` | enum/bool | model字段是否使effective query/filter/output与纯fallback不同且实际被消费 |
| `planner_semantic_plan_hash` | sha256 | canonical model plan，不含raw evidence/时间戳/case id |
| `retriever_consumed_objective_hash` | sha256 | Retriever normalization后实际消费对象的hash |

建议同时保存 `planner_fallback_objective_hash`、`planner_effective_objective_hash` 和 per-field provenance sidecar。不要只保存计数，否则仍无法定位哪一个字段产生贡献。

### 11.2 Behavioral effect判定

只有同时满足以下条件才记 true：

1. 至少一个有效模型字段；
2. effective objective与纯 Runtime fallback objective不同；
3. Retriever consumed hash等于effective hash；
4. 消费字段改变 query、candidate filtering、evidence selection或required output之一；
5. 没有因校验失败回退。

模型只回显 Runtime输入、只被持久化、或被fallback覆盖时都必须是 false。

### 11.3 Phase 1验收

- 旧 run离线重算：359 case应得到 model field=0、source=`runtime_fallback`、behavioral effect=false；
- 单测覆盖纯model、纯fallback、hybrid、invalid fallback、model回显五类；
- `planner_generated_retrieval_objective_count` 删除或重定义，不再无条件为1；
- `planner_objective_present` 改名为 `effective_objective_present`；
- 不改变任何 output hash、route/tool、token或quality。

## 12. Phase 2：Shadow Planner

Planner生成 bounded SemanticTaskPlan，但正式执行继续使用 Runtime默认计划。每 case并排保存：

- raw request hash；
- safe Planner input manifest；
- model plan与schema validation；
- Runtime fallback plan；
- semantic equivalence结果；
- field-level diff；
- oracle/case-id taint结果。

### 12.1 Shadow验证维度

1. Schema validity：所有 enum、长度、字符和列表上限。
2. Semantic equivalence：与 CanonicalTaskSpec/Runtime plan在任务意图、evidence/output需求上兼容。
3. Paraphrase stability：同一语义的不同原始 request生成等价 plan。
4. Cross-family differentiation：不同 family/objective不能全部坍缩成同一个 generic query。
5. No oracle：不得出现 expected facts、route/tool、答案数值和case id。
6. Replay stability：plan canonical hash不能被无关措辞、evidence排序或时间戳扰动。

### 12.2 修正当前 holdout方法

当前 holdout只替换 `request_text`，Planner实际 goal/query仍由 precompiled spec生成。因此 Phase 2必须让 shadow Planner明确读取原始 request，同时只提供安全的 data catalog/schema，不提供 `intent_op/required_tools/quality_checks` 等答案/route先验。

建议拆成两个不同 suite：

- `precompiled_spec_stability`：验证固定 spec下关闭 route hint仍可执行；
- `free_text_semantic_plan_holdout`：验证 raw request -> shadow SemanticTaskPlan。

不要把前者命名成自由文本 genericity。

## 13. Phase 3：受限消费

只有经过 schema、semantic、taint和registry校验的字段可影响 Retriever。

### 13.1 允许影响

- registered retriever的 `enabled` 开关，但 Runtime可强制必需分支；
- bounded query terms；
- evidence type filters；
- entity/time scope；
- required outputs与 Runtime allowed set的交集；
- memory reuse intent，最终仍由 replay gate决定。

### 13.2 禁止影响

- tool/route/candidate key；
- Runtime DAG和step count；
- scorer、expected facts、quality threshold；
- replay compatibility/admissibility；
- arbitrary code或filesystem path；
- lease、retry、sandbox、GC。

### 13.3 Fallback规则

任一条件失败立即完整回退到 Runtime plan：schema invalid、unknown enum、unsafe value、semantic conflict、required evidence缺失、hash不一致、timeout、empty/malformed JSON。不能部分接受来源不明字段。

fallback后必须记录：validation reason、rejected field hashes、fallback hash、effective hash和`planner_behavioral_effect=false`。

### 13.4 不允许的“修复”

不能在 Planner空输出时伪造 `retrieve/execute/summarize` 三个 fallback steps，再宣称模型完成规划。固定四步workflow是 Runtime职责；Planner成功应由 semantic plan validity和downstream consumption证明，不由step count证明。

## 14. Genericity gate 重设计

删除：

```text
planner_workflow_step_count >= 3
```

新 gate至少包括：

| Gate | 通过条件 |
| --- | --- |
| semantic plan validity | schema + semantic validator通过 |
| objective source | 明确model/fallback/hybrid，不允许unknown |
| downstream consumption | effective hash == Retriever consumed hash |
| paraphrase equivalence | 同义请求semantic plan canonical等价 |
| cross-family differentiation | family间objective有预注册最小差异 |
| disabled ablation | 禁用Planner仍能fallback且质量不下降 |
| perturbed ablation | 有效语义扰动导致可预期retrieval变化或被validator拒绝 |
| no oracle | 禁止字段名、值、route/tool、答案、case id扫描通过 |

`planner_behavioral_effect` 不要求每 case都为true。简单任务可以合法使用 Runtime fallback；gate应检查来源诚实和消费一致，而不是强迫模型制造差异。

## 15. 最小实现范围

Phase 1预计只需要：

- `v2/runtime/role_path.py`：保留model payload与field provenance；
- `v2/runtime/smoke.py`：构造 fallback/model/effective三份objective并写正确metrics；
- `v2/retrieval/pipeline.py`：落盘 consumed objective hash/field list；
- `v2/runtime/contracts.py`或新bounded contract模块：objective trace结构；
- `scripts/run_v2_genericity_holdout.py`：删除错误step gate；
- 对应 `tests/v2/` 单测和最小benchmark gate。

Phase 2再增加 SemanticTaskPlan contract和shadow sidecar；Phase 3才改 Retriever消费。不得在 Phase 1提前改变 prompt/query/filter。

## 16. 风险与控制

| 风险 | 影响 | 控制 |
| --- | --- | --- |
| Qwen JSON/schema不稳定 | fallback增多 | closed schema、temperature 0、bounded retry |
| Planner token上涨 | 抵消通信收益 | compact schema、单独统计token，不加入raw evidence |
| semantic plan改变质量 | 已通过实验回归 | Phase 2 shadow、Phase 3 validator+instant fallback |
| oracle泄露 | 虚高质量 | safe input manifest、值级taint、禁止route/tool/facts |
| plan hash破坏replay | 历史全部失效 | hash版本化，Phase 2不进入compatibility signature |
| family特化 | 泛化失败 | 不允许case id、跨family holdout、perturbed A/B |
| fake behavioral metric | 重复当前问题 | fallback/model/effective/consumed四hash闭环 |

## 17. 最小验证矩阵

| 阶段 | 数据 | 运行量 | 必过条件 |
| --- | --- | ---: | --- |
| Phase 1 offline | 当前359 workspace | 0 LLM | source/field count重算正确 |
| Phase 1 unit | synthetic provenance | 快速 | 5种source/fallback组合 |
| Phase 1 smoke | 4 holdout + 1 formal L0-L3 | 8 case-layer级 | output/route/tool/quality不变 |
| Phase 2 shadow | formal 25 | 25 | schema valid、无oracle、family有区分 |
| Phase 2 paraphrase | >=4 family x >=3 paraphrase | >=12 | semantic equivalence稳定 |
| Phase 3 A/B | enabled/disabled/perturbed | 冻结case order | consumed hash闭环、质量floor不降 |
| Phase 3 regression | compare/replay/continuous/formal | 先mini后full | 现有通过证据不回归 |

只有 Phase 1字段语义冻结、Phase 2 shadow通过后，才值得启动 Phase 3或下一次全量实验。

## 18. 修复前推荐决策（已执行）

修复前建议批准的最小修复范围是 Phase 1 + genericity gate 纠正。用户随后明确授权继续推进；实际实施已进一步包含 bounded semantic plan 的受限消费和完整 ablation gate，结果见本文第 0 节及配套 `45` 报告。

原方案中的 Phase 2/3 已通过 fail-closed schema/semantic/taint 校验、Runtime fallback 和 disabled/perturbed local ablation 合并为受限实现。尚未运行 full matrix，因此 compare/replay/formal 的完整跨 stage 回归仍不能宣称。

在确认前保持暂停：不修改 Planner、不启动全量、不把 zero-step改造成伪步骤。

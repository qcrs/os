# StateBus v2 Adaptive Agent 与 LLM CodeAct 实施和验证报告

> 日期：2026-07-19
> 分支：`feat/yzm-v2-migration`
> 结论口径：系统/安全门必须全过；模型质量按真实分子/分母报告；不使用 case-specific、operation-specific 或答案驱动修复。

## 1. 最终结论

本轮完成了 bounded adaptive runtime 的控制面、typed Ref wiring、正式 dispatcher、LLM CodeAct、Claim 闭环和 formal 评测闭环。四个角色的模型输出能够真实改变 approved DAG、检索 query、DSL/Python source、ExecutionArtifactRef 和 ClaimSet；Controller 仍保留 capability、Ref、Grant、预算、sandbox 和 validator 边界。

最终 fresh 25-case 正式串行运行的真实结果是：

| 指标 | 结果 |
| --- | ---: |
| 选择/尝试 case | 25/25 |
| Runtime 完成 case | 25/25 |
| end-to-end expected-facts 通过 | 25/25 |
| 质量通过率 | 100% |
| verified CodeAct / DSL | 19 / 6 |
| Planner policy repair | 1 |
| Planner schema normalization | 25 |
| Executor / Retriever / Summarizer 最终失败 | 0 / 0 / 0 |
| 系统/基础设施失败 | 0 |
| CodeAct policy+runtime repair | 3（其中 runtime 1） |
| model/Runtime/sandbox fallback | 0/0/0 |

因此：

- `system_safety_gate = true`；
- `adaptive_system_safety_gate = true`；
- `high_accuracy_development_gate = true`；
- `all_cases_quality_gate = true`；
- `formal_enhancement_gate = true`；
- 选定的 `high-accuracy` exit gate 通过。

该结果来自全部通用修复落地后的全新、串行、完整 25-case 运行。外部 expected facts
仍只在 Runtime 完成后评分，未进入 Planner、Retriever、Executor 或 Summarizer Prompt；
没有修改 case expected facts、容差或分母。一次串行运行可以证明当前 bundle 通过，
但不能单独证明跨 seed 稳定率，也不能授权延迟优势或单组件因果贡献声明。

正式结果：

```text
/home/qcrs/statebus/runs/adaptive_formal_compare_20260719_fresh25_final_generic_routing/
  adaptive_formal_compare_20260719_121145/
    summary.json
    summary.md
```

作为提升基线，旧 fresh 25-case 位于：

```text
/home/qcrs/statebus/runs/adaptive_formal_compare_20260718_214205/
  adaptive_formal_compare_20260718_134219/summary.json
```

其结果是 Runtime `17/25`、端到端质量 `14/25`、Planner 最终拒绝 `1`、Executor
模型质量失败 `10`、系统失败 `0`。本次提升为 Runtime `+8`、质量 `+11`，质量率
由 `56%` 提升到 `100%`；这不是把 Runtime 的结构成功直接记为答案正确，而是 25 个
case 均额外通过了外部 expected-facts 与最终 ClaimSet 检查。

## 2. Review 结论

### 2.1 四角色的真实决策权

| 角色 | 模型真实决定 | Controller 保留 |
| --- | --- | --- |
| Planner | Retriever/Executor/Summarizer capability、一个或多个 Executor 阶段、阶段目标和报告类型 | stable step ID、typed Ref wiring、预算、合法 DAG、Grant、失败策略 |
| Retriever | 1 至 3 个 query、evidence type 偏好和候选预算内排序请求 | corpus、实体/时间 authority、最大 query/候选和 coverage gate |
| Executor | TransformProgram 或完整 Python source、字段处理、过滤、聚合、比较和异常方法 | 固定输入/输出路径、schema、AST policy、bwrap、quality validator |
| Summarizer | Claim 组织、文本、numeric fields、Evidence/Artifact 引用 | 只允许 verified inputs，ClaimSetValidator 决定接受或拒绝 |

这不是只留接口：每个 case 都实际调用四个模型角色并由 Runtime 消费其输出。较早的 fresh
run 还观察到多 Executor 与单 Executor 两种有效 DAG：

- `benchmark-sample-7`：Retriever -> DSL Executor -> Python Executor -> Summarizer；
- `formal-trend-004`：Retriever -> Python Executor -> Summarizer。

该历史多阶段证据的 approved plan hash 分别为：

```text
benchmark-sample-7: a5bef51a46ac09c0b5f11f6def19bac687e7e8f84457609d43777ecd97bfed55
formal-trend-004:   da4102d7b9f4704484a462cd91fd4262e8582b53cb49b91345d9ebcec91c7ae1
```

### 2.2 CodeAct 真实调用链

当前正式链路为：

```text
Planner raw proposal
  -> controller typed wiring compiler
  -> PlanPolicyValidator / ApprovedPlan
  -> CapabilityGrant
  -> AdaptiveCapabilityDispatcher
  -> local-vLLM 生成完整 Python source
  -> AST policy / 一次有界 repair
  -> bwrap 非 root 执行
  -> schema/provenance/quality gate
  -> verified ExecutionArtifactRef
  -> Summarizer ClaimSet
  -> ClaimSetValidator
  -> 外部 expected-facts 评分
```

expected facts 只在 Runtime 完成后用于外部评分；formal summary 明确记录：

```text
benchmark_oracle_visible_to_roles = false
runtime_quality_scope = generic_schema_provenance_completion_only
semantic_quality_scope = external_formal_expected_facts_after_runtime
```

### 2.3 残留特化和 oracle 泄漏检查

本轮审计的 generic adaptive formal 路径（生产 Runtime、adaptive benchmark adapter
和 diagnostic runner）中未发现 `formal_*_python_v1`、按 task ID/case ID 分支或
operation-specific Python capability。当前 formal Executor 只使用：

```text
execute_analysis_dsl_v2
execute_bounded_python_v2
```

保留的 expected facts、样本内容和评分容差均未修改。task sample 的既有 dirty changes 被视为用户内容，本轮没有回滚或改写。

这个结论只限定于 generic adaptive 路径。仓库中既有 strict benchmark/scorer helper
仍可能包含 operation-aware deterministic 逻辑；它们是对照或外部评分实现，不能拿来
证明 adaptive Executor 的泛化性，也不在本轮被改写。

### 2.4 Planner 的“拒绝”到底是什么

Planner 不直接批准或拒绝用户任务。它产生不可信的 `PlanProposal`，真正执行拒绝的是
`PlanPolicyValidator`。策略层只应拒绝超出以下边界的提案：

- 未注册或未授权 capability、role/capability owner 不匹配；
- 非法或有环 DAG、未知 dependency、typed Ref 不匹配；
- 超出 step、depth、token、runtime 或 attempt budget；
- 超出 Envelope risk class、未授权 bounded Python 或非法 memory policy；
- 输出合同、completion criteria 或多 Executor 字段流不成立；
- Prompt escape、路径/代码安全策略或 Grant 绑定不成立。

最终 25-case 中 `planner_policy_repair_count=1`。`formal-anomaly-001` 的首次提案把
未注册的 `compose_cited_report_v1` 当成 Summarizer capability；策略层以
`unknown_or_unauthorized_capability` 拒绝该候选。唯一一次受限重规划只能从相同 capability
surface、相同 task/Ref/预算重新提案，随后选择已授权的 `compose_risk_memo_v1` 并通过。

所以这不是“任务被 Planner 拒绝”，也不是系统错误。它是一次模型闭集遵循缺陷及其正确的
fail-closed 恢复。它仍有质量和成本含义：多一次 Planner 调用，说明当前模型会偶发虚构名字；
但没有未授权 capability 被执行，也没有 Controller 猜答案或静默替换业务算法。

`planner_schema_normalization_count=25` 也不等于 25 次语义修复。stable step ID、dependency、
typed Ref、输出合同、最终 schema 和 object 输出的行数下界属于 Controller 安全边界；
模型保留 capability、stage goal、Executor 数量和 DSL/Python 方法选择。原始提案、编译后提案、
policy report 和 approved-plan hash 都分别留痕。

### 2.5 为什么旧 Runtime 正确率高于端到端质量

旧结果中 Runtime 完成 `17/25`，端到端质量只有 `14/25`，两者检查的命题不同：

```text
Runtime verified
  = schema + provenance + Grant + sandbox + completion criteria
    + verified artifact lifecycle

End-to-end quality
  = Runtime verified
    + 外部 expected facts
    + 最终 ClaimSet 的引用与数值正确性
```

因此一个输出可以是合法 JSON、来源和沙箱均正确、也已经生成 verified Artifact，却仍选错行、
算错统计量、缺少目标字段或给出错误 Claim。旧 run 的 `14/25` 里，3 个 Runtime 已完成 case
在外部 expected-facts gate 才暴露语义错误；其余失败发生在 Planner 或 Executor 阶段。
本轮没有合并两种指标：最终两者恰好都是 `25/25`，是因为所有 case 同时通过两层检查。

### 2.6 不是所有任务都经过 CodeAct

Planner 在同一个 generic capability surface 中选择 `execute_analysis_dsl_v2` 或
`execute_bounded_python_v2`。最终分布是 6 个 verified DSL、19 个 verified CodeAct，
`fallback_count=0`。DSL 用于其线性 row pipeline 能完整表达的过滤、重命名、排序、基础聚合、
安全派生和两期比较；需要自连接、透视、跨行实体对齐、分支后重组、自定义解析/统计或缺失值
处理时选择 bounded Python。

最后两个残留失败的根因正是能力边界描述不完整：Planner 把需要把不同类别行对齐到同一输出行
的任务交给了线性 DSL。修复只公开 DSL 的真实限制并要求 Planner 在这类组合上选 bounded
Python；没有增加任务名、case ID、业务公式或专用算子。定向 `2/2` 和随后 fresh `25/25`
均显示 Planner 直接选择 CodeAct，且没有 fallback 或 policy repair。

## 3. 实施内容

### 3.1 Adaptive 控制面和合同

关键文件：

- `v2/contracts/adaptive.py`
- `v2/runtime/capability_registry.py`
- `v2/runtime/domain_packs.py`
- `v2/runtime/plan_policy.py`
- `v2/runtime/adaptive_plan_compiler.py`
- `v2/runtime/adaptive_runtime.py`
- `v2/runtime/driver.py`
- `v2/runtime/session.py`
- `v2/runtime/telemetry.py`

完成内容：

- 分离 `PlanProposal` 与 `ApprovedPlan`；
- raw proposal hash、controller-compiled proposal hash 和 approved plan hash 分开留痕；
- capability 的 accepted input union 与 required input presence 分离；
- cited Summarizer 必须同时覆盖 `canonical_evidence_pack` 和 `execution_artifact`；
- Runtime 在发 Grant 前再次检查实际输入种类，缺失时以 `grant_required_input_kind_missing` fail-closed；
- `compile_required_input_wiring()` 只增加 descriptor 要求的 typed dependency，不修改 capability、goal、算法或答案；
- dependency 顺序改为稳定去重，不再按字符串排序；schema-only repair 不允许重排依赖；
- Summarizer 依赖稳定保持 evidence first、intermediate artifacts in producer order、final artifact last。

### 3.2 Retriever、Evidence 和非文本状态

关键文件：

- `v2/runtime/retrieval_adapter.py`
- `v2/runtime/evidence_coverage.py`
- `v2/runtime/evidence_projection.py`
- `v2/runtime/state_consumption.py`
- `v2/retrieval/pipeline.py`

完成内容：

- Retriever 模型生成 bounded query；
- query 实际进入 embedding/rerank 和 evidence selection；
- coverage、projection 和 state consumption record 都保存 hash；
- Controller 注入 corpus/entity/time authority，模型不能扩大 scope；
- EvidencePack 的 locator、task/session 和 coverage 状态进入下游验证。

### 3.3 DSL、LLM CodeAct 和 sandbox

关键文件：

- `v2/runtime/adaptive_dispatcher.py`
- `v2/runtime/transform_dsl.py`
- `v2/runtime/capability_recompute.py`
- `v2/contracts/llm_codeact.py`
- `v2/runtime/llm_codeact.py`
- `v2/runtime/codeact_sandbox.py`
- `v2/runtime/capability_validators.py`

完成内容：

- LLM Python 进入正式 `AdaptiveCapabilityDispatcher`，不是外挂脚本；
- 支持多个 verified ExecutionArtifactRef，固定映射到 `inputs/task.json`、`inputs/upstream-N.json`；
- 所有输入必须按顺序读取，manifest、schema 和 provenance 不得静默丢失；
- AST repair 与 runtime repair 均有界，repaired source 在新 workspace 重新经过 AST、bwrap、schema 和 quality gate；
- CodeExecutionRecord 保存 source、output、policy、quality、runtime error、repair 和 sandbox hashes；
- 允许内存字符串清洗 `str.replace()`；继续拒绝 `Path.replace()`、rename 和任意路径副作用；
- `execute_bounded_python_v2` 的公开合同改为必须消费 verified `execution_artifact`，不再虚假宣称可直接消费 EvidencePack；
- DSL 中间阶段生成提示和 Runtime 校验都使用 step-specific schema，不再误用 final schema。

### 3.4 Formal controller wiring 的最终通用修复

关键文件：

- `scripts/v2_diagnostics/run_adaptive_formal_compare.py`
- `v2/runtime/adaptive_dispatcher.py`
- `v2/runtime/domain_packs.py`

fresh 前发现并修复三处通用缺陷：

1. `PlanPolicyValidator` 曾按字典序排序 dependency，破坏 final artifact last 语义；现改为稳定顺序。
2. 中间 DSL 虽已有独立 step schema，但 worker prompt 和 dispatcher 仍使用 final schema；现统一为 step schema。
3. Planner 把 Retriever step 当成 Python input 时，formal compiler 曾把 EvidencePack 接给只接受 Artifact 的 CodeAct；现按 producer role/type 绑定首个 Executor 的 verified source Artifact。

这些修复不读取 expected facts，不按 case ID 分支，也不修改模型算法。

### 3.5 Claim 和引用闭环

关键文件：

- `v2/runtime/claims.py`
- `v2/runtime/adaptive_dispatcher.py`
- `scripts/v2_diagnostics/run_adaptive_formal_compare.py`

完成内容：

- Summarizer 只接收 verified evidence 和 final verified analysis artifact；
- ClaimSet 必须引用合法 Evidence item 和 ExecutionArtifactRef；
- numeric fields 由 ClaimSetValidator 对 verified rows 校验；
- 失败候选由模型重新生成，不由 Controller 覆盖数值或 citation；
- ClaimSet、validator report 和最终 artifact 全部保存 hash lineage。

### 3.6 Provenance 与 Ref 边界加固

旧 fresh 25-case 之后完成了一轮不改变业务算法的通用边界审计；最终 fresh 25-case
已经包含下列全部修改：

- Evidence projection 过去先记录 `row_lineage.row_index`、再单独排序 rows，可能让
  lineage 指向错误 EvidenceItem；现将 row 与 lineage 成对稳定排序，并在排序后重新编号；
- Retriever 产出的 Evidence Ref 额外记录真实 `(session_id, producer_attempt_id)`；DSL、
  Python 和 Summarizer 都在模型生成或文件副作用前校验 task/session/producer attempt；
- projection、DSL、CodeAct 和 Summarizer 生成的 Artifact metadata 都显式保存
  `attempt_id`，formal controller-bound source 以 `controller-bound-source` 留痕；
- Summarizer 使用 Evidence Ref 的真实 session scope 做 Claim 校验，不再以当前 Grant
  session 代替 Evidence 的来源 session；跨 session Evidence 和多个 EvidencePack
  都 fail-closed；
- `CodeGenerationRequest.input_ref_ids` 必须与 CapabilityGrant 精确同序一致，不能通过
  排序后比较把输入次序变化隐藏掉。

这些修复只收紧 provenance/authorization，不读取 expected facts，不改变 Planner 选择、
DSL/Python 算法或 Claim 数值。

### 3.7 从 14/25 到 25/25 的通用质量修复

旧 run 的 11 个未通过 case 被归纳为合同层面的重复故障，而不是逐 case 打补丁：

1. **Planner/Controller 边界。** Controller 统一编译 stable step ID、typed Ref、dependency、
   final schema 和 object 输出的 `min_rows=1`；Planner 仍选择 capability、stage goal、方法和
   Executor 数量。非法 capability 只允许一次同权重规划修复。
2. **DSL 表达与校验。** 增加通用 `rename(source,target)`；`compare_periods.carry_fields`
   只能携带跨比较行保持不变的授权字段；解释器和独立 recompute 同步实现。最终补充线性
   pipeline 的真实能力边界，避免把 self-join/pivot/cross-row alignment 错交给 DSL。
3. **CodeAct 生成合同。** Prompt 明确 top-level row-array 输入、task parameters 只用于 literal
   filter、所有 nullable 字段在 reducer 前处理、inclusive quantile 使用 `(n-1)*p` 线性插值、
   多输入不能默认拼接。修复 Prompt 同时携带原任务、失败 source、诊断、schema、semantics 和
   completion contract。
4. **静态和运行时修复。** `symtable` 在执行前发现 undefined globals；AST/policy repair 和
   bwrap runtime repair 各最多一次，replacement 在新 workspace 重新经过完整 policy、sandbox、
   schema、provenance 和 quality gate。最终 full run 使用 3 次 bounded repair，其中 runtime 1 次。
5. **Summarizer 合同。** Controller 固定 expected claim count；每个 Claim 只能覆盖实际 verified
   output row；numeric field key/value 必须来自支持该 Claim 的 verified artifact，禁止把日期或字符串
   编码为数字，禁止由 evidence text 扩写不存在的结果行。

这些规则不包含 `formal-*` case ID、公司名、列值、expected facts 或 case-specific answer。
基础工具只用于 JSON/schema、AST/symtable、DSL、provenance 和安全验证；没有用工具替模型选择
业务答案，也没有新增 operation-specific capability。

## 4. 真实证据链

### 4.1 DSL -> Python 多阶段成功实例

`benchmark-sample-7` 的证据：

```text
planner model: qwen3-32b
planner raw output hash: ffd20412fe2f72f8a3b53b33baf551fc0bd8b0ae4bcd1e1ae4b33f2607a1a4aa
raw proposal hash: ab0c0dc4c6315daaf959b19c732449038277ceab6c99686d52e63fba96f0fb45
compiled proposal hash: c4a8362eab87b42032d4ce9b078f7df012a52f04f050ca3137a1339fd8b67489
approved plan hash: a5bef51a46ac09c0b5f11f6def19bac687e7e8f84457609d43777ecd97bfed55
DSL program hash: e4896746fae69620c4146c5689d37a299d1bb9c6b91e6ac169f1e7f277839d57
CodeAct source hash: b1afdac1059035e6b6cffd9501bf68a8d3dcca6addba939e9c5159cd9b0780df
CodeAct output hash: 42bbce992d31ae2061a57b628211651c9bc9b5af592ac58807b3150e99c2c269
quality report hash: a2ec2d0a336ce30f3c1c2f523def3808917e8c4bb9b7edd69e19b02ca0f57836
ClaimSet hash: 3ee10df897c06b66ea0c16cebf1f469c1b34762537b719602b04c4521f7b6b9a
bwrap UID/GID: 65534/65534
repair/fallback: 0/0
```

四个 Grant hash：

```text
d45b8fd1773227f361f641407937347da68817b12cdc5dadbcbb82077b6ffbd8
4c34d777eb3decf5c8564d4053179999dcae7c566865d53dc03904fabb1a2588
9752f58d3649216c8bd57604841c01ad806a615c34cb8b35ef9e5e99abca21fc
7c5b28374e0aea787cee39c9845d29e9c3feaf5b318703a307b245475c2fe3c1
```

Claim validation 为 `ok=true`，最终 operating income 数值 19 通过外部 expected-facts gate。

### 4.2 Retriever 决策实际生效

同一任务中 Retriever 生成 3 个 query，telemetry 为：

```text
retriever_model_query_count = 3
retriever_query_changed_candidate_set_count = 1
```

StateConsumptionRecord 记录：

```text
input decision surface hash:  7c4555d1723a3ee98d5e8f1674cdcbbb36952e20e70e080271a51f2e8fc4c714
output decision surface hash: 6550134fa74e8e541ec93785b87f5b71c86640c3336e3c10b2037656dc0f5a87
selected evidence IDs: ctx-chunk-1, ctx-chunk-3, ctx-chunk-4, fact-operating_income-1, hint-1, hint-2
```

这证明 embedding/rerank 状态被实际读取并改变下游选择，不是只生成未消费的 StateRef。

### 4.3 CodeAct runtime repair 成功实例

`formal-anomaly-001` 的 fresh 结果：

```text
approved plan hash: bfb330ddc9bcae0ed840ef1fb4cca3b871f5e2a5aba58dc6ed3dfd4c6c27a896
CodeAct source hash: 7d3f27b3f53573a7b86e4aa58d19ead76ee6565a6d2cdc079d55612b6bc5f970
output hash: 48f8ef977f484ca26bf4c11a5a10552624475bd2ea4e3b8625aa18a62e06a2a0
quality report hash: 3827ff079a41d8f4a413c9364fd8781554bdead4a8e35e0c73ee816d0600aa15
ClaimSet hash: f4836a78fd28008c7e969dd152df24363457f19a08328b27f15a907995299a64
bwrap backend/UID/GID: bwrap / 65534 / 65534
runtime repair: 1
sandbox fallback: 0
```

外部评分：

```text
mean_no_of_deaths_with_outliers:    10149.429389312978 -> expected 10149.43, pass
mean_no_of_deaths_without_outliers:  5949.081799591002 -> expected 5949.08, pass
```

### 4.4 小型 live Summarizer closure

成功 bundle：

```text
/home/qcrs/statebus/runs/adaptive_summarizer_closure_20260718_192544/
  adaptive_comparison_live_20260717_20260718_112557/
  adaptive_anomaly_acme_delivery_live_20260717_20260718_113520/
```

comparison 选择 retrieval + DSL + Python + cited report。anomaly 选择 retrieval + DSL + Python + cited risk memo；其 Summarizer dependency 稳定为 evidence、intermediate DSL artifact、final CodeAct artifact。anomaly 证据：

```text
CodeAct source hash: ac379f465dfea6495d7a28045d11544a225c48648ca9d6420ad7bc317d485050
CodeAct output hash: 3cc9306d6fa399102981e8505f8902f53d64c16e39171aa935447f2def55ea24
bwrap UID/GID: 65534/65534
fallback: 0
Claim validation: pass
```

### 4.5 最终 full 25-case 证据

```text
run:
  /home/qcrs/statebus/runs/adaptive_formal_compare_20260719_fresh25_final_generic_routing/
    adaptive_formal_compare_20260719_121145/

quality:                 25/25 = 100%
Runtime completed:       25/25
verified CodeAct:        19
verified DSL:             6
Planner policy repair:    1
Planner normalization:   25
CodeAct repairs:           3 (runtime 1)
fallback:                  0
model/system failures:   0/0
system safety gate:       PASS
80% high-accuracy gate:   PASS
all-cases quality gate:   PASS
formal enhancement gate: PASS
```

最终 summary 中 `failures=[]`、`stage_failure_counts={}`、
`failure_classification_counts={}`。19/6 是 Planner 的实际能力选择分布，不是强制所有任务走
CodeAct；所有 25 个通过 case 都产生 verified execution 和 ClaimSet，且 benchmark oracle
对角色不可见。

### 4.6 回归与静态检查

```text
python -m pytest -q tests/v2 tests/test_llm_runtime.py
  540 passed

git diff --check
  pass

PYTHONPYCACHEPREFIX=/tmp/statebus-pycache python -m compileall -q \
  v2 runtime scripts/v2_diagnostics tests/v2 tests/test_llm_runtime.py
  pass
```

`tests/v2/test_memory_runtime.py`、`test_memory_store.py`、`test_replay.py`、
`test_replay_gate.py`、`test_continuous_runner.py` 及 continuous family tests 均在上述 540-test
集合内。Adaptive 路径没有把所有 strict task 改道到 CodeAct；`RuntimeDriver.run()` 的 strict
memory/replay 主路径保持不变，新的入口是独立的 `RuntimeDriver.run_adaptive()`。

## 5. 工具增补的整体判断

本轮最终没有新增 operation-specific 基础工具或外部分析库。

### 5.1 已有通用工具足够解决的问题

- declarative Transform DSL：过滤、选择、排序、聚合、两期比较和基础异常检查；
- bounded Python CodeAct：自定义解析、多阶段统计、异常处理和复杂组合；
- Evidence projection、schema、provenance 和 Claim validators；
- 一次 AST repair 和一次 runtime repair。

Runtime 合同缺陷已经用这些通用能力修复，无需引入按 benchmark family 封装的工具。

### 5.2 不应由工具替模型完成的问题

- 模型在明确要求 `do not merge` 后仍把 source 与其过滤子集相加；
- 模型对中间 DSL step 选择了不适用的统计操作并引用不存在的列；
- Planner 连续两次输出两个 Summarizer；
- `aggregation_by_quarter` 等数值/字段/排序质量错误；
- clean-table 结果与外部 expected facts 不符。

Controller 若自动去重、改算法、改 Plan、重算答案或按 task family 选择工具，会把模型错误隐藏成系统成功。该方向被明确拒绝。

### 5.3 可选后续，但未在本轮实现

- 使用更强或针对 structured plan/DSL 微调的模型；
- 在不读取 oracle 的前提下，评估一次统一 DSL candidate regeneration 是否值得成为产品级 policy；
- 给多输入增加显式关系元数据，例如 `primary_source`、`derived_upstream`，但不得由 Controller 自动合并/去重；
- 用多个独立 seed 重跑，以量化 local-vLLM 输出波动。

这些是模型/协议演进，不是当前验收所需的隐藏兜底。

## 6. 旧 14/25 基线问题分析与最终闭环

### 6.1 旧 run 阶段统计

| 阶段/类别 | 数量 |
| --- | ---: |
| Planner policy rejection | 1 |
| Retriever failure | 0 |
| Executor model quality | 10 |
| Summarizer failure | 0 |
| sandbox/infrastructure | 0 |
| Runtime bug | 0 |

### 6.2 具体失败

| task | 阶段 | 分类 | 原因摘要 |
| --- | --- | --- | --- |
| benchmark-sample-1 | Executor/external score | model quality | source 与 derived upstream 被重复计入，120 输出为 240 |
| benchmark-sample-4 | Executor | model quality | 多输入处理后 exactly-one-row 检查失败 |
| benchmark-sample-6 | Executor | model quality | 多输入处理后 exactly-one-row 检查失败 |
| benchmark-sample-8 | Executor | model quality | 多输入处理后 exactly-one-row 检查失败 |
| formal-trend-003 | DSL Executor | model quality | `unknown_column:4`，模型引用未产生字段 |
| formal-trend-001 | DSL Executor | model quality | `unknown_column:5`，模型用错误 derive 处理 trend label |
| formal-trend-005 | DSL Executor | model quality | `unknown_column:5`，模型引用未产生字段 |
| formal-trend-002 | DSL Executor | model quality | `unknown_column:5`，模型用错误 derive 处理 trend label |
| formal-join-001 | Planner | policy rejection | Retriever 把 task Ref 写进 dependency/input；旧链路未完成安全编译/修复 |
| formal-agg-002 | external score | model quality | 聚合/极值结果未通过 expected facts |
| formal-anomaly-003 | external score | model quality | nullable 字段进入 reducer，clean-table expected facts 未通过 |

这些失败全部保留在旧 run 的 25-case 分母内。最终 run 没有删除、降权或改写任何一项。

### 6.3 根因与通用闭环

| 旧失败簇 | 根因 | 通用修复 |
| --- | --- | --- |
| 4 个 lookup | 多输入/过滤语义含糊，exact-one-row 逻辑作用于错误集合 | 明确 authoritative artifact、禁止默认拼接祖先与派生产物、完整 task/schema repair context |
| 4 个 trend DSL | 线性字段流未被模型正确跟踪，DSL 缺少通用 rename/carry 能力 | `rename`、`compare_periods.carry_fields`、逐操作列跟踪、一次完整 DSL replacement |
| Planner 拒绝 | task Ref、dependency、capability 名称由模型自由编码且偶发越权 | Controller 编译 typed wiring；非法 capability 仍 fail-closed 并只允许一次同权限修复 |
| aggregation | 聚合、极值、舍入和输出合同未同时落实 | Prompt 逐项审计 semantics，repair 保留原始合同，独立 quality recompute |
| clean table | nullable 值被传入 `statistics.mean` 等 reducer | source profile 暴露 missing_count；每个 reducer 就地过滤或按任务显式 impute |
| 最后 2 个 join DSL 波动 | Planner 未看清 DSL 无法分支并重组同一输入的类别行 | 公布线性 DSL 能力边界；需要 pivot/self-join/cross-row alignment 时直接选 bounded Python |

### 6.4 family 最终结果

| family | 旧 run | 最终 run |
| --- | ---: | ---: |
| financial report lookup | 4/8 | 8/8 |
| multi-period trend | 1/5 | 5/5 |
| cross-table join | 4/5 | 5/5 |
| conditional aggregation | 3/4 | 4/4 |
| anomaly detection | 2/3 | 3/3 |

## 7. 测试和验证

formal live wrapper 在 `statebus-dev-qcrs` 内执行；核心 pytest 与静态检查从当前 repo host
环境执行。容器内激活方式为：

```bash
source /workspace/statebus/project/docker/activate_statebus_container.sh
cd /workspace/statebus/project
```

### 7.1 确定性回归

| 命令/范围 | 结果 |
| --- | --- |
| Evidence projection 定向回归 | `3 passed` |
| provenance/dispatcher/CodeAct 相关 7 文件 | `53 passed in 5.54s` |
| continuation prompt 完整定向集合 | `119 passed in 10.11s` |
| deterministic review wrapper focused tests | `103 passed in 5.63s` |
| current-code live wrapper preflight | `55 passed in 5.84s` |
| 最终核心 `python -m pytest -q tests/v2 tests/test_llm_runtime.py` | `540 passed, 100 warnings in 548.48s` |
| 较早完整 repo `python -m pytest -q` | `787 passed, 1 failed` |
| 最终 `compileall` | pass |
| `git diff --check` | pass |

完整 repo 的唯一失败：

```text
tests/test_smoke.py::test_active_docs_reference_memory_dual_mode_fairness_v3_and_drop_old_formal_wording
```

原因是 active path 缺少 `docs/reports/MASTER_PRESENTATION_GUIDE.md`，而历史文件位于 archive。
它是与本轮 Runtime 无关的既有 docs/test 不一致；本轮没有恢复或改写该过时报告。最终
prompt-only 路由修复后没有重复运行 whole-repo suite，核心 540-test suite 已重新全跑。

### 7.2 bwrap readiness

旧 fresh bundle：

```text
/home/qcrs/statebus/runs/adaptive_formal_compare_20260718_214205/bwrap_readiness.json
```

结果：

```text
ready = true
actual_backend = bwrap
bwrap_version = bubblewrap 0.8.0
sandbox_uid = 65534
sandbox_gid = 65534
readiness_digest = b2cc021a5c4123744e728e209b65b29dd35a63499c32ddd280ec30781ac8270c
```

deterministic review bundle：

```text
/home/qcrs/statebus/runs/adaptive_runtime_review_20260719_002655/
```

其中 focused tests、bwrap readiness 和 deterministic mode matrix 三阶段均为 exit code 0。

最终 full run 的 wrapper preflight 为 `63 passed`；25 个 case 中所有 Python execution record
均为 `sandbox_actual_backend=bwrap`、非 root UID/GID，sandbox fallback 为 0。

### 7.3 较早定向 live

修复后的两项 live：

```text
/home/qcrs/statebus/runs/adaptive_contract_fix_targeted_20260718_2030/
  adaptive_formal_compare_20260718_133539/
```

结果为 `2/2` 质量通过，包含 1 个 verified DSL 和 2 个 verified CodeAct，fallback 为 0。wrapper 使用 `all-correct` 时退出码为 1，是因为 full-registry all-correct gate 不允许两项子集置真；case 本身没有失败。

### 7.4 Post-hardening current-code live

最新 provenance/Ref 加固后的独立 bundle：

```text
/home/qcrs/statebus/runs/adaptive_contract_hardening_targeted_20260719_0035/
  adaptive_formal_compare_20260718_163033/
```

串行选择 `benchmark-sample-7` 与 `formal-anomaly-001`，只运行 adaptive lane，并将
`quality_threshold` 设为 `0.0` 以验证系统门。真实结果：

```text
attempted/completed/quality: 2/2/2
verified CodeAct/DSL: 2/1
CodeAct runtime repair: 1
model/runtime/sandbox fallback: 0/0/0
failures: 0
system_safety_gate: true
adaptive_system_safety_gate: true
benchmark_oracle_visible_to_roles: false
```

`benchmark-sample-7` 保留 DSL -> Python 多阶段 DAG，最新 CodeAct source hash 为
`1918c3d19e796dd28d0d2c7e87f0553e7260dfc1d934dc0e4579d99d00793638`；
`formal-anomaly-001` 的 source hash 仍为
`7d3f27b3f53573a7b86e4aa58d19ead76ee6565a6d2cdc079d55612b6bc5f970`，并经过一次
runtime repair。两项 bwrap UID/GID 均为 `65534/65534`。

这里的 `2/2` 和 threshold `0.0` 只是历史边界证据，不能单独解释为 high-accuracy 证据；
后续完整 fresh `25/25` 已取代旧 `14/25`，但仍保留该 bundle 作为 provenance 加固的定向记录。

### 7.5 Fresh 正式命令

```bash
STATEBUS_CUDA_VISIBLE_DEVICES=1 \
STATEBUS_EMBED_DEVICE=cuda:0 \
STATEBUS_LOCAL_VLLM_BASE_URL=http://127.0.0.1:53334/v1 \
STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b \
STATEBUS_ADAPTIVE_FORMAL_RUN_ID=adaptive_formal_compare_20260719_fresh25_final_generic_routing \
STATEBUS_ADAPTIVE_FORMAL_MAX_CASES=25 \
STATEBUS_ADAPTIVE_FORMAL_EXIT_GATE=high-accuracy \
STATEBUS_ADAPTIVE_FORMAL_QUALITY_THRESHOLD=0.80 \
bash scripts/v2_diagnostics/run_adaptive_formal_compare_gpu1.sh
```

fresh run 为严格串行运行，没有并发 local-vLLM timing 混入。

## 8. 运行环境

容器只读检查结果：

```text
container: statebus-dev-qcrs
running: true
outer user: 0:0
privileged: false
network: host
cap_add: SYS_ADMIN, NET_ADMIN
security_opt: seccomp=unconfined, apparmor=unconfined
```

执行身份边界：

```text
host qcrs -> Docker outer runtime 0:0 -> bwrap LLM code 65534:65534
```

模型和 GPU：

```text
local-vLLM base URL: http://127.0.0.1:53334/v1
model: qwen3-32b
model root: /data/models/Qwen3-32B
max_model_len: 8192
physical GPU: 1
container logical embedding device: cuda:0
embedding model: /statebus/models/Qwen3-Embedding-0.6B
```

本轮没有重启、升级或修改 vLLM。

## 9. 能宣称和不能宣称

### 9.1 可以宣称

- 四角色模型输出真实进入正式 adaptive Runtime；
- Planner 的 capability/DAG 选择改变执行；
- Retriever query 改变 embedding/rerank candidate selection；
- Executor 的 LLM source 在 bwrap 非 root 执行并产生 verified artifact；
- 中间 Artifact 可被下游 Executor 消费；
- Summarizer 只消费 verified evidence/artifact，Claim validator 正常工作；
- fresh 25-case 的系统/安全门通过，fallback 为 0；
- 当前这一次完整、串行、fresh 25-case 的真实质量是 25/25，CodeAct/DSL 为 19/6；
- 当前实现没有强制所有任务进入 CodeAct，Planner 的 DSL/Python 选择真实改变执行路径。

### 9.2 不能宣称

- 不能把单次 25/25 外推为跨 seed、跨模型或任意未知任务的稳定 100%；
- 不能用定向 2/2 替代 fresh 25-case 分母；最终结论使用的是完整 fresh 25/25；
- 不能声称 adaptive 比 strict 更快或更省 token；fresh adaptive token/time 都更高；
- 不能做单组件因果归因，summary 明确记录 `component_isolated_causal_claim_allowed=false`；
- 不能声称 production-grade sandbox；外层容器不是 privileged，但使用了较宽的 capability/security profile；
- 不能声称本轮已完成 openEuler VM posterior validation；
- 不能声称支持 hidden-state/KV transfer；该方向仍只能描述为 Future Work 的 Engine-Local Prefix Reuse；
- 不能把模型质量失败、policy rejection 或未通过的 high-accuracy gate 改写成 PASS。

## 10. 最终停止条件

本轮在以下边界停止：

- 已发现的通用 Runtime/合同缺陷有确定性测试和 live 证据；
- v2、strict、CodeAct、memory/replay 和 continuous reuse 核心集合 `540` 项全过；
- bwrap、UID/GID、fallback、oracle visibility 等系统门全过；
- 全部修复后的 fresh 25-case 已完整串行重跑，Runtime 和端到端质量均为 `25/25`；
- 仍保留 Planner 一次 policy repair 作为模型闭集遵循风险，不把它隐藏为 normalization；
- whole-repo 仍有一个与本轮无关的历史文档路径测试失败，未越界恢复旧文档；
- 按用户要求，没有为提高分数新增 case-specific 工具、自动答案修复或 operation-specific capability；
- 后续应以多 seed 稳定性评估和 capability-name structured decoding 为主，而不是继续扩大 Controller 的业务答案权力。

# 代码真实性审查

本文件记录源码级观察，不复述答辩话术。

更新说明：本文件最初基于 deterministic formal artifacts 和源码审查；`local_api_20260706_191835` 已补充 API+local+memfd 实验。最新 full `RUN_FLAGSHIP=1` comprehensive evidence 是 `local_api_20260707_163354`。当前代码事实与实验证据的合并判断以 `code_truth_vs_experiment_issue_matrix_zh.md` 为准。

## 四个 agent 角色

观察到的实现：

- `v2/runtime/role_path.py` 定义了 `RolePathRunner`，并包含 planner、retriever、executor、summarizer 四个独立方法。
- 每个方法都会用 role-specific `purpose` 调用 `llm_client.complete(...)`。
- `v2/benchmark/live_runner.py` 暴露 `--role-path-mode deterministic|api`。

证据：

- Planner：`RolePathRunner.plan_workflow`。
- Retriever：`RolePathRunner.choose_retrieval_candidate`。
- Executor：`RolePathRunner.validate_execution_choice`。
- Summarizer：`RolePathRunner.summarize`。
- deterministic formal artifacts 使用 `role_path_mode=deterministic`。
- `local_api_20260707_163354/r01_05_formal_api_local_memfd` 使用 `role_path_mode=api`，并记录 planner/retriever/executor/summarizer 各 25 次 API call。

真实落地部分：

- API role-path 代码存在，且 role 是分开的。
- API+local+memfd formal internal path 可运行并产生 role telemetry。
- deterministic formal mode 仍可作为 backend/history baseline。

模拟、deterministic 或 harness 部分：

- formal internal 的 25/25 API 证据已经存在。
- formal external compare 仍不是 full registry 25-case API superiority 证明。

主要风险：

- 文档很容易把“formal internal API 四角色证明存在”写成“formal external superiority 已证明”。

建议修复：

- role claim 可以绑定 `r01_05_formal_api_local_memfd`；external superiority claim 必须等 compare gate、schema、scope 修复后再升级。

## CodeAct

观察到的实现：

- `v2/runtime/codeact.py` 构建 bounded plan，并在 task workspace 中执行生成的 `run_executor.py`。
- `v2/runtime/codeact_sandbox.py` 支持 `bwrap`、`resource`、`none`，并有 `auto` fallback。
- Runtime telemetry 记录 `codeact_plan_stage_count`、`codeact_plan_action_count` 和 sandbox backend counts。

证据：

- CodeAct plan classes 与 execution record 是真实存在的。
- `CodeActSandboxRunner` 在可用时先尝试 `bwrap`，否则退到 resource limits 或 `none`。
- `docs/reports/v2_experiment_summary_20260703.md` 已把旧 LLM generation 数字标注为历史诊断证据。

真实落地部分：

- Bounded CodeAct / controlled execution path。
- Artifact 写出与 audit sidecar。
- Sandbox telemetry。

模拟、deterministic 或 harness 部分：

- 当前 formal benchmark 不能证明 realtime open-ended LLM-generated Python。
- 当前 plan 受 runner contract 约束，是 bounded path。

主要风险：

- 历史 “LLM generated 5/5” diagnostic 会被过度写成当前 formal proof。

建议修复：

- 如果要把 realtime LLM code generation 作为 claim，需要新增明确的 formal CodeAct API benchmark stage。

## 结构化控制平面

观察到的实现：

- v1/protocol 路径中，`protocol/statebus.proto` 定义 typed messages 和 `WireEnvelope`。
- v2 路径中，`v2/control/statebus_v2.proto`、`v2/control/messages.py`、`v2/control/transport.py` 定义 typed Protobuf control envelope 与 UDS framing。
- `SubprocessExecutorTransport` 支持 subprocess worker 与 memfd ref encode/decode。

证据：

- `python3 -m runtime.smoke` 在容器 root 路径下通过 text 和 protocol 两种 mode。
- `tests/v2/test_control_plane.py`、`tests/v2/test_uds_loopback.py`、`tests/v2/test_subprocess_executor.py` 覆盖 v2 control/UDS/subprocess memfd，并已纳入 local+api focused pytest；`local_api_20260707_163354` focused stage 115 passed。

真实落地部分：

- UDS + typed Protobuf envelope 是真实 control-plane implementation。
- protocol smoke 可运行。

模拟、deterministic 或 harness 部分：

- formal benchmark runtime 主路径使用 `ControlPlaneLoopbackServer.exchange_sequence_by_contract()`，不是 subprocess worker。
- subprocess memfd 当前主要是单测证据。

主要风险：

- “typed Protobuf” 可以用于 control envelope / frame，但不能暗示 formal benchmark 已验证 subprocess execution 或 fd-passing data plane。

建议修复：

- 将 control/UDS/subprocess tests 纳入 local+api focused gate；如需 claim subprocess execution，增加 subprocess benchmark stage。

## SemanticStateRef / 非文本状态

观察到的实现：

- `v2/refs/models.py` 定义分离的 `SemanticStateRef` 与 `ExecutionArtifactRef`。
- `RuntimeDriver` 同时导入二者，并分别发出 semantic-state telemetry 和 execution artifact refs。
- `HydrationAccountingAudit` 记录 raw evidence bytes、prompt-visible bytes 和 role hydration bytes。

证据：

- deterministic formal artifacts 显示 formal runs 都有 `semantic_state_transfer_count=25`。
- memfd formal local artifact 显示 `state_pool_mode_used=memfd`。
- `local_api_20260707_163354/r01_05_formal_api_local_memfd` 显示 `semantic_state_transfer_count=25`、`memfd_publish_count=25`、`memfd_transfer_count=25`。
- representative sample 7 metadata 显示 `object_kind=EMBEDDING_STATE`、`storage_kind=memfd`。

真实落地部分：

- Ref separation 真实存在。
- Embedding semantic state transfer 与 hydration accounting 是真实 telemetry surface。

模拟、deterministic 或 harness 部分：

- 当前 memfd state object 是 embedding semantic state，不是 hidden-state/KV cache。
- 证据文本/表格仍通过 hydration prompt slices 进入 role prompt。

主要风险：

- claim 可能暗示 raw evidence 永远不会进入 prompt，或暗示 hidden-state/KV transfer。准确说法应是：当前实现有 measured embedding semantic state transfer、StateRef/registry、role hydration accounting。

建议修复：

- 添加回归测试和 artifact 归档，断言代表性任务的 object kind、storage kind、prompt-visible bytes、hydration slices 都可复盘。

## Statepool: shared_memory / mmap / memfd

观察到的实现：

- `v2/state/store.py` 实现 `LayeredStateStore`，支持 shared memory、memfd、mmap file 和 inline materialization。
- `backend_name` 现在使用 last/past actual publish counts。
- `publish()` 会在 shared memory 或 memfd `OSError` 时通过 policy fallback。

证据：

- `formal_auto.stdout.json`：requested `auto`，used `shared_memory`，25 次 shared-memory publish。
- `formal_shared_memory.stdout.json`：requested `shared_memory`，used `shared_memory`，25 次 shared-memory publish。
- `formal_memfd_local.stdout.json`：requested `memfd`，used `memfd`，25 次 memfd transfer/publish，247076 bytes。

真实落地部分：

- Backend reporting 已由 fresh formal runs 支撑。
- Memfd path 在当前运行容器中真实可用。

模拟、deterministic 或 harness 部分：

- Memfd unavailable fallback 仍主要是 failure-path/unit 证据。

主要风险：

- 在真实 no-memfd 主机或显式 capability block stage 之前，不能声称真实 no-memfd host fallback validation。

建议修复：

- 新增 dedicated no-memfd validation environment 或 subprocess capability mask stage。

## Memory / replay / reuse

观察到的实现：

- `v2/runtime/driver.py` 中 replay metrics 区分 validated replay 和 exact replay。
- 本审计已把 `answer_restoration_replay_count` 修正为保持 `0.0`，直到真实 answer-restoration 机制实现。
- `v2/benchmark/continuous_runner.py` 不再从 exact replay 回填 answer restoration。

证据：

- `tests/v2/test_continuous_runner.py` 现在断言 exact replay 和 answer restoration 是分离 metric。
- 修复后 `tests/v2/test_continuous_runner.py`：11 passed。

真实落地部分：

- Exact replay 和 validated replay 已实现并有度量。
- skipped-step/reuse claim 只在对应 telemetry 非零时有效。

模拟、deterministic 或 harness 部分：

- 通用 answer restoration 未实现。

主要风险：

- 旧文档仍可能宽泛使用 “answer restoration”。当前 safe wording 必须避免该说法。

建议修复：

- 在最终展示前搜索并降级所有残留 generic answer-restoration language。

## Formal 任务家族

观察到的实现：

- `v2/benchmark/task_registry.py` 注册 5 个 formal families，期望 case 数分别为 8、5、5、4、3。
- `load_registered_formal_samples()` 加载 JSON samples，并在数量不匹配时 raise。
- `live_runner` 对非 compare formal suites 默认使用 registered formal samples。

证据：

- Fresh formal artifacts 显示 `family_count=5`、`L3_case_count=25`、`L3_quality_pass_count=25`。
- Source assets 位于 `v2/benchmark/samples/formal_financial_family` 和 `tasks/formal/*/samples`。

真实落地部分：

- 25-case / 5-family formal internal benchmark 真实存在。
- Families 覆盖 single metric、multi-period trend、cross-table join、conditional aggregation、anomaly detection。

模拟、deterministic 或 harness 部分：

- `tasks/formal/*/validator.py` 是简单 helper，不是 primary runner contract。
- 主 gate 使用 `v2/runtime/smoke.py` 中的通用 `expected_facts`。

主要风险：

- 把 family validators 称为“真实 validator”会夸大其集成程度。

建议修复：

- 要么把 family-specific validators 接入 runner，要么将其移除或重命名为 helper examples。

## 外部 baseline / formal superiority

观察到的实现：

- `v2/benchmark/external_text_baseline.py` 实现 pure-text four-role external baseline。
- `v2/benchmark/comparator_runner.py` 计算 fairness 和 superiority gates。
- `scripts/run_v2_local_api_comprehensive_stats.sh` 已新增 API+local formal compare stage。

证据：

- `local_api_20260706_191835/r01_06_formal_compare_api_local_memfd` 已跑 API+local+memfd formal compare。
- 该 historical stage 的 scope 是 `formal_financial_family` 8 cases，不是 full formal registry 25 cases / 5 families。
- 该 historical stage 输出 `fixed_answer_external_comparison_valid=false`、`formal_headline_eligible=false`、`formal_superiority_claim_allowed=true`，暴露了 pre-fix gate 字段混用。
- sample 6/7/8 的 external failure 集中在旧 `revenue_value` schema，而不是 route/tool/fairness gate。
- 修复后 `v2-targeted-json-retry-compare-20260707_192452` 输出 `formal_financial_family_8case_compare`、case count 8、registry count 25、full coverage false，并在该 8-case scope 下 strict equal-quality valid。
- 最新 `local_api_20260707_163354/r01_06_formal_compare_api_local_memfd` 也输出相同 8-case scope，fairness gate 8/8 通过，strict equal-quality valid；但 `formal_external_claim_kind=debug_only`，不支持本次 efficiency superiority。

真实落地部分：

- External compare machinery 存在。
- API+local formal financial 8-case compare 已有 post-fix targeted artifact 和 latest full comprehensive artifact。
- fairness hard gate 在 latest full comprehensive compare 中 8/8 通过。
- compare gate 字段和 external metric schema 已修复，8-case strict equal-quality compare 可以作为局部证据；efficiency-superiority 只能按具体 run 单独引用。

模拟、deterministic 或 harness 部分：

- 当前 compare 不是 full registry compare。
- historical artifacts 中 strict equal-quality efficiency compare 与 quality-superiority compare 的字段语义混用；post-fix artifacts 必须优先引用新 gate fields。
- `revenue_value` schema 已迁移到 `metric_name` / `metric_value`；旧字段只应作为兼容字段。

主要风险：

- 把 local+api formal financial 8-case compare 写成 full formal external superiority。
- 引用 pre-fix artifact 时，把旧 schema/gate failure 写成当前质量结论。

建议修复：

- compare gate 字段、compare scope metadata、`metric_value` / `metric_name` schema 已完成 targeted 与 comprehensive core 复验；下一步是 registry-backed formal external compare。

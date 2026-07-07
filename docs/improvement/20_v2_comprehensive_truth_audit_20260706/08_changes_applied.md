# 已应用变更

## V2-AUDIT-002：answer restoration metric 过度声明

变更文件：

- `v2/runtime/driver.py`
- `v2/benchmark/continuous_runner.py`
- `tests/v2/test_continuous_runner.py`

变更内容：

- Runtime exact replay 仍会增加 `exact_replay_count`。
- Runtime 不再增加 `answer_restoration_replay_count`。
- Continuous report 代码不再从 exact replay 合成缺失的 answer-restoration metrics。
- Tests 现在要求 family、case、collection summaries 中 `answer_restoration_replay_count == 0.0`。

原因：

- 当前没有实现 generic answer-restoration feature。Exact replay 是不同的 replay class，不能制造该 claim surface。

验证：

- 第一次 focused pytest 暴露了一个旧 collection assertion。
- 修复后 `tests/v2/test_continuous_runner.py`：11 passed。
- 修复后 focused command：49 passed。

## V2-AUDIT-004：CodeAct 历史 diagnostic 过度声明风险

变更文件：

- `docs/reports/v2_experiment_summary_20260703.md`

变更内容：

- 增加说明：CodeAct section 是 2026-07-04 的历史 diagnostic。
- 将 summary row 从强 claim “CodeAct LLM generation stability” 改为 historical diagnostic record。

原因：

- 当前 formal benchmark evidence 不证明 realtime LLM code generation。

验证：

- Source review 确认当前 CodeAct path 是 bounded/controlled。
- 本审计 formal benchmark artifacts 是 deterministic/local，不是 API codegen proof。

## 审计证据与文档

新增：

- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/00_executive_summary.md`
- `01_document_source_map.md`
- `02_git_history_and_change_review.md`
- `03_code_truth_review.md`
- `04_docs_artifacts_resolution_ledger.md`
- `05_merged_issue_ledger.md`
- `06_test_and_benchmark_evidence.md`
- `07_fix_plan.md`
- `08_changes_applied.md`
- `09_remaining_risks.md`
- `appendix_commands_and_artifacts.md`
- `artifacts/` 下 benchmark artifacts

提交状态：

- 本次 closure pass 未创建 commit；当前变更仍留在工作区，等待人工 review/commit。

## V2-AUDIT-012/013/014：formal compare gate、scope 和 metric schema

变更文件：

- `v2/benchmark/comparator_runner.py`
- `v2/benchmark/models.py`
- `v2/benchmark/scoring.py`
- `v2/benchmark/external_text_baseline.py`
- `v2/benchmark/fixed_answer_runner.py`
- `v2/runtime/smoke.py`
- `v2/runtime/codeact.py`
- `v2/benchmark/samples/formal_financial_family/*.json`
- `tests/v2/test_compare_diagnostics.py`
- `tests/v2/test_fixed_answer_and_external_baseline.py`
- `tests/v2/test_runtime_and_benchmark.py`

变更内容：

- compare output 拆出 strict equal-quality gate、quality-superiority gate、formal efficiency/quality claim flags 和 `formal_external_claim_kind`。
- formal compare payload 输出 8-case compare scope 与 25/5 registry scope，避免继承 internal formal scope。
- fixed-answer / external baseline schema 迁移到 `metric_name` / `metric_value`，`revenue_value` 仅兼容旧字段。

验证：

- `tests/v2/test_runtime_and_benchmark.py::test_fixed_answer_metric_value_schema_distinguishes_requested_metric_from_revenue tests/v2/test_compare_diagnostics.py`：6 passed。
- `v2-targeted-json-retry-compare-20260707_192452`：formal financial 8-case compare exit 0，strict equal-quality valid，full registry coverage false。

后续补丁：

- `v2/benchmark/external_text_baseline.py`：external fairness gate 现在接受 prompt 中可见的 `route::tool` candidate key 被回填到 raw `route` slot 的情况；若 `tool_name` 冲突或 choice 不可见，仍拒绝。
- `tests/v2/test_fixed_answer_and_external_baseline.py`：新增 candidate-key route slot 接受/拒绝 regression tests。

后续验证：

- `tests/v2/test_fixed_answer_and_external_baseline.py tests/v2/test_compare_diagnostics.py tests/v2/test_runtime_and_benchmark.py::test_fixed_answer_metric_value_schema_distinguishes_requested_metric_from_revenue`：53 passed。
- `local_api_20260707_163354/r01_06_formal_compare_api_local_memfd`：fairness gate pass count 8，failed case count 0，strict equal-quality valid。

## V2-AUDIT-018：role JSON response bounded retry

变更文件：

- `v2/runtime/role_path.py`
- `tests/v2/test_fixed_answer_and_external_baseline.py`

变更内容：

- Planner / Retriever / Executor / Summarizer 的 API JSON extraction boundary 增加 bounded retry。
- retry 仅重试 JSON response，不做 candidate fallback，不绕过 strict visible-candidate validation。
- 聚合 retry attempts 的 token usage 和 prompt bytes。

验证：

- `tests/v2/test_fixed_answer_and_external_baseline.py`：45 passed。
- smoke/minimal targeted set：4 passed。
- `v2-targeted-json-retry-formal-20260707_191045`：formal internal API+local+memfd 25/25，5 families，memfd transfer 25。

## V2-AUDIT-019：OpenAI-compatible transport transient retry

变更文件：

- `runtime/llm.py`
- `tests/v2/test_fixed_answer_and_external_baseline.py`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/`

变更内容：

- Provider config 增加 `request_max_attempts`、`retry_initial_delay_s`、`retry_max_delay_s`。
- OpenAI-compatible client 在 provider boundary 对 connection error、timeout、408/409/429/5xx transient status 做 bounded retry。
- retry budget 用尽后仍抛出原始 API exception，不把失败改写为 benchmark pass。

触发证据：

- `local_api_20260707_115051` 的 required stages 全部通过，但 optional continuous / continuous replay / flagship 分别因 API connect error 和 read timeout 失败。
- 该 run 的 `failed_required_stage_count=0`，但 `failed_stages=["r01_09_continuous_api_local","r01_10_continuous_replay_api_local","r01_12_flagship_ablation_api_local"]`。

验证：

- `python -m py_compile runtime/llm.py tests/v2/test_fixed_answer_and_external_baseline.py`：通过。
- `test_openai_compatible_client_retries_transient_transport_error`、`test_openai_compatible_client_stops_after_transport_retry_budget`：2 passed。
- `local_api_20260707_163354`：full `STATEBUS_LOCAL_API_RUN_FLAGSHIP=1` comprehensive 13 stages 全部 exit 0。

限制：

- 外部 API transient failure 仍可能发生，但 transport retry 已不再是当前 latest evidence blocker；flagship stress 仍只有 3/6 pass，不能写成 all-pass。

## V2-AUDIT-020：strict visible-candidate selection retry

变更文件：

- `v2/runtime/role_path.py`
- `tests/v2/test_fixed_answer_and_external_baseline.py`

变更内容：

- Retriever / Executor selection normalization 遇到 `RoleSelectionError` 时，用 visible candidate list 做 bounded retry。
- Retry 后仍拒绝不可见 candidate、route/tool 冲突和 strict parser failure。
- 不引入 best-candidate fallback。

触发证据：

- `local_api_20260707_130958` 的 required、continuous、continuous replay 和 replay negative stages 均通过，但 optional flagship 因 `strict_visible_candidate_mismatch:csv_profiler::csv_profiler` 失败。

验证：

- `python -m py_compile v2/runtime/role_path.py tests/v2/test_fixed_answer_and_external_baseline.py`：通过。
- `python -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py -k 'role_path_retries_strict or candidate_key_route_slot_with_conflicting_tool'`：4 passed。
- `local_api_20260707_163354`：full `STATEBUS_LOCAL_API_RUN_FLAGSHIP=1` comprehensive 13 stages 全部 exit 0，flagship stage exit 0。

## V2-AUDIT-015/016：local+api diagnostics bundle、timeout env 与 focused coverage

变更文件：

- `scripts/run_v2_local_api_comprehensive_stats.sh`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_034412/`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/`

变更内容：

- Summary 现在为 compare cases 输出 expected / external observed / StateBus observed structured fields，不再只依赖 failed cases。
- Host artifact copy 阶段复制 nested benchmark reports、external/statebus case outputs、state metadata、hydration audit、ref registry 和 socket path audit。
- Focused pytest gate 纳入 control/UDS/subprocess tests。
- Wrapper summary 记录 container activation script、Python、CUDA、package versions。
- Wrapper 同时接受 `STATEBUS_LOCAL_API_*_TIMEOUT_SECONDS` 与派生的 `*_TIMEOUT_SECONDS`，并把两组 env 都传入 container，避免 host 设置被 container 默认值覆盖。

验证：

- `bash -n scripts/run_v2_local_api_comprehensive_stats.sh`：通过。
- `local_api_20260707_034412/stages/02_pytest_focused_v2/console.log`：109 passed。
- Docker root control subset：9 passed。
- `local_api_20260707_034412/diagnostics/manifest.json`：copied_file_count=2310。
- `local_api_20260707_034412/summary.json`：formal compare diagnostics 包含 8 个 formal financial compare cases。
- dry run 显示 timeout override 生效：formal 3600s、continuous 4200s、replay 4200s。
- `local_api_20260707_091807/stages/02_pytest_focused_v2/console.log`：111 passed。
- `local_api_20260707_091807/summary.json`：12 stages 全部 exit 0，required failed stage count 0。
- `local_api_20260707_091807/diagnostics/manifest.json`：copied_file_count=1384，证明 exit 0 后 docs artifact copy 自动填充。
- `local_api_20260707_163354/stages/02_pytest_focused_v2/console.log`：115 passed。
- `local_api_20260707_163354/summary.json`：13 stages 全部 exit 0，required failed stage count 0。
- `local_api_20260707_163354/diagnostics/manifest.json`：copied_file_count=2558，按 wrapper 诊断拷贝逻辑补齐。

限制：

- `local_api_20260707_034412` 不是 passing comprehensive run；required formal internal stage timeout，formal compare 是 debug-only。
- `local_api_20260707_091807` 是历史 passing comprehensive core run，但 flagship 已显式关闭。
- `local_api_20260707_163354` 是 latest full `RUN_FLAGSHIP=1` passing comprehensive run，但 flagship stress 只有 3/6，不是 all-pass。

## 2026-07-07 contest audit documentation pass

变更文件：

- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/code_truth_vs_experiment_issue_matrix_zh.md`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/05_merged_issue_ledger.md`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/06_test_and_benchmark_evidence.md`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/07_fix_plan.md`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/09_remaining_risks.md`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/10_contest_oriented_followup_plan_20260707.md`
- `docs/reports/v2_experiment_summary_20260703.md`

变更内容：

- 增加 A-H 赛题导向复核结论：token fairness、flagship 3/6、StateRef claim boundary、formal compare 25/5 gap、v2 text/protocol gap、openEuler VM gap、历史报告误用风险、prompt/completion schema gap。
- 新增 V2-AUDIT-024 到 V2-AUDIT-028：formal compare token split、StateRef additive boundary、flagship family diagnosis、registry compare adapter gap、historical report warning。
- 把 flagship 失败 family 更新为“已诊断但未修复”，并记录 `incident_diagnosis_v2`、`long_doc_metric_replay_v1`、`cross_period_financial_v1` 的不同失败原因。
- 明确 latest full compare 只能支持 prompt/input/control-byte savings，不能支持 total-token superiority 或 efficiency-superiority claim。
- 补强历史实验报告 warning，避免 2026-07-04 `Container (openEuler)`、bwrap、old formal efficiency/superiority flags 被当成当前交付证据。

验证：

- 本 pass 为文档更新，没有改代码路径。
- 需要运行：`bash -n scripts/run_v2_local_api_comprehensive_stats.sh`、`git diff --check`。

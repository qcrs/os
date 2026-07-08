# 合并 Issue Ledger

## ID: V2-AUDIT-001

严重级别：P1

标题：容器 activation 指令与当前运行容器不匹配。

来源：audit prompt、Docker-root verification

影响文件：`deploy/activate_statebus_host.sh`、Docker image/runtime docs

证据：在 `statebus-dev-qcrs` 中执行 `source deploy/activate_statebus_host.sh` 失败，原因是 conda 缺失；repo mount 实际为 `/workspace/statebus/project`，不是 `/workspace`。后续 wrapper 已优先使用 `/usr/local/bin/activate_statebus_container.sh`，`local_api_20260707_163354` 记录 activation status `success`、Python `/usr/bin/python3`、Torch `2.5.1+cu121`、CUDA available。

影响：要求的验证可能静默变成 host verification 或未激活的 container verification。

修复策略：container path 使用 `/usr/local/bin/activate_statebus_container.sh`；不要要求 container root source host conda activation。若后续需要 host conda path，也必须作为 host-only contract 写清。

验证：`local_api_20260707_163354/summary.json` environment block；Docker root command `cd /workspace/statebus/project && source /usr/local/bin/activate_statebus_container.sh && /usr/bin/python3 -m pytest -q tests/v2/test_control_plane.py tests/v2/test_uds_loopback.py tests/v2/test_subprocess_executor.py` 通过 9 tests。

状态：partial；container activation path 已验证，legacy host activation command 不应再作为 container contract

## ID: V2-AUDIT-002

严重级别：P1

标题：Exact replay 曾被错误计入 answer restoration。

来源：`17e_remediation_plan.md`、code audit、failed pytest

影响文件：`v2/runtime/driver.py`、`v2/benchmark/continuous_runner.py`、`tests/v2/test_continuous_runner.py`

证据：runtime metric 与 continuous runner fallback 曾使 `answer_restoration_replay_count == exact_replay_count`。

影响：这会制造虚假的 generic answer-restoration claim surface。

修复策略：在真实 answer-restoration 机制实现前，answer restoration 保持 zero。

验证：`tests/v2/test_continuous_runner.py` 11/11 通过；focused pytest 49/49 通过。

状态：本审计已修复

## ID: V2-AUDIT-003

严重级别：P1

标题：Formal external compare 已有 local+api 证据，但不能作为 full formal superiority。

历史来源：已清理的 `19_claim_upgrade_completion_report_20260706.md`、已清理的 `17f_safe_claim_language.md`、comparator source review

影响文件：`v2/benchmark/comparator_runner.py`、`v2/benchmark/live_runner.py`、`scripts/run_v2_local_api_comprehensive_stats.sh`、docs

证据：`local_api_20260706_191835` 中 `r01_06_formal_compare_api_local_memfd` 已运行 API+local+memfd formal compare，但实际 scope 是 `formal_financial_family` 8 cases，不是 formal registry 25 cases / 5 families；同时该 pre-fix stage 输出 `fixed_answer_external_comparison_valid=false`、`formal_headline_eligible=false`、`formal_superiority_claim_allowed=true`。修复后 `v2-targeted-json-retry-compare-20260707_192452` 输出 `formal_financial_family_8case_compare`、case count 8、registry count 25、full coverage false，并在该 8-case scope 下 strict equal-quality valid。最新 `local_api_20260707_163354` full comprehensive 同样证明 8-case strict equal-quality valid、公平门 8/8，但本次 `formal_external_claim_kind=debug_only`，不能支持 efficiency-superiority claim。

影响：External superiority 是高价值 contest claim；当前证据只能作为 formal financial 8-case compare 的调试/局部质量信号，不能写成 full formal registry external superiority。

修复策略：拆分 strict equal-quality compare 与 quality-superiority compare；补 formal compare scope metadata；修 external metric schema；再实现 registry-backed formal external compare。

验证：targeted rerun 已明确输出 compare scope、case count、claim kind。`local_api_20260707_163354` full comprehensive 输出 8-case scope fields、all-case structured diagnostics、fairness pass count 8、failed count 0。full registry compare 仍未实现。

状态：partial；8-case formal financial strict equal-quality compare complete，targeted run 支持该 scope 下 prompt/token efficiency claim，但 latest full comprehensive 不支持本次 efficiency superiority；full 25/5 registry external compare 仍 open

## ID: V2-AUDIT-004

严重级别：P1

标题：当前 formal benchmark 未证明 CodeAct realtime LLM code generation。

来源：historical experiment summary、CodeAct source review

影响文件：`docs/reports/v2_experiment_summary_20260703.md`、`v2/runtime/codeact.py`、`v2/runtime/codeact_sandbox.py`

证据：当前 formal audit evidence 是 bounded deterministic/local benchmark evidence；旧 5/5 CodeAct LLM diagnostic 是历史记录。

影响：Realtime code-generation claim 会夸大当前 benchmark。

修复策略：保持 bounded CodeAct wording；如需升级，增加 formal API CodeAct run。

验证：已新增 report warning；未来升级需要 API CodeAct artifact。

状态：文档降级已部分修复；feature claim unsupported

## ID: V2-AUDIT-005

严重级别：P2

标题：Family validator 文件是 helper artifacts，不是 active primary validators。

来源：`18_claim_upgrade_execution_plan.md`、source search

影响文件：`tasks/formal/*/validator.py`、`v2/runtime/smoke.py`

证据：`validator.py` 文件定义简单 `validate_output`，但 benchmark validation 使用 `_expected_fact_pass`。

影响：Validator integration 可能被过度声明。

修复策略：把 validators 接入 task loading，或重命名/删除为 helper examples。

验证：添加 failing family-specific validator test，并确认它会导致 benchmark fail。

状态：open

## ID: V2-AUDIT-006

严重级别：P1

标题：Deterministic formal evidence 与 local+api evidence 必须分层引用。

来源：formal artifact review、role-path source review

影响文件：docs、benchmark reports

证据：早期 fresh formal JSON 记录 `role_path_mode=deterministic`；`local_api_20260707_163354/r01_05_formal_api_local_memfd` 已补充 API+local+memfd formal internal 证据，但 formal compare 仍只有 financial 8-case scope。

影响：deterministic backend artifacts、API formal internal artifacts、API formal compare artifacts 的 claim 范围不同；混写会把 strong internal evidence 错写成 external superiority。

修复策略：所有 claim 中都标明 role path、embedding mode、state pool mode、suite scope 和 compare scope；API formal internal 与 API formal compare 分开引用。

验证：docs claim matrix 每条 claim 都能指向对应 artifact；formal internal 指向 `r01_05`，formal compare 指向 `r01_06` 并带 8-case scope。

状态：已修复；post-fix docs 与 targeted compare artifact 均带 role path、embedding mode、state pool mode 和 compare scope

## ID: V2-AUDIT-007

严重级别：P1

标题：State-pool backend observability 此前在 release 后可能低报 actual backend。

来源：`3738f34`、state store tests、fresh formal JSON

影响文件：`v2/state/store.py`

证据：`backend_name` 现在使用 `last_published_storage_kind` 和 publish counts；fresh formal runs 显示 used backend 正确。

影响：`state_pool_mode_used` 必须报告 actual backend，而不是 requested mode。

修复策略：本审计前已修复。

验证：auto/shared_memory/memfd formal artifacts。

状态：本审计前已修复；本审计已验证

## ID: V2-AUDIT-008

严重级别：P2

标题：Memfd unavailable fallback 缺少真实机器验证。

来源：statepool review、test scope review

影响文件：`v2/state/store.py`、tests

证据：memfd 在当前容器可用；unavailable fallback 仍主要是 unit/failure-path evidence。

影响：fallback robustness claim 需要更接近真实负向环境的证据。

修复策略：增加 no-memfd validation stage 或显式 capability-masked subprocess test。

验证：归档 memfd unavailable 且 fallback 遵守 shared-memory budget 的 run。

状态：open

## ID: V2-AUDIT-009

严重级别：P1

标题：端到端速度优势不受支持。

历史来源：已清理的 `17f_safe_claim_language.md`、已清理的 `19_claim_upgrade_completion_report_20260706.md`

影响文件：docs/reports

证据：本审计未做 serialized formal external API timing rerun。`local_api_20260707_163354` 的 formal compare 虽然 strict equal-quality valid，但 `api_task_ms_delta=86580.45313599998` 为正，`formal_efficiency_superiority_claim_allowed=false`。

影响：没有 controlled same-tier reruns 时，speed claim 很容易失效。

修复策略：保持 unsupported；要求 serialized benchmark reruns。

验证：同 tier StateBus vs external compare，且 quality/fairness gate pass，并且 serialized timing 方向支持该 claim。

状态：open；unsupported

## ID: V2-AUDIT-010

严重级别：P2

标题：未执行 openEuler VM validation。

来源：AGENTS constraints、audit prompt

影响文件：docs/deploy claims

证据：本轮审计使用运行中的 container，不是 openEuler VM validation stage。

影响：Compatibility claim 不能从非 VM 证据推出。

修复策略：运行 VM validation stage 并归档 output。

验证：VM command log 和 report。

状态：open；unsupported

## ID: V2-AUDIT-011

严重级别：P2

标题：容器缺少 `jq`，prompt extraction command 不可移植。

来源：Docker-root command failure

影响文件：Docker image、audit scripts

证据：`bash: line 1: jq: command not found`；Python extraction 成功。

影响：必要 audit scripts 不应依赖缺失工具。

修复策略：在 image 中安装 `jq`，或加入 repo-local Python fallback extractor。

验证：`docker exec ... jq --version` 或 Python fallback script 通过。

状态：open；已使用 workaround

## ID: V2-AUDIT-012

严重级别：P0

标题：Formal compare gate 同时表达 strict efficiency compare 与 quality superiority，字段语义混用。

来源：`local_api_20260706_191835`、`v2/benchmark/comparator_runner.py`、`code_truth_vs_experiment_issue_matrix_zh.md`

影响文件：`v2/benchmark/comparator_runner.py`、`tests/v2/test_compare_diagnostics.py`、docs

证据：pre-fix `r01_06_formal_compare_api_local_memfd` 中 `fixed_answer_external_comparison_valid=false`、`formal_headline_eligible=false`、`formal_superiority_claim_allowed=true` 同时出现。源码中 `_headline_metrics()` 要求双方 headline eligible；metadata 中 quality-superiority path 又允许 external quality floor 不满分。

影响：报告会让文档生成和人工审计混淆，无法判断当前是 strict equal-quality efficiency compare 失败，还是 quality-superiority compare 成立。

修复策略：新增 `strict_equal_quality_comparison_valid`、`quality_superiority_comparison_valid`、`formal_quality_superiority_claim_allowed`、`formal_efficiency_superiority_claim_allowed`、`formal_external_claim_kind`；保留 legacy 字段时必须明确其严格语义。

验证：`tests/v2/test_compare_diagnostics.py` 通过；`v2-targeted-json-retry-compare-20260707_192452` 输出 `strict_equal_quality_comparison_valid=true`、`formal_external_claim_kind=efficiency_superiority_equal_quality`；`local_api_20260707_163354` 输出 `strict_equal_quality_comparison_valid=true`、`formal_external_claim_kind=debug_only`。

状态：已修复并以 targeted compare 复验；legacy 字段仍保留但语义已标注

## ID: V2-AUDIT-013

严重级别：P0

标题：Formal compare 覆盖面只有 financial 8 cases，不能继承 formal internal 25/5 scope。

来源：`v2/benchmark/live_runner.py`、`local_api_20260706_191835`

影响文件：`v2/benchmark/live_runner.py`、`v2/benchmark/comparator_runner.py`、`scripts/run_v2_local_api_comprehensive_stats.sh`、docs

证据：formal non-compare 使用 `load_registered_formal_samples()`；formal compare fall through 到 `load_fixed_answer_family()`。`r01_06` metadata 只给出 `external_comparator_claim_scope=formal_financial_family`，没有 case/family/scope label。

影响：容易把 formal internal 25 cases / 5 families 的结果误写成 formal external compare 25 cases / 5 families。

修复策略：compare payload 输出 `formal_compare_scope_label`、`formal_compare_case_count`、`formal_compare_family_count`、`formal_registry_case_count`、`formal_compare_full_registry_coverage`。

验证：`v2-targeted-json-retry-compare-20260707_192452` 和 `local_api_20260707_163354` 均显示 `formal_financial_family_8case_compare`、case count 8、registry count 25、family count 5、full coverage false。

状态：已修复；full registry compare 仍是独立后续项

## ID: V2-AUDIT-014

严重级别：P1

标题：Fixed-answer / external baseline 用 `revenue_value` 表示任意 metric value，误导非 revenue 样本。

来源：`v2/benchmark/scoring.py`、`v2/benchmark/external_text_baseline.py`、formal financial samples、local+api per-case outputs

影响文件：`v2/benchmark/scoring.py`、`v2/benchmark/external_text_baseline.py`、`v2/benchmark/samples/formal_financial_family/*.json`、tests

证据：`benchmark-sample-7` 期望 operating income 19，但 external structured `revenue_value=120`；summary 已写 operating income 19。`benchmark-sample-6`、`benchmark-sample-8` 的 gross margin 也表现相同。

影响：external 失败不能直接解释为模型没有抽取正确事实；这是 prompt/schema 对 metric 字段的错误激励。

修复策略：引入 `metric_name` / `metric_value`，scorer 优先读 metric 字段，external prompt 要求返回 requested metric 对应的值；保留 `revenue_value` 兼容老样本。

验证：`tests/v2/test_runtime_and_benchmark.py::test_fixed_answer_metric_value_schema_distinguishes_requested_metric_from_revenue` 与 `tests/v2/test_fixed_answer_and_external_baseline.py` 通过；post-fix targeted compare 8/8 strict valid。

状态：已修复；`revenue_value` 仅作为兼容字段保留

## ID: V2-AUDIT-015

严重级别：P1

标题：local+api artifact copy 曾缺少 nested comparator reports 和 per-case diagnostics。

来源：`scripts/run_v2_local_api_comprehensive_stats.sh`、run workdir inspection

影响文件：`scripts/run_v2_local_api_comprehensive_stats.sh`、docs artifacts

证据：pre-fix host copy 只复制 `${HOST_RESULT_ROOT}/artifacts`；formal compare 的 nested `runtime/benchmark_reports/*compare*.json`、external/statebus per-case outputs、state metadata、hydration audit、ref registry 仍留在 `/home/qcrs/statebus/runs/.../work/...`。

影响：docs artifact 不自足，后续只能靠手工查原始 runs 复盘 sample 失败、非文本 state、registry refs。

修复策略：增加 diagnostics bundle copy，复制 nested benchmark reports、external/statebus case outputs、state metadata、hydration audit、ref registry、socket path audit，并在 summary 中列出 compare case expected/observed structured fields。

验证：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_034412/diagnostics/manifest.json` 显示 copied_file_count=2310；`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/diagnostics/manifest.json` 显示 copied_file_count=1384，且由 wrapper 在 exit 0 后自动生成；`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/diagnostics/manifest.json` 显示 copied_file_count=2558，按 wrapper 诊断拷贝逻辑补齐。`summary.json` 的 `compare_case_diagnostics.r01_06_formal_compare_api_local_memfd` 有 8 个 compare cases 的 expected/external/statebus structured fields。

状态：已修复并在 `local_api_20260707_163354` docs artifact copy 中验证；后续仍可补测 nonzero container exit 后的 host-copy 行为

## ID: V2-AUDIT-016

严重级别：P2

标题：local+api focused pytest 未覆盖 control/UDS/subprocess memfd tests。

来源：`scripts/run_v2_local_api_comprehensive_stats.sh`、`tests/v2/`

影响文件：`scripts/run_v2_local_api_comprehensive_stats.sh`、`tests/v2/test_control_plane.py`、`tests/v2/test_uds_loopback.py`、`tests/v2/test_subprocess_executor.py`

证据：早期 focused pytest 只跑 `test_state_materialization.py`、`test_minimal_benchmark.py`、`test_preflight_and_live_runner.py`、`test_continuous_runner.py`。`v2-local-api-20260707_015709` 的 focused pytest 已扩展并通过 107 tests；`local_api_20260707_034412` focused pytest 通过 109 tests；`local_api_20260707_091807` focused pytest 通过 111 tests；`local_api_20260707_163354` focused pytest 通过 115 tests，包含 control/UDS/subprocess coverage。

影响：不能把 local+api focused green 直接写成 subprocess memfd / UDS typed control 全面覆盖。

修复策略：把 control/UDS/subprocess tests 加入 focused gate，或新增 `STATEBUS_LOCAL_API_PYTEST_MODE=control` stage。

验证：`v2-local-api-20260707_015709` 中 `02_pytest_focused_v2`：107 passed；`local_api_20260707_034412/stages/02_pytest_focused_v2/console.log`：109 passed；`local_api_20260707_091807/stages/02_pytest_focused_v2/console.log`：111 passed；`local_api_20260707_163354/stages/02_pytest_focused_v2/console.log`：115 passed；Docker root focused control command：9 passed。

状态：已修复；formal benchmark 主路径仍是 loopback harness，subprocess benchmark stage 仍未新增

## ID: V2-AUDIT-018

严重级别：P1

标题：live API role JSON response 缺少 bounded retry，空响应或 malformed JSON 会打断 formal/continuous stage。

来源：`v2-local-api-20260707_015709`、`v2/runtime/role_path.py`

影响文件：`v2/runtime/role_path.py`、`tests/v2/test_fixed_answer_and_external_baseline.py`

证据：`r01_05_formal_api_local_memfd` 因 executor 返回空字符串失败；`r01_10_continuous_replay_api_local` 因 summarizer JSON 中 summary 字段后多一个 semicolon 失败。

影响：单次 API 输出格式抖动会把整套 formal/API run 打断，且失败不是 route/tool 语义错误。

修复策略：在 planner/retriever/executor/summarizer 的 JSON extraction boundary 增加 bounded retry；仍由原有 strict parser 和 visible-candidate normalization 负责最终校验，不做候选 fallback。

验证：新增 regression tests 覆盖 empty executor first response 和 malformed summarizer first response；`tests/v2/test_fixed_answer_and_external_baseline.py` 45 passed；`v2-targeted-json-retry-formal-20260707_191045` formal internal 25/25；`v2-targeted-json-retry-compare-20260707_192452` formal compare exit 0；`local_api_20260707_163354` full comprehensive 13 stages 全部 exit 0。

状态：已修复并 targeted 复验

## ID: V2-AUDIT-019

严重级别：P1

标题：live API transport transient error 会打断长时间 optional benchmark stage。

来源：`v2-local-api-20260707_115051`、`runtime/llm.py`

影响文件：`runtime/llm.py`、`tests/v2/test_fixed_answer_and_external_baseline.py`

证据：`local_api_20260707_115051` 是 `STATEBUS_LOCAL_API_RUN_FLAGSHIP=1` 的 full rerun attempt。required stages 全部 clean，但 optional `r01_09_continuous_api_local` 在约 970s 后因 `openai.APIConnectionError` / `httpx.ConnectError: [Errno -2] Name or service not known` 失败；`r01_10_continuous_replay_api_local` 启动后同类 DNS/connect error 失败；`r01_12_flagship_ablation_api_local` 因 `openai.APITimeoutError` / `httpx.ReadTimeout` 失败。

影响：长时间 local+api comprehensive run 会被单次 provider transport 抖动打断。该失败不是 benchmark quality/fairness/schema failure，但会阻止 optional continuous/replay/flagship 证据产出。

修复策略：在 OpenAI-compatible client boundary 增加 bounded transport retry，只捕获 API connection、timeout、408/409/429/5xx 这类 transient error；不捕获最终业务校验错误，不改变 role JSON retry、candidate validation 或 scorer 语义。

验证：`python -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py::test_openai_compatible_client_retries_transient_transport_error tests/v2/test_fixed_answer_and_external_baseline.py::test_openai_compatible_client_stops_after_transport_retry_budget` 通过；`python -m py_compile runtime/llm.py tests/v2/test_fixed_answer_and_external_baseline.py` 通过。`local_api_20260707_163354` 在 transport retry patch 后完成 full `RUN_FLAGSHIP=1` comprehensive，13 stages 全部 exit 0。

状态：已修复并由 full `RUN_FLAGSHIP=1` comprehensive 复验；外部 API 仍可能有 transient failure，但该缺口不再是当前 evidence blocker

## ID: V2-AUDIT-020

严重级别：P1

标题：strict visible-candidate mismatch 会打断 flagship selection path。

来源：`v2-local-api-20260707_130958`、`v2/runtime/role_path.py`

影响文件：`v2/runtime/role_path.py`、`tests/v2/test_fixed_answer_and_external_baseline.py`

证据：`local_api_20260707_130958` 在 transport retry 后完成 required、continuous、continuous replay 和 replay negative stages，但 optional `r01_12_flagship_ablation_api_local` 因 `strict_visible_candidate_mismatch:csv_profiler::csv_profiler` 失败。该失败不是质量 gate，也不是 external schema 问题，而是 API selection response 没有满足 strict visible-candidate normalization。

影响：长时间 flagship stage 会因为单次 selection response 格式/别名不稳定失败。若简单 fallback 到 best candidate，会破坏 visible-candidate fairness 和 strict validation 语义。

修复策略：retriever/executor selection normalization 遇到 `RoleSelectionError` 时，用可见 candidate list 做 bounded retry；retry 后仍不接受不可见 candidate、冲突 candidate 或 best-candidate fallback。

验证：`python -m py_compile v2/runtime/role_path.py tests/v2/test_fixed_answer_and_external_baseline.py` 通过；strict retriever/executor visible-candidate mismatch retry regression tests 通过；`local_api_20260707_163354` full `RUN_FLAGSHIP=1` comprehensive 13 stages 全部 exit 0，flagship stage 不再卡在该路径。

状态：已修复并由 full `RUN_FLAGSHIP=1` comprehensive 复验

## ID: V2-AUDIT-017

严重级别：P1

标题：非文本中间状态 claim 需要限定为 embedding semantic state + hydration accounting。

来源：`v2/state/store.py`、`v2/refs/models.py`、`v2/runtime/driver.py`、sample 7 metadata/hydration audit

影响文件：docs、telemetry summaries、benchmark reports

证据：sample 7 的 materialized state 为 `object_kind=EMBEDDING_STATE`、`storage_kind=memfd`；hydration audit 显示各 role 仍接收 selected text/table/artifact prompt slices。

影响：如果写成“证据不进 prompt”或“hidden-state/KV transfer”，就是过度 claim。

修复策略：文档精确写成 embedding semantic state transfer、StateRef/registry、role hydration accounting；若要更强 claim，增加 evidence pack/table slice 的非文本 materialization stage。

验证：benchmark summary 明确 object kind 和 prompt-visible bytes；docs 不再把 semantic state 扩写成 KV/hidden-state。

状态：partial；文档边界已明确为 embedding semantic state + hydration accounting，raw evidence replacement / hidden-state / KV transfer 仍 unsupported

## ID: V2-AUDIT-021

严重级别：P0（交付阻塞）

标题：openEuler 24.03-LTS-SP3 交付要求未验证。

来源：`docs/reference/题目.md` 交付要求；本轮赛题导向审计 2026-07-07

影响文件：`scripts/`、`deploy/`、交付文档

证据：赛题明确要求「最终交付的代码需在 openEuler 24.03-LTS-SP3 操作系统版本上能够正常编译、运行和测试」。当前所有证据（含 `local_api_20260707_163354`）均在 Docker + Ubuntu 20.04 host + openEuler container 环境下产出；`docs/constraints/current_host_and_migration.md` 明确将 openEuler VM 定位为后验验证阶段，但该阶段仍未执行。

影响：答辩/评审时无法提供 openEuler 上的可复现运行证明。

修复策略：编写或完善 `scripts/setup_openeuler_env.sh`；在 openEuler 24.03-LTS-SP3 VM 中验证核心依赖安装（faiss-cpu、sentence-transformers、protobuf、pydantic）；跑通 `python3 -m runtime.smoke` 和至少 `tests/v2/test_minimal_benchmark.py`；归档日志。

验证：`docs/improvement/openeuler_validation_YYYYMMDD/smoke_pass.log` 存在，exit 0。

状态：open；交付阻塞

## ID: V2-AUDIT-022

严重级别：P1

标题：演示视频缺失，赛题提交必须项。

来源：`docs/reference/题目.md` 提交内容要求；本轮赛题导向审计 2026-07-07

影响文件：无代码；属于交付材料

证据：赛题要求「提交完整源码、系统设计文档、部署文档、实验报告和演示视频，能够支持评审现场」。当前文档树中无任何视频制作计划、脚本或录制产物。

影响：评审环节缺少演示视频会直接影响评委对系统功能的判断。

修复策略：规划视频内容（见 `10_contest_oriented_followup_plan_20260707.md` § 5 Step 6）；录制后归档视频链接或路径。

验证：视频文件或上传链接存在，时长 3-5 分钟。

状态：open

## ID: V2-AUDIT-023

严重级别：P1

标题：V2 formal benchmark 缺少 StateBus text vs protocol 双模对比 stage，影响通信效率（25分）维度举证。

来源：`docs/reference/题目.md` R03；`local_api_20260707_163354` stage 列表；本轮赛题导向审计 2026-07-07

影响文件：`v2/benchmark/live_runner.py`、`scripts/run_v2_local_api_comprehensive_stats.sh`

证据：v2 formal internal `r01_05` 只运行 StateBus API+local+memfd（protocol 模式），没有对应 text 模式 formal stage。「通信效率（25分）」维度的最强 v2 证据来自 v2 smoke（deterministic、非 API）和 `r01_06` `api_prompt_bytes_delta`（StateBus vs external，不是 StateBus protocol vs StateBus text）。赛题要求「在相同任务条件下完成可复现实验对比」，当前 v2 formal 层缺少自身双模 token 对比数据。

影响：通信效率维度（25分）最重要的对比证据仍只有 v1 历史数据，不是 v2 formal API evidence。

修复策略：在 `live_runner.py` 或 `scripts/` 中新增 text 模式 formal benchmark stage（如 `r01_05b_formal_text_mode`）；summary 中提取 `text_total_tokens`、`protocol_total_tokens`、delta。

验证：`summary.json` 中包含 `protocol_vs_text_token_delta`，方向为 protocol < text；与 v1 数字一致。

状态：open

## ID: V2-AUDIT-024

严重级别：P1

标题：formal compare token claim 需要拆成 prompt/input 与 completion/output，latest full run 不能支持 total-token superiority。

来源：`local_api_20260707_163354` nested comparator report；本轮赛题导向复核 2026-07-07

影响文件：`v2/benchmark/comparator_runner.py`、`v2/benchmark/models.py`、summary extraction、docs

证据：`r01_06_formal_compare_api_local_memfd` 是 8-case strict equal-quality compare，external 与 StateBus 都是四角色，`llm_call_count_delta=0`，fairness gate 8/8。StateBus prompt bytes 更低（30661 vs external 43213，delta -12552），prompt tokens 更低（9645 vs 12678），但 completion tokens 更高（19695 vs 10199），total tokens 更高（29340 vs 22877，delta +6463），`formal_external_claim_kind=debug_only`、`formal_efficiency_superiority_claim_allowed=false`。

影响：如果只写“token 更少”或“efficiency superiority”，会把 prompt/input savings 与 completion verbosity 混成一个结论。

修复策略：报告和文档统一区分 `prompt_tokens_delta` / `completion_tokens_delta` / `total_tokens_delta` / `prompt_bytes_delta`；claim 只允许写 prompt/input/control-byte savings，除非 serialized rerun 同时支持 total-token/timing gate。

验证：nested comparator report 中 external/statebus telemetry split 可复盘；未来 `comparison_summary` 或 canonical payload 应显式输出这些 split 字段。

状态：open；claim boundary 已记录，schema split 仍待补

## ID: V2-AUDIT-025

严重级别：P1

标题：StateRef 是 additive semantic-state/hydration mechanism，不是 raw evidence replacement。

来源：`v2/state/store.py`、`v2/runtime/smoke.py`、`v2/refs/models.py`、`local_api_20260707_163354` hydration/ref diagnostics

影响文件：docs、telemetry summaries、future claim text

证据：`LayeredStateStore.publish()` 对 `EMBEDDING_STATE` / dense semantic state 做 memfd/shared_memory/mmap materialization；`runtime.smoke` 记录 `raw_evidence_bytes_seen_by_llm`、`prompt_visible_total_bytes` 和各 role prompt slice refs；`SemanticStateRef` 与 `ExecutionArtifactRef` 在模型层分离。`r01_12` stress summary 的 claim boundary 明确写明不 claim KV or hidden-state transfer。

影响：将 StateRef 写成“证据不进 prompt”或“向模型传隐藏状态/KV”会违反代码事实，也会和 AGENTS 中 Future Work 约束冲突。

修复策略：所有对外 claim 使用“embedding semantic state + typed refs + hydration accounting”；如果要升级为 raw evidence replacement，需要新增 evidence pack/table slice 非文本 materialization 与 LLM-visible evidence boundary test。

验证：`r01_05` semantic state transfer 25、memfd transfer 25；diagnostics bundle 包含 state metadata、hydration audit 和 ref registry。

状态：文档边界已修；更强 non-text evidence replacement claim unsupported

## ID: V2-AUDIT-026

严重级别：P2

标题：flagship stress 3/6 已有 family-level diagnosis，但不能写 all-pass。

来源：`local_api_20260707_163354/stages/r01_12_flagship_ablation_api_local/stdout.json`

影响文件：docs、`v2/benchmark/flagship_ablation.py` future reporting

证据：stress pass family 为 3/6。通过：`csv_table_profile_v1`、`csv_correlation_replay_v1`、`long_doc_table_v1`。失败 family 的实际原因不同：`incident_diagnosis_v2` 有 L2 semantic transfer 10、StateRef prompt saving 3132 bytes、visible saving 2664 bytes，但 L3 quality 7/10，quality headline 不合格；`long_doc_metric_replay_v1` 有 L2 transfer 10、StateRef prompt saving 3699 bytes、visible saving 357 bytes，但 L3 quality 8/10、validated 7、exact 1、skipped 9，quality/replay headline 不合格；`cross_period_financial_v1` quality 10/10、validated 4、skipped 4，quality/replay headline 合格，但 L2 相对 T2 prompt delta 为 +3268、visible delta +6792，StateRef prompt saving 为 0，失败点是 prompt-saving gate。

影响：将 stage exit 0 或总 savings 37884 bytes 写成 flagship all-pass 会掩盖 family-specific failure。

修复策略：报告中保留 stress pass count 与 per-family `quality_headline_eligible`、`replay_headline_eligible`、`llm_prompt_saved_by_state_ref_bytes`；新增 per-family `stress_fail_reasons` 与 `family_claim_scope`，把 quality/replay failure 和 `no_extra_state_ref_prompt_saving_vs_t2` 分开。后续优化按 family 拆：incident/long_doc_metric 优先 quality/replay，cross_period 优先 semantic-selection-vs-StateRef gate。

验证：`non_text_state_stress_summary` 可直接复盘上述 fields；新增 unit test 覆盖 claimable family 和 diagnostic-only family。

状态：code updated；needs local+api rerun evidence

## ID: V2-AUDIT-027

严重级别：P1

标题：formal registry 25/5 external compare 需要 adapter/prompt/scorer 工作，不能只切换 loader。

来源：`v2/benchmark/task_registry.py`、`v2/benchmark/live_runner.py`、`v2/benchmark/models.py`

影响文件：`v2/benchmark/live_runner.py`、`v2/benchmark/external_text_baseline.py`、`v2/benchmark/scoring.py`、formal sample models

证据：formal non-compare 使用 registry 25 cases / 5 families；formal compare 当前固定到 financial 8 cases。`FixedAnswerSample` 含 `expected_route`、`expected_tool_name`、`expected_facts`，而 registry `MinimalBenchmarkSample` 不具备同等 route/tool/fact schema；非 financial families 也缺 external prompt/scorer 语义。

影响：若直接把 compare loader 指到 registry，会产生 schema/runtime mismatch，或者把 unsupported family 包装成 failed quality。

修复策略：设计 registry-to-compare adapter，明确每个 family 的 expected route/tool/facts、external prompt、scoring contract 和 unsupported reason；再新增 `formal_registry_25case_5family_compare` scope。

2026-07-08 code update：新增 `v2/benchmark/formal_registry_adapter.py`；formal compare 默认加载 registered 25/5 adapter；fixed-answer runner 支持 `metric_projection_key`，用于把 `trend_direction`、`monthly_avg_windspeed.month_1`、`baro_outlier_count` 等 registry facts 投影到 unified `metric_name` / `metric_value` scorer；external baseline 改为使用真实 route catalog，并为 non-financial formal samples 构造公共 evidence context。

验证：summary 输出 `formal_compare_scope_label=formal_registry_25case_5family_compare`、case count 25、family count 5、full registry coverage true，且 unsupported family count 为 0 或逐项解释。

状态：code updated；needs local+api rerun evidence

## ID: V2-AUDIT-028

严重级别：P2

标题：历史实验报告仍含强 claim 语言，必须明确降级为 historical diagnostics。

来源：`docs/reports/v2_experiment_summary_20260703.md` 文档审计

影响文件：`docs/reports/v2_experiment_summary_20260703.md`、presentation/report docs

证据：历史报告中仍出现 `Container (openEuler)`、`formal_superiority_claim_allowed=True`、`formal_efficiency_claim_allowed=True`、`bwrap sandbox`、多项 `强` 证据表述。它们记录 2026-07-04 历史 run，不能替代 latest `local_api_20260707_163354`，也不能证明 openEuler VM validation、current formal external superiority、production sandbox 或 current flagship all-pass。

影响：评审材料若直接摘取历史报告表格，会越过本审计的 claim stopline。

修复策略：在历史报告顶部和 claim summary 前加入更强 warning；presentation/report docs 优先引用 `docs/README.md`、`docs/improvement/README.md` 和本审计目录。

验证：历史报告显式写明 openEuler container 不等于 openEuler VM、bwrap sandbox 是 historical diagnostic、old efficiency fields 不作为 current claim。

状态：partial；warning 已增强，后续 presentation 仍需复核

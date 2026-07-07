# StateBus v2 综合真实性审计 - 执行摘要

日期：2026-07-06
分支：`feat/statebus-v2-container-runtime`
范围：claim-upgrade 文档、artifacts、源码、测试、Docker root 验证和后续修复。

更新：`local_api_20260706_191835` 是上一轮 API+local+memfd 全面测试基线；`v2-local-api-20260707_015709` 暴露了 live API 空/ malformed JSON 响应会打断 formal/continuous stage 的鲁棒性问题。修复后以 targeted artifacts 复验：`v2-targeted-json-retry-formal-20260707_191045` 支持 formal internal 25/25，`v2-targeted-json-retry-compare-20260707_192452` 支持 formal financial 8-case equal-quality prompt/token efficiency compare。`local_api_20260707_034412` 是 post-fix diagnostic rerun，不是 passing comprehensive evidence。`local_api_20260707_091807` 是历史 green comprehensive core evidence：12 个 stage 全部 exit 0，required failed stage 为 0，flagship 显式关闭。`local_api_20260707_115051` 暴露 `RUN_FLAGSHIP=1` 下的 API transport failure；`local_api_20260707_130958` 暴露 transport retry 后的 strict visible-candidate mismatch。二者已分别转化为 `runtime/llm.py` transport retry 与 `v2/runtime/role_path.py` selection retry。最新 full `RUN_FLAGSHIP=1` comprehensive evidence 是 `local_api_20260707_163354`：13 个 stage 全部 exit 0，required failed stage 为 0；flagship stage 跑完，但 stress pass 为 3/6，不能写成 all-pass。当前实现/实验对照以 `code_truth_vs_experiment_issue_matrix_zh.md` 为准。

## 直接结论

当前 v2 claim-upgrade 有一部分已经真实落地，另一部分仍受 compare gate、schema、覆盖面或外部证据限制。

本轮审计完全支持：

- formal internal benchmark 已加载 5 个注册任务家族共 25 个 case，并在 API+local+memfd run 中 25/25 通过。
- API 四角色 formal internal 路径真实发生：planner、retriever、executor、summarizer 各 25 次 call。
- `--state-pool-mode` 已贯穿 formal runner；local+api 结果证明 `memfd + local embedding` 使用 memfd，且记录了 25 次 publish/transfer。
- live API role JSON 响应边界已有 bounded retry；空响应和 malformed JSON 首次响应不会直接打断 formal path，目标复验已通过。
- live API provider transport boundary 已增加 bounded retry；connection/timeout transient error 有单测覆盖，并已由 `local_api_20260707_163354` full `RUN_FLAGSHIP=1` comprehensive rerun 复验。
- strict visible-candidate mismatch 不再静默 fallback；retriever/executor selection normalization 会用可见 candidate list bounded retry。`local_api_20260707_130958` 暴露该问题，`local_api_20260707_163354` 证明 flagship 不再卡在该路径。
- state-pool backend observability 通过 `last_published_storage_kind` 与 `storage_publish_counts` 在 handle release 后仍能保留真实 backend。
- `SemanticStateRef` 与 `ExecutionArtifactRef` 是分离的模型类型和 registry entry。
- text 与 protocol smoke 路径能在容器 root Python 路径下运行。

本轮审计部分支持：

- UDS + typed Protobuf 已作为 v2 control plane 实现；formal benchmark 主路径是 loopback harness，subprocess transport/memfd 主要由单测覆盖。
- Semantic state transfer 与 hydration accounting 是真实的，但当前应精确限定为 embedding semantic state + refs + hydration accounting，不能泛化为任意非文本推理能力。
- CodeAct 是 bounded、deterministic plan/execution path，并有 sandbox telemetry。当前 formal 证据不能证明 realtime LLM-generated code。
- formal compare 有 post-fix local+api evidence，但只覆盖 formal financial 8 cases / 1 family。最新 full comprehensive 中该 scope 下 strict equal-quality compare valid、公平门 8/8 通过，但 `formal_external_claim_kind=debug_only`，不支持本次 efficiency superiority；targeted compare 曾支持 8-case scope 下 prompt/token efficiency-superiority。
- `local_api_20260707_163354` 的 docs artifact copy 已按 wrapper 诊断逻辑补齐 diagnostics bundle，可从 docs 树内复盘 compare case structured fields、nested reports、case outputs、state metadata、hydration audit、ref registry 和 socket path audit。

不支持或仅为文档层：

- full 25-case formal external superiority：当前 formal compare 仍不是 full registry compare。
- 端到端速度优势：当前证据不支持。
- openEuler VM validation：本轮未执行。
- 通用 answer restoration：明确不支持；exact replay 已不再计入 answer restoration。
- 容器内 host conda activation contract：不支持。v2 container path 使用 `/usr/local/bin/activate_statebus_container.sh`，并已在 `local_api_20260707_163354` 验证成功。

## 最高风险发现

1. Docker prompt 路径和环境说明已过时。仓库实际挂载在 `/workspace/statebus/project`，不是 `/workspace`；container path 应使用 `/usr/local/bin/activate_statebus_container.sh`，不要把 host conda activation 当成 container contract。
2. 旧测试/报告契约仍把 exact replay 等同于 `answer_restoration_replay_count`。本轮已在代码和测试中修复。
3. full formal external superiority 仍未闭环。post-fix formal compare 已把 gate/schema/scope 拆清，但只覆盖 formal financial 8 cases / 1 family。
4. CodeAct 证据必须保持 bounded。已有历史 LLM generation diagnostic 不能升级为当前 formal benchmark 证明。
5. `tasks/formal/*/validator.py` 文件存在，但不是 benchmark runner 的主验证路径。实际 quality gate 是 `v2/runtime/smoke.py` 中的通用 `expected_facts`。
6. memfd unavailable fallback 主要仍是 unit/monkeypatch 证据，不是真实 no-memfd 主机验证。
7. external baseline 的 metric schema 已迁移到 `metric_value` / `metric_name`，但 legacy `revenue_value` 只能作为兼容字段读取。
8. 最新 full comprehensive 已 clean，flagship stage 也 exit 0；但 stress pass 只有 3/6，不能声称 flagship ablation 全量通过。
9. `local_api_20260707_115051` 与 `local_api_20260707_130958` 分别是 transport retry 和 selection retry 的失败定位证据；最新 passing 证据以 `local_api_20260707_163354` 为准。

## 本轮已应用修复

- `v2/runtime/driver.py`：`answer_restoration_replay_count` 现在始终为 `0.0`，不再由 exact replay 置为 `1.0`。
- `v2/benchmark/continuous_runner.py`：移除把 answer restoration 从 exact replay 回填出来的逻辑。
- `tests/v2/test_continuous_runner.py`：更新 family、case、collection 断言，强制校验修正后的 metric。
- `docs/reports/v2_experiment_summary_20260703.md`：为 CodeAct diagnostic section 添加历史状态警告。
- 添加本审计目录并复制 fresh benchmark JSON artifacts。
- `v2/benchmark/*` 与 formal financial samples：拆分 strict equal-quality / quality-superiority / efficiency claim gate，formal compare scope 显式标注为 8-case financial compare，metric schema 迁移到 `metric_name` / `metric_value`。
- `v2/runtime/role_path.py`：四角色 API JSON extraction boundary 增加 bounded retry，且不做 oracle/candidate fallback。
- `runtime/llm.py`：OpenAI-compatible API transport 增加 bounded transient retry，覆盖 connection、timeout、408/409/429/5xx。
- `v2/runtime/role_path.py`：retriever/executor strict visible-candidate selection 增加 bounded retry，失败时继续拒绝不可见或冲突 candidate，不做 best-candidate fallback。
- `scripts/run_v2_local_api_comprehensive_stats.sh`：focused pytest 纳入 control/UDS/subprocess tests，summary 输出 compare structured diagnostics，host artifact copy 增加 nested diagnostics bundle。

## 验证摘要

早期验证使用 `statebus-dev-qcrs` 容器 root 的 `/usr/bin/python3`，因为 host conda activation 不适用于 container。最新 full `RUN_FLAGSHIP=1` comprehensive wrapper 使用 `/usr/local/bin/activate_statebus_container.sh` 并记录 activation success。

- 必要 v2 模块 `py_compile`：通过。
- `bash -n scripts/run_v2_full_container_audit_suite.sh`：通过。
- 修复后的 focused pytest 命令：49 passed in 371.18s。
- `tests/v2/test_continuous_runner.py`：metric 修复后 11 passed in 342.32s。
- `python3 -m runtime.smoke`：text 和 protocol smoke 均通过。
- formal benchmark artifacts 已复制到 `artifacts/`：
  - `formal_auto.stdout.json`：25/25，5 families，使用 `shared_memory`。
  - `formal_shared_memory.stdout.json`：25/25，5 families，使用 `shared_memory`。
  - `formal_memfd_local.stdout.json`：25/25，5 families，使用 `memfd`，25 次 memfd transfer，247076 bytes。
- local+api comprehensive artifact 已复制到 `artifacts/local_api_20260706_191835/`：
  - `r01_05_formal_api_local_memfd`：25/25，5 families，API role calls 各 25，memfd transfer/publish 各 25。
  - `r01_06_formal_compare_api_local_memfd`：pre-fix formal financial 8-case compare，StateBus quality 8/8，external quality 5/8，暴露 gate/schema/scope 问题；post-fix targeted compare 已关闭 gate/schema 问题，但 scope 仍是 8/1。
  - `r01_10_continuous_replay_api_local`：20/20 target replay observed，17 validated，3 exact，answer restoration 0。
- interrupted comprehensive artifact：`/home/qcrs/statebus/runs/v2-local-api-20260707_015709/`
  - required `r01_05_formal_api_local_memfd` failed before the retry patch on empty executor JSON.
  - required `r01_06_formal_compare_api_local_memfd` passed and emitted new gate/scope fields, but the run has no final `summary.json` because the optional flagship tail was stopped after the run was already invalid.
  - optional `r01_09_continuous_api_local` timed out at 2400s near the end; optional `r01_10_continuous_replay_api_local` failed on malformed summarizer JSON.
- post-fix targeted artifacts:
  - `/home/qcrs/statebus/runs/v2-targeted-json-retry-formal-20260707_191045/`：formal internal API+local+memfd 25/25，5 families，memfd transfer 25。
  - `/home/qcrs/statebus/runs/v2-targeted-json-retry-compare-20260707_192452/`：formal financial 8-case compare，strict equal-quality valid，`formal_efficiency_superiority_claim_allowed=true`，full registry coverage false。
- post-fix comprehensive diagnostic artifact:
  - `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_034412/summary.json`：focused pytest 109 passed；container activation `/usr/local/bin/activate_statebus_container.sh` success；required `r01_05_formal_api_local_memfd` timeout 124 at 1800s；`r01_06_formal_compare_api_local_memfd` exit 0 but `formal_external_claim_kind=debug_only` because `benchmark-sample-6` failed `planner_visible_choice_only`; optional continuous, continuous-replay and flagship stages timed out.
  - `diagnostics/manifest.json`：2310 nested files copied, including benchmark reports, external/statebus outputs, state metadata, hydration audits, ref registries and stage socket logs.
- post-fix comprehensive core artifact:
  - `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/summary.json`：12 stages 全部 exit 0；required failed stage count 0；focused pytest 111 passed；runtime smoke、preflight、formal internal、formal compare、replay negative 均通过。
  - `r01_05_formal_api_local_memfd`：25/25，5 families，API role calls 各 25，memfd transfer/publish 各 25，247076 bytes。
  - `r01_06_formal_compare_api_local_memfd`：formal financial 8-case compare，fairness gate 8/8，strict equal-quality valid，full registry coverage false，`formal_external_claim_kind=debug_only`，不支持本次 efficiency superiority。
  - `r01_10_continuous_replay_api_local`：20/20 target replay observed，17 validated，3 exact，answer restoration 0。
  - `diagnostics/manifest.json`：1384 nested files copied，证明 host-copy 自动填充 docs artifact。
- flagship-enabled partial artifact:
  - `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/summary.json`：13 stages，failed stage count 3，failed required stage count 0。
  - required `r01_05_formal_api_local_memfd` 和 `r01_06_formal_compare_api_local_memfd` 通过；formal internal 25/25，formal compare 8-case strict equal-quality valid。
  - optional `r01_09_continuous_api_local` 和 `r01_10_continuous_replay_api_local` 因 API DNS/connect error 失败；optional `r01_12_flagship_ablation_api_local` 因 API read timeout 失败。
  - `diagnostics/manifest.json`：663 nested files copied；该 run 只作为 required-core-with-flagship-enabled partial evidence，不作为 optional passing evidence。
- post-transport-retry flagship artifact before selection retry:
  - `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_130958/summary.json`：13 stages，failed stage count 1，failed required stage count 0。
  - formal internal 25/25、formal compare 8-case strict equal-quality、continuous 30 rounds、continuous replay 20/20 observed、replay negative 7/7 均通过。
  - optional flagship 因 `strict_visible_candidate_mismatch:csv_profiler::csv_profiler` 失败；该 run 是 selection retry 的触发证据，不是 latest passing evidence。
- latest full `RUN_FLAGSHIP=1` comprehensive artifact:
  - `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/summary.json`：13 stages 全部 exit 0；failed stage count 0；failed required stage count 0；focused pytest 115 passed。
  - `r01_05_formal_api_local_memfd`：25/25，5 families，API role calls 各 25，memfd transfer/publish 各 25，247076 bytes。
  - `r01_06_formal_compare_api_local_memfd`：formal financial 8-case compare，fairness gate 8/8，strict equal-quality valid，full registry coverage false，`formal_external_claim_kind=debug_only`，不支持本次 efficiency superiority。
  - `r01_09_continuous_api_local`：3 families / 30 rounds，`L3_reuse_gain=9`。
  - `r01_10_continuous_replay_api_local`：20/20 target replay observed，17 validated，3 exact，answer restoration 0。
  - `r01_12_flagship_ablation_api_local`：stage exit 0；6 stress families 中 3 个通过；`total_llm_prompt_saved_by_state_ref_bytes=37884`，`total_prompt_visible_saved_by_state_ref_bytes=21621`。
  - `diagnostics/manifest.json`：copied_file_count=2558，按 wrapper 诊断拷贝逻辑补齐。
- transport retry patch:
  - `python -m py_compile runtime/llm.py tests/v2/test_fixed_answer_and_external_baseline.py`：通过。
  - `tests/v2/test_fixed_answer_and_external_baseline.py::test_openai_compatible_client_retries_transient_transport_error` 和 `::test_openai_compatible_client_stops_after_transport_retry_budget`：2 passed。
- selection retry patch:
  - `python -m py_compile v2/runtime/role_path.py tests/v2/test_fixed_answer_and_external_baseline.py`：通过。
  - strict retriever/executor visible-candidate mismatch retry tests 与 candidate-key fairness tests：4 passed。

## 当前 claim-upgrade 状态

完全支持：

- internal formal benchmark 扩展到 25 cases / 5 families，并在 API+local+memfd 下 25/25 通过。
- memfd 的 state-pool mode reporting 和 positive path publish/transfer。
- typed Protobuf envelope path 与 protocol smoke execution。
- semantic state 与 execution artifact 的 ref 分离。
- formal financial 8-case strict equal-quality compare：只在 8-case / 1-family financial scope 内成立，不覆盖 full registry；targeted run 曾支持 prompt/token efficiency-superiority，但最新 full comprehensive 不支持本次 efficiency superiority。

部分支持：

- shared memory backend reporting，主要来自 deterministic artifacts。
- semantic state 与 hydration accounting，限定为 embedding semantic state + refs + prompt-slice hydration。
- bounded CodeAct / controlled execution。
- memory replay 与 reuse，但只限 telemetry 明确显示 validated replay、exact replay、skipped steps 或 reuse gain 的场景。
- formal financial 8-case external compare 的 gate/schema/scope 已可读；它仍不能继承 formal internal 25/5 scope。
- comprehensive run automation and diagnostics 已有 latest full `RUN_FLAGSHIP=1` green run 证据；但 flagship stress 只有 3/6，仍需 family-level 拆解。

仅文档层：

- 历史 CodeAct LLM-generation diagnostics。
- 部分旧 improvement reports 在新 safe-claim docs 之后已被替代。

不支持：

- full formal registry external superiority。
- 端到端速度优势。
- openEuler VM validation。
- 通用 answer restoration。
- 当前 formal benchmark 下的 realtime open-ended LLM code generation。

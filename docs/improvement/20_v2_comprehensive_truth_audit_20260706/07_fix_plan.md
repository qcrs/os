# 修复计划

本计划以 `code_truth_vs_experiment_issue_matrix_zh.md` 为主入口，目标不是继续调整安全表述，而是让代码字段、实验覆盖和文档 claim 对齐。

## 已完成基线

1. Answer restoration metric 降级

已把 exact replay 与 answer restoration 分离。当前 continuous replay 结果中：

- `validated_replay_count=17`
- `exact_replay_count=3`
- `answer_restoration_replay_count=0`

这意味着 replay/reuse 可以 claim，但 generic answer restoration 不能 claim。

2. CodeAct 历史口径降级

`docs/reports/v2_experiment_summary_20260703.md` 已把历史 CodeAct LLM-generation 数字标注为 diagnostics，当前 formal benchmark 不再把它写成 realtime open-ended LLM code generation proof。

3. local+api 全面测试完成

`local_api_20260706_191835` 证明：

- required stages 全部 exit 0。
- API+local+memfd formal internal 25/25 通过。
- formal compare stage 跑通但暴露 gate/schema/scope 问题。
- continuous replay target 20/20 observed。

4. compare gate / scope / metric schema 修复后 targeted 复验

- `v2-targeted-json-retry-formal-20260707_191045`：formal internal API+local+memfd 25/25，5 families。
- `v2-targeted-json-retry-compare-20260707_192452`：formal financial 8-case compare，strict equal-quality valid，`formal_external_claim_kind=efficiency_superiority_equal_quality`，full registry coverage false。

5. live role JSON retry 修复

`v2-local-api-20260707_015709` 暴露 executor 空字符串 response 会打断 formal stage、summarizer malformed JSON 会打断 continuous replay stage。已在 role JSON extraction boundary 增加 bounded retry，并用 targeted formal/compare 复验。

6. comprehensive diagnostic rerun 与 artifact 自足性

`local_api_20260707_034412` 证明 wrapper 已记录 container activation success、focused pytest 109 passed、formal compare structured diagnostics 和 replay-negative pass，并把 nested runtime evidence 复制到 docs artifact。该 run 仍不是 green comprehensive evidence：required formal internal stage timeout，formal compare 因 `benchmark-sample-6` external fairness gate variance 降级为 debug-only。

7. passing comprehensive core rerun

`local_api_20260707_091807` 证明 post-fix wrapper 可在 flagship 关闭的 core policy 下跑到 clean：

- 12 stages 全部 exit 0，required failed stage count 0。
- focused pytest 111 passed。
- formal internal API+local+memfd 25/25，5 families，memfd transfer 25。
- formal financial 8-case compare strict equal-quality valid，fairness pass 8/8，但 `formal_external_claim_kind=debug_only`，本次不支持 efficiency superiority。
- continuous replay target 20/20 observed，17 validated，3 exact，answer restoration 0。
- diagnostics manifest copied_file_count=1384，由 wrapper 自动写入 docs artifact copy。

8. flagship-enabled rerun attempt 与 API transport retry

`local_api_20260707_115051` 是 `STATEBUS_LOCAL_API_RUN_FLAGSHIP=1` 的 full rerun attempt。它证明 required core stages 仍 clean：

- stage count 13，failed stage count 3，failed required stage count 0。
- formal internal API+local+memfd 25/25，5 families，memfd transfer 25。
- formal financial 8-case compare strict equal-quality valid，fairness failed case count 0，`formal_external_claim_kind=debug_only`。
- replay negative 7/7 pass。

但 optional stages 不是 passing evidence：

- continuous stage 因 API DNS/connect error 失败。
- continuous replay stage 因 API DNS/connect error 失败。
- flagship stage 因 API read timeout 失败。

后续已在 `runtime/llm.py` 增加 bounded OpenAI-compatible transport retry，覆盖 connection/timeout/408/409/429/5xx transient errors；该补丁已有单测，并已由 `local_api_20260707_163354` full `RUN_FLAGSHIP=1` comprehensive 复验。

9. selection retry 与 full `RUN_FLAGSHIP=1` comprehensive rerun

`local_api_20260707_130958` 证明 transport retry 后 required、continuous、continuous replay 和 replay negative stages 均能完成，但 flagship 因 `strict_visible_candidate_mismatch:csv_profiler::csv_profiler` 失败。后续在 `v2/runtime/role_path.py` 为 retriever/executor strict visible-candidate normalization 增加 bounded retry，不做 best-candidate fallback。

`local_api_20260707_163354` 是最新 full `RUN_FLAGSHIP=1` comprehensive evidence：

- 13 stages 全部 exit 0，failed required stage count 0。
- focused pytest 115 passed。
- formal internal API+local+memfd 25/25，5 families，memfd transfer 25。
- formal financial 8-case compare strict equal-quality valid，fairness pass 8/8，但 `formal_external_claim_kind=debug_only`，本次不支持 efficiency superiority。
- continuous replay target 20/20 observed，17 validated，3 exact，answer restoration 0。
- flagship stage exit 0，但 stress pass 为 3/6，不是 all-pass。
- diagnostics manifest copied_file_count=2558，按 wrapper 诊断拷贝逻辑补齐。

## P0：先修 compare 语义（8-case scope 已完成）

### P0-1：拆分 strict compare 与 quality superiority

问题：

pre-fix `r01_06_formal_compare_api_local_memfd` 同时输出：

- `fixed_answer_external_comparison_valid=false`
- `formal_headline_eligible=false`
- `formal_superiority_claim_allowed=true`

这不是单纯文案问题，而是 `v2/benchmark/comparator_runner.py` 中 strict equal-quality headline compare 和 quality-superiority path 共用了一组字段。

改动：

- 新增 `strict_equal_quality_comparison_valid`。
- 新增 `quality_superiority_comparison_valid`。
- 新增 `formal_quality_superiority_claim_allowed`。
- 新增 `formal_efficiency_superiority_claim_allowed`。
- 新增 `formal_external_claim_kind`，取值建议：
  - `none`
  - `quality_superiority`
  - `efficiency_superiority_equal_quality`
  - `debug_only`
- 保留旧字段时，明确 `comparison_valid` 是 legacy strict valid。

测试：

```bash
source deploy/activate_statebus_host.sh
/usr/bin/python3 -m pytest -q tests/v2/test_compare_diagnostics.py
```

验收：

- legacy external 5/8、StateBus 8/8、fairness pass fixture 下，strict 为 false，quality superiority 为 true，efficiency superiority 为 false。
- post-fix targeted compare 下，strict equal-quality valid，efficiency-superiority-equal-quality claim allowed for the 8-case scope；latest full comprehensive 下 strict equal-quality valid，但 efficiency-superiority claim 不成立。
- markdown report 同时列出 strict path 和 quality-superiority path。
- 当前验证：`tests/v2/test_compare_diagnostics.py` 通过；`v2-targeted-json-retry-compare-20260707_192452` 显示 strict equal-quality valid。

### P0-2：补 formal compare scope metadata

问题：

formal internal 是 25 cases / 5 families；formal compare 当前是 formal financial family 8 cases。

改动：

- `live_runner.py` 或 comparator payload 输出：
  - `formal_compare_scope_label`
  - `formal_compare_case_count`
  - `formal_compare_family_count`
  - `formal_registry_case_count`
  - `formal_compare_full_registry_coverage`

验收字段：

```json
{
  "formal_compare_scope_label": "formal_financial_family_8case_compare",
  "formal_compare_case_count": 8,
  "formal_registry_case_count": 25,
  "formal_compare_full_registry_coverage": false
}
```

复验：

```bash
source deploy/activate_statebus_host.sh
STATEBUS_LOCAL_API_RUN_FLAGSHIP=0 bash scripts/run_v2_local_api_comprehensive_stats.sh
```

当前验证：`v2-targeted-json-retry-compare-20260707_192452` 与 `local_api_20260707_163354` 均输出 `formal_financial_family_8case_compare`、case count 8、registry count 25、full coverage false。

## P1：修 external metric schema（已完成）

问题：

`revenue_value` 被用来表示任意 metric value。对 revenue case 没问题，但对 `operating_income`、`gross_margin` 会误导 external pure-text baseline。

改动：

- sample schema 引入：

```json
{
  "expected_facts": {
    "metric_name": "gross_margin",
    "metric_value": "39",
    "selected_doc_hashes": ["sha256:..."]
  }
}
```

- `score_fixed_answer_case()` 优先读 `metric_value`，兼容 `revenue_value`。
- external retriever prompt 改为要求 `metric_name`、`metric_value`。
- executor artifact 和 report 输出 metric fields。
- `revenue_exact` 临时保留为兼容指标，但新增 `metric_value_exact`。

不要做：

- 不要把 `observed_revenue_value` fallback 到 corpus preload。那会让 external 即使没有真实抽取事实也被判正确。

测试：

```bash
source deploy/activate_statebus_host.sh
/usr/bin/python3 -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py tests/v2/test_compare_diagnostics.py
```

验收：

- sample 6/7/8 如果 retriever 输出 requested metric value，则通过。
- 如果 retriever 仍输出 revenue，则失败。
- fairness gate 仍保持 LLM-only decision，不引入 oracle fallback。
- 当前验证：`tests/v2/test_fixed_answer_and_external_baseline.py` 45 passed；`test_fixed_answer_metric_value_schema_distinguishes_requested_metric_from_revenue` 通过；targeted formal compare 8/8 strict valid；`local_api_20260707_163354` full comprehensive formal compare 8/8 strict valid。

## P1：补 per-case diagnostics 和 artifact 归档（已完成一次验证）

原问题：

docs artifact copy 只有 stage stdout 和 summary，缺 nested comparator reports、per-case external/statebus outputs、state metadata、hydration audit、ref registry。

改动：

- 修改 `scripts/run_v2_local_api_comprehensive_stats.sh` 的 host copy 阶段。
- 增加 diagnostics bundle：
  - `benchmark_reports/*compare*.json`
  - failed external outputs
  - failed StateBus outputs
  - representative `state/metadata/*.json`
  - representative `logs/hydration_audit.json`
  - representative `registry/ref_registry.json`
  - socket path audit
- summary 自动列出 compare cases 的 expected vs observed fields，不只列 failed cases。

验收：

- 只看 docs artifact copy，就能复盘 `benchmark-sample-6/7/8` 的 metric fields，以及 `local_api_20260707_034412` 中 `benchmark-sample-6` 的 fairness failure。
- 只看 docs artifact copy，就能看到 memfd state metadata、hydration accounting、ref registry 和 socket path audit。
- 当前验证：`local_api_20260707_034412/diagnostics/manifest.json` copied_file_count=2310；`local_api_20260707_091807/diagnostics/manifest.json` copied_file_count=1384，并验证 exit 0 后 wrapper 自动 host-copy；`local_api_20260707_163354/diagnostics/manifest.json` copied_file_count=2558，按 wrapper 诊断拷贝逻辑补齐。

## P1：修 Docker root activation 语义

原问题：

当前脚本确实用 `docker exec -u 0`，但 container 内 `deploy/activate_statebus_host.sh` 失败后继续 `/usr/bin/python3`。这使“先激活环境”的复验要求和实际路径不一致。

改动方向：

1. 对 host-mainline，继续使用 host activation。

```bash
source deploy/activate_statebus_host.sh
```

2. 对 v2 container runtime，正式使用 container activation：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && source /usr/local/bin/activate_statebus_container.sh && /usr/bin/python3 -c "import v2.runtime.driver"'
```

验收：

- local+api summary 写清 actual activation script、Python path、package versions、CUDA、embedding model、LLM config。
- activation 失败不能静默变成“已激活”。

当前验证：

- `local_api_20260707_163354` environment block 记录 `/usr/local/bin/activate_statebus_container.sh` success。
- Docker root control/UDS/subprocess focused command 9 passed。

## P1：live API role JSON response retry（已完成）

问题：

live API 偶发返回空字符串或 malformed JSON 时，原实现直接让 whole stage fail。

改动：

- `RolePathRunner` 在 planner/retriever/executor/summarizer JSON extraction boundary 做 bounded retry。
- retry 只重新请求 JSON，不替用户选择 candidate，也不绕过 strict validation。
- token usage 与 prompt bytes 聚合进 role decision metrics。

验证：

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py
```

结果：45 passed。targeted formal 25/25，targeted compare exit 0，`local_api_20260707_163354` full comprehensive exit 0。

## P1：live API transport transient retry（已完成并 full rerun 复验）

问题：

`local_api_20260707_115051` 的 optional stages 在长时间 API run 中遭遇 provider transport 抖动：

- `r01_09_continuous_api_local`：`openai.APIConnectionError` / DNS connect error。
- `r01_10_continuous_replay_api_local`：同类 DNS connect error。
- `r01_12_flagship_ablation_api_local`：`openai.APITimeoutError` / read timeout。

改动：

- `runtime/llm.py` 的 OpenAI-compatible client 增加 provider-level `request_max_attempts`、`retry_initial_delay_s`、`retry_max_delay_s`。
- retry 只覆盖 connection error、timeout、408/409/429/5xx transient status。
- retry 不捕获最终 scorer/quality/fairness/candidate validation failure。

验证：

```bash
source deploy/activate_statebus_host.sh
python -m py_compile runtime/llm.py tests/v2/test_fixed_answer_and_external_baseline.py
python -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py::test_openai_compatible_client_retries_transient_transport_error tests/v2/test_fixed_answer_and_external_baseline.py::test_openai_compatible_client_stops_after_transport_retry_budget
```

结果：2 passed。

full rerun 复验：

- `local_api_20260707_163354`：13 stages 全部 exit 0，continuous/replay/flagship stages 均完成。

## P1：strict visible-candidate selection retry（已完成并 full rerun 复验）

问题：

`local_api_20260707_130958` 的 flagship stage 因 `strict_visible_candidate_mismatch:csv_profiler::csv_profiler` 失败。该失败来自 API selection response 与可见 candidate normalization 不匹配，不应通过 oracle fallback 或 best-candidate fallback 掩盖。

改动：

- `v2/runtime/role_path.py` 在 retriever/executor selection normalization 遇到 `RoleSelectionError` 时用可见 candidate list bounded retry。
- retry 后仍拒绝不可见 candidate、route/tool 冲突和 strict parser failure。

验证：

```bash
source deploy/activate_statebus_host.sh
python -m py_compile v2/runtime/role_path.py tests/v2/test_fixed_answer_and_external_baseline.py
python -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py -k 'role_path_retries_strict or candidate_key_route_slot_with_conflicting_tool'
```

结果：4 passed。`local_api_20260707_163354` full `RUN_FLAGSHIP=1` comprehensive 13 stages 全部 exit 0。

## P2：控制面和 statepool 硬化

### 控制面 pytest 覆盖

改动：

- focused local+api pytest 加入：
  - `tests/v2/test_control_plane.py`
  - `tests/v2/test_uds_loopback.py`
  - `tests/v2/test_subprocess_executor.py`

验收：

```bash
source deploy/activate_statebus_host.sh
/usr/bin/python3 -m pytest -q tests/v2/test_control_plane.py tests/v2/test_uds_loopback.py tests/v2/test_subprocess_executor.py
```

注意：

- 当前 formal benchmark 主路径仍是 loopback harness。
- 如果要 claim subprocess execution，需要新增 subprocess benchmark stage，而不是只靠单测。
- 当前状态：`v2-local-api-20260707_015709` focused pytest 已扩展到 107 tests 并通过；`local_api_20260707_034412` focused pytest 109 passed；`local_api_20260707_091807` focused pytest 111 passed；`local_api_20260707_163354` focused pytest 115 passed；Docker root control subset 9 passed。

### memfd unavailable fallback

改动：

- 新增 capability-masked no-memfd validation stage。
- 记录 fallback reason 和 actual backend。

验收：

- 在 memfd unavailable 条件下，stage exit 0，并明确 fallback 到 shared_memory 或 mmap。

## P2：flagship 失败 family 拆解

问题：

`r01_12_flagship_ablation_api_local` 在 latest full `local_api_20260707_163354` 中 stage exit 0，但 6 个 stress families 中只有 3 个通过。

已拆出的 family-level 结论：

- `incident_diagnosis_v2`：L2 semantic transfer 10，StateRef prompt saving 3132 bytes，visible saving 2664 bytes；但 L3 quality 7/10，quality headline 不合格。修复方向是提升 L3 quality/replay admissibility，而不是 claim all-pass。
- `long_doc_metric_replay_v1`：L2 semantic transfer 10，StateRef prompt saving 3699 bytes，visible saving 357 bytes；但 L3 quality 8/10，validated 7，exact 1，skipped 9，quality/replay headline 不合格。修复方向是补 long-doc metric replay 的 quality floor 与 replay target coverage。
- `cross_period_financial_v1`：quality 10/10，validated 4，skipped 4，quality/replay headline 合格；失败来自 L2 相对 T2 `llm_prompt_delta_l2_vs_t2=+3268`、`prompt_visible_delta_l2_vs_t2=+6792`，StateRef prompt saving 为 0。修复方向是改 stress gate 或改 semantic-state packaging；当前应写成 semantic selection dominates this family。

后续输出要求：

- 每个 family 的 quality floor 是否失败。
- replay target 是否失败。
- StateRef prompt saving 是否失败。
- 任务定义是否不适合当前 stress gate。

## P1/P2 后：registry-backed formal external compare

在 compare gate 和 metric schema 稳定后，再做 full registry compare。

新增入口建议：

```text
--suite formal-compare-registry
```

或：

```text
--suite compare --benchmark-tier formal --formal-compare-source registry
```

验收：

- scope：`formal_registry_25case_5family_compare`
- case count：25
- family count：5
- unsupported family count：0，或明确列出 unsupported reason

## 最终复验命令

普通 local+api 全面复验：

```bash
source deploy/activate_statebus_host.sh
STATEBUS_LOCAL_API_RUN_FLAGSHIP=0 bash scripts/run_v2_local_api_comprehensive_stats.sh
```

正式 timing 证据需要 serialized rerun：

```bash
source deploy/activate_statebus_host.sh
STATEBUS_LOCAL_API_REPEAT=3 STATEBUS_LOCAL_API_RUN_FLAGSHIP=1 bash scripts/run_v2_local_api_comprehensive_stats.sh
```

注意：

- API latency claim 只能来自 serialized rerun。
- 不能把 concurrent API launch 的结果当 formal timing evidence。
- 每次 rerun 都要归档 summary、nested diagnostics 和 failed case table。

## 当前 claim stopline

仍禁止写：

- full formal external superiority。
- full 25-case external compare。
- end-to-end speed advantage。
- generic answer restoration。
- hidden-state / KV transfer。
- openEuler VM validation。
- nsjail / production sandbox validation。

可以写但必须带 scope：

- formal internal API+local+memfd：25/25，5 families。
- formal financial 8-case compare：strict equal-quality claim 只限 8 cases / 1 family，不能继承 formal internal 25/5 scope；efficiency-superiority 需要单独引用 targeted/serialized evidence，latest full comprehensive 不支持本次 efficiency superiority。
- continuous replay：20/20 target replay observed，17 validated，3 exact，answer restoration 0。
- memfd positive path：25 publish/transfer。

---

## 赛题交付专项（2026-07-07 新增，来自 10_contest_oriented_followup_plan_20260707.md）

### C0：openEuler 24.03-LTS-SP3 验证（P0 交付阻塞）

赛题要求最终代码在 openEuler 24.03-LTS-SP3 上可运行。当前无此环境验证证据。

需要做：
1. 确认 openEuler VM 是否可用；若不可用，先在 openEuler 容器中近似验证。
2. 安装依赖（pip install，或从源码编译 faiss-cpu）。
3. 跑通：`python3 -m runtime.smoke` 和 `python3 -m pytest -q tests/v2/test_minimal_benchmark.py`。

验收命令（openEuler 24.03 环境中）：

```bash
bash scripts/setup_openeuler_env.sh
python3 -m runtime.smoke
python3 -m pytest -q tests/v2/test_minimal_benchmark.py tests/v2/test_state_materialization.py
```

### C1：V2 formal text vs protocol 双模对比（P1 通信效率证据）

增加 `r01_05b_formal_text_mode` stage，和 `r01_05`（protocol）形成 StateBus 自身双模对比。

```bash
# 目标字段
{
  "text_L3_total_tokens": ...,
  "protocol_L3_total_tokens": ...,
  "protocol_vs_text_token_delta": ...,  # 期望负值（protocol < text）
  "protocol_vs_text_control_byte_delta": ...
}
```

### C2：Serialized timing rerun（P2 efficiency claim）

当前 `api_task_ms_delta=86580ms` 来自并发运行，不可用。需 serialized rerun：

```bash
STATEBUS_LOCAL_API_REPEAT=3 STATEBUS_LOCAL_API_RUN_FLAGSHIP=0 \
  bash scripts/run_v2_local_api_comprehensive_stats.sh
```

注意：latency delta 仍受架构差异影响（StateBus 4-role vs external 1-role），主效率指标应是 token/byte delta 而非 latency delta。

### C3：formal compare token split（P1 claim/schema）

当前 latest full compare 只支持 prompt/input/control-byte savings：

- StateBus prompt bytes 30661 vs external 43213，delta -12552。
- StateBus prompt tokens 9645 vs external 12678。
- StateBus completion tokens 19695 vs external 10199。
- StateBus total tokens 29340 vs external 22877，delta +6463。
- `formal_external_claim_kind=debug_only`。

需要做：
1. 在 comparator canonical payload 或 summary extraction 中显式输出 `prompt_tokens_delta`、`completion_tokens_delta`、`total_tokens_delta`、`prompt_bytes_delta`。
2. 文档 generator 只在 prompt/input 指标上写 savings；除非 total-token/timing gate 同时通过，不写 efficiency superiority。

验收：

```json
{
  "api_prompt_tokens_delta": -3033,
  "api_completion_tokens_delta": 9496,
  "api_llm_total_tokens_delta": 6463,
  "api_prompt_bytes_delta": -12552,
  "formal_external_claim_kind": "debug_only"
}
```

### C4：StateRef claim boundary（P1 docs/schema）

当前可 claim：

- `EMBEDDING_STATE` semantic state materialized through memfd/shared_memory/mmap policy。
- `SemanticStateRef`、prompt-slice refs、hydration audit 和 role prompt slices 都有 diagnostics。
- `ExecutionArtifactRef` 与 `SemanticStateRef` 分离。

当前不能 claim：

- raw evidence never enters prompt。
- StateRef replaces evidence text/table slices。
- hidden-state / KV cache transfer。

后续如需升级，新增 evidence pack/table slice 的 non-text materialization stage，并用 hydration audit 证明哪些 evidence bytes 不再 prompt-visible。

### C5：historical report warning（P2 docs）

`docs/reports/v2_experiment_summary_20260703.md` 是 historical diagnostics。它包含旧 `formal_superiority_claim_allowed=True`、`formal_efficiency_claim_allowed=True`、`Container (openEuler)` 和 `bwrap sandbox` 表述。已经补强 warning；后续 presentation/report 生成必须优先读取本审计目录，不能直接摘历史表格。

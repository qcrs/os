# 测试与 Benchmark 证据

所有命令均优先在 `statebus-dev-qcrs` 中以 Docker root 执行。

重要环境限制：prompt 要求的 `source deploy/activate_statebus_host.sh` 在容器中失败，因为 conda 缺失。因此实际验证使用容器 root 环境的 `/usr/bin/python3`，并在本文中明确标注。

更新说明：本文件保留 deterministic formal artifacts 作为历史/后端基线；`artifacts/local_api_20260706_191835/summary.json` 是上一轮 API+local+memfd 全面测试基线。2026-07-07 的 `v2-local-api-20260707_015709` 暴露了 live API 空/ malformed JSON 响应会打断 role path；修复后 targeted formal 与 formal compare 已复验通过。`artifacts/local_api_20260707_034412/` 是 post-fix comprehensive diagnostic rerun，不是 passing comprehensive evidence。`artifacts/local_api_20260707_091807/` 是历史 passing comprehensive core artifact，flagship 显式关闭。`artifacts/local_api_20260707_115051/` 暴露 `RUN_FLAGSHIP=1` 下 API transport error / timeout；`artifacts/local_api_20260707_130958/` 暴露 transport retry 后 strict visible-candidate mismatch。最新 full `RUN_FLAGSHIP=1` passing comprehensive artifact 是 `artifacts/local_api_20260707_163354/`：13 stages 全部 exit 0，required failed stage count 0，flagship stage 跑完但 stress pass 为 3/6。代码事实与实验证据的合并判断见 `code_truth_vs_experiment_issue_matrix_zh.md`。

## 环境检查

容器路径：

```text
/workspace/statebus/project
```

容器 Python：

```text
/usr/bin/python3
Python 3.11.6
pytest ok
```

Activation failure：

```text
[statebus] conda executable not found; set CONDA_EXE or add conda to PATH
/etc/profile.d/conda.sh missing
conda: command not found
CONDA_PREFIX: unbound variable
```

`jq` failure：

```text
bash: line 1: jq: command not found
```

因此使用 Python 抽取相同字段。

后续 comprehensive wrapper 已改用 container activation path；`local_api_20260707_163354` 记录：

```text
activation_script=/usr/local/bin/activate_statebus_container.sh
activation_status=success
python_executable=/usr/bin/python3
torch=2.5.1+cu121
cuda_available=true
```

## 静态验证

命令：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m py_compile ...'
```

结果：通过。

命令：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && bash -n scripts/run_v2_full_container_audit_suite.sh'
```

结果：通过。

## 测试验证

第一次 focused test attempt：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_continuous_runner.py tests/v2/test_state_materialization.py tests/v2/test_minimal_benchmark.py tests/v2/test_preflight_and_live_runner.py'
```

结果：失败一次，因为 `test_continuous_runner_executes_replay_collection` 仍断言 `answer_restoration_replay_count == exact_replay_count`。

已应用修复：更新 replay metric implementation 和旧断言。

修复后 impacted suite：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_continuous_runner.py'
```

结果：

```text
11 passed in 342.32s (0:05:42)
```

修复后 focused command：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_state_materialization.py tests/v2/test_minimal_benchmark.py tests/v2/test_preflight_and_live_runner.py tests/v2/test_continuous_runner.py'
```

结果：

```text
49 passed in 371.18s (0:06:11)
```

Smoke：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m runtime.smoke'
```

结果：

```text
statebus smoke ok: mode=text memory_hits=0.0 messages=292.0 control_bytes=243456.0 task_ms=5895.53
statebus smoke ok: mode=protocol memory_hits=0.0 messages=292.0 control_bytes=215901.0 task_ms=5469.95
statebus comparator artifact ok: external_claim_surface=formal_ready api_repeat1_ready=True
```

Preflight：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode deterministic --embedding-mode deterministic ...'
```

结果：命令 exit 0。Artifact：`artifacts/preflight_deterministic.stdout.json`。

## Formal benchmark 产物

Artifacts 已提交到：

- `artifacts/formal_auto.stdout.json`
- `artifacts/formal_shared_memory.stdout.json`
- `artifacts/formal_memfd_local.stdout.json`

抽取字段：

| Artifact | Role path | Embedding | Cases | Quality pass | Families | Requested | Used | memfd transfers | memfd publishes | memfd bytes | shm publishes | mmap publishes | semantic transfers |
|---|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| `formal_auto.stdout.json` | deterministic | deterministic | 25 | 25 | 5 | auto | shared_memory | 0 | 0 | 0 | 25 | 0 | 25 |
| `formal_shared_memory.stdout.json` | deterministic | deterministic | 25 | 25 | 5 | shared_memory | shared_memory | 0 | 0 | 0 | 25 | 0 | 25 |
| `formal_memfd_local.stdout.json` | deterministic | local | 25 | 25 | 5 | memfd | memfd | 25 | 25 | 247076 | 0 | 0 | 25 |

## local+api comprehensive 产物

Artifact 目录：

- `artifacts/local_api_20260706_191835/summary.json`
- `artifacts/local_api_20260706_191835/stages/*/stdout.json`

关键 stage：

| Stage | Role path | Embedding | Scope | 关键结果 |
|---|---|---|---|---|
| `r01_05_formal_api_local_memfd` | api | local | formal registry 25 cases / 5 families | 25/25 pass；planner/retriever/executor/summarizer 各 25 calls；memfd publish/transfer 各 25 |
| `r01_06_formal_compare_api_local_memfd` | api | local | formal financial 8-case compare | pre-fix historical result：StateBus 8/8，external 5/8；fairness hard gate pass；strict compare invalid；暴露 gate/schema/scope 问题 |
| `r01_10_continuous_replay_api_local` | api | local | 3 continuous families / 30 rounds | target replay 20/20 observed；17 validated；3 exact；answer restoration 0 |
| `r01_11_replay_negative_api_local` | api | local | replay negative audit 7 cases | pass |
| `r01_12_flagship_ablation_api_local` | api | local | 6 stress families | historical 20260706 artifact 为 4/6 pass；latest `local_api_20260707_163354` 为 3/6 pass；不能 claim all-pass |

这个 historical formal compare 的问题不是 stage failure，而是：

- compare scope 是 financial 8 cases，不是 full formal registry 25 cases。
- strict equal-quality compare 和 quality-superiority compare 的字段语义混用。
- fixed-answer scorer / external prompt 使用 `revenue_value` 表示任意 metric value，误导 gross margin / operating income case。

这些 gate/schema 问题已由 post-fix targeted compare 复验关闭；剩余限制是 compare scope 仍为 8 cases / 1 family，不是 formal registry 25 cases / 5 families。

## 2026-07-07 post-fix targeted 产物

失败的全面 run：

- 原始目录：`/home/qcrs/statebus/runs/v2-local-api-20260707_015709/`
- `02_pytest_focused_v2`：107 passed。
- `r01_05_formal_api_local_memfd`：required，失败。原因是 executor role 首次 API response 为空，`extract_json_object("")` 抛错。
- `r01_06_formal_compare_api_local_memfd`：required，exit 0，并已输出新的 strict / quality / scope fields。
- `r01_09_continuous_api_local`：optional，2400s timeout。
- `r01_10_continuous_replay_api_local`：optional，失败。原因是 summarizer 返回 malformed JSON，summary 字段后有 semicolon。
- `r01_11_replay_negative_api_local`：required，7/7 pass。
- 该 run 没有最终 `summary.json`；optional flagship tail 在 run 已经 invalid 后被停止，不能当作 passing comprehensive evidence。

修复后 targeted formal：

```text
/home/qcrs/statebus/runs/v2-targeted-json-retry-formal-20260707_191045/
```

抽取字段：

```json
{"suite_id":"targeted-json-retry-formal-formal","L3_case_count":25,"L3_quality_pass_count":25,"family_count":5,"state_pool_mode_used":"memfd","memfd_transfer_count":25,"memfd_bytes_transferred":247076}
```

修复后 targeted formal compare：

```text
/home/qcrs/statebus/runs/v2-targeted-json-retry-compare-20260707_192452/
```

抽取字段：

```json
{"formal_compare_scope_label":"formal_financial_family_8case_compare","formal_compare_case_count":8,"formal_compare_family_count":1,"formal_registry_case_count":25,"formal_registry_family_count":5,"formal_compare_full_registry_coverage":false,"strict_equal_quality_comparison_valid":true,"quality_superiority_comparison_valid":false,"formal_external_claim_kind":"efficiency_superiority_equal_quality","formal_efficiency_superiority_claim_allowed":true,"formal_quality_superiority_claim_allowed":false,"state_pool_mode_used":"memfd","memfd_transfer_count":8}
```

可支持的 compare claim 只限：

- formal financial 8-case / 1-family scope。
- equal-quality strict compare valid。
- prompt bytes 与 total tokens 下降的 efficiency-superiority claim。

仍不支持：

- formal registry 25-case / 5-family external compare。
- end-to-end latency superiority；该 targeted compare 中 `api_task_ms_delta` 为正。

## 2026-07-07 post-fix comprehensive diagnostic rerun

Artifact 目录：

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_034412/
```

状态：

```json
{"failed_required_stage_count":1,"failed_required_stages":["r01_05_formal_api_local_memfd"],"failed_stages":["r01_05_formal_api_local_memfd","r01_09_continuous_api_local","r01_10_continuous_replay_api_local","r01_12_flagship_ablation_api_local"]}
```

关键通过项：

- `00_env_probe`、`01_py_compile`、`03_runtime_smoke`、`r01_04_preflight_api_local`、`r01_11_replay_negative_api_local` 均通过。
- `02_pytest_focused_v2`：109 passed，包含 control/UDS/subprocess tests。
- `r01_06_formal_compare_api_local_memfd`：exit 0，并输出 formal financial 8-case scope fields 和 compare case structured diagnostics。
- docs artifact copy 已补齐 diagnostics：`diagnostics/manifest.json` 记录 2310 个 nested files，覆盖 benchmark reports、external/statebus outputs、state metadata、hydration audit、ref registry、socket path audit。

关键限制：

- `r01_05_formal_api_local_memfd` 是 required stage，但 1800s timeout，因此该 run 不能作为 formal internal passing comprehensive evidence。
- `r01_06_formal_compare_api_local_memfd` 虽然 8/8 case quality floor 都通过，但 external fairness hard gate 7/8，`benchmark-sample-6` failed `planner_visible_choice_only`。该 run 的 `formal_external_claim_kind=debug_only`，不能替代 `v2-targeted-json-retry-compare-20260707_192452` 的 valid targeted compare。
- optional `r01_09_continuous_api_local`、`r01_10_continuous_replay_api_local`、`r01_12_flagship_ablation_api_local` timeout。

`benchmark-sample-6` 诊断要点：

- expected：`gross_margin=39`，doc `sha256:doc-acme-2026q2`。
- external structured output：metric exact、doc exact、quality floor pass。
- fairness failure：external planner raw route 返回 `compare_metric::table_retriever`，触发 `planner_visible_choice_only=false`。
- 因此这是 fairness variance / raw planner formatting issue，不是 metric schema 回退，也不是 StateBus quality superiority evidence。

## 2026-07-07 passing comprehensive core rerun

Artifact 目录：

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/
/home/qcrs/statebus/runs/v2-local-api-20260707_091807/
```

状态：

```json
{"stage_count":12,"failed_stage_count":0,"failed_required_stage_count":0}
```

关键通过项：

- `02_pytest_focused_v2`：111 passed，100 warnings。
- `03_runtime_smoke`：text/protocol smoke 和 comparator artifact check 通过。
- `r01_04_preflight_api_local`：API/local preflight 通过，embedding device 为 `cuda:0`。
- `r01_05_formal_api_local_memfd`：25/25，5 families，planner/retriever/executor/summarizer 各 25 calls，memfd publish/transfer 各 25，247076 bytes。
- `r01_06_formal_compare_api_local_memfd`：formal financial 8-case compare，fairness gate pass count 8，failed case count 0，strict equal-quality valid，full registry coverage false，`formal_external_claim_kind=debug_only`。
- `r01_09_continuous_api_local`：3 families / 30 rounds，`L3_reuse_gain=9`。
- `r01_10_continuous_replay_api_local`：3 families / 30 rounds，20/20 target replay observed，17 validated，3 exact，answer restoration 0，`L3_reuse_gain=20`。
- `r01_11_replay_negative_api_local`：7/7 pass。

限制：

- 本次 `STATEBUS_LOCAL_API_RUN_FLAGSHIP=0`，因此不包含 optional flagship ablation evidence。
- Formal compare 仍是 8 cases / 1 financial family，不是 formal registry 25 cases / 5 families。
- 本次 compare 不支持 efficiency superiority：`formal_efficiency_superiority_claim_allowed=false`，`api_task_ms_delta=106135.486703`。

Diagnostics artifact：

```json
{"manifest":"docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/diagnostics/manifest.json","copied_file_count":1384}
```

该 copy 由 wrapper 在 exit 0 后自动生成，覆盖 nested benchmark reports、external/statebus outputs、state metadata、hydration audits、ref registries、socket path logs。

## 2026-07-07 flagship-enabled partial rerun

Artifact 目录：

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/
/home/qcrs/statebus/runs/v2-local-api-20260707_115051/
```

状态：

```json
{"stage_count":13,"failed_stage_count":3,"failed_required_stage_count":0,"failed_stages":["r01_09_continuous_api_local","r01_10_continuous_replay_api_local","r01_12_flagship_ablation_api_local"]}
```

关键通过项：

- `02_pytest_focused_v2`：111 passed。
- `r01_05_formal_api_local_memfd`：25/25，5 families，memfd publish/transfer 各 25，247076 bytes。
- `r01_06_formal_compare_api_local_memfd`：formal financial 8-case compare，strict equal-quality valid，fairness failed case count 0，`formal_external_claim_kind=debug_only`。
- `r01_11_replay_negative_api_local`：7/7 pass。

失败边界：

- `r01_09_continuous_api_local`：optional，运行约 970s 后因 API DNS/connect error 失败，trace 为 `openai.APIConnectionError` / `httpx.ConnectError: [Errno -2] Name or service not known`。
- `r01_10_continuous_replay_api_local`：optional，启动后同样因 API DNS/connect error 失败。
- `r01_12_flagship_ablation_api_local`：optional，因 API read timeout 失败，trace 为 `openai.APITimeoutError` / `httpx.ReadTimeout`。

本次 run 的正确用法：

- 可以作为 required core stages 在 `RUN_FLAGSHIP=1` 配置下仍能完成的补充证据。
- 不能作为 continuous replay passing evidence；continuous/replay 的最新 passing evidence 已由 `local_api_20260707_163354` 接管。
- 不能作为 optional flagship passing evidence；flagship 的最新 stage-exit evidence 已由 `local_api_20260707_163354` 接管，但 stress pass 只有 3/6，不能升级为 all-pass。

Diagnostics artifact：

```json
{"manifest":"docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/diagnostics/manifest.json","copied_file_count":663}
```

该失败暴露的是 API transport transient robustness 缺口，不是 compare/schema/fairness 判定失败。后续已在 `runtime/llm.py` 增加 OpenAI-compatible transport retry，并由 `local_api_20260707_163354` full `RUN_FLAGSHIP=1` comprehensive 复验。

## 2026-07-07 transport retry 后、selection retry 前的 flagship rerun

Artifact 目录：

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_130958/
/home/qcrs/statebus/runs/v2-local-api-20260707_130958/
```

状态：

```json
{"stage_count":13,"failed_stage_count":1,"failed_required_stage_count":0,"failed_stages":["r01_12_flagship_ablation_api_local"]}
```

关键通过项：

- `r01_05_formal_api_local_memfd`：25/25，5 families，memfd publish/transfer 各 25，247076 bytes。
- `r01_06_formal_compare_api_local_memfd`：formal financial 8-case compare，strict equal-quality valid，fairness failed case count 0，`formal_external_claim_kind=debug_only`。
- `r01_09_continuous_api_local`：3 families / 30 rounds，`L3_reuse_gain=9`。
- `r01_10_continuous_replay_api_local`：20/20 target replay observed，17 validated，3 exact，answer restoration 0。
- `r01_11_replay_negative_api_local`：7/7 pass。

失败边界：

- `r01_12_flagship_ablation_api_local`：optional，因 `strict_visible_candidate_mismatch:csv_profiler::csv_profiler` 失败。
- 该 run 说明 transport retry 已越过此前 API connection/timeout 失败，但 strict visible-candidate normalization 还需要 bounded retry。

## 2026-07-07 full RUN_FLAGSHIP=1 passing comprehensive rerun

Artifact 目录：

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/
/home/qcrs/statebus/runs/v2-local-api-20260707_163354/
```

状态：

```json
{"stage_count":13,"failed_stage_count":0,"failed_required_stage_count":0}
```

关键通过项：

- `02_pytest_focused_v2`：115 passed，100 warnings。
- `03_runtime_smoke`：text/protocol smoke 和 comparator artifact check 通过。
- `r01_04_preflight_api_local`：API/local preflight 通过，embedding device 为 `cuda:0`。
- `r01_05_formal_api_local_memfd`：25/25，5 families，planner/retriever/executor/summarizer 各 25 calls，memfd publish/transfer 各 25，247076 bytes。
- `r01_06_formal_compare_api_local_memfd`：formal financial 8-case compare，fairness gate pass count 8，failed case count 0，strict equal-quality valid，full registry coverage false，`formal_external_claim_kind=debug_only`。
- `r01_09_continuous_api_local`：3 families / 30 rounds，`L3_reuse_gain=9`。
- `r01_10_continuous_replay_api_local`：3 families / 30 rounds，20/20 target replay observed，17 validated，3 exact，answer restoration 0，`L3_reuse_gain=20`。
- `r01_11_replay_negative_api_local`：7/7 pass。
- `r01_12_flagship_ablation_api_local`：stage exit 0；6 stress families 中 3 个通过；`total_llm_prompt_saved_by_state_ref_bytes=37884`，`total_prompt_visible_saved_by_state_ref_bytes=21621`。

限制：

- Formal compare 仍是 8 cases / 1 financial family，不是 formal registry 25 cases / 5 families。
- 本次 compare 不支持 efficiency superiority：`formal_efficiency_superiority_claim_allowed=false`，`api_task_ms_delta=86580.45313599998`。
- Flagship stress 不是 all-pass：`csv_table_profile_v1`、`csv_correlation_replay_v1`、`long_doc_table_v1` pass；`incident_diagnosis_v2`、`long_doc_metric_replay_v1`、`cross_period_financial_v1` 未过 stress family gate。

Diagnostics artifact：

```json
{"manifest":"docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/diagnostics/manifest.json","copied_file_count":2558}
```

该 artifact copy 按 wrapper 诊断拷贝逻辑补齐，覆盖 nested benchmark reports、external/statebus outputs、state metadata、hydration audits、ref registries、socket path logs。

## 证据强度分类

强证据：

- local+api formal internal API+local+memfd JSON，支持 25/25、5 families、四角色 API call、memfd publish/transfer。
- post-fix targeted formal JSON，支持 role JSON retry 后 API+local+memfd formal internal 25/25、5 families、memfd publish/transfer。
- post-fix targeted formal compare JSON，支持 8-case financial scope 下 equal-quality prompt/token efficiency compare。
- `local_api_20260707_091807` comprehensive core JSON，支持 required stages clean、formal internal 25/25、formal compare 8-case strict equal-quality、continuous replay 20/20 target observed、replay negative 7/7。
- `local_api_20260707_091807` diagnostics copy，支持 all-case compare structured-field audit 和 nested runtime artifact self-containment，并验证 exit 0 后自动 host-copy。
- `local_api_20260707_115051` partial JSON，支持 `RUN_FLAGSHIP=1` 下 required core stages clean；作为 transport failure 定位证据。
- `local_api_20260707_130958` JSON，支持 transport retry 后 required/continuous/replay clean；作为 selection retry 定位证据。
- `local_api_20260707_163354` full JSON，支持 latest `RUN_FLAGSHIP=1` 13 stages clean、formal internal 25/25、formal compare 8-case strict equal-quality、continuous replay 20/20 target observed、flagship stage exit 0。
- Fresh container-root deterministic formal benchmark JSON，支持 backend matrix 和历史基线。
- 修复后 pytest 对 replay metric behavior 通过。
- text 与 protocol smoke execution。
- continuous replay local+api JSON，支持 20/20 target replay observed、17 validated、3 exact、answer restoration 0。

中等证据：

- v2 control/UDS/subprocess memfd 通过单测源码路径存在；`v2-local-api-20260707_015709` focused pytest 107 passed，`local_api_20260707_034412` focused pytest 109 passed，`local_api_20260707_091807` focused pytest 111 passed，`local_api_20260707_163354` focused pytest 115 passed，Docker root control subset 9 passed。
- CodeAct sandbox 与 artifact path 通过 source/tests 存在，但不是 realtime open-ended LLM formal evidence。
- formal financial 8-case external compare 能作为局部证据；gate/schema/scope 已修，但 coverage 仍是 8/1。

弱或 bounded 证据：

- memfd unavailable fallback。
- family-specific `validator.py` files。
- flagship ablation all-pass；latest full run 只有 3/6 stress families pass。

不支持：

- full formal registry external superiority。
- speed advantage。
- openEuler VM validation。
- generic answer restoration。

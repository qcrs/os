# 06 Future Implementation 与 A0-A9 验收计划

> **事实来源**：[`01`](01_current_state_and_remediation.md) 的 P0/P1/P2 登记册、[`02 §10`](02_prefix_engine_local_reuse_design.md#10-文件级改动表)、[`03 §10`](03_logitstate_core_chain_design.md#10-文件级改动表)、[`04`](04_vertical_data_preprocess_and_task_design.md) 的数据文件设计，以及 [`05`](05_experiment_matrix_metrics_and_statistics.md) 的 preregistration。
> **设计假设**：未来按仓库默认从 `feat/statebus-v2-container-runtime` 的 clean commit 建立独立 worktree；若需从当前 dirty topic worktree 前移任何非 latent 改动，先由用户明确选择 commit。公开数据、排他模型窗口、冷 cache epoch、openEuler 验证和必要评审资源届时可申请。
> **待验证实验**：A0-A9 均为 `planned/not_started`；其中 R0-R12、P-A/P-B/P-C、L-A/L-B/L-C/L-D 只有在对应授权和前置 gate 通过后才执行。

文档导航：[索引](README.md) | [00 决策与包装](00_executive_decision_and_packaging.md) | [01 现状与整改](01_current_state_and_remediation.md) | [02 Prefix](02_prefix_engine_local_reuse_design.md) | [03 LogitState](03_logitstate_core_chain_design.md) | [04 数据与任务](04_vertical_data_preprocess_and_task_design.md) | [05 实验](05_experiment_matrix_metrics_and_statistics.md) | [06 实施与验收](06_implementation_plan_and_acceptance.md) | [07 辅助核对](07_auxiliary_verification_record.md)

## 1. 计划边界与排序原则

本文件只定义未来工程顺序，不授权实现、数据下载、服务访问或模型实验。所有完成框均保持未结算；历史 E0-E6、本轮 focused tests 和 fixed fixture 不能替代任何 A-stage 验收。

排序不可倒置：

```text
A0 clean identity / guardrails
  -> A1 memory truth + semantic accounting
  -> A2 public provenance + gold isolation
  -> A3 fairness + unified preregistration
  -> A4 Prefix exact identity / typed lifecycle
  -> A5 Prefix DAG scheduling / real observation
  -> A6 LogitState exact producer / Ref lifecycle
  -> A7 calibrated ConfidenceGate / bounded effect
  -> A8 freeze and execute independent matrices
  -> A9 openEuler delivery and claim-gated packaging
```

`A0-A9` 是验收阶段，不是财务任务的 `A1-A10` 轮次。后一组只在 [`04 §7`](04_vertical_data_preprocess_and_task_design.md#7-十轮链-a公开财报跨期分析) 中表示 task IDs。

每阶段使用新 root：

```text
runs/contest_rebuild_<version>/acceptance/<A-stage>/<timestamp_run_id>/
```

需要正式样本的阶段再按 [`05 §9`](05_experiment_matrix_metrics_and_statistics.md#9-artifact-与-checksum-合同) 创建 `experiments/<R-or-P-or-L-id>/...` 子 root。任何修复、数据、gold、policy、threshold 或 runtime identity 变化都产生新 version/run ID；旧失败只读保留。

## 2. P0/P1/P2 与 A-stage 映射

| 优先项 | A-stage | 必须先完成的对象 | 退出 gate |
| --- | --- | --- | --- |
| P0-3 memory truth、P1-3 semantic accounting | A1 | actual rendered/recipe receipt；physical/logical/downstream 字段 | R1/R4 harness 可证伪，candidate 不再计 consume |
| P0-4 public vertical、P1-4 fixture 降级 | A2 | source/terms/raw/transform/split/gold ledger；2x10 manifests | R11 静态 gate 可独立重放 |
| P1-1 fairness、P1-2 capability 边界 | A3 | 独立开关、matched visibility、指标字典、自然 selected counts | preregistration/schema tests 全绿 |
| P0-2 Prefix 真实性 | A4-A5 | exact token identity、typed events、DAG ready set、有效 engine observation | P-A 可跑；P-B 对 counter available/unavailable 有确定判定 |
| P0-1 LogitState consumer | A6-A7 | dedicated alias、active Ref、cross-PID gate、calibration、effect receipt | L-A/B/D 先行；未校准不得 gated |
| P0-5 current freeze | A8 | source/config/data/runtime/image/policy hashes | R0 通过才允许正式请求 |
| P2-1 HELLO、P2-2 sandbox 措辞 | A9 | 仅必要时的 capability HELLO；contest validation profile | 不阻塞机制，但阻塞越界交付措辞 |

P0 指“没有它就不能形成正式主张”，并不意味着可以跳过 A0-A3 直接写机制。P1 是可信比较底座，必须在模型实验前完成。P2 只在实际交付需求成立时实现，不得挤占 P0 closure。

## 3. A0-A9 实施与验收

### A0：clean identity、配置护栏与基线冻结

**前置与 owner**：Release owner 从默认 `feat/statebus-v2-container-runtime` clean commit 建独立 worktree；只有需要前移当前 dirty topic worktree 中的非 latent 改动时，才由用户确认具体 commit。不得猜测性合并 latent/alignment 改动，也不得把 2026-07-20 E0-E6 snapshot 当作当前版本。

**未来文件/符号**：

- `v2/runtime/preflight.py`：增加 contest profile identity、forbidden combination 和 writable-root 检查。
- `v2/benchmark/runtime_modes.py`、`experiment_design.py`：把 L0-L3、Prefix、Logit、latent 开关解析为 mutually auditable lanes。
- `v2/benchmark/contest_evidence_closure.py`：冻结 git commit、dirty diff digest、runtime/config/image/model/tokenizer/template hashes，不只保存 branch。
- `docker/compose.yaml`、`docker/activate_statebus_container.sh`：只在最终配置审核后固定 single-container openEuler profile；此阶段不声称当前兼容。
- `tests/v2/test_preflight_and_live_runner.py`、`tests/v2/test_experiment_design.py`、新增 `tests/v2/test_contest_rebuild_config.py`：拒绝 `latent_mode != off`、多 treatment 联动和覆盖既有 run root。

**测试/产物/退出**：先跑无模型 config/preflight tests，再跑 clean full suite；产出 `A0/.../environment.json`、`runtime_config.json`、`source_identity.json`、`tests.json` 和 checksums。退出条件是正式 profile 始终 `STATEBUS_LATENT_MODE=off`，每个 lane 唯一改变项可机器校验，full suite 对选定 commit 通过。

**失败与停止**：base commit 未确认、full suite 失败、identity 不完整或需要改用户现有分支时立即停止；不进入 A1，不覆盖历史 artifact。

### A1：memory truth 与 semantic accounting

**前置与 owner**：A0 通过；Memory、Runtime、Telemetry owners 共同冻结 `candidate -> approved -> projected -> actual_consumed -> effect` 定义。

**未来文件/符号**：

- `v2/contracts/adaptive.py::RoleExecutionReceipt`、`StateConsumptionRecord`：强制 `rendered_request_hash` 或 `executed_recipe_hash`，并拆 `producer_role/PID`、`physical_consumer_component/PID`、`logical_target_role`、`downstream_hydration_roles`。
- `v2/runtime/adaptive_dispatcher.py::_record_memory_consumption`：只有 receipt-backed ID/hash/mode 可计 actual consume；action/effect 单独记账。
- `v2/runtime/smoke.py::_continuous_memory_consumption_records`：legacy approved replay 只保留兼容分类，不推断 assist consumption。
- `v2/runtime/state_consumption.py`、`v2/runtime/telemetry.py`：统一 publish/resolve/consume/effect/reject/release 口径，PID 去重不按角色求和。
- `v2/state/semantic_state.py`、`v2/retrieval/pipeline.py`、`v2/runtime/smoke.py::_build_role_hydrated_slices`：保留数值 selector，绑定 selected IDs、hydration receipts 和 release；不把 matrix 写成 LLM 输入。
- `v2/memory/models.py`、`v2/memory/store.py`、`v2/benchmark/adaptive_memory.py`、`v2/benchmark/continuous_runner.py`：实现 H0/H1/H2/H3 与 paired effect ledger。
- `tests/v2/test_adaptive_dispatcher.py`、`test_adaptive_claims.py`、`test_memory_runtime.py`、`test_retrieval_pipeline.py`、`test_continuous_runner.py`，以及新增 `test_semantic_state_accounting.py`：覆盖 disclosed-only、actual receipt、wrong hash、跨 PID selection、release 和 perturb/refusal。

**测试/产物/退出**：无模型 unit/integration 先证明 candidate/approved 不会增加 actual consume；deterministic S/H fixtures 证明合法 perturb 改变 selected IDs/action surface，非法 ref fail closed。产出 `A1/.../accounting_contract.json`、per-fixture receipts 和拒绝清单。A1 只使 R1/R4 具备可运行条件，不产生 semantic/memory 收益结论。

**失败与停止**：无法绑定真实 rendered/recipe hash、producer/consumer PID 相同却标 cross-process、release 不闭环或 H1 出现 consume 时停止。回滚为 existing baseline accounting reader；旧 E3 `consumed=23` 保持 invalidated historical count。

### A2：公开企业数据、provenance 与 gold 隔离

**前置与 owner**：A0 通过；用户授权下载；Data owner 与 rights reviewer 确认 filings.xbrl.org terms/upstream authority/redistribution 处理，task author、gold author、reviewer 分离。

**未来文件/符号**：逐项采用 [`04 §3`](04_vertical_data_preprocess_and_task_design.md#3-可复现-ingestion-pipeline) 的文件设计：

- `v2/data/public_filings/source_contracts.py`：source/terms/rights ledger schema。
- `fetch_xbrl_filings.py`、`safe_report_package.py`：受限 fetch、hash、safe unpack 和失败 ledger。
- `parse_xbrl_json.py`、`canonicalize_filing.py`：Decimal/context/unit/fact/narrative canonicalization，不读取 gold。
- `build_evidence_catalog.py`、`freeze_dataset.py`：stable ordering、split、visibility 和 checksum freeze。
- `v2/benchmark/samples/public_enterprise_v1/`：`source_ledger.jsonl`、transform/split manifests、redistributable corpus、runtime-visible task manifests 和 runtime-invisible `gold_private/`。
- `v2/benchmark/continuous_task_family.py`：新 manifest schema/version，不静默改旧 five-family fixtures。
- 新增 `tests/v2/data/test_public_filings_contracts.py`、`test_public_filings_parser.py`、`tests/v2/test_public_enterprise_manifest.py`；扩展 `tests/v2/test_contest_fairness.py` 做 gold digest/substrings 和 issuer split audit。

**测试/产物/退出**：raw -> canonical 重建 hash 必须确定；malformed archive、validation error、ambiguous rights、amendment、unit/context conflict 和 gold leakage 全部 fail closed。A2 root 引用 dataset freeze root，不复制 private gold。退出条件是两 family 各恰好 10 个 dependency-closed rounds，source/terms/raw/transform/output/gold/split hashes 完整且 R11 静态部分通过。

**失败与停止**：rights 不明确则 `derived_only/link_only/rejected`；公开样本不足则降为 `public-source pilot`；任何 gold/route hint 泄漏立即停止 formal，不替换 test issuer 迎合模型。

### A3：fairness、主矩阵与统一 preregistration

**前置与 owner**：A1、A2 通过；Benchmark owner 冻结 [`05`](05_experiment_matrix_metrics_and_statistics.md) 的指标、样本下限、ABBA seed、invalid/retry/stop 规则。

**未来文件/符号**：

- `v2/benchmark/contest_fairness.py`：role-visible business information、gold visibility、quality equivalence 和 claim eligibility。
- `v2/benchmark/runtime_modes.py`、`experiment_design.py`：L0-L3 与 S/H/P/G matrices 的唯一改变项验证。
- `v2/benchmark/continuous_task_family.py`、`continuous_runner.py`：依赖闭包、失败保留、独立 lane roots 和 natural route/tool selection receipts。
- `v2/benchmark/reporting.py`、`contest_evidence_closure.py`：统一分母、failed/invalid、ABBA、cold/hot strata、checksums 和 machine-readable claim matrix。
- 新增 `v2/benchmark/contest_rebuild_runner.py`：只编排已注册 experiment，不隐式启用 treatment。
- `tests/v2/test_contest_fairness.py`、`test_experiment_design.py`、`test_continuous_task_family_loader.py`、`test_continuous_suite_schedule.py`、`test_continuous_runner.py`：覆盖 lane leakage、gold leakage、dependency failure、run-root collision 和 claim downgrade。

**测试/产物/退出**：生成不发模型的 synthetic preregistration，验证每个矩阵只有一个 treatment、L0 标为 harness-internal matched comparator、L3 memory 不跨 lane、Prefix/Logit/latent 在 L0-L3 中关闭。退出产物为 `A3/.../preregistration_schema.json`、frozen metric dictionary、order manifest 和 stopping rules。

**失败与停止**：任一 lane 可见业务信息不等价、expected route/tool 进入 prompt、失败样本可被删除或同 ID 覆盖时停止。A3 不因 anticipated result 调整 quality threshold。

### A4：Prefix exact identity、layout 与 typed lifecycle

**前置与 owner**：A1-A3 通过；Prompt/Runtime/Protocol owners 冻结 model/tokenizer/chat-template/layout identity。此阶段只做 [`02 §14`](02_prefix_engine_local_reuse_design.md#14-最小实施顺序与验收) 的 Identity 和 Typed lifecycle slices。

**精确文件计划**：必须逐行执行 [`02 §10`](02_prefix_engine_local_reuse_design.md#10-文件级改动表) 的前半部分，不得替换为通用 “prefix module” 任务：

| `02 §10` 文件/符号 | A4 责任与验收 |
| --- | --- |
| `v2/contracts/prefix.py`（新增） | 实现 `PrefixReuseIntentV2`、identity、request/observation/invalidated event；unknown version fail closed |
| `v2/contracts/__init__.py` | 只导出 typed contracts；import/round-trip test |
| `v2/control/statebus_v2.proto`、`schema.py`、`messages.py` | typed envelope 或审计过的 local-only mapping；生成代码/compat test；永不含 KV bytes |
| `v2/runtime/neural_state.py` | 拆 `PrefixLineageIdentity`/`ExactTokenPrefixIdentity`；`cache_hit` 迁移为 `candidate_handle_seen` |
| `v2/retrieval/pipeline.py` | 输出稳定 selected-entry/visibility keys；selected IDs/rank 不变 |
| `v2/runtime/smoke.py::_build_role_hydrated_slices` | 求 Executor/Summarizer 授权交集；额外 role evidence 留在 suffix |
| `v2/runtime/role_path.py::compile_prefix_layout` | 固定 common-prefix/suffix/schema boundary；legacy string input 只作过渡 |
| `v2/runtime/prefix_identity.py`（新增） | frozen tokenizer/template 编译 exact IDs/hash/full blocks；不可用即 ineligible |
| `runtime/llm.py` | 暴露最终 request/template kwargs digest 和未来 stream hook；不重发请求取 identity |

**测试/产物/退出**：按 `02 §11` 新增/修改 `tests/v2/test_kv_prefix_control_plane.py`、`test_prefix_render_identity.py` 和 Proto contract tests。固定 tokenizer fixture 必须覆盖 same shared prefix equality、reorder/template/role-specific negative controls、visibility intersection 和完整 block gate。A4 产出 intent/event fixtures；只可交付 exact-token intent，不可说 engine hit。

**失败与停止**：不同参与角色 common token IDs 不全等、schema 落入 common window、未授权 evidence 进入交集或 tokenizer/template identity 不可冻结时停在 `ineligible`。回滚 `STATEBUS_PREFIX_POLICY=off` 恢复 A0 baseline renderer。

### A5：Prefix DAG scheduler、真实观测与 P-A readiness

**前置与 owner**：A4 通过；Benchmark/Runtime owners 完成请求级 observation 原子性。访问 `/metrics`、发模型请求或创建 cold epoch 均按第 8 节分别授权。

**精确文件计划**：继续逐行执行 [`02 §10`](02_prefix_engine_local_reuse_design.md#10-文件级改动表)：

| `02 §10` 文件/符号 | A5 责任与验收 |
| --- | --- |
| `v2/runtime/vllm_metrics.py` | 固定 vLLM 版本对应 counter names/labels/unit；拒绝 reset、gauge-only 和污染窗口 |
| `v2/runtime/prefix_feedback.py` | 只消费 valid typed observation；unavailable 不调策略 |
| `v2/benchmark/kv_prefix_schedule.py` | 以 DAG ready set 选择 affinity；cycle/failed dependency 请求前失败 |
| `v2/benchmark/continuous_runner.py` | request-level before/after、exclusive guard、ready-set loop、order/epoch metadata |
| `v2/benchmark/kv_prefix_experiment.py` | P-A/B/C、ABBA、continuous/cold strata 和新 run root；旧 artifacts 只读 |
| `tests/v2/test_kv_prefix_control_plane.py` | deprecated field/compat/fail-closed |
| `tests/v2/test_prefix_render_identity.py`（新增） | real tokenizer/template identity，不发模型 |
| `tests/v2/test_prefix_dependency_schedule.py`（新增） | ready set、cycle、failed dependency、adaptive reorder |
| `tests/v2/test_prefix_metrics_observation.py`（新增） | counter unit/labels/reset/pollution/gauge fixtures |
| `tests/v2/test_prefix_live_capability.py`（新增、opt-in） | 经确认后单次只读 `/metrics`；只判 available/unavailable |

**测试/产物/退出**：无模型 parser/scheduler tests 和 P-A token portion 先通过；五个现有 manifests 只验证兼容/依赖，不升级为正式业务数据。若获服务确认，保存未经改写的 before/after schema snapshot。退出条件是每个请求只能进入 `eligible -> requested -> observed|invalidated|unavailable`，`candidate_handle_seen` 永不进入 observed hit 分母。

**失败与停止**：counter 不存在可交付 honest unavailable；并发污染、epoch 变化和 reset 使 observation invalid，不补发请求制造 hit。回滚只切 prefix policy off，不清用户 cache、不重启服务、不影响 semantic/memory/logit。

### A6：LogitState exact producer、Ref 与跨 PID 生命周期

**前置与 owner**：A1-A3 通过；Runtime/State/Protocol owners 冻结 `executor_tool_recipe_choice_v1` candidate aliases，且 endpoint capability 未知时实现必须 fail closed。此阶段执行 [`03 §14`](03_logitstate_core_chain_design.md#14-配置回滚资源与验收) 中 extractor、contract/store 和 cross-PID slice。

**精确文件计划**：逐行执行 [`03 §10`](03_logitstate_core_chain_design.md#10-文件级改动表) 的 producer/lifecycle 部分：

| `03 §10` 文件/符号 | A6 责任与验收 |
| --- | --- |
| `v2/contracts/logit.py`（新增） | `CandidateSurfaceV2`、`LogitStateContractV2`、GateDecision、EffectReceipt schemas |
| `v2/contracts/__init__.py` | 导出新合同，不改变 baseline behavior |
| `v2/refs/models.py::LogitStateRef` | v2 binding/lease/PID/model/template/policy fields；v1 只读且不得 gated |
| `v2/control/statebus_v2.proto`、`schema.py`、`messages.py` | typed ref/grant/gate result；禁止 raw completion/token strings |
| `runtime/llm.py::OpenAICompatibleLLMClient.complete` | 每 attempt 独立 capability/bytes receipt；missing top-logprobs 为 unavailable |
| `v2/runtime/role_path.py::validate_execution_choice` | dedicated single-token alias choice；legacy JSON path只作 baseline fallback |
| `v2/runtime/logit_state.py` | exact alias position extractor、candidate-order `<f4` probabilities + `other_mass`；peak extractor deprecated diagnostic |
| `v2/state/logit_state.py`（新增） | shared-memory first、mmap fallback、hash/lease/resolve/tombstone/release/TTL |
| `v2/state/store.py::LayeredStoragePolicy` | contest `LOGIT_STATE=(SHARED_MEMORY,MMAP_FILE)`，generic policy变化有回归测试 |
| `v2/control/worker_operations.py`、`subprocess_worker.py` | `logit_gate_v1` independent PID operation、timeout/crash cleanup |
| `v2/runtime/smoke.py` | publish/grant/consume/action/effect/release events；删除伪 transfer/裸 0.3 gate |

**测试/产物/退出**：扩展 `tests/v2/test_logit_state.py`，新增 `test_logit_state_lifecycle.py`、`test_logit_state_fail_closed.py`。覆盖多 token alias、缺 top-k、NaN/tail、错误 dtype/hash/byte order、过期/跨 task ref、consumer crash、重复 resolve/action 和 payload unlink + terminal tombstone。退出要求 producer PID != consumer PID，valid/perturbed 数值能产生可区分 GateDecision receipt；这仍不是质量收益。

**失败与停止**：无法定位唯一 decision token、mapping 不完整、active sidecar release 后仍假装 active 或 baseline outcome 被 invalid ref 污染时停止。回滚 `STATEBUS_LOGIT_POLICY=off`，保留普通 alias choice + standard validator。

### A7：Calibration、ConfidenceGate 与有界 effect

**前置与 owner**：A6 通过；至少 200 个 dev/calibration labeled decisions 且错误正例至少 40，否则只做 exploratory telemetry。Calibration owner 与 holdout evaluator 分离。

**精确文件计划**：完成 [`03 §10`](03_logitstate_core_chain_design.md#10-文件级改动表) 的 consumer/calibration/runner 部分：

| `03 §10` 文件/符号 | A7 责任与验收 |
| --- | --- |
| `v2/runtime/confidence_gate.py`（新增） | 读取 numeric Ref，加载 hash-addressed calibrator/policy，只输出一个 bounded action |
| `v2/runtime/smoke.py` | Controller 执行 `accept/expand_once/verify_once/selection_retry_once/fail_closed` 并写 EffectReceipt |
| `v2/runtime/adaptive_dispatcher.py` | 第二阶段接同一 closed Executor receipt，不扩展到所有角色 |
| `v2/benchmark/logit_calibration.py`（新增） | L-A fit/eval/freeze；holdout 永不写参数 |
| `v2/benchmark/logit_state_experiment.py`（新增） | L-B/C/D 独立 lanes、失败保留和新 run roots |
| `tests/v2/test_confidence_gate.py`（新增） | action budget=1、idempotency、missing calibration、threshold bands |
| `tests/v2/test_logit_live_capability.py`（新增、opt-in） | 经用户授权的一次 fixed request；只判 top-logprobs shape capability |

**测试/产物/退出**：先跑无模型 Gate fixtures，再运行获授权的 L-A offline calibration；冻结 calibration/policy hashes 后才允许 `telemetry_only` 升至 `gated`。ECE/Brier/NLL/risk-coverage/AURC、missingness、false-trigger 预算和 threshold 来源全部保留。L-A/B/D 是进入 L-C 的前置，不等于 L-C quality claim。

**失败与停止**：无预测力、样本不足、threshold 依赖 holdout、额外动作超过 1 或 verifier 递归触发 gate 时不运行 gated formal。保留 telemetry/负结果并回滚 off，不在 holdout 调阈值。

### A8：current-version freeze 与独立正式矩阵

**前置与 owner**：A0-A7 全部通过；Release owner 重新执行 R0，Data owner 复核 R11，Experiment owner 获得串行模型窗口。任何 stage 未通过不得用 “先跑再补证据” 绕过。

**未来执行顺序**：

1. 无模型 gate：R0 identity/regression、R11 provenance/gold visibility、P-A token identity、L-B/D static failure controls。
2. 机制 gate：R1/S semantic lifecycle、R4/H memory actual-effect counterfactual。
3. 主矩阵：R2 L0-L3 与 R3 两个独立 10-round families；Prefix/Logit/latent 固定 off。
4. Prefix：P-A quality portion，P-B continuous；cold/independent epoch 只有单独授权才运行；P-C 最后运行。
5. Logit：L-A frozen artifact复核、L-B/D live lifecycle、L-C off/telemetry/gated quality-cost。
6. R12 只汇总自然 route/tool selected counts；不修改 task manifest 补覆盖。

**未来文件/产物**：`v2/benchmark/contest_rebuild_runner.py` 编排；`continuous_runner.py`、`kv_prefix_experiment.py`、`logit_state_experiment.py` 各自写独立 roots；`reporting.py` 和 `contest_evidence_closure.py` 只读汇总。每 root 必须具备 [`05 §9`](05_experiment_matrix_metrics_and_statistics.md#9-artifact-与-checksum-合同) 的 preregistration、environment、order、events、failures、quality、metrics、claim matrix 和 checksum。

**退出/停止**：必须满足 [`05 §6-§12`](05_experiment_matrix_metrics_and_statistics.md#6-quality-gate-与等价性) 的 hard gate、样本下限、ABBA、CI、失败保留和负结果规则。counter unavailable 不改用 estimate；quality 不等价阻断速度 claim；Logit 无净价值阻断 quality headline；任一修复用新 version/run ID。

### A9：openEuler 交付、回滚演练与 claim-gated 包装

**前置与 owner**：A8 已结算 machine-readable claim matrix；用户授权目标 openEuler 容器验证。Release、Docs 和 independent reviewer 共同签字。

**未来文件/符号**：

- `docker/compose.yaml`、`docker/activate_statebus_container.sh`：冻结 single-container runtime、UID/GID、mount 和 resource profile。
- `scripts/run_v2_full_container_audit_suite.sh`：执行 clean image deterministic/full regression；不得依赖 host Docker socket inside runtime。
- `v2/benchmark/contest_evidence_closure.py`、`reporting.py`：校验 manifests/checksums，生成 claim matrix 和降级原因。
- 新增 `v2/benchmark/claim_matrix.py` 与 `tests/v2/test_claim_matrix.py`：没有 artifact hash、quality gate、counter validity、CI 的句子不可输出。
- `v2/control/statebus_v2.proto`：只有 deployment discovery 确有需求时才增加 HELLO/ACK；否则 P2-1 明确 `not_required`，不伪造 wire handshake。
- packaging lint：sandbox 只称 contest validation profile；Prefix 只称 engine-local；latent/KV handoff 永久关闭。

**验收/回滚**：在 fresh openEuler container 重放 R0 delivery subset、无模型 mechanism contracts、artifact checksum 和 off-mode baselines；演练 `prefix=off`、`logit=off`、memory current recompute。A9 输出 delivery manifest、SBOM/image digest、tests、rollback receipts 和最终 claim matrix。只有 A0-A9 全部结算后，`00` 中 future-gated 句子才可按实际结果升级；失败项自动降级，不能改报告生成器绕过。

## 4. Prefix 文件级追踪完整性

下表是 A4/A5 对 [`02 §10`](02_prefix_engine_local_reuse_design.md#10-文件级改动表) 的覆盖审计，未来 code review 必须逐项勾选；当前均为 `not_started`。

| `02` 计划行 | Stage | 最小 review evidence |
| --- | --- | --- |
| contracts + exports + Proto mapping | A4 | typed schema/round-trip/unknown-version rejection |
| neural identity/registry rename | A4 | lineage/exact identity分离；deprecated reader不写 observed hit |
| retrieval visibility + hydrated slices | A4 | authorized intersection、selected IDs不变、extra evidence suffix |
| role layout + exact tokenizer identity | A4 | final rendered common token IDs/full blocks相同；negative control |
| `runtime/llm.py` request digest/TTFT hook | A4/A5 | final request binding；stream/non-stream availability |
| metrics + feedback | A5 | real-version fixtures、unit/labels/reset/pollution；valid-only feedback |
| DAG scheduler + continuous runner | A5 | ready-set proof、request snapshots、exclusive interval |
| experiment runner | A5/A8 | P-A/B/C unique treatment、ABBA、cold/hot、new roots |
| five planned test surfaces | A4/A5 | unit/render/DAG/metrics/live opt-in，各自授权边界 |

## 5. LogitState 文件级追踪完整性

下表是 A6/A7 对 [`03 §10`](03_logitstate_core_chain_design.md#10-文件级改动表) 的覆盖审计；当前均为 `not_started`。

| `03` 计划行 | Stage | 最小 review evidence |
| --- | --- | --- |
| contracts + exports + Ref v2 + Proto | A6 | candidate/order/binding/lease/PID/policy hash；v1不得 gated |
| LLM attempt receipt + dedicated alias producer | A6 | exact response field/position；missing capability structured unavailable |
| extractor + Logit state store/policy | A6 | `<f4` little-endian candidate order + other_mass；shared memory resolve/release/tombstone |
| worker operation + smoke orchestration | A6/A7 | independent PID、grant、one action token、effect/release finally |
| `confidence_gate.py` | A7 | frozen calibrator、bounded policy、baseline fallback |
| adaptive dispatcher second-stage hook | A7 | same closed decision contract；no role-surface expansion |
| calibration + experiment runners | A7/A8 | L-A dev/test isolation；L-B/C/D roots and failure retention |
| static/lifecycle/gate/fail/live tests | A6/A7 | all listed perturbations；live capability opt-in only |

## 6. 配置、迁移与关闭语义

| 配置 | future default / formal rule | 关闭后的行为 |
| --- | --- | --- |
| `STATEBUS_LATENT_MODE` | `off`，所有 formal lanes固定 | 不创建/消费 latent、prompt embeds 或 hidden/KV state |
| `STATEBUS_PREFIX_POLICY` | `off`; A4后可 `observe`; A5/P gates后才 `on` | A0 frozen independent renderer/order |
| `STATEBUS_PREFIX_LAYOUT_VERSION` | pinned v2 | 版本漂移使 request ineligible |
| `STATEBUS_PREFIX_CACHE_NAMESPACE/EPOCH` | run-scoped / engine start-reset UUID | epoch变化只 invalidate control handles，不操作 engine cache |
| `STATEBUS_PREFIX_REQUIRE_EXCLUSIVE_METRICS` | formal `true` | 无独占证据 observation unavailable |
| `STATEBUS_PREFIX_FEEDBACK_ADAPTIVE` | formal `false` until separate P-B policy study | 固定 preregistered order |
| `STATEBUS_LOGIT_POLICY` | `off`; A6后 `telemetry_only`; L-A/B/D后才可 `gated` | ordinary alias selection + standard validator |
| `STATEBUS_LOGIT_DECISION_TYPE` | `executor_tool_recipe_choice_v1` only | 不扩展到任意 JSON/generation token |
| `STATEBUS_LOGIT_CALIBRATION_ARTIFACT/POLICY` | hash-addressed | 缺失/hash错禁止 gated |
| `STATEBUS_LOGIT_MAX_ACTIONS` | 1 | 不重试 gate、不递归 verify |
| `STATEBUS_LOGIT_STATE_POOL_MODE` | shared_memory, mmap fallback | release payload并保留 terminal tombstone |

迁移分四步：

1. 新 reader 先兼容旧 Prefix/Logit telemetry，并明确标 `legacy_lineage_only`、`deprecated_diagnostic`。
2. 新 writer 只写 `candidate_handle_seen` 与 publish/resolve/consume/effect/release 分事件；不双写假 `hit/transfer`。
3. 所有新 schema 使用新 run root；旧 E0-E6 和本轮 fixture 不做 in-place rewrite。
4. 一个 frozen release 后才能删除 deprecated writer；reader 保留到归档迁移完成。

回滚不得删除失败 artifact、清理用户 cache、重启服务或改变其他机制。Prefix 和 Logit 各自 off；memory incompatible 时 current recompute；semantic ref invalid 时 deterministic baseline selection。回滚本身必须产生 receipt 和 quality result。

## 7. 风险、资源与停止线

| 风险/触发 | 依赖/资源 | 缓解 | 停止线 |
| --- | --- | --- | --- |
| dirty base、未经确认的 forward-port 或历史 identity 混用 | 用户决定、Release owner | 默认 v2 branch clean worktree + complete hashes | 需前移的 commit 未确认则不实施 |
| public terms/rights 或 parser 不确定 | rights reviewer、网络、磁盘、XBRL parser | rejected-by-default ledger、raw/canonical rebuild | R11 失败不跑 formal |
| gold/route leakage | independent authors/reviewer | private gold root、request digest scan | 任一命中立即停 |
| shared prefix 不够 full block/语义漂移 | local tokenizer/model/template files | exact IDs + negative controls + quality gate | ineligible，不改任务造长 prefix |
| vLLM counter schema缺失或流量污染 | 排他服务窗口、metrics schema | unavailable/invalid strata | 不以 estimate/gauge替代 |
| cold epoch 需要服务动作 | service owner、GPU窗口 | 单独批准重启/namespace方案 | 无授权只做 continuous-hot |
| top-logprobs/alias mapping不可用 | 一次 capability probe、closed aliases | baseline fallback、structured unavailable | 不回退 arbitrary JSON peak entropy |
| Logit calibration无预测力 | >=200 dev/cal decisions、>=40 errors、reviewer | telemetry-only/off、保留负结果 | 不运行 gated holdout |
| gate额外成本/false trigger超预算 | verifier/tool/LLM quota | one-action budget、quality-cost frontier | L-C不进 headline |
| shared memory泄漏/consumer crash | `/dev/shm` budget、supervisor | lease、finally release、terminal tombstone | lifecycle test失败不进 live |
| GPU/API时序波动 | 排他 GPU、串行 ABBA、clock sync | cold/hot分层、失败保留、cluster CI | 不比较污染样本 |
| openEuler/image drift | container builder、SBOM、target host | fresh image digest + A9 regression | 只保留历史 E6 措辞 |

最低资源预算在 implementation PR 前冻结：Prefix identity/event 每请求小于 64 KiB；Logit payload为 `4 * (candidate_count + 1)` bytes 且受 candidate cap；`STATEBUS_LOGIT_MAX_ACTIONS=1`；shared-memory 总预算沿 `LayeredStoragePolicy` 配置；formal API严格串行。具体 latency/LLM/tool预算只能由 dev pilot 预注册，不从 holdout反推。

## 8. 用户授权与外部决策点

| ID | 动作 | 为什么需要确认 | 未授权时可继续什么 |
| --- | --- | --- | --- |
| U0 | 确认是否从当前 dirty topic worktree 前移特定非 latent commit | 默认 base 已由 repo 规则固定；前移涉及用户代码归属 | 直接从默认 clean v2 branch 做 future work，或继续只做设计 |
| U1 | 下载/冻结 filings 及 terms snapshot | 网络、数据许可、磁盘与再分发责任 | 写 schema/parser fixtures；不能过 R11 |
| U2 | 访问当前服务 `/metrics` | Prompt允许只读，但本轮未触服务；需协调排他观察窗口 | static Prometheus fixtures；标 counter unknown |
| U3 | 发送一次 `top_logprobs` capability request | 会执行模型并可能改变 cache | static response fixtures；标 capability unknown |
| U4 | 运行 P/L/R 成组模型或正式实验 | GPU/API成本和正式 evidence 生成 | unit/contract/render/parser tests |
| U5 | 重启/清理服务或建立 cold epoch | 改变全局服务/cache状态 | 只报告 continuous-hot 限制 |
| U6 | 在 openEuler 容器/目标机做 final validation | 外部运行状态与交付资源 | 不升级 current-version compatibility claim |

授权只覆盖表中具体动作，不自动授权其他服务变更、数据改造或实验扩展。

## 9. A0-A9 最终验收清单

| Stage | 当前状态 | 必须存在的验收证据 | 失败后的最强可交付 |
| --- | --- | --- | --- |
| A0 | `not_started` | clean identity、latent-off config、full tests、checksums | 本设计与历史证据边界 |
| A1 | `not_started` | semantic/memory真实 receipts、counterfactual、release | store/query或实现事实，无收益 |
| A2 | `not_started` | source/terms/raw/transform/split/gold/2x10 freeze | repo-local/dev fixtures或public-source pilot |
| A3 | `not_started` | matched lanes、gold visibility、preregistration、claim downgrade tests | 机制诊断，不做 superiority |
| A4 | `not_started` | exact common token IDs、typed lifecycle、negative controls | ineligible/intent-only |
| A5 | `not_started` | DAG proof、valid/unavailable observation、P-A readiness | exact intent/schedule，无 engine hit主张 |
| A6 | `not_started` | dedicated alias、active Ref、cross-PID numeric consume、release | lifecycle机制，无质量改善 |
| A7 | `not_started` | calibration freeze、one-action gate、L-A/B/D gates | telemetry/off 或负结果 |
| A8 | `not_started` | R0-R12/P/L 独立 artifacts、quality、ABBA/CI、failures | 逐 claim 自动降级 |
| A9 | `not_started` | fresh openEuler image regression、rollback receipts、claim matrix | 仅历史 E6，不称当前可交付 |

只有对应行真实结算为 pass，包装生成器才可读取其 claim；不存在 “总体 A9 通过” 来覆盖某个失败机制的捷径。

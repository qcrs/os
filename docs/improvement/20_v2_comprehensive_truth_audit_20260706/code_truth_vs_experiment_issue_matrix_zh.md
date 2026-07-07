# 代码事实与实验证据对照矩阵

日期：2026-07-06

分支：`feat/statebus-v2-container-runtime`

主要证据：

- 代码路径：`v2/`、`tests/v2/`、`scripts/run_v2_local_api_comprehensive_stats.sh`
- local+api 运行：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260706_191835/summary.json`
- 原始运行目录：`/home/qcrs/statebus/runs/v2-local-api-20260706_191835/`
- 失败的全面复验：`/home/qcrs/statebus/runs/v2-local-api-20260707_015709/`，没有最终 `summary.json`；required formal stage 失败后 optional stages 继续运行，optional flagship tail 被停止。
- 修复后 targeted formal：`/home/qcrs/statebus/runs/v2-targeted-json-retry-formal-20260707_191045/`
- 修复后 targeted formal compare：`/home/qcrs/statebus/runs/v2-targeted-json-retry-compare-20260707_192452/`
- 修复后 comprehensive diagnostic rerun：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_034412/summary.json`；有最终 summary 和 diagnostics manifest，但 required formal internal timeout，formal compare debug-only。
- 修复后 passing comprehensive core rerun：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/summary.json`；12 stages exit 0，required failed stage count 0，flagship 显式关闭。
- flagship-enabled transport failure rerun：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/summary.json`；13 stages，failed required stage count 0，但 optional continuous / replay / flagship 因 API connection/timeout 失败。
- post-transport-retry selection failure rerun：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_130958/summary.json`；required/continuous/replay clean，但 optional flagship 因 strict visible-candidate mismatch 失败。
- latest full `RUN_FLAGSHIP=1` comprehensive rerun：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/summary.json`；13 stages exit 0，required failed stage count 0，flagship stage exit 0，stress pass 3/6。

本文件是当前 v2 code truth + experiment claim 矩阵。它不生成 prompt，也不服务于答辩话术；它只回答一个问题：代码真实实现、实验实际测到的结构、文档 claim 三者是否一致。

## 0. 审计原则

这轮不能再用“谨慎表述”掩盖实现问题。所有结论按下面规则处理：

- 如果代码实现存在，但 benchmark 没跑到，只能写“实现存在，缺正式实验覆盖”。
- 如果 benchmark 跑通，但跑的是替代路径，要写清替代路径，例如 loopback、fixed-answer、manifest-backed replay。
- 如果实验指标名字和实际语义不一致，要修字段模型，不靠文案解释。
- 如果 external 失败来自 schema/prompt 误导，不能把它包装成纯质量优势。
- 如果共享状态只是 embedding state + hydration refs，不能扩大成 hidden-state / KV transfer。

## 1. 总体判断

当前最强证据是 `formal internal`：

- `local_api_20260707_163354/r01_05_formal_api_local_memfd`
- API 四角色路径
- local embedding
- memfd StatePool
- 25 cases / 5 formal families
- 25/25 quality pass
- planner/retriever/executor/summarizer 各 25 次 API call
- `semantic_state_transfer_count=25`
- `memfd_publish_count=25`
- `memfd_transfer_count=25`

当前最严重问题是 `formal compare`：

- post-fix `v2-targeted-json-retry-compare-20260707_192452` exit 0，但不是 25-case registry compare，而是 formal financial family 8-case compare。
- gate 字段已拆分：`strict_equal_quality_comparison_valid=true`、`formal_external_claim_kind=efficiency_superiority_equal_quality`。
- latest full comprehensive `local_api_20260707_163354` 也证明 formal financial 8-case strict equal-quality compare valid、公平门 8/8，但本次 `formal_external_claim_kind=debug_only`，不支持 efficiency superiority。
- external metric schema 已迁移到 `metric_name` / `metric_value`，该 targeted compare strict valid；旧 `revenue_value` 只能作为兼容字段。

因此结论不是“full external superiority 已闭环”。正确处理是：保留 formal internal 强证据；承认 formal financial 8-case strict equal-quality compare 已成立；把 targeted prompt/token efficiency result 与 latest full comprehensive debug-only timing 结果分开引用；继续把 full formal registry external compare 作为后续覆盖扩展。

历史 comprehensive diagnostic rerun `local_api_20260707_034412` 进一步说明：metric schema 与 structured diagnostics 已可读，8/8 compare case quality floor 都通过；但 external planner raw route 在 `benchmark-sample-6` 中包含 candidate key，触发 fairness hard gate failure，因此该 run 只能作 debug evidence。后续 fairness gate 修复后，`local_api_20260707_163354` 中 8 个 compare cases 全部 fairness pass。

## 1.1 2026-07-07 contest audit pass

本次赛题导向复核把 A-H 八个问题重新压到代码和 artifact 层，不新增 prompt 文档，结论如下：

| 审计点 | 当前结论 | 证据 / 限制 |
|---|---|---|
| A. token fairness | `r01_06` 是同为四角色的 strict equal-quality 8-case compare，`llm_call_count_delta=0`，StateBus prompt bytes/input tokens 更低；但 completion/total tokens 更高，本次 `formal_external_claim_kind=debug_only` | external: prompt tokens 12678、completion 10199、total 22877、prompt bytes 43213；StateBus: prompt tokens 9645、completion 19695、total 29340、prompt bytes 30661。只能写 prompt/input/control-byte 优势，不能写 total-token/efficiency superiority |
| B. flagship stress 3/6 | stage exit 0 不等于 stress all-pass；失败原因已能按 family 定位 | `incident_diagnosis_v2`：L3 quality 7/10，T2 quality 10/10，质量 headline 不合格；`long_doc_metric_replay_v1`：L3 quality 8/10，validated 7、exact 1、skipped 9，质量/回放 headline 不合格；`cross_period_financial_v1`：quality 10/10、replay headline true，但 L2 相对 T2 无 prompt saving，semantic selection dominates |
| C. non-text StateRef boundary | 已实现的是 `EMBEDDING_STATE` semantic state + typed refs + memfd/shared_memory/mmap materialization + hydration accounting | raw evidence/text/table slices 仍通过 hydration 进入 prompt；StateRef 是 additive mechanism，不是 raw-evidence replacement；没有 hidden-state/KV transfer |
| D. formal compare coverage | formal internal 是 25 cases / 5 families；formal compare 仍是 8 cases / 1 financial family | `FixedAnswerSample` 需要 route/tool/expected facts；registry `MinimalBenchmarkSample` 缺少这些字段。扩到 25/5 需要 adapter、prompt 和 scorer 工作 |
| E. v2 text vs protocol | v2 smoke 有 text/protocol attribution，formal internal 当前没有 API text-mode companion stage | 通信效率（25分）仍缺 v2 formal same-task text vs protocol token/byte delta |
| F. openEuler | container evidence 已有，openEuler 24.03-LTS-SP3 VM 仍未验证 | 交付 claim 不能从 Docker/container evidence 外推到 VM |
| G. docs claim risk | `docs/reports/v2_experiment_summary_20260703.md` 是历史报告，仍含 openEuler container、bwrap、old efficiency 字段 | 已加更强 warning；对外 claim 必须优先引用本审计目录和 latest artifact |
| H. schema/reporting gap | comparator canonical payload 已有核心 delta，但 prompt/input 与 completion/output split 仍不够显式 | 后续应把 prompt tokens、completion tokens、prompt bytes、completion bytes/total tokens 分开输出，避免再次把 prompt saving 写成 total-token superiority |

## 2. 代码事实 vs 实验证据矩阵

| 能力 / Claim 对象 | 代码真实路径 | local+api / 测试证据 | 实验是否测到真实结构 | 当前问题 | 级别 | 修复方向 |
|---|---|---|---|---|---|---|
| API 四角色路径 | `v2/runtime/role_path.py`；runtime driver 调 planner / retriever / executor / summarizer | `local_api_20260707_163354/r01_05_formal_api_local_memfd`：四个 role 各 25 次 API call | 是。formal internal 的 API role path 被打到 | 不能外推为 realtime open-ended CodeAct generation | P2 | 保持四角色 API claim；CodeAct claim 继续限定为 bounded path，除非新增 formal API CodeAct stage |
| typed Protobuf 控制面 | `v2/control/messages.py`、`v2/control/schema.py`、`v2/control/transport.py`、`v2/control/statebus_v2.proto` | `tests/v2/test_control_plane.py`、`test_uds_loopback.py`、`test_subprocess_executor.py` 存在；`runtime.smoke` 有 protocol mode；`local_api_20260707_163354` focused pytest 115 passed；Docker root control subset 9 passed | 部分测到。正式 benchmark runtime 使用 `ControlPlaneLoopbackServer.exchange_sequence_by_contract()`，不是 subprocess worker | formal benchmark 的 UDS 是 loopback harness，不是 subprocess transport | P2 | 如要 claim subprocess execution，需要新增 subprocess benchmark stage |
| AF_UNIX 路径风险 | `scripts/run_v2_local_api_comprehensive_stats.sh` 的 `short_socket_path()` | 每个 live stage 使用 `/tmp/sb2-<16hex>.sock`，长度约 30 | 是。当前 local+api 避开了深目录 socket path | 其他脚本未必都有同等保护 | P2 | 保留 fail-fast 长度检查；把 socket path 长度写入 summary；迁移其他 v2 脚本 |
| SemanticStateRef / ExecutionArtifactRef 分离 | `v2/refs/models.py` 的 `SemanticStateRef`、`ExecutionArtifactRef`；registry 分离 ref kind | representative registry 中同时有 semantic state、execution artifact、prompt-slice artifact、memory ref；`local_api_20260707_163354` diagnostics copy 归档 ref registry/state metadata/hydration audit | 是。ref 模型和 registry 路径真实存在 | 仍不能写成 hidden-state/KV transfer | P2 | 保持 ref 类型分离；后续扩展 registry-backed compare 和 replay evidence |
| memfd StatePool 正路径 | `v2/state/store.py` 的 `LayeredStateStore.publish()`、`_materialize_memfd()` | `local_api_20260707_163354/r01_05`：25 publish/transfer，247076 bytes；state metadata 为 `storage_kind=memfd` | 是。memfd 正路径真实发生 | 不能证明 no-memfd fallback；memfd FD 传 subprocess 主要是单测 | P2 | 增加 capability-masked no-memfd stage；保持 `test_subprocess_transport_memfd_e2e` 在 focused gate |
| shared_memory / mmap backend | `v2/state/store.py` policy/fallback | deterministic artifacts 有 shared_memory；mmap 主要作为 fallback/code path | shared_memory 正路径有历史 deterministic 证据；mmap 缺本轮 local+api 强证据 | 不能把所有 backend 都写成本轮 API 证明 | P2 | backend matrix 单独 stage，记录 requested/used/fallback reason |
| 非文本中间状态 | `SemanticStateRef` + `LayeredStateStore` + hydration manifest；runtime 记录 `STATE_PUBLISHED` / `STATE_HYDRATED` | `r01_05` 有 semantic transfer/memfd；sample 7 state metadata 为 `EMBEDDING_STATE`；hydration audit 有 role prompt slices；`r01_12` stress summary 明确不 claim KV/hidden-state | 部分测到。传输的是 embedding semantic state + refs；证据文本/表格仍通过 hydration 进入 prompt | 不能宣称 raw evidence 永不进 prompt；不能宣称 StateRef 替代了证据；不能宣称 hidden-state/KV transfer | P1 | 文档和 telemetry 字段明确 object kind；若要更强非文本 claim，增加 evidence pack / table slice 的非文本 materialization stage |
| formal internal 25/5 | `v2/benchmark/live_runner.py` formal non-compare 使用 `load_registered_formal_samples()` | `r01_05`：25 cases / 5 families / 25 pass | 是。这个是当前最强 formal evidence | 只证明 internal StateBus，不证明 external superiority | P1 | 保留强 claim，但所有 compare claim 分开写 |
| formal compare 覆盖 | `live_runner.py` formal compare 当前仍是 fixed-answer financial family compare | targeted compare 和 `local_api_20260707_163354`：`formal_compare_scope_label=formal_financial_family_8case_compare`，8 cases / 1 family；registry 25 cases / 5 families；full coverage false | 是。scope metadata 已测到；不是 25-case registry compare | 仍不能把 formal internal 25/5 与 formal compare 8/1 混写；latest full comprehensive 不支持本次 efficiency superiority；扩展到 registry 需要 sample adapter，不是换 loader | P0 partially closed | 8/1 metadata 已修；新增 registry-backed formal compare adapter/prompt/scorer |
| compare gate 语义 | `v2/benchmark/comparator_runner.py` 输出 strict / quality / efficiency gate fields | targeted compare：`strict_equal_quality_comparison_valid=true`、`formal_external_claim_kind=efficiency_superiority_equal_quality`；`local_api_20260707_163354`：strict true、`formal_external_claim_kind=debug_only` | 是。字段语义已拆开 | 旧 artifacts 仍有混用字段；latest full run 只有 prompt/input byte advantage，completion/total tokens 不支持 total-token superiority | P0 closed | 继续保留 legacy 字段语义说明；补 prompt/input vs completion/output split；full registry compare 单独实现 |
| external metric schema | `v2/benchmark/scoring.py` 优先读 `metric_value`；`external_text_baseline.py` prompt 要求 `metric_name` / `metric_value` | tests 通过；targeted compare 8/8 strict valid | 是。metric schema 修复已测到 | legacy `revenue_value` 只能兼容，不应作为新 claim 主字段 | P1 closed | 后续所有新 samples 使用 metric fields |
| per-case diagnostics | comparator 写 nested reports；wrapper summary/copy 抽取 compare expected/external/statebus fields | `local_api_20260707_163354` summary 有 8 个 formal compare cases 和 3 个 dev compare cases structured diagnostics；diagnostics manifest copied_file_count=2558 | 是。当前 artifact copy 可支撑复盘 | failure/nonzero wrapper exit 后仍需确认 copy 自动执行 | P1 closed for full run | 保持 diagnostics bundle；后续补测 failure-path host copy |
| continuous replay | `v2/runtime/replay.py` exact / validated gates；`v2/benchmark/continuous_runner.py` replay audit | `r01_10`：30 rounds，20 target observed，17 validated，3 exact，answer restoration 0 | 是，但范围是 manifest/contract-backed replay | 不能说任意共享记忆推理复用；不能说 answer restoration | P1 | 保留 bounded replay claim；新增跨 family / negative / history artifact diagnostics |
| replay negative | `v2/benchmark/replay_negative_audit.py` | `r01_11`：7 cases pass | 是，覆盖构造负例 | 不代表所有真实历史 replay 场景 | P2 | 扩大负例矩阵：runtime signature、output contract、schema shape、artifact hash |
| flagship ablation | `v2/benchmark/flagship_ablation.py` | `local_api_20260707_163354/r01_12`：stage exit 0；6 stress families，3 pass；StateRef prompt savings recorded；stress summary 有 family-level fields | 部分测到 | 不能 claim all-pass；`incident_diagnosis_v2` 与 `long_doc_metric_replay_v1` 是 quality/headline gap，`cross_period_financial_v1` 是 prompt-saving gate gap | P2 | 把三类 failure reason 写入 report；后续按 family 修 quality/replay/prompt-saving gate |
| local+api artifact 归档 | `scripts/run_v2_local_api_comprehensive_stats.sh` host copy 复制 `artifacts/` 并补充 diagnostics bundle | `local_api_20260707_163354` docs artifact 有 `summary.json`、stage stdout、`diagnostics/manifest.json` 和 nested runtime/workspace diagnostics | 是。当前 docs artifact copy 可复盘 compare case、state metadata、hydration audit、ref registry 和 socket path | failure/nonzero run 的 host-copy path 仍需单独补测 | P1 closed for full run | 保持 diagnostics bundle；下一次 failure/nonzero comprehensive rerun 验证 automatic host copy |
| Docker root + activation | 脚本 host 侧 `docker exec -u 0`；container 内优先 `/usr/local/bin/activate_statebus_container.sh`，再 fallback host activation | `local_api_20260707_163354` activation script `/usr/local/bin/activate_statebus_container.sh` success；Docker root control subset 9 passed | container activation path 已测到；host conda activation 不适用于 container root | 仍需避免文档把 host activation contract 写成 container activation contract | P1 partial | summary 明确 actual python/package versions；container docs 使用 `/usr/local/bin/activate_statebus_container.sh` |
| role JSON response robustness | `RolePathRunner._complete_json_role()` retries planner/retriever/executor/summarizer JSON extraction | `v2-local-api-20260707_015709` 暴露 empty executor / malformed summarizer；post-fix tests、targeted formal/compare 和 `local_api_20260707_163354` 通过 | 是。失败形态被 regression 覆盖，full comprehensive rerun 通过 | 不代表模型语义错误会被纠正；仍保留 strict parser 和 visible candidate validation | P1 closed | 保持 bounded retry，不做 oracle/candidate fallback |
| strict visible-candidate selection retry | `RolePathRunner` 对 retriever/executor selection normalization 的 `RoleSelectionError` 做 bounded retry | `local_api_20260707_130958` 暴露 `strict_visible_candidate_mismatch:csv_profiler::csv_profiler`；post-fix selection retry tests 通过；`local_api_20260707_163354` full run 通过 | 是。selection mismatch failure 被 regression 覆盖，flagship full run 不再卡住 | 不代表可以接受不可见 candidate 或 best-candidate fallback | P1 closed | 保持 strict validation；继续记录 retry attempts |
| live API transport robustness | `runtime/llm.py` 的 `OpenAICompatibleLLMClient._create_completion_with_retry()` | `local_api_20260707_115051` 暴露 optional stages 因 `APIConnectionError` / `APITimeoutError` 被打断；post-fix transport retry 单测 2 passed；`local_api_20260707_163354` full `RUN_FLAGSHIP=1` 通过 | 是。代码层 transient retry 已覆盖，并有 full rerun 复验 | 未来长跑仍可能遇到超出 retry budget 的 provider failure | P1 closed for current evidence | 保持 retry budget telemetry；必要时增加 serialized repeat evidence |

## 3. 合并后的问题清单

### P0-1：compare gate 语义混用

historical 现状：

- strict equal-quality headline comparison 失败，因为 external 只有 5/8 quality floor pass。
- quality superiority signal 成立，因为 StateBus 8/8、external 5/8、fairness hard gate pass。
- 代码把这两个判断投射到同一组字段，产生 `comparison_valid=false` 但 `formal_superiority_claim_allowed=true`。

post-fix 现状：

- `v2-targeted-json-retry-compare-20260707_192452` 中 strict equal-quality comparison valid。
- `formal_external_claim_kind=efficiency_superiority_equal_quality`。
- 该结论只覆盖 formal financial 8-case compare scope。

已完成修复：

- `comparison_valid` 保留为 legacy strict valid 或改名。
- 新增：
  - `strict_equal_quality_comparison_valid`
  - `quality_superiority_comparison_valid`
  - `formal_quality_superiority_claim_allowed`
  - `formal_efficiency_superiority_claim_allowed`
  - `formal_external_claim_kind`
- markdown report 同时列出 strict path 和 quality-superiority path，不再只给一个 invalid/allowed 混合状态。

验收状态：

- legacy external 5/8、StateBus 8/8 fixture 下，strict 为 false，quality superiority 为 true，efficiency superiority 为 false。
- post-fix targeted compare 下，strict 为 true，efficiency superiority equal-quality claim allowed；latest full comprehensive 下 strict 为 true，但 efficiency superiority 不成立。
- `claim_restriction` 与 `formal_external_claim_kind` 不再把 fairness failure、strict equal-quality 和 efficiency-superiority 混成同一个判断。

### P0-2：formal compare scope 不等于 formal internal scope

现状：

- internal formal：25 cases / 5 families。
- compare formal：post-fix targeted artifact 仍是 8 cases / 1 financial family。

已完成修复：

- compare payload 必须输出：
  - `formal_compare_scope_label`
  - `formal_compare_case_count`
  - `formal_compare_family_count`
  - `formal_registry_case_count`
  - `formal_compare_full_registry_coverage`

验收状态：

- targeted compare summary 明确显示 `formal_financial_family_8case_compare`、8 compare cases、25 registry cases、full coverage false。
- `local_api_20260707_163354` full comprehensive 也显示相同 scope，并且 8/8 fairness gate pass。
- 文档 generator 不能把它写成 full 25-case external compare。

### P1-1：external baseline metric schema 错误

historical 现状：

- fixed-answer scorer 使用 `revenue_value` 表示所有 metric 的 value。
- external retriever prompt 也要求返回 `revenue_value`。
- gross margin / operating income 样本把 external 模型误导到 revenue 字段。

post-fix 现状：

- scorer 优先读 `metric_value`，external prompt 要求 `metric_name` / `metric_value`。
- targeted compare 8/8 strict valid；`revenue_value` 仅保留兼容。

已完成修复：

- sample schema 引入 `metric_name` / `metric_value`。
- scorer 优先读 `metric_value`，兼容读 `revenue_value`。
- external prompt 改成返回 requested metric 对应的 `metric_value`。
- executor artifact 和 report 改名为 metric 字段。

验收状态：

- 如果 retriever 输出 `metric_name=operating_income, metric_value=19`，sample 7 通过。
- 如果 retriever 仍输出 revenue 120，sample 7 继续失败。
- 不允许用 corpus fallback 自动补正确答案。

### P1-2：artifact 归档不自足

pre-fix 现状：

- docs artifact 只复制 `artifacts/`。
- per-case output、nested comparator reports、hydration/ref registry 留在 run workdir。

修复：

- 脚本在 host copy 阶段增加 diagnostics bundle：
  - `benchmark_reports/*compare*.json`
  - failed external/statebus case outputs
  - representative `state/metadata/*.json`
  - representative `logs/hydration_audit.json`
  - representative `registry/ref_registry.json`
  - socket path audit

验收：

- 只看 docs artifact copy，就能复盘 sample 6/7/8 为什么失败。

当前状态：

- `local_api_20260707_163354` docs artifact copy 已包含 `diagnostics/manifest.json`，copied_file_count=2558，按 wrapper 诊断拷贝逻辑补齐。
- `summary.json` 已包含 8 个 formal compare cases 的 expected / external observed / StateBus observed fields。
- `local_api_20260707_034412` 的 sample 6 fairness failure 已由后续 external fairness gate 修复覆盖；`local_api_20260707_163354` formal compare fairness failed case count 为 0。

### P1-3：Docker root activation 语义不稳定

现状：

- host 脚本确实使用 `docker exec -u 0`。
- container 内正式路径应为 `/usr/local/bin/activate_statebus_container.sh`。
- host conda activation command 仍不能作为 container root contract。

修复：

- 增加 container activation 脚本，或更新 image 使 root 下 activation 成功。
- summary 记录实际 Python、site-packages、CUDA、embedding model、LLM config。

验收：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && source /usr/local/bin/activate_statebus_container.sh && /usr/bin/python3 -c "import v2.runtime.driver"'
```

如果 container 不使用 conda，则改为正式支持：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && source /usr/local/bin/activate_statebus_container.sh && /usr/bin/python3 -c "import v2.runtime.driver"'
```

### P2-1：formal runtime 控制面是 loopback，不是 subprocess benchmark

现状：

- `SubprocessExecutorTransport` 和 memfd FD passing 有代码和测试。
- formal runtime 主要走 loopback harness。

修复：

- focused pytest 纳入 `test_control_plane.py`、`test_uds_loopback.py`、`test_subprocess_executor.py`。
- 如要 claim subprocess execution，新增 subprocess benchmark stage。

### P2-2：memfd fallback 缺少真实负向环境

现状：

- memfd positive path 强。
- no-memfd fallback 主要靠 failure-path/unit 证据。

修复：

- capability-masked subprocess/container stage。
- 记录 fallback selected backend 和 reason。

### P2-3：flagship 3/6 需要失败家族拆解

现状：

- `local_api_20260707_163354` 的 flagship stage exit 0，但只有 3/6 stress families pass。
- `incident_diagnosis_v2`、`long_doc_metric_replay_v1`、`cross_period_financial_v1` 未通过 stress family gate。

修复：

- focused ablation 输出 family-level fail reason。
- 区分 quality fail、replay target fail、prompt saving fail、任务定义不适合 stress gate。

## 4. 修复顺序

### 第 0 步：先固定复验路径

目标：以后每次修复都用同一条 local+api 路径复验。

当前可用命令：

```bash
source deploy/activate_statebus_host.sh
STATEBUS_LOCAL_API_RUN_FLAGSHIP=0 bash scripts/run_v2_local_api_comprehensive_stats.sh
```

正式 Docker root 复验要求：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && source /usr/local/bin/activate_statebus_container.sh && /usr/bin/python3 -m pytest -q tests/v2/test_control_plane.py tests/v2/test_uds_loopback.py tests/v2/test_subprocess_executor.py'
```

如果 container activation 还没修好，脚本必须在 summary 中明确写出 fallback 到 `/usr/bin/python3`，不能假装已经激活 conda env。

### 第 1 步：修 compare gate 字段

先不改 external 行为，只修指标模型。这样可以避免同时改变实验结果和 claim gate，降低定位难度。

需要改：

- `v2/benchmark/comparator_runner.py`
- `tests/v2/test_compare_diagnostics.py` 或新增 comparator gate 单测

复验：

```bash
source deploy/activate_statebus_host.sh
/usr/bin/python3 -m pytest -q tests/v2/test_compare_diagnostics.py
STATEBUS_LOCAL_API_RUN_FLAGSHIP=0 bash scripts/run_v2_local_api_comprehensive_stats.sh
```

### 第 2 步：补 formal compare scope metadata

需要改：

- `v2/benchmark/live_runner.py`
- `v2/benchmark/comparator_runner.py`
- `scripts/run_v2_local_api_comprehensive_stats.sh` summary extraction

复验字段：

- `formal_compare_scope_label=formal_financial_family_8case_compare`
- `formal_compare_case_count=8`
- `formal_registry_case_count=25`
- `formal_compare_full_registry_coverage=false`

### 第 3 步：迁移 metric schema

需要改：

- `v2/benchmark/scoring.py`
- `v2/benchmark/external_text_baseline.py`
- `v2/benchmark/samples/formal_financial_family/*.json`
- fixed-answer / comparator tests

复验：

- sample 6/7/8 的 expected vs observed 使用 `metric_value`。
- external 如果抽对 requested metric 就通过。
- 不允许 corpus fallback 替模型补答案。

### 第 4 步：实现 registry-backed formal external compare

需要改：

- `v2/benchmark/live_runner.py`
- external baseline 对 5 个 formal families 的 prompt/context 支持
- formal compare reports

复验：

- 新 scope：`formal_registry_25case_5family_compare`
- family count 5，case count 25
- unsupported family count 为 0，或明确列出 unsupported reason

### 第 5 步：补证据归档和控制面覆盖

需要改：

- `scripts/run_v2_local_api_comprehensive_stats.sh`
- focused pytest 列表
- diagnostics bundle 生成

复验：

- docs artifact copy 中包含 nested compare report、failed case output、state metadata、hydration audit、ref registry。
- focused pytest 包含 control/UDS/subprocess memfd。

## 5. 修复后的 claim 分层

修复 P0/P1 后，当前只能这样写：

- 强证据：formal internal API+local+memfd 25/25、5 families。
- 强证据：memfd positive path 25 publish/transfer。
- 强证据：continuous replay target 20/20 observed，17 validated，3 exact，answer restoration 0。
- 限定证据：post-fix formal financial 8-case compare strict equal-quality valid；targeted compare 支持该 8-case scope 下的 prompt/token efficiency-superiority-equal-quality claim，latest full comprehensive 不支持本次 efficiency superiority。
- 限定证据：carrier compare 是内部 text vs structured carrier attribution，不是 external superiority。
- 限定证据：flagship ablation latest full run stage exit 0，但 stress families 只有 3/6 pass。

仍不能写：

- full 25-case formal external superiority。
- end-to-end speed advantage。
- openEuler VM validation。
- nsjail / production sandbox validation。
- hidden-state / KV transfer。
- generic answer restoration。

## 6. 这轮真正要改的不是口径

过去反复失败的原因不是“AI 过于谨慎”，而是三个事实没被拆开：

1. internal formal 和 external compare 测的不是同一个样本集合。
2. strict equal-quality efficiency compare 和 quality-superiority compare 是两种 gate。
3. external baseline 的 structured schema 对非 revenue metric 曾是错误激励，post-fix 后只能引用 `metric_name` / `metric_value` targeted evidence。

所以修复不能从”换一种安全说法”开始，而要从字段、schema、coverage、artifact 归档开始。当前字段、schema、transport retry、selection retry 和 full `RUN_FLAGSHIP=1` comprehensive 复验已闭环；剩余闭环点是 full registry compare、flagship stress family 3/6 拆解和 failure-path artifact copy。

---

## 7. 赛题导向 gap 分析（2026-07-07 新增）

更新来源：`10_contest_oriented_followup_plan_20260707.md`

### 7.1 latest artifact 真实结论

| 字段 | 值 | 含义 |
|---|---|---|
| `stage_count` | 13 | 总 stage 数 |
| `failed_stage_count` | 0 | 全部通过 |
| `failed_required_stage_count` | 0 | 必选 stage 零失败 |
| `r01_05` `L3_quality_pass_count` | 25 / 25 | formal internal 全通过 |
| `r01_05` `family_count` | 5 | 5 个 formal family |
| `r01_05` `memfd_transfer_count` | 25 | 非文本 memfd 传输25次 |
| `r01_05` `memfd_bytes_transferred` | 247076 | 非文本传输字节数 |
| `r01_06` `formal_compare_case_count` | 8 | compare 只覆盖 8 cases |
| `r01_06` `formal_compare_full_registry_coverage` | false | 不是 full 25/5 registry compare |
| `r01_06` `strict_equal_quality_comparison_valid` | true | equal-quality gate 通过 |
| `r01_06` `formal_external_claim_kind` | debug_only | **本次不支持 efficiency superiority** |
| `r01_06` `formal_efficiency_superiority_claim_allowed` | false | 禁止写效率优势 |
| `r01_06` `api_task_ms_delta` | +86580ms | StateBus 比 external 慢（并发测量，不可比） |
| `r01_06` `api_prompt_bytes_delta` | -12552 | StateBus prompt bytes 更低（可引用） |
| `r01_10` `replay_observed_round_count` | 20/20 | replay 全部观测到 |
| `r01_10` `validated_replay_count` | 17 | validated replay |
| `r01_10` `exact_replay_count` | 3 | exact replay |
| `r01_10` `answer_restoration_replay_count` | 0 | answer restoration 为零 |
| `r01_12` `stress_pass_family_count` | 3/6 | flagship stress 不是 all-pass |

### 7.2 赛题评分维度证据强度评估

| 评分维度 | 分值 | 证据强度 | 主要缺口 |
|---|---|---|---|
| 通信效率 | 25 | MEDIUM | v2 formal 无 text vs protocol 双模对比；efficiency superiority 当前 debug_only |
| 状态传递创新 | 20 | STRONG | embedding semantic state + memfd 25次/247076bytes；需精确表述，不能扩大为 KV/hidden |
| 记忆复用效果 | 20 | STRONG | replay 20/20,17 validated,3 exact；reuse_gain=20 |
| 系统完整性 | 20 | STRONG | 4 agents,30 rounds,115 tests,UDS/Protobuf |
| 实验验证 | 15 | WEAK | compare 只 8/1 scope；timing evidence 无效；缺 text vs protocol v2 formal 对比 |

### 7.3 新增问题（赛题导向）

| ID | 标题 | 级别 |
|---|---|---|
| V2-AUDIT-021 | openEuler 24.03-LTS-SP3 交付未验证 | P0 |
| V2-AUDIT-022 | 演示视频缺失 | P1 |
| V2-AUDIT-023 | V2 formal 缺 text vs protocol 双模对比 | P1 |
| NEW-004 | comprehensive timing 不可用于效率 claim | P2 |
| NEW-005 | flagship 3/6 失败 family 已诊断但未修复 | P2 |

详细内容见 `05_merged_issue_ledger.md` 和 `10_contest_oriented_followup_plan_20260707.md`。

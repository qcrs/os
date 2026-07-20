# StateBus v2 赛题证据闭环完成审计

日期：2026-07-20

审计对象：[实施与实验执行 Prompt](00_implementation_and_experiment_execution_prompt_zh.md)

结果：实现、测试、E0-E6 新鲜容器证据和报告合同已闭合；Git 分阶段提交与 clean-worktree 条件尚未满足，因为当前执行环境将 `.git` 元数据设为只读。该限制不改变 run 结果，但阻止把 dirty-worktree snapshot 升级成已提交的冻结版本。

## 1. 审计基线

| 字段 | 值 |
| --- | --- |
| Branch | `feat/yzm-v2-migration` |
| Recorded HEAD | `a3a5ec836d13c5e9d77811edd25d58d24af227b6` |
| Canonical worktree flag | `git_dirty=true` |
| Canonical evidence root | `/home/qcrs/statebus/runs/contest_evidence_closure_20260720` |
| Runtime freeze SHA | `e0b04923132f4a139eaa4c2b0ec71b1299d5fd75ccb492d362987a67f5f95afa` |
| Image digest | `sha256:715ded05373ca023f3acf33d180b8db2e0c4f2b1361b6c2a31c58c33c1fb6647` |

## 2. Phase 实施映射

| Prompt 要求 | 主要实现证据 | 主要测试证据 | Run 证据 | 状态 |
| --- | --- | --- | --- | --- |
| Phase 0：冻结身份、串行 stage、不可覆盖 artifact | `v2/benchmark/contest_evidence_closure.py`、`scripts/v2_diagnostics/run_contest_evidence_closure_gpu1.sh` | E0/E6 acceptance gate | 所有 canonical manifest 记录 SHA、dirty flag、image digest、serial flag；失败 root 保留 | PASS |
| Phase 1.1：financial adapter 不预筛唯一答案行 | `v2/benchmark/adaptive_formal.py::_financial_source_rows` | `test_financial_adapter_exposes_the_complete_authorized_table_with_locators` | E5 25/25 | PASS |
| Phase 1.2：公式来自公开 task contract，gold 对 Runtime 不可见 | `v2/benchmark/adaptive_formal.py`、`v2/benchmark/scoring.py` | `test_public_narrative_and_table_operations_recompute_without_expected_facts`、`test_post_runtime_benchmark_scorer_*` | E1 fairness gold audit、E4/E5 `benchmark_oracle_visible_to_roles=false` | PASS |
| Phase 1.3：角色模型与 deterministic Executor 独立配置 | `v2/benchmark/continuous_runner.py`、`v2/benchmark/live_runner.py`、`v2/runtime/smoke.py` | `test_continuous_runner_*`、`test_preflight_and_live_runner.py` | E1 四层都记录三角色 local-vLLM、Executor `deterministic_codeact` | PASS |
| Phase 1.4：matched lane contract 与 subprocess carrier | `v2/benchmark/contest_fairness.py`、`v2/control/messages.py`、`v2/control/transport.py`、`v2/control/subprocess_worker.py` | `test_contest_fairness.py`、`test_subprocess_executor_utf8_text_round_trip`、`test_v2_smoke_subprocess_transport_avoids_loopback` | E1 `comparison_valid=true`、unexpected differences 0 | PASS |
| Phase 2：family store、commit gate、query/match/consume/effect/reject | `v2/memory/models.py`、`v2/memory/store.py`、`v2/runtime/adaptive_mainline.py`、`v2/runtime/adaptive_dispatcher.py`、`v2/benchmark/adaptive_memory.py` | `test_adaptive_memory_persists_across_fresh_runners_*`、`test_adaptive_memory_assist_is_an_actual_executor_input_*`、`test_hybrid_memory_*` | E3 6/6，漏斗闭合，不兼容 fixture fail-closed | PASS |
| Phase 3：`causal_core`/`long_horizon`、R6-R10、R9 fixture | `v2/benchmark/continuous_task_family.py`、`v2/benchmark/continuous_runner.py`、两个 formal manifest 与 schema-drift fixtures | `test_formal_family_views_and_incompatible_fixture_contract`、`test_formal_views_are_dependency_closed_*`、`test_continuous_runner_executes_formal_long_horizon_*` | E1 40/40；E2 20/20 | PASS |
| Phase 4：4-case semantic holdout 与 Runtime freeze | `v2/benchmark/semantic_holdout.py`、`v2/benchmark/samples/semantic_holdout/` | `test_semantic_holdout_*`、`test_semantic_holdout_addition_does_not_change_frozen_runtime_directories`、retrieval routing tests | E4 4/4；semantic 3/table 1；cross-process state gate true | PASS |
| Phase 5：25-case Adaptive DSL/CodeAct 独立证据 | `v2/benchmark/adaptive_formal.py`、`v2/benchmark/adaptive_formal_mainline.py` | `test_adaptive_formal_compare.py`、role prompt、structured retrieval 和 sandbox tests | E5 25/25；DSL 7/Python 18；18 个 bwrap/non-root records | PASS |
| 最终 full gate | wrapper acceptance、`v2.benchmark.live_runner` preflight | full `tests/v2` | E6 558 passed、100 warnings；preflight OK | PASS |

## 3. 完成定义逐条审计

| 完成定义 | 审计读数 | 状态 |
| --- | --- | --- |
| 预解题、错误文案、role/executor 控制、fairness audit 修复 | full-table source；公开 contract；per-role profile；fairness valid | PASS |
| Adaptive memory 跨 task commit/load/match/consume/effect/reject | E3 `6 -> 16 -> 15 -> 15 -> 23 -> 23`，拒绝 1 | PASS |
| 两个 family 均有 5 轮和 10 轮 view | manifest loader/design gate 通过；E1/E2 分别执行 | PASS |
| E1-E5 新鲜、不可覆盖容器 artifact | canonical root 独立；失败 run 未删除或覆盖 | PASS |
| E1 四 lane 各 10/10；E2 两组各 10/10 | 40/40 与 20/20 | PASS |
| semantic holdout 4/4，自然覆盖 semantic/table | semantic 3、table 1 | PASS |
| Adaptive 25/25，DSL/CodeAct 均覆盖，Python bwrap/non-root | DSL 7、Python 18；18/18 bwrap，UID/GID 65534 | PASS |
| memory 指标逐层分开 | E1/E2/E3 均保留 query/candidate/compatible/approved/consumed/effect | PASS |
| final `tests/v2` 与 preflight | 558 passed；preflight `ok=true` | PASS |
| 报告给出负结果和 claim 边界 | 最终报告第 10/11 节 | PASS |
| 两个 README 与最终 evidence index 更新 | 本轮三个文档及两个 README | PASS |
| 代码、测试、报告分阶段提交且工作树无污染 | `.git` 只读，无法创建提交；worktree 仍 dirty | BLOCKED |

按 Prompt 的严格“同时满足”定义，最后一项未完成，因此仓库级完成状态是 `BLOCKED_ON_GIT_METADATA`，而不是伪写成 fully committed。

## 4. 赛题问题到证据的闭环

| 问题 | 主要证据 | 读数 | 审计结论 |
| --- | --- | --- | --- |
| 结构化控制面开销 | E1 L0 -> L1 | control `-83.05%`；wire `-68.95%`；prompt token `+2.88%` | 只支持字节下降，不支持 token 下降 |
| 非文本语义状态 | E1 L1 -> L2；E4 | E1 semantic transfer 9；E4 semantic route 3，数值 top-k 改变 selected IDs | embedding StateRef 成立；hidden/KV 不成立 |
| 跨任务 memory | E1/E2/E3 | E1 effect 2；E2 effect 9；E3 actual consumption 23 | 消费闭环成立；分类不得合并 |
| 至少 3 个 LLM Agent 和受控自主性 | E5 | Planner/Retriever/Executor/Summarizer；25/25 | 有限 registry/离线域成立，开放工具生态不成立 |
| 两组连续任务与长期稳定性 | E1/E2 | 5+5 四层、10+10 L3 全通过 | 单容器离线 family 稳定性成立 |
| openEuler 交付 | E0/E6 | 135 focused；558 full；两次 preflight OK | 单容器成立，VM/跨机不成立 |

## 5. 指标语义审计

以下计数保持分离：

- `history_backed_reuse_count`：前序已验证事实/产物可用；不等于 memory match。
- `artifact_reuse_count`：artifact/lineage 被复用；不等于 replay。
- `assist_count`：MemoryRef 进入角色输入但当前工作仍验证；不等于跳步。
- `validated_replay_count`：复用 recipe/strategy 并对当前输入重算验证；不等于恢复旧答案。
- `exact_replay_count`：精确签名与输入一致才允许恢复；E1-E3 均为 0。
- `skipped_step_count` 与 `skipped_llm_call_count` 独立；E1/E2 是 `2/0`，E3 是 `1/1`。

E3 的 15 个 approved match 生成 23 条消费记录，是因为同一 MemoryRef 可被 Executor 与 Summarizer 多次真实消费；记录按 consumer role/step 保留，没有用 consumption 数反推唯一 match 数。

## 6. Oracle 与真实性审计

- E1 fairness manifest 扫描实际持久化 role requests，并用 value provenance 区分公开输入值与 benchmark-only gold。
- E4/E5 均记录 `benchmark_oracle_visible_to_roles=false`。
- Runtime quality validator 先于 external expected-facts score；memory commit 记录 `benchmark_gold_used=false`。
- financial source adapter 向 Agent 暴露授权范围内完整表与 locator，而不是按 ticker/quarter/metric 预筛唯一目标行。
- capability registry 是权限与 I/O contract，不包含 task ID 或 expected answer；公开 operation/schema 集仍限定为离线分析域。

## 7. Semantic State 与 Freeze 审计

E4 的 semantic state 是 shared-memory float32 matrix。至少一个 canonical matrix 为 `[9,1024]`、36,864 bytes；混合输入 S4 为 `[6,1024]`、24,576 bytes。producer PID 308338 与所有 consumer PID 不同，state consumption record 包含 selected IDs、cosine scores、decision-surface hash 和 downstream evidence ref。

冻结范围：

```text
v2/runtime
v2/control
v2/state
v2/memory
```

E4 freeze audit 对 59 个文件重算后：added 0、changed 0、removed 0。freeze ledger hash 为 `b3a13dd7c23e15c5c726cbec3c7f97259458bed260969d0f712e470122b18ebe`。

## 8. 失败证据审计

失败与诊断 root 均保留。关键修复链为：

- focused 133/134 -> E0 135/135；
- E1/E2 各有一次 SIGTERM，随后使用新 run ID 串行通过；
- E3 5/6 -> 6/6；
- E4 1/4 -> 2/4 -> 3/4 -> 2/4 -> 4/4；
- E5 24/25 -> 单例 probe -> 25/25；
- E6 555 passed/3 failed -> 558 passed。

没有把失败 root 改名为成功证据，也没有删除失败 traceback、SIGTERM exit code 或 shared-memory warning。

## 9. 最终完整性与污染审计

最终只读检查结果：

| 检查 | 结果 |
| --- | --- |
| `git diff --check` | PASS，exit 0 |
| E0-E6 `sha256sum -c --quiet checksums.sha256` | 7/7 PASS，均 exit 0 |
| Runtime per-file ledger | 59/59 PASS，exit 0 |
| `v2/control` directory hash | `35f82790062975a9bb3200ef7b965606c805fb969c1bbf2674947a274b00df09`，MATCH |
| `v2/memory` directory hash | `4439343001073c3d59b603b965593942a3276785c6c5d3b166bc1ae46b5b958c`，MATCH |
| `v2/runtime` directory hash | `772f217de7e74808fda3d44966e310f9b4b388cdd74126b510696b5085b955fd`，MATCH |
| `v2/state` directory hash | `f87587bfad569aeec41b1c3a83fc1011e1530a5bece804fa7d5efe5e86c9e08f`，MATCH |
| git-visible run/cache/model/key/secret scan | PASS，无匹配路径 |
| project 内大于 100 MiB 文件扫描 | 仅命中 `third_party/*/.git/objects/pack`，无模型或 run artifact 混入主 worktree |
| pytest/formal experiment process scan | PASS；除扫描命令自身外无匹配进程 |

工作树仍包含单独的未跟踪研究材料 `docs/2511.20639v3.pdf` 和 `docs/planning/kv_hidden_state_transfer_design_20260720.md`。它们不属于 E0-E6 canonical artifact，也未纳入本轮五组提交尝试；本审计不删除或接管这些既有材料。工作树因此不能被描述为 clean。

StateBus 的 qwen3-32b vLLM 服务仍运行于 PID 1290482，并有正常的 `resource_tracker` 与 model worker 子进程 1290991/1290993；这不是 pytest 或正式实验。

## 10. 提交尝试

Prompt 要求的五条消息均已按顺序实际尝试，并按逻辑文件组先执行 `git add`。结果如下：

| 顺序 | 提交消息 | `git add` | `git commit` | 结果 |
| ---: | --- | --- | --- | --- |
| 1 | `v2: harden contest lane fairness and truth boundaries` | exit 128：无法创建 `.git/index.lock`，read-only filesystem | exit 1：无 staged changes | 未创建 commit |
| 2 | `v2: close adaptive memory consumption loop` | exit 128：同一只读错误 | exit 128：同一只读错误 | 未创建 commit |
| 3 | `v2: add continuous task views and semantic holdout` | exit 128：同一只读错误 | exit 128：同一只读错误 | 未创建 commit |
| 4 | `test: add contest evidence closure gates` | exit 128：同一只读错误 | exit 128：同一只读错误 | 未创建 commit |
| 5 | `docs: report fresh contest evidence closure results` | exit 128：同一只读错误 | exit 128：同一只读错误 | 未创建 commit |

核心错误：

```text
fatal: Unable to create '/home/qcrs/statebus/project/.git/index.lock': Read-only file system
```

提交前后 `git log -5 --oneline` 顶部仍为 `a3a5ec8 docs: make contest closure issues and container gates explicit`，确认没有产生空提交或部分提交。未成功的提交不分配伪造 hash。

### 10.1 可导入 staging 提交序列

为避免只读 `.git` 让分阶段提交内容不可复核，另在用户可写目录建立了同 HEAD 的隔离 clone：

```text
/home/qcrs/statebus/work/contest_evidence_closure_commit_staging_20260720
```

前四个提交为：

| 顺序 | Commit | Subject |
| ---: | --- | --- |
| 1 | `f7995f0` | `v2: harden contest lane fairness and truth boundaries` |
| 2 | `dcc43b7` | `v2: close adaptive memory consumption loop` |
| 3 | `dfbcf52` | `v2: add continuous task views and semantic holdout` |
| 4 | `6a98d2c` | `test: add contest evidence closure gates` |
| 5 | staging branch tip，见外部 commit-series manifest | `docs: report fresh contest evidence closure results` |

最终 bundle 与逐提交 patch 的固定输出位置为：

```text
/home/qcrs/statebus/work/contest_evidence_closure_20260720.bundle
/home/qcrs/statebus/work/contest_evidence_closure_20260720_patches/
/home/qcrs/statebus/work/contest_evidence_closure_20260720_commit_series.txt
```

staging 序列只同步本轮代码、测试、fixtures、wrapper、freeze ledger 和报告；它显式排除了主 worktree 中 `00_implementation_and_experiment_execution_prompt_zh.md` 的既有 KV 研究段落、`docs/2511.20639v3.pdf` 和 `docs/planning/kv_hidden_state_transfer_design_20260720.md`。这组提交是可导入恢复物，不改变主仓库 `.git` 仍只读、主 worktree 仍 dirty 的事实，因此不把完成定义的最后一项改写为 PASS。

## 11. 最终 claim 边界

- matched text 是同一 harness 内的 L0，不是外部系统基线。
- embedding `StateRef` 不是 hidden state/KV。
- E1/E2 没有减少 LLM call。
- expected facts 是 Runtime 后外部评分。
- root + bwrap non-root 不是 production-grade sandbox。
- 本轮只覆盖 openEuler 单容器和有限离线分析域。
- 单次固定顺序时延只作描述，不声称稳定 superiority。

主报告：[contest_evidence_closure_final_report_20260720.md](../../reports/contest_evidence_closure_final_report_20260720.md)

证据索引：[final_v2_contest_evidence_index_20260720.md](../../reports/final_v2_contest_evidence_index_20260720.md)

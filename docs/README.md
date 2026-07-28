# StateBus Docs

更新时间：2026-07-28

这个目录现在按 `v2` clean-room 实现和 contest evidence 来组织。旧的 host-mainline / v1 过程文档已经归档；日常判断不要再从 6 月的 analysis/progress/review 文档进入。

## 当前入口

1. `../README.md`
   - 仓库入口、环境变量和常用命令。

2. `implementation/README.md`
   - 当前 v2 实现手册。按架构、Runtime、非文本状态、Logit Retry Gate、记忆、CodeAct、Studio、任务走读和恢复拆成短专题，并直接链接源码。

3. `start_here.md`
   - 当前 v2 开发、测试和 local+api 复跑入口。

4. `reference/题目.md`
   - 赛题原始要求。所有 claim 最终都要能回到这里。

5. `improvement/20_v2_comprehensive_truth_audit_20260706/00_executive_summary.md`
   - 当前 v2 truth audit 总入口。

6. `improvement/20_v2_comprehensive_truth_audit_20260706/code_truth_vs_experiment_issue_matrix_zh.md`
   - 代码事实、实验事实、问题严重级别和修复状态的主矩阵。

7. `improvement/20_v2_comprehensive_truth_audit_20260706/05_merged_issue_ledger.md`
   - 当前问题账本。后续修复和复跑结果应该回填这里。

8. `contracts/`
   - v2 合同文档：role contract、persistence profile、external fairness gate、bounded CodeAct demo。

9. `planning/statebus_v2_clean_room_rebuild_plan_20260625.md`
   - v2 clean-room 主规划历史。

10. `planning/statebus_v2_container_refactor_bootstrap_20260627.md`
   - v2 container / openEuler bootstrap 历史规划。

11. `reports/v2_*`
    - v2 历史报告。读取时必须用 truth audit 校准，不能单独当最新结论。

## 当前证据口径

- 当前实现主线是 `v2/`，控制面是 `UDS + typed Protobuf`。
- formal internal benchmark 是 25 cases / 5 families。
- formal compare 代码已改为 registry-backed full 25-case adapter，但 live local+api 复跑证据仍要以后续 artifact 为准。
- API latency 优势只能来自 serialized rerun，且必须看 `serialized_latency_superiority_claim_allowed=true`。
- non-text state 当前包括 embedding semantic state，以及 Executor 闭集候选概率形成的 `LogitStateRef`；后者只表示 candidate probabilities + `other_mass`，不能写成完整词表 logits、hidden state 或 KV cache transfer。
- Logit Retry Gate 的 `12/12` 属于独立受控挑战，不更新也不合并进正式 `95/95` 业务基线。
- hidden-state / KV cache transfer 只能写 Future Work / Engine-Local Prefix Reuse，不能写成已实现机制。
- openEuler 只能在 VM/container validation artifact 存在时 claim；不要用 host 或普通 container run 替代。
- flagship family stress 不能写 all-pass；当前修复方向是 family-level fail reasons 和 claim scope。

## 当前 artifact 规则

`improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/` 里保留的是审计证据，不是普通阅读材料。

保留原则：

- passing comprehensive artifact 保留。
- failure artifact 只有在定位具体 bug、transport issue、fairness gate 或 OOM/resource issue 时保留。
- dry-run、半截 rerun、重复失败包不应长期放进 docs；优先留在 `/home/qcrs/statebus/runs/`。
- 新增 artifact 必须能说明它支持哪个 claim、修复哪个 issue，或者为什么只是 diagnostic-only。

## 归档区

旧文档已移到：

- `archive/legacy_202606_host_mainline/analysis/`
- `archive/legacy_202606_host_mainline/progress/`
- `archive/legacy_202606_host_mainline/review/`
- `archive/legacy_202606_host_mainline/reivew_typo/`
- `archive/legacy_202606_host_mainline/reader_doc_blueprint/`
- `archive/legacy_202606_host_mainline/reader_guide/`
- `archive/legacy_202606_host_mainline/planning/`
- `archive/legacy_202606_host_mainline/reports/`

这些目录只用于追溯 6 月 host-mainline、v1/v3 pack、旧审计过程和 prompt 设计。它们不能覆盖当前 v2 truth audit。

## 顶层目录含义

- `contracts/`: 当前 v2 合同和边界。
- `implementation/`: 当前 v2 实现手册，按单一问题拆分的源码级说明与 Mermaid/ASCII 流程图。
- `improvement/`: 当前 truth audit、issue ledger、修复计划和精选 artifacts。
- `planning/`: 当前 v2 clean-room 规划、状态/证据/运行时合同。
- `reports/`: v2 evidence、API readout、container validation 和代码 review。
- `setup/`: host/container/local API 服务配置说明。
- `reference/`: 赛题原文和早期设计参考。
- `archive/`: 旧过程文档，不参与当前 claim 判断。

## 维护规则

- 新文档必须声明自己是 current source-of-truth、historical reference、diagnostic artifact，还是 draft。
- 不再把 prompt、handoff、新窗口交接稿放到 docs 顶层。
- 旧结论如果被 truth audit 覆盖，优先改入口索引，不要让多个“最新结论”并存。
- 对外 claim 必须指向具体代码路径、测试命令、JSON artifact 或 summary。

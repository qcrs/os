# Issue Ledger

审计日期：2026-07-06

## 结论

- P0：未发现当前代码中会直接造成现有 benchmark 假阳性、gold 泄漏、fairness gate 漏判或比赛复现必然失败的 P0。
- P1：发现并修复 2 个会影响证据复现和对外 claim 口径的高风险问题。
- P2：保留若干任务覆盖、benchmark 主路径和文档过时风险，建议下一轮继续收敛。

## P1 修复

| ID | 问题 | 风险 | 修复 | 证据 |
| --- | --- | --- | --- | --- |
| AUDIT-001 | full audit 脚本 socket path 只按 stage label hash，同一容器内并发/近并发同名 stage 有碰撞风险。 | benchmark 互相污染，导致复现失败或 artifact 混用。 | `short_socket_path()` hash 输入加入 `STATEBUS_RUN_ID`。 | `scripts/run_v2_full_container_audit_suite.sh:206` |
| AUDIT-002 | full audit summary 只记录 stage 成败，不解析 formal / compare / replay / fairness / flagship JSON 关键字段。 | 容易 cherry-pick 成功阶段，无法从 `summary.json` 快速审计 claim 自洽性。 | 在 summary Python 中解析 `key_metrics` 并写入 `summary.json` / `summary.md`。 | `scripts/run_v2_full_container_audit_suite.sh:411` |
| REPLAY-001 | `validated_replay_count` 容易被误读为“直接恢复旧答案”，而当前 validated replay 的主路径是同形状 contract 下的 downgraded reusable execution。 | 答辩 claim 过度，尤其跨 ticker / 跨 round 的 replay 可能被表述成 exact answer replay。 | 保留旧字段兼容，新增 `validated_downgraded_reuse_count` 与 `answer_restoration_replay_count`，并在 continuous summary / evidence pack / full audit parser 中透出。 | `v2/runtime/driver.py:1215`, `v2/benchmark/continuous_runner.py:713`, `scripts/run_v2_full_container_audit_suite.sh:483` |

## P2 / 剩余风险

| ID | 问题 | 当前判断 | 建议 |
| --- | --- | --- | --- |
| BENCH-001 | formal financial family 只有 8 case，`L3_reuse_gain=0`。 | formal 是 precision anchor，不足以支撑 broad reasoning 或 replay superiority。 | 新增更难的 formal task family，并将 continuous replay 作为单独 claim。 |
| BENCH-002 | compare 最新 fairness 证据只覆盖 dev fixed-answer external baseline，且 `api_task_ms_delta` 为正。 | 支持 token/prompt/control exposure 降低，不支持端到端速度胜利。 | 串行 API rerun 后再谈 latency；答辩避免速度 headline。 |
| STATE-001 | memfd + SCM_RIGHTS 有能力测试和 e2e 测试，但不是 formal/compare 主 benchmark 路径。 | 可作为 Medium/Weak 能力证据，不应宣称主路径依赖 memfd。 | 若要强 claim，把 memfd transport 接入正式 benchmark stage。 |
| SCRIPT-001 | full audit primary 阶段失败后 fallback 能力仍有限，不是每个重 benchmark 都有同等 fallback matrix。 | 失败会被记录，不会被吞掉；但自动恢复和对比能力不足。 | 把 fallback matrix 扩展到 formal / compare / replay heavy stages。 |
| DOC-001 | `final_v2_evidence_index_20260703.md`、`v2_experiment_summary_20260703.md` 等旧文档包含过时 strong claim。 | 容易误导答辩材料。 | 以 14、15、16 号 improvement 和最新 JSON artifact 为事实源，旧文档标注 historical。 |
| TASK-001 | `gridops_world` / `incident_diagnosis` 能证明连续状态迁移与多轮复用，但 formal financial 默认族仍偏窄。 | 赛题对齐成立但强度不均。 | 增加 offline financial-report / operating-metric 任务族和负控任务。 |

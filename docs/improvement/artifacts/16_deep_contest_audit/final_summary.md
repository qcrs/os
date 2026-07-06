# Final Summary

审计日期：2026-07-06

## 当前结论

StateBus v2 当前可以保守支撑比赛主张中的核心工程链路：typed Protobuf control plane、结构化多角色 handoff、SemanticStateRef 非文本状态承载、ExecutionArtifactRef 分离、shared_memory/mmap/workspace artifact 分层、continuous replay/downgraded reuse，以及 external pure-text fairness gate。

最重要的 claim 边界：

- Strong：formal quality floor、typed control plane、ref 类型边界、continuous replay collection、latest external fairness gate。
- Medium：non-text StateRef prompt saving，因为 stress benchmark 6 个 family 中 4 个 pass。
- Weak：memfd 主路径，因为当前是能力/e2e 测试证据，不是 formal/compare 主 benchmark。
- Unsupported：端到端速度胜利、openEuler 已验证、formal broad superiority、generic answer restoration replay。

## 本轮修复

1. `scripts/run_v2_full_container_audit_suite.sh`
   - socket hash 纳入 `STATEBUS_RUN_ID`，降低并发 stage socket 碰撞风险。
   - `summary.json` / `summary.md` 新增 `key_metrics`，自动解析 formal、compare、fairness、replay、flagship 关键指标。
2. `v2/runtime/driver.py`
   - 新增 `validated_downgraded_reuse_count`。
   - 新增 `answer_restoration_replay_count`。
3. `v2/benchmark/continuous_runner.py`
   - 在 layer evidence、round evidence、single-family summary、collection summary、admissibility summary 中透出新 replay 语义别名。
4. `tests/v2/test_continuous_runner.py`
   - 增加 regression assertions，覆盖新增指标。

## 验证结果

| 命令 | 结果 |
| --- | --- |
| `bash -n scripts/run_v2_full_container_audit_suite.sh` | pass |
| host `/usr/bin/python3 -m pytest -q` | fail，host 缺 `pytest`，不作为有效证据 |
| container targeted pre-existing set | pass，`74 passed in 21.55s` |
| container `tests/v2/test_continuous_runner.py tests/v2/test_replay.py` | pass，`19 passed in 320.16s` |
| container `tests/v2` | pass，`214 passed, 100 warnings in 371.83s` |
| container `runtime.smoke` | pass，text/protocol smoke ok，comparator artifact ok |
| container full repo pytest | pass，`509 passed, 101 warnings in 902.00s` |

## 最新证据路径

- Full audit: `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/summary.latest.json`
- Formal primary: `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/07_formal_primary/stdout.json`
- Continuous replay collection: `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/10_continuous_replay_collection_primary/stdout.json`
- Flagship non-text stress: `/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/15_flagship_ablation_primary/stdout.json`
- Latest fairness gate compare API: `/home/qcrs/statebus/runs/codex-raw-fairness-20260706/runtime/benchmark_reports/codex-raw-fairness-20260706-cold-start-compare-api.json`
- Latest fairness suite: `/home/qcrs/statebus/runs/codex-raw-fairness-20260706/runtime/benchmark_reports/codex-raw-fairness-20260706-cold-start-compare.json`

## 下一轮最值得做的 3 件事

1. 新增更难的 offline financial-report / operating-metric formal task family，并加入负控任务，降低 formal narrow 风险。
2. 把 memfd/subprocess transport 接入正式 benchmark stage，或者从公开材料中继续降级为 capability evidence。
3. 扩展 full audit fallback matrix，对 formal/compare/replay heavy stage 做 api+local、api+deterministic、deterministic+local、deterministic+deterministic 的统一 fallback 和 summary merge。

# Adaptive Mainline 与 Semantic State 容器验证报告（2026-07-20 收口）

## 结论

本轮实现和验证均以 `statebus-dev-qcrs` 的 openEuler 24.03 LTS-SP3 `embed` 容器为执行边界。执行器、Runtime validator、StatePool/semantic consumer、bwrap 和 benchmark 测试都在容器内运行；宿主机只负责容器编排、GPU 映射、日志重定向和读取结果。role model 通过既有 vLLM HTTP endpoint 提供推理，该 endpoint 不执行代码，也不承担验证职责。

Gate 1-7 已按计划收口：

- Gate 6 fresh adaptive formal：25/25 attempted、completed、verified；25/25 quality pass；system-safety、high-accuracy 和 formal-enhancement gate 全部通过；
- Gate 7 openEuler smoke：`516 passed, 100 warnings`，deterministic preflight `ok=true`；
- Gate 4 continuous：2 个正式 offline task family，共 10 轮；semantic state transfer 9，artifact reuse 13，validated replay 2；
- local Qwen embedding：`[4,1024]` binary matrix、16,384 bytes、不同 producer/consumer PID、shared-memory 数值消费和 owner release 全部可观测。

## 验证环境

- 分支：`feat/yzm-v2-migration`
- 容器：`statebus-dev-qcrs`
- 镜像：`statebus-dev-openeuler:24.03-lts-sp3-embed`
- OS：openEuler 24.03 LTS-SP3
- 容器项目根：`/workspace/statebus/project`
- 容器 StateBus 根：`/statebus`
- Python：3.11.6
- bwrap：0.8.0
- embedding：`Qwen3-Embedding-0.6B`，容器内 `cuda:0`
- formal role model：`qwen3-32b`，通过 `http://127.0.0.1:53334/v1`
- CodeAct 外层 harness：容器 root；生成代码实际在 bwrap 内 `UID/GID=65534:65534`

## 证据索引

所有路径均为宿主机挂载路径，动态命令在容器内执行。

| Gate | 结果 | 日志或摘要 |
|---|---|---|
| Gate 1 | composite PASS | `/home/qcrs/statebus/runs/adaptive_mainline_20260719/embed_target_validation_20260720/gate1_focused.log`、`gate1_replay_fix.log`、`gate6_terminal_quality_fix_expanded.log` |
| Gate 2 | `513 passed`（修复前基线） | `/home/qcrs/statebus/runs/adaptive_mainline_20260719/embed_target_validation_20260720/gate2_full_v2.log` |
| Gate 3 | deterministic formal 25/25 | `/home/qcrs/statebus/runs/adaptive_mainline_20260719/embed_target_validation_20260720/gate3_deterministic.log` |
| Gate 4 | 10 rounds + local Qwen process check | `/home/qcrs/statebus/runs/adaptive_mainline_20260719/embed_target_validation_20260720/gate4/runtime/benchmark_reports/statebus-v2-benchmark-continuous.json`、`gate4_continuous_local_embedding.log` |
| Gate 5 | bwrap/non-root PASS | `/home/qcrs/statebus/runs/adaptive_mainline_20260719/embed_target_validation_20260720/gate5_bwrap_readiness.log` |
| Gate 6 | fresh 25/25 PASS | `/home/qcrs/statebus/runs/adaptive_mainline_embed_gate6_fresh25_terminal_fix_20260720/adaptive_formal_compare_20260719_225756/summary.json` |
| Gate 7 | `516 passed`, preflight PASS | `/home/qcrs/statebus/runs/adaptive_mainline_20260719/embed_target_validation_20260720/gate7_openeuler_full_v2_terminal_fix.log` |

## Gate 1-5

### Gate 1：focused deterministic composite

初始 expanded focused run 为 `212 passed, 1 failed`，失败是旧 `continuous-incident` 断言与当前精简任务合同不一致，日志保留在 `gate1_focused.log`。Semantic State replay 修复随后在容器内 `11 passed`（`gate1_replay_fix.log`）；终态质量修复后的相关 expanded 集合为 `62 passed`。Gate 2 全量回归再确认当前 v2 合同没有回归，因此 Gate 1 按 composite evidence 关闭，没有隐藏初始失败。

### Gate 2：全部 v2 regression

修复终态质量判定前的完整容器回归为 `513 passed, 100 warnings in 770.32s`。最终代码变更后的完整复核见 Gate 7：`516 passed, 100 warnings in 742.54s`。

### Gate 3：deterministic formal

容器内 deterministic preflight 为 `ok=true`；formal registry 为 5 个 family、25 cases，L3 quality pass `25/25`，`execution_scope=full`。日志中的 benchmark JSON 同时记录 semantic state 和 protocol ladder 指标。

### Gate 4：continuous 与真实 local embedding

Gate 4 report：

- family：`formal_financial_reports_v1`、`formal_operating_metrics_v1`；
- rounds：`5 + 5 = 10`；两组均成功；
- `L2_semantic_state_transfer_count=9`；
- `L3_artifact_reuse_count=13`；`L3_history_step_reduction_count=7`；
- `validated_replay_count=2`，目标轮次 `2/2`；`exact_replay_count=0`；
- 实际 semantic state backend 只有 `shared_memory`；
- 两个 L3 family report 各执行 5 次 `hybrid_memory_query`，compatibility/replay gate 在融合后生效。

真实 local embedding 日志记录：

```text
shape=[4, 1024]
size_bytes=16384
storage_kind=shared_memory
producer_pid=43533
consumer_pid=45180
query_row_reused_without_encode=true
selected_row_indices=[1, 2]
owner_release_verified=true
```

这条路径使用容器内 Qwen3-Embedding-0.6B，不回退到 deterministic encoder；consumer 从 registry/ref 打开矩阵，执行数值 selection，再决定局部 evidence hydration。

### Gate 5：bwrap readiness

容器 readiness 检查为 `actual_backend=bwrap`、`sandbox_uid=65534`、`sandbox_gid=65534`，无 resource/none fallback。外层容器仍以 root 建 namespace，因此这里不作 production-grade sandbox 声明。

## Gate 6：fresh 25-case adaptive formal

Fresh summary：

| 指标 | 结果 |
|---|---:|
| selected / attempted / completed / verified | 25 / 25 / 25 / 25 |
| quality pass | 25/25（1.0） |
| formal families | 5 |
| CodeAct verified | 17 |
| DSL verified | 8 |
| Planner hard rejection | 0 |
| Planner schema normalization | 25 |
| CodeAct quality rejection/repair | 0 / 0 |
| CodeAct runtime repair | 0（普通 CodeAct repair count 1） |
| DSL quality rejection/repair | 0 / 0 |
| model/runtime/sandbox fallback | 0 / 0 / 0 |
| bwrap execution records | 17，全部 non-root |
| system-safety / high-accuracy / formal-enhancement | pass / pass / pass |

逐例 summary 还确认：25 个终态 quality report 均 `verified=true`，终态 report 的 `output_artifact_hash` 与最终 `ExecutionArtifactRef.blob_hash` 逐例一致；历史 quality report 没有被错误地当作终态验收依据。

### 终态质量判定修复

`formal-anomaly-003` 暴露了一个聚合 bug：CodeAct 质量修复会保留“首次拒绝报告”和“修复后通过报告”，旧逻辑对完整历史做 `all(report.verified)`，导致已经完成的 case 被误报为 `runtime_bug` 并触发 system gate。

原始失败摘要保留在 `/home/qcrs/statebus/runs/adaptive_mainline_embed_gate6_20260720/adaptive_formal_compare_20260719_215820/adaptive/formal-anomaly-003/summary.json`，用于对照修复前后的判定。

当前实现位于 [`adaptive_formal_mainline.py`](/home/qcrs/statebus/project/v2/benchmark/adaptive_formal_mainline.py:146)，按最终执行制品哈希从完整审计历史中筛选 `terminal_quality_reports`；通过条件、system gate 和失败分类都只使用终态报告，历史拒绝报告和 repair counter 继续保留。回归覆盖位于 [`test_adaptive_formal_compare.py`](/home/qcrs/statebus/project/tests/v2/test_adaptive_formal_compare.py:802)。

定向回归结果：

- `47 passed in 6.17s`；
- expanded adaptive/dispatcher/mainline 集合 `62 passed in 8.19s`；
- 单独真实回放 `formal-anomaly-003`：1/1 completed、verified、system-safety pass；
- fresh 25-case：最终无失败分类。

## Gate 7：openEuler 交付 smoke

同一 `statebus-dev-openeuler:24.03-lts-sp3-embed` 容器内按精确命令顺序执行：

```text
cat /etc/os-release
python3 -m pytest -q tests/v2
python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode deterministic --embedding-mode deterministic
```

结果：`516 passed, 100 warnings in 742.54s (0:12:22)`，随后 preflight JSON `ok=true`。因此可以声明当前 openEuler 单容器路径已验证；不能把它扩展为 openEuler VM 或跨机器兼容性声明。

## 实现边界与声明

### 可以声明

- Adaptive formal 使用产品 Runtime 主线，包含 Planner/Retriever/Executor/Summarizer、typed UDS、StateRef、workspace、artifact 和 cleanup；
- dense semantic state 是 binary little-endian float32 matrix，真实跨进程 consumer 数值使用并影响 selected IDs/hydration；
- MemoryProxy/continuous runner 有 hybrid query、compatibility/replay gate 和可观察 reuse 指标；
- formal Executor output 在 Runtime 内基于授权输入和公开 operation contract 独立重算；expected facts 只在 Runtime 完成后作为 external quality layer 使用；
- 当前正式 CodeAct 生成代码只在 bwrap 非 root 身份执行。

### 不能声明

- 不能把外层 root + bwrap 路径称为 production-grade sandbox；
- 不能声称已完成 openEuler VM posterior validation、跨机交付或所有平台兼容；
- 不能把 `exact_replay`、`answer_restoration_replay` 或 vLLM prefix counter 当作已观测机制，本轮均为 0/不可用；
- 不能把 history-backed reuse 全部称为 validated replay；operating-metrics family 仍是 history-backed-only；
- 不能声称 KV cache/hidden-state tensor handoff，边界仍是 `Engine-Local Prefix Reuse` / Future Work。

## Future Work

- 在 openEuler VM 上重跑 bootstrap、full v2、formal all-correct 和 artifact integrity；
- 将 outer-container root 与 bwrap namespace 创建收敛到最小权限交付方案；
- 为 operating-metrics family 补 replay-admissible workload，再讨论 suite 级 replay headline；
- 为 mmap/CAS 长生命周期对象补正式 workload backend coverage；
- `KV cache / hidden-state handoff` 继续只标注为 `Engine-Local Prefix Reuse` / Future Work。

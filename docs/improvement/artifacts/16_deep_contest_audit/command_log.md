# Command Log

审计日期：2026-07-06

## 事实发现命令

```bash
git status --short --branch
```

结果：通过。当前分支 `feat/statebus-v2-container-runtime`；起始状态只有 `scripts/run_v2_full_container_audit_suite.sh` 被前序审计修改，之后本轮新增代码/文档修改。

```bash
git log --oneline --decorate -n 30
```

结果：通过。起点 HEAD：`be74494 Harden external fairness gate raw payload checks`。

```bash
find docs -maxdepth 3 -type f -printf '%T@ %p\n' | sort -nr | sed -n '1,180p'
find docs/improvement -maxdepth 3 -type f -printf '%T@ %p\n' | sort -nr | sed -n '1,160p'
find v2 -maxdepth 4 -type f | sort
find tests/v2 -maxdepth 2 -type f | sort
find scripts -maxdepth 2 -type f | sort
```

结果：通过。用于建立当前阅读清单、实现范围和历史审计链路。

## JSON evidence queries

```bash
jq '{stage_count, failed_stage_count, failed_stages}' /home/qcrs/statebus/runs/v2-full-audit-20260705_213331/summary.latest.json
```

结果：`stage_count=16`、`failed_stage_count=0`、`failed_stages=[]`。

```bash
jq '{waterfall_metrics, comparison_summary}' /home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/07_formal_primary/stdout.json
```

结果：formal primary 8 case 全部质量通过；`L2_semantic_state_transfer_count=8`，`L3_reuse_gain=0`。

```bash
jq '{collection_summary}' /home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/10_continuous_replay_collection_primary/stdout.json
```

结果：3 family / 30 round；20 target replay round 全部 observed；`validated_replay_count=17`、`exact_replay_count=3`。

```bash
jq '{fairness_manifest, comparison_summary}' /home/qcrs/statebus/runs/codex-raw-fairness-20260706/runtime/benchmark_reports/codex-raw-fairness-20260706-cold-start-compare-api.json
```

结果：`pass_hard_gate=true`、fairness coverage true、failed case/check count 均为 0。

## 验证命令

```bash
bash -n scripts/run_v2_full_container_audit_suite.sh
```

结果：通过。

```bash
/usr/bin/python3 -m pytest -q
```

结果：宿主机失败，原因是 host `/usr/bin/python3` 没有安装 pytest：`No module named pytest`。不作为有效测试证据。

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc 'source /usr/local/bin/activate_statebus_container.sh && cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_preflight_and_live_runner.py tests/v2/test_memory_store.py tests/v2/test_fixed_answer_and_external_baseline.py tests/v2/test_compare_diagnostics.py tests/v2/test_replay.py'
```

结果：通过，`74 passed in 21.55s`。

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc 'source /usr/local/bin/activate_statebus_container.sh && cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_continuous_runner.py tests/v2/test_replay.py'
```

结果：通过，`19 passed in 320.16s (0:05:20)`。

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc 'source /usr/local/bin/activate_statebus_container.sh && cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2'
```

结果：通过，`214 passed, 100 warnings in 371.83s (0:06:11)`。warnings 主要来自 generated protobuf descriptor deprecation。

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc 'source /usr/local/bin/activate_statebus_container.sh && cd /workspace/statebus/project && /usr/bin/python3 -m runtime.smoke'
```

结果：通过。

- `statebus smoke ok: mode=text memory_hits=0.0 messages=292.0 control_bytes=243456.0 task_ms=5371.67`
- `statebus smoke ok: mode=protocol memory_hits=0.0 messages=292.0 control_bytes=215901.0 task_ms=5160.97`
- `statebus comparator artifact ok: external_claim_surface=formal_ready api_repeat1_ready=True`

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc 'source /usr/local/bin/activate_statebus_container.sh && cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q'
```

结果：第一次运行的输出会话被中断，后台 pytest 仍运行但 stdout/exit code 不可审计；已终止该丢失会话后重跑同一命令。

重跑结果：通过，`509 passed, 101 warnings in 902.00s (0:15:02)`。warnings 主要来自 generated protobuf descriptor deprecation，另有 `langgraph` pending deprecation warning。

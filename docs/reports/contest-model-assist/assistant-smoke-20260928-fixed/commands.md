# Contest model-assist smoke run

本目录对应 candidate worktree 的 smoke 运行 `assistant-smoke-20260928-fixed`。

## 实际执行命令

```bash
cd /home/qcrs/statebus/work/os-contest-dsl-model-assist-integration
scripts/experiments/contest_model_assist/run_smoke_and_formal.sh \
  --mode smoke --phase both --yes \
  --run-id assistant-smoke-20260928-fixed
```

脚本复用一次 standard APC-on vLLM 完成 F01 Logit/APC，切换一次 candidate APC-off
KV vLLM 完成 F01 replay/continuation，然后停止 KV 并恢复 standard。KV token 内容没有
写入报告。

## 不重新执行的汇总命令

```bash
cd /home/qcrs/statebus/work/os-contest-dsl-model-assist-integration
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  /home/qcrs/statebus/conda-envs/statebus_host/bin/python \
  scripts/experiments/contest_model_assist/run_minimal_probe.py \
  --summarize /home/qcrs/statebus/os/docs/reports/contest-model-assist/assistant-smoke-20260928-fixed/standard-finance
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  /home/qcrs/statebus/conda-envs/statebus_host/bin/python \
  scripts/experiments/contest_model_assist/run_minimal_probe.py \
  --summarize /home/qcrs/statebus/os/docs/reports/contest-model-assist/assistant-smoke-20260928-fixed/kv-finance
```

## 后续 formal 入口

仅在 smoke 结果审阅并取得新的维护窗口后执行：

```bash
cd /home/qcrs/statebus/work/os-contest-dsl-model-assist-integration
scripts/experiments/contest_model_assist/run_smoke_and_formal.sh \
  --mode formal --phase both --family all --yes
```

本 smoke 没有执行 formal 八位置、12 轮主链或完整 benchmark。

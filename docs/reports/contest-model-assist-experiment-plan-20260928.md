# Contest model-assist smoke and formal experiment plan

日期：2026-09-28  
状态：已完成 candidate wiring/live readiness；本文件定义下一轮 smoke 与正式小矩阵的可执行入口，未在本文件生成正式实验结论。

## 目的与边界

本实验只观察比赛 DSL provider boundary 上的三种旁路：

1. `logit`：复用 standard vLLM 的同一次 Executor 请求，读取真实 `top_logprobs`，不增加 generation。
2. `apc`：仍复用 standard vLLM，保持 Automatic Prefix Caching 开启，只改变公共前缀布局并采集 task-window counters。
3. `kv_replay` / `kv_continuation`：切换到独立的 APC-off KV vLLM 服务，验证 producer/capture、consumer/load/forward 和 release。

Memory、CodeAct fallback、主链 12 轮和正式 benchmark 不属于本入口。

## 批次策略

Logit 与 APC 共用一次 standard 服务加载；二者不需要重启 vLLM。KV 是另一种 vLLM 启动模式，必须在维护窗口中停止 standard、启动 KV，完成 KV batch 后由脚本自动停止 KV 并恢复 formal standard。

| 模式 | 默认位置 | 服务 | 目的 |
|---|---|---|---|
| `smoke` | F01 的 `logit -> apc`，再 `kv_replay -> kv_continuation` | standard 一次、KV 一次 | 每次代码/配置变更后的最小真实检查 |
| `formal` | F01/O01 的固定 8 个位置 | standard 一次、KV 一次 | 45 号设计中的有限矩阵，不是 12 轮主链 |

脚本支持单独运行 `--phase standard` 或 `--phase kv`。KV/both 必须显式传 `--yes`，表示操作者已经确认维护窗口和 GPU 使用权。

## 执行入口

代码位于 candidate worktree：

```text
/home/qcrs/statebus/work/os-contest-dsl-model-assist-integration/
  scripts/experiments/contest_model_assist/run_smoke_and_formal.sh
```

先做无副作用检查：

```bash
cd /home/qcrs/statebus/work/os-contest-dsl-model-assist-integration
bash -n scripts/experiments/contest_model_assist/run_smoke_and_formal.sh
scripts/experiments/contest_model_assist/run_smoke_and_formal.sh \
  --mode smoke --phase both --dry-run --run-id design-smoke-check
```

确认维护窗口后运行 smoke：

```bash
scripts/experiments/contest_model_assist/run_smoke_and_formal.sh \
  --mode smoke --phase both --yes
```

smoke 通过后运行正式有限矩阵：

```bash
scripts/experiments/contest_model_assist/run_smoke_and_formal.sh \
  --mode formal --phase both --family all --yes
```

只跑 standard 或只跑 KV 时：

```bash
scripts/experiments/contest_model_assist/run_smoke_and_formal.sh \
  --mode formal --phase standard --family all
scripts/experiments/contest_model_assist/run_smoke_and_formal.sh \
  --mode formal --phase kv --family all --yes
```

`--phase kv` 要求进入前 standard 已健康；退出时无论 probe 成功或失败，脚本都会执行 KV stop、standard start、health/status 检查。服务切换失败时退出码非零，不能把结果标成恢复成功。

## 输出与判读

每次运行使用新的 run id，结果保存在：

```text
/home/qcrs/statebus/os/docs/reports/contest-model-assist/<run-id>/
  execution-manifest.env
  commands.md
  run-status.env
  standard-<family>/
  kv-<family>/
  vllm.env.kv.runtime
```

每个 probe 目录保留 `plan.json`、`task_results.json`、`summary.json`、`summary.md` 以及 slot 原始 evidence。KV 重点检查 `engine-local-kv.json` 中的 `capture_count`、`load_count`、实际 KV bytes、`forward_proof_hash`、release receipts 和服务 registry 回收。APC 重点检查同一 task window 的 `delta_valid`、query/hit token counters 和污染判定。Logit 只报告同次请求的 token-proxy 可用性与 validator 结果。

不要将 `logical_prompt_tokens` 当作实际重算 tokens；不要把 HTTP body bytes 当作 Agent 通信节省；不要从 smoke 或 8 个位置推导统计显著性、长链稳定性或赛题收益。

## 现有 readiness 依据

- Standard F01 Logit/APC 与 KV F01 replay/continuation 已在 candidate 上通过最小 live readiness。
- KV 的真实证据保留在 `/home/qcrs/statebus/runs/contest-model-assist-live-kv-20260928-3/`。
- Candidate/container source、离线测试和服务恢复证据保留在 candidate 的 `preflight/`。
- formal `/home/qcrs/statebus/os` 仅接收本报告和后续实验产物，不表示 candidate 已合并为正式主链。

## 已完成 smoke 记录

本轮已实际执行 candidate smoke：`assistant-smoke-20260928-fixed`。standard F01 的
`logit` 与 `apc` 均为 `success`；KV F01 的 `kv_replay` 与 `kv_continuation` 均为
`success`。continuation 审计为 `capture_count=2`、`load_count=1`，存在非空
`forward_proof_hash`，producer 和 consumer handle 均已 release。脚本退出后再次用
standard env 检查，`/health=200`、`/v1/models=200`，manager status 为运行中。

原始产物位于：
`/home/qcrs/statebus/os/docs/reports/contest-model-assist/assistant-smoke-20260928-fixed/`。
该记录只证明本 candidate smoke 的业务和机制链路可执行，不是性能收益、统计结论或
formal 八位置结果；formal 仍须按 48 号 Prompt 在单独维护窗口执行。

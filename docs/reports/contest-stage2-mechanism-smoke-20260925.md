# Contest Stage 2 机制实验实现与 Live Smoke 报告

日期：2026-09-25

后续状态：s1/null 公共提示已修复，F06/O06 已完成真实验证。最新结论与剩余缺口见 [修复与后续执行报告](contest-stage2-repair-and-next-steps-20260925.md)；以下保留原批次结果。

本报告记录 `36-CONTEST-FINAL-EXPERIMENT-STAGE2-MECHANISM-DESIGN-AND-RUN-PROMPT-20260925.md` 要求的 Stage 2 runner、离线合同检查和最小 GPU smoke。此次只运行 bounded smoke，没有启动 Stage 2 formal campaign，也没有启动 Stage 3 的 40 次主实验。

## 结论

Stage 2 入口已经可运行，且 live smoke 证明了 Memory F01/F02 配对、真实 Qwen3-32B provider 请求、真实 GPU Embedding、StateBus interpreter 和 openEuler workspace-root 容器链路可以执行。此次 smoke 不能放行 formal Stage 2 或 Stage 3：semantic-state `s1/on` 在 Executor CodeAct 输出质量门失败，通信仍只有 Stage 1 callback 诊断，跨 Agent Memory 没有闭合；因此 `formal_stage2_ready=false`、`stage3_allowed=false`。

## 当前实现

新增或修改的实现位于 `os/`：

- `statebus/benchmark/contest_stage2.py`：27 个冻结 slot 的机制计划（Memory 12、state 6、communication 4、CodeAct candidate 4、cross-agent 1），offline/live smoke、manifest、配置、任务计划、raw rows、telemetry、acceptance、phase summary 和 failures。
- `scripts/run_contest_measurement_stages.sh`：Stage 2 入口、`--mechanism`、`--smoke`、`--offline`、`--stop-on-failure`、Stage 1 evidence root 传播和新 output root 保护。
- `tests/measurement/test_contest_stage2.py`：计划数量、选择边界、离线产物和 public projection 检查。

本次修复了通信诊断读取固定历史目录的问题；`_run_communication_smoke()` 现在使用 CLI 传入的 `stage1_root`，不会把历史路径硬编码进 runner。随后又补上了 `--stop-on-failure` 的真实顺序调度：发生 `failed/environment_fail` 后，后续已选机制标为 `not_started`，预定义的 `blocked/not_applicable` 不会被误当作 runner 崩溃。`source_digest()` 也已收敛到 `statebus/`、`scripts/`、`deploy/`，不会把 `runs/` 历史产物混入 source identity。live component 覆盖 offline component 时现在保留嵌套的 `offline_contract`，raw ledger 用 `evidence_scope` 区分两类证据，避免 carrier/contract 行被覆盖。

## 证据分类

- **Architecture truth**：当前 `os/statebus/` 的 Runtime、Memory、semantic-state、CodeAct、validator 和 receipt 实现；Stage 2 runner 只编排和投影这些 authority，不替代它们。
- **Historical truth**：`/home/qcrs/statebus/os/runs/contest-stage1-history-fix-20260925b/` 的 Stage 1 acceptance 和 summary；三批 acceptance 机器准入通过，但 `formal_headline_eligible=false`、`semantic_review_required=true`。
- **This-run runtime truth**：`/home/qcrs/statebus/os/runs/contest-stage2-live-smoke-20260925a/` 及其 `preflight.json`、`acceptance.json`、`state/.../summary.json` 和 Memory task outputs。

当前 checkout 的实际 branch 为 `contest-core-repair-20260921_000126`。工作树原有其他修改均保留，未执行 reset/clean/switch/commit/push。

## 命令与环境

执行命令：

```bash
scripts/run_contest_measurement_stages.sh \
  --stage 2 --smoke --mechanism all \
  --stage1-root /home/qcrs/statebus/os/runs/contest-stage1-history-fix-20260925b \
  --profile qwen3-32b-gpu2-u050 \
  --embedding-gpu 1 \
  --container-name statebus-runtime \
  --runtime-python /home/qcrs/statebus/conda-envs/statebus_host/bin/python \
  --run-root /home/qcrs/statebus/os/runs/contest-stage2-live-smoke-20260925a \
  --stop-on-failure
```

预检事实：

- vLLM served model：`qwen3-32b`；health probe 通过；服务复用 physical GPU 2，未停止或重启其他进程。
- 容器：`statebus-runtime`，镜像 `statebus-dev-openeuler:24.03-lts-sp3-embed`，workspace-root mount 到 `/workspace/statebus/os`。
- Python：`/home/qcrs/statebus/conda-envs/statebus_host/bin/python`。
- Embedding：`/statebus/models/Qwen3-Embedding-0.6B`，容器内 `cuda:0`，physical GPU 1 UUID `GPU-a53fa601-8471-d782-2971-46e5a8e5d328`，实际 encode 维度 1024。
- preflight probe 明确标记为一次 embedding 检查，不计入性能样本。

## Smoke 结果

产物根目录：`/home/qcrs/statebus/os/runs/contest-stage2-live-smoke-20260925a/`

- Memory：`passed`。`SB-NO-MEMORY` 与 `validated_replay` 的 F01/F02 共 4 次真实执行全部完成。F02 的 replay 变体记录 `provider executor=0`，provider request 从 5 降为 4；这是本次配对观察，不是链级 E2E 优势结论。F06、O01/O02/O06 未启动并保留在 `not_started`。
- State：`failed`。`semantic-holdout-s1/off` 和 `consumer_off` 完成；`s1/on` 真实记录了 publish=2、transfer=2、consume=2、downstream effect=`changed`，但 Executor CodeAct 初次生成和一次 bounded repair 均产生 declared string 字段为 `null`，质量门报 `output_type:*`，该 variant `runtime_completed=false`。这是模型输出质量失败，不是把状态生命周期伪装成成功的理由。
- Communication：`diagnostic_only`。读取 Stage 1 F01 callback 观察（3 条 source rows），但当前没有 matched task-level text/typed receiver，因此不报告通信因果差异。
- CodeAct：`not_applicable`。当前没有已验证的共同合法 off 路径，不制造 on/off 正确率对照。
- Cross-agent Memory：`blocked`。当前没有 `source_agent != consumer_agent` 且同时具备 MemoryRef、Grant、消费回执、当前输入重算和 source/Artifact 链的真实 caller。
- Public projection：`passed`，manifest/task projection 没有泄露 `expected` gold 字段。

Acceptance 摘要：

```json
{
  "run_mode": "live_smoke",
  "ok": false,
  "smoke_passed": false,
  "formal_stage2_ready": false,
  "stage3_allowed": false,
  "semantic_review_required": true
}
```

## 验证

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /home/qcrs/statebus/conda-envs/statebus_host/bin/python -m pytest -q tests/measurement/test_contest_stage2.py`：5 passed。新增测试覆盖 stop-on-failure、source digest 忽略 generated runs，以及 live/offline row ledger 不丢失。
- 离线 Stage 2 smoke 已通过合同层检查，且产物合同完整。
- 相关 measurement targeted suite：80 passed。
- 真实 live smoke 产物包含 `manifest.json`、`effective-config.json`、`preflight.json`、`source-digest.txt`、`task-plan.json`、`raw_rows.json`、`telemetry.json`、`acceptance.json`、`phase-summary.json`、`failures.json` 和 `results.json`。

## 用户后续命令（当前不执行）

只有在本报告列出的失败和证据缺口闭合后，才由用户决定运行：

```bash
scripts/run_contest_measurement_stages.sh \
  --stage 2 --mechanism all \
  --stage1-root /home/qcrs/statebus/os/runs/contest-stage1-history-fix-20260925b \
  --profile qwen3-32b-gpu2-u050 \
  --embedding-gpu 1 \
  --container-name statebus-runtime \
  --runtime-python /home/qcrs/statebus/conda-envs/statebus_host/bin/python \
  --stop-on-failure
```

Stage 3 仍需单独满足 Stage 2 gate，并由用户另行授权。当前 checkout 的入口会明确拒绝 Stage 3（正式 40-task runner 尚未实现），因此本次不提供一个看似可执行的 Stage 3 命令，也没有启动任何 Stage 3 任务。

## 后续准入判断

当前不建议运行正式 Stage 2 campaign 或 Stage 3。下一步应先处理并复验 `semantic-holdout-s1/on` 的 CodeAct quality failure，随后补齐 matched task-level communication receiver 和 cross-agent Memory caller；只有这些证据闭合、三类正式 taskpack/scorer 冻结、失败分母和来源账本保持可复核后，才重新评估 Stage 2 formal readiness。此次 smoke 的失败、blocked 和未启动 slot 都应保留，不应删行或补零。


注：live smoke 目录是在 stop-on-failure、source-digest 收敛和 offline row ledger 补丁前创建的；三项补丁随后通过 targeted tests 验证，未改变已完成 Memory/State task 的执行逻辑。

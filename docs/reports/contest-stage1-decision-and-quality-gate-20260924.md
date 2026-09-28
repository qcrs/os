# Contest Stage 1 Decision and Quality Gate

日期：2026-09-24

后续更新：本文保留此前决策和 CPU 命令作为历史记录。当前 GPU 解释器、阶段门与运行命令见
[GPU and admission repair](contest-stages-gpu-and-admission-fix-20260924.md)，不要混合 CPU/GPU 批次成绩。

## 结论

Stage1 值得继续，但不应基于现有开发批次直接扩成正式 40 次矩阵。当前最强、且可以诚实展示的优势是：

- `SB-FULL` 的 `F02/O02` 已观察到合法 `validated_replay`：兼容性、授权、消费和当前输入重新计算均有证据；复用路径跳过了 Executor 生成，实际 Executor provider request 为 0。
- 非文本状态已经完成跨进程的真实生命周期验证：状态对象有 schema/hash/消费记录，发布与回收字节可审计；这不是 KV-cache 或 hidden-state 传输。
- 新输入确实改变了输入规模和输出，旧答案不能通过独立 scorer；失败、repair、首次建库成本保留在分母中。

当前不能宣称：

- 整体 E2E 加速或通信节省。现有 `SB-FULL` 运营链总耗时高于 `P-TEXT`，且两侧不是同一完整 wire 计量边界。
- 稳定的 4/4 或 10 轮质量。最新 `P-TEXT` 4/4 是独立开发批次，不是冻结成绩；当前只覆盖 F01/F02/O01/O02。
- 已满足赛题完整要求。尚缺 3 类业务任务的完整覆盖、跨 Agent Memory 复用、10 轮连续稳定运行、完整结构化控制面与同边界通信对照。

因此本轮停止条件是：完成共同报告质量门、加入可审计的 `SB-NO-MEMORY` 开发对照入口、通过离线定向验证并交付下一轮命令；不启动正式扩量。

## 本轮修复

`statebus/benchmark/contest_stage1_report.py` 增加 `stage1-report-v2-extractive-context` 合同：

- 每个实体必须引用当前发布文件的真实 `filename#section`；
- 报告正文必须包含该实体当前 note/event 的完整上下文句子（保留 uncertainty qualifier）；只放入 `uncertainty_note` 不再算通过；
- 错实体、旧批次上下文、标题/通用 scope 引用都会被拒绝；typed 模式还必须把该文本绑定到同一 evidence item；
- 这是 extractive coverage gate，不冒充通用自然语言 entailment 或因果判断。

SB 与 P-TEXT 共用同一 `report_sources` 和 validator。报告不读取 gold 数值，数值仍由 Runtime 重算和独立 scorer 检验。

`contest_stage1.py` 新增 `--sb-memory-policy {none,validated_replay}`：

- 默认 `validated_replay` 保持既有 Stage1 smoke 语义；
- `none` 生成明确标识的 `SB-NO-MEMORY` 链，要求真实 Executor model role，不把 Memory 关闭伪装成 P-TEXT；
- 两种配置的链目录、history、memory root 和 ledger 独立；P-TEXT 始终 `memory_policy=none`；
- 每个结果写入 Memory variant、报告合同版本和 `semantic_review_required=true`，不把机械门当成人类语义审查。

## 验证

- `tests/measurement/test_contest_stage1.py`：`24 passed`；覆盖发布来源绑定、当前实体上下文、uncertainty-only 负控、旧来源/错实体负控、SB/P-TEXT 共用门、Memory variant 接线和失败分母。
- `python -m compileall`：Stage1 runner/report/text/test 通过。
- `git diff --check`：通过。
- dry-run 已确认真实 role config、`SB-NO-MEMORY` 计划标签、Memory policy 和预算均会落盘；本轮未启动模型、容器或正式矩阵。

## 下一轮最小实验

先做同一数据边界、同一业务链的 `SB-FULL` 与 `SB-NO-MEMORY` 配对，至少覆盖 `F01→F02` 和 `O01→O02`，每个配置使用全新 output root。记录：首次建库、Memory lookup/admission/consumption、Executor provider requests、当前输入重算、report repair、E2E 和完整失败成本。只有在两配置都通过质量门后，才值得扩展更多轮次。

建议由用户在健康预检后执行，命令如下（不会覆盖历史目录）：

```bash
cd /home/qcrs/statebus/os
source ./deploy/activate_statebus_local_vllm_profile.sh qwen3-32b-gpu2-u050
export STATEBUS_VLLM_ENV_FILE=/home/qcrs/statebus/os/deploy/vllm.env.gpu2-32b-u050
RUN_NAME="stage1-sb-no-memory-$(date +%Y%m%d_%H%M%S)"
scripts/run_g6b2_os_container.sh exec /usr/bin/python3 \
  -m statebus.benchmark.contest_stage1 \
  --output-root "/workspace/statebus/os/runs/$RUN_NAME" \
  --profile SB-FULL --family all --sb-memory-policy none \
  --embedding-device cpu --dry-run
scripts/run_g6b2_os_container.sh exec /usr/bin/python3 \
  -m statebus.benchmark.contest_stage1 \
  --output-root "/workspace/statebus/os/runs/$RUN_NAME" \
  --profile SB-FULL --family all --sb-memory-policy none \
  --embedding-device cpu
jq '{planned_count,passed_count,report_contract_version,semantic_review_required,ledger}' \
  "runs/$RUN_NAME/summary.json"
```

然后用另一个全新目录运行同边界的默认 `SB-FULL`（`validated_replay`），不要复用上一个目录：

```bash
RUN_NAME="stage1-sb-full-$(date +%Y%m%d_%H%M%S)"
scripts/run_g6b2_os_container.sh exec /usr/bin/python3 \
  -m statebus.benchmark.contest_stage1 \
  --output-root "/workspace/statebus/os/runs/$RUN_NAME" \
  --profile SB-FULL --family all --sb-memory-policy validated_replay \
  --embedding-device cpu --dry-run
scripts/run_g6b2_os_container.sh exec /usr/bin/python3 \
  -m statebus.benchmark.contest_stage1 \
  --output-root "/workspace/statebus/os/runs/$RUN_NAME" \
  --profile SB-FULL --family all --sb-memory-policy validated_replay \
  --embedding-device cpu
jq '{planned_count,passed_count,report_contract_version,semantic_review_required,ledger}' \
  "runs/$RUN_NAME/summary.json"
```

先不要把这次结果和 `live-v3/live-v5-text` 拼成一个成绩。准入条件是：新批次四项均通过独立 scorer、报告质量门无错误、所有任务有终态且 provider usage 口径完整或明确标记缺失。停止条件是任一任务出现未解释的授权/来源越界、质量门回退、无终态账本、或出现依赖旧答案的输入；此时修复根因后再决定是否继续。

正式扩量的前置条件仍是：补齐同边界通信/结构化协议测量、跨 Agent Memory 复用、至少 10 轮连续链，以及完整 taskpack/scorer；这些缺口不能通过增加重复 smoke 次数解决。

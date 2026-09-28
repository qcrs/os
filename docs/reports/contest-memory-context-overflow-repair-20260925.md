# Memory 上下文超限修复与验证（2026-09-25）

本次是公共模型输入投影缺陷。修复后，在原有 Qwen3-32B / 8192 context / Executor 2200 max_tokens 和现有 openEuler 容器上，携带历史 Memory 的 F06、O06 两次验证均通过。没有扩大上下文、修改模型配置、放宽 scorer、按任务 ID 特判或重新生成旧批次结果。

## 失败原因

原批次：`runs/contest-stage2-memory-20260925_204828`。

12 个计划槽位中启动 9 个：Memory none 的六项通过；validated_replay 的 F01/F02 通过，F06 失败；O01/O02/O06 尚未启动。此前只有 Memory-off 的 F06/O06 验证，遗漏了携带历史记忆切换 schema 的边界。

F06 的真实异常是 HTTP 400：输入 8685 tokens + 预留输出 2200 = 10885 > 8192。请求尚未生成代码，不是 bwrap、GPU 显存或计算正确率失败。兼容门已将旧方法正确降为 assist；但 CodeAct prompt 直接序列化完整 Runtime Memory payload，将相同旧源码重复两次，并附加大量路径、hash 和校验回执。同款 tokenizer 复核旧输入为 8685 tokens，Memory JSON 部分为 4503 tokens。

## 修复

- `statebus/runtime/memory_projection.py`：增加供模型读取的显式字段投影，保留 Memory 身份、摘要、兼容判定和执行方法；相同方法按实际内容去重，用 ref 引用已出现的方法。完整 Memory、授权与回执继续留在 Runtime，未经修改。
- `statebus/runtime/llm_codeact.py`：公共 CodeAct prompt 使用上述投影，明确旧方法不能覆盖当前任务合同。
- `statebus/benchmark/adaptive_formal_mainline.py`：DSL 调用使用同一投影；总结只携带摘要和判定；CodeAct repair 保留当前待修代码，不再重复历史源码。
- `statebus/benchmark/contest_stage1.py`、`contest_stage2.py` 与 shell 入口：将具体任务的异常、variant、日志路径逐层传到 failures.json，并在失败时打印到终端。

增大模型上下文可以暂时容纳旧请求，但不能消除重复信息。先修投影；未来若必需信息确实超出窗口，再对对照组统一评估上下文配置。

## 实际验证

新诊断目录：`runs/contest-memory-context-fix-20260925a`。

F06 使用原失败批次真实 F01/F02 Memory 的隔离副本；O06 使用 `contest-stage1-history-fix-20260925b/stage1/sb-full` 已提交的 O01/O02 Memory 副本。历史目录保持不变，原 artifact 引用仍可验证。

|任务|外部数值与报告校验|Executor 请求|Executor 输入 tokens|CodeAct repair|报告 repair|
|---|---|---:|---:|---:|---:|
|F06|通过|1|5298|0|0|
|O06|通过|1|5486|0|1|

两项都真实检索到两条旧 Memory，兼容判定均为 degraded/assist，重新生成代码并在 bwrap 内对当前输入计算。O06 的一个报告批次首次缺少实体覆盖，现有一次报告 repair 后通过；它不是再次发生上下文超限。两项的新结果均正常提交为 Memory。

F06 输入从 8685 降到 5298，预留输出后为 7498；O06 预留输出后为 7686，都小于 8192。两个任务的 effective-budget.json 与原失败 F06 完全一致。

本次 `memory_consumption_records=[]`，不把这两项宣称为跳过 Executor 或 Memory 加速证据；它们证明存在历史候选时的新口径任务能正常重新计算。GPU 同期有其他工作负载，耗时只留原始记录，不用于性能结论。

验证：宿主机相关回归 158 passed；现有 openEuler 容器 CodeAct / bwrap 集成 25 passed；shell 语法、git diff --check 通过。新完整命令 dry-run 确认 selected_count=planned_count=12、smoke=false。

证据：`review-summary.json`、`verification-detail.json`，各任务 `provider.jsonl`、`scorer.json`、`execution/codeact_execution.json`、`execution/business-report-checks.json`。

## 下一步

本轮只执行了两次有判别力的修复验证，没有自动重跑完整 12 项，也不能把旧 8 项与新两项拼成一个完成批次。现在可运行下面的完整 Memory 小对比；它不是 `--smoke`，输出保留为正式小对比数据。Memory 批次完成也不表示其余 Stage 2 机制或 Stage 3 两条主链已完成；交付顺序仍按 proposal/37。

```bash
cd /home/qcrs/statebus/os
RUN_ROOT="$PWD/runs/contest-stage2-memory-context-fix-$(date +%Y%m%d_%H%M%S)"
scripts/run_contest_measurement_stages.sh \
  --stage 2 --mechanism memory \
  --stage1-root "$PWD/runs/contest-stage1-history-fix-20260925b" \
  --profile qwen3-32b-gpu2-u050 \
  --embedding-gpu 1 --container-name statebus-runtime \
  --runtime-python /home/qcrs/statebus/conda-envs/statebus_host/bin/python \
  --stop-on-failure --run-root "$RUN_ROOT"
```

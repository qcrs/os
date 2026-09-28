# A 主实验实现与执行边界

日期：2026-09-26

## 已完成

A 主实验入口已接入 Finance F01–F10 和 Service Ops O01–O10。F03–F05、F07–F10、O03–O05、O07–O10 使用独立 task contract、独立 scorer 和发布文件；F01/F02/O01/O02/F06/O06 的既有生成路径保持不变。

连续 runner 按 family/profile 隔离保存四条链：Finance/SB-FULL、Finance/P-TEXT、Service Ops/SB-FULL、Service Ops/P-TEXT。每条链按 01→10 发布数据；失败只阻断本链后继，除非指定 `--stop-on-failure`。F10/O10 只有在本配置前九轮均通过独立 scorer 后才接收历史结果。

SB-FULL 与 P-TEXT 都使用同一 CodeAct executor、同一 sandbox、同一 `code_max_tokens`、同一 repair 上限和同一业务 scorer。差异只在 Agent 交接：SB-FULL 使用 typed StateBus path，P-TEXT 使用自然语言文本 path。SB-FULL 的 Memory replay 是额外机制；P-TEXT 不使用 Memory。

统一指标已接入：provider 请求与 prompt/completion/total tokens、handoff logical messages/chars/UTF-8 bytes/local tokens、planner/executor/summarizer repair、timeout，以及失败任务的已观测成本。handoff 指标是 callback projection，不宣称物理 wire bytes，也不冒充 B2 matched receiver。

## 关联性

每个任务有独立 scorer，但业务任务不是独立样本。关联由三层保证：

1. 本轮只能看到截至本轮已发布的 raw files；未来文件不可见。
2. F04/F05/O04/O05 等任务从已发布的前后期数据计算变化；F08/F09 使用分期预算；O08/O09 使用分位数样本。
3. F10/O10 接收当前 profile 自己前九轮经 scorer 重新验证的结果；不能用另一 profile、Memory API 或 scorer reference 冒充。

因此“独立 scorer”是防止 runner 自证，不是把十轮拆成十个互不相关的 smoke。

## 已验证

- 离线合同和主链 runner 回归：71 passed，2 skipped；skip 是主沙箱 bwrap 权限限制，已有容器只读复核过对应最小 bwrap fixture。
- O08 SB-FULL 定向真实验证通过，包含 128 样本 nearest-rank P95 和最终报告。
- F03 P-TEXT 定向真实验证通过。
- F08 的计算和 scorer 语义已核对；曾发现 Summarizer 负小数报告问题和 CodeAct 对预算字段理解偏差，均已加入公共提示/修复路径。F08 复核结果保留在各 targeted run，不能拼成主链通过率。
- B1 Memory 12 个执行已完成；`validated_replay` 变体的 replay 轮出现 Executor 请求为 0，且保留首次生成成本与失败成本。它是 Memory 机制证据，不是 A 主链结果。

## 还没有发生

A 主实验的正式 40 次执行尚未完成，不能把 targeted run 或离线 40-slot dry-run 写成 40/40。运行前冻结源码；正式结果以 `$RUN_ROOT/main/summary.json` 为准，检查 `planned_count=40`、`passed_count`、`main_chain_completed` 和四条 `completed_ten_rounds`。

## 与赛题的对应

A 主实验覆盖三类以上业务处理：聚合/阈值、跨期差分、预算关联、请求分位数和多周汇总；四角色 Planner/Retriever/Executor/Summarizer 实际运行。B1 提供共享记忆复用证据；已有 s1 记录提供非文本状态 publish/transfer/consume 证据；SB-FULL/P-TEXT 提供相同任务条件下的 typed/text 对照。B2 matched receiver 与 B4 跨 Agent Memory 仍按真实证据单独记录，不伪造。

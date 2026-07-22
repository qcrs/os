# StateBus v2 赛题重建设计索引

> **事实来源**：[`PROMPT_722`](../../PROMPT_722_contest_rebuild_prefix_logitstate_without_latent.md)、[`contest readiness audit`](../../reports/statebus_v2_contest_readiness_audit_20260722.md)、当前源码、五个 continuous-family manifest，以及本轮记录在 [`07`](07_auxiliary_verification_record.md) 的只读/固定 fixture 核对。
> **设计假设**：正式主线固定 `latent_mode=off`；embedding `SemanticStateRef` 是非文本状态主证据；Prefix 与 LogitState 是相互独立、默认关闭、必须经新鲜实验才能进入 headline 的机制。
> **待验证实验**：[`05`](05_experiment_matrix_metrics_and_statistics.md) 定义的 R0-R12、P-A/P-B/P-C、L-A/L-B/L-C/L-D；本文不包含这些实验的结果。

文档导航：[索引](README.md) | [00 决策与包装](00_executive_decision_and_packaging.md) | [01 现状与整改](01_current_state_and_remediation.md) | [02 Prefix](02_prefix_engine_local_reuse_design.md) | [03 LogitState](03_logitstate_core_chain_design.md) | [04 数据与任务](04_vertical_data_preprocess_and_task_design.md) | [05 实验](05_experiment_matrix_metrics_and_statistics.md) | [06 实施与验收](06_implementation_plan_and_acceptance.md) | [07 辅助核对](07_auxiliary_verification_record.md)

## 1. 文档状态与适用边界

本目录是 **future implementation / experiment preregistration**，不是实现、实验结果或最终答辩稿。本轮没有修改源码、测试、manifest、数据或既有 artifact，也没有向模型服务发送请求。

正式定位收敛为：

> 面向企业财报与经营指标连续分析的受控多 Agent 基础设施：typed Protobuf/UDS 承载控制合同，embedding 语义状态选择证据，MemoryRef 在兼容门下提供历史知识候选；future engine-local prefix reuse 尝试减少相同 token 前缀的重复 prefill，future LogitState 尝试在闭集决策不确定时触发一次有界核验。所有效果分别受 R2/R4/P-A-C/L-A-D gate 约束。

以下边界不可被后续包装覆盖：

- 不传递、导出或恢复 Agent 间 KV/hidden tensor；Prefix 只表达同一 vLLM 引擎的 APC 使用意图和观测。
- 不使用 `LatentStateRef`、`prompt_embeds` 或 latent 收益；正式配置必须 `latent_mode=off`。
- embedding matrix 由数值 selector 读取以改变 hydration，不能写成“直接喂给下游 LLM”。
- `candidate_handle_seen`、estimate、memory candidate 和 entropy 都不是收益证据。
- 当前历史 evidence 只能按历史快照读取；未来最终版本必须重新 freeze、回归和实验。

## 2. 阅读顺序

| 顺序 | 文档 | 解决的问题 | 主要输出 |
| --- | --- | --- | --- |
| 1 | [`00`](00_executive_decision_and_packaging.md) | 做什么赛题、面向谁、什么现在能说 | 垂类、定位、包装降级树 |
| 2 | [`01`](01_current_state_and_remediation.md) | 代码/证据到底到哪一步 | D0 决定登记册、P0/P1/P2 缺口 |
| 3 | [`04`](04_vertical_data_preprocess_and_task_design.md) | 正式数据与两组十轮如何成立 | 公开来源、provenance、gold 隔离、2x10 合同 |
| 4 | [`02`](02_prefix_engine_local_reuse_design.md) | Prefix 如何形成真实 APC 因果链 | exact identity、布局、事件、调度、P-A/B/C |
| 5 | [`03`](03_logitstate_core_chain_design.md) | LogitState 谁生产、谁消费、如何校准 | 闭集 alias、Ref、ConfidenceGate、L-A/B/C/D |
| 6 | [`05`](05_experiment_matrix_metrics_and_statistics.md) | 如何公平、可重复、可证伪地测 | R0-R12、L0-L3、指标字典、统计纪律 |
| 7 | [`06`](06_implementation_plan_and_acceptance.md) | 未来工程师按什么顺序改哪些文件 | 文件级 P0/P1/P2 计划、回滚与验收 |
| 8 | [`07`](07_auxiliary_verification_record.md) | 本轮事实如何被有限核对 | 命令、观察、局限、待授权探针 |

## 3. 依赖关系

```text
01 当前事实与错误计数边界
  +---> 04 数据来源、预处理和 2x10 任务冻结
  +---> 02 Prefix exact-token 与 engine observation 设计
  +---> 03 LogitState 数值消费与 calibration 设计
                 |
                 v
        05 公平矩阵、指标和统计 preregistration
                 |
                 v
        06 future implementation 与 acceptance
                 |
                 v
      新鲜实现/实验通过后，00 才能升级包装措辞

07 只为上述设计提供有限接口/fixture 事实，不替代任何正式实验。
```

实施依赖必须遵循：

1. 先修 memory truth、semantic accounting、数据 provenance 和 lane fairness。
2. 再完成 Prefix、LogitState 的最小垂直闭环及无模型测试。
3. 再冻结 source/config/data/runtime/image/calibration/policy hash。
4. 再跑 dev 机制实验；失败保留，不改 holdout 迎合结果。
5. 最后跑 frozen holdout、openEuler 交付验证和包装生成。

## 4. 总决策树

```text
数据是否有 source/license(or terms)/raw hash/transform/gold 隔离？
  否 -> 只做 dev/diagnostic，不说企业垂类或外部泛化
  是 -> R11

embedding 是否有 publish -> cross-PID numeric consume -> IDs -> hydration -> release？
  否 -> 不说非文本状态完成
  是且 R1/R2 质量门通过 -> 可说 semantic state 机制与上下文选择

Prefix 是否 exact token-ID 相同且同 engine/epoch？
  否 -> ineligible；不产生 requested/hit 主张
  是 -> P-A -> P-B valid token counters -> P-C 质量等价
       只有 P-C 重复 CI 通过，才可说对应层面的时间变化

LogitState 是否绑定闭集候选和唯一 decision token？
  否 -> unavailable，走普通路径
  是 -> L-A calibration -> L-B numeric consumer -> L-C effect/cost -> L-D fail-closed
       无预测力/无净质量价值 -> 降为 telemetry 或关闭

Memory 是否有实际 rendered/recipe receipt？
  否 -> candidate/approved，不计 consumed
  是 -> R4 paired counterfactual；无跳步/调用收益就不说节省计算
```

## 5. 文件覆盖检查

| Prompt 强制项 | 主文档 | 交叉验证 |
| --- | --- | --- |
| 当前/未来/永久禁止三栏包装 | [`00`](00_executive_decision_and_packaging.md) | [`01`](01_current_state_and_remediation.md)、[`05`](05_experiment_matrix_metrics_and_statistics.md) |
| D0 六类状态登记 | [`01`](01_current_state_and_remediation.md) | [`07`](07_auxiliary_verification_record.md) |
| Prefix 第 5.2.1 节全部部件 | [`02`](02_prefix_engine_local_reuse_design.md) | [`05`](05_experiment_matrix_metrics_and_statistics.md)、[`06`](06_implementation_plan_and_acceptance.md) |
| LogitState 第 6.5 节全部部件 | [`03`](03_logitstate_core_chain_design.md) | [`05`](05_experiment_matrix_metrics_and_statistics.md)、[`06`](06_implementation_plan_and_acceptance.md) |
| 公开垂类、provenance、2x10 | [`04`](04_vertical_data_preprocess_and_task_design.md) | [`05`](05_experiment_matrix_metrics_and_statistics.md) |
| R0-R12、L0-L3、指标和统计 | [`05`](05_experiment_matrix_metrics_and_statistics.md) | [`02`](02_prefix_engine_local_reuse_design.md)、[`03`](03_logitstate_core_chain_design.md) |
| future 文件级实施和验收 | [`06`](06_implementation_plan_and_acceptance.md) | 全部设计文档 |
| 本轮辅助核对与授权状态 | [`07`](07_auxiliary_verification_record.md) | [`01`](01_current_state_and_remediation.md) |

## 6. 当前结论快照

- **保留为当前主证据**：typed control contract；embedding `SemanticStateRef` 的 `<f4`、shared memory/mmap、跨 PID cosine consumer、selected-ID hydration 和 release；受控四角色/执行/validator 的历史机制证据。
- **保留但必须重建正式证据**：MemoryRef 消费/效果；L0-L3；两组十轮；当前工作树回归。
- **已有骨架、尚无正式收益**：Prefix identity/layout/schedule/parser/feedback。
- **telemetry only**：当前 LogitState peak-entropy payload 和粗粒度 gate 计数。
- **正式主线关闭**：latent、`prompt_embeds`、hidden/KV handoff，以及任何对应收益叙事。
- **正式数据决定**：未来 headline 改用 repo 外公开企业披露；现有 ACME/BETA、Orion/Nova 和 disease/weather 全部降为 dev、mechanism 或 parser 回归。

## 7. 仍需用户授权的动作

本目录完成不需要额外授权。未来下列动作必须在执行前单独获得许可或满足外部条件：

- 向当前 `127.0.0.1:53334` 发送一次 `top_logprobs` capability probe；
- 为冷 cache/独立 epoch 重启或清理 vLLM；不得把连续服务窗口冒充冷实验；
- 下载并冻结公开 filings 数据；
- 运行成组模型请求或任何正式 P/L/R 实验；
- 在 openEuler 容器内执行最终验证。

只读 `/metrics` 虽在 Prompt 允许范围内，本轮也未访问；当前服务 counter schema 仍标记为“待核对”，不能在设计文档中当作已可用。

## 8. 环境准备补记

`2026-07-22` 已新增 [`contest rebuild 环境 profile`](../../setup/contest_rebuild_environment.md) 和 offline-only 静态 preflight。它预配置 `53334` 的 API/health/metrics URL、Qwen3-32B model/tokenizer、vLLM `0.9.2` 环境、用户持久目录、未来 filing/openEuler 描述与独立动作 gate；Prefix/Logit 默认关闭，latent 强制关闭。

该补记不结算 A0：没有访问当前服务、下载 filing、运行模型/正式实验、建立 cold epoch 或执行 openEuler 验证，当前 dirty branch 也不是计划要求的 clean `v2` implementation worktree。

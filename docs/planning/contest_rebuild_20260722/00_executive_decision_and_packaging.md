# 00 赛题执行决定与包装边界

> **事实来源**：[`readiness audit`](../../reports/statebus_v2_contest_readiness_audit_20260722.md)、canonical E0-E6 报告、当前实现和 [`07`](07_auxiliary_verification_record.md)；历史数值只描述历史 snapshot。
> **设计假设**：目标用户是需要可追溯、可复核经营分析的财务/运营分析团队；正式数据采用 [`04`](04_vertical_data_preprocess_and_task_design.md) 选择的公开企业披露来源。
> **待验证实验**：R0-R12、P-A/P-B/P-C、L-A/L-B/L-C/L-D，定义见 [`05`](05_experiment_matrix_metrics_and_statistics.md)。

文档导航：[索引](README.md) | [00 决策与包装](00_executive_decision_and_packaging.md) | [01 现状与整改](01_current_state_and_remediation.md) | [02 Prefix](02_prefix_engine_local_reuse_design.md) | [03 LogitState](03_logitstate_core_chain_design.md) | [04 数据与任务](04_vertical_data_preprocess_and_task_design.md) | [05 实验](05_experiment_matrix_metrics_and_statistics.md) | [06 实施与验收](06_implementation_plan_and_acceptance.md) | [07 辅助核对](07_auxiliary_verification_record.md)

## 1. 一句话决定

StateBus v2 不是“传神经隐藏态的通用 Agent 平台”，而是 **公开企业报告连续分析中的可审计协作运行时**：把控制合同、证据选择、执行产物、历史记忆、引擎本地前缀意图和不确定性门拆成不同对象，各有真实消费者、生命周期和反事实实验。

正式主线固定：

```text
typed Protobuf/UDS control
  + embedding SemanticStateRef (当前非文本状态主证据)
  + verified ExecutionArtifactRef
  + compatible MemoryRef
  + Engine-Local Prefix Reuse (future, APC observation)
  + LogitState -> ConfidenceGate (future, bounded quality control)
  - latent / prompt_embeds / hidden-state handoff / KV tensor transfer
```

## 2. 赛题问题、用户和价值

### 2.1 问题

企业财报和经营指标分析往往连续发生：先定位披露、再抽取指标、跨期计算、解释异常、复核风险，最后形成带 locator 的结论。若每个角色都重复传整份文档、重新读取相同证据或盲目相信历史结果，会同时产生通信冗余、上下文膨胀和错误复用风险。

### 2.2 目标用户

- 财务分析、FP&A 和经营分析人员，需要跨期指标和可追溯结论；
- 内部审计/模型风险团队，需要知道哪个组件读了哪个 Ref、为何接受或拒绝；
- 平台工程团队，需要在单容器 openEuler/vLLM 环境中复现实验和资源成本。

### 2.3 可交付价值

| 用户问题 | StateBus 机制 | 证据门 |
| --- | --- | --- |
| “角色间是否少传了控制面数据？” | typed Protobuf/UDS | R2 的 matched L0-L1 bytes；不能推导 token |
| “下游究竟看了哪些证据？” | embedding state + numeric selector + hydration | R1/R2 的 PID、IDs、bytes、quality |
| “历史结果能否安全复用？” | compatibility/policy/receipt/replay | R4 的 actual consumed 与 paired counterfactual |
| “相同报告能否少做 prefill？” | engine-local prefix intent + vLLM APC | P-A/B/C；exact tokens + valid engine counters |
| “模型犹豫时是否值得核验？” | LogitState + calibrated ConfidenceGate | L-A/B/C/D；质量与额外成本同时报告 |

## 3. 三个技术难点与设计回应

1. **非文本不等于不可审计**。Embedding 与 LogitState 都必须是明确 dtype/shape/hash/lease 的二进制 Ref，由独立数值组件读取并留下 effect receipt；LLM 不直接读取向量。
2. **复用不等于命中**。Prefix 的 registry 复见、Memory 的 candidate/approved 和 artifact 可用都不能称为实际复用；只有 engine counter 或 role/recipe receipt 能升级计数。
3. **更快不能牺牲正确性**。所有 latency/TTFT/跳步结论先过 deterministic quality、citation/provenance 和失败保留门；LogitState 允许增加成本，目标是受控风险而非强行省 token。

## 4. 机制亮点的正确层次

```text
embedding semantic state：当前任务应看哪些证据？
  -> selector 改变 selected IDs 与 hydration

engine-local prefix reuse：相同且已授权的 token 前缀能否少做 prefill？
  -> vLLM 自己创建/命中/淘汰 KV blocks；StateBus 不导出 KV

LogitState：闭集 tool/recipe 选择是否不确定，值得一次核验吗？
  -> ConfidenceGate 输出 accept/expand_once/verify_once/retry_once/fail_closed

MemoryRef：历史上已验证的事实、artifact 或 recipe 是否合同兼容？
  -> policy + actual receipt 决定 assist/replay/recompute
```

这四层开关、consumer、指标和实验必须独立。主 L0-L3 矩阵关闭 Prefix/LogitState；Prefix 实验固定 memory/logit；LogitState 实验固定 prefix/memory，详见 [`05`](05_experiment_matrix_metrics_and_statistics.md)。

## 5. 包装主张三栏表

| 当前可说（必须带历史/当前限定） | 通过 future gate 后可说 | 永久禁止 |
| --- | --- | --- |
| 历史 matched E1 中，L0->L1 control bytes `-83.05%`、wire bytes `-68.95%`；prompt tokens 反而 `+2.88%` | R2 fresh freeze 后报告相同定义的新结果和 CI | “Protobuf 必然省 token” |
| 历史 E1 中，L1->L2 prompt tokens `-55.76%`、visible bytes `-81.10%` | R1/R2 证明 selected IDs、hydration、质量不降后称上下文选择收益 | “embedding 就是 KV”或“直接喂给 LLM” |
| E4 是 repo-local frozen holdout 上的跨 PID `<f4` 数值消费机制证据 | R11 公开 source holdout 通过后称企业披露任务上的有效性 | “E4 证明第三方/开放域/生产泛化” |
| Prefix 已有 layout、identity、schedule、metrics parser 和 feedback 骨架 | P-A/B 后称 observed APC token hit/TTFT 机制；P-C 后才称端到端影响 | “registry hit/estimate 就是 GPU cache hit”或 KV transfer |
| LogitState 当前只提取 top-logprobs 并写 telemetry | L-A/B/C/D 后按结果称 calibrated risk gate 的质量/成本效果 | “entropy 低证明答案正确”或“当前已改善质量” |
| Memory 有 store/query/compatibility/policy/replay 设计；当前 receipt 逻辑已收紧 | R4 fresh paired run 后称 actual consumption、跳步或调用变化 | “candidate/approved/artifact reuse 就是 memory hit/replay” |
| 四个角色是 Runtime 控制的固定受控链，Executor 是 DSL/bounded Python | R12 只按自然选择计数扩展 capability coverage | “四个 Prompt 就是自治群体”或“任意 shell/生产沙箱” |
| 历史 canonical evidence 在 openEuler 单容器完成过验证 | 当前版本 R0 + final openEuler gate 后称本版本已复现 | “任意 Linux/VM/跨机均已兼容” |
| 现有样本是 repo-local synthetic/通用 CSV/mechanism fixtures | R11 通过后称公开企业披露上的 frozen holdout | “ACME/BETA/Orion/Nova 证明真实业务泛化” |

## 6. “时间减少”当前不能写成结果

现在没有可用于赛题 headline 的总时延优势，原因是：

- 历史 E1 latency 是单次、固定顺序，没有 ABBA/随机化、充分重复或置信区间；
- Prefix 的 bytes/4 saved-token estimate 不是引擎观测；
- 当前 smoke `/metrics` 窗口覆盖整项任务的多角色请求，且没有证明服务独占；
- vLLM 官方说明 APC 只减少 shared-prefix prefill，不减少 decode；长输出时总时延可能不改善；
- Memory 历史 skip/consumed 口径需要 receipt 和 counterfactual 重建；
- LogitState 的核验可能主动增加 latency、tokens 和调用数。

包装降级规则：

| 最终通过情况 | 允许表述 |
| --- | --- |
| 仅 P-A | “构造了 exact-token-compatible 的 prefix intent” |
| P-A + P-B，P-C 不显著 | “观察到 engine-local cached-token/TTFT 机制效应；未观察到端到端优势” |
| P-A/B/C 且质量等价、CI 方向一致 | “在该 frozen workload/engine 下，prefix policy 对所列 latency 指标产生了测得变化” |
| R4 仅有 actual receipt，无 skip/call 变化 | “完成兼容记忆的真实消费；未证明节省计算” |
| L-C 质量改善但成本增加 | “以所列额外成本换取 verified error recovery”，不说加速 |
| 任一质量门失败 | 只保留机制或负结果，不发布 superiority 句子 |

未来任何百分比都必须从 [`05`](05_experiment_matrix_metrics_and_statistics.md) 的 canonical artifact 生成，不能手工预填。

## 7. 演示故事（结果自适应）

1. 载入一组冻结的公开企业披露，展示 source URL/terms、raw hash、locator 和 runtime 不可见 gold。
2. Planner 只给 bounded retrieval objective；Retriever 生成候选。
3. 展示 embedding matrix 的 shape/dtype/producer PID，独立 selector PID 读取后 selected IDs 改变 EvidencePack；随后 release。
4. Executor 用闭集 capability 执行，validator 生成 `ExecutionArtifactRef`；Summarizer 只能读 verified artifact/授权证据。
5. 第二个兼容任务展示 Memory candidate -> approved -> actual receipt 或 rejection/recompute，不把 candidate 当 hit。
6. Prefix 分屏展示相同 token hash/length、eligible/requested/observed；若 counter 不可用，画面明确显示 unavailable。
7. LogitState 分屏展示短命 Ref、ConfidenceGate 动作、effect receipt 与 release；若 calibration gate 未通过，只展示 telemetry-only。
8. 最后一页由 claim gate 自动选择措辞：通过则给 effect+CI，失败则给负结果和降级结论。

演示不得显示 secret、完整 raw completion、GPU/KV 内容或 hidden tensor。

## 8. 答辩结构

| 页 | 内容 | 证据来源 |
| --- | --- | --- |
| 1 | 企业连续分析中的重复传递、错误复用和风险核验问题 | [`04`](04_vertical_data_preprocess_and_task_design.md) |
| 2 | 四角色 + Controller，typed control/data/artifact/memory 分层 | [`01`](01_current_state_and_remediation.md) |
| 3 | embedding 非文本状态真实消费 | R1/E4（明确历史/新鲜） |
| 4 | Prefix exact token -> same engine APC，不是 KV handoff | [`02`](02_prefix_engine_local_reuse_design.md) |
| 5 | LogitState -> calibrated bounded action | [`03`](03_logitstate_core_chain_design.md) |
| 6 | 两条公开数据 10 轮链和 gold 隔离 | [`04`](04_vertical_data_preprocess_and_task_design.md) |
| 7 | L0-L3、P、L 独立矩阵和失败保留 | [`05`](05_experiment_matrix_metrics_and_statistics.md) |
| 8 | 只展示实际通过的 claim；未通过项自动降级 | canonical future report |

## 9. 包装发布门

最终 README、答辩、图表和视频只能在 [`06`](06_implementation_plan_and_acceptance.md) 的 A0-A9 全部结算后生成。生成器必须读取 machine-readable claim matrix；若找不到对应 artifact hash、quality gate、counter validity 或 CI，则该句子不进入产物。

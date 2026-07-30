# Summarizer：只基于可信输入形成可核验结论

Summarizer 位于业务链末端，但它不是一个可以重新检索或修补执行结果的“万能回答 Agent”。调度器要求其 Grant 中至少包含一个已验证执行产物，并且只能包含一个与当前任务、会话一致且 coverage 状态为 COMPLETE 的 EvidencePack。存在多级 Executor 时，中间产物仍保留在依赖链中，最后一级 verified artifact 才作为直接结论输入。

角色读取规范化产物行、EvidencePack 中的 locator 以及允许暴露的记忆输入，生成 `ClaimSet` 候选。每条 Claim 应把结论值与证据定位、产物来源和任务上下文连接起来。自然语言写得合理并不代表候选可发布，`ClaimSetValidator` 会检查引用是否存在、证据和产物是否属于当前会话、声明值能否在已验证输入中找到支撑，以及状态是否满足输出合同。

校验失败时，步骤以 `claim_validation_failed` 结束，不允许输出一个没有引用的兜底答案。校验通过后，Runtime 才写入 summary artifact，并结合任务是否完成、lineage 是否完整、记忆查询状态和兼容策略决定是否提交 `MemoryRef`。因此“总结”和“记忆写回”虽然处在同一收尾阶段，最终提交权仍属于 Runtime，而不是 Summarizer 自述的 reusable 标签。

| 合同面 | Summarizer 的边界 |
|:--|:--|
| 可见输入 | verified artifact、唯一完整 EvidencePack、Grant 允许的记忆输入 |
| 候选输出 | `ClaimSet`、摘要文本、可复用步骤和标签 |
| 权威校验 | `ClaimSetValidator`、summary artifact 写入、Runtime memory commit decision |
| 禁止范围 | 重选工具、补读证据、修改执行产物、绕过引用校验 |

主要调度逻辑位于 [adaptive_dispatcher.py](../../../statebus/runtime/adaptive_dispatcher.py)，Claim 校验位于 [claims.py](../../../statebus/runtime/claims.py)，记忆提交由 [adaptive_mainline.py](../../../statebus/runtime/adaptive_mainline.py) 收口。跨任务写回与重放边界另见[记忆提交与分级重放](../memory/commit-and-replay.md)。


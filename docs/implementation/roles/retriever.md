# Retriever：在受限语料中形成完整证据面

Retriever 接收的是批准计划中的检索步骤和对应 `CapabilityGrant`。它可以根据任务查询形成 `EvidenceRequest`，但查询数量、候选预算、证据类型和 `corpus_scope_ids` 都受任务 envelope 与 Grant 约束。路由或工具存在多个候选时，角色只能在 Runtime 提供的 closed candidate surface 中选择，不能用自然语言创造一个目录里不存在的新工具。

角色决策之后，真正的检索和对象物化仍由 Runtime 负责。检索管线对不同来源做 fan-out，记录候选池与检索日志，随后把选中内容规范化为 `CanonicalEvidencePack`。结构化片段通过 `HydrateManifest` 保留行、单元格或文本跨度的定位关系；需要稠密选择时，embedding 以 `SemanticStateRef` 发布到 StatePool，消费者凭 registry 记录、runtime signature 和消费回执读取，而不是把完整 float32 数组重新展开到 Agent 文本中。

EvidencePack 还要经过 coverage 检查。证据不足时，Retriever 可以在既定预算内提出一次扩展请求；达到完整状态后，Pack 的 hash、任务与会话范围才可进入 Executor 和 Summarizer。检索分数只是候选排序依据，并不等同于事实正确，更不授权 Retriever 直接撰写最终答案。

| 合同面 | Retriever 的边界 |
|:--|:--|
| 可见输入 | `EvidenceRequest` 上下文、Grant、语料范围、闭集 route/tool surface |
| 候选输出 | 查询与路由选择、候选证据、检索日志 |
| Runtime 物化 | `CanonicalEvidencePack`、`HydrateManifest`、`SemanticStateRef` |
| 禁止范围 | 改写 required outputs、读取范围外文件、生成最终答案、确认执行产物 |

主要实现位于 [role_path.py](../../../v2/runtime/role_path.py)、[retrieval_adapter.py](../../../v2/runtime/retrieval_adapter.py)、[evidence_coverage.py](../../../v2/runtime/evidence_coverage.py) 与 [v2/retrieval](../../../v2/retrieval/)。非文本语义状态和 Hydration 的细节分别见[稠密语义状态](../state/dense-semantic-state.md)与[Hydration 和证据](../state/hydration-and-evidence.md)。


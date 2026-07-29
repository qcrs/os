# 结构化通信协议三页 PPT 提示词

下面提示词用于根据 `structured_communication_protocol.md` 生成一份约 3 页的技术汇报 PPT。目标是突出 SynapseX 结构化通信协议相对纯文本传输的优势、协议结构设计，以及 Context Packet 文本压缩包的构造、排序和校验算法。

## 可直接复制给 PPT 生成工具的提示词

请生成一份 16:9 技术汇报 PPT，共 3 页，语言为中文，风格为工程技术方案汇报，整体视觉简洁、清晰、偏系统架构图风格。不要做营销风格封面，不要堆砌大段文字。每页应有一个明确主标题、3 到 5 个关键要点，以及一张结构化图示或流程图。主题是“SynapseX 多 Agent 结构化通信协议”。

### 第 1 页：技术总览：从纯文本透传到结构化通信

页面标题：结构化通信协议：降低多 Agent 协作中的文本透传开销

核心表达：

- SynapseX 主线工作流为 `planner -> researcher(s) -> analyst -> executor -> summarizer`。
- 纯文本模式中，researcher 生成的长文本容易被继续拼接传给 analyst、executor、summarizer，造成 token 开销高、来源难追踪、下游难校验。
- structured 模式把 Agent 间中间状态拆成四类载荷：`AgentMessage` 控制消息、`context_packets` 压缩证据包、Store 原文引用、可选 `embedding_payloads` 排序信号。
- 该方案不是完全消灭文本，而是避免无差别全文透传，让 LLM 只看必要短证据，系统层负责校验、回补、排序和指标采集。
- 实验结果可作为页脚小结：Protocol B 相比 Protocol A 总 tokens 从 114,021 降到 98,422，减少 15,599，约 13.7%；Context 文本从 104,414 chars 压缩到 41,574 chars，节省 60.2%。

建议图示：

- 左右对比图。
- 左侧为 Text Mode：`researcher full documents -> documents reducer -> analyst full prompt -> summarizer larger analysis`。
- 右侧为 Structured Mode：`researcher full doc -> Store(doc_key)`，同时生成 `context packet + embedding payload -> analyst ranking + verification -> compact evidence prompt -> analysis_digest -> summarizer`。
- 用红色或灰色标注纯文本“全文透传/token 高”，用蓝绿色标注 structured “短证据/可校验/可回补”。

页面备注：

- 不要把所有指标都放成大表，只展示最能说明通信收益的 2 到 3 个数字。
- 强调“系统层协议”而不是“prompt 格式优化”。

### 第 2 页：协议结构设计：控制面、数据面、引用面分离

页面标题：协议结构设计：把动作、证据、原文和非文本信号拆开

核心表达：

- 控制面：`AgentMessage` 统一记录 `source`、`target`、`action`、`params`、`result`、`task_group`、`status`，用于追踪 Agent 间动作和通信开销。
- 数据面：`context_packets` 承载面向 query 的短摘要和 evidence spans，替代 researcher 全文传输给 analyst。
- 引用面：完整文档写入 Store 的 `("docs", doc_key)` namespace，下游通过 `doc_key`、全文 hash、span offset 和 span hash 回查校验。
- 排序面：`embedding_payloads = {doc_key, dims, vector}` 只参与 Python 层排序，不进入 LLM prompt。
- 降级面：关闭 Context Packet 或校验失败时，走 `documents`、`document_payloads` 或 Store rehydrate 路径。

建议图示：

- 中央画 `AgentWorkflowState`，周围分四层通道：
  - `messages`：AgentMessage 控制通道。
  - `context_packets`：压缩文本证据通道。
  - Store `("docs", doc_key)`：原文引用和回补通道。
  - `embedding_payloads`：非文本排序信号通道。
- 下方画 LangGraph fan-out/fan-in：
  - `planner` 通过 `Send` 分发 3 个 `sub_queries` 到并行 `researcher`。
  - 多个 researcher 输出通过 `operator.add` reducer 汇总到 analyst。
- 右侧放一个小型 `AgentMessage` schema 卡片：
  - `action: plan/research/analyze/execute/summarize`
  - `params: structured input`
  - `result: compact output summary`

页面备注：

- 重点讲“控制消息不塞全文，大文本放 Store，prompt 只看短证据”。
- 可以把 `AgentCard/AgentRegistry` 作为页脚补充：支持能力描述和 `retrieve -> research` 协议映射，但主链路仍由 LangGraph 静态拓扑执行。

### 第 3 页：Context Packet 算法：构造、排序、校验与回补

页面标题：Context Packet：可压缩、可排序、可校验的证据包

核心表达：

- 构造阶段：researcher 生成完整 `doc_text`，写入 Store；`build_context_packet()` 从文档中检索与 `sub_query` 相关的 evidence spans。
- 证据评分公式：`score = 0.72 * query_term_coverage + 0.18 * term_density + position_bonus + phrase_bonus`；默认每个文档最多保留 4 个证据片段，每段默认 180 chars，摘要默认 360 chars。
- Packet 字段包括：`doc_key`、`source_query`、`summary`、`evidence_spans`、`retrieval_diagnostics`、`full_doc_ref`、`verification`、`compression_ratio`。
- 排序阶段：analyst 调用 `select_context_packets()` 选择 top-k。无 embedding 时：`0.80 lexical + 0.20 coverage`；有 embedding 时：`0.65 vector + 0.25 lexical + 0.10 coverage`。
- 校验阶段：`verify_context_packet()` 回 Store 检查全文 hash、span offset、span text hash 和 query coverage；可靠则进入 prompt，不可靠则从 Store rehydrate 前 360 字符作为 bounded fallback。

建议图示：

- 用四段流水线图：
  1. `doc_text -> sentence/window spans`
  2. `span scoring -> top evidence_spans -> summary`
  3. `packet ranking -> top_k=3`
  4. `Store verification -> reliable prompt / rehydrate fallback`
- 在图右侧放一个简化 JSON 卡片：
  - `protocol: context-packet`
  - `doc_key`
  - `summary`
  - `evidence_spans[{span_id, text, char_start, char_end, text_hash}]`
  - `full_doc_ref{text_hash}`
  - `verification{reliable, requires_full_doc_lookup}`
- 页脚展示实验验证：30/30 packets reliable，0 rehydrated，0 failed。

页面备注：

- 强调 LLM 不看完整 packet JSON，只看 `format_context_for_prompt()` 渲染出的短证据，例如 `[doc_key#ev1] evidence text`。
- 算法页应体现“压缩不等于丢证据”，因为 offset/hash/Store 引用保证可追溯。

## 全局视觉要求

- 使用统一配色：深蓝/墨绿表示系统层协议，浅灰表示纯文本透传，橙色用于提示开销或风险。
- 每页文字控制在 120 到 180 中文字以内，算法公式和关键字段可以用等宽字体展示。
- 优先使用流程图、分层架构图、schema 卡片，不要使用装饰性插图。
- 保留代码字段原名，例如 `AgentMessage`、`context_packets`、`doc_key`、`embedding_payloads`、`verify_context_packet()`。
- 不要新增第 4 页；如果需要结论，放在第 1 页或第 3 页页脚。

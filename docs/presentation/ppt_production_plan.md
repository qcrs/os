# StateBus PPT 制作建议：每页用什么来讲

这份文档只规划画法，不制作 PPTX 或图。内容顺序见[答辩叙事导航](README.md)，各页的技术内容以对应专题文档为准。这里把[模板与制作规范 v3](StateBus_PPT_Template_Kit_and_Codex_Guidelines_v3.md)的四种制作方式用到 StateBus 的 18 个内容页上：**原生 PPTX 排页面，Draw.io 画关系复杂的图，Chart 表达数据，母版统一视觉。**

## 先定页面任务，再选工具

每页先写下一个问题：“评委看完这一页，要能说出什么？”随后只让一种视觉承担主要说明。标题、注释和数字在 PPTX 中保持可编辑；复杂连线图保留 `.drawio` 源文件并导出 SVG；普通统计图优先用原生 Chart，密集配对图或特殊小倍数图再用 SVG。外部模板只借布局和图形语法，颜色、字体、Logo、页脚以最终使用的 SynapseX 母版为准。

下表的“页型”借用 v3 指南中的 C02、C05 等名称，表示构图方向，不要求直接套用外部 PPTX。制作类型按主视觉标注；“混合”表示图占主体，标题、关键数值和解释仍用原生 PPTX 排版。

## 项目介绍与亮点过渡

| 内容页 | 主视觉与读图顺序 | 制作类型 / 页型 | 具体取舍 |
| --- | --- | --- | --- |
| 1. 为什么需要 StateBus | 从左到右看“交接重复写 → 中间状态重新处理 → 下次任务再做一遍”，每处配一个具体的交接例子。 | 原生 PPTX，C02 Problem | 三个问题的时间位置比三个同样大小的卡片重要。不要提前堆 IPC 或状态名。 |
| 2. StateBus 怎样设计 | 中央放 Runtime，周围只放“步骤请求、可引用对象、执行产物、历史记录”及各自解决的事；从任务进入到结果出来读一遍。 | 原生 PPTX，C03 Solution Transformation | 这是设计选择页，文字和少量原生连线足够；不提前画第三页的完整拓扑。 |
| 3. 系统架构 | 主体沿任务入口 → Planner → Retriever → Executor → Summarizer → 结果阅读；向上看控制层，向下看对象层和模型层，右侧看记忆层回到后续任务。 | Draw.io 分层架构 SVG + 原生 PPTX 标题，C04 Architecture Hero | 以[架构图设计](architecture_page.md)为内容依据。图可以复杂，但主任务线最醒目；层是职责位置，不画成五个串行站点。 |
| 4. 亮点总览 | 四个问题占主要画面：交接、中间状态、执行、再次使用；每个问题旁只标将要展开的机制。 | 原生 PPTX，C06 Innovation 的主次构图 | 这是呼吸页。四块可以有轻微视觉联系，不用强制箭头把四类能力串成步骤。 |

架构图建议借 Draw.io 的 Layered Architecture 或 Mainline + Sideband 语法重新绘制，不以已有 `statebus-architecture.svg` 为底稿。图中缩写、连线和层名要按任务阅读顺序检查；实际比例由可读字号决定，不为容纳全部源码模块继续缩字。

## 项目亮点

| 内容页 | 主视觉与读图顺序 | 制作类型 / 页型 | 具体取舍 |
| --- | --- | --- | --- |
| 5. 结构化协议 | 一次交接的四步：能力登记 → `ExecRequest` → 角色输入投影 → ACK/执行/结果引用。请求卡只展示 operation、input refs、output contract，底部标 Protobuf over UDS 与 Ref 指向的对象。 | Draw.io 简短 Sequence 或 Data/Ref Carrier 图 + 原生请求卡，C05 Mechanism | 重点是协议如何使 Runtime 能安排下一步。UDS 是跨进程控制通道；不要画成所有 Agent 都通过 UDS 通信。 |
| 6. Embedding | 左侧是 query/candidate 矩阵和 manifest，中间将 Ref 与 shared memory/mmap 载体分开，右侧显示下游进程选 row，再回到原文 locator 和 Executor 输入。 | Draw.io 数据路径 SVG + 原生矩阵示意，C05 | 最醒目的连接是 `row index → 原始证据`。Retriever 的全部检索排序无需画入主图。 |
| 7. Logit | 用一组候选概率条展示 `top1`、`margin`、`other_mass`；旁边是 compact evidence 后的继续、展开或 abstain 结果。 | 原生 PPTX 概率条和决策分支，C05 | 核心公式只保留 `margin = p_top1 - p_top2`；`other_mass` 标为候选集合外概率。流程作为解释公式用途的小图，不占满页面。 |
| 8. 显式 KV | 上下两行对照 full replay 与 continuation；同色公共 parent、不同色角色 suffix，并标出 capture、handle、load 的位置。 | 原生 PPTX token 条 + 少量连线，C07 Comparison | 大面积展示“第二次少算了 parent”，Worker-local registry 放辅助位置。不要把 handle 画成跨任意模型传输的 KV tensor。 |
| 9. 共享记忆 | 从上轮验证结果写入，到本轮关键词/标签/语义检索及 RRF 合并，再到参考、方法重算、拒绝；突出 Executor 在本轮输入上重算的出口。 | Draw.io Replay/Lifecycle 图 + 原生三种结果标注，C05 | 检索与实际复用要分成两个视觉阶段。存储格式占一行脚注即可，不能让文件名成为主图。 |
| 10. DSL / CodeAct | 左右两条执行路径：已登记操作走 DSL；开放计算经候选代码、检查、受控执行和结果验收。两条线在 verified Artifact 汇合。 | Draw.io Decision Gate 图 + 原生代码/Artifact 小样，C05 | 展示两条路径为什么都能接上下游。CodeAct 的多项检查合成必要的几个节点，不堆完整策略清单。 |
| 11. APC | 中央并排放两个角色的 `[公共 token 前缀][各自后缀]`，连到同一 vLLM engine；外围画 query/hit 反馈到待执行任务顺序的回环。 | Draw.io 反馈回路 SVG + 原生前缀条，C05 | 前缀对齐与反馈调整都要看得见。APC 是引擎缓存路径，不画 `StateRef` 或 shared memory。 |

三张非文本页用相同的“产生位置、状态对象、消费者、后续动作”小标记，帮助评委对照；主图保持各自的形状：Embedding 是数据回溯，Logit 是概率判断，KV 是重复计算对比。APC 可沿用长文本的视觉符号，但用“引擎自动命中 + 反馈”与显式 KV 的 handle 区分。

## 技术难点

| 内容页 | 主视觉与读图顺序 | 制作类型 / 页型 | 具体取舍 |
| --- | --- | --- | --- |
| 12. 角色输入 | 一个 `EvidencePack` 指向三种角色输入，Executor 分支展开一行 typed data 和一个 source locator，再连回原证据位置。 | 原生 PPTX 分支图 + 输入样例，C05 | 评委应先看到角色拿到的内容不同，再看到来源没有丢。避免重复 Embedding 的矩阵传输。 |
| 13. 任务推进 | 同一任务的三种状态：Planner 的提案、Runtime 批准的步骤、中途变化后的后续步骤。已完成部分保持原色，替换的未执行部分换色。 | Draw.io Activity/Sequence 图 + 原生步骤卡，C05 | 画清 `PlanProposal → ApprovedPlan → attempt` 和一次有限调整，不重画完整系统架构。 |
| 14. 记忆使用 | 左侧一条历史候选，中央列出当前任务需匹配的条件，右侧给出 ASSIST、VALIDATED_REPLAY、拒绝三种去向；以“新数据重算”作为主例。 | 原生 PPTX 决策矩阵/分流图，C08 Decision Matrix | 比再画一遍 Memory 检索流程更能回答“搜到了何时能用”。`EXACT_REPLAY` 可在小字说明其严格条件。 |

这三页都以一个具体追问作为标题。它们的图各有任务：第 12 页解释输入内容，第 13 页解释进度变化，第 14 页解释复用资格。不要把三个问题再次压缩成“Runtime 负责协调”这类总括句。

## 项目测试

| 内容页 | 主视觉与读图顺序 | 制作类型 / 页型 | 具体取舍 |
| --- | --- | --- | --- |
| 15. 实验设置 | 两条任务时间线：`finance` F01-F12 与 `service_ops` O01-O12；旁边给 openEuler、Qwen3-32B、24 对同任务及两种配置。 | 原生 PPTX 时间线/信息表，C12 Multi-Evidence | 先让评委知道任务怎样连续，再看对照条件；环境只保留影响理解结果的项。 |
| 16. 24 组主线对照 | 顶部先给 `24/24` vs `24/24` 质量结果；主体用同单位的成对横条展示 requests、total tokens、Executor generations、总耗时，每组写清数值和变化。 | 原生 PPT Chart + 原生标题与标注，C11 Experiment Claim + Chart | 不把 token、请求和秒画在同一数值轴上。若加 24 任务配对点图，用单独 SVG 或附录，不挤压总体结论。 |
| 17. 主链运行记录 | 顶部用短链标交接对象及 carrier 计数；中部 Memory 漏斗显示候选、实际消费、validated replay；旁边一对 DSL/CodeAct Artifact 样例。 | 原生 PPTX 图形 + 必要时 SVG 漏斗，C12 | Memory-on 专项、主线 carrier 和 CodeAct showcase 的分母分别写在各自图旁，不能混算。 |
| 18. 非文本与模型侧专项 | 四个独立证据区：Embedding 从 row 回证据；Logit 按需展开；KV 减少 computed prefill；APC 增加 hit tokens 并降低 TTFT。每区一条行为线索、一项代表数字。 | 原生 PPTX 证据矩阵 + 可选 SVG small multiples，C12 | 使用四组独立对照，标注各自的样本数和指标单位；不把局部 TTFT 与端到端时延混成一张“总加速”图。 |

实验数字统一从[实验部分工作稿](experiments_overview.md)列出的最终汇总和 `tests/evidence/` 读取。第 16 页优先给整体判断，第 17 页说明主链真的执行了这些动作，第 18 页证明每条专项路径的行为。图表标题直接写观察结果，图例保留对照名称、分母和单位。

## 实际制作顺序

1. 拿到最终 SynapseX 母版后，先提取颜色、字号、网格、Logo 和页脚规则；从 v3 指南挑几种真正要用的版式建立原生页型。无需先做满 16 种页型或下载整套外部模板。
2. 先做六张代表页：架构、结构化协议、Logit、Memory、主线对照、非文本专项。确认它们的可读字号、图文比例和视觉节奏，再复用相同规则完成其余页面。
3. 对需要复杂关系的页面单独保存 `.drawio` 源文件并导出 SVG；简单的 token 条、概率条、矩阵和文字框保留为原生对象，方便最后改文案。
4. 图表使用最终精选结果制作；每张图在制作稿旁记录数据文件、筛选字段、分母和单位。总体图与逐任务图分开处理。
5. 完整渲染后逐页检查：标题能否对应主视觉、五秒内能否读出主关系、缩放投影后文字是否清楚、所有连线是否指向实际对象、数字是否与结果文件一致。出现拥挤时先删次要注释或移到讲稿，不靠持续缩字解决。

页间节奏建议为“问题页较轻、架构和机制页较密、亮点过渡留白、实验结果再形成强焦点”。模板负责稳定视觉，页面要保留各自的内容形状；不把 18 页都做成同一种卡片或同一种流程图。

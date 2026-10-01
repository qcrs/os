# StateBus PPT Template Kit 与 Codex 制作规范 v3
## —— 面向竞赛答辩的 Draw.io / PPTX / Chart 模板体系

> 目标：给 Codex 一套可复用模板，避免每页自由发挥。
>
> 外部模板只参考**布局、构图、图形语法**；最终颜色、字体、页脚、Logo 统一服从现有 SynapseX 母版。

---

# 1. 模板分四类

| 类型 | 推荐格式 | 适合内容 |
|---|---|---|
| 流程图 | Draw.io XML / `.drawio` | Swimlane、Sequence、Gate、Lifecycle、Replay |
| 架构图 | Draw.io XML / `.drawio` | 总架构、分层架构、组件关系、数据/存储拓扑 |
| 普通答辩页 | 原生 PPTX | 背景、方案、亮点、对比、截图、总结 |
| 实验图表 | Native PPT Chart / SVG | A/B、Slope、Matrix、Heatmap、Funnel、Small Multiples |

核心原则：

```text
Diagram 负责复杂结构
PPTX 负责页面排版
Chart 负责数据表达
Master 负责统一视觉
```

---

# 2. Draw.io 模板：建议收集得丰富一些

StateBus 技术图较多，建议准备约 20 个基础模板，而不是只留 5–6 个。

## Flow / Process

1. Simple Linear Flow
2. Decision Gate
3. Horizontal Swimlane
4. Vertical Swimlane
5. Cross-functional Flow
6. Runtime Sequence
7. Mechanism Sequence
8. Activity Diagram
9. State Machine
10. Lifecycle Strip

## Architecture / Data

11. System Component
12. Layered Architecture
13. C4 Container
14. C4 Component
15. Internal Block Diagram
16. Mainline + Sideband
17. Storage Topology
18. Data / Ref Carrier
19. Provenance Graph
20. Model-state Architecture

---

# 3. Draw.io 主要 GitHub 参考

## jgraph/drawio-diagrams

https://github.com/jgraph/drawio-diagrams

最重要的模板来源。

### Flowcharts

https://github.com/jgraph/drawio-diagrams/tree/dev/templates/flowcharts

重点：

```text
cross_functional_flowchart_1.xml
cross_functional_flowchart_2.xml
workflow_1.xml
workflow_2.xml
flowchart_1.xml
flowchart_2.xml
```

### Software

https://github.com/jgraph/drawio-diagrams/tree/dev/templates/software

重点：

```text
component_1.xml
component_2.xml
data_flow_1.xml
data_flow_2.xml
database_1.xml
entity_relationship_1.xml
```

### UML

https://github.com/jgraph/drawio-diagrams/tree/dev/templates/uml

重点：

```text
sequence_1.xml
sequence_2.xml
activity_diagram_1.xml
state_machine.xml
sysml.xml
```

### Business

https://github.com/jgraph/drawio-diagrams/tree/dev/templates/business

重点：

```text
swimlane.xml
timeline_1.xml
timeline_2.xml
archimate_1.xml
archimate_2.xml
```

### Examples

https://github.com/jgraph/drawio-diagrams/tree/dev/examples

值得参考：

```text
sequence-diagram-examples.drawio
sysml-internal-block-diagram.drawio
sysml-block-definition-diagram.drawio
timeline-example.drawio
gemfile-dependency-graph.drawio
infographic-project-steps.drawio
aws-simple-architecture.drawio
```

---

## jgraph/drawio

https://github.com/jgraph/drawio

内置模板索引：

https://github.com/jgraph/drawio/blob/dev/src/main/webapp/templates/index.xml

用于查官方有哪些 template family。

---

## kaminzo/c4-draw.io

https://github.com/kaminzo/c4-draw.io

重点：

```text
c4.drawio.library.xml
c4-icons.drawio.library.xml
```

适合借：

- System boundary
- Container
- Component
- Relationship label

不需要完整照搬 C4。

---

## jgraph/drawio-libs

https://github.com/jgraph/drawio-libs

适合补充：

- infrastructure
- network
- cloud
- vendor-specific icons

---

# 4. Codex 使用 XML：精简规则

出现以下任意情况，优先 Draw.io：

```text
节点 >= 6
连线 >= 5
有分支 / 回环
有 3+ lanes
有 subgraph / boundary
有复杂 provenance
```

普通文字页、截图页、两栏页、大数字页不要用 XML。

推荐工作流：

```text
选模板
→ 替换节点
→ 应用母版色
→ 调布局
→ 检查连线
→ 导出 SVG
→ 插入 PPT
```

建议：

- 一页一个 `.drawio`
- 同时保留 `.svg`
- 优先 orthogonal connector
- 节点先布局，最后画线
- 图内文字尽量短
- 一旦字号需要继续缩小，就拆图

---

# 5. PPTX 原生模板：应改成“竞赛答辩”体系

之前偏学术汇报的模板不够贴合。

竞赛答辩更强调：

```text
让评委快速形成判断
技术可信
真实产品/系统存在
结果有证据
页面节奏有变化
```

因此原生 PPTX Layout Kit 建议以“比赛页型”为中心。

---

# 6. 推荐的竞赛答辩原生 PPTX 页面族

建议至少准备以下 16 类。

## C01 Cover Hero

大标题 + 项目主视觉 + 少量身份信息。

---

## C02 Problem / Pain Point

不要三个完全一样的卡片。

推荐：

```text
一个核心场景
+
三个非对称问题点
+
底部一句结论
```

---

## C03 Solution Transformation

非常适合比赛：

```text
Before / Input
       ↓
Core Solution
       ↓
After / Value
```

或者：

```text
Problem → StateBus → Result
```

---

## C04 Core Architecture Hero

标题 + 70% 大架构图 + 右/下简短说明。

技术答辩高频版式。

---

## C05 Mechanism Explain

左：

```text
复杂流程图 / sequence
```

右：

```text
3 个机制结论
```

适合讲单个关键技术。

---

## C06 Innovation / Key Contributions

不是普通四卡片。

推荐：

```text
1 个主创新
+
2–3 个辅助创新
```

主次明确。

---

## C07 Comparison / Differentiation

适合：

```text
Traditional
vs
StateBus
```

或者：

```text
Baseline
vs
Our Method
```

---

## C08 Model / Scheme Choice

比赛里很常见：

```text
候选方案
+
判断指标
+
最终选择
+
真实部署/实验依据
```

可做 Decision Matrix。

---

## C09 Version / Iteration Story

三阶段：

```text
V1
→ V2
→ V3
```

每阶段：

- 一个真实产物；
- 一个改进点；
- 一个效果。

---

## C10 System Showcase

大截图为主。

推荐：

```text
1 张主截图
+
2 张局部截图
+
3 个 numbered callout
```

截图本身应比文字更大。

---

## C11 Experiment Claim + Chart

一张原生图表为主。

标题直接写结论。

---

## C12 Multi-Experiment Evidence

适合：

- Evidence Matrix
- 机制覆盖矩阵
- 多实验总览

---

## C13 Big Number Proof

例如：

```text
39.05%
```

旁边只放：

- 指标是什么；
- 对照是什么；
- denominator；
- 一句解释。

---

## C14 Evidence Wall

比赛材料里很有用。

适合：

- GitHub
- 实验记录
- 软件截图
- 测试记录
- 文档
- 证书/成果

按“证明什么”分组，而不是按文件类型堆照片。

---

## C15 Roadmap / Next Step

区分：

```text
DONE
IN PROGRESS
NEXT
```

避免普通五格时间轴。

---

## C16 Conclusion / Q&A

推荐：

```text
核心结论
技术证据
项目边界
GitHub / QR
```

比纯 Thank You 页更有效。

---

# 7. 最值得参考的“竞赛类”GitHub

## competition-ppt-template-first-skill

https://github.com/che626/competition-ppt-template-first-skill

这是目前检索到最贴近“竞赛答辩”的参考。

它不是一套固定 PPTX 主题，而是一套**竞赛页面构图方法**。

重点文件：

```text
skills/competition-ppt-template-first/references/layout-archetypes.md
skills/competition-ppt-template-first/references/workflow.md
skills/competition-ppt-template-first/templates/layout-registry.md
skills/competition-ppt-template-first/templates/slide-blueprint.md
skills/competition-ppt-template-first/templates/data-evidence-plan.md
```

最值得借的 Layout Archetypes：

```text
Cover: hero scene + identity
Pain-point: three failures around a visual scene
Solution: central visual transformation
Model choice: decision matrix + deployment evidence
Iteration: version story
System showcase: screenshots as anchor
Evidence wall: artifact-led proof
Roadmap: grounded next steps
```

这组比“学术论文汇报模板”更适合比赛。

### 需要调整的地方

该仓库比较强调“整页背景模板图”。

StateBus 不需要完全照做。

我们建议：

```text
竞赛页型 / 阅读顺序 / 页面节奏
        ↓
借用

整页 AI 背景图
        ↓
不作为默认
```

技术页仍以：

- 原生 PPTX
- Draw.io SVG
- 真实截图
- 原生图表

为主。

---

# 8. 原生 PPTX：最值得直接参考的模板库

## wuhua2026/ppt-templates

https://github.com/wuhua2026/ppt-templates

优点：

- 大量真实 `.pptx`
- 分类丰富
- 适合直接观察页面几何关系

最值得取用的不是颜色，而是：

```text
content geometry
visual ratio
title / diagram / chart placement
```

### 推荐 Content 模板

```text
templates/static/content/comparison_blue_technology.pptx
templates/static/content/comparison_ocean_blue.pptx

templates/static/content/four_grid_blue_technology.pptx
templates/static/content/four_grid_minimalist_bw.pptx

templates/static/content/text_image_layout_blue_technology.pptx
templates/static/content/text_image_layout_ocean_blue.pptx

templates/static/content/three_column_blue_technology.pptx
templates/static/content/three_column_minimalist_bw.pptx

templates/static/content/full_image_overlay_blue_technology.pptx
```

### 推荐 Timeline

```text
templates/static/timeline/horizontal_blue_technology.pptx
templates/static/timeline/vertical_blue_technology.pptx
```

### 推荐 Directory

```text
templates/static/directory/timeline_style_blue_technology.pptx
templates/static/directory/sidebar_blue_technology.pptx
```

### 使用方式

不要整套拷贝 Master。

只提取：

```text
x / y / w / h
字体层级关系
主图占比
文本块比例
```

然后在 SynapseX 母版上重建。

---

# 9. 真实 Native PPTX Pitch Deck 参考

## docxology/template-pitch-deck

https://github.com/docxology/template-pitch-deck

仓库直接提供真实 PPTX：

```text
output/pptx/template_template_pitch_short.pptx
output/pptx/template_template_pitch_medium.pptx
output/pptx/template_template_pitch_long.pptx
```

它不是传统“创业融资模板”，更接近：

```text
技术项目
科研工程
证据驱动 pitch
```

可借：

- short / medium / long deck 结构
- section
- content
- stat
- diagram
- quote
- 一页一个主要论点
- 图表/diagram 做主视觉

它的原生布局类型只有 6 类：

```text
title
section
content
stat
quote
diagram
```

### 适合参考什么

- 技术项目怎样保持简洁；
- 大数字页；
- diagram-first 页；
- evidence-led pitch。

### 不适合直接照搬

- 视觉较克制；
- 不够“比赛舞台化”；
- 页面类型不足以独立覆盖复杂系统答辩。

所以它应作为：

```text
Native PPTX engineering + pitch discipline reference
```

而不是唯一视觉模板。

---

# 10. Academic 模板：降级为“工程实现参考”

## yctrrr/academic-ppt-template

https://github.com/yctrrr/academic-ppt-template

不再把它当主视觉参考。

它仍然很值得保留，因为它展示了：

- 原生 PPTX
- native charts
- native arrows
- reusable template kit
- layout validation
- editable objects

重点：

```text
assets/template-kit/ppt-template.js
assets/template-kit/flow-charts.js
assets/template-kit/academic-research-flow.js
references/slide-patterns.md
references/style-spec.md
```

尤其值得借：

```text
固定 anchor
复用组件
避免每页重新算箭头
```

视觉颜色和学术页型不需要照搬。

---

# 11. Codex PPTX 框架参考

## zythum/pptxgen-ts-starter

https://github.com/zythum/pptxgen-ts-starter

建议参考其工程组织：

```text
src/token/
src/components/
src/slides/
.deck/
scripts/estimate-text.ts
scripts/color-tool.ts
```

适合建立自己的：

```text
StateBus PPT codebase
```

而不是用它的默认设计。

---

# 12. PPT 工作流参考

## Quicklime555/academic-report-pptx

https://github.com/Quicklime555/academic-report-pptx

虽然定位偏 academic，但工作流仍然值得保留：

```text
读取现有模板
→ 提取视觉系统
→ 页型规划
→ 代表页
→ 批量生成
→ render QA
```

只借 workflow，不借学术风格。

---

# 13. 原生图表参考

## PptxGenJS

https://github.com/gitbrent/PptxGenJS

Chart 示例：

https://github.com/gitbrent/PptxGenJS/blob/master/demos/modules/demo_chart.mjs

适合：

```text
Bar
Column
Line
Area
Scatter
Bubble
Radar
Combo
Doughnut
```

StateBus 推荐优先：

```text
Bar
Column
Line
Combo
```

Pie / Doughnut 不作为默认。

---

# 14. 比赛实验页建议预制的 Chart Patterns

建议至少 10 个。

```text
01 Paired Bar
02 Grouped Column
03 Dumbbell
04 Slope
05 Small Multiples
06 Lifecycle Strip
07 Pipeline Counts
08 Evidence Matrix
09 Benefit / Cost
10 Annotated Scatter
```

其中：

### Native PPT 优先

```text
Paired Bar
Grouped Column
Line
Simple Combo
```

### SVG 优先

```text
Dumbbell
Slope
Evidence Matrix
Heatmap
Lifecycle Strip
Complex Small Multiples
```

---

# 15. 比赛 PPT 最重要的“页面节奏”

可以直接借 `competition-ppt-template-first-skill` 的思路：

```text
anchor
dense
breathing
```

## Anchor

强主视觉 / 强结论。

适合：

- 封面
- 总架构
- 核心机制
- 最强实验结果

## Dense

多证据但仍有阅读顺序。

适合：

- Evidence Matrix
- System architecture
- 多实验总览
- 技术细节

## Breathing

低信息量过渡。

适合：

- 章节页
- 单句结论
- 大数字
- 关键转场

建议避免连续 5 页都是 dense。

---

# 16. 建议的 Competition Native Layout Kit

最终在 SynapseX 母版中做一份：

```text
statebus-layout-kit.pptx
```

建议页型：

```text
L01 Hero Cover
L02 Section Divider
L03 Pain Point
L04 Solution Transformation
L05 Architecture Hero
L06 Mechanism Explain
L07 Innovation
L08 Comparison
L09 Decision Matrix
L10 Version Story
L11 Screenshot Showcase
L12 Result Chart
L13 Multi-Evidence
L14 Big Number
L15 Evidence Wall
L16 Roadmap
L17 Conclusion
```

Codex 后续不要从 Blank Slide 自由设计。

优先：

```text
复制 Layout
→ 填内容
→ 替换图
→ QA
```

---

# 17. 母版颜色处理

外部模板颜色全部忽略。

Codex 应先从当前 SynapseX PPTX 提取：

```text
style-tokens.json
```

至少包含：

```text
background
surface
text-primary
text-secondary
primary
secondary
state
memory
ref
warning
border
```

所有：

- XML
- SVG
- chart
- native shape

都使用这套 token。

---

# 18. Codex 最终选择规则

## 复杂流程 / 架构

```text
Draw.io XML
→ SVG
→ PPT
```

## 普通比赛页面

```text
SynapseX native layout
→ PowerPoint text / shapes / image
```

## 普通统计图

```text
Native PPT Chart
```

## 特殊实验图

```text
programmatic SVG
```

---

# 19. 推荐工作区目录

```text
presentation/
├─ master/
│  ├─ synapsex-master.pptx
│  ├─ statebus-layout-kit.pptx
│  ├─ style-tokens.json
│  └─ visual-rules.md
│
├─ templates/
│  ├─ drawio/
│  │  ├─ flow/
│  │  ├─ architecture/
│  │  ├─ sequence/
│  │  └─ lifecycle/
│  ├─ charts/
│  └─ competition-layouts/
│
├─ diagrams/
│  ├─ source/
│  └─ rendered/
│
├─ icons/
└─ template-manifest.yaml
```

---

# 20. Template Manifest 示例

```yaml
runtime_swimlane:
  type: drawio
  source: templates/drawio/flow/runtime-swimlane.drawio
  output: svg

system_architecture:
  type: drawio
  source: templates/drawio/architecture/system-component.drawio
  output: svg

competition_solution:
  type: pptx-layout
  source_slide: L04

architecture_hero:
  type: pptx-layout
  source_slide: L05

result_chart:
  type: pptx-layout
  source_slide: L12

dumbbell:
  type: svg-chart

paired_bar:
  type: ppt-native-chart
```

---

# 21. 推荐保留的 GitHub 参考清单

## Draw.io / Architecture

- https://github.com/jgraph/drawio-diagrams
- https://github.com/jgraph/drawio
- https://github.com/kaminzo/c4-draw.io
- https://github.com/jgraph/drawio-libs

## Competition / Pitch Layout

- https://github.com/che626/competition-ppt-template-first-skill
- https://github.com/wuhua2026/ppt-templates
- https://github.com/docxology/template-pitch-deck

## PPTX Engineering

- https://github.com/yctrrr/academic-ppt-template
- https://github.com/zythum/pptxgen-ts-starter
- https://github.com/Quicklime555/academic-report-pptx
- https://github.com/gitbrent/PptxGenJS

## Icons

- https://github.com/lucide-icons/lucide
- https://github.com/tabler/tabler-icons
- https://github.com/simple-icons/simple-icons

---

# 22. 最终建议

这套 PPT 的模板来源可以分成三层：

```text
SynapseX Master
      ↓
颜色 / 字体 / Logo / 页脚

Competition Layout Kit
      ↓
竞赛叙事与普通页面构图

Technical Diagram Kit
      ↓
复杂架构 / 流程 / 时序 / 生命周期

Chart Kit
      ↓
实验数据
```

其中最值得新增的是：

> **Competition Layout Kit**

因为 Draw.io 技术图本身并不是现在最大的风险；真正容易“AI 味重”的，是普通 PPT 页面。

因此后续建议优先完成：

1. 从 SynapseX 母版提取 style tokens；
2. 建 15–17 个竞赛原生 PPTX layout；
3. 收集 20 个 Draw.io 基础模板；
4. 建 10 个实验图表 pattern；
5. 用 `template-manifest.yaml` 让 Codex 自动选模板。

这样 Codex 后续不是“画一页 PPT”，而是：

```text
识别页面任务
→ 选择比赛页型 / 技术图模板 / Chart Pattern
→ 映射母版
→ 生成
→ Render QA
```

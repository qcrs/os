# 实验部分：结果怎么讲、证据在哪里

这份文档用于准备答辩中的“项目测试”部分。它先固定实验的口径和顺序，再决定图表。答辩只使用已经整理好的最终汇总和逐任务索引，不从 `runs/` 目录重新挑选结果。

结果读取顺序固定为：先看 [`docs/experiments/results.md`](../experiments/results.md) 的汇总表，再按需要查看 [`tests/evidence/`](../../tests/evidence/) 下的机器可读聚合和逐任务记录。`runs/` 只保留作来源追溯，答辩制图不依赖它。

## 一、实验部分要回答的三个问题

实验部分让评委依次得到三个结论：

1. StateBus 能把一项多步骤、多角色任务完整跑完，结果质量保持不变。
2. 在同一批任务上，结构化交接、State、Memory 和执行路径减少了重复搬运、重复生成和重复计算。
3. Embedding、Logit、APC、显式 KV 这些非文本路径确实被运行时消费，并在各自的长文本或证据选择场景中产生可测量的结果。

这三个结论对应三种证据：主线对照、机制记录、模型侧专项。三组实验的任务集合和对照不同，数字按各自分母报告。主线采用后来补做并整理出的最终汇总：24 组匹配任务、48 个执行位置，两种配置的质量均为 `24/24`。早期的 `23/24` 轮次属于过程记录，不进入答辩图表和结论。

## 二、四页的整体安排

| 页次 | 页面主题 | 评委在这一页得到的结论 | 主要证据 |
| --- | --- | --- | --- |
| 1 | 实验设置与任务范围 | 测试覆盖了什么环境、多少轮任务、什么对照 | openEuler、Qwen3-32B、24 对匹配任务、任务族和指标 |
| 2 | 24 组同任务对照 | 质量保持，StateBus 的整体请求、Token、生成和时延开销下降 | `SB-FULL` / `P-TEXT` 的总体和逐任务结果 |
| 3 | 主链运行记录 | 结构化交接、Memory 复用、DSL/CodeAct 执行都有实际运行记录 | carrier、Memory 事件、DSL/CodeAct showcase |
| 4 | 非文本与模型侧专项 | 不同中间状态分别承担证据选择、候选展开和模型计算复用 | Embedding/State、Logit、APC、显式 KV 对照 |

四页的关系很简单：第一页交代比较条件，第二页给出总结果，第三页展示主链里发生过什么，第四页补充长文本和非文本机制的专项证据。

---

## 三、第一页：实验设置与任务范围

### 页面主题

**实验设置：同一套任务、两种协作方式、三层证据。**

第一页的职责是让评委知道后面每个数字的分母和来源。页面上不展开 State、Memory 或 APC 的实现细节。

### 环境

展示以下信息即可：

| 项目 | 本轮设置 |
| --- | --- |
| 操作系统 | openEuler 24.03 LTS-SP3 |
| 系统 | StateBus Runtime、Worker 和执行组件 |
| 模型服务 | Qwen3-32B，vLLM，OpenAI-compatible API |
| 主线任务 | `finance` F01–F12、`service_ops` O01–O12 |
| 主线执行量 | 24 个任务对，`SB-FULL` 与 `P-TEXT` 各执行一次，共 48 个位置 |
| 逻辑角色 | Planner、Retriever、Executor、Summarizer；每个任务至少经过检索、执行、总结三个步骤 |

主线采集日期为 `2026-09-27`。模型侧专项使用单独的长文本 utility suite，不能和 48 个主线位置合并计算。

### 两种主线配置

| 配置 | 协作方式 | State / Memory |
| --- | --- | --- |
| `SB-FULL` | Runtime 中的 typed object、结构化请求和对象引用 | 开启并记录状态生命周期和 Memory 事件 |
| `P-TEXT` | 相同任务、相同输入和质量门，Agent 交接使用 UTF-8 JSON text | State、Memory 关闭，作为纯文本对照 |

两种配置的输入文件、任务顺序和最终质量判断保持一致。对照关注请求数、模型 Token、Executor 生成次数、修复次数、端到端时延和消息 carrier。

### 任务到底做了什么

主线使用两类合成但有明确数据口径的连续任务。每个任务都由 Retriever 准备资料，Executor 按固定输出合同处理数据，Summarizer 生成带引用的结果。任务之间通过历史 Artifact 或 Memory 形成关联。

#### `finance`：按月核算、对比预算、汇总历史结果

输入包含期间、业务单元、收入、退款和成本等 CSV，以及定义和说明文档。输出保持 `period`、`unit_id`、`revenue_cny`、`cost_cny`、`profit_cny` 等结构化字段。

| 任务 | 任务内容 | 连续关系 |
| --- | --- | --- |
| F01、F02 | 分别汇总 2026-01、2026-02 各业务单元的收入、退款、成本和利润 | 建立前两期可复用结果 |
| F03 | 计算 2026-03，并按 `unit_id` 接入 F01、F02 的两期收入，形成三期序列 | 使用两个历史结果 |
| F04、F05 | 将当前期间收入与历史基线连接，输出差额 | 使用 F01 或 F02 的基线 |
| F06、F07 | 使用 v2 字典处理 2026-04、2026-05 的同类汇总 | 检验版本变化下的执行合同 |
| F08、F09 | 将当期实际收入与预算表连接，输出预算差额 | 处理两个输入表 |
| F10 | 读取已验证的多期结果，按业务单元汇总 2026-01 至 2026-06 的收入、成本、利润和期数 | 使用 F01、F02、F03、F06、F07、F09 的结果 |
| F11 | 在 2026-06 的实际数据和预算上重新计算兼容方法，形成同源审计结果 | 复用方法，重新读取当前输入 |
| F12 | 由另一个 Summarizer 读取 F10 的结构化 Artifact，交叉核对总数并生成带引用的审计报告 | 跨角色消费结构化结果 |

计算规则由任务包固定，例如退款只扣除一次，输出字段和排序也由 output contract 固定。数据中的说明文本用于提供背景，不能直接当作因果结论。

#### `service_ops`：按周统计站点请求和失败，连接计划并汇总历史

输入包含周、站点、请求数和最终失败数的 hourly CSV，以及事件说明、计划表和字典。输出包含 `request_count`、`failed_count`，必要时包含计划差额或历史期数。

| 任务 | 任务内容 | 连续关系 |
| --- | --- | --- |
| O01、O02 | 汇总 W01、W02 各站点的请求数和最终失败数 | 建立前两周结果 |
| O03 | 汇总 W03，并接入 O01、O02 的历史失败数，形成三周序列 | 使用两个历史结果 |
| O04、O05 | 计算当前周与基线周的失败数差额 | 使用 O02 或 O03 的基线 |
| O06、O07 | 使用 v2 字典汇总 W05、W06 | 检验版本变化下的执行合同 |
| O08、O09 | 将 W07、W08 的实际请求数与独立生成的计划表连接，输出计划差额 | 处理实际表和计划表 |
| O10 | 读取 W01 至 W08 的已验证结果，按站点汇总请求数、失败数和期数 | 使用 O01、O02、O03、O05、O06、O07、O08、O09 的结果 |
| O11 | 在 W08 的实际数据和计划上重新计算兼容方法，形成同源审计结果 | 复用方法，重新读取当前输入 |
| O12 | 由另一个 Summarizer 读取 O10 的结构化 Artifact，交叉核对总数并生成带引用的审计报告 | 跨角色消费结构化结果 |

`finance` 和 `service_ops` 各有 12 轮，满足连续任务的要求。前几轮形成可用结果，后几轮使用历史结果、版本变化、预算/计划连接和跨角色审计，能把“记忆和 Artifact 是否真的被使用”落到具体任务上。

### 采集指标

第一页可以用三组小标签说明采集范围：

- **任务结果**：质量门、业务质量、修复次数、端到端时延。
- **模型开销**：provider requests、prompt/completion/total tokens、Executor generations。
- **系统事件**：typed/text carrier、State 的 publish/transfer/consume/release、Memory query/candidate/consumption/replay，以及模型侧的 TTFT、prefill 和 logical input。

---

## 四、第二页：24 组同任务对照

### 页面主题

**24 组同任务对照：质量保持，整体开销下降。**

这一页只承担主线总体结论。所有百分比都来自 24 对匹配任务，不能用单个 F07 或 O07 的结果替代总体数字。

### 总体数字

| 指标 | `SB-FULL` | `P-TEXT` | `SB-FULL` 相对变化 |
| --- | ---: | ---: | ---: |
| 质量通过 | 24/24 | 24/24 | 保持 |
| provider requests | 41 | 60 | 降低 31.67% |
| provider prompt tokens | 60,544 | 103,534 | 降低 41.52% |
| provider completion tokens | 13,636 | 18,168 | 降低 24.94% |
| provider total tokens | 74,180 | 121,702 | 降低 39.05% |
| Executor generations | 17 | 36 | 降低 52.78% |
| Executor repairs | 5 | 12 | 降低 58.33% |
| 24 个任务总耗时 | 1,543.3 s | 2,043.4 s | 降低 24.47% |
| Agent carrier | 89 条 typed object | 108 条 UTF-8 JSON text | 条数降低 17.59% |

`provider tokens` 是模型服务用量，`carrier` 是 Agent 交接记录，两者放在同一页但使用不同标签，避免把模型 Token 当成通信字节。

### 建议的展示顺序

1. 顶部放质量结果：`SB-FULL 24/24`、`P-TEXT 24/24`。这先说明对照的任务结果一致。
2. 中间用四组并列柱状条展示 requests、total tokens、Executor generations、总耗时。每组只放两个数和变化百分比。
3. 底部放 `finance` 与 `service_ops` 的分组结果，让评委看到收益来自两类任务，而非某一个任务族。

分组结果如下：

| 任务族 | `SB-FULL` provider tokens | `P-TEXT` provider tokens | Token 变化 | `SB-FULL` E2E | `P-TEXT` E2E | E2E 变化 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `finance` | 44,968 | 75,275 | 降低 40.26% | 927.1 s | 1,266.4 s | 降低 26.79% |
| `service_ops` | 29,212 | 46,427 | 降低 37.09% | 616.2 s | 777.0 s | 降低 20.69% |

### 逐任务结果怎么准备

总体数字旁边可以放一张 24 行的配对点图，横轴选择 `provider_total_tokens` 或 `e2e_ms`，每一行是 F01–F12、O01–O12，同一行画 `SB-FULL` 和 `P-TEXT` 两个点。这样可以看到每个任务的具体差异，主图仍然保持简洁。

重点任务可以用标注方式突出：

- F02、F07、O02、O07：Memory-on 对照中出现明显的请求和 Token 下降，适合在第三页解释复用事件。
- F10、F12、O10、O12：跨多期 Artifact 汇总和跨角色审计，适合说明连续任务和结构化结果的后续使用。
- F03、F04、F08、F10 等有 repair 的位置：可用于说明完整运行中仍记录了执行尝试和最终质量，不改变总体质量结果。

逐任务图的数据直接来自 `tests/evidence/mainline/tasks.csv`。图表制作时按 `task_id` 配对，不按运行目录的修改时间排序。

### 这一页最后要留下的结论

在 24 组相同任务上，StateBus 保持质量通过，同时减少模型请求、模型输入输出量、Executor 重复生成和总耗时。机制归因放到后两页，第二页只陈列主线总结果。

---

## 五、第三页：主链运行记录

### 页面主题

**主链运行记录：交接、复用和执行都有对应结果。**

这页的重点是“系统确实这样运行过”。它把前面亮点中的三项机制放回同一条主链：结构化对象完成交接，Memory 在连续任务中提供复用，DSL/CodeAct 负责把输入变成下游可用的 Artifact。

### 页面内容

#### 1. 结构化交接

页面上方画一条短链：

```text
PlanProposal → ExecRequest → ArtifactRef → MemoryCommit
```

旁边放两项运行统计：

- `SB-FULL` 主线记录了 89 条 `in_process_typed_object` carrier。
- `P-TEXT` 主线记录了 108 条 `utf8_json_text` carrier，并产生 780,825 个 UTF-8 text bytes。

这里的文字只说明“交接记录是什么、数量是多少”。协议字段和 UDS/Protobuf 的实现已经在亮点部分介绍，实验页不再重复字段表。

#### 2. Memory 复用

使用一个漏斗表示事件先后：

```text
8 个 Memory-on 位置
  → 6 个 candidate hit
  → 4 个 actual consumption
  → 4 个 validated replay
  → 4 个跳过 Executor 生成边界
```

旁边给出 off/on 汇总：

| 指标 | off | on | 变化 |
| --- | ---: | ---: | ---: |
| 质量通过 | 8/8 | 8/8 | 保持 |
| provider requests | 18 | 12 | 降低 33.33% |
| provider tokens | 31,466 | 17,581 | 降低 44.12% |
| 任务耗时总和 | 550.2 s | 401.0 s | 降低 27.12% |
| repair | 2 | 0 | 降低 100% |

逐任务对照可从 `tests/evidence/mechanisms/tasks.csv` 取出。F02、F07、O02、O07 的 on 路径分别出现 50%–66.67% 的 request 减少，适合作为小型实例；最终汇总仍使用 8 个位置的总体数字。

主线 24 个位置还记录了 24 次 Memory 查询、22 次返回候选、132 个候选、12 次 actual consumption 和 12 次 validated replay。这些数字来自主线记录，用于说明连续任务中的 Memory 事件；第三页展示 Memory-on 专项时，使用上面的 8 位置分母。

#### 3. DSL 与 CodeAct

页面底部放一个执行路径对照：

```text
已登记、可表达的操作   → DSL → verified Artifact
超出 DSL 表达范围       → CodeAct fallback → verified Artifact
```

CodeAct showcase 的独立结果是 DSL 3 个样例中 2 个通过，CodeAct fallback 2 个样例中 2 个通过，合计 4/5。这个数字用于说明执行能力的覆盖方式，和 24 对主线的请求、Token、E2E 汇总分开标注。

页面上展示一个 DSL 结果和一个 CodeAct 结果的 Artifact 名称、验证状态和下游步骤即可。CodeAct 的代码内容不放在实验页；评委需要看到的是两条执行路径都能交付 Runtime 继续使用的结果。

### 这页的布局

建议采用“上方一条主链 + 下方两个证据卡”的结构：

- 主链：typed carrier 和 `PlanProposal → ExecRequest → ArtifactRef → MemoryCommit`。
- 左卡：Memory 复用漏斗和 off/on 数字。
- 右卡：DSL/CodeAct 两条路径及独立样例通过数。

State 的 publish/transfer/consume/release 放到第四页的 Embedding/State 专项，避免把状态生命周期和 Memory 复用混成一个事件。

---

## 六、第四页：非文本与模型侧专项

### 页面主题

**非文本路径：选择需要的内容，复用已经算过的内容。**

四个模块放在同一页，但各自有独立场景和对照。它们共同说明中间结果可以由 Runtime 保存、传递、消费，随后服务于下游；它们不组成一条必须连续开启的流水线。

### 页面结构：2×2

|  | 选择输入 | 复用计算 |
| --- | --- | --- |
| 任务侧状态 | Embedding / State：从候选资料中选出证据 | — |
| 模型侧状态 | Logit：决定是否继续展开证据 | APC / 显式 KV：复用长上下文计算 |

也可以把 APC 和显式 KV 放在右侧上下两个小框中，明确它们的实现层次：APC 依赖 vLLM 的公共前缀缓存布局，显式 KV 由 Runtime 交接 parent KV handle。四个专项的百分比按各自对照计算。

### Embedding / State

展示链路：

```text
query/candidate embedding matrix
        ↓ SemanticStateRef
下游进程读取并选择 top-k 行
        ↓ HydrateManifest
原始文本片段 / 表格单元格
        ↓
Executor evidence input
```

四个 semantic holdout 各运行 off/on，共 8 个位置。State-on 记录了 `publish / transfer / consume` 各 10 次，4 个位置全部记录 release；质量通过为 4/4。逻辑 payload/read bytes 均为 221,184。

这一格的图只需要标出 `Ref → 数值矩阵 → row index → 原始证据`，并在旁边放 `publish=10、transfer=10、consume=10、release=4/4`。State-on 任务耗时总和为 593.4 s，off 为 614.5 s；该专项主要展示状态被真实消费并回到证据，端到端收益数字不与主线收益合并。

### Logit

展示三种输入路径的对照：

```text
full context → compact context → logit-selective
```

每个候选选择 case 记录 exact candidate probability、action、是否 expanded、selected candidate 或 abstention。`logit-selective` 使用 `tau=0.10` 和 `other_mass_limit=0.20` 作为选择条件。

4 个 case 共 12 个位置：

- resolved case 中，compact/selective 的 logical input 平均降低 75.21%；
- provider request wall：compact 降低 17.18%，selective 降低 18.51%；
- 9 个 resolved case 通过，3 个位置给出正确 `abstention`。

页面上画一个候选概率条和“保留 / 展开 / abstention”的结果即可。公式、阈值和 exact probability 放在小字或讲解稿中，图的中心是“模型先用紧凑证据判断是否值得展开”。

### APC

APC 专项比较同一长文本 case 的 `apc_on_independent` 和 `apc_on_shared`。四个 case 为 `MU-ORION-4K-COST`、`MU-ORION-6K-COST`、`MU-NOVA-4K-DELIVERY`、`MU-NOVA-6K-DELIVERY`，共 8 个位置。

展示一条公共前缀：

```text
producer context ─┐
                  ├─ shared prefix layout → consumer
consumer context ─┘
```

结果：

- consumer TTFT 从 2,540.2 ms 降到 264.3 ms，降低 89.59%；
- observed hit tokens 从 48 增加到 5,168；
- 完整 task wall 平均降低 4.29%。

APC 的重点是“引擎识别公共前缀并复用”，不是 Runtime 显式搬运 KV。页面上把 shared prefix、hit tokens 和 consumer TTFT 放在同一格即可。

### 显式 KV

显式 KV 使用同一组四个长文本 case，比较 `full_replay` 和 `continuation`。展示链路：

```text
producer capture/store
        ↓ parent KV handle
consumer load/continuation
```

结果：

- computed prefill 从 5,666.5 降到 545.5 tokens，降低 90.37%；
- consumer TTFT 从 2,570.6 ms 降到 1,005.7 ms，降低 60.88%；
- consumer request wall 降低 11.88%，完整 task wall 降低 3.58%；
- continuation 路径记录了平均 store 2,986.4 ms、load 749.0 ms 的资源成本。

这一格让评委看到 Runtime 交接 parent KV 状态、consumer 继续运行并完成同一任务。`full_replay` 与 `continuation` 的分母单独标注。

### 这一页的读法

左侧的 Embedding 和 Logit 都在回答“当前只需要哪些内容”；右侧的 APC 和显式 KV 都在回答“已经算过的长上下文怎样继续使用”。四种机制分别开关、分别测量，图中用四个独立小框表达。

---

## 七、结果文件和读取方法

### 展示时使用的最终汇总

| 内容 | 首选文件 | 用途 |
| --- | --- | --- |
| 实验总说明 | [`docs/experiments/README.md`](../experiments/README.md) | 了解三组实验的分母和阅读顺序 |
| 所有汇总表 | [`docs/experiments/results.md`](../experiments/results.md) | 直接取总体、分组和专项数字 |
| 证据目录说明 | [`tests/evidence/README.md`](../../tests/evidence/README.md) | 确认精选证据的范围 |
| 主线汇总 | [`tests/evidence/mainline/results.md`](../../tests/evidence/mainline/results.md) | 24 对、48 个主线位置 |
| 主线机器结果 | [`tests/evidence/mainline/results.json`](../../tests/evidence/mainline/results.json) | 读取聚合字段 |
| 主线逐任务索引 | [`tests/evidence/mainline/tasks.csv`](../../tests/evidence/mainline/tasks.csv) | 画 F01–F12、O01–O12 的单任务图 |
| 主线逐任务记录 | [`tests/evidence/mainline/tasks.jsonl`](../../tests/evidence/mainline/tasks.jsonl) | 查看每项任务的完整聚合字段 |
| 主线来源清单 | [`tests/evidence/mainline/manifest.json`](../../tests/evidence/mainline/manifest.json) | 确认汇总覆盖范围和 48 条记录 |
| Memory / State 汇总 | [`tests/evidence/mechanisms/results.md`](../../tests/evidence/mechanisms/results.md) | 读取 off/on、事件漏斗和 holdout 结果 |
| Memory / State 机器结果 | [`tests/evidence/mechanisms/results.json`](../../tests/evidence/mechanisms/results.json) | 读取聚合字段 |
| Memory / State 逐位置索引 | [`tests/evidence/mechanisms/tasks.csv`](../../tests/evidence/mechanisms/tasks.csv) | 画逐位置对照 |
| APC / KV / Logit 汇总 | [`tests/evidence/model-assist/summary.md`](../../tests/evidence/model-assist/summary.md) | 读取专项分母和通过情况 |
| APC / KV / Logit 详细报告 | [`tests/evidence/model-assist/report.md`](../../tests/evidence/model-assist/report.md) | 查看逐位置记录和质量结果 |
| APC / KV / Logit 机器结果 | [`tests/evidence/model-assist/metrics.json`](../../tests/evidence/model-assist/metrics.json) | 读取专项聚合指标 |

### 单任务和机制结果从哪里取

逐任务图直接从精选索引读取：

- 主线任务：`tests/evidence/mainline/tasks.csv`，按 `task_id` 配对 `SB-FULL` 和 `P-TEXT`；
- Memory / State：`tests/evidence/mechanisms/tasks.csv`，按各自的 `off/on` 或 holdout 记录取值；
- APC / KV / Logit：`tests/evidence/model-assist/report.md` 和 `metrics.json`，按专项 case 读取。

这些文件已经把每个任务的状态、质量、请求数、Token、耗时和机制事件整理出来。制作图表时直接使用这些字段，不再从 `runs/` 目录重新计算，也不把不同轮次的 slot 混在一起。

`runs/` 只在需要回答“某个数字来自哪次执行、某个事件的原始证据是什么”时使用。它不是答辩结果库，历史 run、试跑、修复检查和不同实验目的的记录都不进入汇总。

CodeAct showcase 也遵循同一规则：先使用已整理的摘要和报告；它是独立的 DSL/CodeAct 小样例，不能并入 24 组主线的总体数字。

模型侧专项的正式汇总入口是 `tests/evidence/model-assist/summary.md`、`report.md` 和 `metrics.json`，其中 APC 8 个位置、显式 KV 8 个位置、Logit 12 个位置，共 28 个计分位置；warmup 和恢复记录不进入这些分母。

## 八、图表制作时的口径

1. 主线总体使用 `docs/experiments/results.md` 和 `tests/evidence/mainline/results.*` 的最终数字；这两处不一致时先检查汇总版本，不去历史 `runs/` 中自行挑选。
2. 逐任务图使用 `mainline/tasks.csv`，按 `task_id` 将 `SB-FULL` 和 `P-TEXT` 配对。
3. Memory / State 使用 `mechanisms` 自己的 16 个 Memory 位置和 8 个 State 位置；不要把 8 个 Memory-on 位置和主线 24 个位置混成一个分母。
4. APC、KV、Logit 分别报告 8、8、12 个位置；它们属于模型侧专项，放在第四页作为补充证据。
5. `provider tokens`、`communication carrier`、`State payload/read bytes` 和 `logical input` 使用不同单位，图例中写全名称。
6. 图中显示“质量通过”和结果数字，讲解时补充任务输入、对照关系和精选证据文件。实验页不放原始 JSON，也不展示 `runs/` 路径。

## 九、暂定讲解顺序

可以用下面四句话串起四页：

1. “我们先固定环境和任务：两类数据、各 12 轮，每轮都有检索、执行和总结，并做一组纯文本对照。”
2. “在 24 组相同任务上，两种配置质量都是 24/24；StateBus 的请求、Token、重复生成和总耗时都更低。”
3. “这些结果在精选记录里都有对应事件：交接使用 typed object，Memory 有候选到 replay 的过程，DSL 和 CodeAct 都能交付可继续使用的 Artifact。”
4. “长文本专项再把四类非文本路径拆开测：Embedding 选择证据，Logit 决定展开，APC 和显式 KV 复用已经算过的上下文。”

讲完四页，评委应当同时看到系统的完整运行结果、单任务证据和专项机制数据；每个数字都能沿着精选汇总文件追到任务记录。

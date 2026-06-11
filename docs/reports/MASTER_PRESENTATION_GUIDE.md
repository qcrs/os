# StateBus 系统讲解总览

日期：`2026-06-11`

**三份文档按"数据→设计→架构"递进。本文档是串联入口。**

---

## 一、文档定位

| 你要讲什么 | 看哪个 | 内容 |
|-----------|--------|------|
| 系统跑出什么结果？ | `benchmark_results_interpretation` | 完整数据 + 每指标含义 + 公平性边界 |
| 系统怎么设计的？测了什么？ | `task_design_and_mode_comparison` | 24 task 设计 + 三层差异矩阵 + pack 分工 |
| 系统内部怎么工作的？ | `architecture_and_data_flow` | 代码架构 + 数据流图 + Agent职责：谁调LLM、谁不调 |

---

## 二、核心数据速查

```
主张              状态        最强证据                         关键数据
──────────────────────────────────────────────────────────────────────
通信效率           ✅ 成立     communication 专用包              ↓15.9% control_bytes
                              formal_controlled fresh_retrieval ↓15.1%
                              (排除replay污染)

状态传递创新        ✅ 成立     text_brief→state_ref             文本握手 ↓59%
                              非文本 0→3671 bytes               真实性成立

记忆复用           ⚠️ 部分    replay_enabled                    ↓12.3% task_ms
                              assist_only                       ❌ 不work

系统完整性          ✅ 成立     24 task repeat-3                 0 failure
                              open_validation                   1.00 expectation
```

---

## 三、讲述路线

### 第1步：一句话定义（30秒）

> StateBus 是四个 Agent（Planner/Retriever/Executor/Summarizer）通过两种模式协作的运行时。text 模拟传统自然语言通信，protocol 用结构化协议通信。同一个任务各跑一遍，控制所有变量，只让通信格式不同——对比开销差异。

### 第2步：三分钟讲架构

1. **控制面 vs 状态面**（`architecture_and_data_flow` §一、§六）
   - 控制面传"谁干什么"（协议消息），线上传输
   - 状态面传"实际数据"（StateRef 指针→mmap），本地零拷贝
   - `handoff_wire_bytes`（线上字节）= 真通信量；`handoff_payload_bytes`（负载字节）= 不是

2. **三个不调LLM的Agent + 一个调的**（`architecture_and_data_flow` §四）
   - Retriever/Executor 不调 LLM：两种模式产出完全相同
   - Summarizer 调 LLM：text 下收到原材料（原始 evidence），proto 下收到加工品（上游提取的结构化结论）——token 差异的来源

3. **三层差异矩阵**（`task_design_and_mode_comparison` §四）
   - 21 个 task：只有消息格式+prompt 不同（握手相同）
   - 3 个 task：多了握手策略不同（text_brief vs state_ref）

### 第3步：两分钟跑结果

1. **通信**→ 见 `benchmark_results_interpretation` §三：protocol 省 15.9% 控制面、21.4% token
2. **状态传递**→ 见 §五：文本握手↓59%，非文本从无到有，wire 仅差81字节
3. **记忆**→ 见 §四：replay 跳过步骤省 12.3%，assist 不 work（诚实标注）

### 第4步：预判评委提问

| 可能问 | 答 | 证据 |
|--------|-----|------|
| "Planner真的会规划吗？" | 受控包不让它干活（控制变量）。开放包真调LLM，全部通过 | open_validation expectation=1.00 |
| "protocol省token是不是因为给了更少信息？" | 不是更少，是更浓缩。上游已提取结论，不需要Summarizer再推理。输出一致证明等价 | expectation_match=1.00 |
| "state_transfer wire才差81字节，意义大吗？" | 因为两者都走StatePool。真正纯文本应内联在消息里。我们诚实标注了这个边界 | 见fairness分析 |
| "assist怎么不行？" | 记忆当额外文本塞给Summarizer，prompt变长→token反而多。我们诚实不claim | memory结果 |

### 第5步：诚实边界（加分项）

"我们在报告里诚实标注了三件事：assist_only不work所以不claim、state_transfer的wire差异来自共享StatePool而非'纯文本通信'、受控包里Planner不工作是为了控制变量。这种诚实性比宣称'全面胜利'更有说服力。"

---

## 四、三个概念不要混

| 概念 | 含义 | 在哪讲 |
|------|------|--------|
| `text vs protocol` | 控制面消息格式+LLM prompt | communication主张 |
| `text_brief vs state_ref` | hybrid握手真实性 | typed_handoff_authenticity |
| `pure_text vs state_ref` | 真纯文本vs结构化 | pure_text_vs_state |

`text_brief` 不是"纯文本baseline"——它把结构化信息写成Key-Value，然后走StatePool传指针。和state_ref共享同一套通信基础设施。

# StateBus Benchmark 结果完整解读

日期：`2026-06-11`
数据来源：`runs/benchmark_suite_20260611_124126_api_repeat3/`
执行方式：live API, repeat=`3`, serialized（时序串行，一次只跑一个 task）

> 当前定位：历史结果解读 / v1-v2 背景材料。本文保留旧 pack 名称、`text_brief -> state_ref` 读法和历史 repeat=3 数据，不能替代当前 v3 active surface。当前 v3 结论请优先看 `README.md`、`tasks/README.md` 和 `docs/reports/task_design_and_mode_comparison.md`，并以 active v3 pack 的 manifest/report/gate 为准。
>
> 还要额外注意三条历史边界：
> 1. 文中关于 `formal_controlled` / `open_validation` 的 pack 组织是历史阶段对象，不是当前 active headline 结构。
> 2. 文中出现的 “Planner 不干活”、“Retriever/Executor 不调 LLM” 只适用于当时的特定历史 pack，不代表当前实现。
> 3. 当前 active communication headline 是 `superiority_comm_v1`，不是本文中的旧 headline/旧 aggregate surface。

---

## 零、为什么要做这个实验

赛题的核心问题是：**结构化通信协议替代自然语言交互，到底有没有省开销？省了多少？非文本状态传递到底存不存在？共享记忆到底能不能复用？**

要回答这些问题，不能只跑一遍——需要设计一个**可复现的对比实验**：

1. **同一个 task 跑两遍**——一遍 text 模式（模拟传统自然语言通信），一遍 protocol 模式（结构化协议通信）
2. **所有其他变量必须控制住**——同一个 plan、同一个 corpus、同一个 LLM、同样的记忆策略
3. **跑多轮取平均**——repeat=3，消除 API 波动
4. **多个 pack 分别验证不同主张**——不能把所有问题混在一个实验里回答

**受控包（`formal_controlled`）是什么**：这是历史阶段对象。它固定所有变量，只让通信格式不同；当时 Plan 来自 YAML 文件，因此当时那个对象里 Planner 不参与 LLM 规划。这个描述只适用于该历史包，不能外推到当前 active communication headline。

**开放包（`open_validation`）是什么**：放开变量，让 Planner 真调 LLM 生成 Plan，测试 route 歧义处理、低信度拒绝等边界行为。目的：**证明系统在开放场景下也能正常工作，不是只会跑脚本化的假动作。** 标记为 `support_only`——不参与正式 headline claim，只做答辩佐证。

---

## 一、最终结论

四条分开的读法，不混成一句总 headline：

| 读法 | 判断 | 这个实验说明了什么 |
|------|------|-----------------|
| `communication`（通信效率） | ✅ 成立 | 结构化协议确实比自然语言省：控制面消息更紧凑 + LLM prompt 更短 = 省了 15.9% 控制面字节和 21.4% token |
| `typed_handoff_authenticity`（结构化握手真实性） | ✅ 成立 | Retriever→Executor 用结构化 state_ref 代替文本描述，Executor 能正确消费，文本依赖下降 59%，非文本状态从无到有 |
| `pure_text_vs_state`（纯文本vs结构化） | ⚠️ 正式补齐，但 state 不更轻 | 真·自然语言握手已纳入对比。state_ref 让非文本状态出现，但从 carrier 成本看更重——不支持低开销 headline |
| `memory replay`（记忆复用的回放效果） | ⚠️ 部分成立 | replay_enabled 跳过步骤后省了 12.3% 时间。但 assist_only（查记忆当参考但不跳步）没有效果——不能 claim |

**诚实边界**：
- `protocol` 在通信侧更省（`control_bytes`↓15.7%, `llm_total_tokens`↓21.4%）
- `state_ref` 的 typed handoff 真实性成立（文本握手↓59%，非文本从无到有）
- 当前 `state_ref` 不能讲成"相对 pure text 的低开销胜利"——它走的是相同的 StatePool 基础设施
- 记忆层只 headline `replay_enabled / skipped_step_count`（跳过步骤数），不包括 `assist_only`

---

## 二、跑分环境

| 参数 | 值 | 说明 |
|------|-----|------|
| LLM | `deepseek-v4-flash` | Planner/Summarizer 共用。受控包 Planner 不调 |
| 编码器 | `Qwen3-Embedding-0.6B` | 本地运行，1024维向量 |
| StatePool | `MMAP_FILE` | 文件映射共享内存——数据面存储 |
| Executor | `local` | 本地 subprocess |
| Repeat | `3` | 每个 pack 跑 3 轮取平均 |
| Mode schedule | `paired_round_robin_alternating` | 每轮 text→proto 交替，消除时序偏差 |

---

## 三、指标速查——每个字段是什么意思，怎么看

### 3.1 核心对比指标

| 英文 | 中文 | 什么意思 | 怎么看 |
|------|------|---------|--------|
| `control_bytes` | 控制面字节数 | Agent 间协议消息（Plan/PlanStep/StepResult/Ack 等）全部序列化后的总字节数。**通信开销的核心指标** | ↓ 越小越好。text/proto 的差异就是"纯通信格式"省的 |
| `state_bytes` | 状态面字节数 | StatePool 中所有 StateRef payload 的总字节数。**不是通信量**——是本地 mmap 文件大小 | 一般不看绝对值，只看 text/proto 是否有异常差异 |
| `llm_total_tokens` | LLM 总 token | 调用 API 消耗的 token 总数。在本文对应的历史受控包里，主要来自 Summarizer，因为当时 Planner 不参与 LLM 规划 | ↓ 越小越省钱省时 |
| `task_ms` | 单任务耗时（毫秒） | 从 task 开始到结束的墙上时间 | ↓ 越小越快 |
| `memory_hit_rate` | 记忆命中率 | 查共享记忆时找到结果的比例。1.0=每次都命中 | 命中≠收益——assist 有命中无加速 |
| `skipped_step_count` | 跳过步骤数 | 因 replay 匹配成功跳过的 step 数。>0 说明记忆复用触发了跳步 | 只在 `replay_enabled` 策略下有意义 |
| `reuse_gain` | 复用收益比 | 跳过步骤数 ÷ 总步骤数。0.33=省了 1/3 步骤 | 越大越好，配合 `skipped_step_count` 看 |
| `expectation_match_rate` | 期望匹配率 | benchmark 中 task 的预期行为（如预期 assist、预期 reject）与实际行为的一致性 | 必须 = 1.00 |
| `failure_count` | 失败数 | task 执行异常数 | 必须 = 0 |

### 3.2 握手（handoff）相关指标——⭐ 这是新版加入的

旧版只有一个笼统的 `handoff_bytes`，错误地把 StatePool 存储量当通信量。新版拆成了线上和本地：

| 英文 | 中文 | 是通信量？ | 什么意思 |
|------|------|:---:|---------|
| `handoff_wire_bytes` | 握手线上字节 | ✅ 是 | StateRefLite 指针（state_id+kind+length）protobuf 序列化后的字节数。**每个指针约 50-80 字节**——这才是 Agent 间真实传输的 |
| `handoff_payload_bytes` | 握手负载字节 | ❌ 不是 | StatePool 中 mmap 文件的 payload 大小。Executor 本地 mmap 读取——不占线 |
| `handoff_textual_bytes` | 文本握手字节 | ❌ 不是 | DENSE_EVIDENCE + TOOL_ARTIFACT 类 payload 大小。text 模式下这个值大=文本依赖重 |
| `handoff_nontext_bytes` | 非文本握手字节 | ❌ 不是 | FEATURE_BUNDLE + EMBEDDING 等结构化 payload 大小。>0 = 非文本状态存在 |

**关键边界**：`wire`（线上字节）= 真正的 Agent 间通信开销。`payload`（负载字节）= 本地共享内存读取量。**两者差了 20-50 倍**——指针只有几十字节，payload 有几千字节。

### 3.3 头部元数据

| 英文 | 中文 | 说明 |
|------|------|------|
| `Task pack type` | 包类型 | `formal`=可进入正式 claim，`support_only`=仅供诊断 |
| `Continuous tasks per run` | 每轮连续 task 数 | 同一轮内串行执行的总数 |
| `Mode-specific task counts` | 每种模式执行的 task 数 | **text 和 proto 应该相等才公平**。不相等说明有 task 只在一种模式下跑 |
| `Benchmark lane counts` | 各赛道 task 数 | 当前：communication=6, state_transfer=3, memory=3, internal_regression=12 |
| `Claim lanes` | 该包声称的主张 | 当前必须分 lane 解读，不能混成一句话 |
| `Artifact expectation counts` | 产出预期数 | 启用了多少 misfire audit 检查（route/tool/doc 等是否匹配预期） |

---

## 四、`communication`（通信效率）—— ✅ 成立，证据最干净

### 4.1 这个实验说明了什么

**问题**：结构化协议替代自然语言，到底省了多少通信开销？

**实验设计**：6 个 task，memory 全部禁用，握手全部固定 `state_ref`。**只有一个变量——控制面消息格式 + LLM prompt 格式。** text 用自然语言，protocol 用紧凑协议。

`communication` 专用包（2 task × r3，最干净）：

```
              text        proto       节省        节省率
control_bytes  6,847       5,758       ↓1,089      ↓15.9%
llm_tokens     482         387         ↓96         ↓19.9%
task_ms        4,611ms     3,988ms     ↓623ms      ↓13.5%
failure_count  0           0
```

**这个数据说明**：即使只跑 2 个最干净的 task，protocol 也比 text 省 15.9% 控制面、19.9% token、13.5% 时间。**这是通信效率主张的单点最强证据。** 变量控制到了极限——握手相同、memory 禁用、只有通信格式不同。

### 4.2 总门面 `formal_controlled` 复现同方向（24 task × r3）

```
                  text          protocol      节省量        节省率
control_bytes      166,466       140,327       ↓26,139       ↓15.7%
llm_total_tokens   11,588        9,111         ↓2,477        ↓21.4%
task_ms            102,892ms     92,406ms      ↓10,486ms     ↓10.2%
message_count      285           285           完全相同       ← task 数相同
failure_count      0             0
```

**这个数据说明**：在 24 个 task 的综合门面上，协议优势方向与专用包一致。更大的样本量，同样的结论。

### 4.3 排除 replay 干扰——`fresh_retrieval` vs `step_skipping`

**问题**：protocol 的优势是不是因为"跳过了步骤"（replay 效果），而不是"通信格式"本身？

**实验设计**：把 24 个 task 分成两组——检索真实执行、没有跳步的 task（`fresh_retrieval`），和因为 replay 跳了步骤的 task（`step_skipping`）。分别看协议优势。

```
                    text控制面   proto控制面   节省      proto耗时节省
──────────────────────────────────────────────────────────────────
fresh_retrieval     6,881        5,840         ↓1,041    ↓425ms
step_skipping       6,878        5,684         ↓1,194    ↓482ms
```

**这个数据说明**：即使在 `fresh_retrieval` 上（检索真实执行、没有跳步），protocol 仍然省了 15.1% 控制面。**协议优势不是靠 replay 作弊来的**——在步骤完整执行的情况下同样成立。

### 4.4 为什么能省——机制解释

```
三个层面的节省:
  ✅ 层面1（控制面消息）: 自然语言字符串 → protobuf 二进制 → control_bytes ↓
  ✅ 层面2（LLM prompt）: "你是纯文本协作环境中..." → "sb-summary-v1:..." → tokens ↓
  ❌ 不靠: Planner差异（planner_requests=0）、replay跳步（已排除）
  
省的不是因为"少干了活"——Retriever 和 Executor 在两种模式下干的事完全相同。
省的是"把内部状态文本化再让下游重新理解"的往返。
```

---

## 五、`memory`（记忆复用）—— ⚠️ 部分成立

### 5.1 这个实验说明了什么

**问题**：共享记忆能不能让后续 task 更快？

**实验设计**：3 个 task，都是 protocol-only，同一个 query。但给不同的记忆策略——一个完全不查记忆（baseline），一个查记忆当参考但不跳步（assist），一个查记忆匹配后直接跳过步骤（replay）。

`memory` 专用包（protocol-only, 3 task × r3）：

```
策略              耗时       token   命中率  跳过步  复用收益  说明
──────────────────────────────────────────────────────────────────
memory_off        4,488ms    395     0.00    0       0.00      ← 基线：不查记忆
assist_only       4,440ms    452     1.00    0       0.00      ← 查到了但不跳步
replay_enabled    3,934ms    382     0.00    1       0.33      ← 匹配跳步
```

### 5.2 为什么 assist_only 不 work

**根因**：assist 命中记忆后，把记忆内容当"额外参考文本"塞给了 Summarizer。Summarizer 的 prompt 变长了 → token 反而从 395 涨到 452 → 省下的检索时间被 Summarizer 多吃的 token 抵消了。

**启示**：记忆命中 ≠ 收益。只有 replay（匹配后直接跳过步骤）才真正省时间。assist 是"好心办坏事"——信息多了，LLM 反而处理更慢。

### 5.3 正确口径

可以 claim：`replay_enabled / skipped_step_count`——跳过 1 步，节省 12.3% 时间。
不能 claim：`assist_only` 有任何收益。

---

## 六、`state_transfer`（状态传递）

### 6.1 这个实验说明了什么

**问题**：用结构化数据（state_ref）代替文本描述（text_brief），来实现 Agent 间的中间状态传递——这件事到底能不能做？效果如何？

**两层实验**：
- **authenticity**：证明 state_ref 是"真实的"——Executor 能消费它，文本依赖确实下降了
- **pure_text**：用更诚实的 baseline（真正的自然语言，不是格式化的 Key-Value）来重新对比

### 6.2 authenticity（结构化握手真实性）—— ✅ 成立

**先理解"真实性"在测什么**：

赛题要求"实现一种非文本中间状态传递机制，支持 embedding、语义向量或其他中间表示在 Agent 间直接交换，并说明其生成方式、传递方式、接收方式及后续使用方式"。

"真实性"回答的问题是：**Retriever 用结构化数据（state_ref）代替文本描述（text_brief）传给 Executor——这件事到底是真的在发生吗？Executor 能正确理解和使用这些结构化数据吗？文本依赖真的下降了吗？**

这个实验在 protocol 模式下，对同一个 task 跑两种握手方式，看 Executor 的行为是否一致。

**表格每一列的含义**：

```
                  text_brief (文本握手)          state_ref (结构化握手)
                  ──────────────────           ──────────────────────
Retriever做的:    构建 Key-Value 文本           构建 msgpack 结构化 blob
                  "Route: cache_invalidation    {route:"cache_invalidation",
                   Tool: fix_cache              tool:"fix_cache",
                   Confidence: 0.92"            confidence:0.92, ...}
                  写入 StatePool → 1个指针     写入 StatePool → 5个指针

Executor收到的:   1个 TOOL_ARTIFACT             1个 FEATURE_BUNDLE + 
                  (Key-Value文本)               1个 TOOL_CANDIDATE_SET +
                                               1个 RANKED_EVIDENCE +
                                               1个 REPLAY_ELIGIBILITY +
                                               1个 EMBEDDING

Executor做的事:   解析文本 "Route:\s*(.+)"      直接读字段 bundle["route"]
                  → 正则提取字段                 → 直接使用
                  → 选 tool                      → 选 tool
```

**具体数据**：

```
handoff策略   控制面    线上握手    负载字节    文本握手    非文本     耗时
             (总消息)  (指针字节)  (mmap大小)  (文本payload) (结构化)   (端到端)
──────────────────────────────────────────────────────────────────────────
text_brief     5,012     123        1,830       1,830        0        4,445ms
state_ref      5,757     204        4,443        772        3,671     4,624ms
差异            +745     +81        +2,613      ↓1,058      +3,671    +179ms
```

**逐列解读**：

- **`控制面`（`control_bytes`，总消息字节）**：text_brief=5,012, state_ref=5,757。state_ref 多 745 字节——因为 StepResult 的 `output_state_refs` 有 5 个 StateRef 而非 1 个，序列化出来的 StepResult 消息体积稍大。

- **`线上握手`（`handoff_wire_bytes`，StateRef 指针字节）**：text_brief=123, state_ref=204。差异仅 81 字节——1 个指针 vs 5 个指针。**这才是 Agent 间真实的通信量——几十到一百多字节，不是几千字节。**

- **`负载字节`（`handoff_payload_bytes`，mmap 文件大小）**：text_brief=1,830, state_ref=4,443。差异 +2,613 字节。这不是通信量——是 StatePool 里 mmap 文件的 payload 大小。state_ref 更大是因为存了 5 种 blob。**这个数字不要理解为"通信开销"。**

- **`文本握手`（`handoff_textual_bytes`，文本类 payload 大小）**：text_brief=1,830, state_ref=772。**↓1,058 字节（↓59%）**。Executor 在 state_ref 下收到的文本描述从 1,830 字节降到了 772 字节。**文本依赖大幅减少。**

- **`非文本`（`handoff_nontext_bytes`，结构化 payload 大小）**：text_brief=0, state_ref=3,671。**从 0 到 3,671。** 非文本的中间状态确实在 Agent 间传递了——FEATURE_BUNDLE、TOOL_CANDIDATE_SET 等 msgpack blob。

- **`耗时`（`task_ms`，端到端时间）**：text_brief=4,445ms, state_ref=4,624ms。+179ms，基本持平。Executor 多读了几个 StateRef 的 payload，但总时间影响很小。

**这个数据证明了什么（可以说的）**：

1. **真实性成立**：Executor 在两种握手方式下选了相同的 tool，做了相同的决策（`expectation_match`=1.00）。结构化握手不是花架子——它真的能工作。

2. **文本依赖下降了 59%**：Executor 不再需要消费大段文本描述来做决策。从"收到一段 Key-Value 文本→自己解析"变成了"直接读结构化字段"。

3. **非文本状态从无到有**：`handoff_nontext_bytes` 从 0 涨到 3,671。系统确实在 Agent 间传递了非文本的中间状态——满足了赛题"实现非文本中间状态传递机制"的要求。

4. **通信层面差异极小**：线上指针字节只差了 81 字节。不是因为"结构化传递更省通信"——而是因为两者都走 StatePool（共享内存→指针），通信路径相同。

**这个数据不能证明什么（不能说的）**：

- "state_ref 比文本更轻"——payload 更大（+2,613），控制面也更大（+745）
- "typed handoff 已经打败了纯文本协作"——这里的 text_brief 不是真·自然语言，它走的是和 state_ref 相同的 StatePool 基础设施

**这个对比的本质**：不是"结构化通信 vs 自然语言通信"，而是"在共享内存基础设施上，payload 编码格式是 Key-Value 文本还是 msgpack 二进制"。真正的"纯文本通信"应该把文本内联在 StepResult 消息里，不经过 StatePool——那个实验在下面的 pure_text 包。

### 6.3 pure_text（纯文本 vs 结构化）—— ⚠️ 正式补齐

`state_transfer_pure_text` 专用包（protocol-only, 6 task × r3）：

测试：`natural_handoff_text`（真正的自然语言描述，不做 Key-Value 格式化）vs `state_ref`（结构化 msgpack）

```
handoff策略           控制面  线上握手  负载字节  文本握手  非文本    耗时
────────────────────────────────────────────────────────────────────
natural_handoff_text   5,041   143       1,269     1,269     0        4,428ms
state_ref              5,988   216       4,481     786       3,695    4,455ms
差异                    +948    +73      +3,212    ↓483      +3,695   +27ms
```

**这个数据说明**：
- pure-text baseline 已正式补齐——有了真正的"自然语言"对照组（不是格式化的 Key-Value，是更像人写的自然语言描述）
- `state_ref` 仍然让非文本状态出现（文本握手↓483，非文本 +3,695）
- 但从 carrier 成本看，`state_ref` 更重——**不支持低开销 headline**
- 耗时几乎持平（+27ms）——两者的执行时间差异在噪声范围

**两个 state_transfer 包的分工**：
- `authenticity`（authenticity）：证明"结构化握手这件事是真的能做"——typed handoff 真实可用。text_brief 是 hybrid baseline（用了 StatePool 的半结构化文本）
- `pure_text`：提供真正的 natural language baseline——防止把 text_brief 误当成"普通文本"。让对比更诚实

---

## 七、Summarizer token 为什么会省——机制解释

在本文对应的历史受控包里，`llm_total_tokens` 主要来自 Summarizer；这是当时对象的历史计量前提，不代表当前实现。

```
                 text 模式                         protocol 模式
                 ─────────                        ─────────────
Summarizer 收到:  原始 evidence 全文               上游提取的结构化 handoff
                 (几千字节自然语言)                "Query: ... Route: cache_invalidation
                                                  Route confidence: 0.92
                                                  Matched signals: invalidation, batch-sync"

Prompt 格式:     "你是纯文本协作环境中             "sb-summary-v1: Output JSON
                 的 Summarizer..."                 {\"s\":\"summary\",...}"

Token 消耗:      ≈ 500+ token                     ≈ 200+ token

根因:            Retriever 的推理结果(route)       Retriever 的推理结果(route)
                 → 文本化成自然语言                → 结构化字段直传
                 → Summarizer 重新理解文本         → Summarizer 直接使用
                 → "状态→文本→状态" 往返           → 消灭了往返
```

**这不是"给 Summarizer 更少信息"——是给"更浓缩的信息"。** 上游 Agent 已经把 route、confidence、signals 提取好了，不需要 Summarizer 重新从原始文本中推断。`expectation_match=1.00` 证明最终输出完全一致。

---

## 八、`open_validation`（开放验证包，support-only）—— 为什么要有这个包

**问题**：在这个历史 `formal_controlled` 对象里，Planner 不参与 LLM 规划（plan 来自 YAML）；那评委问"你们的 Planner 真的会规划吗"怎么办？

**实验设计**：15 个 task，包含 3 个 `plan_source=llm` 的 task（Planner 真调 LLM 生成 plan）、route 歧义诊断 task、Executor 低信度 abstain task、replay 边界拒绝 task。

```
               text 98,529 → proto 83,552   ↓15.2% control_bytes
               text 8,467  → proto 5,998    ↓29.2% llm_tokens
               expectation_match=1.00, failure_count=0
```

**这个数据说明**：
- Planner 自主规划可以工作（3 个 task 全部通过）
- route 系统能处理歧义（metadata hint 和 lexical evidence 冲突时，lexical 胜出）
- Executor 能在低信度下正确 abstain
- replay gate 能在不满足条件时正确拒绝

**但不用于 formal headline**：这个包标记为 `support_only`。它的存在是为了回答"系统除了 benchmark 之外还像不像真 Agent runtime"——不让 formal_controlled 的受控设计被误读成"系统只会跑脚本"。

---

## 九、防止三种误读

1. **把 `communication` 的胜利自动扩展成 `state_transfer` 的低开销胜利**
   communication 省的是控制面消息 + LLM prompt。state_transfer 对比的是 handoff 格式——两者走的是相同的 StatePool 基础设施，wire 差异仅 81 字节。

2. **把 `text_brief` 当成纯文本 baseline**
   `text_brief` 把结构化信息写成 Key-Value 格式，然后走 StatePool 传指针。它不是"真的用自然语言在线上传"——它和 state_ref 共享同一套高效的通信基础设施。

3. **把 `assist_only` 的命中自动读成记忆收益**
   命中 ≠ 收益。assist 有命中（`memory_hit_rate`=1.0）但没有加速（token 反而更高）。只有 `replay_enabled`（匹配后跳过步骤）才产生时间收益。

---

## 十、各实验的"一句话"总结

| 实验 | 一句话 |
|------|--------|
| `communication` 专用包 | 最干净的通信对比——一个变量，省 15.9% |
| `formal_controlled` 主包 | 综合门面——复现方向，但不替代专用包 |
| `fresh_retrieval` 拆分 | protocol 优势不是靠 replay 作弊——真实执行的 task 上也省 |
| `memory` 专用包 | assist 不行，replay 行——记忆层只 claim replay |
| `state_transfer_authenticity` | structured handoff 是真实可用的——文本依赖降 59%，非文本从无到有 |
| `state_transfer_pure_text` | 纯文本 baseline 已补齐——state 不是更轻，但让非文本状态发生了 |
| `open_validation` | Planner 真会规划，系统不是只会跑脚本——佐证用，不进 headline |

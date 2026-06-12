# StateBus 任务设计与模式对比

日期：`2026-06-11`
执行数据：`runs/benchmark_suite_20260611_124126_api_repeat3/`

---

## 一、Pack 地图

不同 pack 负责不同主张，不能混读：

| pack | 类型 | task数 | mode | 测什么 | headline | 不对外推什么 |
|------|------|--------|------|--------|----------|-------------|
| `formal_controlled` | formal-overview | 24 | text+proto | 系统总门面 | 总览/回归 | 不替代单项最干净证据 |
| `communication` | formal | 2 | text+proto | 纯text vs proto通信 | `communication` | 不证明handoff真实性 |
| `memory` | formal | 3 | proto-only | 三种记忆策略 | `memory replay` | 不证明text vs proto |
| `state_transfer_authenticity` | formal | 6 | proto-only | text_brief vs state_ref | `typed handoff真实性` | 不证明战胜纯文本 |
| `state_transfer_pure_text` | formal | 40 | proto-only | natural_text vs state_ref | `pure text fairness` | 不支持state更轻 |
| `state_transfer_strict_pure_text` | formal-secondary | 40 | proto-only | strict inline text vs minimal state packet | `strict executor-facing pure text` | 不进正式headline aggregate |
| `state_transfer_carrier` | formal | 40 | proto-only | 载体编码格式对比 | `carrier headline` | 不混读真实性/公平性 |
| `state_transfer_inline_text_support` | support | 6 | proto-only | 严格内联纯文本 vs 最小状态包 | inline-text smoke support | 不做headline |
| `open_validation` | support | 15 | text+proto | Planner/歧义/边界 | 开放能力证明 | 不进入正式claim |
| `open_planner_support` | support | 5 | text+proto | 5-family `plan_source=llm` | Planner真实生成plan | 不进入正式claim |

---

## 二、Task 定义

当前 contest-release `state_transfer` packs 采用统一骨架：

- `5 family x 4 case`
- family: `checkout / auth / cache / billing / deploy`
- case: `clean / distractor / ambiguous / replay-reusable`
- 每个 case 在各 pack 中都做成严格 paired task，除了 `transfer_strategy` 与 pack contract 外不允许改 `goal / query / corpus_doc_ids / task_group / task_theme / summary_hint`

每个 task 是一次 Agent 协作诊断。用户给问题 → 系统检索 corpus → 判 route → 执行 → 总结。

| 字段 | 示例 | 作用 |
|------|------|------|
| `task_id` | `sample-cache-001` | 唯一标识 |
| `task_group` | `cache_chain` | 同链 task 共享记忆（同一个 SQLite） |
| `task_theme` | `repo_local_cache_staleness` | 主题标签；记忆检索过滤条件 |
| `goal` | 自然语言 | 要解决的问题 |
| `query` | 英文关键词 | corpus 检索查询 |
| `corpus_doc_ids` | `[cache-invalid-anchor, ...]` | 指定要检索的文档 |
| `transfer_strategy` | `state_ref` / `mode_split_*` | 决定 Retriever→Executor 握手方式 |
| `runtime_reuse_contract` | `reuse_disabled` / `assist_allowed` / `validated_replay` / `exact_replay` | 记忆复用合同——控制能否查记忆、能否跳步 |
| `expected_reuse_mode` | `none` / `assist` / `skip_execute` / `skip_retrieve_execute` | benchmark 验证——预期复用行为 |
| `plan_source` | `yaml` / `llm` | Plan 来源：固定模板 or LLM 生成 |

**记忆跨 task 共享**：同 `task_group` 的 task 共享一个 SQLite+FAISS。跨 run 不共享（每次跑全新实例）。

---

## 三、`formal_controlled` 的 24 个 task

```
cache_chain ×6         内部回归——验证 replay 稳定性
latency_chain ×6       内部回归——同上，换 domain
transfer_lane ×3       状态传递对比
communication_lane ×6  通信开销对比
memory_lane ×3         记忆策略对比
```

### 3.1 cache_chain + latency_chain（12 task，内部回归）

**目的**：验证 replay scaffold 完整性和稳定性。`claim_lanes=[]`——不参与赛题主张，但支撑"系统能稳定跑"的可信度。

每个 chain 6 个 task，结构同构：

| 序号 | 复用模式 | 在测什么 |
|------|---------|---------|
| 1 | none | **冷启动基线**——无记忆，首次诊断 |
| 2 | assist | **记忆辅助**——查记忆当参考，不跳步 |
| 3 | none | **误导拒绝**——查记忆但不符合，拒绝复用 |
| 4 | assist | **控制回放**——再跑一次积累记忆 |
| 5 | skip_execute | **验证回放**——匹配？→跳过执行步骤 |
| 6 | skip_retrieve_execute | **精确回放**——完全匹配？→两层都跳过 |

**text/proto 差异**：只有控制面消息格式 + LLM prompt 不同。握手固定 `state_ref`。

### 3.2 transfer_lane（3 task，状态传递）

**目的**：验证 text_brief vs state_ref 握手。**这是 typed handoff 的真实性证明。** `transfer_strategy: mode_split_text_brief_vs_state_ref`——text 下走 text_brief，proto 下走 state_ref。

```
transfer-cache-001    text→text_brief, proto→state_ref
transfer-latency-001  同上
transfer-session-001  同上
```

**这 3 个 task 有全部三层差异**：控制面消息格式 + LLM prompt + 握手策略。

### 3.3 communication_lane（6 task，最干净通信对比）

**目的**：纯 text vs proto 通信对比。**单一变量——只有控制面消息格式和 LLM prompt 不同。**

```
通信对比: memory全部禁用 | 握手全部固定state_ref | 3 domain × 2 类型
communication-cache-001   冷启动  communication-cache-002   拒绝控制
communication-latency-001 冷启动  communication-latency-002 拒绝控制
communication-session-001 冷启动  communication-session-002 拒绝控制
```

### 3.4 memory_lane（3 task，记忆策略）

**目的**：对比三种记忆策略。**protocol-only——不参与 text vs proto。**

```
memory-cache-001    memory_off      冷启动基线
memory-cache-002    assist_only     有命中但不跳步
memory-cache-003    replay_enabled  命中匹配→跳过步骤
```

---

## 四、text 和 protocol 差异的三个层面

```
层面1: 控制面消息格式          ← 所有24 task都有
  text:    自然语言字符串序列化    → control_bytes 大
  protocol: protobuf二进制帧      → control_bytes 小

层面2: LLM Prompt 格式          ← 所有24 task都有
  text:    自然语言prompt         → llm_total_tokens 高
  protocol: 紧凑协议prompt         → llm_total_tokens 低

层面3: Retriever→Executor 握手   ← 只有 transfer_lane 的 3 task 有
  text:    text_brief (Key-Value文本 → StatePool → 指针)
  proto:   state_ref (msgpack结构化 → StatePool → 指针)
```

### 层面差异矩阵

| task 组 | 层面1(消息格式) | 层面2(prompt) | 层面3(握手) |
|---------|:---:|:---:|:---:|
| cache_chain ×6 | ✅ | ✅ | 固定state_ref |
| latency_chain ×6 | ✅ | ✅ | 固定state_ref |
| transfer_lane ×3 | ✅ | ✅ | text_brief vs state_ref |
| communication_lane ×6 | ✅ | ✅ | 固定state_ref |
| memory_lane ×3 | N/A | N/A | protocol-only |

---

## 五、三种 handoff 对比不要混

| 对比 | 主要对象 | 对应 headline |
|------|----------|---------------|
| `text vs protocol` | 控制面消息 + LLM prompt | `communication` |
| `text_brief vs state_ref` | hybrid handoff 真实性 | `typed_handoff_authenticity` |
| `pure_text vs state_ref` | 真纯文本 vs 结构化 | `pure_text_vs_state` |

`text_brief` 不是"纯文本 baseline"——它把结构化信息格式化为 Key-Value 文本，然后走 StatePool 传指针。和 state_ref 走的是相同的通信路径（StatePool→指针→mmap）。真正的"纯文本"应该是把自然语言内联在消息里，不经过 StatePool；当前这条严格合同放在 `state_transfer_inline_text_support`，只作为 support-only。

---

## 六、各 Pack 对应的主张

| 想看什么 | 看哪个包 |
|---------|---------|
| 通信效率（纯text vs proto） | `communication` 专用包 |
| 记忆复用效果 | `memory` 专用包 |
| protocol-only carrier headline | `state_transfer_carrier` |
| 状态传递真实性（handoff） | `state_transfer_authenticity` |
| 纯文本 vs 结构化 | `state_transfer_pure_text` |
| 整体门面 | `formal_controlled` |
| Planner能力/边界行为 | `open_validation`（support-only） |
| 固定工作流质疑 | `open_planner_support`（support-only，text/protocol 都跑 `plan_source=llm`） |
| 最严格纯文本 baseline | `state_transfer_strict_pure_text`（formal-secondary，executor-facing 输入只允许消息体文本） |

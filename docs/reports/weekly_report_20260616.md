# StateBus 周报

日期：2026-06-16

---

## 一、系统实现方式

### 架构概述

基于 LangGraph 的多 Agent 编排系统。核心链路：

```
LangGraph DAG (planner → retriever → [validate] → executor → summarizer)
    └── 每个节点调用 Orchestrator 的原语
        ├── PlannerAgent (LLM)    — 3-5 步可变 plan，支持 yaml/LLM 两种模式
        ├── RetrieverAgent        — 证据检索 + 生成 typed state
        ├── ExecutorAgent         — 工具选择 + playbook 执行，支持 validate gate
        └── SummarizerAgent (LLM) — 总结 + MemoryCommit

协议层：Protobuf 控制帧 (Hello/Capability/Plan/StepResult/...等 10+ 消息类型)
数据面：StateRef → mmap StatePool，重状态不内联到消息里
记忆层：SQLite + FAISS，支持 assist/replay 两种复用路径
```

semantic_role 系统让 PlanStep 通过语义角色（而非固定 step_id）标识，Plan 可以 3-5 步可变，支持条件路由（如 validate 步骤按 plan 结构动态插入）。

### Benchmark 评测

12 个 v3 pack，按赛题三条主线分层：

| 主线 | 核心 pack | 验证内容 |
|---|---|---|
| 通信效率 | contest_dual_mode_controlled_v3 | text vs protocol 同任务对照 |
| 状态传递 | typed_state_mechanism_v3 | natural_text vs typed_packet 的机制真实性 |
| 记忆复用 | memory_policy_controlled_v3 | 单变量 replay 归因 (reuse_disabled→exact_replay) |

其余 pack 为 audit/support/legacy 面，不进 headline。

---

## 二、当前结果

全量 API repeat=3 跑通（12 pack，real LLM + real embedding），191 pytest passed。

三条主线数据：
- **通信**：control_bytes -19.8%，wrong_family 0.00，admissible 1.00
- **状态传递**：exact_match 1.00，kind_match 1.00，zero unexpected kind
- **记忆复用**：exact_match 1.00，replay gate pass，reuse_gain 0.67

---

## 三、主要挑战与遗留问题

### 任务设计

没有直接可用的外部 benchmark 数据集——现有数据集（HotpotQA/MuSiQue 等）缺少 StateBus 需要的 route/tool/replay 合同，无法直接映射。任务和 corpus 全部自己设计，需要在"难度足够体现协议优势"和"受控对照可归因"之间平衡。去 corpus 预标签后 retrieval 质量下降明显，在一些 ambiguous case 上信号不足。

### 当前遗留

- **contest formal headline 被 withheld**：text handoff 因公平性修复携带了显式 Route/Tool 字段，被 guard 误标为 hidden field leak；repeat 不足 10 轮
- **部分 family tool 精度偏差**：corpus 措辞与 ToolRegistry match pattern 的词汇偏差导致 billing family 系统性选偏 tool
- **Planner 在 contest 包上被 plan_source:yaml 绕过**：受控实验的设计选择，Planner 证据在 planner_support_v3 独立呈现
- **LangGraph 集成深度有限**：当前是条件路由 + graph state 传播的编排 wrapper，语义逻辑仍在 Orchestrator 内，未用到并行/动态路由等高级特性

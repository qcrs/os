# StateBus Repeat-1 全量 Smoke 深度分析

日期：2026-06-16 17:03
运行目录：`runs/api_repeat1_smoke_20260616_165207/`
提交：`56ff2c8 change planner` + 11 文件 unstaged（validate-first 闭环代码未包含在运行中）

---

## 一、核心发现：协议模式正确率远低于文本模式

### Contest 双模式 per-task 统计

| 指标 | Text | Protocol |
|---|---|---|
| Retrieval 产出 generic_triage | 19/20 | 19/20 |
| Executor 产出 generic_triage | **9/20** | **19/20** |
| Executor 精确匹配 | **8/20** | **1/20** |
| Executor 容许匹配 | 11/20 | 1/20 |

**Text 模式：retrieval 给了 19 个 generic_triage，但 executor 纠正了 10 个。**

**Protocol 模式：retrieval 给了 19 个 generic_triage，executor 全部接受，0 个纠正。**

### 根因

代码路径差异：

| 模式 | Executor 入口 | 行为 |
|---|---|---|
| text_strict_pure_lane | `_feature_bundle_from_strict_pure_text_handoff()` → `registry.retrieve_candidates()` | **独立词法匹配**，不信任 retriever，自己重新找 route |
| state_packet_minimal | `_feature_bundle_from_executor_decision_packet()` | **直接读取 decision packet 的 route**，retriever 给了 generic_triage 就接受 |

**Text 的 executor 会自己重新做 lexical matching → 能在 retriever 失败时自救。**

**Protocol 的 executor 完全信任 decision packet → retriever 失败时跟着一起输。**

这是结构性不对称：protocol 的"非文本状态传递"让 executor 依赖 retriever 的输出，但 retriever 在去掉 corpus hint 后质量很差（19/20 generic_triage），protocol 没有 fallback 路径。

---

## 二、其余数据要点

### planner_support_v3 — 运行正常但 admissible 0.27

- one_shot_valid=1.00, repair=0 — Planner 修复完美生效
- 但 admissible 0.27 — 因为 retrieval 质量差，Planner 产出的 plan 无法被正确执行

### memory_policy_controlled_v3 — replay 仍然稳健

- exact_match=1.00, replay gate pass, reuse_gain=0.67
- 去 hint 不影响 memory replay（replay 靠 route/docset/hash 匹配，不靠 retrieval 质量）

### typed_state_consumer_sensitivity_v3 — 统计口径干净

- missing_decision_failure=1.00, wrong_tool=1.00, expected_neg=5, unexpected=0

### typed_state_mechanism_v3 — exact_match=0.00

- 去 hint 后 zero exact matches。两种 handoff 对象都受限于 retrieval 质量
- state_packet task_ms 比 natural_text 快 10%（-566ms），但 correct 是 0

### memory_dual_mode_fairness_v3 — object_parity pass

- 之前 broken 的包已修复，只 withheld for repeat=1

---

## 三、结构性问题

### 1. Protocol executor 缺乏 fallback lexical matching

当 retriever 产出 `generic_triage`（低置信度）时：
- Text executor 做独立 lexical matching → 能找到正确 route
- Protocol executor 直接接受 decision packet → 只能出 generic_triage

这使得 **protocol 的正确率天花板被 retriever 质量完全锁死**，而 text 可以绕开。

### 2. Retriever 在去 hint 后几乎完全失效

19/20 task 的 retrieve 结果都是 `generic_triage`（置信度 0.0）。唯一例外是 auth clean。这说明当前 retrieval 的 lexical/semantic matching 在没有 corpus 预标签的情况下缺乏足够信号。

### 3. 当前 benchmark 存在结构不对称

protocol 被要求"信任 retriever 的结构化输出"——这是赛题要求的"非文本状态传递"。但 text 侧被允许"executor 自己做 lexical matching"——这不公平。如果 protocol 的 executor 也应该有一个 fallback，或者 text 的 executor 也应该被限制为"只能信任 retriever 输出"——但现在不是这样。

### 4. 11 文件 unstaged 未包含在运行中

validate-first 闭环代码（contracts.py 的 VALIDATION_GATE_PACKET、executor_runtime.py 的 generic_triage 拒绝、build_plan 的 4-step 支持等）在 `56ff2c8` 提交之后才修改，本次 benchmark 没有运行这些代码。这意味着 contest 包的 protocol executor 没有 generic_triage 拒绝——如果有了，contest protocol 的 19 个 task 会全部 fail 而不是 completed with generic_triage。

# 17f - 安全声明语言指南 (Safe Claim Language Guide)

**审计日期：** 2026-07-06
**状态：** 已按 claim-upgrade 执行结果更新
**关联主报告：** [17_final_system_audit_20260706.md](../../17_final_system_audit_20260706.md)
**新增完成报告：** [19_claim_upgrade_completion_report_20260706.md](../../19_claim_upgrade_completion_report_20260706.md)

---

## 使用说明

本文档给出答辩和对外沟通的推荐用语。每个声明都按当前证据边界分为：

- ✅ **可以声明**：有代码、测试或 benchmark JSON 证据支持
- ⚠️ **谨慎声明**：可以说，但必须带范围限定
- ❌ **不能声明**：当前证据不足，或会越过项目约束

本次 claim-upgrade 新增两类可声明证据：

1. 形式化 benchmark 从 8 个单指标案例扩展为 25 个案例、5 个任务家族。
2. `memfd` transport 已进入 formal benchmark 主线，并在 JSON 中可观测到真实 transfer count 和 bytes。

---

## 第一部分：核心创新声明

### 1. 类型化控制平面

✅ **推荐表述：**

> "StateBus 实现了 UDS + Protobuf 类型化控制平面，支持四角色结构化交接（Planner -> Retriever -> Executor -> Summarizer）。在扩展后的形式化 benchmark 上，四角色流程完成 25/25 案例并维持质量通过。"

**支持证据：**

- 代码：`v2/control/transport.py`, `v2/runtime/driver.py`
- Benchmark：`/tmp/statebus-claim-upgrade-formal-runtime-local-final/benchmark_reports/claim-upgrade-formal-local-final-formal-suite.json`
- 关键指标：`L3_case_count=25`, `L3_quality_pass_count=25`

**避免过度表述：**

- ❌ "类型化控制平面显著提升端到端速度"
- ❌ "零开销类型系统"

---

### 2. SemanticStateRef 非文本状态载体

✅ **推荐表述：**

> "StateBus 引入 SemanticStateRef 作为非文本状态载体。扩展形式化 benchmark 中，语义状态传输覆盖 25/25 案例，并通过 state-pool 后端传递检索后的结构化状态。"

**支持证据：**

- 代码：`v2/refs/models.py`, `v2/state/store.py`, `v2/runtime/smoke.py`
- Benchmark：`waterfall_metrics.L2_semantic_state_transfer_count=25`

**必要限定语：**

- ⚠️ "语义状态传输"不是"完全消除文本"
- ⚠️ 当前证据覆盖 repo-local formal benchmark，不代表开放域所有任务

---

### 3. 连续任务降级复用

✅ **推荐表述：**

> "StateBus 支持基于策略的降级复用：当任务家族、意图操作和工具集满足准入条件时，可以跳过规划步骤；字节完全相同时可触发 exact replay。准入门基于 SHA-256 哈希匹配，强调安全性和可追溯性。"

**支持证据：**

- 代码：`v2/runtime/replay.py`
- 历史审计证据：连续任务 replay collection 与 negative audit

**必须说明：**

| 级别 | 语义 | 跳步 |
|------|------|------|
| EXACT_REPLAY | 字节完全相同 | 可跳过更多步骤 |
| VALIDATED_DOWNGRADED_REUSE | 家族和工具集匹配，参数不同 | 跳过规划步骤 |
| ASSIST | 历史支持但不满足跳步准入 | 不跳步 |

**避免过度表述：**

- ❌ "通用答案恢复"
- ❌ "AI 长期记忆"
- ❌ "泛化重放能力"

---

### 4. 外部纯文本公平门（dev 范围）

✅ **推荐表述：**

> "StateBus 已实现 dev 固定答案范围的外部纯文本公平门。外部基线采用四角色独立 LLM 调用，并通过公平性检查约束可见信息。该证据支持 dev 范围的资源效率对比，不自动扩展为 formal tier 外部优势。"

**支持证据：**

- 代码：`v2/benchmark/external_text_baseline.py`, `v2/benchmark/comparator_runner.py`
- 历史审计证据：dev fixed-answer external gate

**必要限定语：**

- ⚠️ "dev 固定答案范围"
- ⚠️ "formal tier 外部比较未在本次 claim-upgrade 中重新执行"
- ⚠️ 不把内部 formal 25/25 结果说成外部优势

**避免过度表述：**

- ❌ "形式化财务外部优势已由本次升级验证"
- ❌ "端到端速度更快"

---

### 5. 形式化多样化推理验证

✅ **推荐表述：**

> "StateBus 形式化 benchmark 已扩展到 25 个案例、5 个任务家族：财务单指标提取、多期趋势分析、跨表关联、条件聚合、异常检测。local-embedding formal run 中质量基线维持 25/25 通过。"

**支持证据：**

- 任务注册：`v2/benchmark/task_registry.py`
- 新任务目录：`tasks/formal/`
- Benchmark JSON：`L3_case_count=25`, `L3_quality_pass_count=25`, `family_count=5`
- Families：`financial_report_analysis`, `multi_period_trend_analysis_v1`, `cross_table_join_analysis_v1`, `conditional_aggregation_v1`, `anomaly_detection_v1`

**必要限定语：**

- ⚠️ "形式化多样化推理验证"可以说
- ⚠️ "大规模开放域 benchmark"不能说
- ⚠️ 当前证据是 local-embedding formal run，不是 API formal external comparison

---

### 6. memfd benchmark 主线验证

✅ **推荐表述：**

> "StateBus formal benchmark 主线已可通过 `--state-pool-mode memfd` 使用 memfd state-pool 后端。claim-upgrade local-embedding formal run 中，JSON 记录 `state_pool_mode_used=\"memfd\"`，并观测到 25 次 memfd transfer、25 次 memfd publish、247046 bytes transferred。"

**支持证据：**

- 代码：`v2/state/store.py`, `v2/runtime/driver.py`, `v2/runtime/smoke.py`, `v2/benchmark/live_runner.py`
- Benchmark JSON：`state_pool_mode_used="memfd"`, `memfd_transfer_count=25`, `memfd_publish_count=25`, `memfd_bytes_transferred=247046`
- 审计脚本：`scripts/run_v2_full_container_audit_suite.sh` stage 07/08 传入 `--state-pool-mode memfd`

**必要限定语：**

- ⚠️ "formal benchmark 主线可观测使用 memfd"
- ⚠️ 不说"生产级 memfd transport"
- ⚠️ 不把 mode 字段单独当证据，必须同时引用 transfer count 和 bytes

---

## 第二部分：限制和边界

### 7. 系统开销当前为正

⚠️ **推荐表述：**

> "StateBus 展示了令牌和提示字节效率改进，但当前不能声称端到端速度优势。历史外部比较中系统开销为正，主要来自多角色协调、状态序列化和多次角色调用。速度优化仍是后续工作。"

**必须诚实说明：**

- ✅ 当前不能说更快
- ✅ 只能说资源效率和结构化状态传递
- ✅ 角色并行、序列化优化、Engine-Local Prefix Reuse 都是后续优化方向

---

### 8. openEuler 只验证到容器范围

⚠️ **推荐表述：**

> "StateBus v2 面向 openEuler 24.03-LTS-SP3 容器环境进行了验证。openEuler VM 验证仍属于 posterior validation，不应提前声称。"

**避免过度表述：**

- ❌ "openEuler VM 验证"
- ❌ "openEuler 生产环境验证"

---

### 9. Bounded CodeAct 不是实时 LLM 代码生成证明

⚠️ **推荐表述：**

> "StateBus 实现了 bounded CodeAct 路径，在受控执行环境中运行受限代码执行流程。当前主线 claim 不应表述为 benchmark 已证明实时 LLM 代码生成能力。"

**避免过度表述：**

- ❌ "Benchmark 证明实时 LLM 代码生成"
- ❌ "动态代码生成能力已被 formal benchmark 证明"

---

### 10. 形式化外部优势本次未升级

⚠️ **推荐表述：**

> "本次 claim-upgrade 验证了 local-embedding internal formal benchmark 的 25/25 质量和 memfd 主线传输。formal tier 外部比较需要 `STATEBUS_LLM_API_KEY` 和 `--suite compare --benchmark-tier formal --role-path-mode api --embedding-mode local` 重新运行后才能声明。"

**避免过度表述：**

- ❌ "形式化财务外部优势已由 25-case local-embedding internal run 证明"
- ❌ "formal_superiority_claim_allowed=True"（除非引用同一环境下重新生成的 formal compare JSON）

---

## 第三部分：禁用表述清单

| 禁用词 | 原因 | 替代表述 |
|--------|------|----------|
| "更快" / "faster" | 端到端速度优势未建立 | "资源效率改进" |
| "延迟改进" | 外部比较中系统开销为正 | "令牌/提示字节节省" |
| "大规模开放域验证" | 当前 formal 为 25 个 repo-local 案例 | "25-case formal diversified benchmark" |
| "通用答案恢复" | replay 需要准入门 | "基于策略的降级复用" |
| "AI 长期记忆" | 不是泛化记忆系统 | "历史支持复用" |
| "VM 验证" | 只有容器/宿主验证证据 | "openEuler 容器验证" |
| "实时 LLM 代码生成证明" | 主线 claim 不支持 | "bounded CodeAct 路径" |
| "生产级 memfd" | benchmark 主线已验证，但非生产认证 | "formal benchmark memfd path" |
| "formal external superiority" | 本次未运行 formal external compare | "formal internal quality baseline" |

---

## 第四部分：答辩模板

### 开场白（30 秒）

> "StateBus 是一个宿主侧多代理协作框架，探索通过 UDS + Protobuf 类型化控制平面和非文本状态载体降低跨角色文本暴露，并让中间状态以可追溯的 StateRef 形式传递。系统编排 Planner、Retriever、Executor、Summarizer 四个角色。"

### 核心创新（1 分钟）

> "我们实现了三类核心机制：第一，类型化控制平面，四角色交接走结构化协议；第二，SemanticStateRef 非文本状态载体，formal benchmark 中 25/25 案例完成语义状态传输；第三，基于策略的降级复用，严格通过任务家族和工具集准入门控制跳步。"

### 新增验证（30 秒）

> "本次升级把形式化 benchmark 从 8 个单指标案例扩展到 25 个案例、5 个任务家族，包括多期趋势、跨表关联、条件聚合和异常检测。local-embedding formal run 维持 25/25 质量通过。同时，formal 主线通过 `--state-pool-mode memfd` 观测到 25 次 memfd transfer、25 次 memfd publish、247046 bytes transferred。"

### 诚实边界（30 秒）

> "我们不声称端到端速度优势，不声称 openEuler VM 验证，不声称通用答案恢复，也不把本次 local-embedding internal formal run 说成 formal external superiority。外部公平门目前只可按已有 dev/fixed-answer 证据谨慎表述；formal external claim 需要单独 API compare JSON。"

---

## 第五部分：问答应对策略

### Q: "现在可以说形式化广泛推理了吗？"

✅ **推荐回答：**

> "可以说形式化 benchmark 已扩展为 25-case、5-family diversified reasoning validation。但不能说大规模开放域验证，也不能说 formal external superiority，因为这两个需要不同证据。"

### Q: "memfd 的证据是什么？"

✅ **推荐回答：**

> "证据不是只有配置开关。formal benchmark JSON 同时记录 `state_pool_mode_used=\"memfd\"`、`memfd_transfer_count=25`、`memfd_publish_count=25`、`memfd_bytes_transferred=247046`，说明有真实发布、传输计数和字节数。"

### Q: "为什么不声称更快？"

✅ **推荐回答：**

> "当前证据支持资源效率和状态传递，不支持端到端速度优势。多角色串行、状态序列化和多次角色调用会带来系统开销。速度优化需要后续工程。"

### Q: "validated reuse 和 exact replay 有什么区别？"

✅ **推荐回答：**

> "Exact replay 是字节完全相同的重放；validated downgraded reuse 是任务家族和工具集满足准入但参数不同，只跳过规划步骤；assist 只是历史支持，不跳步。我们有意保守，避免把历史答案泛化到不安全的新任务。"

---

## 第六部分：审计签名

本文档已按 claim-upgrade 执行结果更新：

- ✅ 形式化任务：25 cases / 5 families / 25 quality passes
- ✅ memfd 主线：25 transfers / 25 publishes / 247046 bytes
- ✅ 仍保守：速度优势、openEuler VM、通用答案恢复、实时 LLM 代码生成、formal external superiority

**审计日期：** 2026-07-06
**证据锚点：** `/tmp/statebus-claim-upgrade-formal-runtime-local-final/benchmark_reports/claim-upgrade-formal-local-final-formal-suite.json`
**答辩前必读：** 是

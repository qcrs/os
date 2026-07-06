# 17a - 证据表 (Evidence Table)

**审计日期：** 2026-07-06
**关联主报告：** [17_final_system_audit_20260706.md](../../17_final_system_audit_20260706.md)

---

## 声明强度分级标准

- **Strong**：代码真实实现 + 测试通过 + benchmark JSON 指标一致 + 无明显漏洞
- **Medium**：证据部分完整，有已知限制但不影响核心声明
- **Weak**：证据存在但覆盖不足，或依赖特定条件
- **Unsupported**：证据不足或与声明矛盾

---

## 完整证据表

### 1. 类型化控制平面和结构化角色交接

**声明强度：** ⭐⭐⭐ **Strong**

| 维度 | 证据 | 位置 |
|------|------|------|
| **代码实现** | ✅ UDS + Protobuf 真实实现 | `v2/control/transport.py:283-419` (SubprocessExecutorTransport)<br>`v2/runtime/driver.py:1-1300+` (四角色编排) |
| **控制开销测量** | ✅ control_bytes_delta = +360B | `runs/v2-full-audit-20260705_213331/stages/07_formal_primary/stdout.json` |
| **测试覆盖** | ✅ 214 tests passed (v2 suite) | `pytest tests/v2/ -q` |
| **Benchmark 验证** | ✅ 8/8 质量通过，无质量回归 | formal_primary stdout.json |

**边界/警告：**
- ⚠️ `ControlPlaneLoopbackServer` (deterministic 模式) 是脚本化线束，执行器不运行真实代码
- ✅ 真实执行路径在 `SubprocessExecutorTransport` (api 模式)
- ⚠️ memfd transport 实现存在但不在 formal/compare benchmark 主线

**支持声明：**
> "StateBus 实现了 UDS + Protobuf 控制平面，四角色清晰职责边界，控制开销可控（+360B）。"

---

### 2. SemanticStateRef / ExecutionArtifactRef 分离

**声明强度：** ⭐⭐⭐ **Strong**

| 维度 | 证据 | 位置 |
|------|------|------|
| **类型定义** | ✅ 清晰分离的引用类型 | `v2/refs/models.py:38-97` |
| **架构遵守** | ✅ SemanticStateRef 用于中间状态<br>✅ ExecutionArtifactRef 用于最终输出 | `v2/runtime/driver.py` 全文 |
| **哈希完整性** | ✅ CanonicalEvidencePack 计算 pack_hash<br>✅ HydrateManifest 计算 manifest_hash | `v2/refs/models.py:74-97` |

**边界/警告：** 无

**支持声明：**
> "StateBus 严格区分 SemanticStateRef（语义状态）和 ExecutionArtifactRef（执行工件），确保类型安全。"

---

### 3. 非文本状态传输减少提示暴露

**声明强度：** ⭐⭐ **Medium/Strong**

| 维度 | 证据 | 位置 |
|------|------|------|
| **代码实现** | ✅ LayeredStateStore 真实 shared_memory + mmap | `v2/state/store.py:26-75` |
| **压力测试覆盖** | ⚠️ 4/6 家族通过（非均匀） | `runs/v2-full-audit-20260705_213331/stages/15_flagship_ablation_primary/stdout.json` |
| **提示节省测量** | ✅ 2208B LM 提示节省<br>✅ 8409B 提示可见节省 | flagship_ablation stdout.json |
| **质量维持** | ✅ 质量无回归 | 同上 |

**边界/警告：**
- 🔴 **非均匀覆盖**：2/6 家族未通过（gridops_capacity_planning, incident_diagnosis）
- ⚠️ `semantic_state_transfer_count` 在 `driver.py:1184` 硬编码为 0.0（此计数器未被真实使用）
- ✅ 真实的非文本状态传输通过其他字段测量（pruning_bytes_saved, prompt_bytes_delta）

**不支持声明：**
- ❌ "所有任务家族都受益于非文本状态传输"（实际 4/6）

**支持声明：**
> "SemanticStateRef 在 4/6 任务家族中成功减少提示暴露（8409B 提示可见节省），保持质量无回归。非文本状态传输在表格检索和长文档任务中效果显著。"

---

### 4. 形式化财务质量基线

**声明强度：** ⭐⭐⭐ **Strong**（质量基线）⭐ **Weak**（广泛推理）

| 维度 | 证据 | 位置 |
|------|------|------|
| **质量分数** | ✅ 8/8 质量通过，确定性验证器 | `runs/v2-full-audit-20260705_213331/stages/07_formal_primary/stdout.json` |
| **剪枝节省** | ✅ 6255B 语义剪枝节省 | 同上 |
| **控制开销** | ✅ +360B 类型化控制 | 同上 |
| **任务覆盖** | 🔴 **只有 8 案例**，单指标表格检索 | 同上 |
| **重放增益** | ⚠️ L3_reuse_gain = 0（冷启动，预期） | 同上 |

**边界/警告：**
- 🔴 **形式化家族狭窄**：8 个 financial_report_analysis 案例，全部为单指标表格检索
- 🔴 **缺少时序数据**：api_task_ms 字段缺失，无法计算端到端时序增量
- ✅ **质量基线可靠**：确定性验证器 + 事实覆盖检查
- ⚠️ **冷启动重放为 0**：符合预期，不是缺陷

**不支持声明：**
- ❌ "形式化广泛推理优势"
- ❌ "复杂多代理协作优势"

**支持声明：**
> "形式化质量基线维持（8/8 精密锚点案例通过）。语义剪枝节省 6255B，类型化控制开销 +360B。"

---

### 5. 连续重放/复用观测

**声明强度：** ⭐⭐⭐ **Strong**

| 维度 | 证据 | 位置 |
|------|------|------|
| **重放计数** | ✅ 17 次验证重放，3 次精确重放 | `runs/v2-full-audit-20260705_213331/stages/10_continuous_replay_collection_primary/stdout.json` |
| **目标匹配** | ✅ 20/20 目标轮次匹配<br>✅ 0 缺失，0 意外 | 同上 |
| **复用增益** | ✅ L3_reuse_gain = 20<br>✅ history_step_reduction = 12 | 同上 |
| **准入门实现** | ✅ SHA-256 基于的真实准入逻辑 | `v2/runtime/replay.py:123-528` |
| **历史读取** | ✅ 从磁盘读取真实历史记录 | `v2/runtime/replay.py:395-448` |

**家族分解：**
- **csv_correlation_replay_v1**: 8 次验证重放，13 次历史复用
- **cross_period_financial_v1**: 4 次验证重放，16 次历史复用，8 复用增益，12 步骤减少
- **long_doc_metric_replay_v1**: 5 次验证 + 3 次精确重放，10 次历史复用

**边界/警告：**
- ⚠️ `validated_downgraded_reuse_count` 等于 `validated_replay_count`（冗余指标，`driver.py:1218-1219`）
- 🔴 **对外术语风险**：必须说"降级复用（validated downgraded reuse）"，不是"通用答案恢复"
- ✅ **三个家族不同模式**：证明非合成、非硬编码

**不支持声明：**
- ❌ "通用答案恢复重放"
- ❌ "泛化的安全答案恢复"

**支持声明：**
> "在 3 个连续任务家族中观测到 17 次验证降级复用、3 次精确重放，20/20 目标轮次匹配。重放准入基于任务家族、意图操作和工具集匹配，跳过规划步骤但保留检索和执行。"

---

### 6. 外部纯文本公平门通过

**声明强度：** ⭐⭐⭐ **Strong (dev 固定答案)** 🔴 **Unsupported (formal 财务)**

| 维度 | 证据 | 位置 |
|------|------|------|
| **公平门通过** | ✅ 3/3 案例通过，0 失败 | `runs/codex-raw-fairness-20260706/runtime/benchmark_reports/codex-raw-fairness-20260706-cold-start-compare-api.json` |
| **每案例检查** | ✅ 7 项检查全覆盖<br>✅ external_fairness_gate_failed_check_count = 0 | 同上 |
| **外部实现** | ✅ 真实四角色独立 LLM 调用 | `v2/benchmark/external_text_baseline.py:389-688` |
| **质量对等** | ✅ 双方都 3/3 精确匹配 | codex-raw-fairness JSON |
| **formal 资格** | 🔴 **formal_superiority_claim_allowed = False** | 同上 |
| **范围限制** | 🔴 **claim_restriction = "dev_fixed_answer_only"** | 同上 |

**公平门检查明细（7 项）：**
1. ✅ `no_statebus_imports` - 硬编码 True（代码结构保证）
2. ✅ `no_lexical_fallback` - 硬编码 True（代码结构保证）
3. ✅ `no_typed_state_used` - 动态扫描 FORBIDDEN_TERMS
4. ✅ `no_metadata_leakage` - 动态扫描 oracle 字段
5. ✅ `llm_only_decisions` - 检查四个原始载荷非空
6. ✅ `planner_visible_choice_only` - 规划器只选可见候选
7. ✅ `retriever_visible_choice_only` - 检索器只选可见候选

**边界/警告：**
- 🔴 **范围仅限 dev 固定答案**：fixed-answer-auth-001, fixed-answer-cache-001, fixed-answer-worker-001
- 🔴 **不能声明形式化财务优势**：formal_superiority_claim_allowed = False
- ⚠️ **两项检查硬编码**：no_statebus_imports 和 no_lexical_fallback 始终 True，无法运行时失败
- ✅ **质量对等真实**：双方都通过相同验证器

**效率对比：**
- ✅ **令牌节省**：-1023 tokens (-34%)
- ✅ **提示字节节省**：-4992 bytes (-39%)
- 🔴 **时间增加**：+9906ms (+108%) - StateBus 更慢

**不支持声明：**
- ❌ "形式化财务外部优势"
- ❌ "端到端速度优势"

**支持声明：**
> "Dev 固定答案外部纯文本公平门通过（3/3 案例，0 失败），每案例 7 项公平检查全覆盖。StateBus 展示令牌和提示字节显著节省（-34% tokens, -39% bytes），但系统开销当前为正（+9.9s）。形式化外部标题资格待定。"

---

### 7. StateBus 端到端速度更快

**声明强度：** 🔴 **Unsupported**

| 维度 | 证据 | 位置 |
|------|------|------|
| **端到端时间** | 🔴 api_task_ms_delta = **+9906ms**（更慢） | codex-raw-fairness-20260706 JSON |
| **LLM 时间** | 🔴 api_llm_ms_delta = **+2588ms**（更慢） | 同上 |
| **系统开销** | 🔴 api_system_overhead_ms_delta = **+1643ms** | 同上 |
| **所有审计一致** | 🔴 所有审计报告一致：StateBus 慢 9-13 秒 | 文档 12, 14, 15, 16 |

**每案例分解：**
- fixed-answer-auth-001: +6551ms
- fixed-answer-cache-001: +1610ms
- fixed-answer-worker-001: +1745ms

**边界/警告：**
- 🔴 **不能声明速度优势**
- 🔴 **不能声明延迟改进**
- ✅ **令牌和字节节省真实**：-1023 tokens, -4992 bytes
- ⚠️ **-65.7% CodeAct 加速**仅限同进程热缓存重运行，不是通用改进

**支持声明：**
> "StateBus 展示了令牌和提示字节的显著效率改进（-34% tokens, -39% prompt bytes），但当前系统开销为正（+9.9s）。优化空间明确，资源效率改进已验证。"

---

### 8. openEuler 兼容性验证

**声明强度：** ⭐ **Weak (容器)** 🔴 **Unsupported (VM)**

| 维度 | 证据 | 位置 |
|------|------|------|
| **容器测试** | ✅ 194 tests passed | Docker 容器内 pytest |
| **容器镜像** | ✅ openEuler 24.03-LTS-SP3 | `docker/Dockerfile` |
| **VM 验证** | 🔴 **无 VM 阶段证据** | 未找到 VM 验证日志 |

**边界/警告：**
- 🔴 **不能声明 openEuler VM 验证**
- ✅ **可以声明容器环境测试通过**
- ℹ️ CLAUDE.md 明确："Do not claim openEuler compatibility unless validated in VM"

**支持声明：**
> "openEuler 24.03-LTS-SP3 容器环境测试通过（194 tests）。"

---

### 9. memfd transport 为 benchmark 主路径

**声明强度：** ⭐ **Weak (能力展示)** 🔴 **Unsupported (benchmark 主线)**

| 维度 | 证据 | 位置 |
|------|------|------|
| **代码实现** | ✅ memfd_create + SCM_RIGHTS + shm fallback | `v2/state/store.py:26-75` |
| **能力测试** | ✅ tests/v2/ 通过 | pytest 覆盖 |
| **formal benchmark** | 🔴 未观测到 memfd 路径被使用 | formal_primary stdout.json 无 state_pool_mode 字段 |
| **compare benchmark** | 🔴 审计脚本 stage 08 使用 --benchmark-tier dev | `scripts/run_v2_full_container_audit_suite.sh:306` |

**边界/警告：**
- 🔴 **不在 formal/compare benchmark 主线**
- ✅ **真实实现存在且通过测试**
- ℹ️ **可作为能力展示**，不能作为 benchmark 证明的主路径

**支持声明：**
> "MemfdStatePool 真实实现（memfd_create + SCM_RIGHTS + shm fallback），能力测试通过。"

---

### 10. 形式化广泛推理优势

**声明强度：** 🔴 **Unsupported**

| 维度 | 证据 | 位置 |
|------|------|------|
| **案例数量** | 🔴 只有 8 案例 | formal_primary stdout.json |
| **案例类型** | 🔴 全部单指标表格检索 | `tasks/formal/financial_report_analysis_v1/` |
| **复杂推理** | 🔴 无多轮推理、多表关联、时间序列分析 | 任务定义缺失 |

**边界/警告：**
- 🔴 **不能声明广泛推理优势**
- 🔴 **不能声明复杂多代理协作优势**
- ✅ **可以声明精密锚点质量基线**

**支持声明：**
> "形式化质量基线维持（8/8 精密锚点案例通过，单指标表格检索）。"

---

### 11. KV cache / 隐藏状态交接

**声明强度：** ℹ️ **Not Claimed (未来工作)**

| 维度 | 证据 | 位置 |
|------|------|------|
| **实现状态** | ℹ️ 明确标记为未来工作 | `docs/reports/final_v2_evidence_index_20260703.md` |
| **CLAUDE.md 指导** | ℹ️ "描述为 Engine-Local Prefix Reuse" | CLAUDE.md |

**支持声明：**
> "KV cache 和隐藏状态交接为未来工作。当前仅依赖引擎本地前缀复用机制。"

---

## 总结：声明强度矩阵

| 声明 | 强度 | 代码 | 测试 | Benchmark | 限制 |
|------|------|------|------|-----------|------|
| 类型化控制平面 | ⭐⭐⭐ Strong | ✅ | ✅ | ✅ | ⚠️ deterministic 模式为测试线束 |
| Ref 类型分离 | ⭐⭐⭐ Strong | ✅ | ✅ | ✅ | 无 |
| 非文本状态传输 | ⭐⭐ Medium/Strong | ✅ | ✅ | ⚠️ 4/6 | 🔴 非均匀覆盖 |
| 形式化质量基线 | ⭐⭐⭐ Strong (质量) | ✅ | ✅ | ✅ | 🔴 范围狭窄（8 案例） |
| 连续重放/复用 | ⭐⭐⭐ Strong | ✅ | ✅ | ✅ | ⚠️ 命名需降级 |
| 外部公平门 (dev) | ⭐⭐⭐ Strong | ✅ | ✅ | ✅ | 🔴 仅 dev 范围 |
| 端到端速度 | 🔴 Unsupported | - | - | 🔴 反证 | 🔴 更慢 +9.9s |
| openEuler VM | 🔴 Unsupported | - | ⚠️ 容器 | 🔴 无 | 🔴 无 VM 证据 |
| memfd 主路径 | 🔴 Unsupported | ✅ | ✅ | 🔴 无 | 🔴 非 benchmark 主线 |
| 广泛推理 | 🔴 Unsupported | - | - | 🔴 反证 | 🔴 只有 8 案例 |
| KV cache | ℹ️ Not Claimed | - | - | - | ℹ️ 未来工作 |

---

**最后更新：** 2026-07-06

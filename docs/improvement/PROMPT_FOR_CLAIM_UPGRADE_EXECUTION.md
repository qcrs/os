# Prompt: 执行 StateBus v2 声明升级计划

**任务目标：** 根据 `docs/improvement/18_claim_upgrade_execution_plan.md` 执行声明升级修复，将"不能声称"的项目通过真实工程修复升级为"完全支持的声明"。

**当前代码库状态：**
- 分支：`feat/statebus-v2-container-runtime`
- HEAD：`a31089f` (Add document 17 final system audit and document 18 upgrade plan)
- 基线审计：文档 17 最终系统审计报告

---

## 一、环境准备

### 1.1 进入容器环境

StateBus v2 需要在 Docker 容器中运行（openEuler 24.03-LTS-SP3）。

```bash
# 如果容器未运行，先启动
export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
export STATEBUS_DOCKER_TARGET=core
docker compose -f docker/compose.yaml up -d

# 进入容器
docker exec -it statebus-dev-qcrs bash
```

### 1.2 激活环境

进入容器后，激活 StateBus 环境：

```bash
# 在容器内执行
cd /workspace
source deploy/activate_statebus_host.sh

# 验证环境
python -c "import v2.runtime.driver; print('Environment OK')"
```

### 1.3 验证基线测试通过

```bash
# 快速烟雾测试（容器内）
python -m runtime.smoke

# 完整测试套件（可选，耗时 ~15 分钟）
python -m pytest -q tests/v2/
# 期望：214 passed
```

---

## 二、必读文档

在开始修复前，请仔细阅读以下文档：

### 核心文档（必读）

1. **`docs/improvement/18_claim_upgrade_execution_plan.md`**
   - 完整的执行计划和步骤
   - 可升级项目 vs 保守表述项目
   - 时间预算和风险评估

2. **`docs/improvement/17_final_system_audit_20260706.md`**
   - 当前状态基线
   - 问题分类账
   - 证据强度分级

3. **`docs/improvement/artifacts/17_final_system_audit/17d_issue_ledger.md`**
   - 完整的问题清单（P0/P1/P2）
   - 每个问题的当前状态

4. **`docs/improvement/artifacts/17_final_system_audit/17e_remediation_plan.md`**
   - 详细修复方案
   - 验证命令和回归测试

### 参考文档

5. **`CLAUDE.md`** - 项目约束和命令参考
6. **`docs/contracts/v2_role_contract.md`** - v2 角色契约
7. **`docs/contracts/v2_persistence_profiles.md`** - 持久化配置文件

---

## 三、执行计划概览

根据 `18_claim_upgrade_execution_plan.md`，你需要按以下顺序执行：

### 阶段 1：快速胜利（3 小时，必做）

**目标：** memfd 主线集成 + 4 项保守表述文档更新

**任务清单：**
- [ ] 1.1 添加 `--state-pool-mode` 参数到 `v2/benchmark/live_runner.py`
- [ ] 1.2 在 `v2/runtime/driver.py` 记录 `state_pool_mode_used` 指标
- [ ] 1.3 更新 `scripts/run_v2_full_container_audit_suite.sh` 启用 memfd
- [ ] 1.4 运行 formal benchmark 验证 memfd 路径
- [ ] 1.5 更新 4 项保守表述文档

**验证命令：**
```bash
# 运行 formal benchmark（容器内）
python -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier formal \
  --role-path-mode deterministic \
  --embedding-mode deterministic \
  --state-pool-mode memfd

# 验证 JSON 输出
cat runs/*/formal-*/stdout.json | jq '.state_pool_mode_used'
# 期望输出："memfd"
```

### 阶段 2：高价值修复（7 小时，强烈建议）

**目标：** 扩展形式化任务家族（8 → 25 案例）

**任务清单：**
- [ ] 2.1 设计 4 个新任务家族（多期趋势、跨表关联、条件聚合、异常检测）
- [ ] 2.2 创建 17 个新案例（5+5+4+3）
- [ ] 2.3 实现 4 个验证器
- [ ] 2.4 注册到 `v2/benchmark/task_registry.py`
- [ ] 2.5 运行 formal benchmark 验证 25/25 通过
- [ ] 2.6 更新文档声明

**目录结构：**
```
tasks/formal/
├── financial_report_analysis_v1/        # 现有 8 案例
├── multi_period_trend_analysis_v1/      # 新增 5 案例
├── cross_table_join_analysis_v1/        # 新增 5 案例
├── conditional_aggregation_v1/          # 新增 4 案例
└── anomaly_detection_v1/                # 新增 3 案例
```

**验证命令：**
```bash
# 运行扩展后的 formal benchmark（容器内）
python -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier formal \
  --role-path-mode deterministic \
  --embedding-mode deterministic

# 检查案例数和质量
cat runs/*/formal-*/stdout.json | jq '{
  case_count: .L3_case_count,
  quality_pass: .L3_quality_pass_count,
  families: .families | length
}'
# 期望：case_count=25, quality_pass=25, families=5
```

### 阶段 3：高风险尝试（6.5 小时，可选）

**目标：** 将外部公平门扩展到 formal tier

**⚠️ 风险警告：** 外部基线可能质量追平或超过 StateBus，导致无法声称优势。

**任务清单：**
- [ ] 3.1 为 8 个 formal 案例添加 `external_visible_candidates`
- [ ] 3.2 验证 `v2/benchmark/external_text_baseline.py` 支持 formal tier
- [ ] 3.3 在 1-2 案例上试运行外部基线（决策点）
- [ ] 3.4 如果外部基线质量可接受，运行完整 formal tier 外部比较
- [ ] 3.5 根据结果更新文档

**验证命令：**
```bash
# 运行 formal tier 外部比较（容器内，需要 STATEBUS_LLM_API_KEY）
export STATEBUS_LLM_API_KEY="your-api-key"

python -m v2.benchmark.live_runner \
  --suite compare \
  --benchmark-tier formal \
  --role-path-mode api \
  --embedding-mode local

# 检查关键指标
cat runs/*/compare-formal-*/stdout.json | jq '{
  formal_superiority_claim_allowed,
  statebus_quality: .statebus_quality_pass_count,
  external_quality: .external_quality_pass_count,
  tokens_delta: .api_llm_total_tokens_delta
}'
```

### 额外分析：端到端速度优化（可选，20-40 小时）

**目标：** 分析并尝试减少系统开销（从 +9.9s 缩小到可接受范围）

⚠️ **注意：** 文档 18 标记为"需要架构级优化"，但你可以先分析低垂果实（quick wins）。

**可能的优化路径（优先级排序）：**

1. **角色并行执行（高收益，中难度）**
   - 当前：Planner → Retriever → Executor → Summarizer（串行）
   - 优化：Retriever + Executor 部分并行
   - 预计收益：-2 to -4 秒
   - 文件：`v2/runtime/driver.py`

2. **优化序列化开销（中收益，中难度）**
   - 当前：每次角色切换完整序列化/反序列化
   - 优化：增量序列化 + 懒加载
   - 预计收益：-1 to -2 秒
   - 文件：`v2/state/store.py`, `v2/refs/models.py`

3. **减少 LLM 调用延迟（低收益，高难度）**
   - 当前：4 个独立 LLM 调用
   - 优化：KV cache 复用（需要引擎支持）
   - 预计收益：-1 to -3 秒
   - 依赖：外部 LLM 引擎特性

**分析任务清单：**
- [ ] 使用 profiler 分析 `v2/runtime/driver.py` 热点
- [ ] 测量每个角色的纯执行时间 vs 切换开销
- [ ] 评估并行执行的可行性和收益
- [ ] 如果收益 > 2 秒，考虑实施

**Profiling 命令：**
```bash
# 在容器内运行
python -m cProfile -o profile.stats -m v2.benchmark.live_runner \
  --suite compare \
  --benchmark-tier dev \
  --role-path-mode deterministic \
  --embedding-mode deterministic

# 分析结果
python -c "
import pstats
p = pstats.Stats('profile.stats')
p.sort_stats('cumulative').print_stats(30)
"
```

### 额外分析：通用答案恢复的可行性（可选）

**目标：** 评估是否可以实现"模糊匹配"的重放准入

⚠️ **注意：** 文档 18 标记为"架构设计特性"，但你可以探索安全的模糊匹配方案。

**可能的方案：**

1. **基于嵌入相似度的准入门（中风险）**
   - 当前：SHA-256 精确匹配（家族 + 工具集）
   - 优化：嵌入相似度 > 0.95 + 工具集子集匹配
   - 风险：误匹配导致错误答案
   - 缓解：仍然跳过规划，保留检索+执行+总结

2. **分级重放准入（低风险）**
   - Level 1: 精确匹配（当前）→ 跳过 2 步
   - Level 2: 家族匹配 + 嵌入相似 > 0.95 → 跳过 1 步
   - Level 3: 家族匹配 + 嵌入相似 > 0.80 → 辅助（无跳步）
   - 文件：`v2/runtime/replay.py`

**分析任务清单：**
- [ ] 读取当前重放准入逻辑（`v2/runtime/replay.py:123-528`）
- [ ] 评估嵌入相似度的误匹配风险
- [ ] 在连续任务上模拟分级准入的收益
- [ ] 如果安全性可保证，考虑实施 Level 2

---

## 四、Git 工作流程

### 4.1 分支策略

在 `feat/statebus-v2-container-runtime` 上工作，每完成一个阶段就提交：

```bash
# 在宿主机（容器外）执行 git 命令

# 阶段 1 完成后
git add v2/benchmark/live_runner.py v2/runtime/driver.py scripts/run_v2_full_container_audit_suite.sh
git commit -m "Stage 1: Integrate memfd into benchmark mainline

- Add --state-pool-mode parameter to live_runner
- Record state_pool_mode_used in driver telemetry
- Enable memfd in audit script stage 07
- Verified: formal benchmark uses memfd transport

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

# 阶段 2 完成后
git add tasks/formal/ v2/benchmark/task_registry.py
git commit -m "Stage 2: Expand formal task families to 25 cases

- Add multi_period_trend_analysis_v1 (5 cases)
- Add cross_table_join_analysis_v1 (5 cases)
- Add conditional_aggregation_v1 (4 cases)
- Add anomaly_detection_v1 (3 cases)
- Verified: 25/25 quality pass on formal benchmark

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

# 阶段 3 完成后（如果执行）
git add tasks/formal/*/samples/*.json v2/benchmark/external_text_baseline.py
git commit -m "Stage 3: Extend external fairness gate to formal tier

- Add external_visible_candidates to 8 formal cases
- Run formal tier external comparison
- Result: [填写实际结果，如 formal_superiority_claim_allowed=True/False]

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### 4.2 文档更新提交

每个阶段完成后，更新相关文档：

```bash
# 更新文档
git add docs/improvement/ docs/reports/ docs/contracts/

git commit -m "Update documentation after claim upgrades

- Update v2_experiment_summary with new metrics
- Mark historical documents (MASTER_PRESENTATION_GUIDE.md)
- Update safe claim language (17f)
- Add stage completion evidence

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### 4.3 创建里程碑标签

所有阶段完成后，打标签：

```bash
git tag -a v2-claim-upgrade-20260706 -m "StateBus v2 claim upgrade milestone

- memfd mainline integration ✅
- Formal families expanded to 25 cases ✅
- [Optional] Formal external fairness gate ✅/⚠️

Strong evidence claims: 6 → 8-9
Unsupported claims: 6 → 3-4"

git push origin feat/statebus-v2-container-runtime --tags
```

---

## 五、关键约束和注意事项

### 5.1 不要违反的原则（来自 CLAUDE.md）

1. ❌ **不要声称 openEuler VM 兼容**，除非在 VM 中验证（当前只有容器）
2. ❌ **不要声称 KV cache / 隐藏状态交接**，明确标记为未来工作
3. ❌ **不要使用 `nsjail`**，系统未安装
4. ❌ **不要提交配置文件**：`deploy/statebus_llm.yaml.local`, `deploy/statebus_llm.env.local`
5. ✅ **formal benchmark 只引用 `--embedding-mode local`** 结果（Qwen3-Embedding-0.6B）

### 5.2 测试和验证要求

每个修改后，必须运行回归测试：

```bash
# 最小回归测试（容器内，~5 分钟）
python -m runtime.smoke
python -m pytest -q tests/v2/test_driver.py tests/v2/test_replay.py

# 完整回归测试（容器内，~15 分钟）
python -m pytest -q tests/v2/

# Benchmark 验证（容器内，视范围而定）
python -m v2.benchmark.live_runner --suite preflight \
  --role-path-mode deterministic --embedding-mode deterministic
```

### 5.3 Benchmark 运行环境

- **deterministic 模式**：用于快速验证，无需 API key
- **api 模式**：用于真实 LLM 调用，需要 `STATEBUS_LLM_API_KEY`
- **local embedding**：使用 `$HOME/statebus/models/Qwen3-Embedding-0.6B`
- **API embedding**：需要 API key（不用于 formal 声明）

### 5.4 容器和宿主机文件同步

Docker compose 挂载了宿主机目录到容器 `/workspace`：
- 容器内修改会立即反映到宿主机
- Git 操作在宿主机执行
- 代码修改、测试在容器内执行

---

## 六、预期输出

完成所有阶段后，你需要提供：

### 6.1 代码修改

- [ ] `v2/benchmark/live_runner.py` - 添加 `--state-pool-mode` 参数
- [ ] `v2/runtime/driver.py` - 记录 `state_pool_mode_used` 指标
- [ ] `scripts/run_v2_full_container_audit_suite.sh` - 启用 memfd
- [ ] `tasks/formal/` - 4 个新任务家族，17 个新案例
- [ ] `v2/benchmark/task_registry.py` - 注册新家族
- [ ] [可选] `tasks/formal/*/samples/*.json` - 外部可见候选定义
- [ ] [可选] `v2/runtime/driver.py` - 性能优化（如果执行额外分析）

### 6.2 文档更新

- [ ] 标注历史文档（`docs/reports/MASTER_PRESENTATION_GUIDE.md` 等）
- [ ] 更新 `docs/reports/v2_experiment_summary_20260703.md`
- [ ] 更新 `docs/improvement/artifacts/17_final_system_audit/17f_safe_claim_language.md`
- [ ] 创建新文档：`docs/improvement/19_claim_upgrade_completion_report_20260706.md`

### 6.3 Benchmark 证据

- [ ] memfd 路径 JSON 证据（`state_pool_mode_used: "memfd"`）
- [ ] 25 案例 formal benchmark JSON（`case_count: 25, quality_pass: 25`）
- [ ] [可选] formal tier 外部比较 JSON（`formal_superiority_claim_allowed: true/false`）

### 6.4 最终总结文档

创建 `docs/improvement/19_claim_upgrade_completion_report_20260706.md`，包含：

1. **执行摘要**：完成了哪些阶段，耗时多少
2. **升级前后对比**：Strong 证据声明 6 → X，Unsupported 6 → Y
3. **新支持的声明**：完整的安全表述
4. **Benchmark 证据索引**：所有 JSON 文件路径
5. **Git 提交历史**：所有相关 commit
6. **回归测试结果**：pytest 通过率，benchmark 通过率
7. **剩余问题**：哪些仍然只能保守表述
8. **推荐答辩口径**：更新后的 30 秒答辩模板

---

## 七、故障排查

### 常见问题

**Q1: 容器内找不到 Python 模块**
```bash
# 确认已激活环境
source deploy/activate_statebus_host.sh
echo $PYTHONPATH  # 应包含 /workspace
```

**Q2: Benchmark 运行失败（missing API key）**
```bash
# 使用 deterministic 模式避免 API 调用
python -m v2.benchmark.live_runner \
  --role-path-mode deterministic \
  --embedding-mode deterministic
```

**Q3: 测试失败**
```bash
# 查看详细错误
python -m pytest -vv tests/v2/test_driver.py

# 只运行失败的测试
python -m pytest --lf
```

**Q4: Git 提交失败（pre-commit hook）**
```bash
# 查看 hook 错误
git commit -v

# 如果是代码格式问题，运行格式化工具（如果有）
# 不要使用 --no-verify 跳过 hook
```

---

## 八、执行检查清单

### 启动前检查

- [ ] 已阅读 `docs/improvement/18_claim_upgrade_execution_plan.md`
- [ ] 已阅读 `docs/improvement/17_final_system_audit_20260706.md`
- [ ] 容器环境已启动并激活
- [ ] 基线测试通过（`python -m runtime.smoke`）
- [ ] Git 工作区干净（`git status`）
- [ ] 当前分支为 `feat/statebus-v2-container-runtime`

### 阶段 1 检查

- [ ] `--state-pool-mode` 参数已添加
- [ ] `state_pool_mode_used` 指标已记录
- [ ] 审计脚本已更新
- [ ] Formal benchmark 验证 memfd 路径成功
- [ ] JSON 输出包含 `state_pool_mode_used: "memfd"`
- [ ] 回归测试通过
- [ ] Git 提交完成

### 阶段 2 检查

- [ ] 4 个新任务家族已创建
- [ ] 17 个新案例已实现
- [ ] 4 个验证器已实现
- [ ] 任务注册到 `task_registry.py`
- [ ] Formal benchmark 25/25 通过
- [ ] JSON 输出包含 `case_count: 25`
- [ ] 回归测试通过
- [ ] Git 提交完成

### 阶段 3 检查（可选）

- [ ] 外部可见候选已添加
- [ ] 试运行 1-2 案例成功
- [ ] 外部基线质量评估完成（决策点）
- [ ] 完整 formal tier 外部比较完成
- [ ] JSON 输出包含 `formal_superiority_claim_allowed`
- [ ] 回归测试通过
- [ ] Git 提交完成

### 文档更新检查

- [ ] 历史文档已标注
- [ ] 实验摘要已更新
- [ ] 安全声明语言已更新
- [ ] 完成报告已创建（文档 19）
- [ ] Git 提交完成

### 最终交付检查

- [ ] 所有代码修改已提交
- [ ] 所有文档更新已提交
- [ ] 所有测试通过（pytest 214 passed）
- [ ] 所有 benchmark 证据已归档
- [ ] Git 标签已创建
- [ ] 完成报告已审阅

---

## 九、立即开始

**你现在的工作流程：**

1. **复制本 prompt 到你的 Claude 会话**
2. **进入容器环境**（见第一节）
3. **阅读必读文档**（见第二节）
4. **按阶段顺序执行**（见第三节）
5. **每个阶段完成后提交**（见第四节）
6. **创建最终总结文档**（见第六节）

**开始命令：**

```bash
# 宿主机执行
export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
export STATEBUS_DOCKER_TARGET=core
docker compose -f docker/compose.yaml up -d
docker exec -it statebus-dev-qcrs bash

# 容器内执行
cd /workspace
source deploy/activate_statebus_host.sh
python -m runtime.smoke  # 验证环境

# 开始阶段 1
# [按照计划执行...]
```

---

**Prompt 创建人：** Claude (Kiro)
**Prompt 创建时间：** 2026-07-06
**目标执行时间：** 10-16.5 小时
**预期收益：** Strong 证据声明 6 → 8-9，Unsupported 声明 6 → 3-4

**准备好了吗？开始执行！**

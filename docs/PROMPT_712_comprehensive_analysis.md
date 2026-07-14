# Prompt: StateBus v2 Qwen3-32B 综合实验分析与问题诊断

## 上下文 Context

### 代码库状态
- **仓库**: `/home/qcrs/statebus/project`
- **分支**: `feat/statebus-gap-fix-and-logit-state`
- **最新提交**: `c5bb94a` — "kv: Track A/B/C — logit peak-scan, baseline schema parity, task_metrics persist"
- **今日脚本修复**（未提交）:
  1. `scripts/run_v2_comprehensive_qwen3.sh` Stage 1 — preflight 绕过 `run_v2_local_vllm_formal_suite.sh`，直接用轻量路径检查
  2. `scripts/run_v2_local_vllm_formal_suite.sh` — jq 汇总脚本增加条件分支，支持 `statebus`/`formal` 和 `compare` 两种 suite 输出格式

### Track A/B/C 改动摘要（commit c5bb94a）

**Track A: Logit Peak-Scan (替代 top_logprobs[-1] 末位偏差)**
- `v2/runtime/logit_state.py` 完全重写：`serialize_logit_state_v2()` 扫描整个 logprobs 序列，找最大 entropy 位置作为 `peak_position`
- 新增字段：`varentropy`, `top_gap`, `peak_position`, `decision_entropy`
- `v2/runtime/role_path.py` 中 `ExecutorRoleDecision` 增加 3 字段：`logit_varentropy`, `logit_top_gap`, `logit_peak_position`
- `v2/runtime/smoke.py` 修复：增加 `task_metrics.json` 持久化（之前只有 `telemetry.json`，但 logit 字段在 smoke 层添加，未落盘）

**Track B: Prefix Feedback Loop**
- `v2/runtime/prefix_feedback.py` 新文件：`PrefixCacheFeedbackLoop` 类，用于校准 prefix cache hit rate 预测 vs 实测

**Track C: Baseline Schema Parity (enum closed-set)**
- `v2/benchmark/external_text_baseline.py` 修复：`_build_baseline_selection_schema()` 增加 `additionalProperties: False` 和所有字段 `enum` 约束，消除 Qwen3-32B 的 JSON 退化（copier attractor）

**测试覆盖**
- `tests/v2/test_logit_state.py` — 15 个测试全过（0.57s）

### 实验配置

**模型**: Qwen3-32B (local vLLM, port 53334, GPU 0, 65GB, `enable_prefix_caching=True`, `max_model_len=8192`)

**实验脚本**: `scripts/run_v2_comprehensive_qwen3.sh`

**Stage 设计**（简单→复杂，8192 context 约束，结果每阶段落盘）:
- **Stage 0**: vLLM + GPU 健康检查
- **Stage 1**: Preflight — JSON schema / Track C 验证（dev tier）
- **Stage 2**: Logit KV 链路验证 — statebus dev tier, max 2 cases（验证 Track A logit 字段 + KV prefix cache）
- **Stage 3**: Compare suite formal — text vs protocol（G-01 gap: 验证 compare mode 的公平性，Qwen3-32B 替换 DeepSeek）
- **Stage 4**: Statebus replay-ready — L3 auto-bootstrap（G-02 gap: KV 主线 replay memory）
- **Stage 5**: Continuous multi-family — csv_table_profile + cross_period_financial（G-03/G-11 gap: 单一 family → 多 family，连续稳定性）
- **Stage 6**: Formal L0-L3 全量 — 25 case, 5 family, E7（G-01 最终证据）

**关键环境变量**:
```bash
STATEBUS_LOCAL_VLLM_BASE_URL=http://127.0.0.1:53334/v1
STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix
STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1
STATEBUS_EMBED_DEVICE=cuda:1
STATEBUS_EMBED_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B
```

### 实验结果路径

**宿主机**: `/home/qcrs/statebus/runs/comprehensive_qwen3_20260712_223614/`

**容器内**: `/statebus/runs/comprehensive_qwen3_20260712_223614/`

**主要输出文件**:
```
comprehensive_qwen3_20260712_223614/
├── run.log                     # 主脚本 stdout
├── s0_vllm_health.json         # vLLM health probe
├── s0_gpu_memory.txt           # GPU 内存快照
├── s1_preflight.log            # Stage 1 日志
├── s2_logit_verify.log         # Stage 2 日志
├── s2_logit_report.json        # Stage 2 Python 汇总
├── s3_compare.log              # Stage 3 日志
├── s4_replay.log               # Stage 4 日志
├── s5a_continuous_csv.log      # Stage 5a 日志
├── s5b_continuous_cross.log    # Stage 5b 日志
├── s6_formal_e7.log            # Stage 6 日志
└── final_summary.json          # 最终汇总（Python 脚本生成，字段为 null 说明脚本有 bug）
```

**每个 stage 对应的 run 目录** (容器内 `/statebus/runs/<run_id>/`):
- `s1-preflight-20260712_223614/`
- `s2-logit-verify-20260712_223614/`
- `s3-compare-qwen3-20260712_223614/`
- `s4-replay-ready-qwen3-20260712_223614/`
- `s5a-continuous-csv-20260712_223614/`
- `s5b-continuous-cross-20260712_223614/`
- `s6-formal-qwen3-e7-20260712_223614/`

每个 run 目录包含：
- `formal_suite.stdout.json` — live_runner 原始输出
- `formal_suite.summary.json` — jq 汇总后的精简版（如果 jq 成功）
- `runtime/benchmark_reports/*.json` — 各 layer 和 mode 的详细报告
- `runtime/benchmark_reports/*.md` — markdown 报告
- `workspaces/<case_id>/` — 每个测试 case 的工作目录（含 agent logs、task outputs、telemetry）

### 已知问题快照

**Stage 3 Compare 核心矛盾**（会话中已诊断）:
- StateBus: 66,472 tokens, quality floor 25/25 pass
- Baseline (external text path): 95,592 tokens, quality floor **0/25 pass**
- Token delta: -29,120 (-30.5%)
- `comparison_valid = false`, `invalid_reason = "quality_floor_gate_failed"`
- 结论：baseline 端在 Qwen3-32B + formal tier 下完全失效，无法建立公平比较基线

**final_summary.json 字段全为 null**:
- 说明综合脚本末尾的 Python 汇总代码有 bug（未正确读取各 stage 的 summary JSON）

---

## 任务 Task

你需要**系统化分析这次完整实验的所有结果**，从原始日志、JSON 输出、benchmark 报告中提取关键信号，诊断问题根因，评估 Track A/B/C 和各 gap 修复的有效性，并给出后续优化方案。

### 分析目标
0. **严格约束**
   - 下面问题只是一部分，需要全面筛选和梳理实验结果，汇总各种有用的字段，帮助分析 不要偷懒

1. **Track A (Logit Peak-Scan) 有效性**
   - Stage 2 的 logit 字段值（`logit_varentropy`, `logit_top_gap`, `logit_peak_position`）是否合理？
   - `peak_position` 是否避开了末位？`varentropy` 是否有区分度？
   - Stage 3/4/5/6 中 `logit_state_transfer_count` 是否 >0？

2. **Track B (Prefix Feedback) 部署情况**
   - 代码已提交但未在实验中激活使用——确认是否需要后续实验验证

3. **Track C (Baseline Schema Parity) 有效性**
   - Stage 1 preflight 是否通过？
   - Stage 3 baseline 0/25 失败的根因是什么？
     - Track C 修复是否在 external text path 生效？
     - 是否存在其他 JSON schema 配置不一致？
     - Qwen3-32B 在 formal tier 的 quality floor 定义是否过严？
   - Stage 6 formal 的 baseline 表现如何？

4. **G-01 Gap: Compare Suite 公平性**
   - Stage 3 `comparison_valid = false` 的深层原因
   - Stage 6 formal 全量是否也遇到同样问题？
   - 需要什么修复才能让 `comparison_valid = true`？

5. **G-02 Gap: KV 主线 Replay Memory**
   - Stage 4 replay-ready 是否成功 auto-bootstrap？
   - `reuse_gain` 是否 >0？`skipped_step_count` 是否 >0？
   - 实际的 KV prefix cache hit rate 是多少？

6. **G-03 / G-11 Gap: Multi-Family 和连续稳定性**
   - Stage 5a (csv_table_profile) 和 5b (cross_period_financial) 各自的结果？
   - 是否成功覆盖 2 个 family？
   - 连续运行的稳定性指标？

7. **Stage 6 Formal 全量结果**
   - 25 case, 5 family 是否全部完成？
   - L0/L1/L2/L3 各层的 quality floor pass count？
   - Protocol vs text token delta？
   - 是否达到 formal claim 级别？

8. **Hidden State (Logit) 实现的实际效果**
   - `logit_state_transfer_count` 在各 stage 的分布？
   - 与 `neural_prefix_shared_prefix_bytes`（KV cache）的相关性？
   - 对决策质量的影响？

9. **对比历史 API 结果**
   - 找到 `docs/improvement/` 或类似目录下的历史 fixed-answer API 结果（DeepSeek 等）
   - 对比 token delta、quality pass、efficiency 指标
   - Qwen3-32B 的表现是进步还是退步？

10. **缺失的实验**
    - 根据 audit 文档 (`30_independent_audit_report_20260711.md`, `31_comprehensive_gap_audit_20260711.md`) 和当前结果，还缺什么验证？

11. **实现 Bug 和优化点**
    - 脚本层 bug（如 `final_summary.json` 字段 null）
    - 运行时逻辑 bug
    - 性能瓶颈
    - 可观测性缺口

---

## 执行指南

### 环境访问

**容器**: `statebus-dev-qcrs`

**进入方式**:
```bash
docker exec -it statebus-dev-qcrs bash
# 或者
docker exec -u root -it statebus-dev-qcrs bash  # root 权限
```

**容器内环境激活**:
```bash
source /home/qcrs/statebus/project/docker/activate_statebus_container.sh
```

**宿主机环境**:
- vLLM 服务运行中：`http://127.0.0.1:53334/v1` (Qwen3-32B, GPU 0)
- Python 3.11, pytest, jq, docker CLI 可用

### 分析方法

1. **读取所有 stage 日志和 JSON 输出**
   - 用 `Read` 工具或 `docker exec` + Python 脚本
   - 提取关键字段，构建结构化数据集

2. **写 Python 分析脚本**（推荐）
   - 脚本路径建议：`scripts/analyze_comprehensive_qwen3_20260712.py`
   - 输出 markdown 报告：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/40_qwen3_comprehensive_analysis_20260712.md`
   - 输出结构化 JSON：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/40_qwen3_comprehensive_data_20260712.json`

3. **分层分析**
   - **Stage-level**: 每个 stage 的 pass/fail, 关键指标, 异常信号
   - **Case-level**: 深入失败 case 的日志、agent 决策、tool 输出
   - **Metric-level**: 汇总各维度指标（token, quality, latency, KV hit rate, logit）

4. **对比分析**
   - 找到 `docs/improvement/` 下之前的 API 实验汇总文档（DeepSeek, GPT-4, Claude 等）
   - 提取对应的 token delta, quality floor pass rate, formal claim 状态
   - 制表对比

5. **根因诊断**
   - Stage 3 baseline 0/25 失败：逐个读取 case workspace，看 external text path 的 JSON 输出、错误日志
   - Track C 是否生效：检查 `_build_baseline_selection_schema()` 在 external path 的调用链
   - KV cache hit rate：从 telemetry 或 vLLM metrics 提取

6. **输出要求**
   - **文档**: 完整的 markdown 分析报告，包含：
     - Executive Summary（3-5 段）
     - 每个 Track 的有效性评估
     - 每个 Gap 的填补状态
     - 发现的 Bug 列表（优先级排序）
     - 优化建议（短期/中期/长期）
     - 缺失实验清单
     - 对比历史结果的表格
   - **数据**: JSON 格式的结构化结果，便于后续脚本消费
   - **修复 PR**: 如果发现明确 bug，准备修复代码（但先在文档中列出，等用户确认优先级）

---

## 参考文档路径

**Audit 文档** (问题清单):
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/30_independent_audit_report_20260711.md`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/31_comprehensive_gap_audit_20260711.md`

**历史 API 结果** (需要你查找，可能在以下路径):
- `docs/improvement/*/` 
- `docs/reports/`
- `docs/evaluation/`
- `eval/results/` (如果存在)

**系统设计文档**:
- `docs/reports/statebus_system_method_task_and_results_explainer.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`

**代码入口**:
- `v2/benchmark/live_runner.py` — suite 编排
- `v2/benchmark/external_text_baseline.py` — baseline (external) path
- `v2/benchmark/fixed_answer_runner.py` — compare suite 主逻辑
- `v2/runtime/role_path.py` — LLM 调用和 logit 采集
- `v2/runtime/logit_state.py` — Track A 实现

---

## 输出格式

完成分析后，输出以下内容：

1. **Markdown 报告**: `docs/improvement/20_v2_comprehensive_truth_audit_20260706/40_qwen3_comprehensive_analysis_20260712.md`
   - 包含所有章节（Executive Summary, Track 评估, Gap 状态, Bug 列表, 优化建议, 对比分析）

2. **结构化数据**: `docs/improvement/20_v2_comprehensive_truth_audit_20260706/40_qwen3_comprehensive_data_20260712.json`
   - 每个 stage 的关键指标 JSON
   - Case-level 失败详情
   - Metric 汇总

3. **简短摘要**（给用户的会话回复）:
   - 3-5 个关键发现（bullet points）
   - 最严重的 2-3 个 bug
   - 下一步建议（是否需要重跑实验、修复代码、补充实验）

4. **可选: 修复脚本**
   - 如果 `final_summary.json` 的 bug 明确且容易修，直接修复 `scripts/run_v2_comprehensive_qwen3.sh` 末尾的 Python 代码

---

## 重要约束

- **不要假设字段存在**：很多 JSON 可能缺字段或为 null，用 `.get()` 或 `// null` 防御
- **不要遗漏 stage**：6 个 stage 都要分析，不能只看部分
- **不要只看汇总**：深入到 case-level 日志，找根因
- **对比要公平**：历史结果可能用不同模型/tier/task，需要说明对比条件
- **优先级排序**：Bug 和优化建议按影响面和严重度排序

---

## 示例分析流程（伪代码）

```python
import json, glob, os
from pathlib import Path

RUNS_ROOT = Path("/statebus/runs")
STAMP = "20260712_223614"
COMPREHENSIVE_DIR = RUNS_ROOT / f"comprehensive_qwen3_{STAMP}"

# Stage 元数据
stages = {
    "s1": {"run_id": f"s1-preflight-{STAMP}", "suite": "preflight"},
    "s2": {"run_id": f"s2-logit-verify-{STAMP}", "suite": "statebus"},
    "s3": {"run_id": f"s3-compare-qwen3-{STAMP}", "suite": "compare"},
    "s4": {"run_id": f"s4-replay-ready-qwen3-{STAMP}", "suite": "statebus"},
    "s5a": {"run_id": f"s5a-continuous-csv-{STAMP}", "suite": "statebus"},
    "s5b": {"run_id": f"s5b-continuous-cross-{STAMP}", "suite": "statebus"},
    "s6": {"run_id": f"s6-formal-qwen3-e7-{STAMP}", "suite": "statebus"},
}

results = {}

for stage_name, meta in stages.items():
    run_dir = RUNS_ROOT / meta["run_id"]
    stdout_json = run_dir / "formal_suite.stdout.json"
    
    if not stdout_json.exists():
        results[stage_name] = {"status": "missing"}
        continue
    
    data = json.loads(stdout_json.read_text())
    
    # 提取关键字段（按 suite 类型）
    if meta["suite"] == "preflight":
        results[stage_name] = {
            "ok": data.get("ok"),
            "checks": data.get("checks", []),
        }
    elif meta["suite"] == "compare":
        results[stage_name] = {
            "comparison_valid": data.get("mode_reports", [{}])[0].get("comparison_valid"),
            "invalid_reason": data.get("mode_reports", [{}])[0].get("invalid_reason"),
            "token_delta": data.get("comparison_summary", {}).get("local_vllm_llm_total_tokens_delta"),
            "statebus_quality_pass": data.get("comparison_summary", {}).get("local_vllm_debug_statebus_quality_floor_pass_count"),
            "external_quality_pass": data.get("comparison_summary", {}).get("local_vllm_debug_external_quality_floor_pass_count"),
        }
    elif meta["suite"] == "statebus":
        # 提取 layers, logit 字段, KV 字段
        layers = data.get("layers", [])
        results[stage_name] = {
            "selected_case_count": data.get("selected_case_count"),
            "layers": [{
                "layer": l.get("layer"),
                "case_count": l.get("aggregated_metrics", {}).get("case_count"),
                "quality_floor_pass": l.get("aggregated_metrics", {}).get("quality_floor_pass_count"),
            } for l in layers],
            # 从 workspace telemetry 提取 logit/KV 指标（需进一步遍历 case）
        }
    
    # 深入 case-level 分析（读取 workspaces/<case_id>/logs/*.json）
    workspaces_dir = run_dir / "workspaces"
    if workspaces_dir.exists():
        case_ids = [d.name for d in workspaces_dir.iterdir() if d.is_dir()]
        results[stage_name]["cases"] = {}
        for case_id in case_ids:
            logs_dir = workspaces_dir / case_id / "logs"
            if logs_dir.exists():
                telemetry = logs_dir / "telemetry.json"
                task_metrics = logs_dir / "task_metrics.json"
                # 读取并提取 logit_*, neural_prefix_* 字段
                # ...

# 汇总分析
# ...

# 生成 markdown 报告
# ...
```

---

## 你的下一步

1. 启动 Docker 容器环境
2. 读取所有 stage 的输出和日志
3. 写 Python 分析脚本（或直接在会话中逐步分析）
4. 生成完整报告和结构化数据
5. 给出摘要和建议

开始吧！

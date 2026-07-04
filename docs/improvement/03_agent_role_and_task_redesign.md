# Agent 角色与任务重设计

**目标**：满足"3类任务"要求，展示角色真实分工，设计可以演示"越跑越快"的连续任务

---

## 问题一：当前只有1类 formal 任务（财务分析）

### 问题描述

所有 formal compare 任务都是 `formal_financial_family`（financial report metric extraction）。赛题要求"至少3类任务"，当前 continuous family 有 CSV 分析和长文档分析，但它们没有对应的 external compare，无法作为完整的任务类演示。

### 解决方案：新增 incident_diagnosis_v2 任务族

**设计原则**：服务诊断任务天然需要日志语义检索（EMBEDDING StateRef），需要探针脚本执行（CodeAct），需要策略跨轮复用（replay）。三个要素完美对应赛题三个维度。

**corpus 结构**（创建 `v2/benchmark/samples/incident_corpus/`）：

```bash
mkdir -p v2/benchmark/samples/incident_corpus/{inference-gateway,service-b,service-c}

# inference-gateway/boot_log.txt
cat > v2/benchmark/samples/incident_corpus/inference-gateway/boot_log.txt << 'EOF'
[00:00.000] systemd: Starting inference-gateway.service
[00:00.012] inference-gateway: Loading model weights from /models/llm-7b
[00:02.341] inference-gateway: Model load complete (2.3s)
[00:02.342] inference-gateway: Waiting for storage mount: /data/inference-cache
[00:08.891] inference-gateway: Storage mounted (6.5s wait) - high IO wait detected
[00:09.001] inference-gateway: Initializing request queue
[00:09.045] inference-gateway: Ready - total startup: 9.0s
EOF

# inference-gateway/journal.txt（含干扰项）
cat > v2/benchmark/samples/incident_corpus/inference-gateway/journal.txt << 'EOF'
Jul 03 09:00:00 systemd[1]: Starting inference-gateway.service...
Jul 03 09:00:08 kernel: EXT4-fs: /dev/sdb1 mounted
Jul 03 09:00:09 inference-gateway[2341]: Service started, listening on :8080
Jul 03 09:00:09 sshd[1204]: Accepted publickey for admin
Jul 03 09:00:10 cron[856]: (CRON) INFO (pidfile fd = 3)
EOF
```

**任务设计（3轮 continuous）**：

```json
// v2/benchmark/samples/incident_corpus/manifest.json
{
  "family_id": "incident_diagnosis_v2",
  "description": "Service startup diagnosis with log-based semantic retrieval",
  "corpus_type": "system_logs",
  "tasks": [
    {
      "task_id": "incident-001",
      "round_number": 1,
      "request_text": "Diagnose why inference-gateway.service takes 9 seconds to start",
      "expected_route": "log_analysis",
      "expected_tool_name": "boot_timing_probe",
      "expected_facts": {
        "slow_phase": "storage_mount",
        "wait_duration_seconds": 6.5,
        "root_cause": "high_io_wait"
      },
      "depends_on": [],
      "minimum_reuse_class": "cold_start"
    },
    {
      "task_id": "incident-002",
      "round_number": 2,
      "request_text": "Diagnose why service-b.service also starts slowly",
      "expected_route": "log_analysis",
      "expected_tool_name": "boot_timing_probe",
      "depends_on": ["incident-001"],
      "minimum_reuse_class": "validated_replay"
    },
    {
      "task_id": "incident-003",
      "round_number": 3,
      "request_text": "Re-check inference-gateway.service after storage optimization",
      "expected_route": "log_analysis",
      "expected_tool_name": "boot_timing_probe",
      "depends_on": ["incident-001"],
      "minimum_reuse_class": "exact_replay"
    }
  ]
}
```

**注册到 live_runner.py**：

```python
# v2/benchmark/live_runner.py：在 TASK_FAMILY_REGISTRY 中添加
TASK_FAMILY_REGISTRY["incident_diagnosis_v2"] = IncidentDiagnosisFamily(
    corpus_dir="v2/benchmark/samples/incident_corpus",
    embedding_field="log_text",
)
```

**验收测试**：

```bash
python -m v2.benchmark.live_runner \
  --suite statebus --benchmark-tier dev \
  --family incident_diagnosis_v2 \
  --role-path-mode api --embedding-mode local \
  --replay-mode replay-ready \
  2>&1 | grep -E "skipped_steps|validated_replay|quality|task_id"
# 期望：Round 2 触发 validated_replay，Round 3 触发 exact_replay
```

---

## 问题二：Retriever 的定位需要主动澄清

### 问题描述

当前 Retriever 对 `formal_financial_family` 使用 `table_retriever`（精确匹配 metric_name），这不是传统意义的"语义检索"。评委会质疑"你的 Retriever 是真检索还是 hardcoded lookup"。

### 解决方案：明确两种检索模式，在报告中主动披露

**在答辩/报告中定位为"结构化路由检索"**：

```
StateBus Retriever 支持两种检索策略，根据任务类型自动选择：

1. 结构化路由检索（Structured Route Retrieval）
   适用：有 schema 约束的 corpus（financial report 等）
   机制：route + tool_name → metric_name 精确匹配
   优点：accuracy=100%，不依赖 LLM 猜测，StateBus 8/8 vs external 6/8 的质量差异来源于此

2. 语义相似度检索（Semantic Similarity Retrieval）
   适用：非结构化文档（日志、长文档等）
   机制：Qwen3-Embedding-0.6B → cosine similarity → top-k
   优点：泛化能力强，continuous family evidence 缩减 57~67%
   使用：api/local embedding mode 下 top_k=3（pipeline.py with_embedding_mode() line 200）
```

两种策略通过同一 StateRef 接口（DENSE_EVIDENCE + EMBEDDING）输出，下游 Executor 无需感知检索方式差异。

---

## 问题三：10轮连续任务的完整展示方案

### 问题描述

赛题要求"稳定执行不少于10轮连续任务"。当前有 csv_correlation_replay_v1（10轮）和 long_doc_metric_replay_v1（10轮），合计20轮，满足要求。但这两个 family 是分开的，没有一个单一的"10轮递增效果演示"。

### 解决方案：设计 cross_period_financial_v1（10轮，越跑越快）

**任务链设计**：

```
Round 1: 提取 ACME 2026Q1 revenue → cold_start，写入 memory
Round 2: 提取 ACME 2025Q4 revenue → validated_replay（复用 Route/Tool）
Round 3: 计算 Q1 vs Q4 delta → exact_replay（两个数值都在 memory）
Round 4: 提取 ACME 2025Q3 revenue → validated_replay
Round 5: 计算三季度趋势 → exact_replay（三个数值都在 memory）
Round 6: 提取 BETA 2026Q1 revenue → validated_replay（复用 Route/Tool）
Round 7: 对比 ACME vs BETA → validated_replay
Round 8: 提取 BETA 2025Q4 → validated_replay
Round 9: 计算 BETA 趋势 → exact_replay
Round 10: 生成完整对比报告 → exact_replay（所有数值都在 memory）
```

**manifest.json**：

```json
{
  "family_id": "cross_period_financial_v1",
  "description": "Cross-period cross-ticker financial analysis — demonstrates progressive memory speedup",
  "corpus_type": "offline_financial_multi_period",
  "tickers": ["ACME", "BETA"],
  "periods": ["2026Q1", "2025Q4", "2025Q3"],
  "expected_progression": {
    "tokens_per_round_trend": "decreasing",
    "skipped_steps_cumulative": "increasing",
    "quality_per_round": "stable_1.0"
  }
}
```

**验收命令**：

```bash
python -m v2.benchmark.live_runner \
  --suite statebus --benchmark-tier dev \
  --family cross_period_financial_v1 \
  --role-path-mode api --embedding-mode local \
  --replay-mode replay-ready \
  2>&1 | grep -E "round|tokens|skipped|reuse_class"
# 期望：tokens 从 Round1 到 Round10 整体下降，skipped_steps 累计增加
```

---

## 问题四：Executor 的"执行"需要更真实

### 问题描述

当前 Executor 对 formal financial task 走 `codeact_data_tasks.py` 的 deterministic 函数，没有展示真正的"工具执行"或"代码生成执行"。对于评委来说，Executor 感觉像是一个"分析器"而不是"执行器"。

### 解决方案

**Option A（快）**：在 incident_diagnosis_v2 中，Executor 真实运行一个探针脚本（读取日志文件，计算启动阶段耗时），通过 bwrap sandbox，输出 timing_profile.json。这样在答辩演示时，可以展示"Executor 真的运行了代码，产生了文件"。

**Option B（更完整）**：在 formal pipeline 中，为部分 task 启用 `force_llm_generation=True`（见 `04_codeact_and_sandbox_hardening.md`），让 Executor 真正走 LLM CodeAct 路径。

**建议**：先做 Option A（3个 incident 任务，确定性探针脚本），作为答辩演示的重点展示场景。

```python
# incident_diagnosis_v2 的 Executor tool 实现
# v2/benchmark/samples/incident_corpus/boot_timing_probe.py
import json
from pathlib import Path

def analyze_boot_log(log_path: str) -> dict:
    """分析启动日志，提取各阶段耗时"""
    log = Path(log_path).read_text()
    phases = []
    last_ts = 0.0
    for line in log.splitlines():
        if "[" in line and "]" in line:
            ts_str = line.split("[")[1].split("]")[0]
            try:
                ts = float(ts_str.replace(":", ".").split(".")[0]) * 60 + float(ts_str.split(".")[-1]) / 1000
            except (ValueError, IndexError):
                continue
            phases.append({"timestamp": ts, "description": line.strip()})
    # 找到最长停顿
    max_gap = 0.0
    slow_phase = ""
    for i in range(1, len(phases)):
        gap = phases[i]["timestamp"] - phases[i-1]["timestamp"]
        if gap > max_gap:
            max_gap = gap
            slow_phase = phases[i]["description"]
    return {"slow_phase": slow_phase, "max_gap_seconds": round(max_gap, 3)}

if __name__ == "__main__":
    result = analyze_boot_log("inputs/boot_log.txt")
    Path("bounded_codeact_result.json").write_text(json.dumps(result))
```

### 验收测试

```bash
# 验证 Executor 真正运行了探针脚本
python -m v2.benchmark.live_runner \
  --suite statebus --family incident_diagnosis_v2 \
  --role-path-mode api --embedding-mode local \
  2>&1 | grep -E "codeact_sandbox|tool_artifact|timing_profile"
# 期望：codeact_sandbox_bwrap_count=3，TOOL_ARTIFACT StateRef 出现
```

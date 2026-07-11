# 可执行修复计划

日期：2026-07-08
状态：按 P0/P1/P2 排序的固定步骤计划，后续执行者按步骤做，不需要重新设计

依据文档：
- `15_deep_problem_analysis_20260708.md`（本计划的问题来源）
- `13_artifact_mining_deep_analysis_20260708.md`
- `14_diagnostic_artifact_mining_readout_20260708.md`
- `code_truth_vs_experiment_issue_matrix_zh.md`

---

## P0-1：formal external compare 已完成 25/5 但 latency 负结果需要独立 serialized rerun

### 目标

当前 formal external compare 25/5 已支持 quality-superiority + token reduction，但 latency 是负结果。如要重开 latency claim，需要 serialized repeat rerun 独立证据。

### 要改的文件

- `scripts/run_v2_local_api_comprehensive_stats.sh`

### 具体修改点

1. 在综合脚本中新增 `STATEBUS_LOCAL_API_LATENCY_RERUN` 模式：
   ```bash
   if [[ "${STATEBUS_LOCAL_API_LATENCY_RERUN:-0}" == "1" ]]; then
     # 跑 formal compare 3 次，每次 serialized（先跑完所有 StateBus，再跑完所有 external；再反过来）
     for repeat in 1 2 3; do
       python -m v2.benchmark.live_runner \
         --suite compare \
         --benchmark-tier formal \
         --role-path-mode api \
         --embedding-mode local \
         --state-pool-mode memfd \
         --repeat-id "$repeat" \
         --timing-contract serialized_alternating
     done
   fi
   ```

2. 在 `v2/benchmark/comparator_runner.py` 中新增字段：
   ```python
   "serialized_repeat_count": repeat_count,
   "serialized_timing_direction_consistent": all(d < 0 for d in task_ms_deltas),
   "serialized_latency_superiority_claim_allowed": (
       strict_equal_quality_valid
       and all(d < 0 for d in task_ms_deltas)
       and repeat_count >= 3
   ),
   ```

### 验证命令

```bash
source deploy/activate_statebus_host.sh
STATEBUS_LOCAL_API_LATENCY_RERUN=1 bash scripts/run_v2_local_api_comprehensive_stats.sh
```

### 通过标准

- summary 输出 `serialized_repeat_count >= 3`
- `serialized_latency_superiority_claim_allowed` 为 true 或 false（如果为 false 则 latency 仍不能 claim，属于合法结果）
- 每轮 task_ms_delta 方向一致

### 失败时看

- `artifacts/stages/r*_latency_rerun_*/stdout.json` 中每轮的 `task_ms_delta`、`llm_ms_delta`、`system_overhead_ms_delta`
- 如果方向不一致（有正有负），说明 API 抖动过大，需要增加 repeat 或换低负载时段

### 注意

当前预期是 latency 仍为负结果。本步骤的价值不是为了强行 claim latency，而是用 serialized 证据关闭"是不是单轮抖动"的疑问。如果 3 轮都是 StateBus 更慢，则 latency 负结果确认，后续专注 token reduction + quality superiority。

---

## P0-2：openEuler 24.03-LTS-SP3 交付验证

### 目标

赛题硬性要求最终代码在 openEuler 24.03-LTS-SP3 上可运行。当前零 openEuler 证据。

### 要改的文件

- `scripts/setup_openeuler_env.sh`（新建或完善）
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/openeuler_validation/`（新建目录）

### 具体修改点

1. 编写 `scripts/setup_openeuler_env.sh`：
   ```bash
   #!/bin/bash
   set -e
   # openEuler 24.03-LTS-SP3 依赖安装
   dnf install -y python3 python3-pip python3-devel gcc gcc-c++ make
   pip3 install --upgrade pip
   pip3 install numpy pydantic orjson msgpack protobuf pyyaml rich networkx
   pip3 install faiss-cpu sentence-transformers transformers torch --index-url https://download.pytorch.org/whl/cpu
   pip3 install openai pytest
   # 验证
   python3 -c "import numpy, pydantic, faiss, torch; print('deps ok')"
   ```

2. 在 openEuler 环境中执行验证序列：
   ```bash
   cd /path/to/statebus/project
   python3 -m py_compile v2/runtime/driver.py v2/runtime/role_path.py v2/benchmark/live_runner.py
   python3 -m runtime.smoke
   python3 -m pytest -q tests/v2/test_minimal_benchmark.py tests/v2/test_state_materialization.py
   python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode deterministic --embedding-mode deterministic
   ```

3. 归档日志到 `docs/improvement/20_v2_comprehensive_truth_audit_20260706/openeuler_validation/`：
   - `env_probe.log`（OS version、Python version、package list）
   - `smoke_pass.log`
   - `pytest_pass.log`
   - `preflight_pass.log`

### 验证命令

```bash
# 在 openEuler 24.03-LTS-SP3 VM 中
bash scripts/setup_openeuler_env.sh
python3 -m runtime.smoke 2>&1 | tee openeuler_validation/smoke_pass.log
python3 -m pytest -q tests/v2/test_minimal_benchmark.py 2>&1 | tee openeuler_validation/pytest_pass.log
```

### 通过标准

- `smoke_pass.log` 包含 exit 0 和 `smoke_complete`
- `pytest_pass.log` 至少 10 tests passed，0 failed
- `preflight_pass.log` 包含 preflight suite exit 0

### 失败时看

- `faiss-cpu` 编译失败：检查 gcc/g++ 版本，可能需要源码编译
- `torch` 安装失败：openEuler 24.03 glibc 版本，可能需要 conda 环境
- `shared_memory` 不可用：检查 `/dev/shm` 挂载

---

## P0-3：formal-trend-002 structured carrier route miss 修复

### 目标

formal text/protocol carrier compare 25/5 中，structured side 少 1 个 quality pass（`formal-trend-002`），失败集中在 route label 选择。

### 要改的文件

- `v2/runtime/role_path.py`（route normalization / candidate selection 逻辑）
- `tests/v2/test_fixed_answer_and_external_baseline.py`（新增 regression）

### 具体修改点

1. 在 `_select_route_from_candidates()` 或等效函数中，增加 route alias normalization：
   - 当 `structured` carrier 返回 `generate_chart` 但正确答案是 `compare_metric` 时，检查 visible candidate keys 中是否有 `compare_metric::table_retriever`
   - 如果 tool 和 doc/value 都对，route 是 visible candidate 之一但不是 scorer 期望的那个，记录 warning 但不 fallback
   - 关键：不做 oracle fallback，但确保 structured carrier 的 route prompt 不会系统性偏向 `generate_chart`

2. 检查 structured carrier prompt 中 route candidate 的呈现顺序：
   - 诊断点：`formal-trend-002` 的 planner prompt 中 candidate 列表是否把 `generate_chart` 排在 `compare_metric` 前面
   - 如果是 prompt ordering bias，固定 candidate 排序为 alphabetical 或 manifest 声明顺序

3. 新增 regression test：
   ```python
   def test_formal_trend_002_route_selection_structured_carrier():
       """structured carrier 不应把 compare_metric task 误选为 generate_chart"""
       # 构造 formal-trend-002 的 visible candidates
       # 验证 structured carrier selection 返回 compare_metric
   ```

### 验证命令

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py -k "trend_002_route"
python -m v2.benchmark.live_runner --suite carrier-compare --benchmark-tier formal --role-path-mode api --embedding-mode local --state-pool-mode memfd
```

### 通过标准

- regression test pass
- carrier compare 输出 `structured_quality_pass_count=25`（而不是 24）
- `route_exact` 在 `formal-trend-002` 为 1.0

### 失败时看

- `work/r*_06_*/runtime/benchmark_reports/*carrier-compare*.json` 中 `formal-trend-002` 的 `planner_plan_payload`、`route`、`visible_candidate_keys`
- 如果 prompt 中 candidate 顺序无问题但 LLM 仍选错，可能需要在 structured carrier prompt 中增加 route-selection instruction

---

## P1-1：completion token 膨胀诊断与瘦身

### 目标

completion tokens 增加 80.5%（+5825），主要来自 strict JSON role surface。需要区分"必需的结构化输出"和"benchmark audit 冗余字段"，减少后者。

### 要改的文件

- `v2/runtime/role_path.py`（JSON role output schema）
- `v2/benchmark/comparator_runner.py`（per-role completion split 记录）

### 具体修改点

1. 在 role JSON schema 中把字段分为两类：
   ```python
   # 必需字段（进 scorer、进 replay、进下一个 role）
   REQUIRED_OUTPUT_KEYS = {"route", "tool_name", "metric_name", "metric_value", "summary_text", "selected_doc_hashes"}

   # 审计字段（只进 telemetry/artifact，不进 LLM completion 要求）
   AUDIT_ONLY_KEYS = {"evidence_pack_hash", "produced_artifact_refs", "consumed_artifact_refs",
                      "produced_strategy_refs", "consumed_strategy_refs", "retrieval_log_hash",
                      "codeact_plan_hash", "codeact_stage_count", "codeact_action_count"}
   ```

2. 新增 `STATEBUS_LEAN_COMPLETION=1` 环境变量：
   - 打开时，role prompt 只要求返回 REQUIRED_OUTPUT_KEYS
   - 审计字段由 runtime post-processing 从 telemetry/artifact 中回填
   - 关闭时（默认），行为不变

3. 在 comparator 输出中新增 per-role completion split：
   ```python
   "role_completion_tokens": {
       "planner": ...,
       "retriever": ...,
       "executor": ...,
       "summarizer": ...
   }
   ```

### 验证命令

```bash
source deploy/activate_statebus_host.sh
STATEBUS_LEAN_COMPLETION=1 python -m v2.benchmark.live_runner --suite compare --benchmark-tier formal --role-path-mode api --embedding-mode local --state-pool-mode memfd
```

### 通过标准

- quality pass count 不下降（仍 25/25）
- completion tokens 相比 baseline 下降 ≥20%
- scorer 结果不变（metric_value_exact 维度不退化）

### 失败时看

- 如果 quality 下降：某些 scorer 依赖 audit 字段做判断，需要把该字段从 AUDIT_ONLY 移回 REQUIRED
- 如果 completion 没有显著下降：说明主要膨胀来自 summary_text 和 metric fields 本身，不是 audit 冗余

---

## P1-2：v2 formal text vs protocol 双模对比 stage

### 目标

赛题通信效率（25分）要求"在相同任务条件下完成可复现实验对比"。当前 v2 formal 层缺少自身 text mode vs protocol mode 的 token 对比。

### 要改的文件

- `scripts/run_v2_local_api_comprehensive_stats.sh`
- `v2/benchmark/live_runner.py`（可能需要增加 text-mode formal entry）

### 具体修改点

1. 在综合脚本中新增 required stage `r01_05b_formal_text_mode_api_local_memfd`：
   ```bash
   run_stage "r01_05b_formal_text_mode_api_local_memfd" "yes" \
     python -m v2.benchmark.live_runner \
       --suite formal \
       --benchmark-tier formal \
       --role-path-mode api \
       --embedding-mode local \
       --state-pool-mode memfd \
       --carrier-mode text
   ```

2. 在 `live_runner.py` 中支持 `--carrier-mode text`：
   - text 模式下 `structured_control_enabled=False`，使用 L0 layer profile
   - 其余配置（API、local embedding、memfd）相同

3. 在 summary extraction 中新增对比字段：
   ```json
   {
     "protocol_L3_total_tokens": ...,
     "text_L0_total_tokens": ...,
     "protocol_vs_text_token_delta": ...,
     "protocol_vs_text_prompt_bytes_delta": ...,
     "protocol_vs_text_control_bytes_delta": ...
   }
   ```

### 验证命令

```bash
source deploy/activate_statebus_host.sh
bash scripts/run_v2_local_api_comprehensive_stats.sh
# 检查 summary 中是否包含 protocol_vs_text 字段
jq '.protocol_vs_text_token_delta' artifacts/summary.json
```

### 通过标准

- `text_L0_total_tokens` > `protocol_L3_total_tokens`（protocol 模式 token 更低）
- `protocol_vs_text_token_delta < 0`
- 两个 stage 的 quality pass count 相同（25/25）

### 失败时看

- 如果 text mode quality < protocol mode quality：检查 text mode prompt 是否正确包含了所有 evidence
- 如果 token delta 方向不符合预期：检查 L0 text 是否确实多了 scaffolding/control overhead

---

## P1-3：continuous replay missing target round 修复

### 目标

`long_doc_metric_replay_v1` 在 base continuous-replay 中 missing target round 7；`kv_prefix_reuse_v1` missing target round 3。这阻塞 replay-headline gate。

### 要改的文件

- `v2/benchmark/samples/continuous_task_families/long_doc_metric_replay/manifest.json`
- `v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/manifest.json`
- `v2/benchmark/continuous_runner.py`（replay gate 逻辑审查）

### 具体修改点

1. 检查 `long_doc_metric_replay` manifest round 7 的定义：
   - `depends_on_rounds` 是否包含了一个实际不可达的前置轮
   - `reuse_contract.minimum_reuse_class` 是否是 `validated_replay` 但前置条件不满足
   - `expected_facts` 是否和 round 6/8 有冲突

2. 检查 `kv_prefix_reuse` manifest round 3 的定义：
   - 同上逻辑

3. 如果问题是 quality gate 拦截了 replay：
   - 检查 round 7 的 `quality_checks` 是否过于严格
   - 如果 metric_value_exact 在 replay 场景下应该放宽到 metric_value_close，修改 quality check 定义

4. 如果问题是 replay target 定义本身不合理：
   - 调整 `l0_l3_expectations.L3.target_nonzero_rounds` 排除该轮
   - 并在 manifest 中说明原因

### 验证命令

```bash
source deploy/activate_statebus_host.sh
python -m v2.benchmark.live_runner --suite continuous-replay --role-path-mode api --embedding-mode local --family long_doc_metric_replay_v1
```

### 通过标准

- `replay_headline_eligible=true` for `long_doc_metric_replay_v1`
- `missing_target_rounds=[]`（或者 target rounds 定义已合理缩小）
- `validated_replay_count` 不下降

### 失败时看

- `work/r*_11_*/runtime/benchmark_reports/*continuous-replay*.json` 中 round 7 的 `replay_gate_reason`
- round 7 的 per-case output 中 `quality_checks` 哪个维度失败

---

## P1-4：KV prefix vLLM probe（已移至 KV-1 独立验证阶段）

**注：** 此项已调整为独立验证项目 **KV-1**，详见文档末尾"独立验证：KV prefix vLLM metrics probe"章节。

**调整原因：**
1. 当前 control-plane + estimate 已是合格创新证据，不阻塞核心 claim
2. 需要本地 vLLM 部署，环境依赖较重，适合作为独立项目验证
3. 优先完成 P0/P1 核心交付项后再进行

---

## P1-5：演示视频制作

### 目标

赛题提交要求演示视频。

### 要改的文件

- `docs/delivery/video_script.md`（新建）
- 视频文件归档路径

### 具体修改点

1. 视频内容规划（3-5 分钟）：
   - 0:00-0:30 系统架构总览（4 agents、typed protocol、memfd data plane）
   - 0:30-1:30 运行演示：formal benchmark 25/5 执行过程（可以加速回放）
   - 1:30-2:30 关键结果对比：quality superiority、token reduction、replay 复用
   - 2:30-3:30 非文本状态传递演示：memfd publish/transfer、semantic StateRef
   - 3:30-4:00 KV prefix scheduling demo + CodeAct bwrap demo
   - 4:00-4:30 总结

2. 录制工具：`asciinema` 或 `script + screencast`

3. 归档到 `docs/delivery/demo_video.mp4` 或外部链接

### 验证命令

```bash
# 验证视频文件存在且时长合理
ffprobe docs/delivery/demo_video.mp4 2>&1 | grep Duration
```

### 通过标准

- 视频时长 3-5 分钟
- 覆盖系统架构、运行演示、结果对比、非文本传递四个部分
- 包含 terminal 实际运行画面

---

## P2-1：flagship stress 失败 family 修复

### 目标

flagship stress 5/6 pass，`incident_diagnosis_v2` 是 diagnostic-only 负例。当前不需要修到 6/6，但需要确认 5 个 claimable families 的 evidence 稳定。

### 要改的文件

- `v2/benchmark/flagship_ablation.py`（输出 per-family failure reason）

### 具体修改点

1. 在 `non_text_state_stress_summary` 中新增：
   ```python
   "per_family_stress_result": {
       "csv_correlation_replay_v1": {"pass": True, "llm_prompt_saved": 12980, "visible_saved": 7242},
       "incident_diagnosis_v2": {"pass": False, "reason": "semantic_selection_dominates", "scope": "diagnostic_only"},
       ...
   }
   ```

2. 不要修 `incident_diagnosis_v2` 为 pass——它是合法负例，保留它证明方法不是 universal claim。

### 验证命令

```bash
source deploy/activate_statebus_host.sh
python -m v2.benchmark.live_runner --suite flagship --role-path-mode api --embedding-mode local
```

### 通过标准

- 5 个 claimable families pass（与当前一致）
- `incident_diagnosis_v2` 明确标注为 `diagnostic_only`
- per-family stress result 字段可读

---

## P2-2：subprocess benchmark stage

### 目标

当前 formal benchmark 主路径是 loopback harness。如要 claim subprocess execution，需新增 stage。

### 要改的文件

- `scripts/run_v2_local_api_comprehensive_stats.sh`
- `v2/benchmark/live_runner.py`（支持 `--transport subprocess`）

### 具体修改点

1. 新增 optional stage：
   ```bash
   run_stage "r01_14_subprocess_formal_api_local_memfd" "no" \
     python -m v2.benchmark.live_runner \
       --suite formal \
       --benchmark-tier formal \
       --role-path-mode api \
       --embedding-mode local \
       --state-pool-mode memfd \
       --transport subprocess
   ```

2. 在 live_runner 中增加 `--transport` 参数，控制使用 `ControlPlaneLoopbackServer` vs `SubprocessExecutorTransport`。

### 验证命令

```bash
source deploy/activate_statebus_host.sh
python -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode deterministic --transport subprocess
```

### 通过标准

- 25/25 quality pass（与 loopback 一致）
- transport 字段记录为 `subprocess`
- memfd FD passing 通过（有 publish/transfer telemetry）

### 失败时看

- subprocess 启动失败：检查 socket path 长度、权限
- memfd FD 传递失败：检查 `/proc/sys/kernel/yama/ptrace_scope`、`os.sendmsg` 权限

---

## 执行顺序总结

**基于文档4 review 发现的调整说明：**
- KV prefix vLLM probe (P1-4) **后移至独立验证阶段**，原因：
  1. 当前 control-plane + estimate 已是合格创新证据
  2. 需要本地 vLLM 部署，环境依赖较重
  3. 不阻塞核心 claim（quality-superiority + token reduction）
- 其他优先级不变

| 优先级 | 编号 | 任务 | 预估工作量 | 依赖 | 阻塞性 |
|--------|------|------|------------|------|--------|
| P0 | P0-2 | openEuler 交付验证 | 2-4h（含环境排错） | openEuler VM 可用 | 硬性交付要求 |
| P0 | P0-3 | formal-trend-002 route miss 修复 | 1-2h | 无 | carrier compare 通过率 |
| P0 | P0-1 | serialized latency rerun | 2-3h（跑实验） | P0-3 完成后 | 排除单轮抖动疑问 |
| P1 | P1-2 | text vs protocol 双模 stage | 2h | 无 | 通信效率证据补强 |
| P1 | P1-1 | completion token 瘦身 | 3-4h | 无 | 改善 completion inflation |
| P1 | P1-3 | replay missing round 修复 | 1-2h | 无 | replay headline gate |
| P1 | P1-5 | 演示视频 | 2-3h | P0 完成后 | 交付材料 |
| P2 | P2-1 | flagship family 输出完善 | 1h | 无 | 锦上添花 |
| P2 | P2-2 | subprocess benchmark stage | 2-3h | 无 | 可选证据 |
| **独立验证** | **KV-1** | **KV prefix vLLM probe** | **3-4h** | **本地 vLLM 可用** | **创新加分项** |

**建议执行路径：**

**阶段1（核心交付）：** P0-2 + P0-3 并行 → P0-1 → P1-2 → P1-5
- 完成后可交付，满足硬性要求 + 核心 claim

**阶段2（证据补强）：** P1-1 → P1-3 → P2-1
- 进一步改善 completion tokens、replay headline、flagship 完整性

**阶段3（独立验证）：** KV-1（原 P1-4）
- 作为独立项目验证，需要：
  1. 本地 vLLM 服务部署完成
  2. 核心 claim 已稳定（不依赖 KV）
  3. 有足够时间进行环境调试
- 如时间不足，作为 future work 不影响答辩

**阶段4（可选）：** P2-2
- subprocess benchmark，锦上添花

---

## 独立验证：KV-1 - KV prefix vLLM metrics probe

**优先级：** 独立验证（原 P1-4）

**调整说明：** 本项从 P1 移至独立验证阶段，原因：
1. 当前 control-plane + estimate 已是合格创新证据
2. 需要本地 vLLM 部署（环境依赖重）
3. 不阻塞核心 claim（quality-superiority + token reduction）
4. 适合在核心交付完成后作为加分项独立验证

### 目标

当前 KV prefix 只有 control-plane prototype + estimate。如要升级为 mechanism evidence，需要接入本地 vLLM。

### 前置条件（必须满足）

1. **本地 vLLM 服务已部署并启动**
   ```bash
   python3 -m vllm.entrypoints.openai.api_server \
     --model $HOME/statebus/models/Qwen3-8B \
     --enable-prefix-caching \
     --max-model-len 8192 \
     --max-num-seqs 1 \
     --host 127.0.0.1 --port 8000
   ```

2. **vLLM metrics 端点可访问**
   ```bash
   curl http://127.0.0.1:8000/metrics | grep prefix_cache
   # 应该看到 vllm:gpu_prefix_cache_hits_total 等指标
   ```

3. **核心交付项（阶段1）已完成**
   - openEuler 验证通过
   - route miss 已修复
   - Serialized latency rerun 已完成
   - 演示视频已制作

### 要改的文件

- `v2/benchmark/kv_prefix_experiment.py`（已有独立 probe，需确认输出格式）
- `scripts/run_v2_local_api_comprehensive_stats.sh`（新增 optional vLLM probe stage）
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/kv_vllm_validation/`（新建目录归档结果）

### 具体修改点

#### 步骤1：在综合脚本中新增 optional stage

在 `scripts/run_v2_local_api_comprehensive_stats.sh` 中添加：

```bash
# KV prefix vLLM probe（optional，需要 STATEBUS_RUN_VLLM_PREFIX_PROBE=1）
if [[ "${STATEBUS_RUN_VLLM_PREFIX_PROBE:-0}" == "1" ]]; then
  echo "=== KV prefix vLLM probe enabled ==="
  
  # Cache-friendly schedule
  run_stage "s01_09_vllm_prefix_cache_friendly" "no" \
    python -m v2.benchmark.kv_prefix_experiment \
      --vllm-base-url "${STATEBUS_VLLM_BASE_URL}" \
      --vllm-metrics-url "${STATEBUS_VLLM_METRICS_URL}" \
      --family kv_prefix_reuse_v1 \
      --mode cache_friendly \
      --output artifacts/kv_prefix_probe/cache_friendly.json

  # Cache-hostile schedule
  run_stage "s01_09b_vllm_prefix_cache_hostile" "no" \
    python -m v2.benchmark.kv_prefix_experiment \
      --vllm-base-url "${STATEBUS_VLLM_BASE_URL}" \
      --vllm-metrics-url "${STATEBUS_VLLM_METRICS_URL}" \
      --family kv_prefix_reuse_v1 \
      --mode cache_hostile \
      --output artifacts/kv_prefix_probe/cache_hostile.json

  # Summary comparison
  run_stage "s01_09c_vllm_prefix_summary" "no" \
    python -m v2.benchmark.kv_prefix_experiment \
      --mode compare \
      --friendly artifacts/kv_prefix_probe/cache_friendly.json \
      --hostile artifacts/kv_prefix_probe/cache_hostile.json \
      --output artifacts/kv_prefix_probe/summary.json
fi
```

#### 步骤2：确认 kv_prefix_experiment.py 输出格式

检查 `v2/benchmark/kv_prefix_experiment.py`，确保输出标准化 JSON：

**cache_friendly.json / cache_hostile.json 格式：**
```json
{
  "mode": "cache_friendly",
  "family_id": "kv_prefix_reuse_v1",
  "vllm_prefix_cache_queries_total_before": 0,
  "vllm_prefix_cache_queries_total_after": 10,
  "vllm_prefix_cache_hits_total_before": 0,
  "vllm_prefix_cache_hits_total_after": 8,
  "vllm_prefix_cache_hit_rate_window": 0.8,
  "ttft_ms_p50": 45.2,
  "ttft_ms_p95": 67.8,
  "quality_floor_pass_rate": 1.0,
  "quality_floor_pass_count": 10,
  "total_rounds": 10,
  "claim_boundary": "engine_local_prefix_reuse_with_vllm_metrics"
}
```

**summary.json 格式：**
```json
{
  "friendly_hit_rate": 0.8,
  "hostile_hit_rate": 0.1,
  "hit_rate_delta": 0.7,
  "friendly_ttft_p50": 45.2,
  "hostile_ttft_p50": 89.4,
  "ttft_delta_ms": -44.2,
  "friendly_quality": 1.0,
  "hostile_quality": 1.0,
  "quality_maintained": true,
  "claim_upgrade": "control_plane_to_mechanism_verified"
}
```

#### 步骤3：归档验证结果

创建归档目录和 README：

```bash
mkdir -p docs/improvement/20_v2_comprehensive_truth_audit_20260706/kv_vllm_validation
```

归档文件清单：
- `cache_friendly.json`（完整输出）
- `cache_hostile.json`（完整输出）
- `summary.json`（对比总结）
- `vllm_metrics_before.txt`（probe 前的 vLLM metrics 快照）
- `vllm_metrics_after.txt`（probe 后的 vLLM metrics 快照）
- `validation_log.md`（验证过程日志）

### 验证命令

#### 前置验证：检查 vLLM 服务

```bash
# 检查服务是否启动
curl http://127.0.0.1:8000/v1/models

# 检查 metrics 端点
curl http://127.0.0.1:8000/metrics | grep prefix_cache

# 保存初始 metrics
curl http://127.0.0.1:8000/metrics > vllm_metrics_before.txt
```

#### 执行 probe

```bash
source deploy/activate_statebus_host.sh

# 设置环境变量
export STATEBUS_RUN_VLLM_PREFIX_PROBE=1
export STATEBUS_VLLM_BASE_URL=http://127.0.0.1:8000/v1
export STATEBUS_VLLM_METRICS_URL=http://127.0.0.1:8000/metrics

# 单独运行 cache-friendly probe
python -m v2.benchmark.kv_prefix_experiment \
  --family kv_prefix_reuse_v1 \
  --mode cache_friendly \
  --vllm-base-url $STATEBUS_VLLM_BASE_URL \
  --vllm-metrics-url $STATEBUS_VLLM_METRICS_URL \
  --output /tmp/kv_friendly.json

# 重启 vLLM（清空 cache）
# ... restart vLLM service ...

# 单独运行 cache-hostile probe
python -m v2.benchmark.kv_prefix_experiment \
  --family kv_prefix_reuse_v1 \
  --mode cache_hostile \
  --vllm-base-url $STATEBUS_VLLM_BASE_URL \
  --vllm-metrics-url $STATEBUS_VLLM_METRICS_URL \
  --output /tmp/kv_hostile.json

# 生成对比总结
python -m v2.benchmark.kv_prefix_experiment \
  --mode compare \
  --friendly /tmp/kv_friendly.json \
  --hostile /tmp/kv_hostile.json \
  --output /tmp/kv_summary.json

# 查看结果
cat /tmp/kv_summary.json | jq .
```

#### 归档结果

```bash
cp /tmp/kv_friendly.json docs/improvement/20_v2_comprehensive_truth_audit_20260706/kv_vllm_validation/cache_friendly.json
cp /tmp/kv_hostile.json docs/improvement/20_v2_comprehensive_truth_audit_20260706/kv_vllm_validation/cache_hostile.json
cp /tmp/kv_summary.json docs/improvement/20_v2_comprehensive_truth_audit_20260706/kv_vllm_validation/summary.json
curl http://127.0.0.1:8000/metrics > docs/improvement/20_v2_comprehensive_truth_audit_20260706/kv_vllm_validation/vllm_metrics_after.txt
```

### 通过标准

**必须全部满足：**

1. **Cache hit rate 差异显著**
   - `friendly_hit_rate >= 0.5`（至少一半请求命中 prefix cache）
   - `hostile_hit_rate <= 0.2`（hostile schedule 命中率低）
   - `hit_rate_delta >= 0.3`（两者差异 ≥30%）

2. **TTFT 改善可观测**
   - `ttft_delta_ms < 0`（friendly 比 hostile 快）
   - `abs(ttft_delta_ms) >= 20`（差异至少 20ms）

3. **质量不下降**
   - `friendly_quality == 1.0`
   - `hostile_quality == 1.0`
   - 两种 schedule 的 quality floor pass rate 都是 100%

4. **Metrics 一致性**
   - vLLM metrics 中 `gpu_prefix_cache_hits_total` 增量和 probe 报告的 hit count 一致
   - vLLM metrics 中 `gpu_prefix_cache_queries_total` 增量和 probe 报告的 query count 一致

### 失败时看

#### 1. Hit rate 为 0 或极低

**检查点：**
- vLLM 是否真的启用了 `--enable-prefix-caching`？
  ```bash
  ps aux | grep vllm | grep prefix-caching
  ```
- Prompt token-level 对齐是否精确？vLLM APC 要求 block-level 精确匹配（默认 block size 16 tokens）
- Cache capacity 是否足够？检查 vLLM 日志中是否有 cache eviction

**诊断命令：**
```bash
# 查看 vLLM 日志
tail -100 vllm_server.log | grep -i "prefix\|cache"

# 查看当前 cache 状态
curl http://127.0.0.1:8000/metrics | grep -E "prefix_cache|block_cache"
```

#### 2. Friendly 和 hostile 的 hit rate 接近

**可能原因：**
- Schedule 生成逻辑有问题，实际顺序没有区别
- Corpus prefix 太短，cache 优势不明显
- vLLM cache capacity 过大，所有请求都命中

**诊断：**
```bash
# 检查 schedule manifest
cat v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/manifest.json | jq '.schedule_hint'

# 检查实际执行顺序
grep "round.*task_id" /tmp/kv_friendly.json
grep "round.*task_id" /tmp/kv_hostile.json
```

#### 3. TTFT 没有改善或方向相反

**可能原因：**
- vLLM 版本不支持 prefix caching TTFT 优化
- Network latency 掩盖了 prefix cache 的收益（应该用 local vLLM）
- Prefix 太短，prefill saving 不明显

**诊断：**
```bash
# 检查 vLLM 版本
python3 -c "import vllm; print(vllm.__version__)"

# 检查 prefix 长度 estimate
jq '.corpus_level_prefill_saved_tokens_estimate' artifacts/kv_prefix_probe/cache_friendly.json
```

#### 4. Quality 下降

**可能原因：**
- vLLM prefix caching 改变了 generation behavior（不应该发生，但检查一下）
- Probe 代码有 bug，质量评估逻辑错误

**诊断：**
```bash
# 查看失败 case 的详细输出
jq '.failed_cases' /tmp/kv_friendly.json

# 对比 control-plane demo 的质量
# control-plane demo 应该是 10/10 pass
```

### 成功标准总结

**Minimum viable success：**
- Friendly hit rate >= 0.5
- Hit rate delta >= 0.3
- TTFT delta < -20ms
- Quality maintained (both 1.0)

**Strong success（答辩加分）：**
- Friendly hit rate >= 0.7
- Hit rate delta >= 0.5
- TTFT delta < -50ms
- Quality maintained
- vLLM metrics 一致性验证通过

### 如果验证失败怎么办

**短期方案：** 作为 future work，答辩中说明：
- Control-plane + estimate 已实现（有代码 + 单测 + demo 10/10）
- Schedule planning 已验证（cache-friendly vs hostile 逻辑正确）
- Mechanism validation 需要 local vLLM 环境（环境约束导致暂未完成）
- 方法论正确，实现路径清晰，属于工程落地问题

**长期方案：** 排查 vLLM 环境问题，可能需要：
- 升级 vLLM 到最新版本（支持更好的 prefix caching）
- 调整 cache capacity 配置
- 使用更长的 corpus prefix（修改 task family manifest）

### 验证成功后的 claim 升级

**当前 claim（无 vLLM probe）：**
> StateBus 实现了 Engine-Local Prefix Reuse 的 control-plane prototype，包括 PrefixLayoutPlan、EngineLocalPrefixRegistry 和 cache-aware scheduling。Control-plane estimate 显示 corpus-level 可节省 2144 tokens，engine-local 可节省 2680 tokens。

**升级后 claim（有 vLLM probe）：**
> StateBus 实现了 Engine-Local Prefix Reuse 并通过 vLLM 验证。在 cache-friendly schedule 下，prefix cache hit rate 达到 X%，TTFT 相比 cache-hostile schedule 降低 Y ms。Control-plane scheduling 使 LLM 推理引擎的 automatic prefix caching 从随机命中提升为系统可规划的优化，同时保持质量不变（quality floor pass rate 100%）。

---

## KV-1 执行时机建议

**最佳时机：** 阶段1（核心交付）完成后，阶段2（证据补强）进行中

**前提条件检查清单：**
- [ ] P0-2 openEuler 验证通过
- [ ] P0-3 route miss 修复并 rerun carrier compare
- [ ] P0-1 serialized latency rerun 完成
- [ ] P1-5 演示视频制作完成
- [ ] 本地 vLLM 服务可稳定运行
- [ ] 有 3-4 小时连续时间进行环境调试

**如果时间紧张：**
- 优先完成 P1-1（completion token 瘦身）和 P1-3（replay missing round）
- KV-1 可以推迟到答辩后作为补充验证
- 答辩时说明"control-plane 已实现，mechanism validation 是下一步工作"

**如果 vLLM 环境无法搞定：**
- 不影响答辩，control-plane + estimate 已是合格创新证据
- 在文档3（Claim 边界）中明确标注为 future work
- 准备答辩材料时说明：方法论正确、实现路径清晰、只是环境约束

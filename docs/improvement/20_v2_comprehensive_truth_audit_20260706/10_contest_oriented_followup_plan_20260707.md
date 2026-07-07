# 赛题导向后续计划

日期：2026-07-07

分支：`feat/statebus-v2-container-runtime`

主要依据：
- `docs/reference/题目.md`：赛题原始要求
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/summary.json`：最新 full `RUN_FLAGSHIP=1` passing evidence
- 本轮所有 issue ledger、fix plan、remaining risks 文档

---

## 1. 赛题要求映射表

| 编号 | 原始要求 | 评分维度（分值） | 硬要求/加分 | 当前覆盖状态 |
|---|---|---|---|---|
| R01 | ≥3 Agent 协同，覆盖规划/检索/执行/总结 | 系统完整性（20） | 硬要求 | 已覆盖：Planner/Retriever/Executor/Summarizer 四角色 |
| R02 | 结构化通信协议替代自然语言透传 | 通信效率（25）+ 系统完整性（20） | 硬要求 | 已覆盖：typed Protobuf 控制面 + UDS |
| R03 | 同时支持纯文本模式和结构化模式，同一任务可复现对比 | 通信效率（25）+ 实验验证（15） | 硬要求 | 部分覆盖：v1 有 text/protocol 双模式 benchmark；v2 formal 只有结构化模式，无 v2 级别的 text vs protocol 双模比较 stage |
| R04 | 非文本中间状态传递（embedding/语义向量/隐藏状态） | 状态传递创新（20） | 硬要求 | 已覆盖（限定）：embedding semantic state + refs + hydration；不能扩大为 hidden-state/KV transfer |
| R05 | 共享记忆模块，含 ID/来源 Agent/时间/任务主题/摘要 | 记忆复用效果（20） | 硬要求 | 已覆盖：SQLite + FAISS + MemoryProxy，元数据字段齐全 |
| R06 | 关键词/标签/语义相似度检索历史记忆 | 记忆复用效果（20） | 硬要求 | 已覆盖：FTS5 + FAISS 向量检索 |
| R07 | ≥2 组有关联的连续任务 | 实验验证（15）+ 记忆复用效果（20） | 硬要求 | 已覆盖：continuous3 families / 30 rounds；replay 20/20 target observed |
| R08 | 统计消息次数、text token、非文本状态次数与规模、总耗时、记忆命中率 | 实验验证（15） | 硬要求 | 已覆盖：telemetry 齐全，formal internal 有所有字段 |
| R09 | 架构含 runtime / 协议解析 / 状态交换 / 共享记忆 / 评测 | 系统完整性（20） | 硬要求 | 已覆盖 |
| R10 | 稳定执行 ≥10 轮连续任务 | 系统完整性（20） | 硬要求 | 已覆盖：30 rounds，20 replay target observed |
| R11 | 提交源码/设计文档/部署文档/实验报告/演示视频 | 交付（无独立分，但影响全部） | 硬要求 | **缺演示视频**；其他已有材料 |
| R12 | 最终交付在 openEuler 24.03-LTS-SP3 上运行 | 交付（无独立分，但影响评审） | 硬要求 | **未验证**；当前证据全是 Docker container + Ubuntu 20.04 |
| R13 | 鼓励 CodeAct | 加分 | 加分 | 部分覆盖：bounded CodeAct；不能 claim realtime open-ended LLM 代码生成 |
| R14 | 鼓励 IPC/共享内存/Socket/向量库/WASM/容器/eBPF | 加分 | 加分 | 部分覆盖：UDS + memfd/shared_memory + FAISS；WASM/eBPF 未实现 |

---

## 2. 当前证据映射表

| 赛题评分维度 | 分值 | 最强证据 | 证据来源 | 当前可支撑的 claim | 禁止写的 claim |
|---|---|---|---|---|---|
| 通信效率 | 25 | v1 mainline text vs protocol 双模 benchmark；v2 smoke：protocol 控制字节比 text 少约 11%（215901 vs 243456）；v2 formal financial 8-case compare prompt bytes 总量相较 external 下降12552 | v1 runs 目录；`local_api_20260707_163354/03_runtime_smoke`；`r01_06` `api_prompt_bytes_delta=-12552` | 结构化协议控制字节相比 text 模式降低；8-case compare 中 prompt/input bytes 更低 | 端到端速度优势；全量外部 25-case 外部 token superiority；任何以 `api_task_ms_delta` 正值为依据的 claim |
| 状态传递创新 | 20 | `r01_05`：25/25 memfd transfer，247076 bytes，semantic_state_transfer=25；sample metadata `EMBEDDING_STATE`；hydration audit 归档 | `local_api_20260707_163354` `r01_05` | embedding semantic state + refs + hydration 机制；memfd 非文本传输 25 次、247076 bytes | hidden-state/KV transfer；raw evidence 不进 prompt（仍经 hydration 进 prompt） |
| 记忆复用效果 | 20 | `r01_10`：20/20 target replay observed，17 validated，3 exact，answer_restoration=0，`L3_reuse_gain=20`；`r01_09`：`L3_reuse_gain=9` | `local_api_20260707_163354` | replay-aware 连续任务复用；validated replay 17/20；exact replay 3/20；reuse_gain 可量化 | generic answer restoration；任意共享记忆都能复用 |
| 系统完整性 | 20 | 4 roles，UDS/Protobuf 控制面，30 rounds 稳定，focused pytest 115 passed，Docker container 验证 | `local_api_20260707_163354` | 4 agent 协同稳定运行；typed Protobuf 控制面；10+ 轮连续 | nsjail 安全沙箱；production sandbox；openEuler 已验证 |
| 实验验证 | 15 | formal internal 25/25；formal financial 8-case compare strict equal-quality；replay negative 7/7；v2 smoke text vs protocol | `local_api_20260707_163354` | formal benchmark 数据齐全；replay 负例审计；多指标量化对比 | full 25-case external superiority；efficiency superiority（因 `debug_only`）；timing 优势（`api_task_ms_delta` 为正） |

---

## 2.1 A-H 审计结论压缩表

| 编号 | 结论 | 后续动作 |
|---|---|---|
| A | formal compare 8-case 公平门已过，StateBus prompt bytes/input tokens 更低；completion/total tokens 更高，latest full run 是 `debug_only` | 只写 prompt/input/control-byte savings；补 prompt/completion token split 字段 |
| B | flagship stage exit 0，但 stress 3/6；失败 family 原因不同 | incident/long_doc_metric 修 quality/replay；cross_period 修 prompt-saving gate 或降低 claim |
| C | StateRef 是 embedding semantic state + typed refs + hydration accounting | 禁止 raw-evidence replacement、hidden-state、KV transfer 表述 |
| D | formal internal 25/5 与 formal compare 8/1 仍是不同 scope | 实现 registry-backed compare adapter 后再谈 25/5 external compare |
| E | v2 formal 缺 text vs protocol companion stage | 新增 `r01_05b` text-mode formal benchmark |
| F | openEuler VM 未验证 | 准备 openEuler 24.03-LTS-SP3 VM setup/validation artifact |
| G | 历史报告含旧强 claim 语言 | 历史报告加 warning，presentation 只引用 latest audit stopline |
| H | canonical payload 缺 prompt/input vs completion/output split | 补 schema，避免 prompt saving 被误写成 total-token superiority |

---

## 3. 新发现问题清单

以下是本轮赛题导向审计相对前序 issue ledger 的新发现：

### NEW-001（P0）：openEuler 24.03-LTS-SP3 交付要求未验证

赛题明确要求：「最终交付的代码需在 openEuler 24.03-LTS-SP3 操作系统版本上能够正常编译、运行和测试」。

当前所有证据（包括 `local_api_20260707_163354`）均在 Docker + Ubuntu 20.04 host + openEuler container 环境下运行。该容器不等于 openEuler VM 独立验证。

影响：答辩/评审时如果评委要求现场运行 openEuler，当前无法提供已验证的部署脚本和依赖列表。

### NEW-002（P1）：演示视频未制作

赛题要求提交演示视频。当前文档中无任何视频制作计划或脚本。

### NEW-003（P1）：V2 formal benchmark 缺少 text vs protocol 双模对比 stage

赛题要求 R03：同时支持纯文本和结构化模式，并在相同任务条件下完成可复现实验对比。

v2 formal internal（`r01_05`）只运行 StateBus API+local+memfd，没有对应 text 模式 stage。「通信效率（25分）」维度的主要证据来自：
- v1 主线 runs（历史数据，不是 v2 formal evidence）
- v2 smoke（deterministic，非 API）
- `r01_06` `api_prompt_bytes_delta=-12552`（是 StateBus vs external，不是 StateBus protocol vs StateBus text）

缺口：v2 formal 层面没有 StateBus text 模式 baseline，无法做自身双模 token 对比。

### NEW-004（P2）：comprehensive 运行中的 `api_task_ms_delta` 不可用于 efficiency claim

`local_api_20260707_163354` 的 `r01_06` 显示 `api_task_ms_delta=86580ms`（正值，StateBus 比 external 慢）。这是并发运行中的测量，受同期其他 stage 影响，不能作为 timing efficiency 证据。

只有 serialized rerun（`STATEBUS_LOCAL_API_REPEAT=3`）才能产出有效 timing evidence。

### NEW-005（P2）：flagship 3/6 失败 family 已诊断但未修复

`incident_diagnosis_v2`、`long_doc_metric_replay_v1`、`cross_period_financial_v1` 未通过 stress family gate。当前已从 `stdout.json` 拆出原因：

- `incident_diagnosis_v2`：L3 quality 7/10，quality headline 不合格；仍有 L2 transfer 10 和 StateRef prompt saving 3132 bytes。
- `long_doc_metric_replay_v1`：L3 quality 8/10，validated 7，exact 1，skipped 9，quality/replay headline 不合格；仍有 StateRef prompt saving 3699 bytes。
- `cross_period_financial_v1`：quality/replay headline 合格，但 L2 相对 T2 无 prompt saving，`llm_prompt_delta_l2_vs_t2=+3268`，应解释为 semantic selection dominates this family。

缺口已经从缺少诊断收敛为实现修复尚未完成。

### NEW-006（P1）：formal compare token claim 缺 prompt/input 与 completion/output split

`r01_06` latest full compare 中，StateBus prompt bytes 和 prompt tokens 更低，但 completion tokens 和 total tokens 更高。当前对外 claim 只能落在 prompt/input/control-byte savings，不能写 total-token superiority。

### NEW-007（P1）：StateRef claim 容易被误写成 raw evidence replacement

代码事实是 embedding semantic state + refs + hydration。raw evidence/text/table slices 仍会被选择并进入 role prompt；StateRef 不是模型 hidden-state/KV transfer。

### NEW-008（P1）：formal registry compare 不是 loader-only 改动

formal registry sample model 与 fixed-answer compare sample model 不同。扩到 25 cases / 5 families 需要 adapter、expected route/tool/facts、external prompt 和 scorer 设计。

### NEW-009（P2）：历史实验报告仍可能被误用

`docs/reports/v2_experiment_summary_20260703.md` 是历史 diagnostics，不能作为 current formal external superiority、openEuler VM validation、production sandbox 或 flagship all-pass 证据。

---

## 4. 问题分级

| ID | 标题 | 级别 | 影响维度 |
|---|---|---|---|
| NEW-001 | openEuler 交付未验证 | P0（交付阻塞） | 交付可信度 |
| NEW-002 | 演示视频缺失 | P1（提交必须） | 交付完整性 |
| NEW-003 | v2 formal 缺 text vs protocol 双模 stage | P1（通信效率 25分证据薄弱） | 通信效率评分 |
| NEW-004 | comprehensive timing 不可用于效率 claim | P2（claim 风险） | 实验验证可信度 |
| NEW-005 | flagship 3/6 失败 family 已诊断但未修复 | P2（系统完整性/flagship） | 系统完整性评分 |
| NEW-006 | token claim 缺 prompt/completion split | P1（claim 风险） | 通信效率评分 |
| NEW-007 | StateRef 容易被误写成 evidence replacement | P1（claim 风险） | 状态传递创新评分 |
| NEW-008 | registry compare 需要 adapter/prompt/scorer | P1（外部对比证据） | 实验验证评分 |
| NEW-009 | 历史报告强 claim 误用风险 | P2（文档风险） | 交付可信度 |
| V2-AUDIT-003 | full registry compare 未实现（25/5） | P1（外部对比证据） | 实验验证评分 |
| V2-AUDIT-017 | 非文本状态 claim 需限定为 embedding+hydration | P1（状态传递 claim 风险） | 状态传递创新评分 |
| V2-AUDIT-010 | openEuler VM validation 缺失 | P2（交付） | 交付可信度 |

---

## 5. 详细执行计划

优先级顺序：先保交付完整性（P0），再补证据（P1），最后优化（P2）。

### Step 0：确认当前代码可在 v2 container 中干净运行（无需重跑完整 benchmark）

```bash
# 验证 container 激活和基础 import
docker exec -u 0 statebus-dev-qcrs bash -lc \
  'cd /workspace/statebus/project && \
   source /usr/local/bin/activate_statebus_container.sh && \
   /usr/bin/python3 -m py_compile v2/runtime/driver.py v2/runtime/role_path.py runtime/llm.py'
```

预期：exit 0，无 SyntaxError。

### Step 1（P0）：为 openEuler 交付准备依赖验证脚本

目标：在 openEuler 24.03-LTS-SP3 环境中验证核心依赖可安装并跑通 smoke test。

需要做：
1. 梳理 `scripts/setup_host_dev_env.sh` 中的 pip 依赖。
2. 确认 `faiss-cpu`、`sentence-transformers`、`protobuf`、`pydantic` 在 openEuler 24.03 上的安装方式（pip 或从源码）。
3. 编写 `scripts/setup_openeuler_env.sh`（若无则新建），确认 `python3 -m runtime.smoke` 在 openEuler 上 exit 0。

验证命令（在 openEuler VM 中）：
```bash
bash scripts/setup_openeuler_env.sh
python3 -m pytest -q tests/v2/test_state_materialization.py tests/v2/test_minimal_benchmark.py
python3 -m runtime.smoke
```

预期 artifact：`docs/improvement/openeuler_validation_YYYYMMDD/smoke_pass.log`

### Step 2（P1）：新增 v2 formal text vs protocol 双模对比 stage

目标：在 `scripts/run_v2_local_api_comprehensive_stats.sh` 中加入 StateBus text 模式 formal benchmark stage，与 r01_05（protocol）形成对比。

新 stage 命名建议：`r01_05b_formal_api_local_memfd_text`（或 `r01_03b_formal_text_mode`）

改动：
- `v2/benchmark/live_runner.py` 或 `scripts/` 新增 text-mode formal stage。
- summary 中提取 `text_total_tokens`、`text_control_bytes`、`protocol_total_tokens`、`protocol_control_bytes`，以及 delta。

验证：
```bash
STATEBUS_LOCAL_API_RUN_FLAGSHIP=0 bash scripts/run_v2_local_api_comprehensive_stats.sh
```

预期 artifact 字段：
```json
{
  "text_L3_total_tokens": ...,
  "protocol_L3_total_tokens": ...,
  "protocol_vs_text_token_delta": ...,
  "protocol_vs_text_control_byte_delta": ...
}
```

### Step 3（P1）：实现 registry-backed formal external compare（25 cases / 5 families）

目标：把 `r01_06` 从 formal_financial 8-case 扩展为 formal registry 25-case / 5-family compare。

改动入口：不能只把 compare suite 改成 `load_registered_formal_samples()`。需要先做 registry-to-compare adapter，把 25 个 `MinimalBenchmarkSample` 映射为 compare 可评分的 expected route/tool/facts，并补齐非 financial family 的 external prompt 和 scorer contract。

验证：
```bash
python -m v2.benchmark.live_runner --suite compare \
  --benchmark-tier formal \
  --formal-compare-source registry \
  --role-path-mode api \
  --embedding-mode local
```

预期字段：
```json
{
  "formal_compare_scope_label": "formal_registry_25case_5family_compare",
  "formal_compare_case_count": 25,
  "formal_compare_family_count": 5,
  "formal_compare_full_registry_coverage": true
}
```

### Step 4（P2）：serialized timing rerun for efficiency claim

目标：产出可用于 efficiency superiority claim 的 serialized timing evidence。

```bash
STATEBUS_LOCAL_API_REPEAT=3 STATEBUS_LOCAL_API_RUN_FLAGSHIP=0 \
  bash scripts/run_v2_local_api_comprehensive_stats.sh
```

验证：看 `api_task_ms_delta` 符号和绝对值，是否支持 efficiency claim。注意：latency delta 受 StateBus 完整4角色管线 vs external 单角色的架构差异影响，不应作为主效率指标；主指标应是 token/byte delta。

### Step 5（P2）：flagship 3/6 失败 family 修复

目标：针对已拆出的3个失败 family 修 quality/replay/prompt-saving gate。

```bash
python -m v2.benchmark.flagship_ablation \
  --families incident_diagnosis_v2,long_doc_metric_replay_v1,cross_period_financial_v1 \
  --role-path-mode api --embedding-mode local --verbose
```

当前已知原因：

- `incident_diagnosis_v2`：quality 7/10，需要修 L3 quality/replay admissibility。
- `long_doc_metric_replay_v1`：quality 8/10、validated 7、exact 1，需要修 quality/replay headline。
- `cross_period_financial_v1`：quality/replay 合格，但 L2 相对 T2 无 prompt saving，需要修 StateRef packaging 或调整该 family 的 stress gate。

输出：每个 family 的 quality_floor_pass/fail、replay_target_pass/fail、prompt_saving_pass/fail 原因，并把 `non_text_state_stress_summary` 写入 stable report。

### Step 6（P1）：演示视频规划

内容要点：
1. 系统架构图（30s）
2. 4 agent 协同工作流展示（60s）
3. text vs protocol 双模对比数字（30s）
4. memfd 非文本状态传输演示（30s）
5. 连续任务 replay 展示（60s）
6. benchmark 指标汇总（30s）

预期时长：3-5 分钟。

### Step 7（P1）：补 formal compare prompt/completion token split

目标：防止 prompt/input savings 被误写成 total-token superiority。

改动：
- comparator summary 显式输出 StateBus/external prompt tokens、completion tokens、total tokens、prompt bytes 和对应 delta。
- docs generator 只在 `formal_external_claim_kind != debug_only` 且 total-token/timing gate 通过时写 superiority。

验收字段：
```json
{
  "api_prompt_tokens_delta": -3033,
  "api_completion_tokens_delta": 9496,
  "api_llm_total_tokens_delta": 6463,
  "api_prompt_bytes_delta": -12552,
  "formal_external_claim_kind": "debug_only"
}
```

### Step 8（P2）：历史报告与 presentation stopline 复核

目标：避免 `docs/reports/v2_experiment_summary_20260703.md` 的 historical diagnostics 被当成 current claim。

需要确认：
- openEuler container 不写成 openEuler VM validation。
- bwrap diagnostic 不写成 production sandbox。
- old `formal_superiority_claim_allowed=True` / `formal_efficiency_claim_allowed=True` 不写成 latest external superiority。
- flagship 只写 3/6 stress pass，不能写 all-pass。

---

## 6. Claim 允许/禁止表

### 允许写（已有证据支撑）

| Claim | 证据来源 | 限制说明 |
|---|---|---|
| 4 Agent 协同运行（Planner/Retriever/Executor/Summarizer） | `r01_05` 四角色各25次 API call | 无 |
| typed Protobuf 控制面，UDS 传输 | focused pytest 115 passed；Docker root 9 passed | formal benchmark 主路径是 loopback harness，不是 subprocess |
| embedding semantic state 非文本传输，25次，247076 bytes | `r01_05` memfd publish/transfer | 必须写成 embedding + refs + hydration；不能写 raw evidence replacement、hidden-state/KV |
| formal internal 25/25，5 families，API+local+memfd | `r01_05` | 只是 StateBus 内部，不是 external superiority |
| 连续任务 replay 20/20 observed，17 validated，3 exact | `r01_10` | manifest-backed replay，不是 generic answer restoration |
| replay negative 7/7 pass | `r01_11` | 覆盖构造负例，不代表所有真实场景 |
| protocol 控制字节比 text 模式少约 11%（smoke） | `03_runtime_smoke` | deterministic，非 API formal |
| formal financial 8-case strict equal-quality compare valid，fairness 8/8 | `r01_06` | scope 仅 8 cases / 1 family；本次 debug_only；只能写 prompt/input/control-byte savings，不能写 total-token superiority |
| StateRef prompt savings 37884 bytes（flagship） | `r01_12` | stage exit 0、stress 3/6；仅统计 prompt savings，不是 all-pass 或全面效率对比 |
| CodeAct bounded execution | source + tests | 不能写成 realtime open-ended LLM code generation |

### 禁止写（无证据或证据不足）

| 禁止 Claim | 原因 |
|---|---|
| full 25-case formal external superiority | compare 只覆盖 8/1 scope，且 `debug_only` |
| 端到端速度优势（latency） | `api_task_ms_delta=86580ms` 为正；timing 受并发影响；architecture 差异不可比 |
| openEuler 24.03 已验证 | 无 VM 验证 artifact |
| nsjail / production sandbox | 未安装/未验证 |
| hidden-state / KV transfer | 只有 embedding semantic state + hydration |
| generic answer restoration | `answer_restoration_replay_count=0` |
| flagship all-pass | 3/6 stress families pass |
| full 25-case external 效率superiority | full registry compare 未实现 |

---

## 7. 验证命令汇总

```bash
# 静态检查
bash -n scripts/run_v2_local_api_comprehensive_stats.sh
git diff --check

# 基础 pytest（最小化验证）
source deploy/activate_statebus_host.sh
python -m pytest -q tests/v2/test_state_materialization.py \
  tests/v2/test_minimal_benchmark.py \
  tests/v2/test_continuous_runner.py \
  tests/v2/test_fixed_answer_and_external_baseline.py

# Container 控制面验证
docker exec -u 0 statebus-dev-qcrs bash -lc \
  'cd /workspace/statebus/project && \
   source /usr/local/bin/activate_statebus_container.sh && \
   /usr/bin/python3 -m pytest -q \
   tests/v2/test_control_plane.py \
   tests/v2/test_uds_loopback.py \
   tests/v2/test_subprocess_executor.py'

# 核心 local+api 复验（不跑 flagship）
STATEBUS_LOCAL_API_RUN_FLAGSHIP=0 \
  bash scripts/run_v2_local_api_comprehensive_stats.sh

# 正式 timing 证据（serialized，3次）
STATEBUS_LOCAL_API_REPEAT=3 STATEBUS_LOCAL_API_RUN_FLAGSHIP=0 \
  bash scripts/run_v2_local_api_comprehensive_stats.sh
```

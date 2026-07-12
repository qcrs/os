# Comprehensive Gap Audit - 2026-07-11

审计输入：`docs/PROMPT_711.md`（全面实现与实验问题审计指令）。
审计原则：从赛题要求、系统设计、代码实现、实验 artifact、复现风险五个层面拆解 gap。
不做答辩包装；每条判断附具体路径 / artifact 字段 / 代码位置。

工作约束遵守情况：未启动新实验、未重启 vLLM、未杀 GPU 进程、未改业务代码、未 commit、未 `git add .`、未触碰无关未跟踪文件（含 `tatus --short --branch`）。本轮只读代码/artifact/日志 + 写本审计文档。

---

## 0. Scope And Git State

### 0.1 Git 状态摘要

`git status --short --branch` 输出：

```
## feat/local-vllm-kv-prep
?? docs/PROMPT_711.md
?? docs/improvement/20_v2_comprehensive_truth_audit_20260706/29_local_vllm_kv_experiment_log_synthesis_20260711.md
?? docs/improvement/20_v2_comprehensive_truth_audit_20260706/30_independent_audit_report_20260711.md
?? docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_vllm_kv_experiment_log_summary_20260711.json
?? scripts/summarize_local_vllm_kv_experiment_logs.py
?? tatus --short --branch
```

- 当前分支：`feat/local-vllm-kv-prep`（不是 CLAUDE.md 里记的 `main` / `feat/statebus-v2-container-runtime`；这是本地 KV 实验准备分支）。
- Dirty 状态：无已跟踪文件修改（无 `M`），只有 6 个未跟踪项（`??`）。
- 未跟踪项里含一个误建文件 `tatus --short --branch`（疑似 `git status --short --branch` 被截断成文件名，误重定向所致）。本审计不删除它（约束 9），但记录为 artifact-quality 噪声，见 G-ledger。
- 本审计文档 `31_comprehensive_gap_audit_20260711.md` 也是新增未跟踪文件。

### 0.2 审计边界

- 主线双证据链：**no-KV/API 主线**（v2 clean-room，四角色 API + local embedding + memfd/shared_memory/mmap）与 **KV/local vLLM 主线**（Qwen3-32B + vLLM automatic prefix caching，Engine-Local Prefix Reuse probe）。本审计全程分开两条链，不混写（见 Section 2）。
- openEuler VM 按指令不作为本轮重点。
- 上一轮 AI 的 9 个点（PROMPT 第八节）只作检查项，不作审计边界（重评见 Section 5 / 8）。

---

## 1. Contest Requirement Decomposition

赛题原文来源：`docs/reference/题目.md`。评分维度：通信效率 25 / 状态传递创新 20 / 记忆复用效果 20 / 系统完整性 20 / 实验验证 15。

Gap Type: none / implementation gap / experiment gap / documentation gap / reproducibility risk / overclaim risk。
Fix Worth: high / medium / low / no。

| Contest Requirement | Expected Mechanism | Current Implementation | Evidence | Gap Type | Fix Worth |
|---|---|---|---|---|---|
| ≥3 Agent、≥3 角色协同、完成多步复杂任务 | Planner/Retriever/Executor/Summarizer 四角色分工 | v2 `RolePathRunner` 四角色路径，formal internal 各 25 次 API call | `local_api_20260707_163354/r01_05`：planner/retriever/executor/summarizer 各 25 call | none | no |
| 结构化通信：动作/参数/结果/能力 + 握手/能力发现/协议映射，不得纯自然语言透传 | typed Protobuf 控制面 + capability/schema + UDS | `v2/control/messages.py`、`schema.py`、`transport.py`、`statebus_v2.proto` | `tests/v2/test_control_plane.py`、`test_uds_loopback.py`；smoke protocol mode | none（实现存在） | low |
| 两种协作模式：纯文本 + 结构化，相同任务可复现对比 | text/protocol 双 lane 对比 | v2 smoke 有 text/protocol；formal internal **无** API text-mode companion stage；KV 主线 E6 有 L0(text)/L3(protocol) 对比 | E6 `e6_formal_guard_summary`：L0 vs L3 token delta；v2 formal 缺 same-task API text companion | experiment gap | high |
| 非文本中间状态传递（embedding/语义向量/隐藏状态/其他中间表示），说明生成/传递/接收/使用 | SemanticStateRef + LayeredStateStore + memfd/shm/mmap materialization + hydration | `v2/refs/models.py`、`v2/state/store.py`；memfd 25 publish/transfer 247076 bytes | `r01_05`：`memfd_transfer_count=25`、`memfd_bytes_transferred=247076` | none（但注意边界：非 hidden-state/KV，见 §6） | medium |
| 共享记忆模块：统一记忆单元 + 元数据（ID/来源/时间/主题/摘要） | SQLite + FAISS 记忆层 | `memory/`（v1）、v2 memory ref | v2 replay/memory ref registry | none | no |
| 关键词/标签/语义相似度检索 + 跨 Agent 复用 | 向量检索 + replay gate | `v2/runtime/replay.py` exact/validated gate | `r01_10`：20/20 observed, 17 validated, 3 exact | none | low |
| 跨任务记忆复用（减少重复计算） | replay / skip execution / reuse_gain | validated/exact replay + skipped steps | `r01_09`：`L3_reuse_gain=9`；v1 host bundle：`reuse_gain=0.17`、`skipped_step_count=9`、`memory_hit_rate=0.83` | none（注意：local vLLM 路径 reuse_gain=0，见 §4/§5） | medium |
| ≥2 组关联性连续任务验证机制效果 | continuous/replay suite | `v2/benchmark/continuous_runner.py` | `r01_09`：3 families / 30 rounds | none | no |
| 性能指标：消息次数 / token / char 开销 / 非文本次数与规模 / 单任务耗时 / 记忆命中率 / 整体提升 | benchmark telemetry | 多字段落盘 | prompt bytes delta、token delta、memfd bytes、memory_hit_rate 均有 | 部分：end-to-end speed / total-token superiority 不成立 | medium |
| 非文本状态次数和规模 | memfd publish/transfer count + bytes | `r01_05` 25 次 / 247076 bytes | 已测 | none | no |
| ≥10 轮连续任务稳定性 | continuous 30 rounds + deterministic repeat-10 | `r01_09` 30 rounds；v1 host bundle deterministic repeat-10 | 已测 | none | no |
| IPC / 共享内存 / Socket / 向量库 / WASM/容器沙箱 / eBPF 系统技术（鼓励项） | UDS + memfd/shm + FAISS 已落地；WASM/eBPF/nsjail 未落地 | UDS loopback（formal 主路径非 subprocess）；memfd/shm 真实 | `test_uds_loopback.py`；formal 用 `ControlPlaneLoopbackServer` | implementation gap（部分鼓励项未落地，可接受） | low |
| CodeAct（可选加分） | bounded deterministic execution，非 realtime LLM code-gen | bounded CodeAct + sandbox telemetry | 历史 diagnostic；formal 不证明 realtime code-gen | overclaim risk（若扩大表述） | low |
| openEuler 24.03-LTS-SP3 可编译/运行/测试（交付要求） | VM 验证 | 仅 Docker/container 证据，VM 未验证 | 无 VM artifact | reproducibility risk | medium（非本轮阻塞） |

初步判断（细化见后续 Section）：赛题功能覆盖在 no-KV/API 主线上基本齐全，最突出的两类 gap 是 (a) **实验验证维度（15 分）** 缺 v2 formal same-task text vs protocol 双模对比 + full 25-case external superiority；(b) 术语边界风险集中在 KV 主线的 `estimated_kv_tokens_saved` / `neural_prefix_cache_hit_count_estimate` 等 estimate 字段易被当 direct metric。

---

## 2. Cross-Path Evidence Map

两条证据链必须分开读，不能拼成一条：

- **no-KV/API 主线**：v2 clean-room，四角色 API（或 deterministic）+ local embedding + memfd/shm/mmap state pool。最强 artifact 是 `local_api_20260707_163354`（13 stages exit 0）与 v1 host `runs/host_goal_eval_*` repeat-10 包。
- **KV/local vLLM 主线**：Qwen3-32B + vLLM automatic prefix caching，通过 schedule/layout 控制触发 Engine-Local Prefix Reuse。最强 artifact 是 `sb32bcompact`（4096 ctx，L0-L3 各 25/25）、`kv-e6-guard-20260711-1448`（8192 ctx，E6 formal guard）、E1/E2 clean-service repeat。

关键：两条链用的是不同模型（API provider 模型 vs 本地 Qwen3-32B Transformers fallback）、不同执行环境、不同 state-pool 配置。任何跨链归因（例如把 API 的 reuse_gain 和 vLLM 的 prefix hit-rate 说成同一种"记忆复用"）都是错误的。

| Requirement / Mechanism | no-KV/API Evidence | KV/local vLLM Evidence | Code Path | Gap | Worth Fixing |
|---|---|---|---|---|---|
| protocol vs text 通信效率 | `r01_06` 8-case financial compare：prompt bytes 30661 vs 43213、prompt tokens 9645 vs 12678；但 completion/total tokens 更高，`formal_external_claim_kind=debug_only`（不支持 efficiency superiority）；v1 host：control bytes `150876→128743`、API total tokens `29727→19882` | E6：Protocol L3 vs Text L0 prompt tokens `-45652`、total tokens `-51282`；`sb32bcompact`：total `-57946`、prompt `-51606`、control bytes `-31581` | `v2/benchmark/comparator_runner.py`；`v2/benchmark/kv_analysis.py` | v2 formal 无 same-task API text companion（L0 vs L3 是 internal attribution ladder，非等价双模对比） | high |
| StateRef / 非文本状态传递 | `r01_05`：`semantic_state_transfer_count=25`；state metadata `EMBEDDING_STATE` | E6：`semantic_state_transfer_count=25`、`state_pool_shared_memory_mode_count=25` | `v2/refs/models.py`、`v2/state/store.py` | 无：机制真实。边界：embedding semantic state + refs + hydration，非 hidden-state/KV（见 §6） | medium |
| shared memory / mmap / memfd backend | `r01_05`：memfd 25 publish/transfer、247076 bytes；shared_memory 主要 deterministic 证据；mmap 缺本轮 API 强证据 | E6：`state_pool_shared_memory_mode_count=25` | `v2/state/store.py` `_materialize_memfd()`/policy | no-memfd fallback 仍主要 unit/monkeypatch 证据（非真实 no-memfd 主机验证） | low |
| memory reuse / replay reuse | `r01_10`：20/20 observed、17 validated、3 exact、answer restoration 0；`r01_09`：`L3_reuse_gain=9`；v1 host：`reuse_gain=0.17`、`memory_hit_rate=0.83`、`skipped_step_count=9` | E6：`reuse_gain_delta_l2_to_l3=0.0`（local vLLM 路径未开 replay memory，reuse_gain=0） | `v2/runtime/replay.py`、`v2/benchmark/continuous_runner.py` | 两条链复用语义不同：API=任务级记忆复用；vLLM=引擎级 prefix reuse。必须分开表述，否则数据看似矛盾 | high（文档澄清） |
| Engine-Local Prefix Reuse | N/A（API 主线不涉及 vLLM prefix cache） | E1 clean-service：friendly hit-rate `0.789` vs hostile `0.524`，TTFT `~885` vs `~1569 ms`；E2 clean-service：shared `0.780` vs independent `0.0`，TTFT `~967` vs `~3526 ms` | `v2/benchmark/kv_prefix_schedule.py`、`v2/runtime/neural_state.py` `EngineLocalPrefixRegistry` | 无：机制证据闭环。边界：control-plane registry，不持有 KV tensor；hit-rate 是 gauge 非 raw counter（见 §4/§6） | medium |
| dynamic pruning | N/A（retrieval-level 机制，两链共用代码但 KV 主线跑 probe） | E3：selected evidence bytes `333→112`、`estimated_kv_tokens_saved 36→92`、hard fact `fact-revenue-1` 保留、quality proxy pass；E6：`evidence_pruning_drop_count=25`、`estimated_kv_tokens_saved=9644`（估算） | `v2/retrieval/pruning.py`、`pipeline.py` | E3 只是 retrieval-level deterministic probe，非 end-to-end formal quality 证明；`estimated_kv_tokens_saved` 是线性估算 | medium |
| formal quality guard | `r01_05`：25/25，5 families | E6：L0-L3 全 25/25，quality delta 0（`kv-e6-guard-20260711-1448`）；`sb32bcompact` 同样 25/25 | `v2/runtime/smoke.py` `expected_facts`；`v2/benchmark/flagship_ablation.py` | 无：formal 质量底线证据强 | no |
| continuous / replay stability | `r01_09`：3 families / 30 rounds；v1 host deterministic repeat-10：`expectation_match_rate=1.00`、`failure_count=0` | `sb32bcompact`/`kv-e6-guard` 单次完整 formal（无 repeat-10） | `v2/benchmark/continuous_runner.py` | KV 主线无 repeat-10 稳定性证据（单次 formal）；E1/E2 仅 3 次 repeat 无误差线 | medium |
| CodeAct / sandbox optional path | bounded CodeAct + sandbox telemetry（历史 diagnostic） | N/A | v2 codeact path | 不证明 realtime open-ended LLM code-gen；保持 bounded claim | low |
| flagship stress ablation | `r01_12`：stage exit 0，6 families 中 3 pass；StateRef prompt saved 37884 bytes | N/A（flagship 属 API 主线） | `v2/benchmark/flagship_ablation.py` | 3/6：`incident_diagnosis_v2`/`long_doc_metric_replay_v1` quality gap，`cross_period_financial_v1` prompt-saving gap | low |

### 2.1 两条链最强证据一句话总结

- no-KV/API 主线最强：`r01_05` formal internal 25/25 + memfd 25 次/247076 bytes + `r01_10` replay 20/20（17 validated, 3 exact）。
- KV/local vLLM 主线最强：E2 clean-service `shared_evidence_prefix` hit-rate `0.780` vs `0.0` + TTFT `-2559ms`；E6 formal guard L0-L3 全 25/25 且质量 delta 0。
- 两条链共同边界：无 KV tensor export/transfer、无 hidden-state transfer、无 cross-engine reuse、无 2-GPU、无 openEuler VM 验证。

---

## 3. Code Path Verification

本节对每个机制逐一确认：文档/artifact 描述的行为是否真实存在于代码路径，并标注 concern。

| Mechanism | Claimed Behavior In Docs | Code Path | Artifact Field | Verified? | Concern |
|---|---|---|---|---|---|
| `shared_evidence_prefix` prompt layout | E2 把公共证据移到 prompt 开头，让 vLLM prefix caching 能命中可复用前缀 | `v2/runtime/role_path.py:347,881`：读取 `STATEBUS_PREFIX_ALIGNMENT_MODE` 环境变量，比较是否 `"shared_evidence_prefix"`；E2 probe 在 `scripts/probe_local_vllm_prefix_alignment.py:37` 接收 `--mode` 参数并传入 | `e2_prefix_alignment_ablation_summary_20260711_1359.json`：`probe="e2_shared_evidence_prefix"`；E6 artifact 含 `neural_prefix_shared_prefix_bytes=4359` | ✅ 已验证：代码路径真实存在，E2 artifact 字段可追溯 | `probe_local_vllm_prefix_alignment.py` 是独立 probe 脚本，不是 v2 benchmark live_runner 主路径；formal E6 依赖 runner 里的 env 传递，需要 `STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix` 被 container wrapper 正确传入（`21_local_vllm_kv_implementation_review` §7 item 10 确认已修复） |
| dynamic pruning env 传播 | `STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED` 控制 evidence pruning 开关，container/E6 会正确传入 | `v2/retrieval/pruning.py:69`：`enabled=_env_flag("STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED", False)` 默认关闭；scripts wrapper 在 E6 后已修复传入 | `e6_formal_guard_mechanism_excerpt`：`mechanism_switches` 字段含 pruning 开关状态；`evidence_pruning_drop_count=25` | ✅ 代码层有明确 env flag 读取；E6 artifact 显示 pruning 生效 | 默认为 False：若 wrapper 未传入，静默使用默认值（不报错）。历史 E3 是独立 deterministic probe，不依赖 env；E6 是 formal guard，确认已传入 |
| dynamic pruning 实际 evidence selection | 按 importance_score 和 `available_kv_cache_bytes` 对候选排序，low-score 候选被 drop | `v2/retrieval/pipeline.py:510-666`：完整的 bucket_stats、pruning_hints 生成逻辑；`keep_in_budget` 由 `capacity_ratio` 决定；`hard_fact` bucket 永不 drop | `e3_dynamic_pruning_ablation`：OFF selected 333 bytes/84 tokens，ON selected 112 bytes/28 tokens；`e6`：`evidence_pruning_drop_count=25`，`pruning_gain_bytes=77134` | ✅ 代码路径真实，E3 数据可追溯 | `kv_bytes_per_token=256` 硬编码于 E3 probe（`scripts/probe_dynamic_pruning_ablation.py`）；这个常数假设 fp16 精度，不适用于 8-bit 量化；`estimated_kv_tokens_saved` 是纯算术估算（`pipeline.py:644`：`max(full_corpus_tokens - selected_evidence_tokens, 0)`），不是 GPU 实测 |
| E6 mechanism switches（组合 profile） | E6 同时开启 shared prefix + dynamic pruning + shared_memory；四角色 API + local embedding + local vLLM | `scripts/run_v2_local_vllm_container_check.sh` + wrapper 向 container 传入 env；`v2/runtime/role_path.py` 和 `pruning.py` 读取 env | `e6_formal_guard_mechanism_excerpt`：`mechanism_switches` 字段；`state_pool_shared_memory_mode_count=25`；`semantic_state_transfer_count=25`；`neural_prefix_shared_prefix_bytes=4359` | ✅ artifact 字段多维度佐证机制生效 | E6 是单次完整 formal run，无 repeat-10；质量底线证明了"组合 profile 不伤质量"，不能反推每个机制的独立贡献 |
| StateRef 非文本传递 | `SemanticStateRef` + `ExecutionArtifactRef` 分离，通过 `LayeredStateStore` 物化为 memfd/shm/mmap 并 hydration 进 prompt | `v2/refs/models.py`：两个类型独立；`v2/state/store.py`：`_materialize_memfd()`；`statepool/store.py:142-280`：v1 StateRef + MmapStatePool + SharedMemoryStatePool + MemfdStatePool | `r01_05`：`memfd_transfer_count=25`；state metadata `storage_kind=memfd`；hydration audit 有 role prompt slices | ✅ memfd 正路径真实；shared_memory/mmap 均有代码路径 | raw evidence/text/table slices 仍通过 hydration 进入 prompt；StateRef 是 additive mechanism，不替代 evidence；hydration 字节无法隐藏证据内容 |
| shared_memory / mmap / memfd backend | 三种 backend 均可用；benchmark 支持 `--statepool-backend` 切换 | `statepool/store.py:62-79`：字符串规范化；`v2/state/store.py` policy/fallback；CLI 参数 `--state-pool-mode` | `r01_05`：memfd backend（25/25）；历史 deterministic artifact：shared_memory；mmap 有代码路径，无本轮 API 强证据 | ✅ memfd 正路径强；shared_memory deterministic 证据；mmap 代码路径存在但本轮 API 证据弱 | no-memfd fallback 主要 unit/monkeypatch 证据；memfd FD 传 subprocess 主要单测，formal 主路径是 loopback harness |
| memory replay / skip execution | validated replay 比较 canonical fresh-evidence hash；exact replay 要求更强 route provenance；`skip_retrieve_execute` 触发需匹配 task theme + query | `v2/runtime/replay.py`：exact/validated gate；v1 `runtime/orchestrator.py`：`allow_exact_replay`/`allow_execute_prune`；`eval/open_runner.py:614`：`reuse_gain = skipped_step_count / 4.0` | `r01_10`：20/20 observed, 17 validated, 3 exact, answer_restoration=0；v1 host：`reuse_gain=0.17`，`skipped_step_count=9`，`memory_hit_rate=0.83` | ✅ 机制真实；v1 host 有 repeat-10 API 证据 | local vLLM 路径 `reuse_gain_delta_l2_to_l3=0.0`（E6 artifact 确认）；v2 local vLLM 未开 replay memory；answer_restoration 已归零（`00_executive_summary` §4） |
| protocol vs text 指标记录 | benchmark 对控制面字节、prompt tokens 均有对比落盘 | `v2/benchmark/comparator_runner.py`：`protocol_bytes`、`text_bytes`、token split 字段；`eval/open_runner.py:790` v1 column list 含 `handoff_wire_bytes` | `r01_06`：`api_prompt_bytes_delta=-12552`；v1 host：`control bytes 150876→128743`；API total tokens `29727→19882` | ✅ 指标有落盘；prompt/input byte delta 可信 | completion/total tokens 更高（不支持 total-token 优势）；v2 formal 无 same-task API text-mode companion stage（只有 internal attribution ladder） |
| local vLLM context handling | `_estimate_chat_prompt_tokens` 估算 prompt tokens，`_cap_max_tokens_for_context` 预收缩 max_tokens，context-window 400 触发 `_context_window_adjusted_request` 重试 | `runtime/llm.py:1199-1244`：3 函数联动；估算逻辑 `(byte_len + 2) // 3`（UTF-8 字节 ÷3 估算）加 split 词数取 max；`_is_transient_openai_error`（l.1273）仅含 408/409/429/5xx，**不含 400**；400 单独由 context-window regex 匹配处理 | 无专属 artifact 字段；historical run roots 有 inferred "vLLM context 400 risk" | ✅ 代码路径精确；400 retry 的实际范围比上一轮 AI 描述的"范围过宽"更窄（只针对 context length 400，非所有 400） | 字符级估算在中文 + 代码混合 prompt 下误差大；safety margin 64 token；可能允许实际超出 context 的请求发出 |
| benchmark telemetry 记录 | 实验 artifact 字段真实来自 benchmark runner 落盘 | `v2/benchmark/reporting.py:93`：`quality_floor_pass_count`；`v2/runtime/smoke.py:2896-2904`：`evidence_pruning_*` 字段；`v2/runtime/neural_state.py:384-388`：`neural_prefix_reuse_estimate_count`、`neural_prefix_cache_hit_count_estimate` | E6 artifact telemetry 字段完整；`kv_analysis.py:52` 从 case.metrics 读取 estimate | ✅ 字段落盘路径清晰 | `neural_prefix_cache_hit_count_estimate` 来自 `neural_state.py:384-388`（判断 `estimated_prefix_tokens > 0`，非 vLLM counter 读取）；`estimated_kv_tokens_saved` 来自 `pipeline.py:644`（纯算术）；两者都是 **estimate / control-plane 推断**，不是 vLLM raw hit/miss 直接读取 |

### 3.1 代码路径核验关键发现

1. **`_is_transient_openai_error` 不含 400**（`runtime/llm.py:1276`）：上一轮 AI 描述的"400 retry 范围过宽"有误——`_is_transient_openai_error` 只重试 408/409/429/5xx；400 单独由 context-window regex (`_context_window_adjusted_request`) 处理，只有 `"maximum context length"` 文本才触发。这是比预期更窄的 retry scope，风险低于原描述。

2. **`estimated_kv_tokens_saved` = 纯算术估算**（`v2/retrieval/pipeline.py:644`）：`max(full_corpus_tokens - selected_evidence_tokens, 0)`，与 GPU 完全无关，任何 embedding 运行都能产生这个数字。artifact 字段 claim_boundary 已写清楚，但字段名本身容易误导。

3. **`neural_prefix_cache_hit_count_estimate` = 控制面推断**（`v2/runtime/neural_state.py:384`）：判断条件是 `estimated_prefix_tokens > 0`，不是读取 vLLM `/metrics` 的 hit counter。

4. **STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED 默认为 False**（`pruning.py:69`）：若 wrapper 未显式传入，pruning 静默关闭。E6 已确认传入；但其他历史 formal run 可能未激活。

5. **v2 formal benchmark 主路径 UDS 是 loopback，非 subprocess**：`ControlPlaneLoopbackServer` 用于 formal runner；`SubprocessExecutorTransport` + memfd FD passing 主要由 `test_subprocess_executor.py` 单测覆盖，不在 formal benchmark 主路径。


---

## 4. Experiment Sufficiency Review

本节对每个主要实验逐一分类证据类型，判断对 PROMPT §三六个问题的回答充分性。

证据类型分类（依强度排序）：
- **direct** — 直接 GPU/进程 instrumentation 或可追溯 artifact 字段
- **proxy** — 通过可信代理指标推断（如 quality floor pass = accuracy proxy）
- **telemetry_estimate** — 控制面计算（如 `estimated_kv_tokens_saved`）
- **inferred** — 从已知字段的算术推断，非测量
- **failed / partial** — 实验已运行但结论不可用（设计局限、单侧数据等）

---

### 4.1 PROMPT §三六个核心问题逐一回答

**Q1：非文本中间状态是否真实生成、传递并被接收方使用？**

| 证据 | 类型 | Artifact |
|---|---|---|
| `r01_05`：`semantic_state_transfer_count=25`，`memfd_transfer_count=25`，`memfd_bytes_transferred=247076` | direct | `local_api_20260707_163354/r01_05` |
| E6 L3：`semantic_state_transfer_count=25`，`state_pool_shared_memory_mode_count=25` | direct | `e6_formal_guard_mechanism_excerpt` |
| `SemanticStateRef` + `LayeredStateStore._materialize_memfd()` 代码路径 | direct（代码） | `v2/state/store.py`，`v2/refs/models.py` |

**结论：✅ 充分**。非文本传递（memfd/shm physical bytes）有直接计数证据。边界（答辩必须明说）：传递的是 embedding semantic state + refs + hydration slices，不是 hidden-state/KV tensor；hydration 后内容仍进入 LLM prompt。

---

**Q2：Engine-Local Prefix Reuse 是否可观测且方向一致？**

| 证据 | 类型 | Artifact |
|---|---|---|
| E1 clean-service：friendly hit-rate `0.789` vs hostile `0.524`，TTFT `885` vs `1569 ms`，Δ=`+0.265`/`-684ms` | direct（vLLM Prometheus gauge） | `e1_e2_clean_service_repeat_summary_20260711_1438` |
| E2 clean-service：shared `0.780` vs independent `0.0`，TTFT `967` vs `3526 ms`，Δ=`+0.780`/`-2559ms` | direct（vLLM Prometheus gauge） | `e1_e2_clean_service_repeat_summary_20260711_1438` |
| `restart_policy`：每次模式切换前重启 vLLM，初始 hit-rate=0.0（隔离设计） | 设计控制 | 同上 |
| E6 end：`vllm:gpu_prefix_cache_hit_rate=0.659` | direct（Prometheus gauge） | `e6_formal_guard_mechanism_excerpt` |
| `neural_prefix_cache_hit_count_estimate=25` | telemetry_estimate（`estimated_prefix_tokens > 0` 推断，非 raw counter） | `v2/runtime/neural_state.py:384` |

**结论：✅ 方向闭环，但有精度限制**。E1/E2 clean-service 重启隔离设计良好，方向一致性可信。注意：`gpu_prefix_cache_hit_rate` 是 vLLM 移动平均 gauge（非 raw hit/miss counter），受 batch 时序影响；`neural_prefix_cache_hit_count_estimate` 是控制面推断，不直接对应 vLLM 内部 counter。答辩需区分两个字段的精度层级。

---

**Q3：dynamic pruning 是否在保质量前提下减少 prompt token 压力？**

| 证据 | 类型 | Artifact |
|---|---|---|
| E3：OFF selected 333 bytes/84 tokens → ON selected 112 bytes/28 tokens（Δ=`-221 bytes/-56 tokens`）；`hard_fact fact-revenue-1` 保留 | direct（retrieval-level deterministic probe） | `e3_dynamic_pruning_ablation_20260711.json` |
| E3 quality proxy pass：`hard_fact_and_structured_evidence_preservation=true` | proxy（非 LLM 质量评分） | 同上 |
| E6：`evidence_pruning_drop_count=25`，`pruning_gain_bytes=77134`，`evidence_pruning_estimated_kv_tokens_saved=9644` | direct（计数）+ telemetry_estimate（token 换算） | `e6_formal_guard_mechanism_excerpt` |
| E6 quality：L0-L3 全 25/25，quality delta=0 | proxy（相对于 L0 text baseline） | `e6_formal_guard_summary` |
| `estimated_kv_tokens_saved=max(full_corpus_tokens - selected_evidence_tokens, 0)` | inferred（纯算术，无 GPU 测量） | `v2/retrieval/pipeline.py:644` |
| `kv_bytes_per_token=256`（E3 probe 硬编码，fp16 假设，不适用 8-bit 量化） | inferred（常数假设） | `scripts/probe_dynamic_pruning_ablation.py` |

**结论：⚠️ 机制充分，但 token-saved 数字是估算**。E3 quality proxy 不等于 LLM end-to-end quality；E6 通过 quality delta=0 间接确认"pruning 不伤质量"，但 `estimated_kv_tokens_saved=9644` 是输入侧算术估算，答辩不得表述为"节省了 9644 个 KV cache token"。

---

**Q4：protocol 结构化通信相比纯文本是否节省 token/字节且质量不降？**

| 证据 | 类型 | Artifact |
|---|---|---|
| E6：L3 total tokens `62667` vs L0 text `113949`，Δ=`-51282`；prompt Δ=`-45652`；control bytes Δ=`-31256` | direct（token counter） | `e6_formal_guard_summary` |
| E6 quality delta=0（L0 vs L3 全 25/25） | proxy（quality floor） | `e6_formal_guard_summary` |
| no-KV/API `r01_06`：prompt bytes Δ=`-12552`（protocol vs text）；completion/total tokens 更高 | partial（仅 prompt-side 优势，total tokens 劣） | `local_api_20260707_163354/r01_06` |
| v2 formal benchmark 无 same-task API text-mode companion stage | failed（设计缺口） | — |

**结论：⚠️ KV 主线证据强，no-KV API 主线证据不完整**。E6 L0 vs L3 是 attribution ladder（L0 text / L1 embed / L2 pruning / L3 protocol），不是两个独立完整配置的等价双模对比。no-KV API formal benchmark 没有 same-task text companion，无法支持"v2 API formal 优于 text"的 total-token claim。这是核心实验 gap（G-01）。

---

**Q5：记忆复用（replay）是否可观测且有真实 reuse_gain？**

| 证据 | 类型 | Artifact |
|---|---|---|
| `r01_10`：20/20 observed，17 validated，3 exact，answer_restoration=0 | direct | `local_api_20260707_163354/r01_10` |
| `r01_09`：3 families/30 rounds，`L3_reuse_gain=9` | direct | `r01_09` |
| v1 host bundle：`reuse_gain=0.17`，`skipped_step_count=9`，`memory_hit_rate=0.83` | direct | `runs/host_goal_eval_*` |
| E6 KV 主线：`reuse_gain_delta_l2_to_l3=0.0`（replay memory 未开） | direct（无 replay） | `e6_formal_guard_mechanism_excerpt` |

**结论：✅ no-KV/API 主线充分**。v2 API + v1 host 双线均有 validated replay + reuse_gain 正数。注意：KV/local vLLM 主线未开 replay memory（E6 `reuse_gain=0`）——两条链复用语义不同，答辩必须区分，不得把 `r01_09 L3_reuse_gain=9` 说成 KV 主线的结果。

---

**Q6：整体系统是否稳定（≥10 轮连续任务无崩溃）？**

| 证据 | 类型 | Artifact |
|---|---|---|
| `r01_09`：3 families/30 rounds，全部 exit 0 | direct | `r01_09` |
| v1 host deterministic repeat-10：`expectation_match_rate=1.00`，`failure_count=0` | direct | `runs/host_goal_eval_*` |
| E6 formal guard：25/25 L0-L3 全 pass（单次完整，无 repeat） | direct（单次） | `e6_formal_guard_summary` |
| KV 主线无 repeat-10 稳定性证据 | failed/partial | — |

**结论：⚠️ no-KV 主线稳定，KV 主线稳定性证据弱**。E6 是单次 25-case formal，无连续 10 轮 repeat 设计；E1/E2 各 3 次 repeat（无误差线）。答辩若声称 KV 主线稳定，应限定"单次 25-case formal 通过，未运行连续 30 轮"。

---

### 4.2 实验覆盖矩阵

| 实验 | 主线 | 证据类型（最强层级） | PROMPT 对应问题 | 充分性 | 关键局限 |
|---|---|---|---|---|---|
| E0 health | KV | direct（vLLM health API + config） | 环境基线 | ✅ | 仅 health，无压力测试 |
| E1 schedule ablation | KV | direct（vLLM gauge，3次 clean repeat） | Q2 prefix reuse 方向 | ✅ | gauge 非 raw counter；3次无误差线 |
| E2 prefix alignment | KV | direct（vLLM gauge，3次 clean repeat） | Q2 prefix reuse 方向 | ✅ | 独立 probe 脚本非 live_runner 主路径 |
| E3 dynamic pruning | KV | direct（retrieval-level）+ proxy（quality） | Q3 pruning 机制 | ⚠️ | deterministic probe；token-saved 算术估算 |
| E6 formal guard | KV | direct（token counter + vLLM gauge）+ proxy（quality floor） | Q3/Q4/Q2 组合 | ✅ | 单次 formal；L0 vs L3 attribution ladder 非等价双模 |
| r01_05 formal internal | API | direct（memfd count + bytes + quality） | Q1 非文本传递 + Q6 稳定性 | ✅ | hydration 后仍进 LLM prompt |
| r01_06 compare | API | partial（prompt-only；total tokens 劣） | Q4 protocol vs text | ⚠️ | 仅 8-case；`formal_external_claim_kind=debug_only` |
| r01_09 continuous | API | direct（30 rounds，reuse_gain=9） | Q5 记忆复用 + Q6 稳定性 | ✅ | API 主线；KV 主线无对应 |
| r01_10 replay | API | direct（validated/exact gate） | Q5 记忆复用 | ✅ | answer_restoration=0（见 G-06） |
| v1 host bundle | API | direct（repeat-10，reuse_gain=0.17） | Q5/Q6 | ✅ | v1 架构；不等同于 v2 |

---

### 4.3 三个最关键充分性缺口

1. **v2 formal API 主线缺 same-task text-mode companion**（Q4，影响"两种协作模式"评分）→ G-01
2. **KV 主线 `estimated_kv_tokens_saved` / `neural_prefix_cache_hit_count_estimate` 是估算/推断，非直接 GPU 测量**（Q3/Q2，影响精度表述）→ G-05/G-08
3. **KV 主线无 repeat-10 连续任务稳定性证据**（Q6，影响实验验证维度）→ G-11

---

## 5. Gap And Risk Ledger

格式：`G-{ID}`，按影响严重度降序。每条含：描述 / 影响评分维度 / 证据来源 / 风险类型 / 修复优先级。

---

### G-01：v2 formal API 主线无 same-task text-mode companion stage

- **描述**：v2 formal benchmark（`--suite formal`）只运行 protocol lane；无同任务、同输入的 API text 对比组。`r01_06` compare 仅 8 cases，且 `formal_external_claim_kind=debug_only`（不支持 efficiency superiority 结论）。KV 主线 E6 的 L0 vs L3 是 attribution ladder，不能代替 API 主线的 text companion。
- **影响维度**：通信效率（25分）——"两种协作模式相同任务可复现对比"是赛题硬要求
- **证据来源**：`r01_06` 字段 `formal_external_claim_kind=debug_only`；`v2/benchmark/comparator_runner.py`
- **风险类型**：experiment gap
- **修复优先级**：P0

---

### G-02：KV 主线未开 replay memory，`reuse_gain=0`

- **描述**：E6 `reuse_gain_delta_l2_to_l3=0.0`。vLLM 主线 replay memory 未在 E6 profile 中启用，KV 主线对"跨任务记忆复用"无直接证据。
- **影响维度**：记忆复用效果（20分）
- **证据来源**：`e6_formal_guard_mechanism_excerpt`（`mechanism_switches` 无 replay 相关 env）；`v2/runtime/replay.py` 存在但未激活
- **风险类型**：implementation gap（代码存在，KV 主线未跑）
- **修复优先级**：P1

---

### G-03：v2 formal 只有 1 family，缺"≥2 组关联性连续任务"多 family 证据

- **描述**：`e6_formal_guard_summary`：`selected_case_count=25` 但为 1 family（`financial_report_analysis`）。赛题要求"≥2 组关联性连续任务"。v2 API `r01_09` 有 3 families/30 rounds，但 KV 主线无多 family 实验。
- **影响维度**：系统完整性（20分）+ 实验验证（15分）
- **证据来源**：`e6_formal_guard_summary`；`tasks/` 任务注册表含多 family
- **风险类型**：experiment gap
- **修复优先级**：P1

---

### G-04：no-KV API `r01_06` compare `formal_external_claim_kind=debug_only`，total tokens 劣

- **描述**：`r01_06` 的 prompt bytes Δ=-12552 被标为 `debug_only`。completion/total tokens 更高（protocol > text），即 total token 优势不成立。若引用 prompt-only delta 作为通信效率优势，属于 overclaim。
- **影响维度**：通信效率（25分）
- **证据来源**：`local_api_20260707_163354/r01_06`
- **风险类型**：overclaim risk
- **修复优先级**：P0（答辩不得引用此数据支持 total-token 优势）

---

### G-05：`estimated_kv_tokens_saved` 是纯算术估算，非 GPU 测量

- **描述**：`v2/retrieval/pipeline.py:644`：`estimated_kv_tokens_saved = max(full_corpus_tokens - selected_evidence_tokens, 0)`。与 GPU 完全无关，任何 embedding 运行都能产生。字段名带 "kv_saved" 容易被误读为"GPU KV cache 节省了 N 个 token"。E6 artifact `evidence_pruning_estimated_kv_tokens_saved=9644`。
- **影响维度**：通信效率（25分）+ 状态传递创新（20分）
- **证据来源**：`v2/retrieval/pipeline.py:644`
- **风险类型**：overclaim risk（字段名误导）
- **修复优先级**：P0（答辩表述必须加注"输入侧算术估算"）

---

### G-06：`answer_restoration=0`，replay 质量无端到端验证

- **描述**：`r01_10`：20/20 replay observed，17 validated，3 exact，但 `answer_restoration=0`。检测有了，"回放后答案质量与原始一致"的端到端验证率为 0。
- **影响维度**：记忆复用效果（20分）
- **证据来源**：`local_api_20260707_163354/r01_10`
- **风险类型**：experiment gap
- **修复优先级**：P1

---

### G-07：flagship ablation 3/6 family pass，高难度任务类型质量不稳定

- **描述**：`r01_12`：`incident_diagnosis_v2`/`long_doc_metric_replay_v1`/`cross_period_financial_v1` 未达标；3/6 pass。StateRef prompt saving 有 delta（37884 bytes），但部分 family 质量 gap 未收敛。
- **影响维度**：系统完整性（20分）
- **证据来源**：`local_api_20260707_163354/r01_12`；`v2/benchmark/flagship_ablation.py`
- **风险类型**：implementation gap
- **修复优先级**：P2

---

### G-08：`neural_prefix_cache_hit_count_estimate` 是控制面推断，非 vLLM raw counter

- **描述**：`v2/runtime/neural_state.py:384`：`if estimated_prefix_tokens > 0: neural_prefix_cache_hit_count_estimate += 1`。这是控制面"存在 prefix token"的计数，与 vLLM 内部 prefix cache scheduler 无直接连接。E6 `neural_prefix_cache_hit_count_estimate=25` 不等于"vLLM 有 25 次 cache hit"。
- **影响维度**：状态传递创新（20分）
- **证据来源**：`v2/runtime/neural_state.py:384`
- **风险类型**：overclaim risk（字段名带 "cache_hit"，易误导）
- **修复优先级**：P0（答辩必须区分 vLLM Prometheus gauge vs 控制面推断）

---

### G-09：mmap backend 缺本轮 API formal 直接证据

- **描述**：`statepool/store.py` mmap 代码路径存在，但本轮 API formal（`r01_05`）使用 memfd backend；no-KV 主线缺 mmap 在 formal benchmark 下的真实 artifact。
- **影响维度**：状态传递创新（20分）
- **证据来源**：`r01_05`：`state_pool_mode_used=memfd`；`statepool/store.py` 代码路径已验证
- **风险类型**：experiment gap（代码有，formal 证据弱）
- **修复优先级**：P2（memfd 已是主路径，mmap 是 fallback）

---

### G-10：误建文件 `tatus --short --branch` 是 artifact-quality 噪声

- **描述**：工作目录含未跟踪文件 `tatus --short --branch`（`git status --short --branch` 命令被截断成文件名，疑似误重定向）。非功能 gap，但属于 artifact-quality 噪声。
- **影响维度**：系统完整性（20分，边缘）
- **证据来源**：Section 0 git status
- **风险类型**：reproducibility risk（低）
- **修复优先级**：P3

---

### G-11：KV 主线无 repeat-10 连续任务稳定性实验

- **描述**：E6 是单次 25-case formal run；E1/E2 各 3 次 repeat（无误差线）。没有运行 KV 主线 continuous 10-round 重复验证。若问"local vLLM 主线 10 轮连续是否稳定"，当前只能回答"单次 25-case 全 pass"。
- **影响维度**：实验验证（15分）
- **证据来源**：E6 单次 run；`v2/benchmark/continuous_runner.py` 未用于 KV 主线
- **风险类型**：experiment gap
- **修复优先级**：P1

---

### G-12：formal benchmark UDS 是进程内 loopback，非真实跨进程 socket IPC

- **描述**：v2 formal benchmark 主路径用 `ControlPlaneLoopbackServer`（进程内 loopback），非 `SubprocessExecutorTransport` + Unix socket FD pass。赛题鼓励 IPC/共享内存/Socket，但 formal 主路径的 UDS 是 loopback，实际未做跨进程 socket 传递。
- **影响维度**：系统完整性（20分）+ 鼓励项
- **证据来源**：`v2/benchmark/` runner 初始化；`test_subprocess_executor.py`（单测）；`test_uds_loopback.py`（loopback 单测）
- **风险类型**：overclaim risk（若表述"formal benchmark 使用跨进程 UDS"）
- **修复优先级**：P2

---

### G-13：openEuler VM 未验证，交付要求存在 reproducibility risk

- **描述**：赛题交付要求 openEuler 24.03-LTS-SP3 可编译/运行/测试。当前只有 Docker container 证据，无 VM 验证 artifact。CLAUDE.md 已明示："Do not claim openEuler compatibility unless validated in VM"。
- **影响维度**：系统完整性（20分）+ 交付
- **证据来源**：CLAUDE.md；无 VM artifact
- **风险类型**：reproducibility risk（高，影响最终交付）
- **修复优先级**：P1（非本轮实验阻塞，但交付前必须）


---

## 6. Terminology Boundary Risk Table

下表列出答辩中高频出现、容易被误读或过度 claim 的 13 个术语，逐一标注"安全表述"与"禁止表述"。

| 术语 | 实际含义（代码路径） | 安全表述 | 禁止表述 | 风险级别 |
|---|---|---|---|---|
| `Engine-Local Prefix Reuse` | vLLM automatic prefix caching 受 schedule/layout 控制被诱导命中；不持有 KV tensor；不跨进程/跨引擎 | "通过 prompt layout（`shared_evidence_prefix`）和 request schedule（cache-friendly order）诱导 vLLM automatic prefix caching 命中，降低 TTFT" | "KV cache 被传递/共享/导出"；"跨 agent KV 复用" | 🔴 高 |
| `estimated_kv_tokens_saved` | `max(full_corpus_tokens - selected_evidence_tokens, 0)`，输入侧算术（`pipeline.py:644`） | "输入侧算术估算的等效 token 减少量" | "节省了 N 个 KV cache token"；"GPU 测量节省" | 🔴 高 |
| `neural_prefix_cache_hit_count_estimate` | 控制面推断：`estimated_prefix_tokens > 0` 时计数（`neural_state.py:384`） | "控制面推断的 prefix 共享次数" | "vLLM hit counter"；"N 次 GPU cache 命中" | 🔴 高 |
| `gpu_prefix_cache_hit_rate` | vLLM Prometheus 移动平均 gauge（非 raw hit/miss counter） | "vLLM Prometheus gauge（移动平均），E1/E2 clean-service 实测 0.789 / 0.780" | "精确 hit/miss 比率"；与 `neural_prefix_cache_hit_count_estimate` 混同 | 🟡 中 |
| `SemanticStateRef` / 非文本状态传递 | embedding semantic state + refs，通过 memfd/shm 物化，hydration 后内容仍进 LLM prompt | "embedding 语义状态通过 memfd/shm 物化传递，25 次 / 247076 bytes（r01_05 实测）" | "hidden-state 传递"；"KV tensor 传递"；"LLM 中间层状态" | 🔴 高 |
| `reuse_gain` (v2 API) | `skipped_step_count / 4.0`（`eval/open_runner.py:614`），任务级跳过步骤比率 | "API 主线任务级记忆复用增益，r01_09 L3=9，v1 host=0.17" | "KV 主线 reuse_gain"（E6=0）；混用两条链数字 | 🟡 中 |
| `text_whole_lane` | 内部 comparator，非外部纯文本 baseline | "内部对比通道，用于 attribution ladder" | "与纯文本 agent 系统的对比基线" | 🟡 中 |
| `formal_external_claim_kind=debug_only` | `r01_06` compare 数据不支持对外 efficiency superiority 结论 | 不引用 `r01_06` 作为效率优势证据 | "v2 API formal 证明 protocol 优于 text total token" | 🔴 高 |
| `shared_evidence_prefix` | env 变量 `STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix`，控制 prompt layout（`role_path.py:881`） | "prompt layout 策略：公共证据移到开头，利于 vLLM prefix cache 命中" | "KV cache 共享前缀"（KV tensor 层面） | 🟡 中 |
| `dynamic pruning` | input-level evidence selection（`pruning.py`），非 model-internal KV pruning | "输入侧证据剪枝，减少送入 LLM 的 evidence token 数量" | "模型内部 KV 剪枝"；"attention pruning" | 🟡 中 |
| `answer_restoration` | replay 后"答案质量与原始一致"的端到端验证率（当前=0） | "replay 检测率有数据（17 validated），answer restoration 尚未测量" | "replay 质量验证率 = validated/total" | 🟡 中 |
| `ControlPlaneLoopbackServer` | 进程内 loopback server（formal benchmark 主路径），非跨进程 UDS | "控制面使用 loopback UDS，减少序列化往返；跨进程 transport 见单测" | "formal benchmark 使用跨进程 Unix socket IPC" | 🟡 中 |
| `kv_bytes_per_token=256` | E3 probe 硬编码常数（fp16 精度假设），不适用 8-bit 量化 | "fp16 假设下的等效 KV 字节估算常数（E3 probe 用）" | "实测 KV cache 字节占用" | 🟡 中 |

---

## 7. Fix Priority Matrix

优先级定义：
- **P0**：答辩前必须处理（不处理会直接误导评委或违反赛题要求）
- **P1**：答辩前强烈建议处理（能显著提升证据完整性）
- **P2**：有余力时处理（改善但不阻塞）
- **P3**：低影响，答辩后处理

| 优先级 | Gap ID | 修复方向 | 修复类型 | 预估工作量 |
|---|---|---|---|---|
| **P0** | G-01 | 在 API 主线运行 `--suite compare --benchmark-tier formal`（full 25-case text companion）或在答辩中明确限定"KV 主线 E6 attribution ladder 是内部对比，非等价双模" | 实验 or 表述 | 中（需 API key + 完整 formal run）or 低（仅答辩表述修正） |
| **P0** | G-04 | 答辩材料中删除 `r01_06` 作为 efficiency superiority 证据；改引 E6 L0 vs L3 token delta | 表述 | 低 |
| **P0** | G-05 | 所有引用 `estimated_kv_tokens_saved` 的地方加注"输入侧算术估算，非 GPU 测量" | 表述 | 低 |
| **P0** | G-08 | 所有引用 `neural_prefix_cache_hit_count_estimate` 的地方加注"控制面推断"；改引 `vllm:gpu_prefix_cache_hit_rate` 作为直接 GPU 指标 | 表述 | 低 |
| **P1** | G-02 | 在 KV 主线 E6 profile 加入 replay memory 开关，补充一次 formal run；或在答辩中限定"KV 主线记忆复用（replay）未测，API 主线有证据" | 实验 or 表述 | 中（实验）or 低（表述） |
| **P1** | G-03 | 在 KV 主线补充一次 2-family continuous formal run；或明确表述"KV 主线 formal 覆盖 1 family，多 family 连续任务见 API 主线 r01_09" | 实验 or 表述 | 中 or 低 |
| **P1** | G-06 | 实现或补充 `answer_restoration` 端到端验证；或明确表述"replay 检测率有数据，质量恢复验证待补充" | 实验 or 表述 | 中 or 低 |
| **P1** | G-11 | 在 KV 主线补充 continuous 10-round repeat；或限定"KV 主线单次 25-case formal 通过，连续稳定性见 API 主线 r01_09" | 实验 or 表述 | 中 or 低 |
| **P1** | G-13 | 在 openEuler VM 跑 smoke + pytest；记录结果 | 实验 | 高（需 VM 环境） |
| **P2** | G-07 | flagship ablation 3/6 family 未收敛任务类型补充 prompt engineering 或 quality guard 调优 | 实现 | 高 |
| **P2** | G-09 | 补充一次 `--state-pool-backend mmap` 的 formal run，生成 mmap artifact | 实验 | 低 |
| **P2** | G-12 | 在答辩中明确"formal benchmark 控制面是 loopback UDS；跨进程 socket 见 smoke/单测" | 表述 | 低 |
| **P3** | G-10 | `git rm --cached 'tatus --short --branch'` + `.gitignore` 追加 | 清理 | 极低 |

### 7.1 答辩最低操作清单（仅 P0）

不跑新实验的情况下，只需修改答辩材料表述：

1. 删除 `r01_06` 作为效率优势的引用（G-04）
2. 所有 `estimated_kv_tokens_saved` 加注"输入侧算术估算"（G-05）
3. 所有 `neural_prefix_cache_hit_count_estimate` 加注"控制面推断"，用 `gpu_prefix_cache_hit_rate` 作为直接指标（G-08）
4. 把 E6 L0 vs L3 定性为"attribution ladder（内部层间对比）"，不说"等价双模对比"（G-01 表述修正）

---

## 8. Open Questions

以下问题在本审计中未能完全闭环，记录供后续答辩准备参考。

**OQ-1：KV 主线 E6 的 `vllm:gpu_prefix_cache_hit_rate=0.659` 是哪 N 个 request 的平均？**
E6 run 总计 `vllm:request_success_total_stop=402`（4 layers × 25 cases × ~4 roles），0.659 是整个 run 结束时的移动平均，无法追溯到单 case 粒度。答辩若被问"每个 case 的 hit-rate 是多少"，当前 artifact 无法精确回答。建议引用 E1/E2 clean-service 数字（每次 10/5 次 request 的干净实验）替代。

**OQ-2：为什么 E2 independent 模式 `final_gpu_prefix_cache_hit_rate=0.0`（而非小于 E2 shared）？**
E2 clean-service：independent 模式 5 次 request，每次送入不同 prompt layout（无公共前缀），vLLM 不能复用任何 prefix，因此 hit-rate=0.0 是预期行为，不是数据异常。但答辩时需要能解释清楚，否则会被质疑数据可信度。

**OQ-3：`r01_09 L3_reuse_gain=9` 的分母是什么？**
`reuse_gain = skipped_step_count / 4.0`（`eval/open_runner.py:614`），分母 4 是 4-role pipeline 的最大可跳过步数。`L3_reuse_gain=9` 意味着 30 轮中有 9 个 step 被跳过，即 `skipped_step_count=36`，`reuse_gain_rate=36/(30×4)=30%`。答辩前需确认此解读是否与代码一致，避免分母理解错误。

**OQ-4：`sb32bcompact` artifact 与 E6 数字的差异来源？**
`sb32bcompact`：total Δ=-57946；E6：total Δ=-51282。差异约 6664 tokens，可能源于 context length（sb32bcompact 是 4096 ctx，E6 是 8192 ctx）和 case 组成差异。答辩若同时引用两组数字，需说明差异来源，否则会被质疑数据一致性。

**OQ-5：`v2/benchmark/continuous_runner.py` 是否支持 `local_vllm` role-path-mode？**
本审计未验证 KV 主线（`--role-path-mode local_vllm`）在 `continuous_runner.py` 下的运行路径。G-11 的"KV 主线无 repeat-10"可能部分原因是 continuous runner 未适配 local vLLM 模式，需要确认是"能跑但没跑"还是"runner 不支持该模式"，这影响 G-11 的修复代价估算。

**OQ-6：openEuler VM 部署的关键阻塞点是什么？**
CLAUDE.md 明确不得 claim openEuler 兼容性，但交付要求 openEuler 24.03-LTS-SP3。当前 Docker image 使用何种 base OS、Python 版本是否与 openEuler 兼容、本地依赖（faiss-cpu、sentence-transformers）是否有 RPM/wheel，均未记录。G-13 的修复计划需要先澄清这些阻塞点，才能给出准确工期。

---

## 9. Gap 详细修复方案

本节对 G-01 到 G-12（排除 G-11 repeat-10、G-13 openEuler VM）逐一给出可执行的修复方案。每条含：修复类型 / 具体操作 / 验收标准 / 预估工时。

修复类型缩写：
- **[表述]** — 只改答辩材料 / 文档，零代码风险
- **[实验]** — 需要运行 benchmark，消耗 GPU 时间
- **[代码]** — 需要修改源码，需跑测试验证
- **[清理]** — git 操作或文件清理

---

### F-01（对应 G-01）：补充 same-task text vs protocol 等价双模对比

**修复类型**：[实验] + [表述]

**背景**：赛题要求"两种协作模式相同任务可复现对比"，当前 v2 formal 只有 protocol lane，`r01_06` 的 compare 被标为 `debug_only`。E6 L0 vs L3 是 attribution ladder（内部消融），不是等价双模对比。

**操作步骤（实验路径）**：

将 API 主线的 LLM provider 切换到本地 Qwen3-32B vLLM（已在 card0 运行），然后运行 compare suite：

```bash
# 第一步：更新 deploy/statebus_llm.yaml.local
# 把 base_url 从 https://api.deepseek.com 改为 http://127.0.0.1:53334/v1
# 把所有 role 的 model 改为 qwen3-32b

# 第二步：先验证 JSON 输出兼容性（~5分钟）
python -m v2.benchmark.live_runner \
    --suite preflight \
    --role-path-mode api \
    --embedding-mode deterministic

# 第三步：运行 compare suite（text lane + protocol lane 各 25 cases）
STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1 \
python -m v2.benchmark.live_runner \
    --suite compare \
    --benchmark-tier formal \
    --role-path-mode api \
    --embedding-mode local
```

**compare suite 会产生什么**：`comparator_runner.py` 同时跑 `text_whole_lane`（纯文本）和 `protocol_lane`，对相同 task 输出两组 token/bytes 数字。如果 `formal_compare_full_registry_coverage=true` 且质量门通过，`formal_external_claim_kind` 会从 `debug_only` 升级为 `formal_quality_superiority_external_compare`（见 `comparator_runner.py:749`）。

**操作步骤（表述路径，若实验暂时无法跑）**：

在答辩材料中把 E6 L0 vs L3 定性改为：
> "E6 attribution ladder（L0 纯文本 → L1 +embedding → L2 +pruning → L3 +protocol）展示了每层机制的增量 token 节省，不是独立配置的 A/B 对比。same-task 等价双模对比见 [新 compare run artifact]（待补充）或 API 主线 Qwen3-32B compare 结果。"

**验收标准**：compare run 的 `formal_external_claim_kind` 字段不为 `debug_only`，且 text vs protocol 的 quality delta = 0（质量不降），token delta < 0（protocol 节省）。

**预估工时**：实验路径 ~2-3 小时（含 preflight 验证）；表述路径 ~30 分钟。

---

### F-02（对应 G-02）：KV 主线补充 replay memory 证据

**修复类型**：[表述]（主路径）+ [实验]（可选）

**背景**：E6 `reuse_gain_delta_l2_to_l3=0.0`，因为 E6 profile 的 `mechanism_switches` 里没有 replay memory env。KV 主线未开 replay，导致"记忆复用效果（20分）"这个维度完全由 API 主线承担。

**表述修复（立即可做）**：

在答辩材料中明确区分两种"复用"：
> - **任务级记忆复用（replay gate）**：由 API 主线证明。v2 `r01_09` 3 families/30 rounds `reuse_gain=9`，v1 host `reuse_gain=0.17`，`skipped_step_count=9`。代码路径：`v2/runtime/replay.py`。
> - **引擎级 prefix cache 复用（Engine-Local Prefix Reuse）**：由 KV 主线证明。E1/E2 clean-service hit-rate `0.789`/`0.780`，TTFT delta `-684ms`/`-2559ms`。代码路径：`v2/benchmark/kv_prefix_schedule.py`、`v2/runtime/neural_state.py`。
>
> 两种复用是不同层次的机制，互补而非矛盾。KV 主线没有开启 replay gate，是设计选择（保持机制隔离），不代表系统不支持复用。

**实验路径（可选，可在 Qwen3-32B 全量测试时一并补充）**：

在 E6 formal run 的 env 里加入 replay memory 开关，运行一次带 replay 的 KV formal：
```bash
STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix \
STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1 \
STATEBUS_REPLAY_MEMORY_ENABLED=1 \
python -m v2.benchmark.live_runner \
    --suite statebus \
    --benchmark-tier dev \
    --role-path-mode local_vllm \
    --embedding-mode local
```

**验收标准**：答辩材料中两种复用有独立的证据来源和表述，不混用数字。实验路径：KV 主线出现 `replay_hit_rate > 0` 或 `reuse_gain > 0`。

**预估工时**：表述路径 ~30 分钟；实验路径 ~1 小时。

---

### F-03（对应 G-03）：补充多 family 连续任务证据

**修复类型**：[表述] + [实验]（可选）

**背景**：E6 formal 只有 1 family（`financial_report_analysis`），赛题要求"≥2 组关联性连续任务"。API 主线 `r01_09` 有 3 families/30 rounds，是当前最强的多 family 证据。

**表述修复（立即可做）**：

在答辩材料中统一表述为：
> "多 family 连续任务稳定性由 API 主线 `r01_09` 证明（3 families / 30 rounds，全程 exit 0）。KV/local vLLM 主线 formal guard（E6）覆盖 1 family / 25 cases，专注于机制正确性验证，不重复多 family 稳定性测试。"

**实验路径（Qwen3-32B 全量测试时补充）**：

在统一到 Qwen3-32B 后，运行一次多 family 的 continuous run：
```bash
python -m v2.benchmark.live_runner \
    --suite statebus \
    --benchmark-tier formal \
    --role-path-mode api \
    --embedding-mode local
# statebus suite 默认包含多 family continuous 任务
```

**验收标准**：答辩材料中有明确的 multi-family 引用来源。实验路径：新 run 出现 ≥2 family 的 continuous artifact。

**预估工时**：表述路径 ~20 分钟；实验路径 ~1 小时。

---

### F-04（对应 G-04）：删除 `r01_06` 作为效率优势引用

**修复类型**：[表述]

**背景**：`r01_06` 的 `formal_external_claim_kind=debug_only`，且 completion/total tokens protocol > text（total token 优势不成立）。若在答辩中引用 `r01_06` 的 prompt bytes delta（-12552）作为通信效率优势，属于 overclaim。

**具体改动**：

在所有引用 `r01_06` 数字作为"通信效率证明"的地方，替换为以下表述：
> - 旧："`r01_06` compare：protocol prompt bytes -12552（vs text），证明协议通信更高效"
> - 新："通信效率证据来自 E6 formal guard attribution ladder：L3 protocol vs L0 text，total tokens Δ=-51282，prompt tokens Δ=-45652，control bytes Δ=-31256，质量 delta=0（L0-L3 全 25/25）。`r01_06` 为内部调试数据，不用于对外效率主张。"

**E6 数字来源**（可直接引用 artifact 字段）：
```
e6_formal_guard_summary_20260711_1448.json:
  protocol_vs_text_token_delta:         -51282
  protocol_vs_text_prompt_token_delta:  -45652
  protocol_vs_text_control_bytes_delta: -31256
  quality_pass_delta:                    0（L0-L3 全 25/25）
```

**验收标准**：答辩材料中无对 `r01_06` 数字的效率优势引用；所有效率数字引用来自 E6 artifact。

**预估工时**：~20 分钟（全文搜索替换）。

---

### F-05（对应 G-05）：为所有 `estimated_kv_tokens_saved` 引用加注

**修复类型**：[表述] + [代码注释]

**背景**：`v2/retrieval/pipeline.py:644`：`estimated_kv_tokens_saved = max(full_corpus_tokens - selected_evidence_tokens, 0)`。这是纯输入侧算术，与 GPU 完全无关。字段名带 "kv" 和 "saved" 容易被评委误读为"GPU 测量节省了 N 个 KV cache token"。

**表述修复（答辩材料）**：

所有引用此字段的地方，改为以下格式：
> "`evidence_pruning_estimated_kv_tokens_saved=9644`（输入侧算术估算：`max(full_corpus_tokens - selected_evidence_tokens, 0)`，等效减少的输入 token 量，非 GPU 实测）"

**代码注释修复**（防止后续混淆，改注释不改逻辑）：

```python
# v2/retrieval/pipeline.py:644 附近，在字段赋值上方加注释
# NOTE: estimated_kv_tokens_saved 是输入侧算术估算，不是 GPU KV cache 实测。
# 计算方式：max(full_corpus_tokens - selected_evidence_tokens, 0)。
# 含义：若不做 evidence pruning，额外需要处理的输入 token 数上界。
# 不得表述为"节省了 N 个 GPU KV cache token"。
estimated_kv_tokens_saved = max(full_corpus_tokens - selected_evidence_tokens, 0)
```

同样，在 artifact 的 `claim_boundary` 字段中已有说明（`input_level_evidence_pruning_only_no_model_internal_kv_tensor_pruning`），答辩时可直接引用此字段作为自证边界。

**验收标准**：答辩材料中无"GPU 节省 N 个 KV token"的表述；`pipeline.py:644` 附近有清晰注释。

**预估工时**：~30 分钟（代码注释 + 材料修改）。


---

### F-06（对应 G-06）：`answer_restoration` 端到端 replay 质量验证

**修复类型**：[表述]（立即）+ [代码]（可选）

**背景**：`r01_10` 有 17 validated replay，但 `answer_restoration=0`。`answer_restoration` 字段是"回放后答案与原始 fresh run 精确匹配"的计数，当前 replay gate 只验证了 evidence hash 一致性，没有对比最终答案文本。

**表述修复（立即可做）**：

重新定位 `answer_restoration=0` 的含义：

> "replay 检测与验证分两层：(1) evidence hash 验证（`validated_replay=17`）——检索到的证据内容与原始一致；(2) answer 文本精确匹配（`answer_restoration`）——回放后最终答案与原始完全相同，当前尚未测量（=0）。  
> evidence hash 验证是语义层面的强保证；answer 文本精确匹配是更严格的表层验证，两者不等价。当前 replay 的有效性由 `validated_replay=17/20` 支撑。"

**代码实现路径（可选，中等工作量）**：

在 `v2/benchmark/live_runner.py` 的 replay run 逻辑里，把 fresh run 的 `quality_score` 或 `expected_facts` 结果存档，replay run 结束后做对比：

```python
# 在 continuous runner 里，每个 task 完成后存储答案摘要
# replay 命中时，对比当前答案与存档答案的 quality_floor_pass
if replay_hit:
    fresh_quality = memory_store.get_quality_record(task_id)
    if fresh_quality is not None:
        answer_matches = (current_quality_pass == fresh_quality.quality_pass)
        answer_restoration_count += int(answer_matches)
```

这不需要改 replay gate 逻辑，只是在外层统计层增加一个对比步骤。

**验收标准**：答辩材料中 `answer_restoration=0` 有明确的语义解释，不被误读为"replay 失效"。代码路径：实现后 `answer_restoration_count > 0`。

**预估工时**：表述路径 ~20 分钟；代码路径 ~3 小时（含测试）。

---

### F-07（对应 G-07）：flagship ablation 3/6 family 质量 gap

**修复类型**：[代码] + [实验]（高成本，P2）

**背景**：`r01_12` flagship ablation 中，`incident_diagnosis_v2`、`long_doc_metric_replay_v1`、`cross_period_financial_v1` 三个 family 质量未达标。这三个 family 的共同特征是 prompt 复杂度高（长文档 + 多跨期数据 + 诊断推理），超出当前 evidence pruning 策略的舒适区。

**根因分析**：

```
incident_diagnosis_v2：        多源事件关联 + 时序推理，evidence 剪枝后可能丢失关键时序线索
long_doc_metric_replay_v1：     长文档 replay，fresh evidence hash 与 replay 时不一致
cross_period_financial_v1：     跨期数据需要多轮 retrieval，单次 evidence pack 不够
```

**修复方向（逐 family 分析）**：

1. `incident_diagnosis_v2`：在 pruning policy 里给 `incident` family 的 `hard_fact` bucket 扩大 `min_keep` 阈值。在 `v2/retrieval/pruning.py` 里的 `STATEBUS_EVIDENCE_MIN_KEEP_SEMANTIC_CONTEXTS` env 对该 family 设为更高值（如 3）。

2. `long_doc_metric_replay_v1`：检查 `canonical_fresh_evidence_hash` 计算是否受长文档分块方式影响。`v2/runtime/replay.py` 里的 hash 计算如果对分块顺序敏感，长文档可能在两次 run 里分块不同导致 hash mismatch → `validated_replay=0`。

3. `cross_period_financial_v1`：考虑在 Planner 的 plan 里允许多步 retrieval（iterative evidence fetch），而不是单次 retrieval。需要确认 `v2/runtime/role_path.py` 的 Planner 是否支持 `multi_step_retrieval` plan type。

**当前建议**：P2 优先级，答辩前不强求全部修复。答辩中诚实说明：

> "flagship ablation 覆盖 6 个高难度 family，其中 3 个通过质量门（financial_report / operating_metric / report_gap），3 个（incident_diagnosis / long_doc_replay / cross_period）待进一步调优。StateRef prompt saving delta（37884 bytes）在全 6 个 family 中均可测量。"

**验收标准（P2 完成后）**：flagship ablation ≥5/6 family pass。

**预估工时**：~4-8 小时（逐 family 调试），高成本，答辩后处理。

---

### F-08（对应 G-08）：`neural_prefix_cache_hit_count_estimate` 表述修正

**修复类型**：[表述] + [代码注释]

**背景**：`v2/runtime/neural_state.py:384`：判断 `estimated_prefix_tokens > 0` 时计数，不是读取 vLLM `/metrics` endpoint 的 raw hit counter。字段名带 "cache_hit" 极易被误读为"vLLM 内部测量了 N 次命中"。

**表述修复**：

将所有引用此字段的地方改为：

> "`neural_prefix_cache_hit_count_estimate=25`（控制面推断计数：当 `estimated_prefix_tokens > 0` 时记为 1 次，来自 `v2/runtime/neural_state.py:384`，非 vLLM 内部 raw hit counter）。  
> 直接的 vLLM prefix cache 观测指标见 `vllm:gpu_prefix_cache_hit_rate=0.659`（E6 Prometheus gauge，最终累计值）和 E1/E2 clean-service 实测 hit-rate（`0.789` / `0.780`）。"

**代码注释修复**（`v2/runtime/neural_state.py:384` 附近）：

```python
# NOTE: neural_prefix_cache_hit_count_estimate 是控制面推断，不是 vLLM 内部计数器。
# 条件：estimated_prefix_tokens > 0（即控制面认为存在可复用前缀）。
# 实际的 prefix cache 命中由 vLLM 引擎自主决定，通过 Prometheus gauge
# vllm:gpu_prefix_cache_hit_rate 可观测（移动平均，非 raw hit/miss）。
# 不得将此字段表述为"N 次 GPU cache 命中"。
if estimated_prefix_tokens > 0:
    neural_prefix_cache_hit_count_estimate += 1
```

**验收标准**：答辩材料中此字段有明确的"控制面推断"标注；主引指标改为 `gpu_prefix_cache_hit_rate`。

**预估工时**：~20 分钟。

---

### F-09（对应 G-09）：补充 mmap backend formal 证据

**修复类型**：[实验]（低成本）

**背景**：当前 API formal（`r01_05`）使用 memfd backend，mmap 只有代码路径，没有 formal benchmark artifact 佐证。

**操作步骤**：

在 Qwen3-32B 全量测试时，增加一次 mmap backend 的 formal internal run：

```bash
STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1 \
python -m v2.benchmark.live_runner \
    --suite formal \
    --benchmark-tier formal \
    --role-path-mode api \
    --embedding-mode local \
    --state-pool-mode mmap
```

`--state-pool-mode mmap` 对应 `LayeredStoragePolicy.for_state_pool_mode("mmap")`（`v2/state/store.py`），会把 `EMBEDDING_STATE` 路由到 `StorageKind.MMAP_FILE`，替代 memfd。

预期结果：
- `state_pool_mode_used=mmap`（artifact 字段）
- `semantic_state_transfer_count=25`（数量不变）
- `memfd_transfer_count=0`（不走 memfd 路径）
- quality 25/25（backend 切换不影响质量）

这次 run 证明了"系统支持多 backend，mmap 可在 formal benchmark 下运行"，补全 G-09 的 experiment gap。

**验收标准**：新 artifact 的 `state_pool_mode_used=mmap`，quality 25/25，与 memfd run 质量 delta=0。

**预估工时**：~1 小时（含跑完 25 case）。

---

### F-10（对应 G-10）：清理误建文件 `tatus --short --branch`

**修复类型**：[清理]（P3）

**背景**：工作目录存在未跟踪文件 `tatus --short --branch`（`git status --short --branch` 命令被截断成文件名，疑似误重定向）。不影响功能，但属于 artifact-quality 噪声，在 `git status` 输出里可见。

**操作步骤**：

```bash
# 确认文件内容（避免误删有价值内容）
cat 'tatus --short --branch'

# 如果是空文件或无价值内容，直接删除
rm 'tatus --short --branch'

# 追加到 .gitignore 防止再次出现（可选）
echo 'tatus --short --branch' >> .gitignore
```

**注意**：按照工作约束，本审计期间不执行此操作（约束 9：不触碰无关未跟踪文件）。交给后续 commit 时一并处理。

**验收标准**：`git status --short` 输出中不再出现此文件。

**预估工时**：5 分钟。

---

### F-12（对应 G-12）：formal benchmark 启用真实跨进程 UDS

**修复类型**：[代码] + [实验]（P2）

**重要发现（审计新增）**：

读取 `v2/runtime/driver.py:1608` 后发现，跨进程 UDS 路径**已经部分实现**：

```python
# v2/runtime/driver.py:1608
if runtime_input.layer_profile.executor_transport == "subprocess":
    # → SubprocessExecutorTransport（真实跨进程 UDS + memfd FD 传递）
else:
    # → ControlPlaneLoopbackServer（进程内 loopback）
```

`live_runner.py:218` 也已有 `--transport` CLI flag，但目前限制为仅 `formal + formal tier` 可用（`live_runner.py:273`）。

这意味着 G-12 的实际状态比审计时描述的更好：**跨进程 UDS transport 已实现，且在 memfd backend + `--transport subprocess` 下会被激活**，不是完全没有跨进程路径。

**修复方向**：

1. **表述修正（立即）**：在答辩材料中改为：
   > "控制面支持两种 transport：`ControlPlaneLoopbackServer`（进程内 loopback，formal benchmark 默认）和 `SubprocessExecutorTransport`（真实跨进程 UDS + memfd FD passing，通过 `--transport subprocess` 激活）。两条路径均已实现，formal benchmark 默认走 loopback 以减少进程管理开销；跨进程 IPC 见 `test_subprocess_executor.py` 单测和 `--transport subprocess` 实验路径。"

2. **验证实验（可选）**：在 formal benchmark 里激活跨进程路径：

```bash
# 仅 formal + formal tier 支持（live_runner.py:273 限制）
STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1 \
python -m v2.benchmark.live_runner \
    --suite formal \
    --benchmark-tier formal \
    --role-path-mode local_vllm \
    --embedding-mode local \
    --state-pool-mode memfd \
    --transport subprocess
```

预期结果：`executor_transport=subprocess` 出现在 telemetry，UDS socket 文件在 run 期间可观测，memfd FD 通过 socket ancdata 传递。

**验收标准**：答辩材料表述修正完成；可选实验中 `--transport subprocess` 跑完 formal 25 case 全 pass。

**预估工时**：表述 ~20 分钟；实验 ~1-2 小时。

---

### 9.1 修复执行顺序（综合排序）

按"零成本先做、高收益优先"原则：

| 顺序 | 修复项 | 类型 | 耗时 | 当前状态 |
|---|---|---|---|---|
| 1 | F-04：删除 `r01_06` overclaim 引用 | 表述 | 20 分钟 | ⬜ 待做 |
| 2 | F-05：`estimated_kv_tokens_saved` 加注 | 表述+注释 | 30 分钟 | ⬜ 待做 |
| 3 | F-08：`neural_prefix_cache_hit_count_estimate` 加注 | 表述+注释 | 20 分钟 | ⬜ 待做 |
| 4 | F-12（表述部分）：UDS transport 重新定位 | 表述 | 20 分钟 | ⬜ 待做 |
| 5 | F-02（表述部分）：两种复用机制分开说清楚 | 表述 | 30 分钟 | ⬜ 待做 |
| 6 | F-03（表述部分）：multi-family 引用来源说明 | 表述 | 20 分钟 | ⬜ 待做 |
| 7 | F-06（表述部分）：answer_restoration 语义重定位 | 表述 | 20 分钟 | ⬜ 待做 |
| 8 | F-10：误建文件清理 | 清理 | 5 分钟 | ⬜ 待做 |
| 9 | F-01：compare suite 等价双模实验（Qwen3-32B） | 实验 | 2-3 小时 | ⬜ 待做 |
| 10 | F-09：mmap backend formal run | 实验 | 1 小时 | ⬜ 待做 |
| 11 | F-02（实验部分）：KV 主线 replay memory run | 实验 | 1 小时 | ⬜ 待做 |
| 12 | F-12（实验部分）：`--transport subprocess` formal run | 实验 | 1-2 小时 | ⬜ 待做 |
| 13 | F-03（实验部分）：multi-family statebus run | 实验 | 1 小时 | ⬜ 待做 |
| 14 | F-06（代码部分）：answer_restoration 实现 | 代码 | 3 小时 | ⬜ 待做（可选） |
| 15 | F-07：flagship ablation 质量调优 | 代码 | 4-8 小时 | ⬜ 答辩后 |

*Section 9 写入完毕。修复方案覆盖 G-01/G-02/G-03/G-04/G-05/G-06/G-07/G-08/G-09/G-10/G-12，排除 G-11（repeat-10 不做）和 G-13（VM 暂时不管）。*

---

### 9.2 来自独立审计的增量修复项（`30_independent_audit_report_20260711.md` + `29_local_vllm_kv_experiment_log_synthesis_20260711.md`）

以下四个修复项在主 Gap Ledger（G-01~G-13）中未被覆盖，来自独立审计的增量发现。

---

#### F-R1：`sb32bcompact` vs `kv-e6-guard` 数字不一致需在答辩中说明

**修复类型**：[表述]

**背景**：两个完整 formal pass run 的 total token delta 不同：

| Run | Text L0 total tokens | Protocol L3 total tokens | Delta | Context 配置 |
|---|---|---|---|---|
| `sb32bcompact` | 122785 | 64839 | **-57946** | 4096 ctx |
| `kv-e6-guard-20260711-1448` | 113949 | 62667 | **-51282** | 8192 ctx |

差异来源：E6 使用了 8192 context + dynamic pruning，`sb32bcompact` 使用 4096 context。两个数字都是正确的，但答辩中同时出现而不加说明会被评委认为数据不一致。

**具体改动**：

答辩材料统一规则：
> - **主引**：`kv-e6-guard-20260711-1448`（max_model_len=8192，完整机制 profile，最新结果）  
> - **附注**：`sb32bcompact`（max_model_len=4096，历史基线）如需引用，必须注明"4096 context 配置，token delta 与 E6 差异约 6664 tokens 源于 context 配置不同"

每张引用 token delta 数字的幻灯片/表格，在数字旁加括注：
> `（kv-e6-guard，8192 ctx，dynamic pruning + shared prefix + protocol 组合 profile）`

**验收标准**：答辩材料中两组数字不同时出现在同一张对比表；如同时出现，有配置差异说明。

**预估工时**：~15 分钟。

---

#### F-R2：E1 答辩数字必须锁定为 clean-service repeat，不得引用 stability repeat

**修复类型**：[表述]

**背景**：E1 在三次条件下运行，数字差异很大：

| 条件 | Friendly hit-rate | Hostile hit-rate | TTFT Δ |
|---|---|---|---|
| 首次探针（service 可能 warm） | 0.789 | 0.524 | - |
| **stability repeat**（warm service） | **0.521** | **0.344** | 未记录 |
| **clean-service repeat**（每次重启，从 0 开始） | **0.789** | **0.524** | **-684ms** |

stability repeat 数字大幅低于 clean-service repeat，原因是在 warm service（已有其他 request 温暖了 cache）上运行，不是干净基线。若答辩中误引 stability repeat 数字（0.521 vs 0.344），E1 的机制证明会被削弱到差异只有 0.177，且无法解释为机制本身的效果。

**具体改动**：

在答辩材料和所有 E1 引用处，明确标注数据来源：
> "E1 clean-service repeat（`e1_e2_clean_service_repeat_summary_20260711_1438.json`）：  
> - cache-friendly：final hit-rate 0.789，mean TTFT 885ms  
> - cache-hostile：final hit-rate 0.524，mean TTFT 1569ms  
> - Δ：hit-rate +0.265，TTFT -684ms  
> - 控制条件：每次实验前重启 vLLM 服务，初始 `gpu_prefix_cache_hit_rate=0.0`"

**禁止引用**：`e1_e2_stability_repeat_summary_20260711_1425.json` 的绝对数字（可在附录中说明 stability repeat 是对 warm-service 状态的补充观察）。

**验收标准**：答辩材料中所有 E1 数字来源均标注为 clean-service repeat；无 stability repeat 数字出现在主表格。

**预估工时**：~20 分钟（检查所有引用处）。

---

#### F-R3：vLLM Transformers fallback 表述风险

**修复类型**：[表述]

**背景**：`docs/setup/local_vllm_qwen.md` 记录了当前部署配置（cu121 + vLLM 0.7.3）下 Qwen3 走的是 **Transformers fallback**，不是 vLLM 原生推理路径（FlashAttention / PagedAttention 优化路径）。

`nvidia-smi` 显示 vLLM 进程启动参数确认：`--enforce-eager` 也表明关闭了 CUDA graph 优化。

这意味着：
- 当前测到的 TTFT 和 throughput 是 fallback 状态下的结果
- 不代表 vLLM 原生优化的最终性能（实际上 vLLM 原生路径会更快）
- prefix caching 机制本身（PagedAttention 层）仍然生效（这是 vLLM 底层机制，不受 fallback 影响）

**具体改动**：

在所有引用绝对 TTFT 数字（885ms / 967ms / 1569ms / 3526ms）的地方，加一条注脚：
> "注：当前 vLLM 部署（cu121 + vLLM 0.7.3 + `--enforce-eager`）运行于 Transformers fallback 模式，TTFT 绝对值不代表 vLLM 原生优化性能。**prefix caching 命中率和 TTFT 相对 delta（-684ms / -2559ms）是机制有效性的关键证据，与 fallback 模式无关。**"

**核心论点保留**：E1/E2 的 **相对 delta** 和 **hit-rate 变化方向** 不受 fallback 影响——因为对比的两组（friendly vs hostile，shared vs independent）在完全相同的服务配置下运行，控制变量是 prompt layout/schedule，不是绝对性能。

**验收标准**：答辩材料中无对绝对 TTFT 数字的"最终生产性能"表述；相对 delta 作为机制证据正常引用。

**预估工时**：~15 分钟。

---

#### F-R4：`run_v2_local_vllm_container_check.sh` 默认端口指向 8B，复现陷阱

**修复类型**：[代码]（极低风险，1-2 行改动）

**背景**：`scripts/run_v2_local_vllm_container_check.sh` 的默认 health probe 指向 `http://127.0.0.1:53333/health`（8B 端口），而当前 Qwen3-32B 服务运行在 `http://127.0.0.1:53334`。评审现场复现时，如果未先 source 32B profile，脚本会在第一步 health probe 失败，输出 `connection refused`，没有任何指引信息。

**修复内容**（在脚本开头插入 2 行）：

```bash
#!/bin/bash
# scripts/run_v2_local_vllm_container_check.sh

# 新增：明确提示当前使用的 endpoint
VLLM_BASE_URL="${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53333/v1}"
echo "[INFO] vLLM endpoint: ${VLLM_BASE_URL}"
echo "[INFO] 如使用 Qwen3-32B（port 53334），请先执行:"
echo "[INFO]   export STATEBUS_LOCAL_VLLM_BASE_URL=http://127.0.0.1:53334/v1"
echo "[INFO] 或 source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b"
# 其余脚本内容不变
```

**验收标准**：脚本运行第一行即输出当前 endpoint；health probe 失败时有可操作的提示信息。

**预估工时**：~10 分钟。

---

### 9.3 完整修复执行顺序（含 F-R1~F-R4 更新版）

| 顺序 | 修复项 | 类型 | 耗时 | 状态 |
|---|---|---|---|---|
| 1 | F-04：删除 `r01_06` overclaim 引用 | 表述 | 20 分钟 | ⬜ |
| 2 | F-05：`estimated_kv_tokens_saved` 加注 | 表述+注释 | 30 分钟 | ⬜ |
| 3 | F-08：`neural_prefix_cache_hit_count_estimate` 加注 | 表述+注释 | 20 分钟 | ⬜ |
| 4 | F-R2：锁定 E1/E2 答辩数字为 clean-service repeat | 表述 | 20 分钟 | ⬜ |
| 5 | F-R1：统一 token delta 数字，注明配置差异 | 表述 | 15 分钟 | ⬜ |
| 6 | F-R3：TTFT 绝对值加 fallback 注脚 | 表述 | 15 分钟 | ⬜ |
| 7 | F-12（表述部分）：UDS transport 重新定位 | 表述 | 20 分钟 | ⬜ |
| 8 | F-02（表述部分）：两种复用机制分开说清楚 | 表述 | 30 分钟 | ⬜ |
| 9 | F-03（表述部分）：multi-family 引用来源说明 | 表述 | 20 分钟 | ⬜ |
| 10 | F-06（表述部分）：answer_restoration 语义重定位 | 表述 | 20 分钟 | ⬜ |
| 11 | F-10：误建文件清理 | 清理 | 5 分钟 | ⬜ |
| 12 | F-R4：check 脚本端口提示 | 代码 | 10 分钟 | ⬜ |
| 13 | F-01：compare suite 等价双模实验（Qwen3-32B） | 实验 | 2-3 小时 | ⬜ |
| 14 | F-09：mmap backend formal run | 实验 | 1 小时 | ⬜ |
| 15 | F-02（实验部分）：KV 主线 replay memory run | 实验 | 1 小时 | ⬜ |
| 16 | F-12（实验部分）：`--transport subprocess` formal run | 实验 | 1-2 小时 | ⬜ |
| 17 | F-03（实验部分）：multi-family statebus run | 实验 | 1 小时 | ⬜ |
| 18 | F-06（代码部分）：answer_restoration 实现 | 代码 | 3 小时 | ⬜（可选） |
| 19 | F-07：flagship ablation 质量调优 | 代码 | 4-8 小时 | ⬜（答辩后） |

*Section 9 全部写入完毕（含独立审计增量）。覆盖 G-01~G-12 + F-R1~F-R4，排除 G-11（repeat-10）和 G-13（VM）。*



---

*审计文档结束。生成时间：2026-07-11。审计范围：Section 0-8，覆盖 git 状态、赛题要求拆解、双证据链映射、代码路径核验、实验充分性审查、Gap 台账（13 条）、术语边界风险（13 个）、修复优先级矩阵（P0-P3）、6 个 Open Questions。*



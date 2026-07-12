# StateBus 独立审计报告

**日期**: 2026-07-11  
**分支**: `feat/local-vllm-kv-prep`  
**审计范围**: 赛题要求 × 当前规划 × KV/local vLLM 实验链 × 代码/artifact 一致性  
**审计方法**: 仅读文档与 artifact，不重跑实验，不重启 vLLM，不动 GPU 进程

---

## 第一部分：Findings — 赛题覆盖分析（问题 1）

### 1.1 赛题满分项（25+20+20+20+15 = 100 分）对照

| 赛题评分维度 | 满分 | 当前证据状态 | 最强证据位置 | 薄弱点 |
|---|---:|---|---|---|
| 通信效率（token 节省） | 25 | **基本充分**：Protocol L3 vs Text L0 prompt tokens -51606（`sb32bcompact`），-45652（`kv-e6-guard`），API 模式 prompt bytes 30661 vs 43213 | `artifacts/local_vllm_kv_audit_20260711.json`、`local_api_20260707_163354` | v2 formal text-mode companion stage 仍缺；目前 text vs protocol 对比基于 internal attribution ladder，不是 same-task external superior |
| 状态传递创新（设计新颖性） | 20 | **中等**：实现了 `EMBEDDING_STATE + memfd/shared_memory + hydration accounting`；E1/E2 证明 schedule/layout 能影响 vLLM engine-local prefix reuse | `21_local_vllm_kv_implementation_review_20260711.md` §3 | 没有 KV tensor 传递、hidden-state 传递；能展示的是"用 prompt layout 诱导推理引擎复用"，新颖性不如真正的 KV handoff |
| 记忆复用效果（跨任务复用准确率） | 20 | **中等**：API 模式有 `reuse_gain=0.17`、`memory_hit_rate=0.83`、`skipped_step_count=9`；local vLLM 模式 `reuse_gain_delta_l2_to_l3=0.0`（E6 artifact 确认） | `current_feature_scope.md` §2.4、`e6_formal_guard_mechanism_excerpt_20260711_1448.json` | local vLLM 模式下 `reuse_gain=0`；answer restoration 已归零；展示的记忆复用收益是 API 模式下的历史基线，local vLLM 路径未补充记忆复用正式实验 |
| 系统完整性（四角色协作稳定性） | 20 | **充分**：`local_api_20260707_163354` 13 stages exit 0，四角色 API 各 25 call，25/25 quality pass；`sb32bcompact` 和 `kv-e6-guard` 均 25/25 | `00_executive_summary.md`、`local_vllm_kv_audit_20260711.json` | Flagship stress 3/6（`local_api_20260707_163354`）；openEuler VM 验证仍未执行 |
| 实验验证（对比数据说服力） | 15 | **中等偏强**：E1/E2/E3/E6 实验链闭合，artifact 齐全，clean-service repeat 已做；API 模式 v1 有 repeat-10 稳定基线 | `e1_e2_clean_service_repeat_summary_20260711_1438.json`、`e6_formal_guard_summary_20260711_1448.json` | E3 只是 retrieval-level 确定性探针，不是 end-to-end formal 质量证明；E1/E2 sample size 小（10/5 个请求）；没有误差线或多次 repeat 的统计分布 |

### 1.2 哪些评分项还最薄

按薄弱程度排序：

1. **通信效率（25分）中的 v2 formal text vs protocol 对比缺口**  
   当前 local vLLM 的 token 节省只有 internal attribution ladder（L0 vs L3），没有 same-task 的 API text-mode companion stage。`code_truth_vs_experiment_issue_matrix_zh.md` §1.1 明确写了"通信效率（25分）仍缺 v2 formal same-task text vs protocol token/byte delta"。

2. **记忆复用效果（20分）中 local vLLM 路径的复用收益为零**  
   `e6_formal_guard_mechanism_excerpt_20260711_1448.json` 中 `reuse_gain_delta_l2_to_l3=0.0`；API 模式的 `reuse_gain=0.17` 是历史基线，local vLLM 正式运行没有补充记忆复用证据。

3. **状态传递创新（20分）中"创新性"的答辩脆弱点**  
   当前最强的非文本中间态是 `EMBEDDING_STATE + hydration accounting`，属于 input-level 机制，不是真正的 model-internal state handoff。E1/E2 展示了"通过 prompt layout 间接影响推理引擎缓存行为"——这是真实的工程价值，但如果评委追问"这和普通 KV cache 有什么区别"，需要有清晰的答辩逻辑。

4. **实验验证（15分）中 E1/E2 样本量和统计严谨性**  
   E1 友好/对立各 10 个请求，E2 共享/独立各 5 个请求。这个量级对于机制验证基本够用，但用于正式提交的对比图表时，缺少置信区间或 Bootstrap 误差线。

---

## 第二部分：Findings — KV 机制表述审计（问题 2）

### 2.1 当前机制已讲清楚的部分

| 机制 | 实现位置 | 宣传边界是否清晰 |
|---|---|---|
| Engine-Local Prefix Reuse（调度控制） | `v2/benchmark/kv_prefix_schedule.py`；`NeuralPrefixIdentity` claim boundary 字段 | **清晰**：artifact 中 claim_boundary 字段每次都写了 `corpus_prefix_schedule_control_plane_only_no_kv_tensor_export` |
| Shared Evidence Prefix Layout | `v2/runtime/role_path.py`，`STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix` | **清晰**：E2 artifact claim_boundary = `shared_evidence_prefix_layout_probe_only_no_kv_tensor_export` |
| Input-level Dynamic Pruning | `v2/retrieval/pruning.py`；`EvidencePruningHint`，`claim_boundary` 字段 = `input_level_evidence_pruning_only_no_model_internal_kv_tensor_pruning` | **清晰** |
| Engine-local prefix registry | `v2/runtime/neural_state.py`，`EngineLocalPrefixRegistry` | **清晰**：注释明确为控制面注册，不持有 KV tensor |

### 2.2 可能被评委质疑的表述风险点

**风险 A：E6 telemetry 字段 `neural_prefix_cache_hit_count_estimate=25` 容易被误读**

`e6_formal_guard_mechanism_excerpt_20260711_1448.json` 中的 `neural_prefix_reuse_estimate_count=25`、`neural_prefix_cache_hit_count_estimate=25` 是控制面估算结果，不是直接从 vLLM counters 读取的 raw hit count。  
- **风险**：答辩中如果直接说"25 个 case 都命中了 prefix cache"，评委会问"你怎么知道命中了"，而正确答案是"我们估算每个 case 都有 shared prefix bytes"。  
- **建议**：答辩时明确区分"**我们构造的 prompt 具备 prefix 对齐条件**"（可测量）vs "**vLLM 确实命中了 prefix cache**"（只有 gauge hit-rate 间接证明）。

**风险 B：`evidence_pruning_estimated_kv_tokens_saved=9644` 是估算值**

该字段基于 `kv_bytes_per_token=256` 的线性估算，不是实际测量到的 CUDA kernel 层面节省。  
- **风险**：如果用这个数字作为"减少了多少推理计算"的论据，评委可以质疑估算模型的合理性。  
- **建议**：只说"减少了 input evidence tokens，从而降低了推理引擎需要 prefill 的序列长度"，不要直接说"节省了 9644 个 KV 计算"。

**风险 C：E1 的 hit-rate 数值在不同 repeat 之间有漂移**

- E1 首次探针（`e1_kv_schedule_ablation_summary_20260711_134159.json`）：friendly 0.789，hostile 0.524  
- E1 stability repeat（`e1_e2_stability_repeat_summary_20260711_1425.json`）：friendly 0.521，hostile 0.344  
- E1 clean-service repeat（`e1_e2_clean_service_repeat_summary_20260711_1438.json`）：friendly 0.789，hostile 0.524  
- **风险**：stability repeat 的绝对值大幅下降，这是因为 probe 在 service warm-up 状态下运行，而不是从冷 cache 开始。评委可能追问"你的实验控制条件是什么"。  
- **建议**：答辩表格只用 clean-service repeat 的数值，明确注明"每次实验前重启服务使 `gpu_prefix_cache_hit_rate` 从 0 开始"。

**风险 D：vLLM 在 cu121 + vLLM 0.7.3 下走 Transformers fallback**

`docs/setup/local_vllm_qwen.md` 明确说明当前 cu121 + vLLM 0.7.3 下 Qwen3 走的是 Transformers fallback，不是 vLLM 原生推理路径。这意味着当前测到的 prefix cache hit-rate 和 TTFT 是 Transformers fallback 下的表现，不能等同于 vLLM 原生优化的最终性能。  
- **建议**：答辩时不要声称"这是 vLLM 的最终生产性能"，只说"在当前配置下实测到的 engine-local prefix reuse 行为"。

### 2.3 已经明确不允许宣称的（已有文档保护）

以下 claim 在所有 artifact 的 `claim_boundary` 字段和多份审计文档中均已明确禁止：

- KV tensor export / transfer
- Hidden-state transfer  
- Cross-engine KV reuse  
- 2-GPU 成功  
- openEuler VM 已验证

这部分文档保护做得很好，不构成当前主要风险。

---

## 第三部分：Findings — 实验链充分性（问题 3）

### 3.1 E1/E2/E3/E6 的覆盖度评估

| 实验 | 目标 | 样本量 | 重复性 | 充分性判断 | 主要 artifact |
|---|---|---|---|---|---|
| E0 | 服务可观测性恢复 | 1次健康检查 | N/A | **充分**：服务可观测性不需要统计重复 | `local_vllm_kv_audit_20260711.json` |
| E1（schedule ablation） | 证明 cache-friendly 调度收益 | 各 10 请求 | 3次（首次探针 + stability + clean-service） | **基本充分**：方向在 3 次都重现；clean-service repeat 从冷 cache 起步，最干净 | `e1_e2_clean_service_repeat_summary_20260711_1438.json` |
| E2（prefix alignment） | 证明 shared prefix layout 收益 | 各 5 请求 | 3次 | **基本充分**：TTFT delta 非常显著（~2.5s），方向稳定；hit-rate 绝对值的干净度依赖服务重启 | `e2_prefix_alignment_ablation_summary_20260711_1359.json` |
| E3（dynamic pruning） | 证明 input-level pruning 机制 | 1个合成 task | 1次（确定性探针） | **部分充分**：证明了 pruning 机制本身和 hard-fact preservation，不是 end-to-end formal 质量证明 | `e3_dynamic_pruning_ablation_20260711.json` |
| E6（formal quality guard） | 证明组合机制不破坏 25-case 质量底线 | 25 cases / L0-L3 | 1次完整 formal | **充分**：L0-L3 全 25/25，质量 delta=0，L3 telemetry 详尽 | `e6_formal_guard_summary_20260711_1448.json` |

### 3.2 还必须补的实验（必须补）

**不需要补新实验**。已有证据链对于"Engine-Local Prefix Reuse"这个 claim 来说是闭环的：
- E1/E2 证明机制收益（TTFT + hit-rate），且有 clean-service repeat 保证干净度
- E3 证明 pruning 机制本身
- E6 证明组合 profile 的 formal 质量保障

### 3.3 只建议补的（图表/复述/误差线）

1. **E1/E2 TTFT 分布图**：把 10/5 个请求的 TTFT 值画成 box plot 或 violin plot，替代当前只有 mean 的展示。这不需要新实验，只需要从 artifact 中提取 per-request TTFT 值。

2. **E6 telemetry 对比表格**：把 `evidence_pruning_drop_count=25`、`neural_prefix_shared_prefix_bytes=4359`、`state_pool_shared_memory_mode_count=25`、`semantic_state_transfer_count=25` 整理成一张"L3 mechanism telemetry summary"放进汇报材料。数据已在 artifact 中，只需格式化。

3. **E1/E2/E6 统一数据表**：把三个实验的"控制变量—因变量"整合成一个 3 行的对比表，用于答辩 PPT 的单张总结幻灯片。

4. **`sb32bcompact` vs `kv-e6-guard` 对比说明**：两个 formal pass run 的 token delta 有轻微差异（-57946 vs -51282），需要一句话解释（E6 使用了 8192 context + dynamic pruning，而 sb32bcompact 使用 4096 context），避免评委认为数据不一致。

---

## 第四部分：Evidence — 代码/脚本层 bug、复现风险、配置风险（问题 4）

### 4.1 已确认的代码风险

**风险 1：`runtime/llm.py` 的 400 retry 匹配范围过宽**

`21_local_vllm_kv_implementation_review_20260711.md` §3 明确指出：
> "The retry path matches status/text broadly. It should stay documented as a local vLLM hardening behavior, not as proof that all providers share the same semantics."

- **位置**：`runtime/llm.py`，`_context_window_adjusted_request` 的 400 retry 逻辑
- **风险**：如果把同一个 runtime 切回 API 模式，这个 retry 可能会掩盖合法的 API 参数错误，导致静默重试而不是立即报错
- **最小 patch 建议**：在 retry 条件里增加一个 `local_vllm_mode` guard，只在 `role_path_mode == "local_vllm"` 时激活这段 retry 路径
- **影响面**：`runtime/llm.py` 约 1 处 if 条件，风险低

**风险 2：`_estimate_chat_prompt_tokens` 是字符级粗糙估算**

- **位置**：`runtime/llm.py`
- **风险**：对于中文 + 代码混合 prompt，字符数与 token 数比率差异很大。当 prompt 逼近 context 上限时，粗估可能允许实际超出限制的请求发出，导致 400 错误
- **最小 patch 建议**：在 local vLLM 路径中，用 `tiktoken` 或 `transformers` tokenizer 做精确估算（Qwen3 tokenizer 可以通过 `AutoTokenizer.from_pretrained("qwen3-32b")` 加载）；或者增大 safety margin 从 64 token 到 256 token
- **影响面**：`runtime/llm.py`，不影响 benchmark 正确性，只影响极端情况下的稳定性

**风险 3：E6 时 `scripts/run_v2_local_vllm_container_check.sh` 默认指向 8B 端口**

`21_local_vllm_kv_implementation_review_20260711.md` §5 记录：
> "Default `scripts/run_v2_local_vllm_container_check.sh` Failed at host health probe for default 8B URL `http://127.0.0.1:53333/health`; connection refused."

- **位置**：`scripts/run_v2_local_vllm_container_check.sh`，默认服务 URL 是 8B 端口
- **风险**：如果测试者忘记先 source 32B profile，脚本会 fail-fast 在错误的端口，不会给出清晰提示
- **最小 patch 建议**：在脚本开头增加一行注释或 `echo` 提示当前使用的 endpoint，并在 health probe 失败时输出"请检查是否已 source 32B profile"

**风险 4：`sb32bcompact` 配置中 max_context_tokens=4096，E6 使用 8192，两套配置未统一**

`local_vllm_kv_audit_20260711.json` 显示 `sb32bcompact` 的 context 上限是 4096，而 E6 (`kv-e6-guard`) 使用 8192。  
- **风险**：两个 formal pass 的 token 统计不可直接对比（E6 有更大的证据空间，所以 total tokens 略低）  
- **当前文档保护**：`21_local_vllm_kv_implementation_review_20260711.md` §7 item 11 已经记录这个差异  
- **不需要改代码**，但答辩材料必须区分引用

### 4.2 Artifact 不一致性

**不一致点 1：`e6_formal_guard_mechanism_excerpt` 与 `e6_formal_guard_summary` 中 protocol_vs_text_prompt_token_delta 的差异**

- `e6_formal_guard_summary_20260711_1448.json`：`protocol_vs_text_prompt_token_delta = -45652`
- `e6_formal_guard_mechanism_excerpt_20260711_1448.json`：`protocol_vs_text_prompt_token_delta = -45652`（一致 ✓）
- `29_local_vllm_kv_experiment_log_synthesis_20260711.md` 的 Evidence Map 中写 "E6 L3 tokens 62667; L0 tokens 113949; quality delta 0"，与 artifact 一致 ✓

**不一致点 2：两个 formal pass 的 total token delta 数字**

| Run | Text L0 total tokens | Protocol L3 total tokens | Delta |
|---|---|---|---|
| `sb32bcompact` | 122785 | 64839 | -57946 |
| `kv-e6-guard-20260711-1448` | 113949 | 62667 | -51282 |

这个差异是**真实的、预期内的**（不同 context 配置），不是 artifact 错误，但答辩材料中必须说明。  
- **风险**：如果两个数字出现在同一张 PPT 幻灯片而不加说明，评委会认为数据有误。

**不一致点 3：`e1_e2_stability_repeat` 中 E2 的 independent 组 hit-rate 非零（0.431）**

在 stability repeat 中，E2 independent 组的 final GPU prefix cache hit rate 是 0.431，而 clean-service repeat 中是 0.0。  
- **原因**：stability repeat 在同一 service lifetime 内运行，先前 E1 的请求已经温暖了 prefix cache  
- **风险**：如果只引用 stability repeat 的数字，E2 的机制证明会被削弱（hit-rate delta 变成 0.05 而不是 0.78）  
- **建议**：答辩只引用 clean-service repeat 的 E2 数字

---

## 第五部分：Risks — 综合风险汇总

### 5.1 答辩/评审风险（最高优先）

| 风险 | 严重程度 | 当前缓解状态 | 建议 |
|---|---|---|---|
| 两个 formal pass（`sb32bcompact` vs `kv-e6-guard`）用了不同 context 配置，数字不同 | 高 | 已在文档中记录，答辩材料未统一 | 答辩材料只用 E6 (`kv-e6-guard`) 的数字作为"带完整机制 profile 的最新结果"，`sb32bcompact` 作为"历史基线"附注 |
| E2 在 stability repeat 中 hit-rate delta 很小（0.05），容易被评委抓住 | 高 | clean-service repeat 修正了这个问题 | 答辩表格只用 clean-service repeat；必须注明"每次实验前服务已重启，初始 hit-rate 从 0 开始" |
| `neural_prefix_cache_hit_count_estimate=25` 被误读为直接观测 | 中 | artifact claim_boundary 字段已写清楚 | 口头补充"这是控制面估算，基于我们构造的 shared prefix bytes；vLLM 实际 hit-rate 在 E6 run 结束时为 0.659" |
| v2 formal text vs protocol companion stage 仍缺 | 中 | `code_truth_vs_experiment_issue_matrix_zh.md` 已记录 | 答辩时把这个说成"当前 local vLLM 路径的 L0 vs L3 是内部归因梯队，full text-mode companion 是后续工作" |
| local vLLM 路径 reuse_gain=0，无法展示记忆复用 | 中 | API 模式有 reuse_gain=0.17 可用 | 答辩时明确区分两条证据链：① local vLLM 路径证明 Engine-Local Prefix Reuse；② API 路径证明共享记忆 reuse_gain |

### 5.2 复现风险

| 风险 | 来源 | 影响 |
|---|---|---|
| vLLM 8B 服务未运行，默认 check 脚本会 fail | `scripts/run_v2_local_vllm_container_check.sh` 默认端口 53333 | 评审现场复现时可能会卡在第一步 |
| cu121 + vLLM 0.7.3 下 Qwen3 走 Transformers fallback，性能不代表 vLLM 原生 | `docs/setup/local_vllm_qwen.md` | 不影响机制验证，但影响速度宣传 |
| GPU blocks 被强制 override 为 573，复现时 GPU 内存状态可能不同 | `num_gpu_blocks_override=573` 在 E1/E2/E6 的 service profile 中均硬编码 | 如果评审现场 GPU 已用 0 blocks，override 会失败 |
| E2 的 independent 组在 8192 context 下会超出限制（已有 log 证明） | `vllm_qwen3_32b_gpu0_53334_8192_e2_independent_blocks573_20260711_1400.log` 中有 11270 > 8192 报错 | 如果评审现场重跑 E2 independent，可能再次触发 context overflow；需要确认 dynamic pruning 和 context cap 都开启 |

### 5.3 代码层技术债

| 风险 | 文件 | 严重程度 |
|---|---|---|
| 400 retry 掩盖 API 参数错误 | `runtime/llm.py` | 低（只影响极端情况下的调试体验） |
| 字符级 token 估算精度不足 | `runtime/llm.py`，`_estimate_chat_prompt_tokens` | 低（已有 64-token safety margin，目前没有触发失败的记录） |
| E3 的 pruning 参数（`kv_bytes_per_token=256`）硬编码，不适应不同量化精度 | `v2/retrieval/pruning.py` | 低（当前是 16-bit fp16，256 bytes/token 合理；但 8-bit 量化下应改为 128） |
| `STATEBUS_EVIDENCE_*` 环境变量在 container 中需要通过 wrapper 显式传入，否则静默使用默认值 | `scripts/run_v2_local_vllm_container_check.sh` | 低（wrapper 在 E6 之后已修复，`21_local_vllm_kv_implementation_review_20260711.md` §7 item 10 已记录） |

---

## 第六部分：Recommended Next Steps — 优先级最高的 3-5 个动作（问题 5）

**时间有限的情况下，按优先级排序：**

### 优先级 1（必做）：统一答辩材料中的数字引用

- 使用 `kv-e6-guard-20260711-1448` 作为**唯一当前正式结果**
- `sb32bcompact` 只作为"历史基线"在附录中出现
- 在每张对比表旁注明：
  - 协议对比是 internal attribution ladder（L0 text vs L3 protocol+KV+pruning）
  - 不是 same-task external superior
  - 服务配置：GPU0, max_model_len=8192, prefix_caching=True, 573 blocks

**根据**：`local_vllm_kv_experiment_log_summary_20260711.json` §judgment 中已明确 `formal_pass_run_roots = [kv-e6-guard-20260711-1448, sb32bcompact]`，但两者 context 配置不同。

---

### 优先级 2（必做）：把 E1/E2 答辩表格锁定为 clean-service repeat 数字

从 `e1_e2_clean_service_repeat_summary_20260711_1438.json` 提取以下数字，写入答辩表格：

| 维度 | Friendly vs Hostile (E1) | Shared vs Independent (E2) |
|---|---|---|
| Final GPU prefix hit-rate | 0.789 vs 0.524（Δ+0.265） | 0.780 vs 0.0（Δ+0.780） |
| Mean TTFT (ms) | 885 vs 1569（Δ-684ms） | 967 vs 3526（Δ-2559ms） |
| 控制条件 | 服务重启，初始 hit-rate=0 | 服务重启，初始 hit-rate=0 |

注明：每个实验组前均重启 vLLM 服务，确保初始 GPU prefix cache hit-rate=0。

---

### 优先级 3（必做）：为"记忆复用"章节区分两条证据链

答辩报告和实验报告必须明确写：

- **API 路径**（`local_api_20260707_163354`）：`reuse_gain=0.17`，`memory_hit_rate=0.83`，`skipped_step_count=9`，证明跨任务记忆复用；
- **local vLLM 路径**（`kv-e6-guard`）：`reuse_gain_delta_l2_to_l3=0.0`，当前未开启 replay memory；KV 相关收益来自 **Engine-Local Prefix Reuse**，是推理引擎层面的前缀缓存复用，不是应用层的任务记忆复用。

否则评委会认为两条路径的记忆复用数据矛盾。

---

### 优先级 4（建议做）：补一页 E6 L3 telemetry 展示

从 `e6_formal_guard_mechanism_excerpt_20260711_1448.json` 的 `l3_telemetry_excerpt` 和 `final_vllm_metrics_excerpt` 提取，做成一张"机制生效的可观测证据"表：

| 指标 | 值 | 含义 |
|---|---|---|
| `evidence_pruning_drop_count` | 25 | 25 个 case 全部触发了 evidence pruning |
| `evidence_pruning_estimated_kv_tokens_saved` | 9644 | 估算减少的 prefill tokens（估算值） |
| `pruning_gain_bytes` | 77134 | 输入级 evidence 字节减少量 |
| `neural_prefix_shared_prefix_bytes` | 4359 | 构造的 shared prefix 字节 |
| `state_pool_shared_memory_mode_count` | 25 | 25 个 case 均使用了 shared_memory 状态池 |
| `semantic_state_transfer_count` | 25 | 25 次语义状态传递成功 |
| `gpu_prefix_cache_hit_rate`（vLLM 最终值） | 0.659 | vLLM 实测的 GPU prefix cache 命中率 |

这是"黑盒机制"有可观测支撑的最强证明。

---

### 优先级 5（建议做，有时间再做）：补 `scripts/run_v2_local_vllm_container_check.sh` 的端口提示

在脚本开头增加：
```bash
echo "[INFO] 当前 vLLM endpoint: ${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53333/v1}"
echo "[INFO] 如需使用 32B 服务，请先运行: source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b"
```

这是 1-2 行改动，能大幅降低评审现场复现时的迷惑程度。

---

## 第七部分：Claim Boundary — 目前够了的 claim vs 需要补救的 claim（问题 6）

### 7.1 目前够了（已有充分证据）的 claim

以下 claim 当前有直接、可机器验证的 artifact 支持：

1. **local vLLM 路径 formal 质量底线**  
   `sb32bcompact` 和 `kv-e6-guard-20260711-1448` 均 25/25，L0-L3 全部通过。  
   → 够用于提交的"系统完整性"和"实验验证"评分项。

2. **Protocol 控制面 token 显著低于 text 模式**  
   E6：prompt tokens -45652（-46.0%），control bytes -31256（-72.8%）。  
   → 够用于"通信效率"评分项的主数据。

3. **cache-friendly scheduling 提升 vLLM engine-local prefix reuse**  
   E1 clean-service：hit-rate 0.789 vs 0.524，TTFT -684ms。  
   → 够用于答辩时的"系统优化机制"展示。

4. **shared evidence prefix layout 显著提升 prefix cache hit-rate 和 TTFT**  
   E2 clean-service：hit-rate 0.780 vs 0.0，TTFT -2559ms。  
   → 这是所有 KV 相关 claim 中**最强的机制证据**，应该在答辩中重点展示。

5. **input-level dynamic pruning 在保留关键事实前提下减少输入证据量**  
   E3：selected evidence bytes 333 → 112，hard fact `fact-revenue-1` 保留。  
   → 够用于"状态传递机制"的设计亮点展示。

6. **API 路径跨任务记忆复用有实测收益**  
   `local_api_20260707_163354`：`reuse_gain=0.17`，`skipped_step_count=9`，repeat-10 稳定。  
   → 够用于"记忆复用效果"评分项。

---

### 7.2 不够、需要最小补救路径的 claim

**缺口 1：v2 same-task text vs protocol formal compare（通信效率 25 分的硬核证据）**

- **问题**：当前 local vLLM 路径的 L0 vs L3 对比是 internal attribution ladder（text L0 = 不用协议的基准，protocol L3 = 使用所有机制的最优），不是完全等价的同一任务两种模式对比。
- **最小补救**：在答辩中明确说明这是"internal attribution ladder，衡量机制叠加的边际贡献"，并引用 API 路径的 `v2-targeted-json-retry-compare-20260707_192452`（8-case formal financial compare，protocol prompt bytes 30661 vs external 43213，prompt tokens 9645 vs 12678）作为补充。
- **不需要重新跑实验**，只需要正确引用已有的 API compare 数据。

**缺口 2：local vLLM 路径的记忆复用证据**

- **问题**：`kv-e6-guard` 中 `reuse_gain_delta_l2_to_l3=0.0`，local vLLM 模式没有展示出应用层记忆复用。
- **最小补救**：答辩中把两条路径的收益点分开展示，不混淆：① API 路径展示任务级记忆复用；② local vLLM 路径展示推理引擎级 prefix reuse。这不是弱点，而是"两层复用"的架构展示。

**缺口 3：openEuler VM 未验证**

- **问题**：赛题交付要求明确说"代码需在 openEuler 24.03-LTS-SP3 上正常编译、运行和测试"。
- **当前状态**：Docker container（`statebus-dev-qcrs`）已验证，但 openEuler VM 本身没有运行记录。
- **最小补救**：至少跑一次 `python -m pytest -q tests/v2` 和 `python -m runtime.smoke` 在 openEuler VM 上，并保存输出。这是**提交前必须做的**，否则交付合规性存疑。

---

## 第八部分：总结与结论（按 7 个问题直接作答）

### Q1：是否已足够支撑提交/答辩？

**结论：主体已够，有两处补救必须完成。**

当前证据链可以支持提交，但在完整提交前必须完成：  
① 区分两条证据链的答辩材料整理（不需要新实验）  
② openEuler VM 的一次基础 smoke 验证

### Q2：KV 机制是否讲清楚了？

**结论：代码和 artifact 层讲得很清楚，答辩口径需要补充两个区分。**

需要在答辩中明确补充：  
- "命中了 prefix cache"= 构造了 shared prefix 条件 + vLLM gauge hit-rate 升高，不是直接观测到 KV tensor 命中  
- E2 TTFT 结果只在 clean-service 条件下成立，不是一般性保证

### Q3：实验链是否充分？

**结论：E1/E2/E3/E6 链已闭环，只建议补图表误差线，不需要补新实验。**

### Q4：代码/脚本层有没有明显 bug？

**结论：没有导致 benchmark 结果错误的 bug，有 3 个低优先级工程风险。**

风险均为"边缘情况下的稳定性"和"答辩现场的操作体验"，不影响已有实验结果的有效性。

### Q5：优先级最高的 3-5 个动作？

1. 统一答辩数字到 `kv-e6-guard` 并注明配置差异
2. 锁定 E1/E2 表格为 clean-service repeat 数字
3. 区分 API 路径记忆复用 vs local vLLM 路径 prefix reuse
4. 补 E6 L3 telemetry 展示表
5. openEuler VM smoke 验证

### Q6：目前够了 vs 不够的 claim？

- **够了**：formal 质量（25/25），protocol token 节省（-46%），E1/E2 机制收益（TTFT -684ms/-2559ms），API 记忆复用（reuse_gain=0.17）
- **不够，需补救**：v2 formal text compare 需要明确说明是 internal ladder；openEuler 验证缺失需要在提交前补上

### Q7：报告结构

已按 Findings / Evidence / Risks / Recommended Next Steps / Claim Boundary 结构写入本文档各部分。

---

*审计结束时间：2026-07-11*  
*文件路径：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/30_independent_audit_report_20260711.md`*


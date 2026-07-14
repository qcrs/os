 你现在要对 StateBus 项目做一轮“全面实现与实验问题审计”。这不是答辩 claim 包装，也不是只复核上一轮 AI 提到的问题，而是从赛题
  要求、系统设计、代码实现、实验 artifact、复现风险五个层面系统拆解：当前还有哪些漏洞、哪些实验不足、哪些实现风险、哪些问题值
  得修，哪些只是文档澄清。

  仓库路径：

  /home/qcrs/statebus/project

  重要：你的输出主要写入文档，不要只在聊天窗口里总结。请分批写入以下文档：

  docs/improvement/20_v2_comprehensive_truth_audit_20260706/31_comprehensive_gap_audit_20260711.md

  如果内容很长，可以分批追加写入同一个文档。不要等最后才写。每批完成后简短说明已写入哪一节即可。

  ---

  ## 工作约束

  1. 不要启动新实验。
  2. 不要重启 vLLM。
  3. 不要杀 GPU 进程。
  4. 不要修改业务代码，除非我后续明确要求。
  5. 可以读取文档、artifact、代码、日志。
  6. 可以写审计文档。
  7. 不要 commit。
  8. 不要 git add .。
  9. 不要碰无关未跟踪文件：`tatus --short --branch`。
  10. 不要把 openEuler VM 当作本轮重点；VM 不是这次审计核心。
  11. 不要只围绕上一轮 AI 的问题。上一轮问题只是输入线索，不是审计边界。
  12. 不要做答辩话术。只做技术问题、实验问题、实现漏洞、修复价值判断。

  先执行：

  git status --short --branch

  并在审计文档开头记录当前分支和 dirty 状态摘要。

  ---

  ## 审计目标

  你要回答的核心不是“我们怎么 claim”，而是：

  - 从赛题原文看，StateBus 当前实现是否真正覆盖要求？
  - 从代码路径看，文档说的机制是否真的跑到了？
  - 从 artifact 看，实验是否真的验证了机制？
  - 从工程角度看，哪些地方可能是 bug、复现风险、实验混杂或数据解释风险？
  - 哪些问题值得修，哪些只需要文档说明，哪些可以不管？
  - 如果要继续投入，最小修复路径是什么？

  注意：不要因为“没有真正 hidden-state / KV tensor transfer”就直接判弱。赛题要求是 embedding、语义向量、隐藏状态特征或其他中
  间表示，hidden-state 不是唯一要求。必须基于赛题原文判断当前 StateRef / FEATURE_BUNDLE / shared_memory / memfd / evidence
  pruning / prefix layout / Engine-Local Prefix Reuse 是否构成有效覆盖。

  ---

  ## 文档写入格式

  请把审计文档写成以下结构，可以分批写：

  ```markdown
  # Comprehensive Gap Audit - 2026-07-11

  ## 0. Scope And Git State

  ## 1. Contest Requirement Decomposition

  ## 2. Cross-Path Evidence Map

  ## 3. Code Path Verification

  ## 4. Experiment Sufficiency Review

  ## 5. Gap And Risk Ledger

  ## 6. Misleading Terms And Boundary Risks

  ## 7. Fix Priority Matrix

  ## 8. Open Questions

  每个 section 要包含具体路径、artifact 字段、代码位置。不要只写判断。

  ———

  ## 一、必须先读：赛题与规划

  先读这些文档：

  - README.md
  - docs/reference/题目.md
  - docs/planning/implementation_plan.md
  - docs/constraints/current_host_and_migration.md
  - docs/constraints/current_feature_scope.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/00_executive_summary.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/code_truth_vs_experiment_issue_matrix_zh.md

  请在文档 ## 1. Contest Requirement Decomposition 中拆解：

   Contest Requirement    Expected Mechanism    Current Implementation    Evidence    Gap Type    Fix Worth
  ━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━  ━━━━━━━━━━  ━━━━━━━━━━━

  至少覆盖：

  - 多 Agent 协作
  - 结构化通信
  - text vs protocol 双模式
  - 非文本中间状态传递
  - 共享记忆模块
  - 关键词/标签/语义检索
  - 跨任务记忆复用
  - 两组连续任务
  - 通信开销 / token / latency 指标
  - 非文本状态次数和规模
  - 10 轮稳定性
  - IPC/shared memory/socket 等系统技术
  - CodeAct optional

  Gap Type 使用：

  - none
  - implementation gap
  - experiment gap
  - documentation gap
  - reproducibility risk
  - overclaim risk

  Fix Worth 使用：

  - high
  - medium
  - low
  - no

  ———

  ## 二、必须读：no-KV / API 主线证据

  这部分是之前固定下来的 StateBus v2 主线，不要只看 KV。

  重点文档：

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/11_local_api_combined_result_analysis_20260708.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/12_artifact_mining_readout_20260708.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/13_artifact_mining_deep_analysis_20260708.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/14_local_api_non_kv_followup_deep_analysis_20260709.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/15_local_api_non_kv_followup_review_20260709.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/17_claim_boundary_and_experiment_upgrade_20260708.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/18_review_supplementary_findings_20260708.md

  重点 artifact：

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/summary.json
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/status.tsv
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/summary.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/summary.json
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_130958/summary.json
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/summary.json
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260706_191835/summary.json

  non-KV followup 深挖：

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/
    deep_mining/deep_mining_summary.json

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/
    deep_mining/deep_mining_readout.md

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/
    deep_mining/claim_validity_matrix.csv

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/
    deep_mining/replay_reuse_matrix.csv

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/
    deep_mining/state_transport_backend_matrix.csv

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/
    deep_mining/prompt_token_byte_matrix.csv

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/
    deep_mining/runtime_overhead_matrix.csv

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/
    deep_mining/quality_artifact_validation_matrix.csv

  请在 ## 2. Cross-Path Evidence Map 中把 no-KV/API 主线和 KV/local vLLM 主线分开，不要混成一条。

  表格格式：

   Requirement / Mechanism    no-KV/API Evidence    KV/local vLLM Evidence    Code Path    Gap    Worth Fixing
  ━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━  ━━━━━  ━━━━━━━━━━━━━━

  必须覆盖：

  - protocol vs text 通信效率
  - StateRef / 非文本状态传递
  - shared memory / mmap / memfd backend
  - memory reuse / replay reuse
  - Engine-Local Prefix Reuse
  - dynamic pruning
  - formal quality guard
  - continuous/replay stability
  - CodeAct / sandbox optional path

  ———

  ## 三、必须读：KV / local vLLM 证据

  重点文档：

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/19_kv_research_comprehensive_analysis_and_roadmap_20260710.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/21_local_vllm_kv_implementation_review_20260711.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/22_e0_32b_observability_probe_20260711.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/23_e1_kv_schedule_ablation_20260711.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/24_e2_prefix_alignment_ablation_20260711.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/25_e3_dynamic_pruning_ablation_20260711.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/26_e1_e2_stability_repeat_20260711.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/27_e1_e2_clean_service_repeat_20260711.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/28_e6_formal_guard_20260711.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/29_local_vllm_kv_experiment_log_synthesis_20260711.md
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/30_independent_audit_report_20260711.md

  重点 artifact：

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_vllm_kv_audit_20260711.json
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/e1_kv_schedule_ablation_summary_20260711_134159.json
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/
    e2_prefix_alignment_ablation_summary_20260711_1359.json

  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/e3_dynamic_pruning_ablation_20260711.json
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/e1_e2_stability_repeat_summary_20260711_1425.json
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/e1_e2_clean_service_repeat_summary_20260711_1438.json
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/e6_formal_guard_summary_20260711_1448.json
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/e6_formal_guard_mechanism_excerpt_20260711_1448.json
  - docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_vllm_kv_experiment_log_summary_20260711.json

  相关 run root：

  - /home/qcrs/statebus/runs/kv-e6-guard-20260711-1448
  - /home/qcrs/statebus/runs/sb32bcompact
  - /home/qcrs/statebus/runs/sb32bcap3k
  - /home/qcrs/statebus/runs/sb32bformal900
  - /home/qcrs/statebus/runs/sb32bformal3k
  - /home/qcrs/statebus/runs/sb32bformalx4k
  - /home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-gpu0-mini5-20260710_2234
  - /home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-gpu0-formal-20260710_2250
  - /home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-gpu0-formal-timeout900-20260711_0015

  请在 ## 4. Experiment Sufficiency Review 中明确区分：

  - direct evidence
  - proxy evidence
  - telemetry estimate
  - inferred evidence
  - failed / partial evidence

  重点判断：

  - E1/E2 是否充分证明 schedule/layout 改变了 engine-local prefix reuse 行为。
  - E3 是否只证明 retrieval-level dynamic pruning。
  - E6 是否只证明 combined profile 不伤 formal quality，而不是单独证明所有机制收益。
  - vLLM hit-rate gauge 是否足以作为机制指标，缺少 raw hit/miss counter 有多严重。
  - 8192 context 越界日志对当前 E2/E6 证据有没有破坏性影响。
  - clean-service repeat 是否足够排除 cache 污染。

  ———

  ## 四、必须读代码实现

  不要只读文档。请抽样读这些代码和脚本，确认 artifact 是否真的由实现路径支撑。

  环境/profile/服务脚本：

  - deploy/activate_statebus_local_vllm_profile.sh
  - scripts/start_vllm_qwen3_32b_prefix_cache.sh
  - scripts/run_v2_local_vllm_container_check.sh

  KV probe / audit：

  - scripts/probe_local_vllm_kv_schedule.py
  - scripts/probe_local_vllm_prefix_alignment.py
  - scripts/probe_dynamic_pruning_ablation.py
  - scripts/audit_local_vllm_kv_results.py
  - scripts/summarize_local_vllm_kv_experiment_logs.py

  v2 主路径：

  - v2/benchmark/live_runner.py
  - v2/benchmark/
  - v2/runtime/
  - v2/protocol/
  - v2/state/
  - v2/memory/
  - runtime/llm.py
  - runtime/orchestrator.py
  - protocol/messages.py
  - statepool/store.py
  - memory/

  建议使用 rg 搜：

  - STATEBUS_PREFIX_ALIGNMENT_MODE
  - shared_evidence_prefix
  - STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED
  - evidence_pruning
  - estimated_kv_tokens_saved
  - neural_prefix
  - prefix_cache
  - FEATURE_BUNDLE
  - StateRef
  - shared_memory
  - memfd
  - reuse_gain
  - skipped_step_count
  - memory_hit_rate
  - quality_floor_pass_count
  - max_context_tokens
  - _estimate_chat_prompt_tokens
  - BadRequestError
  - retry

  请在 ## 3. Code Path Verification 写表：

   Mechanism    Claimed Behavior In Docs    Code Path    Artifact Field    Verified?    Concern
  ━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━  ━━━━━━━━━━━━━━━━  ━━━━━━━━━━━  ━━━━━━━━━

  至少覆盖：

  - shared_evidence_prefix prompt layout
  - dynamic pruning env propagation
  - dynamic pruning actual evidence selection
  - E6 mechanism switches
  - StateRef non-text transfer
  - shared_memory / mmap / memfd path
  - memory replay / skip execution
  - protocol vs text metrics
  - local vLLM context handling
  - benchmark telemetry recording

  ———

  ## 五、Gap And Risk Ledger

  在 ## 5. Gap And Risk Ledger 里列所有问题，不要只列上一轮 AI 的问题。

  每个问题使用这个格式：

  ### G-XX: short title

  - Severity: high / medium / low
  - Area: contest requirement / code path / experiment design / artifact quality / reproducibility / documentation
  - Evidence:
    - path:line or artifact field
  - Why It Matters:
  - Fix Worth: high / medium / low / no
  - Minimal Fix:
  - Need New Experiment: yes / no
  - Notes:

  请重点寻找这些类型的问题：

  - 赛题要求没有直接实验覆盖
  - 文档说已实现，但代码路径不明显
  - artifact 字段是 estimate，但容易被当作 direct metric
  - benchmark 对照组不干净
  - no-KV 和 KV 两条证据链混淆
  - local vLLM 和 API 路径的模型/执行环境不同导致归因不清
  - 只在 deterministic/proxy 下验证，缺少 live/formal guard
  - context cap / prompt token estimate 可能导致 hidden truncation 或 retry 混杂
  - E6 token delta 被错误归因到 KV/prefix reuse
  - memory reuse 指标与 prefix reuse 指标命名冲突
  - 复现脚本默认值容易误导
  - artifact summarizer 漏数据或误归因
  - 代码注释/文档术语过度宣传

  ———

  ## 六、Misleading Terms And Boundary Risks

  在 ## 6. Misleading Terms And Boundary Risks 中专门列术语风险。

  格式：

   Term    Actual Meaning In Code/Artifacts    Not Proven / Not Meaning    Risk    Suggested Wording Or Fix
  ━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━

  必须至少分析：

  - KV mechanism
  - Engine-Local Prefix Reuse
  - neural_prefix_cache_hit_count_estimate
  - estimated_kv_tokens_saved
  - gpu_prefix_cache_hit_rate
  - hidden-state transfer
  - StateRef
  - FEATURE_BUNDLE
  - reuse_gain
  - skipped_step_count
  - memory_hit_rate
  - shared_evidence_prefix
  - formal guard
  - quality floor

  ———

  ## 七、Fix Priority Matrix

  在 ## 7. Fix Priority Matrix 中做一个优先级矩阵，不要写成最终口头建议。

  格式：

   Priority    Item    Category    Why Now    Minimal Action    Needs Code?    Needs Experiment?    Risk If Skipped
  ━━━━━━━━━━  ━━━━━━  ━━━━━━━━━━  ━━━━━━━━━  ━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━

  Priority 使用：

  - P0: 必须修，否则影响赛题有效性或实验可信度
  - P1: 值得修，成本低收益高
  - P2: 可修但不阻塞
  - P3: 不建议当前修，只澄清或延后

  要求：

  - 至少 3 个 P0/P1 候选。如果你认为没有 P0，要明确写“no P0 found”。
  - 不要把 openEuler VM smoke 放成默认 P0，除非你能从赛题/当前交付要求论证它是本轮阻塞。
  - 对每个候选说明是否需要新实验。优先寻找“不需要新实验，只需 artifact mining / 文档澄清 / 小代码修复”的动作。
  - 如果发现某个问题值得修但成本高，也要写明为什么可能不做。

  ———

  ## 八、特别要重新评估上一轮 AI 的几个点，但不要局限于它们

  上一轮 AI 提到这些问题，请重新评估其是否成立、严重程度、是否值得修：

  1. “没有 hidden-state / KV tensor transfer，所以状态传递创新弱”
  2. “local vLLM 路径没有 same-task text companion stage”
  3. “local vLLM 路径 reuse_gain=0，因此记忆复用弱”
  4. “E1/E2 样本量小，没有误差线”
  5. “E3 只是 retrieval-level probe”
  6. “E6 token delta 是否能归因到 KV/prefix reuse”
  7. “runtime/llm.py 400 retry 范围过宽”
  8. “_estimate_chat_prompt_tokens 字符级估算不准”
  9. “run_v2_local_vllm_container_check.sh 默认 8B 端口可能误导”

  但请注意：这些只是检查项。你必须继续主动发现其他问题。

  ———

  ## 九、完成方式

  请按批次工作：

  ### Batch 1

  读取赛题/规划/no-KV/KV 文档和主要 JSON/CSV artifact，写入：

      0. Scope And Git State
      1. Contest Requirement Decomposition
      2. Cross-Path Evidence Map

  ### Batch 2

  读取代码路径，写入：

      3. Code Path Verification

  ### Batch 3

  审计实验充分性和风险，写入：

      4. Experiment Sufficiency Review
      5. Gap And Risk Ledger

  ### Batch 4

  写术语边界和修复优先级，写入：

      6. Misleading Terms And Boundary Risks
      7. Fix Priority Matrix
      8. Open Questions

  每个 batch 写完后，在聊天里只简短报告：

  - 已写入哪些 section
  - 当前发现的最高优先级风险是什么
  - 下一批准备读什么

  不要在聊天里输出完整审计正文，正文写进 markdown 文件。

  ———

  ## 十、最终检查

  完成后运行：

  python -m py_compile scripts/summarize_local_vllm_kv_experiment_logs.py
  jq empty docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/
  local_vllm_kv_experiment_log_summary_20260711.json
  git diff --check
  git status --short --branch

  最终聊天回复只需要：

  - 文档路径
  - 写入了哪些 section
  - P0/P1 数量
  - 是否修改了代码
  - 是否有未运行或失败的校验
# StateBus v2 改进与修复入口

这个目录只保留当前仍然会影响实现判断、claim 边界和下一步修复的材料。早期 01-19 的阶段性审计、prompt 和中间态 artifacts 已清理；需要追溯时请从 git 历史读取，不再把它们作为日常阅读入口。

## 当前必读

1. `20_v2_comprehensive_truth_audit_20260706/13_artifact_mining_deep_analysis_20260708.md`
   - 2026-07-08 base + supplement 两组 artifact 的全量抽取后深度拆解。
   - 当前最适合判断“优势在哪里、损耗在哪里、哪些不能 claim、哪些问题还要修”的文档；覆盖 formal external compare、formal layer waterfall、text/protocol carrier compare、continuous/replay、flagship、KV prefix 和 CodeAct。

2. `20_v2_comprehensive_truth_audit_20260706/14_diagnostic_artifact_mining_readout_20260708.md`
   - 由 `scripts/diagnose_v2_artifact_mining.py` 从既有 base + supplement artifacts 生成的诊断层抽取。
   - 专门补 latency decomposition、`formal-trend-002` route miss forensic、completion/schema inflation；对应机器 JSON 为 `14_diagnostic_artifact_mining_summary_20260708.json`。

3. `20_v2_comprehensive_truth_audit_20260706/12_artifact_mining_readout_20260708.md`
   - 由 `scripts/analyze_v2_artifact_evidence.py` 递归扫描 run artifact 生成的机器抽取读数。
   - 用来追溯 JSON/report/prompt slice/telemetry/code gate 的聚合事实；对应机器 JSON 为 `12_artifact_mining_summary_20260708.json`。

4. `20_v2_comprehensive_truth_audit_20260706/11_local_api_combined_result_analysis_20260708.md`
   - 2026-07-08 `sb2-gpu1-20260708_084458` base run 与 `sb2-gpu1-health-20260708_110413` supplement run 的合并读数。
   - 当前最适合用来判断 formal 25/5、external compare、continuous/replay、CodeAct、KV prefix demo 和 flagship supplement 的实验结论、claim 边界、收益/损耗归因。

5. `20_v2_comprehensive_truth_audit_20260706/00_executive_summary.md`
   - 当前 v2 claim-upgrade 真实性审计入口。
   - 说明哪些已经真实落地，哪些仍是 deterministic、历史或文档层证据。

6. `20_v2_comprehensive_truth_audit_20260706/05_merged_issue_ledger.md`
   - 当前问题分类账。
   - 后续修复应优先从这里和本轮 local+api 深挖文档交叉读取。

7. `20_v2_comprehensive_truth_audit_20260706/code_truth_vs_experiment_issue_matrix_zh.md`
   - 当前最重要的代码事实与实验证据对照矩阵。
   - 用来判断结构化控制面、非文本中间状态、共享记忆/replay、formal compare 是否被实验真实测到。
   - 后续修复应优先按这个矩阵中的 P0/P1 排序。

8. `20_v2_comprehensive_truth_audit_20260706/07_fix_plan.md`
   - 当前修复计划基线。
   - 注意：它已结合 local+api formal compare 与代码事实矩阵更新。

9. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260708_084458/`
   - 2026-07-08 full-registry local+api comprehensive base artifact。
   - Required stages 全部通过；formal internal 25/25、formal carrier compare 25/5、formal external compare 25/5、continuous/replay、replay-negative 均可读。

10. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260708_084458_supplement_20260708_110413/`
   - 2026-07-08 supplement artifact。
   - CodeAct acceptance、KV prefix demo、flagship ablation rerun 均通过；raw summary 中两个 base-audit failures 是已修脚本误报，不是实验 stage failure。

11. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/`
   - 最新 full `RUN_FLAGSHIP=1` local+api comprehensive artifact。
   - 13 stages 全部 exit 0；required failed stage count 为 0；该旧 artifact 的 formal compare 是 8-case strict equal-quality，通过但不支持 efficiency superiority；flagship stage 跑完但 stress pass 为 3/6。现在主要作为历史对照，不再是最新读数。

12. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260706_191835/deep_dive_analysis_and_fix_plan_zh.md`
   - historical local+api 全面测试深度拆解。
   - 重点定位 formal compare gate 语义混用、8-case compare 覆盖缺口、external metric schema 问题。

13. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_034412/`
   - post-fix comprehensive diagnostic rerun。
   - 注意：不是 passing comprehensive evidence；required formal internal timeout，formal compare debug-only，但 diagnostics bundle 自足。

14. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_130958/`
   - transport retry 后、selection retry 前的 `RUN_FLAGSHIP=1` rerun。
   - 注意：required、continuous、continuous replay 都 clean，但 flagship 因 strict visible-candidate mismatch 失败。

15. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/`
   - `RUN_FLAGSHIP=1` transport failure rerun。
   - 注意：required stages clean，但 optional continuous/replay/flagship 因 API connection/timeout 失败，不是 optional passing comprehensive evidence。

## 当前可引用证据

- `20_v2_comprehensive_truth_audit_20260706/artifacts/formal_auto.stdout.json`
- `20_v2_comprehensive_truth_audit_20260706/artifacts/formal_shared_memory.stdout.json`
- `20_v2_comprehensive_truth_audit_20260706/artifacts/formal_memfd_local.stdout.json`
- `20_v2_comprehensive_truth_audit_20260706/artifacts/preflight_deterministic.stdout.json`
- `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260706_191835/`
- `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_034412/`
- `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/`
- `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_130958/`
- `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/`
- `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/`
- `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260708_084458/`
- `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260708_084458_supplement_20260708_110413/`
- `20_v2_comprehensive_truth_audit_20260706/12_artifact_mining_summary_20260708.json`
- `20_v2_comprehensive_truth_audit_20260706/12_artifact_mining_readout_20260708.md`
- `20_v2_comprehensive_truth_audit_20260706/13_artifact_mining_deep_analysis_20260708.md`
- `20_v2_comprehensive_truth_audit_20260706/14_diagnostic_artifact_mining_summary_20260708.json`
- `20_v2_comprehensive_truth_audit_20260706/14_diagnostic_artifact_mining_readout_20260708.md`

## 当前不要再引用为 source-of-truth 的内容

- 已删除的 `01_*` 到 `19_*` 阶段性 improvement 文档。
- 已删除的 prompt / new-window / handoff 文档。
- 已删除的 `docs/improvement/artifacts/15_*`、`16_*`、`17_*` 中间审计过程日志。

这些内容的价值是历史追溯，不是当前实现判断。保留在主目录只会让 claim 口径继续摇摆。

## 当前核心判断

- `formal internal` 证据强：API+local+memfd 下 25 cases / 5 families 跑通并 25/25 通过。
- `formal compare` 已有 2026-07-08 full registry 25 cases / 5 families live local+api artifact；当前可写 quality-superiority + prompt/total token reduction，但不能写 strict equal-quality efficiency superiority 或 latency superiority。
- compare gate 语义、8-case scope metadata 和 external metric schema 已拆清；`local_api_20260707_163354` 证明 formal financial 8-case strict equal-quality compare valid，但本次 API timing 下没有 efficiency superiority claim。
- `local_api_20260707_034412` 中 external compare 的 metric fields 8/8 quality pass，但 `benchmark-sample-6` fairness hard gate fail，因此该旧 diagnostic run 不支持 formal external claim。
- 非文本中间状态当前应精确写成 embedding semantic state + refs + hydration accounting；证据文本/表格仍通过 hydration 进入 prompt，不能扩大为 hidden-state/KV transfer。
- formal runtime 的 UDS/protobuf 主 benchmark 路径是 loopback harness；subprocess memfd 目前主要由单测覆盖。
- 端到端速度优势、openEuler VM validation、nsjail production sandbox、hidden-state/KV transfer 仍不能 claim。
- `sb2-gpu1-health-20260708_110413` supplement 证明 CodeAct 5/5、KV prefix demo、flagship rerun 均通过；flagship 5 个 claimable families 通过，1 个 diagnostic-only family 不支持通用化 claim。

## 下一步修复顺序

1. 如要 claim latency/efficiency superiority，新增 serialized repeat rerun；当前 2026-07-08 证据只支持 quality-superiority + prompt/total token reduction，不支持 latency。
2. 如要 claim actual vLLM prefix-cache mechanism，启动 local vLLM prefix-cache service 后运行 `STATEBUS_RUN_VLLM_PREFIX_PROBE=1`，同时收集 metrics delta 与 streaming TTFT。
3. 修 `long_doc_metric_replay_v1` missing target round 7 和 `kv_prefix_reuse_v1` missing target round 3，使 replay-headline gate 更完整。
4. 继续验证 diagnostics host-copy 在后续 failure/nonzero container exit 后也能自动填充 docs artifact。
5. 如要 claim subprocess execution，新增 subprocess benchmark stage，而不是只靠单测。

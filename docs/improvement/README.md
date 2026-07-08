# StateBus v2 改进与修复入口

这个目录只保留当前仍然会影响实现判断、claim 边界和下一步修复的材料。早期 01-19 的阶段性审计、prompt 和中间态 artifacts 已清理；需要追溯时请从 git 历史读取，不再把它们作为日常阅读入口。

## 当前必读

1. `20_v2_comprehensive_truth_audit_20260706/00_executive_summary.md`
   - 当前 v2 claim-upgrade 真实性审计入口。
   - 说明哪些已经真实落地，哪些仍是 deterministic、历史或文档层证据。

2. `20_v2_comprehensive_truth_audit_20260706/05_merged_issue_ledger.md`
   - 当前问题分类账。
   - 后续修复应优先从这里和本轮 local+api 深挖文档交叉读取。

3. `20_v2_comprehensive_truth_audit_20260706/code_truth_vs_experiment_issue_matrix_zh.md`
   - 当前最重要的代码事实与实验证据对照矩阵。
   - 用来判断结构化控制面、非文本中间状态、共享记忆/replay、formal compare 是否被实验真实测到。
   - 后续修复应优先按这个矩阵中的 P0/P1 排序。

4. `20_v2_comprehensive_truth_audit_20260706/07_fix_plan.md`
   - 当前修复计划基线。
   - 注意：它已结合 local+api formal compare 与代码事实矩阵更新。

5. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/`
   - 最新 full `RUN_FLAGSHIP=1` local+api comprehensive artifact。
   - 13 stages 全部 exit 0；required failed stage count 为 0；该旧 artifact 的 formal compare 是 8-case strict equal-quality，通过但不支持 efficiency superiority；flagship stage 跑完但 stress pass 为 3/6。

6. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260706_191835/deep_dive_analysis_and_fix_plan_zh.md`
   - historical local+api 全面测试深度拆解。
   - 重点定位 formal compare gate 语义混用、8-case compare 覆盖缺口、external metric schema 问题。

7. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_034412/`
   - post-fix comprehensive diagnostic rerun。
   - 注意：不是 passing comprehensive evidence；required formal internal timeout，formal compare debug-only，但 diagnostics bundle 自足。

8. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_130958/`
   - transport retry 后、selection retry 前的 `RUN_FLAGSHIP=1` rerun。
   - 注意：required、continuous、continuous replay 都 clean，但 flagship 因 strict visible-candidate mismatch 失败。

9. `20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/`
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

## 当前不要再引用为 source-of-truth 的内容

- 已删除的 `01_*` 到 `19_*` 阶段性 improvement 文档。
- 已删除的 prompt / new-window / handoff 文档。
- 已删除的 `docs/improvement/artifacts/15_*`、`16_*`、`17_*` 中间审计过程日志。

这些内容的价值是历史追溯，不是当前实现判断。保留在主目录只会让 claim 口径继续摇摆。

## 当前核心判断

- `formal internal` 证据强：API+local+memfd 下 25 cases / 5 families 跑通并 25/25 通过。
- `formal compare` 仍不能写成 full formal external superiority：`local_api_20260707_163354` 这份旧证据只覆盖 formal financial 8 cases；代码已升级为 registry-backed 25/5 adapter，但需要新的 live local+api rerun artifact 才能 claim。
- compare gate 语义、8-case scope metadata 和 external metric schema 已拆清；`local_api_20260707_163354` 证明 formal financial 8-case strict equal-quality compare valid，但本次 API timing 下没有 efficiency superiority claim。
- `local_api_20260707_034412` 中 external compare 的 metric fields 8/8 quality pass，但 `benchmark-sample-6` fairness hard gate fail，因此该旧 diagnostic run 不支持 formal external claim。
- 非文本中间状态当前应精确写成 embedding semantic state + refs + hydration accounting；证据文本/表格仍通过 hydration 进入 prompt，不能扩大为 hidden-state/KV transfer。
- formal runtime 的 UDS/protobuf 主 benchmark 路径是 loopback harness；subprocess memfd 目前主要由单测覆盖。
- 端到端速度优势、openEuler VM validation、nsjail production sandbox、hidden-state/KV transfer 仍不能 claim。
- `local_api_20260707_163354` 证明 transport retry 与 strict selection retry 后 full `RUN_FLAGSHIP=1` comprehensive 可跑完；但 flagship stress pass 为 3/6，不能写成 all-pass。

## 下一步修复顺序

1. 用新的 local+api serialized rerun 证明 registry-backed formal external compare 覆盖 25 cases / 5 families。
2. 拆解 `local_api_20260707_163354` 的 flagship stress 3/6，区分 family 定义、semantic selection 与 StateRef prompt-saving failure。
3. 继续验证 diagnostics host-copy 在后续 failure/nonzero container exit 后也能自动填充 docs artifact。
4. 如要 claim subprocess execution，新增 subprocess benchmark stage，而不是只靠单测。
5. 增强 memfd unavailable fallback 负向验证。

# StateBus 文档入口

这个目录之前积累了大量设计稿、审计稿、prompt、会话交接和历史实验读数。当前阅读策略是：先看仍能指导实现和 claim 的 source-of-truth，再把历史过程文档当背景材料，而不是让它们参与当前判断。

## 当前优先阅读顺序

1. `../README.md`
   - 仓库入口和环境/命令概览。

2. `reference/题目.md`
   - 赛题原始要求，所有 claim 都要能回到这里。

3. `constraints/current_host_and_migration.md`
   - host、container、openEuler、Docker、nsjail 的真实边界。

4. `constraints/current_feature_scope.md`
   - 当前已经实现和不能声称的能力边界。

5. `contracts/`
   - v2 当前合同文档，尤其是 role、persistence、external fairness、bounded CodeAct。

6. `reports/final_v2_evidence_index_20260703.md`
   - v2 历史证据索引。

7. `reports/v2_experiment_summary_20260703.md`
   - v2 实验摘要，注意其中历史 CodeAct 和 external compare 口径需要结合最新 audit 阅读。

8. `improvement/README.md`
   - 当前修复和问题入口。

9. `improvement/20_v2_comprehensive_truth_audit_20260706/`
   - 最新综合真实性审计。

10. `improvement/20_v2_comprehensive_truth_audit_20260706/code_truth_vs_experiment_issue_matrix_zh.md`
    - 代码事实、local+api 实验证据、问题严重级别和修复顺序的当前矩阵。
    - 这是判断“实现到底测没测到”的主入口。

11. `improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/`
    - 最新 full `RUN_FLAGSHIP=1` local+api comprehensive artifact；13 stages 全部 exit 0，required failed stage count 为 0，flagship stage 跑完但 stress pass 为 3/6。

12. `improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_130958/`
    - transport retry 后、selection retry 前的失败证据；required/continuous/replay clean，但 flagship 因 strict visible-candidate mismatch 失败。

13. `improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/`
    - `RUN_FLAGSHIP=1` transport failure artifact；required stages clean，但 optional continuous/replay/flagship 因 API connection/timeout 失败。

14. `improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/`
    - 历史 passing local+api comprehensive core artifact；required stages 全部 exit 0，flagship 显式关闭。

15. `improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260706_191835/deep_dive_analysis_and_fix_plan_zh.md`
    - historical local+api 全面测试深挖和修复计划。

## 当前不建议作为入口的目录

- `analysis/`
  - 多轮历史审计和思考过程，很多内容被后续 v2 audit 覆盖。

- `progress/`
  - 6 月 host-mainline 过程记录，主要用于追溯，不应覆盖当前 v2 分支判断。

- `review/` 和 `reivew/`
  - 历史 review、prompt 和计划集合。当前有用结论应已经迁移到 reports/contracts/improvement。

- `reader_doc_blueprint/`
  - 读者文档模板，不是当前事实源。

## 当前 claim 边界

可以作为当前强证据继续推进：

- v2 formal internal 25 cases / 5 families。
- API+local+memfd formal internal 跑通。
- semantic state transfer / memfd transfer telemetry。
- continuous replay 的 observed / validated / exact replay 指标。

必须继续限定：

- formal external compare 当前不是 full 25-case registry compare。
- compare gate/scope/schema 已修；`local_api_20260707_163354` 中 formal financial 8-case compare 公平门和 strict equal-quality 通过，但 `formal_external_claim_kind=debug_only`，不支持本次 efficiency superiority。
- legacy `revenue_value` 只作为兼容字段；新判断使用 `metric_name` / `metric_value`。
- 当前 semantic state transfer 证据应限定为 embedding semantic state + refs + hydration accounting。
- formal benchmark 的控制面主路径是 loopback UDS/protobuf harness；subprocess memfd 需要单独测试或新增 benchmark stage。
- openEuler VM validation、nsjail production sandbox、hidden-state/KV transfer、端到端速度优势仍不能声称。
- `local_api_20260707_163354` 是当前 latest full `RUN_FLAGSHIP=1` passing evidence；但 flagship stress 只有 3/6 families pass，不能写成 all-pass。
- `local_api_20260707_115051` 和 `local_api_20260707_130958` 只作为 transport retry / selection retry 的失败定位证据，不替代最新 passing evidence。

## 文档维护原则

- 新文档必须说明它是 source-of-truth、历史记录，还是实验 artifact 解释。
- prompt 和新窗口交接内容不要再放入主 docs 树；需要时放到临时工作区或 issue/任务系统。
- 已被最新审计覆盖的中间态文档不要继续保留在阅读入口。
- 任何对外 claim 必须指向具体 JSON artifact、测试命令或代码路径。

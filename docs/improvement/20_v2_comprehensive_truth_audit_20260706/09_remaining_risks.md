# 剩余风险

## P0：Formal external superiority 仍未闭环

`v2-targeted-json-retry-compare-20260707_192452` 已产出 post-fix API+local+memfd formal compare JSON，并在 formal financial 8 cases / 1 family scope 下支持 equal-quality prompt/token efficiency claim。`local_api_20260707_163354` 进一步证明该 8-case scope 下 strict equal-quality compare valid、公平门 8/8，但本次 `formal_external_claim_kind=debug_only`，不支持 efficiency superiority。二者都不是 formal registry 25 cases / 5 families compare。因此 full formal external superiority claim 仍必须 blocked。

## P1：Deterministic evidence 与 local+api evidence 必须分层引用

早期 fresh 25/25 formal runs 使用 `role_path_mode=deterministic`，证明 backend/plumbing 基线。`v2-targeted-json-retry-formal-20260707_191045` 和 `local_api_20260707_163354/r01_05_formal_api_local_memfd` 证明 API+local+memfd formal internal 25/25。二者都不能自动推出 external superiority；formal compare claim 必须单独引用 `r01_06` 或 targeted compare，并带 8-case scope。

## P1：Container activation 损坏

host activation command 在 container root 下仍不成立，因为容器缺少 conda；但 v2 container path `/usr/local/bin/activate_statebus_container.sh` 已在 `local_api_20260707_163354` 中验证成功。剩余风险是文档/脚本不能再混用 host activation contract 和 container activation contract。

## P1：flagship stress 未全量通过

`local_api_20260707_163354` 是 latest full `RUN_FLAGSHIP=1` comprehensive run：13 stages exit 0，required failed stage count 0，flagship stage exit 0。但 stress pass 为 3/6：`csv_table_profile_v1`、`csv_correlation_replay_v1`、`long_doc_table_v1` 通过；`incident_diagnosis_v2`、`long_doc_metric_replay_v1`、`cross_period_financial_v1` 未过 stress family gate。

失败原因已经能分层，但尚未修复：

- `incident_diagnosis_v2`：L2 semantic transfer 10，StateRef prompt saving 3132 bytes，visible saving 2664 bytes；L3 quality 7/10，quality headline 不合格。
- `long_doc_metric_replay_v1`：L2 semantic transfer 10，StateRef prompt saving 3699 bytes，visible saving 357 bytes；L3 quality 8/10，validated 7，exact 1，skipped 9，quality/replay headline 不合格。
- `cross_period_financial_v1`：quality 10/10、validated 4、skipped 4，quality/replay headline 合格；失败来自 L2 相对 T2 无 StateRef prompt saving，`llm_prompt_delta_l2_vs_t2=+3268`、`prompt_visible_delta_l2_vs_t2=+6792`，属于 semantic selection dominates this family。

因此只能写 flagship stage completed / stress 3 of 6 / total StateRef prompt savings 37884 bytes，不能写 flagship all-pass。

## P1：formal compare token 边界仍需 schema 化

`r01_06` latest full compare 中，StateBus 与 external 都是四角色，`llm_call_count_delta=0`，strict equal-quality valid，fairness pass 8/8。StateBus prompt bytes 和 prompt tokens 更低，但 completion tokens 和 total tokens 更高：external prompt tokens 12678、completion tokens 10199、total 22877、prompt bytes 43213；StateBus prompt tokens 9645、completion tokens 19695、total 29340、prompt bytes 30661。

剩余风险是 report/summary 字段仍容易把 prompt/input savings 写成 token/efficiency superiority。当前只能写 prompt/input/control-byte savings；`formal_external_claim_kind=debug_only` 仍禁止 total-token 或 efficiency-superiority claim。

## P1：StateRef claim 仍可能被误读成 evidence replacement

当前实现是 `EMBEDDING_STATE` semantic state + typed refs + hydration accounting。StateRef 让 runtime 传递 semantic state 和 refs，并把 selected prompt slices 归档；它没有让模型直接消费 vectors，也没有让 raw evidence 完全消失。任何“raw evidence never enters prompt”“hidden-state transfer”“KV cache transfer”的表述仍不受支持。

## P1：long-running API transport 仍是外部依赖风险

`runtime/llm.py` 已增加 OpenAI-compatible transport retry，并用单测覆盖 connection/timeout transient retry 与 retry-budget exhaustion。`local_api_20260707_163354` 已在补丁后完成 full `RUN_FLAGSHIP=1` comprehensive，因此 retry 缺口不再阻塞当前 evidence。剩余风险是外部 provider 仍可能在未来长跑中出现超出 retry budget 的 transient failure。

## P2：local+api artifact copy 的 failure-path 自动化仍要复查

`local_api_20260707_091807` 的 docs artifact copy 由 wrapper 在 exit 0 后自动生成，`diagnostics/manifest.json` 显示 copied_file_count=1384。`local_api_20260707_163354` 的 docs artifact copy 已按 wrapper 诊断逻辑补齐，copied_file_count=2558。剩余风险是 nonzero container exit 后的 host-copy failure path 仍应再测一次，避免失败 run 只创建空目录。

## P1：CodeAct 必须保持 bounded

当前可辩护 claim 是 bounded CodeAct / controlled execution。Realtime LLM code generation 需要 fresh formal API artifact。

## P2：Family validators 不是 active primary validators

在 runner import 并使用 `tasks/formal/*/validator.py` 前，不应引用它们作为 benchmark quality enforcement。

## P2：Memfd negative fallback 需要更强证据

Memfd positive path 已验证。Memfd unavailable fallback 需要真实负向环境或显式 capability-masked stage。

## P2：openEuler VM validation 缺失

容器 run 不等于 openEuler VM validation。Compatibility claims 仍不支持。

## P2：Nested protobuf payloads 仍包含 JSON fields

Typed Protobuf envelope 真实存在，但若干 nested payload 仍使用 JSON strings。措辞必须精确。

## P2：容器缺少 `jq`

Audit prompt 中的 extraction command 对当前 image 不可移植。应安装 `jq` 或添加 repo-local Python extractor。

## P3：Benchmark artifact size 与 ownership

Fresh JSON artifacts 总计约 3 MB，从容器 `/tmp` 复制而来。Ownership 已恢复为 `qcrs:qcrs`，但未来 scripts 应直接以正确 UID/GID 写 artifact。

---

## 赛题交付风险（2026-07-07 新增）

### P0：openEuler 24.03-LTS-SP3 交付要求未验证（V2-AUDIT-021）

赛题交付要求最终代码在 openEuler 24.03-LTS-SP3 上可编译、运行和测试。当前全部证据来自 Docker + Ubuntu 20.04 + openEuler container，不等于 VM 独立验证。此项是评审现场复现的前提，未验证等于交付阻塞。

关联计划：`10_contest_oriented_followup_plan_20260707.md` § 5 Step 1。

### P1：演示视频缺失（V2-AUDIT-022）

赛题要求提交演示视频。当前无任何视频产物或制作计划。

关联计划：`10_contest_oriented_followup_plan_20260707.md` § 5 Step 6。

### P1：V2 formal 缺 text vs protocol 双模对比（V2-AUDIT-023）

「通信效率（25分）」的直接证据需要同一任务集在 text 和 protocol 两种模式下的 token/byte 对比。v2 formal 层面只有 protocol 模式，text 模式对比仍停留在 v1 历史数据和 v2 smoke（deterministic）。

关联计划：`10_contest_oriented_followup_plan_20260707.md` § 5 Step 2。

### P2：comprehensive 运行 timing 不可用于效率 claim（NEW-004）

`r01_06` 的 `api_task_ms_delta=86580ms`（正值）来自并发综合测试，受其他 stage 影响，不代表真实效率对比。timing efficiency claim 必须来自 serialized rerun（`STATEBUS_LOCAL_API_REPEAT=3`）。此外，StateBus 运行完整4角色管线，external 只运行单角色，端到端 latency delta 本质上不可比，不应作为主效率指标；主指标是 token/byte delta。

### P2：历史实验报告仍需防误用（V2-AUDIT-028）

`docs/reports/v2_experiment_summary_20260703.md` 保留 2026-07-04 历史诊断数据。它的 `Container (openEuler)`、old formal efficiency/superiority flags、bwrap sandbox 和若干 `强` 表述不能替代本审计 latest evidence。后续答辩材料必须优先引用 `local_api_20260707_163354` 和本审计 stopline。

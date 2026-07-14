# StateBus v2 Planner、KV Prefix 与 Replay 定向修复结果

日期：2026-07-14  
结构化账本：`45_planner_kv_replay_fix_results_20260714.json`  
状态：定向修复与验证完成；未重跑完整 16-stage matrix

## 1. 结果摘要

三条主线已经落地，不再只是 Phase 设计：

| 主线 | 实施结果 | 定向验证 |
| --- | --- | --- |
| Planner | bounded `SemanticTaskPlan` 被受限消费；四类 Retriever objective 分离；schema/semantic/taint 校验失败时 fail closed 到 Runtime fallback；固定四步拓扑不变 | local vLLM primary/original/disabled/perturbed 共 16 次执行，完整 gate 通过 |
| KV prefix | vLLM V0 block query/hit counter exporter、task-local before/after delta 和 TTFT probe 已接通 | 4/4 pair、40/40 请求、40/40 JSON contract、40/40 counter delta 通过 |
| Replay | exact identity 排除 Planner 措辞、query-derived score 和 lexical routing hint，同时继续绑定 evidence 内容、locator、source 和 Runtime signature | incident L3 10/10 quality；7 exact、2 validated、1 cold/disallowed |

Docker 定向回归结果为 `128 passed in 469.01s`。日志位于 `/home/qcrs/statebus/runs/targeted_planner_kv_replay_fixes_20260714/targeted_regression_final.log`，SHA256 为 `9d905e6f1930d091433a2b80f49f785b279a2c69f49d405834adbacc090b3553`。

## 2. Planner 已达到的可用程度

Planner 现在负责稳定的语义规划，而不是生成任意 DAG。模型生成 `statebus.semantic_task_plan.v1`，包含 task semantics、required evidence、required outputs，以及 `lexical_metadata`、`semantic_chunk`、`table_structure`、`memory` 四类不同 retrieval objective。Runtime 仍控制固定 workflow、允许的 output/evidence enum、route/tool、replay、fallback、lease 和 GC。

可观测性已经闭环：`objective_source`、model/fallback/consumed field count、model/fallback/effective plan hash、field provenance、behavioral effect、每类 Retriever consumed objective hash 均落盘。Retriever 在 [pipeline.py](/home/qcrs/statebus/project/v2/retrieval/pipeline.py:1031) 规范化并 hash 实际消费的四类 objective；Planner resolution 与 fail-closed merge 位于 [semantic_plan.py](/home/qcrs/statebus/project/v2/runtime/semantic_plan.py:302)。

local vLLM ablation 产物为 `/home/qcrs/statebus/runs/targeted_genericity_ablation_local_gate3_20260714/stdout.json`：

- primary 4/4 quality pass、plan valid、semantic equivalent、`objective_source=hybrid`、behavioral effect 为 true，16/16 Retriever consumed hash 匹配；
- original/paraphrase 4/4 quality pass，4/4 semantic equivalence；
- disabled 4/4 quality pass，全部回到 `runtime_fallback`，behavioral effect 全为 false；
- perturbed 4/4 quality pass，effective plan hash 和 consumed objective hashes 全部改变，behavioral effect 全为 true；
- disabled/perturbed 的 route 和 tool 均保持稳定；
- route hints 关闭，4 个 Planner prompt 的 taint scan 为 0 match；四个 family 形成 4 个 semantic signature。

这证明“Planner 数据被实际消费且可改变 retrieval objective”，不只是被调用、保存或透传。它仍不证明自由文本 `CanonicalTaskSpec` 编译泛化，因为 holdout 继续使用预编译 spec；这一边界已经写入 gate 输出。

## 3. KV Prefix 的真实证据

原先只有服务生命周期累计 gauge，无法计算 task-local hit。现在 exporter 从 vLLM V0 block manager 采集单调累计的 block query/hit counter，StateBus 在 task/pair 前后取样并计算 delta。解析和 delta 校验见 [vllm_metrics.py](/home/qcrs/statebus/project/v2/runtime/vllm_metrics.py:78)，exporter 位于 [vllm_v0_prefix_counter_exporter.py](/home/qcrs/statebus/project/scripts/vllm_v0_prefix_counter_exporter.py)。

最终重复实验 `/home/qcrs/statebus/runs/targeted_prefix_alignment_repeats_json_contract_20260714/repeat_summary.json`：

| 模式 | Block queries | Cached block hits | Hit rate | Warm TTFT median |
| --- | ---: | ---: | ---: | ---: |
| shared prefix | 6,996 | 5,458 | 78.02% | 267.06 ms |
| independent prefix | 7,200 | 0 | 0% | 2,282.89 ms |

四对交替顺序为 shared-first、independent-first、shared-first、independent-first；4/4 pair 中 shared 更快，配对平均差为 -2,016.26 ms。

这些 counter 是 vLLM engine 内 block query/hit，不是 request 数，也不是传输了多少 KV tensor。结果证明同一 engine 内 prefix reuse 机制及其 TTFT 差异，不是 hidden-state/KV tensor handoff，也不能单独升级为 StateBus 端到端加速声明。

## 4. Replay 修复

修复前 exact gate 把 Planner 自由文本 objective、query-derived evidence score 和 lexical routing hint 纳入 identity，因此语义相同且实际 execution input 不变的轮次会错误降级为 validated replay。

新增 [evidence_execution_input_replay_hash()](/home/qcrs/statebus/project/v2/runtime/replay.py:217)，exact identity 现在由三个稳定 hash 构成：hydrated evidence/source identity、hydrate manifest、Runtime signature manifest bundle。完整 Planner handoff 和 evidence observation hash 仍保留在 replay audit 中，但不参与 exact 判定。evidence 文本、locator、source hash、manifest 或 Runtime signature 变化仍会使 exact identity 失效。

incident 报告 `/home/qcrs/statebus/runs/targeted_planner_kv_replay_fixes_20260714/incident_benchmark_reports/continuous-incident.json` 的 L3 结果为：

- 10/10 quality pass；
- exact replay：round 3、4、6、7、8、9、10；
- validated replay：round 2、5；
- round 1 为 cold/disallowed；
- missing/unexpected target rounds 均为空；
- `eligible_for_replay_headline=true`。

## 5. 验证与风险边界

最终定向测试覆盖 Planner schema/consumption/ablation、genericity gate、prefix metrics/exporter/probe、replay identity、smoke 和相关 benchmark runner，共 `128/128` 通过。`git diff --check` 通过。

仍不能宣称：

- 新的 16-stage extended matrix 全通过；
- 自由文本直接编译成正确 `CanonicalTaskSpec`；
- KV/hidden-state 跨进程或跨 engine tensor transfer；
- 当前 prefix probe 等同于 StateBus 全流程 latency/token 收益；
- 修复后的 compare/formal/UDS/continuous 全矩阵均无回归。

下一步应是经确认后运行最小跨 stage smoke，再决定是否投入新的 full matrix；当前不需要再修改 Planner 角色边界。

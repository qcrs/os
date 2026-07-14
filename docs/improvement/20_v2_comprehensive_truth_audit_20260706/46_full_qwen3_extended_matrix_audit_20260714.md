# StateBus v2 Qwen3-32B 16-Stage 完整矩阵严格审计

审计日期：2026-07-14

审计对象：`/home/qcrs/statebus/runs/full_qwen3_extended_gpu1_20260714_135500`

结构化账本：`46_full_qwen3_extended_matrix_audit_20260714.json`

分析脚本：`scripts/analyze_full_qwen3_extended_matrix_20260714.py`

历史基线：tag `v2-non-kv-baseline-20260710`，commit `d83627dc2b792b4c8ac2c2d58337fc8281771803`

## 1. 执行摘要

本次 16-stage 矩阵完整落盘，记录状态为 14 pass、2 fail；`matrix_complete=true`，但 `overall_ok=false`，所以不能写成“完整矩阵通过”。两个失败都不是简单的端到端能力失败：

- Stage 03 的 25 个 target 全部通过质量门，其中 15 个 `exact_replay` 真实恢复已验证 output，并跳过 Retriever、Executor、Summarizer；10 个 `validated_replay` 继续执行四角色。launcher 仍要求四角色各调用 25 次，因而把真实减算误判为失败。与此同时，`llm_call_count` 少计 15 次实际 Planner 请求，`answer_restoration_replay_count` 又把 15 次恢复写成 0。
- Stage 08 的 primary、disabled、perturbed 共 12 次运行均通过质量，4 个 original 也完成。48 个 taint violation 全是同一个合法 `sp` shared-prefix 元数据合同在 3 个下游角色、16 次请求上的重复误报。独立存在的真实问题是 `formal-agg-004` paraphrase 的模型计划漏了 `groupby_artifact_ref`；Runtime fallback 补齐 effective plan，质量、route、tool 未受影响。

最可信的性能结果是三轮等质量 external system compare 的 token 节省：total token delta 分别为 `-23,567`、`-23,603`、`-23,439`，标准差仅 70.38。相反，StateBus 三轮 E2E 都更慢，task time delta 分别为 `+37,737.9 ms`、`+214,354.2 ms`、`+221,222.4 ms`。因此可以声明“系统级、等质量、可重复的 token 节省”，不能声明 latency superiority，也不能把全部收益单独归因于 Protobuf、shared memory 或 prefix reuse。

当前最扎实的创新证据是：typed control 减少 control bytes；SemanticStateRef 在 L2/L3 真实 publish、transfer、hydrate；bounded Planner 的四类 objective 形成 model/fallback/effective/consumed 闭环；exact replay 恢复 verified output 并减少三个下游 Agent 请求；同一 vLLM engine 内 shared prefix 有真实 block hits。仍不能宣称自由文本 spec compilation、跨 Agent KV/hidden-state tensor handoff、强安全 sandbox、openEuler 已验证或 StateBus 端到端加速。

## 2. 数据完整性和方法

脚本只读取持久化 artifact 和源码文本，不导入 Runtime，也不修改 run。它递归枚举 27,461 个文件：25,558 个 JSON、942 个 JSONL、21 个 log、456 个 workspace Python artifact、471 个 SQLite 文件。942 个 JSONL 共 25,598 条记录，解析错误为 0；唯一 JSON 错误是空的 `/home/qcrs/statebus/runs/full_qwen3_extended_gpu1_20260714_135500/vllm_health.json`。

账本保存 471 个 StateBus workspace 的 case 级证据、75 个 external repeat case、94 个 stage/layer/family 聚合组。每个 StateBus case 尽可能关联 `task_metrics.json`、Planner handoff、四角色 rendered request、retrieval/replay audit、telemetry 和 result hash；无法恢复的字段显式保留为空，不推测。

计数类字段求和；比率不直接相加。446 个带 task-local prefix counter 的 case 共 `41,890 hits / 70,926 queries`，重算 hit rate 为 59.06%。原始 summary 把 per-case `vllm_prefix_observed_hit_rate` 相加，整体得到 223.31，证明该汇总字段数学上无效。

主要证据入口：

- run 状态：`summary.json`、`status.tsv`、`logs/*.log`；
- stage 汇总：`stages/*/stdout.json`；
- case 账本：`stages/*/workspaces/**/{inputs,outputs,logs}`；
- Runtime 事件：`stages/*/runtime/**/telemetry/*.jsonl`；
- compare：`runtime/benchmark_reports/*.json` 和 `latency_repeat_summary.json`；
- 代码位置由分析脚本在当前 dirty working tree 中重新定位，行号不是历史 commit 的永久坐标。

## 3. 16-Stage 结果

| Stage | 状态 | 实际范围 | 质量/关键结果 | 最强可支持声明 | 不能支持 |
| --- | --- | --- | --- | --- | --- |
| 00 preflight | PASS | 4 项配置/依赖/device 检查 | 4/4 ready | Qwen3、embedding 依赖/模型、CUDA:1 配置可用 | 端到端任务成功 |
| 01 pytest v2 | PASS | v2 tests | 308 passed，100 warnings | 捕获环境中的代码回归通过 | live 性能或无 warning |
| 02 compare | PASS | 25 StateBus + 25 external，5 family | 双侧 25/25 quality | 第一轮系统级等质量 compare | carrier-only 因果归因 |
| 03 replay | FAIL | 25 bootstrap + 25 L3 target | target 25/25；15 exact、10 validated | exact restore 和真实下游减算 | 当前 launcher/LLM/restore 指标正确 |
| 04 CSV continuous | PASS | 10 rounds x L0-L3 | 40/40 | history artifact/strategy lineage | artifact reuse 等于少调用 Agent |
| 05 cross-period | PASS | 10 rounds x L0-L3 | 40/40；L3 4 validated | 连续依赖和 validated reuse | validated replay 跳过四角色 |
| 06 formal | PASS | 25 cases x 5 family x L0-L3 | 100/100 | fixed registry 上的 layer 路径和质量 | 所有 layer 都是单变量消融 |
| 07 subprocess UDS | PASS | 同 25 x 4 layers | 100/100 | subprocess + AF_UNIX + typed Protobuf 路径可运行 | 稳定 overhead/speedup |
| 08 genericity | FAIL | 4 primary + 4 original + 8 ablation | 16/16 quality；3/4 model paraphrase equivalent | bounded Planner objective 被消费和扰动 | free-text spec compilation 泛化 |
| 09 prefix shared | PASS | 5 serialized requests | 1,372/1,762 hits；5/5 contract | engine-local shared-prefix hit | StateBus E2E 加速 |
| 10 prefix independent | PASS | 5 salted requests | 0/1,805 hits；0/5 contract | independent salt 消除 block hit | 与 Stage 09 输出质量等价 |
| 11 carrier compare | PASS | 同主线 L0 text vs L1 typed，25+25 | 双侧 25/25 | typed control bytes 更少 | external superiority 或 UDS/SHM 单变量 |
| 12 compare repeat 2 | PASS | 25+25 serialized | 双侧 25/25 | 第二次 token 结果 | latency 优势 |
| 13 compare repeat 3 | PASS | 25+25 serialized | 双侧 25/25 | 第三次 token 结果 | latency 优势 |
| 14 latency aggregate | PASS | 聚合 3 个不同 stage | 3/3 comparison valid | token 稳定，latency 三轮不利 | StateBus 更快 |
| 15 tag audit | PASS | 当前源码 vs 历史 tag | 静态 diff 完成 | 选定实现差异存在 | 历史 tag 在当前环境的运行结果 |

Formal registry 的 25 case 分布为 financial 8、trend 5、join 5、aggregation 4、anomaly 3。workspace 内 Runtime task family 归并为 3 类，不能用它替代赛题口径的 5 个 registry family。

## 4. Layer、Family 和 Case 统计

Stage 06 loopback formal：

| Layer | Quality | Prompt token | Total token | Task ms | Control bytes | Semantic transfer/SHM publish | Replay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| L0 | 25/25 | 85,915 | 97,242 | 882,473 | 42,926 | 0 / 0 | disabled |
| L1 | 25/25 | 87,915 | 98,492 | 822,370 | 10,936 | 0 / 0 | disabled |
| L2 | 25/25 | 44,421 | 54,867 | 815,174 | 11,545 | 25 / 25 | disabled |
| L3 | 25/25 | 44,421 | 54,867 | 764,779 | 12,595 | 25 / 25 | enabled，无 history match |

L3 相对 L0 为 prompt `-41,494`、total `-42,375`、control bytes `-30,331`、task time `-117,694 ms`。主要 token 差发生于 L1 到 L2，但这一跳同时启用 semantic pruning 和 semantic-state transport，不能把收益只归给 shared memory。L2 到 L3 在 formal cold history 下 token 完全相同，不能作为 replay 收益证据。

Stage 04/05 的 L3 连续任务：

| Family | Rounds | Quality | Prompt/Total | Memory match | Artifact/strategy reuse events | Validated/Exact | Skip/Reuse gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CSV | 10 | 10/10 | 20,811 / 24,817 | 16 | 21 / 7 | 0 / 0 | 0 / 0 |
| cross-period | 10 | 10/10 | 21,452 / 25,820 | 18 | 16 / 3 | 4 / 0 | 4 / 4 |

两个 continuous runner 都让 L0-L3 看见 history roots；L0-L2 只是抑制 replay 指标，不构成严格 no-history baseline。因此 continuous 的层间比较只可作诊断，正式 memory claim 只采用 L3 的 lineage/replay 事实。

## 5. Stage 03 失败根因

### 5.1 Case 级闭环

25 个 target 全部有独立 `_history_bootstrap/<task_id>` source，质量 25/25，output hash 25/25 验证通过。分类和实际调用完全一致：

| Replay class | Cases | Planner requests | Retriever/Executor/Summarizer requests | Skip | Output restoration |
| --- | ---: | ---: | ---: | ---: | --- |
| exact replay | 15 | 15 | 0 / 0 / 0 | 15 x 2 | 15/15 与 bootstrap output 在去除 restore 元数据后相同 |
| validated replay | 10 | 10 | 10 / 10 / 10 | 10 x 1 | 重新执行，不计 direct restoration |
| 合计 | 25 | 25 | 10 / 10 / 10 | 40 | 15 verified restores |

因此 `skipped_step_count=40` 与 replay class 规则一致，实际 rendered request 数为 `15 x 1 + 10 x 4 = 55`。它证明 exact replay 确实减少 45 个下游角色请求；不能把 validated 的 `skip=1` 自动解释成少一次 Agent 调用。

### 5.2 失败 gate

[run_v2_full_qwen3_container.sh](/home/qcrs/statebus/project/scripts/run_v2_full_qwen3_container.sh:245) 在确认 exact+validated 覆盖 25 后仍调用 `require_role_calls(payload, selected)`，要求四角色各为 25。实际 Retriever/Executor/Summarizer 各 10 正是 15 个 exact replay 的目标行为。故 Stage fail 的主因是陈旧 launcher gate，不是质量或 replay capability 失败。

### 5.3 两个观测冲突

- [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2883) 在 exact restore 时把 `llm_call_count` 写成 0，但 Planner 仍实际请求且有 prompt/completion tokens。telemetry 记录 40 次 LLM，rendered artifacts 为 55 次，少计 15。
- [driver.py](/home/qcrs/statebus/project/v2/runtime/driver.py:1241) 将 `answer_restoration_replay_count` 固定为 0；它与 15 个 `artifact_reuse_count`、restore marker、source/target equality 冲突。

最终定性：Stage 03 是“真实能力成功 + gate 缺陷 + 指标缺陷”，不是 replay 真实性失败。

## 6. Stage 08 失败根因

### 6.1 Taint 误报

taint audit 扫描 16 个 task、64 个 role request。48 条 violation 全是：

| Role | Kind | Key | Count |
| --- | --- | --- | ---: |
| Retriever | `unexpected_role_payload_keys` | `sp` | 16 |
| Executor | `unexpected_role_payload_keys` | `sp` | 16 |
| Summarizer | `unexpected_role_payload_keys` | `sp` | 16 |

`sp` 的实际值只有 `contract=statebus-shared-prefix-v1`、`contains=hydrated_evidence` 和 byte length，由 [role_path.py](/home/qcrs/statebus/project/v2/runtime/role_path.py:374) 生成。它不包含 expected answer、route、tool、preferred candidate 或 scorer 信息。genericity 的 allowlist 在 [run_v2_genericity_holdout.py](/home/qcrs/statebus/project/scripts/run_v2_genericity_holdout.py:73) 仍只允许旧键，故 48 条是同一 schema 演进遗漏的重复误报。

no-hint 检查中 preferred candidate match 为 0；枚举的 3,282 个 role-visible surface 未发现 forbidden literal field。这个结果降低了显式 oracle 风险，但不是对同义答案或模板特化的形式化证明。

### 6.2 真实 Planner 漂移

4 个 primary 均 quality pass、route hints=0、plan valid、behavioral effect=true，16/16 Retriever consumed hash 匹配。disabled 和 perturbed 各 4/4 quality pass，前者全部回到 `runtime_fallback` 且 behavioral effect=false，后者全部改变 effective/consumed hash 且 behavioral effect=true；route/tool 保持不变。

original/paraphrase 中仅 `formal-agg-004` 的 model plan 不等价：一侧 model `required_outputs=[monthly_avg_windspeed]`，另一侧多出 `groupby_artifact_ref`。Runtime merge 后两侧 effective outputs 都是 `[monthly_avg_windspeed, groupby_artifact_ref]`，所以最终质量和执行合同一致。这是真实的模型层 paraphrase instability，被 fallback 安全屏蔽；不应与 taint 误报合并成一个 capability failure。

[run_v2_genericity_holdout.py](/home/qcrs/statebus/project/scripts/run_v2_genericity_holdout.py:583) 把 taint pass 纳入总 gate，[同文件](/home/qcrs/statebus/project/scripts/run_v2_genericity_holdout.py:585) 又要求 4/4 model semantic equivalence，所以两项都能令 stage fail。正确报告应分别输出 model-plan stability diagnostic 与 effective-contract safety gate。

### 6.3 声明边界

Stage 08 使用预编译 `CanonicalTaskSpec`，代码入口见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:1874)。它证明 bounded plan 在固定合同下可被生成、merge、消费和扰动；不证明自由文本能够编译出完整、正确的新任务合同。

## 7. External Compare 和三轮时延

三轮都覆盖相同 25 case/5 family、同 Qwen3-32B、同四角色数量、同 quality/scorer/history policy，external fairness hard gate 75/75 通过，双侧质量均为 75/75。

| Repeat | StateBus/External quality | Prompt delta | Total delta | StateBus faster cases | Task time delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stage 02 | 25/25 / 25/25 | -27,074 | -23,567 | 8/25 | +37,737.9 ms |
| Stage 12 | 25/25 / 25/25 | -27,119 | -23,603 | 3/25 | +214,354.2 ms |
| Stage 13 | 25/25 / 25/25 | -27,091 | -23,439 | 2/25 | +221,222.4 ms |

total token delta 均值为 -23,536.3，标准差 70.38；prompt delta 均值 -27,094.7，标准差 18.55。token 结果跨 repeat 非常稳定。StateBus 每轮 25/25 prompt 更低，但 total token 每轮仅 17/25 更低，financial family 的 completion overhead 会抵消部分 prompt 收益。

公平性仍有限：两侧 prompt、Planner selection schema、evidence exposure 和执行实现不是 carrier-identical。三轮固定 `serialized_statebus_then_external_within_each_mode_v1`，未做 AB/BA 顺序控制。结论只能是系统级 compare；若继续讨论 latency，需要交替顺序并给出 median/p90/p95，当前 run 已明确否定 latency superiority。

## 8. L0-L3 消融解释

- L0：text collaboration、无 semantic pruning、无 replay。
- L1：typed structured control、无 semantic pruning、无 replay。
- L2：typed control + semantic pruning + SemanticState shared-memory publish/transfer。
- L3：L2 机制 + replay stack；是否产生 reuse 取决于 history。

L0 到 L1 同时改变 carrier、prompt scaffolding 和编码，不是纯 Protobuf 单变量；L1 到 L2 同时改变 pruning 与 semantic state transport；formal L2 到 L3 没有 history reuse。故 formal ladder 可证明各 profile 可运行及结果相关性，不能为所有机制分别给出因果效应。

Stage 11 是更接近 carrier attribution 的同主线 L0/L1 compare：两侧 25/25 quality，visible evidence bytes 相同；typed 相对 text control bytes `-30,590`，task time `-188,725.8 ms`，但 prompt tokens `+1,994`、total tokens `+1,213`。它支持“typed control 降低控制字节”，不支持“typed carrier 降低总 token”，更不是 UDS/shared-memory transport compare。

## 9. 四个 Agent 的真实贡献

| Agent | 被调用/生成/保存 | 下游消费证据 | 行为或减算证据 | 边界 |
| --- | --- | --- | --- | --- |
| Planner | 非 exact case 正常请求；exact case也请求 | 446 个目标 case 中 1,784 个四路 consumed hash match | Stage 08 disabled/perturbed 改变 objective hash；exact 不跳 Planner | fallback 参与较多，不能只按 call count 归功 |
| Retriever | 非 exact case请求并产生 selected evidence | consumed objective hash 与四类 plan objective闭环 | pruning 改变 prompt；exact 15 case 完全跳过 | selected evidence 很大部分由固定 pipeline/metadata 约束 |
| Executor | 非 exact case请求，执行 route/tool/CodeAct合同 | 消费 hydrated evidence、route/tool闭集 | exact 15 case 跳过且恢复 output | deterministic helper 和 fallback 仍承担执行正确性 |
| Summarizer | 非 exact case请求并提交 summary/memory | continuous 后续轮有 artifact/strategy lineage | exact 15 case跳过；连续任务存在后续消费 | quality 对移除 Summarizer 没有独立 A/B |

四角色调用均为 1 只能证明参与；Stage 08 ablation 和 Stage 03 exact replay 才分别提供 Planner 行为变化与三下游真实减算证据。

## 10. Planner 专项

446 个非 bootstrap/非 exact-restore 目标 case 的 Planner 汇总：432 个 `hybrid`、14 个 `runtime_fallback`；436 个 plan valid/equivalent，10 个 validation-error case；7,728 个 model-generated fields，5,659 个 fallback fields，5,500 个 model fields 被下游消费，432 个 case 记录 behavioral effect。

这些数字不能简化为“Planner 完全自主生成计划”。effective plan 由 [semantic_plan.py](/home/qcrs/statebus/project/v2/runtime/semantic_plan.py:512) 将模型字段与 Runtime fallback/allowlist 合并；route/tool、workflow、required output enum 仍由 Runtime闭集保护。`formal-agg-003` 等 validation error 会 fail closed 到 fallback。

四类 Retriever 在 [pipeline.py](/home/qcrs/statebus/project/v2/retrieval/pipeline.py:219) 落盘实际 `consumed_objective_hash`，使 model/fallback/effective/consumer 链可以逐 case复核。Stage 08 证明目标内容可改变，但 disabled/perturbed 后质量仍全部通过，也说明当前 fixed cases 对 Planner objective 的结果质量不敏感；“有行为贡献”不能升级为“已证明质量收益”。

## 11. Semantic State、KV Prefix 和 LogitState

### 11.1 Semantic State

Stage 06 的 L2/L3 各有 25 次 shared-memory publish 和 25 次 semantic-state transfer，下游 hydrated artifacts 与质量完整。它证明 embedding/dense semantic state 走了非文本 ref 数据面。由于 L1 到 L2 同时启用 pruning，当前只能把 token 降低归为组合机制，不能单独量化 shared memory 的收益。

### 11.2 Engine-Local Prefix Reuse

Stage 09 shared：`1,372/1,762=77.87%` block hits，5/5 completion contract valid，warm TTFT mean 374.59 ms。Stage 10 independent：`0/1,805` hits，warm TTFT mean 2,378.48 ms，但 completion contract 0/5 valid。两者证据文件相同、prompt bytes 接近，却只有一次 shared-first pair，并且输出合同不等价。

因此真实成立的是“同一 vLLM engine 的 shared prefix 能产生 block reuse”；TTFT 差只能作为 diagnostic，不能形成稳定 causal/E2E claim。这里没有 KV tensor 从 StateBus 导出、持久化或跨 Agent传输。

正式 case summary 的 rate 还存在聚合 bug：例如 Stage 06 L1 per-case rate sum 为 17.18，而 `sum(hits)/sum(queries)=4,061/5,453=74.47%`。所有正式 rate 应使用 numerator/denominator 重算。

### 11.3 LogitState

431 个 case 有 LogitState：entropy 均值 0.2568、top gap 均值 0.8426、varentropy 均值 0.00447；431/431 peak 都在最后 token 之前。原始 top-logprobs 未持久化，无法离线重算 comparator；`logit_confidence_gate_trigger_count=0`。

它是 top-logprobs 派生的 compact decision summary，不是 hidden state 或 KV。当前证据级别是非文本决策侧信道和可观测性原型，没有证明它改变 route、tool、retry、evidence 或质量。

## 12. Memory、Replay 和连续任务

必须区分 memory match、assist reuse、artifact/strategy reuse、validated replay、exact replay、output restoration 和真实 call reduction。

- Stage 03：25 memory matches 最终分成 15 exact + 10 validated；exact 直接恢复 verified output 并跳过三个下游角色，validated 仍执行四角色。
- CSV L3：16 memory matches、21 artifact events、7 strategy events，但无 exact/validated、无 skipped steps、`reuse_gain=0`。这是 lineage/assist，不是计算跳过。
- cross-period L3：18 memory matches、16 artifact events、3 strategy events、4 validated、4 skip/reuse gain；四角色仍各调用 10 次，所以 validated 的 skip 不等价于 Agent call reduction。

Stage 03 bootstrap/target 目录和 source markers 未发现跨 stage 污染。exact source 与 target 是同 task/spec/evidence identity，适合证明确定性 replay，不能外推成相似问题的泛化复用。

## 13. Formal、UDS、Carrier 和 CodeAct

Stage 06/07 对应 100 个 layer/case pair 的 quality、prompt token、output hash 全部相同。代码路径包含 [transport.py](/home/qcrs/statebus/project/v2/control/transport.py:61) 的 `AF_UNIX` 和 [transport.py](/home/qcrs/statebus/project/v2/control/transport.py:377) 的 `subprocess.Popen`。Stage 07 `stdout.transport=subprocess`，200 个 Runtime JSONL 存在，但 PID/socket/transport lifecycle 字段命中为 0。

单次 pair 中 subprocess task time 相对 loopback 总和 `-217,551.5 ms`，中位 delta `-2,654.9 ms`。这更可能混有服务负载/顺序效应，repeat=1 时不能称 subprocess speedup，也不能精确归因 UDS overhead。

Stage 11 的 carrier 结论见第 8 节。Formal CodeAct 的 `bwrap=0`，resource fallback 覆盖所有 audited cases；可以称 bounded execution prototype，不能称强安全 sandbox。最终交付还需做 filesystem/network negative tests。

## 14. 泄露、特化和实验漏洞

扫描 471 份 `CanonicalTaskSpec`、471 份 Planner handoff、1,884 个 prompt slice、456 个 CodeAct bundle，共 3,282 个 role-visible surface。列举的 forbidden field literal match 为 0，源码扫描未发现 literal case-id branch。

这不等于没有强先验。角色仍能看到 `intent_op`、required tools/outputs、target/time scope 和部分 quality checks；它们属于预编译 typed contract，合理但显著降低开放式理解难度。route hints 开启时还存在由 intent/top candidate 派生的闭集先验。Stage 08 关闭 route hints 且 preferred candidate 未进入 prompt，是更强的无显式 hint 证据。

主要实验漏洞是：

- external 两侧并非 carrier-identical，只能做系统级比较；
- compare 固定 StateBus-first，latency 无顺序控制；
- continuous L0-L2 仍看见 history roots；
- prefix shared/independent 只有一个 shared-first pair，且 completion contract 不等价；
- fallback 保住 quality，必须同时报告 model 与 effective plan；
- prefix rate 被错误求和；
- Stage 03 gate 和 call/restoration metrics 与真实执行矛盾。

没有证据表明存在固定答案直接注入角色 prompt；但基于固定 registry、预编译 spec 和 deterministic fallback 的成功，不能包装成开放域自主 Agent 泛化。

## 15. 赛题覆盖和创新证据

证据等级：1=代码存在，2=路径执行，3=产生真实数据，4=下游消费/改变行为，5=公平 A/B 证明收益。

| 赛题/创新 | 等级 | 本次证据 | 主要缺口 |
| --- | ---: | --- | --- |
| >=3 Agent / >=3 task type | 4 | 四角色、5 registry family；Planner ablation、exact skip | 非每个角色都有独立移除 A/B |
| typed Protobuf control | 4 | L0/L1 control bytes、Stage 07 UDS | external 非 carrier-only |
| Ref registry/多数据面 | 4 | control/state/artifact refs 落盘并 hydrate | 机制独立收益未全部隔离 |
| SemanticState shared memory | 4 | L2/L3 publish/transfer/consume | 与 pruning 捆绑 |
| CanonicalEvidencePack/HydrateManifest | 4 | evidence identity、hydrate、replay gate | 缺独立 A/B |
| bounded SemanticTaskPlan | 4 | 四 objective hash、disabled/perturbed | free-text spec compilation 未测 |
| dynamic evidence pruning | 4 | L1->L2 token 大降且质量不变 | 与 semantic state捆绑 |
| engine-local prefix | 4 | shared hits、independent 0 hit | 单 pair、合同不等价、非 E2E |
| LogitState | 3 | 431 个真实摘要 | gate 0 trigger，无行为收益 |
| memory/exact replay | 4 | 15 verified restore + 三下游跳过 | metric/gate 待修、无 latency A/B |
| subprocess UDS | 3 | 100 case路径成功 | lifecycle telemetry 和 repeats 缺失 |
| bounded CodeAct | 3 | formal执行、deterministic validation | 全部 resource fallback，无强 sandbox |
| openEuler delivery | 1 | 目标和 compose 路径存在 | 本 run 未验证 |

竞赛评分上最强的是状态传递、记忆复用和系统完整性；最易被质疑的是性能归因、prefix 输出等价性、Planner free-text 边界、sandbox 与 openEuler delivery。不能据此伪造确定分数。

## 16. 当前可宣称与不可宣称

最新实验已证明：

- 16 个计划 stage 全部有记录，最终 14 pass、2 fail；
- 三轮同任务、同质量门的系统级 compare 有稳定 token 节省；
- exact replay 恢复 verified output，并跳过 Retriever/Executor/Summarizer；
- bounded Planner objective 被四类 Retriever 消费且可被 ablation 改变；
- SemanticState shared-memory 路径和 subprocess UDS 路径真实执行；
- shared prefix 在同一 vLLM engine 内产生 block hit，independent salt 为 0 hit。

只有 proxy/diagnostic：single-pair TTFT、`neural_prefix_*` estimate、service-lifetime gauge、LogitState entropy、tag source diff、单次 subprocess timing。

当前不能宣称：full matrix passed、StateBus latency superiority、external token delta 的 carrier-only attribution、free-text `CanonicalTaskSpec` compilation、跨 Agent KV/hidden-state handoff、安全 sandbox、openEuler 已验证。

## 17. P0/P1/P2 问题清单

共 11 项：P0 4、P1 5、P2 2。完整逐项方案见 `47_failure_root_cause_and_optimization_plan_20260714.md`。

| Priority | 问题 | 影响 |
| --- | --- | --- |
| P0 | replay gate 要求 exact case 下游仍调用 | Stage 03 假失败 |
| P0 | exact replay `llm_call_count=0` 忽略 Planner | 夸大 LLM 减算 15 次 |
| P0 | taint allowlist 不认识合法 `sp` | Stage 08 假失败 48 次 |
| P0 | prefix hit rate 按 case 求和 | formal rate 数学无效 |
| P1 | `formal-agg-004` model paraphrase 漂移 | Planner 稳定性仅 3/4 |
| P1 | independent prefix 0/5 completion contract | TTFT 对照无质量等价 |
| P1 | compare 固定顺序且三轮更慢 | 禁止 latency superiority |
| P1 | answer restoration metric 固定 0 | exact restore 观测假阴性 |
| P1 | CodeAct 全部 resource fallback | 不能宣称强 sandbox |
| P2 | 空 `vllm_health.json` | provenance/解析噪声 |
| P2 | 100 protobuf deprecation warnings | 交付噪声和未来兼容风险 |

## 18. 最小修复范围

不改变 Planner/Runtime 架构，只修合同和观测：

1. replay gate 按 class 计算期望调用：Planner=25，下游=validated/cold 实际执行数；同时继续硬验 output hash、restore marker、quality 和 skip。
2. `llm_call_count` 从 rendered/per-role calls 聚合，exact case计 Planner=1；`answer_restoration_replay_count` 只在 verified restore 完成后置 1。
3. taint scanner 对下游角色允许严格 schema 的 `sp={contract,contains,bytes}`，其他键、错误 contract、额外字段仍 fail closed。
4. prefix summary 使用 `sum(hit_delta)/sum(query_delta)`；禁止 rate 累加。
5. model-plan equivalence 与 effective-contract safety 分开报告，不用 fallback 的成功掩盖模型漂移。
6. prefix probe 要么强制两侧 100% 同一 completion contract，要么使用不依赖生成内容的 probe；做交替顺序多 pair。

本轮按审计约束没有实施以上修复。

## 19. 最小验证矩阵

建议顺序：

1. 静态/单元测试：mixed exact/validated replay gate、exact call metrics、verified restoration、严格 `sp` schema、ratio aggregation。
2. 只重跑 Stage 03，要求 25/25 quality、exact/validated 分类、rendered request、telemetry call、restore metric 和 source equality 全部一致。
3. 只重跑 Stage 08，分别输出 model/effective paraphrase 结果，要求 taint 0 false positive 且 oracle negative tests 仍可拦截。
4. prefix 做至少 4 对 shared/independent，AB/BA 交替，所有 request completion contract 等价，再报告 paired TTFT 和 block counters。
5. 只有仍需 latency claim 时，才做 external compare AB/BA serialized repeats；保留 token 与 latency 两套独立结论。
6. P0/P1 通过后再跑 16-stage full matrix；openEuler delivery 另做独立验证。

## 20. 是否需要重跑

当前不需要立刻重跑完整矩阵。Stage 03/08 根因已由现有 artifact 闭环，先修 P0 并跑两个单 stage 最省成本。prefix 需要 targeted paired matrix，不应靠 full matrix 中单个 Stage 09/10 pair解决。只有定向验证全部通过、报告字段一致后，才值得投入新的 full matrix 作为 contest-facing final evidence。

本报告完成后应暂停，等待用户确认实际修复范围；不得把审计建议自动解释为修改 Runtime、gate 或测试的授权。

## 21. 复现

结构化账本可由以下只读命令重建：

```bash
/home/qcrs/statebus/conda-envs/statebus_host/bin/python \
  scripts/analyze_full_qwen3_extended_matrix_20260714.py \
  /home/qcrs/statebus/runs/full_qwen3_extended_gpu1_20260714_135500 \
  --output docs/improvement/20_v2_comprehensive_truth_audit_20260706/46_full_qwen3_extended_matrix_audit_20260714.json
```

JSON 的 `cases.statebus` 保存 471 个完整 case ledger，`cases.external_compare_repeats` 保存 75 个 external case；Markdown 只呈现能够审阅的聚合和异常，不复制 5.5 MB 明细。

# StateBus v2 失败根因与最小优化方案

日期：2026-07-14

事实账本：`46_full_qwen3_extended_matrix_audit_20260714.json`

配套审计：`46_full_qwen3_extended_matrix_audit_20260714.md`

状态：只完成静态根因分析；尚未修改 Runtime、Planner、gate 或测试

## 1. 结论和范围

最新 full matrix 的两个 fail 应拆成五个不同性质的问题：

```text
Stage 03 fail
├── 主因：launcher 仍要求 exact replay 的三个下游角色执行
├── 计量：exact replay 的 Planner 请求未计入 llm_call_count
└── 计量：verified output restoration 被固定记录为 0

Stage 08 fail
├── 主因：taint allowlist 未跟随合法 sp shared-prefix 合同演进
└── 真实诊断：formal-agg-004 的 model plan 有一次 paraphrase 漂移
    └── Runtime fallback 补齐 effective contract，未造成质量/route/tool 失败
```

修复目标不是“放宽 gate 让矩阵变绿”，而是让 gate 对准真实合同，让 metric 与实际请求/恢复一致，并继续保留质量、hash、oracle、route/tool 和 output verification 的硬约束。

问题账本共 11 项：P0 4、P1 5、P2 2。P0 修复后只需先重跑 Stage 03/08；prefix 和 latency 采用独立 targeted matrix；最后才决定是否重跑 full matrix。

## 2. 设计原则

1. gate 从 replay class、实际请求和 verified artifact 推导期望，不写固定四角色次数。
2. 行为 metric 从发生的事件或 persisted request 推导，不从“理论上应该跳过”反推。
3. taint policy 采用按角色、按 schema、按值的 allowlist；允许合法合同不等于允许任意新键。
4. model plan 与 effective plan 分开打分；fallback safety 不能抹掉模型 instability。
5. rate 只由 numerator/denominator 聚合；estimate、observed counter、service gauge 各自独立。
6. latency 必须有输出合同等价、AB/BA 顺序控制和重复；否则只作 diagnostic。
7. 修复不改变固定四角色拓扑、route/tool 闭集、CanonicalTaskSpec、replay identity 或 scorer。

## 3. P0-1：Replay Gate 拒绝正确的 Exact 减算

**现象**

Stage 03 报 `replay gate failed: L3 retriever calls 10/25`。实际 25/25 quality pass，15 exact、10 validated；exact 的 Retriever/Executor/Summarizer 均为 0，validated 均为 1。

**根因**

[run_v2_full_qwen3_container.sh](/home/qcrs/statebus/project/scripts/run_v2_full_qwen3_container.sh:245) 在确认 `exact+validated=selected` 后仍调用通用 `require_role_calls(payload, selected)`，沿用“每 case 四角色均调用”的旧假设。该假设与 exact replay 的定义冲突。

**Artifact 证据**

- `stages/03_replay_full/stdout.json`：exact=15、validated=10、quality=25、skip=40、下游 calls=10；
- `logs/03_replay_full.stderr.log`：精确失败消息；
- 15 个 exact `logs/task_metrics.json`：Planner=1、其余三角色=0；
- 10 个 validated case：四角色均=1；
- 15 个 exact target output 在去除 `restored_from_memory_id/restored_replay_class` 后与 bootstrap output 相同。

**影响**

造成 false full-matrix failure，并可能诱导错误修复为“exact replay 也执行下游 Agent”，从而直接破坏真实减算。

**最小修复**

在 replay stage gate 中按 persisted replay class 计算：

```text
expected_planner = selected
expected_downstream = validated_replay + cold_or_disallowed_execution
expected_exact_downstream = 0
```

同时保留：25/25 quality、replay coverage、exact source/target compatibility、verified output hash、restore marker、skipped steps 和 artifact reuse 一致性。若 stage 合同明确只允许 exact/validated，则 `expected_downstream=validated_replay_count`。

**回归风险**

只按聚合 class count 校验，可能漏掉某个 exact case误调用、另一个 validated case少调用后聚合抵消。必须增加 per-case gate，不能只修总数。

**最小测试**

- unit：1 exact + 1 validated，Planner=2、下游=1，pass；
- negative：exact 下游任一角色=1，fail；
- negative：validated 任一角色=0，fail；
- targeted Stage 03：25 个 case逐案 class/calls/output restoration 全部闭环。

## 4. P0-2：Exact Replay 少计 Planner LLM Call

**现象**

Stage 03 telemetry `llm_call_count=40`，但实际 rendered requests 为 55：25 Planner + 10 x 3 下游。15 个 exact case都有 Planner request 和 Planner tokens，却各记录 `llm_call_count=0`。

**根因**

[smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2883) 使用 `0.0 if replay_restore_enabled else 4.0`。它把“跳过三个下游角色”错误简化成“跳过所有 LLM”。同一 metrics block 已正确保留 `planner_call_count=1`，内部自相矛盾。

**Artifact 证据**

- `stages/03_replay_full/workspaces/L3/benchmark-sample-1/logs/task_metrics.json`：Planner=1、LLM=0、Planner tokens非零；
- 同 workspace `logs/rendered_llm_requests/planner.rendered_request.json`：1 个 request；
- 15 个 exact case一致；全 stage rendered=55、recorded=40。

**影响**

夸大 exact replay 的 LLM request reduction 15 次，并污染 cost、latency decomposition 和 Agent contribution 结论。

**最小修复**

优先由四角色实际 request/call count 求和：

```text
llm_call_count = planner + retriever + executor + summarizer
```

如果 Runtime 还存在额外 verifier/retry，则从统一 request event ledger 聚合，避免再次硬编码 1/4。

**回归风险**

`call_count` 与 HTTP attempt/retry 的口径可能不同。修复前先明确它表示 logical role call 还是 physical model request；本报告建议 headline 同时保留两者，现有字段采用 persisted rendered request 数。

**最小测试**

- exact：Planner=1、下游=0、LLM=1；
- validated/cold：四角色均=1、LLM=4；
- retry case：logical calls和physical requests分别断言；
- metrics 总数与 rendered artifact 数一致。

## 5. P0-3：Genericity Taint Allowlist 对合法 `sp` 误报

**现象**

64 个 role request 中记录 48 个 violation：Retriever、Executor、Summarizer 各 16 个，全部为 `unexpected_role_payload_keys=[sp]`。

**根因**

[role_path.py](/home/qcrs/statebus/project/v2/runtime/role_path.py:374) 在 shared evidence prefix 被抽到公共前缀后，用 `sp` 在 suffix 中声明 bounded metadata；[run_v2_genericity_holdout.py](/home/qcrs/statebus/project/scripts/run_v2_genericity_holdout.py:73) 的角色策略仍只允许旧的 `e` 等键，没有同步 schema。

合法 `sp` 只有：

```json
{
  "contract": "statebus-shared-prefix-v1",
  "contains": "hydrated_evidence",
  "bytes": 12345
}
```

它不包含 answer、route、tool、candidate、expected fact 或 scorer 数据。

**Artifact 证据**

- `stages/08_genericity_holdout/stdout.json.prompt_taint_audit`：48/48 同类；
- 16 x 3 个 rendered request 中 `sp` schema和值均验证通过；
- `preferred_candidate_match_count=0`、no-hint check pass。

**影响**

Stage 08 假失败，并把真正的单个 paraphrase model drift 淹没在 48 个重复噪声中。

**最小修复**

对 Retriever/Executor/Summarizer 允许 `sp`，但做完整值校验：key 集必须恰为 `{contract,contains,bytes}`；contract 和 contains 必须是固定 enum；bytes 必须是非负整数并与实际 shared prefix UTF-8 length一致。Planner 当前不需要 `sp`，继续禁止。

violation 输出按 `(role, kind, key, normalized_value)` 分组，保留 occurrence count，避免把 schema 漏项写成 48 个独立泄露。

**回归风险**

若只把 `sp` 加进 allowed keys 而不验值，攻击性 payload 可借该容器携带 oracle。因此必须是 typed schema allowlist，不是键名豁免。

**最小测试**

- accept：三个下游角色的精确 `sp` 合同；
- reject：额外 `answer/route/tool/candidate` 子键；
- reject：错误 contract、contains、负数/字符串 bytes；
- reject：Planner 带 `sp`；
- targeted Stage 08：taint 0 violation，同时已知 oracle fixture 仍 fail。

## 6. P0-4：Observed Prefix Rate 被按 Case 求和

**现象**

正式 summary 中 `vllm_prefix_observed_hit_rate` 可大于 1。Stage 06 L1 为 17.18，实际 `4,061 hits / 5,453 queries = 0.7447`；446 个 case 的 reported rate sum 为 223.31，实际整体为 0.5906。

**根因**

[fixed_answer_runner.py](/home/qcrs/statebus/project/v2/benchmark/fixed_answer_runner.py:748) 先对所有 case metric 无差别求和；[metric_aggregation.py](/home/qcrs/statebus/project/v2/benchmark/metric_aggregation.py:8) 只重算 `neural_prefix_*_estimate`，没有重算 `vllm_prefix_observed_hit_rate`。

**Artifact 证据**

- `stages/06_formal_full/stdout.json.layers[].telemetry_summary`；
- JSON `prefix_case_metrics.aggregate_rate_bug_groups`：94 个 stage/layer/family group 中 80 个 rate sum异常；
- 446/446 task-local delta available/valid。

**影响**

prefix headline 数学无效，可能把 74% 写成 1,718%，影响 formal、continuous、compare 和评审可信度。

**最小修复**

在统一 finalizer 中加入：

```text
observed_rate = sum(vllm_prefix_observed_hit_delta) /
                sum(vllm_prefix_observed_query_delta)
```

无 query 时返回 0 或 unavailable，但必须与 case-level availability/validity count一起报告。禁止对 rate、ratio、mean、percentile做通用 additive aggregation。

**回归风险**

只修 fixed-answer runner 会遗漏 continuous/comparator 的其他聚合入口。应让所有 runner 共用一个 non-additive metric registry/finalizer。

**最小测试**

- 两 case：1/2 和 9/10，聚合应为 10/12，不是 1.4；
- rate 始终在 `[0,1]`；
- query=0、unavailable、invalid delta分别覆盖；
- Stage 06 静态 fixture重算值与脚本一致。

## 7. P1-1：`formal-agg-004` Model Plan Paraphrase 漂移

**现象**

4 个 original/paraphrase 对仅 3/4 model semantic equivalent。`formal-agg-004` 一次模型输出只有 `monthly_avg_windspeed`，另一次还含 `groupby_artifact_ref`。

**根因**

模型在 paraphrase 下对 bounded required outputs 不稳定；[semantic_plan.py](/home/qcrs/statebus/project/v2/runtime/semantic_plan.py:144) 的比较器正确发现 `required_outputs_equal=false`。这不是 hash bug或比较器过严。随后 [semantic_plan.py](/home/qcrs/statebus/project/v2/runtime/semantic_plan.py:512) 用 registered fallback 补齐两侧 effective contract。

**Artifact 证据**

- `stages/08_genericity_holdout/stdout.json.paraphrase_semantic_equivalence.formal-agg-004=false`；
- `planner_facts` 中 original/primary model/effective required outputs；
- 两侧 effective outputs 相等，quality、route、tool 均通过。

**影响**

不能声明 Planner model 在本轮 4/4 paraphrase stable；但 Runtime capability 和安全执行合同没有失败。

**最小修复**

先修报告和 gate，而不是扩大模型权限：分别记录 `model_semantic_equivalence` 和 `effective_contract_equivalence`。前者作为稳定性 quality floor/diagnostic，后者作为 Runtime safety hard gate。若竞赛要求 model 4/4，则通过更明确的 enum/schema提示和小规模重复提高稳定性，但 fallback仍保留。

**回归风险**

把 model drift 降为纯 warning 可能掩盖长期退化；把 effective fallback 的成功计作 model pass又会虚报能力。两条指标必须同时保留。

**最小测试**

- fixture：model outputs不同、effective相同，分别得到 false/true；
- 4 case x 多 paraphrase seed重复，报告稳定率和具体字段；
- route/tool/quality 在 fallback后不回归。

## 8. P1-2：Independent Prefix Probe 0/5 输出合同有效

**现象**

Stage 09 shared 的 5/5 completion JSON/contract valid；Stage 10 independent 虽 HTTP 5/5 ok，但 completion JSON/contract 0/5 valid。两侧 block hits 分别为 1,372/1,762 和 0/1,805。

**根因**

当前 probe 把模型生成内容和 prefix timing绑定在一起，stage pass主要看请求/counter，而未要求 shared/independent output contract parity。[probe_local_vllm_prefix_alignment.py](/home/qcrs/statebus/project/scripts/probe_local_vllm_prefix_alignment.py:394) 已统计 validity，但 full-suite gate没有将两侧等价作为硬条件。

**Artifact 证据**

- `stages/09_prefix_shared/stdout.json`：5/5；
- `stages/10_prefix_independent/stdout.json`：0/5；
- 两侧 evidence 文件相同、bytes接近、role数均5。

**影响**

block hit机制证据仍有效，但 TTFT/E2E 比较缺少输出合同等价，不能升级为公平 causal speedup。

**最小修复**

两个选择：

1. 让两侧使用完全相同 response schema和约束，要求 100% contract valid；
2. 将 probe 改为 response-independent microbenchmark，固定生成长度/stop条件，只把 block counter和TTFT作为输出。

随后跑至少 4 对 shared/independent，顺序 AB/BA 交替，并在每对前记录 engine/service状态。

**回归风险**

过强 JSON grammar 本身可能改变 prefill/decoding时延；若采用固定生成长度，应把它明确写成 microbenchmark，而不是任务质量测试。

**最小测试**

- shared/independent 10/10 contract valid或明确 response-independent；
- 每对 prompt prefix/evidence/model/temperature/max tokens一致，仅 salt/layout变量不同；
- paired hit delta、TTFT、request order都落盘。

## 9. P1-3：External Compare 固定顺序且三轮更慢

**现象**

三轮 StateBus task time 都高于 external，delta 为 +37.7s、+214.4s、+221.2s；StateBus faster case从 8 降到3、2。三轮固定 StateBus-first。

**根因**

[comparator_runner.py](/home/qcrs/statebus/project/v2/benchmark/comparator_runner.py:670) 的 timing contract 为 `serialized_statebus_then_external_within_each_mode_v1`，没有 lane-order交替；服务负载、cache和随时间变化可能与系统开销混合。但无论顺序效应如何，本 run 都不支持 latency superiority。

**Artifact 证据**

- `latency_repeat_summary.json`：3/3 comparison valid、favorable repeat=0；
- Stage 02/12/13 benchmark reports：每 case分布和顺序合同；
- token delta同时保持高度稳定，说明 token与latency结论应拆开。

**影响**

系统级 token claim 很强，latency claim 被本 run否定；也不能通过事后选择 Stage 02 的 LLM delta来宣称整体更快。

**最小修复**

代码无需为本轮结果“修快”。先保持 `latency_superiority_claim_allowed=false`。只有业务需要 latency claim 时，新增 AB/BA lane order、warmup、至少 4-6 repeats，并报告 per-case paired median/p90/p95 和服务负载快照。

**回归风险**

过度追求 latency 可能牺牲质量、验证或可观测性。优化必须在相同 output/quality/scorer合同下评估。

**最小测试**

- AB/BA 各至少2轮；
- 每轮双侧25/25 quality和 fairness hard gate；
- order effect单独估计；
- superiority gate要求多数 repeat和置信区间，而非单次负 delta。

## 10. P1-4：Answer Restoration Metric 固定为 0

**现象**

Stage 03 有15个 exact verified restores、15个 artifact reuse和15个 restore marker，但 `answer_restoration_replay_count=0`。

**根因**

[driver.py](/home/qcrs/statebus/project/v2/runtime/driver.py:1241) 无条件写 `0.0`。真实 output restore 位于 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2325)，两者没有事件连接。

**Artifact 证据**

- 15 个 target `outputs/result.json` 含 `restored_from_memory_id/restored_replay_class`；
- source/target normalized equality 15/15；
- telemetry exact=15、artifact reuse=15、restoration=0。

**影响**

使可观测性把已验证能力写成未发生，评审时会被认为 artifact reuse 与 answer restoration 自相矛盾。

**最小修复**

仅在以下条件同时满足时记1：进入 exact restore分支、source artifact verified、target materialization成功、target hash/normalized output verification通过。validated replay保持0。

**回归风险**

在读取 source 时就提前计数，会把后续 materialization/verification失败误报为成功。metric必须在 commit/verification之后产生。

**最小测试**

- exact success=1；validated=0；
- source hash错误、copy失败、target verify失败均=0并 fail；
- stage总数必须与 restore marker、artifact reuse和normalized equality一致。

## 11. P1-5：CodeAct 只有 Resource Fallback

**现象**

formal audited cases 中 `codeact_sandbox_bwrap_count=0`，resource/fallback覆盖全部执行。

**根因**

代码支持 bwrap command构造，见 [codeact.py](/home/qcrs/statebus/project/v2/runtime/codeact.py:562)，但当前容器/host能力使 sandbox runner退到 resource backend。telemetry 在 [driver.py](/home/qcrs/statebus/project/v2/runtime/driver.py:1249) 如实记录 backend。

**Artifact 证据**

- Stage 06 每层 `sandbox_fallback_count=25`、bwrap=0；
- continuous 和 subprocess formal相同；
- 现有 run没有 negative filesystem/network isolation结果。

**影响**

可以声明 bounded deterministic execution/resource controls，不能声明强安全 sandbox或生产隔离。

**最小修复**

当前 contest文案先收紧，不强行安装系统组件。到正式 delivery环境再做 capability probe；若 bwrap 可用，验证只读 project、workspace write、网络禁用、进程/资源限制。不可用时明确 resource fallback边界。

**回归风险**

启用 bwrap可能破坏模型/数据路径、动态库和 subprocess UDS。应在 openEuler/container delivery环境独立验证，不在当前审计阶段改变执行栈。

**最小测试**

- backend capability probe；
- 允许的 workspace read/write positive test；
- project/system write、network、路径逃逸 negative tests；
- fallback 时 telemetry和文案一致。

## 12. P2-1：空 `vllm_health.json`

**现象**

27,461 个文件中唯一 JSON parse error 是零字节 `vllm_health.json`，但 Stage 00 通过其他 preflight路径证明服务 ready。

**根因**

[run_v2_full_qwen3_container.sh](/home/qcrs/statebus/project/scripts/run_v2_full_qwen3_container.sh:594) 将 `/health` body重定向到 JSON 文件；服务可返回空 body，文件名却承诺 JSON。

**Artifact 证据**

- run root `vllm_health.json`：empty/parse error；
- Stage 00 `stdout.json.ok=true`，LLM config ready。

**影响**

不推翻 run，但制造解析噪声，并使该 sidecar不能作为 health response provenance。

**最小修复**

保存 HTTP status、headers、body和timestamp的自有 JSON envelope；若只需 probe，则不要创建 `.json` 空占位。curl失败仍必须 fail closed。

**回归风险**

不能因为 body为空就把任何 2xx都视为模型 ready；仍需保留实际 model/list或小请求 preflight。

**最小测试**

- empty 200、JSON 200、非2xx三种 fixture；
- artifact inventory JSON parse error=0；
- preflight失败传播不变。

## 13. P2-2：100 个 Protobuf Descriptor Deprecation Warning

**现象**

Stage 01 为 `308 passed, 100 warnings in 493.48s`。warnings主要来自旧 generated protobuf descriptor API。

**根因**

生成文件与当前 protobuf runtime 的推荐 API/pinned版本存在代差。它是兼容性债务，不是当前测试失败。

**Artifact 证据**

- `logs/01_pytest_v2.log` warning summary和调用栈；
- `protocol/statebus_pb2.py` generated descriptors。

**影响**

当前308个测试仍有效，但交付日志噪声大，未来 runtime升级可能变成硬错误。

**最小修复**

使用仓库固定的 protoc/runtime组合重新生成，不手改 generated file；记录生成命令和版本。不要仅全局忽略 DeprecationWarning。

**回归风险**

protoc/runtime版本变化可能改变序列化或 generated API。需做 golden wire compatibility和跨进程 UDS回归。

**最小测试**

- protobuf serialize/deserialize golden fixtures；
- loopback/UDS typed round trip；
- pytest warning audit，目标相关 warning=0。

## 14. 实施批次

### Batch A：观测和 Gate P0

范围：replay per-case gate、LLM call计量、restoration event、strict `sp` taint schema、observed rate finalizer。虽然 restoration metric列为P1，但它与 Stage 03同一闭环，建议与P0一起修。

验收：单元测试全部通过，Stage 03/08 targeted重跑通过，且没有通过放松 quality/hash/oracle条件实现。

### Batch B：实验合同 P1

范围：model/effective Planner稳定性分层、prefix output contract与多 pair交替、compare AB/BA（仅在需要 latency claim时）。

验收：prefix两侧合同等价；Planner model/effective指标不混淆；latency没有足够证据时继续显示 claim forbidden。

### Batch C：交付 P1/P2

范围：sandbox capability/negative tests、health envelope、protobuf再生成、openEuler验证。

验收：交付环境证据独立落盘，不把当前host/container结果冒充 openEuler结果。

## 15. 最小验证矩阵

| 顺序 | 验证 | 规模 | 必须通过的硬条件 | 失败后的动作 |
| ---: | --- | --- | --- | --- |
| 1 | static/unit | 秒到分钟 | mixed replay、call count、restore、`sp`、ratio | 留在对应模块修复 |
| 2 | Stage 03 only | 25 bootstrap+25 target | 25 quality；per-case class/calls/hash/restore一致 | 不跑 full matrix |
| 3 | Stage 08 only | 16 executions | taint 0误报；oracle negative生效；model/effective分开 | 定位 scanner或Planner |
| 4 | prefix targeted | >=4 AB/BA pairs | counter有效、合同100%等价、paired TTFT落盘 | 不作 causal claim |
| 5 | compare timing | 可选，>=4 AB/BA repeats | 双侧等质量、公平、顺序平衡 | 保留 no-latency-claim |
| 6 | full matrix | 最后 | 16/16 recorded且P0/P1指标一致 | 不用汇总 pass掩盖单项失败 |
| 7 | openEuler delivery | 独立 | build/run/tests/sandbox/UDS路径 | 保留未验证声明 |

## 16. 修复后验收不变量

Stage 03：

```text
quality_pass = selected
exact + validated = selected
planner_requests = selected
downstream_requests = validated
llm_requests = planner + 3 * validated
exact_restoration = exact
exact_normalized_source_equal = exact
exact_downstream_requests = 0
```

Stage 08：

```text
primary quality/route/tool = pass
route_hints = 0
consumed_hash_matches = 4 per primary case
taint violations = 0 for valid sp
oracle negative fixtures = rejected
model equivalence and effective equivalence = separately reported
```

Prefix：

```text
0 <= sum(hits)/sum(queries) <= 1
reported rate = recomputed rate
shared and independent output contracts are equivalent
request order is balanced across pairs
KV tensor transfer claim remains false
```

## 17. 不应实施的“修复”

- 不要让 exact replay重新调用 Retriever/Executor/Summarizer来满足旧 gate。
- 不要把 `llm_call_count` 继续硬编码成1或4；从事件聚合。
- 不要简单允许任意 `sp` payload；严格验 schema和值。
- 不要删除 model paraphrase比较；把 model/effective结果分层。
- 不要用 per-case rate平均替代 ratio-of-sums，除非明确报告 unweighted mean且不称整体 hit rate。
- 不要为了 prefix JSON pass改变两侧不同的 prompt/生成合同。
- 不要用异步并发 timing代替正式 serialized AB/BA。
- 不要把 resource fallback改名为 sandbox success。
- 不要在本轮顺手修改 Runtime、Planner或测试；当前用户授权仅为审计。

## 18. 最终建议

最小且正确的下一步是 Batch A：修四个 P0，并把 restoration metric一并纳入 Stage 03闭环；随后只重跑 Stage 03和08。完成这两个 targeted stage后，再独立修 prefix实验合同。当前没有理由直接重跑完整矩阵，也没有证据支持先做大规模 Planner或Runtime重构。

本方案刻意保留现有安全边界：固定 workflow、typed contract、route/tool allowlist、verified replay identity、quality scorer和fallback都不需要放宽。需要改变的是验收逻辑和可观测性，使“真实减算、合法状态合同、模型漂移、Runtime安全恢复”能够被分别看见。

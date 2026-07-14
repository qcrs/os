# Qwen3-32B GPU1 全量实验真实性审计

审计对象：`/home/qcrs/statebus/runs/full_qwen3_gpu1_20260713_182556`

结构化数据：`42_full_qwen3_gpu1_20260713_data.json`

## 1. 结论

本轮不是“只有流程跑通”。它形成了三组可信的正向证据：25-case/5-family External 等质量 compare、25-case/5-family L0-L3 internal attribution、两组 10 轮 continuous memory/replay。所有 stage 通过，296 个 v2 测试通过，openEuler 24.03-LTS-SP3 容器、Qwen3-32B local vLLM、GPU1 local embedding 的实际路径都被执行。

当前最可靠的结果是 token 和质量：Compare 中 StateBus 与 External 都是 25/25 quality pass，StateBus prompt tokens 少 12028（-16.82%），total tokens 少 11970（-15.26%），而且 25/25 case 的 prompt token 都更低。Formal internal L3 相比 L0 total tokens 少 44955（-40.34%），质量仍为 25/25。

当前不能把“所有 stage PASS”解释成 KV/hidden tensor transfer、真实 vLLM prefix hit rate、稳定时延优势、强安全沙箱或 subprocess UDS 全部完成。本轮传递的是 shared-memory embedding semantic state 和 compact logit summary；prefix 只有控制面 estimate；CodeAct 使用确定性 plan/script 且 bwrap 全部 fallback；formal transport 是 loopback。

实验可靠性判定：对“链路可运行、质量门、token、结构化状态、共享记忆/replay、四角色参与”可靠；对“时延 superiority、真实 GPU KV cache、hidden-state transfer、强隔离、真实 UDS benchmark”证据不足。

## 2. 环境和阶段

| 项目 | 实际值 | 判定 |
| --- | --- | --- |
| OS | openEuler 24.03 (LTS-SP3) | 满足交付 OS 版本路径 |
| LLM | Qwen3-32B, `http://127.0.0.1:53334/v1` | local vLLM path |
| Embedding | Qwen3-Embedding-0.6B, `cuda:1`, 1024 dims | probe 成功，不是 CPU/DEMS |
| StatePool | `auto -> shared_memory` | L2/L3 实际 publish |
| pytest | 296 passed, 100 warnings | warning 为 protobuf/Transformers deprecation |

| Stage | 结果 | Stage 内时长 | 主要覆盖 |
| --- | --- | ---: | --- |
| 00 preflight | PASS | 3 s | 配置、依赖、模型目录、CUDA |
| 01 pytest v2 | PASS | 468 s | 296 tests |
| 02 compare | PASS | 1097 s | 25/5 StateBus vs External |
| 03 replay | PASS | 1286 s | 25-case L3 history bootstrap |
| 04 CSV continuous | PASS | 958 s | 10 rounds, L0-L3 |
| 05 cross-period continuous | PASS | 1246 s | 10 rounds, L0-L3 |
| 06 formal | PASS | 2842 s | 25/5, L0-L3 |

这里的 stage duration 是 `START -> PASS`，不包含 stage 间初始化空档，不能当整个 launcher 的精确 wall time。

## 3. External Compare

### 3.1 质量和公平性

| 指标 | StateBus | External | 结论 |
| --- | ---: | ---: | --- |
| Cases | 25 | 25 | 5 families 全覆盖 |
| Quality pass | 25 | 25 | strict equal quality 成立 |
| Fairness gate | - | 25/25 | hard gate 通过 |
| Contamination | - | 0 | 未检测到 |
| Public tool | - | 17/17 | 非 financial public-file tool 全成功 |

External lane 的 `no_metadata_leakage`、`no_typed_state_used`、`no_statebus_imports`、`llm_only_decisions` 和 visible-candidate 检查均通过。它不是拿 StateBus 的 typed state 或内部 helper 伪装出来的 baseline。

### 3.2 Token

| 指标 | StateBus | External | Delta |
| --- | ---: | ---: | ---: |
| Prompt tokens | 59491 | 71519 | -12028 (-16.82%) |
| Completion tokens | 6982 | 6924 | +58 |
| Total tokens | 66473 | 78443 | -11970 (-15.26%) |

这组 token 结论可信度高于平均值单点：25/25 case 的 prompt delta 都为负，范围 -1675 到 -42，中位数 -204。收益主要来自输入上下文压缩，不是 completion 变短。

### 3.3 时间

| 指标 | StateBus | External | Delta |
| --- | ---: | ---: | ---: |
| Task wall time | 539738 ms | 552001 ms | -12263 ms (-2.22%) |
| LLM time delta | - | - | -56627 ms |
| System overhead delta | - | - | +44364 ms |

这个结果只能写成 first-pass observation：StateBus 只在 11/25 case 更快，External 在 14/25 更快；per-case delta 中位数为 StateBus 慢 624 ms；repeat_count=1。原 artifact 把 `serialized_latency_superiority_claim_allowed` 标成 true 是 claim gate bug，已修为至少需要 3 次 serialized repeat。最终 latency claim 仍应由跨三次运行的 aggregator 判断。

## 4. Formal L0-L3

覆盖 family：financial report、multi-period trend、cross-table join、conditional aggregation、anomaly detection。

| Layer | Quality | Prompt tokens | Total tokens | Control bytes | Semantic transfer | Shared memory |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| L0 text | 25/25 | 101287 | 111428 | 42926 | 0 | 0 |
| L1 typed control | 25/25 | 102950 | 110073 | 10711 | 0 | 0 |
| L2 + semantic state | 25/25 | 59491 | 66473 | 11320 | 25 | 25 |
| L3 full cold stack | 25/25 | 59491 | 66473 | 12370 | 25 | 25 |

L3 vs L0：prompt -41796、total -44955（-40.34%）、prompt bytes -105689、control bytes -30556、quality delta 0。主要增益发生在 L1 -> L2 的 semantic pruning/state path；这次 formal L3 是 cold run，没有 replay 增益，因此不能把 L2/L3 相同 token 归因为 memory replay。

本轮 formal layer 缺少 `task_ms`，只有 `llm_wall_ms` 和 stage wall time。这是 runner reporting bug，不代表任务没有耗时；代码已增加 per-case `perf_counter` 测量，下一次 run 才会有可用的 formal/continuous task wall time。

## 5. Memory 和 Replay

### 5.1 Replay-ready diagnostic

25/25 case quality pass，25/25 memory match，25/25 validated replay，25 skipped steps，50 verified artifacts，0 invalidated artifacts。history source 是真实 `history_bootstrap`，不是 synthetic seed。

边界：这是 `execution_scope=diagnostic_partial` 的单层 L3 replay 机制验证，`formal_headline_eligible=false`。每个目标 case 前先运行一次 L0 bootstrap，因此证明“同任务历史产物经过验证后可降级复用”，不证明任意跨任务泛化。

原 artifact 的 `benchmark_tier=formal` 同时配了 `baseline_kind=statebus_fixed_answer_dev` 和 `task_family_tier=dev_fixed_answer`，属于元数据 bug。代码已改成 `statebus_formal_registry_adapter/formal_registry`。

### 5.2 CSV continuous

10/10 rounds、L0-L3 全部质量通过。L3 raw counts：memory match 16、artifact reuse 21、history observed reuse rounds 9、target rounds 6、history step reduction 2、history reuse gain 1、validated replay 0。

这组 family 的正确 claim 是 assist/artifact/history reuse。它没有声明 replay target，因此 0 validated replay 不是失败，也不能把 16 次 memory match 除以 10 解释为 160% hit rate；该字段是候选/匹配事件计数，不是布尔 round hit rate。

### 5.3 Cross-period continuous

10/10 rounds、L0-L3 全部质量通过。L3 raw counts：memory match 18、artifact reuse 16、history reuse gain 8、history step reduction 12、validated replay 4、skipped steps 4。

预注册 replay target 是 rounds 2/4/6/8，四轮全部 observed/validated，没有 missing 或 unexpected replay。L3 CodeAct actions 为 26，而 L0/L1/L2 都是 30，少的 4 次与 4 个 skipped step 一一对应。这是本轮“记忆确实减少执行动作”的最直接证据。

## 6. KV、Prefix 和 Hidden-like State

### 6.1 Prefix/KV

原始 suite 字段 `neural_prefix_cache_hit_rate_estimate` 被逐 case 相加：formal/replay 为 12.5，CSV 为 4.5，cross-period 为 5.0。这些数不是 1250%/450%/500%。按分子分母重算：

| Scope | Estimated hits | Estimated queries | 正确 rate |
| --- | ---: | ---: | ---: |
| Formal/replay | 25 | 50 | 0.5 |
| CSV | 9 | 18 | 0.5 |
| Cross-period | 10 | 20 | 0.5 |

代码已修复聚合为 `sum(hits)/sum(queries)`，prefill savings ratio 也按 token denominator 重算。

但 0.5 仍是控制面 estimate：一个 shared prefix 给 executor 和 summarizer，首个 consumer 算 query、后续 consumer 推测为 hit。它不是 vLLM `/metrics` 的 before/after counter delta；本轮 `kv_prefix_probe` 为空，Prefix Feedback 没有进入 scheduler。因此不能宣称真实 GPU KV cache hit rate、KV tensor export 或 Agent 间 KV tensor transfer。

### 6.2 Logit summary

Formal 有 100/100 layer-case `logit_state_transfer_count`。peak_is_last=0，peak_before_last=100；varentropy mean 0.00503，top-gap mean 0.83288，decision entropy mean 1.68345。peak-scan 已经解决“固定取最后 token”的观测偏差。

这个对象是 top-logprobs 派生的 compact decision summary，不是模型 hidden-state tensor。confidence gate 本轮没有形成 intervention A/B，因此只证明 telemetry/state plumbing 和 peak-scan 行为，不证明它提升了正确率。

## 7. CodeAct 和隔离

Formal 每层有 75 plan stages / 75 actions；replay 有 50/50；cross-period L3 因 replay skip 降到 26 actions。plan、script、stdout/stderr、artifact manifest 都落盘，可审计性成立。

实现边界很重要：当前 plan/script 是系统按已知 data task 确定性生成，不是 LLM 自由生成 Python；formal 每层 `bwrap=0`、resource fallback=25。可以称为 CodeAct-shaped bounded auditable execution，不能称完整 LLM CodeAct，也不能称 bwrap/namespace 强隔离已验证。

## 8. 四 Agent 是否真实参与

Compare 的 StateBus 和 External 两条 lane 都是每个 case planner/retriever/executor/summarizer 各调用一次，两个 lane 均无 violation。Formal 的 100 个 layer-case 和两组 continuous 的 80 个 layer-round 也全部满足每角色恰好一次调用。

role-visible artifact 扫描结果：255 份 canonical spec、255 份 planner handoff、255 份 CodeAct bundle、1020 份 prompt slice；四个角色各 255 份 prompt slice。代表样本显示不同角色看到不同 hydration/table/memory slice，不是一个 Agent 输出复制四遍。

仍需限定“发挥作用”的含义：路由不是完全 open-ended autonomous classification。Retriever/Executor 收到由 `canonical_task_spec.intent_op` 和 top visible candidate 形成的 route hints，模型必须从可见候选中严格选择。这是 compiler-assisted multi-Agent system，符合系统赛题，但不能用来证明 Qwen3 从零发现 route/tool 的能力。

## 9. 答案泄露审计

扫描 1785 个 role-visible 文件，禁止字段 `expected_facts`、`expected_route`、`expected_tool_name`、`oracle_answer`、`correctness_hint` 命中为 0。源码调用链显示 `expected_facts` 仅在角色运行完成后进入 artifact validator/scorer；它会写 validator audit，但没有进入 role prompt slice。External fairness hard gate 同时确认 no metadata leakage/no StateBus imports/no typed state。

Prompt 中出现报告表格和正确数值不是答案泄露，而是任务要求 Agent 从公共输入证据计算答案。需要防的是 scorer-only oracle 或 expected label 进入 prompt，本轮未发现这种情况。

结论应写成“在已枚举 role-visible surface 和当前调用链中未发现 oracle leakage”，不能写成形式化证明。未来应把 forbidden-field scan 变成 full script 的强 gate，并对 validator/history hydration 增加 taint test。

## 10. 赛题覆盖矩阵

| 赛题要求 | 本轮证据 | 状态 |
| --- | --- | --- |
| >=3 Agent / >=3 roles | 4 roles，每 case/layer 均有调用 | 已覆盖 |
| >=3 task types | 5 formal families | 已覆盖 |
| 纯文本 + 结构化协议 | L0-L3，同任务质量一致 | 已覆盖 |
| 结构化 action/args/result/capability | typed control 与 control bytes；协议单测 | 已覆盖，但 full run transport 为 loopback |
| 非文本中间状态 | embedding semantic state，L2/L3 各 25 shared-memory transfer | 已覆盖 |
| hidden/KV | logit summary + prefix estimate | 部分覆盖，不是 tensor handoff |
| 共享记忆存储/检索/复用 | replay 25/25；两组 continuous raw reuse | 已覆盖 |
| 2 组关联连续任务 | CSV + cross-period，各 10 轮 | 已覆盖 |
| 稳定 >=10 轮 | 两组均完成 10 轮且质量全过 | 已覆盖，single run |
| 消息/token/字符/state size | report 中均有 | 已覆盖 |
| 单任务总耗时 | compare/replay 有；formal/continuous artifact 缺 | 部分覆盖，代码已修 |
| 记忆命中率 | raw match/reuse/replay counts | 部分覆盖，缺统一 denominator |
| CodeAct | bounded deterministic execution artifacts | 部分覆盖 |
| openEuler 24.03-LTS-SP3 | 容器内执行成功 | 已覆盖容器路径 |
| 强沙箱 / subprocess UDS | bwrap fallback；formal loopback | 未由本轮验证 |

按评分项判断：通信效率证据最强；状态传递和系统完整性证据较强；记忆复用有正向机制证据但缺统一命中率/多次统计；实验验证仍被 latency repeat、真实 KV gauge、task_ms 缺失和 loopback/bwrap 边界限制。

## 11. Review Findings

### P0/P1

1. Prefix rate/savings ratio 被简单求和，产生 12.5 等非法 suite rate。已修复并补测试。
2. Formal/continuous 没有记录 per-case `task_ms`。已补 `perf_counter` 测量；旧 artifact 无法回填。
3. repeat=1 仍允许 latency superiority claim。已增加 repeat>=3 gate；最终 claim 必须读取三次 serialized aggregate。
4. Replay/formal scope metadata 与实际 registry 不一致。已改为 formal registry metadata。
5. Stage 00 preflight 只检查配置，不发 LLM JSON Schema 请求。Track C 的真实验证来自 Stage 02 compare，而不是 preflight 本身。

### P2

6. Formal transport 是 `loopback`；subprocess UDS 是代码/单测能力，不是本轮 benchmark 证据。
7. CodeAct 100% resource fallback；bwrap strong isolation 没有在容器中成立。
8. Prefix Feedback 未接调度器，也没有 vLLM counter delta。
9. `gc_issue_count` 实际统计 `GC_ISSUED` 事件，不是 GC error，字段名容易误读。
10. `TRANSFORMERS_CACHE` 和旧 protobuf descriptor 产生弃用 warning，不影响本轮正确性，但应在交付前清理。

## 12. 已实施修复和验证

本次只修改通用 runner/reporting/gate，没有改 sample、scorer 阈值、expected facts、LLM prompt 答案或 replay 判定：

- 新增 non-additive metric 聚合器，重算 prefix hit/savings ratio。
- Minimal/continuous 增加 per-case 和 suite `task_ms`。
- Formal registry metadata 与实际 scope 对齐。
- Full script 增加 compare fairness、contamination、四角色调用、task_ms、prefix ratio、logit/state transfer gate。
- 分析脚本增加逐 case role audit 和 role-visible oracle scan。

针对性回归：4 passed（72.20 s）；Python compile、`bash -n`、`git diff --check` 需要作为最终交付 gate 保留。旧 full artifact 不会被代码修改反向改写，修复后的字段需要下一次 full/smoke rerun 验证。

## 13. 下一轮实验建议

不需要再次把所有矩阵重复 10 次。赛题要求的 10 轮是连续任务链，不是同一实验重复 10 次。

1. 先跑修复后的 live smoke：1 个 non-revenue compare、1 个 L3 replay、continuous round 1->2、1 个 formal case L0-L3，确认 `task_ms`、prefix rate、metadata 和新 gates。
2. 全量矩阵再跑 1 次，用于生成修复后的正式 artifact。
3. 只对 formal compare 做 3 次 serialized clean repeat，冻结 case order，报告 token 固定值和 latency mean/median/std/faster-case count。
4. 单独做 prefix experiment：每 task 前后抓 vLLM query/hit counter delta，增加 cache-friendly vs hostile schedule；不要混入正式 token claim。
5. 单独做 subprocess UDS 和 bwrap/capability validation；失败时按环境限制报告，不与业务质量矩阵混跑。

最终可对外使用的核心表述：StateBus 在 Qwen3-32B、openEuler container、25-case/5-family 等质量 compare 中将 prompt tokens 降低 16.82%、total tokens 降低 15.26%；在 internal L0-L3 attribution 中保持 25/25 quality 并将 L3 total tokens 相比 L0 降低 40.34%；两组 10 轮连续任务全部通过，其中 cross-period 的 4 个 replay target 全部 validated 并减少 4 个执行动作。其余 KV/hidden、latency、sandbox、UDS 结论按上述边界处理。

# StateBus v2 赛题证据闭环最终报告

日期：2026-07-20

状态：E0-E6 canonical run 全部通过；代码提交受只读 Git 元数据阻塞，详见完成审计。

证据根：`/home/qcrs/statebus/runs/contest_evidence_closure_20260720`

## 1. 结论

本轮在 openEuler 24.03 LTS-SP3 单容器内完成了赛题要求的六段证据链：matched text 到 typed Protobuf、embedding `StateRef`、跨任务 memory、两组 10 轮连续任务、semantic holdout、以及 25-case Adaptive DSL/CodeAct。E0-E6 的工程门和质量门均通过。

结论必须按下列边界读取：

- L0 是同一 benchmark harness 内的 matched pure-text lane，不是独立外部系统。
- 非文本状态是 little-endian float32 embedding semantic matrix，经 shared-memory `StateRef` 传递；它不是 LLM hidden state，也不是 KV cache tensor handoff。
- history reuse、artifact reuse、assist、validated replay、exact replay 分开统计；query 和 candidate 不等于消费或 replay。
- E1 和 E2 各观测到 2 个 skipped step，但 `skipped_llm_call_count` 都是 0。
- `expected_facts` 只在 Runtime 完成之后用于外部 benchmark 评分，不参与 Prompt、Runtime operation selection、memory commit 或 replay decision。
- 外层容器 root 创建 bwrap namespace，生成的 Python 在 bwrap 内以 `65534:65534` 执行；这不是 production-grade sandbox。
- 当前只证明 openEuler 单容器、repo-local 离线财报/运营指标分析域内的 bounded generalization，不证明 VM、跨机、任意 Linux 或开放域泛化。

## 2. 冻结身份与环境

| 字段 | 记录值 |
| --- | --- |
| 分支 | `feat/yzm-v2-migration` |
| canonical Git HEAD | `a3a5ec836d13c5e9d77811edd25d58d24af227b6` |
| worktree | `git_dirty=true`，所有 canonical manifest 均如实记录 |
| 容器 | `statebus-dev-qcrs` |
| 镜像 digest | `sha256:715ded05373ca023f3acf33d180b8db2e0c4f2b1361b6c2a31c58c33c1fb6647` |
| OS | openEuler 24.03 LTS-SP3 |
| Python | 3.11.6，`/usr/bin/python3` |
| bwrap | 0.8.0 |
| role model | `qwen3-32b`，temperature 0 |
| embedding | `/statebus/models/Qwen3-Embedding-0.6B`，revision `4.51.3`，CUDA |
| capability registry digest | `239fdc32997c4f81e13e614b8f1fe5c99cf099d3a40e07164b2652d54000ac57` |

E1 fairness manifest 为 `comparison_valid=true`，两个 family 的 `unexpected_difference_count=0`。四个 lane 的 task/source/prior fact、角色图、消息边界、模型配置、Executor/validator、capability surface 和 subprocess topology 均通过不变量检查；唯一允许变化的是 carrier、semantic state 和 memory feature flags。L0 使用 `utf8_text`，L1-L3 使用 Protobuf，四层都走 `driver_uds_executor_subprocess`。

Runtime 在 E4 前按 dirty-worktree 内容冻结：

- `runtime_freeze_sha=e0b04923132f4a139eaa4c2b0ec71b1299d5fd75ccb492d362987a67f5f95afa`
- 59 个 per-file 条目，ledger hash `b3a13dd7c23e15c5c726cbec3c7f97259458bed260969d0f712e470122b18ebe`
- E4 结束后 `v2/runtime`、`v2/control`、`v2/state`、`v2/memory` 的 added/changed/removed files 均为空

这是一项 worktree snapshot audit，不是 commit-range freeze；原因是仓库 Git 元数据只读。

## 3. E0-E6 总览

| ID | canonical run | 结果 | 关键门 |
| --- | --- | --- | --- |
| E0 | `e0_focused_20260720_142422` | PASS | `135 passed`；deterministic preflight `ok=true` |
| E1 | `e1_causal_serial_20260720_150801` | PASS | 40/40；四 lane 各 10/10；fairness valid |
| E2 | `e2_stress_serial_20260720_152924` | PASS | 20/20；两个 family 各 10/10 |
| E3 | `e3_adaptive_memory_final_20260720_160244` | PASS | 6/6；commit/load/match/consume/effect/reject 闭环 |
| E4 | `e4_semantic_holdout_final4_20260720_175430` | PASS | 4/4；semantic 3、table 1；Runtime freeze unchanged |
| E5 | `e5_adaptive_final_20260720_190107` | PASS | 25/25；DSL 7、bounded Python 18；fallback 0 |
| E6 | `e6_full_final_20260720_201043` | PASS | `558 passed, 100 warnings`；preflight `ok=true` |

## 4. E1：L0-L3 单变量矩阵

两个 family 的前 5 轮组成 `2 x 5 x 4 = 40` 次串行执行。四层质量均为 10/10。

| Lane | control bytes | total wire bytes | LLM prompt bytes | prompt tokens | total tokens | prompt-visible bytes | LLM calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| L0 | 25,196 | 36,069 | 130,676 | 29,876 | 33,974 | 75,926 | 40 |
| L1 | 4,270 | 11,200 | 126,406 | 30,737 | 34,891 | 75,926 | 40 |
| L2 | 4,507 | 11,827 | 56,326 | 13,599 | 17,739 | 14,353 | 40 |
| L3 | 5,357 | 12,677 | 57,738 | 13,885 | 17,870 | 15,847 | 40 |

### 4.1 L0 -> L1：结构化控制面

- control bytes：`-83.05%`
- total wire bytes：`-68.95%`
- LLM prompt bytes：`-3.27%`
- prompt tokens：`+2.88%`
- total tokens：`+2.70%`

因此本轮可声明 typed Protobuf 在 matched subprocess topology 中降低了控制面和总 wire 字节；不能声明 token 同步下降。L0/L1 的 Agent-visible evidence 相同，prompt-visible bytes 都是 75,926。

### 4.2 L1 -> L2：embedding StateRef

- prompt bytes：`-55.44%`
- prompt tokens：`-55.76%`
- prompt-visible bytes：`-81.10%`
- semantic state transfer：9

L2 使用本地 Qwen embedding 和 shared memory，没有 deterministic embedding fallback。数值 top-k 的 selected IDs 决定局部 hydration，因此这里证明的是 semantic matrix 的跨进程数值消费和 prompt hydration 缩减。

### 4.3 L2 -> L3：共享 memory

E1 的 L3 漏斗为：

```text
query 10 -> candidate 15 -> compatible 2 -> approved 2 -> consumed 2 -> effect 2
assist 0; validated replay 2; exact replay 0; rejected incompatible 13
skipped step 2; skipped LLM call 0
```

两个 validated replay 都来自 financial family 的 R2/R4；operating family 只有 history/artifact reuse，不升级为 replay。L3 相比 L2 的 prompt bytes、prompt tokens 和 prompt-visible bytes 略增，且 40 次 LLM call 没有减少。可以声明两次真实消费和两次步骤跳过，不能声明 LLM 调用减少。

### 4.4 描述性时延

以下是单次固定顺序串行 run 的 10-case 线性插值读数，仅用于描述：

| Lane | p50 (s) | p95 (s) |
| --- | ---: | ---: |
| L0 | 31.953 | 33.440 |
| L1 | 32.355 | 35.589 |
| L2 | 32.391 | 36.336 |
| L3 | 29.135 | 35.212 |

未执行反向 lane 顺序重复，因此这些数据不支持稳定时延 superiority。

## 5. E2：两组 10 轮稳定性

E2 只运行 `long_horizon` L3，不冒充完整四层对照。两个 family 都是 10/10，合计 20/20。

```text
query 20 -> candidate 48 -> compatible 9 -> approved 9 -> consumed 9 -> effect 9
assist 7; validated replay 2; exact replay 0; rejected incompatible 39
skipped step 2; skipped LLM call 0
```

E2 还记录 44 次 history-backed artifact reuse，其中 financial 16、operating 28；这些不是 44 次 replay。financial 仅 R2/R4 为 validated replay，operating 仍是 history-backed-only。R9 的不兼容候选可见、被拒绝且当前任务重新计算通过。

描述性时延：financial p50/p95 为 33.596/38.430 秒，operating 为 28.676/35.805 秒。和 E1 一样，不作稳定时延优势声明。

## 6. E3：Adaptive memory 消费闭环

E3 为 5 个 financial case 加 1 个 runtime-signature 不兼容负例，6/6 通过。六个终态 verified artifact 均完成 commit，后续 case 使用新的 Runner 从同一 family store 重新加载。

```text
query 6 -> candidate 16 -> compatible 15 -> approved 15 -> consumed 23 -> effect 23
assist 0; validated replay 1; exact replay 0; rejected incompatible 1
skipped step 1; skipped LLM call 1
```

`consumed=23` 大于 `compatible=15` 不是重复计数错误：15 个 approved match 可被多个真实 consumer 使用；23 条消费记录由 Executor 8 条、Summarizer 15 条组成，涉及 5 个唯一 memory ID。负例 fixture 出现在 candidate pool，runtime incompatibility 被记录，fixture 没有进入角色输入，当前输出重新计算并验证通过。

memory commit decision 明确记录 `benchmark_gold_used=false`；commit 由 verified artifact hash、terminal quality report、input lineage、output contract 和 validator digest 决定。

## 7. E4：semantic holdout

4 个 repo-local offline holdout 全部通过：

| Case | 输入 | Retriever | Executor | 结果 |
| --- | --- | --- | --- | --- |
| S1 | narrative only | semantic | bounded Python | PASS |
| S2 | narrative only | semantic | bounded Python | PASS |
| S3 | table only | table | DSL | PASS |
| S4 | narrative + table | semantic | bounded Python | PASS |

三个 semantic case 的 query/candidate matrix 都是 little-endian float32、shared memory、Qwen3-Embedding-0.6B。S1/S2 的单次矩阵为 `[9,1024]`、36,864 bytes；S4 为 `[6,1024]`、24,576 bytes。producer PID 为 308338，consumer PID 分别为独立进程，例如 308651、308717、308783。消费操作是 `cosine_topk_budget_pruning`，selected candidate IDs 和 input/output decision-surface hash 均发生变化。

S1/S2 每个 case 留下 3 份物理矩阵 metadata，共 110,592 bytes，并记录 3 次 release、released bytes 110,592；S4 对应 3 份、73,728 bytes，release 数和字节同样闭合。`benchmark_oracle_visible_to_roles=false`，4/4 expected facts 只在 Runtime 之后评分。

该结果支持冻结 Runtime 后通过 manifest/schema 扩展完成有限 holdout；它不是严格双盲学术 holdout，也不支持开放域泛化。

## 8. E5：Adaptive Agent 与 CodeAct

E5 运行固定六项 capability registry 的全部 25 个 formal case，25/25 quality pass。Planner、Retriever、Executor、Summarizer 均使用 qwen3-32b；Planner 最终批准 25 个 plan，schema normalization 25 次，hard rejection 0。

| Capability | registry advertised | selected | verified workflow |
| --- | --- | ---: | ---: |
| `retrieve_semantic_evidence_v1` | yes | 0 | 0 |
| `retrieve_table_evidence_v1` | yes | 25 | 25 |
| `execute_analysis_dsl_v2` | yes | 7 | 7 |
| `execute_bounded_python_v2` | yes | 18 | 18 |
| `compose_claim_set_v2` | yes | 23 | 23 |
| `compose_risk_memo_v1` | yes | 2 | 2 |

semantic Retriever 的自然覆盖由独立 E4 提供，未为了 E5 分布强制路由。18 条 Python execution record 全部为 bwrap，全部 `UID/GID=65534:65534`；model/runtime/sandbox fallback 均为 0。DSL/Python 两种执行方式都有自然覆盖，但 18/7 只是选择分布，不是性能提升比例。

## 9. E0 与 E6 工程门

- E0：focused suite `135 passed in 632.42s`，deterministic preflight `ok=true`。
- E6：完整 `tests/v2` 为 `558 passed, 100 warnings in 858.69s`，随后 deterministic preflight `ok=true`。

两者都在目标 openEuler 容器内运行。100 条 warning 来自现有 Protobuf descriptor deprecation 等，不影响 pass，但仍应作为后续依赖升级事项保留。

## 10. 失败与重跑历史

失败 artifact 未删除、未覆盖，也不进入 canonical 聚合：

| Run | 结果与处置 |
| --- | --- |
| `focused_20260720_140122` | 133 passed、1 个旧 planner memory-policy 断言失败；后续 E0 135 passed |
| `causal_20260720_142709` | 40/40 通过，但与 E0 并发重叠，不作为正式串行证据 |
| `e1_causal_20260720_143554` | child SIGTERM `-15`；后续全新 E1 run 通过 |
| `stress_20260720_145740` | child SIGTERM `-15`，并保留 1 个 shared-memory cleanup warning；后续全新 E2 run 通过 |
| `e3_adaptive_memory_serial_20260720_154048` | 5/6；负例 compatibility/recompute gate 未闭合；后续 E3 6/6 |
| E4 前四次 run | 分别 1/4、2/4、3/4、2/4；`final4` 才是 4/4 canonical |
| `e5_adaptive_serial_20260720_180846` | 24/25；`formal-agg-002` 区间数值解析失败 |
| `e5_formal_agg_002_probe_20260720_185808` | 单例探针通过，正确输出为 `2081990 / Nigeria / 2010`；随后 E5 25/25 |
| `e6_full_serial_20260720_195042` | 555 passed、3 failed；preflight 已通过；修复后 E6 558 passed |
| `e6_memory_slice_probe_20260720_200735` | assist 输入进入角色，但 replay 不允许且不跳步；用于定向诊断，不升级为 replay 证据 |
| `phase5_focused_20260720_140910` | 125 passed、1 个旧断言失败；后续 `phase5_focused_20260720_142012` 为 126 passed |

这些失败说明最终结果来自 fail-closed 修复和全新 run，而不是删除失败数据、修改 gold 或挑选有利 case。

## 11. 可声明与不可声明

可以声明：

- matched subprocess topology 下，typed Protobuf 相比 matched text lane 显著减少 control/total-wire bytes；
- Qwen embedding matrix 经 shared-memory `StateRef` 在不同 PID 间传递，数值 top-k 改变 selected IDs 和 hydration；
- MemoryRef 经 candidate、compatibility、approval 和实际角色输入消费，并观测到 behavioral effect；
- E3 有 1 次真实 skipped LLM call，E1/E2 只有 skipped step、没有 LLM call reduction；
- LLM 在冻结的六项 capability surface 内自然覆盖 DSL 和 bounded Python；
- 本轮在 openEuler 24.03 LTS-SP3 单容器完成 fresh E0-E6 和完整回归。

不可声明：

- token、端到端时延或整体性能稳定 superiority；
- 15/48 个 candidate 或 13/44 次 artifact reuse 都是 memory hit/replay；
- exact replay、answer restoration replay、hidden state 或 KV tensor transfer；
- root+bwrap 是 production-grade sandbox；
- openEuler VM、跨机器、任意 Linux 或开放域 Agent 泛化；
- expected facts 是 Runtime 自主验证依据。

完整 artifact 路径与 checksum ledger 见 [final_v2_contest_evidence_index_20260720.md](final_v2_contest_evidence_index_20260720.md)，逐条完成定义映射见 [完成审计](../improvement/25_contest_evidence_closure_20260720/01_completion_audit_20260720.md)。

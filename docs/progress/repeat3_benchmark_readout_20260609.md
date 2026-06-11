# StateBus Repeat-3 Benchmark Readout

日期：`2026-06-09`

适用范围：这份报告解释本轮 `repeat=3` host-side live API benchmark 到底跑了什么、各个指标和术语分别是什么意思、以及为什么在已经做过一次 memory assist 紧缩之后，`assist_only` 仍然不能升级成正式 headline。

## 1. 先说结论

本轮已经完成两层 benchmark：

1. 正式受控包
   - `runs/host_goal_eval_20260609_controlled_api_repeat3_serial/`
   - 用于当前 host-mainline 的正式 `communication / state_transfer / memory` claim 复查
2. 开放验证包
   - `runs/open_validation_eval_20260609_api_repeat3_serial_refresh/`
   - 用于 retrieval / executor / replay boundary 的 support-only 复查

当前没有 benchmark 还在运行。

本轮不再补到 `repeat=5`，因为 `repeat=3` 已经足够说明问题：

- 正式受控包三轮全部完成，`text` / `protocol` 两侧 `failure_count = 0`
- 开放验证 refresh 包三轮全部完成，`text` / `protocol` 两侧 `failure_count = 0`
- 关键方向没有翻转：
  - `protocol` 仍稳定比 `text` 更省 control bytes、更省 live tokens、更快
  - `state_transfer` 仍成立，但 baseline 必须继续写成 `text brief handoff`
  - memory 仍只成立到 `replay_enabled / step-skipping reuse`
  - `assist_only` 仍然只能算诊断层，不该包装成正式收益

## 2. 这次到底跑了什么

### 2.1 正式受控包

命令：

```bash
source deploy/activate_statebus_host.sh
python -m eval.runner \
  --task-set tasks/sample_benchmark.yaml \
  --repeat 3 \
  --modes text,protocol \
  --llm-mode api \
  --out runs/host_goal_eval_20260609_controlled_api_repeat3_serial \
  --quiet-progress
```

含义：

- `tasks/sample_benchmark.yaml`
  - 当前正式受控 benchmark pack
  - 用来做当前 contest headline claim
- `--repeat 3`
  - 每个 mode 各跑 3 轮
- `--modes text,protocol`
  - 同一任务集分别跑 `text` 协作模式和 `protocol` 协作模式
- `--llm-mode api`
  - `Planner` 和 `Summarizer` 走真实 live API，不是 deterministic 假模型
- `serial`
  - 这里读作串行 live API benchmark，不把并发 API 发起当 timing evidence

这包的任务组成：

- 总任务数：`26`
- `18` 个 `internal_regression`
- `2` 个 `communication`
- `3` 个 `state_transfer`
- `3` 个 `memory`

这包的定位：

- 当前最应该引用的 `repeat=3` 复查包
- 可以回答当前三条主张是否仍然保持方向正确
- 但正式最强证据层仍是已有 `repeat=10` live API 包，而不是本次 `repeat=3`

### 2.2 开放验证包

命令：

```bash
source deploy/activate_statebus_host.sh
python -m eval.runner \
  --task-set tasks/open_validation_benchmark.yaml \
  --repeat 3 \
  --modes text,protocol \
  --llm-mode api \
  --out runs/open_validation_eval_20260609_api_repeat3_serial_refresh \
  --quiet-progress
```

含义：

- `tasks/open_validation_benchmark.yaml`
  - 当前 support-only open validation pack
  - 只用于 retrieval / executor / replay boundary 检查
  - 不用于正式 `communication / state_transfer / memory` headline claim

这包的任务组成：

- 总任务数：`12`
- 全部在 `internal_regression` lane
- `memory_off = 10`
- `replay_enabled = 2`
- 没有 `assist_only`

补充说明：

- 本轮较早的 `runs/open_validation_eval_20260609_api_repeat3_serial/` 只完成了 `2` 轮
- 因此后续引用应以 `..._refresh/` 为准

### 2.3 运行前回归门

本轮跑之前通过了：

```bash
python -m pytest -q
python -m runtime.smoke
```

结果：

- `pytest`: `85 passed`
- `runtime.smoke`: 通过

## 3. 这些术语分别是什么意思

### 3.1 `text` vs `protocol`

- `text`
  - 角色之间用自然语言 brief / narrative frame 协作
- `protocol`
  - 角色之间用结构化 protobuf control frame 协作

这不是“有无 LLM”的区别，而是“协作控制面如何表达”的区别。

### 3.2 `communication`

这条 lane 主要回答：

> 在不混 memory reuse 和 state-transfer claim 的前提下，结构化控制面是否更省。

所以它尽量隔离出：

- control bytes
- live tokens
- task latency

### 3.3 `state_transfer`

这条 lane 主要回答：

> 如果 text side 用 executor-targeted text brief，protocol side 直接传 `StateRef`，那么非文本中间态传递是否更合适。

当前 baseline 必须写清楚：

- text side 不是“把所有中间态全文自然语言重写”
- text side 是 `text brief handoff to executor`
- protocol side 是 `state_ref` handoff

### 3.4 `memory`

这条 lane 不是一个单一模式，而是三档 policy 对比：

- `memory_off`
  - 不查共享记忆
- `assist_only`
  - 允许 memory assist
  - 但不允许 step-skipping
  - 仍要 fresh retrieval / validation
- `replay_enabled`
  - 允许 replay / step-skipping
  - 可以出现 `skip_execute` 和 `skip_retrieve_execute`

### 3.5 `internal_regression`

这不是 contest 单项 headline lane，而是主链稳定性回归层。

它主要覆盖：

- cold start
- reject control
- assist
- validated replay
- exact replay

## 4. 关键指标都是什么意思

### 4.1 `control_bytes`

含义：

- `text` mode 下读 `text_bytes`
- `protocol` mode 下读 `protocol_bytes`
- 表示控制面通信开销

它回答的是：

> 角色之间为了协作，控制信息到底传了多少字节。

### 4.2 `llm_total_tokens`

含义：

- live API 实际消耗的 LLM prompt + completion tokens

它回答的是：

> 这个协作模式最终给在线模型增加了多少 token 成本。

### 4.3 `task_ms`

含义：

- 单任务端到端 wall-clock 时间

它回答的是：

> 用户真的要等多久。

### 4.4 `handoff_textual_bytes`

含义：

- 真正交给 `Executor` 的文本 handoff 负载

它不是“系统里所有文本 state 的总量”，而是：

> 最终 executor 真正收到多少文本型中间态。

### 4.5 `handoff_nontext_bytes`

含义：

- 真正交给 `Executor` 的非文本 handoff 负载
- 当前主要对应 `StateRef` 指向的非文本中间态

它回答的是：

> 非文本状态传递到底有没有真的发生，而不是只存在于总 state 统计里。

### 4.6 `memory_hit_rate`

含义：

- memory query 发出后，有多少任务拿到了 memory hit

它只能说明：

> 有多少任务“碰到了记忆”

它不能单独说明：

> 这些记忆是否真的带来了端到端收益

### 4.7 `skipped_step_count`

含义：

- 因 replay / exact replay 发生而被跳过的 step 数量

这是真正会带来明显端到端收益的指标之一，因为它对应：

- 少做 retrieve
- 少做 execute
- 少做重复工作

### 4.8 `reuse_gain`

含义：

- 当前 benchmark 对“复用带来的实际收益”的归一化统计

它比单纯 `memory_hit_rate` 更接近真实收益，因为它要求：

- 不是只 hit 到记忆
- 而是复用真的减少了后续工作

### 4.9 `prior_applied_rate / candidate_reduction / route_agreement_rate / rescue_rate`

这些是 `assist_only` 的机制级诊断指标。

它们主要回答：

- 记忆 prior 有没有被实际采纳
- 候选集合有没有因为 assist 变小
- memory prior 和 fresh route 是否一致
- assist 是否真的起到了 rescue 作用

这些指标有用，但它们仍然不能替代 `task_ms` 的正式 headline 判断。

## 5. 本轮正式受控包读数

证据文件：

- `runs/host_goal_eval_20260609_controlled_api_repeat3_serial/benchmark_report.md`
- `runs/host_goal_eval_20260609_controlled_api_repeat3_serial/benchmark_results.json`

### 5.1 Aggregate

| mode | control_bytes | llm_total_tokens | task_ms | memory_hit_rate | skipped_step_count | reuse_gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| text | 157713.33 | 29745.67 | 118083.63 | 0.77 | 10.00 | 0.13 |
| protocol | 135518.00 | 19836.67 | 93612.18 | 0.77 | 10.00 | 0.13 |

读法：

- `protocol` 相比 `text`
  - control bytes 更低
  - live tokens 更低
  - task latency 更低
- 这说明结构化协作主线当前仍稳定成立

但 aggregate 不能直接当三条单项 claim 的唯一证据，因为它混合了：

- `internal_regression`
- `communication`
- `state_transfer`
- `memory`

### 5.2 `communication` lane

| mode | control_bytes | llm_total_tokens | task_ms |
| --- | ---: | ---: | ---: |
| text | 5938.00 | 1141.50 | 4756.34 |
| protocol | 5032.50 | 728.00 | 3740.42 |

结论：

- `communication` 仍成立
- 结构化控制面当前仍更省、更快

### 5.3 `state_transfer` lane

| mode | control_bytes | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | task_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| text | 5261.33 | 1735.89 | 0.00 | 1120.78 | 4578.78 |
| protocol | 4692.67 | 738.00 | 2011.67 | 698.67 | 3626.88 |

结论：

- text side 当前是真实 text brief handoff
- protocol side 当前是真实 non-text `state_ref` handoff
- `state_transfer` claim 当前仍成立

但外部表述必须保留这个范围：

> 当前证明的是 `text brief handoff` 对 `state_ref handoff` 的 scoped comparison，
> 不是“所有纯文本中间态 baseline 都被全面击败”。

### 5.4 `memory` policy 对比

| memory_policy | text task_ms | protocol task_ms | 解释 |
| --- | ---: | ---: | --- |
| `memory_off` | 4672.59 | 3680.73 | 无共享记忆基线 |
| `assist_only` | 4714.03 | 3620.68 | 允许 assist，但不允许跳步 |
| `replay_enabled` | 4109.38 | 3494.14 | 允许 replay / step-skipping |

当前最诚实的读法：

1. `replay_enabled` 稳定成立
2. `assist_only` 仍然不稳
3. 因此当前 memory headline 仍只能写成：
   - `replay_enabled / step-skipping reuse` 成立

不能写成：

- assist-style shared memory 已经普遍更优
- 开放自然任务上的通用 assist gain 已成立

## 6. 本轮开放验证包读数

证据文件：

- `runs/open_validation_eval_20260609_api_repeat3_serial_refresh/benchmark_report.md`
- `runs/open_validation_eval_20260609_api_repeat3_serial_refresh/benchmark_results.json`

### 6.1 Aggregate

| mode | control_bytes | llm_total_tokens | task_ms | skipped_step_count | reuse_gain |
| --- | ---: | ---: | ---: | ---: | ---: |
| text | 67271.67 | 12912.00 | 76591.93 | 2.00 | 0.06 |
| protocol | 57281.00 | 7997.33 | 60671.12 | 2.00 | 0.06 |

这包的作用不是做正式 headline，而是看边界是否干净。

### 6.2 Misfire Audit

两侧都是：

- `field_match_rate = 1.00`
- `task_match_rate = 1.00`
- `reuse_match_rate = 1.00`

并且：

- `route`
- `route_source`
- `tool_name`
- `top_doc_id`

都没有 misfire。

这说明当前 retrieval / executor / replay boundary 在这组开放验证任务上是稳定的。

## 7. 为什么改过一次 memory assist 之后，`assist_only` 还是有问题

### 7.1 之前改了什么

见：

- `docs/progress/memory_assist_compact_optimization_20260608.md`

那次改动的核心不是“直接把 memory 变强到能赢 benchmark”，而是：

1. 不再把整段 prior summary 直接塞回 assist 路径
2. 改成有界的 `MEMORY_ASSIST_HINT`
3. `FEATURE_BUNDLE` 继续优先由 fresh corpus evidence 构造
4. assist 元数据只保留必要结构信号

换句话说，那次改动主要解决的是：

> assist path 太臃肿、prompt/context 开销太大

它让 assist 机制更自然、更紧凑，但不等于自动把 `assist_only` 变成正式收益。

### 7.2 为什么它仍然不够

因为 `assist_only` 的结构性限制没有变：

1. 它仍然要 fresh retrieval
2. 它仍然要 validate recalled playbook
3. 它不能像 `replay_enabled` 一样直接跳步
4. 它仍然要为 memory query、memory validation、hint 注入付出额外成本

所以 `assist_only` 的真实问题不是“有没有 hit 到记忆”，而是：

> 记忆提供的帮助，能不能稳定抵消它自己引入的额外开销。

当前答案仍然是：

> 还不稳定。

### 7.3 从这次 `repeat=3` 结果看

本轮受控包里：

- text
  - `memory_off = 4672.59 ms`
  - `assist_only = 4714.03 ms`
  - assist 仍然更慢
- protocol
  - `memory_off = 3680.73 ms`
  - `assist_only = 3620.68 ms`
  - assist 略快一些，但差距很小，不足以升级成正式 headline

而且 `assist_only` 的机制诊断值虽然存在：

- `prior_applied_rate = 0.54`
- `candidate_reduction = 0.54`
- `route_agreement_rate = 0.54`
- `rescue_rate = 0.54`

这只能说明：

> assist 机制在工作

不能说明：

> assist 已经稳定带来端到端收益

### 7.4 为什么我还是说它“还有问题”

因为当前最强正式边界仍然要服从已有的 live API formal evidence。

见：

- `docs/progress/benchmark_fairness_audit_20260608.md`
- `docs/progress/host_goal_26task_serialized_api_decision_20260608.md`

那里基于更强的 serialized API `repeat=10` 结论已经明确收口为：

- `communication`：成立
- `state_transfer`：成立，但要带 `text brief handoff`
- `memory`：只成立到 `replay_enabled / step-skipping reuse`
- `assist_only`：仍不能宣称比 `memory_off` 更优

所以当前最诚实的说法不是：

> memory 改完了但没效果

而是：

> memory assist 机制已经被改得更紧凑、更合理，但它还没有在当前 workload 上形成稳定的正式端到端优势。

## 8. 这轮之后最适合怎么表述

### 可以直接说

- 当前 `protocol` 相比 `text` 仍稳定更省 control bytes、更省 live tokens、更快
- 当前 `communication` claim 成立
- 当前 `state_transfer` claim 成立，但必须带 `text brief handoff` baseline 范围
- 当前 memory 的正式 headline 仍然是 `replay_enabled / step-skipping reuse`
- 当前开放验证包显示 retrieval / executor / replay boundary 没有 misfire

### 不要直接说

- assist-only shared memory 已经普遍更优
- 当前已经证明所有纯文本中间态都不如 state-ref
- 当前开放验证包也能替代正式受控包

## 9. 当前最短结论

如果只保留一句话，那么当前最准确的收口是：

> 这次跑的是 host-side live API `repeat=3` 的一组正式受控包加一组开放验证包；`communication` 和 scoped `state_transfer` 继续成立，memory 仍然只成立到 `replay_enabled / step-skipping reuse`，而 `assist_only` 虽然机制上已经做过紧缩优化，但在当前 workload 上还没有形成稳定、可正式宣称的端到端收益。

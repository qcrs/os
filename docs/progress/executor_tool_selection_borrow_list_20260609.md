# Executor Tool Selection Borrow List

日期：`2026-06-09`

适用范围：这份文档只服务当前 `/home/qcrs/statebus/project` 的 host-mainline。
它不是框架选型文档，也不是外部仓库导入计划；只记录这轮围绕
`executor tool selection + abstain discipline` 做的定向检索、可借机制和明确不借的部分。

## 1. 当前问题是什么

当前弱点不是“没有工具选择”，而是：

> `runtime/executor_runtime.py` 已经有
> `small ranked tool_candidates + metadata-only abstain + ambiguous-candidate abstain`，
> 但对“单一路径、支撑证据仍很弱”的情况仍可能直接落到具体 playbook。

这会留下两个问题：

1. 执行层仍偏 `route -> playbook` 直落
2. 当前 claim surface 虽已收紧，但执行决策仍不够像“有阈值纪律的小候选检索层”

## 2. 看了哪些本地仓库 / 文件

### 2.1 `third_party/langgraph-bigtool`

看了：

- `third_party/langgraph-bigtool/README.md`
- `third_party/langgraph-bigtool/langgraph_bigtool/tools.py`
- `third_party/langgraph-bigtool/langgraph_bigtool/graph.py`

得到的机制：

1. 先检索小候选工具集，再把它暴露给执行层
2. 候选工具检索函数可以很轻，不必绑定到完整框架 store
3. `limit` 本身就是关键约束，不需要一次性暴露全部工具

### 2.2 `third_party/semantic-router`

看了：

- `third_party/semantic-router/README.md`
- `third_party/semantic-router/docs/user-guide/features/route-filter.md`
- `third_party/semantic-router/docs/user-guide/features/threshold-optimization.md`

得到的机制：

1. route 不是非黑即白；低于阈值就应该返回 `None` / no match
2. 阈值应该被当成显式决策边界，而不是隐含在排序里
3. 即使 route 集已过滤，仍允许“没有任何 route 通过阈值”

### 2.3 `third_party/AgentRx`

看了：

- `third_party/AgentRx/README.md`

得到的机制：

1. 可以把失败 / 误判对象写成可审计轨迹，而不是只看最终输出
2. 这更适合后续 replay misfire / false reuse / tool-choice misfire 诊断

## 3. 借了什么

这轮只借两件事：

1. 来自 `langgraph-bigtool`
   - 保留并强化“先生成小候选工具集，再选择是否执行”的思路
2. 来自 `semantic-router`
   - 明确加入“低置信度时返回 no match / abstain”的边界

对应到当前代码，就是：

1. 保持 `tool_candidates` 是小集合，不扩成全工具表
2. 在已有
   - `metadata_only_abstain`
   - `ambiguous_candidates_abstain`
   之外，新增
   - `low_confidence_abstain`

## 4. 为什么和赛题契合

因为这一步不会删除四角色语义，也不会把系统改写成开放域 agent 框架。

它做的只是：

1. 让 `Executor` 更少直接吃固定 route 直落
2. 让“何时该执行、何时该先补证据”更诚实
3. 保持当前 repo-local、contest-shaped、host-mainline 的对象不变

## 5. 为什么不直接整套照搬

### 5.1 不照搬 `langgraph-bigtool`

不借：

- LangGraph runtime 替换
- 外部 store / memory 主线替换
- 大规模工具生态扩张

原因：

- 当前 repo 只需要小候选工具检索思路，不需要重做 runtime

### 5.2 不照搬 `semantic-router`

不借：

- 外部 route layer 框架
- 独立语义路由基础设施
- 训练式大规模 route 体系

原因：

- 当前 repo 已经有 `FEATURE_BUNDLE + route_confidence + tool_candidates`
- 现在只需要补清晰阈值纪律，不需要替换决策骨架

### 5.3 不照搬 `AgentRx`

不借：

- 全套轨迹 IR / invariant / judge pipeline

原因：

- 当前问题不是“先建一整套诊断平台”
- 只需记住它适合后续误判审计，不该挤到当前主线前面

## 6. 这轮的 defended next action

这轮最合理的小步是：

> 在当前执行层里加入 `low_confidence_abstain`，
> 但只作用于“无 hint 的弱单一路径”这类目前仍会过早直落工具的情况。

不把这条规则扩大到：

1. 已检索到且同向的 `hint_consensus`
2. 当前 repeat-10 主线里的高置信任务
3. 更大范围的 route / retrieval 框架替换

## 7. 如果这步没有收益，下一步怎么办

如果这步只带来更多 `collect_more_evidence`，却没有改善边界解释或稳定性，
那最诚实的后续不是继续叠阈值，而是：

1. 停在当前执行层边界
2. 保留现有 claim surface
3. 转去做更明确的 tool usage note / capability note 检索
4. 或者只做误判诊断，不继续主线改动

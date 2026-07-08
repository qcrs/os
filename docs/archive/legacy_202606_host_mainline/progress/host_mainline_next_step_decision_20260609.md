# StateBus Host-Mainline Next-Step Decision

日期：`2026-06-09`

适用范围：这份短文档只回答当前 `/home/qcrs/statebus/project` 在最近一轮 fairness / claim-surface 收紧之后，主问题还剩什么、下一步最值得做什么、为什么不是别的方向。

## 1. 当前主问题是什么

当前主问题已经**不是**：

- 赛题主骨架是否存在
- `text/protocol` 双模式是否可跑
- `communication` / `state_transfer` / `replay_enabled` 是否完全没有 formal 证据

这些点现在都有本地代码、测试和 `26` 任务 serialized API `repeat=10` 包支撑。

这份文档在本轮更新前，把“继续收紧 executor tool selection”放成了最优先的 next step。

但在补完 out-of-band observability、并对主 `26` 任务与
`executor_diagnostic` 任务集重新审计之后，当前更诚实的判断已经变成：

> executor 仍然是一个受控 selector，
> 但当前主线里还没有足够强的新证据支持继续沿 mechanism 层盲加规则。

因此当前主问题已经更准确地变成：

> 在 claim surface 已经明显收紧之后，
> 应该如何诚实地停住当前 executor 主线边界，
> 并把新增价值更多写成 observability / explanation closure，
> 而不是继续为了去特化硬叠规则。

## 2. 为什么这会改写优先级

因为当前其它几条线已经有更清楚的边界：

1. `communication`
   - 当前 lane 已经能直接成立
2. `state_transfer`
   - 当前 lane 已经能成立，但必须保持 `text brief handoff` 的范围限定
3. `memory`
   - 当前也已经收口到诚实边界：只把 `replay_enabled / step-skipping` 当 headline，不把 `assist_only` 包装成已赢
4. sandbox / Docker / openEuler VM
   - 这些都不属于当前 host-mainline 下一步最高收益对象

重新审计后的结论是：

1. 当前主线里的 `hint_consensus` 大多已经带有真实 lexical / tag support
2. 之前最可疑的一批 text-side case，主要是在撞 `text_brief`
   observability gap，而不是抓到新的机制漏洞
3. 继续叠 executor 规则，最容易重新引入：
   - 不必要 abstain
   - benchmark fairness 扰动
   - “为了去特化而去特化”的过拟合修补

所以当前更优先的问题不再是“继续 mechanism hardening”，而是：

1. 把当前 executor 的边界与负判断写清楚
2. 如果还要继续推进，优先转向更明确的说明层 / capability note /
   tool-usage note，而不是继续改决策规则

## 3. 当前最值得做的一步

当前最值得做的一步是：

> 暂停 executor 主线 mechanism 改动，
> 保留当前边界，
> 并把新增价值明确落成
> `claim-surface / observability closure`
> 或更正式的 negative-result wording。

更具体地说：

1. 不继续往 `hint_consensus` 主线盲加新的 abstain 条件
2. 不把更多 debug 字段塞回 live path
3. 不为了“更像通用 agent”而强行继续改 executor
4. 如果继续推进，优先做更清晰的能力说明 / 使用说明 / route-family 说明

## 4. 为什么现在不该优先追别的方向

### 4.1 不该优先追 `assist_only` headline

原因很直接：

- 当前 formal lane 仍显示 `assist_only` 没有稳定打赢 `memory_off`
- 强行追这条线，最容易把目标重新带回“为了 headline 追收益”的旧问题

### 4.2 不该优先追 sandbox 主线

原因也直接：

- 当前 host runnable path 已经存在
- 当前最主要弱点不是“完全无法隔离执行”，而是“执行决策还过于受控”

### 4.3 不该优先做大框架化检索重构

原因：

- 当前检索 / 记忆 / route 分层已经比旧线清楚得多
- 现在直接引重型外部框架，收益不如先把当前边界与负判断写清楚

## 5. 这一判断下的诚实 claim

如果下一轮沿当前更诚实的方向推进，那么最有价值的新增 claim 不是“性能又涨了多少”，而是：

> 当前 host-mainline 的 executor 主线，
> 在 observability 补齐之后，
> 还没有出现足够强的新证据来支持继续往 mechanism 层叠规则；
> 因此当前最诚实的位置是停在这条边界上，
> 把新增价值记成 claim-surface / observability closure。

如果这一轮做不出收益，最诚实的后续也很明确：

- 停在当前执行层边界
- 保留现有 claim surface
- 不继续为了 headline 强行追 executor 新机制、memory assist 或更大重构

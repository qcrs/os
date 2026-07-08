# Executor Mainline Observability Re-Audit 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前 `/home/qcrs/statebus/project` 在
executor mainline 上，用新的 out-of-band observability 重新做的一次审计。
它不是新的 benchmark headline，也不等于“executor 已完全泛化”。

## 1. 这轮为什么要重审

上一轮之前，一个看起来很诱人的判断是：

> 当前主线里的 `hint_consensus`
> 可能大量只是 metadata-driven 弱共识，
> 所以还应该继续往 executor 里叠规则。

但在把 observability 放回正确位置之后，这个判断需要重新审。

原因很直接：

1. 之前的部分“弱共识”印象来自 payload 观测面太窄
2. `text_brief` 路径之前还缺少 out-of-band feature reconstruction
3. 如果这些问题不先补齐，就很容易把“看不见支撑”误判成“没有支撑”

## 2. 这轮具体看了什么

这轮使用新的 out-of-band `feature_observability`，
分别重审了：

1. 当前主 `26` 任务 benchmark
2. 当前 `executor_diagnostic` 任务集
3. `text_brief` 路径的 feature reconstruction 是否完整

重点看：

1. `hint_consensus` 任务到底有没有真实 lexical support
2. replay / skip path 下这些支持证据是否还能被正确读出
3. text/protocol 两侧的 observability 是否一致

## 3. 这轮得到的主判断

### 3.1 主线里的 `hint_consensus` 大多不是 metadata-only

在当前主 `26` 任务里，重新审完之后可以直接看到：

1. `text`
   - `hint_consensus = 26`
   - `with_signals = 23`
   - `with_tags = 23`
   - `signals_ge_2 = 23`
   - `score_ge_20 = 20`
2. `protocol`
   - `hint_consensus = 26`
   - `with_signals = 26`
   - `with_tags = 26`
   - `signals_ge_2 = 26`
   - `score_ge_20 = 23`

这说明当前主线里绝大多数 `hint_consensus`
已经有真实 lexical / tag support，
不是“只靠 metadata label 在硬路由”。

### 3.2 之前 text-side 的一部分“零支撑”主要是 observability 缺口

这轮补完 `text_brief` 的 out-of-band reconstruction 后，
当前 `text` 下已经不再剩

- `feature_route_source = hint_consensus`
- 但 `feature_observability.matched_signals` 为空

的主线任务。

所以当前更诚实的判断是：

> 之前那批 text-side 的“零支撑”印象，
> 主要是在撞到 `text_brief` observability gap，
> 而不是已经抓到新的 executor 机制漏洞。

### 3.3 诊断集仍然有价值，但它当前更多是 guardrail，不是 headline driver

`executor_diagnostic` 任务集继续证明：

1. `low_confidence_abstain`
2. `metadata_only_abstain`
3. `lexical_thin_support`
4. `corpus_metadata_conflict + thin override`
5. `ambiguous_candidates_abstain`

都还在按预期工作。

但这组证据当前更像：

- boundary guardrail
- regression protection

而不是：

- 继续推动主线 headline 的直接增益来源

## 4. 这轮最重要的负判断

这轮最重要的结论其实是否定性的：

> 在当前 observability 已经补齐之后，
> 没有足够证据支持继续沿主线盲加 executor 规则。

原因：

1. 主线 `hint_consensus` 已经大多带真实 lexical support
2. 之前最可疑的一批 text-side case 主要是观测缺口，不是机制缺口
3. 继续叠规则，最容易重新引入：
   - 不必要 abstain
   - benchmark fairness 扰动
   - “为了去特化而去特化”的过拟合修补

## 5. 这轮之后最诚实的 next step

如果继续推进，当前最合理的 next step 不是：

1. 再往 `hint_consensus` 主线加新的 abstain 条件
2. 再把更多 debug 字段塞进 live path
3. 强行追 executor 新 headline

而更可能是二选一：

1. 暂停 executor 主线机制改动，保留当前边界
2. 转向更明确的审计/说明层：
   - capability note
   - tool-usage note
   - route-family note
   - 或更正式的 negative-result wording

## 6. 当前最诚实的结论

这轮最值得保留的判断是：

> 当前 host-mainline 的 executor 主线，
> 在 observability 补齐之后，
> 还没有出现足够强的新证据来支持继续往机制层叠规则。

所以当前最诚实的位置是：

> 先停在这条 executor 主线边界上，
> 把新增价值记成 claim-surface / observability closure，
> 而不是继续把它往新的 headline 方向硬推。

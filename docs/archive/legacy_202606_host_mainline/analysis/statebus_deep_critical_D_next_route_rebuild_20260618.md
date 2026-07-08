# 文档 D：下一阶段路线重构建议

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

## 1. 总判断

当前不建议推倒重做，也不建议继续把所有创新点塞进一个 headline。

最合理路线是：

> 维护 `contest_honest_headline_v1` 作为受控主提交对象；冻结它的核心证据；把 Planner、memory、external text、LangGraph/open baseline 拆成 secondary/audit。

原因：

- current headline 已经 repeat=10 closed；
- S1/S2/replay 已进入 current headline；
- object purity 和 coverage 已闭合；
- 主风险已经从“不能提交”变成“叙事过宽会失真”。

## 2. 如果维持当前主线，怎么收口

### 2.1 主线 claim

推荐主 claim：

> StateBus 在受控多 Agent contest task object 中，用结构化控制和 typed-state handoff 替代 whole-lane natural-language handoff，稳定降低控制面通信开销，并支持 S1 validation 与 S2 prior-dependent replay。

这句话故意不说：

- external pure text；
- open planner；
- LangGraph innovation；
- broad long-term memory；
- hidden-state/KV。

### 2.2 报告结构

主报告按三层写：

1. Formal headline:
   - `contest_honest_headline_v1`
   - repeat=10 API + deterministic
   - object parity / formal stability / control bytes / typed packet / S1/S2/replay gates
2. Secondary mechanisms:
   - planner support；
   - typed-state consumer sensitivity；
   - memory policy controlled；
   - statepool backend matrix。
3. Audit boundaries:
   - external pure text baseline；
   - route/corpus shaping；
   - LangGraph substrate；
   - openEuler/Docker/nsjail deferred。

### 2.3 Freeze line

建议冻结：

- current headline task count；
- `text_whole_lane` vs `state_packet_minimal`；
- repeat=10 run packages；
- S1/S2/replay gate interpretation；
- no external pure-text claim。

只允许修改文档解释和 report indexing，不继续动 headline runtime。

## 3. 如果分包，怎么拆

### Mainline

`contest_honest_headline_v1`

回答：

- current contest formal object；
- paired text/protocol comparison；
- structured communication compactness；
- typed state packet；
- controlled S1/S2/replay effect。

不回答：

- external pure text；
- open planner；
- open memory；
- LangGraph value。

### Secondary A: Memory

可以保留两条：

- current-headline S2 replay effect；
- `memory_policy_controlled_v3` / `memory_reuse_v3` 作为归因层。

强调：

- current headline memory 是 controlled S2 replay；
- broad memory claim 需要另一个 benchmark。

### Secondary B: Planner

`planner_support_v3`

回答：

- system supports Planner role；
- LLM planner path exists；
- planner contract can be validated。

不回答：

- headline performance；
- protocol vs text；
- adaptive open-world planning。

### Secondary C: Typed-state sensitivity

`typed_state_consumer_sensitivity_v3`

回答：

- typed packet is consumed；
- missing/wrong packet has detectable behavioral impact；
- minimal packet boundary is real。

### Audit

Audit objects:

- external pure text baseline；
- text helper path ablation；
- route/corpus taxonomy stress；
- LangGraph-native/open comparison；
- broader tool universe。

Audit 只能影响 future claim strength，不能反向污染 current formal headline。

## 4. 如果重构，先重构哪个 object

当前不建议重构 headline，但如果下一阶段要提升研究强度，优先顺序应是：

1. External text baseline audit
   - 目标：测清楚 `text_whole_lane` 与传统 pure-text baseline 的距离。
   - 不并入 current headline。
2. S2 negative-control audit
   - prior missing / wrong rejection / wrong route 时是否降级；
   - 证明 replay 不是硬标签 shortcut。
3. Route/corpus stress
   - 换 family taxonomy；
   - 替换 distractor corpus；
   - 减少 route keyword alignment。
4. Planner secondary
   - yaml vs llm plan；
   - validate gate presence；
   - planner role impact。
5. Packet granularity ablation
   - `DENSE_EVIDENCE` only；
   - `EXECUTOR_DECISION_PACKET` only；
   - validation packet on/off。

这些都应该是 secondary/audit，不是重开 current headline。

## 5. 哪些东西不值得继续投入

### 5.1 把 LangGraph 讲成主创新

不值得。它会把 StateBus 拉回 generic orchestration framework，反而削弱 protocol/state/memory claim。

### 5.2 为了“更系统”现在做 Docker/nsjail/openEuler

不值得在本轮做。AGENTS 与环境约束已经把 openEuler/容器/强沙箱放到后验验证。

### 5.3 继续扩 carrier variants

不值得。current issue 不是 carrier 不够多，而是 claim layering 容易混。

### 5.4 把 Planner 强行塞回 headline

不值得。会破坏 single-variable mode comparison。

### 5.5 把 external baseline 并入 headline

当前不值得。external baseline 的工程差异太大，应先 audit-only。

## 6. 必须改的叙事 stopline

后续材料必须避免以下句型：

- “StateBus 全面优于纯文本多 Agent。”
- “LangGraph 是 StateBus 的核心创新。”
- “Planner 已经证明开放规划能力。”
- “我们实现了 hidden-state/KV 传递。”
- “current headline 证明广义长期记忆复用。”
- “text_whole_lane 就是传统 pure-text baseline。”

可替代为：

- “current headline 是 StateBus 内部 whole-lane text comparator vs minimal typed-state packet。”
- “LangGraph 是 execution substrate。”
- “Planner support 是 secondary evidence。”
- “memory replay 是 controlled S2 replay effect。”
- “State transfer 是 feature/packet/StateRef 级非文本中间态。”

## 7. 下一步执行建议

### 必做

1. 在 active report/index 中加入本轮分层结论。
2. 明确 current headline freeze。
3. 把 Goal2 旧结论标成 superseded where necessary。
4. 把 external pure text 和 LangGraph comparison 降到 audit。
5. 准备答辩用的 claim matrix：claim / evidence / boundary / not claimed。

### 可做

1. 写 external baseline audit 方案；
2. 写 S2 negative-control audit 方案；
3. 生成 run evidence index；
4. 增加 row-level gate explanation；
5. 补一页 Planner/LangGraph 降级说明。

### 不做

1. 不改 current headline runtime；
2. 不跑更大 repeat 来替代叙事收口；
3. 不进入 openEuler/Docker/nsjail；
4. 不把 external baseline 作为正式 headline；
5. 不新增新 headline pack 名称。

## 8. D 文档结论

当前项目应被讲成：

> 一个已经足够扎实的受控赛题主提交对象，同时带有明确 secondary/audit 分层。

不是：

- 只能叫 prototype 的弱对象；
- 应推倒重构的失败对象；
- 已经证明所有赛题维度全面强成立的终局对象；
- 赛题 object 完全不合理导致无法提交的对象。

最现实的路线：

1. 维护 current formal headline；
2. 降级过宽叙事；
3. 分包 Planner/memory/external baseline；
4. 停止用 LangGraph 做故事主角；
5. 后续只做能检验一个明确怀疑点的 audit。

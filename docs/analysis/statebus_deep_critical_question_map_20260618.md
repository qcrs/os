# StateBus 深度质疑问题地图

日期：`2026-06-18`

定位：

- 这不是继续沿 Goal1/Goal3 做执行收口的文档。
- 这不是“当前 headline 已经成立，所以只差交付”的文档。
- 这是给新窗口 / 新评审 / 新作者视角使用的“深度质疑地图”。

目标：

- 不预设当前主线必须继续维护；
- 不预设当前 `contest_honest_headline_v1` 已经足够解释方法价值；
- 不把“当前 benchmark 能跑通”误读成“系统问题已经想清楚”；
- 允许直接挑战题目对象、benchmark 对象、text baseline、planner 角色、LangGraph 作用、memory/replay 解释、创新点定义、以及赛题要求本身的耦合方式；
- 如果问题够大，允许得出“应分包 / 降级 claim / 重构主线 / 批判赛题对象”的结论。

这份文档的用途不是帮新窗口回答问题，而是帮助它：

1. 先搞清楚当前真正的问题在哪里；
2. 先区分“已经闭合的收口问题”和“仍未解决的深层问题”；
3. 再判断哪些问题值得继续做，哪些问题不值得掩饰，哪些问题必须承认做不到。

这份文档**不是**：

- FAQ
- checklist
- 逐条作答任务单
- 最终结论

它首先是一个“多角度怀疑框架”。

推荐读法：

1. 先带着 `题目.md` 的赛题硬约束来读；
2. 把下面的问题当成“应该从哪些角度怀疑当前 object”的地图；
3. 不要一上来逐条回答；
4. 先用它建立多个视角：
   - benchmark/object 视角
   - text 定义视角
   - planner 角色视角
   - LangGraph 角色视角
   - innovation / narrative 视角
   - 赛题耦合视角
5. 然后再回到本地 docs / code / artifact 里验证：
   - 哪些怀疑成立
   - 哪些怀疑过度
   - 哪些怀疑其实只是受控 benchmark 的自然代价
6. 最后再把问题收敛成：
   - submission-level 真实问题
   - secondary enhancement 问题
   - 不值得继续投入的问题

一句话：

> 这份文档的主要作用，是先防止你被当前主线叙事绑住，而不是替你下结论。

---

## 1. 当前完成情况：哪些旧问题已经不应再当主问题

以下结论基于当前代码树与最新主 artifact：

- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`

当前已经不应再被当作主 blocker 的问题：

1. `contest_honest_headline_v1` 不再停留在“repeat 不足”的老状态。
   - API `repeat=10` 已闭合；
   - `formal_stability_gate.passed = true`；
   - `withheld_headline_reason = ""`。

2. 当前主 headline 不再停留在“object purity 没清干净”的老状态。
   - `object_parity_gate.passed = true`；
   - text/protocol 的 formal reading contract 已固定；
   - support surface 与 headline 的混读已大幅收紧。

3. 当前主 headline 不再停留在“memory/replay 只存在于历史 support 包”的老状态。
   - 最新 headline 的 S2 行已开启当前 object 内的 replay；
   - `headline_memory_replay_effect_gate.memory_replay_effect_ready = true`；
   - S1 / S2 / memory effect / repeat closure 都已在 current headline 内闭合。

4. “现在的主要问题只是继续修 benchmark 公平性”这个判断已经过时。
   - benchmark fairness/object 问题不是完全消失；
   - 但它已经不再是最显眼的未收口问题。

换句话说：

> 当前项目已经不是“benchmark 没整理好、对象不纯、repeat 不足”的旧状态。
> 当前更值得质疑的是：这个已经闭合的受控 object，到底证明了什么、没证明什么、是否值得作为主叙事继续强化。

---

## 2. 当前最重要的重新提问：我们到底在证明什么

新窗口首先必须回答下面这个最高优先级问题：

> 当前项目的主创新对象，到底是什么？

如果这个问题不先被回答，后面的 planner、LangGraph、text、memory、benchmark 讨论都会继续混乱。

必须允许至少同时考虑下面几种互相竞争的答案：

1. `structured communication` 是主创新对象
2. `typed / non-text state transfer` 是主创新对象
3. `memory replay / cross-task reuse` 是主创新对象
4. `multi-agent runtime architecture` 是主创新对象
5. `planner-driven adaptive coordination` 是主创新对象
6. `benchmark methodology / claim layering` 反而成了当前最真实的产出

必须严格追问：

- 当前最强、最值得讲硬的对象到底只有哪一个？
- 哪些对象只是“系统里存在”，但不该升格为主创新？
- 哪些对象只是“赛题要求驱动下的配套角色”，并不构成方法贡献？

如果最终发现当前系统的真实产出是：

- communication 最强；
- state transfer 次强；
- memory 仅在受控 object 下成立；
- planner 不强；
- LangGraph 只是 substrate；

那么就必须允许得出这种结论，而不是硬把所有点讲成“全面创新”。

---

## 3. 一级问题一：benchmark 到底在测什么

### 3.1 当前 benchmark 测到的是机制优势，还是受控工程优势

必须追问：

- 当前 benchmark 真在比较“structured protocol vs text collaboration”吗？
- 还是在比较“同一受控 runtime 下两种 handoff carrier”？
- 如果是后者，这是否足以支撑赛题主结论？
- 当前 benchmark 测到的是系统层机制，还是受控语料上的 route classification + playbook selection？

### 3.2 当前 benchmark 的复杂性是真复杂，还是 contract 复杂

必须追问：

- `S1/S2`、`reasoning_hops_min`、`dependency_depth` 是否只是 schema 层显式化？
- 当前复杂性有多少来自真实任务结构，有多少来自 contract + gate 的人工定义？
- 如果去掉这些字段，只看任务自然对象，这个 benchmark 还剩多少真实厚度？
- 当前“厚度”是否过度依赖 runner 的 gate 解释，而不是任务本身的自然难度？

### 3.3 当前 benchmark 是否仍然过于 route-shaped / corpus-shaped

必须追问：

- 当前任务是不是本质上仍在问“属于哪个已知事故家族、走哪个已知 playbook”？
- route/tool/family/corpus 是否被共同设计得过于紧？
- 如果换语料组织方式、换工具集合、换 family taxonomy，当前优势是否还成立？
- 当前检索是不是在帮助恢复 route label，而不是支持更一般的多 agent 协作问题？

### 3.4 当前 benchmark 的区分度是否足够

必须追问：

- 错误 route / tool 的代价够不够大？
- protocol 优势是否被任务对象真实放大，还是只在 control bytes 层可见？
- 当前 benchmark 是否能清楚区分：
  - benchmark 合格但方法无明显优势；
  - benchmark 合格且方法有局部优势；
  - benchmark 合格且方法有稳定 headline 优势？

### 3.5 当前 benchmark 是否仍存在“叙事公平但对象不强”的风险

必须追问：

- 当前主 object 已经 clean，不代表它已经足够强；
- 会不会出现“形式很诚实、artifact 很完整、repeat=10 也通过了，但测到的仍是一个偏窄的受控对象”？

---

## 4. 一级问题二：text 到底应该怎么定义

这是当前最危险、最值得重新审查的问题之一。

### 4.1 必须先区分四种不同的 text

新窗口必须强制区分：

1. `StateBus runtime` 内的自然语言 whole-lane handoff
2. 强模板化的 text carrier
3. 外部传统 pure-text multi-agent baseline
4. text + 同一 memory/store/runtime 栈的内部对照系统

这四种东西不是一个对象。

### 4.2 当前 `text_whole_lane` 到底算什么

必须追问：

- 它是不是“文本传输”？
  - 是，它确实通过文本 handoff。
- 它是不是“传统纯文本多 agent 系统”？
  - 这就未必。
- 它是不是“在同一 runtime 下，为了单变量 mode 对比而定义的内部 fair carrier baseline”？
  - 很可能更接近这个。

### 4.3 当前 text 定义的真正难点是什么

必须追问：

- 当前没有使用外部纯文本 baseline，是因为：
  1. 原理上难以公平实现；
  2. 工程上尚未实现；
  3. 一旦实现更真实的纯文本 baseline，当前 headline 优势可能会变化；
  4. 赛题本身没有清楚定义 baseline，所以当前只好收敛成内部 comparator；
- 这几种原因里，哪个才是真的？

### 4.4 当前 text 是否存在“为了公平而被增强”的问题

必须追问：

- text 侧从自然语言 handoff 中恢复 route/tool，到底是合理的文本理解，还是为了不让 text 太弱而做的内部增强？
- 如果完全不允许这种恢复，当前 text 是否会过弱，进而导致比较不公平？
- 如果允许这种恢复，那它还能否被说成“传统纯文本 baseline”？

### 4.5 当前 text 的问题该不该解决

必须明确区分：

- 如果目标是内部单变量 fair comparator：
  - 当前 text 也许已经足够；
- 如果目标是外部世界可理解的纯文本 baseline：
  - 当前 text 很可能还不够；

所以新窗口必须判断：

- 当前 text 定义是“赛题主提交已经够用的收敛结果”；
- 还是“为了收口主线而暂时接受、但后续必须拆出的结构性债务”。

---

## 5. 一级问题三：Planner 到底有没有真实价值

### 5.1 当前 Planner 是不是仅仅作为角色存在

必须追问：

- 当前 Planner 是否主要只是满足“至少三种角色”这条赛题要求？
- 它是否真正改变了计划结构、信息流向、行动边界？
- 还是只是把 task contract 编译成固定 DAG？

### 5.2 当前 Planner 的作用层级到底是什么

必须区分：

1. 合规层：
   - 系统中确实有 Planner；
   - 运行时确实经过 planner phase；
2. 方法层：
   - Planner 是否真正提供自主规划能力？
3. benchmark 层：
   - 当前 headline 是否把 planner openness 当成被评测对象？

### 5.3 当前 Planner 弱，是设计选择还是能力不足

必须追问：

- 当前不开放 Planner，是因为为了锁定单变量 mode 对比而故意收敛？
- 还是因为一旦 Planner 放开，系统本身的稳定性与优势会受到挑战？
- 还是因为当前任务本来就不真正需要 Planner？

### 5.4 如果 Planner 放开，是否会暴露更大的问题

必须追问：

- 如果 `plan_source = llm/open`，当前 benchmark 还公平吗？
- 当前 task 对 Planner 是否真的有需求，还是 planner 放开后仍然只会产出同一个四步结构？
- 如果放开后仍然几乎不变，说明问题在 Planner，还是问题在 task object？

### 5.5 Planner 问题是否必须现在解决

必须允许得出以下任意一种判断：

1. Planner 对当前 headline 足够，没必要强行主线化
2. Planner 是明显弱点，但应作为 secondary pack 单独研究
3. Planner 的弱不是小问题，而说明当前“多 agent / planning”叙事被高估了

---

## 6. 一级问题四：LangGraph 到底扮演什么角色

### 6.1 当前 LangGraph 是否真实使用

必须承认：

- 不是假的；
- `StateGraph`、节点、条件边、graph state 都是真实接入；
- 它不是文档摆设。

### 6.2 当前 LangGraph 是否被“真正发挥”

必须追问：

- 当前图结构和节点集是否过于预定义？
- LangGraph 在当前系统里是执行 substrate，还是开放编排引擎？
- 当前结果依赖的是 LangGraph 的开放图能力，还是 StateBus 自己的 contract / packet / replay 逻辑？

### 6.3 如果不用 LangGraph，系统 object 还剩什么

必须追问：

- 如果换成一个简单 DAG runner，结论会发生多大变化？
- 如果变化不大，那当前最真实的创新对象是不是根本不在 LangGraph？
- 如果变化很大，那大的是工程完整性，还是方法本身？

### 6.4 LangGraph 问题是否必须现在解决

必须允许得出以下任一判断：

1. 当前 LangGraph 只需被准确降级为 substrate，不需继续深挖；
2. 当前 LangGraph 的浅使用暴露了系统上层 object 过于受控；
3. 后续应开 `langgraph_native_open_baseline` 或 support/audit 包；
4. 当前主线完全不需要继续拿 LangGraph 做故事主角。

---

## 7. 一级问题五：memory / replay 现在到底算不算强

### 7.1 当前 memory 已经不该被说成“没做”

必须承认：

- 当前 mainline headline 内已经有 S2 replay effect；
- 不能再沿用“memory 只在 support 包存在”的旧判断。

### 7.2 但当前 memory 仍可能偏受控

必须追问：

- current headline 的 replay 是不是仍然依赖同 family / 近邻 prior / 强结构匹配？
- 它证明的是“经验复用”，还是“验证性 replay gate 成立”？
- 当前 memory 的收益是不是集中在少量 S2 行？
- 它更像“省执行步骤”，还是“改变决策边界”？

### 7.3 memory 的 claim 是否仍应被谨慎分层

必须追问：

- 当前 memory 是否已经足够当主创新点？
- 还是更适合作为：
  - current headline 已闭合的一条子 claim；
  - 但仍不应膨胀成“广义长期记忆 agent 已经成立”的故事？

---

## 8. 一级问题六：创新点是否被说散了

### 8.1 当前最容易发生的错误

必须防止：

- communication、state transfer、memory、planner、LangGraph、benchmark methodology 全部一起讲；
- 导致最强点不突出、最弱点拖累整体。

### 8.2 必须逼问自己

- 当前最强、最值得讲硬的点只有哪一个？
- 第二强的点是什么？
- 哪些点只是系统完整性，不是创新主轴？
- 哪些点是加分项，不该成为 headline？

### 8.3 必须允许的尖锐结论

例如：

- 当前真正的创新可能主要是 `communication + typed state`
- memory 是当前可成立但受控的 secondary strength
- planner 几乎不是当前创新点
- LangGraph 不是当前创新点
- 真正做得最扎实的，反而可能是 benchmark/object/claim layering 的重构

这类结论必须允许出现，不能因为“看起来不够全面”就回避。

---

## 9. 一级问题七：缺失的消融与解释实验

必须强追问：

1. 是否缺少 `planner-open vs planner-closed`
2. 是否缺少 `text_whole_lane vs 更外部的纯文本 baseline`
3. 是否缺少 packet 粒度 / state object 粒度消融
4. 是否缺少 `validate gate on/off`
5. 是否缺少 `memory on/off` 的同 object 归因
6. 是否缺少 `LangGraph substrate on/off` 或更简单 runner 对照
7. 是否缺少更大 tool set / 更弱 prior / 更开放语料下的 stress test

新窗口不能默认这些都必须立刻做。

它必须先判断：

- 这些实验是当前 submission 必需；
- 还是增强版 / secondary pack 所需；
- 还是只是为了理解创新归因，而不是为了让主提交成立。

---

## 10. 一级问题八：赛题本身是否存在耦合问题

新窗口必须被授权直接质疑赛题 object，而不是默认赛题写法天然合理。

必须追问：

- 赛题是否把 `communication`、`state transfer`、`memory reuse` 三条本该拆开的 claim 强行耦合？
- 赛题是否诱导大家做出“角色齐全但每条机制都不够纯”的复杂系统？
- 赛题是否对 baseline 定义不足，导致“内部公平 comparator”和“外部世界 baseline”混在一起？
- 赛题是否过度强调“系统什么都要有”，而没有给出干净的 claim layering？

必须允许得出如下结论：

1. 赛题要求本身存在耦合缺陷；
2. 最合理的实现/汇报结构并不是一个单一大故事；
3. 更合理的是：
   - 一个 formal headline；
   - 一个 planner secondary；
   - 一个 memory secondary；
   - 一个 external/open audit baseline；
4. 如果赛题本身不合理，也应该在 review 中明确指出，而不是被迫掩饰。

---

## 11. 如果我是作者，最希望别人问我的问题

1. 你们到底在证明 StateBus 的哪一个核心对象？
2. 当前 text 到底代表什么世界里的“文本协作”？
3. 当前 planner 是真实规划，还是角色合规壳？
4. 当前 task 是真实协作问题，还是 route/playbook 受控问题？
5. 当前 packet 传的是状态，还是压缩后的答案提示？
6. 当前 replay 是经验复用，还是受控 shortcut？
7. 当前不用 LangGraph，方法还剩什么？
8. 当前优势是不是主要来自 benchmark/object 设计？
9. 当前最强 claim 到底只有哪一条？
10. 如果赛题本身不合理，应该怎么拆 story 才诚实？

---

## 12. 如果我是裁判，我会重点质疑什么

1. 你们的优势是不是来自 benchmark 设计，而不是方法本身？
2. 你们的 text baseline 为什么不是更自然、更外部的纯文本系统？
3. 你们为什么需要 Planner？它现在是否真的有决策权？
4. 当前 memory 的成立是否过于依赖同 family / 同 route / 同 prior？
5. 当前 benchmark 是否只是一个受控 prototype，而不是开放 agent benchmark？
6. LangGraph 是工具，还是你们的创新点？
7. 如果把 StateBus packet 换成普通 schema + shared store，还剩什么独特性？
8. 当前是否更像“很会做受控 benchmark 的系统”，而不是“系统层机制已经广泛成立”？

---

## 13. 这份文档希望新窗口做出的不是答案，而是判断

新窗口不应只回答单个问题。

它必须最终给出：

1. 当前系统真正的主创新对象是什么
2. 当前 headline object 值不值得继续作为主提交对象
3. 当前 text 定义是不是足够，还是只是 submission-level 收敛结果
4. 当前 planner 是否只是角色壳，是否值得单开 secondary pack
5. 当前 LangGraph 是否应降级为 substrate，而不是继续包装成创新点
6. 当前 memory/replay 是否需要更开放对象才能讲得更强
7. 当前缺失的实验里，哪些必须现在补，哪些不值得再动
8. 当前赛题 object 本身是否有不合理耦合，是否应该显式批判
9. 如果重构，应该怎么拆主线 / secondary / audit
10. 如果不重构，应该明确承认哪些边界并停止继续装强

一句话总结：

> 这份文档不是让新窗口继续“把当前主线修得更漂亮”，而是让它先搞清楚当前主线到底值不值得继续作为主线。

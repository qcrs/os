# StateBus 赛题导向 Task Family 设计稿

日期：`2026-06-10`

适用范围：

- 当前工作目录：`/home/qcrs/statebus/project`
- 当前目标：先扩更贴赛题对象的 task family，再做 `repeat=3`

这份文档只回答三件事：

1. 先看赛题，当前最值得扩的 family 是什么
2. 本地 `third_party/` 和对应 GitHub 仓库里，哪些 benchmark pattern 值得借
3. 下一步最值得先落哪一类 YAML 任务

它不是结果报告，也不是新的 benchmark 读数页。

---

## 1. 先对齐赛题对象

赛题真正要求的是：

- 多 Agent 协作
- 结构化通信对比纯文本协作
- 非文本中间状态传递
- 共享记忆复用
- 连续任务、重复利用、性能对比

因此 task 设计不能只停在：

- 单点 triage
- 一次性 route 选择
- 薄 handoff
- 没有连续修正的短任务

更合适的对象是：

> 受控、可复现、证据驱动、带连续修正压力的协作任务族

这仍然是 controlled benchmark，不是开放世界 benchmark。

---

## 2. 先借什么，不借什么

### 2.1 `openai/evals`

可借：

- YAML/JSON 驱动 eval 包装
- split / task-set / repeat 分离
- 把“任务定义”和“运行记录”分开

不借：

- model-graded 结果直接替代系统效率证据

为什么适合当前 StateBus：

- 我们正好也在做 pack 化、lane 化、artifact 化 benchmark。

### 2.2 `tau-bench` / `tau3-bench`

可借：

- tool-agent-user 的多轮任务形态
- policy + tool + user state 共同约束任务
- `pass^k` 式重复运行稳定性观念

不借：

- 客服/订票业务域本身
- simulated user 作为当前主 benchmark 前置条件

为什么适合当前 StateBus：

- 它提醒我们任务不能只是“选一个 route”，而要让后续动作和约束也进入对象。

### 2.3 `agbench`

可借：

- 从共同初始条件反复运行
- 任务定义、trace、summary 分层
- `repeat` 是对既定场景重复执行，而不是换任务

不借：

- Docker-first 运行模型
- 代码编写类任务直接作为当前主线

为什么适合当前 StateBus：

- 当前我们最需要的是“固定对象后重复验证”，不是先追更开放的环境。

### 2.4 `langgraph` / `langgraph-bigtool`

可借：

- 显式 stateful workflow
- small candidate set first
- 工具候选集作为中间对象

不借：

- 把 LangGraph 当 StateBus runtime 替代品

为什么适合当前 StateBus：

- StateBus 的强项之一就是把“候选对象”和“handoff object”显式化。

### 2.5 `semantic-router`

可借：

- route layer
- threshold / abstain
- ambiguous case 设计

不借：

- 用 semantic router 本身替代 state-transfer benchmark

为什么适合当前 StateBus：

- 新 family 应该显式包含 clean / distractor / ambiguous 三类对象。

### 2.6 `AgentRx`

可借：

- trajectory IR
- failure-step localization
- auditable misfire log

不借：

- 把 failure diagnosis 反客为主变成主 benchmark

为什么适合当前 StateBus：

- 它更适合放到 misfire / observability 侧，而不是 formal headline。

### 2.7 `memsearch` / `mem0`

可借：

- progressive retrieval
- hybrid retrieval
- working / long-term split
- memory unit 的结构化形态

不借：

- 把聊天记忆产品逻辑直接等同于 StateBus replay gain

为什么适合当前 StateBus：

- 后续 memory family 应该复用“结构化经验单元”，而不只是复用一段摘要文本。

---

## 3. 现在最值得先做哪类 family

结论先说：

> 当前第一优先级不是代码修复 benchmark，也不是纯文本摘要 benchmark，
> 而是“发布回归协作链 family”。

原因：

1. 它最贴赛题
2. 它最贴当前 executor/tool surface
3. 它最容易把 `Planner -> Retriever -> Executor -> Summarizer` 串成更厚的对象
4. 它最容易放大 structured carrier 的优势

### 为什么不是“代码分析/修复”优先

不是说代码分析没价值，而是当前不该先做它。

原因：

1. 当前 executor/tool registry 仍然是 incident / playbook 风格
2. 如果现在硬切到代码修复，会把 task family 扩张和 executor 能力扩张绑在一起
3. 这样很难判断最后变强的是 carrier，还是只是 executor 语义被改了

### 为什么不是“纯文本摘要”优先

因为纯摘要题太容易退化成：

- 谁更会写字
- 谁更会压缩语言

这会削弱：

- 非文本状态传递
- 参数化 handoff
- 连续任务修正

---

## 4. 我建议的 3 类 family

### Family A：发布回归协作链

定位：

- 当前最值得先落地
- 先服务 `state_transfer`

任务对象：

- release 后出现回归
- 需要从 incident / metrics / logs / rollout diff / runbook 综合判断
- 后续会插入新证据和缩小 scope

关键中间对象：

- 候选原因
- 冲突证据
- 第一动作
- 验证检查

最适合的 lane：

- `state_transfer carrier`
- `state_transfer authenticity`
- `natural_support` 仅 support

### Family B：参数化执行交接

定位：

- 第二优先级
- 放大 structured handoff 的字段优势

任务对象：

- executor 不只选 tool
- 还要消费
  - `action_type`
  - `target_scope`
  - `validation_checks`
  - `fallback`

当前判断：

- 方向是对的
- 但要等 executor/tool contract 稍微扩一层再做
- 不建议和当前 family 扩张一起开

### Family C：连续近邻任务 + 共享记忆复用

定位：

- memory 线的正题

任务对象：

- 同服务、同知识域、不同实例
- 第 2/3 个任务不是重做，而是带历史先验的新实例

要复用的 memory 单元更像：

- component signature
- failure mode
- validated checks
- unsafe actions

当前判断：

- 值得做
- 但应建立在 Family A 任务对象稳定之后

---

## 5. 当前实际落地顺序

只建议这个顺序：

1. 先落 `Family A`
2. 用同一 family 映射出
   - carrier pack
   - authenticity pack
   - natural support pack
3. 先跑 `repeat=3`
4. 如果 carrier 方向开始稳定，再考虑 `repeat=10`
5. 再扩 `Family C`
6. 最后才考虑 `Family B`

---

## 6. Family A 的具体对象

### 6.1 统一 artifact 形态

每个任务步骤从下列 artifact 中取 `3-5` 份：

- incident report
- metrics snapshot
- log excerpt
- rollout / config diff
- runbook excerpt
- scope note
- distractor evidence

### 6.2 每个 family 至少 3 步

每个 group 建议固定：

1. `step1`
   - 初始诊断
2. `step2`
   - 新证据插入
3. `step3`
   - scope 缩小 / 动作修正 / 验证窗口收紧

### 6.3 必须包含的 case 类型

每个 family 里至少要有：

- clean case
- distractor case
- route-ambiguous pressure
- follow-up narrowing

---

## 7. 当前最值得先落的 draft family

当前最值得先落的是：

> `contest_release_regression_carrier_benchmark.yaml`

为什么选它：

1. 完全贴当前 executor 工具面
2. 不需要先扩新工具
3. 比当前 repo-local triage 更像赛题里的多步协作对象
4. 能直接拿来做 carrier 对照

对应新 corpus：

- `tasks/contest_release_regression_corpus.yaml`

当前 draft 先放 3 个 group：

1. `checkout_release_chain`
   - `db_pool_saturation`
2. `auth_rotation_chain`
   - `auth_session_drift`
3. `inventory_rollout_chain`
   - `cache_invalidation`

每个 group 3 步，每步做：

- `text_packet_minimal`
- `state_packet_minimal`

因此当前 carrier draft 共 `18` 个任务。

---

## 8. 为什么这版比当前 formal carrier pack 更好

相对当前 `cache / latency / session` 的单点 triage，对这版 draft 更有利的是：

1. artifact 更厚
2. follow-up 更明显
3. handoff 不再只是“一句 route 判断”
4. 更像 release regression 协作对象
5. 更贴赛题“连续任务 + 非文本状态 + 结构化协作”

但它仍然保持：

- repo-local
- 可复现
- 不开放世界
- 不混 memory headline

---

## 9. 下一步建议

建议直接做这个顺序：

1. 先审一遍 `tasks/contest_release_regression_corpus.yaml`
2. 再决定是否补一份同 family 的 authenticity draft pack
3. 若对象满意，先用这份 carrier draft 跑 `repeat=3`
4. 看 signal 是否比当前三类 triage family 更稳定

一句话收束：

> 当前最值的不是继续加 `repeat=10`，也不是先跳去代码修复 benchmark，
> 而是先把 formal `state_transfer` 的对象升级成更贴赛题的发布回归协作链。

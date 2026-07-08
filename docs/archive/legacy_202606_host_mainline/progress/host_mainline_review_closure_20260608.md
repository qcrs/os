# StateBus Host-Mainline 收口审计

日期：`2026-06-08`

适用范围：这份文档只收口当前 `/home/qcrs/statebus/project` 的 host-mainline 结论，不把 Docker、openEuler VM、`nsjail`、强沙箱终态、hidden-state/KV 传递拉回当前执行主线。

## 1. 先给结论

1. 当前最强的 `structured vs text` 正式证据，已经不是 deterministic 包，而是新的 serialized real API 包：
   - `runs/host_goal_eval_20260608_162206_role_phase_telemetry_refresh/api_repeat10_serial/`
2. deterministic 包现在主要证明：
   - host-mainline 稳定性
   - replay / reuse headline
   - control-plane bytes 差异
   - 它不证明 token 优势，因为 deterministic 运行里 `llm_total_tokens = 0`
3. 这轮 telemetry 补完之后，`structured` 的优势可以更诚实地拆成三层：
   - `control_bytes`
   - `llm_total_tokens`
   - `task_ms`
   同时还能把“结构化通信优势”和“replay/reuse 联合收益”分开看。
4. 当前 host-mainline 赛题主骨架已经完成，但还没有进入“只剩调参”的阶段。
5. 当前最值得继续做的，不是强沙箱，不是再补一层 report，而是让执行层从 `route-aware playbook selector` 再往前走一步：
   - 先做小候选工具检索
   - 再做 threshold / abstain
   - 再决定执行或回退 collect-more-evidence

## 2. 新 formal API 包到底证明了什么

证据包：

- diagnostic：`runs/host_goal_eval_20260608_162206_role_phase_telemetry_refresh/api_repeat1_serial_diagnostic/`
- formal：`runs/host_goal_eval_20260608_162206_role_phase_telemetry_refresh/api_repeat10_serial/`

formal `repeat=10` aggregate：

| mode | control_bytes | llm_total_tokens | task_ms | memory_hit_rate | skipped_step_count | reuse_gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| text | 103590.40 | 21106.90 | 90725.26 | 0.80 | 9.00 | 0.17 |
| protocol | 89047.00 | 15031.10 | 75143.35 | 0.80 | 9.00 | 0.17 |

这说明：

1. `protocol` 相对 `text`，当前正式证据里三项都更好：
   - control bytes 更低
   - total tokens 更低
   - serialized API latency 更低
2. replay headline 没变：
   - 两边都是 `memory_hit_rate = 0.80`
   - 两边都是 `skipped_step_count = 9`
   - 两边都是 `reuse_gain = 0.17`
3. 所以这轮最好不要再把结论写成“structured 更好，因为 replay 更强”。
4. 更准确的写法是：
   - replay/reuse headline 目前基本持平
   - `structured` 的新增正式优势主要体现在通信和 LLM token / planner latency 上

## 3. 新 role/phase telemetry 带来的关键判断

role-level token：

| mode | planner_total_tokens | summarizer_total_tokens | llm_total_tokens |
| --- | ---: | ---: | ---: |
| text | 12079.20 | 9027.70 | 21106.90 |
| protocol | 6010.30 | 9020.80 | 15031.10 |

phase timing：

| mode | planner_ms | retrieve_ms | execute_ms | summarize_ms | phase_overhead_ms | task_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| text | 46896.87 | 8300.89 | 1922.55 | 31869.08 | 1735.88 | 90725.26 |
| protocol | 32481.78 | 8547.68 | 1912.73 | 30434.45 | 1766.72 | 75143.35 |

最重要的新判断只有一个：

> 当前结构化优势主要落在 `Planner`，不是 `Summarizer`。

具体表现：

- planner tokens：`12079.20 -> 6010.30`
- summarizer tokens：`9027.70 -> 9020.80`
- planner latency：`46896.87 -> 32481.78 ms`
- summarize latency：也有改善，但幅度远小于 planner

所以这轮 telemetry 的价值不是“多了一组漂亮指标”，而是把下面两个东西拆开了：

1. 结构化通信本身确实在减少 planner 负担。
2. replay/reuse headline 并不是这轮 `protocol` 优势的主要来源。

## 4. 赛题要求对照后的 host-only 判断

| 赛题对象 | 当前判断 | 边界说明 |
| --- | --- | --- |
| 至少 3 个 Agent | 已完成 | `Planner/Retriever/Executor/Summarizer` 已真实跑通 |
| `text/protocol` 双模式 | 已完成 | 同一任务链、同一 benchmark 持续对比 |
| 结构化通信 | 已完成 | protobuf control frames 已在主线 |
| 非文本中间态 | 已完成 | `StateRef / FEATURE_BUNDLE / EMBEDDING / DENSE_EVIDENCE` 是真实路径 |
| 共享记忆与复用 | 已完成 | SQLite + FAISS + assist/replay 分层都已在主线 |
| 关联连续任务 | 已完成 | 当前为 3 组 x 6 任务 |
| benchmark 指标展示 | 已完成 | 已能拆 control bytes / tokens / phase timing / reuse |
| 10 轮稳定运行 | host-only 已完成 | deterministic repeat-10 与 serialized API repeat-10 都已有新证据 |
| openEuler 最终交付 | 未完成 | 这本来就不属于本轮主线 |

硬判断：

1. 当前仓库不是“只剩文档包装”的状态。
2. 当前仓库也不是“开放任务上的通用多 Agent runtime 完成态”。
3. 更准确的定位仍然是：
   - 一个真实可运行的 host-side contest mainline
   - 带共享记忆、结构化通信和受控 replay
   - 但执行层仍明显带有固定 route / playbook 形状

## 5. 无 sudo 时 sandbox 到底能不能试

这轮只回答可行性，不把沙箱实现拉成主线。

当前宿主机事实：

- `unshare` 存在：`/usr/bin/unshare`
- `bwrap` 存在：`/usr/bin/bwrap`
- `/proc/sys/kernel/unprivileged_userns_clone = 1`
- `/proc/sys/user/max_user_namespaces = 4125443`
- `unshare -Ur true` 已直接成功

据此可以明确分四类：

### 5.1 当前可做轻量验证

- user namespace
- `unshare -Ur`
- `bwrap` / bubblewrap 风格的用户态隔离
- 更收紧的 subprocess 执行目录、只读绑定、临时工作目录

这类路线的结论是：

> 当前宿主机上可行，可以做轻量 host-side 验证。

### 5.2 真实宿主机可做，但当前 goal 不值得先做

- 执行层命令白名单进一步工程化
- 更明确的文件系统只读/可写边界
- 基于 user-space sandbox 的 executor smoke lane

这类路线的问题不在“做不了”，而在“现在不是收益最高的下一步”。

### 5.3 需要 root / sudo / 系统级安装

- `nsjail`
- 更强的 seccomp / cgroup / mount policy
- Docker daemon 路线
- openEuler 上的正式交付型隔离验证

这类路线当前不能被写成 host-mainline 已具备。

### 5.4 当前不值得作为下一主线

原因很直接：

1. 赛题 host-mainline 主骨架已经能跑。
2. 当前最明显的系统弱点不在“完全没有隔离”，而在“执行层仍偏固定 playbook 选择器”。
3. 所以 sandbox 这轮最诚实的结论是：
   - `当前可做轻量验证`
   - `当前不值得先做成主线实现`

## 6. 静态知识检索要不要单独维护

结论：**值得有一个更明确的 repo-local 静态知识层，但不值得在这轮扩成新的外部 RAG 系统。**

先把边界说清楚：

1. repo-local corpus
   - 作用：当前任务证据检索、playbook 触发前的事实支撑
   - 形态：任务文档、故障描述、样例语料
2. 共享记忆
   - 作用：assist / replay
   - 形态：运行后沉淀的摘要、replay artifacts、reuse evidence
3. 脚本 / 工具说明层
   - 作用：告诉执行层“有什么可用能力、何时该用、何时该 abstain”
   - 形态：playbook capability note、tool usage note、failure mode note

所以 `Retriever` 不能被简化成“只查共享记忆”。当前至少还是三层对象：

- repo-local 任务证据
- 工具/能力说明
- 运行后共享记忆

如果要维护更明确的 repo-local 知识层，最值得放进去的是：

1. playbook / capability / tool usage note
2. repo-local 常见故障模式与排障摘要
3. benchmark task family 的结构化摘要
4. 适合 embedding 的短摘要，而不是长原文堆叠

不建议这轮做的事情：

1. 再引一个平行向量数据库主线
2. 为了“像 RAG”而复制一套新存储系统
3. 把 memory store 和静态知识层混成一个对象

## 7. 当前工具层要不要加强

结论：**要，但要收敛到“小候选工具检索 + abstain discipline”，不是扩工具数量，也不是重做执行架构。**

当前更适合留在固定工具层的，仍然是：

- playbook execution
- repo-local 查询
- 脚本/状态/环境探测

值得沉淀成小工具，而不是继续塞 prompt 的，是：

- capability lookup
- tool usage note lookup
- collect-more-evidence fallback
- ambiguity explanation / refusal reason

当前不建议直接上主线的，是：

- 重型 CodeAct
- 宽泛 shell agent
- 一大批新工具注册

原因是当前最需要的不是“更多工具”，而是“工具选择更诚实”。

## 8. `third_party/` 借什么，不借什么

### 8.1 `langgraph-bigtool`

借：

- `retrieve_tools` 先收小候选工具集，再执行
- 工具描述单独索引，而不是把所有工具直接暴露给 Planner / Executor

不借：

- 整个 LangGraph runtime 替换
- 为了扩工具生态而提前扩大工具表

### 8.2 `semantic-router`

借：

- threshold discipline
- close-call abstain
- no-match 返回空路由

不借：

- 把现有 feature bundle / route 全部外包给新框架

### 8.3 `memsearch`

借：

- source-of-truth 与 shadow index 分离
- 静态知识短摘要优先，而不是长原文优先

不借：

- 新外部 memory 产品化形态
- 当前仓库不需要多平台代理层

### 8.4 `AgentRx`

借：

- 轨迹审计思路
- invariant/checker 风格的失败归因层

不借：

- 整条重型 trajectory diagnosis pipeline

### 8.5 `langgraph` / `haystack`

借：

- pipeline node 边界更明确
- short-term / long-term / checkpoint 分层表达

不借：

- 框架级重写
- 为了“更像通用 agent 平台”而冲淡当前 host-mainline

## 9. 只选一条下一步主线

我建议的单一路线是：

> **做一层轻量的 tool retrieval + abstain executor。**

具体不是“只做 Retriever”，而是四件成套的小事：

1. 给现有 playbook / tool 建一个 repo-local capability index
2. `Executor` 先拿 query + feature bundle 检索出小候选工具集
3. 对 close-call 和 low-confidence 情况显式 abstain 到 `tool.collect_more_evidence`
4. benchmark 新增面向 fresh retrieval / ambiguous routing 的定向 slice

为什么它是当前最值得做的：

1. 它直接打当前最明显的系统弱点：
   - executor 仍偏 `route-aware playbook selector`
2. 它仍然停在 host-mainline：
   - 不需要 Docker
   - 不需要 openEuler
   - 不需要 `nsjail`
3. 它比继续补 telemetry 更接近真实能力提升：
   - telemetry 现在已经够支撑下一轮判断
4. 它比先做 sandbox 更值：
   - sandbox 现在是“能做轻量验证，但不是最强增益点”
5. 它比直接上 CodeAct 更稳：
   - 先把工具选择做诚实，再谈更宽的执行自由度

## 10. 本轮收口结论

这轮 goal 到这里可以收口成一句话：

> `structured vs text` 的正式比较口径已经比之前干净，新的 serialized API formal 包已经给出更可信的 token / latency 证据；host-only review 之后，最值得继续的主线不是强沙箱，也不是再补报告，而是把 executor 推进到“先检索小候选工具集，再 threshold / abstain”的更诚实形态。

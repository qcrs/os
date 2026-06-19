# LangGraph 在 Demo 中的作用清单

## 一、图构建与执行（langgraph.graph）

| API | 作用 | Demo 中的使用位置 |
|-----|------|------------------|
| `StateGraph` | 核心图构建器，定义节点和边 | `graph.py` — 构建 ResearchState 图 |
| `START` | 图入口哨兵节点 | `graph.py` — `add_edge(START, "planner")` |
| `END` | 图出口哨兵节点 | `graph.py` — `add_edge("summarizer", END)` |
| `add_node(name, fn)` | 注册 Agent 函数为图节点 | `graph.py` — 注册 planner/retriever/executor/summarizer |
| `add_edge(src, dst)` | 定义无条件有向边 | `graph.py` — 串联四个节点 |
| `add_conditional_edges(src, fn, targets)` | 定义条件路由 | `graph.py` — planner 之后根据子查询数量动态路由 |
| `compile(store=...)` | 编译图，注入共享 Store | `graph.py` — 将 InMemoryStore 注入编译后的图 |
| `graph.invoke(input)` | 同步执行编译后的图 | `run_demo.py` — 执行 Task A 和 Task B |

## 二、动态扇出（langgraph.types）

| API | 作用 | Demo 中的使用位置 |
|-----|------|------------------|
| `Send("retriever", payload)` | 动态并行派发节点调用 | `graph.py` — `fan_out_retrieval()` 根据子查询数量创建多个 Send 包 |

**原理**：planner 拆分出 N 个子查询 → `fan_out_retrieval` 返回 N 个 `Send` 包 → LangGraph 自动并行调用 N 次 retriever → 结果通过 `Annotated[list, operator.add]` 汇总。

## 三、结构化状态与通道（隐式 API）

| 模式 | 作用 | Demo 中的使用位置 |
|------|------|------------------|
| `TypedDict` 状态定义 | 类型化的图状态声明 | `graph.py` — `ResearchState(TypedDict, total=False)` |
| `Annotated[list[T], operator.add]` | 并行分支结果累加（fan-in） | `graph.py` — `documents` 字段，多个 retriever 的结果自动合并 |

**作用**：替代自然语言交互，Agent 之间通过 TypedDict 字段传递结构化数据。

## 四、共享记忆（langgraph.store）

| API | 作用 | Demo 中的使用位置 |
|-----|------|------------------|
| `InMemoryStore` | 进程内 KV 存储，支持语义搜索 | `memory.py` — 创建共享 Store 实例 |
| `InMemoryStore(index={...})` | 配置向量索引，启用语义搜索 | `memory.py` — CharacterEmbeddings + 50 维向量 |
| `BaseStore` | Store 抽象接口 | `agents.py` — 所有 Agent 函数的 store 参数类型 |
| `store.put(ns, key, value)` | 写入存储 | `memory.py` — 所有 Agent 写入计划/文档/分析/摘要 |
| `store.get(ns, key)` | 按 key 读取 | `memory.py` — 按需获取已存储内容 |
| `store.search(ns, query=..., limit=...)` | 语义向量搜索 | `memory.py` + `run_demo.py` — 跨任务记忆检索 |

**命名空间设计**：
- `("plans",)` — planner 写入的计划
- `("docs",)` — retriever 写入的检索文档
- `("analysis",)` — executor 写入的分析结果
- `("summaries",)` — summarizer 写入的摘要

## 五、LangChain 组件（被 LangGraph 调用）

| 组件 | 作用 | Demo 中的使用位置 |
|------|------|------------------|
| `ChatOpenAI` | LLM 调用（DeepSeek V4 兼容 OpenAI 接口） | `models.py` — 所有 Agent 调用 LLM |
| `SystemMessage` / `HumanMessage` | 消息格式 | `agents.py` — 构造 LLM 输入 |
| `JsonOutputParser` | JSON 输出解析 | `agents.py` — planner/executor/summarizer 解析 LLM 输出 |
| `Embeddings` | 向量嵌入基类 | `memory.py` — CharacterEmbeddings 实现 |

## 六、LangGraph 特性覆盖总结

```
┌─────────────────────────────────────────────────────┐
│                   LangGraph 框架                     │
├──────────────────┬──────────────────────────────────┤
│  图编排           │  StateGraph + add_node/edge      │
│  动态扇出         │  Send + add_conditional_edges    │
│  结构化状态       │  TypedDict + Annotated reducer   │
│  共享记忆         │  InMemoryStore + 语义搜索        │
│  编译执行         │  compile() + invoke()            │
└──────────────────┴──────────────────────────────────┘
```

Demo 用到的 LangGraph 特性：**5 大类，16 个 API**。

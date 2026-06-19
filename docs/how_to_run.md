# Multi-Agent Demo 运行指南

本 demo 位于 `examples/multi_agent_demo/`，当前版本使用：

- DeepSeek Chat：负责 planner / retriever / executor / summarizer 的文本生成。
- DashScope `text-embedding-v4`：负责 `InMemoryStore` 的语义向量检索。
- LangGraph `StateGraph`：负责编排 4 个 Agent 节点和状态传递。

## 环境要求

- Docker 容器 `langgraph-demo`（推荐）或 Python 3.10+ 环境。
- `DEEPSEEK_API_KEY`：DeepSeek Chat API key。
- `DASHSCOPE_API_KEY`：DashScope / 百炼 API key，用于 `text-embedding-v4`。
- 依赖：`langgraph`、`langchain-core`、`langchain-openai`、`dashscope`、`numpy`。

> 不要把 API key 写进 `config.py`。当前代码从环境变量读取 key。

---

## 方式一：使用已有 Docker 容器运行（推荐）

当前机器上已有容器 `langgraph-demo`。实测 demo 在容器内路径是 `/demo`。

### 1. 启动容器

```bash
docker start langgraph-demo
```

### 2. 进入容器

```bash
docker exec -it langgraph-demo bash
```

### 3. 安装/补齐依赖

容器里如果已经安装过，可以跳过；否则执行：

```bash
python3 -m pip install langgraph langchain-core langchain-openai dashscope numpy
```

其中 `numpy` 不是必需，但建议安装，否则 `InMemoryStore` 会退回纯 Python 向量计算，速度较慢。

### 4. 设置 API key

```bash
export DEEPSEEK_API_KEY="sk-cb5c286c1f484374a23b295b1a573224"
export DASHSCOPE_API_KEY="sk-e992f9a937724b63980e13a05008435d"
```

如果担心 shell history 记录 key，可以用静默输入：

```bash
read -s DEEPSEEK_API_KEY
export DEEPSEEK_API_KEY
read -s DASHSCOPE_API_KEY
export DASHSCOPE_API_KEY
```

### 5. 处理代理

本次实测中，文档旧代理 `10.1.72.10:7890` 连接超时；直连可以跑通。因此建议先清掉代理：

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
```

如果你的网络必须走代理，再改为可用代理地址：

```bash
export http_proxy="http://你的代理地址:端口"
export https_proxy="http://你的代理地址:端口"
```

### 6. 运行 demo

```bash
cd /demo
python3 -u run_demo.py
```

---

## 方式二：本地 Python/Conda 环境运行

当前宿主机默认 Python 缺少 demo 依赖，建议单独建环境。

### 1. 创建环境

```bash
conda create -n langgraph-demo python=3.11 -y
conda activate langgraph-demo
```

如果不用 Conda，也可以使用 venv：

```bash
cd /data/mingwei/Synapse
python3.11 -m venv .venv-demo
source .venv-demo/bin/activate
```

### 2. 安装依赖

在仓库根目录执行：

```bash
cd /data/mingwei/Synapse
python -m pip install -e langgraph/libs/checkpoint -e langgraph/libs/langgraph
python -m pip install langchain-core langchain-openai dashscope numpy
```

### 3. 设置 API key

```bash
export DEEPSEEK_API_KEY="你的 DeepSeek API key"
export DASHSCOPE_API_KEY="你的 DashScope API key"
```

### 4. 运行

```bash
cd /data/mingwei/Synapse
python -u run_demo.py
```

---

## 一次性 Docker 命令

如果不想进入容器，可以在宿主机执行以下命令。注意不要把真实 key 直接保存到脚本或提交到 Git。

```bash
docker start langgraph-demo

docker exec -it langgraph-demo bash -lc '
  export DEEPSEEK_API_KEY="你的 DeepSeek API key"
  export DASHSCOPE_API_KEY="你的 DashScope API key"
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
  cd /demo
  python3 -u run_demo.py
'
```

---

## 项目文件结构

```text
Synapse/
├── src/                # 核心代码
│   ├── config.py       # 配置常量，从环境变量读取 API key 和 embedding 配置
│   ├── models.py       # DeepSeek Chat 模型封装
│   ├── memory.py       # DashScope text-embedding-v4 + InMemoryStore 共享记忆
│   ├── metrics.py      # 性能指标采集（时延、Store 操作计数）
│   ├── agents.py       # 4 个 Agent 实现（planner/retriever/executor/summarizer）
│   ├── graph.py        # StateGraph 定义 + Send 扇出
│   └── protocol.py     # 结构化通信协议
├── run_demo.py         # 主入口，运行 2 组关联任务
├── docs/               # 项目文档
├── langgraph/          # LangGraph 框架（git submodule）
└── README.md
```

## Demo 运行流程

```text
run_demo.py
    │
    ├─ 初始化：DashScope embedding、Store、compiled graph、metrics
    │
    ├─ Task A: 分析 LangGraph 框架的多智能体协作机制、状态管理和记忆系统
    │   ├─ planner → 拆分子查询，写入 Store
    │   ├─ retriever ×N → 并行检索（Send 扇出），写入 Store
    │   ├─ executor → 分析文档，写入 Store
    │   └─ summarizer → 生成摘要，写入 Store
    │
    ├─ Task B: 基于之前的分析结果，设计改进的多智能体协作系统架构
    │   └─ 复用 Task A 写入的共享记忆
    │
    ├─ 记忆复用演示：从 Store 检索跨任务知识
    │
    └─ 输出性能报告
```

## 预期输出

一次完整运行会输出：

```text
Building multi-agent graph...
  Store: InMemoryStore with semantic search (text-embedding-v4, 1024 dims)

Task Group A_langgraph_analysis: ...
  [Planner]
  [Retrievers] (parallel fan-out)
  [Executor]
  [Summarizer]
  Task duration: ~20-40s

Task Group B_system_design: ...
  ...
  Task duration: ~20-40s

Memory Reuse Demonstration
  Found relevant memory item(s)

Performance Metrics Report
  node_planner / node_retriever / node_executor / node_summarizer
  Store Operations
  Memory Reuse
```

## 常见问题

### 1. `DASHSCOPE_API_KEY must be set`

没有设置 DashScope key。执行：

```bash
export DASHSCOPE_API_KEY="你的 DashScope API key"
```

### 2. `ProxyError` 或 `Connection to 10.1.72.10 timed out`

旧文档中的代理不可用。先尝试直连：

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
```

如果你的环境必须使用代理，请换成可用代理地址。

### 3. `NumPy not found`

这只是性能警告，不影响功能。建议安装：

```bash
python3 -m pip install numpy
```

### 4. `Hit rate: 700.0%` 或负的 framework overhead

这是当前 `metrics.py` 的统计公式问题：

- `memory_reuse_hits` 统计的是多处命中次数。
- `memory_reuse_attempts` 当前只加了 1 次。
- 并行 retriever 的节点耗时简单相加，会大于 wall-clock 任务总耗时。

因此这两个指标当前只能作参考，不能作为严格性能提升结论。

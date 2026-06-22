# Multi-Agent Demo 运行指南

本 demo 位于仓库根目录 `/data/mingwei/SynapseX`，核心代码在 `src/`，入口脚本在根目录。

当前代码支持两类 Chat 后端：

- **OpenAI 兼容后端**：默认 `CHAT_BACKEND=openai`，默认 base URL 为 `https://api.deepseek.com`，默认模型为 `deepseek-chat`。
- **本地 Transformers 后端**：设置 `CHAT_BACKEND=transformers` 后加载 `LOCAL_MODEL_PATH`，默认 `/data/models/Qwen3-8B`。

Embedding/共享记忆使用 `InMemoryStore(index=...)`：设置 `DASHSCOPE_API_KEY` 时使用 DashScope `text-embedding-v4`；未设置时自动使用 `LocalHashEmbeddings` 本地 fallback，不会因为缺少 DashScope key 直接退出。长期记忆默认启用，写入 `.memory/shared_memory.jsonl`，下一次启动会自动加载历史 MemoryUnit。

> 不要把 API key 写入文档或 `config.py`。当前代码从环境变量读取 key。

## 环境要求

- Python 3.10+（建议 Python 3.11）。
- 基础依赖：`langgraph`、`langchain-core`、`langchain-openai`、`dashscope`、`numpy`。
- 本地 Transformers 后端额外依赖：`transformers`、`torch`、`accelerate`，以及可访问的本地模型目录。

## 安装依赖

在仓库根目录执行：

```bash
cd /data/mingwei/SynapseX
python -m pip install langgraph langchain-core langchain-openai dashscope numpy
```

如果要使用本地 Qwen3-8B / Transformers 后端，再安装：

```bash
python -m pip install transformers torch accelerate
```

如果要使用仓库内的 LangGraph 子模块版本，而不是 PyPI 版本，可安装本地包：

```bash
python -m pip install -e langgraph/libs/checkpoint -e langgraph/libs/langgraph
```

## 长期共享记忆

默认启用长期记忆。所有通过 `store_put()` 写入的 `MemoryUnit` 会追加保存到仓库根目录的 `.memory/shared_memory.jsonl`；下一次运行 `create_store()` 时会自动加载该文件里的最新记忆，并重新建立 `InMemoryStore` 的语义索引。

常用环境变量：

```bash
# 默认 1；设为 0/false/no 可临时关闭长期记忆
export PERSISTENT_MEMORY_ENABLED=1

# 默认 /data/mingwei/SynapseX/.memory/shared_memory.jsonl
export PERSISTENT_MEMORY_PATH=/data/mingwei/SynapseX/.memory/shared_memory.jsonl
```

如果要做一次完全干净的运行，可以临时关闭长期记忆或删除该 JSONL 文件。`.memory/` 已加入 `.gitignore`，不会把本地长期记忆提交到仓库。

## 方式一：本地 Transformers 后端

```bash
cd /data/mingwei/SynapseX
export CHAT_BACKEND=transformers
export CHAT_MODEL=qwen3-8b
export LOCAL_MODEL_PATH=/data/models/Qwen3-8B
export LOCAL_MODEL_DEVICE=cuda:0
export LOCAL_MODEL_DTYPE=bfloat16

# 可选：关闭 Qwen thinking 模板参数
export CHAT_DISABLE_THINKING=1

# 可选：使用 DashScope embedding；不设置则用 LocalHashEmbeddings
export DASHSCOPE_API_KEY="你的 DashScope API key"

python -u run_demo.py
```

`CHAT_BACKEND=transformers` 时，脚本不会要求 `DEEPSEEK_API_KEY`。Structured 模式下如果 `ENABLE_HIDDEN_STATE_TRANSFER=1`，planner/retriever 会捕获本地模型 pre-generation hidden state 并通过 `planner_hidden_state` / `hidden_state_payloads` 传递。

## 方式二：OpenAI 兼容后端

默认配置等价于 DeepSeek OpenAI 兼容接口：

```bash
cd /data/mingwei/SynapseX
export CHAT_BACKEND=openai
export CHAT_API_KEY="你的 Chat API key"
export CHAT_BASE_URL="https://api.deepseek.com"
export CHAT_MODEL="deepseek-chat"

# 兼容旧变量名：DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL 仍可使用
# export DEEPSEEK_API_KEY="你的 DeepSeek API key"

# 可选：使用 DashScope embedding；不设置则用 LocalHashEmbeddings
export DASHSCOPE_API_KEY="你的 DashScope API key"

python -u run_demo.py
```

OpenAI 兼容后端不会产生真实 Transformers hidden state；结构化模式仍会传递 `AgentMessage`、`context_packets` 和 `embedding_payloads`。

## 入口脚本

| 脚本 | 作用 | 输出文件 |
|------|------|----------|
| `run_demo.py` | 先跑 Text 模式 A/B 两组任务，再跑 Structured 模式 A/B 两组任务，并输出对比报告 | 仅终端输出 |
| `run_12rounds.py` | 12 轮连续任务，依次运行 Text 和 Structured 双模式对比 | `results_12rounds.json` |
| `run_structured_only.py` | 只跑 12 轮 Structured 模式，并尝试读取已有 `results_12rounds.json` 中的 Text 结果做对比 | `results_structured_only.json` |

## 三通道开关

Structured 模式下有三类可独立开关的结构化载荷：

```bash
export ENABLE_CONTEXT_PACKETS=1       # Retriever 构造压缩文本证据包，Executor 使用 compact evidence
export ENABLE_EMBEDDING_TRANSFER=1    # Retriever 生成 embedding_payloads，Executor 可用于排序
export ENABLE_HIDDEN_STATE_TRANSFER=1 # 本地 Transformers 后端捕获并传递 hidden state
```

相关细粒度参数：

```bash
export HIDDEN_STATE_CONTEXT_TOP_K=2
export HIDDEN_STATE_EVIDENCE_PER_DOC=1
export HIDDEN_STATE_EVIDENCE_CHARS=120
export EMBEDDING_MODEL=text-embedding-v4
export EMBEDDING_DIMS=1024
export EMBEDDING_BATCH_SIZE=10
```

## 项目文件结构

```text
SynapseX/
├── src/                    # 核心代码
│   ├── config.py           # 环境变量与常量配置
│   ├── models.py           # OpenAI 兼容 / Transformers Chat 后端
│   ├── memory.py           # DashScopeEmbeddings / LocalHashEmbeddings + InMemoryStore + JSONL 长期记忆
│   ├── metrics.py          # token、时延、Store、通信与压缩指标
│   ├── agents.py           # planner/retriever/executor/summarizer
│   ├── graph.py            # StateGraph 定义 + Send 扇出 + Store 注入
│   └── protocol.py         # AgentMessage、AgentCard、ContextPacket 与选择/压缩逻辑
├── run_demo.py             # A/B 两组任务双模式 demo
├── run_12rounds.py         # 12 轮双模式实验
├── run_structured_only.py  # 12 轮 Structured-only 实验
├── ablation_results/       # 消融实验结果
├── docs/                   # 项目文档
├── langgraph/              # LangGraph 子模块
└── README.md
```

## Demo 运行流程

```text
run_demo.py
    │
    ├─ 打印 AgentRegistry 能力发现摘要
    │
    ├─ Phase 1: Text 模式
    │   ├─ Task A: 分析 LangGraph 多智能体协作、状态管理和记忆系统
    │   └─ Task B: 基于 Task A 结果设计改进架构
    │
    ├─ 记忆复用演示：从 Store 的 summaries/plans/docs/analysis namespace 检索
    │
    ├─ Phase 2: Structured 模式
    │   ├─ AgentMessage 记录动作和结构化 params/result
    │   ├─ ContextPacket 将文档压缩为摘要、证据片段、引用和校验信息
    │   ├─ Embedding payload 作为非文本语义排序信号
    │   └─ 本地 Transformers 后端可传递 hidden state
    │
    └─ Phase 3: 输出 Text vs Structured 指标对比
```

## 常见问题

### 1. `DEEPSEEK_API_KEY not set` / Chat API key 为空

当 `CHAT_BACKEND` 不是 `transformers` 时，需要配置 Chat API key：

```bash
export CHAT_API_KEY="你的 Chat API key"
# 或兼容旧变量名
export DEEPSEEK_API_KEY="你的 DeepSeek API key"
```

### 2. 没有 `DASHSCOPE_API_KEY`

当前代码会自动使用 `LocalHashEmbeddings` fallback，可正常运行；只是语义检索质量不如 DashScope `text-embedding-v4`。如需启用 DashScope：

```bash
export DASHSCOPE_API_KEY="你的 DashScope API key"
```

### 3. `ProxyError` 或连接超时

先清理旧代理变量：

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
```

如果你的环境必须使用代理，请换成可用代理地址。

### 4. 本地模型加载失败

确认 `LOCAL_MODEL_PATH` 指向存在的 Hugging Face 模型目录，并确认 GPU/CPU 设备配置可用：

```bash
ls /data/models/Qwen3-8B
export LOCAL_MODEL_DEVICE=cuda:0
```

### 5. 共享记忆命中率或 framework overhead 不直观

`metrics.py` 中 `memory_reuse_hits` 是多处搜索命中累计值，`memory_reuse_attempts` 是脚本层手动计数；并行 retriever 的节点耗时会累加，因此可能大于 wall-clock 任务耗时。这些指标适合做相对参考，不宜单独作为严格性能结论。

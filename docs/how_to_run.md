# SynapseX 运行指南

SynapseX 位于仓库根目录 `/data/mingwei/SynapseX`，核心代码在 `src/`，常规入口脚本在根目录，任务实验入口在 `task/` 和 `exp/`。

当前主流程架构为：

```text
planner → researcher(s) → analyst → executor → summarizer
```

其中 `context_packets` 压缩的是 `researcher → analyst` 的上下文材料；机器评测任务优先读取 `executor.final_answer` / `executor.extracted_answers`，`summarizer.summary` 只作为人类可读总结。

当前代码支持两类 Chat 后端：

- **OpenAI 兼容后端**：默认 `CHAT_BACKEND=openai`，默认 base URL 为 `https://api.deepseek.com`，默认模型为 `deepseek-chat`；也可以指向本机 vLLM 的 OpenAI-compatible API。
- **本地 Transformers 后端**：设置 `CHAT_BACKEND=transformers` 后加载 `LOCAL_MODEL_PATH`，默认 `/data/models/Qwen3-8B`。

运行期文档使用无索引的 `InMemoryStore`，只按 `doc_key` 回取完整文档以校验 `context_packet`。跨任务复用只使用 Qdrant；embedding 只服务 Qdrant 和记忆相关的 structured 向量排序，不参与运行期文档回传。

> 不要把 API key 写入文档或 `config.py`。当前代码从环境变量读取 key。

## 环境要求

- Python 3.10+（建议 Python 3.11）。
- 基础依赖：`langgraph`、`langchain-core`、`langchain-openai`、`dashscope`、`numpy`。
- 本地 Transformers 后端额外依赖：`transformers`、`torch`、`accelerate`，以及可访问的本地模型目录。
- 如果要跑 `task/group1_*` CSV 评测，建议环境里有 `pandas`；如需严格复现统计检验类任务，还需要 `scipy`。

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
python -m pip install -e third_party/langgraph/libs/checkpoint -e third_party/langgraph/libs/langgraph
```

## 长期共享记忆

长期记忆默认使用 Qdrant。`analysis`、`summary` 和可选 `task_state` 会写入配置的 Qdrant collection；planner 只从这里检索候选记忆。运行期完整文档不会写入 Qdrant。

常用环境变量：

```bash
# 设为 0/false/no 可完全关闭跨任务记忆
export LONG_TERM_MEMORY_ENABLED=1

# 为一次实验指定隔离的本地 Qdrant 数据目录和 collection
export LONG_TERM_MEMORY_QDRANT_PATH=.memory/experiments/qwen/data/qdrant
export LONG_TERM_MEMORY_COLLECTION=shared_memories_qwen_1024

# 本地 embedding 服务已启动时使用它；否则可选 dashscope 或 local_hash
export EMBEDDING_BACKEND=local_api
```

如果要做一次完全干净的运行，使用新的 Qdrant 目录和 collection，或设 `LONG_TERM_MEMORY_ENABLED=0`。`.memory/` 已加入 `.gitignore`，不会把本地记忆提交到仓库。

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

`CHAT_BACKEND=transformers` 时，脚本不会要求 `DEEPSEEK_API_KEY`。Structured 模式只传递 `AgentMessage`、`context_packets` 和 `embedding_payloads`。

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

结构化模式会传递 `AgentMessage`、`context_packets` 和 `embedding_payloads`；模型级中间状态复用请使用 trueKV/KV cache 实验路径。

### 使用本机 vLLM / Qwen3-8B OpenAI 兼容接口

在 `SynapseX-wang` 容器内，本次实验使用已启动的 vLLM 服务：

```bash
cd /data/mingwei/SynapseX
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
export CHAT_BACKEND=openai
export CHAT_API_KEY=EMPTY
export CHAT_BASE_URL=http://127.0.0.1:8000/v1
export CHAT_MODEL=/data/models/Qwen3-8B
export CHAT_DISABLE_THINKING=1
```

可用下面命令检查模型服务：

```bash
python3 - <<'PY'
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:8000/v1/models", timeout=3).read().decode()[:500])
PY
```

## 入口脚本

| 脚本 | 作用 | 输出文件 |
|------|------|----------|
| `run_demo.py` | SynapseX 基础示例入口：先跑 Text 模式 A/B 两组任务，再跑 Structured 模式 A/B 两组任务，并输出对比报告 | 仅终端输出 |
| `run_12rounds.py` | 12 轮连续任务，依次运行 Text 和 Structured 双模式对比 | `results_12rounds.json` |
| `run_structured_only.py` | 只跑 12 轮 Structured 模式，并尝试读取已有 `results_12rounds.json` 中的 Text 结果做对比 | `results_structured_only.json` |
| `task/run_group1_single.py` | 跑 Group1 Titanic 单协议实验，`--mode text` 为 Protocol A，`--mode structured` 为 Protocol B | JSON 写到 stdout，通常重定向到 `exp/comm_exp/*.json` |

## 三通道开关

Structured 模式下有三类可独立开关的结构化载荷：

```bash
export ENABLE_CONTEXT_PACKETS=1       # researcher 构造压缩文本证据包，analyst 使用 compact evidence
export ENABLE_EMBEDDING_TRANSFER=1    # researcher 生成 embedding_payloads，analyst 可用于排序
```

相关细粒度参数：

```bash
export EMBEDDING_MODEL=text-embedding-v4
export EMBEDDING_DIMS=1024
export EMBEDDING_BATCH_SIZE=10
```

## Task1 Context Packets A/B 对照实验

本节记录本次在 `SynapseX-wang` 容器里跑 Group1 Titanic 任务的推荐流程。任务文件是 `task/group1_tasks.json`，gold 文件是 `task/group1_gold.json`，结果报告写入 `exp/comm_exp/task1_context_packets.md`。

### 实验口径

- **Protocol A**：`mode=text`，纯文本传输。
- **Protocol B**：`mode=structured`，只启用压缩文本 `context_packets`，关闭 embedding 非文本通道。
- **记忆隔离**：实验时设置 `LONG_TERM_MEMORY_ENABLED=0`，避免历史 Qdrant 记忆影响结果。
- **模型后端**：推荐使用 vLLM OpenAI-compatible API 跑 `/data/models/Qwen3-8B`，比直接 Transformers 加载更快。
- **评测来源**：只比较 executor 输出的 `extracted_answers`；`summary` 不参与自动评测。

### Protocol A 命令

```bash
cd /data/mingwei/SynapseX
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

CHAT_BACKEND=openai \
CHAT_API_KEY=EMPTY \
CHAT_BASE_URL=http://127.0.0.1:8000/v1 \
CHAT_MODEL=/data/models/Qwen3-8B \
CHAT_DISABLE_THINKING=1 \
EXPERIMENT_CONTAINER=SynapseX-wang \
LONG_TERM_MEMORY_ENABLED=0 \
ENABLE_CONTEXT_PACKETS=0 \
ENABLE_EMBEDDING_TRANSFER=0 \
python3 -u task/run_group1_single.py --mode text \
  > exp/comm_exp/task1_protocol_a_text.json \
  2> exp/comm_exp/task1_protocol_a_text.log
```

### Protocol B 命令

```bash
cd /data/mingwei/SynapseX
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

CHAT_BACKEND=openai \
CHAT_API_KEY=EMPTY \
CHAT_BASE_URL=http://127.0.0.1:8000/v1 \
CHAT_MODEL=/data/models/Qwen3-8B \
CHAT_DISABLE_THINKING=1 \
EXPERIMENT_CONTAINER=SynapseX-wang \
LONG_TERM_MEMORY_ENABLED=0 \
ENABLE_CONTEXT_PACKETS=1 \
ENABLE_EMBEDDING_TRANSFER=0 \
python3 -u task/run_group1_single.py --mode structured \
  > exp/comm_exp/task1_protocol_b_structured.json \
  2> exp/comm_exp/task1_protocol_b_structured.log
```

### 进度与结果检查

运行中可看日志：

```bash
tail -f exp/comm_exp/task1_protocol_a_text.log
tail -f exp/comm_exp/task1_protocol_b_structured.log
```

完成后检查 JSON 是否跑满 10 轮，以及答案是否来自 executor：

```bash
python3 - <<'PY'
import json
for p in [
    'exp/comm_exp/task1_protocol_a_text.json',
    'exp/comm_exp/task1_protocol_b_structured.json',
]:
    data = json.load(open(p, encoding='utf-8'))
    first = data['rounds'][0]
    print(p, data['mode'], len(data['rounds']), data['metrics_summary']['total_tokens'])
    print('answer_source=', first.get('answer_source'), 'final_answer=', first.get('final_answer'))
PY
```

报告中的关键指标包括：

- `LLM 调用`、`输入 tokens`、`输出 tokens`、`总 tokens`。
- `Context 压缩`：`context_original_chars → context_compressed_chars`，表示传给 analyst 的 researcher 上下文文本压缩量。
- `context_packets_reliable / rehydrated / failed`：压缩包验证是否通过，以及是否回退到 Store 原文片段。
- `答案字段准确率` 和 `正确性评估`：按 `task/group1_gold.json` 中列出的字段比较 executor 的 `extracted_answers`。

当前没有单独的固定报告生成脚本；本次报告是根据两个 JSON、`task/group1_tasks.json` 和 `task/group1_gold.json` 聚合生成的。如果重跑 A/B，需要同步刷新 `exp/comm_exp/task1_context_packets.md`，至少包含：总体 token/耗时、分 agent token、context packet 计数、逐轮 gold 对比和实验观察。

### 本次实验经验

- 如果 `context_packets_reliable=0` 且大量 `rehydrated`，通常是压缩验证太严格或 evidence span 不适配 LLM 生成文本；现在验证逻辑以结构正确性为主，query coverage 只作为 warning。
- `context_packets` 主要减少 `analyst` 输入中的 context 部分，不会压缩 planner 指令，也不会压缩发往其他 agent 的所有内容。
- Group1 当前 prompt 只把 `titanic.csv` 前 40 行塞进 query，而 gold 是完整 CSV 口径；因此 A/B 正确率低时，优先检查“数据口径/是否真正读取完整 CSV”，不要直接归因到通信协议。
- 如果要评估通信协议本身，最好让 executor 读取完整 CSV 并做确定性 pandas/scipy 计算，再比较 A/B 的 token、耗时、压缩率。
- vLLM 多轮输出可能仍有数值计算误差；现在格式抽取问题已经和 summarizer 解耦，`summary` 不按 `@field[value]` 输出不再影响机器评测。

## 项目文件结构

```text
SynapseX/
├── src/                    # 核心代码
│   ├── config.py           # 环境变量与常量配置
│   ├── models.py           # OpenAI 兼容 / Transformers Chat 后端
│   ├── memory.py           # DashScopeEmbeddings / LocalHashEmbeddings + InMemoryStore + JSONL 长期记忆
│   ├── metrics.py          # token、时延、Store、通信与压缩指标
│   ├── agent/              # planner/researcher/analyst/executor/summarizer
│   ├── agents.py           # 兼容旧导入的聚合/别名模块
│   ├── graph.py            # StateGraph 定义 + Send 扇出 + Store 注入
│   └── protocol.py         # AgentMessage、AgentCard、ContextPacket 与选择/压缩逻辑
├── run_demo.py             # SynapseX 基础示例入口，A/B 两组任务双模式运行
├── run_12rounds.py         # 12 轮双模式实验
├── run_structured_only.py  # 12 轮 Structured-only 实验
├── ablation_results/       # 消融实验结果
├── docs/                   # 项目文档
├── third_party/            # 外部源码子模块
│   ├── langgraph/          # LangGraph 子模块
│   └── vllm/               # vLLM 子模块
└── README.md
```

## SynapseX 基础运行流程

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
    │   ├─ ContextPacket 将 researcher 文档压缩为摘要、证据片段、引用和校验信息
    │   ├─ analyst 选择并验证 context packet 后生成 analysis/candidate_answers
    │   ├─ executor 生成 execution artifact 和机器评测用 final_answer/extracted_answers
    │   ├─ summarizer 生成自然语言总结，不作为机器评测来源
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

`metrics.py` 中 `memory_reuse_hits` 是多处搜索命中累计值，`memory_reuse_attempts` 是脚本层手动计数；并行 researcher 的节点耗时会累加，因此可能大于 wall-clock 任务耗时。这些指标适合做相对参考，不宜单独作为严格性能结论。

# 性能对比实验报告

## 一、实验设计

### 1.1 实验目标

在相同任务条件下，对比"纯文本协作模式"和"结构化协议协作模式"的性能差异，验证结构化通信协议的 token/字符节省效果和非文本状态传递能力。

### 1.2 实验条件

| 项目 | 配置 |
|------|------|
| 任务 | Task A（LangGraph 框架分析）+ Task B（改进系统设计） |
| Agent | planner → retriever ×3（并行） → executor → summarizer |
| LLM | OpenAI 兼容 Chat 后端（实验原始记录使用 DeepSeek；当前代码也支持本地 Transformers） |
| Embedding | DashScope `text-embedding-v4`（1024 维）或 `LocalHashEmbeddings` fallback |
| 记忆 | InMemoryStore + 语义检索 |
| 运行环境 | Python 3.11；历史实验曾使用 Docker，当前仓库可在 `/data/mingwei/SynapseX` 直接运行 |

### 1.3 对照设计

- **text 模式**: 自然语言透传，Agent 输出直接写入 State，无结构化消息
- **structured 模式**: Agent 输出封装为 AgentMessage（含 action_type、params、result、embedding），通过 State.messages 传递
- 两种模式使用相同 query、相同任务分组、相同 LLM 参数

## 二、实验结果

### 2.1 LLM Token 对比（核心指标）

| 指标 | Text 模式 | Structured 模式 | 差值 |
|------|----------|----------------|------|
| LLM 调用次数 | 12 | 12 | 0 |
| **Input tokens** | **9,551** | **8,723** | **-828 (-8.7%)** |
| **Output tokens** | **6,710** | **5,882** | **-828 (-12.3%)** |
| **Total tokens** | **16,261** | **14,605** | **-1,656 (-10.2%)** |

按 Agent 分解：

| Agent | Text (in/out) | Structured (in/out) |
|-------|--------------|-------------------|
| planner | 539/334 | 448/267 |
| retriever ×6 | 467/3701 | 375/3311 |
| executor | 7051/1429 | 6312/1454 |
| summarizer | 1494/1246 | 1588/850 |

**Token 节省原因**：structured 模式下文档写入 Store，executor 的 prompt 中用 doc_key 引用而非全文拼接，减少了 input tokens。

### 2.2 运行时间对比

| 指标 | Text 模式 | Structured 模式 | 差值 |
|------|----------|----------------|------|
| Task A 耗时 | 29.82s | 23.99s | -5.83s (-19.6%) |
| Task B 耗时 | 27.60s | 27.03s | -0.57s (-2.1%) |
| **总耗时** | **57.42s** | **51.02s** | **-6.40s (-11.1%)** |

节点级耗时：

| 节点 | Text 模式 (avg) | Structured 模式 (avg) |
|------|----------------|----------------------|
| planner | 3.62s | 2.95s |
| retriever ×6 | 10.00s | 9.38s |
| executor | 7.97s | 7.63s |
| summarizer | 5.90s | 4.59s |

### 2.3 通信指标对比

| 指标 | Text 模式 | Structured 模式 |
|------|----------|----------------|
| Agent 消息次数 | 0（不可见） | **12**（全部可追踪） |
| 协议字符数 | 0（不可见） | **3,061** |
| embedding 传递 | 0 | **6 次 × 1024 维** |
| embedding 数据量 | 0 | **~24 KB**（6 × 1024 × 4 bytes） |

### 2.4 消息类型分布

| Action | 消息数 | 说明 |
|--------|--------|------|
| plan | 2 | planner → retriever（每个 Task 1 条） |
| retrieve | 6 | retriever → executor（3 并行 × 2 Task） |
| analyze | 2 | executor → summarizer |
| summarize | 2 | summarizer → output |

### 2.5 共享记忆命中

| 指标 | Text 模式 | Structured 模式 |
|------|----------|----------------|
| 记忆命中次数 | 7 | 7 |
| Store 操作数 | 33（12 put + 21 search） | 33（12 put + 21 search） |
| 检索平均分 | 0.625 | 0.654 |

## 三、Token 节省分析

### 3.1 实测 Token 数据

| 指标 | Text 模式 | Structured 模式 | 差值 |
|------|----------|----------------|------|
| Input tokens | 9,551 | 8,723 | **-828 (-8.7%)** |
| Output tokens | 6,710 | 5,882 | **-828 (-12.3%)** |
| Total tokens | 16,261 | 14,605 | **-1,656 (-10.2%)** |

### 3.2 节省原因分析

structured 模式 token 更少的原因：

1. **Store 引用替代全文拼接** — executor 的 input 中，text 模式拼接了文档全文（~7051 input tokens），structured 模式用 doc_key 引用（~6312 input tokens），节省 ~739 input tokens
2. **输出更精炼** — structured 模式下 LLM 输出倾向于结构化格式，output tokens 减少 ~828
3. **协议字符不额外消耗 LLM token** — AgentMessage 的 3,061 协议字符由 Python 代码生成，不经过 LLM

### 3.3 非文本传递的 token 替代

| 方式 | 传递语义信息 | token 开销 |
|------|------------|-----------|
| Text 模式 | 全文 ~2000 字符/文档 | ~500-700 token |
| Structured 模式 | 1024 维 embedding 向量 | **0 token**（非文本通道） |

6 次 embedding 传递替代了约 **3,000-4,200 token** 的文本通信，且不计入 LLM token 消耗。

### 3.4 协议开销

| 开销项 | 说明 |
|--------|------|
| AgentMessage 结构 | 3,061 字符，由 Python 代码生成，**不消耗 LLM token** |
| embedding 生成 | 6 次 DashScope API 调用，不计入 DeepSeek token |
| 时间开销 | 本次实验 structured 模式反而更快（-11.1%） |

## 四、结论

### 4.1 结构化协议的优势

1. **Token 节省**: 实测 -1,656 tokens（-10.2%），Store 引用机制减少了 input tokens
2. **可观测性**: 12 条消息全部可追踪（vs text 模式 0 条可见）
3. **非文本传递**: 6 次 embedding 传递（~24 KB），完全不消耗 LLM token
4. **协议规范**: action_type + structured params/result 替代自由文本
5. **性能无退化**: structured 模式总耗时反而更短（-11.1%）

### 4.2 注意事项

1. 单次实验存在 LLM 非确定性，需多次运行取均值
2. 当前两种模式都传递了 documents 字段（兼容设计），去掉后 token 节省更显著
3. embedding 生成有额外 API 调用成本（DashScope，非 DeepSeek token）

### 4.3 Token 节省总结

| 维度 | 效果 |
|------|------|
| LLM token 总量 | **-1,656 tokens (-10.2%)** |
| 其中 input tokens | -828 (-8.7%) |
| 其中 output tokens | -828 (-12.3%) |
| 非文本传递替代 | 6 次 embedding，~3,000-4,200 tokens 不经过 LLM |
| 协议字符开销 | 3,061 字符，Python 生成，不消耗 LLM token |

## 五、可复现步骤

```bash
cd /data/mingwei/SynapseX

# 方式 A：本地 Transformers 后端
export CHAT_BACKEND=transformers
export CHAT_MODEL=qwen3-8b
export LOCAL_MODEL_PATH=/data/models/Qwen3-8B
export LOCAL_MODEL_DEVICE=cuda:0

# 方式 B：OpenAI 兼容后端
# export CHAT_BACKEND=openai
# export CHAT_API_KEY="你的 Chat API key"
# export CHAT_BASE_URL="https://api.deepseek.com"
# export CHAT_MODEL="deepseek-chat"

# 可选：启用 DashScope embedding；不设置则使用 LocalHashEmbeddings
# export DASHSCOPE_API_KEY="你的 DashScope API key"

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
python -u run_demo.py
```

输出包含：
- Phase 1: Text 模式运行 2 个 Task Group
- Phase 2: Structured 模式运行 2 个 Task Group
- Phase 3: 双模式对比表 + 结构化通信指标

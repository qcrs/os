# D 模式 Latent KV 非文本状态传递设计 v1

本文档说明当前仓库中 D 模式的 latent KV 非文本状态传递设计与运行方式。D 模式的核心思想是：前半段继续使用可检查、可追踪的显式结构化协作，后半段把 Agent 中间推理状态保留在模型服务端的 KV cache 中，通过轻量 handle 在 Agent 间传递。

```text
planner -> 3×researcher -> analyst_latent -> executor_latent -> summarizer_latent
```

D 模式把多 Agent 协作拆成两个平面：

| 平面 | 内容 | 作用 |
|---|---|---|
| Control plane | plan、sub_queries、context_packets、latent_kv_handle_id | 轻量、可检查、适合 LangGraph 调度 |
| Data plane | server-side past_key_values tensors | 保存模型真实中间推理状态 |

这样，LangGraph state 中只需要传递结构化字段和 KV handle；真正高维、连续、模型原生的状态留在 GPU 模型服务中继续被后续 Agent 使用。

## 1. 设计目标

D 模式用于展示一种更贴近模型内部状态流动的多 Agent 协作方式：

1. planner 和 researcher 保持显式结构化输出，便于审计任务拆解和证据来源。
2. analyst 之后进入 latent KV 链路，减少长自然语言中间状态在 Agent 间反复生成和读取。
3. executor 和 summarizer 直接继承上游 KV handle，在已有推理状态上继续工作。
4. A/B/D 在业务拓扑上保持一致，D 只替换后半段状态传递机制。
5. 3 个 researcher 分支仍然并行产生 evidence/context packet，保证上下文覆盖面。

## 2. 当前拓扑

```text
┌─────────┐
│ planner │
└────┬────┘
     │ plan + 3 sub_queries
     ├───────────────┬───────────────┐
     ▼               ▼               ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│ researcher │  │ researcher │  │ researcher │
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      └───────────────┴───────────────┘
              context_packets + evidence refs
                         ▼
┌────────────────┐
│ analyst_latent │
└───────┬────────┘
        │ latent_kv_handle_id
        ▼
┌────────────────┐
│ executor_latent│
└───────┬────────┘
        │ latent_kv_handle_id
        ▼
┌──────────────────┐
│ summarizer_latent│
└──────────────────┘
        │ final answer
        ▼
      output
```

### 显式结构化区

planner 输出：

```json
{
  "plan": "A concise research plan",
  "sub_queries": [
    "focused sub-query 1",
    "focused sub-query 2",
    "focused sub-query 3"
  ]
}
```

3 个 researcher 分支分别输出：

```json
{
  "context_packets": [
    {
      "doc_key": "...",
      "source_query": "...",
      "summary": "...",
      "evidence_spans": [],
      "full_doc_ref": {
        "namespace": "docs",
        "key": "...",
        "text_hash": "..."
      }
    }
  ],
  "messages": ["AgentMessage(research)"]
}
```

这些显式结构化材料会 fan-in 到 analyst，作为第一次 latent KV prefill 的输入。

### Latent KV 区

从 `analyst_latent` 开始，Agent 间主要传递：

```json
{
  "latent_kv_handle_id": "handle-id-on-server"
}
```

handle 是控制面标识；真实 data plane 是模型服务内的 KV tensor。executor 和 summarizer 使用这个 handle 继续注入角色 token、运行 latent steps、decode 小段代码或最终答案。

## 3. 核心模块

| 文件 | 作用 |
|---|---|
| `src/graph.py` | 定义 D 模式 LangGraph 拓扑和 3 researcher fan-out |
| `src/agent/planner.py` | 生成 3 个互补 sub-query |
| `src/agent/shared.py` | 规范化 sub_queries，确保最多 3 个有效分支 |
| `src/agent/latent_kv_agents.py` | D 模式 explicit wrapper 和 latent Agent 实现 |
| `src/latent_kv_runtime.py` | LatentKVRuntime facade，封装 prefill、latent steps、inject、decode、delete |
| `src/latent_kv_model_server.py` | GPU 模型服务，保存真实 KV tensors |
| `exp/latent_kv_exp/run_7city_abd.py` | 7city A/B/D runner |

关键 graph 连接：

```python
builder.add_node("planner", planner_explicit_for_latent)
builder.add_node("researcher", researcher_explicit_for_latent)
builder.add_node("analyst", analyst_latent)
builder.add_node("executor", executor_latent)
builder.add_node("summarizer", summarizer_latent)

builder.add_edge(START, "planner")
builder.add_conditional_edges("planner", fan_out_latent_explicit_research, ["researcher"])
builder.add_edge("researcher", "analyst")
builder.add_edge("analyst", "executor")
builder.add_edge("executor", "summarizer")
builder.add_edge("summarizer", END)
```

## 4. Latent KV 运行流程

### 4.1 analyst_latent

`analyst_latent` 将 task、plan、3 个 researcher 的 context packets 合成为 analyst material：

```text
<|agent_analyst_input|>
# Task
...
# Explicit Planner Plan
...
# Explicit Sub Queries
- ...
- ...
- ...
# Explicit Research Context Packets
...
# Document References
...
# Analyst Contract
Do main reasoning in latent space.
</|agent_analyst_input|>
```

然后执行：

```text
runtime.prefill(analyst_material)
runtime.run_latent_steps(handle, ANALYST_LATENT_STEPS, "analyst")
```

### 4.2 executor_latent

executor 继承 analyst 的 KV handle：

```text
inject_role_transition("<|agent_executor|>")
run_latent_steps(EXECUTOR_LATENT_STEPS)
decode compact CodeAct snippet
execute sandboxed code
inject execution_result
run_latent_steps(POST_EXEC_LATENT_STEPS)
```

executor 不需要接收长篇 analysis 文本，而是在 analyst 的 KV 状态上继续推进任务。

### 4.3 summarizer_latent

summarizer 继承完整 KV chain：

```text
inject_role_transition("<|agent_summarizer|>")
run_latent_steps(SUMMARIZER_LATENT_STEPS)
generate_summary(...)
```

默认 latent step 配置：

```text
ANALYST_LATENT_STEPS=64
EXECUTOR_LATENT_STEPS=32
POST_EXEC_LATENT_STEPS=16
SUMMARIZER_LATENT_STEPS=8
```

也可以在实验中覆盖成更轻量的配置，例如：

```text
ANALYST_LATENT_STEPS=32
EXECUTOR_LATENT_STEPS=16
POST_EXEC_LATENT_STEPS=8
SUMMARIZER_LATENT_STEPS=0
```

## 5. 设计亮点

### 5.1 更自然的模型状态传递

传统文本 handoff 会把模型内部状态压缩成自然语言，再交给下一个 Agent 重新 tokenize 和 prefill。D 模式直接保留 KV continuation，让下游 Agent 在上游推理轨迹上继续工作，更接近模型原生的状态流。

### 5.2 减少长中间文本的反复处理

在多 Agent 链路中，analysis、execution rationale、summary draft 等中间文本很容易膨胀。D 模式把后半段中间推理保留在 latent KV 中，下游只拿 handle，避免把大量中间状态反复转成文本再读回模型。

### 5.3 保留显式可检查证据

D 模式不是完全黑盒化。planner 和 3 个 researcher 仍输出显式 plan、sub_queries、context_packets 和 evidence refs。系统既能保留可审计的证据链，又能在 analyst 之后享受 latent KV continuation 的高效状态传递。

### 5.4 适合多 Agent 长链路

Agent 越多、上游中间结果越长，文本 handoff 的重复 decode/prefill 越明显。D 模式把这种重复转换为 KV handle 继承，让 analyst、executor、summarizer 形成连续的推理链。

### 5.5 控制面轻、数据面强

LangGraph 只需要管理小 JSON 字段和 handle，模型服务管理真实 KV tensor。这个分层非常清晰：

```text
LangGraph: orchestration + structured state
Runtime: handle operation facade
Model server: GPU KV state + decode
```

这样的架构利于扩展、观测和工程维护。

## 6. 如何运行 D 模式

以下命令以 `SynapseX-wmw71` 容器、GPU1、端口 `8102` 为例。

### 6.1 启动 latent KV server

```bash
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz

docker exec -d SynapseX-wmw71 bash -lc '
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
export PYTHONPATH=$PWD/src:$PYTHONPATH
export CUDA_VISIBLE_DEVICES=1
export LATENT_KV_SERVER_GPU=0
export LATENT_KV_SERVER_PORT=8102
export VLLM_MODEL_PATH=/data/models/Qwen3-8B
python3 src/latent_kv_model_server.py > /tmp/latent_kv_server_gpu1.log 2>&1
'
```

健康检查：

```bash
docker exec SynapseX-wmw71 bash -lc '
for i in $(seq 1 60); do
  curl -s http://localhost:8102/health && exit 0
  sleep 5
done
tail -120 /tmp/latent_kv_server_gpu1.log
exit 1
'
```

### 6.2 单独运行 D 模式

```bash
docker exec SynapseX-wmw71 bash -lc '
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
export PYTHONPATH=$PWD/src:$PYTHONPATH
export CUDA_VISIBLE_DEVICES=1
export LATENT_KV_SERVER_PORT=8102
export LATENT_KV_SERVER_HOST=localhost
export LATENT_KV_BACKEND=real
python3 -u exp/latent_kv_exp/run_7city_abd.py --modes D --rounds 3
'
```

### 6.3 运行 A/B/D 对比

```bash
docker exec SynapseX-wmw71 bash -lc '
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
export PYTHONPATH=$PWD/src:$PYTHONPATH
export CUDA_VISIBLE_DEVICES=1
export LATENT_KV_SERVER_PORT=8102
export LATENT_KV_SERVER_HOST=localhost
export LATENT_KV_BACKEND=real
python3 -u exp/latent_kv_exp/run_7city_abd.py --modes A B D --rounds 3
'
```

### 6.4 使用轻量 latent step 配置

```bash
docker exec SynapseX-wmw71 bash -lc '
cd /data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz
export PYTHONPATH=$PWD/src:$PYTHONPATH
export CUDA_VISIBLE_DEVICES=1
export LATENT_KV_SERVER_PORT=8102
export LATENT_KV_SERVER_HOST=localhost
export LATENT_KV_BACKEND=real
python3 -u -c '"'"'
import sys
from exp.latent_kv_exp import run_7city_abd as r

_orig_set_unified_env = r._set_unified_env

def _patched_set_unified_env(comm_mode, extra=None):
    extra = dict(extra or {})
    if comm_mode == "latent_kv":
        extra.update({
            "ANALYST_LATENT_STEPS": "32",
            "EXECUTOR_LATENT_STEPS": "16",
            "POST_EXEC_LATENT_STEPS": "8",
            "SUMMARIZER_LATENT_STEPS": "0",
        })
    return _orig_set_unified_env(comm_mode, extra)

r._set_unified_env = _patched_set_unified_env
sys.argv = ["run_7city_abd.py", "--modes", "D", "--rounds", "3"]
r.main()
'"'"'
'
```

### 6.5 停止 server

```bash
docker exec SynapseX-wmw71 bash -lc '
pkill -f latent_kv_model_server.py || true
'
```

确认端口关闭：

```bash
docker exec SynapseX-wmw71 bash -lc '
curl -sS --max-time 2 http://localhost:8102/health || true
'
```

## 7. 推荐使用场景

D 模式特别适合这些多 Agent 工作流：

1. 中间分析长、最终答案短。
2. analyst 和 executor 之间存在大量推理状态继承。
3. 需要保留显式 evidence refs，同时希望减少后半段文本 handoff。
4. 多轮任务中希望把模型内部状态作为连续推理链使用。
5. 希望探索非文本状态传递、KV continuation 和 Agent orchestration 的结合。

D 模式的价值在于把“Agent 间传长文本”升级为“Agent 间传可定位的模型状态 handle”。它保留了结构化协作的可解释性，同时引入模型原生 KV 状态延续，是一条很有表现力的非文本状态传递路线。

# 面向多智能体协作的低开销通信、状态传递与共享记忆机制 —— 系统设计文档

> 版本：v1.0  
> 目标平台：openEuler 24.03-LTS-SP3  
> 开发语言：Python 3.11+

---

## 一、设计目标

当前多 Agent 系统普遍以自然语言或 JSON 作为通信媒介，存在三个核心问题：

1. **通信冗余**：Agent 间传递的上下文重复率高，token 消耗大。
2. **状态转换损耗**：中间结果在"内部状态 → 文本 → 内部状态"之间反复编解码，增加时延并引入语义损耗。
3. **知识无法沉淀**：任务执行过程中形成的经验和中间知识无法跨任务复用，相似任务每次都从零开始。

本系统围绕 **结构化通信协议**、**非文本状态传递**、**共享记忆复用** 三个方面，设计并实现一套可运行原型，并通过可复现实验验证其相较传统纯文本协作方式的改进效果。

---

## 二、系统架构总览

系统采用四层 + 横切层架构，每层职责单一、边界清晰：

```
┌──────────────────────────────────────────────────────────┐
│  第一层：Agent / Workflow                                 │
│  角色定义 · 编排引擎 · 双模切换 · 任务生命周期              │
├──────────────────────────────────────────────────────────┤
│  第二层：Protocol / State                                 │
│  结构化协议 · 握手与能力发现 · Embedding 状态交换           │
├──────────────────────────────────────────────────────────┤
│  第三层：Memory / Tool                                    │
│  共享记忆存储与检索 · 引用式上下文 · 工具注册 · CodeAct 沙箱 │
├──────────────────────────────────────────────────────────┤
│  第四层：Provider / Executor / Metrics                    │
│  LLM 适配 · 执行环境 · 原始指标采集                        │
├──────────────────────────────────────────────────────────┤
│  横切层：实验对比框架                                      │
│  A/B 对比引擎 · 指标聚合 · 报告生成                        │
└──────────────────────────────────────────────────────────┘
```

### 分层设计原则

- **第一层与第二层的分离**：编排逻辑（"谁干什么"）与通信机制（"怎么传消息"）解耦，编排器通过双模切换器选择当前使用结构化协议还是纯文本模式，Protocol 层按指令执行，两者互不侵入。
- **第二层与第三层的分离**：消息通信是每条消息都要走的"热路径"，共享记忆是任务粒度的"冷路径"，调用频率差异大，拆开后可独立优化性能。
- **横切层独立**：评测模块不属于任何一层，而是作为观察者通过装饰器/中间件挂载到各层的关键路径上采集数据，对业务逻辑零侵入。

---

## 三、第一层：Agent / Workflow

### 3.1 Agent 角色设计

系统设计 4 个 Agent，覆盖规划、检索、执行、总结四种角色：

| Agent | 角色 | 核心职责 | 调用 LLM 的目的 | 对赛题的贡献 |
|-------|------|---------|----------------|-------------|
| Planner | 规划者 | 理解任务意图，分解为带依赖关系的子任务列表，指定每个子任务由哪个 Agent 执行 | 任务分解与排序 | 产生 Agent 间通信流量，驱动结构化协议 |
| Retriever | 检索者 | 接收检索指令，先查共享记忆再补充外部检索，返回结构化结果 | 判断检索策略、整合多源结果 | 记忆复用的主要受益者，命中率的核心指标来源 |
| Executor | 执行者 | 在沙箱中运行工具或代码，生成结构化执行结果，传递 embedding 状态 | 生成可执行代码（CodeAct） | 非文本状态传递的主要产生者 |
| Summarizer | 总结者 | 整合多个 Agent 的输出，生成最终报告，将关键结论沉淀为共享记忆 | 证据整合与报告生成 | 记忆沉淀的执行者 |

#### 为什么是 4 个而不是更多或更少

- **最少 3 个**（赛题底线）：可以将 Summarizer 合并到 Planner 中，但会导致规划和总结的 prompt 混杂，降低输出质量。
- **恰好 4 个**（推荐方案）：每个 Agent 各自承担一个赛题评分维度的核心展示任务，职责清晰且不冗余。
- **5 个以上**（过度设计）：增加的 Agent（如 Validator、Monitor）不会带来额外评分收益，反而增加通信复杂度。

#### 各 Agent 为什么不能合并

- **Planner vs Retriever**：Planner 的 prompt 是"你是任务分解专家"，Retriever 的 prompt 是"你是信息检索专家"。不同的 system prompt 对应不同的能力定位，合并会降低 LLM 在单一任务上的表现质量。
- **Retriever vs Executor**：Retriever 只需数据查询权限，Executor 需要代码执行权限（沙箱环境）。权限隔离是安全性的基本要求。
- **Executor vs Summarizer**：Executor 的输出是结构化数据（依赖树、扫描结果），Summarizer 的输出是面向人类的自然语言报告。两者的输出形式和目标受众完全不同。

### 3.2 编排引擎

编排引擎负责接收用户任务、调用 Planner 分解、按依赖关系调度子任务到各 Agent。

```python
class Orchestrator:
    def __init__(self, agents: dict[str, BaseAgent], mode: str = "structured"):
        self.agents = agents
        self.mode = mode  # "structured" 或 "text"，由双模切换器控制

    async def run_task(self, task: Task, mode: str = None):
        current_mode = mode or self.mode

        # 1. Planner 分解任务
        plan = await self.agents["planner"].decompose(task)

        # 2. 按拓扑排序执行子任务
        for subtask in topological_sort(plan.subtasks):
            agent = self.agents[subtask.assigned_agent]
            result = await agent.execute(subtask, mode=current_mode)
            subtask.result = result

        # 3. Summarizer 整合结果
        report = await self.agents["summarizer"].synthesize(plan)

        return report
```

### 3.3 双模切换器

双模切换器位于编排引擎中，控制 Protocol 层的行为模式：

- `mode = "structured"`：Agent 间消息使用 `AgentMessage` 结构体 + MessagePack 序列化。
- `mode = "text"`：同样的信息内容被拼接为自然语言 prompt 字符串，使用 UTF-8 文本传递。

两种模式走完全相同的 Agent 角色和任务分解逻辑，只有"通信格式"不同——这保证了 A/B 对比实验的公平性。

---

## 四、第二层：Protocol / State —— 结构化通信

> 本层对应赛题评分：**通信效率（25 分）** + **状态传递创新（20 分）**

### 4.1 结构化通信协议设计

#### 4.1.1 消息结构体

定义一个紧凑的消息结构体，替代冗长的自然语言交互：

```python
@dataclass
class AgentMessage:
    msg_id: str                     # 消息唯一 ID（UUID 短格式）
    msg_type: MessageType           # 枚举：HANDSHAKE / CAPABILITY_QUERY / TASK_ASSIGN / RESULT / STATE_TRANSFER
    sender: str                     # 发送方 Agent 名称
    receiver: str                   # 接收方 Agent 名称
    action: str                     # 动作名称，如 "retrieve", "execute_code", "summarize"
    params: dict                    # 紧凑键值对参数（不包含描述性文字）
    result: Any                     # 结构化返回结果
    embedding_ref: Optional[str]    # 指向状态交换层的 embedding 引用 ID
    memory_refs: list[str]          # 引用的共享记忆 ID 列表
    timestamp: float                # 时间戳
```

#### 4.1.2 与纯文本的对比

同一个子任务指令在两种模式下的表现：

**结构化模式**（MessagePack 序列化，约 180 字节）：

```python
AgentMessage(
    msg_type=MessageType.TASK_ASSIGN,
    sender="planner",
    receiver="retriever",
    action="search_cve",
    params={"packages": ["requests==2.28.0", "flask==2.3.1"], "severity": "HIGH"},
    embedding_ref="emb_dep_scan_001",
    memory_refs=["mem_cve_cache_2024"]
)
```

**纯文本模式**（UTF-8 字符串，约 850 字节 / 约 320 token）：

```
你是一个安全漏洞检索专家。请根据以下依赖列表检索已知的 CVE 漏洞信息。
依赖列表如下：
1. requests，版本 2.28.0
2. flask，版本 2.3.1
请重点关注严重等级为 HIGH 及以上的漏洞。
以下是之前的依赖扫描结果供参考：[此处包含完整的扫描报告文本...]
此外，请参考之前的 CVE 缓存数据：[此处包含历史 CVE 查询结果文本...]
请以结构化格式返回漏洞列表，包含包名、版本、CVE 编号、严重等级和修复建议。
```

**预期节省效果**：结构化模式相比纯文本模式在通信体积上节省 60-80%，主要来自于三个方面：

1. 消除描述性语句（"你是一个..."、"请..."等指令词占纯文本的 30% 以上）。
2. 参数紧凑编码（`{"severity": "HIGH"}` vs "请重点关注严重等级为 HIGH 及以上的漏洞"）。
3. 引用替代内联（`embedding_ref` 和 `memory_refs` 用 ID 引用代替完整文本内联）。

#### 4.1.3 序列化方案

采用 MessagePack 作为序列化格式（而非 JSON），原因：

- MessagePack 的序列化体积比 JSON 小 30-50%。
- 二进制格式，解析速度比 JSON 快 2-3 倍。
- 支持 Python 原生类型映射，无需额外的编解码逻辑。

```python
import msgpack

def serialize(msg: AgentMessage) -> bytes:
    return msgpack.packb(msg.to_dict(), use_bin_type=True)

def deserialize(data: bytes) -> AgentMessage:
    return AgentMessage.from_dict(msgpack.unpackb(data, raw=False))
```

#### 4.1.4 握手与能力发现机制

每个 Agent 启动时向编排器注册一份能力清单（Capability Manifest）：

```python
@dataclass
class CapabilityManifest:
    agent_name: str
    supported_actions: list[ActionSchema]
    resource_limits: dict              # 如最大并发数、超时时间
    input_formats: list[str]           # 支持的输入格式
    output_formats: list[str]          # 支持的输出格式

@dataclass
class ActionSchema:
    action_name: str                   # 如 "search_cve"
    input_schema: dict                 # JSON Schema 定义输入参数
    output_schema: dict                # JSON Schema 定义输出格式
    estimated_latency_ms: int          # 预估耗时
```

握手流程：

1. Agent 启动 → 发送 `HANDSHAKE` 消息，携带 `CapabilityManifest`。
2. 编排器接收 → 更新全局能力路由表。
3. Planner 分解任务时 → 查询路由表匹配最合适的 Agent，而不是靠 LLM 猜测。
4. 如果目标 Agent 不支持请求的 action → 返回 `CAPABILITY_MISMATCH` 错误，Planner 重新规划。

### 4.2 非文本状态传递机制

> 本节对应赛题评分：**状态传递创新（20 分）**

#### 4.2.1 设计思路

传统方式中，Agent A 的输出要先序列化为文本，传给 Agent B 后再反序列化理解。当中间结果是结构化数据（如依赖树、扫描报告、检索结果集）时，"数据 → 文本描述 → 理解数据"的过程既浪费 token 又可能损失信息。

本系统引入 embedding 直传机制：Agent A 将中间结果编码为语义向量，通过共享内存直接传递给 Agent B。Agent B 可以：

- 直接用向量做语义检索（不需要还原成文字）。
- 用向量作为下游任务的语义锚点。
- 仅在必须生成自然语言时才解码。

#### 4.2.2 实现方案

**生成方式**：使用本地 embedding 模型（推荐 `bge-small-zh-v1.5`，384 维，支持中文）将中间结果编码为密集向量。

```python
from sentence_transformers import SentenceTransformer
import numpy as np

class EmbeddingEncoder:
    def __init__(self, model_name="BAAI/bge-small-zh-v1.5"):
        self.model = SentenceTransformer(model_name)

    def encode(self, text: str) -> np.ndarray:
        return self.model.encode(text, normalize_embeddings=True)

    def encode_batch(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(texts, normalize_embeddings=True)
```

**传递方式**：通过 `multiprocessing.shared_memory` 开辟共享内存段，避免进程间的序列化开销。

```python
from multiprocessing import shared_memory

class StateExchange:
    """Agent 间非文本状态交换模块"""

    def __init__(self, encoder: EmbeddingEncoder):
        self.encoder = encoder
        self.registry = {}  # ref_id -> SharedMemory 元信息

    def publish(self, agent_name: str, content: str, ref_id: str):
        """发布方：将内容编码为 embedding 并写入共享内存"""
        vector = self.encoder.encode(content)
        shm = shared_memory.SharedMemory(create=True, size=vector.nbytes)
        buffer = np.ndarray(vector.shape, dtype=vector.dtype, buffer=shm.buf)
        buffer[:] = vector[:]
        self.registry[ref_id] = {
            "shm_name": shm.name,
            "shape": vector.shape,
            "dtype": str(vector.dtype),
            "source_agent": agent_name,
            "content_hash": hash(content),  # 用于去重
        }
        return ref_id

    def consume(self, ref_id: str) -> np.ndarray:
        """接收方：从共享内存读取 embedding 向量"""
        meta = self.registry[ref_id]
        shm = shared_memory.SharedMemory(name=meta["shm_name"])
        vector = np.ndarray(
            meta["shape"],
            dtype=np.dtype(meta["dtype"]),
            buffer=shm.buf
        ).copy()  # 拷贝出来后可以安全释放 shm
        return vector
```

**接收与使用方式**：

```python
# Retriever 接收 Executor 传来的依赖扫描 embedding
dep_vector = state_exchange.consume("emb_dep_scan_001")

# 直接用向量在 CVE 数据库中做语义检索，不需要还原为文字
similar_cves = cve_vector_db.search(dep_vector, top_k=10)

# 仅在需要生成报告时才解码为文字
if need_text_output:
    text = retriever.decode_to_text(dep_vector, context=subtask)
```

#### 4.2.3 传递数据量对比

| 传递方式 | 数据量 | 说明 |
|---------|-------|------|
| 自然语言文本 | ~2,400 字节 (约 600 token) | 依赖扫描报告的完整文本描述 |
| JSON 结构化 | ~800 字节 | 依赖列表 + 版本号的 JSON |
| Embedding 向量 | ~1,536 字节 (384 维 float32) | 语义向量，可直接用于检索 |

embedding 方式的体积与 JSON 接近，但优势在于：接收方无需解析即可直接用于语义检索，省掉了"解析 JSON → 理解内容 → 构造检索 query"的 LLM 调用。

---

## 五、第三层：Memory / Tool —— 共享记忆复用

> 本层对应赛题评分：**记忆复用效果（20 分）**

### 5.1 记忆单元数据模型

```python
@dataclass
class MemoryUnit:
    memory_id: str              # 唯一标识（UUID 短格式）
    source_agent: str           # 创建者 Agent 名称
    created_at: datetime        # 创建时间
    task_id: str                # 所属任务 ID
    task_topic: str             # 任务主题（如"FastAPI 依赖安全分析"）
    summary: str                # 摘要描述（不超过 200 字）
    content: Any                # 完整结构化内容（证据链、策略、数据表等）
    embedding: np.ndarray       # 语义向量，用于相似度检索
    tags: list[str]             # 标签列表（如 ["security", "python", "cve"]）
    access_count: int           # 累计访问次数
    last_accessed: datetime     # 最近访问时间
    ttl: Optional[int]          # 过期时间（秒），None 表示永不过期
```

元数据字段覆盖赛题要求的全部五项（记忆 ID、来源 Agent、创建时间、任务主题、摘要描述），并额外增加了 tags、access_count 等用于检索和管理的字段。

### 5.2 存储架构

采用双存储引擎：

- **ChromaDB**：存储 embedding 向量，支持语义相似度检索。
- **SQLite**：存储元数据和完整内容，支持关键词和标签检索。

```python
class SharedMemoryStore:
    def __init__(self, db_path="memory.db"):
        self.chroma = chromadb.Client()
        self.collection = self.chroma.create_collection(
            name="shared_memory",
            metadata={"hnsw:space": "cosine"}
        )
        self.sqlite = sqlite3.connect(db_path)
        self._init_schema()

    def store(self, unit: MemoryUnit):
        """存储一条记忆"""
        # 向量存入 ChromaDB
        self.collection.add(
            ids=[unit.memory_id],
            embeddings=[unit.embedding.tolist()],
            documents=[unit.summary],
            metadatas=[{
                "source_agent": unit.source_agent,
                "task_id": unit.task_id,
                "task_topic": unit.task_topic,
                "tags": ",".join(unit.tags),
                "created_at": unit.created_at.isoformat(),
            }]
        )
        # 完整内容存入 SQLite
        self.sqlite.execute(
            "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (unit.memory_id, unit.source_agent, unit.created_at.isoformat(),
             unit.task_id, unit.task_topic, unit.summary,
             json.dumps(unit.content), ",".join(unit.tags), 0)
        )
        self.sqlite.commit()
```

### 5.3 三种检索方式

赛题要求支持关键词、标签、语义相似度三种检索方式：

```python
class SharedMemoryStore:
    # ... 接上文

    def search_by_keyword(self, keyword: str, limit: int = 10) -> list[MemoryUnit]:
        """关键词检索：在 summary 和 content 中全文搜索"""
        cursor = self.sqlite.execute(
            "SELECT * FROM memories WHERE summary LIKE ? OR content LIKE ? LIMIT ?",
            (f"%{keyword}%", f"%{keyword}%", limit)
        )
        return [self._row_to_unit(row) for row in cursor.fetchall()]

    def search_by_tags(self, tags: list[str], limit: int = 10) -> list[MemoryUnit]:
        """标签检索：匹配任意一个标签"""
        conditions = " OR ".join(["tags LIKE ?" for _ in tags])
        params = [f"%{tag}%" for tag in tags] + [limit]
        cursor = self.sqlite.execute(
            f"SELECT * FROM memories WHERE ({conditions}) LIMIT ?", params
        )
        return [self._row_to_unit(row) for row in cursor.fetchall()]

    def search_by_semantic(self, query_embedding: np.ndarray,
                           top_k: int = 5, threshold: float = 0.75) -> list[dict]:
        """语义相似度检索：用 embedding 向量在 ChromaDB 中检索"""
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )
        # 过滤低于阈值的结果
        filtered = []
        for i, score in enumerate(results["distances"][0]):
            similarity = 1 - score  # ChromaDB cosine distance → similarity
            if similarity >= threshold:
                filtered.append({
                    "memory_id": results["ids"][0][i],
                    "summary": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "similarity": similarity,
                })
        return filtered
```

### 5.4 记忆复用流程

Agent 在执行新任务前，自动检索共享记忆：

```
新任务到达
    │
    ▼
用任务描述生成 embedding
    │
    ▼
在共享记忆中做语义检索
    │
    ├── 命中（similarity ≥ 0.75）→ 直接复用历史结果，跳过检索/执行步骤
    │
    └── 未命中 → 正常执行，完成后将结果沉淀为新的记忆单元
```

### 5.5 引用式上下文传递

传统方式中，Agent B 需要 Agent A 的完整输出文本作为上下文。引用式传递改为只传 `ref_id`：

```python
# 传统方式：把完整内容放进 prompt（消耗大量 token）
prompt = f"以下是依赖扫描结果：\n{full_scan_report}\n请基于此分析漏洞..."

# 引用方式：只传 ID，需要时按需展开
message = AgentMessage(
    action="analyze_cve",
    params={"scope": "HIGH"},
    embedding_ref="emb_dep_scan_001",      # 向量引用，可直接检索
    memory_refs=["mem_scan_result_001"],    # 记忆引用，按需展开
)
```

接收方在需要完整内容时才通过 `memory_refs` 去 Memory 层查询，不需要完整内容时直接用 `embedding_ref` 做语义操作。

### 5.6 工具注册与 CodeAct 沙箱

Executor Agent 支持两种执行方式：

**注册式工具调用**：预定义的工具函数，通过统一接口调用。

```python
class ToolRegistry:
    def __init__(self):
        self.tools = {}

    def register(self, name: str, func: Callable, schema: dict):
        self.tools[name] = {"func": func, "schema": schema}

    async def execute(self, name: str, params: dict) -> Any:
        tool = self.tools[name]
        return await tool["func"](**params)
```

**CodeAct 模式**：LLM 生成 Python 代码，在轻量沙箱中执行。

```python
class CodeActSandbox:
    """轻量代码执行沙箱"""

    async def execute(self, code: str, timeout: int = 30) -> dict:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode(),
                "stderr": stderr.decode(),
            }
        except asyncio.TimeoutError:
            proc.kill()
            return {"success": False, "error": "execution timeout"}
```

---

## 六、第四层：Provider / Executor / Metrics

### 6.1 LLM Provider 适配层

统一封装不同 LLM 后端的调用接口：

```python
class LLMProvider:
    """兼容 OpenAI 接口的统一 LLM 调用层"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    async def chat(self, messages: list[dict], **kwargs) -> ChatCompletion:
        return await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs,
        )
```

支持的后端包括：Qwen（通义千问）、DeepSeek、本地 vLLM 部署，均兼容 OpenAI API 格式。

### 6.2 原始指标采集

通过装饰器模式在各层关键路径埋点，采集原始指标数据。详见第七章评测模块。

---

## 七、横切层：评测模块详细设计

### 7.1 指标体系

评测模块采集四类指标，覆盖赛题全部评分维度：

| 指标类别 | 采集层 | 具体指标 | 对应评分 |
|---------|--------|---------|---------|
| 通信效率 | Protocol 层 | 消息总数、总 token 数、总字节数、序列化方式、单消息往返时延 | 25 分 |
| 状态传递 | Protocol 层 | 向量传递次数、向量总数据量、等价文本 token 数、压缩比 | 20 分 |
| 记忆复用 | Memory 层 | 查询次数、命中次数、命中率、因复用节省的 token 数、平均相似度 | 20 分 |
| 整体性能 | Agent 层 + Provider 层 | 单任务总耗时、LLM 总 token 消耗（prompt + completion）、任务成功率 | 15 分 |

### 7.2 采集机制：四个探针

每个探针用装饰器模式实现，对业务代码零修改：

**TaskProbe**（Agent 层）：装饰编排器的 `run_task()`，记录任务启停时间、当前模式、成功/失败。

```python
class TaskProbe:
    def wrap(self, orchestrator):
        original_run = orchestrator.run_task

        async def instrumented(task, mode="structured"):
            run = TaskRun(task_id=task.id, mode=mode, start_time=time.time())
            ctx_token = current_run_ctx.set(run)
            try:
                result = await original_run(task, mode=mode)
                run.success = True
            finally:
                run.end_time = time.time()
                self.store.save(run)
                current_run_ctx.reset(ctx_token)
            return result

        orchestrator.run_task = instrumented
```

**ProtocolProbe**（Protocol 层）：拦截消息总线的 `send()`，统计每条消息的字节数、token 数、时延。

**MemoryProbe**（Memory 层）：拦截共享记忆的 `search()` 和 `store()`，统计命中率和节省的 token 量。

**ProviderProbe**（Provider 层）：拦截 LLM 调用，统计每次请求的 prompt/completion token 数和 API 耗时。

### 7.3 上下文关联

使用 Python 的 `contextvars.ContextVar` 将同一次任务执行中各层的指标关联到同一个 `TaskRun` 对象。asyncio 并发环境下不同任务的指标不会混淆。

```python
import contextvars

current_run_ctx: contextvars.ContextVar[TaskRun] = contextvars.ContextVar("current_run")
```

各探针在采集指标时通过 `current_run_ctx.get()` 获取当前任务的 `TaskRun` 对象，将指标追加到对应的列表中。

### 7.4 A/B 对比引擎

同一个任务跑两遍（structured + text），指标自动按模式分桶：

```python
class ExperimentRunner:
    async def run_comparison(self, task_group: str, tasks: list[Task], rounds: int = 10):
        for round_idx in range(rounds):
            for task in tasks:
                await self.orchestrator.run_task(task, mode="structured")
                await self.orchestrator.run_task(task, mode="text")

        return self.report_gen.generate(task_group)
```

### 7.5 持久化存储

所有原始指标存入 SQLite 数据库，表结构如下：

```sql
CREATE TABLE task_runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT,
    task_group TEXT,
    mode TEXT,            -- "structured" 或 "text"
    start_time REAL,
    end_time REAL,
    success BOOLEAN
);

CREATE TABLE message_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES task_runs(run_id),
    sender TEXT,
    receiver TEXT,
    raw_bytes INTEGER,
    token_count INTEGER,
    serialization TEXT,
    latency_ms REAL,
    has_embedding_ref BOOLEAN
);

CREATE TABLE embedding_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES task_runs(run_id),
    source_agent TEXT,
    target_agent TEXT,
    vector_dim INTEGER,
    bytes_size INTEGER,
    equivalent_text_tokens INTEGER
);

CREATE TABLE memory_accesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES task_runs(run_id),
    operation TEXT,       -- "query" 或 "store"
    hit BOOLEAN,
    similarity_score REAL,
    latency_ms REAL,
    tokens_saved INTEGER
);

CREATE TABLE llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES task_runs(run_id),
    agent_name TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    latency_ms REAL,
    model TEXT
);
```

---

## 八、任务设计

### 8.1 任务组 A：技术调研类（验证记忆复用）

| 任务 | 描述 | 涉及 Agent | 记忆复用点 |
|------|------|-----------|-----------|
| A1 | 调研 RISC-V 生态系统现状 | Planner → Retriever → Summarizer | 首次执行，产生记忆 |
| A2 | 对比 RISC-V 与 ARM 在边缘计算的优劣 | Planner → Retriever → Summarizer | 复用 A1 的 RISC-V 资料，只需新增 ARM 部分 |

**预期效果**：A2 的 Retriever 检索次数应显著少于 A1（因为 RISC-V 部分从记忆命中），总耗时缩短 30% 以上。

### 8.2 任务组 B：代码分析类（验证状态传递 + 记忆复用）

| 任务 | 描述 | 涉及 Agent | 记忆复用点 |
|------|------|-----------|-----------|
| B1 | 分析 Python 项目的依赖安全性 | Planner → Executor → Retriever → Summarizer | 首次执行，Executor 通过 embedding 传递扫描结果给 Retriever |
| B2 | 为 B1 中发现的漏洞依赖制定迁移方案 | Planner → Retriever → Executor → Summarizer | 直接复用 B1 的漏洞列表和 CVE 数据，Executor 只验证修复方案 |

**预期效果**：B2 跳过完整的依赖扫描和 CVE 检索，LLM token 消耗减少 50% 以上。

### 8.3 连续执行稳定性

以上两组任务按交替顺序执行 10 轮（共 40 次任务执行），每轮均在两种模式下各执行一次，验证系统在长时间运行中的指标稳定性（标准差应 < 10%）。

---

## 九、实验报告输出格式

### 9.1 报告结构

最终实验报告包含以下章节：

```
实验报告
├── 1. 实验概述
│     ├── 系统配置（硬件、OS、LLM 后端、embedding 模型）
│     ├── 任务描述（两组任务的详细说明）
│     └── 实验参数（轮次、阈值、模型参数）
│
├── 2. 通信效率对比（对应 25 分）
│     ├── 汇总表：structured vs text 的消息数、token 数、字节数
│     ├── 节省率计算
│     └── 逐 Agent 对通信开销分布图
│
├── 3. 非文本状态传递（对应 20 分）
│     ├── 向量传递统计：次数、总数据量、等价 token 数
│     ├── 压缩比分析
│     └── 具体传递实例说明（哪个 Agent 传给哪个 Agent、什么内容）
│
├── 4. 记忆复用效果（对应 20 分）
│     ├── 按任务组的命中率统计
│     ├── 因复用节省的 token 数和计算步骤
│     └── 关联任务间的指标对比（A1 vs A2、B1 vs B2）
│
├── 5. 整体性能对比（对应 15 分）
│     ├── 按任务的耗时对比表
│     ├── 加速比统计
│     └── 10 轮执行的稳定性分析（均值、标准差）
│
└── 6. 结论
      ├── 各维度的量化改进总结
      └── 系统局限性与改进方向
```

### 9.2 核心对比表模板

#### 表 1：通信效率对比

| 指标 | Structured 模式 | Text 模式 | 节省率 |
|------|----------------|----------|-------|
| Agent 间消息总数 | — | — | — |
| 通信总 token 数 | — | — | — |
| 通信总字节数 | — | — | — |
| 平均单消息字节数 | — | — | — |
| 序列化方式 | MessagePack | UTF-8 文本 | — |

#### 表 2：非文本状态传递统计

| 指标 | 数值 |
|------|------|
| Embedding 传递总次数 | — |
| 传递总数据量 | — |
| 等价文本 token 数 | — |
| 压缩比（等价 token / 向量字节） | — |
| 向量维度 | 384 (bge-small-zh) |

#### 表 3：记忆复用效果

| 指标 | 任务组 A | 任务组 B |
|------|---------|---------|
| 记忆查询次数 | — | — |
| 命中次数 | — | — |
| 命中率 | — | — |
| 因复用节省 token 数 | — | — |
| 平均 top-1 相似度得分 | — | — |

#### 表 4：任务耗时对比

| 任务 | Structured (s) | Text (s) | 加速比 |
|------|---------------|---------|-------|
| A1 | — | — | — |
| A2 | — | — | — |
| B1 | — | — | — |
| B2 | — | — | — |
| **平均** | — | — | — |

#### 表 5：10 轮稳定性验证

| 指标 | 均值 | 标准差 | 变异系数 |
|------|------|-------|---------|
| 单轮 token 节省率 | — | — | — |
| 单轮加速比 | — | — | — |
| 记忆命中率 | — | — | — |

### 9.3 报告自动生成

`ReportGenerator` 从 SQLite 数据库聚合原始指标，自动填充上述表格并导出为 Markdown 和 JSON 两种格式：

```python
class ReportGenerator:
    def generate(self, task_group: str) -> ExperimentReport:
        # 从数据库查询两种模式的所有 TaskRun
        structured_runs = self.store.get_runs(task_group, mode="structured")
        text_runs = self.store.get_runs(task_group, mode="text")

        # 聚合各维度指标
        report = ExperimentReport(task_group=task_group)
        report.communication = self._calc_communication(structured_runs, text_runs)
        report.state_transfer = self._calc_state_transfer(structured_runs)
        report.memory = self._calc_memory(structured_runs)
        report.performance = self._calc_performance(structured_runs, text_runs)
        report.stability = self._calc_stability(structured_runs, text_runs)

        return report

    def export_markdown(self, report: ExperimentReport, path: str):
        """导出为 Markdown 格式的实验报告"""
        # ... 按上述模板填充数据

    def export_json(self, report: ExperimentReport, path: str):
        """导出为 JSON 格式，供可视化工具读取"""
        # ... 结构化数据导出
```

---

## 十、技术栈总结

| 组件 | 技术选型 | 选型理由 |
|------|---------|---------|
| 开发语言 | Python 3.11+ | asyncio 原生支持、生态丰富 |
| 消息序列化 | MessagePack | 体积比 JSON 小 30-50%，有利于通信效率对比 |
| 进程间通信 | Unix Domain Socket + shared_memory | 低延迟、适合 embedding 向量传输 |
| Embedding 模型 | bge-small-zh-v1.5 (384 维) | 支持中文、体积小、可本地运行 |
| 向量存储 | ChromaDB | 轻量、Python 原生、支持 cosine 检索 |
| 元数据存储 | SQLite | 零配置、嵌入式、SQL 查询能力 |
| LLM 后端 | OpenAI 兼容接口 | 支持 Qwen、DeepSeek、本地 vLLM |
| 代码沙箱 | subprocess + 资源限制 | 简单可靠，可选 nsjail 增强隔离 |
| 目标平台 | openEuler 24.03-LTS-SP3 | 赛题硬性要求 |

---

## 十一、交付物清单

| 交付物 | 格式 | 说明 |
|--------|------|------|
| 完整源码 | Python 项目 | 含所有模块代码、配置文件、依赖声明 |
| 系统设计文档 | Markdown / PDF | 即本文档 |
| 部署文档 | Markdown | openEuler 一键部署脚本和环境配置说明 |
| 实验报告 | Markdown + JSON | 包含全部对比数据、图表和分析结论 |
| 演示视频 | MP4 | 完整运行流程录屏，展示两种模式对比效果 |

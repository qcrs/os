# 系统架构设计文档

## 1. 系统概述

本文档详细说明多智能体协作系统的整体架构设计，包括各个模块的职责、通信机制、状态交换方式和记忆管理策略。

## 2. 分层架构设计

### 2.1 应用层 (Application Layer)
- **职责**: 定义和执行具体业务任务
- **组成**: 各类任务的定义（RAG任务、代码分析任务等）
- **接口**: 任务配置、执行启动、结果获取

### 2.2 运行时与调度层 (Runtime & Scheduler Layer)
- **职责**: Agent生命周期管理、任务调度、执行编排
- **核心模块**:
  - AgentRuntime: Agent实例创建、销毁、状态维护
  - TaskScheduler: 任务队列管理、优先级调度
  - ExecutionEngine: 任务执行引擎，支持DAG和管道模式
- **功能**: 
  - 动态Agent注册与发现
  - 任务依赖关系解析
  - 并发执行控制
  - 异常处理与容错

### 2.3 Agent协作层 (Multi-Agent Layer)
- **职责**: 实现各类Agent，以及Agent间的交互逻辑
- **Agent类型**:
  1. **PlannerAgent** - 任务规划和分解
  2. **RetrieverAgent** - 信息检索和查询
  3. **ExecutorAgent** - 任务执行和工具调用
  4. **SummarizerAgent** - 结果总结和生成
- **交互方式**: 通过协议层进行通信

### 2.4 协议与状态交换层 (Protocol & State Exchange Layer)
包含三个通信模式：

#### 模式 A: 结构化协议模式 (Protocol Mode)
- 使用二进制格式的通信协议
- 消息包含：动作类型、参数、结果、能力
- 握手与能力发现机制

#### 模式 B: 非文本状态传递模式 (Embedding Mode)
- Embedding向量的直接传递
- 隐藏状态特征的共享
- 语义表示的交换

#### 模式 C: 纯文本模式 (Text-Only Mode, 用于对比)
- 传统的自然语言文本交互
- 用于基准测试和性能对比

### 2.5 共享记忆层 (Shared Memory Layer)
- **记忆存储** (Memory Store): 持久化记忆单元
- **语义索引** (Semantic Index): 向量索引，支持相似度搜索
- **检索引擎** (Retrieval Engine): 按关键词、标签、向量相似度检索

### 2.6 评测与分析层 (Evaluation & Profiling Layer)
- **性能指标收集**: 通信开销、时延、记忆命中率等
- **对比分析**: 三种模式的性能对比
- **可视化**: 数据展示与性能仪表盘

## 3. 通信协议设计

### 3.1 消息结构

```
┌─────────────┬──────────┬──────────┬────────────┬──────────┐
│   Header    │  Type    │ Payload  │ Extensions │ Checksum │
│  (16 bytes) │ (1 byte) │ (n bytes)│  (n bytes) │ (4 bytes)│
└─────────────┴──────────┴──────────┴────────────┴──────────┘
```

### 3.2 消息类型

| 类型 | 编码 | 说明 | 内容 |
|------|------|------|------|
| HANDSHAKE | 0x01 | 握手 | agent_id, version, caps |
| CAPABILITY | 0x02 | 能力描述 | capability_list |
| ACTION | 0x03 | 动作请求 | action, params, context |
| RESULT | 0x04 | 结果响应 | result, status, metadata |
| STATE | 0x05 | 状态传递 | embedding/vector |
| ERROR | 0x06 | 错误信息 | error_code, message |
| ACK | 0x07 | 确认 | msg_id, status |

### 3.3 握手与能力发现

```
Agent A                          Agent B
  │                                │
  ├─── HANDSHAKE ──────────────────>
  │    (version, capabilities)      │
  │                                │
  │<───── ACK + CAPABILITIES ───────┤
  │    (supported types)            │
  │                                │
  ├─── PROTOCOL_AGREED ────────────>
  │    (negotiated protocol)        │
  │                                │
  └──── Ready for Communication ────┘
```

## 4. 状态交换机制

### 4.1 Embedding层状态传递

```python
# 发送端：
state_vector = embedding_manager.encode(state_object)
message = create_state_message(state_vector, metadata)
send_message(target_agent, message)

# 接收端：
received_vector = extract_vector(message)
decoded_state = embedding_manager.decode(received_vector)
use_state(decoded_state)
```

### 4.2 隐藏状态特征传递

```
Agent A (执行)                Agent B (接收)
   │                              │
   ├─ extract_hidden_state()      │
   │  (从LLM中间层提取)             │
   │                              │
   ├─ quantize_features()         │
   │  (量化压缩)                    │
   │                              │
   ├─── STATE_VECTOR ────────────>│
   │    (压缩的特征向量)             │
   │                              │
   │                     ← map_to_context()
   │                     (映射到新Agent的context)
   │                              │
   │                     ← enrich_prompt()
   │                     (充实提示词)
```

### 4.3 状态转换流程

- **生成**: 从中间结果生成Embedding或特征向量
- **传递**: 通过协议或向量数据库传递
- **接收**: 解码或映射到接收Agent的内部表示
- **使用**: 集成到接收Agent的处理流程中

## 5. 共享记忆设计

### 5.1 记忆单元结构

```python
{
  "memory_id": "mem_20260615_001",
  "source_agent": "planner_agent",
  "created_at": "2026-06-15T10:30:00Z",
  "task_topic": "RAG_retrieval",
  "summary": "Retrieved 5 relevant documents about ML optimization",
  "content": {...},
  "embedding": [...],  # 向量表示
  "tags": ["retrieval", "ml", "optimization"],
  "confidence": 0.95,
  "metadata": {
    "task_id": "task_001",
    "context": "initial_retrieval",
    "parent_memory_id": null
  }
}
```

### 5.2 记忆存储架构

```
┌─────────────────────────────────────┐
│    共享记忆存储                      │
├─────────────────────────────────────┤
│ ┌─────────────────────────────────┐ │
│ │ 关系数据库 (SQLite/PostgreSQL)   │ │
│ │ 存储: ID、元数据、文本内容       │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ 向量数据库 (FAISS/Chroma)       │ │
│ │ 存储: Embedding向量             │ │
│ │ 支持: 相似度搜索                 │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ 缓存层 (Redis)                  │ │
│ │ 存储: 热点记忆                   │ │
│ │ 加速: 高频访问                   │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

### 5.3 检索机制

支持以下检索方式：

1. **精确检索** (Exact Retrieval)
   - 按 memory_id 直接查询
   - O(1) 时间复杂度

2. **关键词检索** (Keyword Search)
   - 按标签、任务主题模糊搜索
   - 返回匹配的记忆单元

3. **语义检索** (Semantic Search)
   - 计算查询语句的Embedding
   - 使用向量相似度(如余弦距离)排序
   - 返回Top-K相似记忆

4. **融合检索** (Hybrid Search)
   - 组合关键词和语义检索结果
   - 使用排序函数融合排名

## 6. 评测与度量

### 6.1 核心指标

| 指标 | 单位 | 说明 |
|------|------|------|
| message_count | 条 | Agent间消息总数 |
| text_tokens | tokens | 文本模式的token消耗 |
| text_chars | 字符 | 文本模式的字符消耗 |
| state_transfer_count | 次 | 非文本状态传递次数 |
| state_transfer_size | bytes | 非文本状态的数据量 |
| task_duration | 秒 | 单个任务总耗时 |
| memory_hit_rate | % | 记忆命中率 |
| speedup | 倍数 | 性能加速比 |

### 6.2 对比框架

```
┌─────────────────────────────────────────┐
│        性能对比矩阵                     │
├──────────────────┬──────────┬──────────┤
│      指标        │ 文本模式 │ 协议模式 │
├──────────────────┼──────────┼──────────┤
│ 通信消息数       │   N      │  N-30%   │
│ Token消耗        │   M      │  M-50%   │
│ 平均时延         │   T      │  T-40%   │
│ 记忆命中率       │   0%     │  45-65%  │
│ 整体加速比       │   1.0x   │  1.5-2x  │
└──────────────────┴──────────┴──────────┘
```

## 7. 系统组件详解

### 7.1 Agent基类

```python
class Agent:
    def __init__(self, agent_id, capabilities):
        self.agent_id = agent_id
        self.capabilities = capabilities
        self.protocol_handler = ProtocolHandler()
        self.memory_client = MemoryClient()
        
    async def handle_message(self, message):
        # 接收并处理消息
        
    async def send_message(self, target_agent, message):
        # 发送消息到目标Agent
        
    async def execute_action(self, action, params):
        # 执行具体动作
        
    async def save_memory(self, memory_unit):
        # 保存记忆单元到共享存储
        
    async def retrieve_memory(self, query):
        # 从记忆中检索相关内容
```

### 7.2 协议解析器

```python
class ProtocolHandler:
    def encode_message(self, message_obj) -> bytes:
        # 将Python对象编码为二进制协议
        
    def decode_message(self, data: bytes) -> dict:
        # 将二进制协议解码为Python对象
        
    def negotiate_protocol(self, remote_capabilities) -> str:
        # 协议协商
        
    def validate_message(self, data: bytes) -> bool:
        # 验证消息完整性
```

### 7.3 记忆管理器

```python
class MemoryManager:
    def store_memory(self, memory_unit: MemoryUnit):
        # 存储新记忆单元
        
    def retrieve_by_keyword(self, keywords: List[str], top_k: int):
        # 关键词检索
        
    def retrieve_by_similarity(self, query_embedding, top_k: int):
        # 语义相似度检索
        
    def update_hit_stats(self, memory_id):
        # 更新命中统计
```

## 8. 执行流程

### 8.1 单任务执行流程

```
任务开始
   ↓
[1] PlannerAgent: 制定计划, 分解子任务
   ↓
[2] 保存规划记忆
   ↓
[3] RetrieverAgent: 执行检索, 获取必要信息
   ↓
[4] 保存检索结果到共享记忆
   ↓
[5] ExecutorAgent: 基于计划和检索结果执行任务
   ↓
[6] 保存执行结果和中间状态
   ↓
[7] SummarizerAgent: 总结最终结果
   ↓
[8] 保存总结记忆
   ↓
任务完成, 收集性能指标
```

### 8.2 跨任务记忆复用

```
任务1执行 → 积累记忆 (M1, M2, M3, ...)
   ↓
记忆索引建立 (关键词索引, 向量索引)
   ↓
任务2开始
   ↓
[检索阶段] 查询相关历史记忆
   ↓
[命中] 如果找到可复用的记忆
   ├→ 直接使用或融合历史结果
   └→ 减少重复计算, 加速任务
   ↓
任务2完成, 新增更多记忆
```

## 9. 系统部署与扩展

### 9.1 单机部署
- 所有组件运行在同一进程或容器中
- 使用本地消息队列和文件系统存储

### 9.2 分布式部署
- 各Agent运行在不同进程/容器中
- 使用Socket/gRPC进行IPC通信
- Redis作为分布式缓存和消息中间件
- 分布式向量数据库存储记忆Embedding

### 9.3 性能优化建议

1. **通信优化**
   - 使用Protocol Buffers替代JSON
   - 消息压缩和批量发送
   - 连接复用

2. **记忆优化**
   - 多层缓存策略
   - 异步索引更新
   - 定期归档旧记忆

3. **并发优化**
   - 异步I/O
   - 线程池/进程池
   - 非阻塞消息处理

## 10. 参考架构实现框架

这个架构设计支持灵活的实现方式：

- **消息传输**: Socket、gRPC、Redis Pub/Sub
- **序列化**: Protocol Buffers、MessagePack、自定义二进制
- **向量存储**: FAISS、Chroma、Pinecone
- **数据库**: SQLite、PostgreSQL、MongoDB
- **LLM集成**: OpenAI API、LocalLLM (Ollama)

---

**版本**: 1.0  
**最后更新**: 2026-06-15

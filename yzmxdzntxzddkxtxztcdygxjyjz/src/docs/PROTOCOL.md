# 多Agent协议规范 (Protocol Specification)

## 1. 概述

本文档定义了多智能体系统中Agent间通信的结构化协议。该协议旨在替代冗长的自然语言交互，通过高密度的语义单元实现高效通信。

## 2. 协议栈

```
┌──────────────────────────┐
│   应用层 (Application)   │
│  Agent Business Logic    │
├──────────────────────────┤
│   协议层 (Protocol)      │
│  Message Format & Types  │
├──────────────────────────┤
│   序列化层 (Serialization)│
│  Binary/MessagePack/etc  │
├──────────────────────────┤
│   传输层 (Transport)     │
│  Socket/gRPC/Redis/IPC   │
├──────────────────────────┤
│   网络层 (Network)       │
│  TCP/UDP/Shared Memory   │
└──────────────────────────┘
```

## 3. 消息帧结构

### 3.1 二进制帧格式

```
Byte Layout:
+-------+-------+-------+-------+-------+-------+-------+
| Magic | Ver.  | Type  | Flags |   Payload Length    |
| (2B)  | (1B)  | (1B)  | (1B)  |       (2B)          |
+-------+-------+-------+-------+-------+-------+-------+
|          Sequence ID (4B)       |  Reserved (4B)    |
+-------+-------+-------+-------+-------+-------+-------+
|                    Payload (Variable)                 |
+-------+-------+-------+-------+-------+-------+-------+
|              Checksum (CRC32, 4B)                    |
+-------+-------+-------+-------+-------+-------+-------+

Total Header: 16 bytes + Variable Payload + 4 bytes Checksum
```

### 3.2 字段说明

| 字段 | 大小 | 说明 |
|------|------|------|
| Magic | 2B | 固定值 0xAB 0xCD，用于识别协议 |
| Version | 1B | 协议版本，当前为 0x01 |
| Type | 1B | 消息类型，见 3.3 节 |
| Flags | 1B | 标志位，bit0:是否需要ACK, bit1:是否压缩 |
| Payload Length | 2B | 负载长度（网络字节序） |
| Sequence ID | 4B | 消息序列号，用于重传和排序 |
| Reserved | 4B | 预留字段 |
| Payload | 可变 | 具体消息内容 |
| Checksum | 4B | CRC32校验和 |

## 4. 消息类型

### 4.1 消息类型列表

```python
MessageType = {
    0x00: "RESERVED",
    0x01: "HANDSHAKE",
    0x02: "CAPABILITY_QUERY",
    0x03: "CAPABILITY_RESPONSE",
    0x04: "ACTION_REQUEST",
    0x05: "ACTION_RESULT",
    0x06: "STATE_TRANSFER",
    0x07: "STATE_REQUEST",
    0x08: "MEMORY_SAVE",
    0x09: "MEMORY_QUERY",
    0x0A: "MEMORY_RESPONSE",
    0x0B: "ERROR",
    0x0C: "ACK",
    0x0D: "HEARTBEAT",
    0xFF: "RESERVED"
}
```

## 5. 消息定义详解

### 5.1 HANDSHAKE (0x01) - 握手消息

**目的**: Agent初始化时的相互识别和协议协商

**Payload 结构** (JSON/MessagePack):
```json
{
  "sender_id": "agent_planner_001",
  "receiver_id": "agent_retriever_001",
  "protocol_version": 1,
  "supported_message_types": [1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13],
  "capabilities": [
    {
      "name": "plan_task",
      "input_schema": {...},
      "output_schema": {...}
    }
  ],
  "timestamp": 1623456789,
  "nonce": "abc123def456"  // 用于防重放攻击
}
```

**响应**: ACK (0x0C) 或 ERROR (0x0B)

---

### 5.2 CAPABILITY_QUERY (0x02) & CAPABILITY_RESPONSE (0x03) 

**查询消息 Payload**:
```json
{
  "query_type": "all",  // "all" | "by_name" | "by_category"
  "filter": null        // 可选的过滤条件
}
```

**响应消息 Payload**:
```json
{
  "capabilities": [
    {
      "id": "cap_001",
      "name": "retrieve_documents",
      "category": "information_retrieval",
      "description": "Retrieve relevant documents from knowledge base",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "Search query"},
          "top_k": {"type": "integer", "default": 5}
        },
        "required": ["query"]
      },
      "output_schema": {
        "type": "object",
        "properties": {
          "documents": {
            "type": "array",
            "items": {"type": "object"}
          },
          "total_count": {"type": "integer"}
        }
      },
      "performance_profile": {
        "avg_latency_ms": 150,
        "throughput": 100
      }
    }
  ]
}
```

---

### 5.3 ACTION_REQUEST (0x04) & ACTION_RESULT (0x05)

**请求消息 Payload**:
```json
{
  "request_id": "req_20260615_001",
  "action": "retrieve_documents",
  "agent_id": "executor_agent_001",
  "target_capability": "cap_001",
  "parameters": {
    "query": "machine learning optimization techniques",
    "top_k": 5,
    "include_scores": true
  },
  "context": {
    "task_id": "task_001",
    "session_id": "sess_001",
    "parent_action_id": null
  },
  "timeout_ms": 5000,
  "require_state_transfer": true,  // 是否需要Embedding
  "metadata": {
    "priority": 1,
    "retry_count": 0
  }
}
```

**结果消息 Payload**:
```json
{
  "request_id": "req_20260615_001",
  "status": "success",  // "success" | "partial" | "failed" | "timeout"
  "execution_time_ms": 234,
  "result": {
    "documents": [
      {
        "id": "doc_001",
        "title": "...",
        "content": "...",
        "score": 0.95,
        "embedding": [0.1, 0.2, ..., 0.9]  // 可选的Embedding
      }
    ],
    "total_count": 1000,
    "query_cost": 10  // token数量
  },
  "state_transferred": {
    "type": "embedding",
    "format": "float32_array",
    "size_bytes": 4096,
    "encoding": "base64"  // 如果需要在JSON中传输
  },
  "error": null,
  "metadata": {
    "agent_version": "1.0.0"
  }
}
```

---

### 5.4 STATE_TRANSFER (0x06) & STATE_REQUEST (0x07)

**非文本状态传递消息 Payload**:
```json
{
  "state_id": "state_20260615_001",
  "source_agent": "retriever_agent_001",
  "state_type": "embedding",  // "embedding" | "hidden_state" | "vector" | "representation"
  "format": "float32_array",
  "dimension": 768,
  "data_size_bytes": 3072,
  "data": "base64_encoded_binary_data_here",
  "metadata": {
    "model": "sentence-transformers/all-MiniLM-L6-v2",
    "semantic_type": "document_relevance",
    "context": {
      "task_id": "task_001",
      "source_action": "retrieve"
    }
  },
  "timestamp": 1623456789,
  "ttl_seconds": 3600  // 状态在内存中的生存时间
}
```

**状态请求消息 Payload**:
```json
{
  "state_id": "state_20260615_001",
  "source_agent": "retriever_agent_001",
  "conversion_hint": "convert_to_context_vector"  // 可选的转换提示
}
```

---

### 5.5 MEMORY_SAVE (0x08) - 保存记忆

**Payload**:
```json
{
  "memory_unit": {
    "memory_id": "mem_20260615_001",
    "source_agent": "executor_agent_001",
    "created_at": "2026-06-15T10:30:00Z",
    "task_id": "task_001",
    "task_topic": "rag_retrieval",
    "summary": "Retrieved 5 relevant ML papers, total tokens: 2500",
    "content": {
      "type": "document_batch",
      "documents": [...],
      "metadata": {...}
    },
    "embedding": [0.1, 0.2, ..., 0.9],
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "tags": ["ml", "optimization", "retrieval"],
    "confidence": 0.92,
    "parent_memories": ["mem_20260615_000"],
    "expiry_at": "2026-07-15T10:30:00Z"
  }
}
```

**响应**: 
```json
{
  "status": "saved",
  "memory_id": "mem_20260615_001",
  "indexed": true,
  "retrieval_ready": true
}
```

---

### 5.6 MEMORY_QUERY (0x09) & MEMORY_RESPONSE (0x0A)

**查询消息 Payload**:
```json
{
  "query_type": "hybrid",  // "keyword" | "semantic" | "hybrid" | "tag"
  "keyword_query": "machine learning optimization",
  "semantic_query": {
    "text": "How to optimize ML models",
    "embedding": [0.15, 0.25, ..., 0.85],  // 可选，避免重复计算
    "model": "sentence-transformers/all-MiniLM-L6-v2"
  },
  "tag_filters": ["ml", "optimization"],
  "task_filter": "task_001",
  "time_range": {
    "start": "2026-06-01T00:00:00Z",
    "end": "2026-06-15T23:59:59Z"
  },
  "top_k": 5,
  "min_confidence": 0.7,
  "include_content": true
}
```

**响应消息 Payload**:
```json
{
  "query_id": "query_20260615_001",
  "status": "success",
  "total_matches": 3,
  "returned_count": 3,
  "memories": [
    {
      "memory_id": "mem_20260615_001",
      "source_agent": "executor_agent_001",
      "created_at": "2026-06-15T10:30:00Z",
      "task_topic": "rag_retrieval",
      "summary": "...",
      "confidence": 0.92,
      "relevance_score": 0.88,  // 查询相关度
      "content": {...}
    }
  ],
  "search_cost": {
    "tokens": 50,
    "time_ms": 45
  }
}
```

---

### 5.7 ERROR (0x0B) - 错误消息

**Payload**:
```json
{
  "error_code": "CAPABILITY_NOT_FOUND",
  "error_message": "Requested capability 'cap_002' not found in agent 'retriever_001'",
  "error_level": "WARNING",  // "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL"
  "related_request_id": "req_20260615_001",
  "recovery_suggestion": "Try querying available capabilities first using CAPABILITY_QUERY",
  "timestamp": 1623456789,
  "context": {}
}
```

---

### 5.8 ACK (0x0C) - 确认消息

**Payload**:
```json
{
  "ack_for_message_id": "req_20260615_001",
  "ack_type": "received",  // "received" | "processed" | "delivered"
  "status": "ok",
  "timestamp": 1623456790
}
```

---

### 5.9 HEARTBEAT (0x0D) - 心跳

**Payload**:
```json
{
  "agent_id": "executor_agent_001",
  "timestamp": 1623456789,
  "status": "healthy",
  "uptime_seconds": 3600,
  "message_count": 50,
  "queue_size": 3
}
```

## 6. 序列化格式

### 6.1 支持的序列化格式

- **MessagePack** (默认): 二进制紧凑格式
- **Protocol Buffers** (可选): Google的高效序列化
- **JSON** (调试模式): 便于开发和观察
- **自定义二进制** (性能优先): 对特定消息类型的优化

### 6.2 序列化选择

```python
# MessagePack 示例 (二进制高效)
payload = {
    "request_id": "req_001",
    "action": "retrieve",
    "parameters": {"query": "ML", "top_k": 5}
}
binary_payload = msgpack.packb(payload)  # ~50-100 bytes

# JSON 示例 (文本，便于调试)
json_payload = json.dumps(payload)  # ~150-200 bytes

# 压缩 (Flags 中指示)
compressed_payload = zlib.compress(binary_payload)
```

## 7. 通信流程示例

### 7.1 完整的Agent交互流程

```
Agent A                              Agent B
  │                                    │
  ├─ 1. HANDSHAKE ──────────────────> │
  │   (握手, 交换协议版本和能力)       │
  │                                    │
  │ <─ 2. ACK ───────────────────────  │
  │   (确认握手成功)                   │
  │                                    │
  ├─ 3. CAPABILITY_QUERY ────────────> │
  │   (查询对方支持的能力)             │
  │                                    │
  │ <─ 4. CAPABILITY_RESPONSE ───────  │
  │   (返回能力列表)                   │
  │                                    │
  ├─ 5. ACTION_REQUEST ──────────────> │
  │   (请求执行具体动作)               │
  │   - action: "retrieve_documents"  │
  │   - parameters: {...}             │
  │                                    │
  │ <─ 6. ACTION_RESULT ──────────── │
  │   (返回动作执行结果)               │
  │   - result: {...}                 │
  │   - state_transferred: {...}      │
  │                                    │
  ├─ 7. STATE_TRANSFER ──────────────> │
  │   (传递非文本状态)                 │
  │   - embedding: [0.1, 0.2, ...]   │
  │   - metadata: {...}               │
  │                                    │
  │ <─ 8. ACK ───────────────────────  │
  │   (确认收到状态)                   │
  │                                    │
  └─ 9. MEMORY_SAVE ────────────────> │
      (保存交互过程中的记忆)           │
```

## 8. 性能特征

### 8.1 消息大小对比

| 消息类型 | 纯文本 (JSON) | 协议 (MessagePack) | 节省比例 |
|---------|-------------|-----------------|---------|
| 简单查询 | ~200 bytes | ~80 bytes | 60% |
| 复杂结果 | ~5KB | ~2KB | 60% |
| 状态转移 | ~10KB (text) | ~4KB (binary) | 60% |
| 记忆保存 | ~3KB | ~1.2KB | 60% |

### 8.2 吞吐量

- **消息吞吐**: >10,000 msg/s (单连接)
- **带宽**: 根据消息大小和频率
- **延迟**: 平均 1-5ms (本地Socket)

## 9. 错误处理与重试

### 9.1 错误类型

| 错误码 | 含义 | 恢复策略 |
|-------|------|--------|
| AGENT_UNREACHABLE | Agent不可达 | 重试 + 超时 |
| CAPABILITY_NOT_FOUND | 能力不存在 | 重新查询能力列表 |
| INVALID_PARAMETERS | 参数错误 | 返回错误信息，由调用者修正 |
| TIMEOUT | 超时 | 重试或降级 |
| VERSION_MISMATCH | 版本不匹配 | 版本协商 |

### 9.2 重试策略

- **指数退避**: 1s, 2s, 4s, 8s, ...
- **最大重试次数**: 3次
- **断路器**: 快速失败，避免级联故障

## 10. 安全机制

### 10.1 消息验证

- **校验和**: CRC32 验证消息完整性
- **序列号**: 检测消息丢失或重复
- **时间戳**: 防重放攻击
- **nonce**: 握手阶段的随机值

### 10.2 访问控制

- Agent认证 (基于 agent_id)
- 能力级别的权限检查
- 审计日志记录

## 11. 实现指南

### 11.1 编码消息

```python
from protocol import MessageEncoder, MessageType

encoder = MessageEncoder()

# 创建ACTION_REQUEST
message = {
    "request_id": "req_001",
    "action": "retrieve_documents",
    "parameters": {"query": "ML", "top_k": 5}
}

# 编码
binary_data = encoder.encode(
    msg_type=MessageType.ACTION_REQUEST,
    payload=message,
    sequence_id=1
)

# 发送
send_over_socket(socket, binary_data)
```

### 11.2 解码消息

```python
from protocol import MessageDecoder

decoder = MessageDecoder()

# 接收二进制数据
binary_data = receive_from_socket(socket)

# 解码
msg_type, sequence_id, payload = decoder.decode(binary_data)

# 处理
if msg_type == MessageType.ACTION_REQUEST:
    handle_action_request(payload)
```

---

**版本**: 1.0  
**最后更新**: 2026-06-15  
**维护者**: 项目开发团队

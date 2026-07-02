# 部署与配置文档

## 1. 系统要求

### 1.1 硬件要求

- **CPU**: 多核处理器 (建议 ≥4核)
- **内存**: ≥8GB (向量数据库需求较大)
- **存储**: ≥20GB (用于记忆数据库和日志)
- **网络**: 100Mbps+ (如果分布式部署)

### 1.2 软件要求

- **操作系统**: Ubuntu 20.04+, CentOS 8+, 或其他Linux发行版
- **Python**: 3.8+
- **Docker** (可选): 用于容器化部署
- **数据库**: SQLite (默认) 或 PostgreSQL (生产环境)
- **向量数据库**: Chroma (推荐) 或 FAISS

## 2. 快速启动 (单机模式)

### 2.1 环境准备

```bash
# 克隆项目
git clone <repository-url>
cd multi-agent-collab

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 下载预训练模型 (可选，但推荐)
python -c "from sentence_transformers import SentenceTransformer; \
           model = SentenceTransformer('all-MiniLM-L6-v2'); \
           print('Model downloaded successfully')"
```

### 2.2 配置文件

创建 `config/default.yaml`:

```yaml
# 系统配置
system:
  environment: "development"  # development | staging | production
  debug: true
  log_level: "INFO"

# Agent配置
agents:
  max_agents: 10
  agent_timeout: 30  # 秒
  default_encoding: "utf-8"

# 通信配置
communication:
  protocol: "structured"  # structured | text_only | hybrid
  transport: "socket"  # socket | grpc | redis
  compression: true
  message_batch_size: 10

# 向量/Embedding配置
embedding:
  model: "all-MiniLM-L6-v2"
  dimension: 384
  batch_size: 32
  cache_enabled: true

# 记忆存储配置
memory:
  backend: "chroma"  # chroma | faiss | milvus
  db_path: "./data/memories"
  max_memory_size: 1000000  # 最大记忆条数
  cache_size: 100  # Redis缓存大小
  retention_days: 90  # 记忆保留天数

# 性能监控
monitoring:
  enabled: true
  metrics_port: 8888
  profiling: false
  sample_rate: 0.1

# LLM API配置 (如果使用OpenAI)
llm:
  provider: "openai"  # openai | local | mock
  api_key: "${OPENAI_API_KEY}"
  model: "gpt-3.5-turbo"
  temperature: 0.7
  max_tokens: 2000

# 实验配置
experiments:
  num_tasks: 10
  task_seeds: [42, 43, 44, 45, 46, 47, 48, 49, 50, 51]
  modes: ["text_only", "structured", "with_memory"]
  repeat_count: 1
```

### 2.3 初始化系统

```bash
# 创建必要的目录
mkdir -p data/memories
mkdir -p logs
mkdir -p models

# 初始化数据库
python scripts/init_db.py

# 验证安装
python -c "from src.core.agent import Agent; print('Installation successful!')"
```

### 2.4 运行示例

```bash
# 运行第一个示例任务
python examples/example_task1.py

# 运行性能对比测试
python examples/benchmark.py

# 查看结果
python examples/comparator.py
```

## 3. Docker 部署

### 3.1 构建Docker镜像

创建 `Dockerfile`:

```dockerfile
FROM python:3.9-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY . /app/

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 下载预训练模型
RUN python -c "from sentence_transformers import SentenceTransformer; \
               model = SentenceTransformer('all-MiniLM-L6-v2')"

# 暴露端口
EXPOSE 8888

# 启动应用
CMD ["python", "examples/benchmark.py"]
```

### 3.2 构建和运行

```bash
# 构建镜像
docker build -t multi-agent-collab:latest .

# 运行容器 (单机)
docker run -v $(pwd)/data:/app/data \
           -v $(pwd)/logs:/app/logs \
           -p 8888:8888 \
           multi-agent-collab:latest

# 运行容器 (后台)
docker run -d --name multi-agent \
           -v $(pwd)/data:/app/data \
           -v $(pwd)/logs:/app/logs \
           -p 8888:8888 \
           multi-agent-collab:latest

# 查看日志
docker logs -f multi-agent

# 停止容器
docker stop multi-agent
```

### 3.3 Docker Compose (分布式)

创建 `docker-compose.yml`:

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  postgres:
    image: postgres:14-alpine
    environment:
      POSTGRES_DB: agent_memory
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: agent_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  agent_runtime:
    build: .
    environment:
      - REDIS_URL=redis://redis:6379
      - DATABASE_URL=postgresql://agent:agent_password@postgres:5432/agent_memory
      - ENVIRONMENT=production
    ports:
      - "8888:8888"
    depends_on:
      - redis
      - postgres
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs

  # 可选: Milvus向量数据库
  milvus:
    image: milvusdb/milvus:latest
    environment:
      COMMON_STORAGETYPE: local
    ports:
      - "19530:19530"
      - "9091:9091"
    volumes:
      - milvus_data:/var/lib/milvus

volumes:
  redis_data:
  postgres_data:
  milvus_data:
```

```bash
# 启动所有服务
docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f agent_runtime

# 停止所有服务
docker-compose down
```

## 4. 分布式部署

### 4.1 架构

```
┌─────────────────────────────────────────────┐
│          Load Balancer / API Gateway        │
└────────────────────┬────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     │               │               │
┌────▼────┐  ┌──────▼──────┐  ┌─────▼──────┐
│ Agent 1  │  │   Agent 2   │  │  Agent 3   │
│(Planner) │  │(Retriever)  │  │(Executor)  │
└────┬─────┘  └──────┬──────┘  └─────┬──────┘
     │               │               │
     └───────────────┼───────────────┘
                     │
    ┌────────────────┼────────────────┐
    │                │                │
┌───▼───┐   ┌────────▼────────┐  ┌───▼──────┐
│Redis  │   │  PostgreSQL DB  │  │ Milvus   │
│Cache  │   │  (Memory Store) │  │(Vector DB)│
└───────┘   └─────────────────┘  └──────────┘
```

### 4.2 部署步骤

#### 第1步: 部署基础设施

```bash
# 部署Redis
docker run -d --name redis \
           -p 6379:6379 \
           redis:7-alpine

# 部署PostgreSQL
docker run -d --name postgres \
           -e POSTGRES_DB=agent_memory \
           -e POSTGRES_USER=agent \
           -e POSTGRES_PASSWORD=secure_password \
           -p 5432:5432 \
           postgres:14-alpine

# 部署Milvus (向量数据库)
docker-compose -f milvus-compose.yml up -d
```

#### 第2步: 部署Agent实例

每个Agent运行在独立的容器中：

```bash
# Agent 1: Planner
docker run -d --name agent_planner \
           -e AGENT_TYPE=planner \
           -e REDIS_URL=redis://redis:6379 \
           -e DB_URL=postgresql://agent:password@postgres:5432/agent_memory \
           -p 8001:8000 \
           multi-agent-collab:latest

# Agent 2: Retriever
docker run -d --name agent_retriever \
           -e AGENT_TYPE=retriever \
           -e REDIS_URL=redis://redis:6379 \
           -e DB_URL=postgresql://agent:password@postgres:5432/agent_memory \
           -p 8002:8000 \
           multi-agent-collab:latest

# Agent 3: Executor
docker run -d --name agent_executor \
           -e AGENT_TYPE=executor \
           -e REDIS_URL=redis://redis:6379 \
           -e DB_URL=postgresql://agent:password@postgres:5432/agent_memory \
           -p 8003:8000 \
           multi-agent-collab:latest
```

#### 第3步: 配置通信

修改 `config/production.yaml` 以使用分布式设置：

```yaml
communication:
  transport: "grpc"  # 跨进程通信
  endpoints:
    planner: "grpc://agent_planner:5001"
    retriever: "grpc://agent_retriever:5002"
    executor: "grpc://agent_executor:5003"

memory:
  backend: "milvus"
  endpoints:
    - "milvus:19530"
```

### 4.3 服务发现 (可选)

```yaml
# 使用Consul或etcd进行服务注册和发现
service_discovery:
  enabled: true
  backend: "consul"  # consul | etcd
  server: "consul:8500"
  health_check_interval: 10
  deregister_on_exit: true
```

## 5. 性能调优

### 5.1 内存优化

```yaml
embedding:
  cache_enabled: true
  cache_size: 10000  # 缓存最常用的embedding
  
memory:
  batch_size: 100  # 批量操作以减少数据库往返
  index_refresh_interval: 3600  # 每小时刷新索引
  cache_ttl: 3600
```

### 5.2 并发优化

```yaml
agents:
  thread_pool_size: 16
  async_enabled: true
  max_concurrent_tasks: 100

communication:
  connection_pool_size: 50
  message_queue_size: 1000
```

### 5.3 网络优化

```yaml
communication:
  compression: true  # 启用消息压缩
  compression_level: 6  # 1-9, 默认6
  message_batch_size: 50  # 批量发送消息
  tcp_keepalive: true
  tcp_nodelay: true  # 禁用Nagle算法
```

## 6. 监控与日志

### 6.1 Prometheus 指标

暴露在 `http://localhost:8888/metrics`:

```python
# 关键指标
- multi_agent_message_count  # 消息总数
- multi_agent_message_latency  # 消息延迟 (直方图)
- multi_agent_text_tokens  # 文本token消耗
- multi_agent_memory_hit_rate  # 记忆命中率
- multi_agent_task_duration  # 任务耗时
```

### 6.2 日志配置

```yaml
logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  handlers:
    console:
      enabled: true
      level: INFO
    file:
      enabled: true
      path: "logs/agent.log"
      level: DEBUG
      max_size: 100MB
      backup_count: 10
    remote:
      enabled: false  # 可选: 集中日志收集
      endpoint: "http://logging-server:8081"
```

### 6.3 Grafana 仪表板

```bash
# 启动Grafana
docker run -d --name grafana \
           -p 3000:3000 \
           grafana/grafana:latest

# 访问 http://localhost:3000
# 添加Prometheus数据源: http://prometheus:9090
```

## 7. 故障排除

### 7.1 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|--------|
| Agent连接失败 | 网络问题或Agent未启动 | 检查日志，确保所有服务运行 |
| 记忆查询缓慢 | 向量数据库索引未优化 | 重建索引，调整cache_size |
| 高内存占用 | 缓存过大或向量存储未压缩 | 减少cache_size，启用压缩 |
| 消息超时 | 网络延迟或Agent处理缓慢 | 增加timeout时间，检查Agent日志 |
| Embedding模型加载失败 | 模型未下载或路径错误 | 重新下载模型，检查路径配置 |

### 7.2 调试模式

```bash
# 启用调试日志
export LOG_LEVEL=DEBUG
export DEBUG=true

# 运行with verbose output
python examples/benchmark.py --verbose --debug

# 启用性能分析
python examples/benchmark.py --profile
```

## 8. 升级与维护

### 8.1 版本升级

```bash
# 更新依赖
pip install -r requirements.txt --upgrade

# 迁移数据库
python scripts/migrate_db.py --version=2.0

# 重新启动服务
docker-compose restart
```

### 8.2 备份与恢复

```bash
# 备份记忆数据库
python scripts/backup_memories.py --output=backup_20260615.tar.gz

# 恢复
python scripts/restore_memories.py --input=backup_20260615.tar.gz
```

### 8.3 清理与维护

```bash
# 清理过期记忆 (超过90天)
python scripts/cleanup_old_memories.py --days=90

# 重建向量索引
python scripts/rebuild_vector_index.py

# 压缩数据库
python scripts/compact_database.py
```

---

**版本**: 1.0  
**最后更新**: 2026-06-15

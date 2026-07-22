"""Configuration constants for the multi-agent research demo."""

import os

# OpenAI-compatible chat model configuration.
# Defaults keep the original DeepSeek path, while local deployments can point
# the same four agents to a vLLM/SGLang endpoint by setting these variables.
CHAT_API_KEY = os.getenv("CHAT_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
CHAT_BASE_URL = os.getenv(
    "CHAT_BASE_URL", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
)
CHAT_MODEL = os.getenv("CHAT_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
CHAT_BACKEND = os.getenv("CHAT_BACKEND", "openai").lower()
CHAT_DISABLE_THINKING = os.getenv("CHAT_DISABLE_THINKING", "0").lower() in {"1", "true", "yes"}

# Local Transformers backend configuration.
LOCAL_MODEL_PATH = os.getenv("LOCAL_MODEL_PATH", "/data/models/Qwen3-8B")
LOCAL_MODEL_DEVICE = os.getenv("LOCAL_MODEL_DEVICE", "cuda:0")
LOCAL_MODEL_DTYPE = os.getenv("LOCAL_MODEL_DTYPE", "bfloat16")
LOCAL_TRANSFORMERS_MAX_NEW_TOKENS = int(os.getenv("LOCAL_TRANSFORMERS_MAX_NEW_TOKENS", "768"))

# vLLM cache-handoff backend configuration. vLLM does not expose a stable
# public raw-KV handle to application code; the cache mode therefore passes a
# prefix cache handle while vLLM manages the actual KV cache internally.
VLLM_MODEL_PATH = os.getenv("VLLM_MODEL_PATH", LOCAL_MODEL_PATH)
VLLM_MAX_MODEL_LEN = int(os.getenv("VLLM_MAX_MODEL_LEN", "8192"))
VLLM_MAX_NUM_SEQS = int(os.getenv("VLLM_MAX_NUM_SEQS", "16"))
VLLM_MAX_NUM_BATCHED_TOKENS = int(os.getenv("VLLM_MAX_NUM_BATCHED_TOKENS", "4096"))
VLLM_GPU_MEMORY_UTILIZATION = float(os.getenv("VLLM_GPU_MEMORY_UTILIZATION", "0.85"))
VLLM_TENSOR_PARALLEL_SIZE = int(os.getenv("VLLM_TENSOR_PARALLEL_SIZE", "1"))
VLLM_DTYPE = os.getenv("VLLM_DTYPE", LOCAL_MODEL_DTYPE)
VLLM_MAX_NEW_TOKENS = int(os.getenv("VLLM_MAX_NEW_TOKENS", "384"))
VLLM_TRUST_REMOTE_CODE = os.getenv("VLLM_TRUST_REMOTE_CODE", "1").lower() in {"1", "true", "yes"}
VLLM_ENABLE_PREFIX_CACHING = os.getenv("VLLM_ENABLE_PREFIX_CACHING", "1").lower() in {"1", "true", "yes"}
VLLM_ENFORCE_EAGER = os.getenv("VLLM_ENFORCE_EAGER", "0").lower() in {"1", "true", "yes"}

ENABLE_CONTEXT_PACKETS = os.getenv("ENABLE_CONTEXT_PACKETS", "1").lower() in {"1", "true", "yes"}
ENABLE_EMBEDDING_TRANSFER = os.getenv("ENABLE_EMBEDDING_TRANSFER", "1").lower() in {"1", "true", "yes"}
REDUCE_RESEARCH_ON_MEMORY_HIT = os.getenv("REDUCE_RESEARCH_ON_MEMORY_HIT", "1").lower() in {
    "1", "true", "yes", "on"
}
PLANNER_MEMORY_CONFIDENCE_THRESHOLD = float(
    os.getenv("PLANNER_MEMORY_CONFIDENCE_THRESHOLD", "0.5") or "0.5"
)

# Backward-compatible names used by older scripts/docs.
DEEPSEEK_API_KEY = CHAT_API_KEY
DEEPSEEK_BASE_URL = CHAT_BASE_URL
DEEPSEEK_MODEL = CHAT_MODEL

# DashScope text embedding configuration
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "auto").lower()
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_HTTP_API_URL = os.getenv(
    "DASHSCOPE_BASE_HTTP_API_URL", "https://dashscope.aliyuncs.com/api/v1"
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_DIMS = int(os.getenv("EMBEDDING_DIMS", "1024"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "10"))

# Persistent shared memory configuration.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSISTENT_MEMORY_ENABLED = os.getenv("PERSISTENT_MEMORY_ENABLED", "1").lower() in {
    "1", "true", "yes", "on"
}
PERSISTENT_MEMORY_PATH = os.getenv(
    "PERSISTENT_MEMORY_PATH",
    os.path.join(PROJECT_ROOT, ".memory", "shared_memory.jsonl"),
)

# Qdrant-backed reusable memory configuration. This is separate from the
# LangGraph runtime Store, which is still used for current-run state and docs.
LONG_TERM_MEMORY_ENABLED = os.getenv("LONG_TERM_MEMORY_ENABLED", "1").lower() in {
    "1", "true", "yes", "on"
}
LONG_TERM_MEMORY_QDRANT_PATH = os.getenv(
    "LONG_TERM_MEMORY_QDRANT_PATH",
    os.path.join(PROJECT_ROOT, ".memory", "memory_module", "data", "qdrant"),
)
LONG_TERM_MEMORY_COLLECTION = os.getenv(
    "LONG_TERM_MEMORY_COLLECTION",
    f"shared_memories_{EMBEDDING_DIMS}",
)
LONG_TERM_MEMORY_ADD_LOG_PATH = os.getenv(
    "LONG_TERM_MEMORY_ADD_LOG_PATH",
    os.path.join(PROJECT_ROOT, ".memory", "memory_module", "logs", "memory_add.jsonl"),
)
LONG_TERM_MEMORY_SEARCH_MODE = os.getenv("LONG_TERM_MEMORY_SEARCH_MODE", "hybrid")
LONG_TERM_MEMORY_TOP_K = int(os.getenv("LONG_TERM_MEMORY_TOP_K", "2"))
LONG_TERM_MEMORY_BM25_MODEL_PATH = os.getenv("LONG_TERM_MEMORY_BM25_MODEL_PATH", "")
LONG_TERM_MEMORY_DENSE_SCORE_THRESHOLD = float(
    os.getenv("LONG_TERM_MEMORY_DENSE_SCORE_THRESHOLD", "0") or "0"
)
LONG_TERM_MEMORY_FILTER_HYBRID_BY_DENSE = os.getenv(
    "LONG_TERM_MEMORY_FILTER_HYBRID_BY_DENSE", "0"
).lower() in {"1", "true", "yes", "on"}
LONG_TERM_TASK_STATE_ENABLED = os.getenv(
    "LONG_TERM_TASK_STATE_ENABLED", "1"
).lower() in {"1", "true", "yes", "on"}

# Store namespaces
NS_PLANS = ("plans",)
NS_DOCS = ("docs",)
NS_ANALYSIS = ("analysis",)
NS_EXECUTIONS = ("executions",)
NS_SUMMARIES = ("summaries",)

# Task group IDs
TASK_GROUP_A = "A_langgraph_analysis"
TASK_GROUP_B = "B_system_design"

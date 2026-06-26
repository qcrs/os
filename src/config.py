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
LOCAL_HIDDEN_POOLING = os.getenv("LOCAL_HIDDEN_POOLING", "last_token")
LOCAL_HIDDEN_ROUND_DECIMALS = int(os.getenv("LOCAL_HIDDEN_ROUND_DECIMALS", "6"))
ENABLE_CONTEXT_PACKETS = os.getenv("ENABLE_CONTEXT_PACKETS", "1").lower() in {"1", "true", "yes"}
ENABLE_EMBEDDING_TRANSFER = os.getenv("ENABLE_EMBEDDING_TRANSFER", "1").lower() in {"1", "true", "yes"}
ENABLE_HIDDEN_STATE_TRANSFER = os.getenv("ENABLE_HIDDEN_STATE_TRANSFER", "1").lower() in {"1", "true", "yes"}
HIDDEN_STATE_CONTEXT_TOP_K = int(os.getenv("HIDDEN_STATE_CONTEXT_TOP_K", "2"))
HIDDEN_STATE_EVIDENCE_PER_DOC = int(os.getenv("HIDDEN_STATE_EVIDENCE_PER_DOC", "1"))
HIDDEN_STATE_EVIDENCE_CHARS = int(os.getenv("HIDDEN_STATE_EVIDENCE_CHARS", "120"))

# Backward-compatible names used by older scripts/docs.
DEEPSEEK_API_KEY = CHAT_API_KEY
DEEPSEEK_BASE_URL = CHAT_BASE_URL
DEEPSEEK_MODEL = CHAT_MODEL

# DashScope text embedding configuration
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

# Store namespaces
NS_PLANS = ("plans",)
NS_DOCS = ("docs",)
NS_ANALYSIS = ("analysis",)
NS_EXECUTIONS = ("executions",)
NS_SUMMARIES = ("summaries",)

# Task group IDs
TASK_GROUP_A = "A_langgraph_analysis"
TASK_GROUP_B = "B_system_design"

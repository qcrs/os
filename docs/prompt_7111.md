 # StateBus 项目执行 Prompt

  ## 项目位置
  /home/qcrs/statebus/project

  ## 当前环境
  - 3张 A100 80GB PCIe
  - card0：Qwen3-32B vLLM 已在运行（PID 3182893，port
  53334，bfloat16，max_model_len=8192，num_gpu_blocks_override=573，enable_prefix_caching=True，enforce-eager）
  - card1：约 51GB 空闲
  - 本地模型：~/statebus/models/Qwen3-Embedding-0.6B（sentence-transformer，用于 local embedding）
  - Docker 容器：statebus-dev-qcrs（进入方式：docker exec -it statebus-dev-qcrs bash，然后 source
  deploy/activate_statebus_host.sh）
  - 当前分支：feat/local-vllm-kv-prep

  ## 工作约束（始终遵守）
  1. 不得重启 vLLM 进程（card0 上 PID 3182893）
  2. 不得杀 GPU 进程
  3. 不得 git add . 或 git commit（除非明确要求）
  4. 不得修改已有 artifact JSON 文件
  5. 不得触碰无关未跟踪文件（包括 `tatus --short --branch`）
  6. openEuler VM 本轮不做

  ## 审计文档参考
  完整审计结果在：
  docs/improvement/20_v2_comprehensive_truth_audit_20260706/31_comprehensive_gap_audit_20260711.md
  该文档 Section 9 包含 19 条修复项（F-01~F-12 + F-R1~F-R4），是本次执行的任务清单。

  独立审计参考：
  docs/improvement/20_v2_comprehensive_truth_audit_20260706/30_independent_audit_report_20260711.md
  实验合成参考：
  docs/improvement/20_v2_comprehensive_truth_audit_20260706/29_local_vllm_kv_experiment_log_synthesis_20260711.md

  ## 执行计划（按顺序）

  ### 阶段 0：清理脏树，新建工作分支

  ```bash
  cd /home/qcrs/statebus/project
  git status --short --branch

  # 清理误建文件（F-10）
  cat 'tatus --short --branch'   # 先确认内容
  rm 'tatus --short --branch'

  # 新建分支（从当前 feat/local-vllm-kv-prep）
  git checkout -b feat/statebus-gap-fix-and-logit-state

  git status --short --branch    # 确认干净
  
  ---
  以下详细设计参考：docs/improvement/20_v2_comprehensive_truth_audit_20260706/31_comprehensive_gap_audit_20260711.md
  该文档 Section 9 包含 19 条修复项（F-01~F-12 + F-R1~F-R4），是本次执行的任务清单。
  阶段 1：表述修正（纯文档/注释，不跑实验）

  以下修改只动代码注释和答辩文档，零风险，按顺序执行：

  F-04：在所有答辩材料中删除 r01_06 作为效率优势引用，改引 E6 数字：
  - E6 token delta：total -51282，prompt -45652，control bytes -31256，quality delta=0

  F-05：v2/retrieval/pipeline.py:644 附近，在 estimated_kv_tokens_saved 赋值上方加注释：
  # NOTE: estimated_kv_tokens_saved 是输入侧算术估算，不是 GPU KV cache 实测。
  # 计算方式：max(full_corpus_tokens - selected_evidence_tokens, 0)
  # 不得表述为"节省了 N 个 GPU KV cache token"

  F-08：v2/runtime/neural_state.py:384 附近加注释：
  # NOTE: neural_prefix_cache_hit_count_estimate 是控制面推断（estimated_prefix_tokens > 0）
  # 不是 vLLM 内部 raw hit counter。直接 GPU 指标见 vllm:gpu_prefix_cache_hit_rate

  F-R4：scripts/run_v2_local_vllm_container_check.sh 开头加端口提示：
  VLLM_BASE_URL="${STATEBUS_LOCAL_VLLM_BASE_URL:-http://127.0.0.1:53333/v1}"
  echo "[INFO] vLLM endpoint: ${VLLM_BASE_URL}"
  echo "[INFO] 如使用 Qwen3-32B (port 53334)，请先: export STATEBUS_LOCAL_VLLM_BASE_URL=http://127.0.0.1:53334/v1"

  ---
  阶段 2：实现路线 A — LogitStateRef（增量添加，不破坏已有路径）

  背景：当前非文本传递只有 embedding semantic state（SemanticStateRef，sentence-transformer 向量）。LogitStateRef
  增加第二种非文本状态：LLM 输出层的 logprob 概率向量（float32 binary），通过 memfd/shm 传递给下游 agent，用于 confidence
  gating。
  
  2-1：v2/contracts.py — 在 RefKind enum 追加：
  LOGIT_STATE = "logit_state"

  2-2：v2/refs/models.py — 在 SemanticStateRef 之后追加新 dataclass：

  class LogitStateRef:
      """Executor 输出层 logprob 向量的非文本状态 ref。
      传递 top-k token 的 log 概率 float32 向量（binary），
      是 LLM 输出分布的直接投影，不是文本字符串。
      """
      state_id: str
      producer_role: str          # 通常是 executor
      consumer_role: str          # 通常是 summarizer
      storage_kind: StorageKind
      length: int                 # float32 向量元素数
      blob_hash: str
      top_k: int = 20
      entropy: float = 0.0        # H = -Σ p_i * log(p_i)，预计算
      confidence_proxy: float = 0.0  # 1 - normalized_entropy
      channel: str = "logit_state"
      metadata: dict = field(default_factory=dict)
      
      def registry_entry(self) -> RefRegistryEntry:
          return RefRegistryEntry(
              ref_id=self.state_id,
              ref_kind=RefKind.LOGIT_STATE,
              storage_kind=self.storage_kind,
              status=RefStatus.ACTIVE,
              blob_hash=self.blob_hash,
              schema_version=self.metadata.get("schema_version", "logit_state.v1"),
          )

  2-3：v2/state/store.py — LayeredStoragePolicy.kind_preferences dict 追加：
  "LOGIT_STATE": (StorageKind.MEMFD, StorageKind.SHARED_MEMORY, StorageKind.MMAP_FILE),

  2-4：v2/runtime/role_path.py — Executor LLM 请求构建处，仅 local_vllm 模式下注入 logprobs：
  # 仅 local_vllm 模式：通过 extra_body 请求 logprobs
  # extra_body 字段已存在于 LLMRequest（runtime/llm.py:88），无需改 dataclass
  if role_path_mode == "local_vllm":
      extra_body = dict(llm_request_kwargs.get("extra_body") or {})
      extra_body["logprobs"] = Trueextra_body["top_logprobs"] = 20
      llm_request_kwargs["extra_body"] = extra_body

  2-5：新增序列化工具函数（可放在 v2/runtime/role_path.py 或单独 v2/runtime/logit_state.py）：
  import struct, math

  def serialize_logit_state(
      top_logprobs: list[dict],   # vLLM API 返回的 top_logprobs 列表
      top_k: int = 20,
  ) -> tuple[bytes, float, float]:
      """
      序列化 vLLM 返回的 top_logprobs 为 float32 binary。
      返回 (payload_bytes, entropy, confidence_proxy)。
      """
      if not top_logprobs:
          return b"", 0.0, 0.0
      # 取最后一个生成 token 的 top-k logprob（代表整体生成置信度）
      last = top_logprobs[-1]
      logprob_values = list(last.values())[:top_k]
      probs = [math.exp(lp) for lp in logprob_values]
      total = sum(probs) or 1.0 
      probs = [p / total for p in probs]
      entropy = -sum(p * math.log(p + 1e-12) for p in probs)
      max_entropy = math.log(len(probs)) if len(probs) > 1 else 1.0
      confidence_proxy = 1.0 - (entropy / max_entropy)
      payload = struct.pack(f"<{len(probs)}f", *probs)
      return payload, entropy, confidence_proxy

  2-6：在 Executor 完成后，把 logit state publish 到 state store，构造 LogitStateRef，传给 Summarizer 的 input_state_refs。

  2-7：Summarizer 处理逻辑增加：若 logit_state_ref.confidence_proxy < 0.3（低置信），记录到 telemetry
  logit_confidence_gate_trigger_count。

  2-8：新增 telemetry 字段：
  - logit_state_transfer_count：成功序列化传递的次数
  - logit_state_mean_entropy：所有 case 的平均 entropy
  - logit_confidence_gate_trigger_count：低置信触发次数

  完成后运行：
  python -m pytest -q tests/v2/test_refs.py tests/v2/test_state_store.py -x
  python -m runtime.smoke --mode protocol

  ---
  阶段 3：API 正确性验证（no-KV 主线，先用 DeepSeek API）

  阶段 2 完成后，先用现有 API 配置（DeepSeek）验证路线 A 没有破坏已有功能：

  # 进入容器
  docker exec -it statebus-dev-qcrs bash
  source deploy/activate_statebus_host.sh

  # preflight 验证
  python -m v2.benchmark.live_runner \
      --suite preflight \
      --role-path-mode api \
      --embedding-mode deterministic

  # 如果通过，跑 formal internal
  python -m v2.benchmark.live_runner \
      --suite formal \
      --benchmark-tier formal \
      --role-path-mode api \
      --embedding-mode local

  观察：
  - logit_state_transfer_count 字段是否出现（API 模式下不会触发，因为只在 local_vllm 模式注入 logprobs）
  - 已有字段（memfd_transfer_count、semantic_state_transfer_count、quality）是否正常

  ---
  阶段 4：切换到 Qwen3-32B local vLLM 进行 KV 实验

  修改 deploy/statebus_llm.yaml.local：

  providers:
    default:
      kind: openai_compatible
      base_url: http://127.0.0.1:53334/v1
      timeout_s: 120

  roles:
    planner:
      model: qwen3-32b
      json_output: true
      temperature: 0.0
    retriever:
      model: qwen3-32b
      json_output: true
      temperature: 0.0
    executor:
      model: qwen3-32b
      json_output: true
      temperature: 0.0
    summarizer:
      model: qwen3-32b
      json_output: true
      temperature: 0.0

  4-1：兼容性测试（preflight，~5 分钟）

  python -m v2.benchmark.live_runner \
      --suite preflight \
      --role-path-mode api \
      --embedding-mode deterministic

  观察：JSON 输出是否稳定（Qwen3-32B 的 JSON structured output 遵循度）。

  4-2：F-01 — text vs protocol 等价双模对比（补 G-01）

  STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1 \
  python -m v2.benchmark.live_runner \
      --suite compare \
      --benchmark-tier formal \
      --role-path-mode api \
      --embedding-mode local

  目标：formal_external_claim_kind 从 debug_only 升级，text vs protocol 各 25 case 全质量通过。立即保存 artifact。

  4-3：formal internal（补基线）

  STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1 \
  python -m v2.benchmark.live_runner \
      --suite formal \
      --benchmark-tier formal \
      --role-path-mode api \
      --embedding-mode local

  4-4：LogitStateRef 在 local_vllm 模式下的首次端到端测试

  STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1 \
  STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix \
  python -m v2.benchmark.live_runner \
      --suite formal \
      --benchmark-tier formal \
      --role-path-mode local_vllm \
      --embedding-mode local

  观察：logit_state_transfer_count、logit_state_mean_entropy、vllm:gpu_prefix_cache_hit_rate。

  4-5：mmap backend 对比（补 G-09）

  STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1 \
  python -m v2.benchmark.live_runner \
      --suite formal \
      --benchmark-tier formal \
      --role-path-mode api \
      --embedding-mode local \
      --state-pool-mode mmap

  4-6：subprocess transport（补 G-12）

  STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1 \
  python -m v2.benchmark.live_runner \
      --suite formal \
      --benchmark-tier formal \
      --role-path-mode local_vllm \
      --embedding-mode local \
      --state-pool-mode memfd \
      --transport subprocess

  4-7：multi-family continuous（补 G-03）

  python -m v2.benchmark.live_runner \
      --suite statebus \
      --benchmark-tier dev \
      --role-path-mode api \
      --embedding-mode local

  ---
  重要提示

  每次实验完成后立即：
  1. git status --short 确认只有预期文件变动
  2. 记录 run_id 和关键 artifact 路径
  3. 不要用 git add .，只 stage 已审核的文件

  上下文管理：
  - 8192 token 限制通过 STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1 和 _context_window_adjusted_request 自动处理
  - 如果某个 case 触发 context 400 error，是已知风险，不需要人工干预

  vLLM 不要重启（除非明确需要切换 prefix caching 开关状态进行 A/B 对比）。

  ---
# Start Here

当前默认工作对象是 `v2` clean-room branch / worktree。旧 host-mainline 文档已经归档到 `docs/archive/legacy_202606_host_mainline/`，不要用它们覆盖当前 v2 判断。

## 1. 基础状态

```bash
cd /home/qcrs/statebus/project
git branch --show-current
git status --short
git rev-parse --short HEAD
```

当前 worktree 可能带有 KV/prefix/neural-state 实验改动。正式提交或复跑归档前，先确认这些改动是否属于本次证据范围。

## 2. Host 环境

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/v2
```

如果依赖缺失：

```bash
bash scripts/setup_host_dev_env.sh
```

## 3. v2 Container

```bash
export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
export STATEBUS_DOCKER_TARGET=core
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d
docker exec -it statebus-dev-qcrs bash
```

## 4. Local+API Comprehensive Rerun

物理 GPU 选择用 `STATEBUS_CUDA_VISIBLE_DEVICES`。如果指定物理卡 1，容器/PyTorch 内部仍使用 `cuda:0`：

```bash
cd /home/qcrs/statebus/project

export STATEBUS_LOCAL_API_STAMP="$(date +%Y%m%d_%H%M%S)"
export STATEBUS_LOCAL_API_RUN_ID="sb2-gpu1-${STATEBUS_LOCAL_API_STAMP}"

export STATEBUS_LOCAL_API_NO_TIMEOUTS=1
export STATEBUS_LOCAL_API_PYTEST_MODE=full
export STATEBUS_LOCAL_API_RUN_FLAGSHIP=1
export STATEBUS_LOCAL_API_REPEAT=1
export STATEBUS_LOCAL_API_STRICT_EXIT=1

export STATEBUS_CUDA_VISIBLE_DEVICES=1
export CUDA_VISIBLE_DEVICES=1
export STATEBUS_EMBED_DEVICE=cuda:0

export TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export STATEBUS_CODEACT_SANDBOX_BACKEND=auto

bash scripts/run_v2_local_api_comprehensive_stats.sh
```

复跑后看：

```bash
ART="/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_${STATEBUS_LOCAL_API_STAMP}"

jq '{
  run_id,
  failed_stage_count,
  failed_required_stage_count,
  failed_stages,
  failed_required_stages,
  key_metrics
}' "$ART/summary.json"

sed -n '1,260p' "$ART/summary.md"
```

## 5. 当前必须检查的证据字段

- `formal_compare_full_registry_coverage`
- `formal_compare_case_count`
- `formal_compare_family_count`
- `strict_equal_quality_comparison_valid`
- `serialized_latency_superiority_claim_allowed`
- `comparator_token_split_schema`
- `api_statebus_prompt_tokens`
- `api_external_prompt_tokens`
- `api_statebus_completion_tokens`
- `api_external_completion_tokens`
- `stress_failure_reason_counts`

## 6. Claim 边界

- formal compare 代码已经走 full registry adapter，但 live API evidence 必须以后续 rerun artifact 为准。
- latency 优势只能在 serialized rerun guard 允许时 claim。
- StateRef 当前是 embedding semantic state + refs + hydration accounting。
- 不要 claim hidden-state / KV cache transfer。
- 不要 claim openEuler VM validation，除非有 VM/container validation artifact。

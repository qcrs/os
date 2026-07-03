# P0-1：证据刷新与验证闭环

**优先级**：P0（阻塞其他所有 claim）
**目标**：在 HEAD 代码下完整重跑所有 v2 证据，确保 frozen baseline 之后的修复不破坏已有结论

---

## 一、问题根因

当前所有正式证据绑定 frozen baseline commit `f7dcb15`，而之后的修复提交：

| commit | 内容 | 潜在影响 |
|---|---|---|
| `43c41bc` | fix: fail closed and fallback bounded codeact generation | codeact_sandbox 路径、bounded_llm_codeact_demo |
| `43b5951` | fix: unwrap bounded codeact json responses | codeact response parser，影响 API 生成解析 |
| `5762d88` | fix: add bounded codeact repair loop | repair loop 新增，影响 demo 流程 |
| `b9695df` | fix: stabilize external pure-text comparator diagnostics | external comparator 诊断稳定性 |

此外存在**未提交修改**：
- `scripts/v2_diagnostics/bounded_llm_codeact_demo.py`
- `tests/v2/test_bounded_llm_codeact_demo.py`

在这些修改未提交、证据未重跑的情况下，任何新实验的证据都无法与 frozen baseline 正确对齐。

---

## 二、执行步骤

### Step 1：提交未提交的修改

在容器外（host 侧）先确认 dirty files：

```bash
cd /home/qcrs/statebus/project
git status --short
git diff scripts/v2_diagnostics/bounded_llm_codeact_demo.py
git diff tests/v2/test_bounded_llm_codeact_demo.py
```

确认修改内容后提交（不要 amend，新建 commit）：

```bash
git add scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
        tests/v2/test_bounded_llm_codeact_demo.py
git commit -m "fix: commit bounded codeact demo and test updates post-repair-loop"
```

---

### Step 2：完整 v2 pytest 容器重跑

```bash
export STATEBUS_CONTAINER_VALIDATION_DIR=/statebus/runs/container-validation-head-pytest-$(date +%Y%m%d_%H%M%S)
export STATEBUS_HOST_VALIDATION_DIR=$HOME/statebus/runs/container-validation-head-pytest-$(date +%Y%m%d_%H%M%S)
mkdir -p "$STATEBUS_HOST_VALIDATION_DIR"

docker exec \
  -e STATEBUS_CONTAINER_VALIDATION_DIR="$STATEBUS_CONTAINER_VALIDATION_DIR" \
  statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  mkdir -p "$STATEBUS_CONTAINER_VALIDATION_DIR"

  # 环境记录
  python3 --version 2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/env.log"
  git log --oneline -8 2>&1 | tee -a "$STATEBUS_CONTAINER_VALIDATION_DIR/env.log"
  git status --short 2>&1 | tee -a "$STATEBUS_CONTAINER_VALIDATION_DIR/env.log"

  # 全量 v2 pytest
  python3 -m pytest -q tests/v2 \
    2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/pytest-v2-head.log"

  echo "PYTEST_EXIT=$?" | tee -a "$STATEBUS_CONTAINER_VALIDATION_DIR/pytest-v2-head.log"
  echo "$STATEBUS_CONTAINER_VALIDATION_DIR"
'
```

**验收标准**：`pytest-v2-head.log` 末尾出现 `N passed` 且无 `error`，N ≥ 154

---

### Step 3：CodeAct bounded demo 单独重跑

```bash
docker exec \
  -e STATEBUS_CONTAINER_VALIDATION_DIR="$STATEBUS_CONTAINER_VALIDATION_DIR" \
  statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  mkdir -p "$STATEBUS_CONTAINER_VALIDATION_DIR/diagnostics"

  # deterministic mode（应稳定通过）
  python3 scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
    --role-path-mode deterministic \
    --sandbox-backend bwrap \
    --output-root "$STATEBUS_CONTAINER_VALIDATION_DIR/diagnostics/codeact-det" \
    2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/codeact-det.log"

  # api mode（记录失败原因供后续分析）
  python3 scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
    --role-path-mode api \
    --sandbox-backend bwrap \
    --max-repair-attempts 3 \
    --output-root "$STATEBUS_CONTAINER_VALIDATION_DIR/diagnostics/codeact-api" \
    2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/codeact-api.log"
'
```

**验收标准**：
- deterministic：`ok=true`，`ast_policy_pass=true`，`sandbox_backend=bwrap`
- api：记录失败原因（`generation_attempts.json` 保存每次 attempt），供 `04_codeact_stabilization.md` 分析

---

### Step 4：flagship ablation + replay negative audit 重跑

```bash
docker exec statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  REPORT_ROOT=/statebus/runs/v2-head-evidence-$(date +%Y%m%d_%H%M%S)
  mkdir -p "$REPORT_ROOT"

  python3 -m v2.benchmark.flagship_ablation \
    --role-path-mode api \
    --embedding-mode local \
    2>&1 | tee "$REPORT_ROOT/flagship-ablation.log"

  python3 -m v2.benchmark.live_runner \
    --suite replay-negative-audit \
    --role-path-mode api \
    --embedding-mode local \
    2>&1 | tee "$REPORT_ROOT/replay-negative-audit.log"

  python3 -m v2.benchmark.live_runner \
    --suite formal \
    --benchmark-tier formal \
    --role-path-mode api \
    --embedding-mode local \
    2>&1 | tee "$REPORT_ROOT/formal-suite.log"

  echo "$REPORT_ROOT"
'
```

---

### Step 5：更新 final evidence index

重跑完成后，更新 `docs/reports/final_v2_evidence_index_20260703.md`（或新建 `final_v2_evidence_index_head.md`），记录：
- 新的 commit hash
- 新的 pytest 通过数量
- 每个 benchmark JSON 的 sha256
- 时间戳

---

## 三、预期产出

| 产出 | 路径 | 用途 |
|---|---|---|
| HEAD pytest log | `$VALIDATION_DIR/pytest-v2-head.log` | 替代 frozen baseline 的 pytest 证据 |
| CodeAct det bundle | `$VALIDATION_DIR/diagnostics/codeact-det/summary.json` | bounded CodeAct claim 基础 |
| CodeAct api attempts | `$VALIDATION_DIR/diagnostics/codeact-api/generation_attempts.json` | 供 `04_codeact_stabilization.md` 分析 |
| flagship ablation JSON | runtime artifact root | 非文本状态传递证据 |
| replay negative audit JSON | runtime artifact root | replay 边界证据 |
| formal suite JSON | runtime artifact root | formal 质量基线 |

---

## 四、注意事项

1. **Step 4 中的 api 命令需要 `STATEBUS_LLM_API_KEY` 环境变量**，确认容器内已配置
2. **flagship ablation 和 continuous 依赖本地 embedding 模型**：确认 `/statebus/models/Qwen3-Embedding-0.6B` 存在
3. **重跑不修改任何代码**，只是跑现有代码并记录结果
4. **如果 pytest 出现新的 failure**，先记录 failure 信息，不要立即修复，而是在 `01_p0_evidence_refresh.md` 中追加问题记录

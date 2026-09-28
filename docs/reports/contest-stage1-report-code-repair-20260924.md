# Stage1 通用报告、CodeAct 和验收修复（2026-09-24）

## 结论与停止点

修复已落地；最终离线检查和定向真实角色复核通过。**最终代码尚未重新通过四任务整批验收，不应启动三配置扩量或正式 40 次矩阵。** 下一步先运行一个新目录下的 SB-NO-MEMORY 四任务诊断批次，4/4 且 acceptance 通过后，再另开冻结三配置 Stage1。

本轮只修改 os；未改 project，未启动/重启 GPU、vLLM、容器，未改 sandbox/authority，未 commit/push。没有增加原有 retry、token、timeout 预算，没有自动填充正文或猜补坏 JSON。

证据目录：`runs/contest-repair-20260924_230853/`；成本与文件校验汇总：`final-audit.json`。

## 落地修改

1. **正文要求显式传递**：通用 RolePath 接收调用者的 `report_requirements`，不内置业务实体或风险字段。去除 SB task_goal 中重复合同，明确 claim_id/uncertainty_note 不替代 claim_text。两产品路径使用同一公开报告合同。
2. **完整 repair 上下文**：同一次既有 repair 接收前次候选、全部验证错误、字段要求。实体缺失时，可用唯一证据绑定做诊断关联，但实体覆盖错误仍保留；绝不把引用或 ID 算作正文。无唯一关联时不猜测。
3. **具体格式反馈**：真实模型仍使用 `risk: true` / `risk_change: initial`，因此补上明确的 `=` 要求及字段级解释，指向已验证行，不提供参考业务答案。P-TEXT 也获得同样解释。正文质量门未放宽，仍是 `stage1-report-v2-extractive-context`；完整自然语言质量仍需人工审阅。
4. **代码格式诊断**：坏 JSON/fenced JSON 标为 `code_response_format`，给出有限长的解析原因和行列；真正 Python 错误标为 `syntax_error` 并给出行列/原因。坏包装保持原文、不得执行；沿原一次 policy repair 要求完整 raw Python。合法 raw、Python/py/no-language fence、JSON、JSON fence 均回归通过。
5. **验收不再首错吞账**：批次计数失败仍继续审阅全部四个计划任务，保留 journal、usage、失败分类、scorer、报告检查、预算/配置等；最后 fail-closed。usage 缺失保留 null 和原因，另列已观察部分，失败与 repair 不丢账。不追随 ledger 中任意 result_path。
6. **追加的 Planner 根因修复**：新诊断发现 Executor 输出不受支持的 `max_conflicts`。只加提示不足，实际响应 schema 复用了所有角色的字段并集。现按 capability registry 为固定 role slot 生成该角色的 criteria 字段并集；同角色多个 capability 的精确边界仍由原 PlanPolicyValidator 检查。没有为 O02 特删字段，没有由 Controller 修补候选或扩大 authority。

业务相关字段留在既有 benchmark 合同；通用 RolePath/CodeAct 不含 F/O task ID、固定实体或答案。测试用不同命名的传感器报告及动态 capability 注册内容验证这一点。

## 验证证据与边界

各批独立，不合并计数：

| 验证 | 结果 | 证据 |
|---|---|---|
| 最终 Host：报告/任务/验收/提示/AST/formal compare | 179 passed | `schema-host-tests-verified.log` |
| openEuler：含 bwrap、CodeAct integration 的完整相关批次（最后 role-slot schema 修改前） | 198 passed, 5 skipped | `final-container-tests.log` |
| 最终 role-slot schema、原 Planner policy、真实失败报告回归 | 42 passed | `schema-container-tests.log` |
| GPU/service 预检 | 通过；物理 GPU1 → cuda:0，1024 维实际 encode | `preflight/preflight.json` |
| 历史 0/4 批次只读重审 | 仍拒绝；四任务、19 请求、53,424 tokens 完整 | `historical-acceptance-recheck.json` |

容器 5 项 skip 是缺少 jq 的 Host shell 编排测试，Host 已覆盖。早期受限环境的 bwrap 验证未能进入 namespace；批准在宿主运行同组测试后 25 passed，并在真实容器重新覆盖。未通过改 sandbox 掩盖失败。一次测试命令误写不存在的 test_plan_policy.py，未运行测试；随后按实际 tests/test_adaptive_planner_policy.py 完成验证。

回归包括：
- 保存并重放历史 F01/F02/O01 的原始失败候选、两份 O02 坏 JSON，测试不依赖 runs 目录存在。
- 真实 worker → RolePath → rendered request → candidate → validator 链，验证所有缺项及前次候选能进入唯一 repair；持续失败仍严格停止。
- 冒号格式仍被拒绝；正确正文通过；只把正文移入 claim_id 仍失败。
- 财务与巡检跨期负控：改用非原始实体名，让末行风险与全周期聚合风险双向相反。错误 risk_change 同时被独立 Decimal scorer 与 Runtime 重算拒绝；未修改算法或生成数据去帮助模型过关。
- 完整/损坏代码包装、真实 Python syntax、有界诊断、坏包装无执行、一次修复进入真实 bwrap。
- 验收在失败、超时、缺 scorer/journal、坏数据/配置、伪造 result_path 时继续汇总而不放行。
- 动态 role-slot schema：未知业务能力按 registry 推导；当某 Executor capability 合法注册 max_conflicts 时字段仍可用。

`git diff --check` 与阶段脚本 `bash -n` 均通过。

## 真实运行：不能掩盖中间失败

### 修复途中冻结四任务批次

目录：`sb-no-memory/`。源码摘要前后一致，见 `source-before.txt`、`source-after.txt` 和 `live-exit-status.txt`。此批发生在最后的字段解释和 role-slot schema 修复之前。

| 任务 | 结果 | 直接原因 |
|---|---|---|
| F01 | 失败 | 数值通过一次 quality repair；正文用了冒号，报告 repair 未纠正 |
| F02 | 失败 | 数值通过；risk_change 使用冒号，报告 repair 未纠正 |
| O01 | 通过 | 两个报告子批均在既有单次 repair 后通过 |
| O02 | 失败 | Planner 初始及 repair 均将 max_conflicts 放入不支持它的 Executor capability |

合计 **1/4，20 请求，59,054 tokens，任务 elapsed 合计 594.663 秒**。耗时不是性能比较，资源不独占。外层 acceptance 正确拒绝并完整保存全部成本、原因。

### 最后角色级复核

- `final-role-probes/`：两份失败报告分别用一次真实 Summarizer 请求修复，均通过；同批一次 prompt-only Planner 请求仍失败。共 3 请求、8,794 tokens。
- `schema-planner-probe/`：收敛 role-slot schema 后，同一 Planner 诊断输入单次请求通过原 policy。1 请求、4,335 tokens。
- 角色探针没有执行整个业务任务，没有 Memory，也不构成 F01/F02/O02 新的 task pass。
- 代码包装 repair 在离线真实 bwrap 中验证；本轮最后 live 没有重新覆盖原 O02 Executor 坏包装路径，不能称它的真实端到端表现已验证。

本轮全部新模型成本：**24 请求、72,183 tokens**（含 20 次整批请求和全部 4 次角色诊断，包括失败的 Planner 请求）。历史重审不产生新模型成本，不与本轮相加。明细见 `final-audit.json`。

## 下一步：仅一个新的四任务诊断批次

不要重用旧目录，不启动 `--stage all`。以下命令先预检，再只运行 SB-NO-MEMORY；即使 runner 失败也保存 acceptance。服务只复用，不启动或重启。运行中不得修改代码、提示或预算。

```bash
cd /home/qcrs/statebus/os
(
  set -uo pipefail
  ROOT="$PWD/runs/contest-next-check-$(date +%Y%m%d_%H%M%S)"
  scripts/run_contest_measurement_stages.sh --stage 1 --preflight-only \
    --run-root "$ROOT" || exit $?
  digest() {
    rg --files -0 statebus scripts deploy -g '*.py' -g '*.sh' -g '*.example' -g '*.yaml' \
      | sort -z | xargs -0 sha256sum | sha256sum
  }
  digest >"$ROOT/source-before.txt"
  CROOT="$(scripts/run_g6b2_os_container.sh map-path "$ROOT")"
  PY=/home/qcrs/statebus/conda-envs/statebus_host/bin/python
  scripts/run_g6b2_os_container.sh exec "$PY" -m statebus.benchmark.contest_stage1 \
    --output-root "$CROOT/sb-no-memory" --profile SB-FULL --family all \
    --sb-memory-policy none --embedding-model-path /statebus/models/Qwen3-Embedding-0.6B \
    --embedding-device cuda:0 >"$ROOT/sb-no-memory.log" 2>&1
  runner_status=$?
  scripts/run_g6b2_os_container.sh exec "$PY" -m statebus.benchmark.contest_stage_gate \
    --root "$CROOT/sb-no-memory" --variant sb-no-memory >"$ROOT/gate.log" 2>&1
  gate_status=$?
  digest >"$ROOT/source-after.txt"
  cmp "$ROOT/source-before.txt" "$ROOT/source-after.txt"; source_status=$?
  printf 'root=%s\nrunner=%s gate=%s source=%s\n' "$ROOT" "$runner_status" "$gate_status" "$source_status"
  (( runner_status == 0 && gate_status == 0 && source_status == 0 ))
)
```

只有这一批 4/4、acceptance.ok=true、源码未变，才从另一个新目录启动三配置 `scripts/run_contest_measurement_stages.sh --stage 1`。仍不能把这些开发 smoke 或不同代码版本拼成正式成绩。

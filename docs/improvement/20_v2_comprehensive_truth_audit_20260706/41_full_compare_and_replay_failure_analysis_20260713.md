# Qwen3-32B Full Compare / Replay Failure Analysis

日期：2026-07-13  
运行环境：`statebus-dev-qcrs`，local embedding，最终回归使用 `cuda:1`；四角色使用 `http://127.0.0.1:53334/v1` 的 `qwen3-32b`。

## 结论摘要

这次 full run 不是“所有链路都失败”。原始运行的 preflight、v2 回归测试和 25-case compare 均完成；失败发生在 replay stage 的质量门。失败退出语义现在是正确的：脚本不会把有部分输出的失败阶段标记为成功。

原始 replay 中有两个不同层次的问题：一是某次 planner 请求超过原来的 120 秒请求预算，导致 stage 直接退出；二是 L0 的四个 case 选择了 `generate_chart`，数值事实虽正确，但 route 不满足严格质量门。延长到 240 秒并设置两次请求尝试后，超时不再是主阻塞；L0 route 提示修复后，四个 case 已在真实 local-vLLM 回归中全部通过。

全量 replay 的最后一个失败是 `formal-agg-003`。它输出了正确的均值 `5.979`、正确的 `csv_profiler`，但从候选列表全局排序中选了 `profile_table`，而 canonical intent 是 `profile_and_mean`。修复后，卡 1 单例 L3 replay-ready 真实回归通过，说明问题是候选提示/排序契约，而不是数据、artifact、replay gate 或 embedding。

## 证据边界

- 原始运行：`/statebus/runs/full_qwen3_gpu0_20260713/`（用户提供的容器日志；该目录在当前容器重启后不再可读）。
- 已保存的 25-case replay 机制证据：`/statebus/runs/replay_fix_full_gpu1_20260713/`。
- 修复后的真实单例：`/statebus/runs/replay_fix_formal_agg_003_gpu1_20260713/`。
- 所有 formal 结论必须同时满足 case coverage、quality floor、route/tool/fact exact 和 replay telemetry，不能只依据进程 exit code。

## 原始 full run 分阶段结果

| 阶段 | 结果 | 可信解释 |
|---|---:|---|
| `00_preflight` | PASS | 配置、vLLM、local embedding 检查通过；后续已增加真实 embedding encode probe。 |
| `01_pytest_v2` | PASS | v2 测试集通过，属于代码回归证据，不等于 live LLM 质量证据。 |
| `02_compare_full` | PASS | 25/25 StateBus 和 External quality floor，通过 strict equal-quality gate；这是 serialized first-pass，不是重复实验后的统计结论。 |
| `03_replay_full` | FAIL | 原始 120 秒请求预算触发 timeout；随后暴露 L0 route 和 replay artifact 契约问题。 |
| 后续阶段 | 未执行 | `set -e` + stage gate 正确停止，避免假阳性。 |

### Compare 结果如何解读

原始 compare 记录为：StateBus quality 25/25，External quality 25/25，fairness gate 25/25，strict equal quality 有效；StateBus task time 586,785 ms，External 817,567 ms，差值 -230,782 ms；StateBus prompt tokens 59,489，External 71,519。该结果可以作为一次 serialized first-pass 观测，但不能单独升级为稳定性或统计显著性 claim。

## 根因定位

### 1. 请求预算过短

原配置为 `timeout_s=120`、`request_max_attempts=1`。Qwen3-32B 在 L3 planner 请求中出现 `openai.APITimeoutError`，stage 因此失败。修复后的 full script 默认使用 `timeout_s=240`、`request_max_attempts=2`、可配置 retry delay，并保留失败即退出的语义。

### 2. L0 route exact 不稳定

`formal-trend-001/002/005` 和 `formal-join-004` 的值和 artifact 正确，但自由文本角色从公开候选中选择了 `generate_chart`，严格 route gate 因此失败。修复没有改变 scorer，也没有注入标准答案；`role_path.py` 只把公开的 preferred candidate 及 route hints 展示给模型。真实 GPU1 回归结果为 4/4 quality、4/4 route exact、4/4 tool exact、4/4 metric exact。

### 3. scorer 字段污染 replay runtime

formal adapter 过去把 scorer 用的 `metric_name/metric_value` 合成字段注入运行时 `expected_facts`。非财务 formal case 的 artifact validator 因此要求任务本身不存在的字段，例如 `formal-trend-003` 实际输出 `{delta_value, delta_pct}`，却被要求同时提供合成的 `metric_name/metric_value`，导致 artifact 无法进入 replay memory。

现在 adapter 保留任务原始事实；`metric_name/metric_value` 只在 `score_fixed_answer_case()` 边界通过 `expected_facts_for_scoring()` 生成。这样 scorer 仍可共享质量定义，但 replay validator 只看到真实任务 contract。该修复已由 `formal-trend-003` 单例 replay 回归验证。

### 4. `formal-agg-003` 候选排序 bug

该 case 的公开候选同时包含：

- 全局高排名：`profile_table::csv_profiler`
- canonical intent：`profile_and_mean::csv_profiler`

旧逻辑只调用 `best_visible_candidate()`，所以把 `profile_table` 提示给模型。修复后的 `_preferred_candidate_payload()` 按 `route_hints` 顺序优先匹配 canonical intent，再回退全局排序（见 [role_path.py](/home/qcrs/statebus/project/v2/runtime/role_path.py:577)）。新增测试明确断言该 case 选择 `profile_and_mean/csv_profiler`。

## Replay 机制证据

修复后的 25-case L3 replay 产物显示：

- case coverage：25/25
- validated replay：25/25
- memory match：25/25
- skipped step：25
- runtime artifact quality：25/25
- verified artifacts：50
- semantic state transfer：25
- shared-memory publish：25
- logit state transfer：25

该轮共享 scorer 仍为 24/25，唯一失败为 `formal-agg-003` 的 route exact；其 metric、artifact、memory match 和 replay gate 都已通过。因此不能把 24/25 写成“replay 机制失败”，应区分“机制层通过”和“质量层 route 仍有一例失败”。

### GPU1 单例最终回归

产物：`/statebus/runs/replay_fix_formal_agg_003_gpu1_20260713/stdout.json`。

关键字段：

```text
selected_case_count=1, available_case_count=25
selected_layer=L3, effective_statebus_mode=replay_ready
quality_floor_pass_count=1
route_exact=1, tool_exact=1, metric_value_exact=1
validated_replay_count=1, skipped_step_count=1
memory_match_count=1, verified_artifact_count=2
logit_state_transfer_count=1
neural_prefix_cache_hit_count_estimate=1/2
```

这里 `validated_replay_count=1` 而 `exact_replay_count=0` 是预期的：当前 gate 证明了兼容性并允许复用，但候选 key 不是 exact-key replay。该结果不能宣传为 KV tensor transfer； prefix 字段仍受 `engine_local_prefix.v1` 的 identity/scheduling-only claim boundary 限制。

## 代码修复清单

1. [role_path.py](/home/qcrs/statebus/project/v2/runtime/role_path.py:577)：route hint 优先的 preferred candidate，并同时用于 structured/text collaboration prompt。
2. [formal_registry_adapter.py](/home/qcrs/statebus/project/v2/benchmark/formal_registry_adapter.py:77)：运行时 facts 保持原始任务事实，不再写入 scorer projection。
3. [scoring.py](/home/qcrs/statebus/project/v2/benchmark/scoring.py:38)：在 scorer 边界生成 projection 字段。
4. `external_text_baseline.py`：external lane 使用独立 public-file tool；不导入 StateBus runtime、不读取 expected facts，并使用 closed-set schema。
5. [run_v2_full_qwen3_container.sh](/home/qcrs/statebus/project/scripts/run_v2_full_qwen3_container.sh:61)：默认 local embedding `cuda:1`、240 秒 timeout、两次请求尝试；stage gate 失败即停止，replay 只执行 L3，避免重复跑 L0-L2。
6. 新增 `formal-agg-003` preferred-candidate 回归测试；本地测试和脚本语法检查均通过。

## 验证结果

```text
python -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py  # 69 passed
python -m pytest -q tests/v2/test_preflight_and_live_runner.py tests/v2/test_smoke.py  # 43 passed
python -m py_compile v2/runtime/role_path.py tests/v2/test_fixed_answer_and_external_baseline.py
bash -n scripts/run_v2_full_qwen3_container.sh
git diff --check
```

真实 GPU1 单例使用 local embedding、local-vLLM、L3 replay-ready，exit code 0 且所有上述单例门禁通过。

## 尚未解决或不应过度宣称的事项

- 25-case replay 需要在 route 修复后重新跑一次，才能获得 25/25 shared quality 的新全量证据；单例不能替代全量。
- Prefix Feedback Loop 当前仍未接入调度器。现有 `neural_prefix_cache_hit_rate_estimate` 是任务内估计，不是 vLLM 生命周期累计 counter delta；正式归因实验前不能写成真实服务命中率。
- `bwrap` 在容器中不可用时会 fallback 到 resource backend；这不是 `nsjail` 或强隔离证明。
- full script 的连续 family 仍是稳定性/连续任务验证，不应与单例 smoke 混用。轻量 smoke 应使用 `--case-id`、L3 replay-ready 和 Round 1→2 的最小矩阵；全量报告仍保留 25-case/各 family 的完整证据。
- 当前结果是一次 serialized first-pass 证据；若要形成性能 headline，需要预先冻结重复次数、随机种子、顺序和报告规则，再进行重复实验。

## 推荐后续顺序

1. 在容器内用 `cuda:1` 重跑 full script，保留 compare、L3 replay、两类 continuous 和 formal L0-L3；确认 `summary.json` 的所有 stage 为 pass。
2. 在全量重跑前，可先执行 `formal-agg-003` 单例作为 20 秒级路由 smoke；失败时不浪费 25-case 运行时间。
3. 另行设计 Prefix Feedback counter-delta 实验，不把当前估计字段纳入正式 claim。
4. 完成全量后再讨论重复轮数；“10 轮”是赛题要求的连续稳定性能力，不等于每个 full case 必须重复十次。

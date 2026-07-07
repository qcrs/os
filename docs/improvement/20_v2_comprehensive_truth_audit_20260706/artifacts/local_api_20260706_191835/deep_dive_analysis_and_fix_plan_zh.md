# StateBus v2 local+api 结果深度拆解与修复计划

运行 ID：`v2-local-api-20260706_191835`

分析日期：2026-07-06

主结果目录：`/home/qcrs/statebus/runs/v2-local-api-20260706_191835/artifacts`

审计副本目录：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260706_191835/`

对应代码提交：`ddb8c8d28873ffa457e0068486e2d44c77b94767`

本轮分析目标不是再做一次表面汇总，而是回答三个问题：

1. 本次 local+api 全面测试实际验证了哪些实现路径。
2. formal compare 为什么仍然出现“跑通但 claim 不能闭环”的情况。
3. 后续应该按什么顺序修，才能避免之前那种反复改、反复不收敛。

## 1. 一句话结论

本轮测试整体执行成功，13 个 stage 全部 exit 0，required stage 失败数为 0。`formal internal` 路径的证据很强：API 四角色、local embedding、memfd StatePool、25 case / 5 formal families 全部跑通并 25/25 通过。

但 `formal compare` 仍不能直接作为 headline formal external superiority 证据。核心原因不是执行失败，也不是 fairness gate 失败，而是 compare 指标语义已经混在一起：

- 旧语义：`comparison_valid` 要求 StateBus 和 external 都通过 headline quality floor。
- 新语义：`formal_superiority_claim_allowed` 又允许 external 质量不满分时，将 StateBus 的质量优势作为 superiority 证据。
- 这两个语义同时存在，导致同一份报告里出现 `comparison_valid=False`、`formal_headline_eligible=False`，但 `formal_superiority_claim_allowed=True`。

这就是之前修复一直不成功的主因：修复只补了一个 superiority path，但没有把“严格同质量效率比较”和“质量优势比较”拆成两个独立 gate。

## 2. 运行过程拆解

### 2.1 脚本执行方式

本轮由 `scripts/run_v2_local_api_comprehensive_stats.sh` 驱动。脚本在 host 侧启动 container 内命令：

- container 默认：`statebus-dev-qcrs`
- host project root：`/home/qcrs/statebus/project`
- container project root：`/workspace/statebus/project`
- host runs root：`/home/qcrs/statebus/runs`
- container runs root：`/statebus/runs`

脚本进入 container 后使用：

- `/usr/bin/python3 -m v2.benchmark.live_runner`
- `--role-path-mode api`
- `--embedding-mode local`
- formal / compare / carrier compare stages 使用 `--state-pool-mode memfd`
- 每个 stage 使用独立 `runtime_root` 和 `workspace_root`

这点很重要：本轮不是 deterministic fallback 证据，也不是共享 workspace 污染出来的结果。每个 benchmark stage 都有独立运行目录。

### 2.2 AF_UNIX 风险处理

脚本显式使用短 socket：

```text
/tmp/sb2-<16hex>.sock
```

运行日志中每个 live stage 的 socket path 长度都是 30，例如：

```text
/tmp/sb2-4e63ff307efd1455.sock len=30
/tmp/sb2-628c1fcc5c5ff1ce.sock len=30
```

因此本轮没有触发 Linux `AF_UNIX` 路径过长风险。这个处理是必要的，因为原先如果把 socket 放到深层 `runs/.../work/...` 路径下，很容易接近或超过 Unix domain socket 路径长度限制。

后续保留要求：

- 所有脚本化 benchmark 都继续使用 `/tmp/sb2-*.sock` 短路径。
- 如果未来需要把 socket 放进 runtime root，必须先做长度检查并在超限时 fail fast。

### 2.3 Stage 时间线

| Stage | Required | Exit | 耗时 | 作用 |
|---|---:|---:|---:|---|
| `00_env_probe` | 1 | 0 | 0s | 记录分支、commit、API/env、CUDA/local embedding 能力 |
| `01_py_compile` | 1 | 0 | 0s | 编译 v2 关键模块 |
| `02_pytest_focused_v2` | 1 | 0 | 383s | 跑 focused v2 tests |
| `03_runtime_smoke` | 1 | 0 | 36s | 跑 runtime smoke |
| `r01_04_preflight_api_local` | 1 | 0 | 3s | 验证 API + local embedding 配置 |
| `r01_05_formal_api_local_memfd` | 1 | 0 | 866s | formal internal, API + local + memfd |
| `r01_06_formal_compare_api_local_memfd` | 1 | 0 | 122s | formal financial compare, API + local + memfd |
| `r01_07_dev_compare_api_local_memfd` | 0 | 0 | 51s | dev fixed-answer external compare |
| `r01_08_carrier_compare_api_local_memfd` | 0 | 0 | 55s | internal text vs structured carrier compare |
| `r01_09_continuous_api_local` | 0 | 0 | 1067s | continuous families |
| `r01_10_continuous_replay_api_local` | 0 | 0 | 1051s | continuous replay families |
| `r01_11_replay_negative_api_local` | 1 | 0 | 3s | replay negative audit |
| `r01_12_flagship_ablation_api_local` | 0 | 0 | 2737s | non-text state flagship ablation |

总 stage duration 求和为 6374 秒，约 1 小时 46 分 14 秒。

## 3. 环境与日志证据

`00_env_probe` 记录：

- branch：`feat/statebus-v2-container-runtime`
- commit：`ddb8c8d28873ffa457e0068486e2d44c77b94767`
- Python：`3.11.6`
- `STATEBUS_LLM_API_KEY=set`
- `STATEBUS_LLM_CONFIG_FILE=/workspace/statebus/project/deploy/statebus_llm.yaml.local`
- `STATEBUS_LLM_ENV_FILE=/workspace/statebus/project/deploy/statebus_llm.env.local`
- `STATEBUS_EMBED_DEVICE=cuda:0`
- `CUDA_VISIBLE_DEVICES=0`
- `torch_cuda_available=true`
- `sentence_transformers_present=true`
- `torch_version=2.5.1+cu121`

`preflight` JSON 记录：

- `preflight_ok=True`
- local embedding model：`/statebus/models/Qwen3-Embedding-0.6B`
- device：`cuda:0`
- LLM config：`/workspace/statebus/project/deploy/statebus_llm.yaml.local`

日志噪声：

- `TRANSFORMERS_CACHE` FutureWarning。
- `langgraph.checkpoint` deprecation warning。

没有看到：

- AF_UNIX path too long。
- stage-level traceback。
- required stage failure。
- memfd fallback。

## 4. formal internal 实现路径与证据

### 4.1 formal internal 走的是 registry 全量 formal samples

`v2/benchmark/live_runner.py` 对 `--benchmark-tier formal` 且 suite 不是 `compare` 的路径，使用：

```text
load_registered_formal_samples()
run_minimal_benchmark_suite(...)
```

本轮 `r01_05_formal_api_local_memfd` 的 formal registry 为：

| Family | Reasoning type | Expected cases |
|---|---|---:|
| `financial_report_analysis_v1` | `single_metric_extraction` | 8 |
| `multi_period_trend_analysis_v1` | `multi_period_trend` | 5 |
| `cross_table_join_analysis_v1` | `cross_table_relation` | 5 |
| `conditional_aggregation_v1` | `conditional_aggregation` | 4 |
| `anomaly_detection_v1` | `anomaly_detection` | 3 |

合计 5 families / 25 cases。

### 4.2 关键指标

`r01_05_formal_api_local_memfd`：

- `L3_case_count=25`
- `L3_quality_pass_count=25`
- `family_count=5`
- `state_pool_mode_requested=memfd`
- `state_pool_mode_used=memfd`
- `memfd_transfer_count=25`
- `memfd_publish_count=25`
- `memfd_bytes_transferred=247076`
- `semantic_state_transfer_count=25`
- API role calls：
  - `planner_call_count=25`
  - `retriever_call_count=25`
  - `executor_call_count=25`
  - `summarizer_call_count=25`

### 4.3 可支持的 claim

这部分可以强 claim：

- API + local embedding + memfd StatePool 下，formal internal 25/25 通过。
- 覆盖 5 个 formal families。
- 四角色 API 调用真实发生，每个 role 25 次。
- memfd 正路径真实发生，25 次 publish / transfer。

不能从这一部分直接 claim：

- external superiority。
- openEuler VM validated。
- end-to-end speed superiority。
- hidden-state / KV transfer。

## 5. formal compare 实现路径与问题

### 5.1 formal compare 不是 25-case registry compare

这是最容易误读的地方。

`v2/benchmark/live_runner.py` 当前逻辑是：

- formal tier 且 suite 不是 `compare`：使用 registered formal samples。
- formal tier 且 suite 是 `compare`：fall through 到 fixed-answer compare 路径。

代码注释也说明：

```text
formal + compare: fall through to the dev compare path below,
using load_fixed_answer_family
```

而默认 formal family dir 是：

```text
v2/benchmark/samples/formal_financial_family
```

因此本轮 `r01_06_formal_compare_api_local_memfd` 实际比较的是：

- formal financial family。
- 8 个 fixed-answer 样本。
- 不是 formal registry 的 25 个样本。

这不是执行错误，但必须在文档和 claim 中明确标注，否则会把 25-case internal 证据误说成 25-case external compare 证据。

### 5.2 formal compare 指标

`r01_06_formal_compare_api_local_memfd` exit 0，但关键字段如下：

- `fixed_answer_external_comparison_valid=False`
- `api_comparison_valid=0`
- `invalid_reason=quality_floor_gate_failed`
- `formal_headline_eligible=False`
- `formal_superiority_claim_allowed=True`
- `formal_efficiency_claim_allowed=True`
- `external_comparator_claim_scope=formal_financial_family`
- `state_pool_mode_used=memfd`
- `memfd_transfer_count=8`

debug metrics：

- case count：8
- StateBus quality floor pass：8
- external quality floor pass：5
- quality floor delta：+3
- route exact delta：0
- tool exact delta：0
- exact match delta：0
- LLM total tokens delta：-734
- prompt bytes delta：-10902
- control bytes delta：+917
- task ms delta：+36239.201

fairness manifest：

- `pass_hard_gate=true`
- `external_fairness_gate_coverage=true`
- `external_fairness_gate_pass_count=8`
- `external_fairness_gate_failed_case_count=0`
- `no_external_contamination=true`
- `same_role_graph=true`
- `same_task_family=true`
- `same_quality_floor_contract=true`
- `same_scoring_contract=true`

### 5.3 矛盾字段的根因

`v2/benchmark/comparator_runner.py` 里存在两套语义。

第一套语义在 `_headline_metrics()`：

```text
if not statebus_report.eligible_for_headline or not external_report.eligible_for_headline:
    return {}, "quality_floor_gate_failed"
```

这意味着只要 external 有 case 没过 quality floor，`comparison_valid` 就会变成 false：

```text
comparison_valid = not mode_missing_reason and not invalid_reason
```

第二套语义在 suite metadata 的 `formal_superiority_claim_allowed`：

```text
Path A: formal tier + no missing + fairness hard gate pass
        + StateBus eligible + quality_floor_pass_delta > 0
```

这个 Path A 故意不要求 external eligible，因为 external 失败本身被视为 StateBus 质量优势证据。

所以结果就变成：

- strict equal-quality headline comparison：失败。
- quality superiority signal：成功。
- 但报告字段没有把这两者拆开，导致同一份报告同时说 invalid 和 claim allowed。

这不是简单的阈值 bug，而是指标模型设计 bug。

## 6. external 失败样本拆解

external 失败不是因为 route/tool 选错，也不是 fairness gate 失败。三个失败样本全部表现为：

- route exact：1
- tool exact：1
- selected doc hashes exact：1
- summary present：1
- fairness gate pass：1
- revenue exact：0
- admissible match：0

| Task | 期望指标 | expected `revenue_value` | external 结构化 `revenue_value` | external 摘要 | 失败点 |
|---|---|---:|---:|---|---|
| `benchmark-sample-7` | `operating_income` | 19 | 120 | 写到了 operating_income = 19 | 结构化字段填成 revenue |
| `benchmark-sample-6` | `gross_margin` | 39 | 132 | 写到了 gross_margin = 39 | 结构化字段填成 revenue |
| `benchmark-sample-8` | `gross_margin` | 31 | 87 | 写到了 gross_margin = 31 | 结构化字段填成 revenue |

以 `benchmark-sample-7` 为例：

样本定义：

```json
{
  "task_id": "benchmark-sample-7",
  "expected_facts": {
    "revenue_value": "19"
  },
  "canonical_task_spec": {
    "arguments": {
      "metric": "operating_income"
    }
  }
}
```

external report：

```text
Retriever evidence summary: operating income of 19; revenue was 120
Executor artifact: {"revenue_value":"120", ...}
Summarizer output: Report the operating_income value for ACME 2026Q1: 19.
```

StateBus output：

```json
{
  "revenue_value": "19",
  "summary_text": "... Operating income was 19."
}
```

结论：

external 模型其实看到了正确事实，summary 也写对了，但结构化输出字段 `revenue_value` 被固定理解成表里的 `revenue`，没有按 `canonical_task_spec.arguments.metric` 映射到 `operating_income` 或 `gross_margin`。scorer 又只看 `expected_facts.revenue_value`，因此判错。

### 6.1 实现层面的具体位置

`v2/benchmark/external_text_baseline.py` 中 `_load_execution_context()` 已经会根据 metric 取正确值：

```text
row.metric_name == canonical_task_spec.arguments["metric"]
```

但正式打分时，external baseline 使用的是 LLM Retriever 返回的 `revenue_value`：

```text
llm_revenue_value = retriever_payload.get("revenue_value", ...)
observed_revenue_value = llm_revenue_value
```

代码注释明确说明不回退到 corpus preload，目的是防止 external baseline 没真实抽取事实却看起来正确。这条原则本身是合理的。

真正的问题是 prompt/schema 仍然要求字段名叫 `revenue_value`，但样本已经不只问 revenue：

- revenue case：`revenue_value` 字段语义刚好正确。
- operating_income case：`revenue_value` 字段名误导 external。
- gross_margin case：`revenue_value` 字段名误导 external。

所以这里不能简单开启 fallback，否则会污染 external baseline 的真实性；应该修 schema 和 prompt，让 external 必须输出“请求 metric 对应的 value”。

## 7. 为什么之前修复不成功

之前修复不成功不是因为单点代码没改对，而是三个问题叠在一起。

### 7.1 Gate 语义混用

`comparison_valid` 原本表达的是：

```text
双方都通过 quality floor，才可以输出 headline efficiency metrics。
```

新加的 `formal_superiority_claim_allowed` 表达的是：

```text
如果 StateBus 通过所有 case，external 没通过所有 case，而且 fairness gate 通过，那么可以作为质量优势信号。
```

这两个判断都合理，但必须是两个不同字段。现在强塞到同一个报告里，就会出现：

```text
comparison_valid=false
formal_superiority_claim_allowed=true
formal_headline_eligible=false
```

这会让任何后续文档生成、claim gate、人工审计都困惑。

### 7.2 formal internal 和 formal compare 覆盖面不一致

internal：

```text
25 cases / 5 families
```

compare：

```text
8 cases / 1 formal financial family
```

如果修复只盯 compare gate，最后仍然只能 claim `formal_financial_family_8case_compare`，不能 claim `25case formal registry external compare`。

### 7.3 external baseline 输出 schema 对非 revenue metric 不友好

formal financial family 里的部分样本问的是 `gross_margin` 或 `operating_income`，但 fixed-answer scorer 仍使用 `expected_facts.revenue_value`。StateBus 内部路径能把它映射对，external pure-text 路径容易按字段名抽 revenue。

因此 external 5/8 不是公平性失败，而是 schema/prompt 对 metric 语义表达不清。这个问题不解决，formal compare 很难稳定。

## 8. 其他结果拆解

### 8.1 Dev compare

`r01_07_dev_compare_api_local_memfd`：

- `fixed_answer_external_comparison_valid=True`
- `api_comparison_valid=1`
- StateBus quality floor：3
- external quality floor：3
- LLM total tokens delta：-986
- prompt bytes delta：-5082
- control bytes delta：-305
- task ms delta：+13546.113

解读：

- dev fixed-answer compare 是有效比较。
- 可以说 StateBus 在该 dev compare 中 tokens/prompt/control bytes 更少。
- 不能说端到端速度更快，因为 task time 更慢约 13.5 秒。

### 8.2 Carrier compare

`r01_08_carrier_compare_api_local_memfd`：

- valid mode count：1
- quality delta：0
- llm total tokens delta：-286
- llm prompt bytes delta：-1922
- task ms delta：-5288.337

解读：

- 这是同一 mainline 内部 text carrier vs structured carrier 比较。
- 可以支持内部 attribution：structured carrier 减少 prompt scaffolding / prompt bytes。
- 不能把它包装成 external superiority。

### 8.3 Continuous replay

`r01_10_continuous_replay_api_local`：

- family count：3
- continuous rounds：30
- replay target rounds：20
- replay observed rounds：20
- replay missing target rounds：0
- validated replay count：17
- validated downgraded reuse count：17
- exact replay count：3
- answer restoration replay count：0
- L2 semantic state transfer count：30
- L3 reuse gain：20

解读：

- replay/reuse 路径是本轮强证据。
- `answer_restoration_replay_count=0` 是正确边界，避免把 exact replay 误包装成 generic answer restoration。
- 仍然不能说已有完整 persisted live history artifact 审计，只能说本轮 continuous replay suite 目标 replay 20/20 observed。

### 8.4 Replay negative audit

`r01_11_replay_negative_api_local`：

- `audit_pass=True`
- `case_count=7`

解读：

- 负向 replay audit 通过。
- 它验证的是构造的 negative checks，不等于覆盖所有真实历史 replay 场景。

### 8.5 Flagship ablation

`r01_12_flagship_ablation_api_local`：

- stress family count：6
- stress pass family count：4
- total LLM prompt saved by StateRef bytes：22079
- total prompt visible saved by StateRef bytes：8514

失败/不满足 stress pass 的 family：

- `long_doc_metric_replay_v1`
- `incident_diagnosis_v2`

解读：

- 可以 claim：flagship ablation 跑通，并在 4/6 stress families 上显示 non-text state transfer / StateRef prompt saving。
- 不能 claim：所有 stress family 通过。
- 不能 claim：KV cache 或 hidden-state transfer，因为报告自身 claim boundary 也明确不是 KV/hidden-state。

## 9. 问题清单与优先级

### P0：拆分 compare claim gate 语义

当前问题：

```text
comparison_valid=false
formal_headline_eligible=false
formal_superiority_claim_allowed=true
```

这组字段不能继续原样用于文档生成或 claim upgrade。

建议修法：

新增明确字段：

- `strict_equal_quality_comparison_valid`
- `quality_superiority_comparison_valid`
- `formal_quality_superiority_claim_allowed`
- `formal_efficiency_superiority_claim_allowed`
- `formal_external_claim_allowed`
- `formal_external_claim_kind`

建议语义：

```text
strict_equal_quality_comparison_valid:
  fairness hard gate pass
  and no missing
  and StateBus quality pass all cases
  and external quality pass all cases
  and headline metrics emitted

quality_superiority_comparison_valid:
  benchmark_tier == formal
  and fairness hard gate pass
  and no missing
  and StateBus quality pass all cases
  and quality_floor_pass_delta > 0
  and external comparator scope is explicitly named

formal_efficiency_superiority_claim_allowed:
  strict_equal_quality_comparison_valid
  and llm_total_tokens_delta < 0
  and prompt_bytes_delta < 0

formal_quality_superiority_claim_allowed:
  quality_superiority_comparison_valid
```

对旧字段的处理：

- 保留 `comparison_valid`，但定义为 legacy strict valid，或改名后保留兼容字段。
- `fixed_answer_external_comparison_valid` 不应该再暗示所有 formal external claim 都无效；它只能表示 strict equal-quality compare 是否有效。
- `claim_restriction` 文案要区分：
  - fairness failed
  - strict quality floor failed
  - quality superiority valid but not strict equal-quality efficiency compare
  - dev-only scope

验收标准：

- formal quality superiority case 不再同时输出含糊的 `comparison_valid=false` 和笼统 `formal_superiority_claim_allowed=true`。
- markdown report 中明确写出：
  - strict equal-quality compare：invalid，原因 external quality floor failed。
  - quality superiority compare：valid，StateBus 8/8 vs external 5/8。
  - scope：formal financial family 8-case，不是 full formal registry。

测试建议：

- 新增或扩展 `tests/v2/test_compare_diagnostics.py`。
- 构造 external 5/8、StateBus 8/8、fairness pass 的 fixture。
- 断言：
  - `strict_equal_quality_comparison_valid == False`
  - `quality_superiority_comparison_valid == True`
  - `formal_quality_superiority_claim_allowed == True`
  - `formal_efficiency_superiority_claim_allowed == False`
  - `claim_restriction` 不是 fairness gate failed 文案。

### P0：修正 formal compare 覆盖面标注

当前问题：

- formal internal 是 25/5。
- formal compare 是 8/1。
- 报告里只写 `formal_financial_family`，还不够醒目。

建议修法：

- 在 `live_runner` compare payload 里输出：
  - `formal_compare_sample_source`
  - `formal_compare_family_count`
  - `formal_compare_case_count`
  - `formal_compare_registry_case_count`
  - `formal_compare_scope_label`

例如：

```json
{
  "formal_compare_scope_label": "formal_financial_family_8case_compare",
  "formal_compare_case_count": 8,
  "formal_registry_case_count": 25,
  "formal_compare_full_registry_coverage": false
}
```

验收标准：

- 任何 summary/doc generator 不会把 formal compare 误写成 full 25-case registry compare。
- `formal_superiority_claim_allowed` 如果保留，必须带 scope label。

### P1：实现 registry-backed formal external compare

当前缺口：

即使 P0 修好，formal external compare 仍然只有 financial 8 cases。要支持更强 claim，需要跑 full formal registry 的 external compare。

建议方案：

1. 新增 suite 或参数：

```text
--suite compare --benchmark-tier formal --formal-compare-source registry
```

或新增：

```text
--suite formal-compare-registry
```

2. 对 `load_registered_formal_samples()` 返回的样本建立 external baseline 支持。

3. 确认每个 formal family 是否都有：

- `canonical_task_spec`
- `expected_route`
- `expected_tool_name`
- `expected_facts`
- external baseline 可见候选集合
- pure-text prompt schema
- shared scorer

4. 如果部分 family 不适合 fixed-answer external baseline，必须显式输出 unsupported family，而不是静默降级。

验收标准：

- full registry compare payload 输出 25 cases / 5 families。
- unsupported family count 为 0，或报告明确列出 unsupported reason。
- compare scope 变成：

```text
formal_registry_25case_5family_compare
```

### P1：修 external baseline 的 metric schema

当前问题：

字段名 `revenue_value` 被复用为“任何 metric 的答案值”。这对 StateBus 内部路径可控，但对 external pure-text baseline 明显有误导。

建议修法：

1. 在 sample schema 中逐步引入更准确字段：

```json
{
  "expected_facts": {
    "metric_value": "39",
    "metric_name": "gross_margin",
    "selected_doc_hashes": [...]
  }
}
```

2. 保留 `revenue_value` 作为兼容字段，但 scorer 优先读：

```text
expected_facts.metric_value
```

3. external retriever prompt 改成：

```text
Return JSON with: route, tool_name, evidence_summary, metric_name, metric_value, selected_doc_hashes.
The metric_value must correspond to canonical_task_spec.arguments.metric.
```

4. executor artifact 改成：

```json
{
  "metric_name": "gross_margin",
  "metric_value": "39"
}
```

5. scorer 输出指标也改名：

- `metric_value_exact`
- `metric_name_exact`

同时临时保留：

- `revenue_exact`

用于老报告兼容。

不要做的修法：

- 不要简单开启 corpus fallback，把 `observed_revenue_value` 回退到 `context.revenue_value`。那会让 external baseline 即使没有真实抽取事实，也能被判正确，破坏公平性。

验收标准：

- `benchmark-sample-7/6/8` external 如果 summary 和 retriever 输出正确 metric value，应通过 quality floor。
- 如果 retriever 仍输出 revenue 而非 requested metric，应继续失败。
- fairness gate 不受影响，仍要求 no typed state / no metadata leakage / LLM-only decisions。

### P1：增加 per-case compare diagnostics

当前问题：

本轮定位 external 失败样本需要手工 jq 多个嵌套 report。后续每次跑完都应该自动生成失败样本表。

建议新增工具：

```text
tools/v2_compare_failure_diagnostics.py
```

输入：

```text
benchmark_reports/*compare-api.json
```

输出：

- failed cases table。
- StateBus/external per-case metrics。
- fail reason。
- expected vs observed structured fields。
- external role payload snippets。
- output artifact path。

也可以先集成到 `scripts/run_v2_local_api_comprehensive_stats.sh` 的 summary 生成段。

验收标准：

- `summary.md` 自动列出 external failed cases。
- 每条 case 能看到 route/tool/doc/metric/value 哪个维度失败。

### P2：flagship stress 失败 family 单独拆解

当前问题：

flagship ablation 4/6 pass，失败 family 是：

- `long_doc_metric_replay_v1`
- `incident_diagnosis_v2`

建议后续单独跑这两个 family 的 focused ablation，并输出：

- quality floor 失败还是 replay/headline 不 eligible。
- L2 vs T2 的 prompt saving 是否为负。
- semantic selection 是否已经主导收益。
- 是否因为 family 不适合 non-text transfer stress criterion。

验收标准：

- 不能只写 4/6；要知道 2 个失败 family 是实现问题、任务特性问题，还是 stress gate 定义问题。

### P2：环境与脚本硬化

建议保留和增强：

- `short_socket_path()` 长度检查。
- optional env 只在非空时传入，避免清空 container 内 key。
- 每个 stage 独立 runtime/workspace。
- JSON valid check。

建议新增：

- 在 summary 中记录每个 socket path 长度。
- 如果 activation 失败，明确记录实际 Python path 和 package versions。
- 把 `TRANSFORMERS_CACHE` warning 改为 `HF_HOME`，减少日志噪声。

## 10. 推荐修复顺序

### 第 1 步：先修 compare 语义，不碰 external baseline 行为

目标：

- 让报告字段不再自相矛盾。
- 明确 strict equal-quality vs quality-superiority。

原因：

- 这是当前最影响文档和 claim gate 的问题。
- 不改变 benchmark 行为，风险最低。

### 第 2 步：补 formal compare scope 元数据

目标：

- 明确当前 compare 是 8-case formal financial family。
- 防止误写成 25-case formal registry external compare。

原因：

- 这一步也是报告/metadata 层修复，不改变 benchmark 结果。

### 第 3 步：修 metric schema 和 external prompt

目标：

- 把 `revenue_value` 泛化成 `metric_value`。
- 让 external baseline 对 operating income / gross margin 这类 case 不再被字段名误导。

原因：

- 这一步会改变 external 质量结果，需要测试更谨慎。

### 第 4 步：做 registry-backed formal compare

目标：

- external compare 覆盖 25 cases / 5 families。

原因：

- 这是更大范围的 benchmark 扩展，应该在前面字段和 schema 稳定之后做。

### 第 5 步：重跑 local+api 全面测试

建议运行：

```bash
STATEBUS_LOCAL_API_RUN_FLAGSHIP=1 bash scripts/run_v2_local_api_comprehensive_stats.sh
```

如果要做正式 timing 证据：

```bash
STATEBUS_LOCAL_API_REPEAT=3 STATEBUS_LOCAL_API_RUN_FLAGSHIP=1 bash scripts/run_v2_local_api_comprehensive_stats.sh
```

注意：

- API latency claim 必须用 serialized rerun，不要用并发 API 启动结果当正式速度证据。
- 即使 repeat=3，也要分别报告均值/方差和每轮失败样本。

## 11. 修复后的 claim 目标

修完 P0/P1 后，理想 claim 应该这样分层：

### 可以强 claim

- formal internal API+local+memfd：25/25, 5 families。
- formal financial compare 8-case：如果 quality superiority gate valid，可 claim 在该 scope 下 StateBus quality floor 8/8 vs external 5/8 或修后新结果。
- continuous replay API+local：20/20 target replay observed，17 validated replay，3 exact replay，answer restoration 为 0。
- memfd StatePool 正路径：formal internal 25 publish/transfer。

### 只能限定 claim

- prompt/token saving：只在对应 compare/ablation scope 内 claim。
- flagship ablation：当前只能说 4/6 stress families pass。
- carrier compare：内部 text vs structured attribution，不是 external superiority。

### 仍不能 claim

- openEuler VM validation。
- nsjail / Docker production sandbox validated。
- hidden-state / KV transfer。
- end-to-end speed superiority。
- full 25-case formal external compare，除非新增 registry-backed compare 并跑通。

## 12. 本轮最重要的定位结论

1. 本轮 local+api 执行成功，基础环境和 formal internal 证据强。
2. formal compare 的问题不是 stage 失败，而是 claim gate 语义混用。
3. formal compare 当前只覆盖 8 个 financial formal fixed-answer samples，不是 25-case registry compare。
4. external 失败样本集中在 metric-value 字段语义：summary 答对，但结构化 `revenue_value` 填成 revenue，而期望是 operating income / gross margin。
5. 下一轮修复必须先拆字段语义，再修 external metric schema，最后再扩大到 registry-backed compare。


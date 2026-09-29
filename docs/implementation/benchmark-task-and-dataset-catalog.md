# 任务与样本目录

任务定义与 benchmark 样本分属两个目录：

- tasks/ 保存 task manifest、公开输入和 validator；
- src/statebus/benchmark/samples/ 保存可复用 fixture、gold、compiled input 和 utility sample。

## 当前任务入口

| 范围 | 入口 | 用途 |
| --- | --- | --- |
| contest mainline | src/statebus/benchmark/contest_dsl_taskpack.py、contest_dsl_mainline.py | finance 12 轮 + service_ops 12 轮；SB-FULL/P-TEXT 两种 variant |
| Memory / State mechanism | src/statebus/benchmark/contest_mechanisms.py、memory_ablation.py | 16 个 Memory + 8 个 State 计划位置 |
| formal task manifests | tasks/formal/*/task_manifest.yaml | formal task contract 和 validator |
| semantic holdout | src/statebus/benchmark/samples/semantic_holdout/ | State mechanism 的 holdout 输入和 gold |
| model-assist utility | src/statebus/benchmark/samples/model_assist_utility_v1/ | APC、KV、Logit 的 28 位置 long-text suite |
| explicit KV fixtures | src/statebus/benchmark/samples/engine_local_kv_continuation/ | parent prompt、compiled cases 和 connector 输入 |
| prefix fixture | src/statebus/benchmark/samples/continuous_task_families/kv_prefix_reuse/ | engine-local prefix layout 和 corpus identity 探针 |

## 主链 taskpack

主链 runner 由 taskpack 选择 family、轮次和输入 lineage。12 轮是每个 family 的 runner 参数；SB-FULL 和 P-TEXT 各自运行 finance 与 service_ops 两个 family，因此精选 evidence 的 task 分母为 48。

入口：

~~~text
src/statebus/benchmark/contest_dsl_taskpack.py
src/statebus/benchmark/contest_dsl_mainline.py
scripts/run_contest_dsl_mainchains.sh
~~~

## 机制和 utility 样本

机制 runner 的 Memory 和 State 位置使用各自的 manifest、history 和 quality gate。当前机制结果见 [`tests/evidence/mechanisms/`](../../tests/evidence/mechanisms/)，24 个位置均通过质量门；原始运行仍保留用于审计。质量门用于任务输出有效性，不等于 State 生命周期或业务收益。

utility sample 的计分位置由 model_assist_utility/taskpack.py 的 PLAN_POSITIONS 生成：APC 8、KV 8、Logit 12。warmup 和 calibration 不计入 28 个位置。

## Gold、validator 和结果

任务质量由 task-specific validator、JSON contract、Artifact verification 和当前 quality gate 共同决定。精选五件结果文件：

- tests/evidence/mainline/tasks.jsonl、tasks.csv、results.json；
- tests/evidence/mechanisms/results.json、tasks.jsonl、tasks.csv；
- tests/evidence/model-assist/metrics.json、report.md。

不要从历史 report 的任务数量反推当前 checkout；需要追溯历史运行时，沿精选结果的 raw run ID 进入 `runs/`。

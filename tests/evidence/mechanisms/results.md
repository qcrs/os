# 当前 Memory / State 机制结果

本报告覆盖 24 个计划位置：16 个 Memory 位置和 8 个 State 位置。

## 总体结果

| 指标 | 结果 |
| --- | ---: |
| planned | 24 |
| started | 24 |
| passed | 24 |
| quality pass rate | 24/24 (1.000) |
| status counts | `success=24` |

`quality pass rate` 是任务输出质量门的通过率，用于判断任务结果是否可计入；它不等同于 Memory 或 State 的业务收益。机制事件单独按下表报告。

## Memory

| family | variant | started / passed | provider requests | provider tokens | task e2e sum (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| finance | off | 4 / 4 | 9 | 16,886 | 332,444.389 |
| finance | on | 4 / 4 | 6 | 9,527 | 236,734.899 |
| service_ops | off | 4 / 4 | 9 | 14,580 | 217,736.053 |
| service_ops | on | 4 / 4 | 6 | 8,054 | 164,239.112 |

8 个 Memory-on 位置中，4 个观察到 validated replay consumption；candidate hit、actual consumption 和 validated replay 是不同事件，不能合并成单一命中率。

逐任务 off/on 对照：

| task | quality | provider tokens off -> on | requests off -> on | e2e ms off -> on |
| --- | --- | ---: | ---: | ---: |
| F01 | 通过 -> 通过 | 3,402 -> 3,402 | 2 -> 2 | 83,185 -> 72,666 |
| F02 | 通过 -> 通过 | 3,411 -> 1,339 | 2 -> 1 | 74,098 -> 44,264 |
| F06 | 通过 -> 通过 | 3,427 -> 3,427 | 2 -> 2 | 75,534 -> 74,315 |
| F07 | 通过 -> 通过 | 6,646 -> 1,359 | 3 -> 1 | 99,627 -> 45,490 |
| O01 | 通过 -> 通过 | 2,934 -> 2,934 | 2 -> 2 | 51,395 -> 50,275 |
| O02 | 通过 -> 通过 | 2,949 -> 1,083 | 2 -> 1 | 51,292 -> 31,330 |
| O06 | 通过 -> 通过 | 2,940 -> 2,940 | 2 -> 2 | 52,086 -> 50,516 |
| O07 | 通过 -> 通过 | 5,757 -> 1,097 | 3 -> 1 | 62,963 -> 32,119 |

## State

| variant | started / passed | provider requests | provider tokens | task e2e sum (ms) |
| --- | ---: | ---: | ---: | ---: |
| off | 4 / 4 | 21 | 42,035 | 614,486.355 |
| on | 4 / 4 | 21 | 42,235 | 593,435.187 |

| task | off | on | on publish | on transfer | on consume | on release | on behavioral effect |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| semantic-holdout-s1 | success | success | 2 | 2 | 2 | true | `changed` |
| semantic-holdout-s5 | success | success | 3 | 3 | 3 | true | `no_effect` |
| semantic-holdout-s4 | success | success | 2 | 2 | 2 | true | `no_effect` |
| semantic-holdout-s8 | success | success | 3 | 3 | 3 | true | `no_effect` |

State-on 的 4 个位置均观察到 `publish`、`transfer`、`consume` 和 `release`；总计各 10 次，逻辑 payload/read bytes 均为 221,184。`behavioral_effect` 是运行时观测字段，不单独构成业务收益证明。

`semantic-holdout-s1` 的 on 记录来自最新单独重跑 `runs/smoke-mechanisms-live-20260928_174645-3579687`，状态为 `success`，不是早期的 `quality_fail` 记录；其 `publish=2`、`transfer=2`、`consume=2`、`release=true`、`behavioral_effect=changed`。

## 边界与文件

- `provider tokens` 是模型服务用量，不是 Agent 间通信 token。
- 本报告不推断 `wire_bytes`、`typed_bytes` 或对象边界 serialization bytes。
- `tasks.jsonl` 和 `tasks.csv` 提供逐位置记录；`results.json` 提供机器可读聚合；`manifest.json` 提供来源追溯。

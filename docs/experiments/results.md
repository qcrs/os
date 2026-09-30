# 实验结果详表

本页收录实验的任务、对照、分母和逐组结果。结果来自 `tests/evidence/` 的精选文件，raw run 用于查看单个任务的完整运行记录。

## 结果分组

| 实验 | 任务和分母 | 对照 | 主要指标 |
| --- | --- | --- | --- |
| 主实验 | `finance` F01–F12、`service_ops` O01–O12；24 对、48 次执行 | `SB-FULL` / `P-TEXT` | 质量、requests、provider tokens、Executor generation、repair、E2E、carrier |
| Memory | F01/F02/F06/F07、O01/O02/O06/O07；16 个位置 | `off` / `on` | candidate、actual consumption、validated replay、Executor boundary skip、requests、tokens、E2E |
| State | `semantic-holdout-s1/s5/s4/s8`；8 个位置 | `off` / `on` | publish、transfer、consume、release、payload/read bytes、behavioral effect |
| APC | 4 个长文本 case；8 个位置 | `apc_on_independent` / `apc_on_shared` | query/hit counters、hit tokens、consumer TTFT、task wall |
| 显式 KV | 4 个长文本 case；8 个位置 | `full_replay` / `continuation` | inherited/computed prefill、TTFT、store/load、request wall、task wall |
| Logit | 4 个候选选择 case；12 个位置 | `full_context_once` / `compact_once` / `logit_selective` | probability、action、expanded、logical input、最终选择、`abstention` |

## 主实验：`SB-FULL` 与 `P-TEXT`

来源：[`tests/evidence/mainline/`](../../tests/evidence/mainline/)。采集日期为 `2026-09-27`。

`finance` 和 `service_ops` 各执行 12 轮。每轮在两个配置下各执行一次，形成 24 个匹配任务对。

| 指标 | `SB-FULL` | `P-TEXT` | `SB-FULL` 相对变化 |
| --- | ---: | ---: | ---: |
| 质量通过 | 24/24 | 24/24 | 保持 |
| provider requests | 41 | 60 | **降低 31.67%** |
| provider prompt tokens | 60,544 | 103,534 | **降低 41.52%** |
| provider completion tokens | 13,636 | 18,168 | **降低 24.94%** |
| provider total tokens | 74,180 | 121,702 | **降低 39.05%** |
| Executor generations | 17 | 36 | **降低 52.78%** |
| Executor repairs | 5 | 12 | **降低 58.33%** |
| 24 个任务总耗时 | 1,543.3 s | 2,043.4 s | **降低 24.47%** |
| Agent carrier | 89 条 typed object | 108 条 UTF-8 JSON text | **消息数降低 17.59%** |
| UTF-8 text carrier bytes | — | 780,825 | — |

按任务类别汇总：

| 类别 | `SB-FULL` provider tokens | `P-TEXT` provider tokens | tokens 变化 | `SB-FULL` E2E | `P-TEXT` E2E | E2E 变化 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `finance` | 44,968 | 75,275 | **降低 40.26%** | 927.1 s | 1,266.4 s | **降低 26.79%** |
| `service_ops` | 29,212 | 46,427 | **降低 37.09%** | 616.2 s | 777.0 s | **降低 20.69%** |

主实验记录的消息、State 和 Memory 字段如下：

| 数据类别 | 采集结果 |
| --- | --- |
| 消息 | 197 条消息；89 条 typed object，108 条 UTF-8 JSON text |
| State | `publish/transfer/consume/release=24/24/24/24`；逻辑 payload/read bytes `491,520/491,520` |
| Memory 查询 | 24 次查询，22 次返回候选，共 132 个候选 |
| Memory 消费 | 12 次 actual consumption，12 次 validated replay，14 次 consumption event，2 次跨角色消费 |
| Executor boundary | 12 次记录 skipped Executor generation |

## Memory：检索到复用

来源：[`tests/evidence/mechanisms/`](../../tests/evidence/mechanisms/)。Memory 使用 8 个任务，每个任务运行 `off/on`，共 16 个位置。

### 汇总对比

| 指标 | `off` | `on` | `on` 相对变化 |
| --- | ---: | ---: | ---: |
| 质量通过 | 8/8 | 8/8 | 保持 |
| provider requests | 18 | 12 | **降低 33.33%** |
| provider tokens | 31,466 | 17,581 | **降低 44.12%** |
| 任务耗时总和 | 550.2 s | 401.0 s | **降低 27.12%** |
| repair | 2 | 0 | **降低 100%** |

### 复用漏斗

| Memory 事件 | 位置数 | 占 `on` 位置 |
| --- | ---: | ---: |
| candidate hit | 6 | 6/8 |
| actual consumption | 4 | 4/8 |
| validated replay | 4 | 4/8 |
| skipped Executor boundary | 4 | 4/8 |

### 逐任务对比

| task | 质量 | provider tokens `off → on` | requests `off → on` | E2E `off → on` |
| --- | --- | ---: | ---: | ---: |
| F01 | 通过 → 通过 | 3,402 → 3,402 | 2 → 2 | 83,185 → 72,666 ms |
| F02 | 通过 → 通过 | 3,411 → 1,339（**降低 60.74%**） | 2 → 1（**降低 50%**） | 74,098 → 44,264 ms（**降低 40.26%**） |
| F06 | 通过 → 通过 | 3,427 → 3,427 | 2 → 2 | 75,534 → 74,315 ms |
| F07 | 通过 → 通过 | 6,646 → 1,359（**降低 79.55%**） | 3 → 1（**降低 66.67%**） | 99,627 → 45,490 ms（**降低 54.34%**） |
| O01 | 通过 → 通过 | 2,934 → 2,934 | 2 → 2 | 51,395 → 50,275 ms |
| O02 | 通过 → 通过 | 2,949 → 1,083（**降低 63.28%**） | 2 → 1（**降低 50%**） | 51,292 → 31,330 ms（**降低 38.92%**） |
| O06 | 通过 → 通过 | 2,940 → 2,940 | 2 → 2 | 52,086 → 50,516 ms |
| O07 | 通过 → 通过 | 5,757 → 1,097（**降低 80.95%**） | 3 → 1（**降低 66.67%**） | 62,963 → 32,119 ms（**降低 48.99%**） |

## State：状态传递和下游选择

State 使用 4 个 semantic holdout，每个任务运行 `off/on`，共 8 个位置。State-on 的 4 个位置全部记录了 publish、transfer、consume 和 release。

### 汇总对比

| 指标 | `off` | `on` | `on` 相对变化 |
| --- | ---: | ---: | ---: |
| 质量通过 | 4/4 | 4/4 | 保持 |
| provider requests | 21 | 21 | 保持 |
| provider tokens | 42,035 | 42,235 | 增加 0.48% |
| 任务耗时总和 | 614.5 s | 593.4 s | **降低 3.43%** |
| publish / transfer / consume | 0 / 0 / 0 | 10 / 10 / 10 | on 侧全部发生 |
| release | 0/4 | 4/4 | on 侧全部释放 |
| 逻辑 payload/read bytes | 0 | 221,184 | on 侧全部记录 |

### 四个 holdout

| task | `off` | `on` | publish / transfer / consume | release | behavioral effect |
| --- | --- | --- | ---: | --- | --- |
| `semantic-holdout-s1` | success | success | 2 / 2 / 2 | true | **changed** |
| `semantic-holdout-s5` | success | success | 3 / 3 / 3 | true | `no_effect` |
| `semantic-holdout-s4` | success | success | 2 / 2 / 2 | true | `no_effect` |
| `semantic-holdout-s8` | success | success | 3 / 3 / 3 | true | `no_effect` |

`semantic-holdout-s1` 使用最新的单独重跑记录 `smoke-mechanisms-live-20260928_174645-3579687`。

## APC：公共前缀复用

APC 使用 `MU-ORION-4K-COST`、`MU-ORION-6K-COST`、`MU-NOVA-4K-DELIVERY`、`MU-NOVA-6K-DELIVERY` 四个 case。每个 case 比较 `apc_on_independent` 与 `apc_on_shared`，共 8 个位置。

| 指标 | independent | shared | shared 相对变化 |
| --- | ---: | ---: | ---: |
| 质量通过 | 4/4 | 4/4 | 保持 |
| query/hit 计数窗口 | 4 个 case | 4 个 case | 共享布局全部采集 |
| observed hit tokens | 48 | 5,168 | 增加 10,666.67% |
| consumer TTFT | 2,540.2 ms | 264.3 ms | **降低 89.59%** |
| 完整 task wall | 基线 | — | **降低 4.29%** |

采集字段包括 query/hit counter、prefix identity、shared prefix layout、consumer TTFT、request wall、完整 task wall、vLLM service identity、cache epoch 和质量结果。

## 显式 KV：继续使用已计算状态

KV 使用同一组四个长文本 case。每个 case 比较 `full_replay` 与 `continuation`，共 8 个位置。

| 指标 | `full_replay` | `continuation` | continuation 相对变化 |
| --- | ---: | ---: | ---: |
| 质量通过 | 4/4 | 4/4 | 保持 |
| inherited KV tokens | 0 | 继承 parent KV | continuation 路径全部发生 |
| computed prefill | 5,666.5 | 545.5 | **降低 90.37%** |
| consumer TTFT | 2,570.6 ms | 1,005.7 ms | **降低 60.88%** |
| consumer request wall | 基线 | — | **降低 11.88%** |
| 完整 task wall | 基线 | — | **降低 3.58%** |
| store / load 平均时间 | — | 2,986.4 / 749.0 ms | continuation 资源成本 |

采集字段包括 parent token digest、inherited/computed prefill、capture/store/load/release、实际 KV bytes、scheduler proof、Worker forward proof、consumer TTFT、request wall、task wall 和 registry cleanup。

## Logit：按候选概率展开证据

Logit 使用 4 个固定候选选择 case，每个 case 执行 `full_context_once`、`compact_once`、`logit_selective`，共 12 个位置。

| 指标 | `full_context_once` | `compact_once` | `logit_selective` |
| --- | ---: | ---: | ---: |
| 计分位置 | 4 | 4 | 4 |
| exact candidate probability | 逐位置记录 top-logprobs | 逐位置记录 top-logprobs | 逐位置记录 top-logprobs；`tau=0.10`、`other_mass_limit=0.20` |
| action | full context | compact context | probability-guided selective |
| expanded | 按固定 full context 执行 | 不展开额外 evidence | 按 exact candidate probability 决定是否展开 |
| logical input | 基线 | resolved case 平均减少 75.21% | resolved case 平均减少 75.21% |
| provider request wall | 基线 | **降低 17.18%** | **降低 18.51%** |

套件总结果为 9 个 resolved case 通过、3 个正确 `abstention`。每个位置同时记录 exact candidate probability、最终 action、是否 expanded、selected candidate 和最终选择或 `abstention`。

每个位置还记录 availability、entropy/top-gap、sequence length、logical input tokens、repair 和 validator 结果。

## 结果入口

| 结果 | 精选文件 | raw run |
| --- | --- | --- |
| 主实验 | [`tests/evidence/mainline/results.json`](../../tests/evidence/mainline/results.json)、`tasks.jsonl` | `runs/contest39-sbfull-all-20260927_101009-1987732`、`runs/contest39-ptext-all-20260927_101009-1987732` |
| Memory / State | [`tests/evidence/mechanisms/results.json`](../../tests/evidence/mechanisms/results.json)、`tasks.jsonl`、`manifest.json` | `runs/contest-mechanisms-20260927_171109-3234416`；S1 最新 on 为 `runs/smoke-mechanisms-live-20260928_174645-3579687` |
| APC / KV / Logit | [`tests/evidence/model-assist/metrics.json`](../../tests/evidence/model-assist/metrics.json)、[`summary.md`](../../tests/evidence/model-assist/summary.md) | formal run `longtext-demo-v3-20260929_104844-2545919` |

汇总命令：

```bash
python tests/evidence/summarize_results.py
python tests/evidence/summarize_results.py --json
```

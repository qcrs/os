# Contest Stage 1 Implementation and Smoke

日期：2026-09-24。范围：35 号 prompt，遵循 34 号方案的基础子集。

## 状态与边界

本轮实现 F01→F02、O01→O02，各含 SB-FULL / P-TEXT；不是完整 G0/G1、20 个任务或正式 40 次矩阵。
第三批完整八项的数值/风险/实体引用机器门通过 6/8，其中 SB 两条链均通过；P-TEXT 随后进行了两批独立定向修复复核，结果见下文。
各批代码和提示不同，不能拼成一次冻结实验；机器门通过也不等于自然语言叙述完整性已经得到验证。
最新第五批 P-TEXT 两条链 4/4 通过，两个首轮无需修复，两个次轮各一次代码修复；四份报告均包含各实体当前背景。
已证实 SB 的合法 Memory 消费、新输入重执行和代码生成 skip；尚未证明产品整体加速或同边界通信节省，暂不进入正式扩量。

- 修改只在 `os/`；保留原有 dirty changes，未操作 `project/`，未 commit/push。
- 复用现有健康 vLLM 和 `statebus-runtime`；没有重启、重建、改变挂载/GPU 映射或干预无关进程。
- 数据是固定 seed `20260924` 的 synthetic development 数据，不能作为真实业务外部有效性或正式性能成绩。
- 所有原始证据位于 `runs/contest-stage1-dev-20260924/`，下文相对路径均以 `os/` 为基准。

## 实现

| 文件 | 职责 |
| --- | --- |
| `statebus/benchmark/contest_stage1_taskpack.py` | 四任务、逐轮公开原始文件、类型转换和公开元数据绑定，不聚合答案 |
| `statebus/benchmark/contest_stage1_scorer.py` | 独立 Decimal scorer，从公开原始 CSV / SLO / 段落检查数值及来源 |
| `statebus/benchmark/contest_stage1_report.py` | 统一实体、risk、risk_change 和本轮引用检查；不是通用自然语言 entailment 判定器 |
| `statebus/benchmark/contest_stage1_text.py` | 四个真实模型角色、文本交接、同类受限 Python 工具，无 Memory / StateRef |
| `statebus/benchmark/contest_stage1.py` | 八次串行开发 runner、独立链状态、历史输入、watchdog、终态和失败账本 |
| `statebus/benchmark/request_journal.py` | provider-boundary started/finished 持久日志、实际 messages/raw response/usage 和失败成本 |
| `statebus/benchmark/adaptive_formal*.py` | 新业务 operation / Runtime 重算，复用 canonical `adaptive_bounded` caller；可选 scorer、报告门和交接观察 |
| `statebus/runtime/llm_codeact.py`, `adaptive_dispatcher.py` | 将最终验证通过的 source 交给 recipe，核验 execution-record source hash |

财务每月 24 行、运营每周 672 行，均为四个实体；第二轮绑定当前及已公开前轮原始数据，共 48 / 1344 行。
`is_current`、section locator 和公开 SLO 只作为输入元数据，不包含预计算业务答案。未来文件保留在 sealed 目录，不进入角色输入或 sandbox。
两配置收到相同公开要求、原始数据权限和本配置已执行历史；前轮失败只传失败状态，不注入 gold 或另一配置的结果。
P-TEXT 的文件工具同样解析 CSV、关联公开 SLO，不要求模型心算或重复粘贴整份 CSV；Agent 之间实际传递文本。
其中 Planner/ Retriever 交接是 prose，Executor→Summarizer 是完整 UTF-8 JSON 表格文本，最终输出也使用 JSON Schema 约束。
这是普通工具结果的文本传递，没有 StateBus typed control frame、隐藏 StateRef 或共享 Memory；并非所有交接都写成自然语言，不能直接充当 34 §10.4 的纯 prose/typed 隔离对照。

SB 继续使用既有 Plan/Grant、artifact verification、Memory admission/consumption、非 root bwrap、质量重算及 ClaimSet 验证。
未改 authority、ownership 或 sandbox contract。四角色是逻辑分工，不声称两配置都有四个独立常驻 Agent 进程：
SB 的 planner/retriever/summarizer 经隔离 role worker 调用，生成代码的请求在任务 worker 中；P-TEXT 四角色在一个任务 worker 内串行请求。
semantic state consumer 是另一个进程，实际 PID 见 receipt；provider journal 的 started 事件记录实际调用 PID。

## 环境

| 项目 | 本轮实际值 |
| --- | --- |
| 源码 | `/home/qcrs/statebus/os`，branch `contest-core-repair-20260921_000126`，已有未提交改动 |
| 容器 | `statebus-runtime`，`statebus-dev-openeuler:24.03-lts-sp3-embed`，openEuler 24.03 LTS-SP3，host network |
| 挂载 / import | host 工作区 → `/workspace/statebus`；`/workspace/statebus/os/statebus/__init__.py` |
| live 解释器 | `/usr/bin/python3`，Python 3.11.6；helper 前言的 3.11.15 是另一 Conda 解释器，不作 live 平台证据 |
| vLLM | `http://127.0.0.1:53334/v1`，`/data/models/Qwen3-32B`，served name `qwen3-32b` |
| 实际 profile | 物理 GPU2，BF16，TP=1，context=8192，max-num-seqs=1，max-num-batched-tokens=8192，util=0.82，eager，prefix caching |
| 服务身份 | API 主 PID 3393459，worker PID 3394540，原服务仍在；不是本轮重新启动 |
| embedding | 同一容器 `/statebus/models/Qwen3-Embedding-0.6B`，第二批起显式 `--embedding-device cpu`；P-TEXT 不调用 embedding |
| embedding 原因 | `/usr/bin/python3` 加载 PyTorch `2.5.1+cpu`，`/usr/local/lib64/python3.11/site-packages/torch`，CUDA 不可用；不是 GPU embedding 验证 |
| sandbox | bwrap 0.8.0，uid/gid 65534；实际 readiness probes 通过，不仅检查二进制存在 |
| Host 测试 | `source deploy/activate_statebus_host.sh`，`conda-envs/statebus_host` |

GPU1/GPU2 有共享任务，不是独占计时。CPU 参数由 runner 传到实际 retrieval adapter，并记入每任务 `execution-environment.json`；
没有借助宿主 export 覆盖 helper 的 `cuda:0`，也没有修改共享 deployment 配置。CPU 探针实际编码 1024 维。
服务健康及实际进程参数已检查；服务启动时间不在本轮链成本中，因为未启动服务。每任务初始化、embedding 加载、建库、失败和 repair 均在外层 E2E 内。

证据：`environment-preflight.txt`、`embedding-cpu-preflight.txt`、`sandbox-preflight-verified.txt`、`initial-git-status.txt`、`initial-working-tree.patch`。
旧 `sandbox-preflight.txt` 是权限不可见时的失败记录，不作为成功证明。

## 修复与取舍

1. **环境不匹配**：第一批四次 SB retrieval 均因 CPU-only torch 与 `cuda:0` 冲突失败。
   第二批起显式使用 CPU；相同解释器与模型探针、后续真实消费验证。代价是不能声称复现了 GPU embedding profile 或冻结性能环境。
2. **操作语义不明确**：首轮 risk_change、numeric JSON 字段和 SLO 来源曾导致生成/repair 失败。
   在两配置共用的公开 operation 中明确 `initial/new/resolved/still_risk/still_clear`、未舍入阈值、直接读取数字和逐实体 SLO。
   Runtime 仍独立重算，外部 scorer 负控拒绝旧答案、错数值和错来源；没有把 gold 写进 prompt。
3. **检索/报告漏检**：第二批出现把 prose corpus 当 table 的计划，以及数值正确但引用标题/别的实体、缺风险变化的报告。
   对这两个 operation 增加明确计划约束和现有 Planner repair，统一报告合同与实体级证据检查。
   这份文档只有七段，第三批 `top_k=7` 确保完整覆盖；不宣称裁剪收益，不伪造或替模型修改引用。
4. **Memory 保存错误源码**：第二批 O01 经两次 repair 通过，但 commit_registry 保存了最初失败的源码。
   O02 replay 旧源码触发 repair，最终请求超出 context8192（7640 prompt + 2200 completion = 9840），失败成本保留。
   现将 `accepted_source` 仅在验证成功后返回，dispatcher 校验其 hash 并保存最终源码。
   回归覆盖 repaired recipe 与 artifact source_hash 一致，以及同源码在 fresh input/new grant 下执行、禁止再次 generation。
5. **重复输入与成本遗漏风险**：第三批历史统一只追加一次；CodeAct repair 不再重复附整套已在原 prompt 中的合同。
   不压低 max_tokens。日志在 started/finally finished 时 flush/fsync，失败 usage 为 null，并另保留已观察的 partial usage。
   runner 预置完整分母；失败/timeout 写机器可读终态，只终止自己创建的进程组。
6. **Baseline 角色职责和输出结构**：第三批财务报告出现错误 risk/缩短 locator，第四批进一步暴露 summary 数组与原始小时行未聚合。
   先明确 Retriever/Executor/Summarizer 分工，再为 Summarizer 传入现有 provider 支持的 JSON Schema，约束四行表和 string summary；
   Executor 明确按 entity + is_current 累加全部原始行，质量反馈指出行数或重算错误。
   这些约束来自公开任务，不含 gold，不替模型改答案、不增加 repair 次数。第四、五批分别保留，不能把提示改动等同于稳定性或性能改善。

32 号之前已有的 telemetry、Memory 兼容性及 numeric 指导改动保留，未重复作为本轮新增成果。
没有为了预期速度优势删除 validator、sandbox、重新计算或 Memory 授权。当前样本和边界不足以支持缓存/并发等更大优化，故不做。

## 离线验证

| 范围 | 结果 | 日志 |
| --- | --- | --- |
| Host：Stage1、formal compare、adaptive integration、hybrid Memory、Memory ablation | 123 passed | `host-final-regression.txt` |
| openEuler `/usr/bin/python3`：CodeAct integration / policy / sandbox | 48 passed | `codeact-repaired-recipe-regression.txt` |
| openEuler：repaired source fresh-input 无生成重执行 | 1 passed | `repaired-source-new-input.txt` |
| 最后 typed 引用正文规则及 Stage1 回归 | 13 passed | `report-gate-final-regression.txt` |
| P-TEXT 角色分工、Executor 有效预算覆盖及 Stage1 回归 | 15 passed | `text-role-budget-after-fix.txt` |
| 当前版本：报告 JSON Schema、summary 类型、原始行聚合反馈及 Stage1 回归 | 15 passed | `report-schema-after-fix.txt` |

这些是不同范围/时点的回归，不相加冒充独立测试总量。仅基础子集离线通过，不扩展为完整 G0/G1。
宿主受限 socket 环境曾导致 semantic consumer 测试失败，获准宿主权限后同测试及完整相关回归通过；保留原失败记录。

## Live 结果

### 第三批完整八项

`live-v3` 全部终态，数值/风险/实体引用机器门 6/8 通过、2/8 失败、0 timeout；服务端 usage 全部已返回。
SB 两条连续链和 P-TEXT 运营链通过该门，P-TEXT 财务两轮数值正确但报告不合格。
人工检查还发现 SB F02/O01/O02 的正文没有完整复述各实体背景，只有部分背景留在 `uncertainty_note` 中。
因此以下 pass 不代表公开任务中的背景叙述要求全部满足；本门不验证通用 entailment、因果措辞或背景完整性，正式扩量前仍须补齐这一质量维度。

| 任务 | 配置 | 最终 | E2E s | 请求数 | Prompt tokens | Completion tokens | Code / report 追加请求 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| F01 | SB-FULL | pass | 187.169 | 5 | 10227 | 2133 | 0 / 0 |
| F02 | SB-FULL | pass | 122.989 | 4 | 9479 | 1251 | 0 / 0 |
| F01 | P-TEXT | fail | 210.193 | 5 | 5632 | 2733 | 0 / 1 |
| F02 | P-TEXT | fail | 216.096 | 5 | 6045 | 2835 | 0 / 1 |
| O01 | SB-FULL | pass | 326.651 | 8 | 17247 | 3666 | 1 / 2 |
| O02 | SB-FULL | pass | 201.102 | 5 | 13411 | 1920 | 0 / 0；另有 1 次 Planner repair |
| O01 | P-TEXT | pass | 146.936 | 4 | 4241 | 2286 | 0 / 0 |
| O02 | P-TEXT | pass | 152.574 | 4 | 5986 | 2162 | 0 / 0 |

整批 1563.743s、40 次 **provider 请求**（不是 40 个正式业务任务）、72268 prompt + 18986 completion = 91254 tokens。
整链 E2E：财务 SB 310.163s / P-TEXT 426.290s；运营 SB 527.757s / P-TEXT 299.511s。
财务 P 两项失败，不能拿该链差值作为同等质量加速。运营这一次 SB 更慢且 tokens 更多，不能宣称整套产品加速。

首次与最终分开：P-TEXT 两个财务报告各重试一次仍失败，F01 将 U-B 风险写反且 locator 缺文件名，F02 缺完整 locator。
O01 SB 首次代码 `syntax_error:3`，repair 后执行成功；两个 report batch 首次都漏 `risk=`，各重试一次后通过。
O02 SB 初始 normalized plan 带不支持的 `completion_criteria.max_conflicts`，一次 Planner repair 后通过。
其余四项没有追加模型 repair，最终通过；`live-v3-audit.json` 中 `first_pass_no_repair=4` **仅表示不追加模型请求**。
四个 SB 初始 raw plan 都不是原样准入：沿用既有 controller-owned step/ref/dependency/schema normalization 后再审查。
其中 F01/F02/O01 无需再次请求模型，不能将它们说成 raw Plan 零修正通过；P-TEXT prose planner 没有同一个 raw Plan gate。

第三批交接观测如下。字段边界不同，**不计算百分比节省或总通信优劣**：

| 任务 | SB callback 投影：消息 / 字符 / UTF-8 bytes | P-TEXT 实际交接：消息 / 字符 / UTF-8 bytes |
| --- | --- | --- |
| F01 | 7 / 9460 / 9460 | 6 / 6230 / 6230 |
| F02 | 5 / 6086 / 6086 | 6 / 7108 / 7114 |
| O01 | 13 / 17059 / 17059 | 4 / 5983 / 5983 |
| O02 | 5 / 6225 / 6225 | 4 / 5381 / 5381 |

第三批 provider 调用区间合计与外层 E2E：SB F01 148.233/187.169s，F02 90.482/122.989s，
O01 284.961/326.651s，O02 155.605/201.102s。剩余部分包含初始化、CPU embedding、子进程/验证等未完全拆分工作，不能统称协议开销。

### Baseline 定向修复复核

第三批结束后才修改 P-TEXT 角色提示，没有边跑同一批边改实现。
原 baseline Retriever 把全局报告要求当成自己的输出任务，生成未计算的 risk/示例 ID；Summarizer 照搬错误文字。
新增角色级指令，明确 Retriever 只提供背景、风险/ID/change/完整 locator 以已验证 Executor 表为准，报告 repair 也明确回到该表。
不自动改模型输出、不删报告门，不增加 repair 次数，不压低 max_tokens。
同时统一 executor 环境覆盖的配置来源，避免 dry-run 显示覆盖值但实际仍用固定 2200；本次默认仍为 2200。
两个领域的离线流程回归及预算检查共 15 passed（`text-role-budget-after-fix.txt`）；修复前对应失败记录也保留。

`live-v4-text` 是全新独立链的四项 P-TEXT 复核，不重新执行 SB，不与 `live-v3` 拼成一次八项冻结成绩。
仅 F02 通过，1/4 通过、3/4 失败、0 timeout：角色提示单独修正不足以解决 baseline 问题。

| 任务 | 最终 | E2E s | 请求数 | Prompt tokens | Completion tokens | 失败原因 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| F01 | fail | 208.687 | 5 | 6033 | 2709 | 数值/风险正确，但两次 summary 均为数组且缺完整 locator |
| F02 | pass | 157.180 | 4 | 4278 | 2033 | 首次通过；前轮历史仍为 failed/无输出，没有补 gold |
| O01 | fail | 144.583 | 4 | 4542 | 1865 | 两次代码输出 672 个原始小时行，未按站点聚合 |
| O02 | fail | 186.188 | 5 | 6689 | 2417 | 先 KeyError request_id，修复后只保留末小时，质量 repair 后仍错 |

整批 696.661s、18 requests、21542 prompt + 9024 completion = 30566 tokens；
财务链 365.869s，运营链 330.774s。工具失败也保留 `tool-events.jsonl`、`failure.json` 和完整 provider 成本。

第五批前根据上述直接错误增加报告 schema 与聚合反馈，并用两个领域的离线流程回归验证：错误工具行数会进入 bounded quality repair；
summary 数组/缺 locator 会进入 bounded report repair；verified table 和真实重传交接均保留；schema 确实传到 provider caller。
`live-v5-text` 是这次修改后的四项独立 P-TEXT 链，不增加 SB 样本，也不与前批合并为产品性能对比。

| 任务 | 最终 | E2E s | 请求数 | Prompt tokens | Completion tokens | 追加修复 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| F01 | pass | 174.534 | 4 | 4461 | 2278 | 无 |
| F02 | pass | 222.368 | 5 | 9186 | 2887 | 一次 runtime repair：分组字典初始化漏 key |
| O01 | pass | 154.368 | 4 | 4079 | 2015 | 无 |
| O02 | pass | 212.586 | 5 | 8499 | 2747 | 一次 policy repair：误读未授权 CSV 路径 |

第五批 4/4 通过、0 timeout，四份报告均首次通过；首次完整任务无需 repair 为 2/4。
F02 的 `KeyError: net_revenue_cny` 和 O02 的 `unapproved_path:service_ops/hourly_W01.csv` 都在既定一次修复预算内解决，
没有放宽 sandbox；后者在执行前被拒，改为读取已授权的当前及前轮合并 JSON 后重新执行。
整批 763.870s、18 requests、26225 prompt + 9927 completion = 36152 tokens；
财务链 396.902s，运营链 366.957s。与第四批相比质量改善，但耗时及 tokens 并未减少，不能称性能优化。

事后只读联合复核确认：两次轮的 history 与本配置首轮结果完全对应，全部真实角色输入包含该历史；
财务 24→48、运营 672→1344 行实际进入工具，次轮输出与首轮不同；逐轮公开源文件 hash 与第三批一致。
四任务再次通过独立原始 CSV scorer 和实体引用门，四份 summary 都包含四个原始 note/event 背景事实。
JSON Schema 确实存在于真实 summarizer 请求中；工具最终都经 uid 65534 的 bwrap 成功执行。
这只验证当前四个开发样本，不构成稳定性保证，也不为通用自然语言正确性背书。

第五批 P-TEXT 的真实交接消息数/字符/UTF-8 bytes：F01 `4/4630/4638`、F02 `5/5423/5431`、
O01 `4/4475/4475`、O02 `5/4898/4898`；代码 repair 的 evidence 重传计入，交接 tokens 仍为未观测。
联合核对结果及各批成本见 `final-batches-audit.json`，不覆写原始结果。

### 修复前批次

| 批次 | 计划任务 | 原质量门通过 | Provider requests | 服务端 total tokens | 整批 E2E s |
| --- | ---: | ---: | ---: | --- | ---: |
| `live-v1` | 8 | 2 | 25 | 42753 | 874.591 |
| `live-v2` | 8 | 6 | 33 | null；已观察 partial 73476 | 1182.489 |

以上原质量门未完整验证业务报告，**2/8 和 6/8 不是完整业务通过率**。
第一批四项 SB 环境失败；P-TEXT F01/O01 生成或 bounded repair 失败，F02/O02 原数值门通过。
第二批 SB F01 prose/table retrieval 失败，O02 保存旧源码后的 repair 超出 context；
SB F02 报告四个实体都引用标题 `ctx-section-1`，O01 部分实体引用别的站点且缺风险变化，不能保留为完整成功。
P-TEXT 四项第二批通过的是原检查，不追溯套用第三批新输出格式来计算成功率。

`earlier-batches-audit.json` 是从原 provider journal 生成的补充审计，没有覆写任何原 ledger/result。
第二批 O02 的 3 次请求中，前两次实际观察到 5512 tokens；400 请求没有 usage，故不把总量补零。
此前诊断包括 CPU embedding、sandbox readiness 和离线测试，单列相应日志，不充作 F/O 业务任务或额外成功样本。
第一批六个失败任务只有 ledger/failure/log 而无独立 `result.json`，审计明确标记 `result_file_present=false`；
当前 runner 已补失败终态 result，第二至第五批每项均有该文件，未回填或修饰旧证据。

### 全部开发运行成本，不作为合并性能成绩

共 **32 个开发业务任务、134 次 provider requests**：三批各 8 项，加两批各 4 项；不是正式 40 次矩阵。
五批 E2E 分别为 874.591 / 1182.489 / 1563.743 / 696.661 / 763.870s，合计 5081.353s（约 84.689 分钟）。
该合计包含所有批内初始化、建库、失败与 repair，不包含批间编码、离线测试和预检时间，不能当作整个项目耗时。
完整 token 总数为 null；已观察 partial 为 211811 prompt + 62390 completion = **274201 tokens**，另有第二批一次 HTTP400 未返回 usage。
不合并不同质量门、提示版本的成功率，也不隐藏第四批 1/4 的失败复核成本。

### 当前 Memory / State 证据

`live-v3-memory-state-audit.json` 从四个 SB 结果、Memory registry 和 provider journal 做联合核对：

- 财务输入 24→48 行，运营 672→1344 行，producer/consumer 的输入与输出 hash 均不同。
- F02/O02 各有一条实际 `validated_replay` consumption：admission、当前 grant、attempt-result admission 均有 hash，
  `recipe_recomputed=true`、`recipe_step_status=skipped_generation`；二者实际 executor 请求数均为 0。
- F01 的最终源码和 F02 重执行源码 hash 都是 `02f5a569aff39cba1c05c95a3b8fb02104078a85e5ab1f65099dcdb2d8db2ffc`。
- O01 经语法 repair 后的最终源码、Memory recipe 与 O02 重执行源码 hash 都是
  `0047686ad584e03d1894b9ad064e329da92843c8f41b0da541aacb180435cc85`。这是本轮修复的真实新输入验证，不仅是离线 fixture。
- 当前 canonical 参数与 input lineage 改变时，兼容性给出 `degraded`，允许 validated recipe 重算；不是恢复旧数值的 exact replay。
- SB 冷轮有真实代码生成，warm 轮绕过该生成边界；但 Runtime receipt 的 `provider_boundary=not_observed`、
  `skipped_provider_call_count=0` 原样保留，provider 减少的依据另取本 caller 的真实请求日志，不能篡改 receipt 宣称其直接观察了 HTTP skip。
- 四次任务各发布/消费/回收 3 个 float32 `[8,1024]` semantic objects，每个 32768 bytes；共 12 个、393216 published bytes。
  每个 receipt 的 producer/consumer PID 不同，pin 最终为 0，physical reclaim 均完成。
  consumer read 小计 F01/F02/O01/O02 为 13.770/9.959/6.169/7.484 ms；这只是观测到的 read 区间，不含全部 embedding / hydration 开销。

F02 的 Memory lookup（含 compatibility）50.714 ms、授权/hydration 2.670 ms、commit 12.042 ms；
F01 的 lookup 1.095 ms、commit 11.350 ms。首轮建库都在链 E2E 内。
这些局部计时不能补齐尚未覆盖的 phase，也不支持删除授权等正确性检查。
累计 telemetry 中 `validated_replay_count` / `memory_behavioral_effect_count` 存在多阶段计数，报告采用消费记录基数，不把重复计数当作更多独立复用。

## 计量边界

- Provider：完整 started/finished、实际角色请求、服务端 prompt/completion/total tokens；未返回 usage 为 null，不当成零。
- P-TEXT：在实际接收方调用前记录传入的 planner/evidence/table 文本，repair 重传也计入；不是所有 HTTP prompt bytes。
- SB：`handoffs.jsonl` 记录实际 callback 输入投影（含 controller binding），`observed_callback_*` 不等于完整 Runtime IPC。
- `complete_agent_handoff_bytes`、`control_wire_bytes`、全局 wire bytes 和交接 token 数未观测，不估算为 provider usage，不将二进制 bytes 换算成 tokens。
- State：publication/access/consumer/downstream/reclaim receipts 可追溯，consumer 真实跨进程读取 float32 embedding 状态；不是 hidden-state / KV tensor transfer。
- Memory：使用 query、compatibility、admission、consumption、recipe source hash、当前输入重算及 executor 请求共同判断，不只看 hit/commit 或累计 telemetry 数值。
- 现有 `RUNTIME_PHASE_TIMING` 只覆盖部分 phase，可报告其耗时，但不能把已观测 phase 的和当作完整开销分解。
- 首次/最终质量根据生成尝试、tool/report events、batch repair_index 和最终 scorer 分开；SB 的两个正常 summarizer batch 不是两次 repair。

## 四项机制

| 机制 | 本阶段接线与证据 | 仍缺少 |
| --- | --- | --- |
| 结构化通信 | 同任务/同公开工具能力的 text 与 typed 产品路径；实际调用处记录交接 | 相同完整测量边界及隔离变量对照；不能算总通信节省 |
| 非文本状态 | semantic state 跨进程真实消费、响应准入和回收；七段全覆盖 | 较大检索集上的共同任务对照、选择集合与答案的收益；本轮没有裁剪收益证明 |
| Memory | 连续历史、validated recipe、新输入 sandbox 执行、当前质量验证 | 独立同任务 warm/cold 机制对照、跨 Agent 复用；跨任务不等于跨 Agent |
| CodeAct | 两产品路径都具备合法 bounded Python，失败、repair、最终验证可追溯 | 支持同一任务的合法非 CodeAct 路径；关闭后拒绝执行不算正确性提升证据 |

多输入 CodeAct、P95、schema/policy 改变等复杂链路径尚未覆盖。不能以基础两轮替代这些验证。

## 复现

以下命令从 host `/home/qcrs/statebus/os` 执行，live 使用现有容器的 `/usr/bin/python3`。
运行 smoke 会新增最多八次真实模型任务；**必须使用全新目录**，已有目录会拒绝覆盖。没有正式 40 次 CLI。

```bash
cd /home/qcrs/statebus/os
git status --short --branch
nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu --format=csv
nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv
docker ps -a --filter name=statebus
source ./deploy/activate_statebus_local_vllm_profile.sh qwen3-32b-gpu2-u050
export STATEBUS_VLLM_ENV_FILE=/home/qcrs/statebus/os/deploy/vllm.env.gpu2-32b-u050
scripts/vllm/manage_qwen3_32b.sh print-config
scripts/vllm/manage_qwen3_32b.sh status
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:53334/health
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:53334/v1/models
scripts/run_g6b2_os_container.sh inspect
scripts/run_g6b2_os_container.sh verify
scripts/run_g6b2_os_container.sh exec /usr/bin/python3 -c \
  'import sys, statebus; print(sys.executable); print(sys.version); print(statebus.__file__)'
```

本轮实际已执行的第三批入口如下；重跑时将 `live-v3` 改成未存在的新目录。
当前 checkout 已含后续 baseline 修复，重跑检验的是当前实现，不会恢复第三批旧代码/提示快照：

```bash
scripts/run_g6b2_os_container.sh exec /usr/bin/python3 \
  -m statebus.benchmark.contest_stage1 \
  --output-root /workspace/statebus/os/runs/contest-stage1-dev-20260924/live-v3 \
  --embedding-device cpu --dry-run

scripts/run_g6b2_os_container.sh exec /usr/bin/python3 \
  -m statebus.benchmark.contest_stage1 \
  --output-root /workspace/statebus/os/runs/contest-stage1-dev-20260924/live-v3 \
  --embedding-device cpu

jq '{planned_count,passed_count,e2e_ms,chains_ms,ledger}' \
  runs/contest-stage1-dev-20260924/live-v3/summary.json
```

第四、五批验证过仅 baseline 的 `--profile P-TEXT` 入口。当前代码的同类复核命令如下，
会产生四个业务任务；与上面的八项 smoke 二选一，不要为了查看结果重复启动：

```bash
RUN_NAME="stage1-text-$(date +%Y%m%d_%H%M%S)"
scripts/run_g6b2_os_container.sh exec /usr/bin/python3 \
  -m statebus.benchmark.contest_stage1 \
  --output-root "/workspace/statebus/os/runs/$RUN_NAME" \
  --profile P-TEXT --embedding-device cpu --dry-run
scripts/run_g6b2_os_container.sh exec /usr/bin/python3 \
  -m statebus.benchmark.contest_stage1 \
  --output-root "/workspace/statebus/os/runs/$RUN_NAME" \
  --profile P-TEXT --embedding-device cpu
jq '{planned_count,passed_count,e2e_ms,chains_ms,ledger}' "runs/$RUN_NAME/summary.json"
```

已有第五批只读查看：

```bash
jq '{planned_count,passed_count,e2e_ms,chains_ms,ledger}' \
  runs/contest-stage1-dev-20260924/live-v5-text/summary.json
jq '{ok,repairs,report_checks,summary_text,handoff_measurement}' \
  runs/contest-stage1-dev-20260924/live-v5-text/finance/P-TEXT/F02/result.json
```

有效预算由每任务 `effective-llm.yaml` / `effective-budget.json` 及 dry-run 共同记录：outer watchdog 1800s、
Runtime dispatch 400000ms、HTTP 90s、role worker 105s、provider max attempts 1、Python 30s；
policy/runtime/quality repair 各最多 1 次；planner/retriever/executor/summarizer max tokens 分别为 1024/1024/2200/4096。
role max_tokens 环境覆盖可在 dry-run 查看，不修改共享配置。SB report 的每 batch bounded retry 和既有 numeric/citation 验证继续保留。

```bash
source ./deploy/activate_statebus_host.sh
python -m pytest -q tests/measurement/test_contest_stage1.py \
  tests/test_adaptive_formal_compare.py tests/test_adaptive_mainline_integration.py \
  tests/test_hybrid_memory_query.py tests/measurement/test_memory_ablation.py

scripts/run_g6b2_os_container.sh exec /usr/bin/python3 -m pytest -q \
  tests/test_adaptive_codeact_integration.py tests/test_llm_codeact_policy.py \
  tests/test_llm_codeact_sandbox.py
```

第二条当前会包含新增的 fresh-input 测试；上述 48 + 1 的证据是在新增前整组、新增后单项取得，不能称已运行过合并后的 49 项命令。

## 下一阶段

先完善两配置报告的背景叙述质量检查和 bounded repair，避免把数值/引用门等同于完整业务质量；再扩展完整业务 taskpack/scorer 与逐轮发布，
多输入/P95/变更兼容性等离线负控，以及相同业务任务下的机制测量边界。Memory 先用同一 consumer 的合法 warm/cold 对照确认净收益，
不把首轮建库成本排除；CodeAct 先补共同支持的非 CodeAct 任务路径。最后冻结模型、embedding、共享条件、输入及预算，再由用户运行正式实验。
本阶段保留每批失败及修复成本，不再通过反复抽样挑选最好的一批；本轮没有启动正式 40 次矩阵或完整机制套件。

交付检查：`git diff --check` 通过，报告无待填占位；八个未参与本轮修改的已有 dirty 文件与初始 patch 完全一致。
共享的 dispatcher / CodeAct 文件仅追加本轮所需修复，原有改动保留；没有 commit、push 或清理工作树。

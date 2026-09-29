# Model-assist 长文本场景机制展示与执行设计 v3

初版：2026-09-28；本次修订：2026-09-29（Asia/Shanghai）。
状态：**设计已收敛，待实现和实际验证；本文不是新实验结果。** 本文是实施合同；表中的长度、优势和请求数是目标或预算，不是已观察结果。
交接对象：GPT-5.6 Sol，reasoning effort `max`。suite revision：`longtext-demo-v3`（设计版本；尚无 live run）。

本版取代初版 486 次方案：**只执行 28 个计分任务位置，每条件一次；不扩展大矩阵。** 用户已允许下一位实施 agent 在完成离线验证与安全 preflight 后直接执行这 28 次，不必再次停在“交脚本等待用户启动”。本次文档更新本身不启动服务或实验。

## 1. 定位：48 项主链是主证据，28 次是长文本旁路展示

主链口径：2 个配置（SB-FULL/P-TEXT）× 2 个 family（Finance/Service Ops）× 每条 12 轮 = 48 个执行槽；单个配置是 24 轮。参见 `docs/reports/contest39-mainchains-20260926.md` 和 `scripts/run_contest_dsl_mainchains.sh`。

- 原 48 项负责完整比赛业务链、跨轮历史与系统机制的主要证明，本轮不重跑、不改默认行为。
- 本 suite 展示**长共同证据场景**下的可选 provider 路径：APC 前缀复用、显式 KV 交接，以及 Logit 驱动的按需证据展开。
- 复用 canonical Runtime/Grant/DSL/Artifact/ClaimSet 和 provider 边界，不是脱离系统的纯模型微基准。
- 这不是原 48 项的新结果，不证明主链已获相同收益；本轮也不实现通用自动路由。展示中可称“长文本场景的显式可选路径”。

| 模块 | 固定展示安排 | 计分任务次数 |
|---|---|---:|
| APC | 4 个长文本 case × independent/shared 两布局 | 8 |
| KV | 同样 4 个 case × replay/continuation | 8 |
| Logit | 4 个代表案例 × compact_once/full_context_once/logit_selective | 12 |
| 合计 | 每条件 1 次，无默认重复 | **28** |

28 是任务执行位置，不是 28 份独立业务材料。没有统计显著性、p95/p99、整体成功率提升的泛化结论。保留逐项实际值、质量、失败、缺失和适用条件即可。

实施者按以下顺序做决策，不在 live 结果出来后重新选题：先冻结任务/Gold 与证据可见性，再用真实 tokenizer 编译长度和检查必要性，再实现关闭状态与 28 位置计划，最后做 targeted tests、当前环境 preflight 和 live。**优化的是机制适用场景，而不是筛选正向结果**：长而相同的授权证据、短输出、同一服务连续请求、固定预热；未获益 case 也留在报告。

| 问题 | 预定展示对象 | 对照条件 | 最先看的实际结果 |
|---|---|---|---|
| 同一授权长文给两个角色时，改变布局有无价值？ | APC-on 的 4k/6k dossier | 同内容 independent vs shared | Consumer 命中 token、TTFT，随后看完整 task wall |
| 显式传递已计算的前缀是否减少第二角色计算？ | APC-off 的同四题 | full_replay vs continuation | Consumer computed token、forward proof、TTFT，随后看 store/load 后的 task wall |
| 模型对证据选择的同次概率能否控制展开？ | 4 个冻结的证据路由题 | compact_once/full_context_once/logit_selective | 正确选择/正确拒绝、展开次数、请求数和 logical input token |

只有业务质量和权限合同通过，才讨论效率。APC 与 KV 不和原 48 项做时间对比；Logit 不宣称比未测的规则策略更好。

取消：2k 正式档、四类业务交叉、三次默认重复、APC-off 独立批次、Logit 大开发/确认集、阈值网格、rule_expand 条件、三机制组合矩阵。旧短前缀 F01/O01 报告只读保留为历史边界，不混入新计时比较。

## 2. 依据与时间预算

2026-09-28 的有限 formal `formal-20260928_224955-3234416` 已有 8 个业务/机制成功位置和 standard 恢复证据。这只能证明旧配置当时可运行；本次仍需当前 source/service preflight。

旧结果提示：KV 实际继承约 112 token，不能因 enabled 标签就期待明显收益；capture/store 与初始化也有成本。新展示使用真正需要的 4k/6k 共同证据，补齐 token identity、分段时间与 lifecycle 证据。

旧 8 项 e2e 合计约 459.39 秒，单项 26.38–92.42 秒，均值约 57.42 秒；来自旧报告四个 family/phase 的 task_results.json。按此估算 28 项任务本体约 27 分钟，**建议预留 45–90 分钟维护窗口**。不是新长文本耗时保证，也不含实施/调试时间。预热后更新估时，不承诺必然更快。

默认 scored 批次软预算 `5400s`：达到预算不再启动新 case 对/Logit 三策略组，当前请求按已设 timeout 结束，立即清理和恢复，记录 incomplete_budget。清理与恢复不受该软预算截断；无法完成时交付已有证据和续跑命令，不能装作 28 项已完成。

## 3. 实现范围与默认关闭

### 3.1 本地已有与待实现入口

2026-09-29 只读核对：下面前五项已存在；utility runner 尚未存在，不得把待实现 CLI 当成已验证命令。

| 入口 | 用途与边界 |
|---|---|
| `scripts/experiments/contest_model_assist/run_smoke_and_formal.sh` | 已有 F01/O01 小矩阵；借用身份检查、服务切换、恢复经验，不默认再跑旧 8 项 |
| `scripts/experiments/contest_model_assist/run_minimal_probe.py` | 已有小批业务/provider 探针与汇总参考 |
| `scripts/vllm/manage_qwen3_32b.sh` | host standard/KV 的 start/stop/status/health/print-config；由 ENV_FILE 选择模式 |
| `scripts/experiments/engine_local_kv/start_engine_local_kv_probe_service.sh` | manager 内部调用的 KV server launcher，不另起第二套服务 |
| `scripts/start_statebus.sh`、`scripts/run_g6b2_os_container.sh` | 现有一键准备/容器工具；有附加 smoke 和可能重建行为，不能当无副作用 health 命令 |
| `scripts/experiments/contest_model_assist/run_utility_suite.sh` | 待实现：新旁路 prepare/plan/28 次执行/清理恢复 |
| 同目录 `run_utility_suite.py`、`summarize_utility_suite.py` | 待实现：业务编排及只读结果汇总 |
| `statebus/benchmark/model_assist_utility/` | 待实现：少量任务、编译与 observer/policy 模块 |
| `statebus/benchmark/samples/model_assist_utility_v1/` | 待实现：受控公开素材/任务合同；Gold 独立隔离 |

不得为了复用旧 CLI 而把四个新 case 伪装成原 F01/O01。不要建设通用评测框架；只添加本轮必要能力。

### 3.2 关闭路径

- 新 case 不进入旧 TASKS、SIMPLE_PROFILE 或主链默认入口。旧 logit observation-only 行为不暗改。
- 专用 runner 显式设置进程内 `STATEBUS_MODEL_ASSIST_UTILITY_ENABLED=1`；不持久写部署 env。
- 新 CLI 默认仅显示计划。模型请求需 `--execute`，服务切换需 `--yes`；实施 agent 可按本轮授权显式使用它们。
- utility off/hook None 时，原 prompt/schema、请求数、预算、Memory、Validator、错误和重试语义保持。
- suite 内关闭 Memory lookup/commit 和 Python fallback；不改变主链的相应默认值。
- 不在 import 时访问服务、加载模型或创建报告目录。
- 不改 project/其他 worktree，不创建分支，不 reset/clean/switch/checkout/merge/rebase/cherry-pick/commit/push，保留已有修改。

## 4. APC/KV 的四个长文本业务 case

### 4.1 固定清单与完整业务

| case | 长度 | 业务 |
|---|---|---|
| MU-ORION-4K-COST | 4k | 样本 Q1/Q3 加急费用、异常与变化；解释范围及引用有效口径 |
| MU-NOVA-4K-DELIVERY | 4k | Q1/Q3 加权交付率及百分点变化；引用分母/有效范围规则 |
| MU-ORION-6K-COST | 6k | 同一类型业务，使用更大的有效证据集合 |
| MU-NOVA-6K-DELIVERY | 6k | 同一类型业务，使用更大的有效证据集合 |

不是 4k 与 6k 相互比较加速；只比较同一 case 的两种机制条件。不同长度的明细和答案可不同。Orion/Nova 本来就是仓库合成素材，新增账本也明确标为受控数据，不声称真实公司财报。

固定 seed `20260928`。只生成 Q1/Q3 的唯一、完整、有来源 locator 的运营记录，以及任务真正需要的范围/有效规则说明。按题保留 record_id/company/quarter/region/scope、费用/异常或 committed/on_time 字段；不为已取消的 REGION/CONTROL 任务建设额外任务或无用登记。

### 4.1a 任务模板与 Gold 合同

四题复用两种**完整业务模板**，不是四个只换长度的问答。原 `orion_factory_ops_report_2026.md` / `nova_retail_ops_report_2026.md`（参见第 13 节的旧 KV 样本目录）提供企业背景及引用上下文；新增 ledger 和生效规则是明确标注的受控样本事实，来源 locator 指向实际段落/行。原报告中的全公司指标和新增样本 cohort 指标不能混算。4k/6k 同模板但使用各自冻结的记录集合，不能把 4k 的 Gold 直接当 6k Gold。

| 模板 | 用户问题与最终字段 | Executor 必须从 dossier 决定 | 独立 Gold/validator |
|---|---|---|---|
| Orion cost | 统计获批样本范围内 2026Q1 与 Q3 的加急费用和异常数，给出 Q3-Q1 变化、covered_record_count 与造成变化的有效范围说明 | 按公司、季度、sample cohort、批准状态和规则生效期过滤，聚合 `expedited_fee_usd` 与 `exception_count`；不将原报告公司总费用当样本费用 | 独立 evaluator 从原始结构化 ledger 与规则计算 q1/q3 cost、delta、q1/q3 exceptions、行数；引用必须覆盖规则和至少一处实际明细 |
| Nova delivery | 计算获批样本 2026Q1 与 Q3 的加权准时交付率、百分点差、分子/分母与 covered_record_count，并解释适用范围 | 过滤同一有效 cohort，分别求 `sum(on_time_orders)`/`sum(committed_orders)`；不能平均各行百分比，不能代入原报告总体 OTD | 独立 evaluator 核对两季度分子/分母、率、百分点差、行数与规则/明细引用；允许明确的数值舍入容差 |

每份 ledger 至少有稳定 `record_id, company, quarter, region, scope, status, source_locator` 和模板所需数值字段；规则表至少有 `rule_id, effective_from, effective_to, eligible_scope, status_policy, source_locator`。记录 ID 唯一，source locator 可反查；规则在 dossier 中有少量需要辨别的历史/现行项，不能把已经解析好的最终筛选集合放进角色 suffix。可用的无效/取消项仅在业务需要辨别时出现，不能用大量无关行填长度。任务合同和 source manifest 固定 `case_id`、schema revision、seed、原报告摘要、受控生成说明、目标 cohort、输出字段与单位。Gold 文件仅供 evaluator，拒绝从 prompt、provider 参数或日志把答案泄漏给角色。建议 taskpack 分为 `sources/`（公开原报告、受控 ledger、规则）、`cases.json`（用户问题、可见 refs、预期字段）、`gold.json`（evaluator-only）、`manifest.json`（schema/seed/hash）；名字可按本地样式调整，但访问边界不可合并。

例如 Orion 用户问“获批样本 Q1/Q3 加急费用变化”，共同 dossier 包含费用明细和某条规则的有效日期；Executor suffix 只要求产出获批样本过滤与聚合程序，不能写“用这些 87 行、答案为 X”。Runtime 执行后 Summarizer suffix 才携带 verified Artifact ID/数值与短说明请求，要求回到同一获权 dossier 解释规则和给出定位引用。Nova 同理：规则决定可计入的 committed/on_time 行；验证器从原始行独立计算加权率，不接受引用公司整体 OTD 的貌似正确答案。

具体采样档位用**真实 tokenizer 编译结果**定案：4k 与 6k 各至少一个 Orion/Nova case；先按完整有效记录生成，再增减完整且参与要求计算的记录以进入第 4.2 节的 LCP 区间。无法达到区间或必要性检查失败就记 compile blocked，不能截掉答案相关尾部、复制同一事实或添加无用登记。输出字段数量和最大生成长度保持短，使 prefill/复用有机会成为可见成本；这只是展示合适场景，不保证 wall-time 收益。

长文本生成要求：

1. 每条新增有效明细都参与该 case 的要求计算；少量无效/取消项必须用于检验筛选规则。同一事实不复制填充。on_time 在 0 与 committed 之间。
2. 原报告整体指标与受控样本 ledger 分开 scope；交付率是 sum(on_time)/sum(committed)，不能平均行百分比。
3. early/middle/late 都有相关明细或规则。Gold 由独立 evaluator 算，不进入 prompt 或 provider 映射。
4. Executor 需要从共同 dossier 选择正确 scope/effective rule 并生成 DSL；不能把已解析的最终口径或答案全塞进 suffix。
5. Summarizer 需要从同一获权 dossier 找到限定条件、解释与 citations，不能只复制 suffix 中预填的引用答案。
6. 公开输出保持紧凑：4–8 个数值/标识字段、covered_record_count、2–3 个 citations，不生成长报告来掩盖 prefill 效果。

流程：Controller TaskSpec/Plan → Retriever 授权 refs → LLM Executor TransformProgram → Runtime 执行与 Artifact 验证 → LLM Summarizer ClaimSet → 业务 validator。Planner/Retriever 使用确定性现有能力；正常两次 generation。

不新增通用 DSL 算子。复用 filter/aggregate/derive/join/sort/select；必要的公开派生列不能预计算最终答案。最多一次 Executor repair，Summarizer 结构错误直接记失败，不无限重试。

### 4.2 长文本必要性和 token 门

离线 necessity-checks 至少覆盖：扰动 early/middle/late 相关记录改变要求输出；删除尾部改变 covered_record_count/总量；改口径或有效规则改变所需程序语义/合法 ClaimSet；citations 可定位。账本被 DSL 扫描并不自动证明模型需要长上下文，两个角色的规则/引用依赖须分别留证。

这些是 source/reference evaluator 检查，不伪称模型注意了每一段；live 还要验证实际程序、数字和引用。必要性检查必须同时证明：若去掉指定规则，Executor 的过滤/派生语义会改变；若去掉后段引用/限定，Summarizer 的 ClaimSet 会失去可验证依据。失败就改任务合同/公开素材并产生新 revision，不能只增加长度。我们展示专用长文审阅场景，不主张所有紧凑任务都该扩大 prompt，不宣称优于最优检索/压缩系统。

| 档位 | shared 最终消息真实 LCP | KV parent cap |
|---|---:|---:|
| 4k | 4096–4352 token | 4096 |
| 6k | 6144–6400 token | 6144 |

使用本地真实 tokenizer/chat template，计算最终消息 LCP、16-token block 对齐和实际 inherited。independent 布局记录其实际 LCP，不要求也达到 shared 目标。公共前缀只含角色获权交集；动态 task/run/attempt ID 放角色 suffix，不丢审计/Grant 身份。

通过增减完整唯一记录编译目标区间，不按字符估算或塞 padding。KV 物理切分可在记录中部，完整逻辑 prompt 不截断。无法进入目标区间则 compile failure，不能把 3k 标成 4k。

~~~text
Qwen3-32B BF16; TP=1; max_model_len=8192; max_num_seqs=1
max_num_batched_tokens=8192; temperature=0; seed=7; enable_thinking=false
Executor max_tokens=512; Summarizer max_tokens=384
role suffix 目标 <=768 token，含实际 schema/chat 开销
actual_prompt_tokens + requested_max_tokens + 64 <=8192
~~~

参数在同 case 条件间一致。预算不够就离线修订公开表达并重新编译，不只为某个条件压缩或临时扩大 context。

## 5. APC：8 次，展示共享布局的价值

只用一个 standard/APC-on 服务：`apc_on_independent`（role 在前、同一 dossier 在后）与 `apc_on_shared`（共同 dossier 在前、role 在后）。只移动同一公开内容，不删证据或权限合同。

固定两个角色**同一授权交集**的 dossier 字节和 chat-template 渲染；若某段只获权给一个角色，它不得进入 shared 前缀。shared 形式为 `stable system/template + shared dossier + role-specific suffix`；independent 形式为 `stable system/template + role-specific instruction + same dossier + task suffix`。动态 ID、Executor 程序/Artifact 和角色私有信息都在各自 suffix，Summarizer 不接收 Gold。两布局的逻辑输入、任务语义、schema、采样、最大输出和 validator 一致；只改变排列。逐请求保存 rendered token digest、两角色 LCP 和 role visibility，避免仅凭源文本相同误认缓存键相同。

按第 4.1 节顺序执行各 case 的两布局；case 1/3 independent-first，2/4 shared-first。每个布局内部 Executor→Summarizer，起点不预热正式证据，shared 的 Consumer 可复用 Producer 前缀。不在同一任务内插其他模型负载。

首选已实际验证有效的 cache reset，并且只在独占空闲窗口用。若当前版本不能核实 reset，使用显式受控 namespace 隔离：标识放在证据前、组内一致、条件间不同但等 token 长度，保存真实 LCP；披露共同模板背景命中，不能把 namespace 当业务内容或绝对零命中的保证。不为每 case 重载权重。

记录：token identity/visibility、query/hit delta、engine/cache epoch、Executor 冷请求、Consumer 请求、TTFT、request/task wall、input/output token、请求数、repair、业务质量。TTFT 是发起请求至第一个非空内容 token，不是响应头，也不是完整响应 wall；suite-only streaming observer 不改 schema/采样语义。

每个请求前后独占采 `/metrics`，使用现有 `vllm_metrics.py` 的匹配、单调 token counters；保存原始 `.prom` 和解析结果。主要对比同 case Consumer `observed_hit_token_delta`、`TTFT_ms`，并报告 `task_wall_ms`、Executor 冷请求、总输入/输出与 repair。`hit_rate=hits/queries` 只在 `queries>0` 且 delta_valid、同一 engine/cache epoch、无外部请求污染时算；服务 lifetime gauge 不得代替任务窗口。`TTFT improvement=(independent-shared)/independent`，仅两侧均有真实非零 TTFT 时显示；缺采标 unavailable，不填 0。若 shared 命中升高但整任务不快，应写“前缀命中/Consumer 有利，整任务未见改善”。

优先展示 Consumer TTFT 与命中 token，同时给整任务成本和冷请求。没有 APC-off 独立条件，所以结论只叫“APC-on 服务下共享布局的实际价值”，不声称测得 APC 开关的独立因果收益。

## 6. KV：8 次，完整 capture/load/forward/release

同一个 APC-off KV 服务中执行 `full_replay` 与 `continuation`。四个 case 每条件一次；1/3 replay-first，2/4 continuation-first。两侧 schema、采样、预算和完整逻辑输入相同；逐对核验 rendered prompt/token digest。

真实业务仍是 Executor 生成 TransformProgram、Runtime 执行/验证、Summarizer 输出 ClaimSet。Producer 对共同 dossier 做一次前缀 prefill/capture；Consumer 在同一 engine_generation 与相同 token identity 下 load 已捕获状态，然后处理 Summarizer suffix。replay 完整重送同一逻辑 prompt，但没有 capture/load。KV 只优化**同一 engine 内的一次角色交接**，不是跨进程/跨 GPU 的状态传输，也不减少逻辑输入或 StateBus 消息数量。

- replay 不 capture、不 load；continuation 正常 capture=1/load=1，有 scheduler load 与 worker forward proof。
- 一 handle 仅消费一次；Executor repair 替换 Producer 时先 release 旧 handle，再捕获新 handle，全部 capture 计成本。
- 不预捕获多个大 handle，不扩展多 Consumer、跨 Worker/GPU 或共享内存架构。
- 输入或 repair 路径不同就披露，不把非等输入差异写成严格 token 节省。
- registry before/after entries/bytes 归零；仅释放本 run 的 handle，不清理其他 owner 数据。异常也尝试 release，不能只靠 TTL 或服务退出掩盖未释放。

必采：Producer logical/computed/output token、request/store wall、tensor bytes；Consumer logical/inherited/computed token、TTFT/load/request wall；forward proof/layers/parent/engine identity；captures/replacements/releases；初始化/检索/模型/DSL/验证/报告/清理与 task wall。

Consumer saved tokens = replay computed - continuation computed。整任务 computed 必须包含 Producer、repair 和 Consumer。logical input 不因缓存而减少；store/load 若已包含在 request wall，不再次相加。

每对条件保存 `producer_computed_tokens, consumer_logical_tokens, consumer_computed_tokens, consumer_inherited_tokens, capture_bytes, store_ms, load_ms, consumer_TTFT_ms, task_wall_ms`。Consumer saved token 和比例 `saved/replay_consumer_computed` 只在相同输入、相同输出预算、计数可用时计算。对完整任务另报 `total_computed_tokens`（所有模型请求之和）与 `task_wall_ms`；不能拿 Consumer 指标替代总成本。机制通过须有实际 capture/load receipt、scheduler load、forward proof、engine identity、全部 run-owned handles release 且 registry 归位；只有 `enabled=true` 不算。若 continuation 的 Consumer 少算但 store/load 抵消耗时，优势只能表述为 Consumer 计算减少。

检查 registry 容量能容纳最大单 handle，逐任务释放；预算以实际模型配置和实测 tensor bytes 为准。主展示是 Consumer 少算/首字与完整业务成本，不预先承诺 E2E 加速。

## 7. Logit：4 个案例 × 3 策略 = 12 次

### 7.1 固定案例，不做大样本研究

冻结 4 个案例：1 个 easy、2 个 semantic ambiguity、1 个 unresolved，覆盖 Orion/Nova。明确它们是机制展示案例，不是独立验证集或总体业务分布。Gold 在运行前独立冻结；不根据 live 表现替换“难题”。

每题给两份已授权 evidence bundle 的固定字段摘要，以及 insufficient_evidence 候选。完整用户公式/合同始终公开，不故意删要求制造歧义；完整证据本来就存在于授权 refs，差别仅是是否展开。

实施时把这四个**明确场景**冻结到 taskpack，不临时换成更容易出正向结果的题：

| case 角色 | 用户决策与两份候选证据 | compact/full 的真实差异 | 预期观察；非成功保证 |
|---|---|---|---|
| easy：Nova cohort OTD | 选择可计算样本 Q1/Q3 加权准时率的 `sample_ledger`，对照只有公司整体 OTD 的 `operating_review` | index 已清楚写明 cohort、分子/分母；full 只是展开行和引用 | 正确选 ledger 且 selective 不展开，可少发一个长证据选择请求；若误展开照实计成本 |
| ambiguity A：Orion 加急费 | 两份均获权的费用资料，一份为当前 sample ledger/有效审批规则，一份为历史口径或其他 scope | index 保留真实标题/scope 但不预解最终规则；full 有生效日期、例外项和可追溯明细 | 不确定时展开后纠正或确认选择；若 compact 已明确可规则判定，不能把被省掉的工作归功于 Logit |
| ambiguity B：Nova delivery | 两份均获权的交付资料，一份含 `committed/on_time` 行，一份只有报告总体率或不适用口径 | full 才能核实分母、有效 cohort 与细项；用户要求始终写明加权公式 | 展开可能避免把简单平均/总体率当样本率；若模型高信错误放行，记风险而非成功 |
| unresolved：Orion Q3 例外 | 同一例外的两份授权记录互相冲突，缺最终签核；业务要求确认是否可计入获批费用 | compact 不伪造结论，full 保留冲突和缺失签核的真实受控事实 | 正确终态为 insufficient；若强行二选一或编造值，业务失败 |

这四题可借用 4k/6k 受控语料的*来源类型*，但 Logit taskpack 有独立 case_id、冻结 refs、Gold 和 384–4096 token 证据预算；不能在同一批 live 结果后裁剪 bundle。所有候选先过确定性 Grant/来源/有效期检查，Logit 只处理检查后仍需语义判断的选择。若 ambiguity 在 compact index 已能确定性解决，记录这一事实并展示保守行为，不人为删索引字段制造成功。

compact 目标 384–768 token，full 目标 2048–4096 token；这是 Logit 的信息展开预算，不冒充 APC/KV 的 4k/6k 共同前缀。full 不加无关填充。choice max_tokens=32，报告 max_tokens=256。

### 7.2 三策略和固定门限

| policy | 行为 | 要看什么 |
|---|---|---|
| compact_once | 紧凑索引只选一次 | 不展开的结果与成本 |
| full_context_once | 一开始给完整证据，只选一次 | 高信息参考，不故意多请求造弱参考 |
| logit_selective | 紧凑选择后，必要时只展开一次 | 实际决策变化、纠错/拒绝、额外请求与 token |

模型只输出 `{"choice_code":"A"}`；三个 ASCII alias 对应两个证据与 insufficient，映射公开且在同 case 各策略相同，跨 case 轮换。复用 CandidateSurfaceV2/extract_exact_choice_logit_state，真实检查 decision token/候选覆盖；保存原概率、other_mass、margin 和生成选择，不用序列峰值 entropy 充当业务正确率。

`tau=0.10`、`other_mass_limit=0.20` 在运行前固定，不做网格调参，也不称已校准正确概率。动作：

~~~text
确定性授权/来源/时间范围检查始终先执行。
首次 insufficient → 展开一次。
exact unavailable / selected 非 top1 / other_mass >0.20 / margin <0.10 → 展开一次。
否则 → 执行业务并验证。
full view 仍 insufficient 或不满足同一门 → abstain；禁止第三次选择。
~~~

exact unavailable 触发单列，不归功于概率。如果 readiness 证明当前服务持续拿不到 exact 分布，Logit 子项明确 blocked，不用通用 token proxy 或假概率补齐。其他独立 APC/KV 可继续。

选择 evidence 后，公开纯映射生成通用只读 TransformProgram，不能读 Gold；Runtime 执行，Summarizer 生成报告，validator 检查数值/来源/口径。insufficient 用明确终态，不伪造空程序或 verified Artifact；可回答 case 被拒绝算未完成，unresolved 正确拒绝单列。

三策略按固定轮换顺序执行，不挑最佳结果。无额外 LLM repair；最多两次选择加一次报告。省掉 rule_expand 条件，所以不能声称 Logit 优于所有简单规则。

### 7.3 Runtime-owned 接缝

复用 bound_provider_handlers 和 ProviderCandidate diagnostics。新增可选 `executor_candidate_review` binding/context hook，默认 None，仅 utility flag 与 suite capability 同时开启才生效。

位置：dispatcher detach candidate、核对 Grant/Binding/kind 后、既有 failure 早返回与程序执行前。hook 只处理 executor_program 和本 suite 的 insufficient failure，不拦普通 provider 错误。

- continue：原路径执行与验证。
- request_evidence_recheck：产生 model_assist_review_required，不执行暂缓程序、不产生 verified Artifact。
- abstain：使用既有 failure carrier（payload=None）表示 need_more_evidence 终态，不产生第三次选择。
- suite replan_for_step 只响应 model_assist_review_required；创建 full-evidence step，走原 PlanPolicy、fresh Attempt/Grant；替换 step on_failure=fail，Summarizer dependency 指向新 step，Retriever 不重复。
- max_replans=1、max_total_attempts=4；provider 每次只调用一次模型，不私自循环、重试或调用下一角色。

不移植 legacy Logit shared-memory store，不改权限 authority。若既有类型不能承载，说明具体不兼容，不另造第二套 Runtime。

### 7.4 展示与限制

保留初选→同次概率→Runtime action→复选→实际执行→业务结果 trace。展示容易任务不展开、有益展开、误升级/错误自信/拒绝；未观察到的效果写未观察到。

报告正确完成、拒绝、错误选择/放行、纠正/改错、展开、unavailable、全部 input/output token、请求数。Logit 与 APC 共用 APC-on standard：可以记录时间，但不把策略时延差直接归因于 Logit，避免缓存污染解释。主要比较实际决策、质量与逻辑输入成本；不能用四例外推总体收益。

逐策略记录：首次 `choice_code` 与 Gold、同次候选原始 logprob/覆盖、`top_margin`、`other_mass`、触发原因、是否 fresh Attempt/Grant 展开、复选、Runtime 最终 action、业务 validator、总请求数与 logical input/output token。`compact_once` 和 `full_context_once` 都只做一次 evidence-choice + 同一业务报告；`logit_selective` 是一次 compact choice，必要时一次 full choice，再走同一报告。比较须**优先按正确业务结果分层**：正确时才说 selective 相对 full 省了多少 logical input /请求；纠错时展示相对 compact 的质量改变及额外成本；错误自信/误升级/拒绝分别列出。`savings=(full_input-selective_input)/full_input` 只在两侧均正确且 full_input>0 时作为案例值；这不是通用节省率。

## 8. 直接测试、固定热身与停止规则

### 8.1 同一轮执行，smoke gate 不重复计费

下一位 agent 完成 targeted tests、prepare、dry-run 和安全 preflight 后，**可直接运行 formal 的 28 个位置**。这是本轮明确允许的精简展示，不是旧大矩阵，也不是原 48 项。

正式执行内置最小 gate：standard 先做 Orion-4k 的 APC 两布局和 easy Logit 三策略，共 5 个位置，通过接线/业务/计量门后继续剩余 standard 位置；KV 先做 Orion-4k 两条件，通过后继续剩余 KV。**这 7 个 gate 位置属于 28 次，不另加一遍 smoke。**

“通过 gate”指链路、业务合同和采集可用，不要求已经看到加速或指定概率触发。有明确业务失败、source mismatch、预算/schema、权限或 lifecycle 错误时暂停受影响模块，定位后只复验受影响位置，新增尝试单列。安全/恢复问题立即停止整轮。

独立 `--mode smoke` 仅用于诊断同样 7 个位置，不作为 formal 前的必跑命令。默认直接 formal 内置 gate，避免额外 standard↔KV 切换。

### 8.1a 固定执行顺序与条件配对

先完成标准服务下的 20 个位置，再切一次 KV 跑 8 个位置；不为每题在两种服务间往返。standard 的顺序是：独立 calibration warmup → Orion-4k APC 两布局（gate）→ Logit easy 三策略（gate）→ 其余三个 APC case 每题完整一对 → 其余三个 Logit case 每题完整三策略组。KV 的顺序是：切换/认证/独立 calibration warmup → Orion-4k replay/continuation（gate）→ 其余三个 KV case 每题完整一对 → release 与 registry 检查 → 恢复 standard。APC/KV case 1/3 控制先、2/4 机制先；Logit 三策略用固定轮换顺序，并在 plan 记录，不按前一结果动态换序。

每个 APC/KV 条件对或 Logit 三策略组复用相同 case revision、公开事实、Grant 规则、Gold、生成配置与输出合同。每完成一个 slot 立即写原始 evidence、结果和 checkpoint；下一组前检查前组的业务 validator、输入身份和机制采集。单个 slot 的失败不能使其配对结果“消失”：先记录失败，再按 gate/安全规则决定暂停模块或运行预先安排的另一侧。正式计数为 standard 8 APC+12 Logit=20，KV 8，总数 28；warmup、health、修复复验各自单列。

### 8.2 固定热身与总请求量

- standard APC-on：独立 6k calibration case 的 independent/shared 各一个完整任务，2 个业务 warmup。
- Logit：独立、非计分 calibration easy case 的 compact/full 各一次 choice，2 个 grammar 请求；不拿 scored easy 输入热身。
- KV APC-off：独立 6k calibration case 的 replay/continuation 各一个完整任务，2 个业务 warmup，真实 release。
- 合计 **4 个非计分业务 warmup + 2 个 choice 请求**；正常约 10 次 generation。正式任务无 repair、无拒绝时基础 56 次 generation，Logit 最多增加 4 次展开，实际按执行记录报告。

calibration 验证 6k live budget/调度，也预热进程、Embedding、tokenizer、grammar；namespace 与正式证据隔离。正式任务的冷请求依然保留。固定数量，不反复暖到成绩好看。

尽量同一进程初始化一次 Embedding/tokenizer；无法复用时对称处理、单列启动成本。保持新旁路的小输出预算，先解决已证实的重复初始化/证据重复注入，不偷偷排除真实 store/load 开销。

## 9. 本地 Docker/vLLM 操作合同

### 9.1 执行前核对，不重建容器

工作目录 `/home/qcrs/statebus/os`；host/container Python 均先核实已有 `/home/qcrs/statebus/conda-envs/statebus_host/bin/python`，vLLM 使用独立 `/home/qcrs/statebus/conda-envs/vllm-qwen-cu121`。不得用 statebus_host 是否能 import vllm 判断服务可用。

本轮面向已验证的 `statebus-runtime`，host source `/home/qcrs/statebus/os` → container source `/workspace/statebus/os`。旧 AGENTS 中的 statebus-dev-qcrs 是历史环境描述，不能据此切换到 project；实际容器/挂载不符就报告冲突，不改绑、不重建。

安全 preflight 参考命令（真实存在）：

~~~bash
cd /home/qcrs/statebus/os
source deploy/activate_statebus_host.sh
nvidia-smi -L
nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu --format=csv
nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv
docker inspect statebus-runtime --format '{{.State.Status}} {{.HostConfig.NetworkMode}} {{json .Mounts}}'
STATEBUS_VLLM_ENV_FILE=/home/qcrs/statebus/os/deploy/vllm.env.local scripts/vllm/manage_qwen3_32b.sh print-config
STATEBUS_VLLM_ENV_FILE=/home/qcrs/statebus/os/deploy/vllm.env.local scripts/vllm/manage_qwen3_32b.sh status
~~~

若既有容器只是 exited，在核对 GPU device/mount/owner 后可 `docker start statebus-runtime`；若不存在或需要重建，停止并说明，不自动 compose up。host/container/KV server 都要实际加载当前 checkout 的新源码，留 import/source identity，不能只看 git branch。

不要盲跑 `scripts/start_statebus.sh`：当前脚本会调用 container up/verify/smoke，up 在配置不一致时可能重建。它的 `--print-config` 可用于核对。健康匹配的服务直接复用；仅需启动既有容器时不顺手附带另一套 smoke。

物理 GPU2/vLLM、GPU1/Embedding 是历史配置，不是永久授权；本轮启动前重新检查 owner。已有本工作流服务可按授权复用/切换，不杀其他进程，不强行选择被占的卡。发现其他客户端/非独占负载则标 blocked 或等待明确窗口，不能把 --yes 当排他锁。

host 与 container 的 StateBus 命令都必须使用已核实的 `/home/qcrs/statebus/conda-envs/statebus_host/bin/python`，分别从 host `/home/qcrs/statebus/os` 和 container `/workspace/statebus/os` import；检查 `statebus.__file__`、`contest_model_assist.__file__`、新 utility 模块文件都落在对应 checkout。`docker exec -w /workspace/statebus/os -e PYTHONPATH=/workspace/statebus/os statebus-runtime /home/qcrs/statebus/conda-envs/statebus_host/bin/python ...` 是参考调用形状，只有 inspect 证明这两个路径确实映射后才能用。vLLM 模型服务由 manager 调用其专用 `/home/qcrs/statebus/conda-envs/vllm-qwen-cu121`，不要在 StateBus Python 里 `import vllm` 判断健康。

### 9.2 只进行必要切换

~~~text
standard APC-on：APC 8 次 + Logit 12 次
→ KV APC-off：KV 8 次
→ release 本 run handles；恢复进入前原 standard
~~~

正常只两次切换；若进入时服务未就绪，必要准备时间另记。standard 已匹配 qwen3-32b/context8192/APC-on/allow_logprobs 时不重启。不要增加 standard APC-off 批次。

复用 `manage_qwen3_32b.sh` 的真实 ENV_FILE 接口；不假造 `--mode kv`/`--quiet` 等 manager 参数。standard env 为 `deploy/vllm.env.local`，KV 模板为 `deploy/vllm.env.kv.local`；运行时在新 run 的 service/ 下生成 KV env，覆盖本 run engine_generation，核对 GPU/context/APC-off/registry 容量/token 路径。原 env 不覆盖，API token 不复制进报告、不输出明文、不 bash -x。

runner 设置退出 trap 并保存原 service identity 后执行以下本地命令语义（不是供单独粘贴执行的完整恢复脚本）：

~~~bash
# MU_STANDARD_ENV 是经核实、可恢复原服务的 env 文件；MU_KV_ENV 是本 run 生成的 KV env。
# MU_MANAGER=/home/qcrs/statebus/os/scripts/vllm/manage_qwen3_32b.sh
# 日志由 utility runner 统一写入 run/service/，不丢弃错误。
STATEBUS_VLLM_ENV_FILE="$MU_STANDARD_ENV" "$MU_MANAGER" stop
setsid --wait env STATEBUS_VLLM_ENV_FILE="$MU_KV_ENV" "$MU_MANAGER" start
STATEBUS_VLLM_ENV_FILE="$MU_KV_ENV" "$MU_MANAGER" health
# 执行 KV；释放本 run handle 并检查 registry 后：
STATEBUS_VLLM_ENV_FILE="$MU_KV_ENV" "$MU_MANAGER" stop
setsid --wait env STATEBUS_VLLM_ENV_FILE="$MU_STANDARD_ENV" "$MU_MANAGER" start
STATEBUS_VLLM_ENV_FILE="$MU_STANDARD_ENV" "$MU_MANAGER" health
~~~

从已有 runner 复用 setsid --wait，避免 agent 会话结束杀掉恢复的服务。ENV_FILE 会被 manager source，不能仅靠调用前环境变量假设覆盖成功；检查最终生效配置。manager print-config 只显示部分字段，模型/context/APC 还需实际服务/启动证据核对。

KV health 必须认证：manager health 已从 STATEBUS_KV_API_TOKEN_FILE 读 token，经 stdin header 发请求；不要把 token 拼在 curl argv 或日志。host/container token 必须映射到同一 mode600 文件。验证真实 capture/load/forward/release，而非 health 或 enabled 代替机制证明。

### 9.3 退出恢复

原 standard 的 model/GPU/context/APC/runtime-dir/profile 必须保存并恢复；不能恢复成猜测默认。trap 覆盖正常、错误、INT/TERM；恢复优先于报告美化或后续复验。只处理 manager 所有的进程与本 run handles。

恢复检查：/health、/v1/models、manager running standard、实际模型/context、tokenize、最小 logprobs 请求；KV registry before/after 与 release 证据保存。恢复失败显著标红、非零退出并通知用户。

SIGKILL/掉电不能靠 trap 保证恢复；提供 `--recover-only --run-id ID`，根据 checkpoint 处理已知遗留并恢复，不消费旧 engine 的 handle。先保存相关日志再重启，以免 manager 截断 service.log 丢失证据。

### 9.4 runner 状态机与故障处理

`run_utility_suite.sh` 负责 env/source/资源预检、服务切换、trap、状态文件和安静日志；Python 负责 taskpack、provider→Runtime 的单任务执行与业务 validator；summarizer 只读已有产物，不再发模型请求。脚本不能用 `--dry-run` 启动 Docker/vLLM、创建报告目录或执行模型请求；`--mode prepare` 也只用本地 tokenizer。live 由 `--execute --yes` 双重显式开启；`--yes` 不是 Docker/GPU owner 的事实证明。

| 阶段 | 必做检查/动作 | 失败时 |
|---|---|---|
| 0. 离线 | 冻结 manifest/Gold、必要性扰动、真实 token/LCP/8192 预算、28 位置 plan、targeted tests | 不进入 live；保留失败诊断，不修改旧 run |
| 1. 安全 preflight | `nvidia-smi` 全卡和进程、容器 inspect/mount、host/container import、manager status/print-config、port owner、原 standard 配置和恢复资料 | GPU driver/owner、源码映射或权限不明即 blocked；不 stop 任何服务 |
| 2. standard | 复用匹配的 APC-on standard；查 `/health`、`/v1/models`、tokenize、最小 exact-logprob choice、APC counters；执行 standard warmup/gate/剩余 20 位置 | exact logprob 不可用只阻 Logit；APC 指标不可用只阻 APC；服务安全问题阻全轮 |
| 3. KV switch | 设置 restore checkpoint；保存原服务日志/配置；只 stop manager-owned standard；从 run-local env 启动 APC-off KV；核对 engine_generation/context/source、认证 health/registry | 立即走 restore；没有安全的原配置不开始切换 |
| 4. KV | KV warmup/gate/剩余 8 位置；每任务收 capture/load/forward/proof 与 release，核对 registry baseline | 停受影响模块；尽可能 release 本 run handle 后 restore，不把失败写成功 |
| 5. restore | 先留存 KV 日志与健康证据，stop manager-owned KV，恢复原 standard，验证 health/models/manager/context/APC/tokenize/logprobs | 非零退出、`standard_restored=false`，给 `--recover-only` 命令和当前服务状态 |

若进入时不是 healthy standard、standard 无法确认由本 manager 托管，或已有非本 run 的 KV 服务/registry 内容，不强制切换；报告 blocked 与实测状态。容器只允许 `docker start statebus-runtime` 恢复**已存在且映射正确**的 stopped 容器；不能自动 compose up/recreate/stop 其他容器。runner 的重启只指所管理的 host vLLM standard↔KV，不重启 Docker 引擎、GPU driver、其他服务或机器。

## 10. 安静执行与低频轮询

- 新 runner 实现 `--quiet`：启动时仅输出 run-id/日志路径，过程 stdout/stderr 写入 run.log/service 日志，最终输出一份摘要。不是把日志扔到 /dev/null，也不是吞错误。
- agent 不逐 slot 播报、不反复贴 GPU/health/tail；正常测试保持安静，开始、完成、需要决策或恢复失败时说明。若执行宿主要求心跳，仅给最短状态，不展开过程。
- 外层等待/状态轮询默认 **60 秒**（`--poll-interval-s 60`）；优先等待正在运行的命令/session，不启动重复 runner、不循环重发模型请求。若工具单次等待上限更小，使用其合法上限，累计约 60 秒再做一次状态读取；不靠忙轮询。
- 不用长 sleep 阻塞中断：子进程完成/INT/TERM可及时处理，单次工具阻塞等待不超过 60 秒。
- 现有 manager 启动等待内部每 2 秒 health，这是本地既有 readiness 逻辑；保留、不为静默要求修改公共 manager。外层不再叠加密集 curl。启动超时沿用核实后的配置，不能因短期无输出反复重启。
- APC metrics 保留必要的请求/任务前后采集，KV 保留 health/lifecycle 证据；60 秒指监控等待，不是把精确 TTFT 或实验事件采样降到 60 秒。
- 过程没有输出不等于挂死。按 request/startup timeout、进程退出码与状态文件判断；失败时读取相关日志并有限诊断。

## 11. 尽量形成真实优势，但不筛掉不利结果

优先使用已经固定的 4k/6k 长共同证据、小输出、一次初始化、正确 prefix 布局和明确 Consumer 指标；这些是任务适配与消除无关开销，不是改分数。

结果不符合预期时依次查：业务/输入一致性 → warmup/重复初始化 → 实际 LCP/hit/inherited/proof → decode/repair 主导成本 → capture/store/load → GPU 外部负载和计量窗口。只修有直接证据的问题；对影响比较的改变使用新 revision，受影响 case 的两侧一起复验，旧结果保留。

额外 live 复验默认最多 **4 个任务位置**，单列不混成原 28；超过本轮预算就交付原因和未验证项，不无限“跑到有收益”。既有有界 Executor repair 是一次任务内部成本，也必须保存。

可以突出“Consumer 少算明显、首字更快，但整任务无改善”的局部优势，必须同时给总成本。若没有有益 Logit 展开，写未观察到，不伪造概率/选择；若规则参考没跑，不声称胜过规则；若只一次采样，不称稳定加速或统计证明。

### 11.1 指标口径与报告优先级

所有 wall clock 用同一 monotonic clock；`task_wall` 从任务开始编排到 business validator 终态，含检索、模型、DSL/Artifact、repair 与报告，不含服务启动、跨条件切换、独立 warmup；这些额外时间另报。`request_wall` 从实际发出模型请求到完整响应；`TTFT` 从发出请求到首个非空内容 token。若当前 KV/guided 路径不能在**不改变输出语义**下提供流式 TTFT，记 `unavailable`，仍可用 computed token 和 request/task wall，不通过响应头或估算伪造 TTFT。每请求记录 logical prompt、computed/inherited（若后端提供）、output token；不得把原始文本字符数当 token 或把 saved computed 当 saved logical input。

| 报告顺序 | 有利证据必须同时满足 | 无法支持的结论 |
|---|---|---|
| 先质量 | 业务 Gold/权限/ClaimSet 通过；Logit unresolved 正确拒绝单列 | 只有 schema 正确或机制 enabled 就算业务成功 |
| APC 机制 | 同输入布局、token LCP 和干净 task/request counter 窗口；shared Consumer hit 高于 independent | 没有 APC-off 条件就声称“打开 APC 加速 X%” |
| APC 效用 | 同 case Consumer TTFT 更低；同时给 task wall、冷请求/repair 和全部反例 | 只报全服务 lifetime hit-rate 或只挑最快 case |
| KV 机制 | 同逻辑输入、capture/load/scheduler/forward/release、registry 归位；continuation Consumer computed 更少 | 只凭 `enabled` 或仅请求少一个 token 就称 KV 移交成功 |
| KV 效用 | Consumer TTFT/request wall 有利时展示；如整任务 wall 也有利才称该 case 端到端有利 | 忽略 Producer/capture/store/load/repair 的总成本 |
| Logit 效用 | compact 正确时避免 full，或 ambiguity 经展开纠正，或 unresolved 正确拒绝；附请求/token 代价 | 候选概率高就是正确、四例可推广、优于未跑的规则 |

每 case 给两侧/三策略的原始值和差值，负值照报；汇总只给 `4 cases 中有 N cases` 等描述性计数，不计算跨 case 平均加速或显著性。若首次 live 与预期相反，先用原始证据查任务必要性、输入等价、缓存命中、初始化/repair、输出长度、资源干扰；仅证实缺陷才修复并成对有限复验，旧数据不可删除。

## 12. 产物、测试与交付命令

输出目录固定 `/home/qcrs/statebus/os/docs/reports/contest-model-assist-utility/<run-id>/`，新 run-id，不覆盖历史。至少有 plan/manifest/taskpack/compiled-prefixes/necessity-checks、commands.md、run.log、warmup.jsonl、records.jsonl、decision-traces/、slots/、service/、changes-and-reruns.md、summary.json/csv、report.md、run-status.env。各文件可简洁，不另建大型审计系统。

每条记录关联 run/revision/case/condition/request/attempt；保留 token/timing/proof/质量/失败/清理，missing 不填 0。报告按长文本 APC、KV 和 Logit 三部分组织，旧短前缀仅历史附注。标题明确“长文本场景机制展示”，不写成主链 48 项性能结论。

状态区分 source_ready/offline_passed/smoke_gate_passed/demo_completed/business_quality_passed/mechanism_proven/standard_restored；demo_completed 只表示 28 个位置已按合同结束，不等于全成功。unresolved 正确拒绝与可回答正确完成分开。收益标 observed/mixed/not_observed/unavailable，不由机制通过自动推导。

targeted tests 覆盖：4 个长文本+4 个 Logit 案例与 8/8/12 计划数、Gold 隔离、必要性/token预算、visibility、默认 off 无副作用、真实 hook 的 fresh Grant/一次展开/abstain、KV one-shot/replacement/release、计时不 double count、quiet/退出恢复。只跑受影响 tests、bash -n、静态导入与 dry-run，不跑全量 pytest 或主链。

新 CLI 合同如下，**须实施 agent 创建并核实后才能执行**：

~~~bash
cd /home/qcrs/statebus/os
source deploy/activate_statebus_host.sh

# 离线：本地 tokenizer、公开任务与独立 Gold，不请求 GPU/vLLM/网络。
scripts/experiments/contest_model_assist/run_utility_suite.sh --mode prepare

# 只读计划，显示 28 个位置/热身/切换/预算，不创建 run 目录。
scripts/experiments/contest_model_assist/run_utility_suite.sh --mode formal --phase all --dry-run

# 本轮已授权：离线与安全检查后直接测试；内置 7 个 gate，不另跑重复 smoke。
scripts/experiments/contest_model_assist/run_utility_suite.sh --mode formal --phase all --execute --yes --quiet --poll-interval-s 60 --wall-budget-s 5400

# 仅诊断才单用 --mode smoke；--phase 可选 standard|apc|logit|kv|all。
# 恢复：--recover-only --run-id ID；续跑：--resume ID，成功且有效的位置不重跑。
~~~

prepare 重跑生成新 revision，不覆盖冻结输入；资产缺失明确 blocked，不下载或用字符估算替代 token。续跑 APC 完整条件对/Logit组时校验配置与 revision；被中断而不能保持缓存边界的条件对整体作废另记，不拼成漂亮成绩。

完成后交付脚本、真实命令、28 项及 warmup/复验计数、长文本机制证据/实际收益与代价、恢复结果、报告路径及未验证项，然后停止。不追加原 48 项、旧 8 项重跑、完整 benchmark 或更多长度/组合。

## 13. 源码参考与执行 Prompt

- `statebus/benchmark/contest_model_assist.py`、`contest_dsl_mainline.py`：provider、Runtime/DSL/Artifact/ClaimSet 与 replan。
- `statebus/runtime/adaptive_mainline.py`、`adaptive_dispatcher.py`、`role_providers.py`：Runtime authority 与候选接缝。
- `docs/mrr/mrr10/StateBus-MRR-10-RolePath-Compatibility-Deep-Design.md`：provider 单次调用、Logit sideband、Runtime retry。
- `statebus/runtime/logit_state.py`、`contracts/logit.py`、`prefix_identity.py`、`vllm_metrics.py`：候选概率、前缀与指标；以实际所在路径为准。
- `statebus/benchmark/engine_local_kv_tasks.py`：借用 token 编译，不继承无关附录填长语义。
- `statebus/integrations/vllm_kv/`：capture/load/forward/one-shot/release。
- 本文第 3/9 节列出的本地服务与小批脚本；project 仅只读历史参考，不直接复制覆盖。

执行 Prompt：`/home/qcrs/statebus/astra-measurement-proposal/49-MODEL-ASSIST-UTILITY-IMPLEMENTATION-HANDOFF-PROMPT-20260928.md`。保留原文件名供已有链接使用，内容以本版日期/revision 为准。

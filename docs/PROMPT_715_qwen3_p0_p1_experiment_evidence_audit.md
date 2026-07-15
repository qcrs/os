# Prompt: StateBus v2 Qwen3 P0/P1 全量实验、真实性与赛题符合性审计

## 角色、任务边界和完成目标

你是一名独立的竞赛系统审计工程师。你要审计从 2026-07-14 晚至
2026-07-15 完成的 StateBus v2 Qwen3-32B 实验，而不是复述现有
`summary.json` 的 pass/fail 字段。

你的目标是基于全部原始日志、结构化产物和对应实现代码，建立可复现的
证据账本，持续写入文档，并回答以下问题：

1. 每个实验和每个 stage 实际运行了什么，数据是否完整，哪些结论可复算？
2. P0 16-stage matrix、pytest 修复证据和 P1 扩展实验之间的准确关系是什么？
3. 每个机制到底是代码存在、路径运行、产生数据、被下游消费，还是有公平
   A/B 证据证明收益？
4. 比较、消融、连续任务、replay、后端矩阵和 prefix 的质量、效率、稳定性
   与公平性结果是什么？
5. 是否存在答案泄露、route/tool oracle、case 特化、fallback 掩盖、缓存污染、
   无效 baseline、指标聚合错误或 post-hoc 解释？
6. 对照赛题要求，哪些交付主张真正有证据，哪些只能作为 prototype、proxy 或
   future work？

这是只读审计任务。可以新增分析脚本、CSV/JSON 账本和 Markdown 报告；不能
修改 Runtime、benchmark、gate、测试、实验产物或 vLLM 配置，不能清理数据，
不能重跑模型实验。不要把历史 `summary.json` 改写为通过状态。

不要偷懒：不得只读取 summary、只看若干样例、只搜索关键词，或把 telemetry
字段存在误写成机制有效。先用 Python 递归枚举和抽取全部产物，再形成结论。
关键结论必须可追溯到 artifact 路径、JSON 字段、stage/layer/family/case 和代码行。

完成分析后停止，不实现修复；向用户报告文档路径、最可信结论、最严重缺口和
最小后续验证矩阵。

## 必须先读的仓库上下文

仓库：

```text
/home/qcrs/statebus/project
```

容器内等价路径：

```text
/workspace/statebus/project
```

开始前必须完整阅读：

```text
AGENTS.md
README.md
docs/reference/题目.md
docs/constraints/current_feature_scope.md
docs/constraints/current_host_and_migration.md
docs/planning/implementation_plan.md
docs/planning/ephemeral_neural_state_boundary_note.md
docs/PROMPT_714_full_qwen3_extended_matrix_audit.md
docs/prompt_7111.md
docs/improvement/20_v2_comprehensive_truth_audit_20260706/
  43_full_qwen3_extended_audit_20260714.md
docs/improvement/20_v2_comprehensive_truth_audit_20260706/
  44_planner_role_and_stability_plan_20260714.md
docs/improvement/20_v2_comprehensive_truth_audit_20260706/
  45_planner_kv_replay_fix_results_20260714.md
```

历史 tag 是比较背景，不是本次结果的替代品：

```text
v2-non-kv-baseline-20260710 = d83627d
v2-local-vllm-qwen-path-20260710 = a4d2f4e
```

当前提交的 P0 基线锚点是：

```text
2a8b402 v2: preserve qwen3 full-matrix P0 baseline
```

工作树可能有大量用户未提交改动。严禁 `git reset --hard`、`git checkout --`、
`git clean`、rebase 或覆盖已有改动。历史代码只允许使用只读 `git show`、
`git diff <ref> -- <path>` 和 `git log`。必须记录每个 run 的 manifest 中 git
revision 与当前工作树的差异；不能用后来的代码解释旧实验，除非明确标记为
post-run validation repair。

## 环境和审计约束

容器为 `statebus-dev-qcrs`。如需容器内只读检查，使用已有环境：

```bash
docker exec -u qcrs -e HOME=/home/qcrs statebus-dev-qcrs bash -c '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 --version
'
```

本次实验的实际模型环境需要从 manifest、preflight 和配置中复核，不可只信本
prompt。已知候选配置为：

```text
LLM endpoint: http://127.0.0.1:53334/v1
Model: qwen3-32b
Embedding: local / Qwen3-Embedding-0.6B
Embedding device: cuda:1
```

审计期间：

- 不重启或停止 vLLM；
- 不修改 `/statebus/runs` 中已有 JSON、日志、workspace、cache、statepool；
- 不运行 full suite、P1 suite、prefix probe 或有模型调用的 smoke；
- 不安装 Python 包或创建第二套环境；
- 分析脚本必须使用 `pathlib`、`json`、`csv`、`hashlib` 等静态读取方式，不可
  import 会启动 Runtime 或写入 StatePool 的模块。

## 审计对象和历史状态

以下三个根目录是本次证据的最小闭包。分析时既要使用宿主机实际路径，也要在
报告中记录容器映射路径。

### A. P0 16-stage full matrix 的历史原件

```text
FULL_ROOT=/home/qcrs/statebus/runs/full_qwen3_full_p1_20260715_001059
container=/statebus/runs/full_qwen3_full_p1_20260715_001059
```

它含编号 `00` 到 `15` 的 16 个 stage。历史 `summary.json` 的
`matrix_complete=true`，但 `01_pytest_v2` 当时 fail，因此不能写成一个原子
的 16/16 全通过 matrix。已知的 P0 pytest 失败是 smoke 轻量 stub 没有
`rendered_request_audit` 时，把真实角色 call count 覆盖为零；这是待核对的
表面解释，不是可直接引用的最终根因。

### B. 后续 pytest-only 修复证据

```text
PYTEST_REPAIR_LOG=/home/qcrs/statebus/runs/full_qwen3_full_p1_fix_20260715_001459/logs/01_pytest_v2.log
PARTIAL_REPAIR_ROOT=/home/qcrs/statebus/runs/full_qwen3_full_p1_fix_20260715_001459
```

该日志报告 `320 passed`。它发生在 P0 后，并且该 partial rerun 在 Stage 02
被人工中断。因此它只能修复/支持 `tests/v2` 的 pytest 结论，绝不能被误写成
新的一次完整 16-stage matrix。必须复核日志时间、hash、失败/错误行和当前修复
代码的最小 diff。

### C. P1 additive extension

```text
P1_ROOT=/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121
container=/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121
```

P1 是在 P0 后追加的证据，不得修改或重新解释 P0。其 source eligibility 使用
了 P0 的 15 个模型/评估 stage 通过证据和后续 pytest 修复日志。重点读取：

```text
source_eligibility.json
source_full_summary.json
repaired_pytest_v2.log
manifest.txt
status.tsv
run.log
stages/16_backend_matrix/stdout.json
stages/17_flagship_refresh/stdout.json
stages/18_prefix_parity_clean_repeats/repeat_summary.json
logs/*.log
```

P1 历史 `summary.json` 中 Stage 18 是 `fail`，但失败发生在四轮请求已经完成后：
`verify_stage` 内嵌 Python 访问 `os.environ` 却遗漏 `import os`，报
`NameError: name 'os' is not defined`。当前修复只在
`scripts/run_v2_post_full_p1_qwen3_container.sh` 的 verifier 增加 `import os`。

你必须独立验证下列两件事，并严格区分：

1. Stage 18 的既有 `repeat_summary.json` 是否已实际满足修复后 verifier 的全部
   gate；
2. 历史 P1 `summary.json` 仍应保留 fail，还是应把新的只读复核记为
   `post_run_validator_repair`。不允许修改原 summary；若复核通过，只能在新的
   审计账本中写明“原始模型实验通过、原始 runner 的后处理失败、修复后只读
   validator 复核通过”。

### 关于“18 个实验”的计数

用户将本轮工作称为“18 个实验”，但编号 `00` 到 `18` 有 19 个标号 stage，且
`16_backend_matrix` 内有 3 个 backend variant。不得擅自选择一个数字。首先从
三个根目录及 launcher 脚本建立清单，给出以下三个计数：

- stage label 数；
- 用户意义上的独立实验单元数；
- backend variant、family、layer、repeat、case 展开的运行单元数。

解释计数差异后再写总览表。所有 stage 的实际状态必须从原始 artifact 和日志
推导，不得直接沿用本 prompt 的描述。

## 分析产物和持续写入要求

新建下列审计目录，所有分析结果持续写入，不要等到最后才写一篇印象报告：

```text
AUDIT_ROOT=docs/improvement/22_qwen3_p0_p1_experiment_evidence_audit_20260715
scripts/analyze_qwen3_p0_p1_experiment_evidence_20260715.py
```

至少创建并按顺序更新：

```text
AUDIT_ROOT/00_scope_and_run_index.md
AUDIT_ROOT/01_artifact_inventory.json
AUDIT_ROOT/01_artifact_inventory.md
AUDIT_ROOT/02_normalized_evidence_ledger.json
AUDIT_ROOT/02_stage_layer_family_case.csv
AUDIT_ROOT/02_rendered_request_taint_ledger.csv
AUDIT_ROOT/02_claim_and_boundary_ledger.csv
AUDIT_ROOT/03_working_findings.md
AUDIT_ROOT/04_full_experiment_truth_audit.md
AUDIT_ROOT/04_full_experiment_truth_audit.json
AUDIT_ROOT/05_issue_and_minimum_validation_plan.md
```

可增加 CSV/JSON，但不得遗漏以上文件。`03_working_findings.md` 在完成范围
清点、全量抽取、每一类机制分析后立即更新，保留时间、分析脚本版本和证据路径。
报告和 JSON 内都记录分析命令、输入根目录、输入文件 hash、解析覆盖率、空文件
数、损坏 JSON 数、被排除文件及原因。

Python 脚本必须接受三个 root 参数，默认使用上述路径。例如：

```bash
python3 scripts/analyze_qwen3_p0_p1_experiment_evidence_20260715.py \
  --full-root "$FULL_ROOT" \
  --pytest-repair-log "$PYTEST_REPAIR_LOG" \
  --p1-root "$P1_ROOT" \
  --output-root "$AUDIT_ROOT"
```

脚本应可重复执行、只读输入、确定性输出（除了生成时间字段），并在结束时用
Python 校验自己生成的 JSON、CSV 主键和分母不为零。不要用手工复制的数字填表。

## 第一阶段：先建立全量原始证据账本

在给出任何效果判断前，编写并运行 Python 抽取器。它至少需要：

1. 递归列出每个 root 下的所有文件，按 `json`、`jsonl`、`csv`、`md`、`log`、
   workspace input/output、rendered request、telemetry、benchmark report、配置、
   manifest 分类，记录相对路径、大小、mtime、sha256；
2. 容错解析全部 JSON 和 JSONL，而非只解析顶层 stdout；逐文件记录 schema、
   parse error、空文件、截断、缺字段和重复对象；
3. 把 stage、variant、transport、role-path mode、embedding mode、layer、family、
   case、round、repeat、role、baseline/system identity 规范化为主键；
4. 对同一 case 的 output hash、quality floor、replay class、StateRef、agent call、
   tool call、LLM token、prompt bytes、wall time、state pool backend、fallback 和
   cache/prefix 指标建立长表；
5. 保留 artifact 的原始路径和字段路径。无法解析或缺失时写 `null` 和理由，绝不
   用零填充后再算平均；
6. 用分子/分母重算所有 ratio、hit rate、质量率、token/byte reduction、TTFT delta
   和 latency statistics。禁止把 per-case rate 或 per-stage rate 直接相加；
7. 列出 P0/P1 的代码 revision、LLM 配置 hash、模型名、服务 endpoint、环境变量、
   statepool 模式和运行顺序，以发现代码漂移或 cache/warm-order 混杂；
8. 在 Markdown inventory 中先展示 parse coverage、每个 root 的文件计数、每个
   stage 的 artifact 覆盖与失败/缺失项，然后再开始效果分析。

如果日志/JSON 体量很大，应通过 Python 流式读取 JSONL 和结构化索引解决，不能
以“文件太多”为由抽样。若一种 artifact 结构未知，先用 `rg --files`、`find`、
`head` 和 Python schema inventory 理解格式，再扩展 parser；不要盲目猜测字段。

## 第二阶段：实验完整性、状态重建和可重复性

对每个 P0 stage `00` 至 `15`，以及 P1 stage `16` 至 `18`，逐项形成表格：

```text
stage / 实验目的 / 原始状态 / 完整性 / 实际运行单元 / 质量结果 /
关键指标 / 失败或异常 / 可支持结论 / 不能支持结论 / artifact 路径
```

必须进行下列核对：

- `summary.json`、`status.tsv`、launcher/run log、stage stdout、stderr 和子报告
  是否相互一致；
- 所有阶段是否确实完成，还是存在 fail-fast、人工中断、空 JSON、后写覆盖、复用
  旧 workspace、缺 case 或 timeout；
- P0 的 pytest failure 是测试统计 bug、测试失败还是运行时能力失败；后续 320
  passed 是否覆盖确切失败用例且日志晚于 P0；
- P1 source eligibility 是否严格保留“P0 历史 matrix 未全绿”的边界；
- Stage 18 的四个 pair 是否都在 NameError 前完成；修复后 gate 的每一条判断，
  是否由现存 `repeat_summary.json` 的字段满足；
- 正确复核不等于篡改历史。分别给出 `historical_status`、`artifact_status`、
  `current_verifier_status` 和 `claim_status`；
- 当前 code 和 run-time code 不同的部分，哪些只影响后续 verifier，哪些可能影响
  模型请求或指标语义。需要用 commit/diff 证明，不能靠时间推断；
- 审计是否可以由另一个人只用记录的命令、根目录和脚本输出复现。

## 第三阶段：按机制拆解效果和公平性

### 1. L0-L3、文本控制与非文本状态

分别比较 L0/L1/L2/L3、T2 text-same-semantic-selection、internal carrier 和
external pure-text。对每个 family/case 统计质量、prompt token/bytes、可见 evidence
bytes、scaffolding bytes、wall time、角色调用、StateRef transfer、memory/replay。

重点问题：

- T2 是否真正使用与 L2 相同的语义选择，仅把非文本状态交换改成 text handoff？
- L2 相对 T2 的差异是否证明非文本 StateRef 的额外收益，还是只证明 semantic
  pruning/selection 的收益？
- 对 fixed-answer、continuous、replay family 分开判断；禁止用某一 family 的改善
  推广到所有任务；
- 质量一致性是否由相同 scorer、相同事实覆盖、相同任务和相同模型配置保证？
- 实验中是否使用 shared memory、mmap、memfd 的真实 StateRef，并由下游 hydrate/
  consume 事件证明，而不是只看 publish count？

### 2. P1 后端矩阵

检查 `16_backend_matrix` 的 3 个 variant：

```text
mmap_loopback
shared_memory_loopback
memfd_subprocess
```

逐项验证 requested mode、actual mode、transport、fallback、质量、case coverage、
publish/transfer bytes、跨进程边界和 cleanup。`loopback` 不得宣传为跨进程 IPC；
只有实际子进程 + UDS/memfd 证据可作为跨进程证明。不要把同一套 25 case 的质量
通过误称为三个后端均有性能优势；若没有公平重复 timing，只能陈述功能与取舍。

### 3. Flagship refresh、连续任务、memory 和 replay

严格区分：memory match、assist reuse、strategy/artifact reuse、validated replay、
exact replay、output restoration、skipped runtime step、skipped agent/LLM/tool call 和
`reuse_gain`。

必须审计 P0 Stage 03/04/05 与 P1 Stage 17：

- bootstrap/target 或 round 之间是否真的消费先前产物，history 根目录是否隔离；
- compatibility signature、evidence identity、artifact hash、output hash、replay
  class 和 replay audit 是否彼此一致；
- exact replay 是否恢复已验证 output/artifact，validated replay 是否仍真实执行；
- 任何 `skipped_step_count` 是否有相应的 call/token/tool 减算；
- 10 轮连续任务的依赖关系、task identity、memory key、quality 是否真实；
- P1 StateRef stress 的 5/6 等摘要必须从 family 级原始 ledger 重算，标明
  `incident_diagnosis_v2` 等 diagnostic-only 项为何不应当进入 headline；
- fixed-answer 中若 T2 已解释大多数收益，必须如实写出，不得把语义选择收益包装为
  hidden/KV 状态收益。

### 4. Compare、carrier、formal、UDS 和 CodeAct

审计 P0 Stage 02、06、07、11、12、13、14 和 P1 fixed external/carrier：

- baseline 与 StateBus 是否使用相同模型、温度/max tokens、任务、证据、工具、
  输出契约、quality scorer、执行次数和顺序；
- external baseline 是否被削弱、StateBus 是否拥有 baseline 不可用的 helper、
  deterministic result、route hint 或 answer-derived state；
- 检查 AB/BA、服务 warm cache、first-run 偏差、重复次数、median/p90/p95，不能把
  单次或固定顺序 latency 写成稳定优势；
- UDS/subprocess 是否真有 `subprocess.Popen`、AF_UNIX、Protobuf request/response、
  child PID/socket 生命周期和真实外部 Executor；
- carrier comparison 比较的 payload 语义和工作量是否等价；
- CodeAct 是真实 LLM plan/code、受限执行还是 deterministic helper 为主；分析
  sandbox backend、fallback、resource/bwrap/none 计数及安全边界。

### 5. Prefix、KV、LogitState 和未参与机制

这是高风险术语区域，必须采用“代码路径 -> run 配置 -> telemetry -> 原始请求 ->
下游行为 -> A/B 证据”的链路审计。

对 P0 Stage 09/10 和 P1 Stage 18：

- 分别重算 shared/independent 的 counter queries、hits、hit rate、TTFT 和每 pair
  差异；
- 检查 P1 是否 4 次、AB/BA 均覆盖、两份 evidence corpus 均覆盖、completion
  contract 全部有效；
- 明确 P1 `clean_service_requested=false`、`service_window=continuous_service_between_pairs`
  时不是 per-repeat clean-service 重启实验；
- 检查 prefix counter delta 是否可归属给本次请求，是否会被先前 workload 或并发污染；
- 可写成 engine-local vLLM prefix reuse 的机制证据，但不得写成 Agent 间 KV tensor
  transfer、hidden-state handoff、cross-engine reuse 或端到端 workload speedup；
- 若 TTFT 在小样本中改善，注明样本量、服务窗口、计数器归因和不确定性，不能写成
  稳定 latency superiority。

对 `LogitState`、`logit_*`、`LogitStateRef`、logprobs、hidden-state/KV 路径做专项表：

```text
机制 / 是否配置 / 是否实际产生 / 原始字节/值 / 是否 StateRef 注册 /
哪个角色接收 / 是否被下游消费 / 是否改变 route/tool/retry/fallback /
质量或效率 A/B 证据 / 可宣称边界
```

尤其核对“LogitState/Logits 没有参与”这类主张：不要因字段名出现或为零就草率判断。
若它只做 telemetry/side channel、没有被行为消费，必须写成“未参与本次效果结论”或
“仅可观测性原型”；若有 transfer，也不得把 top-logprobs 写成隐藏状态张量。任何
未参与或未被消费的机制都必须在最终边界表中明确列出，而不能静默省略。

## 第四阶段：答案泄露、作弊风险、特化和实现真实性审计

这是重点章节。必须同时做静态代码追踪和动态 rendered request 审计，并把每项
发现分为：合法 typed task contract、实验局限、指标/gate 缺陷、严重泄露风险或
已证实作弊。不要把所有下游 route/tool 传递都判为泄露，也不能因有 taint scanner
就停止人工角色语义分析。

### 动态请求和数据流

全量读取所有可获得的 Planner、Retriever、Executor、Summarizer rendered request
artifact，包括 P0、P1、ablation、baseline 和 holdout。按 role、stage、case、request
index 建表并解析 tag/payload。既扫描字段名也扫描值/同义表达，至少检测：

- expected answer/fact/value、gold/target/score/validator；
- preferred candidate、candidate key、route、tool、hint；
- case/sample/task ID、family-specific constants、time/entity scope；
- quality checks、ground truth、scorer 规则、output schema；
- CanonicalTaskSpec、SemanticTaskPlan、Evidence/Hydrate manifest、memory artifact；
- Runtime 已验证后合法交给 Executor 的 route/tool，与上游非法 oracle 的区别。

每个命中必须输出到 `02_rendered_request_taint_ledger.csv`：原始路径、stage、case、
role、request index、字段/片段 hash、命中规则、频次、是否重复、上下游来源、角色
职责判断、严重性、代码路径和结论。对于重复 violation，要报告“唯一泄露类型”和
“原始出现次数”，不能把 48 次重复误说成 48 个独立漏洞。

### 静态特化和 fallback 检查

审查当前代码以及运行提交对应的历史代码，搜索并追踪：

- case ID/sample ID/family 分支；
- expected answer、固定 route/tool 映射、candidate order、任务专用 regex；
- corpus metadata 到答案/validator/prompt 的直连；
- deterministic fallback、runtime fallback、repair、quality floor、oracle 或 scorer
  信息进入角色输入；
- 预编译 `CanonicalTaskSpec` 字段及其是否限制自由文本泛化主张；
- planner 模型字段、runtime fallback 字段和下游实际消费字段；
- memory/history/CAS/workspace 是否跨 stage、case、layer 或 baseline 污染；
- cache prefix、embedding cache、statepool、output artifact 是否因运行顺序带来不公平
  warm-start；
- baseline 与 StateBus 是否共享或不共享本应相同的工具、证据和后处理。

还要检查 P0 Stage 08 genericity/holdout 的每个 taint 和 paraphrase gate：具体 role、
字段和值、重复计数、no-hint mode、Planner ablation、semantic-equivalence 原因。若
它们与新代码已经修复，仍要明确“本次历史结果”与“后续修复验证”分别是什么。

对于任何“效果很好”的指标，反向查其来源：是 LLM 实际决策、工具真实执行、缓存
复用、预设任务元数据、后处理修正、fallback，还是聚合脚本。只要存在不确定性，
就降低 claim class，不能选择最乐观解释。

## 第五阶段：赛题逐项核对和主张分级

以 `docs/reference/题目.md` 为准建立矩阵。每一项都要同时给出代码证据、运行证据、
公平性/质量证据、缺口和可宣称级别：

| 赛题要求 | 代码机制 | 本次原始实验 | 已证明内容 | 风险/缺口 | 可宣称级别 |
| --- | --- | --- | --- | --- | --- |
| 至少 3 Agent、至少 3 类角色 | | | | | |
| 结构化协议与能力/握手 | | | | | |
| text 与 structured 的同任务对照 | | | | | |
| 非文本中间状态的生成/传递/接收/消费 | | | | | |
| 共享记忆存储、检索和复用 | | | | | |
| 两组关联连续任务及不少于 10 轮 | | | | | |
| 通信、token/bytes、延迟、state bytes、hit/reuse 指标 | | | | | |
| Runtime/protocol/statepool/memory/eval 系统完整性 | | | | | |
| CodeAct 与安全边界 | | | | | |
| openEuler 交付可复现性 | | | | | |

必须将每项创新按下列五级证据分层：

1. 代码定义存在；
2. 实验路径被执行；
3. 原始产物记录真实数据；
4. 下游消费并改变可观察行为；
5. 公平 A/B 下质量或效率收益被重复验证。

最终不得给出虚假的确定竞赛分数。可按评分维度（通信效率 25、状态传递创新 20、
记忆复用 20、系统完整性 20、实验验证 15）评估证据强弱和评委风险，但必须区分
“已证明”“部分证明”“仅设计/telemetry”“当前不能主张”。

## 最终报告结构和验收标准

`04_full_experiment_truth_audit.md` 至少包含：

1. 执行摘要和审计范围；
2. P0/P1 时间线、实验计数解释和历史/修复状态；
3. 解析覆盖率、数据完整性、代码版本和可复现方法；
4. 全部 stage 的状态与证据表；
5. layer/family/case/role 的全量指标总表和重算方法；
6. P0 pytest failure 与 P1 Stage 18 verifier failure 的精确根因和影响边界；
7. L0-L3/T2/StateRef/后端矩阵的效果与反例；
8. continuous、memory、replay 与真实减算；
9. compare、carrier、UDS、CodeAct、公平性和 latency；
10. prefix、KV、LogitState/Logits 参与性及严格边界；
11. rendered prompt、答案泄露、case 特化、fallback、cache/history 污染审计；
12. 赛题覆盖与创新证据矩阵；
13. 已证明、仅 proxy、diagnostic-only、失败/有缺陷、不能宣称的结论清单；
14. P0/P1/P2 问题台账；
15. 最小修复与最小验证计划，明确哪些需要单测、targeted stage、clean repeat 或
    完整 matrix。

每个问题必须包含：现象、根因或待证假设、artifact 证据、代码位置、对结论影响、
严重性、最小修复、回归风险和最小验证。所有数值必须附带分子/分母、聚合范围和
artifact 路径。结论不得只引用本 prompt 或旧报告。

完成前逐项自检：

- 已递归清点所有三个 root，所有 JSON/JSONL 均有解析或明确错误记录；
- 所有 P0 `00-15`、P1 `16-18` 和 pytest repair 被分别标记，计数差异已解释；
- 没有把 P0 历史 fail 写成全绿，也没有把 post-run verifier repair 写成重跑模型；
- 所有 ratio 都由原始分子/分母重算，未累加 rate；
- 所有 rendered request 都已进入可检索的 role/case ledger，重复命中已去重统计；
- 所有“非文本”“memory/replay”“prefix”“LogitState/Logits”主张均有消费链和
  claim boundary；未参与机制被明确写出；
- 已审查 fallback、case 特化、oracle、answer/scorer 泄露、baseline 公平性和
  cache/history 污染；
- 已按赛题逐项给出代码与实验两层证据；
- 没有修改 Runtime、测试、gate、现有 run artifact，也没有发起模型调用；
- 分析脚本和报告路径已写入最终摘要，另一位工程师可复跑抽取器获得相同账本。


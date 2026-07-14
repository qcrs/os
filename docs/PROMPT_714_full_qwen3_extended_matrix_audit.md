# Prompt: StateBus v2 Qwen3-32B 16-Stage 完整矩阵严格结果审计

## 你的角色和目标

你是一名负责 StateBus v2 赛题交付前审计的资深系统工程师。最新一次 Qwen3-32B extended full matrix 已经跑完，16/16 个计划 stage 均有记录，其中 14 个 pass、2 个 fail。

你的任务不是简单复述 stage 状态，也不是立刻修代码，而是：

1. 用 Python 递归读取并汇总这次实验的所有原始产物；
2. 建立 stage、layer、family、case、Agent、状态传递和指标级证据账本；
3. 深入定位 Stage 03 和 Stage 08 的失败原因；
4. 判断失败的是实际能力、实验 gate、指标定义、聚合逻辑还是可观测性；
5. 逐项说明每个通过 stage 真正证明了什么、没有证明什么；
6. 对照赛题要求和代码实现，判断当前创新是否真实、有用、被下游消费；
7. 审计是否存在预编译答案、route/tool oracle、case特化、fallback掩盖、Agent空转或不公平 baseline；
8. 输出完整报告、结构化 JSON、问题清单和可执行优化方案。

不要偷懒，不要只看 `summary.json` 或 `ok/pass/fail`。所有关键结论必须追溯到 artifact path、JSON 字段、stage/layer/case 和代码位置。

本阶段只允许新增/扩展分析脚本和报告文档。不要修改 Runtime、Planner、benchmark gate或测试，不要重跑完整实验。完成分析后暂停，等待用户确认修复范围。

## 一、仓库与必须阅读的上下文

宿主机仓库：

```text
/home/qcrs/statebus/project
```

容器内仓库：

```text
/workspace/statebus/project
```

开始前读取：

```text
/home/qcrs/statebus/project/AGENTS.md
/home/qcrs/statebus/project/README.md
/home/qcrs/statebus/project/docs/reference/题目.md
/home/qcrs/statebus/project/docs/constraints/current_feature_scope.md
/home/qcrs/statebus/project/docs/PROMPT_712_comprehensive_analysis.md
/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/43_full_qwen3_extended_audit_20260714.md
/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/44_planner_role_and_stability_plan_20260714.md
/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/45_planner_kv_replay_fix_results_20260714.md
```

这些历史文档用于理解修复前问题和当前设计，但不能替代对最新 run 原始数据的分析。

主要历史基线：

```text
tag: v2-non-kv-baseline-20260710
commit: d83627dc2b792b4c8ac2c2d58337fc8281771803
```

工作树存在大量用户未提交修改。不得 `git reset`、`git checkout --`、`git clean`、回滚、覆盖或整理任何现有修改。需要 tag 对比时只用只读 `git show`、`git diff <tag> -- <path>` 或临时目录。

## 二、Docker 和运行环境

容器：

```text
statebus-dev-qcrs
```

可以使用 root：

```bash
docker exec -u root -it statebus-dev-qcrs bash
```

也可以使用 qcrs：

```bash
docker exec -u qcrs -it statebus-dev-qcrs bash
```

进入容器后必须先激活已有环境：

```bash
source /usr/local/bin/activate_statebus_container.sh
cd /workspace/statebus/project
```

非交互命令示例：

```bash
docker exec -u root statebus-dev-qcrs bash -lc \
  'source /usr/local/bin/activate_statebus_container.sh && cd /workspace/statebus/project && python3 --version'
```

不要安装另一套 Python、PyTorch、vLLM 或 embedding 环境。

本次运行环境：

```text
Python: 3.11.6
LLM endpoint: http://127.0.0.1:53334/v1
LLM model: qwen3-32b
Embedding mode: local
Embedding device: cuda:1
Embedding model: /statebus/models/Qwen3-Embedding-0.6B
StatePool: /statebus/work/statepool
```

分析阶段不要重启 vLLM，也不要清理 cache、runs、workspaces 或 statepool。

## 三、最新完整实验

宿主机路径：

```text
/home/qcrs/statebus/runs/full_qwen3_extended_gpu1_20260714_135500
```

容器内路径：

```text
/statebus/runs/full_qwen3_extended_gpu1_20260714_135500
```

关键入口：

```text
summary.json
status.tsv
launcher.log / run.log（如果存在）
logs/*.log
stages/*/stdout.json
stages/*/workspaces/**/inputs/*.json
stages/*/workspaces/**/outputs/*.json
stages/*/workspaces/**/logs/*.json
stages/*/workspaces/**/logs/rendered_llm_requests/*.json
stages/*/runtime/**/telemetry/*.jsonl
stages/*/runtime/benchmark_reports/*
latency_repeat_summary.json
tag_baseline_audit.json
```

计划矩阵已完整记录：

| Stage | 状态 | 目的 |
| --- | --- | --- |
| 00_preflight | pass | 环境、服务、配置和依赖检查 |
| 01_pytest_v2 | pass | v2 回归测试 |
| 02_compare_full | pass | StateBus 与 external text system compare |
| 03_replay_full | fail | formal replay bootstrap/target |
| 04_continuous_csv_full | pass | CSV 10轮连续任务 |
| 05_continuous_cross_full | pass | cross-period 10轮连续任务 |
| 06_formal_full | pass | 25 cases / 5 families / L0-L3 |
| 07_formal_subprocess_uds_full | pass | subprocess + UDS formal |
| 08_genericity_holdout | fail | no-hint、Planner ablation、paraphrase和taint gate |
| 09_prefix_shared | pass | shared evidence prefix probe |
| 10_prefix_independent | pass | independent prefix对照 |
| 11_carrier_compare_full | pass | carrier / transport compare |
| 12_compare_repeat_2 | pass | serialized compare repeat |
| 13_compare_repeat_3 | pass | serialized compare repeat |
| 14_latency_repeat_aggregate | pass | 三轮 latency 汇总 |
| 15_tag_baseline_audit | pass | 当前实现与历史 tag 审计 |

`recorded_stage_count=16`、`matrix_complete=true`，所以这次不存在旧 run 的 fail-fast 截断问题。`overall_ok=false` 是因为 Stage 03 和 Stage 08失败，不能把它概括成“完整实验通过”。

## 四、两个失败点的已知表面信号

下面只作为分析入口，不能直接当根因结论。

### 4.1 Stage 03 Replay

launcher 报错：

```text
replay gate failed: L3 retriever calls 10/25
```

原始 `stdout.json` 表面显示：

- 25/25 quality pass；
- `exact_replay=15`；
- `validated_replay=10`；
- Retriever/Executor/Summarizer 各总调用 10 次；
- exact replay case 中三个下游角色可能为 0 调用；
- validated replay case 仍执行三个下游角色；
- `skipped_step_count` 汇总为 40。

必须判断：

- 10/25 Retriever calls是否恰好是15个 exact replay带来的真实减算；
- launcher gate是否仍按旧 validated-replay预期错误要求25次调用；
- exact replay是否真实恢复经过验证的历史 output/artifact；
- `skipped_step_count=2`、Agent call reduction、LLM call reduction和artifact reuse是否一致；
- 为什么某些 exact replay case可能出现 `planner_call_count=1`、`llm_call_count=0`、但仍有 Planner token字段；
- `answer_restoration_replay_count`、`artifact_reuse_count`、output hash和replay class是否一致；
- 失败应判为能力失败、gate陈旧、指标冲突还是混合问题。

不要因为 quality 25/25 就忽略 replay真实性，也不要因为 stage fail 就否定可能存在的真实 exact replay收益。

### 4.2 Stage 08 Genericity

表面信号：

- 4/4 primary case quality pass；
- 4/4 `route_hints_enabled=0`；
- 4/4 Planner semantic plan valid；
- 4/4 Planner behavioral effect为真；
- 四类 Retriever consumed hash均有记录；
- disabled/perturbed Planner ablation均完成；
- cross-family objective differentiation通过；
- 4组 original/paraphrase中有1组 semantic equivalence失败；
- actual rendered request taint audit记录48个 violation；
- no-hint preferred candidate absence显示通过；
- claim boundary明确仍是预编译 `CanonicalTaskSpec`，不证明自由文本 spec compilation。

必须逐条读取 `prompt_taint_audit` violations 和对应四角色 rendered request：

- violation命中了哪个 role、artifact、字段和值；
- 是真实把 expected answer/route/tool/candidate泄漏给不应看到的角色；
- 还是 Runtime合法地把已经确定的 route/tool交给 Executor；
- 还是审计器没有按角色区分合法下游合同；
- 48个是48个独立问题，还是少数字段在多次 ablation/request中重复计数；
- 1个 paraphrase equivalence失败是模型语义漂移、比较器过严、hash规则错误还是实际 objective改变；
- `ok=false`由哪些精确 gate共同造成。

不能预设 taint scanner一定正确或一定误报。用实际请求内容、角色职责和代码 gate逐项判定。

## 五、分析方法和 Python 数据账本

优先新增或扩展一个 Python 分析脚本：

```text
scripts/analyze_full_qwen3_extended_matrix_20260714.py
```

脚本应静态读取 artifacts，不要导入会执行 Runtime或修改状态的模块。至少做到：

1. 递归枚举全部文件并统计 JSON、JSONL、log、workspace和报告数量；
2. 容错解析 JSON/JSONL，记录每个 parse error、空文件和缺字段；
3. 建立 stage/layer/family/case 主表；
4. 区分 StateBus workspace、bootstrap workspace、ablation workspace和external baseline case；
5. 收集每个 case 的 quality、route、tool、Agent/LLM调用、tokens、latency、state refs、memory/replay、prefix、LogitState、Planner和artifact完整性；
6. 对计数类字段求和，对比率字段使用原始 numerator/denominator重算，禁止直接把 per-case rate相加；
7. 对 stdout summary、task_metrics、telemetry、result和audit sidecar做交叉校验；
8. 输出所有异常case列表和证据路径；
9. 输出结构化 JSON，报告从该 JSON生成或引用；
10. 任何无法从 artifact恢复的字段明确标记 unavailable，不猜测。

每条 case至少保存：

```text
stage
suite/lane
layer
registry family
runtime task family
task_id
workspace_root
quality gate和失败原因
route/tool/candidate
Planner/Retriever/Executor/Summarizer call count
LLM call count及分角色tokens/latency
rendered request artifact和hash
semantic plan source/valid/equivalence/behavioral effect
model/fallback/effective/consumed hashes
retrieval candidate/selected/evidence bytes
semantic state publish/transfer/storage kind
prefix estimate和observed counter delta
LogitState字段
memory match/replay class/artifact reuse/strategy reuse
skipped steps和真实调用减少
output artifact/hash/verification state
UDS/subprocess/carrier证据
异常和缺失字段
```

## 六、Stage-by-stage 严格审计

对16个 stage逐个报告：

1. 实际执行范围和命令/配置；
2. case、family、layer、lane、round和repeat数量；
3. quality、route/tool、Agent调用和异常；
4. 关键token、时间、通信、state、memory和prefix指标；
5. pass/fail gate的代码定义；
6. gate是否与stage目的匹配；
7. 该stage能支持的最强声明；
8. 该stage不能支持的声明；
9. 指标缺陷、fallback或宽松汇总风险。

特别检查：

- Stage 00只证明环境可用，不能当端到端LLM成功；
- Stage 01具体通过多少测试，warning是否影响结论；
- Stage 02/12/13是否同case、同模型、同顺序且可重复；
- Stage 03 bootstrap和target是否使用独立且正确的history roots；
- Stage 04/05 Round 2+是否真实消费Round 1或指定前序产物；
- Stage 06 L0-L3究竟改变了哪些开关，是否为单变量消融；
- Stage 07是否真实 `subprocess.Popen + AF_UNIX + typed Protobuf`，是否有PID/socket/lifecycle证据；
- Stage 08四类ablation实际运行量、prompt和gate；
- Stage 09/10是否使用相同请求、顺序控制、counter delta和TTFT定义；
- Stage 11 carrier两侧任务、payload、模型、质量和执行语义是否等价；
- Stage 14是否正确聚合三次serialized compare，而非重复读取同一run；
- Stage 15 tag audit覆盖了哪些函数/行为，pass是否只表示脚本成功。

## 七、Compare、重复时延与公平性

不要只报告token差值。检查 StateBus 和 external text 两侧是否使用：

- 相同25 cases和5 families；
- 相同Qwen3-32B；
- 相同输入语义和可见evidence；
- 相同质量门和expected-fact scorer；
- 等价的Planner/selection JSON schema；
- 等价的route/tool闭集；
- 等价的工具能力和执行实现；
- 相同的角色数、LLM请求数、temperature和max tokens；
- 公平的warm cache和运行顺序。

分别给出：

- quality pass；
- prompt/completion/total token；
- per-case token胜负；
- latency mean/median/p90/p95/std或可恢复的分布；
- 三次serialized repeat的一致性；
- StateBus/external每次先后顺序是否造成cache或服务负载偏差；
- carrier-only attribution是否成立；
- system-level first-pass compare是否成立。

如果schema、prompt和执行实现仍不等价，只能声明系统级比较，不能把全部收益归因于Protobuf、shared memory或KV。

## 八、L0-L3 和 Agent真实贡献

### 8.1 L0-L3

从代码和artifact列出每层实际开关：

- text/structured handoff；
- semantic pruning；
- shared memory semantic state；
- memory/replay；
- prompt layout；
- Runtime helper和tool路径。

判断哪些层对比是有意义的机制消融，哪些同时改变多个变量。按layer和family报告quality、tokens、task time、control bytes、state transfer和reuse。

### 8.2 每个 Agent 的五层证据

对 Planner、Retriever、Executor、Summarizer分别区分：

1. 被调用；
2. LLM真实生成数据；
3. 数据被保存/透传；
4. 数据被下游读取；
5. 数据真正改变行为或避免计算。

重点分析：

- Planner bounded SemanticTaskPlan是否由模型生成，哪些字段来自fallback；
- 四类retrieval objective是否不同并被对应Retriever消费；
- disabled/perturbed ablation是否证明Planner有行为贡献；
- Retriever是LLM选择证据还是固定pipeline完成主要工作；
- Executor LLM负责route/tool选择到什么程度，CodeAct/工具执行有多少是deterministic helper；
- Summarizer输出是否来自LLM，是否被memory或后续round真正消费；
- exact replay时哪些Agent应该不调用，哪些call metric可能被覆盖或误计；
- 是否存在“增加调用计数但输出不被消费”的角色；
- 如果去掉某个Agent，质量/行为是否有实验支持。

不能用“四角色call count均为1”自动证明四角色都有贡献。

## 九、Planner专项审计

当前实现声称 Planner 已从旧的payload透传升级为 bounded semantic planning。核验最新run中：

- `objective_source`分布；
- `planner_model_generated_field_count`；
- `planner_fallback_field_count`；
- `planner_model_downstream_consumed_field_count`；
- `planner_downstream_consumed_field_count`；
- model/fallback/effective plan hash；
- 四类Retriever consumed objective hash；
- `planner_behavioral_effect`；
- schema validity和semantic equivalence；
- disabled/perturbed ablation；
- route/tool是否仍由安全闭集控制。

检查指标语义是否诚实：

- `planner_generated_retrieval_objective_count`是否与真实model fields一致；
- hybrid是否被误写成model generated；
- behavioral effect是否只比较hash，还是确实改变query/filter/evidence；
- perturbed objective改变hash但selected evidence完全不变时，应如何解释；
- quality保持不变能否说明Planner有用，还是说明Planner对结果不敏感。

继续保留边界：当前holdout仍基于预编译 `CanonicalTaskSpec`，不等于自由文本直接编译完整任务合同。

## 十、KV Prefix、Semantic State 与 LogitState

### 10.1 KV Prefix

严格区分：

- shared evidence prompt layout；
- prefix identity/cache affinity/scheduling；
- `neural_prefix_*_estimate`；
- vLLM task-local block query/hit counter delta；
- service-lifetime hit-rate gauge；
- TTFT；
- KV tensor store/load/transfer；
- hidden state。

分析：

1. 各stage/layer/family的estimate和observed字段分布；
2. counter delta available/valid比例和异常范围；
3. 用 `sum(hit_delta)/sum(query_delta)`重算，检查summary是否错误累加per-case rate；
4. Stage 09/10 shared与independent请求、顺序、质量和长度是否匹配；
5. shared prefix的真实block hit和TTFT差异；
6. 是否有warmup、顺序效应、服务中其他请求和跨stagecache污染；
7. prefix feedback是否真实改变continuous scheduling；
8. 是否证明full StateBus E2E收益，还是仅独立probe中的engine-local收益；
9. 是否存在KV tensor被StateBus导出、传输或持久化。

正确结论边界应明确：当前最多证明同一vLLM engine内的prefix reuse及其局部时间效果；不能写成Agent间KV tensor handoff。

### 10.2 Semantic State

检查 embedding/semantic state：

- producer是谁；
- shared memory中真实保存什么；
- `SemanticStateRef`如何传递；
- Retriever/Executor是否读取；
- 是否改变evidence selection或减少文本；
- publish/transfer count与实际对象数、bytes和fallback是否一致；
- L2/L3相对L1的消融是否足以支持收益声明。

### 10.3 LogitState

`LogitStateRef`是top-logprobs派生摘要，不是hidden state或KV。汇总：

- transfer count；
- entropy、aggregated/mean命名、varentropy、top gap；
- peak position、sequence length、decision entropy；
- 零值、常数值、缺失和异常范围；
- exact replay case为何没有LogitState；
- 是否持久化原始top-logprobs，能否离线重算；
- `logit_confidence_gate_trigger_count`是否触发；
- 是否改变route/tool/retry/evidence/fallback。

如果只记录不消费，应判为“非文本决策侧信道和可观测性原型”，不能宣称已经改善质量或效率。

## 十一、Memory、Replay 和连续任务

严格区分：

- memory match；
- assist reuse；
- artifact reuse；
- strategy reuse；
- validated replay；
- exact replay；
- output restoration；
- skipped runtime steps；
- skipped Agent/LLM/tool calls；
- reuse gain。

分析 Stage 03、04、05：

1. bootstrap与target、Round 1与Round 2+是否使用正确且不同的历史状态；
2. history runtime root是否可能跨stage/case污染；
3. compatibility signature、artifact hash、evidence identity和replay gate是否合理；
4. exact replay是否直接复用verified artifact/output；
5. validated replay是否仍重新执行Agent和工具；
6. `skipped_step_count`是否与真实call reduction一致；
7. output hash是否与source artifact一致；
8. 第二轮是否真实消费第一轮产生的memory/artifact/strategy；
9. CSV与cross-period的reuse语义是否不同；
10. L0-L3是否共享history而破坏memory ablation；
11. Stage 03失败gate应如何修正且不会放宽真实性。

## 十二、UDS、Carrier、CodeAct 和系统实现

### 12.1 UDS/Subprocess

验证 Stage 07 是否真正经过：

```text
subprocess.Popen
AF_UNIX socket
typed Protobuf request/response
外部Executor process
```

检查普通formal与UDS formal的case、model、embedding、quality和output hash是否一致。分析时间变化，但repeat=1时不要声称稳定overhead或speedup。指出PID/socket/transport lifecycle可观测性是否充分。

### 12.2 Carrier Compare

分析 Stage 11究竟比较 text、protobuf、UDS、shared memory还是其他carrier。检查payload语义、任务、执行逻辑和质量是否等价。判断能支持“结构化carrier降低通信开销”还是仅支持“两个系统profile的结果差异”。

### 12.3 CodeAct和Sandbox

检查：

- LLM是否真实生成Python/plan；
- deterministic helper占比；
- tool registry和action contract；
- subprocess/resource sandbox；
- `bwrap`、fallback和none计数；
- 当前能否宣称安全CodeAct或只能宣称bounded execution prototype。

## 十三、答案泄露、特化和“钻空子”审计

这是报告的重点，不能只依赖一个taint count。

### 13.1 扫描实际LLM请求

读取 Planner、Retriever、Executor、Summarizer全部 rendered request artifacts，按角色职责区分：

- expected facts/values；
- expected route/tool；
- candidate key/preferred candidate；
- case id/sample id；
- scorer字段和quality checks；
-答案、目标数值或其同义表达；
- Runtime已验证后合法交给Executor的route/tool；
- Retriever产出后合法交给Executor/Summarizer的evidence。

字段名扫描和值扫描都要做。相同violation跨ablation重复出现时去重并保留频次。

### 13.2 CanonicalTaskSpec和固定任务

分析角色实际能看到哪些预编译字段：

- intent_op；
- required tools/outputs；
- route/tool hints；
- target entities/time scope；
- quality checks；
- expected facts。

判断它们是正常任务合同、强先验还是非法oracle。Genericity只改request text但保留预编译spec时，不能宣称自由文本任务理解泛化。

### 13.3 Case特化和固定闭集

搜索代码中的：

- case id分支；
- sample id；
-固定答案；
- expected route/tool映射；
- corpus metadata直接决定答案；
- family专用fallback；
- scorer信息进入角色prompt；
- route/tool enum使模型只需复制唯一候选。

同时检查实验层面的“隐式钻空子”：

- external baseline被人为设置得更难；
- StateBus使用内部helper而baseline使用公开工具；
- fallback保证quality但掩盖LLM失败；
- pass gate只看字段存在，不看来源和消费；
- telemetry rate被错误求和；
- stage顺序共享warm cache；
-历史目录或CAS污染；
- exact replay source与target其实完全同题，导致结论过强。

发现这些问题时区分：合理的系统约束、实验局限、指标缺陷和真实作弊风险。不要为了“严格”把合法typed contract也一律判成泄露。

## 十四、赛题要求与创新点评估

根据题目逐项建立覆盖矩阵：

| 赛题维度 | 需要分析的证据 |
| --- | --- |
| >=3 Agent / >=3 task type | 四角色真实作用、5 family覆盖 |
| 结构化通信 | action/args/result/capability、Protobuf、UDS |
| text vs structured | compare和carrier公平性 |
| 非文本状态 | embedding/shared memory、是否真实消费 |
| 共享记忆 | store/search/reuse、exact/validated、真实减算 |
| 两组连续任务 | CSV和cross-period 10轮依赖 |
| 性能展示 | token、bytes、TTFT、E2E、state bytes、hit/reuse |
| 系统完整性 | Runtime、protocol、statepool、memory、eval、fallback |
| openEuler | 当前容器路径与尚缺的交付验证 |
| CodeAct | bounded execution和sandbox边界 |

对当前创新点逐一给出评价：

- typed Protobuf + UDS control plane；
- Ref registry和多数据面；
- shared-memory semantic state；
- CanonicalEvidencePack/HydrateManifest；
- bounded SemanticTaskPlan和四类objective；
- dynamic evidence pruning；
- engine-local shared prefix、feedback和task-local counter；
- LogitState；
- artifact/memory/replay；
- exact replay identity；
- subprocess UDS；
- bounded CodeAct。

每项都按以下五级证据回答：

1. 代码存在；
2. 实验路径执行；
3. 产生真实数据；
4. 下游真实消费并改变行为；
5. 有公平A/B证明质量或效率收益。

说明哪些是赛题强创新、哪些只是工程完整性、哪些目前只有原型或telemetry、哪些可能被评委质疑。

评分项可做证据充分度分析，但不要伪造确定竞赛分数：

- 通信效率 25；
- 状态传递创新 20；
- 记忆复用 20；
- 系统完整性 20；
- 实验验证 15。

## 十五、结论分级

所有重要结论必须放入以下类别之一：

- 最新实验已证明；
- 代码实现支持但本次没有充分实验；
- 只有估算或proxy指标；
- diagnostic evidence，不能升级为formal claim；
- 指标、gate或实验存在缺陷；
- 当前不能宣称。

特别禁止：

- 把stage pass直接写成机制有效；
- 把LogitState写成hidden state；
- 把prefix reuse写成Agent间KV tensor transfer；
- 把memory match写成exact replay；
- 把`skipped_step_count`直接写成少一次Agent调用；
- 把预编译spec paraphrase写成自由文本泛化；
- 把一次latency结果写成稳定性能优势；
- 把四角色调用数写成四角色行为贡献。

## 十六、输出产物

建议产物：

```text
scripts/analyze_full_qwen3_extended_matrix_20260714.py
docs/improvement/20_v2_comprehensive_truth_audit_20260706/46_full_qwen3_extended_matrix_audit_20260714.json
docs/improvement/20_v2_comprehensive_truth_audit_20260706/46_full_qwen3_extended_matrix_audit_20260714.md
docs/improvement/20_v2_comprehensive_truth_audit_20260706/47_failure_root_cause_and_optimization_plan_20260714.md
```

先输出结构化 JSON，再写 Markdown 报告。报告至少包括：

1. 执行摘要；
2. 数据完整性和分析方法；
3. 16-stage结果表；
4. layer/family/case统计；
5. Stage 03失败根因；
6. Stage 08失败根因；
7. compare和三次latency repeat；
8. L0-L3消融；
9. 四Agent真实贡献；
10. Planner专项；
11. SemanticState/KV Prefix/LogitState；
12. memory/replay/continuous；
13. formal/UDS/carrier/CodeAct；
14. 泄露、特化和实验漏洞；
15. 赛题覆盖和创新证据矩阵；
16. 当前可宣称与不能宣称；
17. P0/P1/P2问题清单；
18. 最小修复方案；
19. 最小验证矩阵；
20. 是否需要重跑单stage、targeted matrix或full matrix。

每个P0/P1/P2问题写清：

- 现象；
- 根因；
- artifact证据；
- 代码位置；
- 对结论的影响；
- 最小修复；
- 回归风险；
- 修复后最小测试。

## 十七、完成标准

完成前自检：

- 16/16 stage都分析，不遗漏pass stage；
- 所有case和JSONL均已递归统计；
- 比率均由numerator/denominator重算；
- 两个失败都有case级根因；
- Agent贡献不是由call count推断；
- taint violation逐role分类；
- estimate与observed counter严格分开；
- compare公平性和latency重复性均分析；
- 每个赛题要求有代码和实验两层证据；
- 所有重要结论有路径、字段、case和代码引用；
- 没有修改Runtime或重新运行full suite。

最后暂停并向用户汇报：最可信的结果、两个失败的真实性质、最严重的实验/实现缺口、当前创新中真正成立的部分、最小修复范围和建议验证顺序。

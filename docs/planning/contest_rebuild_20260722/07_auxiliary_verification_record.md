# 07 辅助核对、状态影响与待授权探针记录

> **事实来源**：2026-07-22 在当前 worktree 完成的源码/manifest/log/进程只读核对、33 项 focused tests、local tokenizer fixed fixtures、临时 shared-memory fixture，以及本文件列出的官方资料。
> **设计假设**：这些最小核对只用于确认当前接口、fixture 行为和未知项；未保存的 terminal-only fixture 不能替代 future committed regression fixture。
> **待验证实验**：未执行 `/metrics` probe、`top_logprobs` capability request、cold cache/restart、P-A/P-B/P-C、L-A/L-B/L-C/L-D、R0-R12 或任何正式质量/性能实验。

文档导航：[索引](README.md) | [00 决策与包装](00_executive_decision_and_packaging.md) | [01 现状与整改](01_current_state_and_remediation.md) | [02 Prefix](02_prefix_engine_local_reuse_design.md) | [03 LogitState](03_logitstate_core_chain_design.md) | [04 数据与任务](04_vertical_data_preprocess_and_task_design.md) | [05 实验](05_experiment_matrix_metrics_and_statistics.md) | [06 实施与验收](06_implementation_plan_and_acceptance.md) | [07 辅助核对](07_auxiliary_verification_record.md)

## 1. 范围、环境与状态枚举

核对窗口为 2026-07-22，时区 `Asia/Shanghai`，工作目录 `/home/qcrs/statebus/project`，分支 `feat/native-latent-alignment`。开始和结束前均确认存在用户拥有的 latent/alignment 未提交改动；本轮没有改动、回滚或暂存这些文件。

状态枚举：

| 状态 | 含义 |
| --- | --- |
| `checked_static` | 只读文件/API contract/manifest/fixture 已核对 |
| `checked_local_fixture` | 本地 deterministic 进程运行；不调用模型服务 |
| `not_checked` | 没有足够输入或不值得扩大本轮范围 |
| `authorization_required` | 会发模型请求、改变服务/cache、下载数据或运行正式实验 |
| `operational_confirmation_required` | 动作技术上只读，但需确认当前服务观察窗口和归属 |

总边界：

- 没有向任何模型发请求；没有调用 completion/chat/embedding endpoint。
- 没有对 `127.0.0.1:53334` 发 HTTP GET/POST；特别是没有读取 `/metrics`。
- 没有启动、停止、重启、替换或重新配置当前 vLLM 服务，没有清理 cache epoch。
- 没有下载/改造正式数据，没有修改源码、测试、manifest、既有 artifact 或 run root。
- pytest 只执行 focused contract tests；未运行 formal suite。shared-memory fixture 只创建临时本地 segment，完成后 unlink。
- 下列观察不能成为性能、质量、泛化、实际 GPU hit 或 Logit gate 有效性结论。

## 2. 核对总览

| ID | 待确认问题 | 状态 | 接触模型/服务 | 对设计的影响 |
| --- | --- | --- | --- | --- |
| V0 | 当前代码/证据分类是否与 readiness audit 一致 | `checked_static` | 否 | 形成 [`01`](01_current_state_and_remediation.md) D0 登记册 |
| V1 | 当前 Prefix/Logit/Ref focused contracts 是否仍可运行 | `checked_local_fixture` | 否 | 保留骨架，不能升级为收益 |
| V2 | 五个指定 continuous manifests 是否能被 current loader 读取 | `checked_local_fixture` | 否 | 现有数据可作 dev/diagnostic；业务层级仍降级 |
| V3 | `kv_prefix_reuse_v1` 三种顺序是否 dependency-safe、affinity 是否可区分 | `checked_local_fixture` | 否 | 证明 fixture 可支持 future scheduler tests，不证明 APC |
| V4 | 现有 layout 经本地 Qwen3 tokenizer 后 exact-token关系如何 | `checked_local_fixture` | 否 | common intersection 必须显式构造；token count/layout必须冻结 |
| V5 | generic StateStore 能否以 shared memory 发布/读取/释放 8-byte float payload | `checked_local_fixture` | 否 | Logit store可复用机制，但需 terminal tombstone专用语义 |
| V6 | 当前服务版本/启动参数是否提供 future capability 背景 | `checked_static` | 只读进程/包/日志；无 endpoint | 仅支持“APC启动参数存在”；formal config仍必须 latent off |
| V7 | Prefix metrics、calibration、selective risk、数据 terms 是否有官方依据 | `checked_static` | 外部文档 GET；无模型 | 约束指标/claim boundary，不证明本系统效果 |

## 3. V0：源码、历史证据与工作树边界

**目的**：区分 implemented/consumed/telemetry/planned/historical，避免把字段或历史 artifact 写成当前收益。

**授权**：Prompt 第 1.4 节允许的只读核对；无需服务或模型授权。

**命令/输入范围**：以 `rg`、`sed -n`、`git status --short --branch` 读取 Prompt、AGENTS/README/constraints、canonical E0-E6 index/reports、readiness audit，以及下列当前模块：

```text
v2/state/semantic_state.py
v2/retrieval/pipeline.py
v2/runtime/smoke.py
v2/runtime/role_path.py
v2/runtime/neural_state.py
v2/runtime/logit_state.py
v2/runtime/vllm_metrics.py
v2/runtime/prefix_feedback.py
v2/benchmark/continuous_runner.py
v2/benchmark/kv_prefix_schedule.py
v2/contracts/adaptive.py
v2/refs/models.py
v2/state/store.py
```

**观察**：

- embedding `SemanticStateRef` 有 `<f4` publish、跨 PID cosine selector、selected IDs、hydration 和 release 路径，是当前非文本状态主证据。
- Prefix 的 identity/layout/registry/schedule/parser/feedback 有代码骨架；registry `cache_hit` 只表示相同 handle 复见，estimate 不是引擎观察。
- 当前 Logit serializer/Ref/telemetry 存在，但没有 active Ref -> independent numeric consumer -> bounded effect -> release 的主链；全 JSON peak entropy 不能绑定闭集业务决定。
- Memory actual consumption 已有 `RoleExecutionReceipt` 收紧方向，但历史 E3 `consumed=23` 不满足当前 headline 定义。
- 当前 dirty worktree identity 不等于 2026-07-20 E0-E6 snapshot。

**局限/不会证明**：静态可达性不证明 runtime 已执行；历史 artifact 不证明当前 commit；字段和测试不证明质量/性能。

**状态影响**：只读文件和 git metadata；未写 tracked/untracked 实现文件。设计影响已落入 [`01 §2`](01_current_state_and_remediation.md#2-d0-决定登记册)。

## 4. V1：33 项 focused contract tests

**目的**：确认本轮设计引用的现有 Ref、Logit serializer、Prefix control-plane 和 feedback parser 基础测试未明显失效。

**授权**：Prompt 允许现有 focused tests；命令不包含 live/API marker。

**实际命令**：

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q \
  tests/v2/test_contracts_and_refs.py \
  tests/v2/test_logit_state.py \
  tests/v2/test_kv_prefix_control_plane.py \
  tests/v2/test_prefix_feedback.py
```

**观察**：`33 passed in 0.71s`。按文件收集为 7 + 15 + 5 + 6 项。

**局限/不会证明**：这些测试主要验证 current serializer、Ref schema、registry/layout/schedule 和 static metrics delta；不含模型请求、跨 PID Logit consumer、真实 vLLM counters、TTFT、质量或公开数据。current tests 中名为 `cache_hit`/`transfer` 的 legacy 字段仍需按设计迁移。

**状态影响**：短命 Python/pytest 进程；可能更新 ignored `.pytest_cache`，git status 未显示 tracked test/source 变化；未触服务、GPU 或正式 run root。

## 5. V2：五个 continuous-family manifest loader

**目的**：确认 Prompt 指定的五个 manifests 对 current schema/路径/dependency validation 可读取，避免基于已失效 fixture 设计。

**授权**：本地只读 manifest/sample path 核对。

**调用/输入**：用 `v2.benchmark.continuous_task_family.load_continuous_task_family(Path(...))` 逐一加载：

```text
v2/benchmark/samples/continuous_task_families/formal_financial_reports
v2/benchmark/samples/continuous_task_families/formal_operating_metrics
v2/benchmark/samples/continuous_task_families/cross_period_financial
v2/benchmark/samples/continuous_task_families/csv_table_profile
v2/benchmark/samples/continuous_task_families/kv_prefix_reuse
```

Loader 检查 schema version、dataset path、round sequence、backward dependency、reuse contract、quality checks 和 experiment-view dependency closure；没有调用 runner。

**观察**：五个 manifest 均被 current loader 接受。

**局限/不会证明**：loader pass 不证明 source 真实、许可明确、gold 隔离、任务质量或正式垂类有效；`expected_facts` 仍是 repo-local fixture contract。ACME/BETA、disease/weather、Orion/Nova 的降级决定不因此改变。

**状态影响**：只读 JSON/样本路径；未执行 task、模型、parser rewrite 或 artifact 生成。

## 6. V3：Prefix schedule fixed fixture

**目的**：确认当前 `kv_prefix_reuse_v1` 的 explicit input/friendly/hostile order 不违反现有 dependency，并量化 fixture 的 affinity 区分度。

**授权**：本地 manifest + pure Python schedule helper；不运行 continuous task。

**调用/最小输入**：

```python
family = load_continuous_task_family(
    Path("v2/benchmark/samples/continuous_task_families/kv_prefix_reuse")
)
friendly = build_kv_prefix_schedule_plan(family, mode="cache_friendly")
hostile = build_kv_prefix_schedule_plan(family, mode="cache_hostile")
# input order 直接使用 family.rounds；三组均逐项验证 depends_on_rounds 已先出现。
```

**观察**：

| 顺序 | dependency-safe | affinity switches | max contiguous same-affinity run |
| --- | --- | ---: | ---: |
| input | 是 | 3 | 4 |
| cache-friendly | 是 | 1 | 5 |
| cache-hostile | 是 | 9 | 1 |

Current test 另固定 friendly/hostile adjacent reuse opportunities 为 8/0。

**局限/不会证明**：这是一个显式 manifest 的静态性质，不证明通用 scheduler 只从 DAG ready set 选择；不证明 engine cache resident、hit、TTFT 或 latency effect。A5 仍需 ready-set API 和 P-B。

**状态影响**：只读 manifest/source hash；没有 schedule dispatch、模型请求或 feedback state。

## 7. V4：Qwen3-32B tokenizer 与 prompt layout fixtures

### 7.1 原始定向 fixture

**目的**：区分 “metadata/shared text相同” 与 “chat-template后 exact token prefix相同”，并检查当前不同 role slice 的反例。

**授权**：只加载 `/data/models/Qwen3-32B` 本地 tokenizer；`TRANSFORMERS_OFFLINE/HF_HUB_OFFLINE`，不加载权重、不调用 vLLM。

**输入/方法**：固定 shared evidence text；分别构造 Executor/Summarizer 同 shared text 的 layout，再用当前 `apply_chat_template(..., enable_thinking=False)` 取 token IDs；另以当前角色可见 slice 的不同 shared text 构造反例。对 chat template UTF-8 bytes、shared window IDs/hash 和 full-message LCP 做 SHA-256/长度比较。

**观察**：

- chat template SHA-256 为 `a55ee1b1660128b7098723e0abcd92caa0788061051c62d51cbe87d9cf1974d8`；
- 两角色使用同一 shared text 时，比较的 44-token common window IDs/hash 相同；
- 模拟当前 Executor/Summarizer 不同 role slice 时，shared hash 不同，chat-template后 full-message LCP 只有 11 tokens。

**局限**：原始 terminal-only fixture 没有写入 repo artifact，精确 raw message arrays 未持久化；44 是该比较窗口的 token count，不是 vLLM block count或实际 cached tokens。A4 必须把 exact fixture、比较窗口边界、tokenizer/template identity 提交为 regression test 后才能成为实现验收证据。

### 7.2 可复现补充 fixture

为避免只依赖未持久化输入，又用当前 committed test 中的 shared text：

```text
Metric row: revenue_musd 2026Q1=122.4
Metric row: gross_margin_pct 2026Q1=41.2
```

调用 `compile_prefix_layout()` 生成 synthetic Executor/Summarizer suffix，再在本地 tokenizer应用相同 chat template。观察 template hash仍为上述值、`layout_plan.shared_prefix_hash` 相同、两份 full prompt token长度为 145/153、full-message LCP 为 65。该补充只说明 exact count 依赖输入和 boundary；不能拿 65 覆盖原始 44/11 反例，也不能证明 current role hydration 已对齐。

**共同状态影响**：读取本地 tokenizer JSON/config并运行 CPU tokenization；未加载模型权重、未访问网络/endpoint、未改变 vLLM cache。设计因此在 [`02 §4-§5`](02_prefix_engine_local_reuse_design.md#4-canonical-shared-prefix) 要求授权交集、最终 chat-template token hash和完整 block gate。

## 8. V5：Logit 8-byte shared-memory lifecycle fixture

**目的**：确认现有 generic `LayeredStateStore` 能承载短命 float payload，并找出专用 Logit lifecycle 仍缺的 terminal metadata语义。

**授权**：本地临时目录与 `multiprocessing.shared_memory`；不运行模型/服务。

**调用/输入范围**：以 `LayeredStoragePolicy.for_state_pool_mode("shared_memory")` 创建临时 `LayeredStateStore`，对 `object_kind="LOGIT_STATE"` 发布两个 little-endian float32 值（8 bytes），调用 `load()` 比较 payload/hash，再调用 `release()`，检查 shared-memory name不能重新打开以及 metadata path状态。

**观察**：

- selected storage 为 `shared_memory`；publish/load 的 8 bytes 和 blob hash一致；
- release 后 payload segment 已 unlink；
- generic metadata JSON sidecar 仍存在，且不是显式 terminal tombstone。

**局限/不会证明**：producer/consumer在同一核对脚本中，未证明 cross-PID consume；未创建 future `LogitStateRefV2`、grant、ConfidenceGate、action/effect receipt；两个 float也不是 calibrated candidate distribution。此观察只支持复用 store机制，不支持“LogitState transfer完成”。

**状态影响**：瞬时创建并 unlink一个本地 shared-memory segment；临时目录退出后清理。没有写 repo/statebus run root，没有接触当前服务。该差距已进入 [`03 §6`](03_logitstate_core_chain_design.md#6-生命周期进程边界和清理) 的 active -> terminal tombstone设计。

## 9. V6：当前 vLLM 进程、版本和启动参数

**目的**：确认 future Prefix/Logit capability设计面对的当前服务版本和启动背景，同时避免发送探针请求。

**授权**：只读 host process table、服务环境 package metadata和已有 launch log；不访问 endpoint。

**实际命令/输入**：

```bash
pgrep -af 'vllm|api_server|53334|Qwen3-32B'
/home/qcrs/statebus/conda-envs/vllm-qwen-cu121/bin/pip show vllm
rg -n 'enable_prefix_caching|enable-prefix-caching|53334' /home/qcrs/statebus/logs
```

**观察**：

- service environment 的 vLLM 为 `0.9.2`；
- 当前 PID 的命令行包含 `/data/models/Qwen3-32B`、port `53334` 和 `--enable-prefix-caching`；既有启动日志也记录 `enable_prefix_caching=True`；
- 当前进程同时带有 latent/prompt-embeds extension 参数，因此它不是本设计要求的 formal `latent_mode=off` freeze。

**局限/不会证明**：启动开关不证明当前 cache epoch、counter schema、request-level hit、top-logprobs response shape、服务健康或 formal isolation。没有 GET `/health`、`/models`、`/metrics`，也没有 completion request。

**状态影响**：只读进程表、package metadata和日志；没有向 PID发送信号、没有修改环境或服务状态。A0需另建正式 latent-off identity；A5/A6仍把 live capability标 unknown。

## 10. V7：官方资料与外部 source 决策依据

**目的**：约束机制语义、指标和数据使用边界，不在纸面上自创 counter/calibration/rights含义。

**授权**：只读公开网页/论文；无数据集下载、无模型请求。

**输入与观察**：

| 来源 | 核对内容 | 进入设计的位置 |
| --- | --- | --- |
| [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html) | APC复用相同 token prefix 的 engine-local KV blocks；不等于Agent间传输 | [`02 §1`](02_prefix_engine_local_reuse_design.md#1-理论边界与正式名称) |
| [vLLM Prefix Caching Design](https://docs.vllm.ai/en/latest/design/v1/prefix_caching.html) | block/hash/完整前缀与cache管理约束 | `02` exact identity/full blocks |
| [vLLM Production Metrics](https://docs.vllm.ai/en/stable/usage/metrics.html) | cached/query token counters需按当前版本/labels/units核对 | `02 §8`、`05 §5.4` |
| [Guo et al. 2017](https://arxiv.org/abs/1706.04599) | confidence calibration不能用裸阈值替代 | [`03 §8`](03_logitstate_core_chain_design.md#8-calibration-方案) |
| [Geifman & El-Yaniv 2017](https://arxiv.org/abs/1705.08500) | selective risk必须与coverage共同报告 | `03 §8`、`05 §5.5` |
| [Brier 1950 DOI](https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2) | probability forecast proper score依据 | L-A metric dictionary |
| [Kuhn et al. semantic uncertainty](https://arxiv.org/abs/2302.09664) | arbitrary token entropy与semantic correctness不同 | `03`拒绝 arbitrary JSON peak主线 |
| [filings.xbrl.org About](https://filings.xbrl.org/docs/about) / [Terms](https://www.xbrl.org/legal) | repository/source authority/hash能力与当前terms文字 | [`04 §1-§2`](04_vertical_data_preprocess_and_task_design.md#1-数据决定) |

filings 页面核对只支持选择 future source family；没有下载 filing，也没有完成 per-filing upstream rights/redistribution review。SEC页面只作 future source-disjoint备选；遇到 rate-threshold页面，不写成已取得数据。

**局限/不会证明**：官方机制文档不证明 StateBus wiring；论文不证明本 feature有预测力；repository terms不替代每个source ledger和review。网页内容会变化，A2必须保存terms snapshot hash。

**状态影响**：只读网络请求/页面阅读；未写 raw data、dataset、manifest或artifact。

## 11. 明确未执行的探针与实验

| ID | 未执行动作 | 状态/所需授权 | 若未来执行的最小输入 | 只允许形成的结论 |
| --- | --- | --- | --- | --- |
| N1 | `GET http://127.0.0.1:53334/metrics` | `operational_confirmation_required`；本轮即使只读也未访问 | 一次 snapshot；无 completion；记录version/time/labels/units | counter schema `available/unavailable`，不是 hit/effect |
| N2 | `top_logprobs` capability probe | `authorization_required`，因为会发模型请求并改变服务/cache | 一个 frozen closed-alias request，最多一次，不重试迎合 | response field/position `available/unavailable` |
| N3 | cold cache、restart、cache clear或新 epoch | `authorization_required`，会改变共享服务状态 | 预注册restart/reset命令、owner、epoch UUID、恢复计划 | cold epoch validity，不是性能优势 |
| N4 | P-A quality、P-B/P-C | `authorization_required`，成组模型/正式实验 | [`02 §12`](02_prefix_engine_local_reuse_design.md#12-p-ap-bp-c-preregistration) frozen plan | 对应gate的actual result，失败保留 |
| N5 | L-A数据生成、L-B/C/D live | `authorization_required`；calibration/模型/GPU成本 | [`03 §13`](03_logitstate_core_chain_design.md#13-l-al-bl-cl-d-preregistration) frozen plan | lifecycle/calibration/quality-cost各自结论 |
| N6 | R0-R12/L0-L3 formal suite | `authorization_required` | [`05`](05_experiment_matrix_metrics_and_statistics.md) frozen data/config/order/run roots | 逐claim matrix结论，不做跨gate归因 |
| N7 | 公开 filing下载/freeze | `authorization_required`；网络、rights、storage | A2 source roster/terms/retriever version | provenance gate；不提前称外部泛化 |
| N8 | openEuler final validation | `authorization_required`；目标容器/主机资源 | A9 clean image + frozen artifacts | 本版本delivery validation only |

没有执行项不得在后续报告中从 `unknown` 自动变成 `pass`。尤其，当前服务启动了 APC不等于 N1/P-B 通过；当前 client请求字段存在不等于 N2可用；本地 shared-memory fixture不等于 L-B完成。

## 12. 状态影响总账与本轮结论边界

| 影响面 | 实际影响 |
| --- | --- |
| tracked source/tests/manifests/data/artifacts | 无修改 |
| 用户 latent/alignment dirty changes | 未触碰、未回滚、未暂存 |
| pytest/cache | 33个focused tests；可能有ignored pytest cache |
| local filesystem | tokenizer只读；Logit fixture临时目录；payload已unlink，临时sidecar随目录清理 |
| current vLLM PID/service/cache | 仅进程表/package/log读取；无HTTP、signal、restart、request |
| GPU/model weights | 未加载模型权重、未发推理；本地 tokenizer CPU only |
| external network | 只读官方文档/terms；无filing数据下载 |
| formal evidence state | 未创建run root，所有R/P/L/A gates仍未执行 |

本轮辅助核对只支持三项设计判断：现有 Prefix/Logit骨架可作为未来修改起点；当前 role layout不能被假定为 exact shared prefix；generic shared-memory store仍需专用 Logit contract、独立consumer和terminal lifecycle。它不支持任何性能、质量、实际cache hit、Logit收益或企业泛化结论。

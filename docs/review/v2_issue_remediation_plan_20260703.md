# StateBus v2 问题审计与整改计划

日期：2026-07-03

适用仓库：`/home/qcrs/statebus/project`

当前分支：`feat/statebus-v2-container-runtime`

本文用途：

- 作为后续优化、修复、补证据、写最终报告和演示材料的工作底稿。
- 只写当前问题、证据边界、修复方案和验收标准。
- 不作为宣传稿；任何没有 artifact 或代码事实支撑的内容，都按未完成或不可 claim 处理。

## 0. 证据源与当前前提

### 0.1 优先证据源

本文件以 `v2` 最新 API evidence 为主，不用旧 host-mainline 报告覆盖新事实。

主要 evidence：

- API evidence root：`/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352`
- formal suite：`/home/qcrs/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-formal-suite.json`
- internal carrier compare：`/home/qcrs/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-carrier-compare.json`
- external compare debug：`/home/qcrs/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-compare.json`
- flagship ablation：`/home/qcrs/statebus/runs/v2-live/runtime/flagship-ablation/benchmark_reports/statebus-v2-benchmark-non-text-flagship-ablation.json`
- replay negative audit：`/home/qcrs/statebus/runs/v2-live/runtime/replay-negative-audit/benchmark_reports/statebus-v2-benchmark-replay-negative-audit.json`

主要代码和文档：

- `AGENTS.md`
- `README.md`
- `docs/reference/题目.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`
- `docs/reports/v2_api_evidence_readout_and_claim_boundary_20260702.md`
- `docs/setup/docker_dev_openeuler.md`
- `v2/benchmark/live_runner.py`
- `v2/benchmark/flagship_ablation.py`
- `v2/benchmark/continuous_runner.py`
- `v2/benchmark/external_text_baseline.py`
- `v2/benchmark/comparator_runner.py`
- `v2/runtime/smoke.py`
- `v2/runtime/replay.py`
- `v2/runtime/codeact.py`
- `v2/runtime/codeact_sandbox.py`
- `v2/state/disk.py`
- `v2/memory/models.py`
- `v2/memory/store.py`

### 0.2 已接受前提

用户说明容器已经测过。本文不再把“openEuler Docker 容器完全未验证”作为问题。

但仍保留以下边界：

- 容器测过不等于最终评审 VM 或目标机完全闭环，除非提交包里有可复现命令、日志、环境摘要和 commit hash。
- `root + compose.bwrap.yaml` 下 bwrap 通过，不等于默认非 root profile 也支持 bwrap。
- 容器内跑通不等于所有 evidence 都已和一个干净 commit 绑定。

### 0.3 当前可以稳定读的事实

- `pytest-v2`: `152 passed`
- `role_path_mode=api`
- `embedding_mode=local`
- `embedding_device=cuda:0`
- `torch=2.5.1+cu121`
- formal suite `L0-L3` quality 都是 `3/3`
- internal carrier compare：`comparison_valid=true`，`llm_total_tokens_delta=-250`，`llm_prompt_bytes_delta=-1922`，质量不降
- external compare：`comparison_valid=false`，`invalid_reason=fairness_gate_failed`，只能 debug-only
- flagship ablation：`stress_pass_family_count=4/4`
- `csv_table_profile_v1`：quality `10/10`，L2 raw evidence reduction 约 `72.13%`
- `long_doc_table_v1`：quality `10/10`，L2 raw evidence reduction 约 `72.24%`
- `csv_correlation_replay_v1`：replay admissible，quality `10/10`，`validated=8`，`exact=0`，`skipped=8`
- `long_doc_metric_replay_v1`：replay admissible，quality `10/10`，`exact=3`，`validated=5`，`skipped=11`
- replay negative audit：`audit_pass=true`，`7` cases passed
- CodeAct bwrap 在 `root + bwrap` openEuler Docker profile 下有 evidence，无 fallback
- 当前仍没有 KV cache / hidden-state handoff
- external pure-text comparator 不能作为 formal superiority claim

## 1. 总体判断

当前 StateBus v2 已经超过“能跑 demo”的阶段，具备四角色主链、结构化协议、typed semantic state、shared memory publish、连续任务、replay、bwrap CodeAct profile evidence。

但它还不是最终交付闭环。最大风险不是某一个功能完全没有，而是 claim 边界容易被写过头：

- 不能 claim external pure-text formal superiority。
- 不能 claim KV cache / hidden-state transfer。
- 不能 claim mature audit-grade replay。
- 不能 claim 默认非 root sandbox 支持。
- 不能 claim VM 级 openEuler 交付已闭环，除非最终评审环境就是已测容器且 evidence 包完整绑定。

后续优化应优先补“证据闭环、任务强度、baseline 公平性、replay 审计、文档口径”，不要继续做低收益 token 微调。

## 2. Claim 边界冻结表

| 当前 claim | 状态 | 证据 | 正确说法 | 禁止说法 |
|---|---|---|---|---|
| 四角色多 Agent | complete | formal suite metadata `role_graph=planner->retriever->executor->summarizer`；`docs/reports/v2_api_evidence_readout_and_claim_boundary_20260702.md` | API 模式下四角色主链跑通 | 已证明任意复杂任务通用多 Agent 能力 |
| 纯文本与结构化双模式 | complete | carrier compare；flagship baseline contracts | 同一 StateBus runtime 下有 internal pure-text carrier 和 structured carrier | external pure-text baseline 已公平完成 |
| 结构化通信减少开销 | complete but narrow | carrier compare `comparison_valid=true`，`llm_prompt_bytes_delta=-1922`，`llm_total_tokens_delta=-250` | L1 减少 carrier/scaffolding | L1 证明非文本状态本体收益 |
| 非文本状态传递 | complete but bounded | formal L2 `semantic_state_transfer_count=3`，`shared_memory_publish_count=3`；continuous L2 每 family `10` 次 | typed semantic state / StateRef / shared memory publish 已存在 | KV cache / hidden-state 跨 Agent 传递已实现 |
| 共享记忆与 replay | partial | continuous replay families；negative audit 7 cases | replay-admissible family 中有 exact/validated replay 和 skipped steps | 所有连续任务都能自动 replay 加速 |
| CodeAct sandbox | partial | formal/carrier artifacts bwrap count > 0 fallback 0；`docs/setup/docker_dev_openeuler.md` | root+bwrap openEuler Docker profile 下真实 bwrap 执行 | 默认非 root 或生产级沙箱已支持 |
| openEuler 交付 | partial | 用户已测容器；`docs/setup/docker_dev_openeuler.md` | openEuler Docker profile 已测，需要最终 evidence index | openEuler VM / 评审目标环境已完全闭环 |

## 3. 必须修复的问题清单

### P0-001：evidence 没有和干净 commit 强绑定

Severity：high

Finding：

当前工作树非常 dirty，包含大量 modified 和 untracked 文件。最新 evidence 虽然强，但如果无法绑定 commit、命令、环境、artifact hash，评审复现时会出现“这个 JSON 到底对应哪个代码状态”的问题。

Evidence：

- `git status --short --branch` 显示当前分支为 `feat/statebus-v2-container-runtime`，大量 `M` 和 `??`。
- 关键实现和测试大量处于 untracked：`v2/benchmark/live_runner.py`、`v2/benchmark/flagship_ablation.py`、`v2/runtime/codeact.py`、`v2/memory/`、`tests/v2/*` 等。
- 最新 evidence 位于 `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352`，但提交状态未冻结。

Impact：

- 交付复现风险高。
- 后续优化可能污染现有可用 evidence。
- 最终报告里引用 artifact 时，无法回答“评审能不能 checkout 同一版本复跑”。

Recommended fix：

1. 先生成当前状态审计包：
   - `git status --short --branch`
   - `git diff --stat`
   - `git diff --name-only`
   - `python -m pytest -q tests/v2`
   - formal suite、carrier compare、flagship ablation、replay negative audit 的 JSON path 索引
2. 清理不应提交的文件：
   - `task.zip`
   - 临时目录 `task/`
   - 个人临时文件 `some_think.md`
   - 不属于提交包的实验中间物
3. 把 v2 正式实现、测试、docs、docker profile、run scripts 纳入一次冻结提交。
4. 在 `docs/reports/` 下生成 final evidence index：
   - commit hash
   - branch
   - command list
   - environment summary
   - artifact path
   - artifact sha256
   - pass/fail summary
5. 从冻结 commit 重新跑一次最小 final suite，证明不是脏树偶然结果。

Acceptance criteria：

- `git status --short` 只剩允许存在的本地敏感配置或明确 ignore 的 run output。
- final evidence index 中有 commit hash 和 JSON artifact sha256。
- `pytest-v2`、formal suite、flagship ablation、replay negative audit 都能从冻结 commit 复跑或至少有复跑日志。

### P0-002：external pure-text comparator 未过 fairness gate

Severity：high

Finding：

external compare 仍 `fairness_gate_failed`。当前不能把 external pure-text superiority 当作正式结论。

Evidence：

- `/home/qcrs/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-compare.json`
  - `comparison_valid=false`
  - `invalid_reason=fairness_gate_failed`
  - metadata `formal_superiority_claim_allowed=false`
- `v2/benchmark/comparator_runner.py` 中 fairness gate 要求：
  - same task family
  - same role graph
  - same scoring contract
  - same quality floor contract
  - same tier
  - external formal eligible
  - external four role
  - no internal helper contamination
- `docs/reports/v2_api_evidence_readout_and_claim_boundary_20260702.md` 明确 external compare 只能 debug-only。

Impact：

- 如果答辩中 claim “StateBus 正式优于纯文本多 Agent baseline”，会被 artifact 反驳。
- 评分中的通信效率可以用 internal carrier 和 T2 讲，但 external superiority 不能作为 headline。

Recommended fix：

1. 明确 external baseline 的合同：
   - 使用同一批 task samples。
   - 同一 `quality_floor_contract`。
   - 同一 `scoring_contract`。
   - 同一四角色调用顺序。
   - 不允许调用 StateBus internal helpers、semantic selection、artifact replay。
   - 允许纯文本 baseline 使用同等可见 evidence 和同等模型。
2. 在 `v2/benchmark/external_text_baseline.py` 中补齐 formal eligibility metadata：
   - `formal_comparator_eligible=true`
   - `uses_internal_helpers=false`
   - `role_graph=planner->retriever->executor->summarizer`
   - `benchmark_tier` 与 StateBus report 一致
   - `quality_floor_contract` 与 StateBus 一致
3. 在 external lane 输出中显式记录每个角色的：
   - prompt bytes
   - prompt visible bytes
   - raw evidence bytes
   - llm call count
   - exact match / quality floor
   - contamination flag
4. 单独跑 `--suite external`，先确认 external lane 自身 `quality_floor_pass_count` 达标。
5. 再跑 compare，要求 `comparison_valid=true` 才能进入正式报告。

Acceptance criteria：

- external compare JSON 中 `comparison_valid=true`。
- `invalid_reason=""`。
- fairness manifest `pass_hard_gate=true`。
- external baseline 质量不显著低于 StateBus；否则比较不可信。

如果短期无法修复：

- final report 中只写 external comparator 为 debug appendix。
- 正式主叙事改为 internal attribution ladder + T2 isolation + continuous replay。

### P0-003：openEuler 交付证据需要从“容器跑过”变成“可复现提交包”

Severity：high

Finding：

用户已确认容器测过。问题不再是容器没测，而是最终交付需要把容器验证转化成可复现证据：镜像 target、compose profile、用户身份、bwrap profile、GPU/embedding 配置、命令、日志、artifact 必须固化。

Evidence：

- `docs/setup/docker_dev_openeuler.md`：
  - 默认 `v2` 开发容器以 root 运行。
  - bwrap 需要 `docker/compose.bwrap.yaml`，并授予 namespace/mount/network 能力。
  - 文档明确不要表述成默认低权限容器也支持 bwrap。
- evidence summary 中 CodeAct bwrap 已在 root+bwrap Docker profile 下验证，无 fallback。
- 赛题交付要求是 openEuler 24.03-LTS-SP3 能正常编译、运行、测试。

Impact：

- 如果评审使用 VM 或非 root 容器，当前 root+bwrap profile 可能不等价。
- 如果只口头说“容器测过”，没有提交 logs 和 command，复现可信度不足。

Recommended fix：

1. 增加 `docs/reports/openeuler_container_validation_20260703.md`：
   - base image：`hub.oepkgs.net/openeuler/openeuler:24.03-lts-sp3`
   - target：`core` 或 `embed`
   - profile：默认 / root / bwrap
   - user：root 或 qcrs
   - GPU：是否透传
   - Python、torch、sentence_transformers、bwrap 版本
2. 保存容器内命令输出：
   - `python3 --version`
   - `python3 -m pytest -q tests/v2`
   - `python3 -m v2.benchmark.live_runner --suite preflight ...`
   - formal suite
   - carrier compare
   - flagship ablation
   - replay negative audit
3. 把容器 evidence root 与 host evidence root 对齐：
   - container path `/statebus/runs/...`
   - host path `/home/qcrs/statebus/runs/...`
4. 如果最终评审要求 VM，不要把 Docker 证据写成 VM 证据；补跑 VM final validation。
5. 在 final report 中区分：
   - `openEuler Docker validated`
   - `openEuler VM validated`
   - `host-only validated`

Acceptance criteria：

- 有一份可打开的 container validation report。
- report 中包含命令、日志路径、artifact sha256。
- CodeAct bwrap evidence 明确写 profile：`root + compose.bwrap.yaml`。
- 如果做 VM，则 VM report 也包含同等信息。

### P0-004：共享记忆 metadata 不满足赛题一等字段要求

Severity：high

Finding：

赛题要求每条记忆至少包含记忆 ID、来源 Agent、创建时间、任务主题、摘要描述。当前 `MemoryRef` 有 `memory_id`、`source_task_id`、`summary`、`embedding_ref_id`、`metadata`，但 `source_agent`、`created_at`、`task_theme`、`tags` 等不是一等字段，部分可能藏在 metadata 或其他 ledger 中。

Evidence：

- `v2/memory/models.py`：
  - `MemoryRef` 字段包括 `memory_id`、`memory_type`、`replay_class`、`score`、`source_task_id`、`summary`、`canonical_task_spec_hash`、`artifact_ref_id`、`semantic_state_ref_id`、`embedding_ref_id`、`manifest_hash`、`metadata`。
  - 没有一等字段 `source_agent`、`created_at_ns`、`task_theme`、`tags`。
- `v2/memory/store.py` 和 `v2/state/disk.py` 的反序列化也未读取这些一等字段。
- `v2/runtime/ledger.py` 有 `created_at_ns`，但这不是 MemoryRef 自身的统一元数据合同。

Impact：

- 赛题共享记忆模块要求只能算 partial。
- 评审检查 memory JSON 时，可能认为 metadata 不完整或不可审计。
- 后续 replay 负例和记忆溯源难做。

Recommended fix：

1. 升级 memory schema：
   - `MEMORY_REF_SCHEMA_VERSION` 增加版本，例如 `statebus.memory_ref.v2`。
   - `MemoryRef` 增加：
     - `source_agent: str`
     - `created_at_ns: int`
     - `task_theme: str`
     - `tags: tuple[str, ...]`
     - `source_role_path: tuple[str, ...]` 可选
     - `producer_run_id: str` 可选
2. 更新 canonical payload：
   - 新字段进入 `canonical_payload()`。
   - `match_payload()` 至少保留 `source_agent`、`task_theme`、`tags`。
3. 更新反序列化兼容：
   - 旧 payload 缺字段时使用兼容默认值。
   - 但新写入必须填完整。
4. 更新 memory commit 创建处：
   - 当前运行生成 memory 时填 `source_agent="summarizer"` 或实际 producer role。
   - `task_theme` 从 `CanonicalTaskSpec.task_family` 或 role path task theme 取。
   - `tags` 从 sample tags / required_tools / comparison_tags 中规范合并。
5. 更新测试：
   - `tests/v2/test_memory_runtime.py`
   - `tests/v2/test_registry_store.py`
   - 新增 roundtrip 测试，确保 memory JSON 包含所有赛题字段。
6. 更新 evidence：
   - 抽样展示一个 memory commit JSON。
   - final report 中引用 memory metadata screenshot 或 JSON excerpt。

Acceptance criteria：

- 新生成 memory commit JSON 中直接可见：
  - `memory_id`
  - `source_agent`
  - `created_at_ns`
  - `task_theme`
  - `summary`
  - `tags`
- pytest 覆盖旧 schema 读取和新 schema 写入。
- final evidence report 能引用具体 memory artifact。

### P0-005：CodeAct 容易被误 claim 成“LLM 自由生成 Python”

Severity：high

Finding：

当前 CodeAct 是真实执行并有 sandbox evidence，但执行代码主要由 runtime 根据 plan/action 模板组装，不是开放式 LLM 生成 Python 程序。可以 claim “controlled CodeAct-style execution”，不能 claim “LLM 自由生成代码解决通用任务”。

Evidence：

- `v2/runtime/codeact.py`：
  - `CodeActRunner.build_plan()` 在没有 request plan 时用固定 stage/action 组装 plan。
  - `_build_script()` 生成固定 Python 脚本，执行 bundle 中的 action kinds。
  - action kinds 包括 `prepare_execution_context`、`validate_selection`、`write_candidate_summary_json`。
- `v2/runtime/codeact_sandbox.py`：
  - backend 支持 `auto`、`bwrap`、`resource`、`none`。
  - `auto` 下 bwrap 失败可 fallback 到 resource。
- artifacts 证明 bwrap 后端执行，但不证明通用 LLM 代码生成能力。

Impact：

- 过度 claim 会被代码事实反驳。
- CodeAct 是加分项，不应让它成为答辩风险点。

Recommended fix：

短期修复口径：

1. 所有文档统一写：
   - “controlled CodeAct-style execution”
   - “runtime-generated bounded Python action script”
   - “bwrap-backed execution under root+bwrap Docker profile”
2. 禁止写：
   - “LLM generated arbitrary Python code”
   - “general-purpose CodeAct benchmark superiority”
   - “production-grade sandbox”

中期增强能力：

1. 增加一个受限 LLM-code demo：
   - 让 Executor LLM 生成一个小 Python function。
   - 只允许 imports 白名单。
   - AST 检查禁止 network、subprocess、open arbitrary path。
   - 写入 tmp workspace。
   - bwrap 执行。
2. 任务选型：
   - CSV 分组统计。
   - JSON 字段校验。
   - markdown 表格解析。
3. 输出审计：
   - generated source hash。
   - AST audit report。
   - sandbox backend。
   - stdout/stderr capture。
4. 仍然不要把它变成主 benchmark headline，作为 CodeAct showcase 即可。

Acceptance criteria：

- 当前 docs 中 CodeAct claim 不再过界。
- 如果新增 LLM-code demo，则 artifact 中能看到：
  - LLM generated code text/hash
  - AST policy pass
  - bwrap backend
  - no fallback
  - output validator pass

### P0-006：replay exact / validated / assist 边界仍需更硬

Severity：high

Finding：

当前 replay evidence 已经比普通 memory assist 强，但 exact 与 validated 边界必须非常清楚。CSV replay 是 validated-only，long-doc replay 只有 `exact=3`。负例 audit 只有 7 case，且报告本身说不能 claim mature audit-grade replay，直到这些负例也跑在 persisted live history artifacts 上。

Evidence：

- flagship ablation：
  - `csv_correlation_replay_v1`：`exact_replay_count=0`，`validated_replay_count=8`，`skipped_step_count=8`
  - `long_doc_metric_replay_v1`：`exact_replay_count=3`，`validated_replay_count=5`，`skipped_step_count=11`
- replay negative audit：
  - `audit_pass=true`
  - `case_count=7`
  - cases：`exact_control`、`input_hash_changed`、`runtime_signature_degraded`、`runtime_signature_incompatible_tool`、`output_contract_changed`、`intent_changed`、`unverified_output`
  - claim boundary：不能 claim mature audit-grade replay，直到跑 against persisted live history artifacts。
- `docs/reports/v2_api_evidence_readout_and_claim_boundary_20260702.md` 明确 L3 只在 replay/headline-eligible family 中正式讲。

Impact：

- 如果把 CSV replay 说成 exact replay，会被 artifact 否定。
- 如果把 assist/history-backed reuse 说成 skipped-step reuse，会被指标否定。
- replay 是高风险 claim，需要负例和 live persisted history 共同支撑。

Recommended fix：

1. 文档统一 replay 分类：
   - `assist`：提供历史摘要或候选，但不跳步骤。
   - `validated_replay`：跳部分步骤，但重新验证输出合同。
   - `exact_replay`：runtime signature、input hash、output contract、task shape 完全匹配才允许。
2. 在 final report 中每个 family 单独列：
   - exact count
   - validated count
   - skipped step count
   - replay admissible target rounds
   - skipped reason / downgrade reason
3. 增加 persisted-live-history negative audit：
   - 先用真实 continuous replay run 产生 history。
   - 对真实 history artifact 做 mutation：
     - input hash changed
     - output contract changed
     - tool version changed
     - task intent changed
     - required output missing
     - artifact hash corrupted
     - memory metadata forged
     - timestamp/source_agent forged
     - runtime signature degraded/incompatible
   - 复跑 replay gate，确保 exact 不会误放行。
4. 增加 replay audit manifest：
   - 每个负例记录 mutation source、expected outcome、observed outcome、pass/fail。
5. 对 CSV family 保持 validated-only 读法，除非新增 exact target rounds。

Acceptance criteria：

- persisted-live-history negative audit 至少 12 个负例。
- 所有 exact downgrade 都有明确 reason。
- final report 中 CSV 不再出现 exact claim。
- long-doc exact claim 写成 “3 exact target rounds passed”，不是泛化 exact replay。

### P0-007：任务仍偏 synthetic / fixture-driven，需要增强真实感

Severity：high

Finding：

当前任务已经比 fixed-answer 更强，有 long-doc/table/CSV/continuous replay。但 formal suite family case count 只有 `3`，fixed-answer 用于机制拆分，continuous manifests 仍是 repo-local fixture。若最终报告过度声称泛化能力，会被质疑任务太 synthetic。

Evidence：

- formal suite `family_case_count=3`。
- fixed-answer family 主要用于 route/tool/fact checks。
- continuous manifests 位于 `v2/benchmark/samples/continuous_task_families/*/manifest.json`，数据是 repo-local samples。
- flagship ablation 自己也把 fixed-answer 定位为机制拆分，不是长任务 headline。

Impact：

- 实验验证说服力上限受限。
- 评审可能认为 replay 过拟合 manifest 或固定答案。
- 非文本 StateRef 的优势在 fixed-answer 上不明显，必须靠长任务支撑。

Recommended fix：

1. 不要扩 fixed-answer；优先新增 1-2 组真实感更强 continuous families。
2. 推荐新增任务族：
   - financial operating metrics family：
     - 多季度财报/经营指标 markdown + CSV。
     - 每轮问题变更实体、指标、时间范围。
     - 需要检索、表格计算、趋势总结。
   - incident / service SLO report family：
     - 日志摘要、配置片段、SLO 表。
     - 每轮要求定位不同服务或时间窗口。
3. 每组至少 10 轮，且不要直接暴露答案：
   - manifest 写 expected facts，但 prompt 不包含答案。
   - 评分器用 deterministic validator 校验。
4. 增加扰动：
   - 同义指标名。
   - 无关行/段落。
   - 表头顺序变化。
   - 数字格式变化。
   - 缺失值。
5. 每个 family 都输出：
   - L0/L1/L2/L3/T2
   - quality
   - raw evidence bytes
   - prompt visible bytes
   - semantic state transfer count
   - replay class
   - skip counts

Acceptance criteria：

- 至少新增 2 个 family，每个 10 轮。
- 每个 family 至少有 2 类数据源，例如 markdown + CSV。
- L2 相比 L1 raw evidence reduction 保持明显，且 T2 对照存在。
- 至少一个 family 支持 validated/exact replay 负例。

## 4. 应该修复的问题清单

### P1-001：T2 baseline 显示非文本 StateRef 本体优势不稳定

Severity：medium

Finding：

T2 使用同样 semantic selection 但不传 SemanticStateRef。L2 相比 T2 在四个 family 上都有 `llm_prompt_bytes` saving，但 `prompt_visible_total_bytes` 并不总是下降，raw evidence delta 都是 `0`。这说明主要收益来自 semantic selection/pruning，非文本 StateRef 本体额外收益存在但不稳定。

Evidence：

- flagship non-text stress：
  - total `llm_prompt_saved_by_state_ref_bytes=13834`
  - total `prompt_visible_saved_by_state_ref_bytes=2100`
  - `raw_evidence_delta_l2_vs_t2=0` for all stress families
- family details：
  - `csv_correlation_replay_v1`：prompt visible `-1071`
  - `long_doc_table_v1`：prompt visible `-1029`
  - `long_doc_metric_replay_v1`：prompt visible `+399`
  - `csv_table_profile_v1`：prompt visible `+2187`

Impact：

- 不能说 StateRef 本体稳定减少模型可见证据。
- 可以说 StateRef/semantic state 在 prompt packaging 和部分长任务上带来额外压缩。

Recommended fix：

1. 将 L2 拆成两个指标：
   - semantic selection gain：L1 -> T2。
   - non-text transfer gain：T2 -> L2。
2. 对 T2/L2 prompt construction 做 diff：
   - 找出 L2 prompt-visible 增加的原因，是 metadata/header/slice manifest 还是 summarizer payload。
3. 给 StateRef 加 compact receipt：
   - 只传 ref id、schema、hash、selected slice summary。
   - 避免把过多 ref metadata 放进 prompt-visible 部分。
4. 在 report 中分开展示：
   - raw evidence reduction：主要归 L2 semantic selection。
   - StateRef extra saving：只按 family 实测，不泛化。

Acceptance criteria：

- final ablation table 有 L1->T2 和 T2->L2 两列。
- 至少 3/4 continuous family 的 `prompt_visible_delta_l2_vs_t2 <= 0`，或文档解释为什么某些 family 增加。
- 不再把 T2 隔离结果写成 KV/hidden-state 证明。

### P1-002：L0/L1/L2/L3 层定义需要写入机器可读合同

Severity：medium

Finding：

当前层定义在 docs 和代码中基本一致，但 final report 如果只用自然语言描述，容易出现指标污染：L1 carrier、L2 semantic pruning、L3 replay 三类收益混在一起。

Evidence：

- formal suite metadata：`comparison_contract=same_mainline_internal_attribution_ladder`。
- flagship baseline contracts 已拆：
  - `L0_internal_pure_text_carrier`
  - `T2_text_same_semantic_selection`
  - `external_pure_text_four_role`
- `docs/reports/v2_api_evidence_readout_and_claim_boundary_20260702.md` 已说明 L1/L2/L3/T2 读法。

Impact：

- 如果报告写“StateBus 降 token”，但不说明是哪一层带来，会被认为指标污染。
- L3 replay 的 skip gain 不能算进 L2 non-text state。

Recommended fix：

1. 新增 `docs/contracts/v2_ablation_layer_contract.md` 或放入 final report：
   - L0：internal pure text carrier, full evidence, no structured control, no pruning, no replay。
   - L1：structured carrier, full evidence, no semantic pruning, no replay。
   - T2：text handoff, same semantic selection, no SemanticStateRef。
   - L2：structured carrier + semantic state/ref + pruning, no replay。
   - L3：L2 + memory/replay。
2. 在 JSON report metadata 中强制写：
   - `layer_contract_id`
   - `semantic_pruning_enabled`
   - `semantic_state_transfer_enabled`
   - `replay_enabled`
   - `structured_control_enabled`
3. final report 每个收益只归因到对应 delta：
   - L0->L1：carrier。
   - L1->T2：selection。
   - T2->L2：non-text transfer packaging。
   - L2->L3：replay/memory。

Acceptance criteria：

- 每个 ablation artifact 都有 layer contract fields。
- final evidence table 不再只给 L0 vs L3 总差异，而是按 delta 展开。

### P1-003：API timing 不能正式 claim

Severity：medium

Finding：

API timing 受网络、并发、模型服务状态影响。当前 docs 已要求 API latency claims 用 serialized benchmark reruns。当前 evidence 可读 token/bytes/quality，但不宜强 claim latency superiority。

Evidence：

- `AGENTS.md`：API latency claims 必须使用 serialized benchmark reruns，不能把 concurrent API launches 当 formal timing evidence。
- external compare debug 中 StateBus `task_ms_delta` 反而是正值，说明 timing 不稳定。
- persistence buckets 仍存在明显 stage ms。

Impact：

- 如果 claim latency 明显提升，容易被单次 API 抖动推翻。
- 评审更容易接受 bytes/tokens/quality/replay counts。

Recommended fix：

1. final report 将 timing 降级为 diagnostic。
2. 如必须讲 timing，补 serialized repeat：
   - repeat >= 5。
   - 同一模型、同一环境、同一时间窗口。
   - 不并发跑 StateBus 和 baseline。
   - 报 median/p50/p90，不只报一次。
3. 分离 runtime local stage 与 LLM wall ms：
   - control plane exchange。
   - persist and reload。
   - codeact execution。
   - llm wall。
4. 把 persistence overhead 单独列为风险。

Acceptance criteria：

- final report 不把 API timing 作为主 claim。
- timing appendix 有 repeat 和分位数，或直接标 debug-only。

### P1-004：persistence overhead 仍是运行时风险

Severity：medium

Finding：

当前 runtime 为审计和 replay 写入大量 sidecar、manifest、ledger。证据完整性强，但 persistence overhead 是成本桶，不能 claim low-overhead runtime 已成熟。

Evidence：

- formal suite telemetry 中有 `persist_and_reload_stage_ms`、`persist_bundle_write_stage_ms`、`persist_core_reload_stage_ms` 等。
- continuous evidence 中每个 family 都有数百 ms 级 persistence bucket。
- `docs/reports/v2_api_evidence_readout_and_claim_boundary_20260702.md` 明确 low-overhead optimization 未收口。

Impact：

- 系统层低开销 claim 需要区分通信 token/bytes 与 runtime IO 开销。
- 过度持久化可能抵消部分端到端耗时收益。

Recommended fix：

1. 把 persistence 做成 profile：
   - `audit_full`
   - `benchmark_balanced`
   - `fast_runtime`
2. 对每个 profile 明确保留哪些 sidecar：
   - full：全部 audit。
   - balanced：保留 summary、hash、replay ledger。
   - fast：只保留必要 manifest 和 output artifact。
3. 增加 persistence benchmark：
   - bytes written。
   - files written。
   - stage ms。
   - reload ms。
4. 不在 final claim 里说 mature low-overhead runtime，只说 communication/evidence bytes 有下降。

Acceptance criteria：

- 有 `runtime_persistence_profile` 配置和测试。
- final evidence 中有 persistence overhead 表。
- fast profile 不破坏 replay gate 所需最小 manifest。

### P1-005：Planner/Retriever/Executor/Summarizer 角色边界需固化

Severity：medium

Finding：

当前四角色主链已跑通，但 role path 中不同角色都可能看到部分 evidence 和 metadata。需要在文档和测试中固化每个角色能做什么，避免角色漂移。

Evidence：

- `v2/runtime/role_path.py` 中 planner/retriever/summarizer 都构造 prompt，并处理 tags/task theme。
- runtime telemetry 记录各角色 prompt bytes 和 hydrated bytes。
- formal suite metadata 已给 role graph，但没有单独的 role contract audit。

Impact：

- 如果 Planner 做了 Retriever 的选择，或 Summarizer 参与路由，角色分工会被质疑。
- 多 Agent 评分看重角色覆盖，不只看函数名。

Recommended fix：

1. 写 `docs/contracts/v2_role_contract.md`：
   - Planner：任务分解、retrieval objective、required outputs。
   - Retriever：candidate selection、semantic state build。
   - Executor：tool/codeact execution、artifact output。
   - Summarizer：answer synthesis、memory summary。
2. 在 telemetry 增加 role contract counters：
   - planner generated objective count。
   - retriever selected evidence count。
   - executor artifact count。
   - summarizer memory commit count。
3. 添加 role drift tests：
   - Planner prompt 不含完整 answer key。
   - Summarizer 不改变 route/tool。
   - Executor 不重新检索外部 corpus。
4. final report 中展示 role graph + 每个角色输出 artifact。

Acceptance criteria：

- 每个 role 的输入输出合同在文档和测试中可查。
- 至少一个 evidence report 展示四角色各自产物路径。

### P1-006：memory/replay 元数据可伪造的负例不足

Severity：medium

Finding：

当前 negative audit 覆盖了 input hash、runtime signature、output contract、intent、unverified output，但 memory metadata forged 还不是明确负例。补充 memory source/timestamp/task_theme/tags 后，也要验证伪造不会放行 replay。

Evidence：

- replay negative audit 7 cases 中没有 `source_agent_forged`、`created_at_forged`、`task_theme_mismatch`、`tag_mismatch`。
- 当前 `MemoryRef.metadata` 是自由 dict，schema 强约束不足。

Impact：

- 共享记忆的审计可信度不足。
- 伪造 memory metadata 可能绕过人工审阅或 future gate。

Recommended fix：

1. 先做 P0-004 memory schema。
2. replay gate 增加 metadata validation：
   - source_agent 必须在 allowed producer roles。
   - created_at_ns 必须存在且合理。
   - task_theme 与 canonical task spec 一致或兼容。
   - tags 必须与 required_tools / comparison_tags 不冲突。
3. 增加负例：
   - source_agent changed to unknown。
   - task_theme changed。
   - tags removed。
   - created_at_ns zero/future。
   - source_task_id mismatch。
4. 这些负例跑在 persisted live history artifacts 上。

Acceptance criteria：

- replay negative audit case count >= 12。
- metadata forgery 类 case 全部降级为 assist 或 invalid。

### P1-007：Docker root 文件权限污染风险

Severity：medium

Finding：

`docs/setup/docker_dev_openeuler.md` 明确当前容器默认 root 运行。代码和 runs 挂载回宿主机，root 生成的文件可能导致宿主机 qcrs 用户后续无法删除、覆盖或提交。

Evidence：

- `docs/setup/docker_dev_openeuler.md`：默认以 root 运行；挂载 `$HOME/statebus/runs`、`work`、`caches`、`models`。
- bwrap profile 也切 root 并授予额外能力。

Impact：

- 复跑或清理 artifact 失败。
- CI/pytest 因权限失败。
- 交付打包时混入 root-owned 文件。

Recommended fix：

1. 增加容器退出/验证后权限修复脚本：
   - `scripts/fix_container_artifact_ownership.sh`
   - 对 `/home/qcrs/statebus/{runs,work,caches,logs}` 执行 chown 到 `STATEBUS_UID:STATEBUS_GID`。
2. compose 中尽量保留 UID/GID 环境变量。
3. final validation 前跑权限检查：
   - find root-owned files under repo/runs/work。
4. 文档中写清 root profile 是验证 profile，不是默认开发 profile。

Acceptance criteria：

- 权限检查脚本存在。
- final evidence index 记录 root-owned file check。
- repo 下无 root-owned 源码文件。

### P1-008：文档口径存在 host-mainline 与 v2 clean-room 混淆风险

Severity：medium

Finding：

仓库保留大量 host-mainline 历史报告，部分描述 `FEATURE_BUNDLE`、SQLite+FAISS、host repeat-10、旧 runs。v2 当前主线是 clean-room container/runtime，控制面为 typed Protobuf，数据面分层，最新 evidence 是 2026-07-02 API package。最终报告必须避免混读。

Evidence：

- `docs/constraints/current_feature_scope.md` 是 host-mainline 早期长文档，包含很多 `runs/host_goal_eval_20260608_*`。
- `docs/planning/implementation_plan.md` 明确自己不再是当前实现事实层主文档。
- `docs/reports/v2_api_evidence_readout_and_claim_boundary_20260702.md` 是 v2 最新读法。

Impact：

- 最终材料引用旧 runs，会和 v2 JSON 不一致。
- 评审会质疑 evidence 是否 cherry-pick。

Recommended fix：

1. 新增 `docs/reports/final_v2_evidence_index_20260703.md`。
2. 旧报告顶部加 deprecated/历史参考说明，或在 final guide 中明确“不作为 v2 source of truth”。
3. final report 只引用：
   - v2 latest evidence。
   - v2 code paths。
   - v2 tests。
4. README 中添加“当前 v2 source-of-truth”入口。

Acceptance criteria：

- final report 不引用旧 host_goal_eval 作为 v2 主证据。
- README 有 v2 evidence index 链接。

## 5. 可选优化与小问题清单

### P2-001：formal suite case count 偏小

Severity：low

Finding：

formal suite `family_case_count=3`，适合作为 smoke/formal-first-pass，不足以单独支撑强泛化结论。

Fix：

- 保留 formal suite 为稳定门。
- 把连续任务和 replay family 作为主实验。
- 如有时间，把 formal financial family 扩到 6-8 cases。

Acceptance criteria：

- final report 明确 formal suite 是 gate，不是唯一实验。

### P2-002：long-doc exact replay 数量偏少

Severity：low

Finding：

`long_doc_metric_replay_v1` 有 `exact=3`，足以证明 exact replay path 存在，但不足以 claim mature exact replay。

Fix：

- 增加 exact target rounds 到 4-5。
- 保持 validated rounds 混合存在，避免为 exact 过度特化。

Acceptance criteria：

- exact count >= 4，且负例仍能 downgrade。

### P2-003：CSV replay validated-only 要诚实标注

Severity：low

Finding：

`csv_correlation_replay_v1` `exact=0`，但 `validated=8`、`skipped=8`。它是 validated replay 证据，不是 exact replay 证据。

Fix：

- final table 单独列 CSV replay：`validated-only`。
- 不在口播中说“两组 exact replay”。

Acceptance criteria：

- final report 中 CSV family 的 replay class 写为 validated-only。

### P2-004：StateRef 大小和传递次数可视化不足

Severity：low

Finding：

现在有 `semantic_state_transfer_count`、`shared_memory_publish_count`，但 final 材料需要更直观展示 StateRef 本体不是字符串 ref。

Fix：

- 从 artifact 中抽一个 `SemanticStateRef` manifest。
- 展示 ref id、schema、hash、storage kind、selected evidence summary、embedding dim。
- 补一张 “text payload vs StateRef manifest + shared memory object” 表。

Acceptance criteria：

- final report 有 StateRef artifact excerpt。

### P2-005：演示视频材料需要围绕边界设计

Severity：low

Finding：

演示如果只展示“跑完了”，不能体现系统机制。需要展示 L0/L1/L2/L3/T2 的差异和不能 claim 的边界。

Fix：

视频建议结构：

1. 30 秒：赛题要求与 StateBus 三层机制。
2. 60 秒：跑 preflight/formal。
3. 60 秒：打开 JSON 看 L0/L1/L2/L3 指标。
4. 60 秒：展示 continuous family raw evidence reduction。
5. 60 秒：展示 replay exact/validated 和 negative audit。
6. 30 秒：展示 bwrap CodeAct profile。
7. 30 秒：明确不能 claim KV/external superiority。

Acceptance criteria：

- 演示材料引用 final evidence index，不临时口头报数。

## 6. 后续优化优先级路线

### 6.1 必须做，才能稳交付

1. 冻结仓库和 evidence
   - 清理 dirty/untracked。
   - 提交 v2 代码、测试、文档、docker profile。
   - 生成 final evidence index。

2. 生成 openEuler container validation report
   - 用户已测容器，把结果固化为文档和 artifact。
   - 明确 root+bwrap profile。
   - 如果评审口径要求 VM，再补 VM validation。

3. 修 memory metadata
   - `MemoryRef` 增加 `source_agent`、`created_at_ns`、`task_theme`、`tags`。
   - 更新 disk/store roundtrip。
   - 新增测试和 artifact excerpt。

4. 修 final claim boundary
   - external compare debug-only。
   - CodeAct controlled-style。
   - no KV/hidden-state。
   - replay 按 exact/validated/assist 分类。

5. replay negative audit 升级
   - 跑在 persisted live history artifacts 上。
   - 增加 metadata forgery、artifact corruption、tag/theme mismatch 等负例。

### 6.2 应该做，能明显增强说服力

1. external comparator fairness gate
   - 修 metadata、role graph、quality/scoring contract。
   - 先让 external lane 自身质量过关，再 compare。

2. 任务集强化
   - 新增 1-2 个 10 轮 continuous family。
   - 使用多数据源、多扰动、非固定答案。

3. T2/L2 差异收口
   - 分离 semantic selection gain 与 StateRef gain。
   - 减少 L2 prompt-visible metadata。

4. persistence overhead profile
   - `audit_full`、`benchmark_balanced`、`fast_runtime`。
   - 输出 files/bytes/stage ms。

5. role contract audit
   - 文档 + tests 确保四角色职责不漂移。

### 6.3 可选做，作为加分项

1. LLM-generated bounded CodeAct demo
   - AST policy。
   - bwrap execution。
   - 小型 CSV/JSON/markdown 任务。

2. VM final validation
   - 若比赛强制 VM 口径，必须做。
   - 若评审接受 Docker openEuler，可作为加分补证据。

3. 更强 StateRef 可视化
   - manifest excerpt。
   - shared memory publish lifecycle。
   - CAS/replay artifact lineage。

4. 演示视频和一页 claim freeze
   - 让评审快速看到“能 claim / 不能 claim”。

## 7. 最终判断

当前完成度：

- 按赛题最低主链要求，当前约在 `75%-85%`。
- 多 Agent、结构化通信、非文本状态、连续任务、指标、CodeAct profile 都已有实现和 evidence。
- 严格交付闭环、external fairness、memory metadata、audit-grade replay 仍未完全收口。

是否满足最低交付要求：

- 如果交付标准是“源码 + 文档 + 容器 evidence + 可跑 v2 suite”，基本满足，但需要冻结提交和 final evidence index。
- 如果交付标准严格要求 openEuler VM 现场复现，则还需要 VM final validation。

当前最强 claim：

- StateBus v2 在 API + local embedding 路径下，已经形成 `L0/L1/L2/L3/T2` 可分离 evidence。
- L2 typed semantic state 在 long/table continuous tasks 上显著减少 raw evidence。
- L3 在 replay-admissible family 中有 exact/validated replay 和 skipped-step evidence。

当前最弱环节：

- external pure-text comparator fairness gate 未过。
- memory metadata 不完全满足赛题一等字段。
- replay audit 还不是 persisted-live-history audit-grade。
- CodeAct 容易被误读成通用 LLM 生成代码。

如果只剩 1-2 天：

1. 冻结 commit 和 final evidence index。
2. 写 container validation report。
3. 修 memory metadata 一等字段。
4. final report 中严控不能 claim 内容。
5. replay negative audit 至少补 persisted-live-history 版本的关键负例。

如果还有 1 周：

1. 修 external comparator fairness gate。
2. 新增 1-2 个强 continuous task families。
3. 扩 replay negative audit 到 12+ cases。
4. 增加 role contract tests。
5. 增加 bounded LLM-CodeAct demo。
6. 做 VM final validation 或至少独立 clean-container rerun。

## 8. 禁止 claim 清单

当前绝对不要写：

1. “StateBus 已 formal 优于 external pure-text multi-agent baseline”
   - 原因：external compare `fairness_gate_failed`。
   - 需要证据：external compare `comparison_valid=true`。

2. “已经实现 KV cache / hidden-state 跨 Agent handoff”
   - 原因：当前是 typed semantic state / StateRef / artifact replay。
   - 需要证据：模型内部 prefix/KV/hidden state 的生成、传递、接收、使用、隔离和评测。

3. “runtime overhead 已优化完成”
   - 原因：persistence overhead 仍是成本桶。
   - 需要证据：repeat timing、persistence profile、端到端稳定下降。

4. “默认非 root sandbox 支持”
   - 原因：bwrap evidence 是 root+bwrap profile。
   - 需要证据：默认 qcrs/non-root profile bwrap 无 fallback。

5. “openEuler VM 最终交付已完成”
   - 原因：容器已测不自动等价 VM。
   - 需要证据：VM 上完整命令、日志、artifact。

6. “成熟 audit-grade replay”
   - 原因：negative audit 目前 7 cases，且未跑 persisted live history artifacts。
   - 需要证据：persisted-live-history 负例、metadata forgery、artifact corruption、runtime drift 全覆盖。

7. “general-purpose CodeAct benchmark superiority”
   - 原因：当前是 controlled runtime-generated CodeAct-style execution。
   - 需要证据：LLM-generated code、policy audit、多任务 benchmark、sandbox proof。

## 9. 文档维护规则

后续每做一个优化，都应在本文件对应问题下追加：

- 修复 commit。
- 修改文件。
- 新增测试。
- 新 evidence artifact。
- claim 是否升级。

任何 claim 升级必须满足两个条件：

1. 代码路径存在。
2. JSON artifact 或测试日志能证明。

只有文档描述，没有代码和 artifact，不允许升级状态。

# StateBus `contest_honest_headline_v1` 厚化执行计划

日期：`2026-06-18`

适用范围：

- 仓库：`/home/qcrs/statebus/project`
- 环境：host + 本地 conda
- 主对象：`contest_honest_headline_v1`

定位：

- 这不是 correctness/object-purity 回头审计。
- 这不是 runtime 主链路重构计划。
- 这是一份只面向 `contest_honest_headline_v1` 厚化、静态合同补齐、以及方法评测准入门的执行计划。

---

## 1. 当前阶段判断

当前阶段判断固定为：

1. `benchmark correctness`：基本通过
2. `object purity`：基本通过
3. `task thickness`：当前未通过
4. `method strength`：当前不能正式裁决

因此当前主线只能是：

1. 先把 benchmark 厚度写成静态合同
2. 再把厚化落实到 `contest_honest_headline_v1`
3. 再做 deterministic / API `repeat=1` 最小验证
4. 最后才决定是否允许进入下一轮方法评测

---

## 2. 当前 benchmark 厚化缺口

当前 `contest_honest_headline_v1` 的主要缺口不是公平性，而是厚度合同缺失：

1. `clean/distractor/ambiguous` 仍主要读成受控分流题，厚度更多停留在解释层，没有落成字段级合同。
2. `replay_reusable` 已有 prior-case / prior-rejection 门，但还没有被纳入统一的 `S0 / S1 / S2` setting 合同。
3. family 里已有 `route_competition`、`tool_competition`、`abstention_allowed`、`required_prior_case_ids` 等素材，但缺少显式的厚度字段来定义：
   - 至少几跳
   - 哪些中间决策是必须的
   - 哪条 abstention 边界是 score-valid 的
   - 哪些 case 属于 `S1`，哪些 case 属于 `S2`
4. 当前 headline 的最小执行链路仍容易塌成固定 `retrieve -> execute -> summarize` 三步，不足以把“route 竞争 -> scoped action -> validation guard -> reuse dependency”明确写死。

---

## 3. 进入方法评测前，benchmark 至少要修到什么程度

在当前“不重构 runtime 主链路”的硬边界下，本轮把厚度修到下面这个程度，就允许开始正式评方法：

1. headline 仍保持同一个对象：
   - 同一 family
   - 同一 corpus
   - 同一 scoring / loader / logging
   - 同一 `contest_honest_headline_v1`
2. 所有 headline case 都显式写出厚度字段：
   - `thickness_setting`
   - `reasoning_hops_min`
   - `dependency_depth`
   - `route_competition_min`
   - `tool_competition_min`
   - `expected_intermediate_decisions`
   - `abstention_boundary`
   - `required_plan_semantic_roles`
3. `S1` case 必须带 `validate` 语义，至少把 headline floor 从隐式三步抬到显式四步：
   - `retrieve`
   - `validate`
   - `execute`
   - `summarize`
4. `S2` case 必须在 `S1` 基础上继续带 reusable dependency 合同：
   - `required_prior_case_ids`
   - `required_prior_rejections`
   - `required_prior_routes` 先作为静态审计字段记录，不在本轮偷偷升级成 runtime 新变量
5. 以上合同必须有静态测试护栏，并通过 deterministic / API `repeat=1`，且不引入新的 object-purity 回归。

这轮的关键判断是：

- 允许开始评方法，不等于已经证明方法有优势；
- 只表示当前 headline 终于厚到“可以用来判断方法是否有优势”，而不是继续停留在 `S0` 薄对象上争论。

---

## 4. 保留什么，厚化什么

### 4.1 保留

下面这些不改对象身份，只继续沿用：

- `contest_honest_headline_v1` 仍是唯一 contest-facing headline
- 5 个 family 不变
- 每个 family 仍保留 `clean / distractor / ambiguous / replay_reusable`
- `mode` 仍是唯一 headline 主变量
- same corpus / same scoring / same loader / same report surface
- `text_whole_lane` vs `state_packet_minimal` 的 honest headline 读法不变

### 4.2 厚化

本轮只厚化这些层面：

1. family 合同：
   - 显式声明最小 route/tool 竞争要求
2. case 合同：
   - 显式声明厚度 setting、最少 hop、最少 dependency depth、必须的中间决策、abstention 边界
3. plan 语义：
   - headline 厚化 case 统一要求 `validate` 步骤进入计划合同
4. reusable 合同：
   - 把 `required_prior_case_ids` / `required_prior_rejections` 从“已有字段”提升成 `S2` 准入门的一部分
5. query / summary / corpus role 选择：
   - 不直接泄露 route/tool
   - 但要更明确要求“先排竞争路径，再决定 scoped action / abstain”

---

## 5. `S0 / S1 / S2` setting 设计

### 5.1 `S0`

定义：

- 当前 `contest_honest_headline_v1` 的 honest floor
- 主要回答 correctness + object purity

允许得出的结论：

- benchmark 主对象基本干净
- 不允许据此直接判方法强弱

### 5.2 `S1`

定义：

- 在同一个 headline 对象内，把 `clean / distractor / ambiguous` 提升为显式多跳合同
- 不增加 pack，不切换数据集，不改评分

本轮落地策略：

1. 每个 `S1` case 都显式要求：
   - `thickness_setting = S1`
   - `reasoning_hops_min >= 2`
   - `dependency_depth = 1`
   - `required_plan_semantic_roles = [retrieve, validate, execute, summarize]`
2. `clean` 的目标不再只是“选对 route”：
   - 还要先做竞争路径排除
   - 再做 scoped first action 判断
3. `distractor` 的目标不再只是“看见假线索”：
   - 必须保留至少一个强竞争分支
   - 且需要经过 `validate` 才允许执行 first action
4. `ambiguous` 必须保留 score-valid 的 abstention / collect-more-evidence 边界

允许回答的问题：

- 在显式多跳、显式 validation 的同一 headline 对象上，protocol 是否比 pure-text 更有优势。

### 5.3 `S2`

定义：

- 在 `S1` 基础上，把 `replay_reusable` 提升为显式 dependency-thickened setting

本轮落地策略：

1. 每个 `S2` case 都显式要求：
   - `thickness_setting = S2`
   - `reasoning_hops_min >= 2`
   - `dependency_depth >= 2`
   - `required_plan_semantic_roles = [retrieve, validate, execute, summarize]`
   - `required_prior_case_ids` 非空
   - `required_prior_rejections` 非空
2. `required_prior_routes` 本轮先作为静态审计字段落盘：
   - 用来记录“前题 scoped route/action 继承”要求
   - 当前不把它偷偷升级成 runtime 新变量
3. `S2` 的可答问题是：
   - 在已有多跳厚度之上，cross-task dependency / reuse contract 是否进一步放大 protocol 优势。

---

## 6. 字段级改动清单

本轮字段改动只落在 `tasks/contest_family_spec.py`、`tasks/contest_family_spec.yaml` 及其派生 benchmark YAML：

### 6.1 family 级新增字段

- `thickness_contract`
  - `route_competition_min`
  - `tool_competition_min`

### 6.2 case 级新增字段

- `thickness_setting`
- `reasoning_hops_min`
- `dependency_depth`
- `expected_intermediate_decisions`
- `abstention_boundary`
- `required_plan_semantic_roles`
- `required_prior_routes`

### 6.3 case 级保留但重读的字段

- `acceptable_routes`
- `acceptable_tools`
- `required_prior_case_ids`
- `required_prior_rejections`
- `abstention_allowed`
- `allowed_abstain_tool`
- `corpus_doc_roles`
- `query`
- `summary_hint`

---

## 7. 外部 benchmark 原则：借什么，不借什么

当前明确借：

1. `MuSiQue`
   - connected multihop
   - 反 shortcut
2. `HotpotQA`
   - supporting facts / distractor universe
3. `BRIGHT`
   - reasoning-before-retrieval
4. `AgentEscapeBench`
   - dependency depth 明示
5. `LongMemEval-V2`
   - history-to-evidence reusable contract
6. `BenchAgent`
   - loader / logging / answer contract 不变
7. `τ-bench`
   - end-state / abstention / reliability 的 verifier 视角

当前明确不借：

- 不导入新的 headline 数据集
- 不把 WebArena / SWE-bench 环境直接并进当前主对象
- 不靠新 pack 绕开 `contest_honest_headline_v1` 厚化

---

## 8. 静态测试方案

下一轮实现前，先补下面这些静态测试：

1. spec 结构测试
   - 每个 family 都必须带 `thickness_contract`
   - 每个 case 都必须带显式厚度字段
2. `S1 / S2` setting 测试
   - `clean / distractor / ambiguous -> S1`
   - `replay_reusable -> S2`
3. plan 语义测试
   - 所有 `S1/S2` headline case 都必须声明 `validate`
4. reusable 合同测试
   - `S2` case 必须同时带 `required_prior_case_ids` 与 `required_prior_rejections`
   - `required_prior_routes` 至少静态落盘
5. competition / abstention 测试
   - family 竞争下限必须满足
   - `ambiguous` 与 `replay_reusable` 必须带非空 `abstention_boundary`
6. committed benchmark 同步测试
   - `contest_family_spec.yaml -> contest_dual_mode_controlled_v3_benchmark.yaml` 的生成结果必须一致

---

## 9. `S0 -> S1 -> S2` 的进入条件

### 9.1 从 `S0` 进入 `S1`

必须同时满足：

1. static thickness tests 全绿
2. `clean / distractor / ambiguous` 全部带显式厚度字段
3. `required_plan_semantic_roles` 已把 `validate` 纳入 plan 合同
4. thickened `contest_honest_headline_v1` 的 deterministic `repeat=1` 通过
5. thickened `contest_honest_headline_v1` 的 API `repeat=1` 通过
6. whole-lane text guard / hidden leak / object parity 没有新回归

### 9.2 从 `S1` 进入 `S2`

必须同时满足：

1. `replay_reusable` 全部升级为 `S2`
2. `required_prior_case_ids` / `required_prior_rejections` 全部通过现有 reusable gate
3. `required_prior_routes` 已作为静态审计字段落盘
4. `S2` rows 的 deterministic / API `repeat=1` 不引入新污染

---

## 10. 最小验证命令

先激活环境：

```bash
source deploy/activate_statebus_host.sh
```

生成派生 benchmark YAML：

```bash
python scripts/generate_contest_family_yaml.py
```

先跑静态与 smoke：

```bash
python -m pytest -q tests/test_smoke.py -k "contest_family_spec or contest_honest_headline or thickness"
```

最小 deterministic 验证：

```bash
python -m eval.runner \
  --task-set contest_honest_headline_v1 \
  --repeat 1 \
  --embedding-mode deterministic \
  --llm-mode deterministic \
  --out "$STATEBUS_RUNS_DIR/contest_honest_headline_thickness_det_r1"
```

最小 API 验证：

```bash
unset all_proxy
unset ALL_PROXY
python -m eval.runner \
  --task-set contest_honest_headline_v1 \
  --repeat 1 \
  --embedding-mode deterministic \
  --llm-mode api \
  --out "$STATEBUS_RUNS_DIR/contest_honest_headline_thickness_api_r1"
```

---

## 11. 本轮完成后的允许结论

如果本轮合同、静态测试、deterministic/API `repeat=1` 全部通过，则允许进入下一轮：

- 正式开始在 thickened `contest_honest_headline_v1` 上评方法
- 先看 `S1`
- 再看 `S2`
- 再决定是否需要 `repeat=3` / `repeat=10`

如果这些条件没有同时满足，则：

- 不允许把已有结果读成方法结论
- 不允许继续堆更重的旧 benchmark repeat
- 不允许跳回 runtime 主链路重构

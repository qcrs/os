# StateBus Benchmark V2 Execution Plan

日期：`2026-06-12`

适用范围：

- 当前仓库：`/home/qcrs/statebus/project`
- 当前 host-mainline benchmark 重构执行
- 配套对象定义文档：
  - [benchmark_v2_contract_20260612.md](/home/qcrs/statebus/project/docs/planning/benchmark_v2_contract_20260612.md)

这份文档是 **执行计划**，不是结果报告。  
如果后续开始改 pack、task schema、report 或 runner，默认按本文件顺序推进。

---

## 1. 直接结论

V2 的正确推进顺序不是：

1. 先调 routing threshold
2. 先修 handoff text
3. 先继续重跑 formal_controlled

而是：

1. 先冻结旧 benchmark 口径
2. 先重写 benchmark contract
3. 先拆 pack object
4. 再重写 task correctness schema
5. 再做最小实现改动
6. 最后才跑正式 benchmark

一句话执行路线：

> 先让 benchmark object 正确，再让系统行为变好；不要反过来做。

---

## 2. 本轮固定判断与边界

### 2.1 固定判断

后续执行时直接接受下面这些判断：

1. 赛题主对象仍然是：
   - `低开销通信`
   - `非文本状态传递`
   - `共享记忆复用`
2. LangGraph 固定为 orchestration substrate
3. `carrier / semantic_retention / memory / planner_support` 必须分开
4. `strict pure text` 只做 formal-secondary
5. `open planner` 只做 support-only
6. `formal_controlled` 不再继续当唯一 formal headline

### 2.2 当前不纳入

本轮执行明确不纳入：

- Docker/openEuler 迁移
- 外部大规模 benchmark 接入
- Planner 开放自治扩张
- 新工具生态扩张
- hidden-state / KV 传递
- 大规模任务域换血

---

## 3. 每轮开始前必须完成的检查

任何代码修改前，先完成：

1. 读：
   - `AGENTS.md`
   - `README.md`
   - `docs/reference/题目.md`
   - [benchmark_v2_contract_20260612.md](/home/qcrs/statebus/project/docs/planning/benchmark_v2_contract_20260612.md)
   - `docs/reports/task_design_and_mode_comparison.md`
   - `docs/planning/state_transfer_benchmark_redesign_20260610.md`
2. 读公共代码锚点：
   - `tasks/sample_tasks.py`
   - `eval/runner.py`
   - `agents/sample_agents.py`
   - `runtime/executor_runtime.py`
   - `runtime/langgraph_adapter.py`
   - `tests/test_smoke.py`
3. 明确本轮只做一个 phase
4. 明确不碰什么

---

## 4. Phase 划分

V2 执行分 7 个 phase。

只有前一 phase 退出条件满足，后一 phase 才能启动。

### Phase 0：冻结旧口径

目标：

- 把当前 pack 明确降格成 `historical_v1`
- 停止把旧 `formal_controlled` 继续当 v2 主 headline

需要修改的对象：

- pack 说明文档
- report wording
- README / planning 中引用 benchmark 的说明

退出条件：

- 所有文档都能明确分出：
  - `historical_v1`
  - `formal-headline v2`
  - `support-only v2`

验证：

- 搜索 repo 内旧表述，确认不再把 v1 写成唯一 formal 主线

### Phase 1：定义 v2 pack surface

目标：

- 新 pack 名称和 claim surface 固定

必须产出：

- `carrier_controlled_v2`
- `semantic_retention_v2`
- `strict_pure_text_boundary_v2`
- `memory_reuse_v2`
- `planner_support_v2`
- `langgraph_native_text_support_v2`

需要修改的对象：

- `tasks/` 下 pack yaml
- `tasks/sample_tasks.py` 中 alias / pack type
- `eval/runner.py` 中 pack-specific report routing

退出条件：

- 每个 pack 都有：
  - 类型
  - claim
  - stopline
  - support/headline 边界

验证：

- `tests/test_smoke.py` 中 pack boundary regression tests 通过

### Phase 2：重写 task correctness schema

目标：

- 从 family-level 单标签升级到 case-level correctness contract

必须新增字段：

- `case_id`
- `case_type`
- `eval_scope`
- `expected_family`
- `primary_expected_route`
- `primary_expected_tool`
- `acceptable_routes`
- `acceptable_tools`
- `disallowed_families`
- `abstention_allowed`
- `allowed_abstain_tool`
- `abstain_only_when`

需要修改的对象：

- `tasks/*.yaml`
- `tasks/sample_tasks.py`
- `SampleTask` dataclass

退出条件：

- 每个 v2 task 都能独立判断：
  - exact
  - admissible alt
  - abstain

验证：

- 加载任务后可统计三类 case 数量
- 旧 task 不会因为缺字段直接崩

### Phase 3：重写 misfire/eval contract

目标：

- 废掉单一 `task_match_rate` 作为唯一解释指标

必须新增或提升的指标：

- `route_exact_rate`
- `tool_exact_rate`
- `exact_match_rate`
- `admissible_match_rate`
- `abstention_rate`
- `wrong_family_rate`

需要修改的对象：

- `eval/runner.py`
- report tables
- compare csv / json summary

退出条件：

- `checkout distractor` 这类 case 不再被粗暴记成单一“错”
- `billing clean` 这类 system failure 和 benchmark 单解问题能被区分

验证：

- 用已有 repeat=3 包回放或 deterministic run 验证新分类生效

### Phase 4：先落三个主 pack

目标：

- 先让正式主线可跑，不急着全量 pack

执行顺序：

1. `carrier_controlled_v2`
2. `semantic_retention_v2`
3. `memory_reuse_v2`

为什么这个顺序：

1. `carrier` 最容易做到单变量
2. `semantic_retention` 是当前争议最大的一组
3. `memory` 要等 handoff 主线固定后再做

退出条件：

- 三个 pack 都有：
  - yaml
  - task contract
  - report section
  - smoke test

验证：

- deterministic `repeat=1`
- API `repeat=1`
- 指标表与 stopline 文案一致

### Phase 5：落 formal-secondary 和 support-only

目标：

- 把边界型证据补全，但不污染 formal headline

执行：

1. `strict_pure_text_boundary_v2`
2. `planner_support_v2`
3. `langgraph_native_text_support_v2`

退出条件：

- 所有 support pack 都明确标成 support-only
- strict pure text 明确标成 formal-secondary

验证：

- report header 和 boundary wording regression tests

### Phase 6：历史包兼容与迁移

目标：

- 保留 v1 可读性，但不再误导

执行：

1. 旧 pack 保留 alias
2. 文档中改标记为 `historical_v1`
3. 如需要，提供 v1 -> v2 mapping table

退出条件：

- 老结果仍能读
- 新结果不再被旧文案污染

### Phase 7：正式 rerun

目标：

- 在 v2 合同上重新生成正式证据

正式顺序建议：

1. deterministic smoke
2. API repeat=1 sanity
3. API repeat=3 mid proof
4. 必要时再做 repeat=10 formal headline

退出条件：

- v2 headline pack 全部有干净结果
- stopline 能直接复用到答辩/报告

---

## 5. 每个 phase 该改哪些文件

### 5.1 Phase 0-1 主要文件

- `docs/reports/task_design_and_mode_comparison.md`
- `docs/planning/benchmark_v2_contract_20260612.md`
- `tasks/sample_tasks.py`
- `eval/runner.py`
- `tests/test_smoke.py`

### 5.2 Phase 2 主要文件

- `tasks/*.yaml`
- `tasks/sample_tasks.py`
- `tests/test_smoke.py`

### 5.3 Phase 3 主要文件

- `eval/runner.py`
- `tests/test_smoke.py`

### 5.4 Phase 4-5 主要文件

- `tasks/*_v2*.yaml`
- `eval/runner.py`
- `tests/test_smoke.py`
- 必要时：
  - `agents/sample_agents.py`
  - `runtime/executor_runtime.py`

原则：

- benchmark contract 先改
- behavior 调整后改

---

## 6. 任务分拆建议

### 6.1 保留的 family

当前建议保留：

- `checkout`
- `auth`
- `inventory`
- `billing`
- `deploy`

原因：

- 资产已存在
- 已有 paired cases
- 目前问题主要在合同，不在 family 数量

### 6.2 case 的处理方式

#### `clean`

- 先保留
- 默认 exact

#### `distractor`

- 重新审查
- 优先改成 `bounded_alternative`

#### `ambiguous`

- 重新审查
- 必须明确是否允许 `abstention`

#### `replay_reusable`

- 拆成：
  - semantic replay case
  - memory replay case

不要一个 case 同时回答两个问题。

---

## 7. 指标与报告实施建议

### 7.1 runner 必须先支持的聚合项

优先实现：

- exact/admissible/abstain/wrong-family 四类聚合
- case_type breakdown
- pack stopline

### 7.2 不急着先做的

先不做：

- 新的大图表系统
- 复杂前端报告可视化
- 外部 leaderboard 风格结果页

先保证：

- JSON 正确
- Markdown 报告可读
- smoke tests 锁住 contract

---

## 8. 测试策略

### 8.1 每 phase 都要有 smoke

每个 phase 至少补一类 regression test：

1. task loading contract
2. report wording contract
3. metric aggregation contract
4. pack boundary contract

### 8.2 正式 benchmark 之前的最低验证门

在任何 API rerun 前，至少要通过：

```bash
python -m pytest -q tests/test_smoke.py
python -m runtime.smoke
```

如 phase 只改 benchmark surface，可进一步加：

```bash
python -m pytest -q tests/test_smoke.py -k 'benchmark or pack or report'
```

---

## 9. 外部参考如何进入执行

### 9.1 LangGraph

只用于：

- orchestration boundary 参考
- support baseline 参考

不用于：

- 赛题 formal 主 benchmark 对象

### 9.2 SWE-bench / SWE-bench-Live

当前只允许作为：

- external support idea
- correctness-oracle design reference
- future mutation benchmark source

当前明确不执行：

- 把 SWE-bench-Live 直接接进 formal 主 benchmark

原因：

- 对象不匹配
- 环境依赖不匹配
- correctness oracle 不匹配

---

## 10. 推荐的实际执行顺序

如果从下一轮开始直接做，建议按下面顺序：

1. 改文档与 pack boundary
2. 改 task schema
3. 改 eval contract
4. 先做 `carrier_controlled_v2`
5. 再做 `semantic_retention_v2`
6. 再做 `memory_reuse_v2`
7. 最后做 strict/support packs
8. 再决定是否补 external support benchmark

一句话操作 stopline：

> 先把 benchmark contract 设计成不会误读，再去追求更好的 numbers。

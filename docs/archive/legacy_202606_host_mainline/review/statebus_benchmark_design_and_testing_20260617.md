# StateBus Benchmark 设计与测试方案

日期：2026-06-17

范围：

- 仅适用于 `/home/qcrs/statebus/project`
- 仅走 host + 本地 conda：`source deploy/activate_statebus_host.sh`
- 不引入 Docker / openEuler / nsjail

## 1. 结论

当前 benchmark 先别继续扩面，先把对象、口径、测试门禁定死。

最重要的是三件事：

- `contest_honest_headline_v1` 只作为唯一 contest-facing headline
- `contest_dual_mode_controlled_v3` 只保留为内部 controlled surface
- 所有 report 语义必须能回到 row-level

## 2. Benchmark 应该怎么设计

### 2.1 主线对象

主线只保留一条：

- `text_whole_lane` vs `state_packet_minimal`
- 同一任务集、同一语料、同一评分口径、同一 plan source
- 只允许一个主变量：`mode`

### 2.2 最小可行对象

一个可信 headline 至少要满足：

- contest-facing
- single-variable
- text / protocol 对照
- object parity
- formal headline 清晰
- 不依赖额外解释层

### 2.3 任务厚度

现在的任务集能证明机制成立，但还偏薄。

后续厚化只朝这几个方向：

- 多跳协作
- 跨任务依赖
- 竞争性 route/tool
- 明确的 abstention 边界

### 2.4 现有 pack 分层

- `contest_honest_headline_v1`：正式 headline
- `contest_dual_mode_controlled_v3`：内部 controlled composite
- `planner_support_v3`：planner 单变量支撑
- `memory_dual_mode_fairness_v3`：对象公平性审计
- `typed_state_mechanism_v3`：机制真实性

### 2.5 设计分层

- headline 层只允许一个公开结论。
- controlled 层只做内部对照，不向外借用 headline 语义。
- audit 层只回答对象是否干净，不替代主结论。
- support 层只提供局部能力证据，不合并成主故事。

### 2.6 设计禁区

- 不用 hidden fallback 补对象。
- 不用 pack-specific override 美化结果。
- 不把任务太薄的单跳对象包装成多跳证据。
- 不把 report 里的 aggregate 当作比 row-level 更高的真值。

## 3. Benchmark 应该怎么测

### 3.1 静态测试

先测对象是否干净：

- pack type 是否对
- `single_variable` / `variable_axes` 是否对
- text / protocol 任务数是否配对
- `formal_structure_clean_retrieval` 是否开启
- reusable 行是否带 `required_prior_case_ids` / `required_prior_rejections`

### 3.2 语义测试

再测 report 是否和 row-level 一致：

- `planner_one_shot_valid_rate` 必须按 row-level 聚合
- `memory_dual_mode_fairness_v3` 的空 contract 不能写成 `mismatch`
- `benchmark_report.md` 和 `benchmark_results.json` 必须一致

### 3.3 结构化回归

建议固定做这三类断言：

- pack/contract 断言：`single_variable`、`variable_axes`、`public_surface`、`formal_structure_clean_retrieval`
- row 断言：text/protocol 配对、reuse 行依赖、replay 行依赖、plan_source 分层
- report 断言：headline、table、row-level 三者同义

### 3.4 执行测试

本地门禁顺序：

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q
python -m runtime.smoke
```

对 benchmark pack 的回归：

```bash
python -m eval.runner --task-set contest_honest_headline_v1 --repeat 1 --llm-mode api --out /tmp/statebus_headline_api_r1 --quiet-progress
python -m eval.runner --task-set contest_honest_headline_v1 --repeat 10 --llm-mode api --out /tmp/statebus_headline_api_r10 --quiet-progress
```

### 3.5 通过标准

- `pytest` 绿
- `runtime.smoke` 绿
- row-level 和 report 一致
- `repeat=10` 才允许写正式 headline
- `planner_support_v3` 只能在 row-level 聚合修正后再读
- `memory_dual_mode_fairness_v3` 的空 contract 必须显示为 `not_evaluated`

## 4. 外部参考

### 4.1 多跳 / 支持事实

- [HotpotQA](https://arxiv.org/abs/1809.09600): 支持事实 + distractor + 多文档推理，适合借“证据宇宙”与支持事实约束。
- [MuSiQue](https://arxiv.org/abs/2108.00573): 从可组合单跳问题构造多跳问题，适合借“反 shortcut”的任务厚化。

### 4.2 任务变厚 / 真实检索

- [BRIGHT](https://arxiv.org/abs/2407.12883): reasoning-intensive retrieval，适合借“检索必须先推理再检索”的对象设计。

### 4.3 长时记忆

- [LongMemEval](https://arxiv.org/abs/2410.10813): indexing / retrieval / reading 三段式，适合对应 StateBus 的 memory pipeline。

### 4.4 真实代理任务

- [SWE-bench](https://arxiv.org/abs/2310.06770): 真实 issue / PR，适合借执行式评测与环境可复现。
- [WebArena](https://arxiv.org/abs/2307.13854): 真实网站任务，适合借长时任务与固定环境。
- [BenchAgent](https://arxiv.org/abs/2606.05670): normalized loader / tool access / answer contract / trajectory logging，最适合借“统一 loader + 统一日志”的做法。

### 4.5 可直接借的原则

- 先定对象，再定指标。
- 先定 loader，再定 run。
- 先定 answer contract，再看分数。
- 先定 trajectory logging，再谈复盘。
- 先拆 multi-hop / memory / retrieval，再谈 headline 结论。

## 5. 推荐工作顺序

1. 冻结 benchmark charter
2. 冻结主线边界
3. 修 report 语义 bug
4. 只跑必要的 repeat=1 / repeat=10
5. 任务厚化放到后续

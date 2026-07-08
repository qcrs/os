# 模型预热阅读协议

这份协议要求 1M 模型先“全量热身”，再开始写作。

核心原则：

1. 全读，不等于全讲。
2. 先建立地图，再输出文档。
3. 如果代码、冻结 docs、artifact 发生冲突，以当前代码和当前冻结 authoritative artifact 为准。

## 一、预热目标

模型在正式写作前，必须先建立 5 张内部地图：

1. 证据地图
   - 当前哪些 artifact 是 authoritative
   - 哪些是 support
   - 哪些是 audit
2. 系统地图
   - 四角色
   - 三平面
   - 五层架构
   - 核心模块与对象
3. 任务地图
   - `task` / `family` / `chain` / `case`
   - negative control
   - variable axes
4. 对比地图
   - `text` 与 `StateBus` 的固定变量
   - `text` 与 `StateBus` 的变化变量
   - 各自 handoff 方式
5. 口径地图
   - 当前能说什么
   - 当前不能说什么
   - 哪些结果不能升级为更强 claim

## 二、必须阅读的材料

### A. 仓库入口与边界

1. `README.md`
2. `docs/constraints/current_host_and_migration.md`
3. `docs/constraints/current_feature_scope.md`
4. `docs/planning/implementation_plan.md`
5. `docs/reference/题目.md`

### B. 当前冻结口径与架构说明

1. `docs/planning/`
2. `docs/reports/`
3. `docs/progress/`
4. 其他 `docs/` 下与当前实现、当前结果、当前边界直接相关的 markdown

要求：

1. 不只读一两份“总结文档”。
2. 要把 `docs/` 下当前仍与实现和结果直接相关的 markdown 全读一遍。
3. 历史文档可以保留，但要标出哪些是历史背景、哪些是当前 source-of-truth。

### C. 代码

至少要系统阅读这些目录下当前与方法解释直接相关的文件：

1. `agents/`
2. `runtime/`
3. `protocol/`
4. `statepool/`
5. `memory/`
6. `eval/`
7. `tasks/`
8. `tests/`

要求：

1. 不要只挑入口函数。
2. 要读会影响“方法解释、任务设计、结果解释”的实现。
3. 要把对象流而不只是模块名搞清楚。

### D. 任务定义与 benchmark 物料

1. `tasks/README.md`
2. `tasks/*.yaml`
3. `tasks/sample_tasks.py`
4. 与 pack materialization、评分和报告生成直接相关的 `eval/runner.py`

### E. 实验结果

必须读当前冻结 docs 指向的所有主证据：

1. communication authoritative artifact
2. communication support artifact
3. typed-state support artifact
4. memory artifact

每个 artifact 至少读：

1. `benchmark_report.md`
2. `benchmark_results.json`
3. `benchmark_compare.csv`

## 三、预热输出

模型在开始正式写 8 份文档前，必须先产出一个内部工作集，至少包含：

1. 当前概念边界清单
2. authoritative / support / audit artifact 清单
3. 四角色输入输出表
4. 核心对象字典
5. 任务 pack 地图
6. `text` vs `StateBus` 对比矩阵
7. 当前 claim boundary 清单

这些内容可以作为内部草稿，不一定最终落盘，但必须先完成，不能跳过。

## 四、写作规则

1. 不允许把“所有读过的内容”平均分摊进最终文档。
2. 不允许只讲英文术语，不解释中文含义。
3. 不允许把 `memory` 写成完全独立于主方法的外挂章节。
4. 不允许把 `validate` 写成第五个 Agent。
5. 不允许把 support surface 偷换成 headline closure。
6. 不允许只给目录树式介绍，不讲真实数据流和真实任务流。

## 五、开始写作前的自检

开始正式输出前，模型必须确认：

1. 我知道当前 active headline 是什么。
2. 我知道当前 communication authoritative artifact 是哪一个。
3. 我知道当前 typed-state 和 memory 各自是什么角色。
4. 我知道四角色、三平面、五层架构的区别。
5. 我知道 `text` 和 `StateBus` 比较时固定了哪些变量。
6. 我能用一个真实任务把数据流从头讲到尾。

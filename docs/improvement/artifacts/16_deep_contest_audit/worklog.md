# Worklog

审计日期：2026-07-06

## 事实发现

1. 确认当前分支为 `feat/statebus-v2-container-runtime`，起点 HEAD 为 `be74494 Harden external fairness gate raw payload checks`。
2. 按要求检查 git 历史、docs/improvement 更新链路、v2 代码、tests/v2、scripts。
3. 完整阅读当前锚点文档和历史审计抽样文档，区分当前事实源与 historical/过时结论。
4. 抽取最新 benchmark JSON：
   - full audit：`v2-full-audit-20260705_213331`
   - raw fairness gate rerun：`codex-raw-fairness-20260706`
5. 对照赛题要求复核 v2 的结构化协议、非文本状态、memory/replay、四角色、external baseline、公平性 gate、任务族覆盖和实验可信度。

## 主要判断

- 当前 v2 支撑“typed control plane + semantic StateRef + replay/downgraded reuse + external fairness-gated dev compare”的组合 claim。
- formal financial primary 证据通过，但任务族窄且 `L3_reuse_gain=0`，不能当作 broad superiority headline。
- continuous replay collection 有 30 round / 3 family / 20 target replay rounds / 20 observed replay rounds 证据，适合支撑连续任务状态迁移与复用。
- validated replay 的行为更准确表述为 validated downgraded reuse / strategy-backed reuse。
- compare 证据支持 prompt/token/control exposure 下降，不支持端到端 latency 胜利。
- memfd transport 有代码和 e2e 测试，不是 formal/compare 主 benchmark 路径。

## 本轮修改

1. 更新 `scripts/run_v2_full_container_audit_suite.sh`：
   - socket hash 加入 `STATEBUS_RUN_ID`。
   - summary 输出新增 `key_metrics`，自动解析 formal、compare、fairness、continuous replay、negative audit、flagship 指标。
2. 更新 replay 相关机器可读指标：
   - `validated_downgraded_reuse_count`：旧 `validated_replay_count` 的保守语义别名。
   - `answer_restoration_replay_count`：旧 `exact_replay_count` 的 answer-restoration 语义别名。
3. 更新 `v2/benchmark/continuous_runner.py`：
   - 单族 evidence pack、comparison summary、集合 summary、admissibility summary 透出新 replay 别名。
4. 更新 `tests/v2/test_continuous_runner.py`：
   - 覆盖 case / layer / collection / admissibility 的新字段。
5. 新建 16 号审计文档和 artifact 日志。

## 未做事项

- 未在本轮重跑完整 `bash scripts/run_v2_full_container_audit_suite.sh`，因为该脚本是重型 API/benchmark 套件；本轮只做脚本语法、目标 pytest、runtime smoke/full pytest 等验证。
- 未把 memfd transport 接入 formal/compare 主 benchmark。
- 未新增更难 formal financial task family。

# StateBus 项目说明

当前仓库是 StateBus 的 host-side 实现仓库，主线目标是验证多 Agent 协作里的三类能力：

- 通信开销是否能下降
- 中间状态是否能以非纯文本方式传递
- 共享记忆是否能带来真实复用

如果你第一次进入这个仓库，先看这份 README；需要更细的环境细节、设计文档和 benchmark 报告，再进入对应文档。

## 1. 环境安装

推荐的 host 环境路径约定：

```text
$HOME/statebus/
├── conda-envs/
├── models/
├── caches/
├── logs/
├── runs/
└── work/
```

安装步骤：

```bash
cd /path/to/statebus
bash scripts/setup_host_dev_env.sh
source deploy/activate_statebus_host.sh
```

详细说明见：

- `docs/setup/host_environment.md`
- `docs/start_here.md`

## 2. API 配置

LLM 配置分成两部分：

- `deploy/statebus_llm.yaml.local`
  - provider / model / role 行为配置
- `deploy/statebus_llm.env.local`
  - `STATEBUS_LLM_API_KEY` 等本地敏感信息

推荐先复制模板：

```bash
cp deploy/statebus_llm.yaml.example deploy/statebus_llm.yaml.local
cp deploy/statebus_llm.env.example deploy/statebus_llm.env.local
```

然后只在本地 `.local` 文件里填真实 key。

不要提交：

- `deploy/statebus_llm.yaml.local`
- `deploy/statebus_llm.env.local`

## 3. 嵌入模型配置

默认 embedding 模型路径：

```text
$HOME/statebus/models/Qwen3-Embedding-0.6B
```

如果路径不同，可以覆盖：

```bash
export STATEBUS_EMBED_MODEL_PATH="/your/path/Qwen3-Embedding-0.6B"
```

设备默认是 `auto`，有 GPU 时建议显式指定：

```bash
export STATEBUS_EMBED_DEVICE=cuda:0
```

## 4. 项目结构

当前主要开发对象是 `v2/` clean-room package；下面这些顶层目录仍保留 host-mainline / v1 代码和历史参考。

核心目录如下：

- `v2/`
  - 当前 v2 clean-room runtime、typed Protobuf/UDS control plane、benchmark、contracts、state refs 和 tests 主线
- `agents/`
  - host-mainline `Planner / Retriever / Executor / Summarizer`
- `runtime/`
  - host-mainline 编排、合同、LLM、远端执行入口
- `protocol/`
  - host-mainline 消息结构、序列化、协议辅助逻辑
- `statepool/`
  - host-mainline 状态池与 mmap / shared state backend
- `memory/`
  - host-mainline SQLite + 向量检索记忆层
- `eval/`
  - benchmark runner、指标与报告生成
- `tasks/`
  - corpus、task 定义、benchmark pack
- `tests/`
  - smoke、runtime、protocol、memory、benchmark 相关测试
- `deploy/`
  - 激活脚本与配置模板
- `scripts/`
  - 环境初始化与维护脚本
  - 旧 host-mainline / v1 过程文档归档区，不作为当前 v2 source-of-truth

## 5. 测试命令

基础验证：

```bash
python -m pytest -q
python -m runtime.smoke
python -m pytest -q tests/v2
```

benchmark 运行主入口在 `eval/runner.py`。  
任务包索引、pack 角色和读法边界请优先看 `tasks/README.md`，不要只从默认 CLI 文件名推断当前 formal object。

`v2` clean-room benchmark 入口按 formal 与 dev 分开：

```bash
python -m v2.benchmark.live_runner --suite preflight --role-path-mode deterministic --embedding-mode deterministic
python -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode deterministic
python -m v2.benchmark.live_runner --suite statebus --benchmark-tier dev --role-path-mode deterministic --embedding-mode deterministic
python -m v2.benchmark.live_runner --suite compare --benchmark-tier dev --role-path-mode api --embedding-mode local
```

其中：

- 以上是 host 环境口径；如果在 `openEuler` 容器内执行，同样命令请改用 `python3`
- `role-path-mode=api` 需要有效的 `STATEBUS_LLM_API_KEY`
- `embedding-mode=local` 需要本地 embedding 模型目录和可用 device
- formal internal benchmark 默认跑 registered formal samples：25 cases / 5 families
- formal compare 代码已改成 registry-backed full 25-case adapter；live API 证据必须以后续 local+api rerun artifact 为准
- dev tier 的 fixed-answer / assisted comparator 只用于开发诊断，不承载 formal headline
- 在正式 live 跑之前，建议先执行 `--suite preflight`

## 6. 实验结果与新手入口

如果你现在要快速搞清楚“当前可信结果是什么、任务怎么构造、`text` 和 StateBus 怎么比较”，按这个顺序看：

1. `docs/README.md`
2. `docs/improvement/README.md`
3. `docs/improvement/20_v2_comprehensive_truth_audit_20260706/00_executive_summary.md`
4. `docs/improvement/20_v2_comprehensive_truth_audit_20260706/code_truth_vs_experiment_issue_matrix_zh.md`
5. `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/`
6. `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_130958/`
7. `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/`
8. `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/`
9. `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260706_191835/deep_dive_analysis_and_fix_plan_zh.md`
10. `docs/reports/final_v2_evidence_index_20260703.md`
11. `tasks/README.md`

它们分别承担：

- 当前文档入口和 source-of-truth 顺序
- 当前 improvement / 修复入口
- 最新真实性审计入口
- 代码事实与实验证据矩阵
- 最新 full `RUN_FLAGSHIP=1` local+api comprehensive artifact；13 stages 全部 exit 0，required failed stage count 为 0；formal internal 25/25、formal financial 8-case strict equal-quality、continuous/replay、replay negative 和 flagship stage 都跑完；flagship stress 为 3/6，不是 all-pass
- `local_api_20260707_130958` 是 transport retry 后、selection retry 前的失败证据；required/continuous/replay clean，但 flagship 因 `strict_visible_candidate_mismatch:csv_profiler::csv_profiler` 失败
- `local_api_20260707_115051` 是 `RUN_FLAGSHIP=1` transport failure 证据；required stages clean，但 optional continuous/replay/flagship 因 API connection/timeout 失败
- `local_api_20260707_091807` 是历史 passing comprehensive core artifact；required stages 全部 exit 0，但 flagship 显式关闭
- historical local+api 深挖和修复计划
- v2 历史证据索引
- 任务包和 pack 角色索引

历史 v1 / v3 pack 读法仍有参考价值，但不要覆盖当前 v2 truth audit。历史正式读法的最短版本是：

- active communication headline：`superiority_comm_v1`
- formal-secondary support：`typed_state_mechanism_v3`、`typed_state_consumer_sensitivity_v3`、`superiority_memory_v1`
- 当前必须区分：`Communication gate` 与 `Formal stability gate`
- `text_whole_lane` 是 StateBus runtime 内部 comparator，不是 external pure-text baseline

当前相关的 support / audit 边界还包括：

- `memory_dual_mode_fairness_v3`：dual-mode fairness / object parity audit，不并入 headline
- `memory_policy_controlled_v3`：固定 `protocol + state_packet_minimal` 后的 memory policy 单变量归因
- `typed_state_mechanism_v3`：正式机制 claim 的主读取对象
- `external_text_baseline_audit_v3`：独立 external text baseline 审计对象，不并入 formal headline

历史报告已归档，只能当背景材料，不能替代当前 source-of-truth：


这些历史报告如果保留旧 headline、旧 pack 命名或旧实现假设，只能按“历史背景/机制示意”读取；当前 formal 结论以 active object、当前 docs 冻结口径和对应 `runs/*/benchmark_report.md` 为准。

更完整的 object registry、历史对象和脚本入口都放在 `tasks/README.md`，不要把 README 继续写成 pack 全表。

## 7. 建议先读什么

如果你要快速理解当前主线，建议先看：

1. `docs/README.md`
2. `docs/constraints/current_host_and_migration.md`
3. `docs/constraints/current_feature_scope.md`
4. `docs/improvement/README.md`
5. `docs/improvement/20_v2_comprehensive_truth_audit_20260706/00_executive_summary.md`

## 8. 历史说明

之前较长的 host-side 背景、验证快照和仓库角色说明已移到：

- `docs/reference/readme_archive_20260611.md`

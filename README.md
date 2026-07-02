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

核心目录如下：

- `agents/`
  - `Planner / Retriever / Executor / Summarizer`
- `runtime/`
  - 编排、合同、LLM、远端执行入口
- `protocol/`
  - 消息结构、序列化、协议辅助逻辑
- `statepool/`
  - 状态池与 mmap / shared state backend
- `memory/`
  - SQLite + 向量检索记忆层
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
- formal tier 默认跑 `formal_financial_family`
- dev tier 的 fixed-answer / assisted comparator 只用于开发诊断，不承载 formal headline
- 在正式 live 跑之前，建议先执行 `--suite preflight`

## 6. 实验结果与新手入口

如果你现在要快速搞清楚“当前可信结果是什么、任务怎么构造、`text` 和 StateBus 怎么比较”，按这个顺序看：

1. `docs/reports/statebus_system_method_task_and_results_explainer.md`
2. `docs/reader_guide/README.md`
3. `docs/reports/current_task_results_overview_20260622.md`
4. `tasks/README.md`

它们分别承担：

- 新人总览
- 模块化延伸阅读入口
- 当前冻结口径与 authoritative artifact 索引
- 任务包和 pack 角色索引

当前正式读法的最短版本是：

- active communication headline：`superiority_comm_v1`
- formal-secondary support：`typed_state_mechanism_v3`、`typed_state_consumer_sensitivity_v3`、`superiority_memory_v1`
- 当前必须区分：`Communication gate` 与 `Formal stability gate`
- `text_whole_lane` 是 StateBus runtime 内部 comparator，不是 external pure-text baseline

历史报告仍保留参考价值，但只能当背景材料，不能替代当前 source-of-truth：

- `docs/reports/MASTER_PRESENTATION_GUIDE.md`
- `docs/reports/task_design_and_mode_comparison.md`
- `docs/reports/current_architecture_overview_20260622.md`
- `docs/reports/benchmark_results_interpretation_20260610.md`

这些历史报告如果保留旧 headline、旧 pack 命名或旧实现假设，只能按“历史背景/机制示意”读取；当前 formal 结论以 active object、当前 docs 冻结口径和对应 `runs/*/benchmark_report.md` 为准。

更完整的 object registry、历史对象和脚本入口都放在 `tasks/README.md`，不要把 README 继续写成 pack 全表。

## 7. 建议先读什么

如果你要快速理解当前主线，建议先看：

1. `docs/constraints/current_host_and_migration.md`
2. `docs/constraints/current_feature_scope.md`
3. `docs/reports/statebus_system_method_task_and_results_explainer.md`
4. `docs/reader_guide/README.md`
5. `docs/reports/current_task_results_overview_20260622.md`

## 8. 历史说明

之前较长的 host-side 背景、验证快照和仓库角色说明已移到：

- `docs/reference/readme_archive_20260611.md`

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
```

benchmark 运行主入口在：

- `eval/runner.py`

任务与 pack 定义在：

- `tasks/`

## 6. 实验结果

当前正式报告与总览在：

- `docs/reports/MASTER_PRESENTATION_GUIDE.md`
- `docs/reports/architecture_and_data_flow.md`
- `docs/reports/task_design_and_mode_comparison.md`
- `docs/reports/benchmark_results_interpretation_20260610.md`

当前环境、benchmark 设计与结果边界相关的详细材料在：

- `docs/planning/`
- `docs/analysis/`

说明：

- 仓库提交代码、任务定义、报告文档和配置模板
- 本地 `runs/` 结果产物默认不进 git

## 7. 建议先读什么

如果你要快速理解当前主线，建议先看：

1. `docs/constraints/current_host_and_migration.md`
2. `docs/constraints/current_feature_scope.md`
3. `docs/setup/host_environment.md`
4. `docs/reports/MASTER_PRESENTATION_GUIDE.md`

## 8. 历史说明

之前较长的 host-side 背景、验证快照和仓库角色说明已移到：

- `docs/reference/readme_archive_20260611.md`

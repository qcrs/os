# StateBus v2 Contest Rebuild 执行交接 Prompt

日期：`2026-07-22`

把以下内容作为新 AI 在 `/home/qcrs/statebus/project` 的首条任务指令。你是实现与验证 Agent，不是重新做一轮不落地的设计评审。

## 目标

按照已经冻结的 contest rebuild 文档，分阶段实现并验证 StateBus v2 的正式主线：保留 embedding `SemanticStateRef`，修正 memory/semantic 记账，准备公开企业 filing 数据合同，实现 engine-local Prefix 的真实观测闭环，实现 LogitState 的独立数值 consumer 与一次有界动作，并按预注册矩阵生成新鲜、可审计证据。

不要把 planned 设计写成已实现，也不要把历史 artifact 当作新代码通过后的正式结果。每一阶段必须先满足前置 gate，再进入下一阶段。

## 开始前必须完整阅读

先读取当前工作树，不凭 prompt 摘要代替源码事实。按顺序完整阅读：

1. `AGENTS.md`
2. `README.md`
3. `docs/constraints/current_host_and_migration.md`
4. `docs/constraints/current_feature_scope.md`
5. `docs/planning/implementation_plan.md`
6. `docs/reference/题目.md`
7. `docs/PROMPT_722_contest_rebuild_prefix_logitstate_without_latent.md`
8. `docs/reports/statebus_v2_contest_readiness_audit_20260722.md`
9. `docs/reports/statebus_native_latent_long_document_plan_remediation_20260722.md`
10. `docs/setup/contest_rebuild_environment.md`
11. `docs/setup/docker_dev_openeuler.md`
12. `docs/planning/contest_rebuild_20260722/README.md`
13. `docs/planning/contest_rebuild_20260722/00_executive_decision_and_packaging.md`
14. `docs/planning/contest_rebuild_20260722/01_current_state_and_remediation.md`
15. `docs/planning/contest_rebuild_20260722/04_vertical_data_preprocess_and_task_design.md`
16. `docs/planning/contest_rebuild_20260722/02_prefix_engine_local_reuse_design.md`
17. `docs/planning/contest_rebuild_20260722/03_logitstate_core_chain_design.md`
18. `docs/planning/contest_rebuild_20260722/05_experiment_matrix_metrics_and_statistics.md`
19. `docs/planning/contest_rebuild_20260722/06_implementation_plan_and_acceptance.md`
20. `docs/planning/contest_rebuild_20260722/07_auxiliary_verification_record.md`

然后检查 `git status --short`、当前 branch、相关源码和已有测试。当前工作树可能很脏，所有未知改动都视为用户资产。禁止 `git reset --hard`、`git checkout --`、清理未跟踪文件、覆盖历史 artifact 或擅自切分支。若 A0 要求 clean worktree，而当前现场不满足，只报告精确差异并请求用户决定；不要自行搬运或丢弃修改。

## 不可变技术边界

- 正式主线固定 `latent_mode=off`、`latent_handoff_mode=off`、`latent_prompt_embeds_enabled=false`。
- 不创建或宣称 Agent 间 KV/hidden tensor 传输。Prefix 仅限同一 vLLM engine/cache epoch 内的自动 prefix cache 意图、精确 token identity 和真实 counter/TTFT 观测。
- Prefix、LogitState、Memory 和 embedding semantic state 必须各自有开关、consumer、事件、实验和 claim，收益不得相互归因。
- `candidate_handle_seen` 不是 vLLM cache hit；entropy 不是已校准正确率；memory candidate/approved 不是 consumed。
- `ExecutionArtifactRef` 与 `StateRef` 保持分离。
- 正式请求严格串行，`concurrency=1`；计时比较不得并发发 API 请求。
- 新 run 使用全新目录，不覆盖、不删除失败样本，不修改历史 run 或 canonical artifact。
- 不进入或修改其他人的容器，不执行 `docker system prune`，不终止无关 GPU/服务进程。

## Qwen3 正式请求合同：全程静默、禁止 thinking

这里的“不要思考”是模型请求合同，不是降低任务复杂度。任务仍可要求多个业务 reasoning hops，但四角色不得生成 Qwen3 `<think>` 内容。

正式 `Planner`、`Retriever`、`Executor`、`Summarizer` 及所有 capability probe 必须满足：

```yaml
json_output: true
temperature: 0.0
reasoning_effort: null
extra_body:
  chat_template_kwargs:
    enable_thinking: false
```

权威配置是 `deploy/statebus_llm.contest_rebuild.yaml`。`runtime/llm.py` 的 local-vLLM 路径也会默认补 `enable_thinking=false`，但正式执行仍必须在落盘配置中显式写出，不能只依赖默认值。不得通过 `request_kwargs.extra_body`、环境变量或直接 `curl` 偷换成 thinking 模式。

原因与证据边界：历史落盘正式/回归配置一直使用 `enable_thinking=false`；结构化四角色依赖 object-only JSON schema，thinking 会与首 token `{` 的 grammar 约束冲突、增加时延并破坏历史可比性。现有历史没有 thinking-on 对照实验，因此不要额外声称 non-thinking 提升了业务准确率。若未来研究 thinking-on，只能建立独立、预注册的 ablation 和独立 run root，不能混进 P/L/R canonical matrix、Prefix identity 或 LogitState calibration。

测试与日志保持安静：使用 `pytest -q`，不要在终端打印完整 prompt、raw completion、token 分布或服务全量日志；失败时只给最小相关 traceback/尾部日志。对用户只汇报结论、证据路径、失败原因和下一步，不输出内部思考过程。

## 宿主机 vLLM：物理 GPU 1

vLLM 运行在宿主机，不在 StateBus 开发容器中启动。固定服务名：

```text
statebus-vllm-qwen3-32b-allcap
```

先做只读/静态检查：

```bash
cd /home/qcrs/statebus/project
source deploy/activate_statebus_contest_rebuild.sh
python scripts/check_contest_rebuild_environment.py --json
scripts/manage_vllm_qwen3_32b_allcap.sh check
scripts/manage_vllm_qwen3_32b_allcap.sh status
```

只有用户明确要求启动或替换服务时，才在宿主机执行：

```bash
STATEBUS_ALLCAP_VLLM_CUDA_VISIBLE_DEVICES=1 \
  /home/qcrs/statebus/project/scripts/manage_vllm_qwen3_32b_allcap.sh restart
```

管理脚本内部使用 `nohup`，会精确停止同模型、同端口旧服务后异步启动。不得再包一层 `nohup`，不得另开重复实例。状态与日志：

```bash
/home/qcrs/statebus/project/scripts/manage_vllm_qwen3_32b_allcap.sh status
tail -F /home/qcrs/statebus/logs/statebus-vllm-qwen3-32b-allcap.log
```

服务能力与 thinking 分层：服务打开 APC、metrics、top-logprobs、prompt embeds/latent extension 等 all-cap 能力，不表示实验启用它们；thinking 始终由每个请求的 `enable_thinking=false` 控制，改变它不需要重启 vLLM。

## Docker 内测试：root 或 qcrs 均可

Docker 仅承载 StateBus 实现、测试和后续 benchmark client。它通过 `network_mode: host` 访问宿主机 `127.0.0.1:53334`。

优先复用现有 `statebus-dev-qcrs`，不要无理由 `down` 或强制重建。确需首次启动时在宿主机执行：

```bash
cd /home/qcrs/statebus/project
export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
export STATEBUS_DOCKER_TARGET=core
export STATEBUS_NVIDIA_VISIBLE_DEVICES=0
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d
```

物理 GPU 1 留给宿主机 vLLM。若容器测试需要 embedding GPU，默认只给物理 GPU 0；容器内它映射为 `cuda:0`，因此显式设置 `STATEBUS_EMBED_DEVICE=cuda:0`。只跑纯 CPU/unit tests 时不要占 GPU。

root 口径：

```bash
docker exec --user root statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh >/dev/null
  cd /workspace/statebus/project
  python3 -m pytest -q tests/v2/test_contest_rebuild_environment.py
'
```

qcrs 口径：

```bash
docker exec --user qcrs \
  --env HOME=/home/qcrs \
  --env NPM_CONFIG_PREFIX=/home/qcrs/.local \
  statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh >/dev/null
  cd /workspace/statebus/project
  python3 -m pytest -q tests/v2/test_contest_rebuild_environment.py
'
```

`scripts/run_v2_full_qwen3_container.sh` 本身兼容 root/qcrs，并会生成四角色 non-thinking 配置；但它是历史完整 runner，不得在新 P/L/R 实现、数据冻结、gate 和 preregistration 未完成前当作新正式实验入口。

## 验证顺序

按风险分层，禁止一开始直接跑正式全矩阵：

1. 宿主机 contest offline preflight；不得访问 endpoint。
2. Docker 内格式、静态检查、相关 unit/contract tests，使用 `pytest -q`。
3. Docker 内 `python3 -m runtime.smoke` 和相关 `tests/v2` 聚焦回归。
4. 完成 Prefix/Logit/Memory/semantic 最小闭环后，跑无模型 lifecycle、序列化、PID consumer、release、fail-closed 和 negative-control tests。
5. 仅在对应 gate 获得授权后，执行一次 `/metrics` schema 核对或一次固定 `top_logprobs` probe；请求必须 `enable_thinking=false`。
6. 数据 rights/provenance、gold 隔离、配置 hash 和 preregistration 全部冻结后，才运行 P/L/R dev pilot。
7. dev gate 通过后才能运行 frozen holdout；严格串行、独立 run root、失败保留。
8. cold cache/restart、公开 filing 下载、正式成组请求和最终 openEuler validation 各自需要独立授权，授权互不传递。

root 与 qcrs 不必无意义重复整套昂贵实验。权限、挂载、shared memory、artifact ownership 等身份敏感测试至少各跑一次；其余正式矩阵固定一个身份，并把 UID/GID、container image digest、配置 hash 和 run root 写入 manifest。

## 动作 gate

默认保持下列 gate 为 `0`：

```text
STATEBUS_CONTEST_ALLOW_METRICS_CHECK
STATEBUS_CONTEST_ALLOW_TOP_LOGPROBS_PROBE
STATEBUS_CONTEST_ALLOW_FILING_DOWNLOAD
STATEBUS_CONTEST_ALLOW_FORMAL_EXPERIMENTS
STATEBUS_CONTEST_ALLOW_COLD_CACHE
STATEBUS_CONTEST_ALLOW_SERVICE_RESTART
STATEBUS_CONTEST_ALLOW_OPENEULER_VALIDATION
```

实现、fixture、单元测试和 offline preflight 可以继续；访问服务、下载数据、重启、运行正式实验或 final openEuler 前，必须检查对应 gate 和用户授权。不要因为用户授权了一个动作就推定其他动作也获准。

## 执行纪律与交付

- 从 `06_implementation_plan_and_acceptance.md` 的 A0 开始，维护逐阶段状态；一次只推进满足前置条件的阶段。
- 每次改代码前先读调用方、合同和已有测试，沿用仓库模式；不要重写无关模块。
- 每个机制必须有正常、negative、fail-closed、release/cleanup 测试。
- 所有声称都附实际 artifact 路径和 hash；planned、implemented、tested、observed、benefit 分开写。
- 任何失败都保留并解释，不调 holdout/gold/阈值迎合结果。
- 每轮对用户只给简短状态：已完成、验证结果、仍阻塞的 gate、下一步。不要输出长篇思考过程。

现在开始：先完整阅读上述资料，核对当前 branch/dirty worktree、正式 non-thinking 配置和 A0 前置条件；然后在不触发任何 live gate 的前提下，执行能安全完成的第一段实现与 Docker 聚焦测试。不要只给计划后停止。

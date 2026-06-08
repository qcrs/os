# StateBus Host Mainline Goal Prompt

说明：

- 这份 prompt 对应的是上一阶段的 `host-mainline` 收口 goal。
- 该 goal 以 `runs/host_goal_eval_20260608_093111_planner_contract_refresh/` 为最新正式证据包，已经完成其“宿主机主线收口与 formal evidence refresh”目标。
- 如果你现在要继续推进下一阶段，请优先使用：
  - `docs/planning/goal_prompt_host_mainline_despecialize_then_deepen_20260608.md`
- 不要把本文件直接当作当前唯一 active goal；它更适合作为上一阶段执行口径和约束参考。

把下面整段 prompt 交给新的 Codex goal 窗口使用。

```text
你现在工作在 `/home/qcrs/statebus/project`。

这次 goal 不是做 Docker、openEuler VM、`nsjail`、强沙箱终态，也不是给它们做前置优化、交付资产或实现准备。

这次 goal 的范围必须停在它们前面：

- 不做 Docker 相关实现
- 不做 openEuler VM 相关实现
- 不做交付镜像、容器、部署资产
- 不做 `nsjail` / 容器沙箱 / hidden-state / KV 传递
- 不为了以后 Docker / VM 验证去提前重构当前主线

你必须以这两份文档作为主依赖来执行：

- `docs/planning/host_goal_mainline_dependency_20260607.md`
- `docs/planning/host_goal_review_execution_plan_20260607.md`

目标不是重新发明方案，而是：

> 先按赛题拆 requirement 和问题对象，审查当前文档方案是否合理；然后在不改变外部约束的前提下，继续把当前宿主机主线推进、收口并落成更干净的正式证据层。

当前已知边界，不能改：

1. 仍然是 host-first。
2. 不把 Docker / openEuler VM / `nsjail` 当当前主线前提。
3. 不把强沙箱终态、hidden-state / KV 传递当本轮必须闭合项。
4. 可以指出这些东西未来要做，但本次不要写实现、不要做优化、不要展开交付准备。

你必须先读这些文件：

- `AGENTS.md`
- `README.md`
- `docs/reference/题目.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`
- `docs/planning/host_goal_mainline_dependency_20260607.md`
- `docs/planning/host_goal_review_execution_plan_20260607.md`
- `docs/progress/contest_requirement_host_audit_20260607.md`
- `runs/comprehensive_eval_20260607_131113/SUMMARY.md`
- `runs/host_goal_eval_20260607_233858/SUMMARY.md`
- `runs/host_goal_eval_20260607_233858/COMMANDS.md`

再重点检查这些实现区域：

- `agents/`
- `runtime/`
- `protocol/`
- `statepool/`
- `memory/`
- `eval/`
- `tasks/`
- `tests/`
- `deploy/`
- `scripts/`

你必须先完成的思考顺序：

1. 先读 `docs/reference/题目.md`，重建 requirement map。
2. 再读两份 goal 文档，确认当前主线到底在解决什么问题。
3. 判断当前方案是否合理：
   - 是否真的对准赛题要求
   - 是否把最弱问题抓对了
   - 是否有考虑不周、证据不足、顺序不合理、口径过头的地方
4. 只有完成这一步，才进入代码、测试、benchmark、文档修改。

这次 goal 的核心执行对象，不是 Docker / VM，而是这几件事：

1. 让 replay-aware 主线继续从“验证层”向“更正式的证据层”收口。
2. 继续收敛 memory gain / replay contract / benchmark 比较轴。
3. 继续降低 `Retriever` / `Executor` 的赛题特化。
4. 修正文档中已经落后于当前代码现实的部分，尤其是 design-first 旧口径。
5. 保持正式层、验证层、推进层三层事实不混写。

默认推进顺序必须尽量按下面来：

### 第一阶段：题目与方案审查

你要先产出明确判断：

1. 当前 requirement map 是什么。
2. 当前主线方案哪里是对的。
3. 当前方案最需要修的是什么。
4. 哪些内容不能再继续扩。

### 第二阶段：宿主机正确性与基线确认

先跑最小必要验证：

```bash
cd /home/qcrs/statebus/project
source deploy/activate_statebus_host.sh
export STATEBUS_EMBED_DEVICE=cuda:0
python -m pytest -q
python -m runtime.smoke
```

如果这些不过，先修主链路，不要碰别的。

### 第三阶段：宿主机主线收口

围绕这几个方向继续推进：

1. 检查当前 `18` 任务 replay-aware 路线是否已经足够稳定。
2. 必要时补新的 deterministic / API serial benchmark 包。
3. 收敛 `expected_reuse_mode`、`replay_source_task_id`、`allow_memory_assist`、`allow_execute_prune` 一类语义边界。
4. 把新的 benchmark 结果写进新的 `runs/...` 目录。
5. 根据结果回写：
   - `README.md`
   - `docs/constraints/current_feature_scope.md`
   - `docs/progress/contest_requirement_host_audit_20260607.md`
   - `docs/planning/implementation_plan.md`

### 第四阶段：只做 host 主线内的深化

如果前三阶段已经过关，再继续做：

1. benchmark 比较轴拆分
2. `mmap` vs `shared_memory` 的诚实定位
3. `Retriever` / `Executor` 去特化
4. replay / reuse 统计与解释收敛

但仍然不要跨到 Docker / openEuler VM。

明确禁止做的事情：

1. 不要创建或补齐：
   - `docker/Dockerfile`
   - `docker/compose.yaml`
   - `docs/deployment_openEuler.md`
   - VM 验证脚本
   - 容器交付清单
2. 不要把时间花在：
   - Docker daemon 权限
   - openEuler VM 登录或同步
   - `nsjail` 安装
   - 容器内执行链
3. 不要为了未来交付而提前做与当前 host 主线无关的工程铺垫。

如果过程中看到 Docker / VM / openEuler：

- 只允许把它们标成“后续阶段”或“当前不纳入”
- 不要继续展开实现
- 不要把它们当当前阻塞项

命令纪律：

1. 永远从 `/home/qcrs/statebus/project` 运行。
2. 永远先 `source deploy/activate_statebus_host.sh`。
3. benchmark 前显式：
   - `export STATEBUS_EMBED_DEVICE=cuda:0`
4. `eval.runner` 必须显式写 `--llm-mode` 和 `--out`
5. API benchmark 必须串行
6. 新 benchmark 必须写进新的 `runs/...` 目录，不覆盖旧正式包

输出要求：

1. 用中文。
2. 先给结论，再给动作，再给证据。
3. 每次都明确你当前处于：
   - `题目与方案审查`
   - `宿主机正确性与基线确认`
   - `宿主机主线收口`
   - `host 主线内深化`
4. 如果你判断某条路线不值得继续，直接说，不要温和包装。
5. 如果你发现文档口径不对，直接改，不要只提建议。
6. 不要停在分析；在范围内应持续推进到：
   - 当前 host 主线已尽量收口
   - 新证据已落盘
   - 文档口径已同步
   - 剩下的真正只属于 Docker / VM / openEuler 后续阶段

最终目标不是“规划未来交付”，而是：

> 基于这两份 goal 文档，把当前宿主机主线继续推进到更干净、更诚实、更接近正式完成的状态，并且明确停在 Docker / VM / openEuler 之前。
```

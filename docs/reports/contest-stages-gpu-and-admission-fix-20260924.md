# Contest Stages: GPU Environment and Admission Repair

日期：2026-09-24

## 结论与范围

可以开始新的 GPU Stage 1 开发准入批次，不应运行 `all` 或正式 40 次矩阵。
本轮修复 GPU 解释器选择、Stage 1 外层验收和 Stage 2 定位，只执行离线测试、
服务只读检查与一次成功的短文本 GPU embedding。没有运行新的业务任务或 LLM 请求，
没有重启服务、替换容器、安装依赖、停止其他进程，也没有修改 `project/` 或 commit/push。

本报告中的命令替代此前 decision report 的 CPU 运行建议；旧报告、旧 runs 保留为历史证据。

## GPU 根因与验证

同一 `statebus-runtime` 容器内存在两个不同 Python 环境：

| 解释器 | PyTorch | CUDA | 用途判断 |
| --- | --- | --- | --- |
| `/usr/bin/python3` | `2.5.1+cpu` | 不可用 | 不能用于本批 GPU embedding |
| `/home/qcrs/statebus/conda-envs/statebus_host/bin/python` | `2.5.1+cu121` | `12.1`，可用 | 阶段脚本显式选择 |

激活宿主环境不会把显式调用的 `/usr/bin/python3` 变成 CUDA 版；关键是容器内真正执行的解释器。
不需要重新安装 torch 或手动导入额外 CUDA 包。

实际 embedding probe 通过：

- 执行环境是 openEuler 容器，Python/依赖来自挂载的 host Conda 环境，不冒称镜像原生依赖。
- `statebus.__file__` 为 `/workspace/statebus/os/statebus/__init__.py`。
- 可见一个 CUDA 设备；UUID `a53fa601-8471-d782-2971-46e5a8e5d328` 对应物理 GPU 1。
- Qwen3-Embedding-0.6B 模型参数全部在逻辑 `cuda:0`；一次真实 encode 产生 1024 维有限向量。
- 现有 vLLM 健康，模型为 `qwen3-32b`；API 返回 `max_model_len=8192`。
- GPU 1 和 GPU 2 均有其他作业，检查时利用率较高。此次不是独占性能测试。

初次 sandbox 内的 NVIDIA 权限失败和随后 UUID 的 `GPU-` 前缀格式差异均保留日志；
按批准方式检查宿主设备并规范化 UUID 前缀后通过。没有以重启服务绕过问题。

## 脚本与验收修复

`scripts/run_contest_measurement_stages.sh`：

- 复用 `start_statebus.sh --print-env` 的 profile 配置；支持显式解释器、容器名和 embedding 物理 GPU。
- 默认仅复用现有服务；`--preflight-only` 核对实际角色配置、CUDA UUID、模型参数设备和真实 encode。
- 宿主激活留下的 `auto` 明确解析为 `cuda:0`；显式冲突的 CPU 配置拒绝执行，不回退 CPU。
- `--start-services` 是另行显式选择，会运行既有启动 smoke；不与 `--preflight-only` 混用。
  在调用可能重建容器的旧入口前，拒绝缺失或非 workspace-root 挂载的容器，并先检查 GPU。
  本轮没有执行此选项。现有健康服务不需要执行它。
- 三批顺序固定为 `SB-NO-MEMORY -> SB-FULL -> P-TEXT`，每批四个任务。
- runner 失败后仍调用外层验收并保留原始成本；批次失败则不进入下一批。
- 三批期间检查源文件摘要，并比较有效模型配置和预算；变化则停止，不拼成冻结批次。
- dry-run 的计划 JSON 单独落盘，避免容器激活诊断文本混入 JSON。
- 输出目录必须新建，不覆盖或复用历史目录。

新增 `statebus/benchmark/contest_stage_gate.py`，不只相信 summary 成功标志：

- 核对精确任务集合 F01/F02/O01/O02、配置标签、Memory policy、结果身份和报告合同版本。
- 打开每任务 `result.json`、`scorer.json`，根据当前公开输入再次运行独立数值 scorer 和共同报告质量门。
- 核对执行环境、每任务有效预算和模型配置；重新汇总 provider journal，与 ledger 对账。
- 缺失 usage 保留 `null` 和原因，不转换成零；实际 Executor 请求单独统计，不使用 Runtime skip 计数冒充。
- 核对 Memory 的本链 producer、admission、grant/session/attempt、兼容性和消费记录。
  validated replay 还要有当前输入重执行、终态重算验证、输出绑定及已验证源码 hash 对应。
- Memory 未观察到消费记为 `not_observed`，不强迫命中、也不据此宣称收益。
  外层核验不替代 Runtime 的 authority 验证。
- 产出 `acceptance.json`，仍标记 `semantic_review_required=true` 和 `formal_headline_eligible=false`。
  机械门不覆盖完整自然语言推理质量。

`contest_stage1.py` 只增加干净计划文件和结果身份元数据，没有改变提示、质量门、模型预算或公开数据。

## Stage 2 与 Stage 3 的真实状态

Stage 2 当前写出 `stage2-admission.json` 后以退出码 2 停止，不加载模型、不发起替代实验：

| 项目 | 状态 | 含义 |
| --- | --- | --- |
| 真实模型 Memory 12 次对照 | `not_implemented` | 既有 deterministic 实验不能替代 |
| 非文本状态 6 次对照 | `implemented_not_run` | 入口存在，本轮没有执行 |
| 任务级 text/typed 4 次对照 | `not_implemented` | 仍是实际缺口 |
| CodeAct-off | `not_applicable`，`blocking=false` | 没有已验证合法共同路径，不作强制失败项 |

Stage 3 的正式 40 次 runner 尚未实现，继续明确拒绝执行，不调用旧实验冒充。

## 验证与证据

全部新证据位于 `os/runs/contest-stages-fix-20260924/`：

- `host-targeted-final.xml`：49 passed，包含阶段门负控、实际脚本批次停止逻辑、profile、CPU 冲突和防重建测试。
- `container-targeted-final.xml`：46 passed、4 skipped。跳过项依赖宿主 `jq`，已在 Host 验证；
  容器通过项包含真实 bwrap 新输入重执行、输入只读和超时检查。
  随后新增的防重建测试仅在 Host 执行，不并入这次容器测试计数。
- `container-targeted.xml`：保留早期 42 passed、1 failed 的记录；失败是把宿主编排测试放入缺少 `jq` 的容器，之后明确划分测试边界。
- `gpu-preflight-verified/preflight.json` 与 `preflight.log`：真实 GPU encode、解释器、依赖和资源快照。
- `historical-memory-schema-check.json`：新 Memory 核验函数对旧 live-v3 F02/O02 的真实字段交叉检查通过。
  这不是当前版本 Stage 1 验收，更不是新 GPU 性能样本。
- `stage2-admission-check/stage2-admission.json`：实际执行准入检查后预期拒绝，CodeAct-off 不阻塞。
- `stage1-dry-run.log`：当前三批命令，均显式使用 CUDA 解释器和 `cuda:0`。
- `bash -n` 与 `git diff --check` 通过。不同批次测试不合并计数。

## 交给用户执行

当前服务健康，无需先运行启动器或停止历史 PID。直接在宿主执行：

```bash
cd /home/qcrs/statebus/os
scripts/run_contest_measurement_stages.sh --stage 1 --preflight-only
scripts/run_contest_measurement_stages.sh --stage 1
```

两次命令默认各建一个带时间戳的新目录。手动指定 `--run-root` 时也必须分别用新目录。
运行过程中不要修改代码、提示、预算、profile 或模型服务。通过四任务批次后才自动进入下一配置。
失败时保留整个目录，定位根因后重新决定是否以新目录重跑，不挑选旧批次成功任务拼分。

8B 目前只完成配置解析验证，没有启动或做 GPU/live 验证；不能替换或混入这次 32B 对照。
GPU 新批次不能与此前 CPU 批次拼成性能成绩。共享 GPU 环境下先看正确性、请求数与 token 成本，
E2E 仅作为带资源争用条件的观察值；报告仍需人工语义审查。

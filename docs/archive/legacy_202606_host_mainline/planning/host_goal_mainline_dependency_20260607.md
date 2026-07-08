# StateBus 宿主机主线 Goal 依赖文档

日期：`2026-06-07`

适用范围：给后续 `goal` 模型或实现者作为直接执行依赖，明确当前宿主机阶段到底该解什么、不该解什么、为什么 `CodeAct` 应延后、`shared_memory` 值不值得做，以及下一条唯一主线应如何收束。

---

## 1. 先说结论

这一个 goal 的正确边界不是“把所有设计都做掉”，而是：

> 在不依赖更高权限、不把 Docker / openEuler VM 当当前阻塞项、不假装强沙箱已经闭环的前提下，把宿主机内能闭合的赛题主线尽量闭合，并把真正值得深化的部分做扎实。

对应成一句更工程化的话：

> 当前 goal 应该解决 `host-side requirement closure + honest deepening`，而不是 `terminal environment / sandbox / VM delivery closure`。

这意味着：

- 要继续做：共享记忆真实增益、`Retriever/Executor` 去特化、benchmark 比较轴拆分、replay 合同语义收敛、`mmap/shared_memory` 宿主机内正式对比。
- 不要抢做：`nsjail`、Docker daemon 依赖链、openEuler 终态交付、root 级观测、hidden-state/KV 级状态传递。

### 1.1 进入执行前，先拆赛题与审方案

后续 `goal` 模型不要一上来就跑命令、补代码、补 benchmark。

当前正确顺序应先固定为：

1. 先读 `docs/reference/题目.md`，把赛题拆成可核对的要求、边界、交付物。
2. 再读本文件、`README.md`、约束文档、实现代码，重建“当前方案到底想解决什么问题”。
3. 然后判断当前文档里提出的主线方案是否合理：
   - 是否真的对准赛题要求
   - 是否把问题对象拆对了
   - 是否有考虑不周、证据不足、实现顺序不合理的地方
4. 在不改变当前外部约束的前提下，再决定：
   - 哪些方案应继续执行
   - 哪些方案应收缩、改写或降级口径
   - 哪些只是文档想法，还不该直接推进
5. 只有完成这一步，才进入命令执行、代码修改、benchmark 补证据。

这里的关键不是“重新发明一套方案”，而是：

> 先从赛题和问题对象反推当前方案是否站得住，再按计划执行；不是先执行，再事后给方案找解释。

特别注意：

- 允许优化方案顺序、问题拆分方式、证据要求和口径。
- 不允许擅自改写当前已经明确锁定的外部约束：
  - 仍然是 host-first
  - 仍然不把 Docker / openEuler VM / `nsjail` 当当前主线前提
  - 仍然不把强沙箱、hidden-state/KV 传递当本轮必须闭合项
- 如果发现文档方案有不周到之处，应先在文档中明确指出，再决定是否进入实现。

---

## 2. 当前事实层必须分成三层

后续 goal 模型必须严格区分下面三层事实，不能混写。

### 2.1 当前正式已证据化层

这一层以 `README.md` 和 `runs/comprehensive_eval_20260607_131113/` 为准：

- `protocol` 相比 `text` 已有正式通信压缩证据，API 串行 repeat-10 还证明了真实时延收益。
- `StateRef + mmap/shared_memory + SQLite + FAISS` 已经是可运行宿主机实现，不再只是设计稿。
- 当前共享记忆正式结果仍是 assist-only，不可声称已有 step skip 或 runtime gain。
- `shared_memory` 和 `UDS` 当前是宿主机可行路径，但还不是正式主 headline。

直接锚点：

- `README.md:120-171`
- `runs/comprehensive_eval_20260607_131113/SUMMARY.md`
- `runs/comprehensive_eval_20260607_131113/api_repeat10_serial/benchmark_report.md`
- `runs/comprehensive_eval_20260607_131113/deterministic_repeat10/benchmark_report.md`

### 2.2 当前已验证但尚未升格为 repeat-10 正式基线层

这一层以新的 host-goal 验证包和当前已通过测试的代码为准：

- 当前任务集已经扩到 `3` 组链、每组 `6` 任务，共 `18` 任务；
- `assist -> skip_execute -> skip_retrieve_execute` 已经进入可运行 benchmark；
- 当前 repo 内验证包已经证明：
  - deterministic repeat-1 下存在非零 `skipped_step_count` 与 `reuse_gain`
  - serialized API repeat-1 下也存在非零 `skipped_step_count` 与 `reuse_gain`
- 但这一层仍不是新的 repeat-10 稳定性基线。

直接锚点：

- `runs/host_goal_eval_20260607_233858/SUMMARY.md`
- `runs/host_goal_eval_20260607_233858/deterministic_repeat1/benchmark_report.md`
- `runs/host_goal_eval_20260607_233858/api_repeat1_serial/benchmark_report.md`

### 2.3 当前 worktree 正在推进但尚未继续收口层

这一层以当前未提交代码为准：

- replay-aware 主线的代码、文档和评测口径还在继续收敛；
- 仍然存在“新验证层”与“旧 repeat-10 基线层”并存的事实分层问题；
- 但这些还不能直接当作“正式结果已经成立”。

直接锚点：

- `tasks/sample_benchmark.yaml:1-273`
- `runtime/orchestrator.py`
- `agents/sample_agents.py`

因此，后续 goal 模型的基本纪律是：

1. 可以把这条方向当作当前主开发方向。
2. 不能把它直接写成“新的 repeat-10 正式基线已经证明”。
3. 需要先把“当前验证层”和“当前推进层”分别收口，再决定是否升级正式层。

---

## 3. Git 管理纪律

这部分不是附属说明，而是当前 goal 能否收口干净的前提。

### 3.1 当前 Git 基线

写本文件时，当前仓库基线是：

- 分支：`main`
- `HEAD`：`6994efc`
- 当前 worktree：`dirty`

当前 dirty worktree 不是异常，但必须被正确解释：

- 它表示“当前有推进中的实现方向”；
- 不表示“这些方向已经进入正式事实层”；
- 更不表示 `README` / 正式 benchmark / 对外口径可以直接跟着改写。

### 3.2 分层原则

当前仓库至少要维持 3 层 Git 语义：

1. **正式基线层**
   - 已提交
   - 有测试 / benchmark / 文档能对上
   - 可以写进 `README`、约束文档、对外说明
2. **当前推进层**
   - 可以在 worktree 或短期 topic branch 上推进
   - 可以写入 audit / planning 文档
   - 不能直接当正式完成项
3. **实验观察层**
   - 临时 benchmark、局部日志、草稿分析
   - 只用于判断是否继续推进
   - 不应直接污染正式结论

后续 goal 模型最容易犯的错，就是把第 `2` 层和第 `1` 层混掉。

### 3.3 分支与提交策略

当前推荐的 Git 策略是：

- `main` 只承载当前收口后的正式状态。
- 较大的 replay / benchmark / executor 改动，优先在短生命周期 topic branch 上收敛，再回到 `main`。
- 一个提交只解决一个清晰对象，不要把“任务集扩写 + runtime 语义改写 + README 口径改写 + benchmark 结果补录”揉成一个大提交。

推荐的提交粒度：

1. contract / runtime 语义提交
2. 测试与 benchmark 统计提交
3. 文档口径与证据引用提交

如果必须合并，也至少要保证代码、测试、文档在同一对象上闭环，而不是多对象混杂。

### 3.4 正式证据入库规则

后续只要涉及 benchmark 或“已经证明”的说法，都要遵守：

- 新证据进入新的时间戳目录，不覆盖旧正式包。
- `runs/comprehensive_eval_20260607_131113/` 这种目录一旦被当作正式包引用，就视为冻结证据。
- 新的 memory gain / replay gain 结果，应写入新的 `runs/...` 目录，再回写文档。
- 不要因为当前 worktree 成功了一次，就直接把 `README` 里的“assist-only”口径改成“已经 skip”。

### 3.5 每次收口前的最小 Git 检查

后续 goal 模型或实现者，在准备把某条能力升格为“正式已完成”前，至少要做这几步：

```bash
git status --short
git rev-parse --short HEAD
git diff --stat
```

然后明确回答 4 个问题：

1. 这条结论对应的是已提交事实，还是未提交推进？
2. 这次改动是否混入了无关对象？
3. 这次 benchmark 是否有独立落盘证据目录？
4. 文档里的表述是否需要继续保持“当前 worktree 方向”而不是“正式已证明”？

### 3.6 当前 goal 的 Git 收口要求

这一个 goal 的 Git 管理目标不是“提交越多越好”，而是：

- 保持正式层和推进层分离；
- 保持 commit 粒度足够小，便于回看；
- 保持 benchmark 证据有单独目录；
- 保持 `README` / 约束文档 / 审计文档三者口径一致。

只有做到这几点，后续 goal 模型才不会把实现推进过程写成一团混乱的“半事实层”。

---

## 4. 这个 goal 的边界

### 4.1 明确纳入 goal 的内容

下面这些都属于“当前宿主机内应该解决”的内容：

1. 先把赛题拆成可验证的 requirement map，并核对当前方案是否真的对准题目。
2. 先审当前文档和代码提出的问题定义、主线方案、实现顺序是否合理。
3. 如果方案有漏洞，先修正文档中的问题拆分、阶段顺序、证据要求，再进入实现。
4. 让共享记忆从 assist-only 进入可证明的 gain。
5. 把 replay 语义从“任务标签驱动”尽量收敛成“运行时证据驱动”。
6. 拆开 benchmark 比较轴，避免把通信收益和记忆收益混在一起。
7. 降低 `Retriever` / `Executor` 对当前样本语料和 playbook 的过度贴合。
8. 给 `shared_memory` 一个诚实的宿主机内位置：不是摆设，也不是 headline 幻觉。
9. 把文档、测试、benchmark 口径重新对齐。

这里新增的前置要求是：

> 先做 requirement / problem / solution 三层审查，再做实现推进。

不要把“按计划执行”理解成“直接继承文档结论”；应先检查这个计划本身是否合理。

### 4.2 明确排除在当前 goal 外的内容

下面这些不是当前 goal 的阻塞项：

- `nsjail` 正式安全链
- Docker daemon 依赖开发流
- openEuler VM 最终复现与交付验证
- root 级 `perf` / `bpftrace` / `eBPF`
- 容器内 CodeAct 终态
- hidden-state / KV cache 级中间状态传递
- 完整分布式多机 runtime

这些内容可以保留为后续阶段，但不能反向绑架当前 goal。

### 4.3 命令分层与默认限制

后续 goal 模型不要把所有命令当成同一等级来跑。当前应固定分成 4 层：

1. **只读 / 环境确认层**
   - 用途：确认当前仓库、GPU、Python、env 是否正常
   - 命令：
   ```bash
   cd /home/qcrs/statebus/project
   git status --short
   git rev-parse --short HEAD
   nvidia-smi
   source deploy/activate_statebus_host.sh
   export STATEBUS_EMBED_DEVICE=cuda:0
   python --version
   python -m pytest --version
   ```
2. **本地正确性层**
   - 用途：确认当前改动没有破坏主链路
   - 命令：
   ```bash
   python -m pytest -q
   python -m runtime.smoke
   ```
3. **宿主机 benchmark 层**
   - 用途：验证 deterministic / shared_memory / UDS 路径
   - 命令必须显式写 `--llm-mode` 和 `--out`
   - 这些 benchmark 可以频率高于 API，但仍然不能每改一行就重跑
4. **真实 API benchmark 层**
   - 用途：形成正式 timing / token / protocol 证据
   - 必须串行
   - 一次只能开一个 benchmark 进程
   - 只有在前面 3 层通过后才值得跑

命令纪律：

- 永远从 `/home/qcrs/statebus/project` 运行。
- 永远先 `source deploy/activate_statebus_host.sh`。
- embedding 默认强制 `STATEBUS_EMBED_DEVICE=cuda:0`，不要让 goal 模型自己猜 `cpu` 或 `auto`。
- `eval.runner` 必须显式传 `--llm-mode` 和 `--out`。
- API benchmark 不得并发启动；历史上的 `api_repeat1/`、`api_repeat10/` 只能算诊断，不是正式时间证据。

### 4.4 什么时候允许跑真实 benchmark

后续 goal 模型应把真实 benchmark 当成“里程碑检查”，不是“思考辅助工具”。

允许跑一次真实 benchmark 的前提至少是：

1. 当前改动已经落在明确对象上，而不是大范围未收束脏改。
2. `python -m pytest -q` 通过。
3. `python -m runtime.smoke` 通过。
4. 如果改动触及 replay / runner / tasks / statepool / executor，则至少已有一轮宿主机 deterministic 路径验证。
5. 本次 benchmark 的目标清楚：
   - 是验证协议收益
   - 还是验证 memory gain
   - 还是验证 shared_memory / UDS capability

不满足这些条件时，不要跑真实 benchmark，只做本地正确性和定向逻辑验证。

### 4.5 benchmark 频率与结果保留规则

后续 goal 模型应遵守下面的频率控制：

1. **测试优先，benchmark 滞后**
   - 大多数改动先跑 `pytest + runtime.smoke`
   - 只有通过后，才进入 benchmark
2. **deterministic benchmark 只在相关改动后跑**
   - 当改动触及 `runtime/orchestrator.py`、`agents/sample_agents.py`、`eval/runner.py`、`tasks/sample_benchmark.yaml`、`statepool/store.py` 时再跑
3. **shared_memory benchmark 只在后端相关改动后跑**
   - 当改动触及 state backend、embedding state backend、清理逻辑时再跑
4. **UDS benchmark 只在 transport 相关改动后跑**
   - 当改动触及 `runtime/uds_transport.py`、`runtime/remote_executor.py`、executor transport 集成时再跑
5. **API repeat-10 只在阶段收口时跑**
   - 当前不应频繁跑
   - 只有当 protocol / replay / eval 语义达到一个可说明的里程碑时，才跑一次串行正式 API benchmark

结果保留规则：

- 每次正式 benchmark 都写入新的时间戳目录。
- 不覆盖旧结果。
- 跑完后立刻记录：
  - commit / dirty 状态
  - benchmark 目的
  - 是否 formal 还是 diagnostic
- 如果只是中途探测命令能否启动，结果应写到临时目录或明确标为 diagnostic，不得混进正式证据目录。

---

## 5. 为什么 CodeAct 现在应延后

结论先说：

> `CodeAct` 现在延后不是因为它“没价值”，而是因为它在当前阶段会显著放大不稳定性、权限依赖和论证噪声，而且不会优先补上当前最弱证据。

### 5.1 它不是当前赛题闭环的卡点

题目是“鼓励 CodeAct”，不是“没有 CodeAct 就不算完成”。当前真正卡分的不是有没有代码生成执行，而是：

- 共享记忆是否真的减少了步骤或重复计算；
- 协议收益是否有正式 benchmark；
- 非文本状态是否真实传递；
- 多 Agent 主线是否能稳定 repeat-10。

当前前 3 条里，最弱的是第一条，不是 `CodeAct`。

锚点：

- `docs/reference/题目.md:25-26`
- `README.md:129-131`
- `docs/progress/contest_requirement_host_audit_20260607.md:310-334`

### 5.2 它会把执行层问题变成“过早魔法化”

当前 `Executor` 仍然主要是：

- `FEATURE_BUNDLE.route` 驱动的 tool/playbook 选择；
- `ToolRegistry` + `LightweightSubprocessRunner`；
- `UDS` 外部多进程样机。

如果这时把 `CodeAct` 提前抬成主线，会有 4 个直接问题：

1. `Executor` 边界会重新变糊，tool-first 路线还没站稳就会被“一次性生成代码”吞掉。
2. benchmark 结果会掺入代码生成随机性，导致当前最需要收敛的 replay / memory gain 证据变脏。
3. 没有强沙箱时，CodeAct 只能宿主机直接跑或弱隔离跑，口径会更危险。
4. 评委/读者会更容易追问安全性，而当前仓库并没有正式安全链可答。

直接锚点：

- `runtime/executor_runtime.py:12-98`
- `runtime/executor_runtime.py:210-320`
- `docs/constraints/current_feature_scope.md:100-118`

### 5.3 它当前会引入权限和环境依赖

真正值得讲的 `CodeAct`，不是“LLM 能生成一段 Python 然后直接跑”，而是：

- 受控输入
- 受控输出
- 受控文件边界
- 无网络或受限网络
- 资源限制
- 最好还有隔离命名空间 / seccomp / jail

这些恰好都落在当前环境的延期区：

- `nsjail` 未安装
- Docker daemon 不可用
- openEuler VM 终态未验证

所以现在推 `CodeAct`，很容易变成“名义上做了，实际上没有可信安全边界”。

### 5.4 什么时候再把它抬回来

只有在下面 3 件事成立后，`CodeAct` 才适合重新升优先级：

1. `Executor` 的 tool-first 契约已经稳定。
2. memory gain 与 replay 证据已经正式闭环。
3. 宿主机外的隔离环境有可用验证路径。

也就是说，`CodeAct` 适合做：

- 第二阶段增强项
- 展示型加分项
- 最终交付前的系统性补强项

它不适合继续占用当前主 goal 的第一优先级。

---

## 6. shared_memory 到底有没有必要做

结论先说：

> 有必要做，但不该抢成“唯一主线”或“最大亮点”。

更准确地说：

> `shared_memory` 值得保留为真实宿主机能力和正式对比对象，但当前主线仍应以 `mmap` 为准。

### 6.1 为什么它有必要

它至少有 4 个正当理由：

1. 它直接呼应赛题里鼓励的 IPC / 共享内存方向。
2. 它能增强“非文本状态传递不是纯文件落盘伪装”的说服力。
3. 它是后续更强状态通道的近邻，不会把未来路线锁死在单一文件路径。
4. 它是当前宿主机就能做的真实 OS 能力，不需要等 VM / Docker。

### 6.2 为什么它现在不能抢主线

`shared_memory` 现在仍不该抢掉 `mmap` 主线，原因也很直接：

1. 生命周期与清理归属更容易出问题。
2. 多进程边界下更容易混入资源泄露和 benchmark 噪声。
3. 当前正式 benchmark 还没有给出 matched 的 `mmap vs shared_memory` 结论。
4. 当前最弱项仍是 memory gain 证据，而不是状态后端选型。

因此正确定位是：

- `mmap`：当前默认主线
- `shared_memory`：当前真实备选路径 + 正式对比对象
- `UDS + shared_memory`：后续可做宿主机深化，但不是本轮 headline

### 6.3 当前 goal 对 shared_memory 的最低要求

这一轮不是要求把系统改成“以 `shared_memory` 为核心”，而是要求做到：

1. 后端真实可跑，不是死代码。
2. 测试路径真实覆盖。
3. 至少补一组 matched benchmark，对比 `mmap` 与 `shared_memory` 的代价和收益。
4. 文档口径清楚写明它的地位。

如果时间够，再进一步做：

- 看 `skip_execute` / `skip_retrieve_execute` 下，两种后端是否在 state copy / reuse 代价上出现差异。

---

## 7. 单一主线方案

当前只推荐这一条主线：

> host-first、tool-first、replay-contract-aware、evidence-driven memory reuse。

它展开后是：

1. `Planner/Summarizer` 继续保持可控 LLM 入口。
2. `Retriever` 负责 repo-local 检索、共享记忆检索、轻量特征抽取。
3. `Executor` 先被收敛成通用工具执行层，而不是继续装作分布式 CodeAct runtime。
4. `Orchestrator` 根据运行时证据决定 `assist / validated replay / exact replay / skip_execute / skip_retrieve_execute`。
5. benchmark 分成通信轴和记忆收益轴两套。
6. `mmap` 保持默认；`shared_memory` 做真实对比；`UDS` 保持宿主机 transport 样机定位。

### 7.1 第一阶段：先闭本地正确性，不急着跑重 benchmark

第一阶段的目标不是“赶快出新图表”，而是先保证当前改动没有把主链路搞坏。

建议顺序：

```bash
cd /home/qcrs/statebus/project
git status --short
git rev-parse --short HEAD
source deploy/activate_statebus_host.sh
export STATEBUS_EMBED_DEVICE=cuda:0
nvidia-smi
python --version
python -m pytest --version
python -m pytest -q
python -m runtime.smoke
```

这一阶段没过，不要进入真实 benchmark。

### 7.2 第二阶段：只做与改动对象匹配的宿主机验证

本地正确性通过后，不是直接跑所有 benchmark，而是按改动对象选择：

1. 改了 replay / memory / runner 语义：
   - 先跑 deterministic 主线
2. 改了 `shared_memory` 或 state backend：
   - 再补 shared_memory 路径
3. 改了 transport / remote executor：
   - 再补 UDS 路径

推荐命令：

```bash
python -m eval.runner --repeat 10 --llm-mode deterministic --out runs/<stamp>/deterministic_repeat10 --quiet-progress
python -m eval.runner --repeat 1 --llm-mode deterministic --statepool-backend shared_memory --embed-state-backend shared_memory --out runs/<stamp>/deterministic_shared_memory --quiet-progress
python -m eval.runner --repeat 1 --modes protocol --llm-mode deterministic --executor-transport uds --out runs/<stamp>/deterministic_uds --quiet-progress
```

### 7.3 第三阶段：达到收口门槛后，再跑一次真实 API benchmark

真实 API benchmark 不是日常回路，而是收口检查。

只有在下面条件都成立后才跑：

1. 本地正确性通过。
2. 宿主机 deterministic 路径已通过。
3. 当前变更已经足够稳定，值得形成一份新正式证据。
4. 当前没有另一个 benchmark 进程在跑。
5. 能明确说明这次 API rerun 想验证什么。

正式 API benchmark 命令应固定为串行：

```bash
python -m eval.runner --repeat 10 --modes text,protocol --llm-mode api --out runs/<stamp>/api_repeat10_serial --quiet-progress
```

约束：

- 一次只开一个 benchmark 进程。
- 不把 `api_repeat1/`、并发跑出来的 `api_repeat10/` 当正式 timing 证据。
- 如果当前只是改文档、改注释、改不影响 benchmark 的外围逻辑，不要重跑 API。

### 7.4 第四阶段：第一次正式 rerun 后，再进入深化

只有拿到第一轮新的正式 rerun 后，才值得进入下一层深化：

1. 拆 benchmark 轴
2. 收敛 replay 合同
3. 补 memory gain 证据
4. 做 matched `mmap/shared_memory` 对比
5. 继续把 `Executor` 往更清晰的 tool contract 推进

也就是说，深化不是“先加更多功能”，而是：

> 先拿到一轮新的正式证据，再决定下一轮该深化哪个薄弱点。

---

## 8. 当前最关键的设计修正

### 8.1 不要让 `expected_reuse_mode` 回退成运行时主导开关

当前代码已经往前走了一步：

- `Orchestrator` 不再直接按 `expected_reuse_mode` 决定是否尝试 skip；
- `skip_retrieve_execute` 当前由显式 `replay_source_task_id` 合同触发；
- `skip_execute` 当前由显式 `allow_execute_prune` 开关和运行时证据共同触发；
- `Retriever` 的 assist 入口也已从“直接看期望标签”收敛到显式 `allow_memory_assist`。

但它仍明显保留 benchmark 合同驱动痕迹：

- `allow_memory_assist` / `allow_execute_prune` 仍来自 benchmark task contract；
- 当前 replay-aware 收益仍主要由受控任务集触发，而不是开放式运行时自然冒出。

锚点：

- `tasks/sample_tasks.py`
- `agents/sample_agents.py`
- `runtime/orchestrator.py`

当前最应该做的修正是：

> `expected_reuse_mode` 应继续保持 benchmark expectation / 标签地位，不要再把它接回运行时策略主驱动；下一步要逐步降低对 task-contract 开关的依赖。

运行时真正应看的，是：

- `reuse_signature`
- `feature_route`
- `retrieved_doc_ids`
- `candidate_doc_ids`
- `replay_source_task_id`
- artifact / evidence hash
- memory metadata 一致性

### 8.2 把 replay 语义拆成 4 层

后续 goal 模型应按下面 4 层明确实现，而不是继续混成一个“reuse”：

1. `assist`
   - fresh retrieval 仍然执行
   - memory 只补充 hint / summary / route prior
2. `validated replay`
   - fresh retrieval 执行
   - route / docs / hashes 一致时允许 `skip_execute`
3. `exact replay`
   - 有显式 replay source
   - query / route / docs / contract 都匹配时允许 `skip_retrieve_execute`
4. `reject`
   - 命中 memory，但 fresh evidence 或 contract 不一致

### 8.3 benchmark 必须拆成两条主轴

当前最容易被混淆的地方，是通信对比和记忆收益对比搅在一起。

后续 goal 模型应把 benchmark 至少拆成：

1. **通信轴**
   - `text vs protocol`
   - 固定 fresh retrieval
   - 不混入 replay skip
2. **记忆收益轴**
   - `cold vs assist vs validated replay vs exact replay`
   - 固定在同一模式下，例如 `protocol`
   - 直接比较 `skipped_step_count`、`reuse_gain`、`task_ms`

如果这两条轴不拆开，后面很容易继续出现“memory_hit_rate 看起来差不多，但到底说明了什么”这种解释噪声。

---

## 9. 文件级实现依赖

后续 goal 模型如果继续实现，优先关注这些文件。

### 9.1 `tasks/sample_benchmark.yaml`

要做的不是继续堆任务，而是把任务集明确变成两类：

- 通信对比任务
- replay / reuse 任务

同时把 `expected_reuse_mode` 从“运行时暗指令”收敛成“评测期望标签”。

### 9.2 `tasks/sample_tasks.py`

这里需要承担：

- task schema 的 expectation 字段清洗
- replay source / reuse contract 的更清晰建模

### 9.3 `agents/sample_agents.py`

这里的主要工作是：

- 把 `Retriever` 的 memory accept / reject 逻辑尽量改成 evidence-driven；
- 把 `expected_reuse_mode` 的直接策略作用降到最低；
- 保留 `FEATURE_BUNDLE`，但让它更像运行时中间态，而不是 benchmark 特化容器。

### 9.4 `runtime/orchestrator.py`

这里是本轮最关键文件。

需要继续收敛：

- `skip_execute`
- `skip_retrieve_execute`
- `reused_from_memory_id`
- `skipped_step_count`
- replay 匹配合同

重点不是“让 skip 发生”，而是“让 skip 发生得诚实、可解释、可验证”。

### 9.5 `runtime/executor_runtime.py`

这里要继续把 `Executor` 从 route-specific playbook selector 往前推一截：

- 清晰区分 `tool registry`
- `tool contract`
- `tool result`
- replay-able artifact

但不要在这一轮把它扩成“真 CodeAct runtime”。

### 9.6 `eval/runner.py`

这里必须负责把 benchmark 轴拆开，并把新的 reuse 统计做干净：

- `skipped_step_count`
- `reuse_gain`
- `expectation_match_rate`
- `validated_reuse_task_count`
- 按 benchmark family 分组汇总

### 9.7 文档层

至少应同步：

- `README.md`
- `docs/constraints/current_feature_scope.md`
- `docs/progress/contest_requirement_host_audit_20260607.md`

原则只有一个：

> 正式结果、当前 worktree 方向、后续增强项，三层不能再混。

---

## 10. 当前 goal 的优先级顺序

后续 goal 模型应按这个顺序推进：

1. **先拆赛题并重建问题对象**
   - 读 `docs/reference/题目.md`
   - 拆 requirement map
   - 明确当前赛题到底要求什么、不要求什么
2. **再审当前方案是否合理**
   - 读本文件、`README.md`、约束文档、关键实现
   - 判断当前问题拆分、主线方案、实现顺序有没有考虑不周
   - 如果方案本身不稳，先修正文档口径和执行顺序
3. **再过本地正确性门**
   - `pytest`
   - `runtime.smoke`
4. **再过宿主机验证门**
   - deterministic
   - 必要时 shared_memory / UDS
5. **再跑一次真实 formal benchmark**
   - 串行 API repeat-10
   - 只在阶段收口时跑
6. **拿到 formal 结果后，先补最弱证据**
   - memory gain
   - replay 合同
7. **再拆比较轴并去特化**
   - benchmark 拆轴
   - `Retriever/Executor` 去赛题特化
8. **最后才考虑更重的增强项**
   - 更强 transport
   - CodeAct 演示
   - 更后面的 VM / Docker / 终态交付准备

如果时间或 token 不够，宁可停在第 `7` 步，也不要为了“看起来更高级”跳去做 `CodeAct` 或 Docker 链。

---

## 11. 当前不该讲什么

后续任何文档、报告、答辩口径里，都不要把下面这些写成当前主成果：

- `CodeAct` 正式链已完成
- 强沙箱已完成
- openEuler 终态已完成
- `shared_memory` 已经显著优于 `mmap`
- hidden-state / KV 级状态传递已落地
- 当前系统是通用多 Agent runtime
- `UDS` 已经代表完整分布式 runtime

这些要么未验证，要么不是当前主线，要么根本还没到该讲的时候。

---

## 12. 当前应该讲什么

当前最强、最诚实、也最利于后续实现收敛的亮点应是：

1. 宿主机内 `text/protocol` 双模式正式 benchmark 已成立。
2. `StateRef + FEATURE_BUNDLE + shared memory backends` 让非文本状态传递不是空话。
3. 共享记忆已经从“只命中”推进到“正在收敛 replay contract”。
4. 当前项目主线是 host-first contest prototype，方向明确，不再被 Docker / VM 阻塞。

---

## 13. 最终判断

`CodeAct` 当前延后，没有方向性问题；相反，这是为了避免把当前主线带偏。

`shared_memory` 有必要继续做，但它的价值是：

- 增强宿主机状态传递真实性
- 提供正式对比对象
- 为后续更强数据面保留入口

而不是抢占 `mmap` 主线或替代当前最重要的 memory gain 证明工作。

因此，这一个 goal 最正确的定义就是：

> 除去权限、真实操作系统终态、VM/Docker 最终验证这些外部边界，把宿主机内能诚实解决的赛题完成项和主线深化项尽量解决，并把结果收敛成正式证据层。

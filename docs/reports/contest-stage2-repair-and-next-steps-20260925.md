# Stage 2 修复、真实验证与后续执行

日期：2026-09-25。实现目标为 `os/`，当前分支 `contest-core-repair-20260921_000126`。保留既有脏工作树，未修改 sibling `project/`，未创建 commit 或 push。本报告接续 36 号 prompt 与原始 Stage 2 smoke 报告。

当前结论：导致 s1/on 输出 `null` 的公共 CodeAct 提示问题已修复，并已有 s1 三组真实通过证据；新增 F06/O06 的公开 v2 任务、计算合同和独立 scorer 已接通，两次真实模型验证均通过。完整 Stage 2／Stage 3 仍不能宣布通过，原因是完整机制实验和部分 caller 尚未完成。这里的“不准入”是本地实验门禁，不是比赛官方判定项目不合格。

## 1. 原故障与已经落地的修复

### Semantic State：状态传过去了，业务输出却没过质量门

原始失败位于 `runs/contest-stage2-live-smoke-20260925a/` 的 `semantic-holdout-s1/on`。实际 Python 把 JSON 传输中的转义照抄成 `r"\\s+"`，没有生成所需的 `r"\s+"`，所以文本匹配失败、声明为字符串的输出变成 `null`；还使用了 sandbox 不允许的 `re.compile`。一次 repair 去掉 compile 后，错误转义仍在。

修复位于 `statebus/runtime/llm_codeact.py` 的公共生成／repair 指引：明确区分 JSON 传输转义和 Python regex 源码，使用允许的 `re.search`／`re.match`。没有把答案写入模板，没有把 null 强转成字符串，也没有放宽 sandbox、validator、类型或引用检查。

已经完成的修复后复测在 `runs/contest-stage2-state-regex-fix-20260925b/`：

- s1 的 `off/on/consumer_off` 三组均通过业务质量门。
- on 的 publish=2、transfer=2、consume=2，`downstream_effect=true`，release/reclaim 闭合。
- off 和 consumer_off 没有下游状态消费效果；consumer_off 保留生产成本。
- on 输出了实际字符串，包括 `limited cold-storage dock availability` 和 `North Coast corridor`。

这是该 s1 故障已消除的证据，不代表 s3 inactive control 或完整六次 state 实验已经完成。本次收尾只复核这些已有文件，没有再发起三次相同模型任务。

### F06/O06：补齐真实口径变化，避免把旧任务改名冒充

修复/补齐的共同路径包括：

- `contest_stage1_taskpack.py`：新增 v2 dictionary、不同原始字段及公开业务说明。F06 按 booked revenue 减 refund 算净收入；O06 按最终失败请求／已完成请求算错误率，failed attempts 仅为诊断字段。
- `adaptive_formal.py`、`adaptive_formal_mainline.py`、`contest_stage1_text.py`：规划、生成、当前输入重算和文本路径遵守相同公开合同。
- `contest_stage1_scorer.py`：独立 Decimal reference calculation 检查新公式；把 booked revenue 当净收入、把 failed attempts 当最终失败都会被拒绝。
- `contest_stage1.py`、`contest_stage2.py`：Memory 正式两链入口接到同一个 public worker，支持 12 次计划、遇错停止、前轮失败阻断和逐任务账本。

v2 使用独立随机数流，原始四任务的 CSV 与历史发布文件逐字节一致。v2 明确是“新口径首个批次”，`risk_change=initial`；不把旧口径趋势生搬过来，也不伪造 F03–F05/O03–O05 历史。F06/O06 的加入仍不能代替 Stage 3 所需的第三类业务任务。

### 记账：防止离线通过被误写成 live 通过

收尾时修复了同一实验入口的几处问题：

- live 提前停止后，后续组件原本可能沿用 offline 的 `passed`，其行还会被写成 `evidence_scope=live`；现在保留离线证据，未运行组件单独记 `not_started`。
- 离线检查失败且指定 `--stop-on-failure` 时，在真实模型工作之前停止。
- Memory 与 state 的实际逐任务状态写回 `task-plan.json`，不再把已执行的正式任务误列为未开始；state 原始 variant 行进入统一 raw rows。
- `diagnostic_only` 通信不再构成 `smoke_passed=true`。
- shell admission 和旧 readiness 报告不再声称 Memory runner 缺失；准确标注 runner 已有、该检查没有执行正式实验。

这些修复改变的是执行编排和证据分类，不改变已有真实任务的输入、模型、评分或原始结果。旧 run 文件没有重写。

## 2. 本轮新增真实模型结果

结果根：`runs/contest-stage2-v2-live-20260925c/`。复核汇总：该目录下 `review-summary.json`，逐项核对 summary、independent scorer 和 provider journal。

| 任务 | 配置与结果 | 任务耗时 | provider requests | prompt / completion / total tokens |
| --- | --- | ---: | ---: | --- |
| F06 | Memory none；数值、schema、引用及业务报告检查通过 | 107.842 s | 5 | 12051 / 1772 / 13823 |
| O06 | Memory none；数值、schema、引用及业务报告检查通过 | 126.545 s | 6 | 14359 / 2104 / 16463 |

每个任务 Executor 各生成一次；F06 Summarizer 请求 2 次、O06 请求 3 次，全部计入成本，不能未经核对把这些请求统称为 repair。两项 `business_report_errors=[]`。自然语言全面语义审阅仍标为 `semantic_review_required=true`。

复用既有 `statebus-runtime` openEuler 容器、host Qwen3-32B 服务及 Embedding 配置；本轮未重启服务、改模型参数或创建容器。服务实际 context 为 8192；这是运行时观察，不是本轮改成了 8192。只跑了获准的两次新增业务验证，没有启动正式 12 次 Memory 实验或 40 次主实验。

这两次是独立的新口径 smoke，Memory 均关闭。它们证明真实模型能解 v2 任务，尚不证明 Memory-on 遇到口径变化时会正确拒绝旧方法；后者必须放回两条链中比较。

## 3. 验证范围

- 新口径／旧输入冻结／独立评分／失败分母等检查通过；修改输入后旧答案被拒绝。
- 主沙箱两项 real-bwrap 集成测试曾失败；同一相关测试集合在现有 openEuler 容器复核为 **140 passed、5 skipped**，所选 real-bwrap 集成检查通过。这是环境边界差异，不能把主沙箱失败隐藏成第一次就全绿。
- 随后的报告分类与停止逻辑修复：`test_contest_stage2_v2.py`、`test_contest_stage2.py`、`test_contest_stage_gate.py` 共 **48 passed**。这些测试与前一集合有重叠，不相加作总测试量。
- shell syntax、Python 编译与 `git diff --check` 通过。
- 最终 offline contract 产物：`runs/contest-stage2-repair-offline-20260925d/`。Memory/state/communication/public projection 合同通过，CodeAct not_applicable、cross-agent blocked。此处 communication 的通过仅指静态载体合同，不是实际接收 Agent 的业务对照。

## 4. 为什么现在仍不准入

| 项目 | 当前已有证据 | 尚缺什么 |
| --- | --- | --- |
| Memory | 原 F01/F02 两配置共 4/4；replay F02 Executor 请求为 0；新增 v2 两项各一次通过 | 两条三任务链 × none/replay 的完整 12 次；尤其 v2 对旧 Memory 的兼容性判定和首次成本 |
| Semantic State | 修复后的 s1 三配置 3/3，真实 publish/transfer/consume/effect | 正式 s1+s3 六次对照，保留 inactive/no-consumer 边界 |
| Communication | 载体离线检查、Stage 1 callback 观察 | 同接收方的 text/typed 真实任务对照和包含 hydration 的成本 |
| Cross-agent Memory | 底层 Memory 合同存在 | 一条真实不同 Agent 的存储→检索→授权→消费证据链 |
| CodeAct | 已有真实 Python 生成、sandbox 执行、Artifact 与验证 | 没有共同合法 off 路径，故对照 not_applicable；按 36 号 prompt 不阻塞核心交付 |
| Stage 3 | Stage 1 小任务包及上述局部验证 | 完整 F01–F10/O01–O10、第三类任务、对应独立 scorer/live 验证、40 次入口 |

因此 `formal_stage2_ready=false`、`stage3_allowed=false` 仍应保留。不能把不同时刻、不同配置的 smoke 拼成正式矩阵，也不能仅改布尔值放行。与此同时，未完成通信不妨碍继续执行已经接通的 Memory 单项实验。

## 5. Stage 2、Stage 3 分别做什么

**Stage 2 检验机制。** 逐项改变 Memory、state 或通信方式，观察当前输入正确性、下游实际消费、重复工作以及成本。36 号 prompt 的计划是 Memory 12 次、state 6 次、communication 4 次，另有可选 CodeAct 4 次和至少一条 cross-agent 证据。CodeAct 没有合法 off 路径时不硬凑对照。

**Stage 3 检验完整产品。** 财务、运维各 10 个有关联的任务，完整 StateBus 与 P-TEXT 各执行一遍，共 40 次，回答连续任务是否稳定完成、质量和总成本如何。它需要至少三种有实际业务含义的任务，不能用两种任务换标题凑数。当前 runner 仍未实现，暂不提供一个假装可执行的 Stage 3 命令。

这两个 stage 是本项目的实验组织方式，不能当成赛方指定的固定实验轮数。

## 6. matched receiver、跨 Agent Memory 与 KV 的关系

**matched receiver 是通信实验的可比接收方。** 让同一个下游角色，在同输入、模型、工具、输出目标和 scorer 下，一次接收 text，一次接收 typed message/Ref，并真实执行任务。不能仅比较两个字符串的字节长度，也不能只统计很短的 Ref 却漏掉读取实际数据的成本。完整 SB 与 P-TEXT 的产品比较可以保留，但不能自动把产品差异全部归因于通信编码。

**跨 Agent Memory 是不同 Agent 复用共享记忆。** 例如 Executor 产生 verified 的方法或证据，另一个实际 Agent 后续经检索、Grant 授权消费，保留 MemoryRef、消费回执和来源链。当前同一 Executor 跨任务 replay 已有价值，但不能单凭它宣称“不同 Agent”已经复用。

它们是两个不同的缺口；没有“必须先完成 KV 才能补 matched receiver”的依赖。普通共享 Memory 保存的方法、证据、摘要即可，不要求传 GPU KV cache 或隐藏状态。KV/hidden-state 工作继续延后。

依据本地比赛题目 `project/docs/reference/题目.md`：第 12 行要求纯文本／结构化同任务对比，第 17 行要求允许不同 Agent 复用记忆；通信效率 25 分、记忆复用 20 分。赛题允许 embedding/语义向量等非文本表示，没有强制 KV。

建议补这两项，因为它们直接回应赛题要求；验证可以小而明确。通信先用支持的一个任务跑 text/typed 两次接收 smoke，跑通后按现有设计补到两个任务共四次；跨 Agent 先做一条真实共享 Memory 消费 smoke 即可。无需为此先扩建 KV 系统或大规模统计实验，也不应让静态 JSON round-trip 代替实际业务消费。

## 7. 下一步顺序与命令

1. **先执行 Memory 单项 12 次**：F01→F02→F06、O01→O02→O06，分别 none/replay。重点确认 F02/O02 当前输入重算以及 F06/O06 拒绝不兼容旧方法；任何额外重新生成也要计费。这轮尚未执行。
2. **补最小真实 communication receiver 与 cross-agent caller**，复用已有合同和权限边界。现阶段不建设 KV/hidden-state 路径。
3. **完成 state s1+s3 正式六次及共同报告复核**。已通过的局部 smoke 不重复当新成绩。
4. 机制证据就绪后补第三类任务、完整两条十轮链和 Stage 3 runner，再安排 40 次产品比较。

已 dry-run 验证下列命令解析为 **12 个 Memory slot**。运行时会重新 preflight，复用现有服务；若输出目录已存在，必须选新目录。此命令在本轮只做了 dry-run，没有启动正式模型实验：

```bash
cd /home/qcrs/statebus/os
scripts/run_contest_measurement_stages.sh \
  --stage 2 --mechanism memory \
  --stage1-root /home/qcrs/statebus/os/runs/contest-stage1-history-fix-20260925b \
  --profile qwen3-32b-gpu2-u050 \
  --embedding-gpu 1 \
  --container-name statebus-runtime \
  --runtime-python /home/qcrs/statebus/conda-envs/statebus_host/bin/python \
  --stop-on-failure \
  --run-root /home/qcrs/statebus/os/runs/contest-stage2-memory-v2-campaign-20260925d
```

单项 Memory 即使全通过，整体 `formal_stage2_ready` 仍可能是 false；先查看 Memory component 与逐任务 ledger，不要把“整个 Stage 2 尚缺别项”误判成“Memory 执行失败”。

## 证据入口

- 原始失败报告：[contest-stage2-mechanism-smoke-20260925.md](contest-stage2-mechanism-smoke-20260925.md)。仅代表原批次。
- s1 修复后已有证据：[acceptance.json](../../runs/contest-stage2-state-regex-fix-20260925b/acceptance.json)。
- 本轮两次新口径 smoke：[review-summary.json](../../runs/contest-stage2-v2-live-20260925c/review-summary.json)。
- [F06 summary](../../runs/contest-stage2-v2-live-20260925c/F06/summary.json)、[O06 summary](../../runs/contest-stage2-v2-live-20260925c/O06/summary.json)。
- 最终离线结果：[acceptance.json](../../runs/contest-stage2-repair-offline-20260925d/acceptance.json)。仅代表合同检查。

上述分别是原始失败、修复后已有运行、本轮新增运行和最终离线检查；源码实现状态、运行证据与赛题要求分别表述，没有合并为一个虚构的正式通过结果。

# StateBus Native Latent Long-Document and Plan Remediation

日期：2026-07-22

分支：`feat/yzm-v2-migration`

## 1. 结论

本轮已把 native latent benchmark 从短叙事扩展为三类非表格任务：

- 长文档因果分析；
- 跨文档证据综合；
- 根据签字观察值和分支规则选择 operating plan。

第三类是文档驱动的条件分支选择，不是 Runtime Controller 在执行失败后的动态
replan。当前结果不能作为 Controller replan 证据。

原有 C0 路线已证明这组任务可解：完整 v5 中 C0 为 `22/24`。Native latent 的
真实 capture、recurrence、engine-local ref、consumer forward 和 release 仍为
`6/6`，但质量没有闭环：修复模板后 16-step L1 为 `4/24`，恢复设计稿 40-step
下界后为 `8/24`。因此当前问题属于 latent alignment/representation 路线，不是
表格任务依赖，也不是 C0 原路线不可用。

严禁据此声明 latent 提升质量、降低时延或减少总字节。当前准确表述是：

```text
native engine-local latent handoff mechanism demonstrated
+ long-document/cross-document/conditional-plan workload covered
+ quality and performance benefit not demonstrated
```

## 2. v5 任务与隔离合同

Active v5 manifest：

`v2/benchmark/samples/latent_narrative_holdout_v5/manifest.json`

SHA256：

`293abef320c534480ba58358b1f1801e5b2ca86878a96ae84c1255ed9a4b118e`

任务共 6 个 case、24 个 required facts，每类 2 个 case。每个 case 显式声明
`source_item_ids`，EvidencePack 只包含授权文档；跨文档结论必须引用所有声明来源。
Expected facts、term groups 和预期 plan 不进入模型可见 surface。

Scorer 固定为 `statebus.required_fact_phrase.v2`，只做 deterministic phrase/普通词形
匹配和引用检查，不用语义模型替模型输出抬分。历史 v1 manifest 未修改，SHA256 仍为：

`d53c26351732620f3aee6198efc1f6b03147d633a733db8edcf47ce526515c4e`

## 3. 完整 v5 结果

Artifact root：

`/home/qcrs/statebus/runs/statebus_latent_v5_full_20260722_012204`

Checksums 全部通过。

| Lane | facts | mechanism/fallback | 解释 |
| --- | ---: | ---: | --- |
| C0 | 22/24 | full selected evidence | task solvability gate 通过 |
| T0 | 14/24 | Retriever text handoff | 低于冻结 quality floor |
| A0 | 2/24 | anchors only | 无有效信息收益 |
| L1 | 2/24 | latent success 6/6 | 机制成立，质量失败 |
| N1 | 23/24 | pre-forward reject + C0 fallback 6/6 | 负向门成立，不计 latent success |

按类别的 C0/L1：

| 类别 | C0 | L1 |
| --- | ---: | ---: |
| 长文档因果分析 | 7/8 | 1/8 |
| 跨文档综合 | 7/8 | 1/8 |
| 条件 plan 选择 | 8/8 | 0/8 |

L1 每例 tensor 为 `[16,5120]` BF16、163,840 bytes；6 例 capture、15 次 recurrence、
consumer worker-forward 和 release 均完整。完整矩阵解释为
`workload_has_no_demonstrated_latent_need`，`quality_matrix_passed=false`。

## 4. 找到并修复的 latent 合同缺陷

### 4.1 Qwen thinking 不对称

C0/T0 的 OpenAI-compatible chat 请求显式使用
`chat_template_kwargs.enable_thinking=false`，原 latent producer 的 tokenizer 模板没有
传这个参数。16 个 latent step 可能主要覆盖 Qwen thinking 开头，而不是任务事实。

Middleware 现在优先以：

```text
tokenize=false
add_generation_prompt=true
enable_thinking=false
```

渲染 producer messages，并为不支持该参数的 tokenizer 保留兼容回退。

### 4.2 L1 consumer 缺少对称 chat 边界

原 L1 consumer 直接 tokenization 一段裸 `rendered_prompt`，而 C0 使用完整
Summarizer system/user chat。现在 `LatentCompleteRequest` 可携带结构化 messages，
middleware 使用同一 tokenizer/chat template 渲染后再在唯一 marker 处分割；旧的
pre-rendered prompt 调用仍兼容。Messages 必须包含同一 rendered prompt 且 marker
只能出现一次，否则 fail closed。

### 4.3 Step 上限与设计稿冲突

设计稿预先规定第一版 `latent_steps=40`，实现却把 API、registry 和启动脚本上限固定为
32。上限已恢复为 80，health 新增 `registry_max_steps` 审计字段。40-step 只使用设计稿
已有下界，不修改 expected facts 或评分阈值。

### 4.4 Compatibility identity 不能再是未知值

旧 health 中 model revision 为 `None`、chat template digest 为 `unknown`，精确兼容门
实际是在比较两个未知值。启动脚本现在从本地 model manifest、tokenizer 和
tokenizer config 生成稳定 SHA256；support matrix 对空值、`None`、`null`、`unknown`
全部 fail closed。Position contract 也覆盖 non-thinking template kwargs 和 consumer
render mode。

## 5. Post-remediation 诊断

这些 case 已经被观察过，因此以下只用于定位机制，不是新的 formal holdout。

### 5.1 对称模板，16 steps

Artifact root：

`/home/qcrs/statebus/runs/statebus_latent_v5_l1_template_fix_20260722_0220`

结果：L1 `4/24`，latent mechanism `6/6`，checksums 全部通过。相较旧 L1 的
`2/24` 有改善，但仍远低于 C0。

### 5.2 对称模板，40 steps

Diagnostic v6 manifest：

`v2/benchmark/samples/latent_narrative_holdout_v6/manifest.json`

SHA256：

`6c08351e3b08672b494f6dec98f73194fb3d6754aee4c498266254089ecd9e9c`

Artifact root：

`/home/qcrs/statebus/runs/statebus_latent_v6_l1_40step_20260722_0230`

结果：L1 `8/24`，其中长文档 `4/8`、跨文档 `2/8`、条件 plan `2/8`。Mechanism
仍为 `6/6`；每例 tensor 为 `[40,5120]` BF16、409,600 bytes，总 tensor bytes 为
2,457,600；checksums 全部通过。

40-step 结果表明更多状态能保留更多事实，但仍出现错误数值、错误时间、泛化动作和
遗漏条件。继续在同一已观察 case 上增加 step 或调 top-k/temperature 只能算 post-hoc
tuning，不能形成可信收益证据。

## 6. 剩余问题归属

| 问题 | 归属 | 当前证据 |
| --- | --- | --- |
| 任务是否只支持表格 | 已修复的 benchmark 覆盖问题 | v5 三类任务均为 narrative/document driven |
| C0 原路线是否能解 | 原路线当前可用 | 22/24，三类分别 7/8、7/8、8/8 |
| T0 文本压缩是否足够 | 文本 handoff 预算问题 | 14/24，未过 floor |
| L1 是否真实进入模型 | latent 机制已成立 | 6/6 worker-forward proof |
| L1 是否保留足够事实 | latent 当前核心问题 | 16-step 4/24，40-step 8/24 |
| Plan switching 是否已证明 | 只证明文档分支选择 | 未证明 Runtime Controller dynamic replan |
| Latent 是否更快/更省 | 未证明 | 质量不等价，tensor 体量也不可忽略 |

下一阶段若继续 latent，必须先冻结新的 alignment/adapter 机制，再使用未见过的新
holdout。候选方向是 learned adapter、layer/KV working-memory 路径或明确降级为
engine-local prefix reuse；不能通过修改 expected facts 来提高分数。

## 7. 实机与回归状态

当前服务：

| 字段 | 值 |
| --- | --- |
| tmux | `statebus-vllm-latent` |
| PID | `1904684` |
| GPU | physical index 1 |
| GPU UUID | `GPU-a53fa601-8471-d782-2971-46e5a8e5d328` |
| endpoint | `127.0.0.1:53334` |
| model | Qwen3-32B, vLLM 0.9.2/V0 |
| registry max steps | 80 |
| readiness | ready, no errors |
| log | `/home/qcrs/statebus/logs/vllm_latent_20260722_identity_fix.log` |

Exact-identity 2-step live probe：

`/home/qcrs/statebus/runs/statebus_latent_identity_probe_20260722_0245/mechanism_probe_identity-probe-20260722.json`

Probe `ok=true`，`[2,5120]` BF16 capture、1 次 recurrence、consumer worker-forward、
one-shot rejection 和 release 全部通过。Probe 的生成内容不构成质量证据。

最终串行静默回归：

| 范围 | 结果 |
| --- | --- |
| `tests/v2/neural` | `83 passed` |
| `tests/v2` | `686 passed, 3 skipped` |
| repository full | `988 passed, 3 skipped, 1 warning` |

唯一 warning 是 installed LangGraph 的 `allowed_objects` pending-deprecation，不是本轮
StateBus 回归失败。Runtime freeze audit 已更新并通过，63 个冻结文件无 changed/added/
removed 项；freeze SHA 为：

`01b919a7280bcc5f0931b6bf136386ab984d7977337529bd529e2f68686e4866`

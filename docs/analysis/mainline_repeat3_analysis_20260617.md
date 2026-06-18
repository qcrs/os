# StateBus Mainline Repeat-3 深度分析

日期：2026-06-17 14:11
运行：`/home/qcrs/statebus/runs/statebus_mainline_repeat3_suite_20260617_141158/`
门禁全部通过。13+1 个 pack（新增 `contest_honest_headline_v1`）。

---

## 一、contest_honest_headline_v1 — 本轮最重要的新包

### 1.1 与旧 contest_dual_mode_controlled_v3 的关键差异

| 维度 | old: contest_dual_mode_controlled_v3 | new: contest_honest_headline_v1 |
|---|---|---|
| single_variable | no (mode + handoff_object) | **yes (mode)** |
| text 侧 | text_strict_pure_lane（携带 Route: 字段） | **text_whole_lane**（纯自然文本，无结构化字段） |
| whole_lane_text_guard | 0.00（hidden_field_leak=1.00） | **1.00**（leak=0.00） |
| object_parity_gate | not_yet | **pass** |
| withheld | leak + coverage 等 4 个原因 | **仅 contest_repeat_insufficient** |
| 定位 | internal controlled composite | **contest-facing formal headline** |

### 1.2 数据

| 指标 | text_whole_lane | protocol | delta |
|---|---:|---:|---:|
| control_bytes | 8657 | 6641 | **-2016 (-23.3%)** |
| task_ms | 3177 | 3274 | +97 (+3.0%) |
| llm tokens | 415 | 416 | **+1 (+0.2%)** ← 几乎相同！ |
| exact_match | — | — | 0.70 |
| admissible | — | — | 1.00 |
| wrong_family | — | — | **0.00** |

### 1.3 关键发现

**llm_tokens 现在几乎相同**（415 vs 416）。之前 strict_pure_lane 的 text summarizer 只用 315 tokens，protocol 用 415（+32%）。因为 strict_pure_lane 不传 route/tool 给 executor，executor 只能做最简执行，summarizer 收到的是精简的输出。而 text_whole_lane 给 summarizer 的是自然语言 handoff，信息量接近 protocol 的结构化 digest——token 终于对称了。

**但 task_ms 略慢 +97ms**——protocol 的 typed state 开销（StatePool 读写 + msgpack 序列化）使通信节省没能转化为端到端加速。

**这个包的合同是对赛题最诚实的回应**：`single_variable=yes, variable_axes=mode`。text 侧用 `text_whole_lane`（真正的自然文本协作），protocol 侧用 `state_packet_minimal`。不再有 "mode + handoff_object 同时变无法归因" 的问题。

---

## 二、contest_dual_mode_controlled_v3 — 降级为 internal

这个包现在被明确标注为 "internal controlled composite surface, not the contest-facing honest pure-text baseline"。新增 withheld：`text_template_slot_leak_detected`。

```
withheld: whole_lane_text_guard_incomplete, text_hidden_field_leak_detected,
          text_template_slot_leak_detected, contest_repeat_insufficient
```

`text_template_slot_leak_detected` 意味着 fairness 修复后的 structured text 格式（Route:/Tool:/Route source:/Route confidence:...）被 guard 检测到模板槽位泄漏。

数据面与上轮一致：control_bytes -19.8%, wrong_family 0.00, admissible 1.00, exact 0.70。

---

## 三、memory_dual_mode_fairness_v3 — text 侧 replay 修复！

这是本轮第二大惊喜。对比上轮：

| 指标 | 上轮 text | 本轮 text | 上轮 protocol | 本轮 protocol |
|---|---|---|---|---|
| working_assist hit_rate | 0.00 | **1.00** | 1.00 | 1.00 |
| validated_replay skipped | 0.00 | **1.00** | 1.00 | 1.00 |
| exact_replay skipped | 0.00 | **2.00** | 2.00 | 2.00 |
| exact_replay reuse_gain | 0.00 | **0.67** | 0.67 | 0.67 |
| exact_replay task_ms | ~4600 | **1726** | 1743 | 1610 |

**Text 侧现在有完整的 replay 能力！** 上轮 text_whole_lane 全 generic_triage、零 replay benefit。这轮 text 侧的 exact_replay 降到 1726ms（上轮 ~4600ms），reuse_gain 0.67。说明 text_whole_lane 的 handoff 格式现在能携带足够的结构化元数据让 memory replay 生效。

**Object parity gate: pass** ✅。双模式 memory fairness 现在两端都有 replay 收益，不再是不对称的"protocol 有、text 没有"。

---

## 四、planner_support_v3 — 新报告格式

报告改为拆分 yaml vs llm 的 admissible：

```
yaml_control_admissible_match_rate: 0.80
llm_plan_admissible_match_rate: 0.83
```

yaml 行 0.80（5 行中 4 行正确），llm 行 0.83（6 行中 5 行正确）。llm plan 的可容许可率略高于 yaml——LLM 生成的计划没有比固定 plan 差。

但 `planner_one_shot_valid_rate: 0.00` 与 `planner_repair_attempt_total: 0` 共存——语义上矛盾。如果 repair=0（没有 repair 需要），one_shot_valid 应该是 1.00。这更像是新报告格式的指标计算口径问题，不是 Planner 本身的问题。

`planner_llm_request_count=6.00, planned_step_count=38.00` 与上轮一致。Planner 本身工作正常。

---

## 五、其余 pack — 稳定

| pack | 关键指标 | 状态 |
|---|---|---|
| typed_state_mechanism_v3 | exact 1.00, adm 1.00, wrong 0.00 | ✅ 稳定 |
| memory_policy_controlled_v3 | exact 1.00, replay gate pass, reuse 0.67 | ✅ 稳定 |
| typed_state_consumer_sensitivity_v3 | missing_fail 1.00, wrong_tool 1.00, expected_neg 15, unexpected 0 | ✅ 稳定 |

---

## 六、汇总

| 发现 | 类型 |
|---|---|
| `contest_honest_headline_v1` 作为真正的赛题 headline，single_variable=yes, leak=0, 仅 withheld for repeat | 架构进步 |
| text_whole_lane 的 llm_tokens 与 protocol 几乎相同（415 vs 416），消除了之前的 token 不公 | 积极信号 |
| memory_dual_mode text 侧 replay 已恢复（exact_replay 1726ms, reuse 0.67） | 修复回归 |
| `planner_one_shot_valid_rate: 0.00` 与 `repair: 0` 矛盾 | 报告口径需确认 |
| `contest_dual_mode_controlled_v3` 正式降级为 internal surface | 口接收敛 |

**这个 run 是目前最干净的。** contest_honest_headline_v1 解决了 single_variable 归因问题和 hidden_field_leak 问题。memory_dual_mode 的 text replay 恢复消除了不对称性。三条赛题主线（通信/状态/记忆）都有 clean 的 formal surface 承载。

# State Transfer Benchmark API Repeat-3 Result Lock 2026-06-10

日期：`2026-06-10`

目的：

- 固定当前 `state_transfer` redesign 后的正式 live API `repeat=3` 结果
- 避免后续再次把 `carrier / authenticity / natural_support` 三条线混成一个 headline

对应运行包：

- `runs/benchmark_redesign_api_r3_carrier_20260610/`
- `runs/benchmark_redesign_api_r3_authenticity_20260610/`
- `runs/benchmark_redesign_api_r3_natural_support_20260610/`

---

## 1. 结论先锁定

当前 `state_transfer` 三条线都已经按 redesign 后的 contract 独立跑通，报告面干净，没有重新混回旧 aggregate headline。

但 `repeat=3` 结果说明：

1. `typed handoff authenticity` 成立
2. `carrier efficiency` 当前只可说“接近持平、略偏 text_packet 更快”，不能说 `state_packet_minimal` 稳定胜出
3. `natural-text support` 只能继续保留为 support-only，不能升格成 headline

因此当前最稳妥的正式口径是：

> `state_transfer` 机制真实性已经成立；
> `carrier` 路线已经得到公平对比，但在当前 `repeat=3` live API 包里还没有形成稳定的端到端优势；
> `natural free-text` 继续只作 support evidence。

---

## 2. Carrier Pack 结果

来源：

- `runs/benchmark_redesign_api_r3_carrier_20260610/benchmark_report.md`

表内结果：

- `text_packet_minimal`
  - `control_bytes = 5171.00`
  - `handoff_textual_bytes = 1586.00`
  - `handoff_nontext_bytes = 0.00`
  - `llm_total_tokens = 675.00`
  - `task_ms = 4614.49`
- `state_packet_minimal`
  - `control_bytes = 5175.67`
  - `handoff_textual_bytes = 765.33`
  - `handoff_nontext_bytes = 1220.33`
  - `llm_total_tokens = 673.00`
  - `task_ms = 4685.94`
- `delta(state_packet_minimal - text_packet_minimal)`
  - `control_bytes = +4.67`
  - `handoff_textual_bytes = -820.67`
  - `handoff_nontext_bytes = +1220.33`
  - `llm_total_tokens = -2.00`
  - `task_ms = +71.45`

锁定解释：

- `state_packet_minimal` 继续稳定减少文本 handoff
- 但当前 live API `repeat=3` 下，它没有形成稳定端到端优势
- token 几乎持平
- `task_ms` 反而比 `text_packet_minimal` 略高

因此当前 **不能** 把 carrier 线写成：

> `state packet` 在正式 API 结果里已经稳定更快、更省

当前 **只能** 写成：

> `carrier` 线已经被干净拆出，并证明 `state packet` 显著降低 textual handoff；
> 但在当前 `repeat=3` live API 结果里，端到端代价基本持平，暂未形成稳定 headline 优势。

---

## 3. Authenticity Pack 结果

来源：

- `runs/benchmark_redesign_api_r3_authenticity_20260610/benchmark_report.md`

表内结果：

- `text_brief`
  - `control_bytes = 5075.33`
  - `handoff_textual_bytes = 1830.00`
  - `handoff_nontext_bytes = 0.00`
  - `llm_total_tokens = 663.56`
  - `task_ms = 4550.21`
- `state_ref`
  - `control_bytes = 5882.33`
  - `handoff_textual_bytes = 772.33`
  - `handoff_nontext_bytes = 3057.67`
  - `llm_total_tokens = 769.11`
  - `task_ms = 4236.90`
- `delta(state_ref - text_brief)`
  - `control_bytes = +807.00`
  - `handoff_textual_bytes = -1057.67`
  - `handoff_nontext_bytes = +3057.67`
  - `llm_total_tokens = +105.56`
  - `task_ms = -313.31`

锁定解释：

- `state_ref` 仍然稳定减少文本 handoff
- 同时稳定引入更大的 non-text payload
- token 总量更高
- 但 task_ms 平均更低

这正好证明：

- `typed non-text handoff` 是真实可消费的机制
- 它不等于低开销 headline

当前 authenticity 线的固定口径应是：

> `state_ref` 证明了 richer typed handoff 的真实性与可消费性；
> 但由于 non-text payload 与 token 代价更高，它不应用来承担 `state_transfer low-overhead` headline。

备注：

- 第三轮 `transfer-session-state-001` 出现一次 `llm_total_tokens = 1173` 的明显高点，但 route/tool 结果未漂移，三轮都仍指向 `auth_session_drift / tool.auth_session_repair`
- 这说明当前 authenticity 线在 live API 下仍有 summarization 波动风险，更进一步支持“不把它拿来讲 low-overhead headline”

---

## 4. Natural-Support Pack 结果

来源：

- `runs/benchmark_redesign_api_r3_natural_support_20260610/benchmark_report.md`

表内结果：

- `natural_handoff_text`
  - `control_bytes = 5155.33`
  - `handoff_textual_bytes = 1253.67`
  - `handoff_nontext_bytes = 0.00`
  - `llm_total_tokens = 676.11`
  - `task_ms = 4407.58`
- `state_packet_minimal`
  - `control_bytes = 5269.00`
  - `handoff_textual_bytes = 771.33`
  - `handoff_nontext_bytes = 1220.33`
  - `llm_total_tokens = 676.67`
  - `task_ms = 4461.49`
- `delta(state_packet_minimal - natural_handoff_text)`
  - `control_bytes = +113.67`
  - `handoff_textual_bytes = -482.33`
  - `handoff_nontext_bytes = +1220.33`
  - `llm_total_tokens = +0.56`
  - `task_ms = +53.91`

锁定解释：

- 这条线证明当前 free-text natural handoff 已经可以作为一条独立对照存在
- 但当前结果比 carrier 更接近“近乎打平”
- `state_packet_minimal` 没有在 live API `repeat=3` 下形成稳定优势

因此 natural-support 线必须继续锁定为：

> support-only evidence

不能升格成：

> 正式 `state_transfer` headline 对照

---

## 5. 当前对外可讲与不可讲

### 5.1 可以讲

- `state_transfer` benchmark 现在已经被公平拆成三条线：
  - `authenticity`
  - `carrier`
  - `natural-text support`
- `typed non-text handoff authenticity` 成立
- `state packet` 在 carrier 线里显著降低 textual handoff
- `natural text` 已经有独立 support baseline，不再和 `authenticity` / `carrier` 混在一起

### 5.2 不能讲

- 不能说当前 `state_packet_minimal` 已经在正式 API `repeat=3` 下稳定更快
- 不能说当前 `state_ref` 已经形成 `low-overhead state transfer` headline
- 不能说 natural free-text comparison 已经支持正式 superiority claim

---

## 6. 下一步建议

如果继续服务于赛题，而不是继续反复调整 wording，下一步优先级应是：

1. 扩 task family，让 carrier 线不只落在当前 3 类 repo-local triage
2. 保持 `carrier / authenticity / natural_support` 三条线分离，不再回退到混包 formal surface
3. 在扩任务后再重跑 `carrier` formal API 包，观察端到端优势是否稳定出现

在没有扩任务之前，当前最稳妥的固定结论就是：

> redesign 已经成功；
> authenticity 线成立；
> carrier 线公平但尚未形成稳定端到端优势；
> natural-support 继续只作 support。

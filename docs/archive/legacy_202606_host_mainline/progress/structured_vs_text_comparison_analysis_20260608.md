# StateBus Structured vs Text 对比分析

日期：`2026-06-08`

适用范围：这份分析只讨论当前 `/home/qcrs/statebus/project` host-mainline 下，
怎样更诚实地比较 `protocol` 与 `text`，从而显示结构化路径在速度和 token
上的真实优势。

## 1. 先说结论

1. 当前 repo **已经能做** `text vs protocol` 对比，但不同证据包证明的东西并不一样。
2. 想证明“结构化更省 token、更快”，**不能主要看 deterministic 包**，因为当前 deterministic
   运行里 `llm_total_tokens = 0`。
3. 当前最有说服力的正式口径仍然是**serialized API repeat-10**，不是 deterministic。
4. 想把结构化优势讲得更稳，需要把现有总指标拆成三层：
   - 控制面字节优势
   - LLM token 优势
   - 端到端时间优势
5. 当前最该补的不是再跑更多包，而是把 telemetry 再细一层，避免把“结构化优势”和
   “memory replay 优势”混在一起。

## 2. 当前已经有什么证据

### 2.1 deterministic host-mainline 包能证明什么

当前最新 deterministic 证据包：

- `runs/host_goal_eval_20260608_154800_executor_ambiguity_abstain_refresh/deterministic_repeat10/`

它能稳定证明：

- `text/protocol` 都能跑满 `repeat=10`
- `failure_count = 0`
- `expectation_match_rate = 1.00`
- `skipped_step_count = 9`
- `reuse_gain = 0.17`
- `protocol_bytes < text_bytes`

但它**不能证明 token 优势**，因为当前 aggregate 里：

- `text.llm_total_tokens = 0`
- `protocol.llm_total_tokens = 0`

所以 deterministic 更适合回答：

> 在同样 host-mainline runtime 下，结构化控制面是否更轻、回放是否仍稳定。

不适合单独拿来回答：

> 结构化是否真实更省 token。

### 2.2 当前最强的“省 token + 更快”证据在哪里

当前最该引用的正式口径仍然是：

- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/api_repeat10_serial/benchmark_report.md`

这份 serial API repeat-10 的 aggregate 已经给出三条很关键的 headline：

- control bytes：`103503.10 -> 88789.80`
- total tokens：`24384.40 -> 16625.90`
- task time：`81184.06 ms -> 60776.34 ms`

换成相对降幅，大约是：

- control bytes：`-14.2%`
- total tokens：`-31.8%`
- task time：`-25.1%`

这才是当前最适合说“结构化更快、更省 token”的正式证据层。

## 3. 当前对比还不够好的地方

### 3.1 结构化优势和 replay/reuse 优势还混在一起

当前 aggregate 把这些东西放在一起了：

- 控制面格式差异
- memory assist
- validated replay
- exact replay

问题是：

- `reuse_gain` 提升并不等于结构化通信本身更优
- exact replay 跳步后，`task_ms` 会自然下降
- 如果不拆 slice，很容易把 replay 带来的时间下降误说成 protocol 本身的优势

所以如果要更诚实地显示结构化优势，主结论不能只看 aggregate，
还应该至少单独强调：

- `fresh_retrieval` axis
- `cold_start`
- `reject_control`

这些 slice 更接近“纯 communication / orchestration 差异”。

### 3.2 当前 token 只有总量，没有角色拆分

现在 telemetry 里有：

- `llm_prompt_tokens`
- `llm_completion_tokens`
- `llm_total_tokens`

但当前报告主要只展示 aggregate total，没有把 token 按角色拆成：

- planner token
- summarizer token
- 可能的 reroute/replan token

这会导致一个问题：

> 我们知道 protocol 更省 token，但不知道省在了哪一段。

更好的做法是新增 role-split token telemetry：

- `planner_prompt_tokens`
- `planner_completion_tokens`
- `summarizer_prompt_tokens`
- `summarizer_completion_tokens`

这样才能回答：

- 结构化主要是让 planner 更省 token
- 还是让 summarizer 更省 token
- 还是两边都省

### 3.3 当前 control bytes 还不能完全代表“送进 LLM 的输入负担”

`protocol_bytes` / `text_bytes` 很重要，但它们统计的是控制面消息字节。

问题在于：

- 一个更小的 protobuf frame，不一定等于更小的 LLM prompt
- LLM 真正看到的是最终组装后的 prompt / brief / structured packet 文本

所以如果要更有说服力，建议再补一层：

- `planner_input_chars`
- `summarizer_input_chars`
- `planner_output_chars`
- `summarizer_output_chars`

这样就能把：

- transport/control-plane savings
- actual LLM prompt savings

明确分开。

### 3.4 当前“更快”也需要拆掉 embedding / retrieval 干扰

当前 `task_ms` 是端到端指标，里面混了：

- embedding
- corpus retrieval
- memory lookup
- tool execution
- LLM call

如果目标是更清楚显示“结构化更快”，最好再细拆至少两层：

- `llm_ms`
- `non_llm_ms`

更进一步可以拆成：

- `planner_ms`
- `retrieval_ms`
- `executor_ms`
- `summarizer_ms`

否则会出现一种解释歧义：

> 是 protocol 更快，还是只是这一轮 memory/replay 恰好更多。

## 4. 更好的对比设计应该怎么做

### 4.1 主报告用 serialized API repeat-10

如果目标是展示“结构化更快、省 token”，主报告应继续坚持：

```bash
python -m eval.runner \
  --repeat 10 \
  --modes text,protocol \
  --llm-mode api \
  --out runs/<stamp>/api_repeat10_serial \
  --quiet-progress
```

原因很简单：

- token 只有 API 模式才是真值
- 串行 repeat-10 才符合当前 repo 的正式 timing 口径
- 不会把并发 API 抖动误当结构化优势

### 4.2 报告正文分成三条 headline，不要混成一句

最好的 headline 结构不是：

> protocol 更高效。

而是直接拆成：

1. 控制面：`protocol_bytes` 比 `text_bytes` 低多少
2. LLM 成本：`llm_total_tokens` 比 `text` 低多少
3. 端到端时延：`task_ms` 比 `text` 低多少

这样优点很明显：

- 一眼知道优势到底在哪
- 就算三者不完全同向，也不会误导
- 后续优化也知道该打哪一层

### 4.3 主比较应优先看 fresh-retrieval slice

如果要显示“结构化协议本身的优势”，推荐主文里优先放：

- `fresh_retrieval`
- `cold_start`
- `reject_control`

原因：

- 这些 slice 没有 exact replay 的强跳步收益
- 更接近“只改 communication / prompt surface”的比较

而：

- `validated_replay`
- `exact_replay`

更适合放在“结构化 + reuse 联合收益”章节，不适合拿来单独证明结构化本身。

### 4.4 再补一张 role-level 表

建议未来报告新增一张简单表：

| mode | planner tokens | summarizer tokens | total |
| --- | ---: | ---: | ---: |
| text | ... | ... | ... |
| protocol | ... | ... | ... |

这张表的价值很高：

- 可以直接定位结构化收益落点
- 可以防止“总 tokens 降了，但只是某个角色 prompt 偶然缩了”的误判

### 4.5 再补一个“纯通信”对照口径

建议把当前主报告明确拆成两条口径：

1. `communication baseline`
   - 只看 `cold_start/reject_control/fresh_retrieval`
2. `communication + reuse integrated`
   - 看 aggregate / validated replay / exact replay

这样对外表述会更诚实：

- 第一条回答“结构化通信本身有没有价值”
- 第二条回答“结构化 + 记忆复用合起来有没有系统收益”

## 5. 如果现在就要做下一步，我建议只做哪一刀

如果只选一刀，我建议：

> 先给 API benchmark 补 role-level token 和 phase-level time telemetry，
> 再写一版新的 `structured vs text` 正式比较报告。

而不是先做：

- 更多 deterministic 包
- 更多 byte 微调
- 更多 prompt 压缩

原因是：

- 当前“结构化更省 token、更快”的方向已经有正信号
- 真正缺的是**解释力**
- 不是再缺一个 headline

## 6. 最后一句判断

当前 StateBus 已经能说：

> 结构化 `protocol` 模式在正式 serial API repeat-10 下，较 `text` 模式表现出
> 更低控制开销、更低 token 使用和更低端到端时间。

但如果要把这件事讲得更稳、更抗质疑，下一步最值得补的不是更多跑分，
而是把这三个优势拆成：

- control-plane savings
- LLM token savings
- end-to-end latency savings

并明确区分：

- 结构化通信本身的优势
- 结构化 + replay/reuse 的系统级联合优势

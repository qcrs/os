# CodeAct 设计说明

这份文档不展开讲接口细节，而是集中说明四件事：为什么要做 CodeAct，当前分支到底怎么做，它和整条 agent 链路是什么关系，以及现阶段结果说明了什么。

## 1. CodeAct 要解决的不是“不会答”，而是“答得不稳”

表格问答里最难控的部分通常不在检索，而在最后一步落答案。只要题目里同时出现过滤、分组、统计量、数值格式约束和多字段输出，纯文本回答就容易出现三类问题：计算过程和真实数据脱钩，只按题面样例或上文猜；逻辑方向对了，但数值、字段名或格式不稳定；上游分析已经接近正确，最后仍因为答案没有严格写成 `@field[value]` 而被判错。

当前分支对这个问题的判断很直接：既然最后一步的核心风险在“计算”和“格式落盘”，那就不要再把最终回答建模成一段自然语言，而要把它建模成一段可执行程序。模型负责写代码，runtime 负责执行代码，系统负责检查输出字段和答案格式。CodeAct 的本质就是把“直接回答”改成“先写程序，再执行程序，再校验程序产物”。

## 2. 当前实现的核心判断

当前分支只保留一条主路径：

```text
planner / researcher / analyst
    -> executor（执行节点外壳）
    -> codeact（生成/修复代码）
    -> restricted runtime（本地受限执行）
    -> summarizer
```

这里最容易被误解的是 `executor` 和 `codeact` 的关系。当前实现里，`executor` 只是执行节点外壳，负责接入 state、持久化执行记录、把执行结果传给下游；真正负责“为题目写代码并执行”的是 `src/agent/codeact.py`。打开 `ENABLE_CODEACT_EXECUTOR=1` 之后，`src/agent/executor.py` 会直接把 state 交给 `codeact(state, store)`，不会先单独起一轮 executor 自己的 LLM 推理。

因此，在 CodeAct 模式下，执行节点内部最多只有两次模型调用：

1. 第一次调用：生成代码。
2. 第二次调用：只有第一次执行失败、缺字段或答案格式不合格时，才触发一次 repair。

这两次调用都走同一套 `CHAT_BACKEND` / `CHAT_MODEL`，并不是两套模型，更不是并行双开。对整条链路来说，CodeAct 是“执行阶段的唯一模型动作”，而不是附着在 executor 上的第二层回答器。

代码落点也很清楚：

- `src/agent/executor.py`：执行节点外壳、结果持久化、下游状态回填。
- `src/agent/codeact.py`：路由、prompt 组装、代码生成、repair、结果规范化。
- `src/codeact_runtime.py`：受限 Python runtime、helper 集合、AST 与 builtins 限制。

## 3. 为什么是“受限 runtime + helper”，而不是开放 Python

如果让模型自由写 Python，短期看似更强，长期会出现三个更难控制的问题：环境依赖飘忽，修复路径不可预测，结果很难审计。尤其在容器、离线模型、本地数据文件和受限部署环境里，`pandas/numpy/scipy` 这种开放入口会把“答题问题”迅速放大成“环境问题”和“兼容性问题”。

所以当前 runtime 不是“给模型一门完整的 Python”，而是给它一组足够做表格题的稳定积木：

- 读表和 artifact：`load_csv_rows`、`artifact_path`、`list_artifacts`
- 列与值访问：`column_names`、`column_values`、`unique_values`、`value_counts`
- 数值抽取：`numeric_values`、`paired_numeric_values`、`to_float`
- 基础统计：`mean`、`std`、`median`、`quantile`
- 高层统计：`pearson_corr`、`sample_skew`、`normality_pvalue`、`zscore_outlier_count`
- 预载对象：`math`

同时，runtime 明确移除了开放库入口：

- `load_csv`
- `pd`
- `np`
- `scipy_stats`
- `statistics`

这样做的目的不是“故意削弱模型”，而是把可执行空间收紧到一个可部署、可审计、可 repair 的范围内。模型仍然可以写循环、条件、列表推导、lambda、异常处理等通用逻辑，但不能靠导入任意库绕开环境边界。

## 4. Helper 为什么必要，以及它的边界在哪里

helper 的存在不是为了替模型答题，而是为了把运行时能力下沉成稳定原语。当前经验很明确：在“无 import、短 prompt、强格式约束”的条件下，让模型每次都从头手写相关系数、偏度、正态性检验、z-score outlier 逻辑，稳定性不够高，repair 成本也会上升。因此保留 `pearson_corr`、`sample_skew`、`normality_pvalue`、`zscore_outlier_count` 这类统计 helper，是在给模型提供通用统计积木，而不是往 helper 里硬塞题目答案。

helper 的边界也必须讲清楚：

- 可以提供通用表格和统计原语。
- 不可以按具体题目预设过滤条件、分组键、目标列或最终答案。

例如，“给我一个 Pearson 相关系数函数”是合理 helper；“如果题目问 Titanic 的 age 和 fare 相关系数就直接返回某个值”就已经越界。当前分支坚持的原则是：helper 只负责能力下界，题目理解、列选择、过滤链路、聚合顺序和字段落盘仍由模型自己完成。

## 5. 当前链路到底怎么跑

当前 CodeAct 的执行流程很短，但每一步都收得比较死：

1. 从 `query` 中抽出 `Expected answer format`。
2. 从 answer format 里解析 `required_fields`。
3. 检查 `artifact_refs`，只要存在 CSV artifact，就走统一的 `generic_csv_question` 路由；没有 CSV 才退回 legacy fallback。
4. 收集 prompt 所需的最小上下文：原始问题、精确 answer format、`required_fields`、route hint、CSV schema hint、压缩后的 `analysis_hint`、可选 `candidate_answers`、runtime helper 说明。
5. 让模型只输出一段 Python 代码，禁止 markdown、解释、`import`、函数和类定义。
6. 系统对生成代码做两步处理：去掉任何 import；自动补上 `required_fields` 和 `expected_answer_format` 绑定。
7. 代码进入 `src/codeact_runtime.py` 的受限 runtime 执行。
8. 若执行失败、缺字段或结果不完整，则触发一次 repair。
9. 系统清洗 `extracted_answers`，必要时重建 `final_answer`，并把 trace / tool result / summary 回写 state。

这里有两个实现判断值得单独强调。

第一，当前路由非常简单。系统不会先做一大堆题型识别，然后把问题发到 “mean/std route”“correlation route”“outlier route”。当前只判断一件事：有没有真实 CSV artifact。如果有，就让同一套 generic CSV CodeAct 去处理。

第二，prompt 也尽量不吃整段上游上下文。它只保留对代码生成真正有用的内容，避免把 text 模式或 structured 模式的大段分析原文原封不动塞进执行阶段。

一个最小执行样例如下：

```python
rows = load_csv_rows()
fares = numeric_values(rows, "Fare")
extracted_answers["mean_fare"] = f"{mean(fares):.2f}"
extracted_answers["std_dev_fare"] = f"{std(fares):.2f}"
answer_parts = []
answer_parts.append(f"@mean_fare[{extracted_answers['mean_fare']}]")
answer_parts.append(f"@std_dev_fare[{extracted_answers['std_dev_fare']}]")
final_answer = " ".join(answer_parts)
```

这个例子说明了当前设计最重要的一点：系统不要求模型“描述如何求均值和标准差”，而是要求它把计算真正落到 CSV 数据上，并把结果填进机器判分需要的字段里。

## 6. Repair 机制是当前实现里最值得讲的亮点

如果只做“生成一次代码，失败就结束”，CodeAct 很快会退化成另一种脆弱的单步 prompting。当前分支把 repair 做成了正式链路的一部分，而不是调试时临时补的一层兜底。

repair 的进入条件由 `_is_execution_acceptable()` 控制，只要出现下面任一情况，就会触发一次修复：

- runtime 执行失败；
- `required_fields` 没有全部产出；
- 产出的字段是空值、`unknown` 或不合规答案。

repair prompt 不是重新自由答题，而是拿着失败代码和执行结果做定向修复。它会把下面这些内容重新发给模型：

- 原始 query
- 精确 answer format
- `required_fields`
- route hint
- runtime helper 说明
- 失败代码
- 上一次 execution result

模型被要求只做一件事：修正代码，使其在当前 runtime 里可执行，并且能正确写出 `extracted_answers` 和 `final_answer`。它不能改成自由文本答案，也不能绕过 runtime 规则。

这一设计的价值不只在于提升成功率，更在于可追踪。当前结果里会保留：

- `selected_strategy`：`llm_generate`、`llm_repair`、`legacy_*` 等
- `execution_trace`：route、artifact 数量、runtime 是否成功、耗时、error、缺失字段、是否回退重建答案
- `tool_results`：实际执行工具、artifact 路径、执行耗时、报错信息

也就是说，当前 CodeAct 不是黑盒“一次出分”。它保留了“第一次怎么写、为什么失败、是否进入 repair、修完后是否成功”的完整审计线索。这一点在汇报里完全可以单独作为亮点来讲，因为它直接对应系统的可解释性和可实验性。

## 7. `text` 和 `structured` 为什么会分叉

当前 `text` 和 `structured` 走的是同一套 CodeAct，没有两套不同的执行器。两者的差异来自上游 state，而不是 CodeAct 内部换了算法。

真正会影响代码生成的是这些输入：

- `analysis_hint`
- `candidate_answers`
- CSV schema hint
- 上游 analyst 提供的压缩/整理结果

因此，即便 CodeAct prompt 模板完全一致，`text` 和 `structured` 最终看到的分析提示也不相同，生成出来的代码就可能不同。这也是为什么在 executor / runtime 完全一致的前提下，两种模式的准确率、token 和耗时仍然会分叉。

当前 structured 模式的价值主要体现在两点：第一，上游把无关上下文压缩掉之后，执行阶段更容易拿到干净的分析提示；第二，输入 token 会显著下降。它不是“另一套 CodeAct”，而是“同一套 CodeAct 的更干净上游输入”。

## 8. 当前实验结果

下面的结果都来自 `task/data_anas/result/` 下的现有输出文件。需要先说明一件事：当前 Group2 已经不是最早那套重任务 benchmark，而是当前分支中简化后的版本，总计 12 个 round、17 个字段。

### 8.1 Full Agent 结果

| Group | Text 正确率 | Text Tokens | Text 耗时 | Structured 正确率 | Structured Tokens | Structured 耗时 | Structured 压缩收益 |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| Group1 | 9 / 10 = 0.9000 | 144533 | 850.09s | 10 / 10 = 1.0000 | 127678 | 827.62s | 105130 -> 41436，节省 63694 chars |
| Group2 | 14 / 17 = 0.8235 | 198486 | 1660.36s | 15 / 17 = 0.8824 | 174764 | 1584.89s | 128140 -> 48638，节省 79502 chars |
| Group3 | 13 / 15 = 0.8667 | 147874 | 1214.13s | 12 / 15 = 0.8000 | 138231 | 1443.36s | 121654 -> 45654，节省 76000 chars |

如果只看 full-agent 结论，可以得到三个很清晰的判断。

第一，Group1 已经基本打穿。structured 达到 10/10，text 也有 9/10，说明当前 generic CSV CodeAct 在单表统计类任务上已经具备很高稳定性。

第二，当前简化版 Group2 也已经显著可用。structured 15/17，text 14/17，而且 structured 比 text 少用了 23722 tokens，耗时也更低。

第三，Group3 的上限还不完全由 CodeAct 决定。structured 虽然省了 token，但准确率没有压过 text，说明这组任务里上游语义整理仍然非常重要。

### 8.2 剩余错题怎么看

当前错题分布很集中，这反而有利于判断系统边界。

- Group1 text 只剩 1 题未过：`survived + first class` 条件下 `age` 和 `fare` 的 Pearson 相关系数。
- Group1 structured 已经全对。
- Group2 text 错 2 处：一个是按 `WHO Region == Americas` 过滤后找国家；另一个是“替换 outlier 前后均值”。
- Group2 structured 只剩“替换 outlier 前后均值”这一题未稳定通过。
- Group3 text 主要错在 `Income` 标准差的数值精度，以及城市级平均评论数的显著高低判断。
- Group3 structured 额外丢了“至少 100 reviews 的品牌平均星级最高者”。

这些错题说明，当前系统最稳的是单表上的直接统计、缺失值统计、相关系数、正态性判断和标准 outlier 计数；最容易失手的是“多步语义约束 + 中间变量改写 + 最终实体选择”这类链路更长的问题。

### 8.3 CodeAct-only Probe 结果

为了隔离 CodeAct 本身，当前还保留了一条 `run_codeact_group_probe.py` 调试链路。它不代表完整产品流程，但很适合判断“如果只看执行阶段，CodeAct 自己能做多少”。

| Group | CodeAct-only 正确率 | Tokens | 耗时 | 说明 |
| --- | --- | ---: | ---: | --- |
| Group1 | 10 / 10 = 1.0000 | 31323 | 81.48s | 这一组几乎就是 CodeAct 直接解决的问题 |
| Group2 | 16 / 17 = 0.9412 | 46039 | 322.02s | 当前简化版 Group2 的主能力也基本落在 CodeAct 本身 |
| Group3 | 10 / 15 = 0.6667 | 36145 | 139.43s | 仅靠执行阶段还不够，更依赖上游语义整理 |

这组结果非常关键，因为它回答了一个经常会被问到的问题：前面的 agent 还有没有作用。答案不是“有”或“没有”，而是分任务组不同。

- 对 Group1 来说，CodeAct 本身已经足够强，上游更多影响 token 和答案稳定性。
- 对当前 Group2 来说，CodeAct 也已经是主力，full-agent 与 codeact-only 的差距不大。
- 对 Group3 来说，上游分析依然明显有用，因为这组题并不只是“执行一个统计公式”，还涉及更强的语义抽象与选择判断。

## 9. 这些结果说明当前设计是有效的，但边界也很明确

如果把当前分支的设计总结成一句话，就是：我们没有再靠题型硬编码去堆分，而是在单一 generic CSV 路由上，用受限 runtime、通用 helper 和一次可审计 repair，把“表格题最后一步”从自由文本回答收束成了稳定执行。

这套设计当前已经证明了几件事：

- 单表统计型问题可以被统一到一条 generic CodeAct 路径上，不需要给每个题型单独写 route。
- `executor` 不需要再做第二层自然语言推理，执行阶段的主动作就是 CodeAct 本身。
- helper 是必要的，但前提是只提供通用原语，不越界成按题目写答案。
- repair 机制不是装饰，它是让 CodeAct 从“能跑 demo”走向“可反复实验”的关键。

它的边界也同样清楚：

- 对单表、直接统计、标准聚合和常见统计检验，当前已经比较稳。
- 对多步过滤、条件重写、中间变量替换、实体级比较和需要较强语义抽象的问题，仍然会暴露模型本体能力上限。
- Group3 的结果说明，CodeAct 不能替代上游所有理解过程；它更像是把最终执行这一步做对，而不是包办整条链路的全部推理。

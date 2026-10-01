# 执行分层：DSL 覆盖常见变换，CodeAct 处理开放计算

这份文档用于确定 CodeAct 这一页的答辩逻辑和 PPT 内容。重点不是介绍“模型可以写 Python”，而是说明 Executor 怎样根据任务需要选择执行方式，以及两种方式怎样交付同一种可验证产物。

## 这一页要解决的问题

前面的协议和 State 解决了任务怎样交接、输入对象怎样传递。Executor 接到输入以后，还要完成实际计算。这里有两个事实同时存在：

- 很多操作是稳定且可以提前定义的，例如筛选字段、过滤行、排序、聚合、跨期比较；
- 有些任务需要注册操作没有覆盖的组合，例如自定义解析、多阶段统计、插补、跨行对齐、透视，或者先分支计算再合并。

只保留 DSL，执行范围会受限；所有任务都让模型写代码，简单计算也要承担生成和验证代码的成本，结果还更难稳定复现。StateBus 把这两类需求分开处理：已登记的操作由 DSL 完成，超出 DSL 表达范围的计算由受限 Python CodeAct 完成。两条路径都遵守任务的输入授权和输出合同，并把结果交给 Runtime 登记为 Artifact。

这一页的中心句可以定为：

> Executor 根据任务需要选择 DSL 或受限 Python；两条路径最后交付同一种可验证的 Artifact。

评委看完应能回答三个问题：

1. 为什么系统需要两种执行方式；
2. CodeAct 具体怎样从任务合同走到结果；
3. CodeAct 产生的结果怎样接回 StateBus 的后续流程。

## 先把 DSL 和 CodeAct 的关系说准确

这两者是 Executor 的两种执行能力。Planner 根据 Runtime 提供的 capability 描述选择其中一种。Planner 的规则是选择能够完整表达任务的最窄能力：

- 输入字段、操作类型和输出结构都能由已登记操作表达时，选择 `execute_analysis_dsl_v2` 等 DSL capability；
- 任务需要 DSL 中没有的表达能力时，选择 `execute_bounded_python_v2`，由 CodeAct 生成受限 Python。

因此 PPT 上不应画成“DSL 失败后自动转 CodeAct”。DSL 程序本身如果参数错误、执行失败或质量校验未通过，当前实现会在有限预算内修复，之后结束该尝试或由上层重新规划。它和“任务从一开始就超出 DSL 能力范围”是两种情况。

Capability 注册表确实记录了 fallback 关系，但 Runtime 的自动回退分支主要处理 CodeAct 失败后转向已登记的确定性 capability，并且会创建新的 Grant 和新的 attempt。答辩时可以说“Runtime 支持按能力声明重新选择执行路径”，不要说成固定的 DSL 到 CodeAct 自动跳转。

## 为什么采用两条路径

### DSL 解决稳定的常见计算

DSL 使用 `TransformProgram` 表示一组注册操作。操作、参数、输入字段和输出字段都有明确含义，解释器按固定语义执行。同一个程序在相同输入下可以得到可复现的结果，也便于复算和验证。

它适合以下工作：

- `select`、`rename`、`filter_*`、`sort`、`limit`；
- `group_by`、`aggregate`、`derive_safe`、`rank`；
- `compare_periods`、`compare_metric`、`join_by_key`；
- 已注册的异常检测、趋势和结论字段投影。

DSL 的限制也很明确：它是线性的行处理流程，不能自然表达任意 Python 逻辑、开放式文件解析、复杂的跨行对齐、分支后合并、透视或任务专用统计定义。把这些任务硬塞进 DSL，会让操作定义越来越多，参数含义也越来越难维护。

### CodeAct 补上开放计算

CodeAct 适合任务已经有清楚的输入和输出合同，但中间计算无法由注册操作组合出来的情况。它提供适应性，代价是需要处理源码生成、运行环境和结果验收。因此这里的 CodeAct 是一个有边界的执行能力：模型只生成当前 capability 允许的程序，Runtime 决定能读什么、能写什么、怎样判定结果合格。

这带来一个实际取舍：

| 执行方式 | 适合的任务 | 主要特点 |
| --- | --- | --- |
| DSL | 已登记的字段变换和统计操作 | 语义固定、结果稳定、容易复算 |
| CodeAct | DSL 无法表达的定制计算 | 表达范围更大，但需要源码、运行和质量检查 |

亮点不在于“用了 Python”，而在于系统没有在稳定性和表达能力之间二选一。Executor 先使用已有的确定性能力，需要扩展时仍能在同一套输入、输出和 Artifact 流程中接入 CodeAct。

## 两条路径怎样汇合

页面主图应先呈现一个选择点，再展示两条路径，最后汇合到同一个结果对象：

```text
                 任务目标 + 输入合同 + 能力目录
                                  |
                    Executor 选择执行 capability
                       /                         \
                      /                           \
       注册操作可以表达                     需要开放计算
              |                                  |
       TransformProgram                    CodeGenerationRequest
              |                                  |
       参数和输入校验                      生成受限 Python
              |                                  |
       确定性解释执行                      源码策略检查
              |                                  |
       schema / quality 校验                隔离 workspace 执行
              |                                  |
              +-------------> verified ExecutionArtifactRef <-------------+
                                           |
                               Summarizer / 后续步骤读取
```

这里的汇合点很重要。它说明下游角色不需要知道上游用了 DSL 还是 CodeAct：只要 Artifact 已通过 Runtime 的验收，就可以按引用继续使用。两条路径的差别发生在“怎样计算”，结果交付方式保持一致。

## DSL 路径需要讲到什么程度

DSL 在这页只承担一个作用：给 CodeAct 的使用边界提供参照。页面上不需要列出全部操作，也不需要展开每个参数的校验规则。保留下面四个节点即可：

```text
TransformProgram
    -> TransformProgramValidator
    -> TransformDslInterpreter
    -> schema / quality validation
    -> ExecutionArtifactRef
```

讲解时说明两点就够了：

1. Planner 选择的是已经登记的操作集合，Executor 执行的是结构化程序；
2. DSL 产物也要经过 schema 和业务质量校验，合格后才登记为可供下游读取的 Artifact。

源码中，`_dispatch_transform_dsl()` 会先物化获准输入，读取可能复用的 recipe，校验 `TransformProgram`，调用确定性解释器和重算逻辑，再进行 capability quality 校验。失败时最多进行有限修复，不会把未验证结果交给 Summarizer。

## CodeAct 的真实执行链路

CodeAct 这一侧是页面的重点，建议展示完整但简化的六个步骤。

### 1. Runtime 先确定输入和合同

Executor 只能使用当前 `CapabilityGrant` 授权的输入 Ref。输入可能是已经验证的 `ExecutionArtifactRef`；在固定四角色流程中，也可以先把获准的 evidence pack 投影成带字段的 typed artifact。Runtime 同时准备：

- 任务目标和 step 信息；
- 输入 Ref 与 `InputManifest` 摘要；
- 输出 schema 和 `output_contract_version`；
- operation semantics、completion criteria 和业务 validator；
- CodeAct policy、允许的输入路径和运行限制。

这些内容组成 `CodeGenerationRequest`，提供给代码生成器。模型得到的是当前任务的输入结构和输出要求，不是整个 workspace，也不能自行扩大输入范围。

### 2. 模型只生成一个候选程序

CodeAct 接受纯 Python、单个 fenced Python block，或只包含 `code` 字段的 JSON。Runtime 提取源码后计算 source hash 和 raw response hash，后续记录都绑定这些摘要。这样可以知道最终执行的源码是哪一份，也能把生成、修复和执行记录对应起来。

### 3. 先审查源码，再决定是否执行

源码进入 AST、符号表和路径策略检查。当前 policy 会限制导入、符号、路径字面量、源码大小、AST 节点数和循环数，并拒绝动态执行、动态导入、网络和进程相关模块、绝对路径及目录穿越。这个步骤的作用是筛掉不符合 capability 合同的程序，不是把 CodeAct 宣传成一套独立的安全产品。

页面上可以把它合并写成“源码策略检查”，不必把所有禁用项铺开。完整规则留在讲稿或技术难点部分。

### 4. 在受控 workspace 中执行

通过策略检查后，Runtime 先做 bubblewrap readiness probe，再进入实际 sandbox。输入和生成源码以只读方式挂载，只有规定的 output 路径可写；执行使用独立的 namespace，并设置 wall timeout、CPU、地址空间、输出文件大小、文件描述符和进程数限制。

workspace 由 `WorkspaceManager` 按 attempt 建立，包含 `inputs`、`outputs`、`logs`、`tmp`、`script` 和 `manifest`。这使得执行结果、输入快照和诊断信息可以按一次 attempt 保存，而不是散落在进程临时目录中。

### 5. 验收程序输出

程序退出成功不等于结果可用。Runtime 还会检查输出路径、文件类型、大小和 hash，然后执行 output schema 与 capability-specific quality validator。业务 validator 会检查要求的字段、行数、统计结果和 provenance 等条件。

校验失败时，Runtime 可以在预算内要求一次修复；每次修复使用新的 workspace，并重新经过源码检查。超过修复预算，当前 attempt 失败，候选 Artifact 不会进入下游。

### 6. 形成统一的 Artifact

全部检查通过后，`LlmCodeActRunner` 返回输出 payload、执行记录和质量报告，Dispatcher 登记 `StoredAdaptiveArtifact`，并保存与本次程序相关的 execution recipe。对外交付的是 `ExecutionArtifactRef`，而不是一段 Python 源码。

Summarizer 和后续 Executor 只读取已验证的 Artifact。它们可以继续使用结果和来源，却不需要重新判断这段程序是否执行过、输出文件是否完整或字段是否满足合同。

## PPT 页面如何安排

### 页面主题

建议标题：

> 执行分层：DSL 覆盖常见变换，CodeAct 处理开放计算

标题下方放一句具体说明：

> Executor 按任务需要选择执行能力；两条路径都以 verified Artifact 交付结果。

这句话同时交代选择依据和共同出口，评委不需要先记住 `TransformDslInterpreter`、`LlmCodeActRunner` 等类名。

### 页面主体

采用“中间选择、左右路径、底部汇合”的布局。

**中间上方：选择依据**

放一个小的能力选择框：

```text
任务需要的操作
输入 Ref / 输出合同
        |
选择已登记 capability
```

旁边用一句话说明：已登记操作能表达的任务走 DSL，超出操作范围的任务走受限 Python。

**左侧：DSL 路径，控制篇幅**

只放四个方框：

```text
TransformProgram
      ↓
参数与输入校验
      ↓
确定性解释执行
      ↓
schema / quality
```

可以在卡片底部列三个例子：`filter`、`aggregate`、`compare_periods`。它们用于让评委知道 DSL 不是空泛的“规则引擎”，不必列完整操作表。

**右侧：CodeAct 路径，作为主要视觉内容**

按实际顺序放六个节点：

```text
输入 Ref + 输出 schema
          ↓
CodeGenerationRequest
          ↓
生成 Python
          ↓
源码策略检查
          ↓
隔离 workspace 执行
          ↓
schema / 业务质量校验
```

右侧可以在“生成 Python”旁边放一个很短的代码片段，例如读取 `inputs/*.json`、写入固定 `outputs/result.json`。不要放完整代码；代码片段的作用是说明输入和输出路径由 Runtime 提供，不是让评委阅读算法。

**底部：共同出口**

两条箭头汇合到一个较大的框：

```text
verified ExecutionArtifactRef
结果、schema、hash、provenance
        ↓
Summarizer / 后续 Executor
```

这一块应比 `bubblewrap`、AST 等实现名词更醒目。它是 StateBus 体系的连接点，也是 CodeAct 能够接回前面协议和后面 Memory 的原因。

### 页脚小字

页脚只补充两条事实：

```text
CodeAct 仅在 allow_llm_python + bounded_code 条件下启用
失败结果不进入下游；配置了回退能力时由 Runtime 重新发 Grant 和 attempt
```

这两条足以说明 CodeAct 有明确的启用边界和失败处理，不必在本页再画授权、hash、lease、GC 等完整生命周期。

## 这一页不应展示的内容

- 不要画“DSL 失败 → CodeAct”的固定箭头；它不符合当前通用调度逻辑。
- 不要把 CodeAct 画成可以执行任意 shell、任意文件和任意网络请求的代码代理。
- 不要把 AST 禁用项、namespace 类型、资源限制逐项铺满页面；这些是实现依据，不是本页的主线。
- 不要只展示一段 Python 代码。代码本身不能说明输入授权、输出合同和 Artifact 验收。
- 不要让 DSL 和 CodeAct 做成两个完全独立的产品模块。它们的价值在于共享输入授权、校验和结果交付。
- 不要说“执行成功就得到结果”。当前实现只有通过 schema 和业务质量验证的结果才是下游可用的 Artifact。

## 讲解顺序

这一页可以按下面的顺序讲，约一分钟到两分钟：

> Executor 接到任务后，先看这个任务需要的操作是否已经在能力目录中登记。字段筛选、聚合、跨期比较这类操作可以直接组成 DSL，由确定性解释器执行。遇到自定义解析、复杂统计或 DSL 表达不了的组合，再选择受限 Python CodeAct。
>
> CodeAct 也不是把一段代码直接交给机器运行。Runtime 先把获准输入、输出 schema、任务语义和执行策略组成 CodeGenerationRequest，模型只生成当前能力允许的程序。源码通过策略检查后，在受控 workspace 中执行，结果还要经过 schema 和业务质量校验。通过后，Runtime 把它登记成 verified ExecutionArtifactRef。
>
> 所以后续的 Summarizer 只关心这个 Artifact 是否通过验收，不需要区分结果来自 DSL 还是 CodeAct。DSL 提供稳定的常见计算，CodeAct 补足开放计算，两条路径共享同一套交付方式。

## 评委最后应记住什么

这页只需要留下一个清楚的判断：

> 常见、已定义的变换走 DSL；超出操作范围时可以生成受限 Python；两条路径最后都产出可交给下游的 Artifact。

这个判断同时体现了三点：

1. 系统有明确的执行选择，不是所有任务都交给模型写代码；
2. CodeAct 扩展了表达能力，但输入、运行和结果都有 Runtime 规定的边界；
3. CodeAct 没有另起一套结果体系，生成的 Artifact 可以继续进入协议、Summarizer 和 Memory 流程。

## 证据和源码对应

| 要说明的内容 | 代码或文档依据 |
| --- | --- |
| DSL 与 CodeAct 是两种执行 kind | `src/statebus/runtime/execution_routing.py`、`src/statebus/runtime/adaptive_dispatcher.py` |
| Planner 选择最窄能力，超出 DSL 时选择 bounded Python | `src/statebus/runtime/role_path.py` 中的 capability surface 与 Planner 指令 |
| DSL 的校验、解释执行、重算和质量检查 | `src/statebus/runtime/adaptive_dispatcher.py` 的 `_dispatch_transform_dsl()`、`src/statebus/runtime/transform_dsl.py` |
| CodeAct 输入合同、输入投影和生成请求 | `src/statebus/runtime/adaptive_dispatcher.py` 的 `_dispatch_llm_python()` |
| 源码解析、策略检查、sandbox、修复和输出验收 | `src/statebus/runtime/llm_codeact.py`、`docs/implementation/execution.md` |
| workspace、manifest、Artifact 登记 | `src/statebus/runtime/workspace.py`、`src/statebus/runtime/adaptive_dispatcher.py` |
| CodeAct 失败后的声明式回退 | `src/statebus/runtime/adaptive_runtime.py` 的 fallback regrant 分支 |

后续测试页如果需要证明这一页，应分别展示 DSL 路径和 CodeAct 路径都能产生 verified Artifact，并展示 CodeAct 失败或校验不通过时不会把候选结果交给下游。不要用一组笼统的“安全检查通过”替代执行结果、输出合同和产物状态的证据。

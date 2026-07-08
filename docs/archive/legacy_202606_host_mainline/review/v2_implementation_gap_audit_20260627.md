# StateBus V2 实现差距审计

日期：2026-06-27  
范围：当前 `v2/` clean-room 实现相对 `v2` 规划/合同文档的落地情况。  
口径：分成 `已实现`、`部分实现`、`骨架偏多`、`尚未完成` 四类；只描述当前 worktree 事实，不把规划写成已完成。

---

## 1. 当前结论

`v2` 已经不是只有骨架。

当前已经具备可运行的：

1. `TaskCompiler -> Retrieval -> Semantic State -> Execution Artifact -> Replay Gate -> Quality Floor -> Benchmark`
2. `fixed-answer route/tool` live API family
3. strict external pure-text baseline
4. `CodeAct` workspace executor
5. `L0 -> L3` benchmark 分层

但它还没有完全达到文档里的“正式 runtime 系统”上限。

当前最准确的判断是：

1. `runtime / artifact / replay / retrieval` 已经进入真实实现阶段
2. `CodeAct`、`task compiler`、`memory taxonomy` 仍然偏首版
3. `non-text semantic pruning` 已经真实进入主链路，但还没有扩展到更丰富模态
4. `live API` 路径已经能跑通，但性能还没有收敛
5. `fixed-answer live` 读数需要区分 `replay-ready` 和 `cold-start` 两种正式口径

---

## 2. 已实现

### 2.1 Task compiler 与 strict benchmark 入口

已实现：

1. `CanonicalTaskSpec`
2. `TaskCompilerInput`
3. `benchmark_strict` 下编译失败即拒绝
4. `interactive` 风格的 heuristic fallback

对应代码：

1. `v2/runtime/compiler.py`
2. `v2/contracts.py`

判断：

1. 合同主干已落地
2. 目前枚举面还比较窄，但不是空壳

### 2.2 Retrieval fanout 与非文本语义裁剪

已实现：

1. lexical + semantic + table fanout
2. candidate pool
3. rerank result
4. pruning profile
5. canonical evidence pack
6. hydrate manifest
7. `raw_evidence_bytes_seen_by_llm` 口径

对应代码：

1. `v2/retrieval/pipeline.py`
2. `v2/retrieval/models.py`
3. `v2/provenance/*`

判断：

1. 这是当前 `v2` 最实的一段，不是骨架

### 2.3 Semantic state / artifact / workspace contract

已实现：

1. `LayeredStateStore`
2. `shared_memory` / `mmap` 双后端
3. `SemanticStateRef`
4. `ExecutionArtifactRef`
5. task workspace
6. input/output manifest
7. validator reports
8. execution step record

对应代码：

1. `v2/state/*`
2. `v2/refs.py`
3. `v2/runtime/workspace.py`
4. `v2/runtime/execution.py`

判断：

1. artifact 面与 semantic state 面已经逻辑分家
2. 这部分已经明显超过“只有 schema”

### 2.4 Replay admissibility 与 quality floor

已实现：

1. `assist / validated_replay / exact_replay`
2. `RuntimeCompatibilitySignature`
3. replay ledger
4. quality floor
5. verified / invalidated artifact commit

对应代码：

1. `v2/runtime/replay.py`
2. `v2/runtime/driver.py`
3. `v2/runtime/commit_gate.py`
4. `v2/benchmark/models.py`

判断：

1. replay 合同已经真实存在
2. 本轮还把 `exact_replay` 修成了真正快路径，不再是事后打标签

### 2.5 Fixed-answer / external baseline / compare

已实现：

1. live API role path runner
2. fixed-answer family
3. strict external pure-text baseline
4. comparator suite
5. preflight

对应代码：

1. `v2/runtime/role_path.py`
2. `v2/benchmark/fixed_answer_runner.py`
3. `v2/benchmark/external_text_baseline.py`
4. `v2/benchmark/comparator_runner.py`
5. `v2/benchmark/live_runner.py`
6. `v2/runtime/preflight.py`

判断：

1. 这部分已经可以支撑容器内真实 API/GPU 测试
2. 正式 benchmark 时要把 `replay-ready` 与 `cold-start` 分开归档，前者衡量 replay 收益，后者衡量真实 role-path 成本

---

## 3. 部分实现

### 3.1 Runtime state machine

现状：

1. `ACK / RUN_START / HEARTBEAT / RES_SUCC / TRAP / replan`
2. session / workflow step / attempt record
3. fallback dag

对应代码：

1. `v2/runtime/driver.py`
2. `v2/runtime/session.py`
3. `v2/runtime/fallback.py`

差距：

1. 现在是 loopback + driver 内聚实现
2. 还不是完整的多进程常驻 supervisor/worker runtime
3. event type 和合同文档仍有少量命名/覆盖差异

### 3.2 CodeAct

现状：

1. 已有正式 workspace executor
2. request / plan / execution record 都会落盘
3. route/tool/action_contract 已接入执行合同

对应代码：

1. `v2/runtime/codeact.py`

差距：

1. 还是单次计划执行，不是多轮 agentic CodeAct
2. 没有更强沙箱
3. 还没有 validator 驱动的自修正循环

### 3.3 Memory taxonomy

现状：

1. `MemoryIndexStore` 可 commit / lookup / invalidate
2. 有 candidate pool / rerank result / taxonomy 计数

对应代码：

1. `v2/memory/*`

差距：

1. taxonomy 还偏 benchmark-first
2. 跨 family 的真实复用策略还比较薄
3. 还没有把 “strategy reuse / code template reuse / exact artifact replay” 拉成更完整的层级产品面

---

## 4. 骨架偏多

### 4.1 Task family 扩展面

现状：

1. 财报 / fixed-answer 路线最完整

差距：

1. family schema、tool schema、compiler enum 还没有系统化扩展
2. 更通用的 fixed-answer code bug / exact-result task family 还未正式冻结

### 4.2 非文本多模态扩展

现状：

1. 当前非文本主线主要是 embedding / ranked evidence / table facts

差距：

1. 图像、代码 AST、执行中间结构还没进入 formal 主线
2. 所以“non-text”已经成立，但还没达到更激进的设计上限

### 4.3 Telemetry 合同覆盖面

现状：

1. 事件、汇总、benchmark 聚合都存在

差距：

1. 还没有把所有合同事件完整打齐
2. 一部分事件目前更偏 benchmark/runtime 内部使用，而不是 dashboard-ready 统一事件总线

---

## 5. 尚未完成

1. 真正外部化的 execute retrieval service 定义与长驻多进程 runtime
2. 更正式的 route/tool family registry 与固定答案任务大盘
3. 更丰富的 fixed-answer benchmark family，例如代码改错、确定性表格问答
4. 真实 serialized live benchmark 结果的重新归档
5. openEuler 终态验证
6. 强沙箱 CodeAct

---

## 6. 为什么 live API 还慢

当前 slowdown 的主要来源不是一个点，而是三段叠加：

1. StateBus 路径做了 retrieval、state publish、manifest/materialization、memory lookup、artifact/replay/validator 持久化；external pure-text baseline 基本没有这些结构化成本。
2. 在本轮修复前，`exact_replay` 是后验标签，不是真正快路径；现在已经前置成真实跳过 role-path + CodeAct，但用户还需要重新跑 live suite 才能看到新时延。
3. `embedding-mode=local` 下本地模型加载和编码成本不小；本轮已补进程级模型缓存，避免同一进程内每个 case 重载 `SentenceTransformer`。

当前合理预期是：

1. correctness 不应下降
2. `L3` 的 API 时延应比之前明显收敛
3. 但如果还要和 external pure-text baseline 拼绝对时延，仍然需要继续削减：
   - manifest/persist 次数
   - retrieval fanout 成本
   - local embedding 编码次数

---

## 7. 下一步建议

优先顺序建议：

1. 重跑容器内 live suite，确认本轮 `exact_replay` fast-path 和 embedding cache 带来的时延改善
2. 固化一组更强的 fixed-answer task family，加入代码改错/确定性答案任务
3. 把 `execute` / `retrieval` service definition 从当前本地调用收紧成更正式的接口合同
4. 再决定是否继续把 CodeAct 推向多轮自修正

如果目标是“先把容器内 API/GPU 正式测起来”，当前代码已经到这个阶段了。

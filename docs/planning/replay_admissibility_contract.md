# Replay Admissibility Contract

日期：2026-06-26  
状态：`v2` 子合同草案  
作用：定义 `assist / validated_replay / exact_replay` 的准入边界，避免“命中即收益”的伪复用。

---

## 1. 目标

这份合同回答：

1. 什么叫 `assist`
2. 什么叫 `validated_replay`
3. 什么叫 `exact_replay`
4. 哪些条件会降级
5. 哪些条件会直接 invalidate
6. replay 如何与 memory / artifact / CAS 协同

---

## 2. 基本原则

### 2.1 命中不等于收益

这是当前仓库最值得保留的经验之一。

`MemoryHit` 可以发生，但：

1. 不一定减少步骤
2. 不一定减少 token
3. 甚至可能把 prompt 变长

因此：

- `assist` 不能被表述成 replay 收益

### 2.2 exact replay 必须 deterministic

不允许让 LLM 凭感觉判断：

- “看起来差不多，应该能复用”

exact replay 必须只建立在：

1. 规范化 task spec
2. 输入内容签名
3. 工具/抽取/runtime 版本
4. 输出 contract 相容

之上。

### 2.3 embedding 只用于召回，不进入 exact key

embedding 适合：

1. assist 检索
2. validated replay 候选召回

不适合：

1. exact replay key 本体

原因：

- 浮点向量会受模型版本、数值细节、归一化方式影响

---

## 3. 三层复用定义

### 3.1 Assist

含义：

1. 命中历史记忆
2. 只作为参考信息
3. 不直接跳过步骤

典型行为：

1. 读历史 summary
2. 读历史 evidence pack
3. 读历史 code template 作为 hint

不允许 claim：

1. skipped step
2. exact replay

### 3.2 Validated Replay

含义：

1. 任务目标高度相似
2. 输入 schema 相容
3. 可复用已有 strategy / code / canonical evidence shaping
4. 但不能直接复用旧结论

典型行为：

1. 跳过“从零构思代码”
2. 复用旧 code template
3. 用新输入重新执行沙箱

### 3.3 Exact Replay

含义：

1. 任务规范化后等价
2. 输入内容签名等价
3. 依赖工具链版本相容
4. 输出 contract 等价

典型行为：

1. 直接复用旧结论
2. 或跳过 retrieve + execute，直接恢复 replay-ready artifact/state

---

## 4. `CanonicalTaskSpec` 与 `RuntimeCompatibilitySignature`

更细的输入输出合同与签名采集来源，见：

1. [task_compiler_contract.md](/home/qcrs/statebus/project/docs/planning/task_compiler_contract.md)
2. [runtime_compatibility_signature_contract.md](/home/qcrs/statebus/project/docs/planning/runtime_compatibility_signature_contract.md)

### 4.1 `CanonicalTaskSpec` 必须先于 replay 存在

`exact_replay` 不能直接对用户自然语言做哈希。

必须先把任务编译成稳定的、可排序序列化的规范化对象。

建议：

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class CanonicalTaskSpec:
    task_family: str
    intent_op: str
    target_entities: list[str] = field(default_factory=list)
    time_scope: str = ""
    required_outputs: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    arguments: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "statebus.canonical_task_spec.v1"
```

核心纪律：

1. `CanonicalTaskSpec` 是 task compiler 的产物
2. `exact_replay` 只认它的 canonical JSON 哈希
3. display-friendly 原始自然语言不进入 exact replay key

### 4.2 `RuntimeCompatibilitySignature` 不等于只看镜像 digest

单容器 openEuler 目标下，如果只用 container image digest，通常过于敏感。

更合理的 `MVP` 定义是：

```text
SHA256(
  os_release +
  python_version +
  dependency_lock_hash +
  tool_registry_version +
  extractor_bundle_digest
)
```

其中：

1. `os_release`
2. `python_version`
3. `dependency_lock_hash`
4. `tool_registry_version`
5. `extractor_bundle_digest`

如果后续环境能稳定拿到 container image digest，可把它作为补充字段，但不建议在 `MVP` 阶段把它写成唯一判断依据。

---

## 5. 建议的 Replay Key 设计

### 5.1 不采用 embedding key

不建议：

```text
SHA256(task_embedding + ...)
```

### 5.2 exact replay key

建议：

```text
SHA256(
  canonical_task_spec_json +
  input_artifact_hashes_json +
  extractor_version +
  tool_runtime_version +
  runtime_compatibility_signature +
  code_template_version +
  output_contract_version
)
```

### 5.3 字段解释

`canonical_task_spec_json`

- 去掉自然语言表面差异后的规范化任务描述

`input_artifact_hashes_json`

- 输入 CSV / canonical doc / table surface / upstream artifact 的哈希

当前冻结前提：

- formal benchmark 首轮默认服务财报 / 经营数据分析任务家族
- `CanonicalTaskSpec` 的字段枚举与输出合同应优先围绕该任务家族收口

`extractor_version`

- 防止文本切分或表格抽取规则变化后误回放

`tool_runtime_version`

- 防止 pandas / runner / playbook 版本变化后结果不再等价

`runtime_compatibility_signature`

- 用于约束 openEuler release、Python 版本、依赖锁、工具注册表是否发生会影响结果的漂移

`code_template_version`

- 用于约束 validated/exact replay 的执行策略版本

`output_contract_version`

- 防止“以前只要文本总结，现在要求图表+JSON”时还误判能 exact replay

---

## 6. 准入规则

### 6.1 Assist 准入

满足任意一项即可召回：

1. 语义相似
2. 标签命中
3. task theme 命中
4. 路线/工具 hint 命中

### 6.2 Validated Replay 准入

必须同时满足：

1. task family 相同
2. 输入 schema 相容
3. 旧 strategy/code template 仍适配当前 runtime
4. 输出 contract 相容
5. 未发现高风险 drift

其中“输入内容可不同”，这正是它和 exact replay 的区别。

### 6.3 Exact Replay 准入

必须同时满足：

1. `canonical_task_spec_hash` 一致
2. `input_artifact_hashes` 一致
3. `extractor_version` 一致
4. `tool_runtime_version` 相容或一致
5. `runtime_compatibility_signature` 一致或被明确定义为相容
6. `output_contract_version` 一致
7. replay-ready artifact/state 仍可恢复

---

## 7. 降级与失效规则

### 7.1 从 exact 降级到 validated

当以下条件成立：

1. task family 相同
2. 旧 strategy 仍可运行
3. 输入 schema 相容
4. 但输入内容哈希不同

### 7.2 从 validated 降级到 assist

当以下条件成立：

1. 旧 strategy 仅能当参考
2. 不能保证输出 contract
3. 工具/runtime 版本可能已漂移

### 7.3 直接 invalidate

以下任一条件成立时，直接不复用：

1. 输入 schema 不相容
2. 输出 contract 不相容
3. 关键工具链版本不相容
4. 依赖 artifact 丢失
5. 历史 commit 被标记 dirty / rejected / superseded
6. runtime compatibility signature 已漂移到不兼容版本

---

## 8. Memory Commit 准入条件

不是所有成功输出都能写入 replay 层。

### 8.1 允许 commit 到 replay layer 的条件

必须同时满足：

1. `success=True`
2. 最终结果被下游接受
3. 依赖输入可追溯
4. 输出 contract 满足
5. 需要的 artifact/state 可恢复

### 8.2 不允许进入 replay layer 的对象

1. 中间失败后被手工修补的脏结果
2. 只适合参考的散乱文本 summary
3. 缺少输入签名的旧产物

### 8.3 推荐采用两段提交

建议 replay-ready 对象走：

1. `CANDIDATE`
2. `VERIFIED`
3. `INVALIDATED`

推荐流程：

1. Executor 执行完成后，artifact/state 先以 `CANDIDATE` 状态进入缓存
2. 下游 step 成功消费并且最终结果被系统采纳后，Runtime Supervisor 或 Planner 才发出验证提交
3. 只有 `VERIFIED` 对象才进入 validated/exact replay 候选池
4. 一旦后续发现输出 contract 不满足、依赖对象缺失或结果被撤销，状态改为 `INVALIDATED`

推荐默认采用 `end-of-DAG settlement`：

1. 生产门
   - `exit_code == 0`
   - 产物存在且非空
   - 基础 schema / 文件 validator 通过
2. 消费门
   - 至少一个下游消费者或 validator 成功消费
   - 未出现 `artifact_unreadable` / `schema_mismatch`
3. 结算门
   - task 最终状态为 `SUCCESS`
   - quality floor 通过

更完整的质量底线定义见：

1. [benchmark_quality_floor_contract.md](/home/qcrs/statebus/project/docs/planning/benchmark_quality_floor_contract.md)

---

## 9. 与 CAS / replay-ready state 的关系

当前仓库已有：

- CAS blob
- `exact_replay_ready=True`
- `MemoryHit.replay_class`
- `MemoryCommit.evidence_state_refs`

`v2` 应进一步约束：

1. exact replay 只能引用 replay-restorable state/artifact
2. replay-ready state 必须具备稳定 hash
3. 如果底层 blob 缺失，exact replay 自动失效
4. `ExecutionArtifactRef` 是与 `SemanticStateRef` 并列的一等引用对象，而不是“随手塞进 state metadata 的文件字段”

---

## 10. 与当前仓库对象的映射

当前可直接借用：

1. [runtime/reuse_contract.py](/home/qcrs/statebus/project/runtime/reuse_contract.py:1)
2. [MemoryHit](/home/qcrs/statebus/project/protocol/messages.py:215)
3. [MemoryCommit](/home/qcrs/statebus/project/protocol/messages.py:248)
4. [MemoryStore.replay_candidates()](/home/qcrs/statebus/project/memory/store.py:673)
5. [StatePool.put_replay_restorable_bytes()](/home/qcrs/statebus/project/statepool/store.py:276)

当前仍缺：

1. `canonical_task_spec`
2. `output_contract_version`
3. `runtime_compatibility_signature`
4. 明确的 validated replay admissibility rule set
5. dirty/superseded replay memory 标记
6. `CANDIDATE -> VERIFIED -> INVALIDATED` 的状态流转

---

## 11. MVP 实现建议

### 11.1 exact replay 先走严格等价

`MVP` 阶段：

1. 不做模糊 exact replay
2. 只做强哈希等价
3. 由于目标环境是单容器 openEuler，实现时默认把 `runtime_compatibility_signature` 纳入等价前提

### 11.2 validated replay 先走 rule-based

先用规则判断：

1. task family
2. input schema
3. route/tool contract
4. output contract

不让 LLM 决定“能不能 replay”。

### 11.3 assist 继续保留，但不 headline 化

assist 作为系统能力可以保留，但指标口径必须和 replay 分开。

---

## 11. 非目标与暂不承诺

当前不承诺：

1. 全自动跨任务策略迁移
2. LLM 主导的复用合法性判别
3. 跨模型、跨版本的语义稳定 exact replay

---

## 12. 验收建议

建议最小验收：

1. 相同任务 + 相同输入 → exact replay 成立
2. 相同任务族 + 不同输入 → validated replay 成立，exact replay 失效
3. 仅语义相近 → assist 成立，但不跳步
4. 输入 schema 变化 → 直接 invalidate

建议后续补测试：

- `tests/replay/test_exact_replay_key_contract.py`
- `tests/replay/test_validated_replay_downgrade.py`
- `tests/replay/test_replay_invalidation_rules.py`

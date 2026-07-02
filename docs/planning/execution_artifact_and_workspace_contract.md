# Execution Artifact And Workspace Contract

日期：2026-06-26  
状态：`v2` 子合同草案  
作用：定义单容器 `openEuler` 环境下，CodeAct / tool execution 的 workspace 布局、输入输出合同、artifact 物化与回放边界。

---

## 1. 目标

这份合同要解决：

1. 执行 step 在哪里运行
2. 输入文件如何物化到执行环境
3. 输出文件如何被识别为一等 artifact
4. stdout/stderr 如何限制和归档
5. 任务结束后哪些东西删除，哪些东西进入 replay / audit

---

## 2. 当前前提

`v2` 的目标环境明确是：

1. 单容器 `Docker + openEuler`
2. 容器内多进程协作
3. `Planner / Runtime Supervisor / Worker / Executor` 默认共享同一文件系统根

这意味着这份合同不再以宿主机沙箱为前提，也不讨论跨容器挂载同步。

---

## 3. 设计原则

### 3.1 Artifact 是一等公民

执行产物不应只是：

1. stdout 文本
2. 临时变量
3. “看完就没”的中间文件

它们应显式进入：

1. `Execution Artifact Channel`
2. `StateRef` / artifact locator
3. replay / audit / summary 后链路

### 3.2 Workspace 必须任务级隔离

每个 task 至少有独立 workspace 根。

可选再细化到 step 级子目录。

### 3.3 执行代码不直接读任意路径

CodeAct 或 tool worker 的输入输出都必须收口到固定目录布局，而不是让脚本随便读容器任意位置。

### 3.4 Artifact 与 Semantic State 必须逻辑分家

`ExecutionArtifactRef` 不应被定义成“塞了更多 metadata 的 `StateRef`”。

更合理的合同是：

1. `SemanticStateRef`
   - 面向 embedding、feature bundle、ranked evidence
   - 默认短生命周期
   - 优先服务 task 内筛选与路由
2. `ExecutionArtifactRef`
   - 面向 `json/csv/png/text/code`
   - 可跨 step、跨 task 持久存在
   - 优先服务 replay、audit、summary、dashboard

当前冻结决定是：

1. `ExecutionArtifactRef` 首轮就独立成正式对象
2. 不再把它作为“先放进 StateRef.metadata 的过渡方案”来设计主线
3. 如需兼容旧仓库，只允许在适配层做镜像，不允许让正式合同倒退

更细的引用对象落点与生命周期总表，见：

1. [ref_registry_and_manifest_storage_contract.md](/home/qcrs/statebus/project/docs/planning/ref_registry_and_manifest_storage_contract.md)
2. [lifecycle_matrix.md](/home/qcrs/statebus/project/docs/planning/lifecycle_matrix.md)

---

## 4. Workspace 布局

建议的容器内根目录：

```text
/statebus/runtime/
/statebus/statepool/
/statebus/workspaces/
/statebus/artifacts/
/statebus/logs/
/statebus/runs/
```

每个 task 的 workspace：

```text
/statebus/workspaces/{task_id}/
  inputs/
  outputs/
  logs/
  tmp/
  script/
  manifest/
```

如需 step 级子隔离，建议：

```text
/statebus/workspaces/{task_id}/steps/{step_id}/
```

---

## 5. 输入物化合同

### 5.1 输入来源

执行 step 可消费的输入包括：

1. 上游 `StateRef`
2. canonical evidence pack
3. replay 恢复的 artifact
4. 直接参数

### 5.2 物化规则

进入执行前，Runtime Supervisor 或 Executor wrapper 负责：

1. 把需要的 CSV / JSON / TXT / PNG / fragment 文件写入 `inputs/`
2. 生成一份只读 `input_manifest.json`
3. 为脚本提供固定入口路径

### 5.3 输入 manifest

建议：

```json
{
  "task_id": "task_001",
  "step_id": "execute_01",
  "workspace_root_id": "workspace_root",
  "inputs": [
    {
      "name": "evidence_table",
      "artifact_type": "csv",
      "relpath": "inputs/evidence_table.csv",
      "blob_hash": "sha256:...",
      "source_state_id": "state_001"
    }
  ]
}
```

---

## 6. 输出 artifact 合同

### 6.1 允许的主输出类型

`MVP` 先支持：

1. `text`
2. `json`
3. `csv`
4. `png`

### 6.2 输出目录

脚本只允许写到：

1. `outputs/`
2. `logs/`

不允许把最终产物写回 `inputs/`。

### 6.3 输出 manifest

执行后，wrapper 负责扫描 `outputs/`，生成：

```json
{
  "task_id": "task_001",
  "step_id": "execute_01",
  "outputs": [
    {
      "artifact_name": "result_json",
      "artifact_type": "json",
      "relpath": "outputs/result.json",
      "size_bytes": 1832,
      "sha256": "..."
    },
    {
      "artifact_name": "plot_png",
      "artifact_type": "png",
      "relpath": "outputs/plot.png",
      "size_bytes": 88213,
      "sha256": "..."
    }
  ]
}
```

---

## 7. `ExecutionArtifactRef` 建议对象

当前仓库已有 `StateRef`，因此不一定需要新建并行核心类型。

但执行层建议显式定义逻辑对象：

```python
from dataclasses import dataclass

@dataclass
class ExecutionArtifactRef:
    artifact_id: str
    task_id: str
    step_id: str
    artifact_type: str
    root_id: str
    relpath: str
    blob_hash: str
    size_bytes: int
    produced_by: str
    verification_state: str = "candidate"
    replay_ready: bool = False
```

建议控制面和执行结果面显式携带：

1. `state_refs`
2. `artifact_refs`

而不是只保留一个模糊的 `input_refs`。

在兼容旧仓库的适配层中，可以镜像到 manifest；但 `v2` 的 runtime 内部对象和评测口径上必须始终视为独立类型。

---

## 8. stdout / stderr 合同

### 8.1 为什么要单独定

如果不定：

1. 大量 stderr 会污染 prompt
2. 无限制 stdout 会把 token 打爆
3. replay 时无法区分“执行日志”和“正式产物”

### 8.2 建议限制

`MVP` 建议：

1. `stdout_capture_limit_bytes = 16384`
2. `stderr_capture_limit_bytes = 16384`
3. 超出部分截断，并写完整日志文件到 `logs/`

### 8.3 返回给上游的内容

上游默认只看到：

1. `exit_code`
2. `stdout_preview`
3. `stderr_preview`
4. `artifact_manifest`

而不是完整日志全文。

---

## 9. 文件数量与体积限制

为了避免脚本失控，建议设定：

1. `max_output_file_count`
2. `max_single_output_bytes`
3. `max_total_output_bytes`

`MVP` 推荐默认值：

```text
max_output_file_count = 16
max_single_output_bytes = 16 MB
max_total_output_bytes = 64 MB
```

一旦超限：

1. step 标记为 `FAILED` 或 `TRAPPED`
2. 超限原因写入 stderr preview 与 telemetry

---

## 10. 导入与执行边界

### 10.1 `MVP` 路线

当前先沿用：

1. `subprocess`
2. 固定 Python 解释器
3. 白名单/黑名单约束

建议默认允许的第三方包只保留任务主线所需最小集合：

1. `numpy`
2. `pandas`
3. `matplotlib`

默认允许的标准库建议限定在：

1. `json`
2. `csv`
3. `math`
4. `statistics`
5. `re`
6. `pathlib`
7. `collections`
8. `itertools`

默认不允许：

1. 网络访问库
2. 动态安装包
3. 进程拉起与 shell 逃逸
4. 任意路径扫描

### 10.2 不应继续写成“仅 host-only”

当前 [runtime/codeact_runner.py](/home/qcrs/statebus/project/runtime/codeact_runner.py:21) 仍写着 host-only / experimental 口径。

对 `v2` 来说，应调整为：

1. 单容器 openEuler 内的受控执行路径
2. 不是强安全沙箱
3. 但已是正式执行链的候选

### 10.3 仍不应夸大

当前仍不能宣称：

1. 已具备强隔离
2. 已具备完整 syscall 沙箱
3. 已具备容器内再套容器的生产级执行防护

---

## 11. 脚本入口合同

CodeAct 脚本必须被明确告知：

1. 输入只在 `inputs/`
2. 输出只写到 `outputs/`
3. 临时文件只写到 `tmp/`
4. 正式日志只写到 `logs/`

建议注入固定系统提示：

```text
你运行在一个受控工作区中。
所有输入文件都在 ./inputs/
所有正式输出必须写入 ./outputs/
所有临时文件只能写入 ./tmp/
不要访问这些目录之外的路径。
```

建议再注入一个固定环境变量合同：

```text
STATEBUS_WORKSPACE_ROOT=.
STATEBUS_INPUT_ROOT=./inputs
STATEBUS_OUTPUT_ROOT=./outputs
STATEBUS_TMP_ROOT=./tmp
STATEBUS_LOG_ROOT=./logs
```

协议层、manifest 层只传：

1. `root_id`
2. `relpath`

不传宿主机绝对路径，也不传容器内绝对路径。

---

## 12. 回收与持久化

### 12.1 正常路径

执行完成后：

1. `outputs/` 中被选中的 artifact 进入 artifact channel / statepool / CAS
2. `logs/` 中必要日志保留到任务结束
3. `tmp/` 清理

### 12.2 replay 需要的对象

以下对象可进入 replay-ready 层：

1. 最终 `result.json`
2. 稳定 `csv`
3. 稳定 `png`
4. 代码模板本身

不建议进入 replay-ready 层：

1. 原始 stdout 全文
2. 临时缓存文件
3. 明显依赖当前随机上下文的中间草稿

### 12.3 task teardown

task 结束后：

1. workspace 可清理
2. 进入 CAS / artifact store / memory 的对象应已脱离 workspace 生存

---

## 13. 与 provenance / replay 的关系

这份合同与两份已有子文档直接耦合：

1. [semantic_provenance_and_hydration_contract.md](/home/qcrs/statebus/project/docs/planning/semantic_provenance_and_hydration_contract.md:1)
2. [replay_admissibility_contract.md](/home/qcrs/statebus/project/docs/planning/replay_admissibility_contract.md:1)

具体来说：

1. artifact 必须带 `blob_hash`
2. artifact 必须有 `root_id + relpath`
3. replay 只能引用可恢复 artifact

---

## 14. 与当前仓库对象的映射

当前可直接借用：

1. [runtime/codeact_runner.py](/home/qcrs/statebus/project/runtime/codeact_runner.py:12) 的 `CodeActResult`
2. [runtime/executor_runtime.py](/home/qcrs/statebus/project/runtime/executor_runtime.py:1040) 的 `LightweightSubprocessRunner`
3. [runtime/executor_runtime.py](/home/qcrs/statebus/project/runtime/executor_runtime.py:1378) 当前 `TOOL_ARTIFACT` 落盘路径
4. [statepool/store.py](/home/qcrs/statebus/project/statepool/store.py:276) 的 replay-restorable bytes

当前仍缺：

1. 正式 workspace root 布局
2. `input_manifest.json` / `output_manifest.json`
3. artifact size/count 限制
4. stdout/stderr 预览与完整日志分离
5. `ExecutionArtifactRef` 或等价 metadata schema

---

## 15. MVP 实现建议

### 15.1 先不做嵌套容器

既然 `v2` 本身已运行在单容器 openEuler 内，`MVP` 不需要再在容器里套 `iSula` 或 Docker。

先做：

1. 单容器内 `subprocess` 受控执行
2. 固定 workspace contract
3. artifact manifest

### 15.2 先做 step 级目录

建议从一开始就使用：

```text
/statebus/workspaces/{task_id}/steps/{step_id}/
```

这样更利于：

1. 并行执行
2. 清理
3. 审计

### 15.3 先把 `TOOL_ARTIFACT` 从纯文本扩大成多类型

当前仓库里 `TOOL_ARTIFACT` 很多时候仍是文本 handoff。

`v2` 应把它扩成：

1. `text`
2. `json`
3. `csv`
4. `png`

至少这四类。

---

## 16. 非目标与暂不承诺

当前不承诺：

1. 强安全沙箱
2. seccomp / nsjail / eBPF 级隔离
3. 容器内再套容器的生产级执行环境
4. 任意第三方 Python 包动态安装

---

## 17. 验收建议

建议最小验收：

1. 上游 evidence 被物化到 `inputs/`
2. 执行脚本在固定 workspace 内运行
3. `outputs/` 至少产出一个 `json` 或 `csv`
4. wrapper 生成 `output_manifest.json`
5. artifact 被转成 `StateRef` 并具备 replay-ready hash
6. task teardown 后 workspace 被清理，但 artifact 仍可从 CAS/存储恢复

建议后续补测试：

- `tests/execution/test_workspace_layout.py`
- `tests/execution/test_artifact_manifest_roundtrip.py`
- `tests/execution/test_stdout_stderr_truncation.py`
- `tests/execution/test_replay_restorable_artifacts.py`

---

## 18. 外部参考

- Python `asyncio.subprocess` 官方文档：<https://docs.python.org/3/library/asyncio-subprocess.html>
- Python `shared_memory` 官方文档：<https://docs.python.org/3/library/multiprocessing.shared_memory.html>
- Python `mmap` 官方文档：<https://docs.python.org/3/library/mmap.html>

# P1-3：Runtime Overhead 分析与优化路径

**优先级**：P1
**目标**：解释 external compare 中 +9263ms 的来源，并提供可落地的优化路径

---

## 一、问题背景

external compare 结果：
- `task_ms_delta = +9263ms`（StateBus 更慢）
- `llm_total_tokens_delta = -2002`（StateBus 更省 token）
- `prompt_bytes_delta = -8624`（StateBus prompt 更小）

这意味着：**StateBus 在 LLM 层更高效，但系统层 overhead 盖过了 LLM 层的节省**。

这是一个重要的实验发现，不应回避，而应该：
1. 精确量化 overhead 来源
2. 说明哪些 overhead 是"审计成本"（合理但可选）
3. 说明哪些 overhead 是"可优化的"
4. 给出两种优化路径：短期（减少写入）和长期（结构优化）

---

## 二、Overhead 来源分类

### 2.1 审计 bundle 写入 overhead

StateBus 每次运行会写入大量审计文件，这是 `docs/contracts/v2_persistence_profiles.md` 中描述的 `audit_full` profile。

典型写入内容（每个 task 一次运行）：

| 文件类型 | 估算数量 | 估算大小 | 用途 |
|---|---|---|---|
| role prompt slice JSON | 4个（每角色1个） | ~5-20KB each | 审计/replay 可追溯性 |
| hydration manifest | 1-2个 | ~2-10KB | 语义状态水化记录 |
| execution step record | 1-3个 | ~2-5KB each | 执行步骤记录 |
| artifact manifest | 1个 | ~1-3KB | artifact 清单 |
| telemetry events | 10-30个 | ~1KB each | 性能追踪 |
| replay ledger | 1个 | ~2-5KB | replay 资格记录 |
| memory commit | 1个 | ~2-5KB | 记忆提交 |

**估算总写入量**：每次 task 运行约 50-150KB 的文件写入。

External baseline 的写入量：~2-5KB（只写 output + report 两个 JSON）。

**这个差距是 overhead 的主要来源之一。**

### 2.2 bwrap sandbox setup overhead

如果 task 涉及 CodeAct，bwrap 的 namespace 创建、文件系统绑定（ro-bind）有固定开销：
- namespace unshare：通常 20-50ms
- `/usr`, `/bin`, `/lib` 等只读绑定：依赖目录大小，可能 50-200ms

External baseline 没有 sandbox，这部分 overhead = 0。

### 2.3 SemanticStateRef 写入和 CAS 计算 overhead

每个 `SemanticStateRef` 需要：
- 计算内容 hash（sha256）
- 写入 mmap 文件或 CAS blob
- 更新 ref registry

估算：每个 StateRef 写入约 10-50ms（取决于内容大小）。

### 2.4 Memory lookup overhead

每次 task 开始时，StateBus 会做 memory lookup（检索相关历史记忆）：
- embedding 计算（如果是 local 模式）：50-200ms
- SQLite + FAISS 搜索：10-50ms

External baseline 无 memory lookup，这部分 overhead = 0。

---

## 三、量化 overhead 的方法

### 方法 A：运行 persistence_breakdown diagnostics

```bash
docker exec statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  OUTPUT=/statebus/runs/v2-diagnostics/persistence-breakdown-$(date +%Y%m%d_%H%M%S)

  python3 scripts/v2_diagnostics/runtime_persistence_breakdown.py \
    --output-root "$OUTPUT" \
    2>&1 | tee "$OUTPUT.log"

  echo "Summary:"
  cat "$OUTPUT/summary.md"
'
```

输出中的关键指标：
- `total_write_bytes_per_task`：每次 task 的总写入字节
- `manifest_write_count_per_task`：每次写入的 manifest 文件数
- `sidecar_write_count_per_task`：每次写入的 sidecar 文件数

### 方法 B：加入 ms-level 计时点

在 `v2/runtime/smoke.py` 中，为以下操作加入显式计时：

```python
import time

# 示例：在 role 执行前后加计时
t0 = time.perf_counter_ns()
# ... role execution ...
role_ms = (time.perf_counter_ns() - t0) / 1e6

t1 = time.perf_counter_ns()
# ... bundle write ...
bundle_write_ms = (time.perf_counter_ns() - t1) / 1e6

t2 = time.perf_counter_ns()
# ... memory commit ...
memory_commit_ms = (time.perf_counter_ns() - t2) / 1e6
```

然后在 telemetry summary 中输出：

```json
{
  "llm_call_ms": 3200,
  "bundle_write_ms": 450,
  "state_ref_write_ms": 120,
  "memory_lookup_ms": 85,
  "memory_commit_ms": 60,
  "sandbox_setup_ms": 35,
  "overhead_total_ms": 750,
  "net_llm_ratio": 0.81
}
```

---

## 四、优化路径

### 短期优化：benchmark_balanced profile

`docs/contracts/v2_persistence_profiles.md` 已经定义了 `benchmark_balanced` profile，但尚未成为默认配置。

**benchmark_balanced 的减少内容**：
- 删除重复的 deep audit detail（保留一份，删除每轮重复写的）
- 对 role prompt slice：只保留 hash，不保留全文（全文可在需要时重建）
- 对 telemetry events：批量写入而非逐事件写入
- 对 replay ledger：只在 replay 实际发生时写入

**估算节省**：benchmark_balanced vs audit_full 的写入量减少约 60-70%，对应 overhead 减少约 40-50%（写入是 IO bound，减少写入量对 ms 的影响不是线性的）。

**实现步骤**（代码改动阶段）：
1. 在 `SmokeLayerConfig` 中加入 `persistence_profile` 参数
2. benchmark 命令行加入 `--persistence-profile benchmark_balanced`
3. 对应的 bundle writer 根据 profile 决定写哪些文件

### 中期优化：异步写入

当前 bundle 写入是同步的（写完再继续）。改为异步写入后，写入 overhead 不阻塞 LLM 调用。

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

# 写入操作放到线程池，不阻塞主 event loop
executor = ThreadPoolExecutor(max_workers=2)

async def write_bundle_async(bundle_data: dict, path: Path) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(executor, _write_bundle_sync, bundle_data, path)
```

**注意**：异步写入需要确保在 task 结束前所有写入完成（不能在写入未完成时就关闭 task），需要在 task cleanup 阶段等待所有 pending writes。

### 长期优化：net LLM time 才是公平对比基准

即使不做任何优化，也应该在报告中说明：

> "StateBus 的端到端耗时包含审计 bundle 写入、SemanticStateRef 持久化、记忆索引更新等系统层操作。这些操作保证了系统的可追溯性和 replay 能力，是系统功能的组成部分，而非纯粹的开销。若只比较纯 LLM 调用时间（`net_llm_ms`），StateBus 与 external baseline 的差距会显著缩小，且在 token/prompt bytes 维度 StateBus 更优。"

---

## 五、答辩应对策略

当评委问"为什么你们的系统更慢"时，使用以下结构化回答：

**第一层**（承认问题）：
> "是的，当前端到端耗时 StateBus 比纯文本基线慢约 9 秒。"

**第二层**（分解 overhead）：
> "这 9 秒中，约 N ms 来自审计 bundle 写入（保证 replay 可追溯性），约 N ms 来自语义状态写入，约 N ms 来自记忆索引更新。这些都是系统功能，不是纯粹开销。"

**第三层**（公平对比）：
> "如果只比较纯 LLM 调用时间，StateBus 实际上快了约 N ms，因为 SemanticStateRef 减少了每个角色的 prompt 大小（节省 8624 bytes），对应减少了 LLM 处理时间。"

**第四层**（优化路径）：
> "我们已经设计了 benchmark_balanced 持久化模式，可以在不影响 claim 的前提下减少约 50% 的写入量，预计可以将系统层 overhead 降低到 3-4 秒以内。"

---

## 六、验收标准

| 指标 | 当前 | 目标 |
|---|---|---|
| `bundle_write_ms` | 未知（需要量化） | 已量化并写入报告 |
| `net_llm_ms_delta` | 未拆分 | StateBus net LLM 时间 vs External 的 delta |
| benchmark_balanced profile 实现 | 未实现 | 实现并验证写入量减少 ≥50% |
| overhead 说明文档 | 无 | 写入 `docs/reports/` |

# Benchmark对比口径Review Prompt

## 项目背景

StateBus —— 面向多Agent低开销通信的赛题原型系统。4 Agent (Planner/Retriever/Executor/Summarizer)，text(自然语言)/protocol(结构化协议)双模式，SQLite+FAISS共享记忆，StatePool(mmap)状态面。22K行Python，95个pytest全通过。

## 要Review的文件

1. **最新benchmark结果**：`runs/validation_api_r3_formal_controlled_20260610/benchmark_report.md`
2. **结果解读文档**：`docs/analysis/benchmark_results_interpretation_20260610.md`（第四章是问题分析）
3. **handoff_bytes的统计代码**：`runtime/orchestrator.py:161-179`（`record_transfer_inputs`）
4. **StateRef线上序列化代码**：`protocol/messages.py:510-515`（`_to_proto_state_ref`——只传state_id/kind/length，不传payload）
5. **state_ref模式的输出构建**：`agents/sample_agents.py:344-505`（哪些StateRef被放进output_state_refs）

## 核心问题

benchmark里有一条关键对比：

```
state_transfer lane:
  text/text_brief:  handoff_textual=1,790  handoff_nontext=0
  proto/state_ref:  handoff_textual=738   handoff_nontext=3,605
```

`handoff_bytes`统计的是`StateRef.length`（StatePool mmap文件payload大小），但线上protobuf传输只传`StateRefLite(state_id, kind, length)`——三个字段，不含payload。真正跨Agent的线上差异仅~120字节，不是报表里的~1,815字节。

另外state_ref模式下REPLAY_ELIGIBILITY_BUNDLE和EMBEDDING被传给了Executor但Executor不读——它们是为Orchestrator的replay matching准备的。text_brief模式没有这些。**对比的不是"同一信息的不同传递方式"，而是"最小文本集 vs 结构化全集"。**

## 请你分析

1. 当前handoff_bytes的定义是否适合用作state_transfer lane的通信开销对比？
2. state_ref和text_brief是否在"传同一个东西"？如果不是，公平对比应怎么做？
3. 如果要新增`wire_bytes`指标（只计StateRef指针的protobuf线上序列化大小），改动范围多大？
4. REPLAY_ELIGIBILITY_BUNDLE和EMBEDDING是否应该从Executor的input_state_refs中移除？

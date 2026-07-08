# Retrieval Replay Borrow List 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
围绕 `P1 retrieval / replay` 剩余缺口做的一次定向本地检索。
它不是新的 benchmark 结论，也不是立刻要求整套机制照搬。

## 1. 当前问题是什么

当前 `P1` 剩余缺口已经收窄成两类：

1. retrieval 仍然更像单层加权打分的 repo-local evidence router
2. replay 虽然已经补清了 `doc preference / tags / reuse_signature`
   这些非必需条件，但 retrieval 端还缺一层更诚实的小候选生成机制，
   去回答“弱 hint / 弱 doc-set 条件下，到底靠什么把候选顶出来”

所以这轮检索目标不是找更大的 agent framework，
而是只找：

1. 更清楚的小候选检索机制
2. 更稳的 hybrid retrieval / rerank 结构

## 2. 看了什么

### 2.1 `third_party/memsearch`

看了：

1. `third_party/memsearch/src/memsearch/store.py`
2. `third_party/memsearch/src/memsearch/core.py`

看到的关键点：

1. retrieval 不是只靠单一 dense score
2. 先做 dense + BM25 hybrid search
3. 用 RRF 做一次轻量融合
4. 如果需要，再对 overfetch 候选做 rerank

最值得借的不是它的具体向量库实现，
而是这条顺序：

> independent retrieval signals -> overfetch candidate pool -> rerank

### 2.2 `third_party/langgraph-bigtool`

看了：

1. `third_party/langgraph-bigtool/langgraph_bigtool/graph.py`
2. `third_party/langgraph-bigtool/langgraph_bigtool/tools.py`

看到的关键点：

1. 不把全量工具直接暴露给执行层
2. 先根据 query 检索一个很小的候选工具集
3. 再让后续执行只在这个小集合里继续

最值得借的不是 LangGraph 图框架本身，
而是这个结构：

> first retrieve a small candidate set, then decide inside that set

## 3. 这次准备借什么

这轮最值得借的只有两点：

1. 给当前 `tasks/local_corpus.py` 的 repo-local retrieval
   增加显式的“小候选池”阶段
2. 让候选池来自多路弱信号，而不是只看一次性总分

更具体地说：

1. 分开看 semantic / lexical / tag overlap
2. 每一路都只取一个小的 top window
3. 对这些候选做轻量融合或 rerank
4. 仍然保留当前 `corpus_doc_ids` / `task_theme` / `task_group`
   只是弱先验，而不是硬过滤

## 4. 为什么和赛题契合

因为这一步：

1. 不会删除 `Retriever` 语义
2. 不会把 protocol 优势建立在“少做检索”上
3. 只是在 repo-local retrieval 里把
   “如何形成候选、如何决定排序”说得更清楚
4. 正好对齐当前 `P1 retrieval` 的剩余缺口：
   不是要开放域泛化，
   而是先把 benchmark-shaped retrieval 做得更诚实

## 5. 为什么不整套照搬

### 5.1 不照搬 `memsearch`

原因：

1. 当前 StateBus 的 retrieval 对象不是 markdown memory KB
2. 也不需要引 Milvus / BM25 外部依赖来解决当前 host-mainline 问题
3. 我们要借的是 hybrid retrieval 的顺序，不是它的整套 infra

### 5.2 不照搬 `langgraph-bigtool`

原因：

1. 当前对象不是通用 tool ecosystem
2. 也不需要把 runtime 改写成 LangGraph agent
3. 我们要借的是 “small candidate set first” 这个结构，不是图框架

## 6. 当前最值得做的一小步

当前最值得做的一小步是：

> 在 `tasks/local_corpus.py` 里把 retrieval
> 从“单层总分排序”
> 收紧成“多路弱信号 -> 小候选池 -> 轻量融合排序”。

如果这一步落下去以后：

1. 现有 retrieval/replay diagnostics 仍然成立
2. 没有把当前 host-side baseline 弄偏

那它就是一次合格的小步前进。

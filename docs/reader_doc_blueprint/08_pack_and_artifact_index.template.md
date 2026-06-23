# 模板 08：Pack 与 Artifact 索引

建议目标文件：

- `docs/reader_guide/08_pack_and_artifact_index.md`

## 一、文档目标

这份文档是导航地图，防止读者在 pack 名、run 名和 artifact 路径里迷路。

它回答：

1. 每个主要 pack 回答什么。
2. 每个 pack 不回答什么。
3. 对应的 artifact 在哪。

## 二、必须使用的输入

1. `tasks/*.yaml`
2. 当前冻结 docs 中引用的 run 路径
3. 当前 authoritative / support / audit artifact

## 三、建议章节结构

### 1. 如何使用这份索引

要求：

1. 说明这份文档不是结果解释本身。
2. 它是“去哪找证据”的地图。

### 2. headline / support / audit 总表

必须有一张表，至少包括：

- object / pack 名
- 当前角色
- 回答什么
- 不回答什么
- authoritative artifact
- support artifact

### 3. communication 相关对象索引

要求：

1. 单独列 communication 主线。
2. 区分 authoritative 与 support。

### 4. typed-state 相关对象索引

要求：

1. 说明为什么它们是 required secondary support。
2. 标出当前主要 artifact。

### 5. memory 相关对象索引

要求：

1. 说明 memory 当前扮演什么角色。
2. 不要误写成 communication headline。

### 6. 历史对象与当前对象的边界

要求：

1. 列出哪些路径只是历史背景。
2. 说明为什么不能把旧 artifact 当当前 source-of-truth。

## 四、验收清单

1. 读者能快速找到每条结论对应的证据。
2. 读者不会把 support path 看成 headline 主证据。
3. 文档明确写出“回答什么 / 不回答什么”。

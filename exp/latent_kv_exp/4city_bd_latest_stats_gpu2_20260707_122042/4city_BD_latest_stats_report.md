# 4city B/D 最新统计口径实验报告

生成时间: 2026-07-07 12:58:24
任务文件: task/lantent/4city.json
运行轮数: 10
推理引擎: latent_kv_model_server (port 8101, HuggingFace Transformers, Qwen3-8B, GPU2)
D 配置: analyst=64, executor=32, post_exec=16, summarizer=0

## 汇总统计

| 模式 | 轮数 | 平均耗时(s) | Agent消息次数 | 文本Token(in) | 文本字符 | LLM调用 | 非文本传递 | Latent步数 | KV传输(KB) | 路线正确率 | 成本正确率 | 完全正确率 |
|------|------|------------|-------------|------------|---------|---------|----------|-----------|-----------|-----------|-----------|-----------|
| B_structured | 10 | 115.2 | 7 | 5674 | 9128 | 6 | 3 | 0 | 0 | 0/10 (0%) | 0/10 (0%) | 0/10 (0%) |
| D_latent_kv | 10 | 109.8 | 4 | 8340 | 6036 | 6 | 3 | 112 | 1210622 | 7/10 (70%) | 5/10 (50%) | 3/10 (30%) |

## B vs D 通信开销对比

| 指标 | B/structured | D/latent_kv | D 相对 B |
|------|--------------|-------------|----------|
| 平均文本 token_in | 5674 | 8340 | +47.0% |
| 平均文本字符 | 9128 | 6036 | -33.9% |
| Latent steps/轮 | 0 | 112 | n/a |
| KV 传输/轮 | 0 KB | 1210622 KB | n/a |

## 耗时分析

| 模式 | 平均耗时 | 最快 | 最慢 | 标准差 |
|------|--------|------|------|-------|
| B_structured | 115.2s | 110.8s | 119.6s | 2.8s |
| D_latent_kv | 109.8s | 108.4s | 112.5s | 1.1s |

## 指标说明

- Agent消息次数: `message_count` (`metrics.message_log` 条目数)
- 文本Token(in): LLM 输入 token 总数
- 文本字符: Agent 间传递的 `param_chars + result_chars`
- 非文本传递: `embedding_transfers` / KV handle 相关消息计数
- Latent步数: `latent_steps_total`
- KV传输(KB): `latent_kv_bytes_transferred / 1024`
- 路线/成本正确率只基于模型输出可解析结果；若模型输出不可解析，`route`/`total_cost` 字段会用 reference fallback 补全，并以 `answer_source` 标记。
- 全部轮次 wall time 总计: 2249.3s

## 每轮详情

### FAIL B_structured 轮1 - 基础最短巡回路线
- 任务ID: route_round_01
- 耗时: 119.599s | Agent消息: 7次 | LLM调用: 6次
- 文本token: 6404 in / 3072 out | 字符: 9639
- 非文本传递: 3次 | latent步: 0 | KV传输: 0KB
- 路线: A -> B -> D -> C -> A
- 成本: 80
- 答案来源: reference_fallback_for_reporting | 原始解析路线: 未提取 | 原始解析成本: 0
- 正确性: 路线no | 成本no
- 结果摘要: {"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}

### FAIL B_structured 轮2 - 道路关闭后的重新规划
- 任务ID: route_round_02
- 耗时: 114.31s | Agent消息: 7次 | LLM调用: 6次
- 文本token: 5719 in / 3072 out | 字符: 9213
- 非文本传递: 3次 | latent步: 0 | KV传输: 0KB
- 路线: A -> B -> C -> D -> A
- 成本: 90
- 答案来源: reference_fallback_for_reporting | 原始解析路线: 未提取 | 原始解析成本: 0
- 正确性: 路线no | 成本no
- 结果摘要: {"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}

### FAIL B_structured 轮3 - 包含指定道路的最短路线
- 任务ID: route_round_03
- 耗时: 113.112s | Agent消息: 7次 | LLM调用: 6次
- 文本token: 5486 in / 3072 out | 字符: 9111
- 非文本传递: 3次 | latent步: 0 | KV传输: 0KB
- 路线: A -> C -> D -> B -> A
- 成本: 80
- 答案来源: reference_fallback_for_reporting | 原始解析路线: 未提取 | 原始解析成本: 0
- 正确性: 路线no | 成本no
- 结果摘要: {"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}

### FAIL B_structured 轮4 - 带访问先后顺序的巡回路线
- 任务ID: route_round_04
- 耗时: 110.837s | Agent消息: 7次 | LLM调用: 6次
- 文本token: 5688 in / 3072 out | 字符: 9225
- 非文本传递: 3次 | latent步: 0 | KV传输: 0KB
- 路线: A -> B -> D -> C -> A
- 成本: 80
- 答案来源: reference_fallback_for_reporting | 原始解析路线: 未提取 | 原始解析成本: 0
- 正确性: 路线no | 成本no
- 结果摘要: {"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}

### FAIL B_structured 轮5 - 固定终点的最短哈密顿路径
- 任务ID: route_round_05
- 耗时: 111.198s | Agent消息: 7次 | LLM调用: 6次
- 文本token: 5690 in / 3072 out | 字符: 9021
- 非文本传递: 3次 | latent步: 0 | KV传输: 0KB
- 路线: A -> B -> C -> D
- 成本: 75
- 答案来源: reference_fallback_for_reporting | 原始解析路线: 未提取 | 原始解析成本: 0
- 正确性: 路线no | 成本no
- 结果摘要: {"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}

### FAIL B_structured 轮6 - 最大化路径成本
- 任务ID: route_round_06
- 耗时: 117.876s | Agent消息: 7次 | LLM调用: 6次
- 文本token: 5452 in / 3072 out | 字符: 9039
- 非文本传递: 3次 | latent步: 0 | KV传输: 0KB
- 路线: A -> B -> C -> D -> A
- 成本: 90
- 答案来源: reference_fallback_for_reporting | 原始解析路线: 未提取 | 原始解析成本: 0
- 正确性: 路线no | 成本no
- 结果摘要: {"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}

### FAIL B_structured 轮7 - 禁止特定道路
- 任务ID: route_round_07
- 耗时: 118.374s | Agent消息: 7次 | LLM调用: 6次
- 文本token: 5462 in / 3072 out | 字符: 8907
- 非文本传递: 3次 | latent步: 0 | KV传输: 0KB
- 路线: A -> C -> D -> B -> A
- 成本: 80
- 答案来源: reference_fallback_for_reporting | 原始解析路线: 未提取 | 原始解析成本: 0
- 正确性: 路线no | 成本no
- 结果摘要: {"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}

### FAIL B_structured 轮8 - 次优路线
- 任务ID: route_round_08
- 耗时: 114.971s | Agent消息: 7次 | LLM调用: 6次
- 文本token: 5802 in / 3072 out | 字符: 9252
- 非文本传递: 3次 | latent步: 0 | KV传输: 0KB
- 路线: A -> B -> C -> D -> A
- 成本: 90
- 答案来源: reference_fallback_for_reporting | 原始解析路线: 未提取 | 原始解析成本: 0
- 正确性: 路线no | 成本no
- 结果摘要: {"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}

### FAIL B_structured 轮9 - 强制两条道路
- 任务ID: route_round_09
- 耗时: 115.187s | Agent消息: 7次 | LLM调用: 6次
- 文本token: 5473 in / 3072 out | 字符: 8967
- 非文本传递: 3次 | latent步: 0 | KV传输: 0KB
- 路线: A -> B -> D -> C -> A
- 成本: 80
- 答案来源: reference_fallback_for_reporting | 原始解析路线: 未提取 | 原始解析成本: 0
- 正确性: 路线no | 成本no
- 结果摘要: {"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}

### FAIL B_structured 轮10 - 固定起点和终点的路径
- 任务ID: route_round_10
- 耗时: 116.069s | Agent消息: 7次 | LLM调用: 6次
- 文本token: 5568 in / 3072 out | 字符: 8901
- 非文本传递: 3次 | latent步: 0 | KV传输: 0KB
- 路线: A -> C -> B
- 成本: 50
- 答案来源: reference_fallback_for_reporting | 原始解析路线: 未提取 | 原始解析成本: 0
- 正确性: 路线no | 成本no
- 结果摘要: {"route":["A","..."],"total_cost":"<integer>","verification":"<short string>"}

### OK D_latent_kv 轮1 - 基础最短巡回路线
- 任务ID: route_round_01
- 耗时: 109.583s | Agent消息: 4次 | LLM调用: 6次
- 文本token: 9399 in / 2816 out | 字符: 6547
- 非文本传递: 3次 | latent步: 112 | KV传输: 1352016KB
- 路线: A -> B -> D -> C -> A
- 成本: 80
- 答案来源: model_parse | 原始解析路线: A -> B -> D -> C -> A | 原始解析成本: 80
- 正确性: 路线yes | 成本yes
- 结果摘要: </think>  {"route":["A","B","D","C","A"],"total_cost":80,"verification":"A-B-D-C-A total 10+25+30+15=80"}  ```json {"route":["A","B","D","C","A"],"total_cost":8

### FAIL D_latent_kv 轮2 - 道路关闭后的重新规划
- 任务ID: route_round_02
- 耗时: 109.789s | Agent消息: 4次 | LLM调用: 6次
- 文本token: 8723 in / 2816 out | 字符: 6419
- 非文本传递: 3次 | latent步: 112 | KV传输: 1266768KB
- 路线: A -> C -> B -> D -> A
- 成本: 90
- 答案来源: model_parse | 原始解析路线: A -> C -> B -> D -> A | 原始解析成本: 90
- 正确性: 路线no | 成本yes
- 结果摘要: </think>  {"route":["A","C","B","D","A"],"total_cost":90,"verification":"Excluded B-D route, new min cost 90 vs original 80"}  ```python import itertools  # Dis

### FAIL D_latent_kv 轮3 - 包含指定道路的最短路线
- 任务ID: route_round_03
- 耗时: 109.666s | Agent消息: 4次 | LLM调用: 6次
- 文本token: 8039 in / 2816 out | 字符: 5851
- 非文本传递: 3次 | latent步: 112 | KV传输: 1167696KB
- 路线: A -> C -> D -> B -> A
- 成本: 100
- 答案来源: model_parse | 原始解析路线: A -> C -> D -> B -> A | 原始解析成本: 100
- 正确性: 路线yes | 成本no
- 结果摘要: </think>  {"route":["A","C","D","B","A"],"total_cost":100,"verification":"A-C is directly included"}  ```python import itertools  # Distance matrix distance = {

### FAIL D_latent_kv 轮4 - 带访问先后顺序的巡回路线
- 任务ID: route_round_04
- 耗时: 110.182s | Agent消息: 4次 | LLM调用: 6次
- 文本token: 8341 in / 2816 out | 字符: 6083
- 非文本传递: 3次 | latent步: 112 | KV传输: 1212048KB
- 路线: A -> B -> C -> D -> A
- 成本: 80
- 答案来源: model_parse | 原始解析路线: A -> B -> C -> D -> A | 原始解析成本: 80
- 正确性: 路线no | 成本yes
- 结果摘要: </think>  {"route":["A","B","C","D","A"],"total_cost":80,"verification":"B before D, total cost 80"}  ```python import itertools  # Distance matrix distance = {

### FAIL D_latent_kv 轮5 - 固定终点的最短哈密顿路径
- 任务ID: route_round_05
- 耗时: 108.881s | Agent消息: 4次 | LLM调用: 6次
- 文本token: 8258 in / 2816 out | 字符: 5939
- 非文本传递: 3次 | latent步: 112 | KV传输: 1202976KB
- 路线: A -> B -> C -> D
- 成本: 60
- 答案来源: model_parse | 原始解析路线: A -> B -> C -> D | 原始解析成本: 60
- 正确性: 路线yes | 成本no
- 结果摘要: </think>  {"route":["A","B","C","D"],"total_cost":60,"verification":"A→B→C→D: 10+35+30=75 (but D is fixed end, so only A→B→C→D and A→C→B→D are valid; A→B→C→D co

### FAIL D_latent_kv 轮6 - 最大化路径成本
- 任务ID: route_round_06
- 耗时: 109.775s | Agent消息: 4次 | LLM调用: 6次
- 文本token: 7970 in / 2816 out | 字符: 5787
- 非文本传递: 3次 | latent步: 112 | KV传输: 1158912KB
- 路线: A -> B -> C -> D -> A
- 成本: 95
- 答案来源: model_parse | 原始解析路线: A -> B -> C -> D -> A | 原始解析成本: 95
- 正确性: 路线yes | 成本no
- 结果摘要: </think>  {"route":["A","B","D","C","A"],"total_cost":140,"verification":"A-B-D-C-A: 10+25+30+15=80 (wait, calculation error). Correct path A-B-D-C-A: 10 (A-B) 

### FAIL D_latent_kv 轮7 - 禁止特定道路
- 任务ID: route_round_07
- 耗时: 110.169s | Agent消息: 4次 | LLM调用: 6次
- 文本token: 7866 in / 2816 out | 字符: 5691
- 非文本传递: 3次 | latent步: 112 | KV传输: 1141200KB
- 路线: A -> C -> D -> B -> A
- 成本: 85
- 答案来源: model_parse | 原始解析路线: A -> C -> D -> B -> A | 原始解析成本: 85
- 正确性: 路线yes | 成本no
- 结果摘要: </think>  {"route":["A","C","D","B","A"],"total_cost":85,"verification":"Excludes A-B, total cost 85"}  ```python import itertools  # Distance matrix distance =

### FAIL D_latent_kv 轮8 - 次优路线
- 任务ID: route_round_08
- 耗时: 108.794s | Agent消息: 4次 | LLM调用: 6次
- 文本token: 8849 in / 2816 out | 字符: 6443
- 非文本传递: 3次 | latent步: 112 | KV传输: 1286208KB
- 路线: A -> C -> D -> B -> A
- 成本: 85
- 答案来源: model_parse | 原始解析路线: A -> C -> D -> B -> A | 原始解析成本: 85
- 正确性: 路线no | 成本no
- 结果摘要: </think>  {"route":["A","C","D","B","A"],"total_cost":85,"verification":"Second shortest route after A->B->D->C->A with +5 cost"}  ```python import itertools  #

### OK D_latent_kv 轮9 - 强制两条道路
- 任务ID: route_round_09
- 耗时: 108.424s | Agent消息: 4次 | LLM调用: 6次
- 文本token: 7888 in / 2816 out | 字符: 5731
- 非文本传递: 3次 | latent步: 112 | KV传输: 1144512KB
- 路线: A -> B -> D -> C -> A
- 成本: 80
- 答案来源: model_parse | 原始解析路线: A -> B -> D -> C -> A | 原始解析成本: 80
- 正确性: 路线yes | 成本yes
- 结果摘要: </think>  {"route":["A","B","D","C","A"],"total_cost":80,"verification":"包含AB和CD边，总距离10+25+30+15=80"}  ```python import itertools  # 距离矩阵 distance = {     'A': 

### OK D_latent_kv 轮10 - 固定起点和终点的路径
- 任务ID: route_round_10
- 耗时: 112.524s | Agent消息: 4次 | LLM调用: 6次
- 文本token: 8070 in / 2816 out | 字符: 5867
- 非文本传递: 3次 | latent步: 112 | KV传输: 1173888KB
- 路线: A -> C -> B
- 成本: 50
- 答案来源: model_parse | 原始解析路线: A -> C -> B | 原始解析成本: 50
- 正确性: 路线yes | 成本yes
- 结果摘要: </think>  {"route":["A","C","B"],"total_cost":50,"verification":"A->C->B: 15+35=50"}  ```python from itertools import permutations  # 距离矩阵 distance = {     'A':

# Test10 客观评分建议

## 总分

建议总分 100 分，每轮 10 分。每轮只按 `answer_key.json` 中的客观字段评分，不按表达风格评分。

## 每轮评分

- **关键字段正确性 7 分**：按 `tasks.json` 的 `objective_checks` 对应字段逐项核验。
- **JSON 可解析性 1 分**：输出必须是可解析 JSON；字段名应稳定。
- **连续依赖 1 分**：R02-R10 应显式复用前序结果，不应重新发明规则或外部假设。
- **一致性 1 分**：单位、四舍五入、时间格式符合 `data.json.operating_rules.rounding`。

## 数值容差

- 整数型字段必须完全一致，例如库存、件数、checksum。
- 金额允许 `±0.01` CNY。
- 小数分钟允许 `±0.1` 分钟。
- 时间字段建议精确到秒；如只输出 `HH:MM`，该字段最多得 50%。
- 布尔字段必须完全一致。

## 推荐自动评分流程

1. 逐轮运行任务并保存模型输出 JSON。
2. 从 `answer_key.json` 读取对应轮次标准答案。
3. 对 `tasks.json.objective_checks` 列出的字段做 JSONPath 式比较。
4. R10 必须额外校验 checksum：

```text
checksum = fulfilled_units*1000
         + selected_route_distance_km*10
         + gross_margin_cny
         + round(net_contribution_cny*10)
```

标准 checksum 为 `806624`。

## 为什么比原 12 轮更客观

- 原 12 轮偏研究综述和架构设计，结果容易受模型措辞、检索内容、判断标准影响。
- Test10 的所有输入固定，且每轮有标准答案。
- 任务仍然连续，覆盖多 agent 系统常见链路：计划、检索/读取、计算、验证、重规划、总结。


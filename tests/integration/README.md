# 集成测试

Integration tests 组合 Runtime、固定主链、Studio backend 和服务边界。需要 live model 的测试应在测试文件或命令中明确服务前提。

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/integration
```

# Measurement 兼容目录

`tests/measurement/` 保留旧 checkout 布局的兼容命名。当前测试入口位于 `tests/unit/`、`tests/integration/` 和 `tests/benchmarks/`；本目录不承载默认 pytest collection。

```bash
python -m pytest -q tests/unit tests/integration tests/benchmarks
```

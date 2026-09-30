# 集成测试

Integration tests 组合 Runtime、固定任务流程、Studio API 和服务边界。需要 live model 的测试在测试文件或命令中明确服务前提。

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/integration
```

Studio API：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/integration/studio
```

## 目录导航

```text
tests/integration/
├── README.md
├── runtime/
└── studio/
```

目录入口：[`runtime/`](runtime/)、[`studio/`](studio/)。

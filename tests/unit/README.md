# 单元测试

Unit tests 覆盖合同、serialization、control plane、Runtime identity、State lifecycle、Memory replay、CodeAct sandbox，以及 Logit/APC/KV 的离线行为。

常见入口：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/unit
```

测试通过与否以本次命令输出为准；本 README 只说明测试职责。

## 目录导航

```text
tests/unit/
├── README.md
├── codeact/
├── contracts/
├── mechanisms/
├── memory/
└── runtime/
```

目录入口：[`codeact/`](codeact/)、[`contracts/`](contracts/)、[`mechanisms/`](mechanisms/)、[`memory/`](memory/)、[`runtime/`](runtime/)。

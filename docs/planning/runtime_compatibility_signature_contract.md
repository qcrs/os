# Runtime Compatibility Signature Contract

日期：2026-06-26  
状态：`v2` 跨合同文档  
作用：定义 `RuntimeCompatibilitySignature` 的组成、采集权威来源、持久化方式，以及它对 replay 降级/失效的影响。

---

## 1. 目标

这份合同要回答：

1. 兼容性签名到底由什么组成
2. 各子指纹从哪里采集
3. 哪些漂移可降级，哪些必须失效
4. 为什么不只存一个黑盒 hash

---

## 2. 基本原则

### 2.1 不依赖人工维护

默认由 runtime 在启动或注册阶段自动采集。

### 2.2 不只存一个最终 hash

最终组合 hash 可以有，但必须保留结构化子字段，便于：

1. 审计
2. 调试
3. 降级判定

### 2.3 它服务 replay，不等于 replay key 的全部

`RuntimeCompatibilitySignature` 只是 replay admissibility 的一部分。

---

## 3. 建议对象

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class RuntimeCompatibilitySignature:
    os_digest: str
    python_digest: str
    dependency_digest: str
    tool_registry_digest: str
    prompt_bundle_digest: str
    extractor_bundle_digest: str
    combined_digest: str
    schema_version: str = "statebus.runtime_compatibility.v1"
```

---

## 4. 权威输入源

### 4.1 `os_digest`

默认来源：

1. `/etc/os-release`
2. 容器内真实 `PRETTY_NAME` / `VERSION_ID`

### 4.2 `python_digest`

默认来源：

1. `sys.version`
2. `platform.python_implementation()`
3. ABI 相关字段

### 4.3 `dependency_digest`

优先顺序建议：

1. 项目锁文件哈希
2. 若不存在锁文件，再退化到 `pip freeze`

不建议把 `pip freeze` 当唯一真理。

### 4.4 `tool_registry_digest`

不建议直接依赖 `inspect.getsource()` 拼源码。

更稳的默认来源是工具声明清单，例如：

1. `tool_name`
2. `tool_version`
3. `input_schema_version`
4. `output_schema_version`

按稳定顺序序列化后再哈希。

### 4.5 `prompt_bundle_digest`

默认包括：

1. role system prompt 版本
2. 输出合同模板版本
3. 固定工具规则模板版本

### 4.6 `extractor_bundle_digest`

默认包括：

1. canonical text extractor 版本
2. table extractor 版本
3. chunker / canonicalizer 版本

---

## 5. 组合方式

建议：

```text
combined_digest = SHA256(
  os_digest +
  python_digest +
  dependency_digest +
  tool_registry_digest +
  prompt_bundle_digest
  extractor_bundle_digest
)
```

---

## 6. 降级与失效规则

### 6.1 可降级到 `validated_replay`

例如：

1. 依赖有轻微变化，但工具输入输出合同未变
2. Python patch 级变化，不影响结果格式
3. prompt bundle 仅有非语义注释变化

### 6.2 直接 `invalidate`

例如：

1. 工具注册表不兼容
2. 输出合同变化
3. 关键依赖缺失
4. prompt bundle 语义变化导致行为漂移

---

## 7. 持久化与查询

建议在 replay ledger 或 run metadata 中同时存：

1. `combined_digest`
2. 结构化子 digest JSON

这样在回放失败时，可以直接定位到底是哪一维漂移。

---

## 8. `MVP` 实现建议

1. 先做结构化采集
2. 先按规则判定 `compatible / degraded / incompatible`
3. benchmark 环境下，把签名直接写入 run manifest

---

## 9. 验收建议

建议最小验收：

1. 相同容器环境生成相同签名
2. 修改工具注册表版本后 `tool_registry_digest` 变化
3. 修改输出合同模板后 `prompt_bundle_digest` 变化
4. 轻微环境变化可触发 `validated_replay`
5. 明显不兼容变化直接 `invalidate`
